import struct
import unittest

from doc2docx.errors import InvalidWordDocument
from doc2docx.model import ParagraphFrameProperties, ShadingProperties
from doc2docx.msdoc.sprm import (
    apply_character_modifiers,
    apply_paragraph_modifiers,
    parse_grpprl,
    unassigned_language_lids,
)


class SprmTests(unittest.TestCase):
    def test_unassigned_language_lid_is_repaired_to_no_linguistic_content(self) -> None:
        modifiers = parse_grpprl(
            struct.pack("<HH", 0x486E, 0x00FF),
            label="unassigned-language.grpprl",
        )
        properties, unsupported, _ = apply_character_modifiers(modifiers)

        self.assertFalse(unsupported)
        self.assertEqual(properties.east_asia_language, "zxx")
        self.assertEqual(unassigned_language_lids(modifiers), {0x00FF})

    def test_paragraph_frame_drop_cap_and_shading_are_parsed(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0x261B, 0xA0)
                + struct.pack("<HB", 0x2423, 0x02)
                + struct.pack("<Hh", 0x8418, 720)
                + struct.pack("<HH", 0x8419, 0xFFF8)
                + struct.pack("<Hh", 0x841A, 1440)
                + struct.pack("<HH", 0x442B, 0x8000 | 720)
                + struct.pack("<Hh", 0x842E, 120)
                + struct.pack("<Hh", 0x842F, 240)
                + struct.pack("<HB", 0x2430, 1)
                + struct.pack("<HH", 0x443A, 5)
                + struct.pack("<HH", 0x442C, 0x001A)
                + struct.pack("<HH", 0x442D, 0x0101),
                label="paragraph-frame.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        self.assertEqual(
            properties.frame,
            ParagraphFrameProperties(
                horizontal_anchor="page",
                vertical_anchor="text",
                wrap="around",
                horizontal_position_twips=719,
                vertical_alignment="center",
                width_twips=1440,
                height_twips=720,
                height_rule="atLeast",
                horizontal_space_twips=240,
                vertical_space_twips=120,
                anchor_locked=True,
                text_direction="tbRlV",
                drop_cap="margin",
                drop_cap_lines=3,
            ),
        )
        self.assertEqual(
            properties.shading,
            ShadingProperties("clear", "000000", "FFFFFF"),
        )

    def test_picture_location_and_binary_flag_survive_style_resets(self) -> None:
        properties, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<Hi", 0x6A03, 640)
                + struct.pack("<HB", 0x0806, 1)
                + struct.pack("<HH", 0x4A30, 16)
                + struct.pack("<HB", 0x2A33, 0),
                label="picture-style-reset.grpprl",
            )
        )

        self.assertFalse(unsupported)
        self.assertEqual(properties.picture_location, 640)
        self.assertTrue(properties.picture_is_binary)

    def test_special_character_state_survives_character_style_resets(self) -> None:
        properties, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0x0855, 1)
                + struct.pack("<HB", 0x080A, 1)
                + struct.pack("<HB", 0x0856, 1)
                + struct.pack("<HB", 0x085A, 1)
                + struct.pack("<HB", 0x0882, 1)
                + struct.pack("<HB", 0x0811, 1)
                + struct.pack("<HB", 0x2A0C, 6)
                + struct.pack("<HB", 0x286F, 1)
                + struct.pack("<HI", 0x6815, 7)
                + struct.pack("<HI", 0x6816, 8)
                + struct.pack("<HHH", 0x6A09, 3, 0xF03A)
                + struct.pack("<HH", 0x4A30, 16)
                + struct.pack("<HB", 0x2A33, 0),
                label="special-style-reset.grpprl",
            ),
            font_names={3: "Wingdings"},
        )

        self.assertFalse(unsupported)
        self.assertTrue(properties.special)
        self.assertTrue(properties.ole_object)
        self.assertTrue(properties.object_placeholder)
        self.assertTrue(properties.bidirectional)
        self.assertTrue(properties.complex_script)
        self.assertTrue(properties.web_hidden)
        self.assertEqual(properties.highlight, "red")
        self.assertEqual(properties.font_hint, "eastAsia")
        self.assertEqual(properties.revision_format_id, 7)
        self.assertEqual(properties.revision_text_id, 8)
        self.assertEqual(properties.symbol_font, "Wingdings")
        self.assertEqual(properties.symbol_character_code, 0xF03A)

    def test_manual_fit_text_width_and_region_id_are_parsed(self) -> None:
        operand = bytes((8,)) + struct.pack("<ii", 1440, -2)
        properties, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<H", 0xCA76) + operand,
                label="fit-text.grpprl",
            )
        )

        self.assertFalse(unsupported)
        self.assertEqual(properties.fit_text_width_twips, 1440)
        self.assertEqual(properties.fit_text_id, 0xFFFFFFFE)

        _, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<H", 0xCA76)
                + bytes((8,))
                + struct.pack("<ii", -720, 1),
                label="minimum-fit-text.grpprl",
            )
        )
        self.assertEqual(unsupported, {0xCA76})

    def test_character_underline_color_shading_and_border_are_parsed(self) -> None:
        red = bytes((0xFF, 0, 0, 0))
        green = bytes((0, 0xFF, 0, 0))
        shading = red + green + struct.pack("<H", 1)
        border = bytes((0, 0, 0xFF, 0, 8, 1, 0, 0))
        properties, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0x2A3E, 1)
                + struct.pack("<HBBBB", 0x6877, 0x11, 0x22, 0x33, 0)
                + struct.pack("<HB", 0xCA71, len(shading))
                + shading
                + struct.pack("<HB", 0xCA72, len(border))
                + border
                + struct.pack("<HB", 0x2859, 4)
                + struct.pack("<HB", 0x0811, 1)
                + struct.pack("<HB", 0x0818, 1),
                label="decorated-character.grpprl",
            )
        )

        self.assertFalse(unsupported)
        self.assertEqual(properties.underline_color, "112233")
        self.assertEqual(
            properties.shading,
            ShadingProperties("solid", "FF0000", "00FF00"),
        )
        assert properties.border is not None
        self.assertEqual(properties.border.color, "0000FF")
        self.assertEqual(properties.border.size_eighth_points, 8)
        self.assertEqual(properties.text_effect, "antsBlack")
        self.assertTrue(properties.web_hidden)
        self.assertTrue(properties.special_vanish)

    def test_east_asian_run_layout_is_parsed(self) -> None:
        flags = 0x0001 | 0x0002 | (2 << 8) | 0x1000
        operand = bytes((6,)) + struct.pack("<Hi", flags, -3)
        properties, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<H", 0xCA78) + operand,
                label="east-asian-layout.grpprl",
            )
        )

        self.assertFalse(unsupported)
        self.assertTrue(properties.east_asian_vertical)
        self.assertTrue(properties.east_asian_combine)
        self.assertEqual(properties.east_asian_combine_brackets, "square")
        self.assertTrue(properties.east_asian_vertical_compress)
        self.assertEqual(properties.east_asian_layout_id, 0xFFFFFFFD)

    def test_legacy_character_decoration_and_complex_script_flags_are_parsed(self) -> None:
        properties, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<HH", 0x4866, 1 | (2 << 5) | (1 << 10))
                + struct.pack("<H4s", 0x6865, bytes((6, 1, 2, 0)))
                + struct.pack("<HB", 0x085A, 1)
                + struct.pack("<HB", 0x0882, 1),
                label="legacy-character-decoration.grpprl",
            )
        )

        self.assertFalse(unsupported)
        self.assertIsNotNone(properties.shading)
        self.assertIsNotNone(properties.border)
        self.assertTrue(properties.bidirectional)
        self.assertTrue(properties.complex_script)

    def test_line_break_clear_side_is_parsed(self) -> None:
        properties, unsupported, _ = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0x2879, 3),
                label="line-break-clear.grpprl",
            )
        )

        self.assertFalse(unsupported)
        self.assertEqual(properties.line_break_clear, "all")

    def test_modern_table_borders_widths_and_colors_are_parsed(self) -> None:
        border = bytes((0x11, 0x22, 0x33, 0, 4, 1, 0x22, 0))
        table_borders = bytes((48,)) + border * 6
        cell_width = bytes((5, 0, 2, 3)) + struct.pack("<H", 1200)
        top_colors = bytes((8, 0xFF, 0, 0, 0, 0, 0, 0, 0xFF))
        grpprl = b"".join(
            (
                struct.pack("<HH", 0x548A, 1),
                struct.pack("<H", 0xD613) + table_borders,
                struct.pack("<HBH", 0xF614, 3, 2400),
                struct.pack("<HBH", 0xF617, 3, 0),
                struct.pack("<HBH", 0xF618, 3, 0),
                struct.pack("<H", 0xD635) + cell_width,
                struct.pack("<H", 0xD61A) + top_colors,
            )
        )

        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(grpprl, label="modern-table.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        row = properties.table_row
        self.assertEqual(row.alignment, "center")
        self.assertEqual(row.preferred_width_type, "dxa")
        self.assertEqual(row.preferred_width, 2400)
        assert row.borders.top is not None
        self.assertEqual(row.borders.top.color, "112233")
        self.assertEqual(row.borders.top.space_points, 2)
        self.assertTrue(row.borders.top.shadow)
        self.assertEqual(row.cell_width_overrides[0].width_twips, 1200)
        self.assertEqual(row.cell_top_border_colors, ("FF0000", "auto"))

    def test_wps_redundant_table_modifiers_use_the_absolute_grid(self) -> None:
        remainder = bytes((2,)) + struct.pack("<3h", -108, 506, 2262)
        tdef_operand = struct.pack("<H", len(remainder) + 1) + remainder
        nil_shading = b"\x00" * 10
        percentage_width = struct.pack("<BBBBH", 5, 0, 2, 2, 361)
        grpprl = b"".join(
            (
                struct.pack("<H", 0xD608) + tdef_operand,
                struct.pack("<HB", 0xD612, 20) + nil_shading * 2,
                struct.pack("<H", 0xD635) + percentage_width,
                struct.pack("<H", 0xD5FF) + b"\x04\x01\x00\x05\x00",
            )
        )

        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(grpprl, label="wps-table.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        self.assertEqual(
            properties.table_row.cell_boundaries_twips,
            (-108, 506, 2262),
        )
        self.assertEqual(properties.table_row.cell_width_overrides, ())
        self.assertTrue(
            all(
                definition.text_direction is None
                for definition in properties.table_row.cell_definitions
            )
        )

    def test_paragraph_outline_and_borders_are_parsed(self) -> None:
        modern_border = bytes((8, 0, 0, 0, 0xFF, 4, 1, 0, 0))
        red = bytes((0xFF, 0, 0, 0))
        green = bytes((0, 0xFF, 0, 0))
        shading = red + green + struct.pack("<H", 1)
        grpprl = b"".join(
            (
                struct.pack("<HB", 0x2640, 3),
                struct.pack("<H4s", 0x6424, bytes((4, 1, 2, 0))),
                struct.pack("<H", 0xC650) + modern_border,
                struct.pack("<H", 0xC652) + modern_border,
                struct.pack("<HB", 0xC64D, len(shading)) + shading,
                struct.pack("<HH", 0x4439, 2),
                struct.pack("<HB", 0x2470, 1),
                struct.pack("<HB", 0x2471, 2),
                struct.pack("<Hh", 0x4455, 125),
                struct.pack("<Hh", 0x4456, 250),
                struct.pack("<Hh", 0x4457, -75),
                struct.pack("<HI", 0x6629, 0),
                struct.pack("<HB8s", 0xC653, 8, bytes(8)),
                struct.pack("<HB", 0xC669, 0),
                struct.pack("<HB", 0xC66C, 0),
            )
        )

        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(grpprl, label="paragraph-borders.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        self.assertEqual(properties.outline_level, 3)
        assert properties.borders is not None
        assert properties.borders.top is not None
        assert properties.borders.bottom is not None
        assert properties.borders.between is not None
        self.assertEqual(properties.borders.top.color, "0000FF")
        self.assertEqual(properties.borders.bottom.color, "auto")
        self.assertEqual(properties.borders.between.color, "auto")
        self.assertEqual(
            properties.shading,
            ShadingProperties("solid", "FF0000", "00FF00"),
        )
        self.assertEqual(properties.text_alignment, "baseline")
        self.assertTrue(properties.mirror_indents)
        self.assertEqual(properties.textbox_tight_wrap, "firstAndLastLine")
        self.assertEqual(properties.right_indent_chars, 125)
        self.assertEqual(properties.left_indent_chars, 250)
        self.assertEqual(properties.first_line_indent_chars, -75)

    def test_custom_tab_additions_and_deletions_are_parsed(self) -> None:
        operand = bytes((8, 0, 2, 0x39, 0x10, 0x72, 0x20, 0x01, 0x02))
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<H", 0xC60D) + operand,
                label="tabs.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.tab_stops is not None
        self.assertEqual(
            [(tab.position_twips, tab.alignment) for tab in properties.tab_stops],
            [(4153, "center"), (8306, "right")],
        )

        delete_operand = bytes((6, 2, 0x39, 0x10, 0x72, 0x20, 0))
        deleted, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<H", 0xC60D) + delete_operand,
                label="deleted-tabs.grpprl",
            ),
            style_id=0,
        )
        self.assertFalse(unsupported)
        assert deleted.tab_stops is not None
        self.assertEqual(
            [(tab.position_twips, tab.alignment) for tab in deleted.tab_stops],
            [(4153, "clear"), (8306, "clear")],
        )

    def test_implicit_length_tab_changes_do_not_consume_following_sprm(self) -> None:
        tab_operand = (
            bytes((0xFF, 1))
            + struct.pack("<hH", 720, 25)
            + bytes((1,))
            + struct.pack("<hB", 1440, 0x09)
        )
        modifiers = parse_grpprl(
            struct.pack("<H", 0xC615)
            + tab_operand
            + struct.pack("<HB", 0x2405, 1),
            label="implicit-tabs.grpprl",
        )

        self.assertEqual([modifier.opcode for modifier in modifiers], [0xC615, 0x2405])
        properties, unsupported = apply_paragraph_modifiers(modifiers, style_id=0)
        self.assertFalse(unsupported)
        self.assertTrue(properties.keep_lines)
        assert properties.tab_stops is not None
        self.assertEqual(
            [
                (tab.position_twips, tab.alignment, tab.leader)
                for tab in properties.tab_stops
            ],
            [(720, "clear", None), (1440, "center", "dot")],
        )

    def test_regular_sprm_pchg_tabs_uses_delete_close_layout(self) -> None:
        body = (
            bytes((1,))
            + struct.pack("<hH", 720, 25)
            + bytes((0,))
        )
        operand = bytes((len(body),)) + body

        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<H", 0xC615) + operand,
                label="delete-close-tabs.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.tab_stops is not None
        self.assertEqual(
            [(tab.position_twips, tab.alignment) for tab in properties.tab_stops],
            [(720, "clear")],
        )

    def test_east_asian_grid_controls_are_parsed(self) -> None:
        paragraph_grpprl = b"".join(
            struct.pack("<HB", opcode, value)
            for opcode, value in (
                (0x2431, 0),
                (0x240C, 1),
                (0x242A, 1),
                (0x2433, 1),
                (0x2434, 0),
                (0x2435, 1),
                (0x2436, 1),
                (0x2437, 0),
                (0x2438, 1),
                (0x2441, 1),
                (0x2447, 0),
                (0x2448, 1),
                (0x245B, 1),
                (0x245C, 0),
                (0x246D, 1),
            )
        )
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(paragraph_grpprl, label="east-asian.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        self.assertFalse(properties.widow_control)
        self.assertTrue(properties.suppress_line_numbers)
        self.assertTrue(properties.suppress_auto_hyphens)
        self.assertTrue(properties.bidirectional)
        self.assertTrue(properties.kinsoku)
        self.assertFalse(properties.word_wrap)
        self.assertTrue(properties.overflow_punctuation)
        self.assertTrue(properties.top_line_punctuation)
        self.assertFalse(properties.auto_space_east_asian_latin)
        self.assertTrue(properties.auto_space_east_asian_numbers)
        self.assertFalse(properties.snap_to_grid)
        self.assertTrue(properties.adjust_right_indent)
        self.assertTrue(properties.auto_spacing_before)
        self.assertFalse(properties.auto_spacing_after)
        self.assertTrue(properties.contextual_spacing)

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
                + struct.pack("<Hh", 0x8840, -20)
                + struct.pack("<HB", 0x0855, 1)
                + struct.pack("<HB", 0x0875, 1)
                + struct.pack("<HB", 0x085C, 1)
                + struct.pack("<HB", 0x085D, 0)
                + struct.pack("<HB", 0x0838, 0)
                + struct.pack("<HB", 0x0839, 0)
                + struct.pack("<HB", 0x0854, 1)
                + struct.pack("<HB", 0x0858, 0)
                + struct.pack("<HH", 0x4852, 125)
                + struct.pack("<HB", 0x2A34, 4),
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
        self.assertEqual(character.spacing_twips, -20)
        self.assertTrue(character.special)
        self.assertTrue(character.no_proof)
        self.assertTrue(character.complex_script_bold)
        self.assertFalse(character.complex_script_italic)
        self.assertFalse(character.outline)
        self.assertFalse(character.shadow)
        self.assertTrue(character.imprint)
        self.assertFalse(character.emboss)
        self.assertEqual(character.scale_percent, 125)
        self.assertEqual(character.emphasis, "underDot")

    def test_field_hidden_and_revision_save_ids_are_parsed(self) -> None:
        character, unsupported, relative_count = apply_character_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0x0802, 0x81)
                + struct.pack("<HI", 0x6815, 0x12345678)
                + struct.pack("<HI", 0x6816, 0x90ABCDEF),
                label="character-revision.grpprl",
            )
        )

        self.assertFalse(unsupported)
        self.assertEqual(relative_count, 1)
        self.assertEqual(character.revision_format_id, 0x12345678)
        self.assertEqual(character.revision_text_id, 0x90ABCDEF)

        paragraph, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HI", 0x6467, 0x13572468),
                label="paragraph-revision.grpprl",
            ),
            style_id=0,
        )
        self.assertFalse(unsupported)
        self.assertEqual(paragraph.revision_save_id, 0x13572468)

    def test_table_layout_and_style_look_are_parsed(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0x3615, 1)
                + struct.pack("<HhH", 0x740A, 0, 0x04A0),
                label="table-layout.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        row = properties.table_row
        self.assertTrue(row.auto_fit)
        self.assertTrue(row.first_row_style)
        self.assertFalse(row.last_row_style)
        self.assertTrue(row.first_column_style)
        self.assertFalse(row.last_column_style)
        self.assertFalse(row.no_row_banding)
        self.assertTrue(row.no_column_banding)

        with self.assertRaisesRegex(InvalidWordDocument, "padding"):
            apply_paragraph_modifiers(
                parse_grpprl(
                    struct.pack("<HhH", 0x740A, -1, 0x8000),
                    label="invalid-table-layout.grpprl",
                ),
                style_id=0,
            )

    def test_table_leading_and_trailing_grid_widths_are_parsed(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HBH", 0xF617, 3, 240)
                + struct.pack("<HBH", 0xF618, 3, 360),
                label="table-grid-before-after.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        self.assertEqual(properties.table_row.grid_before_width, 240)
        self.assertEqual(properties.table_row.grid_before_width_type, "dxa")
        self.assertEqual(properties.table_row.grid_after_width, 360)
        self.assertEqual(properties.table_row.grid_after_width_type, "dxa")

    def test_prc_data_table_grid_shading_and_revision_are_parsed(self) -> None:
        red = bytes((0xFF, 0, 0, 0))
        green = bytes((0, 0xFF, 0, 0))
        shading = red + green + struct.pack("<H", 1)
        prc_grpprl = (
            struct.pack("<HBBH", 0x7621, 0, 2, 1000)
            + struct.pack("<HBBH", 0x7623, 0, 2, 1200)
            + struct.pack("<HB", 0xD670, len(shading))
            + shading
            + struct.pack("<HI", 0x7479, 0x12345678)
        )
        data_stream = struct.pack("<H", len(prc_grpprl)) + prc_grpprl
        outer = parse_grpprl(
            struct.pack("<HIHh", 0x646B, 0, 0x9601, 720),
            label="table-properties-reference.grpprl",
        )

        properties, unsupported = apply_paragraph_modifiers(
            outer,
            style_id=0,
            data_stream=data_stream,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        row = properties.table_row
        self.assertEqual(row.cell_boundaries_twips, (0, 1200, 2400))
        self.assertEqual(len(row.cell_definitions), 2)
        self.assertIsNone(row.left_indent_twips)
        self.assertEqual(row.revision_save_id, 0x12345678)
        self.assertEqual(
            row.cell_shadings,
            (ShadingProperties("solid", "FF0000", "00FF00"),),
        )

        with self.assertRaisesRegex(InvalidWordDocument, "cyclic"):
            apply_paragraph_modifiers(
                parse_grpprl(
                    struct.pack("<HI", 0x646B, 0),
                    label="cyclic-table-properties.grpprl",
                ),
                style_id=0,
                data_stream=struct.pack("<H", 12)
                + struct.pack("<HI", 0x646B, 0)
                + struct.pack("<HB", 0x2416, 1)
                + struct.pack("<HB", 0x2417, 1),
            )

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

    def test_modern_nested_indent_supersedes_legacy_delta(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<Hh", 0x840F, 100)
                + struct.pack("<Hh", 0x4610, 20)
                + struct.pack("<Hh", 0x465F, -30),
                label="nested-indent.grpprl",
            ),
            style_id=0,
        )
        updated, updated_unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<Hh", 0x845E, 200),
                label="updated-nested-indent.grpprl",
            ),
            style_id=0,
            initial_properties=properties,
        )

        self.assertFalse(unsupported)
        self.assertFalse(updated_unsupported)
        self.assertEqual(properties.left_indent_twips, 70)
        self.assertEqual(updated.left_indent_twips, 170)

    def test_cell_margins_and_word97_shading_are_parsed(self) -> None:
        default_margin = struct.pack("<BBBBBH", 6, 0, 1, 0x0A, 3, 108)
        cell_spacing = struct.pack("<BBBBBH", 6, 0, 1, 0x0F, 3, 72)
        cell_margin = struct.pack("<BBBBBH", 6, 1, 2, 0x05, 3, 36)
        shading_value = 6 | (7 << 5) | (1 << 10)
        shading = struct.pack("<BH", 2, shading_value)
        grpprl = b"".join(
            (
                struct.pack("<H", 0xD634) + default_margin,
                struct.pack("<H", 0xD633) + cell_spacing,
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
        self.assertEqual(row.cell_spacing_twips, 72)
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

    def test_table_preferred_indent_is_parsed(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HBh", 0xF661, 3, -360),
                label="table-indent.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        self.assertEqual(properties.table_row.left_indent_twips, -360)

        with self.assertRaises(InvalidWordDocument):
            apply_paragraph_modifiers(
                parse_grpprl(
                    struct.pack("<HBh", 0xF661, 1, 12),
                    label="invalid-table-indent.grpprl",
                ),
                style_id=0,
            )

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
        restart_flags = (
            2
            | (1 << 2)
            | (3 << 5)
            | (1 << 7)
            | (3 << 9)
            | (1 << 12)
            | (1 << 14)
        )
        continue_flags = 1 | (4 << 2) | (1 << 5) | (2 << 7) | (3 << 9)
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
        self.assertEqual(first.text_direction, "tbRl")
        self.assertEqual(first.vertical_alignment, "center")
        self.assertTrue(first.fit_text)
        self.assertTrue(first.hide_mark)
        assert first.borders.top is not None
        self.assertEqual(first.borders.top.color, "0000FF")
        self.assertEqual(second.horizontal_merge, "continue")
        self.assertEqual(second.vertical_merge, "continue")
        self.assertEqual(second.text_direction, "lrTbV")
        self.assertEqual(second.vertical_alignment, "bottom")

    def test_direct_table_cell_ranges_override_tdef_table(self) -> None:
        remainder = bytes((3,)) + struct.pack("<4h", 0, 800, 1700, 2700)
        tdef_operand = struct.pack("<H", len(remainder) + 1) + remainder
        shading = (
            bytes((0xFF, 0, 0, 0))
            + bytes((0, 0xFF, 0, 0))
            + struct.pack("<H", 1)
        )
        border = bytes((0, 0, 0xFF, 0, 8, 1, 0, 0))
        grpprl = b"".join(
            (
                struct.pack("<H", 0xD608) + tdef_operand,
                struct.pack("<HBB", 0x5624, 0, 2),
                struct.pack("<HBBH", 0x7629, 1, 3, 5),
                struct.pack("<HBBB", 0xD62B, 2, 0, 3),
                struct.pack("<HBBBB", 0xD62C, 3, 0, 2, 1),
                struct.pack("<HBBB", 0xF636, 0, 2, 1),
                struct.pack("<HBBBB", 0xD639, 3, 1, 3, 1),
                struct.pack("<HBBBB", 0xD642, 3, 0, 1, 1),
                struct.pack("<HBBB", 0xD62D, 12, 0, 2) + shading,
                struct.pack("<HBBBB", 0xD62F, 11, 0, 1, 0x30) + border,
            )
        )

        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(grpprl, label="direct-cell-ranges.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        first, second, third = properties.table_row.cell_definitions
        self.assertEqual(first.horizontal_merge, "restart")
        self.assertEqual(second.horizontal_merge, "continue")
        self.assertEqual(first.vertical_merge, "restart")
        self.assertEqual(first.vertical_alignment, "center")
        self.assertEqual(second.vertical_alignment, "center")
        self.assertTrue(first.fit_text)
        self.assertTrue(second.fit_text)
        self.assertEqual(second.text_direction, "tbRlV")
        self.assertEqual(third.text_direction, "tbRlV")
        self.assertTrue(second.no_wrap)
        self.assertTrue(third.no_wrap)
        self.assertTrue(first.hide_mark)
        self.assertEqual(
            properties.table_row.cell_shadings[:2],
            (
                ShadingProperties("solid", "FF0000", "00FF00"),
                ShadingProperties("solid", "FF0000", "00FF00"),
            ),
        )
        assert first.borders.diagonal_down is not None
        assert first.borders.diagonal_up is not None
        self.assertEqual(first.borders.diagonal_down.color, "0000FF")

    def test_legacy_and_alternating_direct_cell_formatting_are_parsed(self) -> None:
        remainder = bytes((3,)) + struct.pack("<4h", 0, 800, 1600, 2400)
        tdef_operand = struct.pack("<H", len(remainder) + 1) + remainder
        shading80 = struct.pack("<H", 1 | (2 << 5) | (1 << 10))
        border80 = bytes((6, 1, 2, 0))
        grpprl = b"".join(
            (
                struct.pack("<H", 0xD608) + tdef_operand,
                struct.pack("<HBB", 0x7628, 0, 3) + shading80,
                struct.pack("<HBBBB", 0xD620, 7, 1, 3, 0x05) + border80,
            )
        )

        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(grpprl, label="legacy-cell-formatting.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        self.assertIsNotNone(properties.table_row.cell_shadings[0])
        self.assertIsNone(properties.table_row.cell_shadings[1])
        self.assertIsNotNone(properties.table_row.cell_shadings[2])
        first, second, third = properties.table_row.cell_definitions
        self.assertIsNone(first.borders.top)
        self.assertIsNotNone(second.borders.top)
        self.assertIsNotNone(second.borders.bottom)
        self.assertIsNotNone(third.borders.top)

    def test_segmented_modern_cell_shading_reaches_cells_23_and_45(self) -> None:
        first = bytes((0xFF, 0, 0, 0)) + bytes((0, 0, 0xFF, 0)) + struct.pack("<H", 1)
        second = bytes((0, 0xFF, 0, 0)) + bytes((0xFF, 0, 0, 0)) + struct.pack("<H", 1)
        third = bytes((0, 0, 0xFF, 0)) + bytes((0, 0xFF, 0, 0)) + struct.pack("<H", 1)
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0xD670, 10)
                + first
                + struct.pack("<HB", 0xD671, 10)
                + second
                + struct.pack("<HB", 0xD672, 10)
                + third,
                label="segmented-cell-shading.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        shadings = properties.table_row.cell_shadings
        self.assertEqual(len(shadings), 45)
        self.assertEqual(shadings[0].foreground, "FF0000")  # type: ignore[union-attr]
        self.assertEqual(shadings[22].foreground, "00FF00")  # type: ignore[union-attr]
        self.assertEqual(shadings[44].foreground, "0000FF")  # type: ignore[union-attr]

    def test_whole_table_shading_is_parsed(self) -> None:
        shading = (
            bytes((0xFF, 0, 0, 0))
            + bytes((0, 0xFF, 0, 0))
            + struct.pack("<H", 1)
        )
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HB", 0xD660, len(shading)) + shading,
                label="whole-table-shading.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        self.assertEqual(
            properties.table_row.table_shading,
            ShadingProperties("solid", "FF0000", "00FF00"),
        )

    def test_direct_table_split_clears_horizontal_merge(self) -> None:
        descriptors = b"".join(
            struct.pack("<HH", value, 0) + bytes(16)
            for value in (2, 1)
        )
        remainder = bytes((2,)) + struct.pack("<3h", 0, 900, 1800) + descriptors
        tdef_operand = struct.pack("<H", len(remainder) + 1) + remainder
        grpprl = (
            struct.pack("<H", 0xD608)
            + tdef_operand
            + struct.pack("<HBB", 0x5625, 0, 2)
        )

        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(grpprl, label="split-cells.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        self.assertEqual(
            [item.horizontal_merge for item in properties.table_row.cell_definitions],
            [None, None],
        )

    def test_table_delete_updates_cell_arrays_and_override_ranges(self) -> None:
        remainder = bytes((3,)) + struct.pack("<4h", 0, 800, 1600, 2400)
        tdef_operand = struct.pack("<H", len(remainder) + 1) + remainder
        shadings = struct.pack(
            "<3H",
            1 | (2 << 5) | (1 << 10),
            2 | (3 << 5) | (1 << 10),
            3 | (4 << 5) | (1 << 10),
        )
        colors = b"".join(
            (
                bytes((0xFF, 0, 0, 0)),
                bytes((0, 0xFF, 0, 0)),
                bytes((0, 0, 0xFF, 0)),
            )
        )
        cell_margin = struct.pack("<BBBBBH", 6, 1, 3, 0x0F, 3, 36)
        cell_width = struct.pack("<BBBBH", 5, 0, 3, 3, 900)
        grpprl = b"".join(
            (
                struct.pack("<H", 0xD608) + tdef_operand,
                struct.pack("<HB", 0xD609, len(shadings)) + shadings,
                struct.pack("<HB", 0xD61A, len(colors)) + colors,
                struct.pack("<H", 0xD632) + cell_margin,
                struct.pack("<H", 0xD635) + cell_width,
                struct.pack("<HBB", 0x5622, 1, 2),
            )
        )

        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(grpprl, label="deleted-cell.grpprl"),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        row = properties.table_row
        self.assertEqual(row.cell_boundaries_twips, (0, 800, 1600))
        self.assertEqual(len(row.cell_definitions), 2)
        self.assertEqual(len(row.cell_shadings), 2)
        self.assertEqual(row.cell_top_border_colors, ("FF0000", "0000FF"))
        self.assertEqual(
            (row.cell_margin_overrides[0].first_cell, row.cell_margin_overrides[0].limit_cell),
            (1, 2),
        )
        self.assertEqual(
            (row.cell_width_overrides[0].first_cell, row.cell_width_overrides[0].limit_cell),
            (0, 2),
        )

    def test_table_direction_and_overlap_are_parsed(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            parse_grpprl(
                struct.pack("<HH", 0x560B, 1)
                + struct.pack("<HH", 0x5664, 1)
                + struct.pack("<HB", 0x3465, 1)
                + struct.pack("<HB", 0x360D, 0xA0)
                + struct.pack("<Hh", 0x940E, 720)
                + struct.pack("<HH", 0x940F, 0xFFF8)
                + struct.pack("<Hh", 0x9410, 120)
                + struct.pack("<Hh", 0x9411, 240)
                + struct.pack("<Hh", 0x941E, 360)
                + struct.pack("<Hh", 0x941F, 480),
                label="table-direction.grpprl",
            ),
            style_id=0,
        )

        self.assertFalse(unsupported)
        assert properties.table_row is not None
        row = properties.table_row
        self.assertTrue(row.bidirectional)
        self.assertTrue(row.no_overlap)
        self.assertEqual(row.horizontal_anchor, "page")
        self.assertEqual(row.vertical_anchor, "text")
        self.assertEqual(row.horizontal_position_twips, 719)
        self.assertEqual(row.vertical_alignment, "center")
        self.assertEqual(row.distance_left_twips, 120)
        self.assertEqual(row.distance_top_twips, 240)
        self.assertEqual(row.distance_right_twips, 360)
        self.assertEqual(row.distance_bottom_twips, 480)

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
