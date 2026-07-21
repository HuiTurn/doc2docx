"""Header-textbox, shape-anchor, and field extraction for Word 97-2003."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import (
    CharacterProperties,
    FloatingTextBox,
    Paragraph,
    ParagraphProperties,
    ShapeStyle,
    Table,
    parse_main_story,
)
from .pieces import PieceTable


_HORIZONTAL_RELATIVE = {0: "margin", 1: "page", 2: "column"}
_VERTICAL_RELATIVE = {0: "margin", 1: "page", 2: "paragraph"}
_WRAP_TYPE = {
    0: "square",
    1: "topAndBottom",
    2: "square",
    3: "none",
    4: "tight",
    5: "through",
}
_WRAP_SIDE = {0: "both", 1: "left", 2: "right", 3: "largest"}


@dataclass(slots=True, frozen=True)
class HeaderTextBoxCollection:
    by_anchor_cp: Mapping[int, FloatingTextBox]
    textbox_count: int = 0
    field_count: int = 0
    styled_textbox_count: int = 0

    def textbox_at(self, cp: int) -> FloatingTextBox | None:
        return self.by_anchor_cp.get(cp)


@dataclass(slots=True, frozen=True)
class _Spa:
    anchor_cp: int
    shape_id: int
    left: int
    top: int
    right: int
    bottom: int
    horizontal_relative: str
    vertical_relative: str
    wrap_type: str
    wrap_side: str
    behind_text: bool
    anchor_locked: bool


@dataclass(slots=True, frozen=True)
class _TextBoxEntry:
    index: int
    cp_start: int
    cp_end: int
    shape_id: int
    chain_length: int
    paragraphs: tuple[Paragraph, ...]
    blocks: tuple[Paragraph | Table, ...]


def _checked_range(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    structure: str,
) -> memoryview:
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"{structure} range [{offset}, {offset + size}) exceeds Table stream"
        )
    return memoryview(table_stream)[offset : offset + size]


def _plc_count(size: int, data_size: int, structure: str) -> int:
    if size < 4 or (size - 4) % (4 + data_size):
        raise InvalidWordDocument(
            f"{structure} size {size} is not valid for {data_size}-byte data elements"
        )
    return (size - 4) // (4 + data_size)


def _read_header_textbox_fields(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    offset: int,
    size: int,
    ccp_header_textboxes: int,
    header_textbox_cp_start: int,
    report: ConversionReport,
) -> int:
    if size == 0:
        return 0
    raw = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure="PlcffldHdrTxbx",
    )
    count = _plc_count(size, 2, "PlcffldHdrTxbx")
    cps = struct.unpack_from(f"<{count + 1}I", raw, 0)
    field_cps = cps[:-1]
    if any(current <= previous for previous, current in zip(field_cps, field_cps[1:])):
        raise InvalidWordDocument("PlcffldHdrTxbx field CP values are not increasing")
    if any(cp >= ccp_header_textboxes for cp in field_cps):
        raise InvalidWordDocument(
            "PlcffldHdrTxbx field CP points beyond the header textbox document"
        )
    data_offset = 4 * (count + 1)
    stack: list[bool] = []
    begin_count = 0
    for index, cp in enumerate(field_cps):
        fldch = raw[data_offset + index * 2] & 0x1F
        if fldch not in (0x13, 0x14, 0x15):
            raise InvalidWordDocument(
                f"PlcffldHdrTxbx entry {index} has invalid field character 0x{fldch:02X}"
            )
        units = piece_table.extract_characters(
            header_textbox_cp_start + cp,
            header_textbox_cp_start + cp + 1,
            report,
            story="header-textboxes",
        )
        if len(units) != 1 or ord(units[0].text) != fldch:
            raise InvalidWordDocument(
                f"PlcffldHdrTxbx entry {index} does not match its story character"
            )
        if fldch == 0x13:
            stack.append(False)
            begin_count += 1
        elif fldch == 0x14:
            if not stack or stack[-1]:
                raise InvalidWordDocument(
                    "PlcffldHdrTxbx contains an invalid field-separator sequence"
                )
            stack[-1] = True
        else:
            if not stack:
                raise InvalidWordDocument(
                    "PlcffldHdrTxbx contains an unmatched field-end character"
                )
            stack.pop()
    if stack:
        raise InvalidWordDocument("PlcffldHdrTxbx contains an unterminated field")
    return begin_count


def _read_spas(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    offset: int,
    size: int,
    ccp_headers: int,
    header_story_cp_start: int,
    report: ConversionReport,
) -> dict[int, _Spa]:
    if size == 0:
        return {}
    raw = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure="PlcSpaHdr",
    )
    count = _plc_count(size, 26, "PlcSpaHdr")
    cps = struct.unpack_from(f"<{count + 1}I", raw, 0)
    anchor_cps = cps[:-1]
    if any(current <= previous for previous, current in zip(anchor_cps, anchor_cps[1:])):
        raise InvalidWordDocument("PlcSpaHdr anchor CP values are not increasing")
    if any(cp >= ccp_headers for cp in anchor_cps):
        raise InvalidWordDocument("PlcSpaHdr anchor CP points beyond the header document")
    data_offset = 4 * (count + 1)
    spas: dict[int, _Spa] = {}
    for index, anchor_cp in enumerate(anchor_cps):
        shape_id, left, top, right, bottom, flags, _ = struct.unpack_from(
            "<I4iHI", raw, data_offset + index * 26
        )
        if shape_id in spas:
            raise InvalidWordDocument(f"PlcSpaHdr repeats shape id {shape_id}")
        if right < left or bottom < top:
            raise InvalidWordDocument(
                f"PlcSpaHdr shape {shape_id} has an inverted rectangle"
            )
        horizontal_code = (flags >> 1) & 0x03
        vertical_code = (flags >> 3) & 0x03
        wrap_code = (flags >> 5) & 0x0F
        wrap_side_code = (flags >> 9) & 0x0F
        if horizontal_code not in _HORIZONTAL_RELATIVE:
            raise InvalidWordDocument(
                f"PlcSpaHdr shape {shape_id} has invalid bx {horizontal_code}"
            )
        if vertical_code not in _VERTICAL_RELATIVE:
            raise InvalidWordDocument(
                f"PlcSpaHdr shape {shape_id} has invalid by {vertical_code}"
            )
        if wrap_code not in _WRAP_TYPE:
            raise InvalidWordDocument(
                f"PlcSpaHdr shape {shape_id} has invalid wr {wrap_code}"
            )
        if wrap_side_code not in _WRAP_SIDE:
            raise InvalidWordDocument(
                f"PlcSpaHdr shape {shape_id} has invalid wrk {wrap_side_code}"
            )
        units = piece_table.extract_characters(
            header_story_cp_start + anchor_cp,
            header_story_cp_start + anchor_cp + 1,
            report,
            story="headers",
        )
        if len(units) != 1 or units[0].text != "\x08":
            raise InvalidWordDocument(
                f"PlcSpaHdr anchor at CP {anchor_cp} is not a shape character"
            )
        spas[shape_id] = _Spa(
            anchor_cp=anchor_cp,
            shape_id=shape_id,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            horizontal_relative=_HORIZONTAL_RELATIVE[horizontal_code],
            vertical_relative=_VERTICAL_RELATIVE[vertical_code],
            wrap_type=_WRAP_TYPE[wrap_code],
            wrap_side=_WRAP_SIDE[wrap_side_code],
            behind_text=bool(flags & 0x4000),
            anchor_locked=bool(flags & 0x8000),
        )
    return spas


def _read_textbox_entries(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    offset: int,
    size: int,
    ccp_header_textboxes: int,
    header_textbox_cp_start: int,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties] | None,
    paragraph_properties_at: Callable[[int], ParagraphProperties] | None,
) -> tuple[_TextBoxEntry, ...]:
    raw = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure="PlcfHdrtxbxTxt",
    )
    count = _plc_count(size, 22, "PlcfHdrtxbxTxt")
    if count < 1:
        raise InvalidWordDocument("PlcfHdrtxbxTxt has no reusable final entry")
    cps = struct.unpack_from(f"<{count + 1}I", raw, 0)
    if cps[0] != 0:
        raise InvalidWordDocument("PlcfHdrtxbxTxt does not begin at CP 0")
    if any(current <= previous for previous, current in zip(cps, cps[1:])):
        raise InvalidWordDocument("PlcfHdrtxbxTxt CP values are not increasing")
    if any(cp > ccp_header_textboxes for cp in cps[:-1]):
        raise InvalidWordDocument(
            "PlcfHdrtxbxTxt textbox CP points beyond the header textbox document"
        )
    data_offset = 4 * (count + 1)
    entries: list[_TextBoxEntry] = []
    for index in range(count):
        entry_offset = data_offset + index * 22
        first_union, second_union = struct.unpack_from("<ii", raw, entry_offset)
        reusable = struct.unpack_from("<H", raw, entry_offset + 8)[0]
        shape_id = struct.unpack_from("<I", raw, entry_offset + 14)[0]
        txid_undo = struct.unpack_from("<I", raw, entry_offset + 18)[0]
        is_final = index == count - 1
        if reusable and not reusable & 0x0001:
            raise InvalidWordDocument(
                f"PlcfHdrtxbxTxt entry {index} has invalid fReusable 0x{reusable:04X}"
            )
        if is_final or reusable:
            if not is_final and (
                cps[index + 1] - cps[index] != 1 or shape_id != 0
            ):
                raise InvalidWordDocument(
                    f"PlcfHdrtxbxTxt reusable entry {index} has invalid bounds or lid"
                )
            continue
        cp_start, cp_end = cps[index], cps[index + 1]
        if cp_end - cp_start <= 1:
            raise InvalidWordDocument(
                f"PlcfHdrtxbxTxt textbox {index} does not contain text and a separator"
            )
        if first_union <= 0 or second_union != 0:
            raise InvalidWordDocument(
                f"PlcfHdrtxbxTxt textbox {index} has invalid chain metadata"
            )
        if shape_id == 0 or txid_undo != 0:
            raise InvalidWordDocument(
                f"PlcfHdrtxbxTxt textbox {index} has invalid shape metadata"
            )
        units = piece_table.extract_characters(
            header_textbox_cp_start + cp_start,
            header_textbox_cp_start + cp_end,
            report,
            story=f"header-textbox-{index}",
        )
        if not units or units[-1].text != "\r":
            raise InvalidWordDocument(
                f"PlcfHdrtxbxTxt textbox {index} has no trailing separator"
            )
        content = units[:-1]
        parsed = parse_main_story(
            content,
            report,
            character_properties_at=character_properties_at,
            paragraph_properties_at=paragraph_properties_at,
            story_name=f"header-textbox-{index}",
        )
        entries.append(
            _TextBoxEntry(
                index=index,
                cp_start=cp_start,
                cp_end=cp_end,
                shape_id=shape_id,
                chain_length=first_union,
                paragraphs=parsed.paragraphs,
                blocks=parsed.blocks,
            )
        )
    return tuple(entries)


def _validate_break_descriptors(
    table_stream: bytes,
    entries: tuple[_TextBoxEntry, ...],
    *,
    offset: int,
    size: int,
    ccp_header_textboxes: int,
) -> None:
    raw = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure="PlcfTxbxHdrBkd",
    )
    count = _plc_count(size, 6, "PlcfTxbxHdrBkd")
    if count < 1:
        raise InvalidWordDocument("PlcfTxbxHdrBkd has no final descriptor")
    cps = struct.unpack_from(f"<{count + 1}I", raw, 0)
    if any(current <= previous for previous, current in zip(cps, cps[1:])):
        raise InvalidWordDocument("PlcfTxbxHdrBkd CP values are not increasing")
    if any(cp > ccp_header_textboxes for cp in cps[:-1]):
        raise InvalidWordDocument(
            "PlcfTxbxHdrBkd CP points beyond the header textbox document"
        )
    data_offset = 4 * (count + 1)
    by_index = {entry.index: entry for entry in entries}
    descriptor_counts: dict[int, int] = {}
    for index in range(count - 1):
        itxbxs = struct.unpack_from("<h", raw, data_offset + index * 6)[0]
        entry = by_index.get(itxbxs)
        if entry is None:
            raise InvalidWordDocument(
                f"PlcfTxbxHdrBkd descriptor {index} references textbox {itxbxs}"
            )
        if cps[index] < entry.cp_start or cps[index + 1] > entry.cp_end:
            raise InvalidWordDocument(
                f"PlcfTxbxHdrBkd descriptor {index} falls outside its textbox range"
            )
        descriptor_counts[itxbxs] = descriptor_counts.get(itxbxs, 0) + 1
    for entry in entries:
        if descriptor_counts.get(entry.index, 0) != entry.chain_length:
            raise InvalidWordDocument(
                f"PlcfTxbxHdrBkd textbox {entry.index} chain length does not match its descriptors"
            )


def read_header_textboxes(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    ccp_headers: int,
    header_story_cp_start: int,
    ccp_header_textboxes: int,
    header_textbox_cp_start: int,
    spa_offset: int,
    spa_size: int,
    text_offset: int,
    text_size: int,
    field_offset: int,
    field_size: int,
    break_offset: int,
    break_size: int,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties] | None = None,
    paragraph_properties_at: Callable[[int], ParagraphProperties] | None = None,
    shape_style_at: Callable[[int], ShapeStyle | None] | None = None,
) -> HeaderTextBoxCollection:
    """Read header textbox contents and associate them with header-story anchors."""

    structure_sizes = (spa_size, text_size, field_size, break_size)
    if ccp_header_textboxes == 0:
        if any(structure_sizes):
            raise InvalidWordDocument(
                "header textbox structures exist while ccpHdrTxbx is zero"
            )
        return HeaderTextBoxCollection({})
    if text_size == 0 or spa_size == 0 or break_size == 0:
        raise InvalidWordDocument(
            "ccpHdrTxbx requires PlcfHdrtxbxTxt, PlcSpaHdr, and PlcfTxbxHdrBkd"
        )
    cp_end = header_textbox_cp_start + ccp_header_textboxes
    if cp_end > piece_table.cp_end:
        raise InvalidWordDocument(
            f"header textbox range [{header_textbox_cp_start}, {cp_end}) exceeds "
            f"Piece Table CP {piece_table.cp_end}"
        )
    field_count = _read_header_textbox_fields(
        table_stream,
        piece_table,
        offset=field_offset,
        size=field_size,
        ccp_header_textboxes=ccp_header_textboxes,
        header_textbox_cp_start=header_textbox_cp_start,
        report=report,
    )
    spas = _read_spas(
        table_stream,
        piece_table,
        offset=spa_offset,
        size=spa_size,
        ccp_headers=ccp_headers,
        header_story_cp_start=header_story_cp_start,
        report=report,
    )
    entries = _read_textbox_entries(
        table_stream,
        piece_table,
        offset=text_offset,
        size=text_size,
        ccp_header_textboxes=ccp_header_textboxes,
        header_textbox_cp_start=header_textbox_cp_start,
        report=report,
        character_properties_at=character_properties_at,
        paragraph_properties_at=paragraph_properties_at,
    )
    _validate_break_descriptors(
        table_stream,
        entries,
        offset=break_offset,
        size=break_size,
        ccp_header_textboxes=ccp_header_textboxes,
    )
    by_anchor_cp: dict[int, FloatingTextBox] = {}
    linked_count = 0
    approximated_style_count = 0
    for entry in entries:
        spa = spas.get(entry.shape_id)
        if spa is None:
            raise InvalidWordDocument(
                f"header textbox {entry.index} has no PlcSpaHdr shape {entry.shape_id}"
            )
        absolute_anchor_cp = header_story_cp_start + spa.anchor_cp
        if absolute_anchor_cp in by_anchor_cp:
            raise InvalidWordDocument(
                f"multiple header textboxes use anchor CP {spa.anchor_cp}"
            )
        shape_style = (
            shape_style_at(entry.shape_id) if shape_style_at is not None else None
        )
        if shape_style is None or shape_style.approximated:
            approximated_style_count += 1
        by_anchor_cp[absolute_anchor_cp] = FloatingTextBox(
            shape_id=entry.shape_id,
            anchor_cp=absolute_anchor_cp,
            left_twips=spa.left,
            top_twips=spa.top,
            width_twips=max(spa.right - spa.left, 1),
            height_twips=max(spa.bottom - spa.top, 1),
            horizontal_relative=spa.horizontal_relative,
            vertical_relative=spa.vertical_relative,
            wrap_type=spa.wrap_type,
            wrap_side=spa.wrap_side,
            behind_text=spa.behind_text,
            anchor_locked=spa.anchor_locked,
            paragraphs=entry.paragraphs,
            blocks=entry.blocks,
            shape_style=shape_style,
        )
        if entry.chain_length > 1:
            linked_count += 1
    if linked_count:
        report.warning(
            "LINKED_HEADER_TEXTBOXES_FLATTENED",
            "linked header textbox chains were emitted in their first shape",
            location=SourceLocation(story="header-textboxes"),
            textbox_count=linked_count,
        )
    if approximated_style_count:
        report.warning(
            "HEADER_TEXTBOX_STYLE_APPROXIMATED",
            "some header textbox OfficeArt fill, line, or inset styling was approximated",
            location=SourceLocation(story="header-textboxes"),
            textbox_count=approximated_style_count,
        )
    return HeaderTextBoxCollection(
        by_anchor_cp=by_anchor_cp,
        textbox_count=len(entries),
        field_count=field_count,
        styled_textbox_count=len(entries) - approximated_style_count,
    )
