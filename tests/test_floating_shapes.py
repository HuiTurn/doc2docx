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


def _assert_formula_shapetype(
    test: unittest.TestCase,
    root: ET.Element,
    shape_type: int,
    *,
    shape_adj: str | None = None,
) -> ET.Element:
    from doc2docx.ooxml._vml_preset_formulas import (
        VML_PRESET_FORMULA_PATHS,
        VML_PRESET_FORMULAS,
        VML_PRESET_HANDLES,
        VML_PRESET_PATH_ATTRIBUTES,
    )

    shapetype = root.find(f".//{V}shapetype")
    shape = root.find(f".//{V}shape")
    assert shapetype is not None
    assert shape is not None
    default_adj, formulas = VML_PRESET_FORMULAS[shape_type]
    test.assertEqual(shapetype.get("id"), f"_x0000_t{shape_type}")
    test.assertEqual(shapetype.get(f"{O}spt"), str(shape_type))
    test.assertEqual(shapetype.get("path"), VML_PRESET_FORMULA_PATHS[shape_type])
    test.assertEqual(shapetype.get("adj"), default_adj)
    formulas_el = shapetype.find(f"{V}formulas")
    if formulas:
        assert formulas_el is not None
        test.assertEqual(len(formulas_el.findall(f"{V}f")), len(formulas))
    else:
        test.assertIsNone(formulas_el)
    test.assertEqual(shape.get("type"), f"#_x0000_t{shape_type}")
    test.assertIsNone(shape.get("path"))
    test.assertIsNone(shape.get(f"{O}spt"))
    test.assertIsNone(shape.find(f"{V}formulas"))
    test.assertEqual(shape.get("adj"), shape_adj)
    path_attrs = VML_PRESET_PATH_ATTRIBUTES.get(shape_type)
    if path_attrs and "limo" in path_attrs:
        path_el = shapetype.find(f"{V}path")
        assert path_el is not None
        test.assertEqual(path_el.get("limo"), path_attrs["limo"])
    expected_handles = VML_PRESET_HANDLES.get(shape_type)
    if expected_handles:
        handles_el = shapetype.find(f"{V}handles")
        assert handles_el is not None
        actual = [dict(h.attrib) for h in handles_el.findall(f"{V}h")]
        test.assertEqual(actual, expected_handles)
    return shape


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
            ["GROUPED_FLOATING_FRAME_FLATTENED", "FLOATING_SHAPE_STYLE_APPROXIMATED"],
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

    def test_recovers_arrow_line_and_plaque_presets(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import VML_PRESET_FORMULA_PATHS

        shape_types = (13, 14, 15, 20, 21)
        officeart = OfficeArtShapeCollection(
            {shape_type: ShapeStyle() for shape_type in shape_types},
            shape_types_by_shape_id={
                shape_type: shape_type for shape_type in shape_types
            },
            adjustments_by_shape_id={21: (2700,)},
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
        self.assertEqual(collection.shapes[-1].geometry_adj, "2700")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "preset-shapes.docx"
            write_docx(
                Document((Paragraph((collection.shapes[-1],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 21, shape_adj="2700")

    def test_recovers_cardinal_and_left_right_arrow_presets(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import (
            VML_PRESET_FORMULA_PATHS,
            VML_PRESET_FORMULAS,
        )

        shape_types = (66, 67, 68, 69)
        officeart = OfficeArtShapeCollection(
            {shape_type: ShapeStyle() for shape_type in shape_types},
            shape_types_by_shape_id={
                shape_type: shape_type for shape_type in shape_types
            },
            adjustments_by_shape_id={
                66: (8100,),
                67: (10800,),
                68: (10800,),
                69: (8100,),
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

        expected_adj = {66: "8100", 67: "10800", 68: "10800", 69: "8100"}
        with tempfile.TemporaryDirectory() as directory:
            for shape in collection.shapes:
                destination = Path(directory) / f"arrow-{shape.shape_type}.docx"
                write_docx(Document((Paragraph((shape,)),)), destination)
                with zipfile.ZipFile(destination) as package:
                    root = ET.fromstring(package.read("word/document.xml"))
                # Short adj inherits remaining slots from <v:shapetype>.
                _assert_formula_shapetype(
                    self,
                    root,
                    shape.shape_type,
                    shape_adj=expected_adj[shape.shape_type],
                )

    def test_recovers_flowchart_preset_shapes(self) -> None:
        shape_types = (109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 177)
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

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-shapes.docx"
            write_docx(
                Document(tuple(Paragraph((shape,)) for shape in collection.shapes)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            shapes = root.findall(f".//{V}shape")
            shapetypes = root.findall(f".//{V}shapetype")
            self.assertEqual(
                [element.get("type") for element in shapes],
                [f"#_x0000_t{value}" for value in shape_types],
            )
            self.assertEqual(
                {element.get(f"{O}spt") for element in shapetypes},
                {str(value) for value in shape_types},
            )
            terminator = next(
                element
                for element in shapetypes
                if element.get(f"{O}spt") == "116"
            )
            self.assertEqual(
                terminator.get("path"),
                "m3475,qx,10800,3475,21600l18125,21600qx21600,10800,18125,xe",
            )
            self.assertEqual(
                terminator.find(f"{V}stroke").get("joinstyle"),
                "miter",
            )

    def test_recovers_chevron_preset_shape(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import VML_PRESET_FORMULA_PATHS

        shape_id = 55
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="3366ff", line_color="003399")},
            shape_types_by_shape_id={shape_id: 55},
            adjustments_by_shape_id={shape_id: (13500,)},
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
        self.assertEqual(collection.shapes[0].geometry_adj, "13500")
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "chevron.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 55, shape_adj="13500")

    def test_recovers_adjustment_formula_preset_shapes_without_deferral(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import (
            VML_PRESET_FORMULA_PATHS,
            VML_PRESET_FORMULAS,
        )

        target_types = (
            16,
            22,
            23,
            53,
            54,
            55,
            59,
            60,
            64,
            65,
            70,
            73,
            77,
            78,
            84,
            92,
            93,
            94,
            96,
            102,
            103,
            104,
            105,
            183,
            184,
            189,
        )
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
                    if shape_type in VML_PRESET_FORMULAS:
                        _assert_formula_shapetype(self, root, shape_type)
                    else:
                        shape = root.find(f".//{V}shape")
                        assert shape is not None
                        self.assertEqual(
                            shape.get(f"{O}spt"),
                            str(shape_type),
                        )
                        self.assertEqual(
                            shape.get("path"), VML_PRESET_FORMULA_PATHS[shape_type]
                        )
                        self.assertIsNone(shape.get("adj"))
                        self.assertIsNone(shape.find(f"{V}formulas"))

    def test_recovers_curved_arrow_formula_presets(self) -> None:
        shape_types = (102, 103, 104, 105)
        officeart = OfficeArtShapeCollection(
            {shape_type: ShapeStyle() for shape_type in shape_types},
            shape_types_by_shape_id={
                shape_type: shape_type for shape_type in shape_types
            },
            adjustments_by_shape_id={
                102: (10800, 18900, 17550),
                103: (10800, 18900, 4050),
            },
        )
        anchors = {
            shape_type: replace(_anchor(shape_type), anchor_cp=index)
            for index, shape_type in enumerate(shape_types)
        }
        report = ConversionReport("curved-arrows.doc")
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
        self.assertEqual(collection.shapes[0].geometry_adj, "10800,18900,17550")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "curved-right.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)),
                destination,
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(
                self, root, 102, shape_adj="10800,18900,17550"
            )

    def test_recovers_up_down_arrow_formula_preset(self) -> None:
        shape_id = 70
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="3366ff", line_color="003399")},
            shape_types_by_shape_id={shape_id: 70},
            adjustments_by_shape_id={shape_id: (None, 10800)},
        )
        report = ConversionReport("up-down-arrow.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )
        self.assertEqual(collection.deferred_count, 0)
        self.assertFalse(report.warnings)
        self.assertEqual(collection.shapes[0].geometry_adj, ",10800")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "up-down-arrow.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            # Sparse OfficeArt adj materializes onto shapetype defaults.
            _assert_formula_shapetype(self, root, 70, shape_adj=",10800")

    def test_recovers_smile_face_formula_preset(self) -> None:
        shape_id = 96
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="ffff00", line_color="000000")},
            shape_types_by_shape_id={shape_id: 96},
        )
        report = ConversionReport("smile-face.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )
        self.assertEqual(collection.deferred_count, 0)
        self.assertFalse(report.warnings)
        self.assertIsNone(collection.shapes[0].geometry_adj)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "smile-face.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 96)
            shapetype = root.find(f".//{V}shapetype")
            assert shapetype is not None
            self.assertIn("xnfem", shapetype.get("path", ""))

    def test_recovers_ribbon_formula_preset(self) -> None:
        shape_id = 78
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="3366ff", line_color="003399")},
            shape_types_by_shape_id={shape_id: 78},
            adjustments_by_shape_id={shape_id: (14035, None, 17550)},
        )
        report = ConversionReport("ribbon.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )
        self.assertEqual(collection.deferred_count, 0)
        self.assertFalse(report.warnings)
        self.assertEqual(collection.shapes[0].geometry_adj, "14035,,17550")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "ribbon.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 78, shape_adj="14035,,17550")

    def test_recovers_arrow_callout_formula_presets(self) -> None:
        officeart = OfficeArtShapeCollection(
            {
                53: ShapeStyle(fill_color="3366ff", line_color="003399"),
                60: ShapeStyle(fill_color="ff6633", line_color="993300"),
            },
            shape_types_by_shape_id={53: 53, 60: 60},
            adjustments_by_shape_id={53: (None, 3600)},
        )
        anchors = {
            53: replace(_anchor(53), anchor_cp=0),
            60: replace(_anchor(60), anchor_cp=1),
        }
        report = ConversionReport("arrow-callouts.doc")
        collection = read_main_floating_shapes(
            anchors,
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )
        self.assertEqual(
            [shape.shape_type for shape in collection.shapes],
            [53, 60],
        )
        self.assertEqual(collection.deferred_count, 0)
        self.assertFalse(report.warnings)
        self.assertEqual(collection.shapes[0].geometry_adj, ",3600")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bent-callout.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 53, shape_adj=",3600")

    def test_recovers_remaining_discovery_formula_presets(self) -> None:
        cases = (
            (65, (18000,), "18000"),
            (77, (7565, None, 4050), "7565,,4050"),
            (189, (), None),
        )
        for shape_type, adjustments, expected_adj in cases:
            with self.subTest(shape_type=shape_type):
                officeart = OfficeArtShapeCollection(
                    {shape_type: ShapeStyle()},
                    shape_types_by_shape_id={shape_type: shape_type},
                    adjustments_by_shape_id=(
                        {shape_type: adjustments} if adjustments else {}
                    ),
                )
                report = ConversionReport(f"preset-{shape_type}.doc")
                collection = read_main_floating_shapes(
                    {shape_type: _anchor(shape_type)},
                    officeart,
                    report=report,
                    character_properties_at=lambda _cp: CharacterProperties(
                        special=True
                    ),
                )
                self.assertEqual(collection.deferred_count, 0)
                self.assertFalse(report.warnings)
                self.assertEqual(collection.shapes[0].geometry_adj, expected_adj)
                with tempfile.TemporaryDirectory() as directory:
                    destination = Path(directory) / f"preset-{shape_type}.docx"
                    write_docx(
                        Document((Paragraph((collection.shapes[0],)),)),
                        destination,
                    )
                    with zipfile.ZipFile(destination) as package:
                        root = ET.fromstring(package.read("word/document.xml"))
                    _assert_formula_shapetype(
                        self, root, shape_type, shape_adj=expected_adj
                    )

    def test_recovers_bracket_and_brace_formula_presets(self) -> None:
        shape_types = (85, 86, 87, 88, 185, 186)
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
        report = ConversionReport("brackets.doc")
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
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "left-bracket.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 85)

    def test_recovers_explosion_path_only_presets(self) -> None:
        shape_types = (71, 72)
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
        report = ConversionReport("explosions.doc")
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
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "explosion1.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 71)

    def test_recovers_action_button_formula_presets(self) -> None:
        shape_types = tuple(range(190, 201))
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
        report = ConversionReport("action-buttons.doc")
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
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "action-home.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 190)

    def test_recovers_remaining_flowchart_formula_presets(self) -> None:
        shape_types = (122, 125, 126, 127, 128, 130, 131, 132, 133, 134, 176)
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
        report = ConversionReport("flowchart-remaining.doc")
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
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flowchart-sort.docx"
            # spt 126 is the sort/merge-like path-only flowchart shape.
            shape = next(s for s in collection.shapes if s.shape_type == 126)
            write_docx(Document((Paragraph((shape,)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 126)

    def test_recovers_math_and_misc_leftover_presets(self) -> None:
        shape_types = (57, 80, 81, 82, 97, 107, 108, 129, 187)
        officeart = OfficeArtShapeCollection(
            {shape_type: ShapeStyle() for shape_type in shape_types},
            shape_types_by_shape_id={
                shape_type: shape_type for shape_type in shape_types
            },
            adjustments_by_shape_id={57: (3038,)},
        )
        anchors = {
            shape_type: replace(_anchor(shape_type), anchor_cp=index)
            for index, shape_type in enumerate(shape_types)
        }
        report = ConversionReport("math-leftovers.doc")
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
        self.assertEqual(collection.shapes[0].geometry_adj, "3038")
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "no-symbol.docx"
            write_docx(Document((Paragraph((collection.shapes[0],)),)), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 57, shape_adj="3038")

    def test_recovers_can_cube_and_donut_presets(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import VML_PRESET_FORMULA_PATHS

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

        with tempfile.TemporaryDirectory() as directory:
            for shape in collection.shapes:
                destination = Path(directory) / f"shape-{shape.shape_type}.docx"
                write_docx(Document((Paragraph((shape,)),)), destination)
                with zipfile.ZipFile(destination) as package:
                    root = ET.fromstring(package.read("word/document.xml"))
                # Default adj lives on shapetype; shape omits adj when unchanged.
                _assert_formula_shapetype(self, root, shape.shape_type)

    def test_emits_sparse_adjust2_value_for_modern_can_preset(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import VML_PRESET_FORMULA_PATHS

        shape_id = 1026
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="3366ff")},
            shape_types_by_shape_id={shape_id: 54},
            adjustments_by_shape_id={shape_id: (None, 14040)},
        )
        report = ConversionReport("modern-can.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )
        self.assertEqual(collection.shapes[0].shape_type, 54)
        self.assertEqual(collection.shapes[0].geometry_adj, ",14040")
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "modern-can.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)), destination
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            # Sparse adj inherits #0 from shapetype default 5400,18900.
            _assert_formula_shapetype(self, root, 54, shape_adj=",14040")

    def test_emits_officeart_adjust_value_on_pentagon_formula_path(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import VML_PRESET_FORMULA_PATHS

        shape_id = 1026
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="3366ff")},
            shape_types_by_shape_id={shape_id: 15},
            adjustments_by_shape_id={shape_id: (13500,)},
        )
        report = ConversionReport("pentagon-adj.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )
        self.assertEqual(collection.shapes[0].geometry_adj, "13500")
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "pentagon-adj.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)), destination
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 15, shape_adj="13500")

    def test_emits_officeart_adjust_value_on_donut_formula_path(self) -> None:
        from doc2docx.ooxml._vml_preset_formulas import VML_PRESET_FORMULA_PATHS

        shape_id = 1026
        officeart = OfficeArtShapeCollection(
            {shape_id: ShapeStyle(fill_color="3366ff")},
            shape_types_by_shape_id={shape_id: 23},
            adjustments_by_shape_id={shape_id: (4050,)},
        )
        report = ConversionReport("donut-adj.doc")
        collection = read_main_floating_shapes(
            {shape_id: _anchor(shape_id)},
            officeart,
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )
        self.assertEqual(collection.shapes[0].geometry_adj, "4050")
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "donut-adj.docx"
            write_docx(
                Document((Paragraph((collection.shapes[0],)),)), destination
            )
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
            _assert_formula_shapetype(self, root, 23, shape_adj="4050")

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
        shapetype = root.find(f".//{V}shapetype")
        assert shapetype is not None
        self.assertEqual(element.get("fillcolor"), "#112233")
        self.assertEqual(element.get("strokecolor"), "#445566")
        self.assertIn("position:absolute", element.get("style", ""))
        self.assertIn("rotation:-45", element.get("style", ""))
        self.assertEqual(element.get("type"), "#_x0000_t4")
        self.assertIn("m10800,", shapetype.get("path", ""))
        self.assertEqual(element.find(f"{V}fill").get("opacity"), "50%")  # type: ignore[union-attr]
        self.assertEqual(element.find(f"{V}stroke").get("dashstyle"), "dash")  # type: ignore[union-attr]
        self.assertEqual(element.find(f"{V}stroke").get("endarrow"), "block")  # type: ignore[union-attr]
        self.assertEqual(element.find(f"{W10}wrap").get("type"), "square")  # type: ignore[union-attr]
        self.assertIsNotNone(root.find(f".//{W}pict"))


if __name__ == "__main__":
    unittest.main()
