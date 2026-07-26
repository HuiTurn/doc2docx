from pathlib import Path
from dataclasses import replace
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    CharacterProperties,
    Document,
    FloatingShape,
    Paragraph,
    ShapeStyle,
    parse_main_story,
)
from doc2docx.msdoc import (
    OfficeArtShapeCollection,
    ShapeAnchor,
    read_header_floating_shapes,
    read_main_floating_shapes,
)
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"
O = "{urn:schemas-microsoft-com:office:office}"
W10 = "{urn:schemas-microsoft-com:office:word}"


def _anchor(shape_id: int) -> ShapeAnchor:
    return ShapeAnchor(
        anchor_cp=7,
        shape_id=shape_id,
        left=720,
        top=144,
        right=2880,
        bottom=1584,
        horizontal_relative="column",
        vertical_relative="paragraph",
        wrap_type="square",
        wrap_side="both",
        behind_text=False,
        anchor_locked=True,
    )


class FloatingShapeTests(unittest.TestCase):
    def test_recovers_supported_preset_shape_at_absolute_story_cp(self) -> None:
        shape_id = 2049
        style = ShapeStyle(fill_color="112233", line_color="445566")
        officeart = OfficeArtShapeCollection(
            {shape_id: style},
            shape_types_by_shape_id={shape_id: 4},
            horizontally_flipped_shape_ids=frozenset((shape_id,)),
            rotations_by_shape_id={shape_id: 22.5},
        )
        report = ConversionReport("shape.doc")

        collection = read_header_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            header_story_cp_start=100,
            report=report,
            character_properties_at=lambda cp: CharacterProperties(
                special=cp == 107
            ),
        )

        self.assertEqual(len(collection.shapes), 1)
        shape = collection.shapes[0]
        self.assertEqual((shape.anchor_cp, shape.shape_type), (107, 4))
        self.assertTrue(shape.flip_horizontal)
        self.assertEqual(shape.rotation_degrees, 22.5)
        self.assertIs(collection.shape_at(107), shape)
        self.assertFalse(report.warnings)

    def test_defers_unknown_geometry_but_preserves_supported_anchor(self) -> None:
        report = ConversionReport("shape.doc")
        officeart = OfficeArtShapeCollection(
            {1: ShapeStyle(), 2: ShapeStyle()},
            shape_types_by_shape_id={1: 1, 2: 202},
        )
        anchors = {1: _anchor(1), 2: _anchor(2)}
        anchors[2] = replace(anchors[2], anchor_cp=8)

        collection = read_main_floating_shapes(
            anchors,
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual([shape.shape_id for shape in collection.shapes], [1])
        self.assertEqual(collection.deferred_count, 1)
        self.assertEqual(report.warnings[0].code, "FLOATING_SHAPE_TYPES_DEFERRED")

    def test_emits_empty_picture_frame_as_unfilled_rect_for_tight_wrap(self) -> None:
        """PictureFrame without a BLIP still carries Spa wrap geometry."""

        shape_id = 1026
        style = ShapeStyle(fill_enabled=False, line_enabled=False)
        officeart = OfficeArtShapeCollection(
            {shape_id: style},
            shape_types_by_shape_id={shape_id: 75},
        )
        anchor = replace(_anchor(shape_id), wrap_type="tight", behind_text=False)
        report = ConversionReport("empty-picture-frame.doc")
        collection = read_main_floating_shapes(
            {shape_id: anchor},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(len(collection.shapes), 1)
        self.assertEqual(collection.shapes[0].shape_type, 75)
        self.assertEqual(collection.shapes[0].wrap_type, "tight")
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "empty-frame.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        rect = root.find(f".//{V}rect")
        assert rect is not None
        self.assertEqual(rect.get("filled"), "f")
        self.assertEqual(rect.get("stroked"), "f")
        wrap = root.find(f".//{W10}wrap")
        assert wrap is not None
        self.assertEqual(wrap.get("type"), "tight")

    def test_flattens_notprimitive_group_frame_as_unstroked_rect(self) -> None:
        from doc2docx.msdoc.officeart import OfficeArtChildAnchor

        parent_id = 1026
        child_id = 1028
        officeart = OfficeArtShapeCollection(
            {
                parent_id: ShapeStyle(
                    fill_enabled=True,
                    fill_color="FFFFFF",
                    line_enabled=True,
                ),
                child_id: ShapeStyle(),
            },
            shape_types_by_shape_id={parent_id: 0, child_id: 202},
            child_anchors_by_shape_id={
                child_id: OfficeArtChildAnchor(
                    parent_shape_id=parent_id,
                    group_left=0,
                    group_top=0,
                    group_right=1000,
                    group_bottom=1000,
                    left=100,
                    top=100,
                    right=400,
                    bottom=400,
                )
            },
        )
        report = ConversionReport("canvas-frame.doc")
        collection = read_main_floating_shapes(
            {parent_id: _anchor(parent_id)},
            officeart,
            excluded_shape_ids=frozenset((child_id,)),
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(len(collection.shapes), 1)
        frame = collection.shapes[0]
        self.assertEqual(frame.shape_type, 1)
        self.assertEqual(frame.vml_z_index, 0)
        assert frame.shape_style is not None
        self.assertTrue(frame.shape_style.fill_enabled)
        self.assertFalse(frame.shape_style.line_enabled)
        self.assertEqual(
            [warning.code for warning in report.warnings],
            [
                "GROUPED_FLOATING_FRAME_FLATTENED",
                "FLOATING_SHAPE_STYLE_APPROXIMATED",
            ],
        )

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "canvas-frame.docx"
            write_docx(
                Document((Paragraph((frame,)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        rect = root.find(f".//{V}rect")
        assert rect is not None
        self.assertEqual(rect.get("filled"), "t")
        self.assertEqual(rect.get("stroked"), "f")
        self.assertIn("z-index:0", rect.get("style", ""))

    def test_omits_transparent_notprimitive_group_frame(self) -> None:
        from doc2docx.msdoc.officeart import OfficeArtChildAnchor

        parent_id = 1026
        child_id = 1028
        officeart = OfficeArtShapeCollection(
            {
                parent_id: ShapeStyle(fill_enabled=False, line_enabled=False),
                child_id: ShapeStyle(),
            },
            shape_types_by_shape_id={parent_id: 0, child_id: 202},
            child_anchors_by_shape_id={
                child_id: OfficeArtChildAnchor(
                    parent_shape_id=parent_id,
                    group_left=0,
                    group_top=0,
                    group_right=1000,
                    group_bottom=1000,
                    left=100,
                    top=100,
                    right=400,
                    bottom=400,
                )
            },
        )
        report = ConversionReport("transparent-group-frame.doc")
        collection = read_main_floating_shapes(
            {parent_id: _anchor(parent_id)},
            officeart,
            excluded_shape_ids=frozenset((child_id,)),
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertFalse(collection.shapes)
        self.assertEqual(collection.deferred_count, 0)
        self.assertFalse(report.warnings)

    def test_recovers_arrow_line_and_plaque_presets(self) -> None:
        shape_types = (13, 14, 15, 20, 21)
        officeart = OfficeArtShapeCollection(
            {shape_type: ShapeStyle() for shape_type in shape_types},
            shape_types_by_shape_id={
                shape_type: shape_type for shape_type in shape_types
            },
        )
        anchors = {
            shape_type: replace(
                _anchor(shape_type),
                anchor_cp=index,
            )
            for index, shape_type in enumerate(shape_types)
        }
        collection = read_main_floating_shapes(
            anchors,
            officeart,
            report=ConversionReport("preset-shapes.doc"),
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(
            [shape.shape_type for shape in collection.shapes],
            list(shape_types),
        )
        self.assertEqual(collection.deferred_count, 0)

    def test_recovers_cardinal_and_left_right_arrow_presets(self) -> None:
        shape_types = (66, 67, 68, 69)
        officeart = OfficeArtShapeCollection(
            {shape_type: ShapeStyle() for shape_type in shape_types},
            shape_types_by_shape_id={
                shape_type: shape_type for shape_type in shape_types
            },
        )
        anchors = {
            shape_type: replace(
                _anchor(shape_type),
                anchor_cp=index,
            )
            for index, shape_type in enumerate(shape_types)
        }
        report = ConversionReport("cardinal-arrows.doc")
        collection = read_main_floating_shapes(
            anchors,
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(
            [shape.shape_type for shape in collection.shapes],
            list(shape_types),
        )
        self.assertEqual(collection.deferred_count, 0)
        self.assertFalse(report.warnings)

        office_ns = "{urn:schemas-microsoft-com:office:office}"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cardinal-arrows.docx"
            write_docx(
                Document(tuple(Paragraph((shape,)) for shape in collection.shapes)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            emitted = [
                (element.get(f"{office_ns}spt"), element.get("path"))
                for element in root.findall(f".//{V}shape")
            ]
            self.assertEqual(
                [shape_type for shape_type, _path in emitted],
                ["66", "67", "68", "69"],
            )
            self.assertTrue(all(path for _shape_type, path in emitted))

    def test_recovers_flowchart_preset_shapes(self) -> None:
        shape_types = (109, 110, 111, 114)
        officeart = OfficeArtShapeCollection(
            {shape_type: ShapeStyle() for shape_type in shape_types},
            shape_types_by_shape_id={
                shape_type: shape_type for shape_type in shape_types
            },
        )
        anchors = {
            shape_type: replace(
                _anchor(shape_type),
                anchor_cp=index,
            )
            for index, shape_type in enumerate(shape_types)
        }
        report = ConversionReport("flowchart-shapes.doc")
        collection = read_main_floating_shapes(
            anchors,
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(
            [shape.shape_type for shape in collection.shapes],
            list(shape_types),
        )
        self.assertEqual(collection.deferred_count, 0)
        self.assertFalse(report.warnings)

        office_ns = "{urn:schemas-microsoft-com:office:office}"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-shapes.docx"
            write_docx(
                Document(tuple(Paragraph((shape,)) for shape in collection.shapes)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            emitted = [
                element.get(f"{office_ns}spt")
                for element in root.findall(f".//{V}shape")
            ]
            self.assertEqual(emitted, ["109", "110", "111", "114"])

    def test_recovers_flowchart_terminator_preset(self) -> None:
        shape_id = 116
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="FF6633", line_color="993300")},
            shape_types_by_shape_id={shape_id: shape_id},
        )
        report = ConversionReport("flowchart-terminator.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].shape_type, shape_id)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-terminator.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        shape = root.find(f".//{V}shape")
        assert shape is not None
        self.assertEqual(
            shape.get("{urn:schemas-microsoft-com:office:office}spt"),
            "116",
        )
        self.assertEqual(
            shape.get("path"),
            "m3475,qx,10800,3475,21600l18125,21600qx21600,10800,18125,xe",
        )

    def test_recovers_flowchart_predefined_process_preset(self) -> None:
        shape_id = 112
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="FF6633", line_color="993300")},
            shape_types_by_shape_id={shape_id: shape_id},
        )
        report = ConversionReport("flowchart-predefined-process.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].shape_type, shape_id)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-predefined-process.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        shapetype = root.find(f".//{V}shapetype")
        shape = root.find(f".//{V}shape")
        assert shapetype is not None and shape is not None
        self.assertEqual(
            shapetype.get(f"{O}spt"),
            "112",
        )
        self.assertEqual(
            shapetype.get("path"),
            "m,l,21600r21600,l21600,xem2610,nfl2610,21600em18990,nfl18990,21600e",
        )
        self.assertEqual(shape.get("type"), "#_x0000_t112")
        path = shapetype.find(f"{V}path")
        assert path is not None
        self.assertEqual(path.get(f"{O}extrusionok"), "f")
        self.assertEqual(path.get(f"{O}connecttype"), "rect")
        self.assertEqual(path.get("textboxrect"), "2610,0,18990,21600")

    def test_recovers_flowchart_internal_storage_preset(self) -> None:
        shape_id = 113
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="FF6633", line_color="993300")},
            shape_types_by_shape_id={shape_id: shape_id},
        )
        report = ConversionReport("flowchart-internal-storage.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].shape_type, shape_id)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-internal-storage.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        shapetype = root.find(f".//{V}shapetype")
        shape = root.find(f".//{V}shape")
        assert shapetype is not None and shape is not None
        self.assertEqual(shapetype.get(f"{O}spt"), "113")
        self.assertEqual(
            shapetype.get("path"),
            "m,l,21600r21600,l21600,xem4236,nfl4236,21600em,4236nfl21600,4236e",
        )
        self.assertEqual(shape.get("type"), "#_x0000_t113")
        path = shapetype.find(f"{V}path")
        assert path is not None
        self.assertEqual(path.get(f"{O}extrusionok"), "f")
        self.assertEqual(path.get(f"{O}connecttype"), "rect")
        self.assertEqual(path.get("textboxrect"), "4236,4236,21600,21600")

    def test_recovers_flowchart_multidocument_preset(self) -> None:
        shape_id = 115
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="FF6633", line_color="993300")},
            shape_types_by_shape_id={shape_id: shape_id},
        )
        report = ConversionReport("flowchart-multidocument.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].shape_type, shape_id)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-multidocument.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        shapetype = root.find(f".//{V}shapetype")
        shape = root.find(f".//{V}shape")
        assert shapetype is not None and shape is not None
        self.assertEqual(shapetype.get(f"{O}spt"), "115")
        self.assertEqual(
            shapetype.get("path"),
            "m,20465v810,317,1620,452,2397,725c3077,21325,3790,21417,4405,21597"
            "v1620,,2202,-180,2657,-272c7580,21280,8002,21010,8455,20917"
            "v422,-135,810,-405,1327,-542c10205,20150,10657,19967,11080,19742"
            "v517,-182,970,-407,1425,-590c13087,19017,13605,18745,14255,18610"
            "v615,-180,1262,-318,1942,-408c16975,18202,17785,18022,18595,18022"
            "r,-1670l19192,16252r808,l20000,14467r722,-75l21597,14392,21597,,2972,"
            "r,1815l1532,1815r,1860l,3675,,20465xem1532,3675nfl18595,3675r,12677"
            "em2972,1815nfl20000,1815r,12652e",
        )
        self.assertEqual(shape.get("type"), "#_x0000_t115")
        path = shapetype.find(f"{V}path")
        assert path is not None
        self.assertEqual(path.get(f"{O}extrusionok"), "f")
        self.assertEqual(path.get(f"{O}connecttype"), "custom")
        self.assertEqual(
            path.get(f"{O}connectlocs"),
            "10800,0;0,10800;10800,19890;21600,10800",
        )
        self.assertEqual(path.get("textboxrect"), "0,3675,18595,18022")
        self.assertIsNone(path.get("gradientshapeok"))

    def test_recovers_flowchart_preparation_preset(self) -> None:
        shape_id = 117
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="FF6633", line_color="993300")},
            shape_types_by_shape_id={shape_id: shape_id},
        )
        report = ConversionReport("flowchart-preparation.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].shape_type, shape_id)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-preparation.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        shapetype = root.find(f".//{V}shapetype")
        shape = root.find(f".//{V}shape")
        assert shapetype is not None and shape is not None
        self.assertEqual(shapetype.get(f"{O}spt"), "117")
        self.assertEqual(
            shapetype.get("path"),
            "m4353,l17214,r4386,10800l17214,21600r-12861,l,10800xe",
        )
        self.assertEqual(shape.get("type"), "#_x0000_t117")
        path = shapetype.find(f"{V}path")
        assert path is not None
        self.assertEqual(path.get("gradientshapeok"), "t")
        self.assertEqual(path.get(f"{O}connecttype"), "rect")
        self.assertEqual(path.get("textboxrect"), "4353,0,17214,21600")
        self.assertIsNone(path.get(f"{O}extrusionok"))

    def test_recovers_flowchart_manual_input_preset(self) -> None:
        shape_id = 118
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="FF6633", line_color="993300")},
            shape_types_by_shape_id={shape_id: shape_id},
        )
        report = ConversionReport("flowchart-manual-input.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].shape_type, shape_id)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-manual-input.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        shapetype = root.find(f".//{V}shapetype")
        shape = root.find(f".//{V}shape")
        assert shapetype is not None and shape is not None
        self.assertEqual(shapetype.get(f"{O}spt"), "118")
        self.assertEqual(
            shapetype.get("path"),
            "m,4292l21600,r,21600l,21600xe",
        )
        self.assertEqual(shape.get("type"), "#_x0000_t118")
        path = shapetype.find(f"{V}path")
        assert path is not None
        self.assertEqual(path.get("gradientshapeok"), "t")
        self.assertEqual(path.get(f"{O}connecttype"), "custom")
        self.assertEqual(
            path.get(f"{O}connectlocs"),
            "10800,2146;0,10800;10800,21600;21600,10800",
        )
        self.assertEqual(path.get("textboxrect"), "0,4291,21600,21600")
        self.assertIsNone(path.get(f"{O}extrusionok"))

    def test_recovers_flowchart_manual_operation_preset(self) -> None:
        shape_id = 119
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="FF6633", line_color="993300")},
            shape_types_by_shape_id={shape_id: shape_id},
        )
        report = ConversionReport("flowchart-manual-operation.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].shape_type, shape_id)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-manual-operation.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        shapetype = root.find(f".//{V}shapetype")
        shape = root.find(f".//{V}shape")
        assert shapetype is not None and shape is not None
        self.assertEqual(shapetype.get(f"{O}spt"), "119")
        self.assertEqual(
            shapetype.get("path"),
            "m,l21600,,17240,21600r-12880,xe",
        )
        self.assertEqual(shape.get("type"), "#_x0000_t119")
        path = shapetype.find(f"{V}path")
        assert path is not None
        self.assertEqual(path.get("gradientshapeok"), "t")
        self.assertEqual(path.get(f"{O}connecttype"), "custom")
        self.assertEqual(
            path.get(f"{O}connectlocs"),
            "10800,0;2180,10800;10800,21600;19420,10800",
        )
        self.assertEqual(path.get("textboxrect"), "4321,0,17204,21600")
        self.assertIsNone(path.get(f"{O}extrusionok"))

    def test_recovers_chevron_preset_shape(self) -> None:
        shape_id = 55
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="3366ff", line_color="003399")},
            shape_types_by_shape_id={shape_id: 55},
        )
        report = ConversionReport("chevron.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].shape_type, 55)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "chevron.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            shape = root.find(f".//{V}shape")
            assert shape is not None
            self.assertEqual(
                shape.get("{urn:schemas-microsoft-com:office:office}spt"),
                "55",
            )
            self.assertIn("16200,0", shape.get("path", ""))

    def test_recovers_adjustment_formula_preset_shapes_without_deferral(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import (
            VML_PRESET_FORMULA_PATHS,
            VML_PRESET_FORMULAS,
        )

        target_types = (59, 64, 73, 84, 92, 93, 94, 183, 184)
        for shape_type in target_types:
            with self.subTest(shape_type=shape_type):
                shape_id = 100 + shape_type
                officeart = OfficeArtShapeCollection(
                    {shape_id: ShapeStyle(fill_color="3366ff", line_color="003399")},
                    shape_types_by_shape_id={shape_id: shape_type},
                )
                report = ConversionReport(f"preset-{shape_type}.doc")
                collection = read_main_floating_shapes(
                    {shape_id: replace(_anchor(shape_id))},
                    officeart,
                    report=report,
                    character_properties_at=lambda _cp: CharacterProperties(special=True),
                )
                self.assertEqual(collection.deferred_count, 0)
                self.assertFalse(report.warnings)
                self.assertEqual(collection.shapes[0].shape_type, shape_type)

                with tempfile.TemporaryDirectory() as directory:
                    destination = Path(directory) / f"preset-{shape_type}.docx"
                    write_docx(
                        Document((Paragraph((collection.shapes[0],)),)), destination
                    )
                    with zipfile.ZipFile(destination) as package:
                        root = ET.fromstring(package.read("word/document.xml"))
                    shape = root.find(f".//{V}shape")
                    assert shape is not None
                    self.assertEqual(
                        shape.get("{urn:schemas-microsoft-com:office:office}spt"),
                        str(shape_type),
                    )
                    self.assertEqual(
                        shape.get("path"), VML_PRESET_FORMULA_PATHS[shape_type]
                    )
                    if shape_type in VML_PRESET_FORMULAS:
                        adj, formulas = VML_PRESET_FORMULAS[shape_type]
                        self.assertEqual(shape.get("adj"), adj)
                        formulas_el = shape.find(f"{V}formulas")
                        assert formulas_el is not None
                        self.assertEqual(len(formulas_el.findall(f"{V}f")), len(formulas))
                    else:
                        self.assertIsNone(shape.get("adj"))
                        self.assertIsNone(shape.find(f"{V}formulas"))

    def test_recovers_can_cube_and_donut_presets(self) -> None:
        shape_types = (16, 22, 23)
        officeart = OfficeArtShapeCollection(
            {shape_type: ShapeStyle() for shape_type in shape_types},
            shape_types_by_shape_id={
                shape_type: shape_type for shape_type in shape_types
            },
        )
        anchors = {
            shape_type: replace(_anchor(shape_type), anchor_cp=index)
            for index, shape_type in enumerate(shape_types)
        }
        report = ConversionReport("can-cube-donut.doc")
        collection = read_main_floating_shapes(
            anchors,
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )
        self.assertEqual(
            [shape.shape_type for shape in collection.shapes],
            list(shape_types),
        )
        self.assertEqual(collection.deferred_count, 0)
        self.assertFalse(report.warnings)

    def test_ungroups_grouped_line_connectors_onto_parent_anchor(self) -> None:
        from doc2docx.msdoc.officeart import OfficeArtChildAnchor

        parent_id = 1000
        line_id = 1001
        parent_anchor = ShapeAnchor(
            anchor_cp=3,
            shape_id=parent_id,
            left=1000,
            top=2000,
            right=5000,
            bottom=8000,
            horizontal_relative="column",
            vertical_relative="paragraph",
            wrap_type="square",
            wrap_side="both",
            behind_text=False,
            anchor_locked=True,
        )
        child = OfficeArtChildAnchor(
            parent_shape_id=parent_id,
            group_left=0,
            group_top=0,
            group_right=1000,
            group_bottom=1000,
            left=500,
            top=100,
            right=500,
            bottom=400,
        )
        officeart = OfficeArtShapeCollection(
            {
                parent_id: ShapeStyle(fill_enabled=False, line_enabled=False),
                line_id: ShapeStyle(
                    fill_enabled=False,
                    line_enabled=True,
                    line_end_arrowhead="block",
                ),
            },
            shape_types_by_shape_id={parent_id: 0, line_id: 20},
            child_anchors_by_shape_id={line_id: child},
        )
        report = ConversionReport("grouped-lines.doc")

        collection = read_main_floating_shapes(
            {parent_id: parent_anchor},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual([shape.shape_id for shape in collection.shapes], [line_id])
        line = collection.shapes[0]
        self.assertEqual(line.shape_type, 20)
        self.assertEqual(line.anchor_cp, 3)
        self.assertEqual(line.left_twips, 3000)
        self.assertEqual(line.width_twips, 1)
        self.assertEqual(line.shape_style.line_end_arrowhead, "block")
        self.assertEqual(len(collection.shapes_at(3)), 1)
        self.assertIn(
            "GROUPED_FLOATING_LINES_UNGROUPED",
            [warning.code for warning in report.warnings],
        )

    def test_unknown_geometry_uses_exact_wrap_contour_as_fallback(self) -> None:
        shape_id = 202
        polygon = ((0, 0), (21600, 0), (10800, 21600), (0, 0))
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle()},
            wrap_polygons_by_shape_id={shape_id: polygon},
            shape_types_by_shape_id={shape_id: 202},
        )
        report = ConversionReport("custom-shape.doc")

        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(
            collection.shapes[0].geometry_path,
            "m0,0l21600,0,10800,21600,0,0xe",
        )
        self.assertEqual(
            report.warnings[0].code,
            "FLOATING_SHAPE_GEOMETRY_APPROXIMATED",
        )

    def test_notprimitive_geometry_path_is_emitted_without_deferral(self) -> None:
        shape_id = 1026
        path = "m10800,4050c15300,-5400,32850,4050,10800,16200c-11250,4050,6300,-5400,10800,4050xe"
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle()},
            geometry_paths_by_shape_id={shape_id: path},
            shape_types_by_shape_id={shape_id: 0},
        )
        report = ConversionReport("notprimitive.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual(collection.deferred_count, 0)
        self.assertEqual(collection.shapes[0].geometry_path, path)
        self.assertEqual(collection.shapes[0].shape_type, 0)
        self.assertFalse(report.warnings)

    def test_parser_and_docx_writer_emit_positioned_vml_geometry(self) -> None:
        shape = FloatingShape(
            shape_id=1026,
            shape_type=4,
            anchor_cp=0,
            left_twips=720,
            top_twips=144,
            width_twips=2160,
            height_twips=1440,
            horizontal_relative="column",
            vertical_relative="paragraph",
            wrap_type="square",
            wrap_side="both",
            behind_text=False,
            anchor_locked=True,
            rotation_degrees=-45.0,
            shape_style=ShapeStyle(
                fill_color="112233",
                fill_opacity=0x8000,
                line_color="445566",
                line_dash="dash",
                line_end_arrowhead="block",
            ),
        )
        parsed = parse_main_story(
            "\x08\r",
            ConversionReport("shape.doc"),
            floating_shape_at=lambda cp: shape if cp == 0 else None,
        )
        self.assertIs(parsed.paragraphs[0].inlines[0], shape)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "shape.docx"
            write_docx(Document((Paragraph((shape,)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))

        element = root.find(f".//{V}shape")
        assert element is not None
        self.assertEqual(element.get("fillcolor"), "#112233")
        self.assertEqual(element.get("strokecolor"), "#445566")
        self.assertIn("position:absolute", element.get("style", ""))
        self.assertIn("rotation:-45", element.get("style", ""))
        self.assertIn("m10800,0", element.get("path", ""))
        self.assertEqual(element.find(f"{V}fill").get("opacity"), "50%")  # type: ignore[union-attr]
        self.assertEqual(element.find(f"{V}stroke").get("dashstyle"), "dash")  # type: ignore[union-attr]
        self.assertEqual(element.find(f"{V}stroke").get("endarrow"), "block")  # type: ignore[union-attr]
        self.assertEqual(element.find(f"{W10}wrap").get("type"), "square")  # type: ignore[union-attr]
        self.assertIsNotNone(root.find(f".//{W}pict"))


if __name__ == "__main__":
    unittest.main()
