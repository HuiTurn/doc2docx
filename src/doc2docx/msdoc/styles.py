"""MS-DOC STSH style-sheet parsing and inheritance resolution."""

from __future__ import annotations

from dataclasses import dataclass, replace
import struct

from ..diagnostics import ConversionReport
from ..errors import InvalidWordDocument
from ..model import (
    CharacterProperties,
    FontDefinition,
    ParagraphProperties,
    StyleDefinition,
    StyleSheet,
)
from .sprm import (
    PropertyModifier,
    apply_character_modifiers,
    apply_paragraph_modifiers,
    merge_character_properties,
    merge_paragraph_properties,
    parse_grpprl,
)


_STYLE_KINDS = {1: "paragraph", 2: "character", 3: "table", 4: "numbering"}


@dataclass(slots=True, frozen=True)
class _RawStyle:
    index: int
    name: str
    kind: str
    based_on: int | None
    next_style: int | None
    table_modifiers: tuple[PropertyModifier, ...]
    paragraph_modifiers: tuple[PropertyModifier, ...]
    character_modifiers: tuple[PropertyModifier, ...]


def _font_name(fonts: tuple[FontDefinition, ...], index: int) -> str | None:
    if 0 <= index < len(fonts):
        return fonts[index].name
    return None


def _read_xstz(data: bytes, position: int, *, label: str) -> tuple[str, int]:
    if position > len(data) - 2:
        raise InvalidWordDocument(f"{label} has a truncated Xstz")
    character_count = struct.unpack_from("<H", data, position)[0]
    position += 2
    byte_count = character_count * 2
    end = position + byte_count
    if end > len(data) - 2:
        raise InvalidWordDocument(f"{label} style name exceeds STD")
    name = data[position:end].decode("utf-16le", errors="replace")
    if struct.unpack_from("<H", data, end)[0] != 0:
        raise InvalidWordDocument(f"{label} style name is not null-terminated")
    return name, end + 2


def _read_lpupx(data: bytes, position: int, *, label: str) -> tuple[bytes, int]:
    if position > len(data) - 2:
        raise InvalidWordDocument(f"{label} has a truncated LPUpx")
    byte_count = struct.unpack_from("<H", data, position)[0]
    position += 2
    end = position + byte_count
    if end > len(data):
        raise InvalidWordDocument(f"{label} LPUpx exceeds STD")
    value = data[position:end]
    position = end + (byte_count & 1)
    if position > len(data):
        raise InvalidWordDocument(f"{label} LPUpx padding exceeds STD")
    return value, position


