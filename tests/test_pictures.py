import base64
import struct
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile
import zlib

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import (
    CharacterProperties,
    Document,
    Field,
    InlinePicture,
    Paragraph,
    StoryCharacter,
    parse_main_story,
)
from doc2docx.msdoc import parse_inline_picture, read_inline_pictures
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/w8AAgMBgN+X2ioAAAAASUVORK5CYII="
)


def _officeart_record(
    record_type: int,
    payload: bytes,
    *,
    version: int,
    instance: int,
) -> bytes:
    return struct.pack(
        "<HHI",
        (instance << 4) | version,
        record_type,
        len(payload),
    ) + payload


def _nil_picf_binary_data(payload: bytes) -> bytes:
    return struct.pack("<iH", 68 + len(payload), 68) + b"\x00" * 62 + payload


def _picf_with_blip(
    record_type: int,
    instance: int,
    image_data: bytes,
) -> bytes:
    return _picf_with_blip_payload(
        record_type,
        instance,
        b"\0" * 16 + b"\xFF" + image_data,
    )


def _picf_with_blip_payload(
    record_type: int,
    instance: int,
    payload: bytes,
) -> bytes:
    shape = _officeart_record(0xF004, b"", version=0xF, instance=0)
    blip = _officeart_record(
        record_type,
        payload,
        version=0,
        instance=instance,
    )
    fbse_payload = (
        b"\x06\x06"
        + b"\0" * 16
        + struct.pack("<HIII", 0x00FF, len(blip), 1, 0xFFFFFFFF)
        + b"\0\0\0\0"
        + blip
    )
    fbse = _officeart_record(0xF007, fbse_payload, version=2, instance=6)
    picf = bytearray(68)
    struct.pack_into("<iHhhhh", picf, 0, 68 + len(shape) + len(fbse), 68, 100, 0, 0, 0)
    struct.pack_into("<hhHH", picf, 28, 1800, 900, 1200, 1200)
    return bytes(picf) + shape + fbse


def _metafile_payload(data: bytes, *, compressed: bool) -> bytes:
    saved = zlib.compress(data) if compressed else data
    return b"\0" * 16 + struct.pack(
        "<I4i2iIBB",
        len(data),
        0,
        0,
        100,
        100,
        360000,
        360000,
        len(saved),
        0x00 if compressed else 0xFE,
        0xFE,
    ) + saved


