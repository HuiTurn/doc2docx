"""Footnote reference and story extraction from PlcffndRef/PlcffndTxt."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import (
    CharacterProperties,
    Footnote,
    FootnoteReference,
    ParagraphProperties,
    parse_main_story,
)
from .pieces import PieceTable


@dataclass(slots=True, frozen=True)
class FootnoteCollection:
    footnotes: tuple[Footnote, ...] = ()
    references_by_cp: dict[int, FootnoteReference] | None = None
    custom_mark_count: int = 0

    @property
    def reference_count(self) -> int:
        return len(self.references_by_cp or {})

    def reference_at(self, cp: int) -> FootnoteReference | None:
        return (self.references_by_cp or {}).get(cp)


def _checked_range(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    label: str,
) -> memoryview:
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"{label} range [{offset}, {offset + size}) exceeds Table stream"
        )
    return memoryview(table_stream)[offset : offset + size]


def _read_references(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    ccp_text: int,
) -> tuple[tuple[int, int], ...]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        label="PlcffndRef",
    )
    if size < 10 or (size - 4) % 6:
        raise InvalidWordDocument(
            f"PlcffndRef size {size} does not describe a whole reference PLC"
        )
    reference_count = (size - 4) // 6
    cp_count = reference_count + 1
    cps = struct.unpack_from(f"<{cp_count}I", data)
    reference_cps = cps[:-1]  # The final CP is undefined by MS-DOC.
    if any(cp >= ccp_text for cp in reference_cps):
        raise InvalidWordDocument("PlcffndRef contains a CP outside the main document")
    if any(current <= previous for previous, current in zip(reference_cps, reference_cps[1:])):
        raise InvalidWordDocument("PlcffndRef reference CPs are not strictly increasing")
    indexes = struct.unpack_from(f"<{reference_count}H", data, cp_count * 4)
    return tuple(zip(reference_cps, indexes, strict=True))


def _read_text_ranges(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    ccp_footnotes: int,
) -> tuple[tuple[int, int], ...]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        label="PlcffndTxt",
    )
    if size < 12 or size % 4:
        raise InvalidWordDocument(
            f"PlcffndTxt size {size} does not describe a whole CP-only PLC"
        )
    cps = struct.unpack_from(f"<{size // 4}I", data)
    story_cps = cps[:-1]  # The final CP is undefined by MS-DOC.
    if any(cp >= ccp_footnotes for cp in story_cps):
        raise InvalidWordDocument("PlcffndTxt contains a CP outside the footnote document")
    if any(current <= previous for previous, current in zip(story_cps, story_cps[1:])):
        raise InvalidWordDocument("PlcffndTxt CPs are not strictly increasing")
    if story_cps[-1] != ccp_footnotes - 1:
        raise InvalidWordDocument(
            "PlcffndTxt second-to-last CP does not equal ccpFtn minus one"
        )
    return tuple(zip(story_cps, story_cps[1:]))


def read_footnotes(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    ccp_text: int,
    ccp_footnotes: int,
    reference_offset: int,
    reference_size: int,
    text_offset: int,
    text_size: int,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties] | None = None,
    paragraph_properties_at: Callable[[int], ParagraphProperties] | None = None,
) -> FootnoteCollection:
    """Parse footnote bodies and map their main-story reference CPs."""

    if ccp_footnotes == 0 and reference_size == 0 and text_size == 0:
        return FootnoteCollection()
    if ccp_footnotes == 0 or reference_size == 0 or text_size == 0:
        raise InvalidWordDocument(
            "footnote document, PlcffndRef, and PlcffndTxt must all exist together"
        )
    footnote_cp_start = ccp_text
    footnote_cp_end = footnote_cp_start + ccp_footnotes
    if footnote_cp_end > piece_table.cp_end:
        raise InvalidWordDocument(
            f"footnote story range [{footnote_cp_start}, {footnote_cp_end}) "
            f"exceeds Piece Table CP {piece_table.cp_end}"
        )

    references = _read_references(
        table_stream,
        offset=reference_offset,
        size=reference_size,
        ccp_text=ccp_text,
    )
    text_ranges = _read_text_ranges(
        table_stream,
        offset=text_offset,
        size=text_size,
        ccp_footnotes=ccp_footnotes,
    )
    if len(references) != len(text_ranges):
        raise InvalidWordDocument(
            "PlcffndRef reference count does not match PlcffndTxt footnote count"
        )

    reference_map: dict[int, FootnoteReference] = {}
    custom_mark_count = 0
    for footnote_id, (reference_cp, numbering_index) in enumerate(references, start=1):
        properties = (
            character_properties_at(reference_cp)
            if character_properties_at is not None
            else CharacterProperties()
        )
        if numbering_index:
            units = piece_table.extract_characters(
                reference_cp,
                reference_cp + 1,
                report,
                story="main-footnote-reference",
            )
            if len(units) != 1 or units[0].text != "\x02":
                raise InvalidWordDocument(
                    f"automatic footnote reference at CP {reference_cp} is not 0x02"
                )
            if properties.special is not True:
                raise InvalidWordDocument(
                    f"automatic footnote reference at CP {reference_cp} has no sprmCFSpec"
                )
        else:
            custom_mark_count += 1
        reference_map[reference_cp] = FootnoteReference(footnote_id, properties)

    if custom_mark_count:
        report.warning(
            "CUSTOM_FOOTNOTE_MARK_APPROXIMATED",
            "custom footnote symbols were converted to automatic numbering",
            location=SourceLocation(story="main"),
            reference_count=custom_mark_count,
        )

    footnotes: list[Footnote] = []
    for footnote_id, (relative_start, relative_end) in enumerate(
        text_ranges,
        start=1,
    ):
        cp_start = footnote_cp_start + relative_start
        cp_end = footnote_cp_start + relative_end
        story_name = f"footnote-{footnote_id}"
        units = piece_table.extract_characters(
            cp_start,
            cp_end,
            report,
            story=story_name,
        )
        if not units or units[-1].text != "\r" or units[-1].cp_end != cp_end:
            raise InvalidWordDocument(
                f"PlcffndTxt footnote {footnote_id} does not end in a paragraph mark"
            )
        # Word stores the automatically generated local reference mark as a
        # leading U+0002 in the footnote range. OOXML represents the same mark
        # structurally as w:footnoteRef, which the package writer adds.
        if units[0].text == "\x02":
            units = units[1:]
        parsed = parse_main_story(
            units,
            report,
            character_properties_at=character_properties_at,
            paragraph_properties_at=paragraph_properties_at,
            story_name=story_name,
        )
        footnotes.append(
            Footnote(
                footnote_id=footnote_id,
                paragraphs=parsed.paragraphs,
                blocks=parsed.blocks,
            )
        )

    return FootnoteCollection(
        footnotes=tuple(footnotes),
        references_by_cp=reference_map,
        custom_mark_count=custom_mark_count,
    )
