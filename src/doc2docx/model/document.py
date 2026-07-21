"""Document intermediate representation with CP-aware direct formatting."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from ..diagnostics import ConversionReport, SourceLocation


class BreakType(StrEnum):
    LINE = "line"
    PAGE = "page"


@dataclass(slots=True, frozen=True)
class CharacterProperties:
    """Direct character properties; ``None`` means not specified by the DOC run."""

    bold: bool | None = None
    italic: bool | None = None
    strike: bool | None = None
    double_strike: bool | None = None
    small_caps: bool | None = None
    caps: bool | None = None
    hidden: bool | None = None
    underline: str | None = None
    color: str | None = None
    highlight: str | None = None
    size_half_points: int | None = None
    vertical_align: str | None = None
    position_half_points: int | None = None


@dataclass(slots=True, frozen=True)
class ParagraphProperties:
    """Direct paragraph properties represented in WordprocessingML units."""

    style_id: int | None = None
    justification: str | None = None
    keep_lines: bool | None = None
    keep_next: bool | None = None
    page_break_before: bool | None = None
    left_indent_twips: int | None = None
    right_indent_twips: int | None = None
    first_line_indent_twips: int | None = None
    space_before_twips: int | None = None
    space_after_twips: int | None = None
    line_spacing_twips: int | None = None
    line_rule: str | None = None


@dataclass(slots=True, frozen=True)
class StoryCharacter:
    """One decoded character and its half-open MS-DOC CP range."""

    text: str
    cp_start: int
    cp_end: int


@dataclass(slots=True, frozen=True)
class TextRun:
    text: str
    properties: CharacterProperties = field(default_factory=CharacterProperties)


@dataclass(slots=True, frozen=True)
class Tab:
    properties: CharacterProperties = field(default_factory=CharacterProperties)


@dataclass(slots=True, frozen=True)
class Break:
    kind: BreakType
    properties: CharacterProperties = field(default_factory=CharacterProperties)


Inline = TextRun | Tab | Break


@dataclass(slots=True, frozen=True)
class Paragraph:
    inlines: tuple[Inline, ...]
    properties: ParagraphProperties = field(default_factory=ParagraphProperties)


@dataclass(slots=True, frozen=True)
class Document:
    paragraphs: tuple[Paragraph, ...]


def _is_xml_character(character: str) -> bool:
    value = ord(character)
    return (
        value in (0x09, 0x0A, 0x0D)
        or 0x20 <= value <= 0xD7FF
        or 0xE000 <= value <= 0xFFFD
        or 0x10000 <= value <= 0x10FFFF
    ) and value not in (0xFFFE, 0xFFFF)


def parse_main_story(
    text: str | Sequence[StoryCharacter],
    report: ConversionReport,
    *,
    character_properties_at: Callable[[int], CharacterProperties] | None = None,
    paragraph_properties_at: Callable[[int], ParagraphProperties] | None = None,
) -> Document:
    if isinstance(text, str):
        characters = tuple(
            StoryCharacter(character, cp, cp + 1)
            for cp, character in enumerate(text)
        )
    else:
        characters = tuple(text)

    default_character_properties = CharacterProperties()
    default_paragraph_properties = ParagraphProperties()

    paragraphs: list[Paragraph] = []
    inlines: list[Inline] = []
    text_buffer: list[str] = []
    text_properties = default_character_properties
    unsupported_controls: dict[int, int] = {}
    deferred_markers: dict[str, int] = {}
    flattened_fields = 0
    field_stack: list[bool] = []  # False=instruction, True=result

    def visible() -> bool:
        return all(field_stack)

    def flush_text() -> None:
        if text_buffer:
            buffered_text = "".join(text_buffer)
            if (
                inlines
                and isinstance(inlines[-1], TextRun)
                and inlines[-1].properties == text_properties
            ):
                previous = inlines[-1]
                inlines[-1] = TextRun(
                    previous.text + buffered_text,
                    previous.properties,
                )
            else:
                inlines.append(TextRun(buffered_text, text_properties))
            text_buffer.clear()

    def append_text(character: str, properties: CharacterProperties) -> None:
        nonlocal text_properties
        if text_buffer and properties != text_properties:
            flush_text()
        text_properties = properties
        text_buffer.append(character)

    def finish_paragraph(properties: ParagraphProperties) -> None:
        flush_text()
        paragraphs.append(Paragraph(tuple(inlines), properties))
        inlines.clear()

    for unit in characters:
        character = unit.text
        cp_offset = unit.cp_start
        value = ord(character)
        character_properties = (
            character_properties_at(cp_offset)
            if character_properties_at is not None
            else default_character_properties
        )

        if value == 0x13:  # field begin
            flush_text()
            field_stack.append(False)
            flattened_fields += 1
            continue
        if value == 0x14 and field_stack:  # field separator
            flush_text()
            field_stack[-1] = True
            continue
        if value == 0x15 and field_stack:  # field end
            flush_text()
            field_stack.pop()
            continue
        if not visible():
            continue

        if character == "\r":
            paragraph_properties = (
                paragraph_properties_at(cp_offset)
                if paragraph_properties_at is not None
                else default_paragraph_properties
            )
            finish_paragraph(paragraph_properties)
        elif character == "\t":
            flush_text()
            inlines.append(Tab(character_properties))
        elif character in ("\n", "\v"):
            flush_text()
            inlines.append(Break(BreakType.LINE, character_properties))
        elif character == "\f":
            flush_text()
            inlines.append(Break(BreakType.PAGE, character_properties))
            deferred_markers["BREAK_KIND_APPROXIMATED"] = (
                deferred_markers.get("BREAK_KIND_APPROXIMATED", 0) + 1
            )
        elif value in (0x01, 0x02, 0x07):
            marker_code = {
                0x01: "OBJECT_ANCHOR_DEFERRED",
                0x02: "NOTE_REFERENCE_DEFERRED",
                0x07: "TABLE_MARKER_DEFERRED",
            }[value]
            deferred_markers[marker_code] = deferred_markers.get(marker_code, 0) + 1
            append_text("\uFFFC", character_properties)
        elif value < 0x20 or not _is_xml_character(character):
            unsupported_controls[value] = unsupported_controls.get(value, 0) + 1
            append_text("\uFFFD", character_properties)
        else:
            append_text(character, character_properties)

    if (
        text_buffer
        or inlines
        or not paragraphs
        or (characters and characters[-1].text != "\r")
    ):
        paragraph_cp = characters[-1].cp_start if characters else 0
        paragraph_properties = (
            paragraph_properties_at(paragraph_cp)
            if paragraph_properties_at is not None
            else default_paragraph_properties
        )
        finish_paragraph(paragraph_properties)

    if field_stack:
        report.warning(
            "UNTERMINATED_FIELD",
            "main story contains an unterminated field; its instruction was hidden",
            location=SourceLocation(
                story="main",
                cp_start=characters[0].cp_start if characters else 0,
                cp_end=characters[-1].cp_end if characters else 0,
            ),
            open_field_count=len(field_stack),
        )
    if flattened_fields:
        report.warning(
            "FIELDS_FLATTENED",
            "field structures were flattened to their displayed result in M2",
            field_count=flattened_fields,
        )
    for codepoint, count in sorted(unsupported_controls.items()):
        report.warning(
            "UNSUPPORTED_CONTROL_CHARACTER",
            f"unsupported control character U+{codepoint:04X} was replaced",
            location=SourceLocation(story="main"),
            count=count,
        )
    deferred_messages = {
        "BREAK_KIND_APPROXIMATED": (
            "page/section break was emitted as a page break because section parsing "
            "is deferred beyond M2"
        ),
        "OBJECT_ANCHOR_DEFERRED": (
            "picture or object anchor was emitted as an object replacement character"
        ),
        "NOTE_REFERENCE_DEFERRED": (
            "note reference was emitted as an object replacement character"
        ),
        "TABLE_MARKER_DEFERRED": (
            "table marker was emitted as an object replacement character"
        ),
    }
    for code, count in sorted(deferred_markers.items()):
        report.warning(
            code,
            deferred_messages[code],
            location=SourceLocation(story="main"),
            count=count,
        )

    return Document(tuple(paragraphs))
