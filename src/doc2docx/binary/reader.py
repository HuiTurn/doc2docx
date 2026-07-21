"""Small, bounded little-endian binary reader."""

from __future__ import annotations

import struct

from ..errors import BinaryBoundsError


class BinaryReader:
    def __init__(
        self,
        data: bytes | bytearray | memoryview,
        *,
        label: str = "binary data",
        base_offset: int = 0,
    ) -> None:
        self._data = memoryview(data).cast("B")
        self._position = 0
        self.label = label
        self.base_offset = base_offset

    def __len__(self) -> int:
        return len(self._data)

    @property
    def position(self) -> int:
        return self._position

    @property
    def remaining(self) -> int:
        return len(self._data) - self._position

    def _check(self, offset: int, size: int) -> None:
        if offset < 0 or size < 0 or offset > len(self._data) - size:
            absolute = self.base_offset + max(offset, 0)
            raise BinaryBoundsError(
                f"{self.label}: read of {size} bytes at offset 0x{absolute:X} "
                f"exceeds {len(self._data)}-byte structure"
            )

    def seek(self, offset: int) -> None:
        self._check(offset, 0)
        self._position = offset

    def skip(self, size: int) -> None:
        self.seek(self._position + size)

    def read(self, size: int) -> bytes:
        self._check(self._position, size)
        start = self._position
        self._position += size
        return self._data[start : start + size].tobytes()

    def read_at(self, offset: int, size: int) -> bytes:
        self._check(offset, size)
        return self._data[offset : offset + size].tobytes()

    def subreader(self, offset: int, size: int, *, label: str | None = None) -> "BinaryReader":
        self._check(offset, size)
        return BinaryReader(
            self._data[offset : offset + size],
            label=label or self.label,
            base_offset=self.base_offset + offset,
        )

    def _unpack(self, fmt: str, size: int) -> int:
        self._check(self._position, size)
        value = struct.unpack_from(fmt, self._data, self._position)[0]
        self._position += size
        return int(value)

    def u8(self) -> int:
        return self._unpack("<B", 1)

    def u16(self) -> int:
        return self._unpack("<H", 2)

    def u32(self) -> int:
        return self._unpack("<I", 4)

    def i32(self) -> int:
        return self._unpack("<i", 4)

    def u64(self) -> int:
        return self._unpack("<Q", 8)

