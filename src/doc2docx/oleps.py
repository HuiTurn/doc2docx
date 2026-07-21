"""Bounded [MS-OLEPS] SummaryInformation property-set parsing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import struct

from .diagnostics import ConversionReport, SourceLocation
from .errors import InvalidWordDocument
from .model import CoreProperties


_MAX_PROPERTY_SET_STREAM = 2 * 1024 * 1024
_SUMMARY_INFORMATION_FMTID = bytes.fromhex(
    "e0859ff2f94f6810ab9108002b27b3d9"
)
_VT_I2 = 0x0002
_VT_LPSTR = 0x001E
_VT_LPWSTR = 0x001F
_VT_FILETIME = 0x0040

_STRING_PROPERTIES = {
    0x02: "title",
    0x03: "subject",
    0x04: "creator",
    0x05: "keywords",
    0x06: "description",
    0x08: "last_modified_by",
    0x09: "revision",
}
_TIME_PROPERTIES = {
    0x0B: "last_printed",
    0x0C: "created",
    0x0D: "modified",
}


def _require_range(
    data: bytes,
    offset: int,
    size: int,
    *,
    limit: int | None = None,
    label: str,
) -> None:
    upper = len(data) if limit is None else limit
    if offset < 0 or size < 0 or upper > len(data) or offset > upper - size:
        raise InvalidWordDocument(
            f"{label} range [{offset}, {offset + size}) exceeds its property set"
        )


def _property_type(data: bytes, start: int, end: int, *, label: str) -> int:
    _require_range(data, start, 4, limit=end, label=label)
    value_type, padding = struct.unpack_from("<HH", data, start)
    if padding:
        raise InvalidWordDocument(f"{label} has nonzero type padding")
    return value_type


def _read_codepage(data: bytes, start: int, end: int) -> int:
    value_type = _property_type(
        data,
        start,
        end,
        label="SummaryInformation CodePage",
    )
    if value_type != _VT_I2:
        raise InvalidWordDocument("SummaryInformation CodePage is not VT_I2")
    _require_range(
        data,
        start + 4,
        4,
        limit=end,
        label="SummaryInformation CodePage value",
    )
    codepage, padding = struct.unpack_from("<HH", data, start + 4)
    if padding:
        raise InvalidWordDocument("SummaryInformation CodePage has nonzero padding")
    if codepage == 0:
        raise InvalidWordDocument("SummaryInformation CodePage is zero")
    return codepage


def _codec_for_codepage(codepage: int) -> str:
    if codepage == 1200:
        return "utf-16le"
    if codepage == 1201:
        return "utf-16be"
    if codepage == 65001:
        return "utf-8"
    return f"cp{codepage}"


def _is_xml_character(character: str) -> bool:
    value = ord(character)
    return (
        value in (0x09, 0x0A, 0x0D)
        or 0x20 <= value <= 0xD7FF
        or 0xE000 <= value <= 0xFFFD
        or 0x10000 <= value <= 0x10FFFF
    ) and value not in (0xFFFE, 0xFFFF)


def _read_string(
    data: bytes,
    start: int,
    end: int,
    *,
    codepage: int,
    property_id: int,
    report: ConversionReport,
) -> str | None:
    label = f"SummaryInformation property 0x{property_id:08X}"
    value_type = _property_type(data, start, end, label=label)
    if value_type not in (_VT_LPSTR, _VT_LPWSTR):
        report.warning(
            "SUMMARY_INFORMATION_PROPERTY_SKIPPED",
            "a core string property used an incompatible OLE property type",
            location=SourceLocation(stream="\\x05SummaryInformation"),
            property_id=f"0x{property_id:08X}",
            property_type=f"0x{value_type:04X}",
        )
        return None
    _require_range(data, start + 4, 4, limit=end, label=f"{label} length")
    character_count = struct.unpack_from("<I", data, start + 4)[0]
    wide = value_type == _VT_LPWSTR or (
        value_type == _VT_LPSTR and codepage in (1200, 1201)
    )
    byte_count = character_count * (2 if wide else 1)
    _require_range(data, start + 8, byte_count, limit=end, label=f"{label} text")
    raw = data[start + 8 : start + 8 + byte_count]
    terminator = b"\0\0" if wide else b"\0"
    if character_count and not raw.endswith(terminator):
        raise InvalidWordDocument(f"{label} is not null-terminated")
    payload = raw[: -len(terminator)] if character_count else raw
    codec = "utf-16le" if value_type == _VT_LPWSTR else _codec_for_codepage(codepage)
    try:
        value = payload.decode(codec)
    except LookupError:
        report.warning(
            "SUMMARY_INFORMATION_CODEPAGE_APPROXIMATED",
            "an unknown SummaryInformation code page was decoded as Windows-1252",
            location=SourceLocation(stream="\\x05SummaryInformation"),
            codepage=codepage,
        )
        value = payload.decode("cp1252", errors="replace")
    except UnicodeDecodeError:
        report.warning(
            "SUMMARY_INFORMATION_TEXT_REPAIRED",
            "invalid text in a core document property was decoded with replacements",
            location=SourceLocation(stream="\\x05SummaryInformation"),
            property_id=f"0x{property_id:08X}",
            codepage=codepage,
        )
        value = payload.decode(codec, errors="replace")
    repaired = "".join(
        character if _is_xml_character(character) else "\uFFFD"
        for character in value
    )
    if repaired != value:
        report.warning(
            "SUMMARY_INFORMATION_TEXT_REPAIRED",
            "characters that are invalid in XML were replaced in a core property",
            location=SourceLocation(stream="\\x05SummaryInformation"),
            property_id=f"0x{property_id:08X}",
        )
        value = repaired
    return value or None


def _read_filetime(
    data: bytes,
    start: int,
    end: int,
    *,
    property_id: int,
    report: ConversionReport,
) -> str | None:
    label = f"SummaryInformation property 0x{property_id:08X}"
    value_type = _property_type(data, start, end, label=label)
    if value_type != _VT_FILETIME:
        report.warning(
            "SUMMARY_INFORMATION_PROPERTY_SKIPPED",
            "a core date property used an incompatible OLE property type",
            location=SourceLocation(stream="\\x05SummaryInformation"),
            property_id=f"0x{property_id:08X}",
            property_type=f"0x{value_type:04X}",
        )
        return None
    _require_range(data, start + 4, 8, limit=end, label=f"{label} FILETIME")
    ticks = struct.unpack_from("<Q", data, start + 4)[0]
    if ticks == 0:
        return None
    try:
        value = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(
            microseconds=ticks // 10
        )
    except OverflowError as exc:
        raise InvalidWordDocument(f"{label} FILETIME is outside the datetime range") from exc
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def read_summary_information(
    data: bytes,
    *,
    report: ConversionReport,
) -> CoreProperties:
    """Parse the simple SummaryInformation property set used by legacy DOC."""

    if len(data) > _MAX_PROPERTY_SET_STREAM:
        raise InvalidWordDocument(
            f"SummaryInformation exceeds {_MAX_PROPERTY_SET_STREAM} bytes"
        )
    if len(data) < 48:
        raise InvalidWordDocument("SummaryInformation PropertySetStream is truncated")
    byte_order, version = struct.unpack_from("<HH", data)
    if byte_order != 0xFFFE:
        raise InvalidWordDocument("SummaryInformation has invalid byte order")
    if version not in (0, 1):
        raise InvalidWordDocument(
            f"SummaryInformation has unsupported version {version}"
        )
    property_set_count = struct.unpack_from("<I", data, 24)[0]
    if property_set_count not in (1, 2):
        raise InvalidWordDocument(
            f"SummaryInformation has invalid property-set count {property_set_count}"
        )
    descriptor_end = 28 + property_set_count * 20
    _require_range(data, 28, property_set_count * 20, label="property-set descriptors")
    property_set_offset: int | None = None
    for index in range(property_set_count):
        position = 28 + index * 20
        format_id = data[position : position + 16]
        offset = struct.unpack_from("<I", data, position + 16)[0]
        if format_id == _SUMMARY_INFORMATION_FMTID:
            if property_set_offset is not None:
                raise InvalidWordDocument(
                    "SummaryInformation repeats its property-set format identifier"
                )
            property_set_offset = offset
    if property_set_offset is None:
        raise InvalidWordDocument(
            "SummaryInformation format identifier is absent"
        )
    if property_set_offset < descriptor_end or property_set_offset % 4:
        raise InvalidWordDocument("SummaryInformation property-set offset is invalid")
    _require_range(data, property_set_offset, 8, label="SummaryInformation PropertySet")
    property_set_size, property_count = struct.unpack_from(
        "<II", data, property_set_offset
    )
    if property_set_size < 8 or property_set_offset > len(data) - property_set_size:
        raise InvalidWordDocument("SummaryInformation PropertySet size is invalid")
    property_set_end = property_set_offset + property_set_size
    table_size = 8 + property_count * 8
    if property_count > (property_set_size - 8) // 8:
        raise InvalidWordDocument("SummaryInformation property count is invalid")
    _require_range(
        data,
        property_set_offset + 8,
        property_count * 8,
        limit=property_set_end,
        label="SummaryInformation property table",
    )

    property_offsets: dict[int, int] = {}
    for index in range(property_count):
        property_id, relative_offset = struct.unpack_from(
            "<II", data, property_set_offset + 8 + index * 8
        )
        if property_id in property_offsets:
            raise InvalidWordDocument(
                f"SummaryInformation repeats property 0x{property_id:08X}"
            )
        if (
            relative_offset < table_size
            or relative_offset >= property_set_size
            or relative_offset % 4
        ):
            raise InvalidWordDocument(
                f"SummaryInformation property 0x{property_id:08X} offset is invalid"
            )
        property_offsets[property_id] = property_set_offset + relative_offset

    ordered = sorted((offset, property_id) for property_id, offset in property_offsets.items())
    boundaries: dict[int, tuple[int, int]] = {}
    for index, (start, property_id) in enumerate(ordered):
        end = ordered[index + 1][0] if index + 1 < len(ordered) else property_set_end
        if end - start < 4:
            raise InvalidWordDocument(
                f"SummaryInformation property 0x{property_id:08X} is truncated"
            )
        boundaries[property_id] = (start, end)

    codepage = 1252
    if 0x01 in boundaries:
        codepage = _read_codepage(data, *boundaries[0x01])
    else:
        report.warning(
            "SUMMARY_INFORMATION_CODEPAGE_DEFAULTED",
            "SummaryInformation has no CodePage property; Windows-1252 was assumed",
            location=SourceLocation(stream="\\x05SummaryInformation"),
        )

    values: dict[str, str | None] = {}
    for property_id, field_name in _STRING_PROPERTIES.items():
        bounds = boundaries.get(property_id)
        if bounds is not None:
            values[field_name] = _read_string(
                data,
                *bounds,
                codepage=codepage,
                property_id=property_id,
                report=report,
            )
    for property_id, field_name in _TIME_PROPERTIES.items():
        bounds = boundaries.get(property_id)
        if bounds is not None:
            values[field_name] = _read_filetime(
                data,
                *bounds,
                property_id=property_id,
                report=report,
            )
    return CoreProperties(**values)
