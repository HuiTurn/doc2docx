"""Shared strict PLC readers for MS-DOC footnotes and endnotes."""

from __future__ import annotations

import struct

from ..errors import InvalidWordDocument


def _checked_range(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    label: str,
) -> memoryview:
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"{label} range [{offset}, {offset + size}) exceeds Table stream"
        )
    return memoryview(table_stream)[offset : offset + size]


def read_note_references(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    ccp_text: int,
    label: str,
) -> tuple[tuple[int, int], ...]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        label=label,
    )
    if size < 10 or (size - 4) % 6:
        raise InvalidWordDocument(
            f"{label} size {size} does not describe a whole reference PLC"
        )
    reference_count = (size - 4) // 6
    cp_count = reference_count + 1
    cps = struct.unpack_from(f"<{cp_count}I", data)
    reference_cps = cps[:-1]  # The final CP is undefined by MS-DOC.
    if any(cp >= ccp_text for cp in reference_cps):
        raise InvalidWordDocument(
            f"{label} contains a CP outside the main document"
        )
    if any(
        current <= previous
        for previous, current in zip(reference_cps, reference_cps[1:])
    ):
        raise InvalidWordDocument(
            f"{label} reference CPs are not strictly increasing"
        )
    indexes = struct.unpack_from(f"<{reference_count}H", data, cp_count * 4)
    return tuple(zip(reference_cps, indexes, strict=True))


def read_note_text_ranges(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    story_length: int,
    story_length_name: str,
    label: str,
    story_kind: str,
) -> tuple[tuple[int, int], ...]:
    data = _checked_range(
        table_stream,
        offset=offset,
        size=size,
        label=label,
    )
    if size < 12 or size % 4:
        raise InvalidWordDocument(
            f"{label} size {size} does not describe a whole CP-only PLC"
        )
    cps = struct.unpack_from(f"<{size // 4}I", data)
    story_cps = cps[:-1]  # The final CP is undefined by MS-DOC.
    if any(cp >= story_length for cp in story_cps):
        raise InvalidWordDocument(
            f"{label} contains a CP outside the {story_kind} document"
        )
    if any(
        current <= previous
        for previous, current in zip(story_cps, story_cps[1:])
    ):
        raise InvalidWordDocument(f"{label} CPs are not strictly increasing")
    if story_cps[-1] != story_length - 1:
        raise InvalidWordDocument(
            f"{label} second-to-last CP does not equal {story_length_name} minus one"
        )
    return tuple(zip(story_cps, story_cps[1:]))
