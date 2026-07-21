"""CFB header parsing and validation."""

from __future__ import annotations

from dataclasses import dataclass
import struct

from .constants import CFB_SIGNATURE, ENDOFCHAIN, FREESECT
from ..errors import InvalidCompoundFile


@dataclass(slots=True, frozen=True)
class CompoundFileHeader:
    minor_version: int
    major_version: int
    sector_size: int
    mini_sector_size: int
    number_of_directory_sectors: int
    number_of_fat_sectors: int
    first_directory_sector: int
    transaction_signature: int
    mini_stream_cutoff: int
    first_mini_fat_sector: int
    number_of_mini_fat_sectors: int
    first_difat_sector: int
    number_of_difat_sectors: int
    difat: tuple[int, ...]

    @classmethod
    def parse(cls, data: bytes | memoryview) -> "CompoundFileHeader":
        view = memoryview(data)
        if len(view) < 512:
            raise InvalidCompoundFile("CFB file is shorter than its 512-byte header")
        if view[:8].tobytes() != CFB_SIGNATURE:
            raise InvalidCompoundFile(
                "input does not have the CFB/OLE compound-file signature"
            )
        if any(view[8:24]):
            raise InvalidCompoundFile("CFB header CLSID must be zero")

        minor, major, byte_order, sector_shift, mini_shift = struct.unpack_from(
            "<HHHHH", view, 24
        )
        if byte_order != 0xFFFE:
            raise InvalidCompoundFile(
                f"unsupported CFB byte order 0x{byte_order:04X}"
            )
        if major not in (3, 4):
            raise InvalidCompoundFile(f"unsupported CFB major version {major}")
        expected_shift = 9 if major == 3 else 12
        if sector_shift != expected_shift:
            raise InvalidCompoundFile(
                f"CFB version {major} requires sector shift {expected_shift}, "
                f"got {sector_shift}"
            )
        if mini_shift != 6:
            raise InvalidCompoundFile(
                f"CFB mini-sector shift must be 6, got {mini_shift}"
            )
        if any(view[34:40]):
            raise InvalidCompoundFile("reserved CFB header bytes must be zero")

        fields = struct.unpack_from("<IIIIIIIII", view, 40)
        (
            number_of_directory_sectors,
            number_of_fat_sectors,
            first_directory_sector,
            transaction_signature,
            mini_stream_cutoff,
            first_mini_fat_sector,
            number_of_mini_fat_sectors,
            first_difat_sector,
            number_of_difat_sectors,
        ) = fields
        if major == 3 and number_of_directory_sectors != 0:
            raise InvalidCompoundFile(
                "CFB version 3 must declare zero directory sectors"
            )
        if mini_stream_cutoff != 0x1000:
            raise InvalidCompoundFile(
                f"CFB mini-stream cutoff must be 4096, got {mini_stream_cutoff}"
            )
        difat = struct.unpack_from("<109I", view, 76)

        if number_of_difat_sectors == 0 and first_difat_sector not in (
            ENDOFCHAIN,
            FREESECT,
        ):
            raise InvalidCompoundFile(
                "CFB header has no DIFAT sectors but a non-free first DIFAT sector"
            )

        return cls(
            minor,
            major,
            1 << sector_shift,
            1 << mini_shift,
            number_of_directory_sectors,
            number_of_fat_sectors,
            first_directory_sector,
            transaction_signature,
            mini_stream_cutoff,
            first_mini_fat_sector,
            number_of_mini_fat_sectors,
            first_difat_sector,
            number_of_difat_sectors,
            tuple(difat),
        )