class InlinePictureTests(unittest.TestCase):
    def test_parses_metafile_and_tiff_blips(self) -> None:
        emf = bytearray(88)
        struct.pack_into("<II", emf, 0, 1, len(emf))
        struct.pack_into("<I", emf, 40, 0x464D4520)
        wmf = struct.pack("<HHHIHIH", 1, 9, 0x0300, 9, 0, 3, 0)
        pict = struct.pack(">HhhhhHH", 14, 0, 0, 100, 200, 0x0011, 0x02FF)
        tiff = b"II*\0\x08\0\0\0\0\0"
        cases = (
            (
                0xF01A,
                0x3D4,
                _metafile_payload(bytes(emf), compressed=True),
                "emf",
                bytes(emf),
            ),
            (
                0xF01B,
                0x216,
                _metafile_payload(wmf, compressed=False),
                "wmf",
                wmf,
            ),
            (
                0xF01C,
                0x542,
                _metafile_payload(pict, compressed=True),
                "pct",
                pict,
            ),
            (0xF029, 0x6E4, b"\0" * 16 + b"\xFF" + tiff, "tif", tiff),
        )
        for picture_id, (record_type, instance, payload, extension, expected) in enumerate(
            cases,
            start=1,
        ):
            with self.subTest(extension=extension):
                picture = parse_inline_picture(
                    _picf_with_blip_payload(record_type, instance, payload),
                    0,
                    picture_id=picture_id,
                )
                self.assertEqual(picture.extension, extension)
                self.assertEqual(picture.data, expected)

    def test_rejects_inconsistent_or_unbounded_metafile_headers(self) -> None:
        emf = bytearray(88)
        struct.pack_into("<II", emf, 0, 1, len(emf))
        struct.pack_into("<I", emf, 40, 0x464D4520)
        payload = bytearray(_metafile_payload(bytes(emf), compressed=True))
        struct.pack_into("<I", payload, 16, 257 * 1024 * 1024)
        with self.assertRaises(InvalidWordDocument):
            parse_inline_picture(
                _picf_with_blip_payload(0xF01A, 0x3D4, bytes(payload)),
                0,
                picture_id=1,
            )

    def test_parses_png_jpeg_and_dib_blips(self) -> None:
        jpeg = b"\xFF\xD8sample\xFF\xD9"
        dib = struct.pack(
            "<IiiHHIIiiII",
            40,
            1,
            1,
            1,
            24,
            0,
            4,
            0,
            0,
            0,
            0,
        ) + b"\0\0\xFF\0"
        cases = (
            (0xF01E, 0x6E0, _PNG, "png", b"\x89PNG"),
            (0xF01D, 0x46A, jpeg, "jpg", b"\xFF\xD8"),
            (0xF01F, 0x7A8, dib, "bmp", b"BM"),
        )
        for picture_id, (record_type, instance, data, extension, signature) in enumerate(
            cases,
            start=1,
        ):
            with self.subTest(extension=extension):
                picture = parse_inline_picture(
                    _picf_with_blip(record_type, instance, data),
                    0,
                    picture_id=picture_id,
                )
                self.assertEqual(picture.extension, extension)
                self.assertTrue(picture.data.startswith(signature))
                self.assertEqual(picture.width_emu, 2160 * 635)
                self.assertEqual(picture.height_emu, 1080 * 635)

        padded_jpeg = parse_inline_picture(
            _picf_with_blip(0xF01D, 0x46A, jpeg + b"\0\0"),
            0,
            picture_id=4,
        )
        self.assertEqual(padded_jpeg.data, jpeg)
        with self.assertRaises(InvalidWordDocument):
            parse_inline_picture(
                _picf_with_blip(0xF01D, 0x46A, jpeg + b"\0\x01"),
                0,
                picture_id=5,
            )

    def test_malformed_picf_is_rejected_and_collection_reports_unknown_blip(self) -> None:
        malformed = bytearray(_picf_with_blip(0xF01E, 0x6E0, _PNG))
        struct.pack_into("<i", malformed, 0, len(malformed) + 1)
        with self.assertRaises(InvalidWordDocument):
            parse_inline_picture(bytes(malformed), 0, picture_id=1)

        unsupported = _picf_with_blip(0xF020, 0x001, b"unsupported")
        properties = CharacterProperties(special=True, picture_location=0)
        report = ConversionReport("unknown-picture.doc")
        collection = read_inline_pictures(
            unsupported,
            (StoryCharacter("\x01", 0, 1),),
            report=report,
            character_properties_at=lambda _cp: properties,
        )
        self.assertFalse(collection.pictures)
        self.assertEqual(collection.deferred_count, 1)
        self.assertEqual(report.warnings[0].code, "INLINE_PICTURE_FORMAT_DEFERRED")

    def test_picture_anchor_replaces_u0001_in_the_document_model(self) -> None:
        picture = InlinePicture(
            1,
            0,
            _PNG,
            "png",
            "image/png",
            914400,
            914400,
        )
        document = parse_main_story(
            "A\x01B\r",
            ConversionReport("picture-model.doc"),
            inline_picture_at=lambda cp: picture if cp == 1 else None,
        )
        self.assertIs(document.paragraphs[0].inlines[1], picture)

    def test_hyperlink_binary_data_is_consumed_without_a_placeholder(self) -> None:
        story = "\x13 REF Target \\h \x01\x14Target text\x15\r"
        characters = tuple(
            StoryCharacter(character, cp, cp + 1)
            for cp, character in enumerate(story)
        )
        anchor_cp = story.index("\x01")
        properties = CharacterProperties(
            special=True,
            picture_location=0,
            picture_is_binary=True,
        )
        hfd = b"\x00" + b"\x00" * 16 + b"hyperlink-object"
        report = ConversionReport("binary-field.doc")

        collection = read_inline_pictures(
            _nil_picf_binary_data(hfd),
            characters,
            report=report,
            character_properties_at=lambda _cp: properties,
        )

        self.assertEqual(collection.binary_data_count, 1)
        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.consumed_binary_data_cps, {anchor_cp})
        self.assertFalse(report.warnings)

        parsed_report = ConversionReport("binary-field.doc")
        document = parse_main_story(
            characters,
            parsed_report,
            bookmark_names=("Target",),
            ignored_character_cps=collection.consumed_binary_data_cps,
        )
        field = document.paragraphs[0].inlines[0]
        self.assertIsInstance(field, Field)
        assert isinstance(field, Field)
        self.assertEqual(field.instruction, " REF Target \\h ")
        self.assertFalse(parsed_report.warnings)

    def test_malformed_hyperlink_binary_data_remains_deferred(self) -> None:
        story = "\x13 HYPERLINK \"https://example.test\"\x01\x14Link\x15\r"
        characters = tuple(
            StoryCharacter(character, cp, cp + 1)
            for cp, character in enumerate(story)
        )
        properties = CharacterProperties(
            special=True,
            picture_location=0,
            picture_is_binary=True,
        )
        invalid_hfd = b"\xE0" + b"\x00" * 16 + b"hyperlink-object"
        report = ConversionReport("malformed-binary-field.doc")

        collection = read_inline_pictures(
            _nil_picf_binary_data(invalid_hfd),
            characters,
            report=report,
            character_properties_at=lambda _cp: properties,
        )

        self.assertEqual(collection.deferred_count, 1)
        self.assertFalse(collection.consumed_binary_data_cps)
        self.assertEqual(report.warnings[0].code, "INLINE_BINARY_DATA_MALFORMED")

    def test_reused_data_offset_gets_unique_drawing_identifiers(self) -> None:
        data = _picf_with_blip(0xF01E, 0x6E0, _PNG)
        properties = CharacterProperties(special=True, picture_location=0)
        collection = read_inline_pictures(
            data,
            (
                StoryCharacter("\x01", 0, 1),
                StoryCharacter("\x01", 1, 2),
            ),
            report=ConversionReport("shared-picture.doc"),
            character_properties_at=lambda _cp: properties,
        )

        self.assertEqual(
            [picture.picture_id for picture in collection.pictures],
            [1, 2],
        )
        self.assertIs(collection.pictures[0].data, collection.pictures[1].data)

    def test_header_scan_uses_requested_picture_id_and_story_diagnostic(self) -> None:
        properties = CharacterProperties(special=True, picture_location=0)
        report = ConversionReport("header-picture.doc")
        collection = read_inline_pictures(
            None,
            (StoryCharacter("\x01", 20, 21),),
            first_picture_id=7,
            story_name="headers",
            report=report,
            character_properties_at=lambda _cp: properties,
        )

        self.assertFalse(collection.pictures)
        self.assertEqual(report.warnings[0].location.story, "headers")

        data = _picf_with_blip(0xF01E, 0x6E0, _PNG)
        collection = read_inline_pictures(
            data,
            (StoryCharacter("\x01", 20, 21),),
            first_picture_id=7,
            story_name="headers",
            report=ConversionReport("header-picture.doc"),
            character_properties_at=lambda _cp: properties,
        )
        self.assertEqual(collection.pictures[0].picture_id, 7)
        self.assertIs(collection.picture_at(20), collection.pictures[0])

    def test_packages_inline_picture_media_relationship_and_drawing(self) -> None:
        picture = InlinePicture(
            1,
            0,
            _PNG,
            "png",
            "image/png",
            914400,
            457200,
            "sample.png",
        )
        paragraph = Paragraph((picture,))
        document = Document((paragraph,), pictures=(picture,))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "picture.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                self.assertEqual(package.read("word/media/image1.png"), _PNG)
                relationships = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                content_types = ET.fromstring(package.read("[Content_Types].xml"))
                document_xml = ET.fromstring(package.read("word/document.xml"))

        image_relationship = next(
            item
            for item in relationships.findall(f"{REL}Relationship")
            if item.get("Type", "").endswith("/image")
        )
        self.assertEqual(image_relationship.get("Id"), "rIdImage1")
        self.assertEqual(image_relationship.get("Target"), "media/image1.png")
        png_default = next(
            item
            for item in content_types.findall(f"{CT}Default")
            if item.get("Extension") == "png"
        )
        self.assertEqual(png_default.get("ContentType"), "image/png")
        extent = document_xml.find(f".//{WP}extent")
        assert extent is not None
        self.assertEqual((extent.get("cx"), extent.get("cy")), ("914400", "457200"))
        blip = document_xml.find(f".//{A}blip")
        assert blip is not None
        self.assertEqual(blip.get(f"{R}embed"), "rIdImage1")
        self.assertIsNotNone(document_xml.find(f".//{W}drawing"))


if __name__ == "__main__":
    unittest.main()
