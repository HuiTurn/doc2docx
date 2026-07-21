"""Safe, read-only CFB/OLE compound-file reader."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import struct

from .constants import (
    DIFSECT,
    ENDOFCHAIN,
    FATSECT,
    FREESECT,
    MAXREGSECT,
    NOSTREAM,
)
from .directory import DirectoryEntry, ObjectType
from .header import CompoundFileHeader
from ..errors import InvalidCompoundFile, StreamNotFound


@dataclass(slots=True, frozen=True)
class CompoundFileLimits:
    max_input_bytes: int = 512 * 1024 * 1024
    max_stream_bytes: int = 256 * 1024 * 1024
    max_directory_entries: int = 1_000_000


class CompoundFile:
    def __init__(
        self,
        data: bytes | bytearray | memoryview,
        *,
        limits: CompoundFileLimits | None = None,
    ) -> None:
        self.limits = limits or CompoundFileLimits()
        if len(data) > self.limits.max_input_bytes:
            raise InvalidCompoundFile(
                f"input is {len(data)} bytes, exceeding the configured "
                f"{self.limits.max_input_bytes}-byte limit"
            )
        self._data = memoryview(data).cast("B")
        self.header = CompoundFileHeader.parse(self._data)
        if len(self._data) < self.header.sector_size:
            raise InvalidCompoundFile("CFB file is shorter than one header sector")
        payload_size = len(self._data) - self.header.sector_size
        if payload_size % self.header.sector_size:
            raise InvalidCompoundFile(
                "CFB file length is not aligned to its declared sector size"
            )
        self._sector_count = payload_size // self.header.sector_size
        if self._sector_count == 0:
            raise InvalidCompoundFile("CFB file contains no sectors")
        if self.header.number_of_fat_sectors > self._sector_count:
            raise InvalidCompoundFile("declared FAT sector count exceeds file size")
        if self.header.number_of_difat_sectors > self._sector_count:
            raise InvalidCompoundFile("declared DIFAT sector count exceeds file size")

        self._fat_sector_ids = self._load_difat()
        self._fat = self._load_fat()
        self._directory_entries = self._load_directory()
        self._entries_by_path = self._index_directory_tree()
        self._mini_fat = self._load_mini_fat()
        self._mini_stream: bytes | None = None

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        limits: CompoundFileLimits | None = None,
    ) -> "CompoundFile":
        file_path = Path(path)
        actual_limits = limits or CompoundFileLimits()
        size = file_path.stat().st_size
        if size > actual_limits.max_input_bytes:
            raise InvalidCompoundFile(
                f"input is {size} bytes, exceeding the configured "
                f"{actual_limits.max_input_bytes}-byte limit"
            )
        return cls(file_path.read_bytes(), limits=actual_limits)

    @property
    def sector_count(self) -> int:
        return self._sector_count

    @property
    def entries(self) -> tuple[DirectoryEntry, ...]:
        return tuple(self._entries_by_path.values())

    def _sector(self, sector_id: int) -> memoryview:
        if sector_id > MAXREGSECT or sector_id >= self._sector_count:
            raise InvalidCompoundFile(f"sector {sector_id} is outside the CFB file")
        start = (sector_id + 1) * self.header.sector_size
        return self._data[start : start + self.header.sector_size]

    def _load_difat(self) -> list[int]:
        fat_sector_ids = [sid for sid in self.header.difat if sid != FREESECT]
        next_sector = self.header.first_difat_sector
        seen: set[int] = set()
        entries_per_sector = self.header.sector_size // 4 - 1

        for _ in range(self.header.number_of_difat_sectors):
            if next_sector in seen:
                raise InvalidCompoundFile("cycle detected in DIFAT sector chain")
            seen.add(next_sector)
            sector = self._sector(next_sector)
            values = struct.unpack_from(
                f"<{entries_per_sector + 1}I", sector, 0
            )
            fat_sector_ids.extend(
                sid for sid in values[:entries_per_sector] if sid != FREESECT
            )
            next_sector = values[-1]

        if self.header.number_of_difat_sectors and next_sector != ENDOFCHAIN:
            raise InvalidCompoundFile("DIFAT chain does not end with ENDOFCHAIN")
        if len(fat_sector_ids) < self.header.number_of_fat_sectors:
            raise InvalidCompoundFile(
                "DIFAT does not contain the declared number of FAT sectors"
            )
        fat_sector_ids = fat_sector_ids[: self.header.number_of_fat_sectors]
        if len(set(fat_sector_ids)) != len(fat_sector_ids):
            raise InvalidCompoundFile("DIFAT contains duplicate FAT sector IDs")
        for sector_id in fat_sector_ids:
            self._sector(sector_id)
        return fat_sector_ids

    def _load_fat(self) -> tuple[int, ...]:
        values: list[int] = []
        entries_per_sector = self.header.sector_size // 4
        for sector_id in self._fat_sector_ids:
            sector = self._sector(sector_id)
            values.extend(struct.unpack_from(f"<{entries_per_sector}I", sector, 0))
        if len(values) < self._sector_count:
            raise InvalidCompoundFile("FAT does not cover every sector in the file")
        for sector_id in self._fat_sector_ids:
            if values[sector_id] != FATSECT:
                raise InvalidCompoundFile(
                    f"FAT sector {sector_id} is not marked FATSECT in the FAT"
                )
        return tuple(values)

    def _chain(
        self,
        start_sector: int,
        allocation_table: tuple[int, ...],
        *,
        label: str,
        expected_sectors: int | None = None,
    ) -> list[int]:
        if start_sector == ENDOFCHAIN:
            if expected_sectors in (None, 0):
                return []
            raise InvalidCompoundFile(f"{label} is empty but data was expected")
        if start_sector in (FREESECT, FATSECT, DIFSECT) or start_sector > MAXREGSECT:
            raise InvalidCompoundFile(
                f"{label} starts at invalid sector marker 0x{start_sector:08X}"
            )

        result: list[int] = []
        seen: set[int] = set()
        current = start_sector
        hard_limit = len(allocation_table) + 1
        while current != ENDOFCHAIN:
            if current in seen:
                raise InvalidCompoundFile(f"cycle detected in {label} sector chain")
            if current >= len(allocation_table) or current > MAXREGSECT:
                raise InvalidCompoundFile(
                    f"{label} references sector {current} outside its allocation table"
                )
            seen.add(current)
            result.append(current)
            if len(result) > hard_limit:
                raise InvalidCompoundFile(f"{label} sector chain is unbounded")
            current = allocation_table[current]
            if current in (FREESECT, FATSECT, DIFSECT):
                raise InvalidCompoundFile(
                    f"{label} chain terminates with invalid marker 0x{current:08X}"
                )

        if expected_sectors is not None and len(result) < expected_sectors:
            raise InvalidCompoundFile(
                f"{label} has {len(result)} sectors but needs {expected_sectors}"
            )
        return result

    def _read_regular_stream(
        self, start_sector: int, size: int, *, label: str
    ) -> bytes:
        if size < 0 or size > self.limits.max_stream_bytes:
            raise InvalidCompoundFile(
                f"{label} size {size} exceeds the configured stream limit"
            )
        if size == 0:
            return b""
        required = (size + self.header.sector_size - 1) // self.header.sector_size
        chain = self._chain(
            start_sector,
            self._fat,
            label=label,
            expected_sectors=required,
        )
        return b"".join(self._sector(sid) for sid in chain[:required])[:size]

    def _load_directory(self) -> list[DirectoryEntry]:
        expected = (
            self.header.number_of_directory_sectors
            if self.header.major_version == 4
            else None
        )
        chain = self._chain(
            self.header.first_directory_sector,
            self._fat,
            label="directory",
            expected_sectors=expected,
        )
        if expected is not None:
            chain = chain[:expected]
        raw = b"".join(self._sector(sid) for sid in chain)
        count = len(raw) // 128
        if count > self.limits.max_directory_entries:
            raise InvalidCompoundFile(
                f"directory contains {count} entries, exceeding configured limit"
            )
        entries = [
            DirectoryEntry.parse(
                raw[index * 128 : (index + 1) * 128],
                index,
                major_version=self.header.major_version,
            )
            for index in range(count)
        ]
        if not entries or entries[0].object_type is not ObjectType.ROOT_STORAGE:
            raise InvalidCompoundFile("directory entry 0 is not the root storage")
        return entries

    def _index_directory_tree(self) -> dict[str, DirectoryEntry]:
        entries = self._directory_entries
        indexed: dict[str, DirectoryEntry] = {}
        visited: set[int] = set()

        def validate_id(entry_id: int, relation: str) -> None:
            if entry_id == NOSTREAM:
                return
            if entry_id >= len(entries):
                raise InvalidCompoundFile(
                    f"directory {relation} ID {entry_id} is out of range"
                )

        def walk_sibling_tree(entry_id: int, parent: str, depth: int = 0) -> None:
            if entry_id == NOSTREAM:
                return
            if depth > 128:
                raise InvalidCompoundFile("directory tree exceeds safe nesting depth")
            validate_id(entry_id, "entry")
            if entry_id in visited:
                raise InvalidCompoundFile("cycle or duplicate detected in directory tree")
            visited.add(entry_id)
            entry = entries[entry_id]
            if entry.object_type is ObjectType.UNALLOCATED:
                raise InvalidCompoundFile(
                    "directory tree references an unallocated entry"
                )
            validate_id(entry.left_sibling_id, "left sibling")
            validate_id(entry.right_sibling_id, "right sibling")
            validate_id(entry.child_id, "child")

            walk_sibling_tree(entry.left_sibling_id, parent, depth + 1)
            path = f"{parent}/{entry.name}" if parent else entry.name
            if path in indexed:
                raise InvalidCompoundFile(f"duplicate directory path {path!r}")
            indexed[path] = replace(entry, path=path)
            if entry.object_type is ObjectType.STORAGE:
                walk_sibling_tree(entry.child_id, path, depth + 1)
            elif entry.child_id != NOSTREAM:
                raise InvalidCompoundFile(
                    f"non-storage directory entry {path!r} has a child"
                )
            walk_sibling_tree(entry.right_sibling_id, parent, depth + 1)

        root = entries[0]
        validate_id(root.child_id, "root child")
        indexed[""] = replace(root, path="")
        visited.add(0)
        walk_sibling_tree(root.child_id, "")
        return indexed

    def _load_mini_fat(self) -> tuple[int, ...]:
        count = self.header.number_of_mini_fat_sectors
        if count == 0:
            return ()
        chain = self._chain(
            self.header.first_mini_fat_sector,
            self._fat,
            label="mini FAT",
            expected_sectors=count,
        )[:count]
        entries_per_sector = self.header.sector_size // 4
        values: list[int] = []
        for sector_id in chain:
            values.extend(
                struct.unpack_from(
                    f"<{entries_per_sector}I", self._sector(sector_id), 0
                )
            )
        return tuple(values)

    def _root_mini_stream(self) -> bytes:
        if self._mini_stream is None:
            root = self._directory_entries[0]
            self._mini_stream = self._read_regular_stream(
                root.starting_sector,
                root.stream_size,
                label="root mini stream",
            )
        return self._mini_stream

    def _read_mini_stream(
        self, start_sector: int, size: int, *, label: str
    ) -> bytes:
        if not self._mini_fat:
            raise InvalidCompoundFile(f"{label} requires a mini FAT, but none exists")
        if size > self.limits.max_stream_bytes:
            raise InvalidCompoundFile(
                f"{label} size {size} exceeds the configured stream limit"
            )
        required = (size + self.header.mini_sector_size - 1) // self.header.mini_sector_size
        chain = self._chain(
            start_sector,
            self._mini_fat,
            label=f"{label} mini",
            expected_sectors=required,
        )[:required]
        mini_stream = self._root_mini_stream()
        chunks: list[bytes] = []
        for mini_sector in chain:
            start = mini_sector * self.header.mini_sector_size
            end = start + self.header.mini_sector_size
            if end > len(mini_stream):
                raise InvalidCompoundFile(
                    f"{label} mini sector {mini_sector} exceeds the root mini stream"
                )
            chunks.append(mini_stream[start:end])
        return b"".join(chunks)[:size]

    def get_entry(self, path: str) -> DirectoryEntry:
        normalized = path.strip("/")
        try:
            return self._entries_by_path[normalized]
        except KeyError as exc:
            raise StreamNotFound(f"compound-file entry {path!r} was not found") from exc

    def open_stream(self, path: str) -> bytes:
        entry = self.get_entry(path)
        if entry.object_type is not ObjectType.STREAM:
            raise StreamNotFound(f"compound-file entry {path!r} is not a stream")
        if entry.stream_size == 0:
            return b""
        if entry.stream_size < self.header.mini_stream_cutoff:
            return self._read_mini_stream(
                entry.starting_sector,
                entry.stream_size,
                label=f"stream {entry.path!r}",
            )
        return self._read_regular_stream(
            entry.starting_sector,
            entry.stream_size,
            label=f"stream {entry.path!r}",
        )
