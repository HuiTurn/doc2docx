from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import Document, Paragraph, TextRun
from doc2docx.msdoc import read_font_table, read_style_sheet
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _font_table() -> bytes:
    name = "Times New Roman\0".encode("utf-16le")
    ffn = b"".join(
        (
            bytes((0x11,)),
            struct.pack("<h", 400),
            bytes((0, 0)),
            bytes(range(10)),
            struct.pack("<6I", 1, 2, 3, 4, 5, 6),
            name,
        )
    )
    return struct.pack("<HHB", 1, 0, len(ffn)) + ffn


def _xstz(name: str) -> bytes:
    return struct.pack("<H", len(name)) + name.encode("utf-16le") + b"\0\0"


def _lpupx(value: bytes) -> bytes:
    return struct.pack("<H", len(value)) + value + (b"\0" if len(value) & 1 else b"")


def _paragraph_std(
    name: str,
    *,
    index: int,
    based_on: int | None,
    character_grpprl: bytes,
) -> bytes:
    based_on_value = 0x0FFF if based_on is None else based_on
    base = struct.pack(
        "<5H",
        0,
        (based_on_value << 4) | 1,
        (index << 4) | 2,
        0,
        0,
    )
    paragraph_upx = struct.pack("<H", index)
    return base + _xstz(name) + _lpupx(paragraph_upx) + _lpupx(character_grpprl)


def _style_sheet() -> bytes:
    normal = _paragraph_std(
        "Normal",
        index=0,
        based_on=None,
        character_grpprl=struct.pack("<HB", 0x0835, 1),
    )
    derived = _paragraph_std(
        "Derived",
        index=1,
        based_on=0,
        character_grpprl=struct.pack("<HB", 0x0835, 0x81),
    )
    stshif = struct.pack("<6H3h", 2, 10, 0, 2, 0, 0, 0, 0, 0)
    return b"".join(
        (
            struct.pack("<H", len(stshif)),
            stshif,
            struct.pack("<H", len(normal)),
            normal,
            struct.pack("<H", len(derived)),
            derived,
        )
    )


class FontAndStyleTests(unittest.TestCase):
    def test_parses_fonts_and_resolves_style_relative_toggle(self) -> None:
        font_bytes = _font_table()
        fonts = read_font_table(font_bytes, offset=0, size=len(font_bytes))
        report = ConversionReport("styles.doc")
        style_bytes = _style_sheet()
        styles = read_style_sheet(
            style_bytes,
            offset=0,
            size=len(style_bytes),
            fonts=fonts,
            report=report,
        )

        self.assertEqual(fonts[0].name, "Times New Roman")
        self.assertEqual(fonts[0].family, "roman")
        self.assertEqual(fonts[0].pitch, "fixed")
        self.assertEqual(styles.styles[1].based_on, 0)  # type: ignore[union-attr]
        self.assertFalse(
            styles.styles[1].character_properties.bold  # type: ignore[union-attr]
        )
        self.assertFalse(styles.effective_character_at(1).bold)
        self.assertFalse(report.warnings)

    def test_writes_font_and_style_parts_with_relationships(self) -> None:
        font_bytes = _font_table()
        fonts = read_font_table(font_bytes, offset=0, size=len(font_bytes))
        style_bytes = _style_sheet()
        styles = read_style_sheet(
            style_bytes,
            offset=0,
            size=len(style_bytes),
            fonts=fonts,
            report=ConversionReport("styles.doc"),
        )
        document = Document((Paragraph((TextRun("Styled"),)),), fonts, styles)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "styles.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                self.assertIn("word/styles.xml", package.namelist())
                self.assertIn("word/fontTable.xml", package.namelist())
                self.assertIn("word/_rels/document.xml.rels", package.namelist())
                style_root = ET.fromstring(package.read("word/styles.xml"))
                font_root = ET.fromstring(package.read("word/fontTable.xml"))

        derived = style_root.findall(f"{W}style")[1]
        self.assertEqual(derived.get(f"{W}styleId"), "DocStyle1")
        self.assertEqual(
            derived.find(f"{W}basedOn").get(f"{W}val"),  # type: ignore[union-attr]
            "DocStyle0",
        )
        self.assertEqual(
            font_root.find(f"{W}font").get(f"{W}name"),  # type: ignore[union-attr]
            "Times New Roman",
        )


if __name__ == "__main__":
    unittest.main()
