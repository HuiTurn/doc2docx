import unittest

from doc2docx.errors import InvalidWordDocument
from doc2docx.msdoc import read_officeart_shapes

from .fixtures import _header_textbox_officeart


class OfficeArtParsingTests(unittest.TestCase):
    def test_reads_basic_header_textbox_shape_style(self) -> None:
        data = _header_textbox_officeart(1025)

        shapes = read_officeart_shapes(data, offset=0, size=len(data))

        style = shapes.style_at(1025)
        assert style is not None
        self.assertFalse(style.fill_enabled)
        self.assertFalse(style.line_enabled)
        self.assertEqual(style.inset_left_emu, 0)
        self.assertEqual(style.inset_top_emu, 0)
        self.assertEqual(style.inset_right_emu, 0)
        self.assertEqual(style.inset_bottom_emu, 0)
        self.assertFalse(style.approximated)

    def test_truncated_drawing_record_is_rejected(self) -> None:
        data = _header_textbox_officeart(1025)

        with self.assertRaises(InvalidWordDocument):
            read_officeart_shapes(data[:-1], offset=0, size=len(data) - 1)


if __name__ == "__main__":
    unittest.main()
