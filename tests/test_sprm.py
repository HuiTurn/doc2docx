import struct
import unittest

from doc2docx.errors import InvalidWordDocument
from doc2docx.msdoc.sprm import apply_paragraph_modifiers, parse_grpprl


class SprmTests(unittest.TestCase):
    def test_table_markers_and_tdef_table_are_parsed(self) -> None:
        boundaries = (-108, 1000, 2100)
        tdef = struct.pack("<HB3h", 8, 2, *boundaries)
        border = bytes((4, 1, 0, 0))
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x2416, 1),
                struct.pack("<HB", 0x2417, 1),
                struct.pack("<Hh", 0x9602, 108),
                struct.pack("<HB", 0xD605, 24) + border * 6,
                struct.pack("<H", 0xD608) + tdef,
            )
        )

        modifiers = parse_grpprl(grpprl, label="table.grpprl")
        properties, unsupported = apply_paragraph_modifiers(
            modifiers,
            style_id=0,
        )

        self.assertFalse(unsupported)
        self.assertTrue(properties.in_table)
        self.assertTrue(properties.table_terminating)
        assert properties.table_row is not None
        self.assertEqual(properties.table_row.cell_boundaries_twips, boundaries)
        self.assertEqual(len(properties.table_row.cell_definitions), 2)
        self.assertEqual(properties.table_row.gap_half_twips, 108)
        top_border = properties.table_row.borders.top
        assert top_border is not None
        self.assertEqual(top_border.style, "single")

    def test_large_tdef_table_uses_its_16_bit_length(self) -> None:
        column_count = 12
        boundaries = struct.pack(
            f"<{column_count + 1}h",
            *(index * 100 for index in range(column_count + 1)),
        )
        descriptors = bytes(20 * column_count)
        operand_without_cb = bytes((column_count,)) + boundaries + descriptors
        operand = struct.pack("<H", len(operand_without_cb) + 1) + operand_without_cb

        modifiers = parse_grpprl(
            struct.pack("<H", 0xD608) + operand,
            label="large-table.grpprl",
        )

        self.assertEqual(len(modifiers), 1)
        self.assertEqual(modifiers[0].operand, operand)

    def test_tdef_table_cell_descriptors_are_parsed(self) -> None:
        border = bytes((6, 1, 2, 0))
        restart_flags = 2 | (3 << 5) | (1 << 7) | (3 << 9) | (1 << 12)
        continue_flags = 1 | (1 << 5) | (2 << 7) | (3 << 9)
        descriptors = b"".join(
            (
                struct.pack("<HH", restart_flags, 900) + border * 4,
                struct.pack("<HH", continue_flags, 1100) + border * 4,
            )
        )
        remainder = bytes((2,)) + struct.pack("<3h", 0, 900, 2000) + descriptors
        operand = struct.pack("<H", len(remainder) + 1) + remainder

        modifiers = parse_grpprl(
            struct.pack("<H", 0xD608) + operand,
            label="described-table.grpprl",
        )
        properties, unsupported = apply_paragraph_modifiers(
            modifiers,
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        first, second = properties.table_row.cell_definitions
        self.assertEqual(first.preferred_width_twips, 900)
        self.assertEqual(first.horizontal_merge, "restart")
        self.assertEqual(first.vertical_merge, "restart")
        self.assertEqual(first.vertical_alignment, "center")
        self.assertTrue(first.fit_text)
        assert first.borders.top is not None
        self.assertEqual(first.borders.top.color, "0000FF")
        self.assertEqual(second.horizontal_merge, "continue")
        self.assertEqual(second.vertical_merge, "continue")
        self.assertEqual(second.vertical_alignment, "bottom")

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
