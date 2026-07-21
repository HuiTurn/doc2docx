"""Strict MS-DOC Plcfld/Fld structure validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import CharacterProperties, FieldEndProperties
from .pieces import PieceTable


_KNOWN_FIELD_TYPES = frozenset(
    {
        0x01,
        0x02,
        0x03,
        0x05,
        0x06,
        0x07,
        0x08,
        0x0A,
        0x0C,
        0x0D,
        0x0E,
        *range(0x0F, 0x4A),
        0x4B,
        0x4F,
        0x50,
        0x51,
        0x53,
        0x54,
        0x55,
        *range(0x57, 0x60),
    }
)


@dataclass(slots=True, frozen=True)
class _OpenField:
    field_type_code: int
    has_separator: bool = False


@dataclass(slots=True, frozen=True)
class FieldTable:
    """Validated field endings keyed by absolute Piece Table CP."""

    ends_by_cp: Mapping[int, FieldEndProperties]
    field_count: int = 0
    character_count: int = 0

    def end_properties_at(self, cp: int) -> FieldEndProperties | None:
        return self.ends_by_cp.get(cp)


def read_field_table(
    table_stream: bytes,
    piece_table: PieceTable,
    *,
    offset: int,
    size: int,
    story_length: int,
    story_cp_start: int,
    structure: str,
    story_name: str,
    report: ConversionReport,
    character_properties_at: (
        Callable[[int], CharacterProperties] | None
    ) = None,
) -> FieldTable:
    """Read one Plcfld and validate its FieldList nesting and story characters."""

    if size == 0:
        return FieldTable({})
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"{structure} range [{offset}, {offset + size}) exceeds Table stream"
        )
    if size < 4 or (size - 4) % 6:
        raise InvalidWordDocument(
            f"{structure} size {size} does not describe 2-byte Fld elements"
        )
    count = (size - 4) // 6
    raw = memoryview(table_stream)[offset : offset + size]
    cps = struct.unpack_from(f"<{count + 1}I", raw)
    field_cps = cps[:-1]
    if story_length == 0:
        if count == 0 and cps[-1] == 0:
            return FieldTable({})
        raise InvalidWordDocument(f"{structure} contains fields for an empty story")
    if any(
        current <= previous
        for previous, current in zip(field_cps, field_cps[1:])
    ):
        raise InvalidWordDocument(f"{structure} field CPs are not increasing")
    if any(cp >= story_length for cp in field_cps):
        raise InvalidWordDocument(f"{structure} contains a CP outside its story")
    if cps[-1] > story_length or (field_cps and cps[-1] <= field_cps[-1]):
        raise InvalidWordDocument(f"{structure} final CP is not the largest story CP")

    data_offset = 4 * (count + 1)
    stack: list[_OpenField] = []
    ends_by_cp: dict[int, FieldEndProperties] = {}
    field_count = 0
    unknown_types: set[int] = set()
    missing_special_count = 0
    inverted_display_count = 0
    private_result_count = 0
    zombie_embed_count = 0
    inconsistent_nested_count = 0

    for index, relative_cp in enumerate(field_cps):
        first, flags = struct.unpack_from("BB", raw, data_offset + index * 2)
        field_character = first & 0x1F
        if field_character not in (0x13, 0x14, 0x15):
            raise InvalidWordDocument(
                f"{structure} entry {index} has invalid field character "
                f"0x{field_character:02X}"
            )
        absolute_cp = story_cp_start + relative_cp
        units = piece_table.extract_characters(
            absolute_cp,
            absolute_cp + 1,
            report,
            story=story_name,
        )
        if len(units) != 1 or ord(units[0].text) != field_character:
            raise InvalidWordDocument(
                f"{structure} entry {index} does not match its story character"
            )
        if (
            character_properties_at is not None
            and character_properties_at(absolute_cp).special is not True
        ):
            missing_special_count += 1

        if field_character == 0x13:
            if flags not in _KNOWN_FIELD_TYPES:
                unknown_types.add(flags)
            stack.append(_OpenField(flags))
            field_count += 1
            continue
        if field_character == 0x14:
            if not stack or stack[-1].has_separator:
                raise InvalidWordDocument(
                    f"{structure} contains an invalid field-separator sequence"
                )
            stack[-1] = _OpenField(stack[-1].field_type_code, True)
            continue
        if not stack:
            raise InvalidWordDocument(
                f"{structure} contains an unmatched field-end character"
            )
        opened = stack.pop()
        nested = bool(flags & 0x40)
        has_separator = bool(flags & 0x80)
        # XE/TC/RD/TA/PRIVATE field characters are intentionally omitted from
        # Plcfld, so fNested can legitimately describe an outer field that is
        # absent from this PLC. Keep the source flag and diagnose the mismatch.
        inconsistent_nested_count += nested != bool(stack)
        if has_separator != opened.has_separator:
            raise InvalidWordDocument(
                f"{structure} field end {index} has inconsistent fHasSep"
            )
        inverted_display_count += bool(flags & 0x01)
        zombie_embed_count += bool(flags & 0x02)
        private_result_count += bool(flags & 0x20)
        ends_by_cp[absolute_cp] = FieldEndProperties(
            field_type_code=opened.field_type_code,
            result_dirty=bool(flags & 0x04),
            result_edited=bool(flags & 0x08),
            locked=bool(flags & 0x10),
            private_result=bool(flags & 0x20),
            nested=nested,
            has_separator=has_separator,
        )
    if stack:
        raise InvalidWordDocument(f"{structure} contains an unterminated field")

    location = SourceLocation(story=story_name, stream="Table")
    if unknown_types:
        report.warning(
            "UNKNOWN_FIELD_TYPES",
            "some Plcfld begin records use field types outside the published enumeration",
            location=location,
            field_types=[f"0x{value:02X}" for value in sorted(unknown_types)],
        )
    if missing_special_count:
        report.warning(
            "FIELD_CHARACTER_SPECIAL_MISSING",
            "some declared field characters do not have sprmCFSpec enabled",
            location=location,
            character_count=missing_special_count,
        )
    if inverted_display_count or zombie_embed_count or private_result_count:
        report.warning(
            "FIELD_END_FLAGS_APPROXIMATED",
            "some legacy field display or embedded-result flags have no direct output equivalent",
            location=location,
            inverted_display_count=inverted_display_count,
            zombie_embed_count=zombie_embed_count,
            private_result_count=private_result_count,
        )
    if inconsistent_nested_count:
        report.warning(
            "FIELD_NESTING_FLAG_INCONSISTENT",
            "some fNested flags refer to fields omitted from this Plcfld",
            location=location,
            field_count=inconsistent_nested_count,
        )
    return FieldTable(
        ends_by_cp,
        field_count=field_count,
        character_count=count,
    )
