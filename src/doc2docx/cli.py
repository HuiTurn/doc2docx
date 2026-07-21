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
from .errors import Doc2DocxError


def _limits(value: int) -> CompoundFileLimits:
    return CompoundFileLimits(max_input_bytes=value)


def _inspection_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doc2docx inspect")
    parser.add_argument("input", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--max-input-bytes", type=int, default=CompoundFileLimits().max_input_bytes
    )
    return parser


def _conversion_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc2docx",
        description="Convert an unencrypted Word 97-2003 .doc file to .docx",
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--max-input-bytes", type=int, default=CompoundFileLimits().max_input_bytes
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


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
        if arguments[:1] == ["inspect"]:
            args = _inspection_parser().parse_args(arguments[1:])
            info = inspect_doc(
                args.input,
                limits=_limits(args.max_input_bytes),
            )
            if args.as_json:
                print(json.dumps(info, ensure_ascii=False, indent=2))
            else:
                _print_inspection(info)
            return 0

        args = _conversion_parser().parse_args(arguments)
        result = convert(
            args.input,
            args.output,
            limits=_limits(args.max_input_bytes),
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
    except (Doc2DocxError, OSError) as exc:
        print(f"doc2docx: error: {exc}", file=sys.stderr)
        return 2

