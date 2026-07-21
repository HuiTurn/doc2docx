"""File Information Block parsing for Word 97-2003 binary documents."""

from __future__ import annotations

from dataclasses import dataclass

from ..binary import BinaryReader
from ..errors import BinaryBoundsError, InvalidWordDocument


FIB_IDENT = 0xA5EC
# FibRgFcLcb97 includes the deprecated fcPlcPad/lcbPlcPad pair after
# fcPlcfSed/lcbPlcfSed. Therefore fcClx/lcbClx is pair 33 (zero-based).
FCLCB97_CLX_INDEX = 33


@dataclass(slots=True, frozen=True)
class FibBase:
    w_ident: int
    n_fib: int
    lid: int
    flags: int
    n_fib_back: int
    l_key: int
    environment: int
    flags2: int

    @property
    def is_template(self) -> bool:
        return bool(self.flags & 0x0001)

    @property
    def is_complex(self) -> bool:
        return bool(self.flags & 0x0004)

    @property
    def has_pictures(self) -> bool:
        return bool(self.flags & 0x0008)

    @property
    def is_encrypted(self) -> bool:
        return bool(self.flags & 0x0100)

    @property
    def uses_1table(self) -> bool:
        return bool(self.flags & 0x0200)

    @property
    def is_write_reserved(self) -> bool:
        return bool(self.flags & 0x0800)

    @property
    def is_obfuscated(self) -> bool:
        return bool(self.flags & 0x8000)

    @property
    def table_stream_name(self) -> str:
        return "1Table" if self.uses_1table else "0Table"


@dataclass(slots=True, frozen=True)
class FcLcb:
    fc: int
    lcb: int


@dataclass(slots=True, frozen=True)
class FileInformationBlock:
    base: FibBase
    fib_rg_w: tuple[int, ...]
    fib_rg_lw: tuple[int, ...]
    fib_rg_fc_lcb: tuple[FcLcb, ...]
    fib_rg_csw_new: tuple[int, ...]
    fib_size: int

    @property
    def n_fib(self) -> int:
        return self.fib_rg_csw_new[0] if self.fib_rg_csw_new else self.base.n_fib

    @property
    def ccp_text(self) -> int:
        if len(self.fib_rg_lw) <= 3:
            raise InvalidWordDocument("FIB does not contain FibRgLw97.ccpText")
        return self.fib_rg_lw[3]

    @property
    def cb_mac(self) -> int:
        if not self.fib_rg_lw:
            raise InvalidWordDocument("FIB does not contain FibRgLw97.cbMac")
        return self.fib_rg_lw[0]

    @property
    def secondary_story_character_counts(self) -> dict[str, int]:
        names_and_indexes = (
            ("footnotes", 4),
            ("headers", 5),
            ("comments", 7),
            ("endnotes", 8),
            ("textboxes", 9),
            ("header_textboxes", 10),
        )
        return {
            name: self.fib_rg_lw[index]
            for name, index in names_and_indexes
            if index < len(self.fib_rg_lw) and self.fib_rg_lw[index]
        }

    @property
    def clx(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_CLX_INDEX:
            raise InvalidWordDocument("FIB does not contain fcClx/lcbClx")
        return self.fib_rg_fc_lcb[FCLCB97_CLX_INDEX]

    @classmethod
    def parse(cls, word_document_stream: bytes) -> "FileInformationBlock":
        reader = BinaryReader(word_document_stream, label="WordDocument FIB")
        try:
            w_ident = reader.u16()
            n_fib = reader.u16()
            reader.skip(2)  # unused
            lid = reader.u16()
            reader.skip(2)  # pnNext
            flags = reader.u16()
            n_fib_back = reader.u16()
            l_key = reader.u32()
            environment = reader.u8()
            flags2 = reader.u8()
            reader.skip(12)  # reserved3 through reserved6

            if w_ident != FIB_IDENT:
                raise InvalidWordDocument(
                    f"WordDocument FIB has wIdent 0x{w_ident:04X}; expected 0xA5EC"
                )

            csw = reader.u16()
            fib_rg_w = tuple(reader.u16() for _ in range(csw))

            cslw = reader.u16()
            fib_rg_lw = tuple(reader.u32() for _ in range(cslw))

            cb_rg_fc_lcb = reader.u16()
            fib_rg_fc_lcb = tuple(
                FcLcb(reader.u32(), reader.u32()) for _ in range(cb_rg_fc_lcb)
            )
            if reader.remaining >= 2:
                csw_new = reader.u16()
                fib_rg_csw_new = tuple(reader.u16() for _ in range(csw_new))
            else:
                fib_rg_csw_new = ()
        except BinaryBoundsError as exc:
            raise InvalidWordDocument(f"truncated or invalid FIB: {exc}") from exc

        if csw < 14:
            raise InvalidWordDocument(
                f"FIB FibRgW has {csw} words; Word 97 layout requires at least 14"
            )
        if cslw < 11:
            raise InvalidWordDocument(
                f"FIB FibRgLw has {cslw} values; expected at least 11"
            )
        if cb_rg_fc_lcb <= FCLCB97_CLX_INDEX:
            raise InvalidWordDocument(
                f"FIB has {cb_rg_fc_lcb} fc/lcb pairs and no CLX entry"
            )
        ccp_text = fib_rg_lw[3]
        if ccp_text >= 0x7FFFFFFF:
            raise InvalidWordDocument(f"invalid main-story character count {ccp_text}")

        return cls(
            base=FibBase(
                w_ident,
                n_fib,
                lid,
                flags,
                n_fib_back,
                l_key,
                environment,
                flags2,
            ),
            fib_rg_w=fib_rg_w,
            fib_rg_lw=fib_rg_lw,
            fib_rg_fc_lcb=fib_rg_fc_lcb,
            fib_rg_csw_new=fib_rg_csw_new,
            fib_size=reader.position,
        )
