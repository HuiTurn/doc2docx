import struct
import unittest

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import CharacterProperties
from doc2docx.msdoc.footnotes import read_footnotes
from doc2docx.msdoc.pieces import Piece, PieceTable


class FootnoteParsingTests(unittest.TestCase):
    @staticmethod
    def _piece_table() -> PieceTable:
        data = b"\x02\rA\r\r\r"
        return PieceTable((Piece(0, len(data), 0, True, 0),), data)

    def test_footnote_fib_parts_must_exist_together(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_footnotes(
                b"",
                self._piece_table(),
                ccp_text=2,
                ccp_footnotes=3,
                reference_offset=0,
                reference_size=0,
                text_offset=0,
                text_size=0,
                report=ConversionReport("missing-footnote-plcs.doc"),
            )

    def test_malformed_reference_plc_size_is_rejected(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_footnotes(
                b"\0" * 32,
                self._piece_table(),
                ccp_text=2,
                ccp_footnotes=3,
                reference_offset=0,
                reference_size=9,
                text_offset=16,
                text_size=12,
                report=ConversionReport("bad-footnote-reference-plc.doc"),
            )

    def test_duplicate_reference_and_text_cps_are_rejected(self) -> None:
        duplicate_references = struct.pack("<3I2H", 0, 0, 2, 1, 1)
        valid_text = struct.pack("<3I", 0, 2, 3)
        duplicate_text = struct.pack("<3I", 0, 0, 3)
        valid_reference = struct.pack("<2IH", 0, 2, 1)
        cases = (
            (duplicate_references + valid_text, len(duplicate_references)),
            (valid_reference + duplicate_text, len(valid_reference)),
        )

        for index, (table_stream, reference_size) in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(InvalidWordDocument):
                    read_footnotes(
                        table_stream,
                        self._piece_table(),
                        ccp_text=2,
                        ccp_footnotes=3,
                        reference_offset=0,
                        reference_size=reference_size,
                        text_offset=reference_size,
                        text_size=12,
                        report=ConversionReport("duplicate-footnote-cp.doc"),
                        character_properties_at=lambda _cp: CharacterProperties(
                            special=True
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
