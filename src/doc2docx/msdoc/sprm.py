"""Bounded parsing and application of supported MS-DOC property modifiers."""

from __future__ import annotations

from dataclasses import dataclass, replace
import locale
import struct
from typing import Callable

from ..errors import InvalidWordDocument
from ..model import (
    BorderProperties,
    CharacterProperties,
    ParagraphProperties,
    ShadingProperties,
    TabStop,
    TableBorders,
    TableCellDefinition,
    TableCellMarginOverride,
    TableCellWidthOverride,
    TableRowProperties,
)


@dataclass(slots=True, frozen=True)
class PropertyModifier:
    opcode: int
    operand: bytes


_FIXED_OPERAND_LENGTHS = {0: 1, 1: 1, 2: 2, 3: 4, 4: 2, 5: 2, 7: 3}


def parse_grpprl(
    data: bytes,
    *,
    label: str,
    allow_trailing_zero_padding: bool = False,
) -> tuple[PropertyModifier, ...]:
    """Parse a complete grpprl, using Sprm.spra to bound every operand."""

    modifiers: list[PropertyModifier] = []
    position = 0
    while position < len(data):
        if len(data) - position < 2:
            if allow_trailing_zero_padding and data[position:] == b"\0":
                break
            raise InvalidWordDocument(
                f"{label} ends with a truncated Sprm at byte {position}"
            )
        opcode = struct.unpack_from("<H", data, position)[0]
        position += 2
        spra = opcode >> 13
        if spra == 6:
            if position >= len(data):
                raise InvalidWordDocument(
                    f"{label} Sprm 0x{opcode:04X} has no variable-length prefix"
                )
            if opcode == 0xD608:
                if position > len(data) - 2:
                    raise InvalidWordDocument(
                        f"{label} sprmTDefTable has no 16-bit length prefix"
                    )
                byte_count = struct.unpack_from("<H", data, position)[0]
                # TDefTableOperand.cb counts the remainder incremented by one;
                # including the two-byte cb itself gives cb+1 operand bytes.
                operand_length = byte_count + 1
            else:
                byte_count = data[position]
                operand_length = 1 + byte_count
            # sprmPChgTabs permits 0xFF with an implicit size. We do not yet
            # consume tab-stop operands, so retaining the remainder as one
            # opaque operand is safer than guessing boundaries.
            if opcode == 0xC615 and byte_count == 0xFF:
                modifiers.append(PropertyModifier(opcode, data[position:]))
                position = len(data)
                continue
        else:
            operand_length = _FIXED_OPERAND_LENGTHS.get(spra)
            if operand_length is None:
                raise InvalidWordDocument(
                    f"{label} Sprm 0x{opcode:04X} has invalid spra {spra}"
                )
        operand_end = position + operand_length
        if operand_end > len(data):
            raise InvalidWordDocument(
                f"{label} Sprm 0x{opcode:04X} operand exceeds grpprl"
            )
        modifiers.append(PropertyModifier(opcode, data[position:operand_end]))
        position = operand_end
    return tuple(modifiers)


_CHARACTER_TOGGLES = {
    0x0835: "bold",
    0x0836: "italic",
    0x0837: "strike",
    0x083A: "small_caps",
    0x083B: "caps",
    0x083C: "hidden",
    0x0855: "special",
    0x085C: "complex_script_bold",
    0x085D: "complex_script_italic",
    0x0868: "snap_to_grid",
    0x0875: "no_proof",
    0x2A53: "double_strike",
}

_PARAGRAPH_TOGGLES = {
    0x2431: "widow_control",
    0x2433: "kinsoku",
    0x2434: "word_wrap",
    0x2435: "overflow_punctuation",
    0x2436: "top_line_punctuation",
    0x2437: "auto_space_east_asian_latin",
    0x2438: "auto_space_east_asian_numbers",
    0x2447: "snap_to_grid",
    0x2448: "adjust_right_indent",
}

_FONT_HINTS = {
    0x00: "default",
    0x01: "eastAsia",
    0x02: "cs",
}

_LANGUAGE_ATTRIBUTES = {
    0x485F: "complex_script_language",
    0x486D: "language",
    0x486E: "east_asia_language",
    0x4873: "language",
    0x4874: "east_asia_language",
}

_NEUTRAL_LANGUAGE_TAGS = {
    0x0001: "ar",
}


def _language_tag_from_lid(lid: int) -> str | None:
    neutral_tag = _NEUTRAL_LANGUAGE_TAGS.get(lid)
    if neutral_tag is not None:
        return neutral_tag
    name = locale.windows_locale.get(lid)
    if name is None:
        return None
    if name == "zh_CHS":
        return "zh-CN"
    if name == "zh_CHT":
        return "zh-TW"
    parts = name.split("_")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        normalized.append(part.title() if len(part) == 4 else part.upper())
    return "-".join(normalized)

