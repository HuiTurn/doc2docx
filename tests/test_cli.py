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
            report = temporary / "report.json"
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

            inspection_output = StringIO()
            with redirect_stdout(inspection_output), redirect_stderr(StringIO()):
                status = main(["inspect", str(source), "--json"])
            self.assertEqual(status, 0)
            self.assertEqual(
                json.loads(inspection_output.getvalue())["fib"]["table_stream"],
                "1Table",
            )
