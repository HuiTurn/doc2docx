"""Word COM bilateral visual compare for doc2docx (dev/regression only).

This module must never be imported by the conversion engine. It depends on
optional packages: pywin32, Pillow, and PyMuPDF.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Word / Office constants
WD_ALERTS_NONE = 0
WD_DO_NOT_SAVE_CHANGES = 0
WD_EXPORT_FORMAT_PDF = 17
WD_EXPORT_OPTIMIZE_FOR_PRINT = 0
WD_FORMAT_DOCUMENT = 0  # Word 97-2003 .doc
WD_STATISTIC_PAGES = 2
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3

DEFAULT_DPI = 120


@dataclass(slots=True)
class PageMetrics:
    page_index: int
    reference_size: tuple[int, int]
    actual_size: tuple[int, int]
    size_mismatch: bool
    mae: float | None
    rmse: float | None
    changed_pixel_ratio: float | None
    ssim: float | None
    reference_png: str
    actual_png: str
    diff_png: str | None
    overlay_png: str | None


@dataclass(slots=True)
class StructureCounts:
    paragraphs: int
    tables: int
    inline_shapes: int
    shapes: int
    sections: int
    headers_footers: int
    footnotes: int
    endnotes: int
    pages: int
    page_width_pt: float | None = None
    page_height_pt: float | None = None


@dataclass(slots=True)
class CompareResult:
    provider: str
    word_version: str
    dpi: int
    source_path: str
    output_path: str
    source_sha256: str
    output_sha256: str
    source_pages: int
    output_pages: int
    page_count_mismatch: bool
    source_structure: StructureCounts
    output_structure: StructureCounts
    pages: list[PageMetrics]
    conversion_report: dict[str, Any]
    evidence_dir: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload

    @property
    def mean_mae(self) -> float | None:
        values = [page.mae for page in self.pages if page.mae is not None]
        if not values:
            return None
        return sum(values) / len(values)

    @property
    def max_changed_pixel_ratio(self) -> float | None:
        values = [
            page.changed_pixel_ratio
            for page in self.pages
            if page.changed_pixel_ratio is not None
        ]
        if not values:
            return None
        return max(values)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _require_visual_deps() -> tuple[Any, Any, Any]:
    try:
        from win32com.client import DispatchEx
    except ImportError as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "pywin32 is required for Word bilateral compare "
            "(install scripts/requirements-visual.txt)"
        ) from exc
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageStat
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Pillow is required for Word bilateral compare "
            "(install scripts/requirements-visual.txt)"
        ) from exc
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyMuPDF is required for Word bilateral compare "
            "(install scripts/requirements-visual.txt)"
        ) from exc
    return DispatchEx, (Image, ImageChops, ImageDraw, ImageStat), fitz


def _configure_word(word: Any) -> str:
    word.Visible = False
    word.DisplayAlerts = WD_ALERTS_NONE
    try:
        word.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
    except Exception:
        pass
    try:
        word.Options.UpdateLinksAtOpen = False
    except Exception:
        pass
    try:
        word.Options.ConfirmConversions = False
    except Exception:
        pass
    version = str(word.Version)
    return version


def _open_readonly(
    word: Any,
    path: Path,
    *,
    password: str | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "FileName": str(path.resolve()),
        "ConfirmConversions": False,
        "ReadOnly": True,
        "AddToRecentFiles": False,
        "NoEncodingDialog": True,
        "Visible": False,
    }
    if password is not None:
        kwargs["PasswordDocument"] = password
    return word.Documents.Open(**kwargs)


def _structure_counts(document: Any) -> StructureCounts:
    headers_footers = 0
    for section in document.Sections:
        for hf_index in range(1, 4):
            try:
                header = section.Headers(hf_index)
                if header is not None and header.Exists:
                    headers_footers += 1
            except Exception:
                pass
            try:
                footer = section.Footers(hf_index)
                if footer is not None and footer.Exists:
                    headers_footers += 1
            except Exception:
                pass
    page_width = None
    page_height = None
    try:
        page_width = float(document.PageSetup.PageWidth)
        page_height = float(document.PageSetup.PageHeight)
    except Exception:
        pass
    footnotes = 0
    endnotes = 0
    try:
        footnotes = int(document.Footnotes.Count)
    except Exception:
        pass
    try:
        endnotes = int(document.Endnotes.Count)
    except Exception:
        pass
    return StructureCounts(
        paragraphs=int(document.Paragraphs.Count),
        tables=int(document.Tables.Count),
        inline_shapes=int(document.InlineShapes.Count),
        shapes=int(document.Shapes.Count),
        sections=int(document.Sections.Count),
        headers_footers=headers_footers,
        footnotes=footnotes,
        endnotes=endnotes,
        pages=int(document.ComputeStatistics(WD_STATISTIC_PAGES)),
        page_width_pt=page_width,
        page_height_pt=page_height,
    )


def _export_pdf(document: Any, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if pdf_path.exists():
        pdf_path.unlink()
    document.ExportAsFixedFormat(
        OutputFileName=str(pdf_path.resolve()),
        ExportFormat=WD_EXPORT_FORMAT_PDF,
        OpenAfterExport=False,
        OptimizeFor=WD_EXPORT_OPTIMIZE_FOR_PRINT,
        BitmapMissingFonts=True,
        DocStructureTags=False,
        CreateBookmarks=0,
        UseISO19005_1=False,
    )


def render_pdf_pages(pdf_path: Path, pages_dir: Path, *, stem: str, dpi: int) -> list[Path]:
    _, _, fitz = _require_visual_deps()
    pages_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    paths: list[Path] = []
    with fitz.open(pdf_path) as pdf:
        for index, page in enumerate(pdf, start=1):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            target = pages_dir / f"{index:04d}_{stem}.png"
            pixmap.save(str(target))
            paths.append(target)
    return paths


def _ssim(reference: Any, actual: Any) -> float:
    """Lightweight SSIM on grayscale 8-bit images of equal size."""

    if reference.size != actual.size:
        return 0.0
    ref = reference.convert("L")
    act = actual.convert("L")
    # Downscale for speed on large pages while keeping relative structure.
    max_side = 512
    width, height = ref.size
    longest = max(width, height)
    if longest > max_side:
        ratio = max_side / float(longest)
        size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
        ref = ref.resize(size)
        act = act.resize(size)
    ref_pixels = list(ref.get_flattened_data())
    act_pixels = list(act.get_flattened_data())
    n = len(ref_pixels)
    if n == 0:
        return 0.0
    mean_x = sum(ref_pixels) / n
    mean_y = sum(act_pixels) / n
    var_x = sum((value - mean_x) ** 2 for value in ref_pixels) / n
    var_y = sum((value - mean_y) ** 2 for value in act_pixels) / n
    cov = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(ref_pixels, act_pixels)
    ) / n
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    numerator = (2 * mean_x * mean_y + c1) * (2 * cov + c2)
    denominator = (mean_x**2 + mean_y**2 + c1) * (var_x + var_y + c2)
    if denominator == 0:
        return 1.0
    return max(0.0, min(1.0, numerator / denominator))


def compare_page_images(
    reference_path: Path,
    actual_path: Path,
    *,
    diff_path: Path,
    overlay_path: Path,
    page_index: int,
    change_threshold: int = 12,
) -> PageMetrics:
    _, pillow, _ = _require_visual_deps()
    Image, ImageChops, ImageDraw, ImageStat = pillow
    reference = Image.open(reference_path).convert("RGB")
    actual = Image.open(actual_path).convert("RGB")
    size_mismatch = reference.size != actual.size
    mae = None
    rmse = None
    changed_ratio = None
    ssim = None
    diff_written: str | None = None
    overlay_written: str | None = None

    if not size_mismatch:
        diff = ImageChops.difference(reference, actual)
        stat = ImageStat.Stat(diff)
        # Mean absolute channel error averaged across RGB.
        mae = sum(stat.mean) / 3.0 / 255.0
        rmse = (sum(value * value for value in stat.mean) / 3.0) ** 0.5 / 255.0
        # Emphasize absolute difference for visual inspection.
        enhanced = diff.point(lambda value: min(255, value * 4))
        enhanced.save(diff_path)
        diff_written = str(diff_path)

        gray = diff.convert("L")
        changed = sum(1 for value in gray.get_flattened_data() if value > change_threshold)
        changed_ratio = changed / float(gray.size[0] * gray.size[1])
        ssim = _ssim(reference, actual)

        overlay = Image.blend(reference, actual, 0.5)
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 0, overlay.size[0] - 1, overlay.size[1] - 1), outline=(255, 0, 0))
        overlay.save(overlay_path)
        overlay_written = str(overlay_path)
    else:
        # Keep both images and a blank marker instead of silently rescaling.
        marker = Image.new("RGB", (max(reference.size[0], actual.size[0]), 64), (255, 240, 240))
        draw = ImageDraw.Draw(marker)
        draw.text(
            (8, 20),
            f"SIZE MISMATCH ref={reference.size} actual={actual.size}",
            fill=(180, 0, 0),
        )
        marker.save(diff_path)
        diff_written = str(diff_path)

    return PageMetrics(
        page_index=page_index,
        reference_size=reference.size,
        actual_size=actual.size,
        size_mismatch=size_mismatch,
        mae=mae,
        rmse=rmse,
        changed_pixel_ratio=changed_ratio,
        ssim=ssim,
        reference_png=str(reference_path),
        actual_png=str(actual_path),
        diff_png=diff_written,
        overlay_png=overlay_written,
    )


def _copy_readonly_temp(source: Path, directory: Path, *, suffix: str) -> Path:
    target = directory / f"readonly_{source.stem}{suffix}"
    shutil.copy2(source, target)
    return target


def create_word97_fixture(
    destination: Path,
    *,
    title: str = "doc2docx bilateral fixture",
    body: str = "Hello from Word bilateral fixture.\rBold line.\r",
) -> Path:
    """Create a minimal Word 97-2003 .doc via Word COM for visual regression."""

    DispatchEx, _, _ = _require_visual_deps()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    word = DispatchEx("Word.Application")
    document = None
    try:
        _configure_word(word)
        document = word.Documents.Add()
        document.Content.Text = body
        if document.Paragraphs.Count >= 2:
            document.Paragraphs(2).Range.Bold = True
        try:
            document.BuiltInDocumentProperties("Title").Value = title
        except Exception:
            pass
        if destination.exists():
            try:
                os.chmod(destination, 0o666)
            except OSError:
                pass
            destination.unlink()
        document.SaveAs(str(destination.resolve()), FileFormat=WD_FORMAT_DOCUMENT)
    finally:
        if document is not None:
            document.Close(WD_DO_NOT_SAVE_CHANGES)
        word.Quit()
        document = None
        word = None
    return destination


def compare_doc_pair(
    source_doc: Path,
    output_docx: Path,
    evidence_dir: Path,
    *,
    conversion_report: dict[str, Any] | None = None,
    dpi: int = DEFAULT_DPI,
    password: str | None = None,
) -> CompareResult:
    """Render source DOC and output DOCX through the same Word instance and diff pages."""

    DispatchEx, _, _ = _require_visual_deps()
    source_doc = Path(source_doc)
    output_docx = Path(output_docx)
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = evidence_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    source_sha = sha256_file(source_doc)
    output_sha = sha256_file(output_docx)
    report_payload = conversion_report or {}

    word = DispatchEx("Word.Application")
    source_document = None
    output_document = None
    temp_root = Path(tempfile.mkdtemp(prefix="doc2docx_word_visual_"))
    try:
        word_version = _configure_word(word)
        source_copy = _copy_readonly_temp(source_doc, temp_root, suffix=".doc")
        output_copy = _copy_readonly_temp(output_docx, temp_root, suffix=".docx")

        source_pdf = evidence_dir / "source_reference.pdf"
        output_pdf = evidence_dir / "output_actual.pdf"

        source_document = _open_readonly(word, source_copy, password=password)
        source_structure = _structure_counts(source_document)
        _export_pdf(source_document, source_pdf)
        source_document.Close(WD_DO_NOT_SAVE_CHANGES)
        source_document = None

        output_document = _open_readonly(word, output_copy)
        output_structure = _structure_counts(output_document)
        _export_pdf(output_document, output_pdf)
        output_document.Close(WD_DO_NOT_SAVE_CHANGES)
        output_document = None
    finally:
        if source_document is not None:
            try:
                source_document.Close(WD_DO_NOT_SAVE_CHANGES)
            except Exception:
                pass
        if output_document is not None:
            try:
                output_document.Close(WD_DO_NOT_SAVE_CHANGES)
            except Exception:
                pass
        try:
            word.Quit()
        except Exception:
            pass
        word = None
        shutil.rmtree(temp_root, ignore_errors=True)

    reference_pages = render_pdf_pages(source_pdf, pages_dir, stem="reference", dpi=dpi)
    actual_pages = render_pdf_pages(output_pdf, pages_dir, stem="actual", dpi=dpi)
    _, pillow, _ = _require_visual_deps()
    Image = pillow[0]
    page_metrics: list[PageMetrics] = []
    page_count = max(len(reference_pages), len(actual_pages))
    for index in range(page_count):
        page_number = index + 1
        if index >= len(reference_pages) or index >= len(actual_pages):
            reference_size = (0, 0)
            actual_size = (0, 0)
            reference_png = ""
            actual_png = ""
            if index < len(reference_pages):
                reference_png = str(reference_pages[index])
                reference_size = Image.open(reference_pages[index]).size
            if index < len(actual_pages):
                actual_png = str(actual_pages[index])
                actual_size = Image.open(actual_pages[index]).size
            page_metrics.append(
                PageMetrics(
                    page_index=page_number,
                    reference_size=reference_size,
                    actual_size=actual_size,
                    size_mismatch=True,
                    mae=None,
                    rmse=None,
                    changed_pixel_ratio=None,
                    ssim=None,
                    reference_png=reference_png,
                    actual_png=actual_png,
                    diff_png=None,
                    overlay_png=None,
                )
            )
            continue
        metrics = compare_page_images(
            reference_pages[index],
            actual_pages[index],
            diff_path=pages_dir / f"{page_number:04d}_diff.png",
            overlay_path=pages_dir / f"{page_number:04d}_overlay.png",
            page_index=page_number,
        )
        page_metrics.append(metrics)

    result = CompareResult(
        provider="office",
        word_version=word_version,
        dpi=dpi,
        source_path=str(source_doc.resolve()),
        output_path=str(output_docx.resolve()),
        source_sha256=source_sha,
        output_sha256=output_sha,
        source_pages=source_structure.pages,
        output_pages=output_structure.pages,
        page_count_mismatch=source_structure.pages != output_structure.pages,
        source_structure=source_structure,
        output_structure=output_structure,
        pages=page_metrics,
        conversion_report=report_payload,
        evidence_dir=str(evidence_dir.resolve()),
    )
    write_json(evidence_dir / "manifest.json", result.to_dict())
    return result


def convert_and_compare(
    source_doc: Path,
    evidence_dir: Path,
    *,
    dpi: int = DEFAULT_DPI,
    password: str | None = None,
    password_file: Path | None = None,
) -> CompareResult:
    """Convert with doc2docx then run Word bilateral visual compare."""

    source_doc = Path(source_doc)
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    secret = password
    if password_file is not None:
        secret = Path(password_file).read_text(encoding="utf-8").splitlines()[0]

    # Import converter only when running compare, keep scripts optional.
    src_root = Path(__file__).resolve().parents[1] / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    from doc2docx import convert

    output_docx = evidence_dir / f"{source_doc.stem}.docx"
    report_path = evidence_dir / "conversion_report.json"
    result = convert(source_doc, output_docx, password=secret)
    result.report.write_json(report_path)

    return compare_doc_pair(
        source_doc,
        output_docx,
        evidence_dir,
        conversion_report=result.report.to_dict(),
        dpi=dpi,
        password=secret,
    )


def compare_corpus(
    corpus_dir: Path,
    output_root: Path,
    *,
    dpi: int = DEFAULT_DPI,
    recursive: bool = False,
) -> list[CompareResult]:
    corpus_dir = Path(corpus_dir)
    pattern = "**/*.doc" if recursive else "*.doc"
    results: list[CompareResult] = []
    for source in sorted(corpus_dir.glob(pattern)):
        if source.name.startswith("~$"):
            continue
        case_dir = output_root / source.stem
        results.append(convert_and_compare(source, case_dir, dpi=dpi))
    summary = {
        "provider": "office",
        "dpi": dpi,
        "corpus": str(corpus_dir.resolve()),
        "cases": [
            {
                "source": item.source_path,
                "evidence_dir": item.evidence_dir,
                "page_count_mismatch": item.page_count_mismatch,
                "mean_mae": item.mean_mae,
                "max_changed_pixel_ratio": item.max_changed_pixel_ratio,
                "warning_codes": [
                    diagnostic.get("code")
                    for diagnostic in item.conversion_report.get("diagnostics", [])
                    if diagnostic.get("severity") == "warning"
                ],
            }
            for item in results
        ],
    }
    write_json(output_root / "corpus_summary.json", summary)
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Word COM bilateral visual compare: source DOC vs doc2docx DOCX "
            "(dev/regression only; not part of the converter runtime)."
        )
    )
    parser.add_argument("source", nargs="?", help="Source .doc path")
    parser.add_argument(
        "-o",
        "--output-dir",
        required=True,
        help="Evidence output directory",
    )
    parser.add_argument("--corpus", help="Directory of .doc files")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse when using --corpus",
    )
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--password-file", type=Path)
    parser.add_argument(
        "--create-fixture",
        type=Path,
        help="Create a minimal Word 97-2003 .doc fixture at this path and exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.create_fixture is not None:
        path = create_word97_fixture(args.create_fixture)
        print(json.dumps({"fixture": str(path.resolve())}, ensure_ascii=False))
        return 0
    output_dir = Path(args.output_dir)
    if args.corpus:
        results = compare_corpus(
            Path(args.corpus),
            output_dir,
            dpi=args.dpi,
            recursive=args.recursive,
        )
        print(
            json.dumps(
                {
                    "cases": len(results),
                    "summary": str((output_dir / "corpus_summary.json").resolve()),
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not args.source:
        parser.error("source .doc path is required unless --corpus/--create-fixture")
    result = convert_and_compare(
        Path(args.source),
        output_dir,
        dpi=args.dpi,
        password_file=args.password_file,
    )
    print(
        json.dumps(
            {
                "provider": result.provider,
                "word_version": result.word_version,
                "dpi": result.dpi,
                "source_pages": result.source_pages,
                "output_pages": result.output_pages,
                "page_count_mismatch": result.page_count_mismatch,
                "mean_mae": result.mean_mae,
                "max_changed_pixel_ratio": result.max_changed_pixel_ratio,
                "evidence_dir": result.evidence_dir,
                "manifest": str(Path(result.evidence_dir) / "manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
