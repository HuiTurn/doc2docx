"""MS-DOC PlcfSed, Sed, Sepx, and basic page-layout parsing."""

from __future__ import annotations

from dataclasses import replace
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import SectionBreakType, SectionProperties
from .number_formats import NUMBER_FORMATS
from .sprm import PropertyModifier, parse_grpprl


_BREAK_TYPES = {
    0x00: SectionBreakType.CONTINUOUS,
    0x01: SectionBreakType.NEXT_COLUMN,
    0x02: SectionBreakType.NEXT_PAGE,
    0x03: SectionBreakType.EVEN_PAGE,
    0x04: SectionBreakType.ODD_PAGE,
}

_DOCUMENT_GRID_TYPES = {
    0x0000: None,
    0x0001: "linesAndChars",
    0x0002: "lines",
    0x0003: "snapToChars",
}

_NUMBER_RESTARTS = {
    0x00: "continuous",
    0x01: "eachSect",
    0x02: "eachPage",
}

# MSOTXFL values 0, 1, 3, and 5 have direct section-level equivalents.
# Values 2 and 4 require glyph rotation/flow behavior that w:sectPr cannot
# preserve faithfully, so they remain diagnosed instead of being mislabeled.
_TEXT_DIRECTIONS = {
    0x0000: "lrTb",
    0x0001: "tbRl",
    0x0003: "tbRl",
    0x0005: "tbRl",
}

_HEADER_DISTANCE_708_LCIDS = {
    1026,
    1027,
    1029,
    1030,
    1035,
    1038,
    1039,
    1043,
    1044,
    1045,
    1048,
    1051,
    1055,
    1058,
    1059,
    1060,
    1061,
    1067,
    1068,
    1069,
    1078,
    1079,
    1087,
    1088,
    1089,
    1092,
    2074,
}

_REQUIRED_MARGIN_SPRMS = {
    0xB021: "left",
    0xB022: "right",
    0x9023: "top",
    0x9024: "bottom",
}


def _default_header_distance(lid: int) -> int:
    if lid == 1063:
        return 567
    if lid in _HEADER_DISTANCE_708_LCIDS:
        return 708
    return 720


def _u16(operand: bytes) -> int:
    return struct.unpack("<H", operand)[0]


def _i16(operand: bytes) -> int:
    return struct.unpack("<h", operand)[0]


def _i32(operand: bytes) -> int:
    return struct.unpack("<i", operand)[0]


def _number_format(operand: bytes) -> str | None:
    value = operand[0] if len(operand) == 1 else _u16(operand)
    return NUMBER_FORMATS.get(value)


