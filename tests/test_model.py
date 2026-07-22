from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    BorderProperties,
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
    TableBorders,
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
                horizontal_position_twips=719,
                vertical_alignment="center",
                width_twips=1440,
                height_twips=720,
                height_rule="atLeast",
                horizontal_space_twips=240,
                vertical_space_twips=120,
                anchor_locked=True,
                text_direction="tbRlV",
                drop_cap="margin",
                drop_cap_lines=3,
            ),
            shading=ShadingProperties("clear", "000000", "FFFFFF"),
            borders=TableBorders(
                between=BorderProperties("single", 8, "112233")
            ),
            text_alignment="baseline",
            mirror_indents=True,
            textbox_tight_wrap="firstAndLastLine",
            left_indent_chars=250,
            right_indent_chars=125,
            first_line_indent_chars=-75,
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
        self.assertEqual(
            names[:5],
            ["keepLines", "framePr", "widowControl", "pBdr", "shd"],
        )
        frame = paragraph_properties.find(f"{W}framePr")
        assert frame is not None
        self.assertEqual(frame.get(f"{W}dropCap"), "margin")
        self.assertEqual(frame.get(f"{W}lines"), "3")
        self.assertEqual(frame.get(f"{W}hAnchor"), "page")
        self.assertEqual(frame.get(f"{W}vAnchor"), "text")
        self.assertEqual(frame.get(f"{W}wrap"), "around")
        self.assertEqual(frame.get(f"{W}x"), "719")
        self.assertEqual(frame.get(f"{W}yAlign"), "center")
        self.assertEqual(frame.get(f"{W}w"), "1440")
        self.assertEqual(frame.get(f"{W}h"), "720")
        self.assertEqual(frame.get(f"{W}hRule"), "atLeast")
        self.assertEqual(frame.get(f"{W}hSpace"), "240")
        self.assertEqual(frame.get(f"{W}vSpace"), "120")
        self.assertEqual(frame.get(f"{W}anchorLock"), "1")
        self.assertEqual(frame.get(f"{W}vert"), "tbRlV")
        shading = paragraph_properties.find(f"{W}shd")
        assert shading is not None
        self.assertEqual(shading.get(f"{W}val"), "clear")
        self.assertEqual(shading.get(f"{W}color"), "000000")
        self.assertEqual(shading.get(f"{W}fill"), "FFFFFF")
        between = paragraph_properties.find(f"{W}pBdr/{W}between")
        assert between is not None
        self.assertEqual(between.get(f"{W}color"), "112233")
        self.assertEqual(
            paragraph_properties.find(f"{W}textAlignment").get(f"{W}val"),  # type: ignore[union-attr]
            "baseline",
        )
        self.assertIsNotNone(paragraph_properties.find(f"{W}mirrorIndents"))
        self.assertEqual(
            paragraph_properties.find(f"{W}textboxTightWrap").get(f"{W}val"),  # type: ignore[union-attr]
            "firstAndLastLine",
        )
        indentation = paragraph_properties.find(f"{W}ind")
        assert indentation is not None
        self.assertEqual(indentation.get(f"{W}leftChars"), "250")
        self.assertEqual(indentation.get(f"{W}rightChars"), "125")
        self.assertEqual(indentation.get(f"{W}hangingChars"), "75")

    def test_character_effects_scale_and_emphasis_are_written(self) -> None:
        character = CharacterProperties(
            outline=True,
            shadow=False,
            emboss=True,
            imprint=False,
            web_hidden=True,
            special_vanish=True,
            text_effect="antsBlack",
            bidirectional=True,
            complex_script=True,
            kerning_half_points=24,
            language="en-US",
            scale_percent=125,
            fit_text_width_twips=1440,
            fit_text_id=7,
            east_asian_vertical=True,
            east_asian_combine=True,
            east_asian_combine_brackets="round",
            east_asian_vertical_compress=True,
            east_asian_layout_id=9,
            emphasis="underDot",
            underline="single",
            underline_color="112233",
            shading=ShadingProperties("solid", "FF0000", "00FF00"),
            border=BorderProperties("single", 8, "0000FF"),
        )
        document = Document((Paragraph((TextRun("effects", character),)),))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "character-effects.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        run_properties = root.find(f"./{W}body/{W}p/{W}r/{W}rPr")
        assert run_properties is not None
        names = [child.tag.removeprefix(W) for child in run_properties]
        self.assertLess(names.index("kern"), names.index("fitText"))
        self.assertLess(names.index("shd"), names.index("fitText"))
        self.assertLess(names.index("lang"), names.index("eastAsianLayout"))
        self.assertLess(names.index("eastAsianLayout"), names.index("specVanish"))
        self.assertIsNotNone(run_properties.find(f"{W}outline"))
        shadow = run_properties.find(f"{W}shadow")
        assert shadow is not None
        self.assertEqual(shadow.get(f"{W}val"), "0")
        self.assertIsNotNone(run_properties.find(f"{W}emboss"))
        imprint = run_properties.find(f"{W}imprint")
        assert imprint is not None
        self.assertEqual(imprint.get(f"{W}val"), "0")
        self.assertIsNotNone(run_properties.find(f"{W}webHidden"))
        self.assertIsNotNone(run_properties.find(f"{W}specVanish"))
        self.assertEqual(
            run_properties.find(f"{W}effect").get(f"{W}val"),  # type: ignore[union-attr]
            "antsBlack",
        )
        self.assertIsNotNone(run_properties.find(f"{W}rtl"))
        self.assertIsNotNone(run_properties.find(f"{W}cs"))
        scale = run_properties.find(f"{W}w")
        assert scale is not None
        self.assertEqual(scale.get(f"{W}val"), "125")
        fit_text = run_properties.find(f"{W}fitText")
        assert fit_text is not None
        self.assertEqual(fit_text.get(f"{W}val"), "1440")
        self.assertEqual(fit_text.get(f"{W}id"), "7")
        east_asian_layout = run_properties.find(f"{W}eastAsianLayout")
        assert east_asian_layout is not None
        self.assertEqual(east_asian_layout.get(f"{W}vert"), "1")
        self.assertEqual(east_asian_layout.get(f"{W}combine"), "1")
        self.assertEqual(east_asian_layout.get(f"{W}combineBrackets"), "round")
        self.assertEqual(east_asian_layout.get(f"{W}vertCompress"), "1")
        self.assertEqual(east_asian_layout.get(f"{W}id"), "9")
        underline = run_properties.find(f"{W}u")
        assert underline is not None
        self.assertEqual(underline.get(f"{W}color"), "112233")
        shading = run_properties.find(f"{W}shd")
        assert shading is not None
        self.assertEqual(shading.get(f"{W}fill"), "00FF00")
        border = run_properties.find(f"{W}bdr")
        assert border is not None
        self.assertEqual(border.get(f"{W}color"), "0000FF")
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

    def test_line_break_clear_side_is_written(self) -> None:
        document = Document(
            (
                Paragraph(
                    (
                        Break(
                            BreakType.LINE,
                            CharacterProperties(line_break_clear="all"),
                        ),
                    )
                ),
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "clear-line-break.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        line_break = root.find(f"./{W}body/{W}p/{W}r/{W}br")
        assert line_break is not None
        self.assertEqual(line_break.get(f"{W}clear"), "all")

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

    def test_safe_hyperlink_fields_remain_live_with_their_cached_result(self) -> None:
        report = ConversionReport("fixture.doc")
        document = parse_main_story(
            "before \x13HYPERLINK https://example.invalid\x14cached\x15 after\r",
            report,
        )
        self.assertEqual(
            document.paragraphs[0].inlines,
            (
                TextRun("before "),
                Field("HYPERLINK https://example.invalid", (TextRun("cached"),)),
                TextRun(" after"),
            ),
        )
        self.assertFalse(report.warnings)

    def test_unsafe_hyperlink_fields_are_flattened_to_displayed_result(self) -> None:
        report = ConversionReport("fixture.doc")
        document = parse_main_story(
            "before \x13HYPERLINK file:///private.doc\x14cached\x15 after\r",
            report,
        )
        self.assertEqual(
            document.paragraphs[0].inlines, (TextRun("before cached after"),)
        )
        self.assertEqual([warning.code for warning in report.warnings], ["FIELDS_FLATTENED"])

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

    def test_local_expression_and_automatic_number_fields_remain_live(self) -> None:
        report = ConversionReport("local-fields.doc")
        document = parse_main_story(
            "".join(
                (
                    "\x13 EQ \\f(1,2) \\* ROMAN \x14II\x15 ",
                    "\x13 QUOTE \\\"literal\\\" \x14literal\x15 ",
                    "\x13 SYMBOL 169 \\f Symbol \x14©\x15 ",
                    "\x13 =SUM(ABOVE) \\# 0.00 \x142.00\x15 ",
                    "\x13 AUTONUMOUT \x14Article I\x15\r",
                )
            ),
            report,
        )

        fields = [
            inline
            for inline in document.paragraphs[0].inlines
            if isinstance(inline, Field)
        ]
        self.assertEqual(
            [field.instruction for field in fields],
            [
                " EQ \\f(1,2) \\* ROMAN ",
                ' QUOTE \\\"literal\\\" ',
                " SYMBOL 169 \\f Symbol ",
                " =SUM(ABOVE) \\# 0.00 ",
                " AUTONUMOUT ",
            ],
        )
        self.assertFalse(report.warnings)

    def test_table_of_contents_field_remains_live(self) -> None:
        report = ConversionReport("toc.doc")
        document = parse_main_story(
            "\x13 TOC \\o \\\"1-3\\\" \\h \\z \\u \x14Heading\t1\x15\r",
            report,
        )

        self.assertEqual(
            document.paragraphs[0].inlines,
            (
                Field(
                    ' TOC \\o \\\"1-3\\\" \\h \\z \\u ',
                    (TextRun("Heading"), Tab(), TextRun("1")),
                ),
            ),
        )
        self.assertFalse(report.warnings)

    def test_index_and_table_of_authorities_fields_remain_live(self) -> None:
        report = ConversionReport("indexes.doc")
        document = parse_main_story(
            "".join(
                (
                    '\x13 XE "Entry" \\b Bold \x15',
                    '\x13 TC "Heading" \\l 1 \x15',
                    '\x13 TA \\l "Case" \\s "123" \x15',
                    '\x13 INDEX \\c 2 \x14Entry, 1\x15',
                    '\x13 TOA \\c 1 \x14Case 123\x15\r',
                )
            ),
            report,
        )

        fields = [
            inline
            for inline in document.paragraphs[0].inlines
            if isinstance(inline, Field)
        ]
        self.assertEqual(
            [field.instruction.lstrip().split()[0] for field in fields],
            ["XE", "TC", "TA", "INDEX", "TOA"],
        )
        self.assertEqual(
            [field.has_separator for field in fields],
            [False, False, False, True, True],
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
