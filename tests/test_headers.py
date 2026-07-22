import struct
import unittest
from unittest.mock import Mock
from pathlib import Path
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import (
    CharacterProperties,
    ContinuationSeparatorMark,
    Document,
    FloatingTextBox,
    InlinePicture,
    Paragraph,
    ParagraphProperties,
    SectionProperties,
    SeparatorMark,
    ShapeStyle,
    StoryCharacter,
    TextRun,
)
from doc2docx.msdoc import (
    Piece,
    PieceTable,
    read_document_settings,
    read_header_footer_stories,
)
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"


class HeaderFooterParsingTests(unittest.TestCase):
    def test_note_separator_stories_are_parsed_and_packaged(self) -> None:
        story_payloads = (
            b"\x03\r\r",
            b"\x04\r\r",
            b"\x01Footnote continues\r",
            b"\x03\r\r",
            b"\x04\r\r",
            b"Endnote continues\r",
        ) + (b"",) * 6
        payload = bytearray()
        story_cps = [0]
        for story in story_payloads:
            payload.extend(story)
            story_cps.append(len(payload))
        header_document = bytes(payload) + b"\r"
        piece_table = PieceTable(
            (Piece(0, len(header_document), 0, True, 0),),
            header_document,
        )
        table_stream = struct.pack(
            f"<{len(story_cps) + 1}I",
            *story_cps,
            0,
        )
        report = ConversionReport("note-separators.doc")
        picture = InlinePicture(
            1,
            0,
            b"png",
            "png",
            "image/png",
            914400,
            457200,
        )

        collection = read_header_footer_stories(
            table_stream,
            piece_table,
            (SectionProperties(0, 1),),
            offset=0,
            size=len(table_stream),
            ccp_headers=len(header_document),
            header_story_cp_start=0,
            report=report,
            character_properties_at=lambda cp: CharacterProperties(
                special=header_document[cp] in (0x03, 0x04)
            ),
            inline_picture_at=lambda cp: picture if cp == story_cps[2] else None,
        )

        self.assertEqual(report.warnings, [])
        self.assertEqual(collection.note_separator_story_count, 6)
        assert collection.footnote_separator is not None
        assert collection.footnote_continuation_separator is not None
        assert collection.footnote_continuation_notice is not None
        self.assertIsInstance(
            collection.footnote_separator.paragraphs[0].inlines[0],
            SeparatorMark,
        )
        self.assertIsInstance(
            collection.footnote_continuation_separator.paragraphs[0].inlines[0],
            ContinuationSeparatorMark,
        )

        document = Document(
            (Paragraph((TextRun("Body"),)),),
            footnote_separator=collection.footnote_separator,
            footnote_continuation_separator=(
                collection.footnote_continuation_separator
            ),
            footnote_continuation_notice=(
                collection.footnote_continuation_notice
            ),
            endnote_separator=collection.endnote_separator,
            endnote_continuation_separator=(
                collection.endnote_continuation_separator
            ),
            endnote_continuation_notice=(
                collection.endnote_continuation_notice
            ),
            pictures=(picture,),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "note-separators.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                names = set(package.namelist())
                footnotes = ET.fromstring(package.read("word/footnotes.xml"))
                endnotes = ET.fromstring(package.read("word/endnotes.xml"))
                footnote_relationships = ET.fromstring(
                    package.read("word/_rels/footnotes.xml.rels")
                )

        self.assertIn("word/footnotes.xml", names)
        self.assertIn("word/endnotes.xml", names)
        self.assertIn("word/_rels/footnotes.xml.rels", names)
        footnote_types = {
            value.get(f"{W}type"): value
            for value in footnotes.findall(f"{W}footnote")
        }
        endnote_types = {
            value.get(f"{W}type"): value
            for value in endnotes.findall(f"{W}endnote")
        }
        self.assertEqual(
            set(footnote_types),
            {"separator", "continuationSeparator", "continuationNotice"},
        )
        self.assertEqual(
            set(endnote_types),
            {"separator", "continuationSeparator", "continuationNotice"},
        )
        self.assertIsNotNone(
            footnote_types["separator"].find(f".//{W}separator")
        )
        self.assertIsNotNone(
            footnote_types["continuationSeparator"].find(
                f".//{W}continuationSeparator"
            )
        )
        self.assertEqual(
            "".join(footnote_types["continuationNotice"].itertext()),
            "Footnote continues",
        )
        self.assertTrue(
            any(
                relationship.get("Target") == "media/image1.png"
                for relationship in footnote_relationships
            )
        )
        self.assertEqual(
            "".join(endnote_types["continuationNotice"].itertext()),
            "Endnote continues",
        )

    def test_inline_picture_callback_is_used_in_header_story(self) -> None:
        story_cps = (0,) * 8 + (3,) * 5 + (0,)
        table_stream = struct.pack("<14I", *story_cps)
        picture = InlinePicture(
            1,
            0,
            b"png",
            "png",
            "image/png",
            914400,
            457200,
        )
        piece_table = Mock(cp_end=14)
        piece_table.extract_characters.return_value = (
            StoryCharacter("\x01", 10, 11),
            StoryCharacter("\r", 11, 12),
            StoryCharacter("\r", 12, 13),
        )

        collection = read_header_footer_stories(
            table_stream,
            piece_table,
            (SectionProperties(0, 1),),
            offset=0,
            size=len(table_stream),
            ccp_headers=4,
            header_story_cp_start=10,
            report=ConversionReport("header-inline-picture.doc"),
            inline_picture_at=lambda cp: picture if cp == 10 else None,
        )

        header = collection.sections[0].default_header
        assert header is not None
        self.assertIs(header.paragraphs[0].inlines[0], picture)

    def test_basic_officeart_shape_style_is_packaged(self) -> None:
        textbox = FloatingTextBox(
            shape_id=1025,
            anchor_cp=0,
            left_twips=0,
            top_twips=0,
            width_twips=1440,
            height_twips=720,
            horizontal_relative="margin",
            vertical_relative="paragraph",
            wrap_type="none",
            wrap_side="both",
            behind_text=False,
            anchor_locked=False,
            paragraphs=(Paragraph((TextRun("Styled"),)),),
            shape_style=ShapeStyle(
                fill_color="FF0000",
                fill_opacity=0x8000,
                line_color="0000FF",
                line_opacity=0x4000,
                line_width_emu=12700,
                line_style="thickBetweenThin",
                line_dash="longdashdot",
                line_join="bevel",
                line_end_cap="square",
                inset_left_emu=12700,
                inset_top_emu=25400,
                inset_right_emu=38100,
                inset_bottom_emu=50800,
            ),
            flip_horizontal=True,
            flip_vertical=True,
            rotation_degrees=30.0,
        )
        document = Document((Paragraph((textbox,)),))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "styled-shape.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        rectangle = root.find(f".//{V}rect")
        assert rectangle is not None
        self.assertEqual(rectangle.get("filled"), "t")
        self.assertEqual(rectangle.get("fillcolor"), "#FF0000")
        self.assertEqual(rectangle.get("stroked"), "t")
        self.assertEqual(rectangle.get("strokecolor"), "#0000FF")
        self.assertEqual(rectangle.get("strokeweight"), "1pt")
        self.assertIn("flip:x", rectangle.get("style", ""))
        self.assertIn("flip:y", rectangle.get("style", ""))
        self.assertIn("rotation:30", rectangle.get("style", ""))
        fill = rectangle.find(f"{V}fill")
        stroke = rectangle.find(f"{V}stroke")
        textbox_element = rectangle.find(f"{V}textbox")
        assert fill is not None
        assert stroke is not None
        assert textbox_element is not None
        self.assertEqual(fill.get("opacity"), "50%")
        self.assertEqual(stroke.get("opacity"), "25%")
        self.assertEqual(stroke.get("linestyle"), "thickBetweenThin")
        self.assertEqual(stroke.get("dashstyle"), "longdashdot")
        self.assertEqual(stroke.get("joinstyle"), "bevel")
        self.assertEqual(stroke.get("endcap"), "square")
        self.assertEqual(textbox_element.get("inset"), "1pt,2pt,3pt,4pt")

    def test_dop_facing_pages_flag_is_read(self) -> None:
        settings = read_document_settings(b"\x01\x00", offset=0, size=2)
        self.assertTrue(settings.even_and_odd_headers)
        self.assertIsNone(settings.adjust_line_height_in_table)

    def test_dop_note_positions_are_read(self) -> None:
        dop = bytearray(84)
        struct.pack_into("<H", dop, 0, 0x0020)
        struct.pack_into("<H", dop, 54, 0x0003)

        settings = read_document_settings(
            dop,
            offset=0,
            size=len(dop),
            n_fib=0x00D9,
        )

        self.assertEqual(settings.footnote_position, "pageBottom")
        self.assertEqual(settings.endnote_position, "docEnd")

        newer = read_document_settings(
            dop,
            offset=0,
            size=len(dop),
            n_fib=0x0101,
        )
        self.assertIsNone(newer.footnote_position)
        self.assertEqual(newer.endnote_position, "docEnd")

    def test_dop_note_numbering_and_newer_fallback_are_read(self) -> None:
        dop = bytearray(500)
        struct.pack_into("<H", dop, 2, (7 << 2) | 0x01)
        struct.pack_into("<H", dop, 52, (9 << 2) | 0x02)
        struct.pack_into("<H", dop, 492, 0x04)
        struct.pack_into("<H", dop, 494, 0x01)

        settings = read_document_settings(
            dop,
            offset=0,
            size=len(dop),
            n_fib=0x00D9,
        )

        self.assertEqual(settings.footnote_number_format, "lowerLetter")
        self.assertEqual(settings.footnote_number_start, 7)
        self.assertEqual(settings.footnote_number_restart, "eachSect")
        self.assertEqual(settings.endnote_number_format, "upperRoman")
        self.assertEqual(settings.endnote_number_start, 9)
        self.assertEqual(settings.endnote_number_restart, "eachPage")

        newer = read_document_settings(
            dop,
            offset=0,
            size=len(dop),
            n_fib=0x0101,
        )
        self.assertEqual(newer.footnote_number_format, "lowerLetter")
        self.assertEqual(newer.footnote_number_start, 7)
        self.assertIsNone(newer.footnote_number_restart)
        self.assertEqual(newer.endnote_number_format, "upperRoman")
        self.assertEqual(newer.endnote_number_start, 9)
        self.assertIsNone(newer.endnote_number_restart)

    def test_invalid_legacy_dop_note_restarts_are_rejected(self) -> None:
        invalid_footnote = bytearray(84)
        struct.pack_into("<H", invalid_footnote, 2, 0x0003)
        with self.assertRaises(InvalidWordDocument):
            read_document_settings(
                invalid_footnote,
                offset=0,
                size=len(invalid_footnote),
            )

        invalid_endnote = bytearray(84)
        struct.pack_into("<H", invalid_endnote, 52, 0x0003)
        with self.assertRaises(InvalidWordDocument):
            read_document_settings(
                invalid_endnote,
                offset=0,
                size=len(invalid_endnote),
            )

    def test_invalid_legacy_dop_note_formats_are_rejected(self) -> None:
        invalid_footnote = bytearray(500)
        struct.pack_into("<H", invalid_footnote, 492, 0x00FE)
        with self.assertRaises(InvalidWordDocument):
            read_document_settings(
                invalid_footnote,
                offset=0,
                size=len(invalid_footnote),
            )

        invalid_endnote = bytearray(500)
        struct.pack_into("<H", invalid_endnote, 494, 0x00FE)
        with self.assertRaises(InvalidWordDocument):
            read_document_settings(
                invalid_endnote,
                offset=0,
                size=len(invalid_endnote),
            )

    def test_invalid_dop_note_positions_are_rejected(self) -> None:
        invalid_footnote = bytearray(84)
        struct.pack_into("<H", invalid_footnote, 0, 0x0060)
        with self.assertRaises(InvalidWordDocument):
            read_document_settings(
                invalid_footnote,
                offset=0,
                size=len(invalid_footnote),
            )

        invalid_endnote = bytearray(84)
        struct.pack_into("<H", invalid_endnote, 54, 0x0001)
        with self.assertRaises(InvalidWordDocument):
            read_document_settings(
                invalid_endnote,
                offset=0,
                size=len(invalid_endnote),
            )

    def test_dop_table_grid_line_height_compatibility_is_read(self) -> None:
        dop = bytearray(88)
        settings = read_document_settings(dop, offset=0, size=len(dop))
        self.assertTrue(settings.adjust_line_height_in_table)

        dop[84] = 0x08
        settings = read_document_settings(dop, offset=0, size=len(dop))
        self.assertFalse(settings.adjust_line_height_in_table)

    def test_dop_mirrored_margins_and_top_gutter_are_read(self) -> None:
        dop = bytearray(84)
        struct.pack_into("<I", dop, 4, 1 << 21)
        struct.pack_into("<H", dop, 82, 1 << 15)

        settings = read_document_settings(dop, offset=0, size=len(dop))

        self.assertTrue(settings.mirror_margins)
        self.assertTrue(settings.gutter_at_top)

    def test_mirrored_margins_and_top_gutter_are_packaged(self) -> None:
        document = Document(
            (Paragraph((TextRun("Mirrored"),)),),
            even_and_odd_headers=True,
            mirror_margins=True,
            gutter_at_top=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "mirrored.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                settings = ET.fromstring(package.read("word/settings.xml"))

        self.assertEqual(
            [child.tag for child in settings],
            [
                f"{W}mirrorMargins",
                f"{W}gutterAtTop",
                f"{W}evenAndOddHeaders",
            ],
        )

    def test_dop_tab_stop_and_hyphenation_settings_are_read(self) -> None:
        dop = bytearray(84)
        struct.pack_into("<I", dop, 4, 1 << 12)
        struct.pack_into("<H", dop, 10, 360)
        struct.pack_into("<H", dop, 14, 720)
        struct.pack_into("<H", dop, 16, 2)

        settings = read_document_settings(dop, offset=0, size=len(dop))

        self.assertEqual(settings.default_tab_stop_twips, 360)
        self.assertTrue(settings.auto_hyphenation)
        self.assertTrue(settings.do_not_hyphenate_caps)
        self.assertEqual(settings.hyphenation_zone_twips, 720)
        self.assertEqual(settings.consecutive_hyphen_limit, 2)

    def test_tab_stop_and_hyphenation_settings_are_packaged(self) -> None:
        document = Document(
            (Paragraph((TextRun("Hyphenation"),)),),
            default_tab_stop_twips=360,
            auto_hyphenation=True,
            do_not_hyphenate_caps=True,
            hyphenation_zone_twips=720,
            consecutive_hyphen_limit=2,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "hyphenation.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                settings = ET.fromstring(package.read("word/settings.xml"))

        self.assertEqual(
            [child.tag for child in settings],
            [
                f"{W}defaultTabStop",
                f"{W}autoHyphenation",
                f"{W}consecutiveHyphenLimit",
                f"{W}hyphenationZone",
                f"{W}doNotHyphenateCaps",
            ],
        )
        self.assertEqual(
            settings.find(f"{W}defaultTabStop").get(f"{W}val"),  # type: ignore[union-attr]
            "360",
        )
        self.assertEqual(
            settings.find(f"{W}consecutiveHyphenLimit").get(f"{W}val"),  # type: ignore[union-attr]
            "2",
        )
        self.assertEqual(
            settings.find(f"{W}hyphenationZone").get(f"{W}val"),  # type: ignore[union-attr]
            "720",
        )

    def test_dop_default_tab_stop_must_fit_ooxml_range(self) -> None:
        dop = bytearray(84)
        struct.pack_into("<H", dop, 10, 32768)

        with self.assertRaises(InvalidWordDocument):
            read_document_settings(dop, offset=0, size=len(dop))

    def test_dop_revision_and_forms_protection_are_read(self) -> None:
        dop = bytearray(84)
        struct.pack_into("<I", dop, 4, (1 << 15) | (1 << 25))
        struct.pack_into("<I", dop, 78, 0x12345678)

        settings = read_document_settings(dop, offset=0, size=len(dop))

        self.assertTrue(settings.track_revisions)
        self.assertEqual(settings.document_protection_edit, "forms")
        self.assertEqual(settings.legacy_protection_key, 0x12345678)
        self.assertFalse(settings.protection_mode_conflict)
        self.assertFalse(settings.track_revisions_repaired)

    def test_locked_revision_protection_enables_revision_tracking(self) -> None:
        dop = bytearray(84)
        struct.pack_into("<I", dop, 4, 1 << 30)

        settings = read_document_settings(dop, offset=0, size=len(dop))

        self.assertTrue(settings.track_revisions)
        self.assertEqual(
            settings.document_protection_edit,
            "trackedChanges",
        )
        self.assertTrue(settings.track_revisions_repaired)

    def test_dop2003_protection_mode_overrides_legacy_flags(self) -> None:
        dop = bytearray(600)
        struct.pack_into("<I", dop, 4, 1 << 25)
        struct.pack_into("<H", dop, 598, (1 << 3) | (3 << 4))

        settings = read_document_settings(
            dop,
            offset=0,
            size=len(dop),
            n_fib=0x010C,
        )

        self.assertEqual(settings.document_protection_edit, "readOnly")
        self.assertFalse(settings.protection_mode_conflict)

    def test_invalid_dop2003_protection_mode_is_rejected(self) -> None:
        dop = bytearray(600)
        struct.pack_into("<H", dop, 598, (1 << 3) | (4 << 4))

        with self.assertRaises(InvalidWordDocument):
            read_document_settings(
                dop,
                offset=0,
                size=len(dop),
                n_fib=0x010C,
            )

    def test_revision_tracking_and_document_protection_are_packaged(self) -> None:
        document = Document(
            (Paragraph((TextRun("Protected"),)),),
            track_revisions=True,
            document_protection_edit="forms",
            default_tab_stop_twips=720,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "protected.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                settings = ET.fromstring(package.read("word/settings.xml"))

        self.assertEqual(
            [child.tag for child in settings],
            [
                f"{W}trackRevisions",
                f"{W}documentProtection",
                f"{W}defaultTabStop",
            ],
        )
        protection = settings.find(f"{W}documentProtection")
        assert protection is not None
        self.assertEqual(protection.get(f"{W}edit"), "forms")
        self.assertEqual(protection.get(f"{W}enforcement"), "1")
        self.assertIsNone(protection.get(f"{W}hash"))

    def test_table_grid_line_height_compatibility_is_packaged(self) -> None:
        document = Document(
            (Paragraph((TextRun("Grid"),)),),
            adjust_line_height_in_table=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "grid.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                settings = ET.fromstring(package.read("word/settings.xml"))

        self.assertIsNotNone(
            settings.find(f"{W}compat/{W}adjustLineHeightInTable")
        )

    def test_truncated_dop_is_rejected(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_document_settings(b"\x01", offset=0, size=1)

    def test_all_zero_legacy_plcf_hdd_without_header_story_is_omitted(self) -> None:
        report = ConversionReport("empty-legacy-headers.doc")

        collection = read_header_footer_stories(
            bytes(52),
            Mock(cp_end=100),
            (SectionProperties(0, 1),),
            offset=0,
            size=52,
            ccp_headers=0,
            header_story_cp_start=1,
            report=report,
        )

        self.assertEqual(collection.story_count, 0)
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["EMPTY_HEADER_TABLE_REPAIRED"],
        )

    def test_title_page_gets_implicit_empty_first_header_and_footer(self) -> None:
        story_payloads = (b"",) * 6 + (
            b"",
            b"Default header\r\r",
            b"",
            b"Default footer\r\r",
            b"",
            b"",
        )
        payload = bytearray()
        story_cps = [0]
        for story in story_payloads:
            payload.extend(story)
            story_cps.append(len(payload))
        header_document = bytes(payload) + b"\r"
        piece_table = PieceTable(
            (Piece(0, len(header_document), 0, True, 0),),
            header_document,
        )
        table_stream = struct.pack(
            f"<{len(story_cps) + 1}I",
            *story_cps,
            0,
        )

        collection = read_header_footer_stories(
            table_stream,
            piece_table,
            (SectionProperties(0, 1, title_page=True),),
            offset=0,
            size=len(table_stream),
            ccp_headers=len(header_document),
            header_story_cp_start=0,
            report=ConversionReport("implicit-first-header.doc"),
            paragraph_properties_at=lambda _cp: ParagraphProperties(style_id=18),
        )

        section = collection.sections[0]
        assert section.first_header is not None
        assert section.first_footer is not None
        self.assertEqual(section.first_header.paragraphs[0].inlines, ())
        self.assertEqual(section.first_footer.paragraphs[0].inlines, ())
        self.assertEqual(section.first_header.paragraphs[0].properties.style_id, 18)
        self.assertEqual(section.first_footer.paragraphs[0].properties.style_id, 18)
        self.assertEqual(collection.story_count, 4)
        self.assertEqual(collection.paragraph_count, 4)

    def test_nonzero_plcf_hdd_without_header_story_is_rejected(self) -> None:
        table = bytearray(52)
        table[4] = 1
        with self.assertRaises(InvalidWordDocument):
            read_header_footer_stories(
                bytes(table),
                Mock(cp_end=100),
                (SectionProperties(0, 1),),
                offset=0,
                size=52,
                ccp_headers=0,
                header_story_cp_start=1,
                report=ConversionReport("invalid-empty-headers.doc"),
            )

    def test_plcf_hdd_must_have_six_stories_per_section(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_header_footer_stories(
                bytes(52),
                Mock(cp_end=100),
                (SectionProperties(0, 1),),
                offset=0,
                size=52,
                ccp_headers=2,
                header_story_cp_start=1,
                report=ConversionReport("malformed-headers.doc"),
            )


if __name__ == "__main__":
    unittest.main()