def _apply_section_modifiers(
    section: SectionProperties,
    modifiers: tuple[PropertyModifier, ...],
) -> tuple[SectionProperties, set[int], set[int]]:
    unsupported: set[int] = set()
    seen: set[int] = set()
    for modifier in modifiers:
        opcode = modifier.opcode
        operand = modifier.operand
        seen.add(opcode)
        if opcode == 0x3009:  # sprmSBkc
            break_type = _BREAK_TYPES.get(operand[0])
            if break_type is None:
                unsupported.add(opcode)
            else:
                section = replace(section, break_type=break_type)
        elif opcode == 0x300A:  # sprmSFTitlePage
            if operand[0] not in (0x00, 0x01):
                unsupported.add(opcode)
            else:
                section = replace(section, title_page=bool(operand[0]))
        elif opcode == 0x300E:  # sprmSNfcPgn
            number_format = _number_format(operand)
            if number_format in (None, "bullet", "none"):
                unsupported.add(opcode)
            else:
                section = replace(section, page_number_format=number_format)
        elif opcode == 0x303C:  # sprmSRncFtn
            restart = _NUMBER_RESTARTS.get(operand[0])
            if restart is None:
                unsupported.add(opcode)
            else:
                section = replace(section, footnote_number_restart=restart)
        elif opcode == 0x303E:  # sprmSRncEdn
            restart = _NUMBER_RESTARTS.get(operand[0])
            if restart not in ("continuous", "eachSect"):
                unsupported.add(opcode)
            else:
                section = replace(section, endnote_number_restart=restart)
        elif opcode == 0xB017:  # sprmSDyaHdrTop
            section = replace(section, header_distance_twips=_u16(operand))
        elif opcode == 0xB018:  # sprmSDyaHdrBottom
            section = replace(section, footer_distance_twips=_u16(operand))
        elif opcode == 0x301D:  # sprmSBOrientation
            orientation = {0x01: "portrait", 0x02: "landscape"}.get(operand[0])
            if orientation is None:
                unsupported.add(opcode)
            else:
                section = replace(section, orientation=orientation)
        elif opcode == 0x3228:  # sprmSFBiDi
            if operand[0] not in (0x00, 0x01):
                unsupported.add(opcode)
            else:
                section = replace(section, bidirectional=bool(operand[0]))
        elif opcode == 0xB01F:  # sprmSXaPage
            width = _u16(operand)
            if not 144 <= width <= 31680:
                raise InvalidWordDocument(
                    f"section page width {width} is outside [144, 31680] twips"
                )
            section = replace(section, page_width_twips=width)
        elif opcode == 0xB020:  # sprmSYaPage
            height = _u16(operand)
            if not 144 <= height <= 31680:
                raise InvalidWordDocument(
                    f"section page height {height} is outside [144, 31680] twips"
                )
            section = replace(section, page_height_twips=height)
        elif opcode == 0xB021:  # sprmSDxaLeft
            section = replace(section, margin_left_twips=_u16(operand))
        elif opcode == 0xB022:  # sprmSDxaRight
            section = replace(section, margin_right_twips=_u16(operand))
        elif opcode == 0x9023:  # sprmSDyaTop
            margin = _i16(operand)
            if not -31665 <= margin <= 31665:
                raise InvalidWordDocument(
                    f"section top margin {margin} is outside [-31665, 31665] twips"
                )
            section = replace(section, margin_top_twips=margin)
        elif opcode == 0x9024:  # sprmSDyaBottom
            margin = _i16(operand)
            if not -31665 <= margin <= 31665:
                raise InvalidWordDocument(
                    f"section bottom margin {margin} is outside [-31665, 31665] twips"
                )
            section = replace(section, margin_bottom_twips=margin)
        elif opcode == 0xB025:  # sprmSDzaGutter
            section = replace(section, gutter_twips=_u16(operand))
        elif opcode == 0x7030:  # sprmSDxtCharSpace
            character_space = _i32(operand)
            if not -670925 <= character_space <= 6488064:
                raise InvalidWordDocument(
                    "section document-grid character spacing "
                    f"{character_space} is outside [-670925, 6488064]"
                )
            section = replace(
                section,
                document_grid_character_space=character_space,
            )
        elif opcode == 0x9031:  # sprmSDyaLinePitch
            line_pitch = _u16(operand)
            if not 1 <= line_pitch <= 31680:
                raise InvalidWordDocument(
                    "section document-grid line pitch "
                    f"{line_pitch} is outside [1, 31680] twips"
                )
            section = replace(
                section,
                document_grid_line_pitch_twips=line_pitch,
            )
        elif opcode == 0x5032:  # sprmSClm
            grid_mode = _u16(operand)
            if grid_mode not in _DOCUMENT_GRID_TYPES:
                unsupported.add(opcode)
            else:
                section = replace(
                    section,
                    document_grid_type=_DOCUMENT_GRID_TYPES[grid_mode],
                )
        elif opcode == 0x5033:  # sprmSTextFlow
            text_direction = _TEXT_DIRECTIONS.get(_u16(operand))
            if text_direction is None:
                unsupported.add(opcode)
            else:
                section = replace(section, text_direction=text_direction)
        elif opcode == 0x5040:  # sprmSNfcFtnRef
            number_format = _number_format(operand)
            if number_format is None:
                unsupported.add(opcode)
            else:
                section = replace(section, footnote_number_format=number_format)
        elif opcode == 0x5042:  # sprmSNfcEdnRef
            number_format = _number_format(operand)
            if number_format is None:
                unsupported.add(opcode)
            else:
                section = replace(section, endnote_number_format=number_format)
        else:
            unsupported.add(opcode)
    return section, unsupported, seen


