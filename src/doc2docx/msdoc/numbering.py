"""MS-DOC PlfLst/LVL and PlfLfo/LFOLVL list parsing."""

from __future__ import annotations

from dataclasses import dataclass, replace
import struct

from ..diagnostics import ConversionReport
from ..errors import InvalidWordDocument
from ..model import (
    AbstractNumbering,
    FontDefinition,
    NumberingDefinitions,
    NumberingInstance,
    NumberingLevel,
    NumberingLevelOverride,
)
from .sprm import (
    apply_character_modifiers,
    apply_paragraph_modifiers,
    parse_grpprl,
)


_LSTF_SIZE = 28
_LVLF_SIZE = 28
_LFO_SIZE = 16
_LFOLVL_SIZE = 8

# [MS-OSHARED] 2.2.1.3 maps MSONFC values directly to ST_NumberFormat.
_NUMBER_FORMATS = {
    0x00: "decimal",
    0x01: "upperRoman",
    0x02: "lowerRoman",
    0x03: "upperLetter",
    0x04: "lowerLetter",
    0x05: "ordinal",
    0x06: "cardinalText",
    0x07: "ordinalText",
    0x08: "hex",
    0x09: "chicago",
    0x0A: "ideographDigital",
    0x0B: "japaneseCounting",
    0x0C: "aiueo",
    0x0D: "iroha",
    0x0E: "decimalFullWidth",
    0x0F: "decimalHalfWidth",
    0x10: "japaneseLegal",
    0x11: "japaneseDigitalTenThousand",
    0x12: "decimalEnclosedCircle",
    0x13: "decimalFullWidth2",
    0x14: "aiueoFullWidth",
    0x15: "irohaFullWidth",
    0x16: "decimalZero",
    0x17: "bullet",
    0x18: "ganada",
    0x19: "chosung",
    0x1A: "decimalEnclosedFullstop",
    0x1B: "decimalEnclosedParen",
    0x1C: "decimalEnclosedCircleChinese",
    0x1D: "ideographEnclosedCircle",
    0x1E: "ideographTraditional",
    0x1F: "ideographZodiac",
    0x20: "ideographZodiacTraditional",
    0x21: "taiwaneseCounting",
    0x22: "ideographLegalTraditional",
    0x23: "taiwaneseCountingThousand",
    0x24: "taiwaneseDigital",
    0x25: "chineseCounting",
    0x26: "chineseLegalSimplified",
    0x27: "chineseCountingThousand",
    0x28: "decimal",
    0x29: "koreanDigital",
    0x2A: "koreanCounting",
    0x2B: "koreanLegal",
    0x2C: "koreanDigital2",
    0x2D: "hebrew1",
    0x2E: "arabicAlpha",
    0x2F: "hebrew2",
    0x30: "arabicAbjad",
    0x31: "hindiVowels",
    0x32: "hindiConsonants",
    0x33: "hindiNumbers",
    0x34: "hindiCounting",
    0x35: "thaiLetters",
    0x36: "thaiNumbers",
    0x37: "thaiCounting",
    0x38: "vietnameseCounting",
    0x39: "numberInDash",
    0x3A: "russianLower",
    0x3B: "russianUpper",
    0xFF: "none",
}

_JUSTIFICATIONS = {0: "left", 1: "center", 2: "right"}
_SUFFIXES = {0: "tab", 1: "space", 2: "nothing"}


@dataclass(slots=True, frozen=True)
class _ListHeader:
    list_id: int
    linked_style_ids: tuple[int | None, ...]
    simple: bool
    hybrid: bool


@dataclass(slots=True, frozen=True)
class _LfoHeader:
    list_id: int
    override_count: int


def _check_range(data: bytes, offset: int, size: int, *, label: str) -> None:
    if offset < 0 or size < 0 or offset > len(data) - size:
        raise InvalidWordDocument(
            f"{label} range [{offset}, {offset + size}) exceeds Table stream"
        )


def _unpack_from(fmt: str, data: bytes, position: int, limit: int, *, label: str):
    size = struct.calcsize(fmt)
    if position < 0 or position > limit - size:
        raise InvalidWordDocument(f"{label} is truncated")
    return struct.unpack_from(fmt, data, position)


