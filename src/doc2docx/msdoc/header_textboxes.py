"""Main/header textbox, shape-anchor, and field extraction for Word 97-2003."""

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
class TextBoxCollection:
    by_anchor_cp: Mapping[int, FloatingTextBox]
    textbox_count: int = 0
    field_count: int = 0
    styled_textbox_count: int = 0

    def textbox_at(self, cp: int) -> FloatingTextBox | None:
        return self.by_anchor_cp.get(cp)

    @property
    def shape_ids(self) -> frozenset[int]:
        return frozenset(textbox.shape_id for textbox in self.by_anchor_cp.values())


# Preserve the public M5c name while exposing the shared collection to M7d.
HeaderTextBoxCollection = TextBoxCollection


@dataclass(slots=True, frozen=True)
class ShapeAnchor:
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


def _read_textbox_fields(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    offset: int,
    size: int,
    ccp_textboxes: int,
    textbox_cp_start: int,
    field_structure: str,
    textbox_story_name: str,
    report: ConversionReport,
) -> int:
    if size == 0:
        return 0
    raw = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure=field_structure,
    )
    count = _plc_count(size, 2, field_structure)
    cps = struct.unpack_from(f"<{count + 1}I", raw, 0)
    field_cps = cps[:-1]
    if any(current <= previous for previous, current in zip(field_cps, field_cps[1:])):
        raise InvalidWordDocument(
            f"{field_structure} field CP values are not increasing"
        )
    if any(cp >= ccp_textboxes for cp in field_cps):
        raise InvalidWordDocument(
            f"{field_structure} field CP points beyond the textbox document"
        )
    data_offset = 4 * (count + 1)
    stack: list[bool] = []
    begin_count = 0
    for index, cp in enumerate(field_cps):
        fldch = raw[data_offset + index * 2] & 0x1F
        if fldch not in (0x13, 0x14, 0x15):
            raise InvalidWordDocument(
                f"{field_structure} entry {index} has invalid field character 0x{fldch:02X}"
            )
        units = piece_table.extract_characters(
            textbox_cp_start + cp,
            textbox_cp_start + cp + 1,
            report,
            story=textbox_story_name,
        )
        if len(units) != 1 or ord(units[0].text) != fldch:
            raise InvalidWordDocument(
                f"{field_structure} entry {index} does not match its story character"
            )
        if fldch == 0x13:
            stack.append(False)
            begin_count += 1
        elif fldch == 0x14:
            if not stack or stack[-1]:
                raise InvalidWordDocument(
                    f"{field_structure} contains an invalid field-separator sequence"
                )
            stack[-1] = True
        else:
            if not stack:
                raise InvalidWordDocument(
                    f"{field_structure} contains an unmatched field-end character"
                )
            stack.pop()
    if stack:
        raise InvalidWordDocument(f"{field_structure} contains an unterminated field")
    return begin_count


