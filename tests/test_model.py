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
    NoBreakHyphen,
    Paragraph,
    ParagraphFrameProperties,
    ParagraphProperties,
    ShadingProperties,
    SoftHyphen,
    Symbol,
    Tab,
    TextRun,
    parse_main_story,
)
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentModelTests(unittest.TestCase):
    def test_paragraph_frame_and_shading_are_written_in_schema_order(self) -> None:
        properties = ParagraphProperties(
            keep_lines=True,
            widow_control=True,
            frame=ParagraphFrameProperties(
                horizontal_anchor="page",
                vertical_anchor="text",
                wrap="around",
                drop_cap="margin",
                drop_cap_lines=3,
            ),
            shading=ShadingProperties("clear", "000000", "FFFFFF"),
        )
        document = Document((Paragraph((TextRun("Frame"),), properties),))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "paragraph-frame.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        paragraph_properties = root.find(f"./{W}body/{W}p/{W}pPr")
        assert paragraph_properties is not None
        names = [child.tag.removeprefix(W) for child in paragraph_properties]
        self.assertEqual(names[:4], ["keepLines", "framePr", "widowControl", "shd"])
        frame = paragraph_properties.find(f"{W}framePr")
        assert frame is not None
        self.assertEqual(frame.get(f"{W}dropCap"), "margin")
        self.assertEqual(frame.get(f"{W}lines"), "3")
        self.assertEqual(frame.get(f"{W}hAnchor"), "page")
        self.assertEqual(frame.get(f"{W}vAnchor"), "text")
        self.assertEqual(frame.get(f"{W}wrap"), "around")
        shading = paragraph_properties.find(f"{W}shd")
        assert shading is not None
        self.assertEqual(shading.get(f"{W}val"), "clear")
        self.assertEqual(shading.get(f"{W}color"), "000000")
        self.assertEqual(shading.get(f"{W}fill"), "FFFFFF")

    def test_character_effects_scale_and_emphasis_are_written(self) -> None:
        character = CharacterProperties(
            outline=True,
            shadow=False,
            emboss=True,
            imprint=False,
            scale_percent=125,
            emphasis="underDot",
        )
        document = Document((Paragraph((TextRun("effects", character),)),))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "character-effects.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        run_properties = root.find(f"./{W}body/{W}p/{W}r/{W}rPr")
        assert run_properties is not None
        self.assertIsNotNone(run_properties.find(f"{W}outline"))
        shadow = run_properties.find(f"{W}shadow")
        assert shadow is not None
        self.assertEqual(shadow.get(f"{W}val"), "0")
        self.assertIsNotNone(run_properties.find(f"{W}emboss"))
        imprint = run_properties.find(f"{W}imprint")
        assert imprint is not None
        self.assertEqual(imprint.get(f"{W}val"), "0")
        scale = run_properties.find(f"{W}w")
        assert scale is not None
        self.assertEqual(scale.get(f"{W}val"), "125")
        emphasis = run_properties.find(f"{W}em")
        assert emphasis is not None
        self.assertEqual(emphasis.get(f"{W}val"), "underDot")

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

    def test_revision_ids_are_written_on_native_nodes(self) -> None:
        character = CharacterProperties(
            revision_format_id=0x12345678,
            revision_text_id=0x90ABCDEF,
        )
        document = Document(
            (
                Paragraph(
                    (TextRun("revision text", character),),
                    ParagraphProperties(revision_save_id=0x13572468),
                ),
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "revision-ids.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        paragraph = root.find(f"./{W}body/{W}p")
        assert paragraph is not None
        self.assertEqual(paragraph.get(f"{W}rsidP"), "13572468")
        run = paragraph.find(f"{W}r")
        assert run is not None
        self.assertEqual(run.get(f"{W}rsidRPr"), "12345678")
        self.assertEqual(run.get(f"{W}rsidR"), "90ABCDEF")

    def test_story_control_characters_map_to_ir(self) -> None:
        report = ConversionReport("fixture.doc")
        document = parse_main_story("a\tb\x1ec\x1fd\ve\ff\r", report)
        paragraph = document.paragraphs[0]
        self.assertEqual(
            paragraph.inlines,
            (
                TextRun("a"),
                Tab(),
                TextRun("b"),
                NoBreakHyphen(),
                TextRun("c"),
                SoftHyphen(),
                TextRun("d"),
                Break(BreakType.LINE),
                TextRun("e"),
                Break(BreakType.PAGE),
                TextRun("f"),
            ),
        )

    def test_word_hyphen_controls_are_written_natively(self) -> None:
        document = Document(
            (
                Paragraph(
                    (
                        TextRun("non"),
                        NoBreakHyphen(),
                        TextRun("breaking soft"),
                        SoftHyphen(),
                        TextRun("hyphen"),
                    )
                ),
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "hyphens.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        self.assertEqual(len(root.findall(f".//{W}noBreakHyphen")), 1)
        self.assertEqual(len(root.findall(f".//{W}softHyphen")), 1)

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

    def test_local_reference_sequence_and_style_fields_remain_live(self) -> None:
        report = ConversionReport("local-fields.doc")
        story = " ".join(
            (
                "\x13 NOTEREF Target \\h \x14note\x15",
                "\x13 FTNREF Target \x14note\x15",
                "\x13 SEQ Figure \\* ARABIC \x141\x15",
                '\x13 STYLEREF "Heading 1" \x14Chapter\x15',
                "\x13 LISTNUM CustomOutline \\l 2 \x141.1\x15",
            )
        ) + "\r"

        document = parse_main_story(
            story,
            report,
            bookmark_names={"Target"},
            style_names={"Heading 1"},
            list_names={"CustomOutline"},
        )

        fields = [
            inline
            for inline in document.paragraphs[0].inlines
            if isinstance(inline, Field)
        ]
        self.assertEqual(len(fields), 5)
        self.assertEqual(
            [field.instruction.strip().split()[0] for field in fields],
            ["NOTEREF", "NOTEREF", "SEQ", "STYLEREF", "LISTNUM"],
        )
        self.assertFalse(report.warnings)

    def test_broken_local_fields_and_listnum_remain_cached_text(self) -> None:
        report = ConversionReport("broken-local-fields.doc")
        story = " ".join(
            (
                "\x13 NOTEREF Missing \x14note\x15",
                "\x13 SEQ \\* ARABIC \x141\x15",
                "\x13 STYLEREF MissingStyle \x14heading\x15",
                "\x13 LISTNUM LegalDefault \x141\x15",
            )
        ) + "\r"

        document = parse_main_story(
            story,
            report,
            bookmark_names={"Target"},
            style_names={"Heading 1"},
        )

        self.assertEqual(
            document.paragraphs[0].inlines,
            (TextRun("note 1 heading 1"),),
        )
        self.assertEqual(
            [warning.code for warning in report.warnings],
            [
                "FIELDS_FLATTENED",
                "BROKEN_BOOKMARK_FIELDS_FLATTENED",
                "BROKEN_SEQUENCE_FIELDS_FLATTENED",
                "BROKEN_STYLE_FIELDS_FLATTENED",
                "BROKEN_LISTNUM_FIELDS_FLATTENED",
            ],
        )

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