_UNDERLINES = {
    0x00: "none",
    0x01: "single",
    0x02: "words",
    0x03: "double",
    0x04: "dotted",
    0x06: "thick",
    0x07: "dash",
    0x09: "dotDash",
    0x0A: "dotDotDash",
    0x0B: "wave",
    0x14: "dottedHeavy",
    0x17: "dashedHeavy",
    0x19: "dashDotHeavy",
    0x1A: "dashDotDotHeavy",
    0x1B: "wavyHeavy",
    0x27: "dashLong",
    0x2B: "wavyDouble",
    0x37: "dashLongHeavy",
}

_ICO_RGB = {
    0x01: "000000",
    0x02: "0000FF",
    0x03: "00FFFF",
    0x04: "00FF00",
    0x05: "FF00FF",
    0x06: "FF0000",
    0x07: "FFFF00",
    0x08: "FFFFFF",
    0x09: "000080",
    0x0A: "008080",
    0x0B: "008000",
    0x0C: "800080",
    0x0D: "800000",
    0x0E: "808000",
    0x0F: "808080",
    0x10: "C0C0C0",
}

_ICO_HIGHLIGHT = {
    0x00: "none",
    0x01: "black",
    0x02: "blue",
    0x03: "cyan",
    0x04: "green",
    0x05: "magenta",
    0x06: "red",
    0x07: "yellow",
    0x08: "white",
    0x09: "darkBlue",
    0x0A: "darkCyan",
    0x0B: "darkGreen",
    0x0C: "darkMagenta",
    0x0D: "darkRed",
    0x0E: "darkYellow",
    0x0F: "darkGray",
    0x10: "lightGray",
}

_BORDER_STYLES = {
    0x00: "none",
    0x01: "single",
    0x03: "double",
    0x05: "single",
    0x06: "dotted",
    0x07: "dashed",
    0x08: "dotDash",
    0x09: "dotDotDash",
    0x0A: "triple",
    0x0B: "thinThickSmallGap",
    0x0C: "thickThinSmallGap",
    0x0D: "thinThickThinSmallGap",
    0x0E: "thinThickMediumGap",
    0x0F: "thickThinMediumGap",
    0x10: "thinThickThinMediumGap",
    0x11: "thinThickLargeGap",
    0x12: "thickThinLargeGap",
    0x13: "thinThickThinLargeGap",
    0x14: "wave",
    0x15: "doubleWave",
    0x16: "dashSmallGap",
    0x17: "dashDotStroked",
    0x18: "threeDEmboss",
    0x19: "threeDEngrave",
    0x1A: "outset",
    0x1B: "inset",
}

_SHADING_PATTERNS = {
    0x00: "clear",
    0x01: "solid",
    0x02: "pct5",
    0x03: "pct10",
    0x04: "pct20",
    0x05: "pct25",
    0x06: "pct30",
    0x07: "pct40",
    0x08: "pct50",
    0x09: "pct60",
    0x0A: "pct70",
    0x0B: "pct75",
    0x0C: "pct80",
    0x0D: "pct90",
    0x0E: "horzStripe",
    0x0F: "vertStripe",
    0x10: "reverseDiagStripe",
    0x11: "diagStripe",
    0x12: "horzCross",
    0x13: "diagCross",
    0x14: "thinHorzStripe",
    0x15: "thinVertStripe",
    0x16: "thinReverseDiagStripe",
    0x17: "thinDiagStripe",
    0x18: "thinHorzCross",
    0x19: "thinDiagCross",
    0x25: "pct12",
    0x26: "pct15",
    0x2B: "pct35",
    0x2E: "pct45",
    0x31: "pct55",
    0x33: "pct62",
    0x34: "pct65",
    0x39: "pct85",
    0x3C: "pct95",
}

_CELL_MARGIN_SIDES = (
    (0x01, "top"),
    (0x02, "left"),
    (0x04, "bottom"),
    (0x08, "right"),
)


def _parse_brc80(data: bytes) -> BorderProperties | None:
    if len(data) != 4:
        raise InvalidWordDocument("Brc80 must contain exactly four bytes")
    if data == b"\xFF\xFF\xFF\xFF" or data[1] in (0x00, 0xFF):
        return None
    style = _BORDER_STYLES.get(data[1])
    if style is None:
        return None
    color = "auto" if data[2] == 0 else _ICO_RGB.get(data[2], "auto")
    return BorderProperties(
        style=style,
        size_eighth_points=max(data[0], 2),
        color=color,
        space_points=data[3] & 0x1F,
        shadow=bool(data[3] & 0x20),
        frame=bool(data[3] & 0x40),
    )


