"""Small M2 document intermediate representation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..diagnostics import ConversionReport, SourceLocation


class BreakType(StrEnum):
    LINE = "line"
    PAGE = "page"


@dataclass(slots=True, frozen=True)
class TextRun:
    text: str


@dataclass(slots=True, frozen=True)
class Tab:
    pass


@dataclass(slots=True, frozen=True)
class Break:
    kind: BreakType


Inline = TextRun | Tab | Break


@dataclass(slots=True, frozen=True)
class Paragraph:
    inlines: tuple[Inline, ...]


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


def parse_main_story(text: str, report: ConversionReport) -> Document:
    paragraphs: list[Paragraph] = []
    inlines: list[Inline] = []
    text_buffer: list[str] = []
    unsupported_controls: dict[int, int] = {}
    deferred_markers: dict[str, int] = {}
    flattened_fields = 0
    field_stack: list[bool] = []  # False=instruction, True=result

    def visible() -> bool:
        return all(field_stack)

    def flush_text() -> None:
        if text_buffer:
            text = "".join(text_buffer)
            if inlines and isinstance(inlines[-1], TextRun):
                previous = inlines[-1]
                inlines[-1] = TextRun(previous.text + text)
            else:
                inlines.append(TextRun(text))
            text_buffer.clear()

    def finish_paragraph() -> None:
        flush_text()
        paragraphs.append(Paragraph(tuple(inlines)))
        inlines.clear()

    for cp_offset, character in enumerate(text):
        value = ord(character)

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
            finish_paragraph()
        elif character == "\t":
            flush_text()
            inlines.append(Tab())
        elif character in ("\n", "\v"):
            flush_text()
            inlines.append(Break(BreakType.LINE))
        elif character == "\f":
            flush_text()
            inlines.append(Break(BreakType.PAGE))
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
            text_buffer.append("\uFFFC")
        elif value < 0x20 or not _is_xml_character(character):
            unsupported_controls[value] = unsupported_controls.get(value, 0) + 1
            text_buffer.append("\uFFFD")
        else:
            text_buffer.append(character)

    if text_buffer or inlines or not paragraphs or (text and text[-1] != "\r"):
        finish_paragraph()

    if field_stack:
        report.warning(
            "UNTERMINATED_FIELD",
            "main story contains an unterminated field; its instruction was hidden",
            location=SourceLocation(story="main", cp_start=0, cp_end=len(text)),
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
