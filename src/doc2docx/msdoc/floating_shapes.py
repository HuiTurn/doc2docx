"""Positioned OfficeArt preset shapes from main and header stories."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, replace

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import CharacterProperties, FloatingShape
from .header_textboxes import ShapeAnchor
from .officeart import OfficeArtShapeCollection


# These OfficeArt presets have stable VML equivalents or bounded paths.
_SUPPORTED_SHAPE_TYPES = frozenset((*range(1, 16), 20, 21))


@dataclass(slots=True, frozen=True)
class FloatingShapeCollection:
    shapes: tuple[FloatingShape, ...] = ()
    by_anchor_cp: Mapping[int, FloatingShape] | None = None
    deferred_count: int = 0

    def shape_at(self, cp: int) -> FloatingShape | None:
        return (self.by_anchor_cp or {}).get(cp)


def _read_floating_shapes(
    anchors_by_shape_id: Mapping[int, ShapeAnchor],
    officeart: OfficeArtShapeCollection,
    *,
    anchor_story_cp_start: int,
    anchor_story_name: str,
    spa_structure: str,
    excluded_shape_ids: Set[int] | frozenset[int],
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties],
) -> FloatingShapeCollection:
    shapes: list[FloatingShape] = []
    by_anchor_cp: dict[int, FloatingShape] = {}
    deferred_types: dict[int, int] = {}
    approximated_style_count = 0
    approximated_geometry_count = 0
    for anchor in sorted(
        anchors_by_shape_id.values(),
        key=lambda value: value.anchor_cp,
    ):
        if anchor.shape_id in excluded_shape_ids:
            continue
        if officeart.image_at(anchor.shape_id) is not None:
            continue
        absolute_cp = anchor_story_cp_start + anchor.anchor_cp
        shape_type = officeart.shape_type_at(anchor.shape_id) or 0
        geometry_path = None
        if shape_type not in _SUPPORTED_SHAPE_TYPES:
            polygon = officeart.wrap_polygon_at(anchor.shape_id)
            if len(polygon) < 3:
                deferred_types[shape_type or 0] = (
                    deferred_types.get(shape_type or 0, 0) + 1
                )
                continue
            geometry_path = (
                f"m{polygon[0][0]},{polygon[0][1]}l"
                + ",".join(f"{x},{y}" for x, y in polygon[1:])
                + "xe"
            )
            approximated_geometry_count += 1
        properties = character_properties_at(absolute_cp)
        if properties.special is not True:
            raise InvalidWordDocument(
                f"{spa_structure} shape anchor at CP {anchor.anchor_cp} "
                "has no sprmCFSpec"
            )
        if absolute_cp in by_anchor_cp:
            raise InvalidWordDocument(
                f"multiple floating shapes use {anchor_story_name} CP "
                f"{anchor.anchor_cp}"
            )
        shape_style = officeart.style_at(anchor.shape_id)
        if shape_style is not None and shape_style.approximated:
            approximated_style_count += 1
        shape = FloatingShape(
            shape_id=anchor.shape_id,
            shape_type=shape_type,
            anchor_cp=absolute_cp,
            left_twips=anchor.left,
            top_twips=anchor.top,
            width_twips=max(anchor.right - anchor.left, 1),
            height_twips=max(anchor.bottom - anchor.top, 1),
            horizontal_relative=anchor.horizontal_relative,
            vertical_relative=anchor.vertical_relative,
            wrap_type=anchor.wrap_type,
            wrap_side=anchor.wrap_side,
            behind_text=anchor.behind_text,
            anchor_locked=anchor.anchor_locked,
            flip_horizontal=officeart.is_horizontally_flipped(anchor.shape_id),
            flip_vertical=officeart.is_vertically_flipped(anchor.shape_id),
            rotation_degrees=officeart.rotation_at(anchor.shape_id),
            geometry_path=geometry_path,
            shape_style=shape_style,
            properties=replace(
                properties,
                special=None,
                picture_location=None,
                picture_is_binary=None,
            ),
        )
        shapes.append(shape)
        by_anchor_cp[absolute_cp] = shape

    if deferred_types:
        report.warning(
            "FLOATING_SHAPE_TYPES_DEFERRED",
            "some OfficeArt shape geometries do not yet have safe VML equivalents",
            location=SourceLocation(story=anchor_story_name),
            shape_count=sum(deferred_types.values()),
            shape_types=[
                f"0x{value:03X}" for value in sorted(deferred_types)
            ],
        )
    if approximated_style_count:
        report.warning(
            "FLOATING_SHAPE_STYLE_APPROXIMATED",
            "some advanced OfficeArt shape effects were reduced to basic fill and line styling",
            location=SourceLocation(story=anchor_story_name),
            shape_count=approximated_style_count,
        )
    if approximated_geometry_count:
        report.warning(
            "FLOATING_SHAPE_GEOMETRY_APPROXIMATED",
            "unsupported OfficeArt geometry was reconstructed from its exact wrap contour",
            location=SourceLocation(story=anchor_story_name),
            shape_count=approximated_geometry_count,
        )
    return FloatingShapeCollection(
        tuple(shapes),
        by_anchor_cp,
        sum(deferred_types.values()),
    )


def read_main_floating_shapes(
    anchors_by_shape_id: Mapping[int, ShapeAnchor],
    officeart: OfficeArtShapeCollection,
    *,
    excluded_shape_ids: Set[int] | frozenset[int] = frozenset(),
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties],
) -> FloatingShapeCollection:
    return _read_floating_shapes(
        anchors_by_shape_id,
        officeart,
        anchor_story_cp_start=0,
        anchor_story_name="main",
        spa_structure="PlcSpaMom",
        excluded_shape_ids=excluded_shape_ids,
        report=report,
        character_properties_at=character_properties_at,
    )


def read_header_floating_shapes(
    anchors_by_shape_id: Mapping[int, ShapeAnchor],
    officeart: OfficeArtShapeCollection,
    *,
    header_story_cp_start: int,
    excluded_shape_ids: Set[int] | frozenset[int] = frozenset(),
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties],
) -> FloatingShapeCollection:
    return _read_floating_shapes(
        anchors_by_shape_id,
        officeart,
        anchor_story_cp_start=header_story_cp_start,
        anchor_story_name="headers",
        spa_structure="PlcSpaHdr",
        excluded_shape_ids=excluded_shape_ids,
        report=report,
        character_properties_at=character_properties_at,
    )
