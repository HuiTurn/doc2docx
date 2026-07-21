"""CFB directory entry structures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct

from .constants import NOSTREAM
from ..errors import InvalidCompoundFile


class ObjectType(IntEnum):
    UNALLOCATED = 0
    STORAGE = 1
    STREAM = 2
    ROOT_STORAGE = 5


@dataclass(slots=True, frozen=True)
class DirectoryEntry:
    entry_id: int
    name: str
    object_type: ObjectType
    color_flag: int
    left_sibling_id: int
    right_sibling_id: int
    child_id: int
    clsid: bytes
    state_bits: int
    creation_time: int
    modified_time: int
    starting_sector: int
    stream_size: int
    path: str = ""
    name_was_repaired: bool = False

    @classmethod
    def parse(
        cls, data: bytes | memoryview, entry_id: int, *, major_version: int
    ) -> "DirectoryEntry":
        view = memoryview(data)
        if len(view) != 128:
            raise InvalidCompoundFile("CFB directory entries must be 128 bytes")

        name_length = struct.unpack_from("<H", view, 64)[0]
        raw_type = view[66]
        try:
            object_type = ObjectType(raw_type)
        except ValueError as exc:
            raise InvalidCompoundFile(
                f"directory entry {entry_id} has invalid object type {raw_type}"
            ) from exc

        name_was_repaired = False
        if object_type is ObjectType.UNALLOCATED:
            name = ""
        else:
            valid_length = 2 <= name_length <= 64 and name_length % 2 == 0
            is_terminated = valid_length and (
                view[name_length - 2 : name_length].tobytes() == b"\x00\x00"
            )
            if not valid_length or not is_terminated:
                # Some Word-produced temporary documents contain a malformed root
                # storage name/length. The root name is not used to resolve child
                # streams, so normalizing only this entry is safe and improves real
                # world compatibility without weakening child-stream validation.
                if entry_id == 0 and object_type is ObjectType.ROOT_STORAGE:
                    name = "Root Entry"
                    name_was_repaired = True
                elif not valid_length:
                    raise InvalidCompoundFile(
                        f"directory entry {entry_id} has invalid UTF-16 name length "
                        f"{name_length}"
                    )
                else:
                    raise InvalidCompoundFile(
                        f"directory entry {entry_id} name is not null terminated"
                    )
            else:
                raw_name = view[: name_length - 2].tobytes()
                try:
                    name = raw_name.decode("utf-16le")
                except UnicodeDecodeError as exc:
                    if entry_id == 0 and object_type is ObjectType.ROOT_STORAGE:
                        name = "Root Entry"
                        name_was_repaired = True
                    else:
                        raise InvalidCompoundFile(
                            f"directory entry {entry_id} has an invalid UTF-16 name"
                        ) from exc
                if (
                    entry_id == 0
                    and object_type is ObjectType.ROOT_STORAGE
                    and name != "Root Entry"
                ):
                    name = "Root Entry"
                    name_was_repaired = True

        left, right, child = struct.unpack_from("<III", view, 68)
        state_bits = struct.unpack_from("<I", view, 96)[0]
        creation_time, modified_time = struct.unpack_from("<QQ", view, 100)
        starting_sector = struct.unpack_from("<I", view, 116)[0]
        stream_size = struct.unpack_from("<Q", view, 120)[0]
        if major_version == 3:
            stream_size &= 0xFFFFFFFF

        return cls(
            entry_id=entry_id,
            name=name,
            object_type=object_type,
            color_flag=int(view[67]),
            left_sibling_id=left,
            right_sibling_id=right,
            child_id=child,
            clsid=view[80:96].tobytes(),
            state_bits=state_bits,
            creation_time=creation_time,
            modified_time=modified_time,
            starting_sector=starting_sector,
            stream_size=stream_size,
            name_was_repaired=name_was_repaired,
        )

    @property
    def has_left(self) -> bool:
        return self.left_sibling_id != NOSTREAM

    @property
    def has_right(self) -> bool:
        return self.right_sibling_id != NOSTREAM

    @property
    def has_child(self) -> bool:
        return self.child_id != NOSTREAM