def _read_sepx(
    word_document: bytes,
    fc_sepx: int,
    *,
    section_index: int,
) -> tuple[PropertyModifier, ...]:
    if fc_sepx == -1:
        return ()
    if fc_sepx < 0 or fc_sepx > len(word_document) - 2:
        raise InvalidWordDocument(
            f"Sed {section_index} fcSepx {fc_sepx} points outside WordDocument"
        )
    byte_count = struct.unpack_from("<h", word_document, fc_sepx)[0]
    if byte_count < 0:
        raise InvalidWordDocument(
            f"Sepx {section_index} has negative byte count {byte_count}"
        )
    end = fc_sepx + 2 + byte_count
    if end > len(word_document):
        raise InvalidWordDocument(
            f"Sepx {section_index} range [{fc_sepx}, {end}) exceeds WordDocument"
        )
    return parse_grpprl(
        word_document[fc_sepx + 2 : end],
        label=f"Sepx {section_index}.grpprl",
    )


def read_sections(
    table_stream: bytes,
    word_document: bytes,
    *,
    offset: int,
    size: int,
    main_story_cp_count: int,
    document_lid: int,
    report: ConversionReport,
) -> tuple[SectionProperties, ...]:
    """Resolve the main-story section PLC into page-layout properties."""

    if size == 0:
        return ()
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"PlcfSed range [{offset}, {offset + size}) exceeds Table stream"
        )
    data = table_stream[offset : offset + size]
    if len(data) < 20 or (len(data) - 4) % 16:
        raise InvalidWordDocument(
            f"PlcfSed size {len(data)} does not match the 16*n+4 PLC layout"
        )
    section_count = (len(data) - 4) // 16
    cps = struct.unpack_from(f"<{section_count + 1}I", data)
    if cps[0] != 0:
        raise InvalidWordDocument(f"PlcfSed starts at CP {cps[0]}, expected 0")
    for previous, current in zip(cps, cps[1:]):
        if current <= previous:
            raise InvalidWordDocument("PlcfSed CP values are not increasing")
    if cps[-1] < main_story_cp_count:
        raise InvalidWordDocument(
            f"PlcfSed ends at CP {cps[-1]} before main story CP {main_story_cp_count}"
        )
    if any(cp > main_story_cp_count for cp in cps[1:-1]):
        raise InvalidWordDocument("PlcfSed has an internal boundary beyond the main story")

    sed_offset = 4 * (section_count + 1)
    default_header_distance = _default_header_distance(document_lid)
    sections: list[SectionProperties] = []
    unsupported: set[int] = set()
    for index in range(section_count):
        record_offset = sed_offset + index * 12
        fc_sepx = struct.unpack_from("<i", data, record_offset + 2)[0]
        modifiers = _read_sepx(
            word_document,
            fc_sepx,
            section_index=index,
        )
        section = SectionProperties(
            cp_start=cps[index],
            cp_end=min(cps[index + 1], main_story_cp_count),
            header_distance_twips=default_header_distance,
            footer_distance_twips=default_header_distance,
        )
        section, section_unsupported, seen = _apply_section_modifiers(
            section,
            modifiers,
        )
        unsupported.update(section_unsupported)
        missing_margins = [
            name for opcode, name in _REQUIRED_MARGIN_SPRMS.items() if opcode not in seen
        ]
        if missing_margins:
            report.warning(
                "SECTION_MARGIN_DEFAULTED",
                "required or implementation-dependent DOC section margins were absent; 1 inch was used",
                location=SourceLocation(
                    story="main",
                    cp_start=section.cp_start,
                    cp_end=section.cp_end,
                    stream="WordDocument" if fc_sepx >= 0 else "Table",
                    fc_start=fc_sepx if fc_sepx >= 0 else offset + record_offset,
                ),
                section_index=index,
                margins=missing_margins,
            )
        if (
            section.document_grid_type is not None
            and section.document_grid_line_pitch_twips is None
        ):
            report.warning(
                "SECTION_GRID_INCOMPLETE",
                "the DOC section enables a document grid without its required line pitch; the grid was omitted",
                location=SourceLocation(
                    story="main",
                    cp_start=section.cp_start,
                    cp_end=section.cp_end,
                    stream="WordDocument" if fc_sepx >= 0 else "Table",
                    fc_start=fc_sepx if fc_sepx >= 0 else offset + record_offset,
                ),
                section_index=index,
                grid_type=section.document_grid_type,
            )
            section = replace(section, document_grid_type=None)
        sections.append(section)

    if unsupported:
        report.warning(
            "UNSUPPORTED_SECTION_SPRMS",
            "some DOC section properties are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported)],
        )
    return tuple(sections)
