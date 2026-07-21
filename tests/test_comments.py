import struct
import unittest
from unittest.mock import Mock

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.msdoc.comments import read_comments


def _read_empty_comments(
    table_stream: bytes,
    report: ConversionReport,
    *,
    starts_size: int,
    ends_size: int,
):
    return read_comments(
        table_stream,
        Mock(cp_end=18),
        ccp_text=18,
        ccp_comments=0,
        comment_story_cp_start=18,
        reference_offset=0,
        reference_size=0,
        text_offset=0,
        text_size=0,
        owners_offset=0,
        owners_size=0,
        bookmark_tags_offset=0,
        bookmark_tags_size=0,
        bookmark_starts_offset=0,
        bookmark_starts_size=starts_size,
        bookmark_ends_offset=4,
        bookmark_ends_size=ends_size,
        report=report,
    )


class CommentCompatibilityTests(unittest.TestCase):
    def test_zero_entry_annotation_bookmark_plcs_are_omitted(self) -> None:
        report = ConversionReport("empty-comment-bookmarks.doc")

        comments = _read_empty_comments(
            struct.pack("<II", 20, 20),
            report,
            starts_size=4,
            ends_size=4,
        )

        self.assertEqual(comments.comments, ())
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["EMPTY_COMMENT_BOOKMARK_TABLES_REPAIRED"],
        )

    def test_inconsistent_empty_annotation_bookmark_plcs_are_rejected(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            _read_empty_comments(
                struct.pack("<II", 20, 19),
                ConversionReport("invalid-comment-bookmarks.doc"),
                starts_size=4,
                ends_size=4,
            )

        with self.assertRaises(InvalidWordDocument):
            _read_empty_comments(
                struct.pack("<II", 20, 20),
                ConversionReport("partial-comment-bookmarks.doc"),
                starts_size=4,
                ends_size=0,
            )


if __name__ == "__main__":
    unittest.main()
