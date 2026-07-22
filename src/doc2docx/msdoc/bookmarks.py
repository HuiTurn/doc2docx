"""Standard MS-DOC bookmark extraction from SttbfBkmk/Plcfbkf/Plcfbkl."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import BookmarkEnd, BookmarkStart


BookmarkBoundary = BookmarkStart | BookmarkEnd


@dataclass(slots=True, frozen=True)
class _BookmarkRecord:
    bookmark_id: int
    name: str
    cp_start: int
    cp_end: int
    column_first: int | None = None
    column_last: int | None = None


@dataclass(slots=True, frozen=True)
class BookmarkCollection:
    """Validated standard bookmarks that can be emitted in supported stories."""

    boundaries_by_cp: Mapping[int, tuple[BookmarkBoundary, ...]]
    names: frozenset[str] = frozenset()
    bookmark_count: int = 0
    preserved_count: int = 0
    column_bookmark_count: int = 0

    def boundaries_at(self, cp: int) -> Sequence[BookmarkBoundary]:
        return self.boundaries_by_cp.get(cp, ())


def _checked_range(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    structure: str,
) -> memoryview:
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"{structure} range [{offset}, {offset + size}) exceeds Table stream"
        )
    return memoryview(table_stream)[offset : offset + size]


def _is_xml_character(character: str) -> bool:
    value = ord(character)
    return (
        value in (0x09, 0x0A, 0x0D)
        or 0x20 <= value <= 0xD7FF
        or 0xE000 <= value <= 0xFFFD
        or 0x10000 <= value <= 0x10FFFF
    ) and value not in (0xFFFE, 0xFFFF)


def _read_names(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
) -> tuple[str, ...]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure="SttbfBkmk",
    )
    if len(data) < 6:
        raise InvalidWordDocument("SttbfBkmk is shorter than its header")
    f_extend, count, extra_size = struct.unpack_from("<HHH", data)
    if f_extend != 0xFFFF:
        raise InvalidWordDocument("SttbfBkmk is not an extended string table")
    if count > 0x3FFB:
        raise InvalidWordDocument("SttbfBkmk contains too many bookmark names")
    if extra_size != 0:
        raise InvalidWordDocument("SttbfBkmk has unexpected extra string data")

    names: list[str] = []
    position = 6
    for index in range(count):
        if position > len(data) - 2:
            raise InvalidWordDocument(
                f"SttbfBkmk entry {index} has no character count"
            )
        character_count = struct.unpack_from("<H", data, position)[0]
        position += 2
        if character_count == 0 or character_count > 40:
            raise InvalidWordDocument(
                f"SttbfBkmk entry {index} has an invalid name length"
            )
        byte_count = character_count * 2
        if position > len(data) - byte_count:
            raise InvalidWordDocument(
                f"SttbfBkmk entry {index} ends outside the string table"
            )
        try:
            name = bytes(data[position : position + byte_count]).decode(
                "utf-16le"
            )
        except UnicodeDecodeError as exc:
            raise InvalidWordDocument(
                f"SttbfBkmk entry {index} contains invalid UTF-16LE"
            ) from exc
        if any(not _is_xml_character(character) for character in name):
            raise InvalidWordDocument(
                f"SttbfBkmk entry {index} contains a non-XML character"
            )
        names.append(name)
        position += byte_count
    if position != len(data):
        raise InvalidWordDocument("SttbfBkmk has trailing bytes")
    if len(set(names)) != len(names):
        raise InvalidWordDocument("SttbfBkmk contains duplicate bookmark names")
    return tuple(names)


def _read_start_records(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    expected_count: int,
    maximum_cp: int,
) -> tuple[tuple[tuple[int, int, int], ...], int]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure="Plcfbkf",
    )
    if size < 4 or (size - 4) % 8:
        raise InvalidWordDocument(
            f"Plcfbkf size {size} does not describe 4-byte FBKF elements"
        )
    count = (size - 4) // 8
    if count != expected_count:
        raise InvalidWordDocument(
            "SttbfBkmk and Plcfbkf contain different numbers of entries"
        )
    cps = struct.unpack_from(f"<{count + 1}I", data)
    starts = cps[:-1]
    if any(current < previous for previous, current in zip(starts, starts[1:])):
        raise InvalidWordDocument("Plcfbkf start CP values are decreasing")
    if any(cp > maximum_cp for cp in starts) or cps[-1] not in (
        maximum_cp,
        maximum_cp + 1,
    ):
        raise InvalidWordDocument("Plcfbkf has an invalid bookmark or terminal CP")

    records: list[tuple[int, int, int]] = []
    end_indexes: set[int] = set()
    data_offset = 4 * (count + 1)
    for index, cp_start in enumerate(starts):
        end_index, bkc = struct.unpack_from("<HH", data, data_offset + index * 4)
        if end_index >= count or end_index in end_indexes:
            raise InvalidWordDocument(
                f"Plcfbkf FBKF {index} has an invalid or duplicate ibkl"
            )
        end_indexes.add(end_index)
        if bkc & 0x0080:
            raise InvalidWordDocument(f"Plcfbkf FBKF {index} has fPub enabled")
        column_first = bkc & 0x007F
        column_limit = (bkc >> 8) & 0x003F
        is_column = bool(bkc & 0x8000)
        if is_column and column_first >= column_limit:
            raise InvalidWordDocument(
                f"Plcfbkf FBKF {index} has an invalid table-column range"
            )
        records.append((cp_start, end_index, bkc))
    return tuple(records), cps[-1]


def _read_end_cps(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    expected_count: int,
    maximum_cp: int,
) -> tuple[tuple[int, ...], int]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        structure="Plcfbkl",
    )
    if size != 4 * (expected_count + 1):
        raise InvalidWordDocument(
            "Plcfbkl size does not match the standard bookmark count"
        )
    cps = struct.unpack_from(f"<{expected_count + 1}I", data)
    ends = cps[:-1]
    if any(current < previous for previous, current in zip(ends, ends[1:])):
        raise InvalidWordDocument("Plcfbkl end CP values are decreasing")
    if any(cp > maximum_cp for cp in ends) or cps[-1] not in (
        maximum_cp,
        maximum_cp + 1,
    ):
        raise InvalidWordDocument("Plcfbkl has an invalid bookmark or terminal CP")
    return ends, cps[-1]


def _build_boundaries(
    records: Sequence[_BookmarkRecord],
) -> dict[int, tuple[BookmarkBoundary, ...]]:
    starts: dict[int, list[_BookmarkRecord]] = {}
    ends: dict[int, list[_BookmarkRecord]] = {}
    for record in records:
        starts.setdefault(record.cp_start, []).append(record)
        ends.setdefault(record.cp_end, []).append(record)

    boundaries: dict[int, tuple[BookmarkBoundary, ...]] = {}
    for cp in sorted(set(starts) | set(ends)):
        values: list[BookmarkBoundary] = []
        zero_length_ids = {
            record.bookmark_id
            for record in starts.get(cp, ())
            if record.cp_end == cp
        }
        for record in sorted(ends.get(cp, ()), key=lambda value: value.bookmark_id):
            if record.bookmark_id not in zero_length_ids:
                values.append(BookmarkEnd(record.bookmark_id))
        for record in sorted(starts.get(cp, ()), key=lambda value: value.bookmark_id):
            values.append(
                BookmarkStart(
                    bookmark_id=record.bookmark_id,
                    name=record.name,
                    column_first=record.column_first,
                    column_last=record.column_last,
                )
            )
            if record.bookmark_id in zero_length_ids:
                values.append(BookmarkEnd(record.bookmark_id))
        boundaries[cp] = tuple(values)
    return boundaries


def read_bookmarks(
    table_stream: bytes,
    *,
    names_offset: int,
    names_size: int,
    starts_offset: int,
    starts_size: int,
    ends_offset: int,
    ends_size: int,
    main_story_length: int,
    total_story_length: int,
    maximum_bookmark_cp: int | None = None,
    report: ConversionReport,
    supported_story_ranges: Sequence[tuple[str, int, int]] | None = None,
) -> BookmarkCollection:
    """Read standard bookmarks and retain ranges wholly in supported stories."""

    sizes = (names_size, starts_size, ends_size)
    if not any(sizes):
        return BookmarkCollection({})
    if not all(sizes):
        raise InvalidWordDocument(
            "SttbfBkmk, Plcfbkf, and Plcfbkl must exist together"
        )
    if main_story_length < 0 or total_story_length < main_story_length:
        raise InvalidWordDocument("FIB contains inconsistent document story lengths")
    bookmark_cp_limit = (
        total_story_length
        if maximum_bookmark_cp is None
        else maximum_bookmark_cp
    )
    if bookmark_cp_limit < total_story_length:
        raise InvalidWordDocument(
            "bookmark CP limit precedes the end of the document stories"
        )

    names = _read_names(
        table_stream,
        offset=names_offset,
        size=names_size,
    )
    start_records, start_terminal_cp = _read_start_records(
        table_stream,
        offset=starts_offset,
        size=starts_size,
        expected_count=len(names),
        maximum_cp=bookmark_cp_limit,
    )
    end_cps, end_terminal_cp = _read_end_cps(
        table_stream,
        offset=ends_offset,
        size=ends_size,
        expected_count=len(names),
        maximum_cp=bookmark_cp_limit,
    )
    if start_terminal_cp != end_terminal_cp:
        raise InvalidWordDocument(
            "Plcfbkf and Plcfbkl use different terminal CP values"
        )
    if start_terminal_cp == bookmark_cp_limit:
        report.warning(
            "BOOKMARK_TERMINAL_CP_COMPATIBILITY",
            "bookmark PLC terminal CP uses the document end instead of one past it",
            location=SourceLocation(story="document", stream="Table"),
            terminal_cp=start_terminal_cp,
        )

    records: list[_BookmarkRecord] = []
    deferred_count = 0
    column_count = 0
    story_ranges = tuple(
        supported_story_ranges or (("main", 0, main_story_length),)
    )
    for story_name, cp_start, cp_end in story_ranges:
        if cp_start < 0 or cp_end < cp_start or cp_end > total_story_length:
            raise InvalidWordDocument(
                f"bookmark story range {story_name!r} [{cp_start}, {cp_end}) is invalid"
            )
    for bookmark_id, (name, start_record) in enumerate(
        zip(names, start_records, strict=True)
    ):
        cp_start, end_index, bkc = start_record
        cp_end = end_cps[end_index]
        if cp_start > cp_end:
            raise InvalidWordDocument(
                f"standard bookmark {bookmark_id} begins after it ends"
            )
        contained_story = next(
            (
                story_name
                for story_name, story_start, story_end in story_ranges
                if story_start <= cp_start <= cp_end <= story_end
            ),
            None,
        )
        if contained_story is None:
            deferred_count += 1
            continue
        is_column = bool(bkc & 0x8000)
        column_first = bkc & 0x007F if is_column else None
        column_last = ((bkc >> 8) & 0x003F) - 1 if is_column else None
        column_count += is_column
        records.append(
            _BookmarkRecord(
                bookmark_id=bookmark_id,
                name=name,
                cp_start=cp_start,
                cp_end=cp_end,
                column_first=column_first,
                column_last=column_last,
            )
        )

    if deferred_count:
        report.warning(
            "SECONDARY_STORY_BOOKMARKS_DEFERRED",
            "bookmarks in unsupported stories or crossing story boundaries were not emitted",
            location=SourceLocation(story="document"),
            bookmark_count=deferred_count,
        )
    return BookmarkCollection(
        boundaries_by_cp=_build_boundaries(records),
        names=frozenset(record.name for record in records),
        bookmark_count=len(names),
        preserved_count=len(records),
        column_bookmark_count=column_count,
    )
