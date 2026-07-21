"""Minimal parsing of document-wide settings from the MS-DOC DOP."""

from __future__ import annotations

from dataclasses import dataclass
import struct

from ..errors import InvalidWordDocument


@dataclass(slots=True, frozen=True)
class WordDocumentSettings:
    even_and_odd_headers: bool = False


def read_document_settings(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
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
    return WordDocumentSettings(even_and_odd_headers=bool(flags & 0x0001))
