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
    Paragraph,
)
from doc2docx.msdoc import (
    OfficeArtRasterImage,
    OfficeArtShapeCollection,
    ShapeAnchor,
    read_main_floating_pictures,
)
from doc2docx.ooxml import write_docx


WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

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


if __name__ == "__main__":
    unittest.main()
