"""Word COM bilateral visual regression tests (Windows + Word + optional deps)."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_compare_module():
    path = SCRIPTS / "word_bilateral_compare.py"
    spec = importlib.util.spec_from_file_location("word_bilateral_compare", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses with slots need the module present in sys.modules during exec.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _visual_stack_available() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Word bilateral compare requires Windows"
    try:
        import win32com.client  # noqa: F401
        from PIL import Image  # noqa: F401
        import fitz  # noqa: F401
    except ImportError as exc:
        return False, f"visual dependencies missing: {exc}"
    try:
        from win32com.client import DispatchEx

        word = DispatchEx("Word.Application")
        try:
            version = str(word.Version)
        finally:
            word.Quit()
    except Exception as exc:  # noqa: BLE001
        return False, f"Word.Application unavailable: {exc}"
    return True, version


class WordBilateralCompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        available, detail = _visual_stack_available()
        cls.visual_available = available
        cls.visual_detail = detail
        if available:
            cls.compare = _load_compare_module()

    def test_bilateral_pipeline_on_word_authored_fixture(self) -> None:
        if not self.visual_available:
            self.skipTest(self.visual_detail)

        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fixture = temporary / "bilateral_hello.doc"
            evidence = temporary / "evidence"
            self.compare.create_word97_fixture(
                fixture,
                title="bilateral-hello",
                body="Hello bilateral visual compare.\rSecond line stays editable.\r",
            )
            self.assertTrue(fixture.is_file())
            self.assertGreater(fixture.stat().st_size, 0)

            result = self.compare.convert_and_compare(fixture, evidence, dpi=96)

            self.assertEqual(result.provider, "office")
            self.assertTrue(result.word_version)
            self.assertEqual(result.dpi, 96)
            self.assertFalse(result.page_count_mismatch)
            self.assertEqual(result.source_pages, result.output_pages)
            self.assertGreaterEqual(result.source_pages, 1)
            self.assertEqual(len(result.pages), result.source_pages)

            manifest_path = evidence / "manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["provider"], "office")
            self.assertEqual(manifest["dpi"], 96)
            self.assertIn("source_sha256", manifest)
            self.assertIn("output_sha256", manifest)
            self.assertIn("conversion_report", manifest)

            page = result.pages[0]
            self.assertFalse(page.size_mismatch)
            self.assertIsNotNone(page.mae)
            self.assertIsNotNone(page.rmse)
            self.assertIsNotNone(page.changed_pixel_ratio)
            self.assertIsNotNone(page.ssim)
            self.assertTrue(Path(page.reference_png).is_file())
            self.assertTrue(Path(page.actual_png).is_file())
            assert page.diff_png is not None
            assert page.overlay_png is not None
            self.assertTrue(Path(page.diff_png).is_file())
            self.assertTrue(Path(page.overlay_png).is_file())

            # A Word-authored plain-text DOC should convert without structural
            # collapse; residual visual delta is reported, not hidden.
            assert page.mae is not None
            assert page.ssim is not None
            self.assertLess(page.mae, 0.15)
            self.assertGreater(page.ssim, 0.7)

            report = result.conversion_report
            self.assertIn("diagnostics", report)
            warning_codes = [
                item.get("code")
                for item in report.get("diagnostics", [])
                if item.get("severity") == "warning"
            ]
            # Padded OLEPS strings must not become U+FFFD core-property damage.
            self.assertNotIn("SUMMARY_INFORMATION_TEXT_REPAIRED", warning_codes)
            self.assertTrue((evidence / "conversion_report.json").is_file())
            self.assertTrue((evidence / f"{fixture.stem}.docx").is_file())
            with zipfile.ZipFile(evidence / f"{fixture.stem}.docx") as package:
                core_xml = package.read("docProps/core.xml")
            self.assertNotIn("\ufffd".encode("utf-8"), core_xml)

            # Re-open the product in Word without saving.
            from win32com.client import DispatchEx

            word = DispatchEx("Word.Application")
            document = None
            try:
                self.compare._configure_word(word)
                document = self.compare._open_readonly(
                    word, evidence / f"{fixture.stem}.docx"
                )
                self.assertGreaterEqual(document.Paragraphs.Count, 1)
                text = document.Content.Text
                self.assertIn("Hello bilateral visual compare", text)
            finally:
                if document is not None:
                    document.Close(False)
                word.Quit()


if __name__ == "__main__":
    unittest.main()
