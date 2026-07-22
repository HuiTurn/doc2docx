"""MS-DOC PlcfSed, Sed, Sepx, and basic page-layout parsing."""

from __future__ import annotations

from dataclasses import dataclass, replace
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

_FOOTNOTE_POSITIONS = {
    0x01: "pageBottom",
    0x02: "beneathText",
}

_LINE_NUMBER_RESTARTS = {
    0x00: "newPage",
    0x01: "newSection",
    0x02: "continuous",
}

_VERTICAL_ALIGNMENTS = {
    0x00: "top",
    0x01: "center",
    0x02: "both",
    0x03: "bottom",
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


@dataclass(slots=True, frozen=True)
class _SectionRecord:
    cp_start: int
    record_offset: int
    fc_sepx: int
    modifiers: tuple[PropertyModifier, ...]
    sed_signature: bytes


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


def _u32(operand: bytes) -> int:
    return struct.unpack("<I", operand)[0]


def _number_format(operand: bytes) -> str | None:
    value = operand[0] if len(operand) == 1 else _u16(operand)
    return NUMBER_FORMATS.get(value)


def _apply_section_modifiers(
    section: SectionProperties,
    modifiers: tuple[PropertyModifier, ...],
) -> tuple[SectionProperties, set[int], set[int]]:
    unsupported: set[int] = set()
    seen: set[int] = set()
    page_number_restart: bool | None = None
    page_number_start: int | None = None
    line_number_count_by: int | None = None
    line_number_start = 0
    line_number_distance_twips = 0
    line_number_restart = "newPage"
    footnote_number_start: int | None = None
    endnote_number_start: int | None = None
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
        elif opcode == 0x3012:  # sprmSFEndnote
            if operand[0] not in (0x00, 0x01):
                unsupported.add(opcode)
            else:
                section = replace(
                    section,
                    suppress_endnotes=not bool(operand[0]),
                )
        elif opcode == 0x3005:  # sprmSFEvenlySpaced
            if operand[0] == 0x01:
                section = replace(section, columns_evenly_spaced=True)
            else:
                # Uneven columns also require the per-column width and
                # spacing operands, which are not modeled yet.
                unsupported.add(opcode)
        elif opcode == 0x500B:  # sprmSCcolumns
            column_count_minus_one = _u16(operand)
            if column_count_minus_one > 43:
                raise InvalidWordDocument(
                    "section column count exceeds the MS-DOC limit of 44"
                )
            section = replace(
                section,
                column_count=column_count_minus_one + 1,
            )
        elif opcode == 0x900C:  # sprmSDxaColumns
            section = replace(section, column_spacing_twips=_u16(operand))
        elif opcode == 0x3019:  # sprmSLBetween
            if operand[0] not in (0x00, 0x01):
                unsupported.add(opcode)
            else:
                section = replace(
                    section,
                    column_separator=bool(operand[0]),
                )
        elif opcode == 0x301A:  # sprmSVjc
            vertical_alignment = _VERTICAL_ALIGNMENTS.get(operand[0])
            if vertical_alignment is None:
                unsupported.add(opcode)
            else:
                section = replace(
                    section,
                    vertical_alignment=vertical_alignment,
                )
        elif opcode == 0x300E:  # sprmSNfcPgn
            number_format = _number_format(operand)
            if number_format in (None, "bullet", "none"):
                unsupported.add(opcode)
            else:
                section = replace(section, page_number_format=number_format)
        elif opcode == 0x3011:  # sprmSFPgnRestart
            if operand[0] not in (0x00, 0x01):
                unsupported.add(opcode)
            else:
                page_number_restart = bool(operand[0])
        elif opcode == 0x501C:  # sprmSPgnStart97
            page_number_start = _u16(operand)
        elif opcode == 0x7044:  # sprmSPgnStart
            value = _u32(operand)
            if value > 2147483646:
                raise InvalidWordDocument(
                    f"section page-number start {value} exceeds 2147483646"
                )
            page_number_start = value
        elif opcode == 0x3013:  # sprmSLnc
            restart = _LINE_NUMBER_RESTARTS.get(operand[0])
            if restart is None:
                unsupported.add(opcode)
            else:
                line_number_restart = restart
        elif opcode == 0x5015:  # sprmSNLnnMod
            value = _u16(operand)
            if value > 100:
                raise InvalidWordDocument(
                    f"section line-number interval {value} exceeds 100"
                )
            line_number_count_by = value
        elif opcode == 0x9016:  # sprmSDxaLnn
            value = _u16(operand)
            if value > 31680:
                raise InvalidWordDocument(
                    f"section line-number distance {value} exceeds 31680 twips"
                )
            line_number_distance_twips = value
        elif opcode == 0x501B:  # sprmSLnnMin
            # SLnnMin and interoperable w:lnNumType writers both use the
            # zero-based value immediately preceding the displayed start.
            line_number_start = _u16(operand)
        elif opcode == 0x303C:  # sprmSRncFtn
            restart = _NUMBER_RESTARTS.get(operand[0])
            if restart is None:
                unsupported.add(opcode)
            else:
                section = replace(section, footnote_number_restart=restart)
        elif opcode == 0x303B:  # sprmSFpc
            position = _FOOTNOTE_POSITIONS.get(operand[0])
            if position is None:
                unsupported.add(opcode)
            else:
                section = replace(section, footnote_position=position)
        elif opcode == 0x303E:  # sprmSRncEdn
            restart = _NUMBER_RESTARTS.get(operand[0])
            if restart not in ("continuous", "eachSect"):
                unsupported.add(opcode)
            else:
                section = replace(section, endnote_number_restart=restart)
        elif opcode == 0x503F:  # sprmSNFtn
            value = _u16(operand)
            if value > 16383:
                unsupported.add(opcode)
            else:
                footnote_number_start = value
        elif opcode == 0x5041:  # sprmSNEdn
            value = _u16(operand)
            if value > 16383:
                unsupported.add(opcode)
            else:
                endnote_number_start = value
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
        elif opcode == 0x5026:  # sprmSDmPaperReq
            # This printer-specific tie breaker MAY be ignored by MS-DOC and
            # has no interoperable WordprocessingML equivalent.
            continue
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
        elif opcode == 0x703A:  # sprmSRsid
            section = replace(section, revision_save_id=_u32(operand))
        else:
            unsupported.add(opcode)
    if page_number_restart is True:
        section = replace(
            section,
            page_number_start=(
                0 if page_number_start is None else page_number_start
            ),
        )
    if line_number_count_by not in (None, 0):
        section = replace(
            section,
            line_number_count_by=line_number_count_by,
            line_number_start=line_number_start,
            line_number_distance_twips=line_number_distance_twips,
            line_number_restart=line_number_restart,
        )
    if (
        footnote_number_start is not None
        and section.footnote_number_restart in (None, "continuous")
    ):
        section = replace(
            section,
            footnote_number_start=footnote_number_start,
        )
    if (
        endnote_number_start is not None
        and section.endnote_number_restart in (None, "continuous")
    ):
        section = replace(
            section,
            endnote_number_start=endnote_number_start,
        )
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
    default_footnote_position: str | None = None,
    default_footnote_number_format: str | None = None,
    default_footnote_number_start: int | None = None,
    default_footnote_number_restart: str | None = None,
    default_endnote_position: str | None = None,
    default_endnote_number_format: str | None = None,
    default_endnote_number_start: int | None = None,
    default_endnote_number_restart: str | None = None,
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
        if current < previous:
            raise InvalidWordDocument("PlcfSed CP values are decreasing")
    if cps[-1] < main_story_cp_count:
        raise InvalidWordDocument(
            f"PlcfSed ends at CP {cps[-1]} before main story CP {main_story_cp_count}"
        )
    if any(cp > main_story_cp_count for cp in cps[1:-1]):
        raise InvalidWordDocument("PlcfSed has an internal boundary beyond the main story")

    sed_offset = 4 * (section_count + 1)
    raw_records: list[_SectionRecord] = []
    for index in range(section_count):
        record_offset = sed_offset + index * 12
        record = data[record_offset : record_offset + 12]
        fc_sepx = struct.unpack_from("<i", record, 2)[0]
        raw_records.append(
            _SectionRecord(
                cp_start=cps[index],
                record_offset=record_offset,
                fc_sepx=fc_sepx,
                modifiers=_read_sepx(
                    word_document,
                    fc_sepx,
                    section_index=index,
                ),
                sed_signature=record[:2] + record[6:],
            )
        )

    records: list[_SectionRecord] = []
    repaired_duplicate_cps: list[int] = []
    for record in raw_records:
        if records and record.cp_start == records[-1].cp_start:
            previous = records[-1]
            if (
                record.sed_signature != previous.sed_signature
                or record.modifiers != previous.modifiers
            ):
                raise InvalidWordDocument(
                    "PlcfSed contains duplicate CPs with different section properties"
                )
            records[-1] = record
            repaired_duplicate_cps.append(record.cp_start)
        else:
            records.append(record)
    if not records or cps[-1] <= records[-1].cp_start:
        raise InvalidWordDocument("PlcfSed ends with an empty section range")
    if repaired_duplicate_cps:
        report.warning(
            "SECTION_DUPLICATE_CP_REPAIRED",
            "equivalent empty sections at duplicate PlcfSed CPs were omitted",
            location=SourceLocation(story="main", stream="Table"),
            duplicate_count=len(repaired_duplicate_cps),
            cps=repaired_duplicate_cps,
        )

    default_header_distance = _default_header_distance(document_lid)
    sections: list[SectionProperties] = []
    unsupported: set[int] = set()
    for index, record in enumerate(records):
        record_offset = record.record_offset
        fc_sepx = record.fc_sepx
        modifiers = record.modifiers
        cp_end = (
            records[index + 1].cp_start
            if index + 1 < len(records)
            else cps[-1]
        )
        section = SectionProperties(
            cp_start=record.cp_start,
            cp_end=min(cp_end, main_story_cp_count),
            header_distance_twips=default_header_distance,
            footer_distance_twips=default_header_distance,
            footnote_position=default_footnote_position,
            footnote_number_format=default_footnote_number_format,
            footnote_number_start=default_footnote_number_start,
            footnote_number_restart=default_footnote_number_restart,
            endnote_position=default_endnote_position,
            endnote_number_format=default_endnote_number_format,
            endnote_number_start=default_endnote_number_start,
            endnote_number_restart=default_endnote_number_restart,
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