def _parse_std(
    index: int,
    data: bytes,
    *,
    base_size: int,
) -> _RawStyle:
    label = f"STSH style {index}"
    if base_size not in (10, 18) or len(data) < base_size:
        raise InvalidWordDocument(
            f"{label} has invalid STD base size {base_size}"
        )
    _, base_word, upx_word = struct.unpack_from("<HHH", data)
    style_kind_code = base_word & 0x0F
    based_on_raw = (base_word >> 4) & 0x0FFF
    upx_count = upx_word & 0x0F
    next_raw = (upx_word >> 4) & 0x0FFF
    kind = _STYLE_KINDS.get(style_kind_code, "unknown")
    name, position = _read_xstz(data, base_size, label=label)

    upx_values: list[bytes] = []
    for upx_index in range(upx_count):
        value, position = _read_lpupx(
            data,
            position,
            label=f"{label} UPX {upx_index}",
        )
        upx_values.append(value)
    if position != len(data) and any(data[position:]):
        raise InvalidWordDocument(
            f"{label} has {len(data) - position} unexpected trailing bytes"
        )

    table_modifiers: tuple[PropertyModifier, ...] = ()
    paragraph_modifiers: tuple[PropertyModifier, ...] = ()
    character_modifiers: tuple[PropertyModifier, ...] = ()
    if kind == "paragraph":
        if upx_values:
            if len(upx_values[0]) < 2:
                raise InvalidWordDocument(f"{label} UpxPapx has no istd")
            paragraph_modifiers = parse_grpprl(
                upx_values[0][2:],
                label=f"{label}.UpxPapx.grpprl",
                allow_trailing_zero_padding=True,
            )
        if len(upx_values) >= 2:
            character_modifiers = parse_grpprl(
                upx_values[1],
                label=f"{label}.UpxChpx.grpprl",
                allow_trailing_zero_padding=True,
            )
    elif kind == "character" and upx_values:
        character_modifiers = parse_grpprl(
            upx_values[0],
            label=f"{label}.UpxChpx.grpprl",
            allow_trailing_zero_padding=True,
        )
    elif kind == "table":
        # StkTableGRLPUPX stores optional TAPX, PAPX, and CHPX values in
        # exactly this order. UpxPapx begins with an istd just like a
        # paragraph-style UpxPapx; UpxChpx is a bare grpprl.
        if upx_values:
            table_modifiers = parse_grpprl(
                upx_values[0],
                label=f"{label}.UpxTapx.grpprl",
                allow_trailing_zero_padding=True,
            )
        if len(upx_values) >= 2:
            if len(upx_values[1]) < 2:
                raise InvalidWordDocument(f"{label} UpxPapx has no istd")
            paragraph_modifiers = parse_grpprl(
                upx_values[1][2:],
                label=f"{label}.UpxPapx.grpprl",
                allow_trailing_zero_padding=True,
            )
        if len(upx_values) >= 3:
            character_modifiers = parse_grpprl(
                upx_values[2],
                label=f"{label}.UpxChpx.grpprl",
                allow_trailing_zero_padding=True,
            )

    return _RawStyle(
        index=index,
        name=name or f"Style {index}",
        kind=kind,
        based_on=None if based_on_raw == 0x0FFF else based_on_raw,
        next_style=None if next_raw == 0x0FFF else next_raw,
        table_modifiers=table_modifiers,
        paragraph_modifiers=paragraph_modifiers,
        character_modifiers=character_modifiers,
    )


