"""Small deterministic CFB writer used to preserve embedded OLE storages."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from .constants import DIFSECT, ENDOFCHAIN, FATSECT, FREESECT, NOSTREAM
from .directory import DirectoryEntry, ObjectType
from ..errors import InvalidCompoundFile


_SECTOR_SIZE = 512
_MINI_SECTOR_SIZE = 64
_MINI_STREAM_CUTOFF = 4096


@dataclass(slots=True)
class _OutputEntry:
    name: str
    object_type: ObjectType
    clsid: bytes = b"\0" * 16
    state_bits: int = 0
    creation_time: int = 0
    modified_time: int = 0
    data: bytes = b""
    parent: int | None = None
    left: int = NOSTREAM
    right: int = NOSTREAM
    child: int = NOSTREAM
    color: int = 1
    start: int = ENDOFCHAIN


def _name_key(name: str) -> tuple[int, str]:
    return len(name.encode("utf-16le")), name.upper()


def _build_sibling_tree(entries: list[_OutputEntry], child_ids: list[int]) -> int:
    root = NOSTREAM
    parents: dict[int, int] = {}

    def rotate_left(node: int) -> None:
        nonlocal root
        pivot = entries[node].right
        if pivot == NOSTREAM:
            return
        entries[node].right = entries[pivot].left
        if entries[pivot].left != NOSTREAM:
            parents[entries[pivot].left] = node
        parent = parents.get(node, NOSTREAM)
        parents[pivot] = parent
        if parent == NOSTREAM:
            root = pivot
        elif node == entries[parent].left:
            entries[parent].left = pivot
        else:
            entries[parent].right = pivot
        entries[pivot].left = node
        parents[node] = pivot

    def rotate_right(node: int) -> None:
        nonlocal root
        pivot = entries[node].left
        if pivot == NOSTREAM:
            return
        entries[node].left = entries[pivot].right
        if entries[pivot].right != NOSTREAM:
            parents[entries[pivot].right] = node
        parent = parents.get(node, NOSTREAM)
        parents[pivot] = parent
        if parent == NOSTREAM:
            root = pivot
        elif node == entries[parent].right:
            entries[parent].right = pivot
        else:
            entries[parent].left = pivot
        entries[pivot].right = node
        parents[node] = pivot

    for entry_id in sorted(child_ids, key=lambda value: _name_key(entries[value].name)):
        entries[entry_id].left = NOSTREAM
        entries[entry_id].right = NOSTREAM
        entries[entry_id].color = 0
        parent = NOSTREAM
        current = root
        while current != NOSTREAM:
            parent = current
            if _name_key(entries[entry_id].name) < _name_key(entries[current].name):
                current = entries[current].left
            else:
                current = entries[current].right
        parents[entry_id] = parent
        if parent == NOSTREAM:
            root = entry_id
        elif _name_key(entries[entry_id].name) < _name_key(entries[parent].name):
            entries[parent].left = entry_id
        else:
            entries[parent].right = entry_id

        node = entry_id
        while node != root and entries[parents[node]].color == 0:
            parent = parents[node]
            grandparent = parents[parent]
            if parent == entries[grandparent].left:
                uncle = entries[grandparent].right
                if uncle != NOSTREAM and entries[uncle].color == 0:
                    entries[parent].color = 1
                    entries[uncle].color = 1
                    entries[grandparent].color = 0
                    node = grandparent
                else:
                    if node == entries[parent].right:
                        node = parent
                        rotate_left(node)
                        parent = parents[node]
                        grandparent = parents[parent]
                    entries[parent].color = 1
                    entries[grandparent].color = 0
                    rotate_right(grandparent)
            else:
                uncle = entries[grandparent].left
                if uncle != NOSTREAM and entries[uncle].color == 0:
                    entries[parent].color = 1
                    entries[uncle].color = 1
                    entries[grandparent].color = 0
                    node = grandparent
                else:
                    if node == entries[parent].left:
                        node = parent
                        rotate_right(node)
                        parent = parents[node]
                        grandparent = parents[parent]
                    entries[parent].color = 1
                    entries[grandparent].color = 0
                    rotate_left(grandparent)
        entries[root].color = 1
    return root


def _directory_bytes(entries: list[_OutputEntry]) -> bytes:
    output = bytearray(math.ceil(len(entries) / 4) * _SECTOR_SIZE)
    for index, entry in enumerate(entries):
        offset = index * 128
        encoded_name = (entry.name + "\0").encode("utf-16le")
        if len(encoded_name) > 64:
            raise InvalidCompoundFile(f"embedded OLE name {entry.name!r} is too long")
        output[offset : offset + len(encoded_name)] = encoded_name
        struct.pack_into("<H", output, offset + 64, len(encoded_name))
        output[offset + 66] = int(entry.object_type)
        output[offset + 67] = entry.color
        struct.pack_into(
            "<III",
            output,
            offset + 68,
            entry.left,
            entry.right,
            entry.child,
        )
        output[offset + 80 : offset + 96] = entry.clsid
        struct.pack_into("<I", output, offset + 96, entry.state_bits)
        struct.pack_into(
            "<QQ",
            output,
            offset + 100,
            entry.creation_time,
            entry.modified_time,
        )
        struct.pack_into("<I", output, offset + 116, entry.start)
        stream_size = (
            len(entry.data)
            if entry.object_type in (ObjectType.STREAM, ObjectType.ROOT_STORAGE)
            else 0
        )
        struct.pack_into("<Q", output, offset + 120, stream_size)
    return bytes(output)


def write_compound_storage(
    root_source: DirectoryEntry,
    descendants: tuple[tuple[str, DirectoryEntry, bytes | None], ...],
) -> bytes:
    entries = [
        _OutputEntry(
            "Root Entry",
            ObjectType.ROOT_STORAGE,
            root_source.clsid,
            root_source.state_bits,
            root_source.creation_time,
            root_source.modified_time,
        )
    ]
    ids_by_path = {"": 0}
    for path, source, data in sorted(
        descendants,
        key=lambda value: (value[0].count("/"), value[0].casefold()),
    ):
        parent_path, _, name = path.rpartition("/")
        if parent_path not in ids_by_path:
            raise InvalidCompoundFile(
                f"embedded OLE entry {path!r} has no parent storage"
            )
        entry_id = len(entries)
        ids_by_path[path] = entry_id
        entries.append(
            _OutputEntry(
                name,
                source.object_type,
                source.clsid,
                source.state_bits,
                source.creation_time,
                source.modified_time,
                data or b"",
                ids_by_path[parent_path],
            )
        )

    for parent_id, parent in enumerate(entries):
        if parent.object_type not in (ObjectType.STORAGE, ObjectType.ROOT_STORAGE):
            continue
        children = [
            entry_id
            for entry_id, entry in enumerate(entries)
            if entry.parent == parent_id
        ]
        parent.child = _build_sibling_tree(entries, children)

    mini_fat: list[int] = []
    mini_stream = bytearray()
    regular_payloads: list[tuple[int, bytes]] = []
    for entry_id, entry in enumerate(entries[1:], start=1):
        if entry.object_type is not ObjectType.STREAM or not entry.data:
            continue
        if len(entry.data) < _MINI_STREAM_CUTOFF:
            entry.start = len(mini_fat)
            count = math.ceil(len(entry.data) / _MINI_SECTOR_SIZE)
            start = len(mini_fat)
            mini_fat.extend(
                index + 1 if index + 1 < start + count else ENDOFCHAIN
                for index in range(start, start + count)
            )
            mini_stream.extend(entry.data)
            mini_stream.extend(b"\0" * (count * _MINI_SECTOR_SIZE - len(entry.data)))
        else:
            regular_payloads.append((entry_id, entry.data))

    def padded(data: bytes) -> bytes:
        count = max(1, math.ceil(len(data) / _SECTOR_SIZE))
        return data + b"\0" * (count * _SECTOR_SIZE - len(data))

    sector_payloads: list[bytes] = []
    fat: list[int] = []

    def add_chain(data: bytes) -> int:
        first = len(sector_payloads)
        padded_data = padded(data)
        chunks = [
            padded_data[offset : offset + _SECTOR_SIZE]
            for offset in range(0, len(padded_data), _SECTOR_SIZE)
        ]
        for index, chunk in enumerate(chunks):
            sector_payloads.append(chunk)
            fat.append(first + index + 1 if index + 1 < len(chunks) else ENDOFCHAIN)
        return first

    for entry_id, data in regular_payloads:
        entries[entry_id].start = add_chain(data)
    if mini_stream:
        entries[0].data = bytes(mini_stream)
        entries[0].start = add_chain(bytes(mini_stream))
    mini_fat_start = ENDOFCHAIN
    mini_fat_sector_count = 0
    if mini_fat:
        mini_fat_sector_count = math.ceil(
            len(mini_fat) * 4 / _SECTOR_SIZE
        )
        mini_fat.extend(
            [FREESECT]
            * (mini_fat_sector_count * (_SECTOR_SIZE // 4) - len(mini_fat))
        )
        mini_fat_bytes = struct.pack(
            f"<{len(mini_fat)}I",
            *mini_fat,
        )
        mini_fat_start = add_chain(mini_fat_bytes)

    directory_data = _directory_bytes(entries)
    directory_start = add_chain(directory_data)

    fat_sector_count = 0
    difat_sector_count = 0
    while True:
        total = (
            len(sector_payloads) + fat_sector_count + difat_sector_count
        )
        needed_fat = math.ceil(total / (_SECTOR_SIZE // 4))
        needed_difat = math.ceil(max(needed_fat - 109, 0) / 127)
        if (
            needed_fat == fat_sector_count
            and needed_difat == difat_sector_count
        ):
            break
        fat_sector_count = needed_fat
        difat_sector_count = needed_difat
    difat_sector_ids = list(
        range(
            len(sector_payloads),
            len(sector_payloads) + difat_sector_count,
        )
    )
    fat_sector_ids = list(
        range(
            len(sector_payloads) + difat_sector_count,
            len(sector_payloads) + difat_sector_count + fat_sector_count,
        )
    )
    fat.extend([DIFSECT] * difat_sector_count)
    fat.extend([FATSECT] * fat_sector_count)
    fat.extend([FREESECT] * (fat_sector_count * 128 - len(fat)))

    remaining_fat_sector_ids = fat_sector_ids[109:]
    for index, sector_id in enumerate(difat_sector_ids):
        start = index * 127
        values = remaining_fat_sector_ids[start : start + 127]
        values.extend([FREESECT] * (127 - len(values)))
        next_sector = (
            difat_sector_ids[index + 1]
            if index + 1 < len(difat_sector_ids)
            else ENDOFCHAIN
        )
        sector_payloads.append(struct.pack("<128I", *values, next_sector))
    for index in range(fat_sector_count):
        sector_payloads.append(
            struct.pack("<128I", *fat[index * 128 : (index + 1) * 128])
        )

    header = bytearray(_SECTOR_SIZE)
    header[:8] = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
    struct.pack_into("<HHHHH", header, 24, 0x003E, 3, 0xFFFE, 9, 6)
    struct.pack_into(
        "<IIIIIIIII",
        header,
        40,
        0,
        fat_sector_count,
        directory_start,
        0,
        _MINI_STREAM_CUTOFF,
        mini_fat_start,
        mini_fat_sector_count,
        difat_sector_ids[0] if difat_sector_ids else ENDOFCHAIN,
        difat_sector_count,
    )
    difat = fat_sector_ids[:109] + [FREESECT] * (109 - len(fat_sector_ids[:109]))
    struct.pack_into("<109I", header, 76, *difat)
    return bytes(header) + b"".join(sector_payloads)
