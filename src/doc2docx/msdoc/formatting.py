"""CHPX/PAPX FKP parsing and physical-FC to logical-CP mapping."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import struct

from ..diagnostics import ConversionReport
from ..errors import InvalidWordDocument
from ..model import CharacterProperties, ParagraphProperties
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
) -> FormattingMap:
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
    style_ids: set[int] = set()
    style_relative_toggles = 0
    character_run_count = 0
    paragraph_run_count = 0

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
            properties = CharacterProperties()
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
                properties, unsupported, relative_count = apply_character_modifiers(
                    modifiers
                )
                unsupported_character_sprms.update(unsupported)
                style_relative_toggles += relative_count
            for cp_start, cp_end in piece_table.fc_range_to_cp_ranges(
                run_fc_start,
                run_fc_end,
            ):
                character_spans.append(
                    CharacterFormatSpan(cp_start, cp_end, properties)
                )

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
                )
                unsupported_paragraph_sprms.update(unsupported)
                if properties.style_id not in (None, 0):
                    style_ids.add(properties.style_id)
            for cp_start, cp_end in piece_table.fc_range_to_cp_ranges(
                run_fc_start,
                run_fc_end,
            ):
                paragraph_spans.append(
                    ParagraphFormatSpan(cp_start, cp_end, properties)
                )

    if unsupported_character_sprms:
        report.warning(
            "UNSUPPORTED_CHARACTER_SPRMS",
            "some direct character properties are deferred beyond M3a",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_character_sprms)],
        )
    if unsupported_paragraph_sprms:
        report.warning(
            "UNSUPPORTED_PARAGRAPH_SPRMS",
            "some direct paragraph properties are deferred beyond M3a",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_paragraph_sprms)],
        )
    if style_relative_toggles:
        report.warning(
            "STYLE_RELATIVE_TOGGLES_DEFERRED",
            "style-relative character toggles require style inheritance and were ignored",
            count=style_relative_toggles,
        )
    if style_ids:
        report.warning(
            "STYLE_INHERITANCE_DEFERRED",
            "paragraph style inheritance is deferred beyond M3a; direct properties were kept",
            style_ids=sorted(style_ids),
        )

    return FormattingMap(
        _merge_character_spans(character_spans),
        _merge_paragraph_spans(paragraph_spans),
        character_run_count,
        paragraph_run_count,
    )
