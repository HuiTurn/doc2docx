"""CHPX/PAPX FKP parsing and physical-FC to logical-CP mapping."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import struct

from ..diagnostics import ConversionReport
from ..errors import InvalidWordDocument
from ..model import CharacterProperties, FontDefinition, ParagraphProperties, StyleSheet
from .pieces import PieceTable
from .sprm import (
    apply_character_modifiers,
    apply_paragraph_modifiers,
    parse_grpprl,
)


FKP_SIZE = 512


@dataclass(slots=True, frozen=True)
class CharacterFormatSpan:
    cp_start: int
    cp_end: int
    properties: CharacterProperties


@dataclass(slots=True, frozen=True)
class ParagraphFormatSpan:
    cp_start: int
    cp_end: int
    properties: ParagraphProperties


@dataclass(slots=True, frozen=True)
class FormattingMap:
    character_spans: tuple[CharacterFormatSpan, ...]
    paragraph_spans: tuple[ParagraphFormatSpan, ...]
    character_fkp_run_count: int = 0
    paragraph_fkp_run_count: int = 0

    def character_properties_at(self, cp: int) -> CharacterProperties:
        if not self.character_spans:
            return CharacterProperties()
        index = bisect_right(
            self.character_spans,
            cp,
            key=lambda span: span.cp_start,
        ) - 1
        if index >= 0:
            span = self.character_spans[index]
            if cp < span.cp_end:
                return span.properties
        return CharacterProperties()

    def paragraph_properties_at(self, cp: int) -> ParagraphProperties:
        if not self.paragraph_spans:
            return ParagraphProperties()
        index = bisect_right(
            self.paragraph_spans,
            cp,
            key=lambda span: span.cp_start,
        ) - 1
        if index >= 0:
            span = self.paragraph_spans[index]
            if cp < span.cp_end:
                return span.properties
        return ParagraphProperties()


def _read_bte_plc(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    label: str,
) -> tuple[tuple[int, int, int], ...]:
    if size == 0:
        return ()
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"{label} range [{offset}, {offset + size}) exceeds Table stream"
        )
    data = table_stream[offset : offset + size]
    if len(data) < 12 or (len(data) - 4) % 8:
        raise InvalidWordDocument(
            f"{label} size {len(data)} does not match the 8*n+4 PLC layout"
        )
    count = (len(data) - 4) // 8
    fcs = struct.unpack_from(f"<{count + 1}I", data, 0)
    for previous, current in zip(fcs, fcs[1:]):
        if current <= previous:
            raise InvalidWordDocument(f"{label} FC values are not increasing")
    page_offset = 4 * (count + 1)
    pages = struct.unpack_from(f"<{count}I", data, page_offset)
    return tuple((fcs[index], fcs[index + 1], pages[index]) for index in range(count))


def _read_fkp_page(word_document: bytes, page_number: int, *, label: str) -> bytes:
    offset = page_number * FKP_SIZE
    if offset < 0 or offset > len(word_document) - FKP_SIZE:
        raise InvalidWordDocument(
            f"{label} page {page_number} at WordDocument offset {offset} is truncated"
        )
    return word_document[offset : offset + FKP_SIZE]


def _run_boundaries(page: bytes, count: int, *, label: str) -> tuple[int, ...]:
    if count == 0:
        raise InvalidWordDocument(f"{label} contains zero runs")
    fcs = struct.unpack_from(f"<{count + 1}I", page, 0)
    for previous, current in zip(fcs, fcs[1:]):
        if current <= previous:
            raise InvalidWordDocument(f"{label} FC values are not increasing")
    return fcs


def _merge_character_spans(
    spans: list[CharacterFormatSpan],
) -> tuple[CharacterFormatSpan, ...]:
    result: list[CharacterFormatSpan] = []
    for span in sorted(spans, key=lambda item: (item.cp_start, item.cp_end)):
        if span.cp_start >= span.cp_end:
            continue
        if (
            result
            and result[-1].cp_end == span.cp_start
            and result[-1].properties == span.properties
        ):
            previous = result[-1]
            result[-1] = CharacterFormatSpan(
                previous.cp_start,
                span.cp_end,
                span.properties,
            )
        else:
            result.append(span)
    return tuple(result)


def _merge_paragraph_spans(
    spans: list[ParagraphFormatSpan],
) -> tuple[ParagraphFormatSpan, ...]:
    result: list[ParagraphFormatSpan] = []
    for span in sorted(spans, key=lambda item: (item.cp_start, item.cp_end)):
        if span.cp_start >= span.cp_end:
            continue
        if (
            result
            and result[-1].cp_end == span.cp_start
            and result[-1].properties == span.properties
        ):
            previous = result[-1]
            result[-1] = ParagraphFormatSpan(
                previous.cp_start,
                span.cp_end,
                span.properties,
            )
        else:
            result.append(span)
    return tuple(result)


def read_formatting(
    table_stream: bytes,
    word_document: bytes,
    piece_table: PieceTable,
    *,
    fc_plcf_bte_chpx: int,
    lcb_plcf_bte_chpx: int,
    fc_plcf_bte_papx: int,
    lcb_plcf_bte_papx: int,
    report: ConversionReport,
    fonts: tuple[FontDefinition, ...] = (),
    style_sheet: StyleSheet | None = None,
    data_stream: bytes | None = None,
) -> FormattingMap:
    style_sheet = style_sheet or StyleSheet()
    font_names = {font.index: font.name for font in fonts}
    character_btes = _read_bte_plc(
        table_stream,
        offset=fc_plcf_bte_chpx,
        size=lcb_plcf_bte_chpx,
        label="PlcBteChpx",
    )
    paragraph_btes = _read_bte_plc(
        table_stream,
        offset=fc_plcf_bte_papx,
        size=lcb_plcf_bte_papx,
        label="PlcBtePapx",
    )

    character_spans: list[CharacterFormatSpan] = []
    paragraph_spans: list[ParagraphFormatSpan] = []
    unsupported_character_sprms: set[int] = set()
    unsupported_paragraph_sprms: set[int] = set()
    style_relative_toggles = 0
    character_run_count = 0
    paragraph_run_count = 0

    # PAPX is parsed first because style-relative CHPX toggles depend on the
    # paragraph style active at each CP.
    for bte_fc_start, bte_fc_end, page_number in paragraph_btes:
        page = _read_fkp_page(word_document, page_number, label="PapxFkp")
        run_count = page[-1]
        header_end = 4 * (run_count + 1) + 13 * run_count
        if run_count == 0 or header_end > FKP_SIZE - 1:
            raise InvalidWordDocument(f"PapxFkp has invalid cpara {run_count}")
        fcs = _run_boundaries(page, run_count, label="PapxFkp")
        bx_offset = 4 * (run_count + 1)
        for index in range(run_count):
            run_fc_start = max(fcs[index], bte_fc_start)
            run_fc_end = min(fcs[index + 1], bte_fc_end)
            if run_fc_start >= run_fc_end:
                continue
            paragraph_run_count += 1
            papx_offset = page[bx_offset + index * 13] * 2
            properties = ParagraphProperties()
            if papx_offset:
                if papx_offset >= FKP_SIZE - 1:
                    raise InvalidWordDocument("Papx offset points outside PapxFkp")
                byte_count = page[papx_offset]
                if byte_count:
                    content_start = papx_offset + 1
                    content_length = byte_count * 2 - 1
                else:
                    if papx_offset + 1 >= FKP_SIZE - 1:
                        raise InvalidWordDocument("extended PapxInFkp is truncated")
                    content_start = papx_offset + 2
                    content_length = page[papx_offset + 1] * 2
                content_end = content_start + content_length
                if content_length < 2 or content_end > FKP_SIZE - 1:
                    raise InvalidWordDocument("PapxInFkp content exceeds PapxFkp")
                style_id = struct.unpack_from("<H", page, content_start)[0]
                modifiers = parse_grpprl(
                    page[content_start + 2 : content_end],
                    label="PapxInFkp.grpprl",
                    allow_trailing_zero_padding=True,
                )
                properties, unsupported = apply_paragraph_modifiers(
                    modifiers,
                    style_id=style_id,
                    data_stream=data_stream,
                )
                unsupported_paragraph_sprms.update(unsupported)
            for cp_start, cp_end in piece_table.fc_range_to_cp_ranges(
                run_fc_start,
                run_fc_end,
            ):
                paragraph_spans.append(
                    ParagraphFormatSpan(cp_start, cp_end, properties)
                )

    def paragraph_at(cp: int) -> ParagraphProperties:
        for span in paragraph_spans:
            if span.cp_start <= cp < span.cp_end:
                return span.properties
        return ParagraphProperties()

    # Piece Prm paragraph modifiers are applied after the PAPX grpprl.
    paragraph_boundaries = {
        boundary
        for piece in piece_table.pieces
        for boundary in (piece.cp_start, piece.cp_end)
    }
    paragraph_boundaries.update(
        boundary
        for span in paragraph_spans
        for boundary in (span.cp_start, span.cp_end)
    )
    composed_paragraph_spans: list[ParagraphFormatSpan] = []
    sorted_paragraph_boundaries = sorted(paragraph_boundaries)
    for cp_start, cp_end in zip(
        sorted_paragraph_boundaries,
        sorted_paragraph_boundaries[1:],
    ):
        if cp_start >= cp_end:
            continue
        properties = paragraph_at(cp_start)
        piece = next(
            (
                value
                for value in piece_table.pieces
                if value.cp_start <= cp_start < value.cp_end
            ),
            None,
        )
        if piece is not None:
            modifiers = piece_table.modifiers_for_piece(piece, property_group=1)
            if modifiers:
                properties, unsupported = apply_paragraph_modifiers(
                    modifiers,
                    style_id=properties.style_id,
                    initial_properties=properties,
                    data_stream=data_stream,
                )
                unsupported_paragraph_sprms.update(unsupported)
        composed_paragraph_spans.append(
            ParagraphFormatSpan(cp_start, cp_end, properties)
        )
    paragraph_spans = list(_merge_paragraph_spans(composed_paragraph_spans))

    def paragraph_at(cp: int) -> ParagraphProperties:
        for span in paragraph_spans:
            if span.cp_start <= cp < span.cp_end:
                return span.properties
        return ParagraphProperties()

    def paragraph_style_character_at(cp: int) -> CharacterProperties:
        return style_sheet.effective_character_at(paragraph_at(cp).style_id)

    paragraph_style_boundaries = {
        boundary
        for span in paragraph_spans
        for boundary in (span.cp_start, span.cp_end)
    }

    for bte_fc_start, bte_fc_end, page_number in character_btes:
        page = _read_fkp_page(word_document, page_number, label="ChpxFkp")
        run_count = page[-1]
        if run_count > 0x65:
            raise InvalidWordDocument(f"ChpxFkp has invalid crun {run_count}")
        header_end = 4 * (run_count + 1) + run_count
        if header_end > FKP_SIZE - 1:
            raise InvalidWordDocument("ChpxFkp header exceeds its 512-byte page")
        fcs = _run_boundaries(page, run_count, label="ChpxFkp")
        rgb_offset = 4 * (run_count + 1)
        for index in range(run_count):
            run_fc_start = max(fcs[index], bte_fc_start)
            run_fc_end = min(fcs[index + 1], bte_fc_end)
            if run_fc_start >= run_fc_end:
                continue
            character_run_count += 1
            chpx_offset = page[rgb_offset + index] * 2
            modifiers = ()
            if chpx_offset:
                if chpx_offset >= FKP_SIZE - 1:
                    raise InvalidWordDocument("Chpx offset points outside ChpxFkp")
                byte_count = page[chpx_offset]
                grpprl_end = chpx_offset + 1 + byte_count
                if grpprl_end > FKP_SIZE - 1:
                    raise InvalidWordDocument("Chpx grpprl exceeds ChpxFkp")
                modifiers = parse_grpprl(
                    page[chpx_offset + 1 : grpprl_end],
                    label="Chpx.grpprl",
                )
            for cp_start, cp_end in piece_table.fc_range_to_cp_ranges(
                run_fc_start,
                run_fc_end,
            ):
                boundaries = [cp_start]
                boundaries.extend(
                    boundary
                    for boundary in paragraph_style_boundaries
                    if cp_start < boundary < cp_end
                )
                boundaries.append(cp_end)
                for span_start, span_end in zip(boundaries, boundaries[1:]):
                    properties, unsupported, relative_count = (
                        apply_character_modifiers(
                            modifiers,
                            base_properties=paragraph_style_character_at(span_start),
                            font_names=font_names,
                            style_properties_at=style_sheet.effective_character_at,
                        )
                    )
                    unsupported_character_sprms.update(unsupported)
                    style_relative_toggles += relative_count
                    character_spans.append(
                        CharacterFormatSpan(span_start, span_end, properties)
                    )

    def character_at(cp: int) -> CharacterProperties:
        for span in character_spans:
            if span.cp_start <= cp < span.cp_end:
                return span.properties
        return CharacterProperties()

    # Piece Prm character modifiers are applied after the CHPX grpprl.
    character_boundaries = {
        boundary
        for piece in piece_table.pieces
        for boundary in (piece.cp_start, piece.cp_end)
    }
    character_boundaries.update(
        boundary
        for span in character_spans
        for boundary in (span.cp_start, span.cp_end)
    )
    character_boundaries.update(paragraph_style_boundaries)
    composed_character_spans: list[CharacterFormatSpan] = []
    sorted_character_boundaries = sorted(character_boundaries)
    for cp_start, cp_end in zip(
        sorted_character_boundaries,
        sorted_character_boundaries[1:],
    ):
        if cp_start >= cp_end:
            continue
        properties = character_at(cp_start)
        piece = next(
            (
                value
                for value in piece_table.pieces
                if value.cp_start <= cp_start < value.cp_end
            ),
            None,
        )
        if piece is not None:
            modifiers = piece_table.modifiers_for_piece(piece, property_group=2)
            if modifiers:
                properties, unsupported, relative_count = apply_character_modifiers(
                    modifiers,
                    initial_properties=properties,
                    base_properties=paragraph_style_character_at(cp_start),
                    font_names=font_names,
                    style_properties_at=style_sheet.effective_character_at,
                )
                unsupported_character_sprms.update(unsupported)
                style_relative_toggles += relative_count
        composed_character_spans.append(
            CharacterFormatSpan(cp_start, cp_end, properties)
        )
    character_spans = list(_merge_character_spans(composed_character_spans))

    if unsupported_character_sprms:
        report.warning(
            "UNSUPPORTED_CHARACTER_SPRMS",
            "some direct character properties are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_character_sprms)],
        )
    if unsupported_paragraph_sprms:
        report.warning(
            "UNSUPPORTED_PARAGRAPH_SPRMS",
            "some direct paragraph properties are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_paragraph_sprms)],
        )
    referenced_style_ids = {
        properties.style_id
        for properties in (
            [span.properties for span in paragraph_spans]
            + [span.properties for span in character_spans]
        )
        if properties.style_id is not None
    }
    missing_style_ids = sorted(
        style_id
        for style_id in referenced_style_ids
        if style_id != 0 and style_sheet.style_at(style_id) is None
    )
    if missing_style_ids:
        report.warning(
            "MISSING_REFERENCED_STYLES",
            "some formatting runs reference absent or unsupported styles",
            style_ids=missing_style_ids,
        )
    if style_relative_toggles:
        report.info(
            "STYLE_RELATIVE_TOGGLES_RESOLVED",
            "style-relative character toggles were resolved through STSH inheritance",
            count=style_relative_toggles,
        )

    return FormattingMap(
        tuple(character_spans),
        tuple(paragraph_spans),
        character_run_count,
        paragraph_run_count,
    )