def _decode_level_text(
    code_units: tuple[int, ...],
    placeholder_offsets: tuple[int, ...],
    *,
    level: int,
    label: str,
) -> str:
    replacements: dict[int, str] = {}
    for one_based_offset in placeholder_offsets:
        index = one_based_offset - 1
        if index < 0 or index >= len(code_units):
            raise InvalidWordDocument(f"{label} placeholder exceeds Xst")
        placeholder_level = code_units[index]
        if placeholder_level > level:
            raise InvalidWordDocument(
                f"{label} has an inconsistent level placeholder"
            )
        replacements[index] = f"%{placeholder_level + 1}"

    pieces: list[str] = []
    raw_units: list[int] = []

    def flush_raw() -> None:
        if not raw_units:
            return
        payload = struct.pack(f"<{len(raw_units)}H", *raw_units)
        pieces.append(payload.decode("utf-16le", errors="replace"))
        raw_units.clear()

    for index, code_unit in enumerate(code_units):
        replacement = replacements.get(index)
        if replacement is None:
            raw_units.append(code_unit)
            continue
        flush_raw()
        pieces.append(replacement)
    flush_raw()
    return "".join(pieces)


def _parse_list_names(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    list_count: int,
    report: ConversionReport,
) -> tuple[str, ...]:
    """Parse SttbListNames and return names parallel to PlfLst.rgLstf."""

    if size == 0:
        return ("",) * list_count
    _check_range(table_stream, offset, size, label="SttbListNames")
    if size < 6:
        raise InvalidWordDocument("SttbListNames is truncated")
    limit = offset + size
    f_extend, entry_count, extra_size = struct.unpack_from(
        "<HHH", table_stream, offset
    )
    if f_extend != 0xFFFF:
        raise InvalidWordDocument("SttbListNames is not an extended STTB")
    if extra_size != 0:
        raise InvalidWordDocument("SttbListNames has nonzero cbExtra")

    position = offset + 6
    values: list[str] = []
    unique_names: set[str] = set()
    for index in range(entry_count):
        if position > limit - 2:
            raise InvalidWordDocument(
                f"SttbListNames is truncated before string {index}"
            )
        character_count = struct.unpack_from("<H", table_stream, position)[0]
        position += 2
        if character_count > 0x00FF:
            raise InvalidWordDocument(
                f"SttbListNames string {index} exceeds 255 characters"
            )
        byte_count = character_count * 2
        if position > limit - byte_count:
            raise InvalidWordDocument(
                f"SttbListNames string {index} exceeds its table bounds"
            )
        try:
            value = table_stream[position : position + byte_count].decode(
                "utf-16le"
            )
        except UnicodeDecodeError as exc:
            raise InvalidWordDocument(
                f"SttbListNames string {index} is not valid UTF-16"
            ) from exc
        position += byte_count
        folded = value.casefold()
        if value and folded in unique_names:
            raise InvalidWordDocument(
                f"SttbListNames repeats list name {value!r}"
            )
        if value:
            unique_names.add(folded)
        values.append(value)
    if position != limit:
        raise InvalidWordDocument(
            f"SttbListNames has {limit - position} unexpected trailing bytes"
        )
    if entry_count > list_count:
        report.warning(
            "EXTRA_LIST_NAMES_IGNORED",
            "list names without parallel PlfLst definitions were ignored",
            list_name_count=entry_count,
            list_definition_count=list_count,
        )
    return tuple((values + [""] * list_count)[:list_count])


