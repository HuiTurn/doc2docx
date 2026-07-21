import struct
import unittest

from doc2docx.errors import InvalidWordDocument
from doc2docx.msdoc.sprm import (
    apply_character_modifiers,
    apply_paragraph_modifiers,
    parse_grpprl,
)


class SprmTests(unittest.TestCase):
    def test_east_asian_grid_controls_are_parsed(self) -> None:
        paragraph_grpprl = b"".join(
            struct.pack("<HB", opcode, value)
            for opcode, value in (
                (0x2431, 0),
                (0x2433, 1),
                (0x2434, 0),
                (0x2435, 1),
                (0x2436, 1),
                (0x2437, 0),
                (0x2438, 1),
                (0x2447, 0),
                (0x2448, 1),
            )
        )
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(paragraph_grpprl, label="east-asian.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        self.assertFalse(properties.widow_control)
        self.assertTrue(properties.kinsoku)
        self.assertFalse(properties.word_wrap)
        self.assertTrue(properties.overflow_punctuation)
        self.assertTrue(properties.top_line_punctuation)
        self.assertFalse(properties.auto_space_east_asian_latin)
        self.assertTrue(properties.auto_space_east_asian_numbers)
        self.assertFalse(properties.snap_to_grid)
        self.assertTrue(properties.adjust_right_indent)

        character, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0x0868, 0)
                + struct.pack("<HB", 0x286F, 1)
                + struct.pack("<HB", 0x286F, 0xFF)
                + struct.pack("<HB", 0x286F, 1)
                + struct.pack("<HH", 0x486D, 0x0409)
                + struct.pack("<HH", 0x486E, 0x0804)
                + struct.pack("<HH", 0x485F, 0x0401)
                + struct.pack("<HH", 0x485F, 0x0001)
                + struct.pack("<HH", 0x4873, 0x0400)
                + struct.pack("<HH", 0x4A61, 24)
                + struct.pack("<Hh", 0x484B, 2)
                + struct.pack("<HB", 0x0855, 1)
                + struct.pack("<HB", 0x085C, 1)
                + struct.pack("<HB", 0x085D, 0),
                label="character-grid.grpprl",
            )
        )
        self.assertFalse(unsupported)
        self.assertFalse(character.snap_to_grid)
        self.assertEqual(character.font_hint, "eastAsia")
        self.assertEqual(character.language, "en-US")
        self.assertEqual(character.east_asia_language, "zh-CN")
        self.assertEqual(character.complex_script_language, "ar")
        self.assertEqual(character.complex_script_size_half_points, 24)
        self.assertEqual(character.kerning_half_points, 2)
        self.assertTrue(character.no_proof)
        self.assertTrue(character.complex_script_bold)
        self.assertFalse(character.complex_script_italic)

    def test_symbol_character_uses_its_font_table_entry(self) -> None:
        character, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<HHH", 0x6A09, 3, 0xF03A),
                label="symbol.grpprl",
            ),
            font_names={3: "Wingdings"},
        )

        self.assertFalse(unsupported)
        self.assertEqual(character.symbol_font, "Wingdings")
        self.assertEqual(character.symbol_character_code, 0xF03A)

    def test_paragraph_spacing_in_line_units_is_preserved(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HhHh", 0x4458, 25, 0x4459, 50),
                label="line-spacing.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        self.assertEqual(properties.space_before_lines, 25)
        self.assertEqual(properties.space_after_lines, 50)

    def test_cell_margins_and_word97_shading_are_parsed(self) -> None:
        default_margin = struct.pack("<BBBBBH", 6, 0, 1, 0x0A, 3, 108)
        cell_margin = struct.pack("<BBBBBH", 6, 1, 2, 0x05, 3, 36)
        shading_value = 6 | (7 << 5) | (1 << 10)
        shading = struct.pack("<BH", 2, shading_value)
        grpprl = b"".join(
            (
                struct.pack("<H", 0xD634) + default_margin,
                struct.pack("<H", 0xD632) + cell_margin,
                struct.pack("<H", 0xD609) + shading,
            )
        )

        modifiers = parse_grpprl(grpprl, label="cell-formatting.grpprl")
        properties, unsupported = apply_paragraph_modifiers(
            modifiers,
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        row = properties.table_row
        self.assertEqual(row.default_cell_margins.left, 108)
        self.assertEqual(row.default_cell_margins.right, 108)
        self.assertEqual(len(row.cell_margin_overrides), 1)
        self.assertEqual(row.cell_margin_overrides[0].first_cell, 1)
        self.assertEqual(row.cell_margin_overrides[0].sides, ("top", "bottom"))
        assert row.cell_shadings[0] is not None
        self.assertEqual(row.cell_shadings[0].pattern, "solid")
        self.assertEqual(row.cell_shadings[0].foreground, "FF0000")
        self.assertEqual(row.cell_shadings[0].background, "FFFF00")

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

    def test_table_style_identifier_is_retained_on_the_row(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HH", 0x563A, 11),
                label="table-style.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        self.assertEqual(properties.table_row.table_style_id, 11)

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
