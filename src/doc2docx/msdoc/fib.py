"""File Information Block parsing for Word 97-2003 binary documents."""

from __future__ import annotations

from dataclasses import dataclass

from ..binary import BinaryReader
from ..errors import BinaryBoundsError, InvalidWordDocument


FIB_IDENT = 0xA5EC
# FibRgFcLcb97 includes the deprecated fcPlcPad/lcbPlcPad pair after
# fcPlcfSed/lcbPlcfSed. Therefore fcClx/lcbClx is pair 33 (zero-based).
FCLCB97_STSHF_INDEX = 1
FCLCB97_PLCF_FND_REF_INDEX = 2
FCLCB97_PLCF_FND_TXT_INDEX = 3
FCLCB97_PLCF_AND_REF_INDEX = 4
FCLCB97_PLCF_AND_TXT_INDEX = 5
FCLCB97_PLCF_SED_INDEX = 6
FCLCB97_PLCF_HDD_INDEX = 11
FCLCB97_PLCF_BTE_CHPX_INDEX = 12
FCLCB97_PLCF_BTE_PAPX_INDEX = 13
FCLCB97_STTBF_FFN_INDEX = 15
FCLCB97_PLCF_FLD_HDR_INDEX = 17
FCLCB97_DOP_INDEX = 31
FCLCB97_CLX_INDEX = 33
FCLCB97_GRP_XST_ATN_OWNERS_INDEX = 36
FCLCB97_STTBF_ATN_BKMK_INDEX = 37
FCLCB97_PLC_SPA_MOM_INDEX = 40
FCLCB97_PLC_SPA_HDR_INDEX = 41
FCLCB97_PLCF_ATN_BKF_INDEX = 42
FCLCB97_PLCF_ATN_BKL_INDEX = 43
FCLCB97_PLCF_END_REF_INDEX = 46
FCLCB97_PLCF_END_TXT_INDEX = 47
FCLCB97_DGG_INFO_INDEX = 50
FCLCB97_PLCF_TXBX_TXT_INDEX = 56
FCLCB97_PLCF_FLD_TXBX_INDEX = 57
FCLCB97_PLCF_HDR_TXBX_TXT_INDEX = 58
FCLCB97_PLCF_FLD_HDR_TXBX_INDEX = 59
FCLCB97_PLCF_TXBX_BKD_INDEX = 75
FCLCB97_PLCF_TXBX_HDR_BKD_INDEX = 76


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
    def ccp_footnotes(self) -> int:
        return self.fib_rg_lw[4] if len(self.fib_rg_lw) > 4 else 0

    @property
    def ccp_headers(self) -> int:
        return self.fib_rg_lw[5] if len(self.fib_rg_lw) > 5 else 0

    @property
    def ccp_comments(self) -> int:
        return self.fib_rg_lw[7] if len(self.fib_rg_lw) > 7 else 0

    @property
    def comment_story_cp_start(self) -> int:
        # Main, footnote, header and macro documents precede comments.
        return sum(self.fib_rg_lw[3:7])

    @property
    def ccp_endnotes(self) -> int:
        return self.fib_rg_lw[8] if len(self.fib_rg_lw) > 8 else 0

    @property
    def endnote_story_cp_start(self) -> int:
        # Main, footnote, header, macro and comment documents precede endnotes.
        return sum(self.fib_rg_lw[3:8])

    @property
    def header_story_cp_start(self) -> int:
        return self.ccp_text + self.ccp_footnotes

    @property
    def ccp_header_textboxes(self) -> int:
        return self.fib_rg_lw[10] if len(self.fib_rg_lw) > 10 else 0

    @property
    def ccp_textboxes(self) -> int:
        return self.fib_rg_lw[9] if len(self.fib_rg_lw) > 9 else 0

    @property
    def textbox_story_cp_start(self) -> int:
        # Main, footnote, header, macro, comment and endnote documents precede
        # the main-textbox document in the global CP space.
        return sum(self.fib_rg_lw[3:9])

    @property
    def header_textbox_story_cp_start(self) -> int:
        # Main, footnote, header, macro, comment, endnote and main-textbox
        # documents precede the header-textbox document in the global CP space.
        return sum(self.fib_rg_lw[3:10])

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

    @property
    def stshf(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_STSHF_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_STSHF_INDEX]

    @property
    def plcf_fnd_ref(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_FND_REF_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_FND_REF_INDEX]

    @property
    def plcf_fnd_txt(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_FND_TXT_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_FND_TXT_INDEX]

    @property
    def plcf_and_ref(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_AND_REF_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_AND_REF_INDEX]

    @property
    def plcf_and_txt(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_AND_TXT_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_AND_TXT_INDEX]

    @property
    def grp_xst_atn_owners(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_GRP_XST_ATN_OWNERS_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_GRP_XST_ATN_OWNERS_INDEX]

    @property
    def sttbf_atn_bkmk(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_STTBF_ATN_BKMK_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_STTBF_ATN_BKMK_INDEX]

    @property
    def plcf_atn_bkf(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_ATN_BKF_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_ATN_BKF_INDEX]

    @property
    def plcf_atn_bkl(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_ATN_BKL_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_ATN_BKL_INDEX]

    @property
    def plcf_sed(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_SED_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_SED_INDEX]

    @property
    def plcf_hdd(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_HDD_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_HDD_INDEX]

    @property
    def plcf_fld_hdr(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_FLD_HDR_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_FLD_HDR_INDEX]

    @property
    def dop(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_DOP_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_DOP_INDEX]

    @property
    def plc_spa_hdr(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLC_SPA_HDR_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLC_SPA_HDR_INDEX]

    @property
    def plc_spa_mom(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLC_SPA_MOM_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLC_SPA_MOM_INDEX]

    @property
    def dgg_info(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_DGG_INFO_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_DGG_INFO_INDEX]

    @property
    def plcf_end_ref(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_END_REF_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_END_REF_INDEX]

    @property
    def plcf_end_txt(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_END_TXT_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_END_TXT_INDEX]

    @property
    def plcf_hdr_txbx_txt(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_HDR_TXBX_TXT_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_HDR_TXBX_TXT_INDEX]

    @property
    def plcf_txbx_txt(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_TXBX_TXT_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_TXBX_TXT_INDEX]

    @property
    def plcf_fld_txbx(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_FLD_TXBX_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_FLD_TXBX_INDEX]

    @property
    def plcf_fld_hdr_txbx(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_FLD_HDR_TXBX_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_FLD_HDR_TXBX_INDEX]

    @property
    def plcf_txbx_hdr_bkd(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_TXBX_HDR_BKD_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_TXBX_HDR_BKD_INDEX]

    @property
    def plcf_txbx_bkd(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_TXBX_BKD_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_TXBX_BKD_INDEX]

    @property
    def sttbf_ffn(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_STTBF_FFN_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_STTBF_FFN_INDEX]

    @property
    def plcf_bte_chpx(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_BTE_CHPX_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_BTE_CHPX_INDEX]

    @property
    def plcf_bte_papx(self) -> FcLcb:
        if len(self.fib_rg_fc_lcb) <= FCLCB97_PLCF_BTE_PAPX_INDEX:
            return FcLcb(0, 0)
        return self.fib_rg_fc_lcb[FCLCB97_PLCF_BTE_PAPX_INDEX]

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