def _parse_colorref(data: bytes) -> str | None:
    if len(data) != 4:
        raise InvalidWordDocument("COLORREF must contain exactly four bytes")
    if data == b"\xFF\xFF\xFF\xFF":
        return None
    if data[3] == 0xFF:
        return "auto"
    return f"{data[0]:02X}{data[1]:02X}{data[2]:02X}"


def _parse_brc(data: bytes) -> BorderProperties | None:
    if len(data) != 8:
        raise InvalidWordDocument("Brc must contain exactly eight bytes")
    if data[4:] == b"\xFF\xFF\xFF\xFF" or data[5] in (0x00, 0xFF):
        return None
    style = _BORDER_STYLES.get(data[5])
    if style is None:
        return None
    flags = struct.unpack_from("<H", data, 6)[0]
    color = _parse_colorref(data[:4])
    return BorderProperties(
        style=style,
        size_eighth_points=max(data[4], 2),
        color=color or "auto",
        space_points=flags & 0x1F,
        shadow=bool(flags & 0x20),
        frame=bool(flags & 0x40),
    )


def _parse_brc_operand(operand: bytes) -> BorderProperties | None:
    if len(operand) != 9 or operand[0] != 8:
        raise InvalidWordDocument("BrcOperand must contain exactly eight data bytes")
    return _parse_brc(operand[1:])


def _parse_table_borders80(operand: bytes) -> TableBorders:
    if len(operand) != 25 or operand[0] != 0x18:
        raise InvalidWordDocument("sprmTTableBorders80 operand must contain 24 bytes")
    values = [
        _parse_brc80(operand[1 + index * 4 : 5 + index * 4])
        for index in range(6)
    ]
    return TableBorders(*values)


def _parse_table_borders(operand: bytes) -> TableBorders:
    if len(operand) != 49 or operand[0] != 0x30:
        raise InvalidWordDocument("TableBordersOperand must contain 48 data bytes")
    values = [
        _parse_brc(operand[1 + index * 8 : 9 + index * 8])
        for index in range(6)
    ]
    return TableBorders(*values)


def _parse_border_colors(operand: bytes) -> tuple[str | None, ...]:
    if not operand or operand[0] != len(operand) - 1 or operand[0] % 4:
        raise InvalidWordDocument("BrcCvOperand has an invalid byte count")
    if operand[0] > 252:
        raise InvalidWordDocument("BrcCvOperand has too many colors")
    return tuple(
        _parse_colorref(operand[position : position + 4])
        for position in range(1, len(operand), 4)
    )


_WIDTH_TYPES = {
    0: "nil",
    1: "auto",
    2: "pct",
    3: "dxa",
}


_TAB_ALIGNMENTS = {
    0: "left",
    1: "center",
    2: "right",
    3: "decimal",
    4: "bar",
    6: "num",
}

_TAB_LEADERS = {
    0: None,
    1: "dot",
    2: "hyphen",
    3: "underscore",
    4: "heavy",
    5: "middleDot",
    7: None,
}


def _parse_tab_changes(operand: bytes) -> tuple[TabStop, ...]:
    if not operand or operand[0] != len(operand) - 1 or operand[0] < 2:
        raise InvalidWordDocument("PChgTabsPapxOperand has an invalid byte count")
    position = 1
    delete_count = operand[position]
    position += 1
    if delete_count > 64 or position + delete_count * 2 > len(operand):
        raise InvalidWordDocument("PChgTabsDel exceeds its operand")
    deleted = struct.unpack_from(f"<{delete_count}h", operand, position)
    position += delete_count * 2
    if tuple(sorted(deleted)) != deleted:
        raise InvalidWordDocument("deleted tab stops are not in ascending order")
    if position >= len(operand):
        raise InvalidWordDocument("PChgTabsPapxOperand has no PChgTabsAdd")
    add_count = operand[position]
    position += 1
    required = position + add_count * 3
    if add_count > 64 or required != len(operand):
        raise InvalidWordDocument("PChgTabsAdd does not match its operand")
    added = struct.unpack_from(f"<{add_count}h", operand, position)
    position += add_count * 2
    if tuple(sorted(added)) != added:
        raise InvalidWordDocument("added tab stops are not in ascending order")
    values = [TabStop(value, "clear") for value in deleted]
    for tab_position, descriptor in zip(added, operand[position:]):
        alignment = _TAB_ALIGNMENTS.get(descriptor & 0x07)
        leader = _TAB_LEADERS.get((descriptor >> 3) & 0x07)
        if alignment is None or ((descriptor >> 3) & 0x07) not in _TAB_LEADERS:
            raise InvalidWordDocument("custom tab stop has an invalid descriptor")
        values.append(TabStop(tab_position, alignment, leader))
    return tuple(values)


