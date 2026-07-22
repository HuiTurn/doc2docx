import struct
from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import Document, Paragraph, TextRun
from doc2docx.msdoc.sections import read_sections
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class SectionParsingTests(unittest.TestCase):
    def test_later_section_sprm_wins(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HH", 0xB01F, 10000),
                struct.pack("<HH", 0xB01F, 12000),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1100),
                struct.pack("<Hh", 0x9023, 1200),
                struct.pack("<Hh", 0x9024, 1300),
                struct.pack("<Hi", 0x7030, -4096),
                struct.pack("<HH", 0x9031, 312),
                struct.pack("<HH", 0x5032, 2),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("fixture.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=2052,
            report=report,
        )

        self.assertEqual(sections[0].page_width_twips, 12000)
        self.assertEqual(sections[0].header_distance_twips, 720)
        self.assertEqual(sections[0].document_grid_type, "lines")
        self.assertEqual(sections[0].document_grid_line_pitch_twips, 312)
        self.assertEqual(sections[0].document_grid_character_space, -4096)
        self.assertFalse(report.warnings)

    def test_section_numbering_direction_and_bidi_are_preserved(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x3000, 3),
                struct.pack("<HB", 0x3001, 2),
                struct.pack("<HB", 0x300E, 1),
                struct.pack("<HB", 0x3011, 1),
                struct.pack("<HH", 0x501C, 7),
                struct.pack("<HI", 0x7044, 123456),
                struct.pack("<HB", 0x3013, 2),
                struct.pack("<HH", 0x5015, 3),
                struct.pack("<HH", 0x9016, 720),
                struct.pack("<HH", 0x501B, 4),
                struct.pack("<HB", 0x3005, 1),
                struct.pack("<HB", 0x303C, 1),
                struct.pack("<HB", 0x303E, 1),
                struct.pack("<HB", 0x303B, 2),
                struct.pack("<HB", 0x3012, 0),
                struct.pack("<HB", 0x3228, 1),
                struct.pack("<HH", 0x5033, 1),
                struct.pack("<HH", 0x500B, 2),
                struct.pack("<HH", 0x900C, 720),
                struct.pack("<HB", 0x3019, 1),
                struct.pack("<HB", 0x301A, 2),
                struct.pack("<HH", 0x5040, 4),
                struct.pack("<HH", 0x5042, 1),
                struct.pack("<HI", 0x703A, 0x12345678),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1100),
                struct.pack("<Hh", 0x9023, 1200),
                struct.pack("<Hh", 0x9024, 1300),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("fixture.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=2052,
            report=report,
            default_footnote_position="pageBottom",
            default_endnote_position="docEnd",
        )

        section = sections[0]
        self.assertEqual(section.page_number_format, "upperRoman")
        self.assertEqual(section.page_number_start, 123456)
        self.assertEqual(section.page_number_chapter_style, 2)
        self.assertEqual(section.page_number_chapter_separator, "emDash")
        self.assertEqual(section.line_number_count_by, 3)
        self.assertEqual(section.line_number_start, 4)
        self.assertEqual(section.line_number_distance_twips, 720)
        self.assertEqual(section.line_number_restart, "continuous")
        self.assertEqual(section.column_count, 3)
        self.assertEqual(section.column_spacing_twips, 720)
        self.assertTrue(section.columns_evenly_spaced)
        self.assertTrue(section.column_separator)
        self.assertEqual(section.vertical_alignment, "both")
        self.assertEqual(section.revision_save_id, 0x12345678)
        self.assertEqual(section.footnote_number_format, "lowerLetter")
        self.assertEqual(section.footnote_number_restart, "eachSect")
        self.assertEqual(section.footnote_position, "beneathText")
        self.assertEqual(section.endnote_number_format, "upperRoman")
        self.assertEqual(section.endnote_number_restart, "eachSect")
        self.assertEqual(section.endnote_position, "docEnd")
        self.assertTrue(section.suppress_endnotes)
        self.assertEqual(section.text_direction, "tbRl")
        self.assertTrue(section.bidirectional)
        self.assertFalse(report.warnings)

        document = Document(
            paragraphs=(Paragraph((TextRun("Body"),)),),
            sections=sections,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "section-properties.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        section_element = root.find(f"./{W}body/{W}sectPr")
        assert section_element is not None
        self.assertEqual(
            [child.tag for child in section_element],
            [
                f"{W}footnotePr",
                f"{W}endnotePr",
                f"{W}pgSz",
                f"{W}pgMar",
                f"{W}pgNumType",
                f"{W}lnNumType",
                f"{W}cols",
                f"{W}vAlign",
                f"{W}noEndnote",
                f"{W}textDirection",
                f"{W}bidi",
            ],
        )
        self.assertEqual(
            section_element.find(f"{W}footnotePr/{W}pos").get(f"{W}val"),  # type: ignore[union-attr]
            "beneathText",
        )
        self.assertEqual(
            section_element.find(f"{W}footnotePr/{W}numFmt").get(f"{W}val"),  # type: ignore[union-attr]
            "lowerLetter",
        )
        self.assertEqual(
            section_element.find(f"{W}footnotePr/{W}numRestart").get(f"{W}val"),  # type: ignore[union-attr]
            "eachSect",
        )
        self.assertEqual(
            section_element.find(f"{W}endnotePr/{W}pos").get(f"{W}val"),  # type: ignore[union-attr]
            "docEnd",
        )
        self.assertEqual(
            section_element.find(f"{W}endnotePr/{W}numFmt").get(f"{W}val"),  # type: ignore[union-attr]
            "upperRoman",
        )
        self.assertEqual(
            section_element.find(f"{W}pgNumType").get(f"{W}fmt"),  # type: ignore[union-attr]
            "upperRoman",
        )
        self.assertEqual(
            section_element.find(f"{W}pgNumType").get(f"{W}start"),  # type: ignore[union-attr]
            "123456",
        )
        self.assertEqual(
            section_element.find(f"{W}pgNumType").get(f"{W}chapStyle"),  # type: ignore[union-attr]
            "2",
        )
        self.assertEqual(
            section_element.find(f"{W}pgNumType").get(f"{W}chapSep"),  # type: ignore[union-attr]
            "emDash",
        )
        line_numbers = section_element.find(f"{W}lnNumType")
        assert line_numbers is not None
        self.assertEqual(line_numbers.get(f"{W}countBy"), "3")
        self.assertEqual(line_numbers.get(f"{W}start"), "4")
        self.assertEqual(line_numbers.get(f"{W}distance"), "720")
        self.assertEqual(line_numbers.get(f"{W}restart"), "continuous")
        self.assertEqual(
            section_element.find(f"{W}textDirection").get(f"{W}val"),  # type: ignore[union-attr]
            "tbRl",
        )
        columns = section_element.find(f"{W}cols")
        assert columns is not None
        self.assertEqual(columns.get(f"{W}num"), "3")
        self.assertEqual(columns.get(f"{W}space"), "720")
        self.assertEqual(columns.get(f"{W}equalWidth"), "1")
        self.assertEqual(columns.get(f"{W}sep"), "1")
        self.assertEqual(
            section_element.find(f"{W}vAlign").get(f"{W}val"),  # type: ignore[union-attr]
            "both",
        )
        self.assertEqual(section_element.get(f"{W}rsidSect"), "12345678")
        self.assertIsNotNone(section_element.find(f"{W}bidi"))

    def test_equivalent_duplicate_section_cps_are_repaired(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x301A, 1),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<3I", 0, 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0) * 2
        report = ConversionReport("duplicate-section.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=1033,
            report=report,
        )

        self.assertEqual(len(sections), 1)
        self.assertEqual((sections[0].cp_start, sections[0].cp_end), (0, 5))
        self.assertEqual(sections[0].vertical_alignment, "center")
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["SECTION_DUPLICATE_CP_REPAIRED"],
        )

    def test_different_duplicate_section_cps_are_rejected(self) -> None:
        first = b"".join(
            (
                struct.pack("<HB", 0x301A, 1),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        second = first.replace(
            struct.pack("<HB", 0x301A, 1),
            struct.pack("<HB", 0x301A, 3),
            1,
        )
        word_document = bytearray(192)
        struct.pack_into("<h", word_document, 32, len(first))
        word_document[34 : 34 + len(first)] = first
        struct.pack_into("<h", word_document, 96, len(second))
        word_document[98 : 98 + len(second)] = second
        plcf_sed = struct.pack("<3I", 0, 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        plcf_sed += struct.pack("<HiHI", 0, 96, 0, 0)

        with self.assertRaises(InvalidWordDocument):
            read_sections(
                plcf_sed,
                bytes(word_document),
                offset=0,
                size=len(plcf_sed),
                main_story_cp_count=5,
                document_lid=1033,
                report=ConversionReport("different-duplicate-section.doc"),
            )

    def test_unequal_column_widths_and_spacings_are_preserved(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HH", 0x500B, 1),
                struct.pack("<HB", 0x3005, 0),
                struct.pack("<HBH", 0xF203, 0, 3000),
                struct.pack("<HBH", 0xF203, 1, 5000),
                struct.pack("<HBH", 0xF204, 0, 400),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("unequal-columns.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=1033,
            report=report,
        )

        section = sections[0]
        self.assertFalse(section.columns_evenly_spaced)
        self.assertEqual(section.column_widths_twips, (3000, 5000))
        self.assertEqual(section.column_spacings_twips, (400,))
        self.assertFalse(report.warnings)

        document = Document(
            paragraphs=(Paragraph((TextRun("Body"),)),),
            sections=sections,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "unequal-columns.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        columns = root.find(f"./{W}body/{W}sectPr/{W}cols")
        assert columns is not None
        self.assertEqual(columns.get(f"{W}num"), "2")
        self.assertEqual(columns.get(f"{W}equalWidth"), "0")
        column_elements = columns.findall(f"{W}col")
        self.assertEqual(
            [column.get(f"{W}w") for column in column_elements],
            ["3000", "5000"],
        )
        self.assertEqual(column_elements[0].get(f"{W}space"), "400")
        self.assertIsNone(column_elements[1].get(f"{W}space"))

    def test_incomplete_unequal_columns_remain_deferred(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HH", 0x500B, 1),
                struct.pack("<HB", 0x3005, 0),
                struct.pack("<HBH", 0xF203, 0, 3000),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("incomplete-unequal-columns.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=1033,
            report=report,
        )

        self.assertIsNone(sections[0].column_widths_twips)
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["UNSUPPORTED_SECTION_SPRMS"],
        )
        self.assertEqual(report.warnings[0].details["opcodes"], ["0x3005"])

    def test_continuous_note_number_offsets_are_preserved(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x303C, 0),
                struct.pack("<HH", 0x503F, 6),
                struct.pack("<HB", 0x303E, 0),
                struct.pack("<HH", 0x5041, 9),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("note-starts.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=1033,
            report=report,
        )

        section = sections[0]
        self.assertEqual(section.footnote_number_start, 6)
        self.assertEqual(section.endnote_number_start, 9)
        self.assertFalse(report.warnings)

        document = Document(
            paragraphs=(Paragraph((TextRun("Body"),)),),
            sections=sections,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "note-starts.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        section_element = root.find(f"./{W}body/{W}sectPr")
        assert section_element is not None
        self.assertEqual(
            section_element.find(f"{W}footnotePr/{W}numStart").get(f"{W}val"),  # type: ignore[union-attr]
            "6",
        )
        self.assertEqual(
            section_element.find(f"{W}endnotePr/{W}numStart").get(f"{W}val"),  # type: ignore[union-attr]
            "9",
        )

    def test_note_offsets_are_ignored_when_numbering_restarts(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x303C, 1),
                struct.pack("<HH", 0x503F, 6),
                struct.pack("<HB", 0x303E, 1),
                struct.pack("<HH", 0x5041, 9),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=1033,
            report=ConversionReport("ignored-note-starts.doc"),
        )

        self.assertIsNone(sections[0].footnote_number_start)
        self.assertIsNone(sections[0].endnote_number_start)

    def test_page_number_start_is_ignored_without_restart(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x3011, 0),
                struct.pack("<HH", 0x501C, 7),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=1033,
            report=ConversionReport("continued-page-number.doc"),
        )

        self.assertIsNone(sections[0].page_number_start)

    def test_chapter_separator_is_ignored_when_chapter_numbering_is_disabled(
        self,
    ) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x3000, 2),
                struct.pack("<HB", 0x3001, 0),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(96)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=1033,
            report=ConversionReport("chapter-numbering-disabled.doc"),
        )

        self.assertIsNone(sections[0].page_number_chapter_style)
        self.assertIsNone(sections[0].page_number_chapter_separator)

    def test_out_of_range_chapter_heading_level_is_rejected(self) -> None:
        grpprl = struct.pack("<HB", 0x3001, 10)
        word_document = bytearray(64)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)

        with self.assertRaises(InvalidWordDocument):
            read_sections(
                plcf_sed,
                bytes(word_document),
                offset=0,
                size=len(plcf_sed),
                main_story_cp_count=5,
                document_lid=1033,
                report=ConversionReport("invalid-chapter-heading.doc"),
            )

    def test_out_of_range_modern_page_number_start_is_rejected(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x3011, 1),
                struct.pack("<HI", 0x7044, 0xFFFFFFFF),
            )
        )
        word_document = bytearray(64)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)

        with self.assertRaises(InvalidWordDocument):
            read_sections(
                plcf_sed,
                bytes(word_document),
                offset=0,
                size=len(plcf_sed),
                main_story_cp_count=5,
                document_lid=1033,
                report=ConversionReport("invalid-page-number.doc"),
            )

    def test_line_number_properties_are_ignored_when_disabled(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x3013, 1),
                struct.pack("<HH", 0x5015, 0),
                struct.pack("<HH", 0x9016, 720),
                struct.pack("<HH", 0x501B, 4),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=1033,
            report=ConversionReport("line-numbers-disabled.doc"),
        )

        self.assertIsNone(sections[0].line_number_count_by)
        self.assertIsNone(sections[0].line_number_start)
        self.assertIsNone(sections[0].line_number_distance_twips)
        self.assertIsNone(sections[0].line_number_restart)

    def test_out_of_range_line_number_values_are_rejected(self) -> None:
        for grpprl in (
            struct.pack("<HH", 0x5015, 101),
            struct.pack("<HH", 0x9016, 31681),
        ):
            word_document = bytearray(64)
            struct.pack_into("<h", word_document, 32, len(grpprl))
            word_document[34 : 34 + len(grpprl)] = grpprl
            plcf_sed = struct.pack("<2I", 0, 5)
            plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)

            with self.assertRaises(InvalidWordDocument):
                read_sections(
                    plcf_sed,
                    bytes(word_document),
                    offset=0,
                    size=len(plcf_sed),
                    main_story_cp_count=5,
                    document_lid=1033,
                    report=ConversionReport("invalid-line-number.doc"),
                )

    def test_incomplete_document_grid_is_reported_and_omitted(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
                struct.pack("<HH", 0x5032, 2),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("fixture.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=2052,
            report=report,
        )

        self.assertIsNone(sections[0].document_grid_type)
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["SECTION_GRID_INCOMPLETE"],
        )

    def test_unrepresentable_section_text_flow_is_reported(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HH", 0x5033, 2),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
            )
        )
        word_document = bytearray(96)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("fixture.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=2052,
            report=report,
        )

        self.assertIsNone(sections[0].text_direction)
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["UNSUPPORTED_SECTION_SPRMS"],
        )
        self.assertEqual(report.warnings[0].details["opcodes"], ["0x5033"])

    def test_malformed_plcf_sed_size_is_rejected(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_sections(
                bytes(19),
                bytes(64),
                offset=0,
                size=19,
                main_story_cp_count=1,
                document_lid=1033,
                report=ConversionReport("malformed.doc"),
            )

    def test_truncated_sepx_is_rejected(self) -> None:
        plcf_sed = struct.pack("<2I", 0, 1)
        plcf_sed += struct.pack("<HiHI", 0, 63, 0, 0)
        with self.assertRaises(InvalidWordDocument):
            read_sections(
                plcf_sed,
                bytes(64),
                offset=0,
                size=len(plcf_sed),
                main_story_cp_count=1,
                document_lid=1033,
                report=ConversionReport("truncated.doc"),
            )


if __name__ == "__main__":
    unittest.main()
