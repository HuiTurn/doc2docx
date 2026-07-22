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
    ParagraphFrameProperties,
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

_TABLE_TEXT_DIRECTIONS = {
    0: "lrTb",
    1: "tbRl",
    3: "btLr",
    4: "lrTbV",
    5: "tbRlV",
}


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
            if opcode == 0xC615 and byte_count == 0xFF:
                if position > len(data) - 2:
                    raise InvalidWordDocument(
                        f"{label} sprmPChgTabs has no PChgTabsDelClose"
                    )
                delete_count = data[position + 1]
                if delete_count > 64:
                    raise InvalidWordDocument(
                        f"{label} sprmPChgTabs has too many deleted tab stops"
                    )
                add_count_position = position + 2 + delete_count * 4
                if add_count_position >= len(data):
                    raise InvalidWordDocument(
                        f"{label} sprmPChgTabs deletion data is truncated"
                    )
                add_count = data[add_count_position]
                if add_count > 64:
                    raise InvalidWordDocument(
                        f"{label} sprmPChgTabs has too many added tab stops"
                    )
                operand_length = 3 + delete_count * 4 + add_count * 3
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
    0x0838: "outline",
    0x0839: "shadow",
    0x083A: "small_caps",
    0x083B: "caps",
    0x083C: "hidden",
    0x0811: "web_hidden",
    0x0818: "special_vanish",
    0x085A: "bidirectional",
    0x0882: "complex_script",
    0x0854: "imprint",
    0x0855: "special",
    0x0858: "emboss",
    0x085C: "complex_script_bold",
    0x085D: "complex_script_italic",
    0x0868: "snap_to_grid",
    0x0875: "no_proof",
    0x2A53: "double_strike",
}

_PARAGRAPH_TOGGLES = {
    0x240C: "suppress_line_numbers",
    0x242A: "suppress_auto_hyphens",
    0x2431: "widow_control",
    0x2433: "kinsoku",
    0x2434: "word_wrap",
    0x2435: "overflow_punctuation",
    0x2436: "top_line_punctuation",
    0x2437: "auto_space_east_asian_latin",
    0x2438: "auto_space_east_asian_numbers",
    0x2441: "bidirectional",
    0x2447: "snap_to_grid",
    0x2448: "adjust_right_indent",
    0x245B: "auto_spacing_before",
    0x245C: "auto_spacing_after",
    0x246D: "contextual_spacing",
}

_FRAME_HORIZONTAL_ANCHORS = {
    0x00: "text",
    0x01: "margin",
    0x02: "page",
    0x03: None,
}

_FRAME_VERTICAL_ANCHORS = {
    0x00: "margin",
    0x01: "page",
    0x02: "text",
    0x03: None,
}

_FRAME_WRAPS = {
    0x00: "auto",
    0x01: "notBeside",
    0x02: "around",
    0x03: "none",
    0x04: "tight",
    0x05: "through",
}

_FRAME_HORIZONTAL_ALIGNMENTS = {
    0x0000: "left",
    0xFFFC: "center",
    0xFFF8: "right",
    0xFFF4: "inside",
    0xFFF0: "outside",
}

_FRAME_VERTICAL_ALIGNMENTS = {
    0x0000: "inline",
    0xFFFC: "top",
    0xFFF8: "center",
    0xFFF4: "bottom",
    0xFFF0: "inside",
    0xFFEC: "outside",
}

_FONT_HINTS = {
    0x00: "default",
    0x01: "eastAsia",
    0x02: "cs",
}

_EMPHASIS_MARKS = {
    0x00: "none",
    0x01: "dot",
    0x02: "comma",
    0x03: "circle",
    0x04: "underDot",
}

_TEXT_EFFECTS = {
    0x00: None,
    0x01: "lights",
    0x02: "blinkBackground",
    0x03: "sparkle",
    0x04: "antsBlack",
    0x05: "antsRed",
    0x06: "shimmer",
}

_LINE_BREAK_CLEARS = {
    0x00: "none",
    0x01: "left",
    0x02: "right",
    0x03: "all",
}

_COMBINE_BRACKETS = {
    0: "none",
    1: "round",
    2: "square",
    3: "angle",
    4: "curly",
}

_PARAGRAPH_TEXT_ALIGNMENTS = {
    0: "top",
    1: "center",
    2: "baseline",
    3: "bottom",
    4: "auto",
}

