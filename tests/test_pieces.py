import unittest
import struct

from doc2docx.diagnostics import ConversionReport
from doc2docx.msdoc import Piece, PieceTable
from doc2docx.msdoc import read_formatting, read_piece_table


class PieceTableTests(unittest.TestCase):
    def test_compact_piece_prm_is_mapped_to_full_sprm(self) -> None:
        # Prm0 isprm 0x56 maps to sprmCFItalic; val is stored in the high byte.
        prm = (1 << 8) | (0x56 << 1)
        word_stream = b"A\r"
        piece_table = PieceTable((Piece(0, 2, 0, True, prm),), word_stream)
        report = ConversionReport("prm0.doc")

        formatting = read_formatting(
            b"",
            word_stream,
            piece_table,
            fc_plcf_bte_chpx=0,
            lcb_plcf_bte_chpx=0,
            fc_plcf_bte_papx=0,
            lcb_plcf_bte_papx=0,
            report=report,
        )

        self.assertTrue(formatting.character_properties_at(0).italic)
        self.assertFalse(report.warnings)

    def test_complex_piece_prm_is_applied_after_fkp_formatting(self) -> None:
        grpprl = struct.pack("<HB", 0x0835, 1)
        word_stream = b"A\r"
        plc_pcd = struct.pack("<2I", 0, 2)
        plc_pcd += struct.pack("<HIH", 0, 0x40000000, 1)
        clx = b"\x01" + struct.pack("<H", len(grpprl)) + grpprl
        clx += b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd
        report = ConversionReport("prm.doc")

        piece_table = read_piece_table(
            clx,
            word_stream,
            fc_clx=0,
            lcb_clx=len(clx),
            report=report,
        )
        formatting = read_formatting(
            b"",
            word_stream,
            piece_table,
            fc_plcf_bte_chpx=0,
            lcb_plcf_bte_chpx=0,
            fc_plcf_bte_papx=0,
            lcb_plcf_bte_papx=0,
            report=report,
        )

        self.assertEqual(len(piece_table.prcs), 1)
        self.assertTrue(formatting.character_properties_at(0).bold)
        self.assertFalse(report.warnings)

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
