import base64
import struct
import unittest

from doc2docx.errors import InvalidWordDocument
from doc2docx.msdoc import read_officeart_shapes

from .fixtures import _header_textbox_officeart


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/w8AAgMBgN+X2ioAAAAASUVORK5CYII="
)


def _record(
    record_type: int,
    payload: bytes,
    *,
    version: int,
    instance: int = 0,
) -> bytes:
    return struct.pack(
        "<HHI",
        (instance << 4) | version,
        record_type,
        len(payload),
    ) + payload


def _floating_picture_officeart(*, complex_pib: bool = False, pib_index: int = 1):
    blip = _record(
        0xF01E,
        b"\0" * 16 + b"\xFF" + _PNG,
        version=0,
        instance=0x6E0,
    )
    if complex_pib:
        dgg_payload = b""
        property_id = 0x8104
        property_value = len(blip)
        complex_data = blip
        delay_stream = None
    else:
        fbse_payload = (
            b"\x06\x06"
            + b"\0" * 16
            + struct.pack("<HIII", 0, len(blip), 1, 32)
            + b"\0\0\0\0"
        )
        fbse = _record(0xF007, fbse_payload, version=2, instance=6)
        dgg_payload = _record(0xF001, fbse, version=0xF, instance=1)
        property_id = 0x4104
        property_value = pib_index
        complex_data = b""
        delay_stream = b"\0" * 32 + blip
    dgg = _record(0xF000, dgg_payload, version=0xF)
    fsp = _record(0xF00A, struct.pack("<II", 1026, 0), version=2, instance=75)
    fopt = _record(
        0xF00B,
        struct.pack("<HI", property_id, property_value) + complex_data,
        version=3,
        instance=1,
    )
    shape = _record(0xF004, fsp + fopt, version=0xF)
    drawing = _record(0xF002, shape, version=0xF)
    return dgg + b"\0" + drawing, delay_stream


class OfficeArtParsingTests(unittest.TestCase):
    def test_resolves_delayed_bstore_blip_through_shape_pib(self) -> None:
        data, delay_stream = _floating_picture_officeart()

        shapes = read_officeart_shapes(
            data,
            offset=0,
            size=len(data),
            delay_stream=delay_stream,
        )

        image = shapes.image_at(1026)
        assert image is not None
        self.assertEqual(image.extension, "png")
        self.assertEqual(image.data, _PNG)
        self.assertEqual(image.blip_index, 1)

    def test_resolves_complex_pib_and_rejects_invalid_bstore_index(self) -> None:
        complex_data, _ = _floating_picture_officeart(complex_pib=True)
        shapes = read_officeart_shapes(
            complex_data,
            offset=0,
            size=len(complex_data),
        )
        self.assertEqual(shapes.image_at(1026).data, _PNG)  # type: ignore[union-attr]

        invalid_data, delay_stream = _floating_picture_officeart(pib_index=2)
        with self.assertRaises(InvalidWordDocument):
            read_officeart_shapes(
                invalid_data,
                offset=0,
                size=len(invalid_data),
                delay_stream=delay_stream,
            )

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

    def test_reads_compound_and_dashed_line_styles(self) -> None:
        data = _header_textbox_officeart(
            1025,
            line_style=4,
            line_dashing=9,
            line_join=0,
            line_end_cap=1,
        )

        style = read_officeart_shapes(data, offset=0, size=len(data)).style_at(1025)

        assert style is not None
        self.assertEqual(style.line_style, "thickBetweenThin")
        self.assertEqual(style.line_dash, "longdashdot")
        self.assertEqual(style.line_join, "bevel")
        self.assertEqual(style.line_end_cap, "square")
        # The fixture disables the line, so supported stored styling should not
        # make an otherwise exact textbox approximation-prone.
        self.assertFalse(style.approximated)

    def test_reads_and_normalizes_wrap_polygon(self) -> None:
        source_points = ((0, 0), (21600, 0), (10800, 21600), (0, 0))
        data = _header_textbox_officeart(1025, wrap_polygon=source_points)

        shapes = read_officeart_shapes(data, offset=0, size=len(data))

        self.assertEqual(shapes.wrap_polygon_at(1025), source_points)

    def test_reads_signed_fixed_point_shape_rotation(self) -> None:
        data = _header_textbox_officeart(1025, rotation_fixed=-45 * 0x10000)

        shapes = read_officeart_shapes(data, offset=0, size=len(data))

        self.assertEqual(shapes.rotation_at(1025), -45.0)

    def test_truncated_drawing_record_is_rejected(self) -> None:
        data = _header_textbox_officeart(1025)

        with self.assertRaises(InvalidWordDocument):
            read_officeart_shapes(data[:-1], offset=0, size=len(data) - 1)


if __name__ == "__main__":
    unittest.main()
