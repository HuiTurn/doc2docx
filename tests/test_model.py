from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    Break,
    BreakType,
    CharacterProperties,
    Document,
    Field,
    Paragraph,
    Symbol,
    Tab,
    TextRun,
    parse_main_story,
)
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


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
        document = parse_main_story(
            "before \x13HYPERLINK https://example.invalid\x14cached\x15 after\r",
            report,
        )
        self.assertEqual(
            document.paragraphs[0].inlines, (TextRun("before cached after"),)
        )
        self.assertEqual(
            [warning.code for warning in report.warnings], ["FIELDS_FLATTENED"]
        )
        self.assertEqual(
            report.warnings[0].details["field_types"],
            {"HYPERLINK": 1},
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

    def test_common_metadata_date_and_statistic_fields_remain_live(self) -> None:
        report = ConversionReport("fixture.doc")
        field_types = (
            "AUTHOR",
            "CREATEDATE",
            "DATE",
            "FILENAME",
            "NUMCHARS",
            "NUMPAGES",
            "NUMWORDS",
            "PAGE",
            "SECTION",
            "SECTIONPAGES",
            "TIME",
            "TITLE",
        )
        story = " ".join(
            f"\x13 {field_type} \\* MERGEFORMAT \x14cached\x15"
            for field_type in field_types
        ) + "\r"

        document = parse_main_story(story, report)

        fields = [
            inline
            for inline in document.paragraphs[0].inlines
            if isinstance(inline, Field)
        ]
        self.assertEqual(len(fields), len(field_types))
        self.assertEqual(
            [field.instruction.strip().split()[0] for field in fields],
            list(field_types),
        )
        self.assertTrue(all(field.has_separator for field in fields))
        self.assertFalse(report.warnings)

    def test_active_external_fields_are_kept_as_cached_text(self) -> None:
        report = ConversionReport("fixture.doc")
        document = parse_main_story(
            'before \x13 DDEAUTO "cmd" "args" \x14cached\x15 after\r',
            report,
        )

        self.assertEqual(
            document.paragraphs[0].inlines,
            (TextRun("before cached after"),),
        )
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["FIELDS_FLATTENED", "ACTIVE_FIELDS_FLATTENED"],
        )
        self.assertEqual(
            report.warnings[1].details["field_types"],
            ["DDEAUTO"],
        )

    def test_resultless_live_field_is_written_without_a_separator(self) -> None:
        report = ConversionReport("fixture.doc")
        parsed = parse_main_story("\x13 DATE \\@ yyyy-MM-dd \x15\r", report)
        field = parsed.paragraphs[0].inlines[0]
        self.assertIsInstance(field, Field)
        assert isinstance(field, Field)
        self.assertFalse(field.has_separator)

        document = Document((Paragraph((field,)),))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "field.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        field_types = [
            element.get(f"{W}fldCharType")
            for element in root.findall(f".//{W}fldChar")
        ]
        self.assertEqual(field_types, ["begin", "end"])
        self.assertFalse(report.warnings)
