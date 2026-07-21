import unittest

from doc2docx.cfb import CompoundFile
from doc2docx.errors import InvalidCompoundFile, StreamNotFound

from .fixtures import build_mini_stream_cfb, build_version4_cfb, build_word_cfb


class CompoundFileTests(unittest.TestCase):
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
