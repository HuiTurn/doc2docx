import unittest

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    Break,
    BreakType,
    CharacterProperties,
    Field,
    Symbol,
    Tab,
    TextRun,
    parse_main_story,
)


class DocumentModelTests(unittest.TestCase):
    def test_symbol_character_replaces_its_story_placeholder(self) -> None:
        report = ConversionReport("symbol.doc")
        symbol_properties = CharacterProperties(
            symbol_font="Wingdings",
            symbol_character_code=0xF03A,
        )
        document = parse_main_story(
            "x\r",
            report,
            character_properties_at=(
                lambda cp: symbol_properties if cp == 0 else CharacterProperties()
            ),
        )

        self.assertEqual(
            document.paragraphs[0].inlines,
            (Symbol("Wingdings", 0xF03A),),
        )
        self.assertFalse(report.warnings)

    def test_paragraph_mark_character_formatting_is_retained(self) -> None:
        report = ConversionReport("paragraph-mark.doc")
        mark_properties = CharacterProperties(
            east_asia_font="SimSun",
            complex_script_size_half_points=21,
        )
        document = parse_main_story(
            "text\r",
            report,
            character_properties_at=(
                lambda cp: mark_properties if cp == 4 else CharacterProperties()
            ),
        )

        self.assertEqual(
            document.paragraphs[0].mark_properties,
            mark_properties,
        )

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