_TEXTBOX_TIGHT_WRAPS = {
    0: "none",
    1: "allLines",
    2: "firstAndLastLine",
    3: "firstLineOnly",
    4: "lastLineOnly",
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
    if lid == 0x00FF:
        # 0x00FF is not assigned by MS-LCID, but has been observed in Word 97
        # files where consumers treat it as an undefined proofing language.
        return "zxx"
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


def unassigned_language_lids(
    modifiers: tuple[PropertyModifier, ...],
) -> set[int]:
    """Return observed unassigned LIDs that receive a bounded repair."""

    return {
        struct.unpack("<H", modifier.operand)[0]
        for modifier in modifiers
        if modifier.opcode in _LANGUAGE_ATTRIBUTES
        and struct.unpack("<H", modifier.operand)[0] == 0x00FF
    }

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


def parse_brc80(data: bytes) -> BorderProperties | None:
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


def parse_brc_operand(operand: bytes) -> BorderProperties | None:
    if len(operand) != 9 or operand[0] != 8:
        raise InvalidWordDocument("BrcOperand must contain exactly eight data bytes")
    return _parse_brc(operand[1:])


def _parse_table_borders80(operand: bytes) -> TableBorders:
    if len(operand) != 25 or operand[0] != 0x18:
        raise InvalidWordDocument("sprmTTableBorders80 operand must contain 24 bytes")
    values = [
        parse_brc80(operand[1 + index * 4 : 5 + index * 4])
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


def _parse_tab_changes(
    operand: bytes,
    *,
    deletion_ranges: bool,
) -> tuple[TabStop, ...]:
    if (
        not operand
        or operand[0] not in (len(operand) - 1, 0xFF)
        or operand[0] < 2
    ):
        raise InvalidWordDocument("PChgTabsOperand has an invalid byte count")
    position = 1
    delete_count = operand[position]
    position += 1
    if delete_count > 64 or position + delete_count * 2 > len(operand):
        raise InvalidWordDocument("PChgTabsDel exceeds its operand")
    deleted = struct.unpack_from(f"<{delete_count}h", operand, position)
    position += delete_count * 2
    if tuple(sorted(deleted)) != deleted:
        raise InvalidWordDocument("deleted tab stops are not in ascending order")
    if deletion_ranges:
        close_end = position + delete_count * 2
        if close_end > len(operand):
            raise InvalidWordDocument("PChgTabsDelClose ranges exceed their operand")
        close_ranges = struct.unpack_from(f"<{delete_count}H", operand, position)
        if any(value == 0 for value in close_ranges):
            raise InvalidWordDocument("PChgTabsDelClose has an invalid close range")
        position = close_end
    if position >= len(operand):
        raise InvalidWordDocument("PChgTabsOperand has no PChgTabsAdd")
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


def _parse_table_indent(operand: bytes) -> int | None:
    if len(operand) != 3:
        raise InvalidWordDocument("FtsWWidth_Indent must contain three bytes")
    width_type, width = struct.unpack("<Bh", operand)
    if width_type in (0x00, 0x01):
        if width:
            raise InvalidWordDocument("automatic table indents must be zero")
        return None
    if width_type != 0x03:
        raise InvalidWordDocument("table indent has an invalid width type")
    if not -31560 <= width <= 31680:
        raise InvalidWordDocument("table indent is outside the MS-DOC range")
    return width


def _parse_table_look(operand: bytes) -> dict[str, bool]:
    if len(operand) != 4:
        raise InvalidWordDocument("TLP must contain exactly four bytes")
    _, flags = struct.unpack("<hH", operand)
    if flags & 0xF800:
        raise InvalidWordDocument("TLP has nonzero padding bits")
    return {
        "first_row_style": bool(flags & 0x0020),
        "last_row_style": bool(flags & 0x0040),
        "first_column_style": bool(flags & 0x0080),
        "last_column_style": bool(flags & 0x0100),
        "no_row_banding": bool(flags & 0x0200),
        "no_column_banding": bool(flags & 0x0400),
    }


def _table_widths(row: TableRowProperties) -> tuple[int, list[int]]:
    boundaries = row.cell_boundaries_twips
    if not boundaries:
        return 0, []
    if len(boundaries) != len(row.cell_definitions) + 1:
        raise InvalidWordDocument(
            "table cell boundaries do not match the cell definitions"
        )
    return boundaries[0], [
        right - left for left, right in zip(boundaries, boundaries[1:])
    ]


def _replace_table_widths(
    row: TableRowProperties,
    start: int,
    widths: list[int],
    definitions: list[TableCellDefinition],
) -> TableRowProperties:
    if any(width < 0 for width in widths) or sum(widths) > 31680:
        raise InvalidWordDocument("table column widths exceed the MS-DOC range")
    boundaries = [start]
    for width in widths:
        boundaries.append(boundaries[-1] + width)
    return replace(
        row,
        cell_boundaries_twips=tuple(boundaries),
        cell_definitions=tuple(definitions),
    )


def _insert_table_cells(
    row: TableRowProperties,
    operand: bytes,
) -> TableRowProperties:
    if len(operand) != 4:
        raise InvalidWordDocument("TInsertOperand must contain exactly four bytes")
    first_cell, cell_count, width = struct.unpack("<BBH", operand)
    start, widths = _table_widths(row)
    definitions = list(row.cell_definitions)
    if not cell_count or first_cell > len(widths) or len(widths) + cell_count > 63:
        raise InvalidWordDocument("TInsertOperand has an invalid cell range")
    if width * cell_count + sum(widths) > 31680:
        raise InvalidWordDocument("TInsertOperand makes the table too wide")
    widths[first_cell:first_cell] = [width] * cell_count
    definitions[first_cell:first_cell] = [TableCellDefinition()] * cell_count
    updated = _replace_table_widths(row, start, widths, definitions)
    optional_arrays = {
        attribute: _insert_optional_cell_values(getattr(row, attribute), first_cell, cell_count)
        for attribute in (
            "cell_shadings",
            "cell_top_border_colors",
            "cell_left_border_colors",
            "cell_bottom_border_colors",
            "cell_right_border_colors",
        )
    }
    return replace(
        updated,
        **optional_arrays,
        cell_margin_overrides=_shift_cell_overrides_for_insert(
            row.cell_margin_overrides,
            first_cell,
            cell_count,
        ),
        cell_width_overrides=_shift_cell_overrides_for_insert(
            row.cell_width_overrides,
            first_cell,
            cell_count,
        ),
    )


def _insert_optional_cell_values(
    values: tuple[object | None, ...],
    first_cell: int,
    cell_count: int,
) -> tuple[object | None, ...]:
    if not values:
        return ()
    return (*values[:first_cell], *([None] * cell_count), *values[first_cell:])


def _shift_cell_overrides_for_insert(
    overrides: tuple[TableCellMarginOverride | TableCellWidthOverride, ...],
    first_cell: int,
    cell_count: int,
) -> tuple[TableCellMarginOverride | TableCellWidthOverride, ...]:
    shifted = []
    for override in overrides:
        if first_cell <= override.first_cell:
            shifted.append(
                replace(
                    override,
                    first_cell=override.first_cell + cell_count,
                    limit_cell=override.limit_cell + cell_count,
                )
            )
        elif first_cell < override.limit_cell:
            shifted.append(
                replace(override, limit_cell=override.limit_cell + cell_count)
            )
        else:
            shifted.append(override)
    return tuple(shifted)


def _delete_table_cells(
    row: TableRowProperties,
    operand: bytes,
) -> TableRowProperties:
    if len(operand) != 2:
        raise InvalidWordDocument("ItcFirstLim must contain exactly two bytes")
    first_cell, limit_cell = operand
    start, widths = _table_widths(row)
    definitions = list(row.cell_definitions)
    if (
        first_cell >= limit_cell
        or limit_cell > len(widths)
        or limit_cell - first_cell >= len(widths)
    ):
        raise InvalidWordDocument("sprmTDelete has an invalid cell range")
    del widths[first_cell:limit_cell]
    del definitions[first_cell:limit_cell]
    updated = _replace_table_widths(row, start, widths, definitions)
    optional_arrays = {
        attribute: _delete_optional_cell_values(
            getattr(row, attribute), first_cell, limit_cell
        )
        for attribute in (
            "cell_shadings",
            "cell_top_border_colors",
            "cell_left_border_colors",
            "cell_bottom_border_colors",
            "cell_right_border_colors",
        )
    }
    return replace(
        updated,
        **optional_arrays,
        cell_margin_overrides=_shift_cell_overrides_for_delete(
            row.cell_margin_overrides,
            first_cell,
            limit_cell,
        ),
        cell_width_overrides=_shift_cell_overrides_for_delete(
            row.cell_width_overrides,
            first_cell,
            limit_cell,
        ),
    )


def _delete_optional_cell_values(
    values: tuple[object | None, ...],
    first_cell: int,
    limit_cell: int,
) -> tuple[object | None, ...]:
    if not values:
        return ()
    return (*values[:first_cell], *values[limit_cell:])


def _shift_cell_overrides_for_delete(
    overrides: tuple[TableCellMarginOverride | TableCellWidthOverride, ...],
    first_cell: int,
    limit_cell: int,
) -> tuple[TableCellMarginOverride | TableCellWidthOverride, ...]:
    deleted_count = limit_cell - first_cell

    def shifted_index(index: int) -> int:
        if index <= first_cell:
            return index
        if index >= limit_cell:
            return index - deleted_count
        return first_cell

    shifted = []
    for override in overrides:
        new_first = shifted_index(override.first_cell)
        new_limit = shifted_index(override.limit_cell)
        if new_first < new_limit:
            shifted.append(
                replace(
                    override,
                    first_cell=new_first,
                    limit_cell=new_limit,
                )
            )
    return tuple(shifted)


def _replace_cell_definition_range(
    row: TableRowProperties,
    first_cell: int,
    limit_cell: int,
    **changes: object,
) -> TableRowProperties:
    definitions = list(row.cell_definitions)
    if first_cell >= limit_cell or limit_cell > len(definitions):
        raise InvalidWordDocument("table property has an invalid cell range")
    for index in range(first_cell, limit_cell):
        definitions[index] = replace(definitions[index], **changes)
    return replace(row, cell_definitions=tuple(definitions))


def _merge_table_cells(
    row: TableRowProperties,
    operand: bytes,
    *,
    merge: bool,
) -> TableRowProperties:
    if len(operand) != 2:
        raise InvalidWordDocument("ItcFirstLim must contain exactly two bytes")
    first_cell, limit_cell = operand
    if not merge:
        return _replace_cell_definition_range(
            row,
            first_cell,
            limit_cell,
            horizontal_merge=None,
        )
    updated = _replace_cell_definition_range(
        row,
        first_cell,
        limit_cell,
        horizontal_merge="continue",
    )
    definitions = list(updated.cell_definitions)
    definitions[first_cell] = replace(
        definitions[first_cell], horizontal_merge="restart"
    )
    return replace(updated, cell_definitions=tuple(definitions))


def _set_table_text_flow(
    row: TableRowProperties,
    operand: bytes,
) -> TableRowProperties:
    if len(operand) != 4:
        raise InvalidWordDocument(
            "CellRangeTextFlow must contain exactly four bytes"
        )
    first_cell, limit_cell, text_flow = struct.unpack("<BBH", operand)
    direction = _TABLE_TEXT_DIRECTIONS.get(text_flow)
    if direction is None:
        raise InvalidWordDocument(
            f"CellRangeTextFlow has invalid text flow {text_flow}"
        )
    return _replace_cell_definition_range(
        row,
        first_cell,
        limit_cell,
        text_direction=direction,
    )


def _set_table_vertical_merge(
    row: TableRowProperties,
    operand: bytes,
) -> TableRowProperties:
    if len(operand) != 3 or operand[0] != 2:
        raise InvalidWordDocument(
            "sprmTVertMerge must contain a two-byte operand"
        )
    cell_index, merge_value = operand[1:]
    if merge_value not in (0, 1, 3):
        raise InvalidWordDocument(
            f"sprmTVertMerge has invalid merge flag {merge_value}"
        )
    return _replace_cell_definition_range(
        row,
        cell_index,
        cell_index + 1,
        vertical_merge={1: "continue", 3: "restart"}.get(merge_value),
    )


def _set_table_vertical_alignment(
    row: TableRowProperties,
    operand: bytes,
) -> TableRowProperties:
    if len(operand) != 4 or operand[0] != 3:
        raise InvalidWordDocument(
            "sprmTVertAlign must contain a three-byte operand"
        )
    first_cell, limit_cell, alignment_value = operand[1:]
    alignment = {0: None, 1: "center", 2: "bottom"}.get(alignment_value)
    if alignment_value not in (0, 1, 2):
        raise InvalidWordDocument(
            f"sprmTVertAlign has invalid alignment {alignment_value}"
        )
    return _replace_cell_definition_range(
        row,
        first_cell,
        limit_cell,
        vertical_alignment=alignment,
    )


def _set_table_boolean_range(
    row: TableRowProperties,
    operand: bytes,
    *,
    attribute: str,
    variable_length: bool,
) -> TableRowProperties:
    expected_length = 4 if variable_length else 3
    if len(operand) != expected_length:
        raise InvalidWordDocument(
            f"table Boolean cell range must contain {expected_length} bytes"
        )
    value_offset = 1 if variable_length else 0
    if variable_length and operand[0] != 3:
        raise InvalidWordDocument(
            "table Boolean cell range has an invalid length prefix"
        )
    first_cell, limit_cell, value = operand[value_offset : value_offset + 3]
    if value not in (0, 1):
        raise InvalidWordDocument(
            f"table Boolean cell range has invalid value {value}"
        )
    return _replace_cell_definition_range(
        row,
        first_cell,
        limit_cell,
        **{attribute: bool(value)},
    )


def _set_table_cell_shading(
    row: TableRowProperties,
    operand: bytes,
    *,
    legacy: bool,
    alternating: bool,
) -> tuple[TableRowProperties, bool]:
    expected_count = 4 if legacy else 13
    expected_prefix = 12
    if len(operand) != expected_count or (
        not legacy and operand[0] != expected_prefix
    ):
        label = "TableShadeOperand" if not legacy else "legacy table shading"
        raise InvalidWordDocument(f"{label} has an invalid byte count")
    offset = 0 if legacy else 1
    first_cell, limit_cell = operand[offset : offset + 2]
    if first_cell >= limit_cell or limit_cell > len(row.cell_definitions):
        raise InvalidWordDocument("table shading has an invalid cell range")
    if legacy:
        shading, approximated = _parse_shd80(operand[offset + 2 :])
    else:
        shading, approximated = _parse_shd(operand[offset + 2 :])
    shadings = list(row.cell_shadings)
    shadings.extend([None] * (len(row.cell_definitions) - len(shadings)))
    step = 2 if alternating else 1
    for index in range(first_cell, limit_cell, step):
        shadings[index] = shading
    return replace(row, cell_shadings=tuple(shadings)), approximated


def _set_table_cell_borders(
    row: TableRowProperties,
    operand: bytes,
    *,
    legacy: bool,
) -> TableRowProperties:
    expected_count = 8 if legacy else 12
    expected_prefix = 7 if legacy else 11
    if len(operand) != expected_count or operand[0] != expected_prefix:
        label = "TableBrc80Operand" if legacy else "TableBrcOperand"
        raise InvalidWordDocument(f"{label} has an invalid byte count")
    first_cell, limit_cell, sides = operand[1:4]
    allowed_sides = 0x0F if legacy else 0x3F
    if not sides or sides & ~allowed_sides:
        raise InvalidWordDocument("table border operand has invalid border sides")
    border = parse_brc80(operand[4:]) if legacy else _parse_brc(operand[4:])
    side_names = (
        (0x01, "top"),
        (0x02, "left"),
        (0x04, "bottom"),
        (0x08, "right"),
        (0x10, "diagonal_down"),
        (0x20, "diagonal_up"),
    )
    definitions = list(row.cell_definitions)
    if first_cell >= limit_cell or limit_cell > len(definitions):
        raise InvalidWordDocument("table border operand has an invalid cell range")
    changes = {name: border for mask, name in side_names if sides & mask}
    for index in range(first_cell, limit_cell):
        definitions[index] = replace(
            definitions[index],
            borders=replace(definitions[index].borders, **changes),
        )
    return replace(row, cell_definitions=tuple(definitions))


def _set_table_column_widths(
    row: TableRowProperties,
    operand: bytes,
) -> TableRowProperties:
    if len(operand) != 4:
        raise InvalidWordDocument("TDxaColOperand must contain exactly four bytes")
    first_cell, limit_cell, width = struct.unpack("<BBH", operand)
    start, widths = _table_widths(row)
    if first_cell >= limit_cell or limit_cell > len(widths):
        raise InvalidWordDocument("TDxaColOperand has an invalid cell range")
    widths[first_cell:limit_cell] = [width] * (limit_cell - first_cell)
    return _replace_table_widths(
        row,
        start,
        widths,
        list(row.cell_definitions),
    )


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


def _parse_cell_spacing(operand: bytes) -> int:
    if len(operand) != 7 or operand[0] != 6:
        raise InvalidWordDocument("cell spacing CSSA must contain six data bytes")
    first_cell, limit_cell, side_flags, width_type, width = struct.unpack_from(
        "<BBBBH",
        operand,
        1,
    )
    if (first_cell, limit_cell, side_flags) != (0, 1, 0x0F):
        raise InvalidWordDocument("cell spacing CSSA has invalid scope or sides")
    if width_type not in (0, 3, 0x13):
        raise InvalidWordDocument("cell spacing CSSA has an invalid width type")
    if width_type == 0 and width:
        raise InvalidWordDocument("cell spacing ftsNil width must be zero")
    if width > 15840:
        raise InvalidWordDocument("cell spacing exceeds 11 inches")
    return width


def _frame_position(
    operand: bytes,
    *,
    horizontal: bool,
) -> tuple[int | None, str | None]:
    raw = struct.unpack("<H", operand)[0]
    alignments = (
        _FRAME_HORIZONTAL_ALIGNMENTS
        if horizontal
        else _FRAME_VERTICAL_ALIGNMENTS
    )
    alignment = alignments.get(raw)
    if alignment is not None:
        return None, alignment
    stored_position = struct.unpack("<h", operand)[0]
    position = stored_position - 1
    if not -31680 <= position <= 31680:
        raise InvalidWordDocument("frame position is outside the MS-DOC range")
    return position, None


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


def _parse_shd(data: bytes) -> tuple[ShadingProperties | None, bool]:
    if len(data) != 10:
        raise InvalidWordDocument("Shd must contain exactly ten bytes")
    foreground = _parse_colorref(data[:4])
    background = _parse_colorref(data[4:8])
    pattern_index = struct.unpack_from("<H", data, 8)[0]
    if pattern_index == 0xFFFF:
        return None, False
    pattern = _SHADING_PATTERNS.get(pattern_index)
    if pattern is None:
        return None, True
    if pattern_index == 0 and foreground in (None, "auto") and background in (
        None,
        "auto",
    ):
        return None, False
    return ShadingProperties(
        pattern,
        foreground or "auto",
        background or "auto",
    ), False


def _parse_def_table_shd(
    operand: bytes,
) -> tuple[tuple[ShadingProperties | None, ...], bool]:
    if not operand or operand[0] != len(operand) - 1 or operand[0] % 10:
        raise InvalidWordDocument("DefTableShdOperand has an invalid byte count")
    if operand[0] > 220:
        raise InvalidWordDocument("DefTableShdOperand has too many cells")
    values: list[ShadingProperties | None] = []
    unsupported = False
    for position in range(1, len(operand), 10):
        shading, approximated = _parse_shd(operand[position : position + 10])
        values.append(shading)
        unsupported = unsupported or approximated
    return tuple(values), unsupported


def _set_table_shading_segment(
    row: TableRowProperties,
    shadings: tuple[ShadingProperties | None, ...],
    *,
    first_cell: int,
) -> TableRowProperties:
    values = list(row.cell_shadings)
    required = first_cell + len(shadings)
    if len(values) < required:
        values.extend([None] * (required - len(values)))
    values[first_cell:required] = shadings
    return replace(row, cell_shadings=tuple(values))


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
        text_flow_value = (tcgrf >> 2) & 0x07
        vertical_value = (tcgrf >> 5) & 0x03
        alignment_value = (tcgrf >> 7) & 0x03
        width_type = (tcgrf >> 9) & 0x07
        text_direction = _TABLE_TEXT_DIRECTIONS.get(text_flow_value)
        if text_direction is None:
            raise InvalidWordDocument(
                f"sprmTDefTable has invalid text flow {text_flow_value}"
            )
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
                text_direction=text_direction,
                vertical_alignment={1: "center", 2: "bottom"}.get(
                    alignment_value
                ),
                fit_text=True if tcgrf & 0x1000 else None,
                no_wrap=True if tcgrf & 0x2000 else None,
                hide_mark=True if tcgrf & 0x4000 else None,
                borders=TableBorders(
                    top=parse_brc80(descriptor_data[start + 4 : start + 8]),
                    left=parse_brc80(descriptor_data[start + 8 : start + 12]),
                    bottom=parse_brc80(descriptor_data[start + 12 : start + 16]),
                    right=parse_brc80(descriptor_data[start + 16 : start + 20]),
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
            if operand[0] != 0:
                raise InvalidWordDocument("sprmCPlain operand must be zero")
            # sprmCPlain resets ordinary direct formatting but MS-DOC
            # explicitly preserves structural, revision, and script state.
            properties = CharacterProperties(
                bidirectional=properties.bidirectional,
                complex_script=properties.complex_script,
                web_hidden=properties.web_hidden,
                special=properties.special,
                picture_location=properties.picture_location,
                picture_is_binary=properties.picture_is_binary,
                ole_object=properties.ole_object,
                object_placeholder=properties.object_placeholder,
                font_hint=properties.font_hint,
                highlight=properties.highlight,
                revision_format_id=properties.revision_format_id,
                revision_text_id=properties.revision_text_id,
                symbol_font=properties.symbol_font,
                symbol_character_code=properties.symbol_character_code,
            )
            style_baseline = paragraph_style_properties
        elif opcode == 0x4A30:  # sprmCIstd
            style_id = struct.unpack("<H", operand)[0]
            # sprmCIstd likewise preserves sprmCFSpec across the style reset.
            properties = CharacterProperties(
                style_id=style_id,
                bidirectional=properties.bidirectional,
                complex_script=properties.complex_script,
                web_hidden=properties.web_hidden,
                special=properties.special,
                picture_location=properties.picture_location,
                picture_is_binary=properties.picture_is_binary,
                ole_object=properties.ole_object,
                object_placeholder=properties.object_placeholder,
                font_hint=properties.font_hint,
                highlight=properties.highlight,
                revision_format_id=properties.revision_format_id,
                revision_text_id=properties.revision_text_id,
                symbol_font=properties.symbol_font,
                symbol_character_code=properties.symbol_character_code,
            )
            style_baseline = paragraph_style_properties
            if style_properties_at is not None:
                style_baseline = merge_character_properties(
                    paragraph_style_properties,
                    style_properties_at(style_id),
                )
        elif opcode == 0x0802:  # sprmCFFldVanish
            # WordprocessingML field instructions are already hidden by their
            # fldChar/instrText structure. Emitting w:vanish would also hide
            # the cached field result in common consumers.
            if operand[0] in (0x80, 0x81):
                style_relative_toggle_count += 1
            elif operand[0] not in (0x00, 0x01):
                unsupported.add(opcode)
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
        elif opcode == 0x6A03:  # sprmCPicLocation
            properties = replace(
                properties,
                picture_location=struct.unpack("<i", operand)[0],
            )
        elif opcode == 0x0806:  # sprmCFData
            if operand[0] in (0, 1):
                properties = replace(
                    properties,
                    picture_is_binary=bool(operand[0]),
                )
            else:
                unsupported.add(opcode)
        elif opcode in (0x080A, 0x0856):  # sprmCFOle2 / sprmCFObj
            if operand[0] not in (0, 1):
                unsupported.add(opcode)
            else:
                attribute = (
                    "ole_object" if opcode == 0x080A else "object_placeholder"
                )
                properties = replace(
                    properties,
                    **{attribute: bool(operand[0])},
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
        elif opcode == 0x6877:  # sprmCCvUl
            if operand[3] == 0xFF:
                underline_color = "auto"
            else:
                underline_color = (
                    f"{operand[0]:02X}{operand[1]:02X}{operand[2]:02X}"
                )
            properties = replace(
                properties,
                underline_color=underline_color,
            )
        elif opcode == 0xCA71:  # sprmCShd
            if len(operand) != 11 or operand[0] != 10:
                raise InvalidWordDocument(
                    "sprmCShd must contain a ten-byte SHDOperand"
                )
            shading, approximated = _parse_shd(operand[1:])
            properties = replace(properties, shading=shading)
            if approximated:
                unsupported.add(opcode)
        elif opcode == 0xCA72:  # sprmCBrc
            properties = replace(
                properties,
                border=parse_brc_operand(operand),
            )
        elif opcode == 0x4866:  # sprmCShd80
            shading, approximated = _parse_shd80(operand)
            properties = replace(properties, shading=shading)
            if approximated:
                unsupported.add(opcode)
        elif opcode == 0x6865:  # sprmCBrc80
            properties = replace(
                properties,
                border=parse_brc80(operand),
            )
        elif opcode == 0x8840:  # sprmCDxaSpace
            properties = replace(
                properties,
                spacing_twips=struct.unpack("<h", operand)[0],
            )
        elif opcode == 0x4852:  # sprmCCharScale
            scale = struct.unpack("<H", operand)[0]
            if not 1 <= scale <= 600:
                raise InvalidWordDocument(
                    "character horizontal scale is outside [1, 600] percent"
                )
            properties = replace(properties, scale_percent=scale)
        elif opcode == 0xCA76:  # sprmCFitText
            if len(operand) != 9 or operand[0] != 8:
                raise InvalidWordDocument(
                    "sprmCFitText must contain an eight-byte CFitTextOperand"
                )
            width, fit_text_id = struct.unpack("<ii", operand[1:])
            if width == 0:
                properties = replace(
                    properties,
                    fit_text_width_twips=None,
                    fit_text_id=None,
                )
            elif 1 <= width <= 31680:
                properties = replace(
                    properties,
                    fit_text_width_twips=width,
                    fit_text_id=fit_text_id & 0xFFFFFFFF,
                )
            else:
                unsupported.add(opcode)
        elif opcode == 0xCA78:  # sprmCFELayout
            if len(operand) != 7 or operand[0] != 6:
                raise InvalidWordDocument(
                    "sprmCFELayout must contain a six-byte FarEastLayoutOperand"
                )
            layout_flags, layout_id = struct.unpack("<Hi", operand[1:])
            if layout_flags & 0x683C:
                raise InvalidWordDocument(
                    "sprmCFELayout has nonzero reserved layout flags"
                )
            bracket_value = (layout_flags >> 8) & 0x07
            combine = bool(layout_flags & 0x0002)
            bracket = _COMBINE_BRACKETS.get(bracket_value)
            if combine and bracket is None:
                raise InvalidWordDocument(
                    "sprmCFELayout has an invalid combine-bracket value"
                )
            properties = replace(
                properties,
                east_asian_vertical=bool(layout_flags & 0x0001),
                east_asian_combine=combine,
                east_asian_combine_brackets=bracket if combine else None,
                east_asian_vertical_compress=bool(layout_flags & 0x1000),
                east_asian_layout_id=layout_id & 0xFFFFFFFF,
            )
        elif opcode == 0x2A34:  # sprmCKcd
            emphasis = _EMPHASIS_MARKS.get(operand[0])
            if emphasis is None:
                unsupported.add(opcode)
            else:
                properties = replace(properties, emphasis=emphasis)
        elif opcode == 0x2859:  # sprmCSfxText
            if operand[0] not in _TEXT_EFFECTS:
                unsupported.add(opcode)
            else:
                properties = replace(
                    properties,
                    text_effect=_TEXT_EFFECTS[operand[0]],
                )
        elif opcode == 0x2879:  # sprmCLbcCRJ
            clear = _LINE_BREAK_CLEARS.get(operand[0])
            if clear is None:
                unsupported.add(opcode)
            else:
                properties = replace(properties, line_break_clear=clear)
        elif opcode == 0x6815:  # sprmCRsidProp
            properties = replace(
                properties,
                revision_format_id=struct.unpack("<I", operand)[0],
            )
        elif opcode == 0x6816:  # sprmCRsidText
            properties = replace(
                properties,
                revision_text_id=struct.unpack("<I", operand)[0],
            )
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


def _read_prc_data(data_stream: bytes, offset: int) -> tuple[PropertyModifier, ...]:
    if offset < 0 or offset > len(data_stream) - 2:
        raise InvalidWordDocument(
            f"PrcData offset {offset} exceeds the Data stream"
        )
    byte_count = struct.unpack_from("<H", data_stream, offset)[0]
    if byte_count < 10 or offset + 2 + byte_count > len(data_stream):
        raise InvalidWordDocument("PrcData has an invalid grpprl byte count")
    return parse_grpprl(
        data_stream[offset + 2 : offset + 2 + byte_count],
        label=f"PrcData[{offset}].grpprl",
    )


def _expand_paragraph_modifiers(
    modifiers: tuple[PropertyModifier, ...],
    data_stream: bytes | None,
    *,
    seen_offsets: frozenset[int] = frozenset(),
) -> tuple[PropertyModifier, ...]:
    if data_stream is None:
        return modifiers
    result: list[PropertyModifier] = []
    for index, modifier in enumerate(modifiers):
        if modifier.opcode == 0x6646:  # sprmPHugePapx
            if index:
                continue
            offset = struct.unpack("<I", modifier.operand)[0]
        elif modifier.opcode == 0x646B:  # sprmPTableProps
            offset = struct.unpack("<I", modifier.operand)[0]
        else:
            result.append(modifier)
            continue
        if offset in seen_offsets or len(seen_offsets) >= 32:
            raise InvalidWordDocument("PrcData paragraph-property chain is cyclic")
        referenced = _read_prc_data(data_stream, offset)
        result.extend(
            _expand_paragraph_modifiers(
                referenced,
                data_stream,
                seen_offsets=seen_offsets | {offset},
            )
        )
        # Processing either indirection means the remainder of its containing
        # Prl array is ignored by MS-DOC.
        break
    return tuple(result)


def apply_paragraph_modifiers(
    modifiers: tuple[PropertyModifier, ...],
    *,
    style_id: int | None,
    initial_properties: ParagraphProperties | None = None,
    data_stream: bytes | None = None,
) -> tuple[ParagraphProperties, set[int]]:
    modifiers = _expand_paragraph_modifiers(modifiers, data_stream)
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
        elif opcode in (0x560B, 0x5664):  # sprmTFBiDi / sprmTFBiDi90
            value = struct.unpack("<H", operand)[0]
            if value not in (0, 1):
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                properties = replace(
                    properties,
                    table_row=replace(row, bidirectional=bool(value)),
                )
        elif opcode == 0x3465:  # sprmTFNoAllowOverlap
            if operand[0] not in (0, 1):
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                properties = replace(
                    properties,
                    table_row=replace(row, no_overlap=bool(operand[0])),
                )
        elif opcode == 0x360D:  # sprmTPc
            value = operand[0]
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    vertical_anchor=_FRAME_VERTICAL_ANCHORS[
                        (value >> 4) & 0x03
                    ],
                    horizontal_anchor=_FRAME_HORIZONTAL_ANCHORS[
                        (value >> 6) & 0x03
                    ],
                ),
            )
        elif opcode in (0x940E, 0x940F):  # sprmTDxaAbs / sprmTDyaAbs
            position, alignment = _frame_position(
                operand,
                horizontal=opcode == 0x940E,
            )
            row = properties.table_row or TableRowProperties()
            prefix = "horizontal" if opcode == 0x940E else "vertical"
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    **{
                        f"{prefix}_position_twips": position,
                        f"{prefix}_alignment": alignment,
                    },
                ),
            )
        elif opcode in (0x9410, 0x9411, 0x941E, 0x941F):
            distance = struct.unpack("<h", operand)[0]
            if not 0 <= distance <= 31680:
                raise InvalidWordDocument("floating table distance is invalid")
            attribute = {
                0x9410: "distance_left_twips",
                0x9411: "distance_top_twips",
                0x941E: "distance_right_twips",
                0x941F: "distance_bottom_twips",
            }[opcode]
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, **{attribute: distance}),
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
        elif opcode == 0xF661:  # sprmTWidthIndent
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    left_indent_twips=_parse_table_indent(operand),
                ),
            )
        elif opcode == 0x3615:  # sprmTFAutofit
            if operand[0] not in (0x00, 0x01):
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                properties = replace(
                    properties,
                    table_row=replace(row, auto_fit=bool(operand[0])),
                )
        elif opcode == 0x740A:  # sprmTTlp
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, **_parse_table_look(operand)),
            )
        elif opcode in (0xF617, 0xF618):
            width_type, width = _parse_table_part_width(operand)
            if width_type == "dxa" and width:
                row = properties.table_row or TableRowProperties()
                prefix = "grid_before" if opcode == 0xF617 else "grid_after"
                properties = replace(
                    properties,
                    table_row=replace(
                        row,
                        **{
                            f"{prefix}_width": width,
                            f"{prefix}_width_type": width_type,
                        },
                    ),
                )
            elif width:
                # Percentage widths cannot be converted into the absolute
                # shared table grid without knowing Word's laid-out width.
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
        elif opcode == 0x7621:  # sprmTInsert
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_insert_table_cells(row, operand),
            )
        elif opcode == 0x5622:  # sprmTDelete
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_delete_table_cells(row, operand),
            )
        elif opcode == 0x7623:  # sprmTDxaCol
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_column_widths(row, operand),
            )
        elif opcode in (0x5624, 0x5625):  # sprmTMerge / sprmTSplit
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_merge_table_cells(
                    row,
                    operand,
                    merge=opcode == 0x5624,
                ),
            )
        elif opcode == 0x7629:  # sprmTTextFlow
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_text_flow(row, operand),
            )
        elif opcode == 0xD62B:  # sprmTVertMerge
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_vertical_merge(row, operand),
            )
        elif opcode == 0xD62C:  # sprmTVertAlign
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_vertical_alignment(row, operand),
            )
        elif opcode == 0xF636:  # sprmTFitText
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_boolean_range(
                    row,
                    operand,
                    attribute="fit_text",
                    variable_length=False,
                ),
            )
        elif opcode == 0xD639:  # sprmTFCellNoWrap
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_boolean_range(
                    row,
                    operand,
                    attribute="no_wrap",
                    variable_length=True,
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
        elif opcode in (0x7627, 0x7628, 0xD62D, 0xD62E):
            row = properties.table_row or TableRowProperties()
            row, approximated = _set_table_cell_shading(
                row,
                operand,
                legacy=opcode in (0x7627, 0x7628),
                alternating=opcode in (0x7628, 0xD62E),
            )
            properties = replace(properties, table_row=row)
            if approximated:
                unsupported.add(opcode)
        elif opcode in (0xD620, 0xD62F):
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_cell_borders(
                    row,
                    operand,
                    legacy=opcode == 0xD620,
                ),
            )
        elif opcode == 0xD642:  # sprmTCellFHideMark
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_boolean_range(
                    row,
                    operand,
                    attribute="hide_mark",
                    variable_length=True,
                ),
            )
        elif opcode in (
            0xD60C,  # sprmTDefTableShd3rd
            0xD616,  # sprmTDefTableShd2nd
            0xD670,  # sprmTDefTableShdRaw
            0xD671,  # sprmTDefTableShdRaw2nd
            0xD672,  # sprmTDefTableShdRaw3rd
        ):
            shadings, approximated = _parse_def_table_shd(operand)
            if opcode in (0xD60C, 0xD672) and len(shadings) > 19:
                raise InvalidWordDocument(
                    "third table-shading segment has more than 19 cells"
                )
            if opcode == 0xD670:
                first_cell = 0
            elif opcode in (0xD616, 0xD671):
                first_cell = 22
            else:
                first_cell = 44
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=_set_table_shading_segment(
                    row,
                    shadings,
                    first_cell=first_cell,
                ),
            )
            if approximated:
                unsupported.add(opcode)
        elif opcode == 0xD660:  # sprmTSetShdTable
            if len(operand) != 11 or operand[0] != 10:
                raise InvalidWordDocument(
                    "sprmTSetShdTable must contain a ten-byte SHDOperand"
                )
            shading, approximated = _parse_shd(operand[1:])
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, table_shading=shading),
            )
            if approximated:
                unsupported.add(opcode)
        elif opcode == 0x7479:  # sprmTRsid
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    revision_save_id=struct.unpack("<I", operand)[0],
                ),
            )
        elif opcode == 0xD633:  # sprmTCellSpacingDefault
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    cell_spacing_twips=_parse_cell_spacing(operand),
                ),
            )
        elif opcode in (0xD632, 0xD634, 0xD63E):
            first_cell, limit_cell, sides, width = _parse_cssa(operand)
            row = properties.table_row or TableRowProperties()
            if opcode in (0xD634, 0xD63E):
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
        elif opcode in (
            0xD47F,
            0xD680,
            0xD681,
            0xD682,
            0xD683,
            0xD684,
            0xD685,
            0xD686,
        ):
            border = parse_brc_operand(operand)
            row = properties.table_row or TableRowProperties()
            attribute = {
                0xD47F: "top",
                0xD680: "bottom",
                0xD681: "left",
                0xD682: "right",
                0xD683: "inside_horizontal",
                0xD684: "inside_vertical",
                0xD685: "diagonal_down",
                0xD686: "diagonal_up",
            }[opcode]
            properties = replace(
                properties,
                table_row=replace(
                    row,
                    style_cell_borders=replace(
                        row.style_cell_borders,
                        **{attribute: border},
                    ),
                ),
            )
        elif opcode == 0xD687:  # sprmTCellShdStyle
            if len(operand) != 11 or operand[0] != 10:
                raise InvalidWordDocument(
                    "sprmTCellShdStyle must contain a ten-byte SHDOperand"
                )
            shading, approximated = _parse_shd(operand[1:])
            row = properties.table_row or TableRowProperties()
            properties = replace(
                properties,
                table_row=replace(row, style_cell_shading=shading),
            )
            if approximated:
                unsupported.add(opcode)
        elif opcode == 0x347C:  # sprmTCellVertAlignStyle
            alignment = {0: "top", 1: "center", 2: "bottom"}.get(operand[0])
            if alignment is None:
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                properties = replace(
                    properties,
                    table_row=replace(
                        row,
                        style_cell_vertical_alignment=alignment,
                    ),
                )
        elif opcode == 0x347D:  # sprmTCellNoWrapStyle
            if operand[0] not in (0, 1):
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                properties = replace(
                    properties,
                    table_row=replace(
                        row,
                        style_cell_no_wrap=bool(operand[0]),
                    ),
                )
        elif opcode in (0x3488, 0x3489):
            band_size = operand[0]
            if not 1 <= band_size <= 3:
                unsupported.add(opcode)
            else:
                row = properties.table_row or TableRowProperties()
                attribute = (
                    "row_band_size" if opcode == 0x3488 else "column_band_size"
                )
                properties = replace(
                    properties,
                    table_row=replace(row, **{attribute: band_size}),
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
        elif opcode == 0x2602:  # sprmPIncLvl
            delta = struct.unpack("<b", operand)[0]
            if properties.style_id is not None and 1 <= properties.style_id <= 9:
                properties = replace(
                    properties,
                    style_id=min(9, max(1, properties.style_id + delta)),
                )
            elif properties.outline_level not in (None, 9):
                properties = replace(
                    properties,
                    outline_level=min(
                        9,
                        max(0, properties.outline_level + delta),
                    ),
                )
        elif opcode == 0x6467:  # sprmPRsid
            properties = replace(
                properties,
                revision_save_id=struct.unpack("<I", operand)[0],
            )
        elif opcode == 0x2405:
            properties = replace(properties, keep_lines=bool(operand[0]))
        elif opcode == 0x2406:
            properties = replace(properties, keep_next=bool(operand[0]))
        elif opcode == 0x2407:
            properties = replace(properties, page_break_before=bool(operand[0]))
        elif opcode == 0x261B:  # sprmPPc
            value = operand[0]
            frame = properties.frame or ParagraphFrameProperties()
            properties = replace(
                properties,
                frame=replace(
                    frame,
                    vertical_anchor=_FRAME_VERTICAL_ANCHORS[(value >> 4) & 0x03],
                    horizontal_anchor=_FRAME_HORIZONTAL_ANCHORS[
                        (value >> 6) & 0x03
                    ],
                ),
            )
        elif opcode == 0x2423:  # sprmPWr
            wrap = _FRAME_WRAPS.get(operand[0])
            if wrap is None:
                unsupported.add(opcode)
            else:
                frame = properties.frame or ParagraphFrameProperties()
                properties = replace(properties, frame=replace(frame, wrap=wrap))
        elif opcode in (0x8418, 0x8419):  # sprmPDxaAbs / sprmPDyaAbs
            position, alignment = _frame_position(
                operand,
                horizontal=opcode == 0x8418,
            )
            frame = properties.frame or ParagraphFrameProperties()
            prefix = "horizontal" if opcode == 0x8418 else "vertical"
            properties = replace(
                properties,
                frame=replace(
                    frame,
                    **{
                        f"{prefix}_position_twips": position,
                        f"{prefix}_alignment": alignment,
                    },
                ),
            )
        elif opcode == 0x841A:  # sprmPDxaWidth
            width = struct.unpack("<h", operand)[0]
            if not 0 <= width <= 31680:
                raise InvalidWordDocument("frame width is outside [0, 31680]")
            frame = properties.frame or ParagraphFrameProperties()
            properties = replace(
                properties,
                frame=replace(frame, width_twips=width or None),
            )
        elif opcode == 0x442B:  # sprmPWHeightAbs
            value = struct.unpack("<H", operand)[0]
            height = value & 0x7FFF
            minimum = bool(value & 0x8000)
            if height > 31680 or (minimum and not height):
                raise InvalidWordDocument("frame height has an invalid value")
            frame = properties.frame or ParagraphFrameProperties()
            properties = replace(
                properties,
                frame=replace(
                    frame,
                    height_twips=height or None,
                    height_rule=(
                        "atLeast" if minimum else "exact" if height else "auto"
                    ),
                ),
            )
        elif opcode in (0x842E, 0x842F):
            distance = struct.unpack("<h", operand)[0]
            if not 0 <= distance <= 31680:
                raise InvalidWordDocument("frame text distance is invalid")
            frame = properties.frame or ParagraphFrameProperties()
            attribute = (
                "vertical_space_twips"
                if opcode == 0x842E
                else "horizontal_space_twips"
            )
            properties = replace(
                properties,
                frame=replace(frame, **{attribute: distance}),
            )
        elif opcode == 0x2430:  # sprmPFLocked
            if operand[0] not in (0, 1):
                unsupported.add(opcode)
            else:
                frame = properties.frame or ParagraphFrameProperties()
                properties = replace(
                    properties,
                    frame=replace(frame, anchor_locked=bool(operand[0])),
                )
        elif opcode == 0x443A:  # sprmPFrameTextFlow
            value = struct.unpack("<H", operand)[0]
            if value & ~0x0007 or (value & 0x0002 and not value & 0x0001):
                raise InvalidWordDocument(
                    "sprmPFrameTextFlow has invalid or reserved flags"
                )
            direction = _TABLE_TEXT_DIRECTIONS.get(value)
            if direction is None:
                raise InvalidWordDocument(
                    "sprmPFrameTextFlow has an unsupported flag combination"
                )
            frame = properties.frame or ParagraphFrameProperties()
            properties = replace(
                properties,
                frame=replace(frame, text_direction=direction),
            )
        elif opcode == 0x442C:  # sprmPDcs
            value = struct.unpack("<H", operand)[0]
            drop_cap_type = value & 0x07
            lines = (value >> 3) & 0x1F
            if drop_cap_type == 0 and lines == 0:
                drop_cap = "none"
                lines_value = None
            elif drop_cap_type in (1, 2) and 1 <= lines <= 10:
                drop_cap = "drop" if drop_cap_type == 1 else "margin"
                lines_value = lines
            else:
                unsupported.add(opcode)
                continue
            frame = properties.frame or ParagraphFrameProperties()
            properties = replace(
                properties,
                frame=replace(
                    frame,
                    drop_cap=drop_cap,
                    drop_cap_lines=lines_value,
                ),
            )
        elif opcode == 0x442D:  # sprmPShd80
            value = struct.unpack("<H", operand)[0]
            shading, approximated = _parse_shd80(operand)
            if shading is None:
                shading = ShadingProperties(
                    "nil" if value == 0xFFFF else "clear"
                )
            properties = replace(properties, shading=shading)
            if approximated:
                unsupported.add(opcode)
        elif opcode == 0xC64D:  # sprmPShd
            if len(operand) != 11 or operand[0] != 10:
                raise InvalidWordDocument(
                    "sprmPShd must contain a ten-byte SHDOperand"
                )
            shading, approximated = _parse_shd(operand[1:])
            properties = replace(properties, shading=shading)
            if approximated:
                unsupported.add(opcode)
        elif opcode == 0x4439:  # sprmPWAlignFont
            value = struct.unpack("<H", operand)[0]
            alignment = _PARAGRAPH_TEXT_ALIGNMENTS.get(value)
            if alignment is None:
                unsupported.add(opcode)
            else:
                properties = replace(properties, text_alignment=alignment)
        elif opcode == 0x2470:  # sprmPFMirrorIndents
            if operand[0] not in (0, 1):
                unsupported.add(opcode)
            else:
                properties = replace(
                    properties,
                    mirror_indents=bool(operand[0]),
                )
        elif opcode == 0x2471:  # sprmPTtwo
            tight_wrap = _TEXTBOX_TIGHT_WRAPS.get(operand[0])
            if tight_wrap is None:
                unsupported.add(opcode)
            else:
                properties = replace(
                    properties,
                    textbox_tight_wrap=tight_wrap,
                )
        elif opcode == 0x2640:
            if operand[0] > 9:
                unsupported.add(opcode)
            else:
                properties = replace(properties, outline_level=operand[0])
        elif opcode == 0x260A:  # sprmPIlvl
            level = operand[0]
            if 0 <= level <= 8:
                properties = replace(
                    properties,
                    numbering_level=level,
                    numbering_skipped=False,
                )
            elif level == 0x0C:
                properties = replace(properties, numbering_skipped=True)
            else:
                unsupported.add(opcode)
        elif opcode == 0x460B:  # sprmPIlfo
            list_index = struct.unpack("<h", operand)[0]
            if list_index in (0, -2047):
                properties = replace(
                    properties,
                    numbering_id=None,
                    numbering_suppressed=True,
                )
            elif 1 <= abs(list_index) <= 0x07FE:
                properties = replace(
                    properties,
                    numbering_id=abs(list_index),
                    numbering_suppressed=False,
                )
            else:
                unsupported.add(opcode)
        elif opcode in (0xC60D, 0xC615):
            properties = replace(
                properties,
                tab_stops=(
                    *(properties.tab_stops or ()),
                    *_parse_tab_changes(
                        operand,
                        deletion_ranges=opcode == 0xC615,
                    ),
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
            base_indent = struct.unpack("<h", operand)[0]
            properties = replace(
                properties,
                left_indent_twips=(
                    base_indent + (properties.nest_indent_twips or 0)
                ),
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
        elif opcode in (0x4455, 0x4456, 0x4457):
            attribute = {
                0x4455: "right_indent_chars",
                0x4456: "left_indent_chars",
                0x4457: "first_line_indent_chars",
            }[opcode]
            properties = replace(
                properties,
                **{attribute: struct.unpack("<h", operand)[0]},
            )
        elif opcode in (0x4610, 0x465F):  # sprmPNest80 / sprmPNest
            modern = opcode == 0x465F
            if not modern and properties.nest_indent_modern:
                continue
            previous_nest = properties.nest_indent_twips or 0
            nest_indent = struct.unpack("<h", operand)[0]
            properties = replace(
                properties,
                left_indent_twips=(
                    (properties.left_indent_twips or 0)
                    - previous_nest
                    + nest_indent
                ),
                nest_indent_twips=nest_indent,
                nest_indent_modern=modern,
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
        elif opcode in (0x6424, 0x6425, 0x6426, 0x6427, 0x6428):
            border = parse_brc80(operand)
            borders = properties.borders or TableBorders()
            attribute = {
                0x6424: "top",
                0x6425: "left",
                0x6426: "bottom",
                0x6427: "right",
                0x6428: "between",
            }[opcode]
            properties = replace(
                properties,
                borders=replace(borders, **{attribute: border}),
            )
        elif opcode in (0xC64E, 0xC64F, 0xC650, 0xC651, 0xC652):
            border = parse_brc_operand(operand)
            borders = properties.borders or TableBorders()
            attribute = {
                0xC64E: "top",
                0xC64F: "left",
                0xC650: "bottom",
                0xC651: "right",
                0xC652: "between",
            }[opcode]
            properties = replace(
                properties,
                borders=replace(borders, **{attribute: border}),
            )
        elif opcode in (0x6629, 0xC653, 0xC669, 0xC66C):
            # Published legacy compatibility operands with no display effect.
            continue
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
