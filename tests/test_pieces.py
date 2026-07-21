import unittest

from doc2docx.diagnostics import ConversionReport
from doc2docx.msdoc import Piece, PieceTable


class PieceTableTests(unittest.TestCase):
    def test_utf16_surrogate_pair_retains_two_cp_units(self) -> None:
        raw = "A😀B".encode("utf-16le")
        table = PieceTable((Piece(0, 4, 0, False, 0),), raw)

        characters = table.extract_characters(
            0,
            4,
            ConversionReport("surrogate.doc"),
            story="main",
        )

        self.assertEqual("".join(unit.text for unit in characters), "A😀B")
        self.assertEqual(
            [(unit.cp_start, unit.cp_end) for unit in characters],
            [(0, 1), (1, 3), (3, 4)],
        )

    def test_fc_ranges_map_across_compressed_and_utf16_pieces(self) -> None:
        stream = b"abc" + b"\0" * 7 + "世界".encode("utf-16le")
        table = PieceTable(
            (
                Piece(0, 3, 0, True, 0),
                Piece(3, 5, 10, False, 0),
            ),
            stream,
        )

        self.assertEqual(table.fc_range_to_cp_ranges(1, 2), ((1, 2),))
        self.assertEqual(table.fc_range_to_cp_ranges(10, 14), ((3, 5),))


if __name__ == "__main__":
    unittest.main()
