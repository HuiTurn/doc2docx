"""Command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from . import __version__
from .cfb import CompoundFileLimits
from .converter import convert, inspect_doc
from .diagnostics import write_json_file
from .errors import Doc2DocxError


def _limits(value: int) -> CompoundFileLimits:
    return CompoundFileLimits(max_input_bytes=value)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve().as_posix().casefold() == right.resolve().as_posix().casefold()


def _report_collision(
    report: Path | None,
    protected_paths: Sequence[Path],
) -> Path | None:
    if report is None:
        return None
    return next((path for path in protected_paths if _same_path(report, path)), None)


def _add_password_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--password")
    group.add_argument("--password-file", type=Path)


def _password(args: argparse.Namespace) -> str | None:
    if args.password is not None:
        return args.password
    if args.password_file is None:
        return None
    if args.password_file.stat().st_size > 4096:
        raise OSError("password file exceeds 4096 bytes")
    return args.password_file.read_text(encoding="utf-8").removesuffix("\n").removesuffix("\r")


def _inspection_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doc2docx inspect")
    parser.add_argument("input", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--max-input-bytes",
        type=_positive_int,
        default=CompoundFileLimits().max_input_bytes,
    )
    _add_password_arguments(parser)
    return parser


def _conversion_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc2docx",
        description="Convert a Word 97-2003 .doc file to .docx",
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--max-input-bytes",
        type=_positive_int,
        default=CompoundFileLimits().max_input_bytes,
    )
    parser.add_argument("--version", action="version", version=__version__)
    _add_password_arguments(parser)
    return parser


def _batch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc2docx batch",
        description="Convert a directory of Word 97-2003 .doc files",
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--max-input-bytes",
        type=_positive_int,
        default=CompoundFileLimits().max_input_bytes,
    )
    _add_password_arguments(parser)
    return parser


def _batch_sources(root: Path, *, recursive: bool) -> list[Path]:
    iterator = root.rglob("*") if recursive else root.iterdir()
    return sorted(
        (
            path
            for path in iterator
            if path.is_file() and path.suffix.casefold() == ".doc"
        ),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )


def _run_batch(args: argparse.Namespace) -> int:
    source_root: Path = args.input
    output_root: Path = args.output
    if not source_root.is_dir():
        print(f"doc2docx: error: batch input is not a directory: {source_root}", file=sys.stderr)
        return 2
    sources = _batch_sources(source_root, recursive=args.recursive)
    if not sources:
        print(f"doc2docx: error: no .doc files found in {source_root}", file=sys.stderr)
        return 2

    potential_destinations = [
        output_root / source.relative_to(source_root).with_suffix(".docx")
        for source in sources
    ]
    collision = _report_collision(
        args.report,
        (*sources, *potential_destinations),
    )
    if collision is not None:
        print(
            f"doc2docx: error: report path would overwrite {collision}",
            file=sys.stderr,
        )
        return 2
    password = _password(args)

    results: list[dict[str, object]] = []
    destinations: set[str] = set()
    succeeded = 0
    failed = 0
    warning_count = 0
    for source in sources:
        relative = source.relative_to(source_root).with_suffix(".docx")
        destination = output_root / relative
        destination_key = str(destination.resolve()).casefold()
        if destination_key in destinations:
            error = f"multiple inputs map to the same output {destination}"
            print(f"Failed {source}: {error}", file=sys.stderr)
            results.append(
                {
                    "source": str(source),
                    "destination": str(destination),
                    "status": "failed",
                    "error": error,
                }
            )
            failed += 1
            continue
        destinations.add(destination_key)
        try:
            conversion = convert(
                source,
                destination,
                limits=_limits(args.max_input_bytes),
                password=password,
            )
        except (Doc2DocxError, OSError) as exc:
            print(f"Failed {source}: {exc}", file=sys.stderr)
            results.append(
                {
                    "source": str(source),
                    "destination": str(destination),
                    "status": "failed",
                    "error": str(exc),
                }
            )
            failed += 1
            continue
        warnings = len(conversion.report.warnings)
        warning_count += warnings
        succeeded += 1
        print(f"Converted {source} -> {destination}")
        results.append(
            {
                "source": str(source),
                "destination": str(destination),
                "status": "converted",
                "warning_count": warnings,
                "report": conversion.report.to_dict(),
            }
        )

    summary = {
        "input": str(source_root),
        "output": str(output_root),
        "recursive": bool(args.recursive),
        "file_count": len(sources),
        "succeeded": succeeded,
        "failed": failed,
        "warning_count": warning_count,
        "results": results,
    }
    if args.report:
        write_json_file(args.report, summary)
    print(
        f"Batch complete: {succeeded} converted, {failed} failed, "
        f"{warning_count} warning(s)",
        file=sys.stderr if failed else sys.stdout,
    )
    return 1 if failed else 0


def _print_inspection(info: dict[str, object]) -> None:
    cfb = info["cfb"]
    fib = info["fib"]
    assert isinstance(cfb, dict) and isinstance(fib, dict)
    print(f"Input: {info['path']}")
    print(
        f"CFB: version {cfb['major_version']}, sector size {cfb['sector_size']}, "
        f"{cfb['sector_count']} sectors"
    )
    print(
        f"FIB: nFib=0x{int(fib['nFib']):04X}, table={fib['table_stream']}, "
        f"ccpText={fib['ccpText']}, encrypted={fib['encrypted']}"
    )
    print("Streams and storages:")
    entries = info["entries"]
    assert isinstance(entries, list)
    for item in entries:
        size = "" if item["size"] is None else f" ({item['size']} bytes)"
        print(f"  {item['type']:12} {item['path']}{size}")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments[:1] == ["batch"]:
            return _run_batch(_batch_parser().parse_args(arguments[1:]))
        if arguments[:1] == ["inspect"]:
            args = _inspection_parser().parse_args(arguments[1:])
            info = inspect_doc(
                args.input,
                limits=_limits(args.max_input_bytes),
                password=_password(args),
            )
            if args.as_json:
                print(json.dumps(info, ensure_ascii=False, indent=2))
            else:
                _print_inspection(info)
            return 0

        args = _conversion_parser().parse_args(arguments)
        destination = args.output or args.input.with_suffix(".docx")
        collision = _report_collision(
            args.report,
            (args.input, destination),
        )
        if collision is not None:
            print(
                f"doc2docx: error: report path would overwrite {collision}",
                file=sys.stderr,
            )
            return 2
        result = convert(
            args.input,
            args.output,
            limits=_limits(args.max_input_bytes),
            password=_password(args),
        )
        if args.report:
            result.report.write_json(args.report)
        print(f"Converted {args.input} -> {result.output_path}")
        if result.report.warnings:
            print(
                f"Completed with {len(result.report.warnings)} warning(s)",
                file=sys.stderr,
            )
        return 0
    except (Doc2DocxError, OSError, UnicodeError) as exc:
        print(f"doc2docx: error: {exc}", file=sys.stderr)
        return 2
