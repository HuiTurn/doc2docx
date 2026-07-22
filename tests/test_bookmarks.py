from pathlib import Path
import struct
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import (
    BookmarkEnd,
    BookmarkStart,
    Document,
    Field,
    FieldEndProperties,
    TextRun,
    parse_main_story,
)
from doc2docx.msdoc.bookmarks import read_bookmarks
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _name_table(names: tuple[str, ...]) -> bytes:
    data = bytearray(struct.pack("<HHH", 0xFFFF, len(names), 0))
    for name in names:
        encoded = name.encode("utf-16le")
        data.extend(struct.pack("<H", len(name)))
        data.extend(encoded)
    return bytes(data)


def _start_table(
    starts: tuple[int, ...],
    end_indexes: tuple[int, ...],
    bkc_values: tuple[int, ...],
    maximum_cp: int,
) -> bytes:
    return struct.pack(f"<{len(starts) + 1}I", *starts, maximum_cp + 1) + b"".join(
        struct.pack("<HH", end_index, bkc)
        for end_index, bkc in zip(end_indexes, bkc_values, strict=True)
    )


def _end_table(ends: tuple[int, ...], maximum_cp: int) -> bytes:
    return struct.pack(f"<{len(ends) + 1}I", *ends, maximum_cp + 1)


def _read(
    names: bytes,
    starts: bytes,
    ends: bytes,
    *,
    main_story_length: int,
    total_story_length: int,
    maximum_bookmark_cp: int | None = None,
    report: ConversionReport | None = None,
    supported_story_ranges: tuple[tuple[str, int, int], ...] | None = None,
):
    offsets = (0, len(names), len(names) + len(starts))
    stream = names + starts + ends
    return read_bookmarks(
        stream,
        names_offset=offsets[0],
        names_size=len(names),
        starts_offset=offsets[1],
        starts_size=len(starts),
        ends_offset=offsets[2],
        ends_size=len(ends),
        main_story_length=main_story_length,
        total_story_length=total_story_length,
        maximum_bookmark_cp=maximum_bookmark_cp,
        report=report or ConversionReport("bookmarks.doc"),
        supported_story_ranges=supported_story_ranges,
    )


