from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    BorderProperties,
    Document,
    Paragraph,
    ParagraphProperties,
    ShadingProperties,
    Table,
    TableBorders,
    TableCellDefinition,
    TableCellMarginOverride,
    TableCellMargins,
    TableCellWidthOverride,
    TableRowProperties,
    TextRun,
    parse_main_story,
)
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class TableConversionTests(unittest.TestCase):
    def test_preferred_table_and_cell_widths_and_border_colors_are_written(self) -> None:
        border = BorderProperties("single", 4, "auto")
        row = TableRowProperties(
            preferred_width=2200,
            preferred_width_type="dxa",
            left_indent_twips=-360,
            cell_boundaries_twips=(0, 1000, 2200),
            cell_definitions=(TableCellDefinition(), TableCellDefinition()),
            borders=TableBorders(
                top=border,
                left=border,
                bottom=border,
                right=border,
                inside_horizontal=border,
                inside_vertical=border,
            ),
            cell_width_overrides=(TableCellWidthOverride(0, 1, 900),),
            cell_top_border_colors=("FF0000", "auto"),
        )
        cell_properties = ParagraphProperties(in_table=True)
        row_mark = ParagraphProperties(
            in_table=True,
            table_terminating=True,
            table_row=row,
        )

        document = parse_main_story(
            "A\x07B\x07\x07",
            ConversionReport("widths.doc"),
            paragraph_properties_at=(
                lambda cp: row_mark if cp == 4 else cell_properties
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "widths.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        table_width = root.find(f".//{W}tblPr/{W}tblW")
        assert table_width is not None
        self.assertEqual(table_width.get(f"{W}w"), "2200")
        self.assertEqual(table_width.get(f"{W}type"), "dxa")
        table_indent = root.find(f".//{W}tblPr/{W}tblInd")
        assert table_indent is not None
        self.assertEqual(table_indent.get(f"{W}w"), "-360")
        self.assertEqual(table_indent.get(f"{W}type"), "dxa")
        cell_widths = root.findall(f".//{W}tr/{W}tc/{W}tcPr/{W}tcW")
        self.assertEqual([value.get(f"{W}w") for value in cell_widths], ["900", "1200"])
        first_top = root.find(f".//{W}tr/{W}tc[1]/{W}tcPr/{W}tcBorders/{W}top")
        assert first_top is not None
        self.assertEqual(first_top.get(f"{W}color"), "FF0000")

    def test_cell_margins_and_shading_are_written(self) -> None:
        row = TableRowProperties(
            cell_boundaries_twips=(0, 1000, 2200),
            cell_definitions=(TableCellDefinition(), TableCellDefinition()),
            default_cell_margins=TableCellMargins(left=108, right=108),
            cell_margin_overrides=(
                TableCellMarginOverride(1, 2, ("top", "bottom"), 36),
            ),
            cell_shadings=(
                ShadingProperties("solid", "FF0000", "FFFF00"),
                None,
            ),
        )
        cell_properties = ParagraphProperties(in_table=True)
        row_mark = ParagraphProperties(
            in_table=True,
            table_terminating=True,
            table_row=row,
        )

        def properties_at(cp: int) -> ParagraphProperties:
            return row_mark if cp == 4 else cell_properties

        document = parse_main_story(
            "A\x07B\x07\x07",
            ConversionReport("formatted-table.doc"),
            paragraph_properties_at=properties_at,
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "formatted-table.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        cells = root.findall(f"./{W}body/{W}tbl/{W}tr/{W}tc")
        self.assertEqual(len(cells), 2)
        for cell in cells:
            left = cell.find(f"{W}tcPr/{W}tcMar/{W}left")
            assert left is not None
            self.assertEqual(left.get(f"{W}w"), "108")
        top = cells[1].find(f"{W}tcPr/{W}tcMar/{W}top")
        assert top is not None
        self.assertEqual(top.get(f"{W}w"), "36")
        shading = cells[0].find(f"{W}tcPr/{W}shd")
        assert shading is not None
        self.assertEqual(shading.get(f"{W}val"), "solid")
        self.assertEqual(shading.get(f"{W}color"), "FF0000")
        self.assertEqual(shading.get(f"{W}fill"), "FFFF00")

    def test_nested_table_is_retained_inside_outer_cell(self) -> None:
        outer_row = TableRowProperties(
            cell_boundaries_twips=(0, 3000),
            cell_definitions=(TableCellDefinition(),),
        )
        inner_row = TableRowProperties(
            cell_boundaries_twips=(0, 1800),
            cell_definitions=(TableCellDefinition(),),
        )

        def properties_at(cp: int) -> ParagraphProperties:
            if cp == 5:
                return ParagraphProperties(in_table=True, table_depth=1)
            if cp == 11:
                return ParagraphProperties(
                    in_table=True,
                    table_depth=2,
                    inner_table_cell=True,
                )
            if cp == 12:
                return ParagraphProperties(
                    in_table=True,
                    table_depth=2,
                    inner_table_row=True,
                    table_row=inner_row,
                )
            if cp == 13:
                return ParagraphProperties(in_table=True, table_depth=1)
            if cp == 14:
                return ParagraphProperties(
                    in_table=True,
                    table_depth=1,
                    table_terminating=True,
                    table_row=outer_row,
                )
            return ParagraphProperties()

        report = ConversionReport("nested-table.doc")
        document = parse_main_story(
            "Outer\rInner\r\r\x07\x07After\r",
            report,
            paragraph_properties_at=properties_at,
        )

        outer = document.body_blocks[0]
        assert isinstance(outer, Table)
        outer_content = outer.rows[0].cells[0].body_blocks
        self.assertEqual(len(outer_content), 3)
        self.assertIsInstance(outer_content[1], Table)
        inner = outer_content[1]
        assert isinstance(inner, Table)
        self.assertEqual(
            inner.rows[0].cells[0].paragraphs[0].inlines,
            (TextRun("Inner"),),
        )
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nested-table.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        self.assertEqual(len(root.findall(f".//{W}tbl")), 2)
        outer_cell = root.find(f"./{W}body/{W}tbl/{W}tr/{W}tc")
        assert outer_cell is not None
        self.assertEqual(
            [child.tag for child in outer_cell if child.tag != f"{W}tcPr"],
            [f"{W}p", f"{W}tbl", f"{W}p"],
        )

    def test_horizontal_and_vertical_cell_merges_are_retained(self) -> None:
        cell_properties = ParagraphProperties(in_table=True)
        row_mark = ParagraphProperties(
            in_table=True,
            table_terminating=True,
            table_row=TableRowProperties(
                cell_boundaries_twips=(0, 1000, 2200),
                cell_definitions=(
                    TableCellDefinition(
                        horizontal_merge="restart",
                        vertical_merge="restart",
                    ),
                    TableCellDefinition(horizontal_merge="continue"),
                ),
            ),
        )

        def properties_at(cp: int) -> ParagraphProperties:
            return row_mark if cp == 3 else cell_properties

        document = parse_main_story(
            "A\x07\x07\x07",
            ConversionReport("merged-table.doc"),
            paragraph_properties_at=properties_at,
        )

        table = document.body_blocks[0]
        assert isinstance(table, Table)
        self.assertEqual(len(table.rows[0].cells), 1)
        merged = table.rows[0].cells[0]
        self.assertEqual(merged.grid_span, 2)
        self.assertEqual(merged.width_twips, 2200)
        self.assertEqual(merged.vertical_merge, "restart")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "merged-table.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        cell_properties_xml = root.find(
            f"./{W}body/{W}tbl/{W}tr/{W}tc/{W}tcPr"
        )
        assert cell_properties_xml is not None
        grid_span = cell_properties_xml.find(f"{W}gridSpan")
        vertical_merge = cell_properties_xml.find(f"{W}vMerge")
        assert grid_span is not None
        assert vertical_merge is not None
        self.assertEqual(grid_span.get(f"{W}val"), "2")
        self.assertEqual(vertical_merge.get(f"{W}val"), "restart")

    def test_cell_and_row_markers_build_a_table_in_body_order(self) -> None:
        cell_properties = ParagraphProperties(in_table=True)
        row_properties = ParagraphProperties(
            in_table=True,
            table_terminating=True,
            table_row=TableRowProperties(
                cell_boundaries_twips=(0, 1000, 2200),
                cell_definitions=(TableCellDefinition(), TableCellDefinition()),
            ),
        )

        def properties_at(cp: int) -> ParagraphProperties:
            if cp in (1, 3):
                return cell_properties
            if cp == 4:
                return row_properties
            return ParagraphProperties()

        report = ConversionReport("table.doc")
        document = parse_main_story(
            "A\x07B\x07\x07After\r",
            report,
            paragraph_properties_at=properties_at,
        )

        self.assertEqual(len(document.paragraphs), 3)
        self.assertIsInstance(document.body_blocks[0], Table)
        table = document.body_blocks[0]
        assert isinstance(table, Table)
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(
            [cell.paragraphs[0].inlines for cell in table.rows[0].cells],
            [(TextRun("A"),), (TextRun("B"),)],
        )
        self.assertEqual([cell.width_twips for cell in table.rows[0].cells], [1000, 1200])
        self.assertIsInstance(document.body_blocks[1], Paragraph)
        self.assertFalse(report.warnings)

    def test_writes_table_grid_rows_cells_and_widths(self) -> None:
        row = TableRowProperties(
            cell_boundaries_twips=(0, 1000, 2200),
            cell_definitions=(TableCellDefinition(), TableCellDefinition()),
            gap_half_twips=222,
        )
        cell_properties = ParagraphProperties(in_table=True)
        row_mark = ParagraphProperties(
            in_table=True,
            table_terminating=True,
            table_row=row,
        )

        def properties_at(cp: int) -> ParagraphProperties:
            return row_mark if cp == 4 else cell_properties

        parsed = parse_main_story(
            "A\x07B\x07\x07",
            ConversionReport("table.doc"),
            paragraph_properties_at=properties_at,
        )
        document = Document(parsed.paragraphs, blocks=parsed.blocks)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "table.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        table = root.find(f"./{W}body/{W}tbl")
        assert table is not None
        self.assertEqual(
            [column.get(f"{W}w") for column in table.findall(f"{W}tblGrid/{W}gridCol")],
            ["1000", "1200"],
        )
        left_margin = table.find(f"{W}tblPr/{W}tblCellMar/{W}left")
        assert left_margin is not None
        self.assertEqual(left_margin.get(f"{W}w"), "108")
        cells = table.findall(f"{W}tr/{W}tc")
        self.assertEqual(len(cells), 2)
        self.assertEqual(["".join(cell.itertext()) for cell in cells], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