def _parse_table_width(operand: bytes) -> tuple[str, int]:
    if len(operand) != 3:
        raise InvalidWordDocument("FtsWWidth_Table must contain exactly three bytes")
    width_type_value, width = struct.unpack("<BH", operand)
    width_type = _WIDTH_TYPES.get(width_type_value)
    if width_type is None:
        raise InvalidWordDocument("FtsWWidth_Table has an invalid width type")
    if width_type in ("nil", "auto") and width:
        raise InvalidWordDocument("automatic table widths must have a zero value")
    if width_type == "pct" and width > 30000:
        raise InvalidWordDocument("percentage table width exceeds 600 percent")
    if width_type == "dxa" and width > 31680:
        raise InvalidWordDocument("table width exceeds 22 inches")
    return width_type, width


def _parse_table_part_width(operand: bytes) -> tuple[str, int]:
    if len(operand) != 3:
        raise InvalidWordDocument("FtsWWidth_TablePart must contain three bytes")
    width_type_value, width = struct.unpack("<BH", operand)
    width_type = _WIDTH_TYPES.get(width_type_value)
    if width_type is None:
        raise InvalidWordDocument("FtsWWidth_TablePart has an invalid width type")
    if width_type == "nil":
        return width_type, 0
    if width_type == "auto" and width:
        raise InvalidWordDocument("automatic table-part widths must be zero")
    if width_type == "pct" and width > 5000:
        raise InvalidWordDocument("table-part width exceeds 100 percent")
    if width_type == "dxa" and width > 31680:
        raise InvalidWordDocument("table-part width exceeds 22 inches")
    return width_type, width


def _parse_cell_width(operand: bytes) -> TableCellWidthOverride | None:
    if len(operand) != 6 or operand[0] != 5:
        raise InvalidWordDocument("TableCellWidthOperand must contain five data bytes")
    first_cell, limit_cell, width_type, width = struct.unpack_from(
        "<BBBH",
        operand,
        1,
    )
    if first_cell >= limit_cell or limit_cell > 63:
        raise InvalidWordDocument("TableCellWidthOperand has an invalid cell range")
    if width_type != 3:
        return None
    if width > 31680:
        raise InvalidWordDocument("preferred cell width exceeds 22 inches")
    return TableCellWidthOverride(first_cell, limit_cell, width)


def _parse_cssa(
    operand: bytes,
) -> tuple[int, int, tuple[str, ...], int | None]:
    if len(operand) != 7 or operand[0] != 6:
        raise InvalidWordDocument("CSSAOperand must contain exactly six data bytes")
    first_cell, limit_cell, side_flags, width_type, width = struct.unpack_from(
        "<BBBBH",
        operand,
        1,
    )
    if first_cell > limit_cell or limit_cell > 63:
        raise InvalidWordDocument("CSSAOperand contains an invalid cell range")
    if not side_flags or side_flags & ~0x0F:
        raise InvalidWordDocument("CSSAOperand contains invalid cell sides")
    if width_type not in (0, 3):
        raise InvalidWordDocument("CSSAOperand contains an unsupported width type")
    if width_type == 0 and width:
        raise InvalidWordDocument("CSSAOperand ftsNil width must be zero")
    if width > 31680:
        raise InvalidWordDocument("CSSAOperand cell margin exceeds 22 inches")
    sides = tuple(name for mask, name in _CELL_MARGIN_SIDES if side_flags & mask)
    return first_cell, limit_cell, sides, width if width_type == 3 else None


def _parse_shd80(data: bytes) -> tuple[ShadingProperties | None, bool]:
    if len(data) != 2:
        raise InvalidWordDocument("Shd80 must contain exactly two bytes")
    value = struct.unpack("<H", data)[0]
    if value in (0x0000, 0xFFFF):
        return None, False
    foreground_index = value & 0x1F
    background_index = (value >> 5) & 0x1F
    pattern_index = (value >> 10) & 0x3F
    pattern = _SHADING_PATTERNS.get(pattern_index)
    unsupported = pattern is None
    if pattern is None:
        pattern = "clear"
    foreground = (
        "auto" if foreground_index == 0 else _ICO_RGB.get(foreground_index, "auto")
    )
    background = (
        "auto" if background_index == 0 else _ICO_RGB.get(background_index, "auto")
    )
    unsupported = unsupported or foreground_index > 0x10 or background_index > 0x10
    return ShadingProperties(pattern, foreground, background), unsupported


def _parse_def_table_shd80(
    operand: bytes,
) -> tuple[tuple[ShadingProperties | None, ...], bool]:
    if not operand or operand[0] != len(operand) - 1 or operand[0] % 2:
        raise InvalidWordDocument("DefTableShd80Operand has an invalid byte count")
    if operand[0] > 126:
        raise InvalidWordDocument("DefTableShd80Operand has too many cells")
    values: list[ShadingProperties | None] = []
    unsupported = False
    for position in range(1, len(operand), 2):
        shading, approximated = _parse_shd80(operand[position : position + 2])
        values.append(shading)
        unsupported = unsupported or approximated
    return tuple(values), unsupported


