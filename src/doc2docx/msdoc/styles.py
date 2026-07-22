"""MS-DOC STSH style-sheet parsing and inheritance resolution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import struct

from ..diagnostics import ConversionReport
from ..errors import InvalidWordDocument
from ..model import (
    CharacterProperties,
    FontDefinition,
    ParagraphProperties,
    StyleDefinition,
    StyleSheet,
    TableCellMargins,
    TableRowProperties,
    TableStyleConditionalProperties,
)
from .sprm import (
    PropertyModifier,
    apply_character_modifiers,
    apply_paragraph_modifiers,
    merge_character_properties,
    merge_paragraph_properties,
    parse_grpprl,
    unassigned_language_lids,
)


_STYLE_KINDS = {1: "paragraph", 2: "character", 3: "table", 4: "numbering"}

_CONDITIONAL_TABLE_STYLE_TYPES = {
    0x0040: "band1Horz",
    0x0080: "band2Horz",
    0x0010: "band1Vert",
    0x0020: "band2Vert",
    0x0004: "firstCol",
    0x0008: "lastCol",
    0x0001: "firstRow",
    0x0002: "lastRow",
    0x0200: "nwCell",
    0x0100: "neCell",
    0x0800: "swCell",
    0x0400: "seCell",
}

_EMPTY_STYLE_TABLE_ROW = TableRowProperties(
    default_cell_margins=TableCellMargins(None, None, None, None)
)


@dataclass(slots=True, frozen=True)
class _RawStyle:
    index: int
    name: str
    kind: str
    based_on: int | None
    next_style: int | None
    table_modifiers: tuple[PropertyModifier, ...]
    paragraph_modifiers: tuple[PropertyModifier, ...]
    character_modifiers: tuple[PropertyModifier, ...]


def _split_conditional_modifiers(
    modifiers: tuple[PropertyModifier, ...],
    *,
    opcode: int,
    label: str,
) -> tuple[
    tuple[PropertyModifier, ...],
    dict[int, tuple[PropertyModifier, ...]],
]:
    unconditional: list[PropertyModifier] = []
    conditional: dict[int, tuple[PropertyModifier, ...]] = {}
    for modifier in modifiers:
        if modifier.opcode != opcode:
            unconditional.append(modifier)
            continue
        operand = modifier.operand
        if len(operand) < 3 or operand[0] != len(operand) - 1:
            raise InvalidWordDocument(f"{label} CNFOperand has an invalid byte count")
        condition = struct.unpack_from("<h", operand, 1)[0]
        if condition not in _CONDITIONAL_TABLE_STYLE_TYPES:
            raise InvalidWordDocument(
                f"{label} CNFOperand has invalid condition 0x{condition & 0xFFFF:04X}"
            )
        nested = parse_grpprl(
            operand[3:],
            label=(
                f"{label} {_CONDITIONAL_TABLE_STYLE_TYPES[condition]} conditional grpprl"
            ),
        )
        conditional[condition] = (*conditional.get(condition, ()), *nested)
    return tuple(unconditional), conditional


def _font_name(fonts: tuple[FontDefinition, ...], index: int) -> str | None:
    if 0 <= index < len(fonts):
        return fonts[index].name
    return None


def _read_xstz(data: bytes, position: int, *, label: str) -> tuple[str, int]:
    if position > len(data) - 2:
        raise InvalidWordDocument(f"{label} has a truncated Xstz")
    character_count = struct.unpack_from("<H", data, position)[0]
    position += 2
    byte_count = character_count * 2
    end = position + byte_count
    if end > len(data) - 2:
        raise InvalidWordDocument(f"{label} style name exceeds STD")
    name = data[position:end].decode("utf-16le", errors="replace")
    if struct.unpack_from("<H", data, end)[0] != 0:
        raise InvalidWordDocument(f"{label} style name is not null-terminated")
    return name, end + 2


def _read_lpupx(data: bytes, position: int, *, label: str) -> tuple[bytes, int]:
    if position > len(data) - 2:
        raise InvalidWordDocument(f"{label} has a truncated LPUpx")
    byte_count = struct.unpack_from("<H", data, position)[0]
    position += 2
    end = position + byte_count
    if end > len(data):
        raise InvalidWordDocument(f"{label} LPUpx exceeds STD")
    value = data[position:end]
    position = end + (byte_count & 1)
    if position > len(data):
        raise InvalidWordDocument(f"{label} LPUpx padding exceeds STD")
    return value, position


def _parse_std(
    index: int,
    data: bytes,
    *,
    base_size: int,
) -> _RawStyle:
    label = f"STSH style {index}"
    if base_size not in (10, 18) or len(data) < base_size:
        raise InvalidWordDocument(
            f"{label} has invalid STD base size {base_size}"
        )
    _, base_word, upx_word = struct.unpack_from("<HHH", data)
    style_kind_code = base_word & 0x0F
    based_on_raw = (base_word >> 4) & 0x0FFF
    upx_count = upx_word & 0x0F
    next_raw = (upx_word >> 4) & 0x0FFF
    kind = _STYLE_KINDS.get(style_kind_code, "unknown")
    name, position = _read_xstz(data, base_size, label=label)

    upx_values: list[bytes] = []
    for upx_index in range(upx_count):
        value, position = _read_lpupx(
            data,
            position,
            label=f"{label} UPX {upx_index}",
        )
        upx_values.append(value)
    if position != len(data) and any(data[position:]):
        raise InvalidWordDocument(
            f"{label} has {len(data) - position} unexpected trailing bytes"
        )

    table_modifiers: tuple[PropertyModifier, ...] = ()
    paragraph_modifiers: tuple[PropertyModifier, ...] = ()
    character_modifiers: tuple[PropertyModifier, ...] = ()
    if kind == "paragraph":
        if upx_values:
            if len(upx_values[0]) < 2:
                raise InvalidWordDocument(f"{label} UpxPapx has no istd")
            paragraph_modifiers = parse_grpprl(
                upx_values[0][2:],
                label=f"{label}.UpxPapx.grpprl",
                allow_trailing_zero_padding=True,
            )
        if len(upx_values) >= 2:
            character_modifiers = parse_grpprl(
                upx_values[1],
                label=f"{label}.UpxChpx.grpprl",
                allow_trailing_zero_padding=True,
            )
    elif kind == "character" and upx_values:
        character_modifiers = parse_grpprl(
            upx_values[0],
            label=f"{label}.UpxChpx.grpprl",
            allow_trailing_zero_padding=True,
        )
    elif kind == "table":
        # StkTableGRLPUPX stores optional TAPX, PAPX, and CHPX values in
        # exactly this order. UpxPapx begins with an istd just like a
        # paragraph-style UpxPapx; UpxChpx is a bare grpprl.
        if upx_values:
            table_modifiers = parse_grpprl(
                upx_values[0],
                label=f"{label}.UpxTapx.grpprl",
                allow_trailing_zero_padding=True,
            )
        if len(upx_values) >= 2:
            if len(upx_values[1]) < 2:
                raise InvalidWordDocument(f"{label} UpxPapx has no istd")
            paragraph_modifiers = parse_grpprl(
                upx_values[1][2:],
                label=f"{label}.UpxPapx.grpprl",
                allow_trailing_zero_padding=True,
            )
        if len(upx_values) >= 3:
            character_modifiers = parse_grpprl(
                upx_values[2],
                label=f"{label}.UpxChpx.grpprl",
                allow_trailing_zero_padding=True,
            )
    elif kind == "numbering" and upx_values:
        # StkListGRLPUPX contains one optional UpxPapx. Its leading istd
        # identifies the numbering style itself; the remaining grpprl can
        # contain only sprmPIlfo according to MS-DOC.
        if len(upx_values[0]) < 2:
            raise InvalidWordDocument(f"{label} UpxPapx has no istd")
        paragraph_modifiers = parse_grpprl(
            upx_values[0][2:],
            label=f"{label}.UpxPapx.grpprl",
            allow_trailing_zero_padding=True,
        )
        if any(modifier.opcode != 0x460B for modifier in paragraph_modifiers):
            raise InvalidWordDocument(
                f"{label} numbering UpxPapx contains a non-list SPRM"
            )

    return _RawStyle(
        index=index,
        name=name or f"Style {index}",
        kind=kind,
        based_on=None if based_on_raw == 0x0FFF else based_on_raw,
        next_style=None if next_raw == 0x0FFF else next_raw,
        table_modifiers=table_modifiers,
        paragraph_modifiers=paragraph_modifiers,
        character_modifiers=character_modifiers,
    )


def read_style_sheet(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    fonts: tuple[FontDefinition, ...],
    report: ConversionReport,
) -> StyleSheet:
    if size == 0:
        return StyleSheet()
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"STSH range [{offset}, {offset + size}) exceeds Table stream"
        )
    data = table_stream[offset : offset + size]
    if len(data) < 20:
        raise InvalidWordDocument("STSH is truncated")
    stshi_size = struct.unpack_from("<H", data)[0]
    if stshi_size < 18 or stshi_size > len(data) - 2:
        raise InvalidWordDocument(f"STSH has invalid cbStshi {stshi_size}")
    stshi = data[2 : 2 + stshi_size]
    style_count, base_size = struct.unpack_from("<HH", stshi)
    if base_size not in (10, 18):
        raise InvalidWordDocument(
            f"STSH has unsupported cbSTDBaseInFile {base_size}"
        )
    default_ascii, default_east_asia, default_other = struct.unpack_from(
        "<hhh", stshi, 12
    )
    # ftcBi lives in the versioned tail of STSHI rather than at a stable
    # Stshif offset, so leave it unspecified until that tail is interpreted.
    default_complex = -1
    default_character = CharacterProperties(
        ascii_font=_font_name(fonts, default_ascii),
        high_ansi_font=_font_name(fonts, default_other),
        east_asia_font=_font_name(fonts, default_east_asia),
        complex_script_font=_font_name(fonts, default_complex),
    )

    raw_styles: list[_RawStyle | None] = []
    position = 2 + stshi_size
    for index in range(style_count):
        if position > len(data) - 2:
            raise InvalidWordDocument(f"STSH is truncated before style {index}")
        std_size = struct.unpack_from("<H", data, position)[0]
        position += 2
        if std_size == 0:
            raw_styles.append(None)
            continue
        end = position + std_size
        if end > len(data):
            raise InvalidWordDocument(f"STSH style {index} exceeds the table")
        raw_styles.append(_parse_std(index, data[position:end], base_size=base_size))
        position = end + (std_size & 1)
    if position > len(data):
        raise InvalidWordDocument("STSH style padding exceeds the table")

    font_names = {font.index: font.name for font in fonts}
    definitions: list[StyleDefinition | None] = [None] * style_count
    effective_paragraphs: list[ParagraphProperties | None] = [None] * style_count
    effective_characters: list[CharacterProperties | None] = [None] * style_count
    visiting: set[int] = set()
    unsupported_character: set[int] = set()
    unsupported_paragraph: set[int] = set()
    unsupported_table: set[int] = set()
    repaired_language_lids: set[int] = set()

    def resolve(index: int) -> None:
        if definitions[index] is not None or raw_styles[index] is None:
            return
        if index in visiting:
            raise InvalidWordDocument(f"STSH style inheritance cycle at style {index}")
        visiting.add(index)
        raw = raw_styles[index]
        assert raw is not None
        repaired_language_lids.update(
            unassigned_language_lids(raw.character_modifiers)
        )
        parent_paragraph = ParagraphProperties()
        parent_character = default_character
        if raw.based_on is not None and 0 <= raw.based_on < style_count:
            resolve(raw.based_on)
            if effective_paragraphs[raw.based_on] is not None:
                parent_paragraph = effective_paragraphs[raw.based_on]  # type: ignore[assignment]
            if effective_characters[raw.based_on] is not None:
                parent_character = effective_characters[raw.based_on]  # type: ignore[assignment]

        table_modifiers = raw.table_modifiers
        paragraph_modifiers = raw.paragraph_modifiers
        character_modifiers = raw.character_modifiers
        conditional_table: dict[int, tuple[PropertyModifier, ...]] = {}
        conditional_paragraph: dict[int, tuple[PropertyModifier, ...]] = {}
        conditional_character: dict[int, tuple[PropertyModifier, ...]] = {}
        if raw.kind == "table":
            table_modifiers, conditional_table = _split_conditional_modifiers(
                table_modifiers,
                opcode=0xD66A,
                label=f"STSH table style {index} TAPX",
            )
            paragraph_modifiers, conditional_paragraph = (
                _split_conditional_modifiers(
                    paragraph_modifiers,
                    opcode=0xC666,
                    label=f"STSH table style {index} PAPX",
                )
            )
            character_modifiers, conditional_character = (
                _split_conditional_modifiers(
                    character_modifiers,
                    opcode=0xCA85,
                    label=f"STSH table style {index} CHPX",
                )
            )

        # A sprmTIstd inside UpxTapx identifies the style itself and MUST be
        # ignored while applying that style. Other supported table modifiers
        # are retained in table_row so they can be emitted in w:tblPr.
        table_paragraph, unsupported = apply_paragraph_modifiers(
            tuple(
                modifier
                for modifier in table_modifiers
                if modifier.opcode != 0x563A
            ),
            style_id=None,
        )
        unsupported_table.update(unsupported)
        direct_paragraph, unsupported = apply_paragraph_modifiers(
            paragraph_modifiers,
            style_id=None,
            initial_properties=table_paragraph,
        )
        unsupported_paragraph.update(unsupported)
        direct_character, unsupported, _ = apply_character_modifiers(
            character_modifiers,
            base_properties=parent_character,
            font_names=font_names,
        )
        unsupported_character.update(unsupported)
        effective_paragraph = merge_paragraph_properties(
            parent_paragraph,
            direct_paragraph,
        )
        effective_character = merge_character_properties(
            parent_character,
            replace(direct_character, style_id=None),
        )
        conditional_definitions: list[TableStyleConditionalProperties] = []
        conditional_ids = (
            set(conditional_table)
            | set(conditional_paragraph)
            | set(conditional_character)
        )
        for condition in _CONDITIONAL_TABLE_STYLE_TYPES:
            if condition not in conditional_ids:
                continue
            conditional_table_paragraph, unsupported = apply_paragraph_modifiers(
                conditional_table.get(condition, ()),
                style_id=None,
                initial_properties=ParagraphProperties(
                    table_row=_EMPTY_STYLE_TABLE_ROW
                ),
            )
            unsupported_table.update(unsupported)
            conditional_direct_paragraph, unsupported = apply_paragraph_modifiers(
                conditional_paragraph.get(condition, ()),
                style_id=None,
                initial_properties=conditional_table_paragraph,
            )
            unsupported_paragraph.update(unsupported)
            nested_character_modifiers = conditional_character.get(condition, ())
            repaired_language_lids.update(
                unassigned_language_lids(nested_character_modifiers)
            )
            conditional_direct_character, unsupported, _ = (
                apply_character_modifiers(
                    nested_character_modifiers,
                    base_properties=parent_character,
                    font_names=font_names,
                )
            )
            unsupported_character.update(unsupported)
            table_row = conditional_direct_paragraph.table_row
            conditional_definitions.append(
                TableStyleConditionalProperties(
                    condition=_CONDITIONAL_TABLE_STYLE_TYPES[condition],
                    table_properties=(
                        table_row
                        if table_row is not None
                        and table_row != _EMPTY_STYLE_TABLE_ROW
                        else None
                    ),
                    paragraph_properties=replace(
                        conditional_direct_paragraph,
                        table_row=None,
                    ),
                    character_properties=conditional_direct_character,
                )
            )
        definitions[index] = StyleDefinition(
            index=index,
            name=raw.name,
            kind=raw.kind,
            based_on=raw.based_on,
            next_style=raw.next_style,
            paragraph_properties=direct_paragraph,
            character_properties=direct_character,
            conditional_table_properties=tuple(conditional_definitions),
        )
        effective_paragraphs[index] = effective_paragraph
        effective_characters[index] = effective_character
        visiting.remove(index)

    for style_index in range(style_count):
        resolve(style_index)

    if unsupported_character:
        report.warning(
            "UNSUPPORTED_STYLE_CHARACTER_SPRMS",
            "some character properties in the DOC style sheet are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_character)],
        )
    if repaired_language_lids:
        report.warning(
            "UNASSIGNED_STYLE_LANGUAGE_LID_REPAIRED",
            "unassigned language IDs in the DOC style sheet were mapped to no linguistic content",
            lids=[f"0x{value:04X}" for value in sorted(repaired_language_lids)],
            output_language="zxx",
        )
    if unsupported_paragraph:
        report.warning(
            "UNSUPPORTED_STYLE_PARAGRAPH_SPRMS",
            "some paragraph properties in the DOC style sheet are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_paragraph)],
        )
    if unsupported_table:
        report.warning(
            "UNSUPPORTED_STYLE_TABLE_SPRMS",
            "some table properties in the DOC style sheet are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_table)],
        )
    deferred_kinds = sorted(
        {raw.kind for raw in raw_styles if raw is not None}
        - {"paragraph", "character", "table", "numbering"}
    )
    if deferred_kinds:
        report.warning(
            "STYLE_KINDS_DEFERRED",
            "unknown style kinds were parsed but not emitted",
            kinds=deferred_kinds,
        )

    return StyleSheet(
        styles=tuple(definitions),
        default_character_properties=default_character,
        effective_character_properties=tuple(effective_characters),
    )
