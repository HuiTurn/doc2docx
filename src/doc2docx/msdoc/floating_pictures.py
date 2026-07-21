"""Main-story floating raster pictures from PlcSpaMom and OfficeArt."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, replace

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import CharacterProperties, FloatingPicture
from .header_textboxes import ShapeAnchor
from .officeart import OfficeArtShapeCollection


@dataclass(slots=True, frozen=True)
class FloatingPictureCollection:
    pictures: tuple[FloatingPicture, ...] = ()
    by_anchor_cp: Mapping[int, FloatingPicture] | None = None
    deferred_count: int = 0
    non_picture_shape_count: int = 0

    def picture_at(self, cp: int) -> FloatingPicture | None:
        return (self.by_anchor_cp or {}).get(cp)


def read_main_floating_pictures(
    anchors_by_shape_id: Mapping[int, ShapeAnchor],
    officeart: OfficeArtShapeCollection,
    *,
    excluded_shape_ids: Set[int] | frozenset[int] = frozenset(),
    first_picture_id: int = 1,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties],
) -> FloatingPictureCollection:
    """Associate main-story shape anchors with supported OfficeArt BLIPs."""

    if first_picture_id <= 0:
        raise ValueError("first_picture_id must be positive")
    pictures: list[FloatingPicture] = []
    by_anchor_cp: dict[int, FloatingPicture] = {}
    deferred_count = 0
    non_picture_shape_count = 0
    approximated_wrap_count = 0
    for anchor in sorted(
        anchors_by_shape_id.values(),
        key=lambda value: value.anchor_cp,
    ):
        if anchor.shape_id in excluded_shape_ids:
            continue
        image = officeart.image_at(anchor.shape_id)
        if image is None:
            unsupported_type = officeart.unsupported_image_type_at(anchor.shape_id)
            if unsupported_type is not None:
                deferred_count += 1
                report.warning(
                    "FLOATING_PICTURE_FORMAT_DEFERRED",
                    "a floating picture uses an unsupported OfficeArt BLIP format",
                    location=SourceLocation(
                        story="main",
                        cp_start=anchor.anchor_cp,
                        cp_end=anchor.anchor_cp + 1,
                    ),
                    shape_id=anchor.shape_id,
                    record_type=f"0x{unsupported_type:04X}",
                )
            else:
                non_picture_shape_count += 1
            continue
        properties = character_properties_at(anchor.anchor_cp)
        if properties.special is not True:
            raise InvalidWordDocument(
                f"PlcSpaMom picture anchor at CP {anchor.anchor_cp} has no sprmCFSpec"
            )
        if anchor.anchor_cp in by_anchor_cp:
            raise InvalidWordDocument(
                f"multiple floating pictures use main-story CP {anchor.anchor_cp}"
            )
        if anchor.wrap_type in ("tight", "through"):
            approximated_wrap_count += 1
        picture = FloatingPicture(
            picture_id=first_picture_id + len(pictures),
            shape_id=anchor.shape_id,
            anchor_cp=anchor.anchor_cp,
            data=image.data,
            extension=image.extension,
            content_type=image.content_type,
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
            properties=replace(
                properties,
                special=None,
                picture_location=None,
                picture_is_binary=None,
            ),
        )
        pictures.append(picture)
        by_anchor_cp[anchor.anchor_cp] = picture

    if approximated_wrap_count:
        report.warning(
            "FLOATING_PICTURE_WRAP_APPROXIMATED",
            "tight/through picture wrap polygons were approximated as square wrapping",
            location=SourceLocation(story="main"),
            picture_count=approximated_wrap_count,
        )
    return FloatingPictureCollection(
        pictures=tuple(pictures),
        by_anchor_cp=by_anchor_cp,
        deferred_count=deferred_count,
        non_picture_shape_count=non_picture_shape_count,
    )
