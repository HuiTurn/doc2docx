"""Minimal OfficeArt drawing and shape-property parsing for Word documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import struct

from ..errors import InvalidWordDocument
from ..model import ShapeStyle


_DGG_CONTAINER = 0xF000
_DG_CONTAINER = 0xF002
_SP_CONTAINER = 0xF004
_FSP = 0xF00A
_OPTION_RECORDS = (0xF00B, 0xF121, 0xF122)
_MAX_RECORD_DEPTH = 32


@dataclass(slots=True, frozen=True)
class OfficeArtShapeCollection:
    by_shape_id: Mapping[int, ShapeStyle]

    def style_at(self, shape_id: int) -> ShapeStyle | None:
        return self.by_shape_id.get(shape_id)


@dataclass(slots=True, frozen=True)
class _Record:
    version: int
    instance: int
    record_type: int
    payload_start: int
    payload_end: int
    children: tuple["_Record", ...] = ()


@dataclass(slots=True, frozen=True)
class _Property:
    value: int
    is_blip: bool
    is_complex: bool


def _read_record(
    data: memoryview,
    position: int,
    limit: int,
    *,
    depth: int = 0,
) -> tuple[_Record, int]:
    if depth > _MAX_RECORD_DEPTH:
        raise InvalidWordDocument("OfficeArt record nesting is too deep")
    if position < 0 or position > limit - 8:
        raise InvalidWordDocument("OfficeArt record header is truncated")
    version_instance, record_type, record_length = struct.unpack_from(
        "<HHI", data, position
    )
    version = version_instance & 0x000F
    instance = version_instance >> 4
    payload_start = position + 8
    payload_end = payload_start + record_length
    if record_type < 0xF000 or payload_end > limit:
        raise InvalidWordDocument(
            f"OfficeArt record 0x{record_type:04X} exceeds its container"
        )
    children: list[_Record] = []
    if version == 0x000F:
        child_position = payload_start
        while child_position < payload_end:
            child, child_position = _read_record(
                data,
                child_position,
                payload_end,
                depth=depth + 1,
            )
            children.append(child)
        if child_position != payload_end:
            raise InvalidWordDocument("OfficeArt container has trailing bytes")
    return (
        _Record(
            version,
            instance,
            record_type,
            payload_start,
            payload_end,
            tuple(children),
        ),
        payload_end,
    )


def _read_properties(
    data: memoryview,
    record: _Record,
) -> dict[int, _Property]:
    if record.record_type not in _OPTION_RECORDS or record.version != 0x0003:
        raise InvalidWordDocument("invalid OfficeArt property table record")
    entries_end = record.payload_start + record.instance * 6
    if entries_end > record.payload_end:
        raise InvalidWordDocument("OfficeArt property table entries are truncated")
    properties: dict[int, _Property] = {}
    complex_size = 0
    for index in range(record.instance):
        raw_identifier, value = struct.unpack_from(
            "<HI", data, record.payload_start + index * 6
        )
        identifier = raw_identifier & 0x3FFF
        if identifier in properties:
            raise InvalidWordDocument(
                f"OfficeArt property table repeats property 0x{identifier:04X}"
            )
        is_complex = bool(raw_identifier & 0x8000)
        if is_complex:
            complex_size += value
        properties[identifier] = _Property(
            value=value,
            is_blip=bool(raw_identifier & 0x4000),
            is_complex=is_complex,
        )
    if entries_end + complex_size != record.payload_end:
        raise InvalidWordDocument(
            "OfficeArt complex property data does not match its table"
        )
    return properties


def _option_properties(
    data: memoryview,
    records: tuple[_Record, ...],
) -> dict[int, _Property]:
    properties: dict[int, _Property] = {}
    for record in records:
        if record.record_type in _OPTION_RECORDS:
            properties.update(_read_properties(data, record))
    return properties


def _simple_property(
    properties: Mapping[int, _Property],
    identifier: int,
    default: int,
) -> tuple[int, bool]:
    value = properties.get(identifier)
    if value is None:
        return default, False
    if value.is_blip or value.is_complex:
        return default, True
    return value.value, False


def _boolean_property(
    properties: Mapping[int, _Property],
    identifier: int,
    bit: int,
    default: bool,
) -> tuple[bool, bool]:
    value, approximated = _simple_property(properties, identifier, 0)
    if approximated:
        return default, True
    if not value & (1 << (16 + bit)):
        return default, False
    return bool(value & (1 << bit)), False


def _color_property(
    properties: Mapping[int, _Property],
    identifier: int,
    default: str,
) -> tuple[str, bool]:
    value, approximated = _simple_property(properties, identifier, 0)
    if approximated:
        return default, True
    entry = properties.get(identifier)
    if entry is None or value >> 24 == 0xFF:
        return default, False
    if value >> 24:
        # System, scheme, and palette colors require host palette state that is
        # outside this first OfficeArt subset.
        return default, True
    return (
        f"{value & 0xFF:02X}{(value >> 8) & 0xFF:02X}"
        f"{(value >> 16) & 0xFF:02X}",
        False,
    )


def _bounded_property(
    properties: Mapping[int, _Property],
    identifier: int,
    default: int,
    maximum: int,
    label: str,
) -> tuple[int, bool]:
    value, approximated = _simple_property(properties, identifier, default)
    if value > maximum:
        raise InvalidWordDocument(f"OfficeArt {label} exceeds its valid range")
    return value, approximated


def _shape_style(properties: Mapping[int, _Property]) -> ShapeStyle:
    approximated = False
    fill_enabled, lossy = _boolean_property(properties, 0x01BF, 4, True)
    approximated |= lossy
    line_enabled, lossy = _boolean_property(properties, 0x01FF, 3, True)
    approximated |= lossy

    fill_type, lossy = _simple_property(properties, 0x0180, 0)
    approximated |= lossy or (fill_enabled and fill_type != 0)
    fill_color, lossy = _color_property(properties, 0x0181, "FFFFFF")
    approximated |= fill_enabled and lossy
    fill_opacity, lossy = _bounded_property(
        properties,
        0x0182,
        0x10000,
        0x10000,
        "fill opacity",
    )
    approximated |= fill_enabled and lossy

    line_type, lossy = _simple_property(properties, 0x01C4, 0)
    approximated |= line_enabled and (lossy or line_type != 0)
    line_color, lossy = _color_property(properties, 0x01C0, "000000")
    approximated |= line_enabled and lossy
    line_opacity, lossy = _bounded_property(
        properties,
        0x01C1,
        0x10000,
        0x10000,
        "line opacity",
    )
    approximated |= line_enabled and lossy
    line_width, lossy = _bounded_property(
        properties,
        0x01CB,
        0x2535,
        0x0132F540,
        "line width",
    )
    approximated |= line_enabled and lossy
    line_style, lossy = _simple_property(properties, 0x01CD, 0)
    approximated |= line_enabled and (lossy or line_style != 0)
    line_dashing, lossy = _simple_property(properties, 0x01CE, 0)
    approximated |= line_enabled and (lossy or line_dashing != 0)

    margins: list[int] = []
    for identifier, default, label in (
        (0x0081, 0x16530, "left text inset"),
        (0x0082, 0xB298, "top text inset"),
        (0x0083, 0x16530, "right text inset"),
        (0x0084, 0xB298, "bottom text inset"),
    ):
        margin, lossy = _bounded_property(
            properties,
            identifier,
            default,
            0x0132F540,
            label,
        )
        margins.append(margin)
        approximated |= lossy

    return ShapeStyle(
        fill_enabled=fill_enabled,
        fill_color=fill_color,
        fill_opacity=fill_opacity,
        line_enabled=line_enabled,
        line_color=line_color,
        line_opacity=line_opacity,
        line_width_emu=line_width,
        inset_left_emu=margins[0],
        inset_top_emu=margins[1],
        inset_right_emu=margins[2],
        inset_bottom_emu=margins[3],
        approximated=approximated,
    )


def _shape_containers(record: _Record):
    for child in record.children:
        if child.record_type == _SP_CONTAINER:
            yield child
        yield from _shape_containers(child)


def read_officeart_shapes(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
) -> OfficeArtShapeCollection:
    """Read basic styles for shapes in the OfficeArt main/header drawings."""

    if size == 0:
        return OfficeArtShapeCollection({})
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"OfficeArtContent range [{offset}, {offset + size}) exceeds Table stream"
        )
    data = memoryview(table_stream)[offset : offset + size]
    drawing_group, position = _read_record(data, 0, len(data))
    if drawing_group.record_type != _DGG_CONTAINER or drawing_group.version != 0xF:
        raise InvalidWordDocument(
            "OfficeArtContent does not begin with OfficeArtDggContainer"
        )
    defaults = _option_properties(data, drawing_group.children)
    drawings: list[tuple[int, _Record]] = []
    drawing_labels: set[int] = set()
    while position < len(data):
        drawing_label = data[position]
        position += 1
        drawing, position = _read_record(data, position, len(data))
        if drawing.record_type != _DG_CONTAINER or drawing.version != 0xF:
            raise InvalidWordDocument("OfficeArtWordDrawing has no OfficeArtDgContainer")
        if drawing_label not in (0, 1):
            raise InvalidWordDocument(
                f"OfficeArtWordDrawing has invalid label {drawing_label}"
            )
        if drawing_label in drawing_labels:
            story_name = "header" if drawing_label else "main"
            raise InvalidWordDocument(
                f"OfficeArtContent repeats the {story_name} drawing"
            )
        drawing_labels.add(drawing_label)
        drawings.append((drawing_label, drawing))

    by_shape_id: dict[int, ShapeStyle] = {}
    for drawing_label, drawing in drawings:
        for container in _shape_containers(drawing):
            shape_records = [
                child for child in container.children if child.record_type == _FSP
            ]
            if len(shape_records) != 1:
                raise InvalidWordDocument(
                    "OfficeArtSpContainer must contain one OfficeArtFSP"
                )
            shape_record = shape_records[0]
            if (
                shape_record.version != 0x2
                or shape_record.payload_end - shape_record.payload_start != 8
            ):
                raise InvalidWordDocument("OfficeArtFSP has an invalid header or size")
            shape_id, flags = struct.unpack_from(
                "<II", data, shape_record.payload_start
            )
            if flags & 0x00000008:
                continue
            if shape_id in by_shape_id:
                story_name = "header" if drawing_label else "main"
                raise InvalidWordDocument(
                    f"OfficeArt {story_name} drawing repeats shape id {shape_id}"
                )
            properties = dict(defaults)
            properties.update(_option_properties(data, container.children))
            by_shape_id[shape_id] = _shape_style(properties)
    return OfficeArtShapeCollection(by_shape_id)
