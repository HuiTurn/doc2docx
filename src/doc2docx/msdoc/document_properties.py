"""Minimal parsing of document-wide settings from the MS-DOC DOP."""

from __future__ import annotations

from dataclasses import dataclass
import struct

from ..errors import InvalidWordDocument


@dataclass(slots=True, frozen=True)
class WordDocumentSettings:
    even_and_odd_headers: bool = False
    adjust_line_height_in_table: bool | None = None
    footnote_position: str | None = None
    endnote_position: str | None = None


def read_document_settings(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    n_fib: int = 0x00D9,
) -> WordDocumentSettings:
    if size == 0:
        return WordDocumentSettings()
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"DOP range [{offset}, {offset + size}) exceeds Table stream"
        )
    if size < 2:
        raise InvalidWordDocument("DOP is truncated before DopBase flags")
    flags = struct.unpack_from("<H", table_stream, offset)[0]
    footnote_position: str | None = None
    if n_fib <= 0x00D9:
        fpc = (flags >> 5) & 0x03
        footnote_position = {
            0x00: "sectEnd",
            0x01: "pageBottom",
            0x02: "beneathText",
        }.get(fpc)
        if footnote_position is None:
            raise InvalidWordDocument(f"DopBase has invalid fpc value {fpc}")
    endnote_position: str | None = None
    if size >= 56:
        epc = struct.unpack_from("<H", table_stream, offset + 54)[0] & 0x03
        endnote_position = {0x00: "sectEnd", 0x03: "docEnd"}.get(epc)
        if endnote_position is None:
            raise InvalidWordDocument(f"DopBase has invalid epc value {epc}")
    adjust_line_height_in_table: bool | None = None
    if size >= 88:
        copts80 = struct.unpack_from("<I", table_stream, offset + 84)[0]
        adjust_line_height_in_table = not bool(copts80 & 0x00000008)
    return WordDocumentSettings(
        even_and_odd_headers=bool(flags & 0x0001),
        adjust_line_height_in_table=adjust_line_height_in_table,
        footnote_position=footnote_position,
        endnote_position=endnote_position,
    )