def read_style_sheet(
    table_stream: bytes,
    *,
    offset: int,
    size: int,
    fonts: tuple[FontDefinition, ...],
    report: ConversionReport,
) -> StyleSheet:
    if size == 0:
        return StyleSheet()
    if offset < 0 or size < 0 or offset > len(table_stream) - size:
        raise InvalidWordDocument(
            f"STSH range [{offset}, {offset + size}) exceeds Table stream"
        )
    data = table_stream[offset : offset + size]
    if len(data) < 20:
        raise InvalidWordDocument("STSH is truncated")
    stshi_size = struct.unpack_from("<H", data)[0]
    if stshi_size < 18 or stshi_size > len(data) - 2:
        raise InvalidWordDocument(f"STSH has invalid cbStshi {stshi_size}")
    stshi = data[2 : 2 + stshi_size]
    style_count, base_size = struct.unpack_from("<HH", stshi)
    if base_size not in (10, 18):
        raise InvalidWordDocument(
            f"STSH has unsupported cbSTDBaseInFile {base_size}"
        )
    default_ascii, default_east_asia, default_other = struct.unpack_from(
        "<hhh", stshi, 12
    )
    # ftcBi lives in the versioned tail of STSHI rather than at a stable
    # Stshif offset, so leave it unspecified until that tail is interpreted.
    default_complex = -1
    default_character = CharacterProperties(
        ascii_font=_font_name(fonts, default_ascii),
        high_ansi_font=_font_name(fonts, default_other),
        east_asia_font=_font_name(fonts, default_east_asia),
        complex_script_font=_font_name(fonts, default_complex),
    )

    raw_styles: list[_RawStyle | None] = []
    position = 2 + stshi_size
    for index in range(style_count):
        if position > len(data) - 2:
            raise InvalidWordDocument(f"STSH is truncated before style {index}")
        std_size = struct.unpack_from("<H", data, position)[0]
        position += 2
        if std_size == 0:
            raw_styles.append(None)
            continue
        end = position + std_size
        if end > len(data):
            raise InvalidWordDocument(f"STSH style {index} exceeds the table")
        raw_styles.append(_parse_std(index, data[position:end], base_size=base_size))
        position = end + (std_size & 1)
    if position > len(data):
        raise InvalidWordDocument("STSH style padding exceeds the table")

    font_names = {font.index: font.name for font in fonts}
    definitions: list[StyleDefinition | None] = [None] * style_count
    effective_paragraphs: list[ParagraphProperties | None] = [None] * style_count
    effective_characters: list[CharacterProperties | None] = [None] * style_count
    visiting: set[int] = set()
    unsupported_character: set[int] = set()
    unsupported_paragraph: set[int] = set()
    unsupported_table: set[int] = set()

    def resolve(index: int) -> None:
        if definitions[index] is not None or raw_styles[index] is None:
            return
        if index in visiting:
            raise InvalidWordDocument(f"STSH style inheritance cycle at style {index}")
        visiting.add(index)
        raw = raw_styles[index]
        assert raw is not None
        parent_paragraph = ParagraphProperties()
        parent_character = default_character
        if raw.based_on is not None and 0 <= raw.based_on < style_count:
            resolve(raw.based_on)
            if effective_paragraphs[raw.based_on] is not None:
                parent_paragraph = effective_paragraphs[raw.based_on]  # type: ignore[assignment]
            if effective_characters[raw.based_on] is not None:
                parent_character = effective_characters[raw.based_on]  # type: ignore[assignment]

        # A sprmTIstd inside UpxTapx identifies the style itself and MUST be
        # ignored while applying that style. Other supported table modifiers
        # are retained in table_row so they can be emitted in w:tblPr.
        table_paragraph, unsupported = apply_paragraph_modifiers(
            tuple(
                modifier
                for modifier in raw.table_modifiers
                if modifier.opcode != 0x563A
            ),
            style_id=None,
        )
        unsupported_table.update(unsupported)
        direct_paragraph, unsupported = apply_paragraph_modifiers(
            raw.paragraph_modifiers,
            style_id=None,
            initial_properties=table_paragraph,
        )
        unsupported_paragraph.update(unsupported)
        direct_character, unsupported, _ = apply_character_modifiers(
            raw.character_modifiers,
            base_properties=parent_character,
            font_names=font_names,
        )
        unsupported_character.update(unsupported)
        effective_paragraph = merge_paragraph_properties(
            parent_paragraph,
            direct_paragraph,
        )
        effective_character = merge_character_properties(
            parent_character,
            replace(direct_character, style_id=None),
        )
        definitions[index] = StyleDefinition(
            index=index,
            name=raw.name,
            kind=raw.kind,
            based_on=raw.based_on,
            next_style=raw.next_style,
            paragraph_properties=direct_paragraph,
            character_properties=direct_character,
        )
        effective_paragraphs[index] = effective_paragraph
        effective_characters[index] = effective_character
        visiting.remove(index)

    for style_index in range(style_count):
        resolve(style_index)

    if unsupported_character:
        report.warning(
            "UNSUPPORTED_STYLE_CHARACTER_SPRMS",
            "some character properties in the DOC style sheet are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_character)],
        )
    if unsupported_paragraph:
        report.warning(
            "UNSUPPORTED_STYLE_PARAGRAPH_SPRMS",
            "some paragraph properties in the DOC style sheet are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_paragraph)],
        )
    if unsupported_table:
        report.warning(
            "UNSUPPORTED_STYLE_TABLE_SPRMS",
            "some table properties in the DOC style sheet are not yet supported",
            opcodes=[f"0x{value:04X}" for value in sorted(unsupported_table)],
        )
    deferred_kinds = sorted(
        {raw.kind for raw in raw_styles if raw is not None}
        - {"paragraph", "character", "table"}
    )
    if deferred_kinds:
        report.warning(
            "STYLE_KINDS_DEFERRED",
            "table, numbering, or unknown style kinds were parsed but not emitted",
            kinds=deferred_kinds,
        )

    return StyleSheet(
        styles=tuple(definitions),
        default_character_properties=default_character,
        effective_character_properties=tuple(effective_characters),
    )
