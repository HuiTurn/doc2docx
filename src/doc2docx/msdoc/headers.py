"""Header/footer story extraction and section association from PlcfHdd."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import (
    BookmarkEnd,
    BookmarkStart,
    CharacterProperties,
    FloatingPicture,
    FloatingShape,
    FloatingTextBox,
    FieldEndProperties,
    HeaderFooterStory,
    InlinePicture,
    NoteSeparatorStory,
    ParagraphProperties,
    SectionProperties,
    StoryCharacter,
    parse_main_story,
)
from .pieces import PieceTable


_STORIES_PER_SECTION = (
    ("even_header", "even header"),
    ("default_header", "default header"),
    ("even_footer", "even footer"),
    ("default_footer", "default footer"),
    ("first_header", "first-page header"),
    ("first_footer", "first-page footer"),
)

_NOTE_SEPARATOR_STORIES = (
    ("footnote_separator", "footnote-separator"),
    ("footnote_continuation_separator", "footnote-continuation-separator"),
    ("footnote_continuation_notice", "footnote-continuation-notice"),
    ("endnote_separator", "endnote-separator"),
    ("endnote_continuation_separator", "endnote-continuation-separator"),
    ("endnote_continuation_notice", "endnote-continuation-notice"),
)


@dataclass(slots=True, frozen=True)
class HeaderFooterCollection:
    sections: tuple[SectionProperties, ...]
    story_count: int = 0
    paragraph_count: int = 0
    footnote_separator: NoteSeparatorStory | None = None
    footnote_continuation_separator: NoteSeparatorStory | None = None
    footnote_continuation_notice: NoteSeparatorStory | None = None
    endnote_separator: NoteSeparatorStory | None = None
    endnote_continuation_separator: NoteSeparatorStory | None = None
    endnote_continuation_notice: NoteSeparatorStory | None = None

    @property
    def note_separator_story_count(self) -> int:
        return sum(
            getattr(self, field_name) is not None
            for field_name, _story_name in _NOTE_SEPARATOR_STORIES
        )


def _read_story_cps(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    ccp_headers: int,
    section_count: int,
) -> tuple[int, ...]:
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"PlcfHdd range [{offset}, {offset + size}) exceeds Table stream"
        )
    story_count = 6 + 6 * section_count
    expected_cp_count = story_count + 2
    expected_size = expected_cp_count * 4
    if size != expected_size:
        raise InvalidWordDocument(
            f"PlcfHdd size {size} does not contain {expected_cp_count} CP values "
            f"for {section_count} section(s)"
        )
    cps = struct.unpack_from(f"<{expected_cp_count}I", table_stream, offset)
    story_cps = cps[:-1]  # The final PlcfHdd CP is undefined by MS-DOC.
    if not story_cps or story_cps[0] != 0:
        raise InvalidWordDocument("PlcfHdd does not begin at header-story CP 0")
    for previous, current in zip(story_cps, story_cps[1:]):
        if current < previous:
            raise InvalidWordDocument("PlcfHdd story CP values are decreasing")
    if ccp_headers < 1 or story_cps[-1] != ccp_headers - 1:
        raise InvalidWordDocument(
            "PlcfHdd second-to-last CP does not equal ccpHdd minus one"
        )
    if any(cp >= ccp_headers for cp in story_cps):
        raise InvalidWordDocument("PlcfHdd story CP points beyond the header document")
    return story_cps


def read_header_footer_stories(
    table_stream: bytes,
    piece_table: PieceTable,
    sections: Sequence[SectionProperties],
    *,
    offset: int,
    size: int,
    ccp_headers: int,
    header_story_cp_start: int,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties] | None = None,
    paragraph_properties_at: Callable[[int], ParagraphProperties] | None = None,
    floating_textbox_at: Callable[[int], FloatingTextBox | None] | None = None,
    inline_picture_at: Callable[[int], InlinePicture | None] | None = None,
    floating_picture_at: Callable[[int], FloatingPicture | None] | None = None,
    floating_shape_at: Callable[[int], FloatingShape | None] | None = None,
    field_end_properties_at: (
        Callable[[int], FieldEndProperties | None] | None
    ) = None,
    bookmark_names: Collection[str] | None = None,
    bookmark_boundaries_at: (
        Callable[[int], Sequence[BookmarkStart | BookmarkEnd]] | None
    ) = None,
    style_names: Collection[str] | None = None,
    list_names: Collection[str] | None = None,
    ignored_character_cps: Collection[int] = (),
) -> HeaderFooterCollection:
    """Read non-empty header/footer stories and attach them to their sections."""

    section_values = tuple(sections)
    if ccp_headers == 0 and size == 0:
        return HeaderFooterCollection(section_values)
    if ccp_headers == 0 and size:
        if offset < 0 or size < 0 or offset > len(table_stream) - size:
            raise InvalidWordDocument(
                f"PlcfHdd range [{offset}, {offset + size}) exceeds Table stream"
            )
        story_count = 6 + 6 * len(section_values)
        expected_size = (story_count + 2) * 4
        raw = memoryview(table_stream)[offset : offset + size]
        if size not in (expected_size - 4, expected_size) or any(raw):
            raise InvalidWordDocument(
                "header document and PlcfHdd must either both exist or both be absent"
            )
        report.warning(
            "EMPTY_HEADER_TABLE_REPAIRED",
            "an all-zero PlcfHdd left by a legacy writer was omitted",
            location=SourceLocation(story="headers", stream="Table"),
            cp_count=size // 4,
        )
        return HeaderFooterCollection(section_values)
    if ccp_headers == 0 or size == 0:
        raise InvalidWordDocument(
            "header document and PlcfHdd must either both exist or both be absent"
        )
    header_story_cp_end = header_story_cp_start + ccp_headers
    if header_story_cp_end > piece_table.cp_end:
        raise InvalidWordDocument(
            f"header story range [{header_story_cp_start}, {header_story_cp_end}) "
            f"exceeds Piece Table CP {piece_table.cp_end}"
        )
    story_cps = _read_story_cps(
        table_stream,
        offset=offset,
        size=size,
        ccp_headers=ccp_headers,
        section_count=len(section_values),
    )

    def content_units(
        story_index: int,
        story_name: str,
    ) -> tuple[StoryCharacter, ...] | None:
        relative_start = story_cps[story_index]
        relative_end = story_cps[story_index + 1]
        if relative_start == relative_end:
            return None
        cp_start = header_story_cp_start + relative_start
        cp_end = header_story_cp_start + relative_end
        units = piece_table.extract_characters(
            cp_start,
            cp_end,
            report,
            story=story_name,
        )
        if not units or units[-1].text != "\r" or units[-1].cp_end != cp_end:
            raise InvalidWordDocument(
                f"non-empty PlcfHdd story {story_index} has no guard paragraph mark"
            )
        return units[:-1]

    separator_replacements: dict[str, NoteSeparatorStory] = {}
    for story_index, (field_name, story_name) in enumerate(
        _NOTE_SEPARATOR_STORIES
    ):
        units = content_units(story_index, story_name)
        if units is None:
            continue
        parsed = parse_main_story(
            units,
            report,
            character_properties_at=character_properties_at,
            paragraph_properties_at=paragraph_properties_at,
            floating_textbox_at=floating_textbox_at,
            inline_picture_at=inline_picture_at,
            floating_picture_at=floating_picture_at,
            floating_shape_at=floating_shape_at,
            field_end_properties_at=field_end_properties_at,
            bookmark_boundaries_at=bookmark_boundaries_at,
            bookmark_names=bookmark_names,
            style_names=style_names,
            list_names=list_names,
            ignored_character_cps=ignored_character_cps,
            story_name=story_name,
            note_separator_story=True,
        )
        content_cp_start = header_story_cp_start + story_cps[story_index]
        content_cp_end = header_story_cp_start + story_cps[story_index + 1] - 1
        separator_replacements[field_name] = NoteSeparatorStory(
            cp_start=content_cp_start,
            cp_end=content_cp_end,
            paragraphs=parsed.paragraphs,
            blocks=parsed.blocks,
        )

    parsed_story_count = 0
    paragraph_count = 0
    resolved_sections: list[SectionProperties] = []
    for section_index, section in enumerate(section_values):
        replacements: dict[str, HeaderFooterStory] = {}
        group_start = 6 + 6 * section_index
        for group_index, (field_name, _display_name) in enumerate(
            _STORIES_PER_SECTION
        ):
            story_index = group_start + group_index
            story_name = f"section-{section_index}-{field_name.replace('_', '-')}"
            units = content_units(story_index, story_name)
            if units is None:
                continue
            if not units or units[-1].text != "\r":
                raise InvalidWordDocument(
                    f"non-empty header/footer story {story_index} is not a whole paragraph"
                )
            parsed = parse_main_story(
                units,
                report,
                character_properties_at=character_properties_at,
                paragraph_properties_at=paragraph_properties_at,
                floating_textbox_at=floating_textbox_at,
                inline_picture_at=inline_picture_at,
                floating_picture_at=floating_picture_at,
                floating_shape_at=floating_shape_at,
                field_end_properties_at=field_end_properties_at,
                bookmark_boundaries_at=bookmark_boundaries_at,
                bookmark_names=bookmark_names,
                style_names=style_names,
                list_names=list_names,
                ignored_character_cps=ignored_character_cps,
                story_name=story_name,
            )
            replacements[field_name] = HeaderFooterStory(
                cp_start=units[0].cp_start,
                cp_end=units[-1].cp_end,
                paragraphs=parsed.paragraphs,
                blocks=parsed.blocks,
            )
            parsed_story_count += 1
            paragraph_count += len(parsed.paragraphs)
        resolved_sections.append(replace(section, **replacements))

    return HeaderFooterCollection(
        sections=tuple(resolved_sections),
        story_count=parsed_story_count,
        paragraph_count=paragraph_count,
        **separator_replacements,
    )
