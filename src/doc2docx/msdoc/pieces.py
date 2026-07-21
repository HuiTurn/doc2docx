"""CLX/Piece Table parsing and CP-to-FC text retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import struct

from ..binary import BinaryReader
from ..diagnostics import ConversionReport, SourceLocation
from ..errors import BinaryBoundsError, InvalidWordDocument
from ..model import StoryCharacter
from .sprm import PropertyModifier, parse_grpprl


_COMPRESSED_SPECIAL_CHARACTERS = {
    0x82: "\u201a",
    0x83: "\u0192",
    0x84: "\u201e",
    0x85: "\u2026",
    0x86: "\u2020",
    0x87: "\u2021",
    0x88: "\u02c6",
    0x89: "\u2030",
    0x8A: "\u0160",
    0x8B: "\u2039",
    0x8C: "\u0152",
    0x91: "\u2018",
    0x92: "\u2019",
    0x93: "\u201c",
    0x94: "\u201d",
    0x95: "\u2022",
    0x96: "\u2013",
    0x97: "\u2014",
    0x98: "\u02dc",
    0x99: "\u2122",
    0x9A: "\u0161",
    0x9B: "\u203a",
    0x9C: "\u0153",
    0x9F: "\u0178",
}


# Prm0 stores a seven-bit isprm instead of a full Sprm. These are the useful
# one-byte mappings from the MS-DOC Prm0 table; unknown values stay diagnostic.
_PRM0_SPRMS = {
    0x05: 0x2461,
    0x07: 0x2405,
    0x08: 0x2406,
    0x09: 0x2407,
    0x4D: 0x2A0C,
    0x53: 0x2A33,
    0x55: 0x0835,
    0x56: 0x0836,
    0x57: 0x0837,
    0x5A: 0x083A,
    0x5B: 0x083B,
    0x5C: 0x083C,
    0x5E: 0x2A3E,
    0x62: 0x2A42,
    0x68: 0x2A48,
    0x73: 0x2A53,
}


@dataclass(slots=True, frozen=True)
class Piece:
    cp_start: int
    cp_end: int
    file_offset: int
    compressed: bool
    prm: int

    @property
    def character_count(self) -> int:
        return self.cp_end - self.cp_start


@dataclass(slots=True, frozen=True)
class PieceTable:
    pieces: tuple[Piece, ...]
    word_document_stream: bytes
    prcs: tuple[tuple[PropertyModifier, ...], ...] = ()

    @property
    def cp_start(self) -> int:
        return self.pieces[0].cp_start if self.pieces else 0

    @property
    def cp_end(self) -> int:
        return self.pieces[-1].cp_end if self.pieces else 0

    def extract(
        self,
        cp_start: int,
        cp_end: int,
        report: ConversionReport,
        *,
        story: str,
    ) -> str:
        if cp_start < self.cp_start or cp_end < cp_start or cp_end > self.cp_end:
            raise InvalidWordDocument(
                f"requested CP range [{cp_start}, {cp_end}) is outside Piece Table "
                f"range [{self.cp_start}, {self.cp_end})"
            )

        return "".join(
            unit.text
            for unit in self.extract_characters(
                cp_start,
                cp_end,
                report,
                story=story,
            )
        )

    def extract_characters(
        self,
        cp_start: int,
        cp_end: int,
        report: ConversionReport,
        *,
        story: str,
    ) -> tuple[StoryCharacter, ...]:
        """Decode a CP range while retaining UTF-16 code-unit coordinates."""

        if cp_start < self.cp_start or cp_end < cp_start or cp_end > self.cp_end:
            raise InvalidWordDocument(
                f"requested CP range [{cp_start}, {cp_end}) is outside Piece Table "
                f"range [{self.cp_start}, {self.cp_end})"
            )

        characters: list[StoryCharacter] = []
        invalid_utf16_ranges: list[tuple[int, int, int, int]] = []
        for piece in self.pieces:
            start = max(cp_start, piece.cp_start)
            end = min(cp_end, piece.cp_end)
            if start >= end:
                continue
            relative_start = start - piece.cp_start
            character_count = end - start
            bytes_per_character = 1 if piece.compressed else 2
            byte_start = piece.file_offset + relative_start * bytes_per_character
            byte_length = character_count * bytes_per_character
            byte_end = byte_start + byte_length
            if byte_start < 0 or byte_end > len(self.word_document_stream):
                raise InvalidWordDocument(
                    f"piece CP [{piece.cp_start}, {piece.cp_end}) references "
                    f"WordDocument bytes [{byte_start}, {byte_end}) outside the stream"
                )
            raw = self.word_document_stream[byte_start:byte_end]
            if piece.compressed:
                characters.extend(
                    StoryCharacter(
                        _COMPRESSED_SPECIAL_CHARACTERS.get(value, chr(value)),
                        start + index,
                        start + index + 1,
                    )
                    for index, value in enumerate(raw)
                )
            else:
                code_units = struct.unpack(f"<{len(raw) // 2}H", raw)
                index = 0
                while index < len(code_units):
                    code_unit = code_units[index]
                    unit_cp = start + index
                    if (
                        0xD800 <= code_unit <= 0xDBFF
                        and index + 1 < len(code_units)
                        and 0xDC00 <= code_units[index + 1] <= 0xDFFF
                    ):
                        low = code_units[index + 1]
                        scalar = 0x10000 + (
                            ((code_unit - 0xD800) << 10) | (low - 0xDC00)
                        )
                        characters.append(
                            StoryCharacter(chr(scalar), unit_cp, unit_cp + 2)
                        )
                        index += 2
                        continue
                    if 0xD800 <= code_unit <= 0xDFFF:
                        characters.append(
                            StoryCharacter("\uFFFD", unit_cp, unit_cp + 1)
                        )
                        invalid_utf16_ranges.append(
                            (
                                unit_cp,
                                unit_cp + 1,
                                byte_start + index * 2,
                                byte_start + index * 2 + 2,
                            )
                        )
                    else:
                        characters.append(
                            StoryCharacter(chr(code_unit), unit_cp, unit_cp + 1)
                        )
                    index += 1

        for invalid_cp_start, invalid_cp_end, invalid_fc_start, invalid_fc_end in (
            invalid_utf16_ranges
        ):
            report.warning(
                "INVALID_UTF16",
                "invalid UTF-16LE code unit was replaced while reading text",
                location=SourceLocation(
                    story=story,
                    cp_start=invalid_cp_start,
                    cp_end=invalid_cp_end,
                    stream="WordDocument",
                    fc_start=invalid_fc_start,
                    fc_end=invalid_fc_end,
                ),
            )
        return tuple(characters)

    def fc_range_to_cp_ranges(
        self,
        fc_start: int,
        fc_end: int,
    ) -> tuple[tuple[int, int], ...]:
        """Intersect a physical FC range with pieces and return CP ranges."""

        if fc_start < 0 or fc_end < fc_start:
            raise InvalidWordDocument(
                f"invalid FC range [{fc_start}, {fc_end})"
            )
        ranges: list[tuple[int, int]] = []
        for piece in self.pieces:
            width = 1 if piece.compressed else 2
            piece_fc_start = piece.file_offset
            piece_fc_end = piece.file_offset + piece.character_count * width
            start = max(fc_start, piece_fc_start)
            end = min(fc_end, piece_fc_end)
            if start >= end:
                continue
            if not piece.compressed and (
                (start - piece_fc_start) % 2 or (end - piece_fc_start) % 2
            ):
                raise InvalidWordDocument(
                    f"FKP FC range [{fc_start}, {fc_end}) splits a UTF-16 code unit"
                )
            cp_range_start = piece.cp_start + (start - piece_fc_start) // width
            cp_range_end = piece.cp_start + (end - piece_fc_start) // width
            ranges.append((cp_range_start, cp_range_end))
        return tuple(ranges)

    def modifiers_for_piece(
        self,
        piece: Piece,
        *,
        property_group: int,
    ) -> tuple[PropertyModifier, ...]:
        """Resolve a PCD Prm and retain only modifiers for one sgc group."""

        if piece.prm == 0:
            return ()
        if piece.prm & 1:
            index = piece.prm >> 1
            if index >= len(self.prcs):
                raise InvalidWordDocument(
                    f"piece Prm references PRC {index}, but CLX has {len(self.prcs)}"
                )
            modifiers = self.prcs[index]
        else:
            isprm = (piece.prm >> 1) & 0x7F
            opcode = _PRM0_SPRMS.get(isprm)
            if opcode is None:
                return ()
            modifiers = (PropertyModifier(opcode, bytes((piece.prm >> 8,))),)
        return tuple(
            modifier
            for modifier in modifiers
            if ((modifier.opcode >> 10) & 0x07) == property_group
        )


def _parse_plc_pcd(
    data: bytes,
    word_document_stream: bytes,
    prcs: tuple[tuple[PropertyModifier, ...], ...],
) -> PieceTable:
    if len(data) < 4 or (len(data) - 4) % 12:
        raise InvalidWordDocument(
            f"PlcPcd size {len(data)} does not match the 12*n+4 layout"
        )
    piece_count = (len(data) - 4) // 12
    if piece_count == 0:
        raise InvalidWordDocument("PlcPcd contains no pieces")

    cp_count = piece_count + 1
    cps = struct.unpack_from(f"<{cp_count}I", data, 0)
    if cps[0] != 0:
        raise InvalidWordDocument(f"Piece Table starts at CP {cps[0]}, expected 0")
    for previous, current in zip(cps, cps[1:]):
        if current <= previous or current >= 0x7FFFFFFF:
            raise InvalidWordDocument(
                "Piece Table CP values must be strictly increasing and valid"
            )

    pieces: list[Piece] = []
    pcd_offset = cp_count * 4
    for index in range(piece_count):
        record = data[pcd_offset + index * 8 : pcd_offset + (index + 1) * 8]
        raw_fc = struct.unpack_from("<I", record, 2)[0]
        prm = struct.unpack_from("<H", record, 6)[0]
        compressed = bool(raw_fc & 0x40000000)
        if raw_fc & 0x80000000:
            raise InvalidWordDocument("FcCompressed reserved bit is set")
        encoded_fc = raw_fc & 0x3FFFFFFF
        if compressed:
            if encoded_fc & 1:
                raise InvalidWordDocument("compressed piece has an odd encoded FC")
            file_offset = encoded_fc // 2
        else:
            file_offset = encoded_fc
        pieces.append(
            Piece(
                cp_start=cps[index],
                cp_end=cps[index + 1],
                file_offset=file_offset,
                compressed=compressed,
                prm=prm,
            )
        )
    return PieceTable(tuple(pieces), word_document_stream, prcs)


def read_piece_table(
    table_stream: bytes,
    word_document_stream: bytes,
    *,
    fc_clx: int,
    lcb_clx: int,
    report: ConversionReport,
) -> PieceTable:
    if lcb_clx < 5:
        raise InvalidWordDocument(f"CLX is too small ({lcb_clx} bytes)")
    if fc_clx > len(table_stream) - lcb_clx:
        raise InvalidWordDocument(
            f"CLX range [{fc_clx}, {fc_clx + lcb_clx}) exceeds Table stream"
        )

    reader = BinaryReader(
        table_stream[fc_clx : fc_clx + lcb_clx],
        label="CLX",
        base_offset=fc_clx,
    )
    prcs: list[tuple[PropertyModifier, ...]] = []
    try:
        while reader.remaining:
            clxt = reader.u8()
            if clxt == 0x01:
                grpprl_size = reader.u16()
                if grpprl_size > 0x3FA2:
                    raise InvalidWordDocument(
                        f"CLX PRC has invalid grpprl size {grpprl_size}"
                    )
                grpprl = reader.read(grpprl_size)
                prcs.append(
                    parse_grpprl(
                        grpprl,
                        label=f"CLX.Prc[{len(prcs)}].grpprl",
                    )
                )
                continue
            if clxt == 0x02:
                plc_size = reader.u32()
                plc_data = reader.read(plc_size)
                if reader.remaining:
                    report.warning(
                        "CLX_TRAILING_DATA",
                        "bytes after the Pcdt in CLX were ignored",
                        byte_count=reader.remaining,
                    )
                piece_table = _parse_plc_pcd(
                    plc_data,
                    word_document_stream,
                    tuple(prcs),
                )
                unknown_prm0 = sorted(
                    {
                        (piece.prm >> 1) & 0x7F
                        for piece in piece_table.pieces
                        if piece.prm
                        and not piece.prm & 1
                        and ((piece.prm >> 1) & 0x7F) not in _PRM0_SPRMS
                    }
                )
                if unknown_prm0:
                    report.warning(
                        "UNSUPPORTED_PRM0_VALUES",
                        "some compact piece-level property modifiers are not supported",
                        isprm=[f"0x{value:02X}" for value in unknown_prm0],
                    )
                # Validate all complex references even if their property group
                # is not implemented yet.
                for piece in piece_table.pieces:
                    if piece.prm & 1 and piece.prm >> 1 >= len(prcs):
                        raise InvalidWordDocument(
                            f"piece Prm references PRC {piece.prm >> 1}, "
                            f"but CLX has {len(prcs)}"
                        )
                return piece_table
            raise InvalidWordDocument(f"CLX contains unknown clxt 0x{clxt:02X}")
    except BinaryBoundsError as exc:
        raise InvalidWordDocument(f"truncated CLX/Piece Table: {exc}") from exc

    raise InvalidWordDocument("CLX does not contain a Pcdt/Piece Table")
