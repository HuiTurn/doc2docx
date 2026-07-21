from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx import convert, inspect_doc
from doc2docx.errors import EncryptedDocumentError, UnsafeOutputPathError

from .fixtures import build_formatted_word_cfb, build_table_word_cfb, build_word_cfb


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ConversionTests(unittest.TestCase):
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
            self.assertEqual(info["fib"]["lcbPlcfBteChpx"], 0)
            self.assertEqual(info["fib"]["lcbPlcfBtePapx"], 0)
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
