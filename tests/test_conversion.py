from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx import convert, inspect_doc
from doc2docx.errors import (
    EncryptedDocumentError,
    InvalidWordDocument,
    UnsafeOutputPathError,
)

from .fixtures import (
    build_bookmark_word_cfb,
    build_comment_word_cfb,
    build_endnote_word_cfb,
    build_formatted_word_cfb,
    build_footnote_word_cfb,
    build_header_footer_word_cfb,
    build_header_textbox_word_cfb,
    build_main_textbox_word_cfb,
    build_nested_table_word_cfb,
    build_sectioned_word_cfb,
    build_table_word_cfb,
    build_word_cfb,
)


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
V = "{urn:schemas-microsoft-com:vml}"


class ConversionTests(unittest.TestCase):
    def test_standard_bookmark_and_ref_field_are_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "bookmark.doc"
            destination = temporary / "bookmark.docx"
            source.write_bytes(build_bookmark_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["bookmark_count"], 1)
            self.assertEqual(
                result.report.statistics["preserved_bookmark_count"],
                1,
            )
            self.assertEqual(result.report.statistics["declared_field_count"], 1)
            self.assertEqual(
                [warning.code for warning in result.report.warnings],
                ["FIELD_CHARACTER_SPECIAL_MISSING"],
            )
            inspected = inspect_doc(source)
            self.assertGreater(inspected["fib"]["lcbSttbfBkmk"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfBkf"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfBkl"], 0)

            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

            start = root.find(f".//{W}bookmarkStart")
            end = root.find(f".//{W}bookmarkEnd")
            field = root.find(f".//{W}instrText")
            assert start is not None and end is not None and field is not None
            self.assertEqual(start.get(f"{W}name"), "Target")
            self.assertEqual(start.get(f"{W}id"), end.get(f"{W}id"))
            self.assertEqual(field.text, " REF Target \\h ")

    def test_main_story_textbox_is_positioned_and_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "main-textbox.doc"
            destination = temporary / "main-textbox.docx"
            source.write_bytes(build_main_textbox_word_cfb(officeart_style=True))

            result = convert(source, destination)

            self.assertEqual(result.report.warnings, [])
            self.assertEqual(result.report.statistics["main_textbox_count"], 1)
            self.assertEqual(result.report.statistics["main_textbox_field_count"], 0)
            self.assertEqual(result.report.statistics["styled_main_textbox_count"], 1)
            inspected = inspect_doc(source)
            self.assertGreater(inspected["fib"]["ccpTxbx"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcSpaMom"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcftxbxTxt"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfTxbxBkd"], 0)

            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

            rectangle = root.find(f".//{V}rect")
            assert rectangle is not None
            self.assertEqual("".join(rectangle.itertext()), "Inside textbox")
            self.assertEqual(rectangle.get("filled"), "f")
            self.assertEqual(rectangle.get("stroked"), "f")
            self.assertNotIn("\uFFFC", "".join(root.itertext()))
            style = rectangle.get("style", "")
            self.assertIn("margin-left:36pt", style)
            self.assertIn("width:144pt", style)

    def test_malformed_main_story_textboxes_are_rejected(self) -> None:
        fixtures = (
            build_main_textbox_word_cfb(malformed_anchor=True),
            build_main_textbox_word_cfb(missing_break_table=True),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, payload in enumerate(fixtures):
                with self.subTest(index=index):
                    source = Path(directory) / f"bad-main-textbox-{index}.doc"
                    source.write_bytes(payload)
                    with self.assertRaises(InvalidWordDocument):
                        convert(source)

    def test_main_story_textbox_page_field_remains_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "main-textbox-field.doc"
            destination = temporary / "main-textbox-field.docx"
            source.write_bytes(
                build_main_textbox_word_cfb(
                    officeart_style=True,
                    page_field=True,
                )
            )

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["main_textbox_field_count"], 1)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            rectangle = root.find(f".//{W}pict/{V}rect")
            assert rectangle is not None
            self.assertEqual(
                [
                    element.get(f"{W}fldCharType")
                    for element in rectangle.findall(f".//{W}fldChar")
                ],
                ["begin", "separate", "end"],
            )
            self.assertEqual(
                rectangle.findtext(f".//{W}instrText"),
                " PAGE \\* MERGEFORMAT ",
            )
            self.assertIn("1", "".join(rectangle.itertext()))

    def test_ranged_comment_is_anchored_and_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "comment.doc"
            destination = temporary / "comment.docx"
            source.write_bytes(build_comment_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.report.warnings, [])
            self.assertEqual(result.report.statistics["comment_count"], 1)
            self.assertEqual(result.report.statistics["comment_reference_count"], 1)
            self.assertEqual(result.report.statistics["comment_range_count"], 1)
            inspected = inspect_doc(source)
            self.assertGreater(inspected["fib"]["ccpAtn"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfandRef"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfandTxt"], 0)
            self.assertGreater(inspected["fib"]["lcbGrpXstAtnOwners"], 0)

            with zipfile.ZipFile(destination) as package:
                names = set(package.namelist())
                document_root = ET.fromstring(package.read("word/document.xml"))
                comments_root = ET.fromstring(package.read("word/comments.xml"))
                relationships_root = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                content_types = package.read("[Content_Types].xml").decode()

            self.assertIn("word/comments.xml", names)
            start = document_root.find(f".//{W}commentRangeStart")
            end = document_root.find(f".//{W}commentRangeEnd")
            reference = document_root.find(f".//{W}commentReference")
            assert start is not None and end is not None and reference is not None
            self.assertEqual(start.get(f"{W}id"), "0")
            self.assertEqual(end.get(f"{W}id"), "0")
            self.assertEqual(reference.get(f"{W}id"), "0")
            comment = comments_root.find(f"{W}comment")
            assert comment is not None
            self.assertEqual(comment.get(f"{W}id"), "0")
            self.assertEqual(comment.get(f"{W}author"), "Alice")
            self.assertEqual(comment.get(f"{W}initials"), "AL")
            self.assertEqual("".join(comment.itertext()), "Comment body")
            relationship = next(
                value
                for value in relationships_root.findall(f"{REL}Relationship")
                if value.get("Target") == "comments.xml"
            )
            self.assertTrue(relationship.get("Type", "").endswith("/comments"))
            self.assertIn("/word/comments.xml", content_types)

    def test_insertion_point_comment_has_no_range_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "point-comment.doc"
            destination = temporary / "point-comment.docx"
            source.write_bytes(build_comment_word_cfb(insertion_point=True))

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["comment_range_count"], 0)
            with zipfile.ZipFile(destination) as package:
                document_root = ET.fromstring(package.read("word/document.xml"))
            self.assertIsNone(document_root.find(f".//{W}commentRangeStart"))
            self.assertIsNone(document_root.find(f".//{W}commentRangeEnd"))
            self.assertIsNotNone(document_root.find(f".//{W}commentReference"))

    def test_comment_bookmark_terminal_cp_two_past_story_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "compatible-comment.doc"
            destination = Path(directory) / "compatible-comment.docx"
            source.write_bytes(build_comment_word_cfb(bookmark_terminal_delta=2))

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["comment_range_count"], 1)
            self.assertEqual(
                [warning.code for warning in result.report.warnings],
                ["COMMENT_BOOKMARK_TERMINAL_CP_REPAIRED"],
            )

    def test_internal_comment_marker_is_omitted_without_losing_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "internal-comment-marker.doc"
            destination = Path(directory) / "internal-comment-marker.docx"
            source.write_bytes(build_comment_word_cfb(internal_comment_marker=True))

            result = convert(source, destination)

            self.assertEqual(
                [warning.code for warning in result.report.warnings],
                ["COMMENT_MARKER_POSITION_REPAIRED"],
            )
            with zipfile.ZipFile(destination) as package:
                comments_root = ET.fromstring(package.read("word/comments.xml"))
            self.assertEqual(
                "".join(comments_root.itertext()),
                "Comment prefix Comment body",
            )

    def test_malformed_comments_are_rejected(self) -> None:
        fixtures = (
            build_comment_word_cfb(missing_special=True),
            build_comment_word_cfb(malformed_reference_character=True),
            build_comment_word_cfb(malformed_text_marker=True),
            build_comment_word_cfb(malformed_text_end=True),
            build_comment_word_cfb(invalid_author_index=True),
            build_comment_word_cfb(missing_bookmark_table=True),
            build_comment_word_cfb(bookmark_terminal_delta=3),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, payload in enumerate(fixtures):
                with self.subTest(index=index):
                    source = Path(directory) / f"bad-comment-{index}.doc"
                    source.write_bytes(payload)
                    with self.assertRaises(InvalidWordDocument):
                        convert(source)

    def test_automatic_endnote_is_linked_and_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "endnote.doc"
            destination = temporary / "endnote.docx"
            source.write_bytes(build_endnote_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.report.warnings, [])
            self.assertEqual(result.report.statistics["endnote_count"], 1)
            self.assertEqual(result.report.statistics["endnote_reference_count"], 1)
            inspected = inspect_doc(source)
            self.assertGreater(inspected["fib"]["ccpEdn"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfendRef"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfendTxt"], 0)

            with zipfile.ZipFile(destination) as package:
                names = set(package.namelist())
                self.assertIn("word/endnotes.xml", names)
                document_root = ET.fromstring(package.read("word/document.xml"))
                endnotes_root = ET.fromstring(package.read("word/endnotes.xml"))
                relationships_root = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                content_types = package.read("[Content_Types].xml").decode()

            reference = document_root.find(f".//{W}endnoteReference")
            assert reference is not None
            self.assertEqual(reference.get(f"{W}id"), "1")
            endnotes = {
                value.get(f"{W}id"): value
                for value in endnotes_root.findall(f"{W}endnote")
            }
            self.assertEqual(set(endnotes), {"-1", "0", "1"})
            self.assertEqual("".join(endnotes["1"].itertext()), "Endnote text")
            self.assertIsNotNone(endnotes["1"].find(f".//{W}endnoteRef"))
            relationship = next(
                value
                for value in relationships_root.findall(f"{REL}Relationship")
                if value.get("Target") == "endnotes.xml"
            )
            self.assertTrue(relationship.get("Type", "").endswith("/endnotes"))
            self.assertIn("/word/endnotes.xml", content_types)

    def test_malformed_automatic_endnotes_are_rejected(self) -> None:
        fixtures = (
            build_endnote_word_cfb(missing_special=True),
            build_endnote_word_cfb(malformed_reference_character=True),
            build_endnote_word_cfb(malformed_text_end=True),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, payload in enumerate(fixtures):
                with self.subTest(index=index):
                    source = Path(directory) / f"bad-endnote-{index}.doc"
                    source.write_bytes(payload)
                    with self.assertRaises(InvalidWordDocument):
                        convert(source)

    def test_custom_endnote_mark_is_explicitly_approximated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "custom-endnote.doc"
            source.write_bytes(build_endnote_word_cfb(custom_mark=True))

            result = convert(source)

            self.assertEqual(
                [warning.code for warning in result.report.warnings],
                ["CUSTOM_ENDNOTE_MARK_APPROXIMATED"],
            )
            self.assertEqual(
                result.report.statistics["custom_endnote_mark_count"],
                1,
            )

    def test_automatic_footnote_is_linked_and_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "footnote.doc"
            destination = temporary / "footnote.docx"
            source.write_bytes(build_footnote_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.report.warnings, [])
            self.assertEqual(result.report.statistics["footnote_count"], 1)
            self.assertEqual(
                result.report.statistics["footnote_reference_count"],
                1,
            )
            self.assertEqual(
                result.report.statistics["custom_footnote_mark_count"],
                0,
            )
            inspected = inspect_doc(source)
            self.assertGreater(inspected["fib"]["ccpFtn"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcffndRef"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcffndTxt"], 0)

            with zipfile.ZipFile(destination) as package:
                names = set(package.namelist())
                self.assertIn("word/footnotes.xml", names)
                document_root = ET.fromstring(package.read("word/document.xml"))
                footnotes_root = ET.fromstring(package.read("word/footnotes.xml"))
                relationships_root = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                content_types = package.read("[Content_Types].xml").decode()

            reference = document_root.find(f".//{W}footnoteReference")
            assert reference is not None
            self.assertEqual(reference.get(f"{W}id"), "1")
            self.assertNotIn("\uFFFC", "".join(document_root.itertext()))
            footnotes = {
                value.get(f"{W}id"): value
                for value in footnotes_root.findall(f"{W}footnote")
            }
            self.assertEqual(set(footnotes), {"-1", "0", "1"})
            self.assertEqual("".join(footnotes["1"].itertext()), "Footnote text")
            self.assertIsNotNone(footnotes["1"].find(f".//{W}footnoteRef"))
            relationship = next(
                value
                for value in relationships_root.findall(f"{REL}Relationship")
                if value.get("Target") == "footnotes.xml"
            )
            self.assertTrue(relationship.get("Type", "").endswith("/footnotes"))
            self.assertIn("/word/footnotes.xml", content_types)

    def test_malformed_automatic_footnotes_are_rejected(self) -> None:
        fixtures = (
            build_footnote_word_cfb(missing_special=True),
            build_footnote_word_cfb(malformed_reference_character=True),
            build_footnote_word_cfb(malformed_text_end=True),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, payload in enumerate(fixtures):
                with self.subTest(index=index):
                    source = Path(directory) / f"bad-footnote-{index}.doc"
                    source.write_bytes(payload)
                    with self.assertRaises(InvalidWordDocument):
                        convert(source)

    def test_custom_footnote_mark_is_explicitly_approximated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "custom-footnote.doc"
            source.write_bytes(build_footnote_word_cfb(custom_mark=True))

            result = convert(source)

            self.assertEqual(
                [warning.code for warning in result.report.warnings],
                ["CUSTOM_FOOTNOTE_MARK_APPROXIMATED"],
            )
            self.assertEqual(
                result.report.statistics["custom_footnote_mark_count"],
                1,
            )

    def test_header_textbox_field_table_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad-header-textbox.doc"
            source.write_bytes(build_header_textbox_word_cfb(malformed_field=True))
            with self.assertRaises(InvalidWordDocument):
                convert(source)

    def test_header_textbox_without_officeart_style_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "header-textbox-without-officeart.doc"
            source.write_bytes(build_header_textbox_word_cfb())

            result = convert(source)

            self.assertEqual(
                [warning.code for warning in result.report.warnings],
                ["HEADER_TEXTBOX_STYLE_APPROXIMATED"],
            )
            self.assertEqual(
                result.report.statistics["styled_header_textbox_count"],
                0,
            )

    def test_header_textbox_and_page_field_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "header-textbox.doc"
            destination = temporary / "header-textbox.docx"
            source.write_bytes(build_header_textbox_word_cfb(officeart_style=True))

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["header_textbox_count"], 1)
            self.assertEqual(
                result.report.statistics["header_textbox_field_count"], 1
            )
            self.assertEqual(
                result.report.statistics["styled_header_textbox_count"], 1
            )
            self.assertEqual(result.report.warnings, [])
            inspected = inspect_doc(source)
            self.assertGreater(inspected["fib"]["lcbPlcSpaHdr"], 0)
            self.assertGreater(inspected["fib"]["lcbDggInfo"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfHdrtxbxTxt"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcffldHdrTxbx"], 0)
            self.assertGreater(inspected["fib"]["lcbPlcfTxbxHdrBkd"], 0)

            with zipfile.ZipFile(destination) as package:
                footer_root = ET.fromstring(package.read("word/footer1.xml"))
            rectangle = footer_root.find(f".//{W}pict/{V}rect")
            assert rectangle is not None
            self.assertEqual(rectangle.get("id"), "_x0000_s1025")
            self.assertEqual(rectangle.get("filled"), "f")
            self.assertEqual(rectangle.get("stroked"), "f")
            style = rectangle.get("style", "")
            self.assertIn("width:144pt", style)
            self.assertIn("height:36pt", style)
            self.assertIn("mso-position-horizontal-relative:margin", style)
            textbox = rectangle.find(f"{V}textbox")
            assert textbox is not None
            self.assertEqual(textbox.get("inset"), "0pt,0pt,0pt,0pt")
            self.assertEqual(
                [
                    element.get(f"{W}fldCharType")
                    for element in footer_root.findall(f".//{W}fldChar")
                ],
                ["begin", "separate", "end"],
            )
            instruction = footer_root.findtext(f".//{W}instrText")
            self.assertEqual(instruction, " PAGE \\* MERGEFORMAT ")
            self.assertIn("1", "".join(footer_root.itertext()))
            self.assertNotIn("\uFFFC", "".join(footer_root.itertext()))

    def test_header_footer_story_without_guard_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad-header.doc"
            source.write_bytes(build_header_footer_word_cfb(malformed_guard=True))
            with self.assertRaises(InvalidWordDocument):
                convert(source)

    def test_header_footer_stories_are_packaged_and_referenced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "headers.doc"
            destination = temporary / "headers.docx"
            source.write_bytes(build_header_footer_word_cfb())

            result = convert(source, destination)

            self.assertFalse(result.report.warnings)
            self.assertEqual(result.report.statistics["section_count"], 1)
            self.assertEqual(result.report.statistics["header_footer_story_count"], 6)
            self.assertEqual(result.report.statistics["header_footer_paragraph_count"], 6)
            self.assertTrue(result.document.even_and_odd_headers)
            self.assertTrue(result.document.sections[0].title_page)
            with zipfile.ZipFile(destination) as package:
                names = set(package.namelist())
                self.assertTrue(
                    {
                        "word/header1.xml",
                        "word/header2.xml",
                        "word/header3.xml",
                        "word/footer1.xml",
                        "word/footer2.xml",
                        "word/footer3.xml",
                        "word/settings.xml",
                        "word/_rels/document.xml.rels",
                    }.issubset(names)
                )
                document_root = ET.fromstring(package.read("word/document.xml"))
                relationships_root = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                settings_root = ET.fromstring(package.read("word/settings.xml"))
                relationship_targets = {
                    item.get("Id"): item.get("Target")
                    for item in relationships_root.findall(f"{REL}Relationship")
                }
                section = document_root.find(f"./{W}body/{W}sectPr")
                assert section is not None
                self.assertIsNotNone(section.find(f"{W}titlePg"))
                self.assertIsNotNone(settings_root.find(f"{W}evenAndOddHeaders"))

                expected = {
                    (f"{W}headerReference", "default"): "Default H",
                    (f"{W}headerReference", "even"): "Even H",
                    (f"{W}headerReference", "first"): "First H",
                    (f"{W}footerReference", "default"): "Default F",
                    (f"{W}footerReference", "even"): "Even F",
                    (f"{W}footerReference", "first"): "First F",
                }
                actual: dict[tuple[str, str], str] = {}
                for reference in section.findall(f"{W}headerReference") + section.findall(
                    f"{W}footerReference"
                ):
                    relationship_id = reference.get(f"{R}id")
                    target = relationship_targets[relationship_id]
                    story_root = ET.fromstring(package.read(f"word/{target}"))
                    actual[(reference.tag, reference.get(f"{W}type"))] = "".join(
                        story_root.itertext()
                    )
                self.assertEqual(actual, expected)

    def test_section_layout_and_break_types_are_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "sections.doc"
            destination = temporary / "sections.docx"
            source.write_bytes(build_sectioned_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["section_count"], 2)
            self.assertEqual(
                result.report.statistics["document_grid_section_count"],
                2,
            )
            self.assertFalse(result.report.warnings)
            self.assertEqual(len(result.document.sections), 2)
            self.assertEqual(result.document.sections[0].break_type, "continuous")
            self.assertEqual(result.document.sections[1].orientation, "landscape")
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

            body = root.find(f"{W}body")
            assert body is not None
            self.assertEqual(
                [element.tag for element in body],
                [f"{W}p", f"{W}p", f"{W}sectPr"],
            )
            paragraphs = body.findall(f"{W}p")
            self.assertEqual(
                ["".join(paragraph.itertext()) for paragraph in paragraphs],
                ["Portrait", "Landscape"],
            )
            self.assertFalse(root.findall(f".//{W}br"))

            first_section = paragraphs[0].find(f"{W}pPr/{W}sectPr")
            assert first_section is not None
            self.assertEqual(
                first_section.find(f"{W}type").get(f"{W}val"),  # type: ignore[union-attr]
                "continuous",
            )
            first_page = first_section.find(f"{W}pgSz")
            assert first_page is not None
            self.assertEqual(first_page.get(f"{W}w"), "12240")
            self.assertEqual(first_page.get(f"{W}orient"), "portrait")
            first_grid = first_section.find(f"{W}docGrid")
            assert first_grid is not None
            self.assertEqual(first_grid.get(f"{W}type"), "lines")
            self.assertEqual(first_grid.get(f"{W}linePitch"), "312")
            self.assertEqual(first_grid.get(f"{W}charSpace"), "0")

            final_section = body.find(f"{W}sectPr")
            assert final_section is not None
            final_page = final_section.find(f"{W}pgSz")
            final_margins = final_section.find(f"{W}pgMar")
            assert final_page is not None
            assert final_margins is not None
            self.assertEqual(final_page.get(f"{W}w"), "15840")
            self.assertEqual(final_page.get(f"{W}h"), "12240")
            self.assertEqual(final_page.get(f"{W}orient"), "landscape")
            self.assertEqual(final_margins.get(f"{W}top"), "-900")
            self.assertEqual(final_margins.get(f"{W}header"), "500")
            self.assertEqual(final_margins.get(f"{W}footer"), "600")
            self.assertEqual(final_margins.get(f"{W}gutter"), "100")
            final_grid = final_section.find(f"{W}docGrid")
            assert final_grid is not None
            self.assertEqual(final_grid.get(f"{W}type"), "snapToChars")
            self.assertEqual(final_grid.get(f"{W}linePitch"), "360")
            self.assertEqual(final_grid.get(f"{W}charSpace"), "4096")

    def test_nested_doc_table_is_emitted_and_counted_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "nested-table.doc"
            destination = temporary / "nested-table.docx"
            source.write_bytes(build_nested_table_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["table_count"], 2)
            self.assertEqual(result.report.statistics["table_row_count"], 2)
            self.assertEqual(result.report.statistics["table_cell_count"], 2)
            self.assertFalse(result.report.warnings)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            self.assertEqual(len(root.findall(f".//{W}tbl")), 2)
            outer_cell = root.find(f"./{W}body/{W}tbl/{W}tr/{W}tc")
            assert outer_cell is not None
            self.assertIsNotNone(outer_cell.find(f"{W}tbl"))

    def test_table_markers_and_row_properties_emit_a_real_docx_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "table.doc"
            destination = temporary / "table.docx"
            source.write_bytes(build_table_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["table_count"], 1)
            self.assertEqual(result.report.statistics["table_row_count"], 1)
            self.assertEqual(result.report.statistics["table_cell_count"], 2)
            self.assertFalse(result.report.warnings)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            body = root.find(f"{W}body")
            assert body is not None
            self.assertEqual(
                [element.tag for element in body],
                [f"{W}p", f"{W}tbl", f"{W}p"],
            )
            table = body.find(f"{W}tbl")
            assert table is not None
            self.assertEqual(
                [column.get(f"{W}w") for column in table.findall(f"{W}tblGrid/{W}gridCol")],
                ["1000", "1200"],
            )
            self.assertEqual(
                ["".join(cell.itertext()) for cell in table.findall(f"{W}tr/{W}tc")],
                ["A", "B"],
            )
            self.assertEqual(
                len(table.findall(f"{W}tblPr/{W}tblBorders/*")),
                6,
            )
            cells = table.findall(f"{W}tr/{W}tc")
            left_margin = cells[0].find(f"{W}tcPr/{W}tcMar/{W}left")
            assert left_margin is not None
            self.assertEqual(left_margin.get(f"{W}w"), "108")
            top_margin = cells[1].find(f"{W}tcPr/{W}tcMar/{W}top")
            assert top_margin is not None
            self.assertEqual(top_margin.get(f"{W}w"), "36")
            shading = cells[0].find(f"{W}tcPr/{W}shd")
            assert shading is not None
            self.assertEqual(shading.get(f"{W}val"), "solid")
            self.assertEqual(shading.get(f"{W}color"), "FF0000")
            self.assertEqual(shading.get(f"{W}fill"), "FFFF00")

    def test_direct_character_and_paragraph_formatting_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "formatted.doc"
            destination = temporary / "formatted.docx"
            source.write_bytes(build_formatted_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.report.statistics["character_fkp_run_count"], 4)
            self.assertEqual(result.report.statistics["paragraph_fkp_run_count"], 2)
            self.assertFalse(result.report.warnings)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

            paragraphs = root.findall(f"./{W}body/{W}p")
            self.assertEqual(
                ["".join(paragraph.itertext()) for paragraph in paragraphs],
                ["Bold plain", "Centered"],
            )
            first_runs = paragraphs[0].findall(f"{W}r")
            self.assertEqual([run.findtext(f"{W}t") for run in first_runs], ["Bold", " ", "plain"])
            self.assertIsNotNone(first_runs[0].find(f"{W}rPr/{W}b"))
            rich_properties = first_runs[2].find(f"{W}rPr")
            assert rich_properties is not None
            self.assertIsNotNone(rich_properties.find(f"{W}i"))
            self.assertEqual(
                rich_properties.find(f"{W}color").get(f"{W}val"),  # type: ignore[union-attr]
                "FF0000",
            )
            self.assertEqual(
                rich_properties.find(f"{W}sz").get(f"{W}val"),  # type: ignore[union-attr]
                "28",
            )

            second_properties = paragraphs[1].find(f"{W}pPr")
            assert second_properties is not None
            self.assertEqual(
                second_properties.find(f"{W}jc").get(f"{W}val"),  # type: ignore[union-attr]
                "center",
            )
            self.assertEqual(
                second_properties.find(f"{W}ind").get(f"{W}left"),  # type: ignore[union-attr]
                "720",
            )
            spacing = second_properties.find(f"{W}spacing")
            assert spacing is not None
            self.assertEqual(spacing.get(f"{W}before"), "120")
            self.assertEqual(spacing.get(f"{W}after"), "240")

    def test_end_to_end_mixed_piece_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "mixed.doc"
            destination = temporary / "mixed.docx"
            source.write_bytes(build_word_cfb())

            result = convert(source, destination)

            self.assertEqual(result.output_path, destination)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o644)
            self.assertEqual(result.report.statistics["piece_count"], 2)
            self.assertEqual(result.report.statistics["paragraph_count"], 2)
            with zipfile.ZipFile(destination) as package:
                self.assertIsNone(package.testzip())
                self.assertEqual(
                    set(package.namelist()),
                    {
                        "[Content_Types].xml",
                        "_rels/.rels",
                        "word/document.xml",
                    },
                )
                self.assertNotIn(b"ns0:", package.read("[Content_Types].xml"))
                self.assertNotIn(b"ns0:", package.read("_rels/.rels"))
                root = ET.fromstring(package.read("word/document.xml"))
            paragraphs = root.findall(f"./{W}body/{W}p")
            self.assertEqual(
                ["".join(p.itertext()) for p in paragraphs], ["Hello", "世界"]
            )

    def test_inspection_reports_selected_table_and_streams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "inspect.doc"
            source.write_bytes(build_word_cfb())
            info = inspect_doc(source)
            self.assertEqual(info["fib"]["table_stream"], "1Table")
            self.assertEqual(info["fib"]["ccpText"], 9)
            self.assertEqual(info["fib"]["ccpHdd"], 0)
            self.assertEqual(info["fib"]["lcbPlcfBteChpx"], 0)
            self.assertEqual(info["fib"]["lcbPlcfBtePapx"], 0)
            self.assertEqual(info["fib"]["lcbPlcfSed"], 0)
            self.assertEqual(info["fib"]["lcbPlcfHdd"], 0)
            self.assertEqual(info["fib"]["lcbSttbListNames"], 0)
            self.assertEqual(
                {item["path"] for item in info["entries"]},
                {"WordDocument", "1Table"},
            )

    def test_zero_table_is_selected_from_fib_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "zero-table.doc"
            source.write_bytes(build_word_cfb(uses_1table=False))
            result = convert(source)
            self.assertEqual(result.report.statistics["table_stream"], "0Table")
            self.assertTrue(result.output_path.exists())

    def test_encrypted_document_is_rejected_before_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "encrypted.doc"
            source.write_bytes(build_word_cfb(encrypted=True))
            with self.assertRaises(EncryptedDocumentError):
                convert(source)
            self.assertFalse(source.with_suffix(".docx").exists())

    def test_conversion_never_overwrites_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.doc"
            original = build_word_cfb()
            source.write_bytes(original)
            with self.assertRaises(UnsafeOutputPathError):
                convert(source, source)
            self.assertEqual(source.read_bytes(), original)

    def test_destination_must_be_docx(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.doc"
            source.write_bytes(build_word_cfb())
            with self.assertRaises(UnsafeOutputPathError):
                convert(source, Path(directory) / "output.bin")
