import unittest
from unittest.mock import Mock
from pathlib import Path
import tempfile
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import (
    Document,
    FloatingTextBox,
    Paragraph,
    SectionProperties,
    ShapeStyle,
    TextRun,
)
from doc2docx.msdoc import read_document_settings, read_header_footer_stories
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"


class HeaderFooterParsingTests(unittest.TestCase):
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
                inset_left_emu=12700,
                inset_top_emu=25400,
                inset_right_emu=38100,
                inset_bottom_emu=50800,
            ),
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
        fill = rectangle.find(f"{V}fill")
        stroke = rectangle.find(f"{V}stroke")
        textbox_element = rectangle.find(f"{V}textbox")
        assert fill is not None
        assert stroke is not None
        assert textbox_element is not None
        self.assertEqual(fill.get("opacity"), "50%")
        self.assertEqual(stroke.get("opacity"), "25%")
        self.assertEqual(textbox_element.get("inset"), "1pt,2pt,3pt,4pt")

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
