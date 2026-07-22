"""Minimal parsing of document-wide settings from the MS-DOC DOP."""

from __future__ import annotations

from dataclasses import dataclass
import struct

from ..errors import InvalidWordDocument
from .number_formats import NUMBER_FORMATS


@dataclass(slots=True, frozen=True)
class WordDocumentSettings:
    even_and_odd_headers: bool = False
    mirror_margins: bool = False
    gutter_at_top: bool = False
    default_tab_stop_twips: int | None = None
    auto_hyphenation: bool | None = None
    do_not_hyphenate_caps: bool | None = None
    hyphenation_zone_twips: int | None = None
    consecutive_hyphen_limit: int | None = None
    adjust_line_height_in_table: bool | None = None
    footnote_position: str | None = None
    footnote_number_format: str | None = None
    footnote_number_start: int | None = None
    footnote_number_restart: str | None = None
    endnote_position: str | None = None
    endnote_number_format: str | None = None
    endnote_number_start: int | None = None
    endnote_number_restart: str | None = None


_NUMBER_RESTARTS = {
    0x00: "continuous",
    0x01: "eachSect",
    0x02: "eachPage",
}


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
    extended_flags = (
        struct.unpack_from("<I", table_stream, offset + 4)[0]
        if size >= 8
        else 0
    )
    view_flags = (
        struct.unpack_from("<H", table_stream, offset + 82)[0]
        if size >= 84
        else 0
    )
    default_tab_stop_twips: int | None = None
    if size >= 12:
        default_tab_stop_twips = struct.unpack_from(
            "<H",
            table_stream,
            offset + 10,
        )[0]
        if default_tab_stop_twips > 32767:
            raise InvalidWordDocument(
                "DopBase default tab stop exceeds the OOXML signed-short range"
            )
    hyphenation_zone_twips = (
        struct.unpack_from("<H", table_stream, offset + 14)[0]
        if size >= 16
        else None
    )
    consecutive_hyphen_limit = (
        struct.unpack_from("<H", table_stream, offset + 16)[0]
        if size >= 18
        else None
    )
    footnote_position: str | None = None
    footnote_number_format: str | None = None
    footnote_number_start: int | None = None
    footnote_number_restart: str | None = None
    if size >= 4:
        footnote_numbering = struct.unpack_from(
            "<H",
            table_stream,
            offset + 2,
        )[0]
        # Word-compatible writers retain the document-wide starting value in
        # DopBase even for newer nFib versions, while moving restart behavior
        # to section SPRMs. Reading the high 14 bits is therefore a safe
        # interoperability fallback; the low restart bits remain legacy-only.
        footnote_number_start = footnote_numbering >> 2
    if n_fib <= 0x00D9:
        fpc = (flags >> 5) & 0x03
        footnote_position = {
            0x00: "sectEnd",
            0x01: "pageBottom",
            0x02: "beneathText",
        }.get(fpc)
        if footnote_position is None:
            raise InvalidWordDocument(f"DopBase has invalid fpc value {fpc}")
        if size >= 4:
            footnote_number_restart = _NUMBER_RESTARTS.get(
                footnote_numbering & 0x03
            )
            if footnote_number_restart is None:
                raise InvalidWordDocument(
                    "DopBase has invalid rncFtn value "
                    f"{footnote_numbering & 0x03}"
                )
    endnote_position: str | None = None
    endnote_number_format: str | None = None
    endnote_number_start: int | None = None
    endnote_number_restart: str | None = None
    if size >= 54:
        endnote_numbering = struct.unpack_from(
            "<H",
            table_stream,
            offset + 52,
        )[0]
        endnote_number_start = endnote_numbering >> 2
        if n_fib <= 0x00D9:
            endnote_number_restart = _NUMBER_RESTARTS.get(
                endnote_numbering & 0x03
            )
            if endnote_number_restart is None:
                raise InvalidWordDocument(
                    "DopBase has invalid rncEdn value "
                    f"{endnote_numbering & 0x03}"
                )
    if size >= 496:
        footnote_format_value, endnote_format_value = struct.unpack_from(
            "<HH",
            table_stream,
            offset + 492,
        )
        footnote_number_format = NUMBER_FORMATS.get(footnote_format_value)
        endnote_number_format = NUMBER_FORMATS.get(endnote_format_value)
        if footnote_number_format is None and n_fib <= 0x00D9:
            raise InvalidWordDocument(
                "Dop97 has invalid nfcFtnRef value "
                f"0x{footnote_format_value:04X}"
            )
        if endnote_number_format is None and n_fib <= 0x00D9:
            raise InvalidWordDocument(
                "Dop97 has invalid nfcEdnRef value "
                f"0x{endnote_format_value:04X}"
            )
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
        mirror_margins=bool(extended_flags & (1 << 21)),
        gutter_at_top=bool(view_flags & (1 << 15)),
        default_tab_stop_twips=default_tab_stop_twips,
        auto_hyphenation=(
            bool(extended_flags & (1 << 12)) if size >= 8 else None
        ),
        do_not_hyphenate_caps=(
            not bool(extended_flags & (1 << 11)) if size >= 8 else None
        ),
        hyphenation_zone_twips=hyphenation_zone_twips,
        consecutive_hyphen_limit=consecutive_hyphen_limit,
        adjust_line_height_in_table=adjust_line_height_in_table,
        footnote_position=footnote_position,
        footnote_number_format=footnote_number_format,
        footnote_number_start=footnote_number_start,
        footnote_number_restart=footnote_number_restart,
        endnote_position=endnote_position,
        endnote_number_format=endnote_number_format,
        endnote_number_start=endnote_number_start,
        endnote_number_restart=endnote_number_restart,
    )
