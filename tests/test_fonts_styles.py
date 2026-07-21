from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    BorderProperties,
    CharacterProperties,
    Document,
    Paragraph,
    ParagraphProperties,
    StyleDefinition,
    StyleSheet,
    Symbol,
    Table,
    TableCell,
    TableRow,
    TableRowProperties,
    TableBorders,
    TabStop,
    TextRun,
)
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


def _table_style_sheet() -> bytes:
    normal = _paragraph_std(
        "Normal",
        index=0,
        based_on=None,
        character_grpprl=b"",
    )
    derived = _paragraph_std(
        "Derived",
        index=1,
        based_on=0,
        character_grpprl=b"",
    )
    table_index = 2
    table_base = struct.pack(
        "<5H",
        0,
        (0x0FFF << 4) | 3,
        (table_index << 4) | 3,
        0,
        0,
    )
    default_margins = struct.pack("<BBBBBH", 6, 0, 1, 0x0A, 3, 108)
    tapx = (
        struct.pack("<HH", 0x563A, table_index)
        + struct.pack("<H", 0xD634)
        + default_margins
    )
    papx = struct.pack("<HHB", table_index, 0x2403, 3)
    chpx = struct.pack("<HH", 0x4A50, 0)
    table = (
        table_base
        + _xstz("Plain Table")
        + _lpupx(tapx)
        + _lpupx(papx)
        + _lpupx(chpx)
    )
    stshif = struct.pack("<6H3h", 3, 10, 0, 3, 0, 0, 0, 0, 0)
    return b"".join(
        (
            struct.pack("<H", len(stshif)),
            stshif,
            struct.pack("<H", len(normal)),
            normal,
            struct.pack("<H", len(derived)),
            derived,
            struct.pack("<H", len(table)),
            table,
        )
    )


