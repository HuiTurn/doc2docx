import base64
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
import zipfile

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    CharacterProperties,
    Document,
    FloatingPicture,
    HeaderFooterStory,
    Paragraph,
    SectionProperties,
)
from doc2docx.msdoc import (
    OfficeArtRasterImage,
    OfficeArtShapeCollection,
    ShapeAnchor,
    read_header_floating_pictures,
    read_main_floating_pictures,
)
from doc2docx.ooxml import write_docx


WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/w8AAgMBgN+X2ioAAAAASUVORK5CYII="
)


def _anchor(shape_id: int, *, wrap_type: str = "square") -> ShapeAnchor:
    return ShapeAnchor(
        anchor_cp=7,
        shape_id=shape_id,
        left=720,
        top=8,
        right=2880,
        bottom=1088,
        horizontal_relative="column",
        vertical_relative="paragraph",
        wrap_type=wrap_type,
        wrap_side="both",
        behind_text=False,
        anchor_locked=False,
    )


class FloatingPictureTests(unittest.TestCase):
    def test_header_anchor_is_exposed_at_absolute_story_cp(self) -> None:
        shape_id = 2049
        officeart = OfficeArtShapeCollection(
            {},
            {
                shape_id: OfficeArtRasterImage(
                    _PNG,
                    "png",
                    "image/png",
                    1,
                )
            },
            horizontally_flipped_shape_ids=frozenset((shape_id,)),
            rotations_by_shape_id={shape_id: 12.5},
        )
        collection = read_header_floating_pictures(
            {shape_id: _anchor(shape_id)},
            officeart,
            header_story_cp_start=100,
            first_picture_id=4,
            report=ConversionReport("header-floating-picture.doc"),
            character_properties_at=lambda cp: CharacterProperties(
                special=cp == 107
            ),
        )

        self.assertEqual(len(collection.pictures), 1)
        self.assertEqual(collection.pictures[0].picture_id, 4)
        self.assertEqual(collection.pictures[0].anchor_cp, 107)
        self.assertTrue(collection.pictures[0].flip_horizontal)
        self.assertEqual(collection.pictures[0].rotation_degrees, 12.5)
        self.assertIs(collection.picture_at(107), collection.pictures[0])

    def test_associates_spa_anchor_with_officeart_raster_image(self) -> None:
        shape_id = 1026
        officeart = OfficeArtShapeCollection(
            {},
            {
                shape_id: OfficeArtRasterImage(
                    _PNG,
                    "png",
                    "image/png",
                    1,
                )
            },
        )
        report = ConversionReport("floating-picture.doc")
        collection = read_main_floating_pictures(
            {shape_id: _anchor(shape_id)},
            officeart,
            first_picture_id=3,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(len(collection.pictures), 1)
        picture = collection.pictures[0]
        self.assertEqual(picture.picture_id, 3)
        self.assertEqual(picture.shape_id, shape_id)
        self.assertEqual((picture.width_twips, picture.height_twips), (2160, 1080))
        self.assertIs(collection.picture_at(7), picture)
        self.assertFalse(report.warnings)

    def test_tight_wrap_is_diagnosed_and_textbox_shape_is_excluded(self) -> None:
        images = {
            shape_id: OfficeArtRasterImage(_PNG, "png", "image/png", 1)
            for shape_id in (100, 101)
        }
        report = ConversionReport("floating-wrap.doc")
        collection = read_main_floating_pictures(
            {
                100: _anchor(100, wrap_type="tight"),
                101: _anchor(101),
            },
            OfficeArtShapeCollection({}, images),
            excluded_shape_ids=frozenset((101,)),
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual([picture.shape_id for picture in collection.pictures], [100])
        self.assertEqual(report.warnings[0].code, "FLOATING_PICTURE_WRAP_APPROXIMATED")

    def test_tight_wrap_polygon_is_preserved_without_approximation(self) -> None:
        shape_id = 100
        polygon = ((0, 0), (21600, 0), (10800, 21600), (0, 0))
        report = ConversionReport("floating-wrap-polygon.doc")
        collection = read_main_floating_pictures(
            {shape_id: _anchor(shape_id, wrap_type="tight")},
            OfficeArtShapeCollection(
                {},
                {shape_id: OfficeArtRasterImage(_PNG, "png", "image/png", 1)},
                {},
                {shape_id: polygon},
            ),
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.pictures[0].wrap_polygon, polygon)
        self.assertFalse(report.warnings)

    def test_packages_positioned_picture_as_wp_anchor(self) -> None:
        picture = FloatingPicture(
            picture_id=1,
            shape_id=1026,
            anchor_cp=7,
            data=_PNG,
            extension="png",
            content_type="image/png",
            left_twips=720,
            top_twips=8,
            width_twips=2160,
            height_twips=1080,
            horizontal_relative="column",
            vertical_relative="paragraph",
            wrap_type="square",
            wrap_side="both",
            behind_text=False,
            anchor_locked=True,
            flip_horizontal=True,
            flip_vertical=True,
            rotation_degrees=-22.5,
        )
        document = Document(
            (Paragraph((picture,)),),
            pictures=(picture,),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "floating.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
                self.assertEqual(package.read("word/media/image1.png"), _PNG)

        anchor = root.find(f".//{WP}anchor")
        assert anchor is not None
        self.assertEqual(anchor.get("locked"), "1")
        horizontal = anchor.find(f"{WP}positionH")
        vertical = anchor.find(f"{WP}positionV")
        assert horizontal is not None and vertical is not None
        self.assertEqual(horizontal.get("relativeFrom"), "column")
        self.assertEqual(horizontal.find(f"{WP}posOffset").text, "457200")  # type: ignore[union-attr]
        self.assertEqual(vertical.get("relativeFrom"), "paragraph")
        self.assertEqual(vertical.find(f"{WP}posOffset").text, "5080")  # type: ignore[union-attr]
        extent = anchor.find(f"{WP}extent")
        assert extent is not None
        self.assertEqual((extent.get("cx"), extent.get("cy")), ("1371600", "685800"))
        self.assertEqual(anchor.find(f"{WP}wrapSquare").get("wrapText"), "bothSides")  # type: ignore[union-attr]
        blip = root.find(
            ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
        )
        assert blip is not None
        self.assertEqual(blip.get(f"{R}embed"), "rIdImage1")
        transform = root.find(f".//{A}xfrm")
        assert transform is not None
        self.assertEqual(transform.get("rot"), "-1350000")
        self.assertEqual(transform.get("flipH"), "1")
        self.assertEqual(transform.get("flipV"), "1")

    def test_packages_tight_wrap_polygon(self) -> None:
        polygon = ((0, 0), (21600, 0), (10800, 21600), (0, 0))
        picture = FloatingPicture(
            picture_id=1,
            shape_id=1026,
            anchor_cp=7,
            data=_PNG,
            extension="png",
            content_type="image/png",
            left_twips=0,
            top_twips=0,
            width_twips=2160,
            height_twips=1080,
            horizontal_relative="column",
            vertical_relative="paragraph",
            wrap_type="tight",
            wrap_side="both",
            behind_text=False,
            anchor_locked=False,
            wrap_polygon=polygon,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "tight-wrap.docx"
            write_docx(Document((Paragraph((picture,)),), pictures=(picture,)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        wrap = root.find(f".//{WP}wrapTight")
        assert wrap is not None
        self.assertEqual(wrap.get("wrapText"), "bothSides")
        points = wrap.findall(f"{WP}wrapPolygon/*")
        self.assertEqual(
            [(point.get("x"), point.get("y")) for point in points],
            [(str(x), str(y)) for x, y in polygon],
        )

    def test_scopes_image_relationships_to_document_and_header_parts(self) -> None:
        main_picture = FloatingPicture(
            picture_id=1,
            shape_id=1026,
            anchor_cp=7,
            data=_PNG,
            extension="png",
            content_type="image/png",
            left_twips=720,
            top_twips=8,
            width_twips=2160,
            height_twips=1080,
            horizontal_relative="column",
            vertical_relative="paragraph",
            wrap_type="square",
            wrap_side="both",
            behind_text=False,
            anchor_locked=False,
        )
        header_picture = FloatingPicture(
            picture_id=2,
            shape_id=2049,
            anchor_cp=10,
            data=_PNG,
            extension="png",
            content_type="image/png",
            left_twips=0,
            top_twips=0,
            width_twips=1440,
            height_twips=720,
            horizontal_relative="margin",
            vertical_relative="paragraph",
            wrap_type="none",
            wrap_side="both",
            behind_text=True,
            anchor_locked=False,
        )
        header = HeaderFooterStory(
            10,
            11,
            (Paragraph((header_picture,)),),
        )
        document = Document(
            (Paragraph((main_picture,)),),
            sections=(SectionProperties(0, 1, default_header=header),),
            pictures=(main_picture, header_picture),
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "scoped-pictures.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                document_rels = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                header_rels = ET.fromstring(
                    package.read("word/_rels/header1.xml.rels")
                )
                header_xml = ET.fromstring(package.read("word/header1.xml"))

        document_images = {
            item.get("Id")
            for item in document_rels.findall(f"{REL}Relationship")
            if item.get("Type", "").endswith("/image")
        }
        header_images = {
            item.get("Id")
            for item in header_rels.findall(f"{REL}Relationship")
            if item.get("Type", "").endswith("/image")
        }
        self.assertEqual(document_images, {"rIdImage1"})
        self.assertEqual(header_images, {"rIdImage2"})
        header_blip = header_xml.find(
            ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
        )
        assert header_blip is not None
        self.assertEqual(header_blip.get(f"{R}embed"), "rIdImage2")


if __name__ == "__main__":
    unittest.main()
