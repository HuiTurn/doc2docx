import unittest

from doc2docx.binary import BinaryReader
from doc2docx.errors import BinaryBoundsError


class BinaryReaderTests(unittest.TestCase):
    def test_reads_little_endian_and_tracks_position(self) -> None:
        reader = BinaryReader(b"\x01\x02\x03\x04\x05")
        self.assertEqual(reader.u8(), 1)
        self.assertEqual(reader.u16(), 0x0302)
        self.assertEqual(reader.read(2), b"\x04\x05")
        self.assertEqual(reader.remaining, 0)

    def test_rejects_out_of_bounds_read(self) -> None:
        reader = BinaryReader(b"\x00", label="fixture")
        with self.assertRaisesRegex(BinaryBoundsError, "fixture"):
            reader.u32()
