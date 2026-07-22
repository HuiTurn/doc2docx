"""Minimal OfficeArt drawing and shape-property parsing for Word documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import struct

from ..errors import InvalidWordDocument
from ..model import ShapeStyle
from .pictures import UnsupportedBlipFormat, decode_officeart_blip


_DGG_CONTAINER = 0xF000
_BSTORE_CONTAINER = 0xF001
_DG_CONTAINER = 0xF002
_SP_CONTAINER = 0xF004
_FBSE = 0xF007
_FSP = 0xF00A
_OPTION_RECORDS = (0xF00B, 0xF121, 0xF122)
_MAX_RECORD_DEPTH = 32

_LINE_STYLES = {
    0: "single",
    1: "thinThin",
    2: "thickThin",
    3: "thinThick",
    4: "thickBetweenThin",
}
_LINE_DASH_STYLES = {
    0: "solid",
    1: "shortdash",
    2: "shortdot",
    3: "shortdashdot",
    4: "shortdashdotdot",
    5: "dot",
    6: "dash",
    7: "longdash",
    8: "dashdot",
    9: "longdashdot",
    10: "longdashdotdot",
}
_LINE_JOIN_STYLES = {0: "bevel", 1: "miter", 2: "round"}
_LINE_END_CAP_STYLES = {0: "round", 1: "square", 2: "flat"}


@dataclass(slots=True, frozen=True)
class OfficeArtImage:
    data: bytes
    extension: str
    content_type: str
    blip_index: int | None = None


# Backwards-compatible name retained for callers of the M8a-M8d API.
OfficeArtRasterImage = OfficeArtImage


@dataclass(slots=True, frozen=True)
class OfficeArtShapeCollection:
    by_shape_id: Mapping[int, ShapeStyle]
    images_by_shape_id: Mapping[int, OfficeArtImage] = field(
        default_factory=dict
    )
    unsupported_image_types_by_shape_id: Mapping[int, int] = field(
        default_factory=dict
    )
    wrap_polygons_by_shape_id: Mapping[int, tuple[tuple[int, int], ...]] = field(
        default_factory=dict
    )
    shape_types_by_shape_id: Mapping[int, int] = field(default_factory=dict)
    horizontally_flipped_shape_ids: frozenset[int] = frozenset()
    vertically_flipped_shape_ids: frozenset[int] = frozenset()
    rotations_by_shape_id: Mapping[int, float] = field(default_factory=dict)

    def style_at(self, shape_id: int) -> ShapeStyle | None:
        return self.by_shape_id.get(shape_id)

    def image_at(self, shape_id: int) -> OfficeArtImage | None:
        return self.images_by_shape_id.get(shape_id)

    def shape_type_at(self, shape_id: int) -> int | None:
        return self.shape_types_by_shape_id.get(shape_id)

    def is_horizontally_flipped(self, shape_id: int) -> bool:
        return shape_id in self.horizontally_flipped_shape_ids

    def is_vertically_flipped(self, shape_id: int) -> bool:
        return shape_id in self.vertically_flipped_shape_ids

    def rotation_at(self, shape_id: int) -> float:
        return self.rotations_by_shape_id.get(shape_id, 0.0)

    def unsupported_image_type_at(self, shape_id: int) -> int | None:
        return self.unsupported_image_types_by_shape_id.get(shape_id)

    def wrap_polygon_at(self, shape_id: int) -> tuple[tuple[int, int], ...]:
        return self.wrap_polygons_by_shape_id.get(shape_id, ())


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
    complex_data: bytes | None = None


@dataclass(slots=True, frozen=True)
class _BlipEntry:
    image: OfficeArtImage | None = None
    unsupported_record_type: int | None = None


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
    entries: list[tuple[int, int, bool, bool]] = []
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
        entries.append(
            (identifier, value, bool(raw_identifier & 0x4000), is_complex)
        )
    complex_position = entries_end
    for identifier, value, is_blip, is_complex in entries:
        complex_data = None
        if is_complex:
            complex_end = complex_position + value
            if complex_end > record.payload_end:
                raise InvalidWordDocument(
                    "OfficeArt complex property data exceeds its table"
                )
            complex_data = bytes(data[complex_position:complex_end])
            complex_position = complex_end
        properties[identifier] = _Property(
            value=value,
            is_blip=is_blip,
            is_complex=is_complex,
            complex_data=complex_data,
        )
    if complex_position != record.payload_end:
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


def _rotation_property(properties: Mapping[int, _Property]) -> float:
    value, approximated = _simple_property(properties, 0x0004, 0)
    if approximated:
        raise InvalidWordDocument("OfficeArt rotation must be a simple property")
    if value & 0x80000000:
        value -= 0x100000000
    return value / 0x10000


def _wrap_polygon(
    properties: Mapping[int, _Property],
) -> tuple[tuple[int, int], ...]:
    entry = properties.get(0x0383)
    if entry is None:
        return ()
    if not entry.is_complex or entry.complex_data is None:
        raise InvalidWordDocument(
            "OfficeArt pWrapPolygonVertices has no complex point array"
        )
    payload = entry.complex_data
    if len(payload) < 6:
        raise InvalidWordDocument("OfficeArt wrap polygon IMsoArray is truncated")
    count, allocated, element_size = struct.unpack_from("<HHH", payload)
    if count < 3 or allocated < count or count > 4096:
        raise InvalidWordDocument("OfficeArt wrap polygon has an invalid point count")
    if element_size == 8:
        stored_size = 8
        point_format = "<ii"
    elif element_size == 0xFFF0:
        stored_size = 4
        point_format = "<hh"
    else:
        raise InvalidWordDocument(
            f"OfficeArt wrap polygon has unsupported point size 0x{element_size:04X}"
        )
    if len(payload) != 6 + count * stored_size:
        raise InvalidWordDocument(
            "OfficeArt wrap polygon point data does not match its IMsoArray header"
        )

    left, _ = _simple_property(properties, 0x0140, 0)
    top, _ = _simple_property(properties, 0x0141, 0)
    right, _ = _simple_property(properties, 0x0142, 21600)
    bottom, _ = _simple_property(properties, 0x0143, 21600)
    if right <= left or bottom <= top:
        raise InvalidWordDocument("OfficeArt wrap polygon geometry bounds are invalid")

    points: list[tuple[int, int]] = []
    for index in range(count):
        x, y = struct.unpack_from(point_format, payload, 6 + index * stored_size)
        normalized_x = round((x - left) * 21600 / (right - left))
        normalized_y = round((y - top) * 21600 / (bottom - top))
        points.append((normalized_x, normalized_y))
    return tuple(points)


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
    line_style_value, lossy = _simple_property(properties, 0x01CD, 0)
    line_style = _LINE_STYLES.get(line_style_value, "single")
    approximated |= line_enabled and (lossy or line_style_value not in _LINE_STYLES)
    line_dashing_value, lossy = _simple_property(properties, 0x01CE, 0)
    line_dash = _LINE_DASH_STYLES.get(line_dashing_value, "solid")
    approximated |= line_enabled and (
        lossy or line_dashing_value not in _LINE_DASH_STYLES
    )
    line_join_value, lossy = _simple_property(properties, 0x01D6, 2)
    line_join = _LINE_JOIN_STYLES.get(line_join_value, "round")
    approximated |= line_enabled and (
        lossy or line_join_value not in _LINE_JOIN_STYLES
    )
    line_end_cap_value, lossy = _simple_property(properties, 0x01D7, 2)
    line_end_cap = _LINE_END_CAP_STYLES.get(line_end_cap_value, "flat")
    approximated |= line_enabled and (
        lossy or line_end_cap_value not in _LINE_END_CAP_STYLES
    )

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
        line_style=line_style,
        line_dash=line_dash,
        line_join=line_join,
        line_end_cap=line_end_cap,
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


def _decode_blip_entry(
    source: bytes | memoryview,
    offset: int,
    limit: int,
    *,
    blip_index: int | None,
) -> tuple[_BlipEntry, int]:
    try:
        image_data, extension, content_type, end = decode_officeart_blip(
            source,
            offset,
            limit=limit,
        )
    except UnsupportedBlipFormat as exc:
        return _BlipEntry(unsupported_record_type=exc.record_type), limit
    return (
        _BlipEntry(
            image=OfficeArtImage(
                image_data,
                extension,
                content_type,
                blip_index,
            )
        ),
        end,
    )


def _decode_fbse(
    data: memoryview,
    record: _Record,
    *,
    blip_index: int,
    delay_stream: bytes | None,
) -> _BlipEntry:
    if record.version != 2 or record.payload_end - record.payload_start < 36:
        raise InvalidWordDocument("OfficeArtFBSE header is invalid or truncated")
    size, reference_count, delay_offset = struct.unpack_from(
        "<III", data, record.payload_start + 20
    )
    name_length = data[record.payload_start + 33]
    if name_length % 2 or name_length > 0xFE:
        raise InvalidWordDocument("OfficeArtFBSE name length is invalid")
    embedded_start = record.payload_start + 36 + name_length
    if embedded_start > record.payload_end:
        raise InvalidWordDocument("OfficeArtFBSE name exceeds its record")
    if reference_count == 0:
        return _BlipEntry()
    if embedded_start < record.payload_end:
        entry, end = _decode_blip_entry(
            data,
            embedded_start,
            record.payload_end,
            blip_index=blip_index,
        )
        if end != record.payload_end:
            raise InvalidWordDocument("OfficeArtFBSE embedded BLIP has trailing data")
        if size and size != end - embedded_start:
            raise InvalidWordDocument("OfficeArtFBSE embedded BLIP size is inconsistent")
        return entry
    if delay_offset == 0xFFFFFFFF or delay_stream is None:
        raise InvalidWordDocument("OfficeArtFBSE delayed BLIP stream is unavailable")
    if size == 0 or delay_offset > len(delay_stream) - size:
        raise InvalidWordDocument("OfficeArtFBSE delayed BLIP exceeds WordDocument")
    limit = delay_offset + size
    entry, end = _decode_blip_entry(
        delay_stream,
        delay_offset,
        limit,
        blip_index=blip_index,
    )
    if end != limit:
        raise InvalidWordDocument("OfficeArtFBSE delayed BLIP size is inconsistent")
    return entry


def _read_blip_store(
    data: memoryview,
    drawing_group: _Record,
    *,
    delay_stream: bytes | None,
) -> tuple[_BlipEntry, ...]:
    stores = [
        child
        for child in drawing_group.children
        if child.record_type == _BSTORE_CONTAINER
    ]
    if not stores:
        return ()
    if len(stores) != 1:
        raise InvalidWordDocument("OfficeArtDggContainer repeats its BLIP store")
    store = stores[0]
    if store.version != 0xF or store.instance != len(store.children):
        raise InvalidWordDocument("OfficeArtBStoreContainer count is inconsistent")
    entries: list[_BlipEntry] = []
    for blip_index, record in enumerate(store.children, start=1):
        if record.record_type == _FBSE:
            entries.append(
                _decode_fbse(
                    data,
                    record,
                    blip_index=blip_index,
                    delay_stream=delay_stream,
                )
            )
            continue
        entry, end = _decode_blip_entry(
            data,
            record.payload_start - 8,
            record.payload_end,
            blip_index=blip_index,
        )
        if end != record.payload_end:
            raise InvalidWordDocument("OfficeArt BLIP store record has trailing data")
        entries.append(entry)
    return tuple(entries)


def _shape_image(
    properties: Mapping[int, _Property],
    blips: tuple[_BlipEntry, ...],
) -> _BlipEntry:
    pib = properties.get(0x0104)
    if pib is None or pib.value == 0:
        return _BlipEntry()
    if pib.is_complex:
        if pib.complex_data is None or len(pib.complex_data) != pib.value:
            raise InvalidWordDocument("OfficeArt pib complex BLIP is missing")
        entry, end = _decode_blip_entry(
            pib.complex_data,
            0,
            len(pib.complex_data),
            blip_index=None,
        )
        if end != len(pib.complex_data):
            raise InvalidWordDocument("OfficeArt pib complex BLIP has trailing data")
        return entry
    if not pib.is_blip:
        raise InvalidWordDocument("OfficeArt pib index does not set fBid")
    if pib.value > len(blips):
        raise InvalidWordDocument(
            f"OfficeArt pib index {pib.value} exceeds the BLIP store"
        )
    entry = blips[pib.value - 1]
    if entry.image is None and entry.unsupported_record_type is None:
        raise InvalidWordDocument(
            f"OfficeArt pib index {pib.value} references an empty BLIP slot"
        )
    return entry


def read_officeart_shapes(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    delay_stream: bytes | None = None,
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
    blips = _read_blip_store(
        data,
        drawing_group,
        delay_stream=delay_stream,
    )
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
    shape_types_by_shape_id: dict[int, int] = {}
    horizontally_flipped_shape_ids: set[int] = set()
    vertically_flipped_shape_ids: set[int] = set()
    rotations_by_shape_id: dict[int, float] = {}
    images_by_shape_id: dict[int, OfficeArtImage] = {}
    unsupported_image_types_by_shape_id: dict[int, int] = {}
    wrap_polygons_by_shape_id: dict[int, tuple[tuple[int, int], ...]] = {}
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
            shape_types_by_shape_id[shape_id] = shape_record.instance
            if flags & 0x00000040:
                horizontally_flipped_shape_ids.add(shape_id)
            if flags & 0x00000080:
                vertically_flipped_shape_ids.add(shape_id)
            rotation = _rotation_property(properties)
            if rotation:
                rotations_by_shape_id[shape_id] = rotation
            wrap_polygon = _wrap_polygon(properties)
            if wrap_polygon:
                wrap_polygons_by_shape_id[shape_id] = wrap_polygon
            image_entry = _shape_image(properties, blips)
            if image_entry.image is not None:
                images_by_shape_id[shape_id] = image_entry.image
            elif image_entry.unsupported_record_type is not None:
                unsupported_image_types_by_shape_id[shape_id] = (
                    image_entry.unsupported_record_type
                )
    return OfficeArtShapeCollection(
        by_shape_id=by_shape_id,
        shape_types_by_shape_id=shape_types_by_shape_id,
        horizontally_flipped_shape_ids=frozenset(
            horizontally_flipped_shape_ids
        ),
        vertically_flipped_shape_ids=frozenset(
            vertically_flipped_shape_ids
        ),
        rotations_by_shape_id=rotations_by_shape_id,
        images_by_shape_id=images_by_shape_id,
        unsupported_image_types_by_shape_id=(
            unsupported_image_types_by_shape_id
        ),
        wrap_polygons_by_shape_id=wrap_polygons_by_shape_id,
    )
