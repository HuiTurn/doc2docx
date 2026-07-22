"""Positioned OfficeArt preset shapes from main and header stories."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, replace

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import CharacterProperties, FloatingShape
from .header_textboxes import ShapeAnchor
from .officeart import OfficeArtChildAnchor, OfficeArtShapeCollection


# These OfficeArt presets have stable VML equivalents or bounded paths.
_SUPPORTED_SHAPE_TYPES = frozenset((*range(1, 16), 20, 21))
# Straight lines and line-like NotPrimitive connectors from grouped diagrams.
_GROUPED_LINE_SHAPE_TYPES = frozenset((20,))


@dataclass(slots=True, frozen=True)
class FloatingShapeCollection:
    shapes: tuple[FloatingShape, ...] = ()
    by_anchor_cp: Mapping[int, tuple[FloatingShape, ...]] | None = None
    deferred_count: int = 0

    def shape_at(self, cp: int) -> FloatingShape | None:
        shapes = (self.by_anchor_cp or {}).get(cp, ())
        return shapes[0] if shapes else None

    def shapes_at(self, cp: int) -> tuple[FloatingShape, ...]:
        return (self.by_anchor_cp or {}).get(cp, ())


def _is_line_like(
    shape_type: int,
    *,
    style_line_enabled: bool,
    style_fill_enabled: bool,
) -> bool:
    if shape_type in _GROUPED_LINE_SHAPE_TYPES:
        return True
    # Grouped flowchart connectors are often stored as NotPrimitive with stroke
    # enabled and fill disabled.
    return shape_type == 0 and style_line_enabled and not style_fill_enabled


def _resolve_grouped_anchor(
    shape_id: int,
    anchors_by_shape_id: Mapping[int, ShapeAnchor],
    child_anchor_at: Callable[[int], OfficeArtChildAnchor | None],
    *,
    seen: frozenset[int] = frozenset(),
) -> ShapeAnchor | None:
    direct = anchors_by_shape_id.get(shape_id)
    if direct is not None:
        return direct
    if shape_id in seen:
        return None
    child = child_anchor_at(shape_id)
    if child is None:
        return None
    parent = _resolve_grouped_anchor(
        child.parent_shape_id,
        anchors_by_shape_id,
        child_anchor_at,
        seen=seen | {shape_id},
    )
    if parent is None:
        return None
    group_width = child.group_right - child.group_left
    group_height = child.group_bottom - child.group_top
    if group_width == 0 or group_height == 0:
        return None
    parent_width = parent.right - parent.left
    parent_height = parent.bottom - parent.top

    def scale_x(value: int) -> int:
        return parent.left + round(
            (value - child.group_left) * parent_width / group_width
        )

    def scale_y(value: int) -> int:
        return parent.top + round(
            (value - child.group_top) * parent_height / group_height
        )

    left, right = sorted((scale_x(child.left), scale_x(child.right)))
    top, bottom = sorted((scale_y(child.top), scale_y(child.bottom)))
    return ShapeAnchor(
        anchor_cp=parent.anchor_cp,
        shape_id=shape_id,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        horizontal_relative=parent.horizontal_relative,
        vertical_relative=parent.vertical_relative,
        wrap_type=parent.wrap_type,
        wrap_side=parent.wrap_side,
        behind_text=parent.behind_text,
        anchor_locked=parent.anchor_locked,
    )


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
    by_anchor_cp_lists: dict[int, list[FloatingShape]] = {}
    deferred_types: dict[int, int] = {}
    approximated_style_count = 0
    approximated_geometry_count = 0
    ungrouped_line_count = 0
    emitted_shape_ids: set[int] = set()
    resolved_anchors: dict[int, ShapeAnchor] = dict(anchors_by_shape_id)

    def emit(shape: FloatingShape) -> None:
        shapes.append(shape)
        by_anchor_cp_lists.setdefault(shape.anchor_cp, []).append(shape)
        emitted_shape_ids.add(shape.shape_id)

    for shape_id, child in officeart.child_anchors_by_shape_id.items():
        if shape_id in excluded_shape_ids or shape_id in resolved_anchors:
            continue
        shape_type = officeart.shape_type_at(shape_id) or 0
        style = officeart.style_at(shape_id)
        if style is None:
            continue
        if not _is_line_like(
            shape_type,
            style_line_enabled=style.line_enabled,
            style_fill_enabled=style.fill_enabled,
        ):
            continue
        if officeart.image_at(shape_id) is not None:
            continue
        resolved = _resolve_grouped_anchor(
            shape_id,
            resolved_anchors,
            officeart.child_anchor_at,
        )
        if resolved is None:
            continue
        resolved_anchors[shape_id] = resolved
        ungrouped_line_count += 1

    for anchor in sorted(
        resolved_anchors.values(),
        key=lambda value: (value.anchor_cp, value.shape_id),
    ):
        if anchor.shape_id in excluded_shape_ids or anchor.shape_id in emitted_shape_ids:
            continue
        if officeart.image_at(anchor.shape_id) is not None:
            continue
        absolute_cp = anchor_story_cp_start + anchor.anchor_cp
        shape_type = officeart.shape_type_at(anchor.shape_id) or 0
        geometry_path = None
        style = officeart.style_at(anchor.shape_id)
        line_like = style is not None and _is_line_like(
            shape_type,
            style_line_enabled=style.line_enabled,
            style_fill_enabled=style.fill_enabled,
        )
        if shape_type not in _SUPPORTED_SHAPE_TYPES and not line_like:
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
        elif line_like and shape_type not in _SUPPORTED_SHAPE_TYPES:
            # Emit NotPrimitive stroke-only connectors with the straight-line path.
            shape_type = 20
        properties = character_properties_at(absolute_cp)
        if properties.special is not True:
            # Grouped children inherit the parent group's shape-character CP; the
            # character may already be validated for the parent Spa entry.
            if anchor.shape_id not in officeart.child_anchors_by_shape_id:
                raise InvalidWordDocument(
                    f"{spa_structure} shape anchor at CP {anchor.anchor_cp} "
                    "has no sprmCFSpec"
                )
        shape_style = style
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
        emit(shape)

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
    if ungrouped_line_count:
        report.warning(
            "GROUPED_FLOATING_LINES_UNGROUPED",
            "grouped OfficeArt line connectors were positioned as independent shapes",
            location=SourceLocation(story=anchor_story_name),
            shape_count=ungrouped_line_count,
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
        {
            cp: tuple(items)
            for cp, items in by_anchor_cp_lists.items()
        },
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
