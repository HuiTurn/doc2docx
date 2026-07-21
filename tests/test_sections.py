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
                struct.pack("<HB", 0x300E, 1),
                struct.pack("<HB", 0x303C, 1),
                struct.pack("<HB", 0x303E, 1),
                struct.pack("<HB", 0x3228, 1),
                struct.pack("<HH", 0x5033, 1),
                struct.pack("<HH", 0x5040, 4),
                struct.pack("<HH", 0x5042, 1),
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
        )

        section = sections[0]
        self.assertEqual(section.page_number_format, "upperRoman")
        self.assertEqual(section.footnote_number_format, "lowerLetter")
        self.assertEqual(section.footnote_number_restart, "eachSect")
        self.assertEqual(section.endnote_number_format, "upperRoman")
        self.assertEqual(section.endnote_number_restart, "eachSect")
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
                f"{W}textDirection",
                f"{W}bidi",
            ],
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
            section_element.find(f"{W}endnotePr/{W}numFmt").get(f"{W}val"),  # type: ignore[union-attr]
            "upperRoman",
        )
        self.assertEqual(
            section_element.find(f"{W}pgNumType").get(f"{W}fmt"),  # type: ignore[union-attr]
            "upperRoman",
        )
        self.assertEqual(
            section_element.find(f"{W}textDirection").get(f"{W}val"),  # type: ignore[union-attr]
            "tbRl",
        )
        self.assertIsNotNone(section_element.find(f"{W}bidi"))

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
