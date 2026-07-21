import unittest
from unittest.mock import Mock
from pathlib import Path
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import Document, Paragraph, SectionProperties, TextRun
from doc2docx.msdoc import read_document_settings, read_header_footer_stories
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class HeaderFooterParsingTests(unittest.TestCase):
    def test_dop_facing_pages_flag_is_read(self) -> None:
        settings = read_document_settings(b"\x01\x00", offset=0, size=2)
        self.assertTrue(settings.even_and_odd_headers)
        self.assertIsNone(settings.adjust_line_height_in_table)

    def test_dop_table_grid_line_height_compatibility_is_read(self) -> None:
        dop = bytearray(88)
        settings = read_document_settings(dop, offset=0, size=len(dop))
        self.assertTrue(settings.adjust_line_height_in_table)

        dop[84] = 0x08
        settings = read_document_settings(dop, offset=0, size=len(dop))
        self.assertFalse(settings.adjust_line_height_in_table)

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