class BookmarkTests(unittest.TestCase):
    def test_reads_overlapping_point_and_column_bookmarks(self) -> None:
        names = _name_table(("Outer", "Inner", "Point"))
        # Inner spans table columns [1, 3), which becomes OOXML colFirst=1,
        # colLast=2. End CPs are sorted independently and paired by ibkl.
        column_bkc = 0x8000 | (3 << 8) | 1
        starts = _start_table(
            (0, 1, 3),
            (2, 1, 0),
            (0, column_bkc, 0),
            7,
        )
        ends = _end_table((3, 5, 6), 7)

        bookmarks = _read(
            names,
            starts,
            ends,
            main_story_length=7,
            total_story_length=7,
        )

        self.assertEqual(
            (
                bookmarks.bookmark_count,
                bookmarks.preserved_count,
                bookmarks.column_bookmark_count,
            ),
            (3, 3, 1),
        )
        self.assertEqual(bookmarks.boundaries_at(0), (BookmarkStart(0, "Outer"),))
        self.assertEqual(
            bookmarks.boundaries_at(1),
            (BookmarkStart(1, "Inner", 1, 2),),
        )
        self.assertEqual(
            bookmarks.boundaries_at(3),
            (BookmarkStart(2, "Point"), BookmarkEnd(2)),
        )
        self.assertEqual(bookmarks.boundaries_at(5), (BookmarkEnd(1),))
        self.assertEqual(bookmarks.boundaries_at(6), (BookmarkEnd(0),))

    def test_writes_story_end_bookmark_and_live_ref_field(self) -> None:
        story = "\x13 REF Target \\h \x14cached\x15\r"
        final_cp = len(story)
        boundaries = {
            0: (BookmarkStart(4, "Target"),),
            final_cp: (BookmarkEnd(4),),
        }
        report = ConversionReport("reference.doc")

        parsed = parse_main_story(
            story,
            report,
            bookmark_boundaries_at=lambda cp: boundaries.get(cp, ()),
            bookmark_names={"Target"},
        )

        self.assertIsInstance(parsed.paragraphs[0].inlines[0], BookmarkStart)
        self.assertIsInstance(parsed.paragraphs[0].inlines[1], Field)
        self.assertIsInstance(parsed.paragraphs[0].inlines[2], BookmarkEnd)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "reference.docx"
            write_docx(Document(parsed.paragraphs), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        start = root.find(f".//{W}bookmarkStart")
        end = root.find(f".//{W}bookmarkEnd")
        assert start is not None and end is not None
        self.assertEqual(start.get(f"{W}id"), "4")
        self.assertEqual(start.get(f"{W}name"), "Target")
        self.assertEqual(end.get(f"{W}id"), "4")
        self.assertEqual(root.findtext(f".//{W}instrText"), " REF Target \\h ")

    def test_flattens_ref_to_a_missing_bookmark(self) -> None:
        report = ConversionReport("missing-reference.doc")

        parsed = parse_main_story(
            "before \x13 REF Missing \x14cached\x15 after\r",
            report,
            bookmark_names={"Existing"},
        )

        self.assertEqual(
            parsed.paragraphs[0].inlines,
            (TextRun("before cached after"),),
        )
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["FIELDS_FLATTENED", "BROKEN_BOOKMARK_FIELDS_FLATTENED"],
        )

    def test_moves_a_boundary_inside_field_instructions_outside_the_field(self) -> None:
        story = "A\x13 REF Target \x14cached\x15B\r"
        hidden_cp = story.index("T")
        boundaries = {
            0: (BookmarkStart(2, "Target"),),
            hidden_cp: (BookmarkEnd(2),),
        }
        report = ConversionReport("field-boundary.doc")

        parsed = parse_main_story(
            story,
            report,
            bookmark_boundaries_at=lambda cp: boundaries.get(cp, ()),
            bookmark_names={"Target"},
        )

        markers = [
            inline
            for inline in parsed.paragraphs[0].inlines
            if isinstance(inline, (BookmarkStart, BookmarkEnd))
        ]
        self.assertEqual(markers, [BookmarkStart(2, "Target"), BookmarkEnd(2)])
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["BOOKMARK_BOUNDARY_APPROXIMATED"],
        )

    def test_removes_non_xml_controls_from_live_field_instructions(self) -> None:
        report = ConversionReport("controlled-field.doc")

        parsed = parse_main_story(
            "\x13 REF Target \\h \x01\x14cached\x15\r",
            report,
            bookmark_names={"Target"},
        )

        field = parsed.paragraphs[0].inlines[0]
        self.assertIsInstance(field, Field)
        assert isinstance(field, Field)
        self.assertEqual(field.instruction, " REF Target \\h ")
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["FIELD_INSTRUCTION_CONTROLS_REMOVED"],
        )

    def test_moves_bookmark_markers_out_of_private_field_results(self) -> None:
        story = "\x13 DATE \x14cached\x15\r"
        result_cp = story.index("c")
        end_cp = story.index("\x15")
        boundaries = {
            0: (BookmarkStart(7, "AroundField"),),
            result_cp: (BookmarkEnd(7),),
        }
        end_properties = FieldEndProperties(
            field_type_code=0x1F,
            private_result=True,
            has_separator=True,
        )
        report = ConversionReport("private-bookmark.doc")

        parsed = parse_main_story(
            story,
            report,
            bookmark_boundaries_at=lambda cp: boundaries.get(cp, ()),
            field_end_properties_at=(
                lambda cp: end_properties if cp == end_cp else None
            ),
        )

        markers = [
            inline
            for inline in parsed.paragraphs[0].inlines
            if isinstance(inline, (BookmarkStart, BookmarkEnd))
        ]
        self.assertEqual(
            markers,
            [BookmarkStart(7, "AroundField"), BookmarkEnd(7)],
        )
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["BOOKMARK_BOUNDARY_APPROXIMATED"],
        )

    def test_defers_bookmarks_outside_the_main_story(self) -> None:
        names = _name_table(("HeaderMark",))
        starts = _start_table((6,), (0,), (0,), 8)
        ends = _end_table((7,), 8)
        report = ConversionReport("secondary.doc")

        bookmarks = _read(
            names,
            starts,
            ends,
            main_story_length=5,
            total_story_length=8,
            report=report,
        )

        self.assertEqual(bookmarks.bookmark_count, 1)
        self.assertEqual(bookmarks.preserved_count, 0)
        self.assertFalse(bookmarks.names)
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["SECONDARY_STORY_BOOKMARKS_DEFERRED"],
        )

    def test_preserves_bookmark_wholly_inside_supported_secondary_story(self) -> None:
        names = _name_table(("HeaderMark",))
        starts = _start_table((6,), (0,), (0,), 8)
        ends = _end_table((7,), 8)
        report = ConversionReport("secondary.doc")

        bookmarks = _read(
            names,
            starts,
            ends,
            main_story_length=5,
            total_story_length=8,
            report=report,
            supported_story_ranges=(
                ("main", 0, 5),
                ("headers", 5, 8),
            ),
        )

        self.assertEqual(bookmarks.preserved_count, 1)
        self.assertEqual(bookmarks.names, frozenset(("HeaderMark",)))
        self.assertEqual(
            bookmarks.boundaries_at(6),
            (BookmarkStart(0, "HeaderMark"),),
        )
        self.assertEqual(bookmarks.boundaries_at(7), (BookmarkEnd(0),))
        self.assertFalse(report.warnings)

    def test_accepts_a_document_end_terminal_cp_with_a_diagnostic(self) -> None:
        names = _name_table(("Compatible",))
        starts = struct.pack("<2IHH", 0, 3, 0, 0)
        ends = struct.pack("<2I", 2, 3)
        report = ConversionReport("compatible.doc")

        bookmarks = _read(
            names,
            starts,
            ends,
            main_story_length=3,
            total_story_length=3,
            report=report,
        )

        self.assertEqual(bookmarks.preserved_count, 1)
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["BOOKMARK_TERMINAL_CP_COMPATIBILITY"],
        )

    def test_accepts_a_piece_table_terminator_after_document_stories(self) -> None:
        names = _name_table(("Compatible",))
        starts = struct.pack("<2IHH", 0, 5, 0, 0)
        ends = struct.pack("<2I", 2, 5)
        report = ConversionReport("piece-terminator.doc")

        bookmarks = _read(
            names,
            starts,
            ends,
            main_story_length=3,
            total_story_length=3,
            maximum_bookmark_cp=4,
            report=report,
        )

        self.assertEqual(bookmarks.preserved_count, 1)
        self.assertFalse(report.warnings)

    def test_rejects_inconsistent_or_malformed_bookmark_tables(self) -> None:
        names = _name_table(("One", "Two"))
        valid_starts = _start_table((0, 1), (1, 0), (0, 0), 3)
        valid_ends = _end_table((1, 2), 3)
        duplicate_ibkl = _start_table((0, 1), (0, 0), (0, 0), 3)
        invalid_terminal = valid_ends[:-4] + struct.pack("<I", 3)

        cases = (
            (names, valid_starts, b""),
            (names, duplicate_ibkl, valid_ends),
            (names, valid_starts, invalid_terminal),
        )
        for index, (name_data, start_data, end_data) in enumerate(cases):
            with self.subTest(index=index):
                if not end_data:
                    stream = name_data + start_data
                    with self.assertRaises(InvalidWordDocument):
                        read_bookmarks(
                            stream,
                            names_offset=0,
                            names_size=len(name_data),
                            starts_offset=len(name_data),
                            starts_size=len(start_data),
                            ends_offset=0,
                            ends_size=0,
                            main_story_length=3,
                            total_story_length=3,
                            report=ConversionReport("invalid.doc"),
                        )
                else:
                    with self.assertRaises(InvalidWordDocument):
                        _read(
                            name_data,
                            start_data,
                            end_data,
                            main_story_length=3,
                            total_story_length=3,
                        )


if __name__ == "__main__":
    unittest.main()
