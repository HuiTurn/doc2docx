from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from doc2docx.cli import main

from .fixtures import build_word_cfb


class CommandLineTests(unittest.TestCase):
    def test_convert_and_inspect_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "cli.doc"
            output = temporary / "cli.docx"
            report = temporary / "reports" / "report.json"
            source.write_bytes(build_word_cfb())

            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                status = main(
                    [str(source), "-o", str(output), "--report", str(report)]
                )
            self.assertEqual(status, 0)
            self.assertTrue(output.exists())
            self.assertEqual(
                json.loads(report.read_text(encoding="utf-8"))["statistics"][
                    "piece_count"
                ],
                2,
            )
            self.assertEqual(list(report.parent.glob("*.tmp")), [])

            inspection_output = StringIO()
            with redirect_stdout(inspection_output), redirect_stderr(StringIO()):
                status = main(["inspect", str(source), "--json"])
            self.assertEqual(status, 0)
            self.assertEqual(
                json.loads(inspection_output.getvalue())["fib"]["table_stream"],
                "1Table",
            )

    def test_batch_converts_recursively_and_isolates_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source_root = temporary / "inputs"
            nested = source_root / "nested"
            output_root = temporary / "outputs"
            summary_path = temporary / "batch-report.json"
            nested.mkdir(parents=True)
            (source_root / "good.doc").write_bytes(build_word_cfb())
            (nested / "also-good.DOC").write_bytes(build_word_cfb())
            (nested / "bad.doc").write_bytes(b"not a compound document")
            (source_root / "ignored.docx").write_bytes(b"ignored")

            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = main(
                    [
                        "batch",
                        str(source_root),
                        "-o",
                        str(output_root),
                        "--recursive",
                        "--report",
                        str(summary_path),
                    ]
                )

            self.assertEqual(status, 1)
            self.assertTrue((output_root / "good.docx").exists())
            self.assertTrue((output_root / "nested" / "also-good.docx").exists())
            self.assertFalse((output_root / "nested" / "bad.docx").exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(
                (summary["file_count"], summary["succeeded"], summary["failed"]),
                (3, 2, 1),
            )
            self.assertIn("Batch complete: 2 converted, 1 failed", stderr.getvalue())

    def test_batch_skips_word_lock_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source_root = temporary / "inputs"
            output_root = temporary / "outputs"
            summary_path = temporary / "batch-report.json"
            source_root.mkdir()
            (source_root / "good.doc").write_bytes(build_word_cfb())
            (source_root / "~$locked.doc").write_bytes(b"\0" * 162)

            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                status = main(
                    [
                        "batch",
                        str(source_root),
                        "-o",
                        str(output_root),
                        "--report",
                        str(summary_path),
                    ]
                )

            self.assertEqual(status, 0)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(
                (summary["file_count"], summary["succeeded"], summary["failed"]),
                (1, 1, 0),
            )
            self.assertFalse((output_root / "~$locked.docx").exists())

    def test_password_file_converts_xor_obfuscated_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "encrypted.doc"
            output = temporary / "encrypted.docx"
            password_file = temporary / "password.txt"
            source.write_bytes(build_word_cfb(password="swordfish"))
            password_file.write_text("swordfish\n", encoding="utf-8")

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                status = main(
                    [
                        str(source),
                        "-o",
                        str(output),
                        "--password-file",
                        str(password_file),
                    ]
                )

            self.assertEqual(status, 0)
            self.assertTrue(output.exists())

    def test_batch_requires_a_directory_with_doc_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            empty = temporary / "empty"
            empty.mkdir()

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(["batch", str(empty), "-o", str(temporary / "out")]),
                    2,
                )

    def test_report_cannot_overwrite_input_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source.doc"
            output = temporary / "output.docx"
            payload = build_word_cfb()
            source.write_bytes(payload)

            for report in (source, output):
                with self.subTest(report=report.name):
                    stderr = StringIO()
                    with redirect_stdout(StringIO()), redirect_stderr(stderr):
                        status = main(
                            [
                                str(source),
                                "-o",
                                str(output),
                                "--report",
                                str(report),
                            ]
                        )
                    self.assertEqual(status, 2)
                    self.assertIn("report path would overwrite", stderr.getvalue())
                    self.assertEqual(source.read_bytes(), payload)
                    self.assertFalse(output.exists())

    def test_invalid_utf8_password_file_is_reported_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source.doc"
            password_file = temporary / "password.txt"
            source.write_bytes(build_word_cfb())
            password_file.write_bytes(b"\xFF")

            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                status = main(
                    [
                        str(source),
                        "--password-file",
                        str(password_file),
                    ]
                )

            self.assertEqual(status, 2)
            self.assertIn("doc2docx: error:", stderr.getvalue())
