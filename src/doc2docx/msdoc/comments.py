"""Legacy comment extraction from MS-DOC annotation structures."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import (
    BookmarkEnd,
    BookmarkStart,
    CharacterProperties,
    Comment,
    CommentRangeEnd,
    CommentRangeStart,
    CommentReference,
    FieldEndProperties,
    ParagraphProperties,
    parse_main_story,
)
from .notes import read_note_text_ranges
from .pieces import PieceTable


@dataclass(slots=True, frozen=True)
class _CommentReferenceData:
    cp: int
    initials: str
    author_index: int
    bookmark_tag: int | None


@dataclass(slots=True, frozen=True)
class CommentCollection:
    comments: tuple[Comment, ...] = ()
    references_by_cp: dict[int, CommentReference] | None = None
    boundaries_by_cp: dict[
        int, tuple[CommentRangeStart | CommentRangeEnd, ...]
    ] | None = None

    @property
    def reference_count(self) -> int:
        return len(self.references_by_cp or {})

    @property
    def range_count(self) -> int:
        return sum(
            isinstance(value, CommentRangeStart)
            for values in (self.boundaries_by_cp or {}).values()
            for value in values
        )

    def reference_at(self, cp: int) -> CommentReference | None:
        return (self.references_by_cp or {}).get(cp)

    def boundaries_at(
        self,
        cp: int,
    ) -> Sequence[CommentRangeStart | CommentRangeEnd]:
        return (self.boundaries_by_cp or {}).get(cp, ())


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


def _decode_utf16(value: bytes | memoryview, *, label: str) -> str:
    try:
        return bytes(value).decode("utf-16le")
    except UnicodeDecodeError as exc:
        raise InvalidWordDocument(f"{label} contains invalid UTF-16LE") from exc


def _read_comment_authors(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
) -> tuple[str, ...]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        label="GrpXstAtnOwners",
    )
    authors: list[str] = []
    position = 0
    while position < len(data):
        if position > len(data) - 2:
            raise InvalidWordDocument("GrpXstAtnOwners ends inside an XST length")
        character_count = struct.unpack_from("<H", data, position)[0]
        position += 2
        if character_count >= 56:
            raise InvalidWordDocument(
                "GrpXstAtnOwners contains an author name of 56 or more characters"
            )
        byte_count = character_count * 2
        if position > len(data) - byte_count:
            raise InvalidWordDocument("GrpXstAtnOwners ends inside an author name")
        authors.append(
            _decode_utf16(
                data[position : position + byte_count],
                label="GrpXstAtnOwners",
            )
        )
        position += byte_count
        if len(authors) > 0x7FFF:
            raise InvalidWordDocument("GrpXstAtnOwners contains too many authors")
    if len(set(authors)) != len(authors):
        raise InvalidWordDocument("GrpXstAtnOwners contains duplicate author names")
    return tuple(authors)


def _read_comment_references(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    ccp_text: int,
) -> tuple[_CommentReferenceData, ...]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        label="PlcfandRef",
    )
    if size < 38 or (size - 4) % 34:
        raise InvalidWordDocument(
            f"PlcfandRef size {size} does not describe a whole reference PLC"
        )
    count = (size - 4) // 34
    cp_count = count + 1
    cps = struct.unpack_from(f"<{cp_count}I", data)
    reference_cps = cps[:-1]
    if any(cp >= ccp_text for cp in reference_cps):
        raise InvalidWordDocument("PlcfandRef contains a CP outside the main document")
    if any(
        current <= previous
        for previous, current in zip(reference_cps, reference_cps[1:])
    ):
        raise InvalidWordDocument("PlcfandRef reference CPs are not strictly increasing")

    values: list[_CommentReferenceData] = []
    position = cp_count * 4
    for index, cp in enumerate(reference_cps):
        record = data[position + index * 30 : position + (index + 1) * 30]
        initials_count = struct.unpack_from("<H", record)[0]
        if initials_count > 9:
            raise InvalidWordDocument(
                f"PlcfandRef comment {index} has more than 9 initials characters"
            )
        initials = _decode_utf16(
            record[2 : 2 + initials_count * 2],
            label=f"PlcfandRef comment {index} initials",
        )
        author_index, bits_not_used, flags_not_used = struct.unpack_from(
            "<HHH", record, 20
        )
        bookmark_tag = struct.unpack_from("<I", record, 26)[0]
        if bits_not_used or flags_not_used:
            raise InvalidWordDocument(
                f"PlcfandRef comment {index} has nonzero reserved fields"
            )
        values.append(
            _CommentReferenceData(
                cp=cp,
                initials=initials,
                author_index=author_index,
                bookmark_tag=(None if bookmark_tag == 0xFFFFFFFF else bookmark_tag),
            )
        )
    return tuple(values)


def _read_annotation_tags(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
) -> tuple[int, ...]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        label="SttbfAtnBkmk",
    )
    if size < 6:
        raise InvalidWordDocument("SttbfAtnBkmk is truncated")
    f_extend, count, extra_size = struct.unpack_from("<HHH", data)
    if f_extend != 0xFFFF or extra_size != 10:
        raise InvalidWordDocument(
            "SttbfAtnBkmk must be an extended STTB with 10-byte extras"
        )
    if size != 6 + count * 12:
        raise InvalidWordDocument("SttbfAtnBkmk size does not match its entry count")
    tags: list[int] = []
    position = 6
    for index in range(count):
        string_length = struct.unpack_from("<H", data, position)[0]
        bookmark_class, tag, old_tag = struct.unpack_from("<HII", data, position + 2)
        if string_length != 0:
            raise InvalidWordDocument(
                f"SttbfAtnBkmk entry {index} has a non-empty string"
            )
        if bookmark_class != 0x0100 or old_tag != 0xFFFFFFFF:
            raise InvalidWordDocument(
                f"SttbfAtnBkmk entry {index} is not a valid annotation bookmark"
            )
        tags.append(tag)
        position += 12
    if len(set(tags)) != len(tags):
        raise InvalidWordDocument("SttbfAtnBkmk contains duplicate annotation tags")
    return tuple(tags)


def _read_annotation_ranges(
    table_stream: bytes,
    *,
    ccp_text: int,
    tag_offset: int,
    tag_size: int,
    start_offset: int,
    start_size: int,
    end_offset: int,
    end_size: int,
    report: ConversionReport,
) -> dict[int, tuple[int, int]]:
    sizes = (tag_size, start_size, end_size)
    if not any(sizes):
        return {}
    if not all(sizes):
        raise InvalidWordDocument(
            "SttbfAtnBkmk, PlcfAtnBkf, and PlcfAtnBkl must exist together"
        )
    tags = _read_annotation_tags(
        table_stream,
        offset=tag_offset,
        size=tag_size,
    )
    starts_data = _checked_range(
        table_stream,
        offset=start_offset,
        size=start_size,
        label="PlcfAtnBkf",
    )
    if start_size < 12 or (start_size - 4) % 8:
        raise InvalidWordDocument(
            f"PlcfAtnBkf size {start_size} does not describe a whole bookmark PLC"
        )
    count = (start_size - 4) // 8
    cp_count = count + 1
    start_cps = struct.unpack_from(f"<{cp_count}I", starts_data)
    starts = start_cps[:-1]
    if any(cp > ccp_text for cp in starts) or any(
        current < previous for previous, current in zip(starts, starts[1:])
    ):
        raise InvalidWordDocument("PlcfAtnBkf contains invalid or unsorted CPs")

    end_data = _checked_range(
        table_stream,
        offset=end_offset,
        size=end_size,
        label="PlcfAtnBkl",
    )
    if end_size < 8 or end_size % 4:
        raise InvalidWordDocument("PlcfAtnBkl size does not describe a CP-only PLC")
    end_cps = struct.unpack_from(f"<{end_size // 4}I", end_data)
    ends = end_cps[:-1]
    if any(cp > ccp_text for cp in ends) or any(
        current < previous for previous, current in zip(ends, ends[1:])
    ):
        raise InvalidWordDocument("PlcfAtnBkl contains invalid or unsorted CPs")
    terminal_cp = start_cps[-1]
    if terminal_cp != end_cps[-1] or terminal_cp not in (
        ccp_text + 1,
        ccp_text + 2,
    ):
        raise InvalidWordDocument(
            "annotation bookmark PLCs have invalid or inconsistent terminal CPs"
        )
    if terminal_cp == ccp_text + 2:
        report.warning(
            "COMMENT_BOOKMARK_TERMINAL_CP_REPAIRED",
            "annotation bookmark PLCs use a terminal CP two positions past ccpText",
            location=SourceLocation(story="comments", stream="Table"),
            terminal_cp=terminal_cp,
        )
    if len(tags) != count or len(ends) != count:
        raise InvalidWordDocument(
            "annotation bookmark tables do not contain the same number of entries"
        )

    end_indexes: set[int] = set()
    ranges: dict[int, tuple[int, int]] = {}
    record_position = cp_count * 4
    for index, (tag, cp_start) in enumerate(zip(tags, starts, strict=True)):
        end_index, bkc = struct.unpack_from(
            "<HH", starts_data, record_position + index * 4
        )
        if end_index >= count or end_index in end_indexes:
            raise InvalidWordDocument("PlcfAtnBkf contains an invalid duplicate ibkl")
        end_indexes.add(end_index)
        if bkc & 0x8080:
            raise InvalidWordDocument(
                "annotation bookmark BKC has fPub or fCol set"
            )
        cp_end = ends[end_index]
        if cp_start >= cp_end:
            report.warning(
                "EMPTY_ANNOTATION_BOOKMARK_SKIPPED",
                "an annotation bookmark with an empty main-story range was omitted",
                location=SourceLocation(story="comments", stream="Table"),
                tag=tag,
                cp_start=cp_start,
                cp_end=cp_end,
            )
            continue
        ranges[tag] = (cp_start, cp_end)
    return ranges


def read_comments(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    ccp_text: int,
    ccp_comments: int,
    comment_story_cp_start: int,
    reference_offset: int,
    reference_size: int,
    text_offset: int,
    text_size: int,
    owners_offset: int,
    owners_size: int,
    bookmark_tags_offset: int,
    bookmark_tags_size: int,
    bookmark_starts_offset: int,
    bookmark_starts_size: int,
    bookmark_ends_offset: int,
    bookmark_ends_size: int,
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
) -> CommentCollection:
    """Parse comment bodies, authors, references, and optional range anchors."""

    core_sizes = (reference_size, text_size, owners_size)
    bookmark_sizes = (
        bookmark_tags_size,
        bookmark_starts_size,
        bookmark_ends_size,
    )
    if ccp_comments == 0 and not any(core_sizes):
        if not any(bookmark_sizes):
            return CommentCollection()
        if (
            bookmark_tags_size == 0
            and bookmark_starts_size == 4
            and bookmark_ends_size == 4
        ):
            start_data = _checked_range(
                table_stream,
                offset=bookmark_starts_offset,
                size=bookmark_starts_size,
                label="PlcfAtnBkf",
            )
            end_data = _checked_range(
                table_stream,
                offset=bookmark_ends_offset,
                size=bookmark_ends_size,
                label="PlcfAtnBkl",
            )
            start_terminal = struct.unpack_from("<I", start_data)[0]
            end_terminal = struct.unpack_from("<I", end_data)[0]
            if (
                start_terminal == end_terminal
                and ccp_text <= start_terminal <= ccp_text + 2
            ):
                report.warning(
                    "EMPTY_COMMENT_BOOKMARK_TABLES_REPAIRED",
                    "zero-entry annotation bookmark PLCs without a comment story were omitted",
                    location=SourceLocation(story="comments", stream="Table"),
                    terminal_cp=start_terminal,
                )
                return CommentCollection()
    if ccp_comments == 0 or not all(core_sizes):
        raise InvalidWordDocument(
            "comment document, PlcfandRef, PlcfandTxt, and authors must exist together"
        )
    comment_story_cp_end = comment_story_cp_start + ccp_comments
    if comment_story_cp_end > piece_table.cp_end:
        raise InvalidWordDocument(
            f"comment story range [{comment_story_cp_start}, "
            f"{comment_story_cp_end}) exceeds Piece Table CP {piece_table.cp_end}"
        )

    authors = _read_comment_authors(
        table_stream,
        offset=owners_offset,
        size=owners_size,
    )
    references = _read_comment_references(
        table_stream,
        offset=reference_offset,
        size=reference_size,
        ccp_text=ccp_text,
    )
    text_ranges = read_note_text_ranges(
        table_stream,
        offset=text_offset,
        size=text_size,
        story_length=ccp_comments,
        story_length_name="ccpAtn",
        label="PlcfandTxt",
        story_kind="comment",
    )
    if len(references) != len(text_ranges):
        raise InvalidWordDocument(
            "PlcfandRef reference count does not match PlcfandTxt comment count"
        )
    annotation_ranges = _read_annotation_ranges(
        table_stream,
        ccp_text=ccp_text,
        tag_offset=bookmark_tags_offset,
        tag_size=bookmark_tags_size,
        start_offset=bookmark_starts_offset,
        start_size=bookmark_starts_size,
        end_offset=bookmark_ends_offset,
        end_size=bookmark_ends_size,
        report=report,
    )

    comments: list[Comment] = []
    reference_map: dict[int, CommentReference] = {}
    boundary_lists: dict[int, list[CommentRangeStart | CommentRangeEnd]] = {}
    for comment_id, (reference, text_range) in enumerate(
        zip(references, text_ranges, strict=True)
    ):
        if reference.author_index >= len(authors):
            raise InvalidWordDocument(
                f"PlcfandRef comment {comment_id} has an invalid author index"
            )
        reference_units = piece_table.extract_characters(
            reference.cp,
            reference.cp + 1,
            report,
            story="main-comment-reference",
        )
        reference_properties = (
            character_properties_at(reference.cp)
            if character_properties_at is not None
            else CharacterProperties()
        )
        if len(reference_units) != 1 or reference_units[0].text != "\x05":
            raise InvalidWordDocument(
                f"comment reference at CP {reference.cp} is not 0x05"
            )
        if reference_properties.special is not True:
            raise InvalidWordDocument(
                f"comment reference at CP {reference.cp} has no sprmCFSpec"
            )

        relative_start, relative_end = text_range
        cp_start = comment_story_cp_start + relative_start
        cp_end = comment_story_cp_start + relative_end
        story_name = f"comment-{comment_id}"
        units = piece_table.extract_characters(
            cp_start,
            cp_end,
            report,
            story=story_name,
        )
        marker_indexes = tuple(
            index for index, unit in enumerate(units) if unit.text == "\x05"
        )
        if len(marker_indexes) != 1:
            report.warning(
                "COMMENT_MARKER_MISSING_SKIPPED",
                "a comment body without exactly one annotation marker was omitted",
                location=SourceLocation(story=story_name, stream="WordDocument"),
                comment_id=comment_id,
                marker_count=len(marker_indexes),
            )
            continue

        reference_map[reference.cp] = CommentReference(
            comment_id,
            reference_properties,
        )

        if reference.bookmark_tag is not None:
            annotation_range = annotation_ranges.get(reference.bookmark_tag)
            if annotation_range is None:
                report.warning(
                    "MISSING_ANNOTATION_BOOKMARK_SKIPPED",
                    "a comment referenced a missing or empty annotation bookmark",
                    location=SourceLocation(story="comments", stream="Table"),
                    comment_id=comment_id,
                    bookmark_tag=reference.bookmark_tag,
                )
            else:
                range_start, range_end = annotation_range
                boundary_lists.setdefault(range_start, []).append(
                    CommentRangeStart(comment_id)
                )
                boundary_lists.setdefault(range_end, []).append(
                    CommentRangeEnd(comment_id)
                )

        marker_index = marker_indexes[0]
        marker_cp = units[marker_index].cp_start
        marker_properties = (
            character_properties_at(marker_cp)
            if character_properties_at is not None
            else CharacterProperties()
        )
        if marker_properties.special is not True:
            raise InvalidWordDocument(
                f"PlcfandTxt comment {comment_id} marker has no sprmCFSpec"
            )
        if units[-1].text != "\r" or units[-1].cp_end != cp_end:
            raise InvalidWordDocument(
                f"PlcfandTxt comment {comment_id} does not end in a paragraph mark"
            )
        if marker_index:
            report.warning(
                "COMMENT_MARKER_POSITION_REPAIRED",
                "a comment annotation marker found after visible text was omitted in place",
                location=SourceLocation(
                    story=story_name,
                    cp_start=marker_cp,
                    cp_end=units[marker_index].cp_end,
                ),
                relative_cp=marker_cp - cp_start,
            )
        content_units = units[:marker_index] + units[marker_index + 1 :]
        parsed = parse_main_story(
            content_units,
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
        comments.append(
            Comment(
                comment_id=comment_id,
                author=authors[reference.author_index],
                initials=reference.initials,
                paragraphs=parsed.paragraphs,
                blocks=parsed.blocks,
            )
        )

    # At a shared CP, close existing ranges before opening new ones. Preserve the
    # source order within each class for deterministic output.
    boundaries = {
        cp: tuple(
            sorted(
                values,
                key=lambda value: 0 if isinstance(value, CommentRangeEnd) else 1,
            )
        )
        for cp, values in boundary_lists.items()
    }
    return CommentCollection(
        comments=tuple(comments),
        references_by_cp=reference_map,
        boundaries_by_cp=boundaries,
    )