class FontAndStyleTests(unittest.TestCase):
    def test_repairs_unassigned_style_language_lid(self) -> None:
        normal = _paragraph_std(
            "Normal",
            index=0,
            based_on=None,
            character_grpprl=struct.pack("<HH", 0x486E, 0x00FF),
        )
        stshif = struct.pack("<6H3h", 1, 10, 0, 1, 0, 0, 0, 0, 0)
        style_bytes = b"".join(
            (
                struct.pack("<H", len(stshif)),
                stshif,
                struct.pack("<H", len(normal)),
                normal,
            )
        )
        report = ConversionReport("unassigned-language.doc")

        styles = read_style_sheet(
            style_bytes,
            offset=0,
            size=len(style_bytes),
            fonts=(),
            report=report,
        )

        normal_style = styles.styles[0]
        assert normal_style is not None
        self.assertEqual(normal_style.character_properties.east_asia_language, "zxx")
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["UNASSIGNED_STYLE_LANGUAGE_LID_REPAIRED"],
        )

    def test_repairs_empty_libreoffice_font_slot_without_shifting_index(self) -> None:
        payload = bytes(39) + b"\0\0"
        table = struct.pack("<HHB", 1, 0, len(payload)) + payload
        report = ConversionReport("unnamed-font.doc")

        fonts = read_font_table(table, offset=0, size=len(table), report=report)

        self.assertEqual(fonts[0].index, 0)
        self.assertEqual(fonts[0].name, "Unnamed DOC font 0")
        self.assertEqual(report.warnings[0].code, "UNNAMED_FONT_SLOT_REPAIRED")

    def test_writes_paragraph_outline_and_borders(self) -> None:
        document = Document(
            (
                Paragraph(
                    (TextRun("Outlined"),),
                    ParagraphProperties(
                        outline_level=2,
                        suppress_line_numbers=True,
                        suppress_auto_hyphens=True,
                        contextual_spacing=True,
                        auto_spacing_before=True,
                        auto_spacing_after=False,
                        bidirectional=True,
                        borders=TableBorders(
                            top=BorderProperties("single", 4, "112233"),
                        ),
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "outlined.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        outline = root.find(f".//{W}pPr/{W}outlineLvl")
        border = root.find(f".//{W}pPr/{W}pBdr/{W}top")
        paragraph_properties = root.find(f".//{W}pPr")
        assert outline is not None
        assert border is not None
        assert paragraph_properties is not None
        self.assertEqual(outline.get(f"{W}val"), "2")
        self.assertEqual(border.get(f"{W}color"), "112233")
        for name in ("suppressLineNumbers", "suppressAutoHyphens", "bidi"):
            self.assertIsNotNone(paragraph_properties.find(f"{W}{name}"))
        spacing = paragraph_properties.find(f"{W}spacing")
        assert spacing is not None
        self.assertEqual(spacing.get(f"{W}beforeAutospacing"), "1")
        self.assertEqual(spacing.get(f"{W}afterAutospacing"), "0")
        self.assertIsNotNone(paragraph_properties.find(f"{W}contextualSpacing"))
        self.assertEqual(
            [child.tag for child in paragraph_properties],
            [
                f"{W}suppressLineNumbers",
                f"{W}pBdr",
                f"{W}suppressAutoHyphens",
                f"{W}bidi",
                f"{W}spacing",
                f"{W}contextualSpacing",
                f"{W}outlineLvl",
            ],
        )

    def test_writes_custom_tab_stops(self) -> None:
        document = Document(
            (
                Paragraph(
                    (TextRun("Tabbed"),),
                    ParagraphProperties(
                        tab_stops=(
                            TabStop(720, "clear"),
                            TabStop(1440, "center", "dot"),
                        ),
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "tabs.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        tabs = root.findall(f".//{W}pPr/{W}tabs/{W}tab")
        self.assertEqual(
            [(tab.get(f"{W}pos"), tab.get(f"{W}val")) for tab in tabs],
            [("720", "clear"), ("1440", "center")],
        )
        self.assertEqual(tabs[1].get(f"{W}leader"), "dot")

    def test_root_style_materializes_document_default_fonts(self) -> None:
        effective = CharacterProperties(
            ascii_font="Times New Roman",
            high_ansi_font="Times New Roman",
            east_asia_font="SimSun",
            size_half_points=21,
        )
        style_sheet = StyleSheet(
            styles=(
                StyleDefinition(
                    index=0,
                    name="Normal",
                    kind="paragraph",
                    character_properties=CharacterProperties(
                        size_half_points=21,
                    ),
                ),
            ),
            default_character_properties=CharacterProperties(
                ascii_font="Times New Roman",
                high_ansi_font="Times New Roman",
                east_asia_font="SimSun",
            ),
            effective_character_properties=(effective,),
        )
        document = Document(
            (Paragraph((TextRun("Styled"),)),),
            styles=style_sheet,
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "root-style.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/styles.xml"))

        fonts = root.find(f"{W}style/{W}rPr/{W}rFonts")
        assert fonts is not None
        self.assertEqual(fonts.get(f"{W}ascii"), "Times New Roman")
        self.assertEqual(fonts.get(f"{W}hAnsi"), "Times New Roman")
        self.assertEqual(fonts.get(f"{W}eastAsia"), "SimSun")

    def test_writes_paragraph_spacing_in_line_units(self) -> None:
        document = Document(
            (
                Paragraph(
                    (TextRun("Grid spacing"),),
                    ParagraphProperties(
                        space_before_lines=25,
                        space_after_lines=50,
                    ),
                    mark_properties=CharacterProperties(
                        east_asia_font="SimSun",
                        complex_script_size_half_points=21,
                    ),
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "paragraph-spacing.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        spacing = root.find(f".//{W}spacing")
        assert spacing is not None
        self.assertEqual(spacing.get(f"{W}beforeLines"), "25")
        self.assertEqual(spacing.get(f"{W}afterLines"), "50")
        mark_properties = root.find(f".//{W}pPr/{W}rPr")
        assert mark_properties is not None
        mark_fonts = mark_properties.find(f"{W}rFonts")
        assert mark_fonts is not None
        self.assertEqual(mark_fonts.get(f"{W}eastAsia"), "SimSun")
        self.assertEqual(
            mark_properties.find(f"{W}szCs").get(f"{W}val"),  # type: ignore[union-attr]
            "21",
        )

    def test_writes_symbol_character(self) -> None:
        document = Document(
            (Paragraph((Symbol("Wingdings", 0xF03A),)),),
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "symbol.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        symbol = root.find(f".//{W}sym")
        assert symbol is not None
        self.assertEqual(symbol.get(f"{W}font"), "Wingdings")
        self.assertEqual(symbol.get(f"{W}char"), "F03A")

    def test_writes_script_specific_character_properties(self) -> None:
        properties = CharacterProperties(
            east_asia_font="SimSun",
            font_hint="eastAsia",
            bold=True,
            complex_script_bold=False,
            italic=False,
            complex_script_italic=True,
            size_half_points=21,
            complex_script_size_half_points=24,
            kerning_half_points=2,
            spacing_twips=-20,
            no_proof=True,
            language="en-US",
            east_asia_language="zh-CN",
            complex_script_language="ar-SA",
        )
        document = Document(
            (Paragraph((TextRun("中文", properties),)),),
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "scripts.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        run_properties = root.find(f".//{W}rPr")
        assert run_properties is not None
        fonts = run_properties.find(f"{W}rFonts")
        assert fonts is not None
        self.assertEqual(fonts.get(f"{W}eastAsia"), "SimSun")
        self.assertEqual(fonts.get(f"{W}hint"), "eastAsia")
        self.assertIsNotNone(run_properties.find(f"{W}b"))
        self.assertEqual(
            run_properties.find(f"{W}bCs").get(f"{W}val"),  # type: ignore[union-attr]
            "0",
        )
        self.assertEqual(
            run_properties.find(f"{W}i").get(f"{W}val"),  # type: ignore[union-attr]
            "0",
        )
        self.assertIsNotNone(run_properties.find(f"{W}iCs"))
        self.assertEqual(
            run_properties.find(f"{W}sz").get(f"{W}val"),  # type: ignore[union-attr]
            "21",
        )
        self.assertEqual(
            run_properties.find(f"{W}szCs").get(f"{W}val"),  # type: ignore[union-attr]
            "24",
        )
        self.assertEqual(
            run_properties.find(f"{W}kern").get(f"{W}val"),  # type: ignore[union-attr]
            "2",
        )
        self.assertEqual(
            run_properties.find(f"{W}spacing").get(f"{W}val"),  # type: ignore[union-attr]
            "-20",
        )
        self.assertIsNotNone(run_properties.find(f"{W}noProof"))
        language = run_properties.find(f"{W}lang")
        assert language is not None
        self.assertEqual(language.get(f"{W}val"), "en-US")
        self.assertEqual(language.get(f"{W}eastAsia"), "zh-CN")
        self.assertEqual(language.get(f"{W}bidi"), "ar-SA")

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

    def test_parses_and_writes_unconditional_table_style_properties(self) -> None:
        font_bytes = _font_table()
        fonts = read_font_table(font_bytes, offset=0, size=len(font_bytes))
        style_bytes = _table_style_sheet()
        report = ConversionReport("table-style.doc")
        styles = read_style_sheet(
            style_bytes,
            offset=0,
            size=len(style_bytes),
            fonts=fonts,
            report=report,
        )
        table_style = styles.styles[2]
        assert table_style is not None
        self.assertEqual(table_style.kind, "table")
        self.assertEqual(table_style.paragraph_properties.justification, "both")
        self.assertEqual(
            table_style.character_properties.east_asia_font,
            "Times New Roman",
        )
        assert table_style.paragraph_properties.table_row is not None
        self.assertEqual(
            table_style.paragraph_properties.table_row.default_cell_margins.left,
            108,
        )
        self.assertFalse(report.warnings)

        paragraph = Paragraph((TextRun("Styled cell"),))
        table = Table(
            (
                TableRow(
                    (TableCell((paragraph,)),),
                    TableRowProperties(table_style_id=2),
                ),
            )
        )
        document = Document(
            (paragraph,),
            fonts,
            styles,
            blocks=(table,),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "table-style.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                document_root = ET.fromstring(package.read("word/document.xml"))
                style_root = ET.fromstring(package.read("word/styles.xml"))

        table_reference = document_root.find(f".//{W}tblPr/{W}tblStyle")
        assert table_reference is not None
        self.assertEqual(table_reference.get(f"{W}val"), "DocStyle2")
        table_style_xml = style_root.find(f"{W}style[@{W}styleId='DocStyle2']")
        assert table_style_xml is not None
        self.assertEqual(table_style_xml.get(f"{W}type"), "table")
        self.assertEqual(
            table_style_xml.find(f"{W}pPr/{W}jc").get(f"{W}val"),  # type: ignore[union-attr]
            "both",
        )
        self.assertEqual(
            table_style_xml.find(f"{W}rPr/{W}rFonts").get(f"{W}eastAsia"),  # type: ignore[union-attr]
            "Times New Roman",
        )
        self.assertEqual(
            table_style_xml.find(f"{W}tblPr/{W}tblCellMar/{W}left").get(  # type: ignore[union-attr]
                f"{W}w"
            ),
            "108",
        )

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
