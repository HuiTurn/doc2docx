import unittest

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import Break, BreakType, Field, Tab, TextRun, parse_main_story


class DocumentModelTests(unittest.TestCase):
    def test_story_control_characters_map_to_ir(self) -> None:
        report = ConversionReport("fixture.doc")
        document = parse_main_story("a\tb\vc\fd\r", report)
        paragraph = document.paragraphs[0]
        self.assertEqual(
            paragraph.inlines,
            (
                TextRun("a"),
                Tab(),
                TextRun("b"),
                Break(BreakType.LINE),
                TextRun("c"),
                Break(BreakType.PAGE),
                TextRun("d"),
            ),
        )

    def test_fields_are_flattened_to_displayed_result(self) -> None:
        report = ConversionReport("fixture.doc")
        document = parse_main_story("before \x13DATE\x14today\x15 after\r", report)
        self.assertEqual(
            document.paragraphs[0].inlines, (TextRun("before today after"),)
        )
        self.assertEqual(
            [warning.code for warning in report.warnings], ["FIELDS_FLATTENED"]
        )

    def test_page_fields_remain_live_with_their_cached_result(self) -> None:
        report = ConversionReport("fixture.doc")
        document = parse_main_story(
            "before \x13 PAGE \\* MERGEFORMAT \x141\x15 after\r",
            report,
        )
        self.assertEqual(
            document.paragraphs[0].inlines,
            (
                TextRun("before "),
                Field(" PAGE \\* MERGEFORMAT ", (TextRun("1"),)),
                TextRun(" after"),
            ),
        )
        self.assertFalse(report.warnings)
