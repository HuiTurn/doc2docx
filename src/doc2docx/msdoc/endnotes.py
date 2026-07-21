"""Endnote reference and story extraction from PlcfendRef/PlcfendTxt."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import (
    CharacterProperties,
    Endnote,
    EndnoteReference,
    FieldEndProperties,
    ParagraphProperties,
    parse_main_story,
)
from .notes import read_note_references, read_note_text_ranges
from .pieces import PieceTable


@dataclass(slots=True, frozen=True)
class EndnoteCollection:
    endnotes: tuple[Endnote, ...] = ()
    references_by_cp: dict[int, EndnoteReference] | None = None
    custom_mark_count: int = 0

    @property
    def reference_count(self) -> int:
        return len(self.references_by_cp or {})

    def reference_at(self, cp: int) -> EndnoteReference | None:
        return (self.references_by_cp or {}).get(cp)


def read_endnotes(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    ccp_text: int,
    ccp_endnotes: int,
    endnote_story_cp_start: int,
    reference_offset: int,
    reference_size: int,
    text_offset: int,
    text_size: int,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties] | None = None,
    paragraph_properties_at: Callable[[int], ParagraphProperties] | None = None,
    field_end_properties_at: (
        Callable[[int], FieldEndProperties | None] | None
    ) = None,
    bookmark_names: Collection[str] | None = None,
    style_names: Collection[str] | None = None,
    list_names: Collection[str] | None = None,
) -> EndnoteCollection:
    """Parse endnote bodies and map their main-story reference CPs."""

    if ccp_endnotes == 0 and reference_size == 0 and text_size == 0:
        return EndnoteCollection()
    if ccp_endnotes == 0 or reference_size == 0 or text_size == 0:
        raise InvalidWordDocument(
            "endnote document, PlcfendRef, and PlcfendTxt must all exist together"
        )
    endnote_story_cp_end = endnote_story_cp_start + ccp_endnotes
    if endnote_story_cp_end > piece_table.cp_end:
        raise InvalidWordDocument(
            f"endnote story range [{endnote_story_cp_start}, "
            f"{endnote_story_cp_end}) exceeds Piece Table CP {piece_table.cp_end}"
        )

    references = read_note_references(
        table_stream,
        offset=reference_offset,
        size=reference_size,
        ccp_text=ccp_text,
        label="PlcfendRef",
    )
    text_ranges = read_note_text_ranges(
        table_stream,
        offset=text_offset,
        size=text_size,
        story_length=ccp_endnotes,
        story_length_name="ccpEdn",
        label="PlcfendTxt",
        story_kind="endnote",
    )
    if len(references) != len(text_ranges):
        raise InvalidWordDocument(
            "PlcfendRef reference count does not match PlcfendTxt endnote count"
        )

    reference_map: dict[int, EndnoteReference] = {}
    custom_mark_count = 0
    for endnote_id, (reference_cp, numbering_index) in enumerate(
        references,
        start=1,
    ):
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
                story="main-endnote-reference",
            )
            if len(units) != 1 or units[0].text != "\x02":
                raise InvalidWordDocument(
                    f"automatic endnote reference at CP {reference_cp} is not 0x02"
                )
            if properties.special is not True:
                raise InvalidWordDocument(
                    f"automatic endnote reference at CP {reference_cp} has no sprmCFSpec"
                )
        else:
            custom_mark_count += 1
        reference_map[reference_cp] = EndnoteReference(endnote_id, properties)

    if custom_mark_count:
        report.warning(
            "CUSTOM_ENDNOTE_MARK_APPROXIMATED",
            "custom endnote symbols were converted to automatic numbering",
            location=SourceLocation(story="main"),
            reference_count=custom_mark_count,
        )

    endnotes: list[Endnote] = []
    for endnote_id, (relative_start, relative_end) in enumerate(
        text_ranges,
        start=1,
    ):
        cp_start = endnote_story_cp_start + relative_start
        cp_end = endnote_story_cp_start + relative_end
        story_name = f"endnote-{endnote_id}"
        units = piece_table.extract_characters(
            cp_start,
            cp_end,
            report,
            story=story_name,
        )
        if not units or units[-1].text != "\r" or units[-1].cp_end != cp_end:
            raise InvalidWordDocument(
                f"PlcfendTxt endnote {endnote_id} does not end in a paragraph mark"
            )
        if units[0].text == "\x02":
            units = units[1:]
        parsed = parse_main_story(
            units,
            report,
            character_properties_at=character_properties_at,
            paragraph_properties_at=paragraph_properties_at,
            field_end_properties_at=field_end_properties_at,
            bookmark_names=bookmark_names,
            style_names=style_names,
            list_names=list_names,
            story_name=story_name,
        )
        endnotes.append(
            Endnote(
                endnote_id=endnote_id,
                paragraphs=parsed.paragraphs,
                blocks=parsed.blocks,
            )
        )

    return EndnoteCollection(
        endnotes=tuple(endnotes),
        references_by_cp=reference_map,
        custom_mark_count=custom_mark_count,
    )
