from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    Document,
    Paragraph,
    ParagraphProperties,
    Table,
    TableCellDefinition,
    TableRowProperties,
    TextRun,
    parse_main_story,
)
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class TableConversionTests(unittest.TestCase):
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
        cells = table.findall(f"{W}tr/{W}tc")
        self.assertEqual(len(cells), 2)
        self.assertEqual(["".join(cell.itertext()) for cell in cells], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
