"""Header/footer story extraction and section association from PlcfHdd."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import (
    CharacterProperties,
    FloatingPicture,
    FloatingTextBox,
    FieldEndProperties,
    HeaderFooterStory,
    InlinePicture,
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


@dataclass(slots=True, frozen=True)
class HeaderFooterCollection:
    sections: tuple[SectionProperties, ...]
    story_count: int = 0
    paragraph_count: int = 0


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
    field_end_properties_at: (
        Callable[[int], FieldEndProperties | None] | None
    ) = None,
    bookmark_names: Collection[str] | None = None,
    style_names: Collection[str] | None = None,
) -> HeaderFooterCollection:
    """Read non-empty header/footer stories and attach them to their sections."""

    section_values = tuple(sections)
    if ccp_headers == 0 and size == 0:
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

    nonempty_separators = 0
    for story_index in range(6):
        if content_units(story_index, f"note-separator-{story_index}") is not None:
            nonempty_separators += 1
    if nonempty_separators:
        report.warning(
            "NOTE_SEPARATOR_STORIES_DEFERRED",
            "footnote or endnote separator stories are not yet emitted",
            location=SourceLocation(story="headers"),
            story_count=nonempty_separators,
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
                field_end_properties_at=field_end_properties_at,
                bookmark_names=bookmark_names,
                style_names=style_names,
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
    )