def read_shape_anchors(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    offset: int,
    size: int,
    ccp_anchor_story: int,
    anchor_story_cp_start: int,
    spa_structure: str,
    anchor_story_name: str,
    report: ConversionReport,
) -> dict[int, ShapeAnchor]:
    """Read and validate one main/header PlcSpa anchor table."""
    if size == 0:
        return {}
    raw = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure=spa_structure,
    )
    count = _plc_count(size, 26, spa_structure)
    cps = struct.unpack_from(f"<{count + 1}I", raw, 0)
    anchor_cps = cps[:-1]
    if any(current <= previous for previous, current in zip(anchor_cps, anchor_cps[1:])):
        raise InvalidWordDocument(
            f"{spa_structure} anchor CP values are not increasing"
        )
    if any(cp >= ccp_anchor_story for cp in anchor_cps):
        raise InvalidWordDocument(
            f"{spa_structure} anchor CP points beyond its document story"
        )
    data_offset = 4 * (count + 1)
    spas: dict[int, ShapeAnchor] = {}
    for index, anchor_cp in enumerate(anchor_cps):
        shape_id, left, top, right, bottom, flags, _ = struct.unpack_from(
            "<I4iHI", raw, data_offset + index * 26
        )
        if shape_id in spas:
            raise InvalidWordDocument(f"{spa_structure} repeats shape id {shape_id}")
        if right < left or bottom < top:
            raise InvalidWordDocument(
                f"{spa_structure} shape {shape_id} has an inverted rectangle"
            )
        horizontal_code = (flags >> 1) & 0x03
        vertical_code = (flags >> 3) & 0x03
        wrap_code = (flags >> 5) & 0x0F
        wrap_side_code = (flags >> 9) & 0x0F
        if horizontal_code not in _HORIZONTAL_RELATIVE:
            raise InvalidWordDocument(
                f"{spa_structure} shape {shape_id} has invalid bx {horizontal_code}"
            )
        if vertical_code not in _VERTICAL_RELATIVE:
            raise InvalidWordDocument(
                f"{spa_structure} shape {shape_id} has invalid by {vertical_code}"
            )
        if wrap_code not in _WRAP_TYPE:
            raise InvalidWordDocument(
                f"{spa_structure} shape {shape_id} has invalid wr {wrap_code}"
            )
        if wrap_side_code not in _WRAP_SIDE:
            raise InvalidWordDocument(
                f"{spa_structure} shape {shape_id} has invalid wrk {wrap_side_code}"
            )
        units = piece_table.extract_characters(
            anchor_story_cp_start + anchor_cp,
            anchor_story_cp_start + anchor_cp + 1,
            report,
            story=anchor_story_name,
        )
        if len(units) != 1 or units[0].text != "\x08":
            raise InvalidWordDocument(
                f"{spa_structure} anchor at CP {anchor_cp} is not a shape character"
            )
        spas[shape_id] = ShapeAnchor(
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
    ccp_textboxes: int,
    textbox_cp_start: int,
    text_structure: str,
    textbox_story_name: str,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties] | None,
    paragraph_properties_at: Callable[[int], ParagraphProperties] | None,
) -> tuple[_TextBoxEntry, ...]:
    raw = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure=text_structure,
    )
    count = _plc_count(size, 22, text_structure)
    if count < 1:
        raise InvalidWordDocument(f"{text_structure} has no reusable final entry")
    cps = struct.unpack_from(f"<{count + 1}I", raw, 0)
    if cps[0] != 0:
        raise InvalidWordDocument(f"{text_structure} does not begin at CP 0")
    if any(current <= previous for previous, current in zip(cps, cps[1:])):
        raise InvalidWordDocument(f"{text_structure} CP values are not increasing")
    if any(cp > ccp_textboxes for cp in cps[:-1]):
        raise InvalidWordDocument(
            f"{text_structure} textbox CP points beyond the textbox document"
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
                f"{text_structure} entry {index} has invalid fReusable 0x{reusable:04X}"
            )
        if is_final or reusable:
            if not is_final and (
                cps[index + 1] - cps[index] != 1 or shape_id != 0
            ):
                raise InvalidWordDocument(
                    f"{text_structure} reusable entry {index} has invalid bounds or lid"
                )
            continue
        cp_start, cp_end = cps[index], cps[index + 1]
        if cp_end - cp_start <= 1:
            raise InvalidWordDocument(
                f"{text_structure} textbox {index} does not contain text and a separator"
            )
        if first_union <= 0 or second_union != 0:
            raise InvalidWordDocument(
                f"{text_structure} textbox {index} has invalid chain metadata"
            )
        if shape_id == 0 or txid_undo != 0:
            raise InvalidWordDocument(
                f"{text_structure} textbox {index} has invalid shape metadata"
            )
        units = piece_table.extract_characters(
            textbox_cp_start + cp_start,
            textbox_cp_start + cp_end,
            report,
            story=f"{textbox_story_name}-{index}",
        )
        if not units or units[-1].text != "\r":
            raise InvalidWordDocument(
                f"{text_structure} textbox {index} has no trailing separator"
            )
        content = units[:-1]
        parsed = parse_main_story(
            content,
            report,
            character_properties_at=character_properties_at,
            paragraph_properties_at=paragraph_properties_at,
            story_name=f"{textbox_story_name}-{index}",
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
    ccp_textboxes: int,
    break_structure: str,
) -> None:
    raw = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure=break_structure,
    )
    count = _plc_count(size, 6, break_structure)
    if count < 1:
        raise InvalidWordDocument(f"{break_structure} has no final descriptor")
    cps = struct.unpack_from(f"<{count + 1}I", raw, 0)
    if any(current <= previous for previous, current in zip(cps, cps[1:])):
        raise InvalidWordDocument(f"{break_structure} CP values are not increasing")
    if any(cp > ccp_textboxes for cp in cps[:-1]):
        raise InvalidWordDocument(
            f"{break_structure} CP points beyond the textbox document"
        )
    data_offset = 4 * (count + 1)
    by_index = {entry.index: entry for entry in entries}
    descriptor_counts: dict[int, int] = {}
    for index in range(count - 1):
        itxbxs = struct.unpack_from("<h", raw, data_offset + index * 6)[0]
        entry = by_index.get(itxbxs)
        if entry is None:
            raise InvalidWordDocument(
                f"{break_structure} descriptor {index} references textbox {itxbxs}"
            )
        if cps[index] < entry.cp_start or cps[index + 1] > entry.cp_end:
            raise InvalidWordDocument(
                f"{break_structure} descriptor {index} falls outside its textbox range"
            )
        descriptor_counts[itxbxs] = descriptor_counts.get(itxbxs, 0) + 1
    for entry in entries:
        if descriptor_counts.get(entry.index, 0) != entry.chain_length:
            raise InvalidWordDocument(
                f"{break_structure} textbox {entry.index} chain length does not "
                "match its descriptors"
            )