def _parse_level(
    data: bytes,
    position: int,
    limit: int,
    *,
    level_index: int,
    linked_style_id: int | None,
    font_names: dict[int, str],
    unsupported_paragraph: set[int],
    unsupported_character: set[int],
    approximated_formats: set[int],
    label: str,
) -> tuple[NumberingLevel, int]:
    fixed = _unpack_from(
        "<iBB9sBiiBBBB",
        data,
        position,
        limit,
        label=f"{label}.LVLF",
    )
    (
        start,
        format_code,
        flags,
        raw_placeholder_offsets,
        follow,
        _saved_indent,
        _unused,
        character_size,
        paragraph_size,
        restart_limit,
        _html_flags,
    ) = fixed
    position += _LVLF_SIZE

    justification_code = flags & 0x03
    justification = _JUSTIFICATIONS.get(justification_code)
    if justification is None:
        raise InvalidWordDocument(
            f"{label}.LVLF has invalid justification {justification_code}"
        )
    suffix = _SUFFIXES.get(follow)
    if suffix is None:
        raise InvalidWordDocument(f"{label}.LVLF has invalid ixchFollow {follow}")
    if format_code not in (0x17, 0xFF) and not 0 <= start <= 0x7FFF:
        raise InvalidWordDocument(f"{label}.LVLF has invalid iStartAt {start}")
    number_format = _NUMBER_FORMATS.get(format_code)
    if number_format is None:
        number_format = "decimal"
        approximated_formats.add(format_code)

    zero_index = raw_placeholder_offsets.find(b"\0")
    if zero_index < 0:
        active_placeholder_offsets = tuple(raw_placeholder_offsets)
    else:
        if any(raw_placeholder_offsets[zero_index + 1 :]):
            raise InvalidWordDocument(
                f"{label}.LVLF rgbxchNums is not zero-terminated"
            )
        active_placeholder_offsets = tuple(raw_placeholder_offsets[:zero_index])
    if (
        len(active_placeholder_offsets) > level_index + 1
        or tuple(sorted(set(active_placeholder_offsets)))
        != active_placeholder_offsets
    ):
        raise InvalidWordDocument(f"{label}.LVLF has invalid rgbxchNums")
    if format_code == 0x17 and active_placeholder_offsets:
        raise InvalidWordDocument(f"{label} bullet level contains placeholders")

    paragraph_end = position + paragraph_size
    character_end = paragraph_end + character_size
    if character_end > limit:
        raise InvalidWordDocument(f"{label} property modifiers exceed the Table stream")
    paragraph_modifiers = parse_grpprl(
        data[position:paragraph_end],
        label=f"{label}.grpprlPapx",
    )
    paragraph_properties, unsupported = apply_paragraph_modifiers(
        paragraph_modifiers,
        style_id=None,
    )
    unsupported_paragraph.update(unsupported)
    paragraph_properties = replace(
        paragraph_properties,
        style_id=None,
        numbering_id=None,
        numbering_level=None,
        numbering_suppressed=None,
        numbering_skipped=None,
    )
    character_modifiers = parse_grpprl(
        data[paragraph_end:character_end],
        label=f"{label}.grpprlChpx",
    )
    character_properties, unsupported, _ = apply_character_modifiers(
        character_modifiers,
        font_names=font_names,
    )
    unsupported_character.update(unsupported)
    position = character_end

    (character_count,) = _unpack_from(
        "<H", data, position, limit, label=f"{label}.Xst"
    )
    position += 2
    text_end = position + character_count * 2
    if text_end > limit:
        raise InvalidWordDocument(f"{label}.Xst exceeds the Table stream")
    code_units = (
        struct.unpack_from(f"<{character_count}H", data, position)
        if character_count
        else ()
    )
    if format_code == 0x17 and character_count != 1:
        raise InvalidWordDocument(f"{label} bullet Xst must contain one character")
    text = _decode_level_text(
        tuple(code_units),
        active_placeholder_offsets,
        level=level_index,
        label=label,
    )
    position = text_end

    no_restart = bool(flags & 0x08)
    if no_restart and restart_limit > level_index:
        raise InvalidWordDocument(
            f"{label}.LVLF has invalid ilvlRestartLim {restart_limit}"
        )
    return (
        NumberingLevel(
            level=level_index,
            start=start if format_code not in (0x17, 0xFF) else 1,
            number_format=number_format,
            text=text,
            justification=justification,
            suffix=suffix,
            paragraph_properties=paragraph_properties,
            character_properties=replace(character_properties, style_id=None),
            linked_style_id=linked_style_id,
            legal=bool(flags & 0x04),
            restart_after_level=restart_limit if no_restart else None,
            tentative=bool(flags & 0x80),
        ),
        position,
    )


