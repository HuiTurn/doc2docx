"""Footnote reference and story extraction from PlcffndRef/PlcffndTxt."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from ..diagnostics import ConversionReport
from ..errors import InvalidWordDocument
from ..model import (
    CharacterProperties,
    BookmarkEnd,
    BookmarkStart,
    FieldEndProperties,
    Footnote,
    FootnoteReference,
    ParagraphProperties,
    parse_main_story,
)
from .pieces import PieceTable
from .notes import read_note_references, read_note_text_ranges


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
    field_end_properties_at: (
        Callable[[int], FieldEndProperties | None] | None
    ) = None,
    bookmark_names: Collection[str] | None = None,
    bookmark_boundaries_at: (
        Callable[[int], Sequence[BookmarkStart | BookmarkEnd]] | None
    ) = None,
    style_names: Collection[str] | None = None,
    list_names: Collection[str] | None = None,
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

    references = read_note_references(
        table_stream,
        offset=reference_offset,
        size=reference_size,
        ccp_text=ccp_text,
        label="PlcffndRef",
    )
    text_ranges = read_note_text_ranges(
        table_stream,
        offset=text_offset,
        size=text_size,
        story_length=ccp_footnotes,
        story_length_name="ccpFtn",
        label="PlcffndTxt",
        story_kind="footnote",
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
        units = piece_table.extract_characters(
            reference_cp,
            reference_cp + 1,
            report,
            story="main-footnote-reference",
        )
        if len(units) != 1:
            raise InvalidWordDocument(
                f"footnote reference at CP {reference_cp} is not one character"
            )
        custom_mark = None
        if numbering_index:
            if len(units) != 1 or units[0].text != "\x02":
                raise InvalidWordDocument(
                    f"automatic footnote reference at CP {reference_cp} is not 0x02"
                )
            if properties.special is not True:
                raise InvalidWordDocument(
                    f"automatic footnote reference at CP {reference_cp} has no sprmCFSpec"
                )
        else:
            custom_mark = units[0].text
            if ord(custom_mark) < 0x20 or ord(custom_mark) in (0xFFFE, 0xFFFF):
                raise InvalidWordDocument(
                    f"custom footnote mark at CP {reference_cp} is not XML-safe"
                )
            custom_mark_count += 1
        reference_map[reference_cp] = FootnoteReference(
            footnote_id,
            custom_mark=custom_mark,
            properties=properties,
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
            field_end_properties_at=field_end_properties_at,
            bookmark_boundaries_at=bookmark_boundaries_at,
            bookmark_names=bookmark_names,
            style_names=style_names,
            list_names=list_names,
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