def _parse_tdef_table(operand: bytes) -> TableRowProperties:
    if len(operand) < 3:
        raise InvalidWordDocument("sprmTDefTable operand is truncated")
    byte_count = struct.unpack_from("<H", operand)[0]
    if len(operand) != byte_count + 1:
        raise InvalidWordDocument(
            f"sprmTDefTable cb {byte_count} does not match {len(operand)} bytes"
        )
    column_count = operand[2]
    if column_count > 63:
        raise InvalidWordDocument(
            f"sprmTDefTable has invalid column count {column_count}"
        )
    boundaries_end = 3 + 2 * (column_count + 1)
    if boundaries_end > len(operand):
        raise InvalidWordDocument("sprmTDefTable column boundaries are truncated")
    boundaries = struct.unpack_from(f"<{column_count + 1}h", operand, 3)
    if any(current < previous for previous, current in zip(boundaries, boundaries[1:])):
        raise InvalidWordDocument("sprmTDefTable column boundaries are decreasing")

    descriptor_data = operand[boundaries_end:]
    if len(descriptor_data) % 20:
        raise InvalidWordDocument("sprmTDefTable TC80 array is truncated")
    descriptor_count = min(len(descriptor_data) // 20, column_count)
    definitions: list[TableCellDefinition] = []
    for index in range(descriptor_count):
        start = index * 20
        tcgrf, preferred_width = struct.unpack_from("<HH", descriptor_data, start)
        horizontal_value = tcgrf & 0x03
        vertical_value = (tcgrf >> 5) & 0x03
        alignment_value = (tcgrf >> 7) & 0x03
        width_type = (tcgrf >> 9) & 0x07
        definitions.append(
            TableCellDefinition(
                preferred_width_twips=(
                    preferred_width if width_type == 3 else None
                ),
                horizontal_merge=(
                    "continue"
                    if horizontal_value == 1
                    else "restart" if horizontal_value in (2, 3) else None
                ),
                vertical_merge={1: "continue", 3: "restart"}.get(vertical_value),
                vertical_alignment={1: "center", 2: "bottom"}.get(
                    alignment_value
                ),
                fit_text=True if tcgrf & 0x1000 else None,
                no_wrap=True if tcgrf & 0x2000 else None,
                borders=TableBorders(
                    top=_parse_brc80(descriptor_data[start + 4 : start + 8]),
                    left=_parse_brc80(descriptor_data[start + 8 : start + 12]),
                    bottom=_parse_brc80(descriptor_data[start + 12 : start + 16]),
                    right=_parse_brc80(descriptor_data[start + 16 : start + 20]),
                ),
            )
        )
    definitions.extend(
        TableCellDefinition() for _ in range(column_count - len(definitions))
    )
    return TableRowProperties(
        cell_boundaries_twips=tuple(boundaries),
        cell_definitions=tuple(definitions),
    )


def apply_character_modifiers(
    modifiers: tuple[PropertyModifier, ...],
    *,
    initial_properties: CharacterProperties | None = None,
    base_properties: CharacterProperties | None = None,
    font_names: dict[int, str] | None = None,
    style_properties_at: Callable[[int], CharacterProperties] | None = None,
) -> tuple[CharacterProperties, set[int], int]:
    properties = initial_properties or CharacterProperties()
    paragraph_style_properties = base_properties or CharacterProperties()
    style_baseline = paragraph_style_properties
    font_names = font_names or {}
    unsupported: set[int] = set()
    style_relative_toggle_count = 0
    for modifier in modifiers:
        opcode = modifier.opcode
        operand = modifier.operand
        if opcode == 0x2A33:  # sprmCPlain
            # sprmCPlain resets ordinary direct formatting but MS-DOC
            # explicitly preserves the special-character state.
            properties = CharacterProperties(special=properties.special)
            style_baseline = paragraph_style_properties
        elif opcode == 0x4A30:  # sprmCIstd
            style_id = struct.unpack("<H", operand)[0]
            # sprmCIstd likewise preserves sprmCFSpec across the style reset.
            properties = CharacterProperties(
                style_id=style_id,
                special=properties.special,
            )
            style_baseline = paragraph_style_properties
            if style_properties_at is not None:
                style_baseline = merge_character_properties(
                    paragraph_style_properties,
                    style_properties_at(style_id),
                )
        elif opcode in _CHARACTER_TOGGLES:
            value = operand[0]
            if value in (0x00, 0x01):
                properties = replace(
                    properties,
                    **{_CHARACTER_TOGGLES[opcode]: bool(value)},
                )
            elif value in (0x80, 0x81):
                style_relative_toggle_count += 1
                attribute = _CHARACTER_TOGGLES[opcode]
                style_value = bool(getattr(style_baseline, attribute))
                properties = replace(
                    properties,
                    **{attribute: style_value if value == 0x80 else not style_value},
                )
            else:
                unsupported.add(opcode)
        elif opcode in (0x4A4F, 0x4A50, 0x4A51, 0x4A5E):
            font_index = struct.unpack("<H", operand)[0]
            font_name = font_names.get(font_index)
            if font_name is None:
                unsupported.add(opcode)
                continue
            attribute = {
                0x4A4F: "ascii_font",
                0x4A50: "east_asia_font",
                0x4A51: "high_ansi_font",
                0x4A5E: "complex_script_font",
            }[opcode]
            properties = replace(properties, **{attribute: font_name})
        elif opcode == 0x6A09:  # sprmCSymbol
            font_index, character_code = struct.unpack("<HH", operand)
            font_name = font_names.get(font_index)
            if font_name is None:
                unsupported.add(opcode)
            else:
                properties = replace(
                    properties,
                    symbol_font=font_name,
                    symbol_character_code=character_code,
                )
        elif opcode == 0x2A3E:
            underline = _UNDERLINES.get(operand[0])
            if underline is None:
                unsupported.add(opcode)
            else:
                properties = replace(properties, underline=underline)
        elif opcode == 0x2A42:
            if operand[0] == 0:
                properties = replace(properties, color="auto")
            elif operand[0] in _ICO_RGB:
                properties = replace(properties, color=_ICO_RGB[operand[0]])
            else:
                unsupported.add(opcode)
        elif opcode == 0x2A0C:
            highlight = _ICO_HIGHLIGHT.get(operand[0])
            if highlight is None:
                unsupported.add(opcode)
            else:
                properties = replace(properties, highlight=highlight)
        elif opcode == 0x4A43:
            size = struct.unpack("<H", operand)[0]
            if 2 <= size <= 3276:
                properties = replace(properties, size_half_points=size)
            else:
                unsupported.add(opcode)
        elif opcode == 0x4A61:  # sprmCHpsBi
            size = struct.unpack("<H", operand)[0]
            if size <= 3276:
                properties = replace(
                    properties,
                    complex_script_size_half_points=size,
                )
            else:
                unsupported.add(opcode)
        elif opcode == 0x484B:  # sprmCHpsKern
            threshold = struct.unpack("<h", operand)[0]
            if 0 <= threshold <= 3276:
                properties = replace(
                    properties,
                    kerning_half_points=threshold,
                )
            else:
                unsupported.add(opcode)
        elif opcode == 0x4845:
            position = struct.unpack("<h", operand)[0]
            properties = replace(properties, position_half_points=position)
        elif opcode == 0x2A48:
            vertical_align = {0: "baseline", 1: "superscript", 2: "subscript"}.get(
                operand[0]
            )
            if vertical_align is None:
                unsupported.add(opcode)
            else:
                properties = replace(properties, vertical_align=vertical_align)
        elif opcode == 0x286F:  # sprmCIdctHint
            if operand[0] == 0xFF:
                properties = replace(properties, font_hint=None)
                continue
            hint = _FONT_HINTS.get(operand[0])
            if hint is None:
                unsupported.add(opcode)
            else:
                properties = replace(properties, font_hint=hint)
        elif opcode in _LANGUAGE_ATTRIBUTES:
            lid = struct.unpack("<H", operand)[0]
            # MS-DOC uses the otherwise special LID 0x0400 to mean that
            # proofing is disabled for this text, rather than to name a
            # concrete language that can be written to w:lang.
            if lid == 0x0400:
                properties = replace(properties, no_proof=True)
                continue
            language = _language_tag_from_lid(lid)
            if language is None:
                unsupported.add(opcode)
            else:
                properties = replace(
                    properties,
                    **{_LANGUAGE_ATTRIBUTES[opcode]: language},
                )
        elif opcode == 0x6870:
            if operand[3] == 0xFF:
                properties = replace(properties, color="auto")
            else:
                properties = replace(
                    properties,
                    color=f"{operand[0]:02X}{operand[1]:02X}{operand[2]:02X}",
                )
        else:
            unsupported.add(opcode)
    return properties, unsupported, style_relative_toggle_count


_JUSTIFICATION = {
    0: "left",
    1: "center",
    2: "right",
    3: "both",
    4: "distribute",
    5: "mediumKashida",
    7: "highKashida",
    8: "lowKashida",
    9: "thaiDistribute",
}


def apply_paragraph_modifiers(
    modifiers: tuple[PropertyModifier, ...],
    *,
    style_id: int | None,
    initial_properties: ParagraphProperties | None = None,
) -> tuple[ParagraphProperties, set[int]]:
    properties = initial_properties or ParagraphProperties(style_id=style_id)
    unsupported: set[int] = set()
    for modifier in modifiers:
        opcode = modifier.opcode
        operand = modifier.operand
        if opcode == 0x4600:
            properties = replace(
                properties,
                style_id=struct.unpack("<H", operand)[0],
            )
        elif opcode == 0x2416:
            properties = replace(properties, in_table=bool(operand[0]))
        elif opcode == 0x2417:
            properties = replace(properties, table_terminating=bool(operand[0]))
        elif opcode == 0x6649:
            depth = struct.unpack("<i", operand)[0]
            if depth < 0:
                unsupported.add(opcode)
            else:
                properties = replace(properties, table_depth=depth)
        elif opcode == 0x664A:
            delta = struct.unpack("<i", operand)[0]
            depth = properties.effective_table_depth + delta
            if depth < 0:
                unsupported.add(opcode)
            else:
                properties = replace(properties, table_depth=depth)
        elif opcode == 0x244B:
            properties = replace(properties, inner_table_cell=bool(operand[0]))
        elif opcode == 0x244C:
            properties = replace(properties, inner_table_row=bool(operand[0]))
        elif opcode == 0x563A:  # sprmTIstd
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    table_style_id=struct.unpack("<H", operand)[0],
                ),
            )
        elif opcode in (0x5400, 0x548A):
            alignment = {0: "left", 1: "center", 2: "right"}.get(
                struct.unpack("<H", operand)[0]
            )
            if alignment is None:
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                properties = replace(
                    properties,
                    table_row=replace(row, alignment=alignment),
                )
        elif opcode == 0x9601:
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    left_indent_twips=struct.unpack("<h", operand)[0],
                ),
            )
        elif opcode == 0x9602:
            gap = struct.unpack("<h", operand)[0]
            if gap < 0:
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                properties = replace(
                    properties,
                    table_row=replace(row, gap_half_twips=gap),
                )
        elif opcode in (0x3403, 0x3466):
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, cant_split=bool(operand[0])),
            )
        elif opcode == 0x3404:
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, is_header=bool(operand[0])),
            )
        elif opcode == 0x9407:
            height = struct.unpack("<h", operand)[0]
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    height_twips=abs(height) if height else None,
                    height_rule="exact" if height < 0 else "atLeast",
                ),
            )
        elif opcode == 0xD605:
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, borders=_parse_table_borders80(operand)),
            )
        elif opcode == 0xD613:
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, borders=_parse_table_borders(operand)),
            )
        elif opcode == 0xF614:
            width_type, width = _parse_table_width(operand)
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    preferred_width=width,
                    preferred_width_type=width_type,
                ),
            )
        elif opcode in (0xF617, 0xF618):
            # Zero leading/trailing width is the default and has no OOXML
            # effect. A nonzero value also requires gridBefore/gridAfter
            # reconstruction, which is intentionally left diagnostic for now.
            _, width = _parse_table_part_width(operand)
            if width:
                unsupported.add(opcode)
        elif opcode == 0xD608:
            definition = _parse_tdef_table(operand)
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    cell_boundaries_twips=definition.cell_boundaries_twips,
                    cell_definitions=definition.cell_definitions,
                ),
            )
        elif opcode == 0xD609:
            shadings, approximated = _parse_def_table_shd80(operand)
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, cell_shadings=shadings),
            )
            if approximated:
                unsupported.add(opcode)
        elif opcode in (0xD632, 0xD634):
            first_cell, limit_cell, sides, width = _parse_cssa(operand)
            row = properties.table_row or TableRowProperties()
            if opcode == 0xD634:
                if (first_cell, limit_cell) != (0, 1):
                    unsupported.add(opcode)
                else:
                    margins = replace(
                        row.default_cell_margins,
                        **{side: width for side in sides},
                    )
                    properties = replace(
                        properties,
                        table_row=replace(row, default_cell_margins=margins),
                    )
            else:
                override = TableCellMarginOverride(
                    first_cell,
                    limit_cell,
                    sides,
                    width,
                )
                properties = replace(
                    properties,
                    table_row=replace(
                        row,
                        cell_margin_overrides=(
                            *row.cell_margin_overrides,
                            override,
                        ),
                    ),
                )
        elif opcode == 0xD635:
            override = _parse_cell_width(operand)
            if override is None:
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                properties = replace(
                    properties,
                    table_row=replace(
                        row,
                        cell_width_overrides=(
                            *row.cell_width_overrides,
                            override,
                        ),
                    ),
                )
        elif opcode in (0xD61A, 0xD61B, 0xD61C, 0xD61D):
            row = properties.table_row or TableRowProperties()
            attribute = {
                0xD61A: "cell_top_border_colors",
                0xD61B: "cell_left_border_colors",
                0xD61C: "cell_bottom_border_colors",
                0xD61D: "cell_right_border_colors",
            }[opcode]
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    **{attribute: _parse_border_colors(operand)},
                ),
            )
        elif opcode in (0x2403, 0x2461):
            justification = _JUSTIFICATION.get(operand[0])
            if justification is None:
                unsupported.add(opcode)
            else:
                properties = replace(properties, justification=justification)
        elif opcode == 0x2405:
            properties = replace(properties, keep_lines=bool(operand[0]))
        elif opcode == 0x2406:
            properties = replace(properties, keep_next=bool(operand[0]))
        elif opcode == 0x2407:
            properties = replace(properties, page_break_before=bool(operand[0]))
        elif opcode == 0x2640:
            if operand[0] > 9:
                unsupported.add(opcode)
            else:
                properties = replace(properties, outline_level=operand[0])
        elif opcode == 0xC60D:
            properties = replace(
                properties,
                tab_stops=(
                    *(properties.tab_stops or ()),
                    *_parse_tab_changes(operand),
                ),
            )
        elif opcode in _PARAGRAPH_TOGGLES:
            if operand[0] not in (0x00, 0x01):
                unsupported.add(opcode)
            else:
                properties = replace(
                    properties,
                    **{_PARAGRAPH_TOGGLES[opcode]: bool(operand[0])},
                )
        elif opcode in (0x840F, 0x845E):
            properties = replace(
                properties,
                left_indent_twips=struct.unpack("<h", operand)[0],
            )
        elif opcode in (0x840E, 0x845D):
            properties = replace(
                properties,
                right_indent_twips=struct.unpack("<h", operand)[0],
            )
        elif opcode in (0x8411, 0x8460):
            properties = replace(
                properties,
                first_line_indent_twips=struct.unpack("<h", operand)[0],
            )
        elif opcode == 0xA413:
            properties = replace(
                properties,
                space_before_twips=struct.unpack("<H", operand)[0],
            )
        elif opcode == 0xA414:
            properties = replace(
                properties,
                space_after_twips=struct.unpack("<H", operand)[0],
            )
        elif opcode in (0x4458, 0x4459):  # sprmPDylBefore / sprmPDylAfter
            line_hundredths = struct.unpack("<h", operand)[0]
            if not -20 <= line_hundredths <= 31680:
                unsupported.add(opcode)
            else:
                attribute = (
                    "space_before_lines" if opcode == 0x4458 else "space_after_lines"
                )
                properties = replace(
                    properties,
                    **{attribute: line_hundredths},
                )
        elif opcode == 0x6412:
            raw_line, multiple = struct.unpack("<HH", operand)
            signed_line = struct.unpack("<h", operand[:2])[0]
            if multiple == 1 and signed_line >= 0:
                properties = replace(
                    properties,
                    line_spacing_twips=raw_line,
                    line_rule="auto",
                )
            elif multiple == 0 and signed_line < 0:
                properties = replace(
                    properties,
                    line_spacing_twips=-signed_line,
                    line_rule="exact",
                )
            elif multiple == 0:
                properties = replace(
                    properties,
                    line_spacing_twips=raw_line,
                    line_rule="atLeast",
                )
            else:
                unsupported.add(opcode)
        elif opcode in (0x6424, 0x6425, 0x6426, 0x6427):
            border = _parse_brc80(operand)
            borders = properties.borders or TableBorders()
            attribute = {
                0x6424: "top",
                0x6425: "left",
                0x6426: "bottom",
                0x6427: "right",
            }[opcode]
            properties = replace(
                properties,
                borders=replace(borders, **{attribute: border}),
            )
        elif opcode in (0xC64E, 0xC64F, 0xC650, 0xC651):
            border = _parse_brc_operand(operand)
            borders = properties.borders or TableBorders()
            attribute = {
                0xC64E: "top",
                0xC64F: "left",
                0xC650: "bottom",
                0xC651: "right",
            }[opcode]
            properties = replace(
                properties,
                borders=replace(borders, **{attribute: border}),
            )
        else:
            unsupported.add(opcode)
    return properties, unsupported


def merge_character_properties(
    base: CharacterProperties,
    overlay: CharacterProperties,
) -> CharacterProperties:
    """Overlay only explicitly specified character-property values."""

    updates = {
        field_name: getattr(overlay, field_name)
        for field_name in CharacterProperties.__dataclass_fields__
        if getattr(overlay, field_name) is not None
    }
    return replace(base, **updates) if updates else base


def merge_paragraph_properties(
    base: ParagraphProperties,
    overlay: ParagraphProperties,
) -> ParagraphProperties:
    """Overlay only explicitly specified paragraph-property values."""

    updates = {
        field_name: getattr(overlay, field_name)
        for field_name in ParagraphProperties.__dataclass_fields__
        if getattr(overlay, field_name) is not None
    }
    return replace(base, **updates) if updates else base
