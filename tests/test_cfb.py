import struct
import unittest

from doc2docx.cfb import CompoundFile, DirectoryEntry, ObjectType
from doc2docx.cfb.constants import ENDOFCHAIN, FREESECT, NOSTREAM
from doc2docx.cfb.writer import write_compound_storage
from doc2docx.errors import InvalidCompoundFile, StreamNotFound

from .fixtures import build_mini_stream_cfb, build_version4_cfb, build_word_cfb


class CompoundFileTests(unittest.TestCase):
    @staticmethod
    def _entry(name: str, object_type: ObjectType, entry_id: int) -> DirectoryEntry:
        return DirectoryEntry(
            entry_id,
            name,
            object_type,
            1,
            NOSTREAM,
            NOSTREAM,
            NOSTREAM,
            bytes((entry_id,)) + b"\0" * 15,
            0,
            0,
            0,
            ENDOFCHAIN,
            0,
        )

    def test_exports_nested_storage_as_standalone_compound_file(self) -> None:
        root = self._entry("Root Entry", ObjectType.ROOT_STORAGE, 0)
        source = write_compound_storage(
            root,
            (
                ("ObjectPool", self._entry("ObjectPool", ObjectType.STORAGE, 1), None),
                ("ObjectPool/_123", self._entry("_123", ObjectType.STORAGE, 2), None),
                (
                    "ObjectPool/_123/\x03ObjInfo",
                    self._entry("\x03ObjInfo", ObjectType.STREAM, 3),
                    b"object-info",
                ),
                (
                    "ObjectPool/_123/Contents",
                    self._entry("Contents", ObjectType.STREAM, 4),
                    b"A" * 5000,
                ),
                (
                    "ObjectPool/_123/Nested",
                    self._entry("Nested", ObjectType.STORAGE, 5),
                    None,
                ),
                (
                    "ObjectPool/_123/Nested/Small",
                    self._entry("Small", ObjectType.STREAM, 6),
                    b"nested-data",
                ),
            ),
        )

        compound = CompoundFile(source)
        exported = CompoundFile(compound.export_storage("ObjectPool/_123"))

        self.assertEqual(exported.get_entry("").clsid[0], 2)
        self.assertEqual(exported.open_stream("\x03ObjInfo"), b"object-info")
        self.assertEqual(exported.open_stream("Contents"), b"A" * 5000)
        self.assertEqual(exported.open_stream("Nested/Small"), b"nested-data")

    def test_writer_uses_difat_for_large_embedded_storage(self) -> None:
        payload = b"large OLE payload" * 512 * 1024
        source = write_compound_storage(
            self._entry("Root Entry", ObjectType.ROOT_STORAGE, 0),
            (
                (
                    "Contents",
                    self._entry("Contents", ObjectType.STREAM, 1),
                    payload,
                ),
            ),
        )

        compound = CompoundFile(source)

        self.assertGreater(compound.header.number_of_difat_sectors, 0)
        self.assertEqual(compound.open_stream("Contents"), payload)

    def test_accepts_complete_free_terminated_difat_chain(self) -> None:
        payload = b"legacy DIFAT payload" * 512 * 1024
        source = bytearray(
            write_compound_storage(
                self._entry("Root Entry", ObjectType.ROOT_STORAGE, 0),
                (("Contents", self._entry("Contents", ObjectType.STREAM, 1), payload),),
            )
        )
        first_difat_sector = struct.unpack_from("<I", source, 68)[0]
        final_link_offset = (first_difat_sector + 1) * 512 + 508
        struct.pack_into("<I", source, final_link_offset, FREESECT)

        compound = CompoundFile(source)

        self.assertGreater(compound.header.number_of_difat_sectors, 0)
        self.assertEqual(compound.open_stream("Contents"), payload)

    def test_rejects_incomplete_free_terminated_difat_chain(self) -> None:
        payload = b"truncated DIFAT payload" * 512 * 1024
        source = bytearray(
            write_compound_storage(
                self._entry("Root Entry", ObjectType.ROOT_STORAGE, 0),
                (("Contents", self._entry("Contents", ObjectType.STREAM, 1), payload),),
            )
        )
        first_difat_sector = struct.unpack_from("<I", source, 68)[0]
        final_link_offset = (first_difat_sector + 1) * 512 + 508
        struct.pack_into("<I", source, final_link_offset, FREESECT)
        declared_fat_sectors = struct.unpack_from("<I", source, 44)[0]
        struct.pack_into("<I", source, 44, declared_fat_sectors + 1)

        with self.assertRaisesRegex(InvalidCompoundFile, "DIFAT chain"):
            CompoundFile(source)

    def test_reads_regular_streams_and_directory_tree(self) -> None:
        compound = CompoundFile(build_word_cfb())
        self.assertEqual(len(compound.open_stream("WordDocument")), 4096)
        self.assertEqual(len(compound.open_stream("1Table")), 4096)
        self.assertGreaterEqual(
            {entry.path for entry in compound.entries},
            {"", "WordDocument", "1Table"},
        )

    def test_reads_stream_from_mini_fat(self) -> None:
        payload = b"hello mini"
        compound = CompoundFile(build_mini_stream_cfb(payload))
        self.assertEqual(compound.open_stream("Small"), payload)

    def test_reads_version4_4096_byte_sectors(self) -> None:
        compound = CompoundFile(build_version4_cfb())
        self.assertEqual(compound.header.major_version, 4)
        self.assertEqual(compound.header.sector_size, 4096)
        self.assertTrue(compound.open_stream("Big").startswith(b"version four"))

    def test_rejects_cycle_in_regular_fat_chain(self) -> None:
        data = bytearray(build_mini_stream_cfb())
        fat_sector_offset = (3 + 1) * 512
        data[fat_sector_offset : fat_sector_offset + 4] = b"\x00\x00\x00\x00"
        compound = CompoundFile(data)
        with self.assertRaisesRegex(InvalidCompoundFile, "cycle"):
            compound.open_stream("Small")

    def test_missing_stream_is_explicit(self) -> None:
        compound = CompoundFile(build_word_cfb())
        with self.assertRaises(StreamNotFound):
            compound.open_stream("0Table")

    def test_rejects_non_cfb_input(self) -> None:
        with self.assertRaisesRegex(InvalidCompoundFile, "shorter|signature"):
            CompoundFile(b"not a document")

    def test_safely_repairs_malformed_root_name_only(self) -> None:
        data = bytearray(build_word_cfb())
        directory_offset = (16 + 1) * 512
        malformed_name = "Y:\\Desktop\\~WRD0000.tmp".encode("utf-16le")
        data[directory_offset : directory_offset + len(malformed_name)] = malformed_name
        data[directory_offset + 64 : directory_offset + 66] = b"\x16\x00"
        compound = CompoundFile(data)
        root = compound.get_entry("")
        self.assertEqual(root.name, "Root Entry")
        self.assertTrue(root.name_was_repaired)
        self.assertEqual(len(compound.open_stream("WordDocument")), 4096)
