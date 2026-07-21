"""Inline raster-picture extraction from PICF and OfficeArt records."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import struct

from ..diagnostics import ConversionReport, SourceLocation
from ..errors import InvalidWordDocument
from ..model import CharacterProperties, InlinePicture, StoryCharacter


_PICF_SIZE = 68
_MM_SHAPE = 0x0064
_MM_SHAPEFILE = 0x0066
_OFFICEART_SP_CONTAINER = 0xF004
_OFFICEART_FBSE = 0xF007
_BLIP_JPEG_TYPES = frozenset((0xF01D, 0xF02A))
_BLIP_PNG = 0xF01E
_BLIP_DIB = 0xF01F
_SUPPORTED_BLIP_TYPES = _BLIP_JPEG_TYPES | frozenset((_BLIP_PNG, _BLIP_DIB))


@dataclass(slots=True, frozen=True)
class InlinePictureCollection:
    pictures: tuple[InlinePicture, ...] = ()
    by_cp: Mapping[int, InlinePicture] | None = None
    deferred_count: int = 0
    binary_data_count: int = 0

    def picture_at(self, cp: int) -> InlinePicture | None:
        return (self.by_cp or {}).get(cp)


@dataclass(slots=True, frozen=True)
class _OfficeArtRecord:
    offset: int
    version: int
    instance: int
    record_type: int
    payload_start: int
    end: int


class UnsupportedBlipFormat(InvalidWordDocument):
    def __init__(self, record_type: int) -> None:
        super().__init__(f"OfficeArt BLIP type 0x{record_type:04X} is unsupported")
        self.record_type = record_type


def _record_at(
    data: bytes | memoryview,
    offset: int,
    limit: int,
    *,
    label: str,
) -> _OfficeArtRecord:
    if offset < 0 or limit < offset or offset > limit - 8:
        raise InvalidWordDocument(f"{label} has a truncated OfficeArt record header")
    version_instance, record_type, record_length = struct.unpack_from(
        "<HHI", data, offset
    )
    end = offset + 8 + record_length
    if end > limit:
        raise InvalidWordDocument(
            f"{label} OfficeArt record 0x{record_type:04X} exceeds its container"
        )
    return _OfficeArtRecord(
        offset=offset,
        version=version_instance & 0x000F,
        instance=version_instance >> 4,
        record_type=record_type,
        payload_start=offset + 8,
        end=end,
    )


def _dib_to_bmp(dib: bytes) -> bytes:
    """Add a BITMAPFILEHEADER to a bounded, uncompressed DIB payload."""

    if dib.startswith(b"BM"):
        if len(dib) < 14:
            raise InvalidWordDocument("OfficeArt DIB contains a truncated BMP header")
        return dib
    if len(dib) < 12:
        raise InvalidWordDocument("OfficeArt DIB has no complete bitmap header")
    header_size = struct.unpack_from("<I", dib, 0)[0]
    if header_size == 12:
        if len(dib) < 12:
            raise InvalidWordDocument("OfficeArt DIB BITMAPCOREHEADER is truncated")
        bit_count = struct.unpack_from("<H", dib, 10)[0]
        palette_entries = (1 << bit_count) if bit_count <= 8 else 0
        pixel_offset = 12 + palette_entries * 3
    elif header_size >= 40:
        if header_size > len(dib):
            raise InvalidWordDocument("OfficeArt DIB bitmap header exceeds BLIP data")
        bit_count = struct.unpack_from("<H", dib, 14)[0]
        compression = struct.unpack_from("<I", dib, 16)[0]
        image_size = struct.unpack_from("<I", dib, 20)[0]
        colors_used = struct.unpack_from("<I", dib, 32)[0]
        palette_entries = colors_used or ((1 << bit_count) if bit_count <= 8 else 0)
        extra_masks = 0
        if header_size == 40 and compression in (3, 6):
            extra_masks = 16 if compression == 6 else 12
        pixel_offset = header_size + extra_masks + palette_entries * 4
        if image_size and image_size <= len(dib):
            inferred_offset = len(dib) - image_size
            if inferred_offset >= header_size:
                pixel_offset = inferred_offset
    else:
        raise InvalidWordDocument(
            f"OfficeArt DIB uses unsupported bitmap header size {header_size}"
        )
    if pixel_offset > len(dib):
        raise InvalidWordDocument("OfficeArt DIB pixel data begins outside the BLIP")
    file_size = 14 + len(dib)
    return struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 14 + pixel_offset) + dib


def _decode_blip(
    data: bytes | memoryview,
    record: _OfficeArtRecord,
) -> tuple[bytes, str, str]:
    if record.version != 0:
        raise InvalidWordDocument(
            f"OfficeArt BLIP 0x{record.record_type:04X} has invalid version "
            f"{record.version}"
        )
    if record.record_type in _BLIP_JPEG_TYPES:
        one_uid_instances = {0x46A, 0x6E2}
        two_uid_instances = {0x46B, 0x6E3}
        extension = "jpg"
        content_type = "image/jpeg"
    elif record.record_type == _BLIP_PNG:
        one_uid_instances = {0x6E0}
        two_uid_instances = {0x6E1}
        extension = "png"
        content_type = "image/png"
    elif record.record_type == _BLIP_DIB:
        one_uid_instances = {0x7A8}
        two_uid_instances = {0x7A9}
        extension = "bmp"
        content_type = "image/bmp"
    else:
        raise UnsupportedBlipFormat(record.record_type)

    if record.instance in one_uid_instances:
        uid_count = 1
    elif record.instance in two_uid_instances:
        uid_count = 2
    else:
        raise InvalidWordDocument(
            f"OfficeArt BLIP 0x{record.record_type:04X} has invalid instance "
            f"0x{record.instance:03X}"
        )
    file_start = record.payload_start + uid_count * 16 + 1
    if file_start > record.end:
        raise InvalidWordDocument("OfficeArt BLIP UID/tag fields exceed the record")
    image_data = bytes(data[file_start:record.end])
    if record.record_type == _BLIP_PNG:
        if not image_data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise InvalidWordDocument("OfficeArt PNG BLIP has no PNG signature")
    elif record.record_type in _BLIP_JPEG_TYPES:
        if not image_data.startswith(b"\xFF\xD8") or not image_data.endswith(b"\xFF\xD9"):
            raise InvalidWordDocument("OfficeArt JPEG BLIP has invalid SOI/EOI markers")
    else:
        image_data = _dib_to_bmp(image_data)
    return image_data, extension, content_type


def decode_officeart_blip(
    data: bytes | memoryview,
    offset: int,
    *,
    limit: int | None = None,
) -> tuple[bytes, str, str, int]:
    """Decode one bounded PNG/JPEG/DIB OfficeArtBlip record."""

    record_limit = len(data) if limit is None else limit
    record = _record_at(data, offset, record_limit, label="OfficeArtBlip")
    image_data, extension, content_type = _decode_blip(data, record)
    return image_data, extension, content_type, record.end


def _decode_file_block(
    data: bytes,
    record: _OfficeArtRecord,
) -> tuple[bytes, str, str]:
    if record.record_type in _SUPPORTED_BLIP_TYPES:
        return _decode_blip(data, record)
    if record.record_type != _OFFICEART_FBSE:
        if 0xF018 <= record.record_type <= 0xF117:
            raise UnsupportedBlipFormat(record.record_type)
        raise InvalidWordDocument(
            f"inline OfficeArt container has unexpected record "
            f"0x{record.record_type:04X}"
        )
    if record.version != 2 or record.payload_start > record.end - 36:
        raise InvalidWordDocument("OfficeArtFBSE header is invalid or truncated")
    name_length = data[record.payload_start + 33]
    if name_length % 2 or name_length > 0xFE:
        raise InvalidWordDocument("OfficeArtFBSE name length is invalid")
    embedded_start = record.payload_start + 36 + name_length
    if embedded_start >= record.end:
        raise InvalidWordDocument("OfficeArtFBSE has no embedded BLIP")
    embedded = _record_at(
        data,
        embedded_start,
        record.end,
        label="OfficeArtFBSE",
    )
    result = _decode_blip(data, embedded)
    if embedded.end != record.end:
        trailing = data[embedded.end:record.end]
        if any(trailing):
            raise InvalidWordDocument("OfficeArtFBSE has unexpected trailing data")
    return result


def parse_inline_picture(
    data_stream: bytes,
    offset: int,
    *,
    picture_id: int,
    properties: CharacterProperties | None = None,
) -> InlinePicture:
    """Strictly parse one PICFAndOfficeArtData at a Data-stream offset."""

    if offset < 0 or offset > len(data_stream) - _PICF_SIZE:
        raise InvalidWordDocument(
            f"inline picture offset {offset} has no complete 68-byte PICF"
        )
    total_size = struct.unpack_from("<i", data_stream, offset)[0]
    if total_size < _PICF_SIZE or total_size > len(data_stream) - offset:
        raise InvalidWordDocument(
            f"inline picture PICF size {total_size} exceeds the Data stream"
        )
    picture_end = offset + total_size
    header_size, mapping_mode = struct.unpack_from("<Hh", data_stream, offset + 4)
    if header_size != _PICF_SIZE:
        raise InvalidWordDocument(
            f"inline picture PICF header size is {header_size}, expected 68"
        )
    if mapping_mode not in (_MM_SHAPE, _MM_SHAPEFILE):
        raise InvalidWordDocument(
            f"inline picture PICF mapping mode 0x{mapping_mode & 0xFFFF:04X} "
            "is unsupported"
        )
    width_goal, height_goal, width_scale, height_scale = struct.unpack_from(
        "<hhHH", data_stream, offset + 28
    )
    if width_goal <= 0 or height_goal <= 0:
        raise InvalidWordDocument("inline picture PICMID goal dimensions are invalid")
    if (
        any(data_stream[offset + 36 : offset + 45])
        or any(data_stream[offset + 62 : offset + 66])
        or struct.unpack_from("<H", data_stream, offset + 66)[0] != 0
    ):
        raise InvalidWordDocument("inline picture PICF reserved fields are nonzero")
    width_twips = (width_goal * width_scale + 500) // 1000
    height_twips = (height_goal * height_scale + 500) // 1000
    if not (15 <= width_twips <= 31680) or not (15 <= height_twips <= 31680):
        raise InvalidWordDocument("inline picture final dimensions are outside MS-DOC limits")

    officeart_start = offset + _PICF_SIZE
    source_name: str | None = None
    if mapping_mode == _MM_SHAPEFILE:
        if officeart_start >= picture_end:
            raise InvalidWordDocument("MM_SHAPEFILE picture has no path length")
        path_length = data_stream[officeart_start]
        path_start = officeart_start + 1
        path_end = path_start + path_length
        if path_end > picture_end:
            raise InvalidWordDocument("MM_SHAPEFILE picture path exceeds PICF data")
        raw_name = data_stream[path_start:path_end].decode("cp1252", errors="replace")
        source_name = raw_name.replace("\\", "/").rsplit("/", 1)[-1] or None
        officeart_start = path_end

    shape = _record_at(
        data_stream,
        officeart_start,
        picture_end,
        label="OfficeArtInlineSpContainer",
    )
    if shape.record_type != _OFFICEART_SP_CONTAINER or shape.version != 0xF:
        raise InvalidWordDocument(
            "inline picture does not begin with an OfficeArtSpContainer"
        )

    position = shape.end
    unsupported_type: int | None = None
    while position < picture_end:
        record = _record_at(
            data_stream,
            position,
            picture_end,
            label="OfficeArtInlineSpContainer",
        )
        try:
            image_data, extension, content_type = _decode_file_block(
                data_stream,
                record,
            )
        except UnsupportedBlipFormat as exc:
            unsupported_type = exc.record_type
        else:
            display_properties = replace(
                properties or CharacterProperties(),
                special=None,
                picture_location=None,
                picture_is_binary=None,
            )
            return InlinePicture(
                picture_id=picture_id,
                source_offset=offset,
                data=image_data,
                extension=extension,
                content_type=content_type,
                width_emu=width_twips * 635,
                height_emu=height_twips * 635,
                name=source_name,
                properties=display_properties,
            )
        position = record.end
    if unsupported_type is not None:
        raise UnsupportedBlipFormat(unsupported_type)
    raise InvalidWordDocument("inline OfficeArt container contains no BLIP")


def read_inline_pictures(
    data_stream: bytes | None,
    characters: Sequence[StoryCharacter],
    *,
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties],
) -> InlinePictureCollection:
    """Resolve valid U+0001 anchors without making one bad picture fatal."""

    anchors: list[tuple[int, CharacterProperties]] = []
    missing_sprm_count = 0
    binary_data_count = 0
    for unit in characters:
        if unit.text != "\x01":
            continue
        properties = character_properties_at(unit.cp_start)
        if properties.special is not True or properties.picture_location is None:
            missing_sprm_count += 1
            continue
        if properties.picture_is_binary is True:
            binary_data_count += 1
            continue
        anchors.append((unit.cp_start, properties))

    if missing_sprm_count:
        report.warning(
            "INLINE_PICTURE_ANCHOR_INVALID",
            "some U+0001 picture anchors lack sprmCFSpec or sprmCPicLocation",
            location=SourceLocation(story="main"),
            anchor_count=missing_sprm_count,
        )
    if binary_data_count:
        report.warning(
            "INLINE_BINARY_DATA_DEFERRED",
            "U+0001 binary-data records are not raster pictures and remain unsupported",
            location=SourceLocation(story="main"),
            anchor_count=binary_data_count,
        )
    if not anchors:
        return InlinePictureCollection(
            deferred_count=missing_sprm_count + binary_data_count,
            binary_data_count=binary_data_count,
        )
    if data_stream is None:
        report.warning(
            "INLINE_PICTURE_DATA_STREAM_MISSING",
            "picture anchors exist but the DOC Data stream is absent",
            location=SourceLocation(story="main", stream="Data"),
            anchor_count=len(anchors),
        )
        return InlinePictureCollection(
            deferred_count=missing_sprm_count + binary_data_count + len(anchors),
            binary_data_count=binary_data_count,
        )

    by_cp: dict[int, InlinePicture] = {}
    by_offset: dict[int, InlinePicture | None] = {}
    pictures: list[InlinePicture] = []
    deferred_count = missing_sprm_count + binary_data_count
    for cp, properties in anchors:
        assert properties.picture_location is not None
        source_offset = properties.picture_location
        first_at_offset = source_offset not in by_offset
        if first_at_offset:
            try:
                picture = parse_inline_picture(
                    data_stream,
                    source_offset,
                    picture_id=len(pictures) + 1,
                    properties=properties,
                )
            except UnsupportedBlipFormat as exc:
                report.warning(
                    "INLINE_PICTURE_FORMAT_DEFERRED",
                    "an inline picture uses an unsupported OfficeArt BLIP format",
                    location=SourceLocation(
                        story="main",
                        cp_start=cp,
                        cp_end=cp + 1,
                        stream="Data",
                        fc_start=source_offset,
                    ),
                    record_type=f"0x{exc.record_type:04X}",
                )
                picture = None
            except InvalidWordDocument as exc:
                report.warning(
                    "INLINE_PICTURE_MALFORMED",
                    str(exc),
                    location=SourceLocation(
                        story="main",
                        cp_start=cp,
                        cp_end=cp + 1,
                        stream="Data",
                        fc_start=source_offset,
                    ),
                )
                picture = None
            by_offset[source_offset] = picture
        cached_picture = by_offset[source_offset]
        if cached_picture is None:
            deferred_count += 1
        else:
            if first_at_offset:
                picture = cached_picture
            else:
                picture = replace(
                    cached_picture,
                    picture_id=len(pictures) + 1,
                    properties=replace(
                        properties,
                        special=None,
                        picture_location=None,
                        picture_is_binary=None,
                    ),
                )
            pictures.append(picture)
            by_cp[cp] = picture

    return InlinePictureCollection(
        pictures=tuple(pictures),
        by_cp=by_cp,
        deferred_count=deferred_count,
        binary_data_count=binary_data_count,
    )