def _read_textboxes(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    ccp_anchor_story: int,
    anchor_story_cp_start: int,
    ccp_textboxes: int,
    textbox_cp_start: int,
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
    is_header: bool,
) -> TextBoxCollection:
    """Read one textbox story and associate its contents with shape anchors."""

    context_name = "header textbox" if is_header else "main textbox"
    count_name = "ccpHdrTxbx" if is_header else "ccpTxbx"
    field_structure = "PlcffldHdrTxbx" if is_header else "PlcfFldTxbx"
    spa_structure = "PlcSpaHdr" if is_header else "PlcSpaMom"
    text_structure = "PlcfHdrtxbxTxt" if is_header else "PlcftxbxTxt"
    break_structure = "PlcfTxbxHdrBkd" if is_header else "PlcfTxbxBkd"
    anchor_story_name = "headers" if is_header else "main"
    textbox_story_name = "header-textbox" if is_header else "textbox"
    textbox_location_story = "header-textboxes" if is_header else "textboxes"

    structure_sizes = (text_size, field_size, break_size)
    if ccp_textboxes == 0:
        if any(structure_sizes):
            raise InvalidWordDocument(
                f"{context_name} structures exist while {count_name} is zero"
            )
        return TextBoxCollection({})
    if text_size == 0 or spa_size == 0 or break_size == 0:
        raise InvalidWordDocument(
            f"{count_name} requires {text_structure}, {spa_structure}, "
            f"and {break_structure}"
        )
    cp_end = textbox_cp_start + ccp_textboxes
    if cp_end > piece_table.cp_end:
        raise InvalidWordDocument(
            f"{context_name} range [{textbox_cp_start}, {cp_end}) exceeds "
            f"Piece Table CP {piece_table.cp_end}"
        )
    field_count = _read_textbox_fields(
        table_stream,
        piece_table,
        offset=field_offset,
        size=field_size,
        ccp_textboxes=ccp_textboxes,
        textbox_cp_start=textbox_cp_start,
        field_structure=field_structure,
        textbox_story_name=textbox_location_story,
        report=report,
    )
    spas = read_shape_anchors(
        table_stream,
        piece_table,
        offset=spa_offset,
        size=spa_size,
        ccp_anchor_story=ccp_anchor_story,
        anchor_story_cp_start=anchor_story_cp_start,
        spa_structure=spa_structure,
        anchor_story_name=anchor_story_name,
        report=report,
    )
    entries = _read_textbox_entries(
        table_stream,
        piece_table,
        offset=text_offset,
        size=text_size,
        ccp_textboxes=ccp_textboxes,
        textbox_cp_start=textbox_cp_start,
        text_structure=text_structure,
        textbox_story_name=textbox_story_name,
        report=report,
        character_properties_at=character_properties_at,
        paragraph_properties_at=paragraph_properties_at,
    )
    _validate_break_descriptors(
        table_stream,
        entries,
        offset=break_offset,
        size=break_size,
        ccp_textboxes=ccp_textboxes,
        break_structure=break_structure,
    )
    by_anchor_cp: dict[int, FloatingTextBox] = {}
    linked_count = 0
    approximated_style_count = 0
    for entry in entries:
        spa = spas.get(entry.shape_id)
        if spa is None:
            raise InvalidWordDocument(
                f"{context_name} {entry.index} has no {spa_structure} shape "
                f"{entry.shape_id}"
            )
        absolute_anchor_cp = anchor_story_cp_start + spa.anchor_cp
        if absolute_anchor_cp in by_anchor_cp:
            raise InvalidWordDocument(
                f"multiple {context_name}s use anchor CP {spa.anchor_cp}"
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
            (
                "LINKED_HEADER_TEXTBOXES_FLATTENED"
                if is_header
                else "LINKED_MAIN_TEXTBOXES_FLATTENED"
            ),
            f"linked {context_name} chains were emitted in their first shape",
            location=SourceLocation(story=textbox_location_story),
            textbox_count=linked_count,
        )
    if approximated_style_count:
        report.warning(
            (
                "HEADER_TEXTBOX_STYLE_APPROXIMATED"
                if is_header
                else "MAIN_TEXTBOX_STYLE_APPROXIMATED"
            ),
            f"some {context_name} OfficeArt fill, line, or inset styling was approximated",
            location=SourceLocation(story=textbox_location_story),
            textbox_count=approximated_style_count,
        )
    return TextBoxCollection(
        by_anchor_cp=by_anchor_cp,
        textbox_count=len(entries),
        field_count=field_count,
        styled_textbox_count=len(entries) - approximated_style_count,
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
) -> TextBoxCollection:
    """Read header textbox contents and associate them with header anchors."""

    return _read_textboxes(
        table_stream,
        piece_table,
        ccp_anchor_story=ccp_headers,
        anchor_story_cp_start=header_story_cp_start,
        ccp_textboxes=ccp_header_textboxes,
        textbox_cp_start=header_textbox_cp_start,
        spa_offset=spa_offset,
        spa_size=spa_size,
        text_offset=text_offset,
        text_size=text_size,
        field_offset=field_offset,
        field_size=field_size,
        break_offset=break_offset,
        break_size=break_size,
        report=report,
        character_properties_at=character_properties_at,
        paragraph_properties_at=paragraph_properties_at,
        shape_style_at=shape_style_at,
        is_header=True,
    )


def read_main_textboxes(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    ccp_text: int,
    ccp_textboxes: int,
    textbox_cp_start: int,
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
) -> TextBoxCollection:
    """Read main-story textbox contents and associate them with main anchors."""

    return _read_textboxes(
        table_stream,
        piece_table,
        ccp_anchor_story=ccp_text,
        anchor_story_cp_start=0,
        ccp_textboxes=ccp_textboxes,
        textbox_cp_start=textbox_cp_start,
        spa_offset=spa_offset,
        spa_size=spa_size,
        text_offset=text_offset,
        text_size=text_size,
        field_offset=field_offset,
        field_size=field_size,
        break_offset=break_offset,
        break_size=break_size,
        report=report,
        character_properties_at=character_properties_at,
        paragraph_properties_at=paragraph_properties_at,
        shape_style_at=shape_style_at,
        is_header=False,
    )
