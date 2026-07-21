"""MS-DOC SttbfFfn and FFN font-table parsing."""

from __future__ import annotations

import struct

from ..errors import InvalidWordDocument
from ..model import FontDefinition


_FONT_FAMILIES = {
    0: "auto",
    1: "roman",
    2: "swiss",
    3: "modern",
    4: "script",
    5: "decorative",
}

_FONT_PITCHES = {
    0: "default",
    1: "fixed",
    2: "variable",
}


def _decode_xsz_ffn(data: bytes, *, label: str) -> tuple[str, ...]:
    if len(data) % 2:
        raise InvalidWordDocument(f"{label} font names have an odd byte count")
    code_units = struct.unpack(f"<{len(data) // 2}H", data)
    names: list[str] = []
    start = 0
    for index, value in enumerate(code_units):
        if value != 0:
            continue
        raw_name = data[start * 2 : index * 2]
        names.append(raw_name.decode("utf-16le", errors="replace"))
        start = index + 1
    if start != len(code_units):
        raise InvalidWordDocument(f"{label} font name is not null-terminated")
    return tuple(names)


def _parse_ffn(index: int, data: bytes) -> FontDefinition:
    # ffid(1), wWeight(2), chs(1), ixchSzAlt(1), PANOSE(10), FONTSIGNATURE(24)
    if len(data) < 41:
        raise InvalidWordDocument(
            f"SttbfFfn font {index} has {len(data)} bytes; expected at least 41"
        )
    ffid = data[0]
    weight = struct.unpack_from("<h", data, 1)[0]
    charset = data[3]
    alternate_index = data[4]
    panose = data[5:15]
    signature = data[15:39]
    names = _decode_xsz_ffn(data[39:], label=f"SttbfFfn font {index}")
    if not names or not names[0]:
        raise InvalidWordDocument(f"SttbfFfn font {index} has no primary name")

    alternate_name: str | None = None
    if alternate_index:
        # ixchSzAlt is an index in UTF-16 code units from xszFfn. Real-world
        # files normally place the alternate name immediately after the first
        # terminator; prefer the indexed value but tolerate that common layout.
        name_data = data[39:]
        byte_offset = alternate_index * 2
        if byte_offset < len(name_data):
            tail = _decode_xsz_ffn(
                name_data[byte_offset:],
                label=f"SttbfFfn font {index} alternate name",
            )
            alternate_name = tail[0] if tail and tail[0] else None
        elif len(names) > 1:
            alternate_name = names[1] or None
    elif len(names) > 1:
        alternate_name = names[1] or None

    return FontDefinition(
        index=index,
        name=names[0],
        alternate_name=alternate_name,
        charset=charset,
        family=_FONT_FAMILIES.get((ffid >> 4) & 0x07),
        pitch=_FONT_PITCHES.get(ffid & 0x03),
        weight=weight if weight > 0 else None,
        panose=panose,
        signature=signature,
    )


def read_font_table(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
) -> tuple[FontDefinition, ...]:
    """Parse the non-extended STTB used by SttbfFfn."""

    if size == 0:
        return ()
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"SttbfFfn range [{offset}, {offset + size}) exceeds Table stream"
        )
    data = table_stream[offset : offset + size]
    if len(data) < 4:
        raise InvalidWordDocument("SttbfFfn is truncated")
    count, extra_size = struct.unpack_from("<HH", data)
    if count == 0xFFFF:
        raise InvalidWordDocument("extended SttbfFfn layout is not valid for MS-DOC")
    if extra_size:
        raise InvalidWordDocument(
            f"SttbfFfn has unsupported cbExtra value {extra_size}"
        )

    fonts: list[FontDefinition] = []
    position = 4
    for index in range(count):
        if position >= len(data):
            raise InvalidWordDocument(f"SttbfFfn is truncated before font {index}")
        byte_count = data[position]
        position += 1
        end = position + byte_count
        if end > len(data):
            raise InvalidWordDocument(f"SttbfFfn font {index} exceeds the table")
        fonts.append(_parse_ffn(index, data[position:end]))
        position = end
    if position != len(data) and any(data[position:]):
        raise InvalidWordDocument(
            f"SttbfFfn has {len(data) - position} unexpected trailing bytes"
        )
    return tuple(fonts)