def _parse_list_definitions(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    level_limit: int,
    font_names: dict[int, str],
    unsupported_paragraph: set[int],
    unsupported_character: set[int],
    approximated_formats: set[int],
) -> tuple[tuple[AbstractNumbering, ...], dict[int, AbstractNumbering]]:
    if size == 0:
        return (), {}
    _check_range(table_stream, offset, size, label="PlfLst")
    if size < 2:
        raise InvalidWordDocument("PlfLst is truncated")
    (list_count,) = struct.unpack_from("<h", table_stream, offset)
    if list_count < 0:
        raise InvalidWordDocument(f"PlfLst has invalid cLst {list_count}")
    expected_size = 2 + list_count * _LSTF_SIZE
    if size != expected_size:
        raise InvalidWordDocument(
            f"PlfLst has size {size}; expected {expected_size} for {list_count} lists"
        )

    headers: list[_ListHeader] = []
    list_ids: set[int] = set()
    position = offset + 2
    for index in range(list_count):
        list_id, _template = struct.unpack_from("<iI", table_stream, position)
        linked_raw = struct.unpack_from("<9h", table_stream, position + 8)
        flags = table_stream[position + 26]
        if list_id == -1 or list_id in list_ids:
            raise InvalidWordDocument(f"PlfLst LSTF {index} has invalid lsid {list_id}")
        list_ids.add(list_id)
        headers.append(
            _ListHeader(
                list_id,
                tuple(None if value == 0x0FFF else value for value in linked_raw),
                simple=bool(flags & 0x01),
                hybrid=bool(flags & 0x10),
            )
        )
        position += _LSTF_SIZE

    position = offset + size
    if level_limit < position or level_limit > len(table_stream):
        raise InvalidWordDocument("PlfLst appended LVL range is invalid")
    abstracts: list[AbstractNumbering] = []
    for abstract_id, header in enumerate(headers):
        level_count = 1 if header.simple else 9
        levels: list[NumberingLevel] = []
        for level_index in range(level_count):
            level, position = _parse_level(
                table_stream,
                position,
                level_limit,
                level_index=level_index,
                linked_style_id=header.linked_style_ids[level_index],
                font_names=font_names,
                unsupported_paragraph=unsupported_paragraph,
                unsupported_character=unsupported_character,
                approximated_formats=approximated_formats,
                label=f"PlfLst list {abstract_id} level {level_index}",
            )
            levels.append(level)
        abstracts.append(
            AbstractNumbering(
                abstract_id=abstract_id,
                source_list_id=header.list_id,
                kind=(
                    "singleLevel"
                    if header.simple
                    else "hybridMultilevel" if header.hybrid else "multilevel"
                ),
                levels=tuple(levels),
            )
        )
    by_list_id = {value.source_list_id: value for value in abstracts}
    return tuple(abstracts), by_list_id


def _parse_list_instances(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    ccp_text: int,
    abstracts_by_list_id: dict[int, AbstractNumbering],
    font_names: dict[int, str],
    unsupported_paragraph: set[int],
    unsupported_character: set[int],
    approximated_formats: set[int],
) -> tuple[NumberingInstance, ...]:
    if size == 0:
        return ()
    _check_range(table_stream, offset, size, label="PlfLfo")
    if size < 4:
        raise InvalidWordDocument("PlfLfo is truncated")
    limit = offset + size
    (instance_count,) = struct.unpack_from("<I", table_stream, offset)
    if instance_count > (size - 4) // (_LFO_SIZE + 4):
        raise InvalidWordDocument(f"PlfLfo has invalid lfoMac {instance_count}")

    headers: list[_LfoHeader] = []
    position = offset + 4
    for index in range(instance_count):
        if position > limit - _LFO_SIZE:
            raise InvalidWordDocument(f"PlfLfo is truncated before LFO {index}")
        list_id = struct.unpack_from("<i", table_stream, position)[0]
        override_count = table_stream[position + 12]
        if override_count > 9:
            raise InvalidWordDocument(
                f"PlfLfo LFO {index} has invalid clfolvl {override_count}"
            )
        if list_id not in abstracts_by_list_id:
            raise InvalidWordDocument(
                f"PlfLfo LFO {index} references unknown lsid {list_id}"
            )
        headers.append(_LfoHeader(list_id, override_count))
        position += _LFO_SIZE

    instances: list[NumberingInstance] = []
    for index, header in enumerate(headers):
        (first_cp,) = _unpack_from(
            "<I", table_stream, position, limit, label=f"PlfLfo LFOData {index}"
        )
        position += 4
        if first_cp != 0xFFFFFFFF and first_cp > ccp_text:
            raise InvalidWordDocument(
                f"PlfLfo LFOData {index} has invalid first paragraph CP {first_cp}"
            )
        abstract = abstracts_by_list_id[header.list_id]
        overrides: list[NumberingLevelOverride] = []
        overridden_levels: set[int] = set()
        for override_index in range(header.override_count):
            start, flags = _unpack_from(
                "<iI",
                table_stream,
                position,
                limit,
                label=f"PlfLfo LFOData {index} LFOLVL {override_index}",
            )
            position += _LFOLVL_SIZE
            level_index = flags & 0x0F
            start_override = bool(flags & 0x10)
            formatting_override = bool(flags & 0x20)
            if level_index > 8 or level_index in overridden_levels:
                raise InvalidWordDocument(
                    f"PlfLfo LFOData {index} has invalid LFOLVL level {level_index}"
                )
            overridden_levels.add(level_index)
            if level_index >= len(abstract.levels):
                raise InvalidWordDocument(
                    f"PlfLfo LFOData {index} overrides an absent level {level_index}"
                )
            if start_override and not formatting_override and not 0 <= start <= 0x7FFF:
                raise InvalidWordDocument(
                    f"PlfLfo LFOData {index} has invalid start override {start}"
                )
            replacement = None
            if formatting_override:
                replacement, position = _parse_level(
                    table_stream,
                    position,
                    limit,
                    level_index=level_index,
                    linked_style_id=abstract.levels[level_index].linked_style_id,
                    font_names=font_names,
                    unsupported_paragraph=unsupported_paragraph,
                    unsupported_character=unsupported_character,
                    approximated_formats=approximated_formats,
                    label=(
                        f"PlfLfo LFOData {index} LFOLVL {override_index} replacement"
                    ),
                )
            overrides.append(
                NumberingLevelOverride(
                    level_index,
                    start=start if start_override and not formatting_override else None,
                    replacement=replacement,
                )
            )
        instances.append(
            NumberingInstance(
                numbering_id=index + 1,
                abstract_id=abstract.abstract_id,
                first_paragraph_cp=(None if first_cp == 0xFFFFFFFF else first_cp),
                overrides=tuple(overrides),
            )
        )
    if position != limit:
        raise InvalidWordDocument(
            f"PlfLfo has {limit - position} unexpected trailing bytes"
        )
    return tuple(instances)


