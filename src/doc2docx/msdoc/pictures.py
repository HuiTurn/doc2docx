"""Inline picture extraction from PICF and OfficeArt records."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import struct
import zlib

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
_BLIP_EMF = 0xF01A
_BLIP_WMF = 0xF01B
_BLIP_TIFF = 0xF029
_METAFILE_BLIP_TYPES = frozenset((_BLIP_EMF, _BLIP_WMF))
_SUPPORTED_BLIP_TYPES = _BLIP_JPEG_TYPES | frozenset(
    (_BLIP_PNG, _BLIP_DIB, _BLIP_TIFF, *_METAFILE_BLIP_TYPES)
)
_MAX_DECOMPRESSED_IMAGE_BYTES = 256 * 1024 * 1024


@dataclass(slots=True, frozen=True)
class InlinePictureCollection:
    pictures: tuple[InlinePicture, ...] = ()
    by_cp: Mapping[int, InlinePicture] | None = None
    deferred_count: int = 0
    binary_data_count: int = 0
    consumed_binary_data_cps: frozenset[int] = frozenset()

    def picture_at(self, cp: int) -> InlinePicture | None:
        return (self.by_cp or {}).get(cp)


@dataclass(slots=True)
class _FieldScanContext:
    instruction: list[str]
    has_separator: bool = False


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


def _decompress_metafile(payload: bytes, expected_size: int) -> bytes:
    if expected_size <= 0 or expected_size > _MAX_DECOMPRESSED_IMAGE_BYTES:
        raise InvalidWordDocument(
            "OfficeArt metafile uncompressed size is outside safe limits"
        )
    decompressor = zlib.decompressobj()
    result = bytearray()
    remaining = payload
    try:
        while remaining:
            chunk = decompressor.decompress(
                remaining,
                expected_size + 1 - len(result),
            )
            result.extend(chunk)
            if len(result) > expected_size or decompressor.unconsumed_tail:
                raise InvalidWordDocument(
                    "OfficeArt metafile expands beyond its declared size"
                )
            remaining = b""
        result.extend(decompressor.flush())
    except zlib.error as exc:
        raise InvalidWordDocument(
            f"OfficeArt metafile DEFLATE data is invalid: {exc}"
        ) from exc
    if (
        not decompressor.eof
        or decompressor.unused_data
        or len(result) != expected_size
    ):
        raise InvalidWordDocument(
            "OfficeArt metafile DEFLATE size does not match its header"
        )
    return bytes(result)


def _validate_emf(data: bytes) -> None:
    if len(data) < 44:
        raise InvalidWordDocument("OfficeArt EMF data is truncated")
    record_type, header_size = struct.unpack_from("<II", data, 0)
    signature = struct.unpack_from("<I", data, 40)[0]
    if record_type != 1 or header_size < 44 or header_size > len(data):
        raise InvalidWordDocument("OfficeArt EMF has an invalid header record")
    if signature != 0x464D4520:
        raise InvalidWordDocument("OfficeArt EMF signature is invalid")


def _validate_wmf(data: bytes) -> None:
    header_offset = 22 if data.startswith(b"\xD7\xCD\xC6\x9A") else 0
    if len(data) < header_offset + 18:
        raise InvalidWordDocument("OfficeArt WMF data is truncated")
    metafile_type, header_words, _version, file_words = struct.unpack_from(
        "<HHHI", data, header_offset
    )
    if metafile_type not in (1, 2) or header_words != 9:
        raise InvalidWordDocument("OfficeArt WMF has an invalid METAHEADER")
    if file_words < header_words or file_words * 2 > len(data) - header_offset:
        raise InvalidWordDocument("OfficeArt WMF size exceeds its BLIP data")


def _decode_metafile_blip(
    data: bytes | memoryview,
    record: _OfficeArtRecord,
) -> tuple[bytes, str, str]:
    if record.record_type == _BLIP_EMF:
        one_uid_instance, two_uid_instance = 0x3D4, 0x3D5
        extension, content_type = "emf", "image/x-emf"
    elif record.record_type == _BLIP_WMF:
        one_uid_instance, two_uid_instance = 0x216, 0x217
        extension, content_type = "wmf", "image/x-wmf"
    else:
        raise UnsupportedBlipFormat(record.record_type)
    if record.instance == one_uid_instance:
        uid_count = 1
    elif record.instance == two_uid_instance:
        uid_count = 2
    else:
        raise InvalidWordDocument(
            f"OfficeArt BLIP 0x{record.record_type:04X} has invalid instance "
            f"0x{record.instance:03X}"
        )
    header_start = record.payload_start + uid_count * 16
    if header_start > record.end - 34:
        raise InvalidWordDocument("OfficeArt metafile header is truncated")
    uncompressed_size = struct.unpack_from("<I", data, header_start)[0]
    saved_size = struct.unpack_from("<I", data, header_start + 28)[0]
    compression, filter_value = struct.unpack_from("<BB", data, header_start + 32)
    file_start = header_start + 34
    payload = bytes(data[file_start:record.end])
    if saved_size != len(payload):
        raise InvalidWordDocument(
            "OfficeArt metafile compressed size does not match its header"
        )
    if filter_value != 0xFE:
        raise InvalidWordDocument("OfficeArt metafile filter must be 0xFE")
    if compression == 0x00:
        image_data = _decompress_metafile(payload, uncompressed_size)
    elif compression == 0xFE:
        if uncompressed_size != len(payload):
            raise InvalidWordDocument(
                "uncompressed OfficeArt metafile size does not match its header"
            )
        image_data = payload
    else:
        raise InvalidWordDocument(
            f"OfficeArt metafile compression 0x{compression:02X} is unsupported"
        )
    if record.record_type == _BLIP_EMF:
        _validate_emf(image_data)
    else:
        _validate_wmf(image_data)
    return image_data, extension, content_type


def _decode_blip(
    data: bytes | memoryview,
    record: _OfficeArtRecord,
) -> tuple[bytes, str, str]:
    if record.version != 0:
        raise InvalidWordDocument(
            f"OfficeArt BLIP 0x{record.record_type:04X} has invalid version "
            f"{record.version}"
        )
    if record.record_type in _METAFILE_BLIP_TYPES:
        return _decode_metafile_blip(data, record)
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
    elif record.record_type == _BLIP_TIFF:
        one_uid_instances = {0x6E4}
        two_uid_instances = {0x6E5}
        extension = "tif"
        content_type = "image/tiff"
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
    elif record.record_type == _BLIP_DIB:
        image_data = _dib_to_bmp(image_data)
    elif not image_data.startswith((b"II*\0", b"MM\0*")):
        raise InvalidWordDocument("OfficeArt TIFF byte-order signature is invalid")
    return image_data, extension, content_type


def decode_officeart_blip(
    data: bytes | memoryview,
    offset: int,
    *,
    limit: int | None = None,
) -> tuple[bytes, str, str, int]:
    """Decode one bounded supported OfficeArtBlip record."""

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


_HYPERLINK_BINARY_FIELD_TYPES = frozenset(
    ("HYPERLINK", "NOTEREF", "PAGEREF", "REF")
)


def _binary_field_types(
    characters: Sequence[StoryCharacter],
) -> dict[int, str]:
    """Associate binary U+0001 characters with their containing field type."""

    result: dict[int, str] = {}
    stack: list[_FieldScanContext] = []
    for unit in characters:
        value = ord(unit.text)
        if value == 0x13:
            stack.append(_FieldScanContext([]))
            continue
        if value == 0x14 and stack:
            stack[-1].has_separator = True
            continue
        if value == 0x15 and stack:
            stack.pop()
            continue
        if not stack:
            continue
        context = stack[-1]
        if value == 0x01:
            tokens = "".join(context.instruction).lstrip().split(maxsplit=1)
            result[unit.cp_start] = tokens[0].upper() if tokens else "UNKNOWN"
        elif not context.has_separator and value >= 0x20:
            context.instruction.append(unit.text)
    return result


def _read_nil_picf_binary_data(data_stream: bytes, offset: int) -> memoryview:
    """Read the bounded binData payload from a NilPICFAndBinData record."""

    header_size = 0x44
    if offset < 0 or offset > len(data_stream) - header_size:
        raise InvalidWordDocument(
            "NilPICFAndBinData header exceeds the Data stream"
        )
    record_size, stored_header_size = struct.unpack_from(
        "<iH", data_stream, offset
    )
    if record_size < header_size:
        raise InvalidWordDocument(
            f"NilPICFAndBinData size {record_size} is smaller than 68 bytes"
        )
    record_end = offset + record_size
    if record_end > len(data_stream):
        raise InvalidWordDocument(
            "NilPICFAndBinData record exceeds the Data stream"
        )
    if stored_header_size != header_size:
        raise InvalidWordDocument(
            f"NilPICFAndBinData cbHeader is {stored_header_size}; expected 68"
        )
    if any(data_stream[offset + 6 : offset + header_size]):
        raise InvalidWordDocument(
            "NilPICFAndBinData reserved header bytes are nonzero"
        )
    return memoryview(data_stream)[offset + header_size : record_end]


def _validate_hyperlink_field_data(payload: memoryview) -> None:
    # HFD contains a one-byte HFDBits value, a 16-byte CLSID, and a variable
    # Hyperlink Object. The three high HFDBits bits are reserved by MS-DOC.
    if len(payload) <= 17:
        raise InvalidWordDocument("HFD hyperlink field data is truncated")
    if payload[0] & 0xE0:
        raise InvalidWordDocument("HFD has nonzero reserved flag bits")


def read_inline_pictures(
    data_stream: bytes | None,
    characters: Sequence[StoryCharacter],
    *,
    first_picture_id: int = 1,
    story_name: str = "main",
    report: ConversionReport,
    character_properties_at: Callable[[int], CharacterProperties],
) -> InlinePictureCollection:
    """Resolve valid U+0001 anchors without making one bad picture fatal."""

    if first_picture_id <= 0:
        raise ValueError("first_picture_id must be positive")

    anchors: list[tuple[int, CharacterProperties]] = []
    binary_anchors: list[tuple[int, CharacterProperties]] = []
    missing_sprm_count = 0
    for unit in characters:
        if unit.text != "\x01":
            continue
        properties = character_properties_at(unit.cp_start)
        if properties.special is not True or properties.picture_location is None:
            missing_sprm_count += 1
            continue
        if properties.picture_is_binary is True:
            binary_anchors.append((unit.cp_start, properties))
            continue
        anchors.append((unit.cp_start, properties))

    binary_data_count = len(binary_anchors)
    consumed_binary_data_cps: set[int] = set()
    deferred_binary_data_count = 0
    deferred_binary_field_types: dict[str, int] = {}
    field_types = _binary_field_types(characters)
    for cp, properties in binary_anchors:
        field_type = field_types.get(cp, "UNKNOWN")
        source_offset = properties.picture_location
        assert source_offset is not None
        if field_type not in _HYPERLINK_BINARY_FIELD_TYPES or data_stream is None:
            deferred_binary_data_count += 1
            deferred_binary_field_types[field_type] = (
                deferred_binary_field_types.get(field_type, 0) + 1
            )
            continue
        try:
            payload = _read_nil_picf_binary_data(data_stream, source_offset)
            _validate_hyperlink_field_data(payload)
        except InvalidWordDocument as exc:
            deferred_binary_data_count += 1
            report.warning(
                "INLINE_BINARY_DATA_MALFORMED",
                str(exc),
                location=SourceLocation(
                    story=story_name,
                    cp_start=cp,
                    cp_end=cp + 1,
                    stream="Data",
                    fc_start=source_offset,
                ),
                field_type=field_type,
            )
        else:
            consumed_binary_data_cps.add(cp)

    if missing_sprm_count:
        report.warning(
            "INLINE_PICTURE_ANCHOR_INVALID",
            "some U+0001 picture anchors lack sprmCFSpec or sprmCPicLocation",
            location=SourceLocation(story=story_name),
            anchor_count=missing_sprm_count,
        )
    if deferred_binary_field_types:
        report.warning(
            "INLINE_BINARY_DATA_DEFERRED",
            "binary field data without a supported HFD mapping remains deferred",
            location=SourceLocation(story=story_name),
            anchor_count=sum(deferred_binary_field_types.values()),
            field_types={
                key: deferred_binary_field_types[key]
                for key in sorted(deferred_binary_field_types)
            },
        )
    if not anchors:
        return InlinePictureCollection(
            deferred_count=missing_sprm_count + deferred_binary_data_count,
            binary_data_count=binary_data_count,
            consumed_binary_data_cps=frozenset(consumed_binary_data_cps),
        )
    if data_stream is None:
        report.warning(
            "INLINE_PICTURE_DATA_STREAM_MISSING",
            "picture anchors exist but the DOC Data stream is absent",
            location=SourceLocation(story=story_name, stream="Data"),
            anchor_count=len(anchors),
        )
        return InlinePictureCollection(
            deferred_count=(
                missing_sprm_count
                + deferred_binary_data_count
                + len(anchors)
            ),
            binary_data_count=binary_data_count,
            consumed_binary_data_cps=frozenset(consumed_binary_data_cps),
        )

    by_cp: dict[int, InlinePicture] = {}
    by_offset: dict[int, InlinePicture | None] = {}
    pictures: list[InlinePicture] = []
    deferred_count = missing_sprm_count + deferred_binary_data_count
    for cp, properties in anchors:
        assert properties.picture_location is not None
        source_offset = properties.picture_location
        first_at_offset = source_offset not in by_offset
        if first_at_offset:
            try:
                picture = parse_inline_picture(
                    data_stream,
                    source_offset,
                    picture_id=first_picture_id + len(pictures),
                    properties=properties,
                )
            except UnsupportedBlipFormat as exc:
                report.warning(
                    "INLINE_PICTURE_FORMAT_DEFERRED",
                    "an inline picture uses an unsupported OfficeArt BLIP format",
                    location=SourceLocation(
                        story=story_name,
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
                        story=story_name,
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
                    picture_id=first_picture_id + len(pictures),
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
        consumed_binary_data_cps=frozenset(consumed_binary_data_cps),
    )
