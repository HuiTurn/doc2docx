import struct
import unittest

from doc2docx.errors import InvalidWordDocument
from doc2docx.msdoc.sprm import parse_grpprl


class SprmTests(unittest.TestCase):
    def test_spra_lengths_allow_unknown_modifiers_to_be_skipped(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x0835, 1),
                struct.pack("<HB2s", 0xC60D, 2, b"xy"),
                struct.pack("<HB", 0x2405, 1),
            )
        )

        modifiers = parse_grpprl(grpprl, label="test.grpprl")

        self.assertEqual(
            [modifier.opcode for modifier in modifiers],
            [0x0835, 0xC60D, 0x2405],
        )
        self.assertEqual(modifiers[1].operand, b"\x02xy")

    def test_papx_alignment_padding_can_be_explicitly_accepted(self) -> None:
        modifiers = parse_grpprl(
            struct.pack("<HB", 0x2431, 0) + b"\0",
            label="PapxInFkp.grpprl",
            allow_trailing_zero_padding=True,
        )

        self.assertEqual(len(modifiers), 1)
        self.assertEqual(modifiers[0].opcode, 0x2431)

    def test_truncated_operand_is_rejected(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            parse_grpprl(b"\x43\x4A\x14", label="truncated.grpprl")


if __name__ == "__main__":
    unittest.main()