def read_numbering(
    table_stream: bytes,
    *,
    list_offset: int,
    list_size: int,
    lfo_offset: int,
    lfo_size: int,
    ccp_text: int,
    fonts: tuple[FontDefinition, ...],
    report: ConversionReport,
    list_names_offset: int = 0,
    list_names_size: int = 0,
) -> NumberingDefinitions:
    """Parse native list definitions and concrete list instances."""

    if list_size == 0 and lfo_size == 0 and list_names_size == 0:
        return NumberingDefinitions()
    if list_size == 0 and (lfo_size or list_names_size):
        raise InvalidWordDocument("PlfLfo or SttbListNames exists without a PlfLst")
    _check_range(table_stream, list_offset, list_size, label="PlfLst")
    if lfo_size:
        _check_range(table_stream, lfo_offset, lfo_size, label="PlfLfo")
    level_start = list_offset + list_size
    level_limit = (
        lfo_offset
        if lfo_size and lfo_offset >= level_start
        else len(table_stream)
    )
    font_names = {font.index: font.name for font in fonts}
    unsupported_paragraph: set[int] = set()
    unsupported_character: set[int] = set()
    approximated_formats: set[int] = set()
    abstracts, by_list_id = _parse_list_definitions(
        table_stream,
        offset=list_offset,
        size=list_size,
        level_limit=level_limit,
        font_names=font_names,
        unsupported_paragraph=unsupported_paragraph,
        unsupported_character=unsupported_character,
        approximated_formats=approximated_formats,
    )
    list_names = _parse_list_names(
        table_stream,
        offset=list_names_offset,
        size=list_names_size,
        list_count=len(abstracts),
        report=report,
    )
    abstracts = tuple(
        replace(abstract, name=list_names[index] or None)
        for index, abstract in enumerate(abstracts)
    )
    by_list_id = {value.source_list_id: value for value in abstracts}
    instances = _parse_list_instances(
        table_stream,
        offset=lfo_offset,
        size=lfo_size,
        ccp_text=ccp_text,
        abstracts_by_list_id=by_list_id,
        font_names=font_names,
        unsupported_paragraph=unsupported_paragraph,
        unsupported_character=unsupported_character,
        approximated_formats=approximated_formats,
    )
    if unsupported_paragraph:
        report.warning(
            "UNSUPPORTED_LIST_LEVEL_PARAGRAPH_SPRMS",
            "some paragraph formatting in list levels is not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_paragraph)],
        )
    if unsupported_character:
        report.warning(
            "UNSUPPORTED_LIST_LEVEL_CHARACTER_SPRMS",
            "some character formatting in list labels is not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_character)],
        )
    if approximated_formats:
        report.warning(
            "LIST_NUMBER_FORMAT_APPROXIMATED",
            "unknown list number formats were converted to decimal",
            format_codes=[
                f"0x{value:02X}" for value in sorted(approximated_formats)
            ],
        )
    return NumberingDefinitions(abstracts, instances)
