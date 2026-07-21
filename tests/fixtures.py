"""Programmatically constructed CFB/MS-DOC fixtures for deterministic tests."""

from __future__ import annotations

import struct

from doc2docx.cfb.constants import ENDOFCHAIN, FATSECT, FREESECT, NOSTREAM


SECTOR_SIZE = 512


def _directory_entry(
    name: str,
    object_type: int,
    *,
    left: int = NOSTREAM,
    right: int = NOSTREAM,
    child: int = NOSTREAM,
    start: int = ENDOFCHAIN,
    size: int = 0,
) -> bytes:
    entry = bytearray(128)
    encoded_name = (name + "\0").encode("utf-16le") if name else b""
    if len(encoded_name) > 64:
        raise ValueError("fixture directory name is too long")
    entry[: len(encoded_name)] = encoded_name
    struct.pack_into("<H", entry, 64, len(encoded_name))
    entry[66] = object_type
    entry[67] = 1
    struct.pack_into("<III", entry, 68, left, right, child)
    struct.pack_into("<I", entry, 116, start)
    struct.pack_into("<Q", entry, 120, size)
    return bytes(entry)


def _header(
    *,
    fat_sector: int,
    directory_sector: int,
    mini_fat_sector: int = ENDOFCHAIN,
    mini_fat_count: int = 0,
) -> bytes:
    header = bytearray(SECTOR_SIZE)
    header[:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<HHHHH", header, 24, 0x003E, 3, 0xFFFE, 9, 6)
    struct.pack_into(
        "<IIIIIIIII",
        header,
        40,
        0,
        1,
        directory_sector,
        0,
        0x1000,
        mini_fat_sector,
        mini_fat_count,
        ENDOFCHAIN,
        0,
    )
    difat = [FREESECT] * 109
    difat[0] = fat_sector
    struct.pack_into("<109I", header, 76, *difat)
    return bytes(header)


def _build_fib(
    *,
    ccp_text: int,
    clx_size: int,
    ccp_footnotes: int = 0,
    ccp_headers: int = 0,
    ccp_header_textboxes: int = 0,
    section_plc: tuple[int, int] = (0, 0),
    header_plc: tuple[int, int] = (0, 0),
    header_shape_plc: tuple[int, int] = (0, 0),
    header_textbox_plc: tuple[int, int] = (0, 0),
    header_textbox_field_plc: tuple[int, int] = (0, 0),
    header_textbox_break_plc: tuple[int, int] = (0, 0),
    chpx_plc: tuple[int, int] = (0, 0),
    papx_plc: tuple[int, int] = (0, 0),
    dop: tuple[int, int] = (0, 0),
    cb_mac: int = 1110,
    encrypted: bool = False,
    uses_1table: bool = True,
) -> bytes:
    fib = bytearray(1024)
    flags = 0x1000  # fExtChar
    if uses_1table:
        flags |= 0x0200
    if encrypted:
        flags |= 0x0100
    struct.pack_into("<H", fib, 0, 0xA5EC)
    struct.pack_into("<H", fib, 2, 0x00C1)
    struct.pack_into("<H", fib, 6, 0x0409)
    struct.pack_into("<H", fib, 10, flags)
    struct.pack_into("<H", fib, 12, 0x00BF)

    position = 32
    struct.pack_into("<H", fib, position, 14)
    position += 2 + 14 * 2
    struct.pack_into("<H", fib, position, 22)
    position += 2
    fib_rg_lw = [0] * 22
    fib_rg_lw[0] = cb_mac
    fib_rg_lw[3] = ccp_text
    fib_rg_lw[4] = ccp_footnotes
    fib_rg_lw[5] = ccp_headers
    fib_rg_lw[10] = ccp_header_textboxes
    struct.pack_into("<22I", fib, position, *fib_rg_lw)
    position += 22 * 4
    struct.pack_into("<H", fib, position, 93)
    position += 2
    pairs = [(0, 0)] * 93
    pairs[6] = section_plc
    pairs[11] = header_plc
    pairs[12] = chpx_plc
    pairs[13] = papx_plc
    pairs[31] = dop
    pairs[33] = (0, clx_size)
    pairs[41] = header_shape_plc
    pairs[58] = header_textbox_plc
    pairs[59] = header_textbox_field_plc
    pairs[76] = header_textbox_break_plc
    for fc, lcb in pairs:
        struct.pack_into("<II", fib, position, fc, lcb)
        position += 8
    return bytes(fib)


def _wrap_regular_word_streams(
    word_document: bytes | bytearray,
    table_stream: bytes | bytearray,
    *,
    uses_1table: bool = True,
) -> bytes:
    if len(word_document) != 4096 or len(table_stream) != 4096:
        raise ValueError("fixture WordDocument and Table streams must be 4096 bytes")
    sectors = [bytearray(SECTOR_SIZE) for _ in range(18)]
    for index in range(8):
        sectors[index][:] = word_document[index * 512 : (index + 1) * 512]
        sectors[8 + index][:] = table_stream[index * 512 : (index + 1) * 512]

    directory = bytearray(SECTOR_SIZE)
    directory[0:128] = _directory_entry("Root Entry", 5, child=1)
    directory[128:256] = _directory_entry(
        "WordDocument", 2, right=2, start=0, size=4096
    )
    table_name = "1Table" if uses_1table else "0Table"
    directory[256:384] = _directory_entry(table_name, 2, start=8, size=4096)
    sectors[16][:] = directory

    fat = [FREESECT] * 128
    for start in (0, 8):
        for sector_id in range(start, start + 7):
            fat[sector_id] = sector_id + 1
        fat[start + 7] = ENDOFCHAIN
    fat[16] = ENDOFCHAIN
    fat[17] = FATSECT
    struct.pack_into("<128I", sectors[17], 0, *fat)
    return _header(fat_sector=17, directory_sector=16) + b"".join(sectors)


def build_sectioned_word_cfb() -> bytes:
    """A two-section DOC with a continuous break and landscape final section."""

    text = b"Portrait\fLandscape\r"
    text_fc = 1024
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    def section_grpprl(
        *,
        break_kind: int,
        orientation: int,
        width: int,
        height: int,
        left: int,
        right: int,
        top: int,
        bottom: int,
        header: int,
        footer: int,
        gutter: int,
        grid_type: int,
        grid_line_pitch: int,
        grid_character_space: int,
    ) -> bytes:
        return b"".join(
            (
                struct.pack("<HB", 0x3009, break_kind),
                struct.pack("<HB", 0x301D, orientation),
                struct.pack("<HH", 0xB01F, width),
                struct.pack("<HH", 0xB020, height),
                struct.pack("<HH", 0xB021, left),
                struct.pack("<HH", 0xB022, right),
                struct.pack("<Hh", 0x9023, top),
                struct.pack("<Hh", 0x9024, bottom),
                struct.pack("<HH", 0xB017, header),
                struct.pack("<HH", 0xB018, footer),
                struct.pack("<HH", 0xB025, gutter),
                struct.pack("<Hi", 0x7030, grid_character_space),
                struct.pack("<HH", 0x9031, grid_line_pitch),
                struct.pack("<HH", 0x5032, grid_type),
            )
        )

    first_sepx_fc = 1200
    second_sepx_fc = 1300
    first_grpprl = section_grpprl(
        break_kind=0,
        orientation=1,
        width=12240,
        height=15840,
        left=1440,
        right=1440,
        top=1440,
        bottom=1440,
        header=720,
        footer=720,
        gutter=0,
        grid_type=2,
        grid_line_pitch=312,
        grid_character_space=0,
    )
    second_grpprl = section_grpprl(
        break_kind=2,
        orientation=2,
        width=15840,
        height=12240,
        left=1000,
        right=1100,
        top=-900,
        bottom=1200,
        header=500,
        footer=600,
        gutter=100,
        grid_type=3,
        grid_line_pitch=360,
        grid_character_space=4096,
    )

    first_section_end = len(b"Portrait\f")
    plcf_sed = struct.pack("<3I", 0, first_section_end, len(text))
    plcf_sed += struct.pack("<HiHI", 0, first_sepx_fc, 0, 0)
    plcf_sed += struct.pack("<HiHI", 0, second_sepx_fc, 0, 0)
    plcf_sed_offset = 128

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(text),
        clx_size=len(clx),
        section_plc=(plcf_sed_offset, len(plcf_sed)),
        cb_mac=1400,
    )
    word_document[text_fc : text_fc + len(text)] = text
    struct.pack_into("<h", word_document, first_sepx_fc, len(first_grpprl))
    word_document[
        first_sepx_fc + 2 : first_sepx_fc + 2 + len(first_grpprl)
    ] = first_grpprl
    struct.pack_into("<h", word_document, second_sepx_fc, len(second_grpprl))
    word_document[
        second_sepx_fc + 2 : second_sepx_fc + 2 + len(second_grpprl)
    ] = second_grpprl

    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[
        plcf_sed_offset : plcf_sed_offset + len(plcf_sed)
    ] = plcf_sed
    return _wrap_regular_word_streams(word_document, table_stream)


def build_header_footer_word_cfb(*, malformed_guard: bool = False) -> bytes:
    """A one-section DOC containing all six header/footer story types."""

    main_text = b"Body\r"
    header_stories = (
        b"",
        b"",
        b"",
        b"",
        b"",
        b"",
        b"Even H\rX" if malformed_guard else b"Even H\r\r",
        b"Default H\r\r",
        b"Even F\r\r",
        b"Default F\r\r",
        b"First H\r\r",
        b"First F\r\r",
    )
    header_payload = bytearray()
    header_cps = [0]
    for story in header_stories:
        header_payload.extend(story)
        header_cps.append(len(header_payload))
    header_document = bytes(header_payload) + b"\r"
    all_text = main_text + header_document

    text_fc = 1024
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(all_text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    sepx_fc = 1400
    section_grpprl = b"".join(
        (
            struct.pack("<HB", 0x300A, 1),
            struct.pack("<HH", 0xB01F, 12240),
            struct.pack("<HH", 0xB020, 15840),
            struct.pack("<HH", 0xB021, 1440),
            struct.pack("<HH", 0xB022, 1440),
            struct.pack("<Hh", 0x9023, 1440),
            struct.pack("<Hh", 0x9024, 1440),
            struct.pack("<HH", 0xB017, 720),
            struct.pack("<HH", 0xB018, 720),
        )
    )
    plcf_sed = struct.pack("<2I", 0, len(main_text))
    plcf_sed += struct.pack("<HiHI", 0, sepx_fc, 0, 0)
    plcf_sed_offset = 128

    # PlcfHdd has one boundary per story plus an ending CP and one final,
    # undefined CP. The header document's last character is outside all stories.
    plcf_hdd = struct.pack(f"<{len(header_cps) + 1}I", *header_cps, 0)
    plcf_hdd_offset = 200
    dop_offset = 300
    dop_size = 84

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(main_text),
        ccp_headers=len(header_document),
        clx_size=len(clx),
        section_plc=(plcf_sed_offset, len(plcf_sed)),
        header_plc=(plcf_hdd_offset, len(plcf_hdd)),
        dop=(dop_offset, dop_size),
        cb_mac=1500,
    )
    word_document[text_fc : text_fc + len(all_text)] = all_text
    struct.pack_into("<h", word_document, sepx_fc, len(section_grpprl))
    word_document[
        sepx_fc + 2 : sepx_fc + 2 + len(section_grpprl)
    ] = section_grpprl

    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[
        plcf_sed_offset : plcf_sed_offset + len(plcf_sed)
    ] = plcf_sed
    table_stream[
        plcf_hdd_offset : plcf_hdd_offset + len(plcf_hdd)
    ] = plcf_hdd
    table_stream[dop_offset] = 0x01  # DopBase.fFacingPages
    return _wrap_regular_word_streams(word_document, table_stream)


def build_header_textbox_word_cfb(*, malformed_field: bool = False) -> bytes:
    """A DOC whose default footer contains a floating PAGE-field textbox."""

    main_text = b"Body\r"
    header_stories = [b""] * 12
    header_stories[9] = b"\x08\r\r"
    header_payload = bytearray()
    header_cps = [0]
    for story in header_stories:
        header_payload.extend(story)
        header_cps.append(len(header_payload))
    header_document = bytes(header_payload) + b"\r"

    field_text = b"\x13 PAGE \\* MERGEFORMAT \x141\x15"
    textbox_range = field_text + b"\r\r"
    header_textbox_document = textbox_range + b"\r"
    all_text = main_text + header_document + header_textbox_document

    text_fc = 1024
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(all_text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    sepx_fc = 1400
    section_grpprl = b"".join(
        (
            struct.pack("<HH", 0xB01F, 12240),
            struct.pack("<HH", 0xB020, 15840),
            struct.pack("<HH", 0xB021, 1440),
            struct.pack("<HH", 0xB022, 1440),
            struct.pack("<Hh", 0x9023, 1440),
            struct.pack("<Hh", 0x9024, 1440),
            struct.pack("<HH", 0xB017, 720),
            struct.pack("<HH", 0xB018, 720),
        )
    )
    plcf_sed = struct.pack("<2I", 0, len(main_text))
    plcf_sed += struct.pack("<HiHI", 0, sepx_fc, 0, 0)
    plcf_sed_offset = 128

    plcf_hdd = struct.pack(
        f"<{len(header_cps) + 1}I",
        *header_cps,
        len(header_document),
    )
    plcf_hdd_offset = 200

    shape_id = 1025
    plcf_spa_hdr = struct.pack("<2I", 0, len(header_document))
    plcf_spa_hdr += struct.pack(
        "<I4iHI",
        shape_id,
        0,
        0,
        2880,
        720,
        0x0070,
        0,
    )
    plcf_spa_hdr_offset = 300

    textbox_cps = (0, len(textbox_range), len(header_textbox_document))
    plcf_header_textboxes = struct.pack("<3I", *textbox_cps)
    plcf_header_textboxes += struct.pack(
        "<iiHiII",
        1,
        0,
        0,
        -1,
        shape_id,
        0,
    )
    plcf_header_textboxes += struct.pack(
        "<iiHiII",
        -1,
        0,
        1,
        0,
        0,
        0,
    )
    plcf_header_textboxes_offset = 350

    plcf_breaks = struct.pack("<3I", *textbox_cps)
    plcf_breaks += struct.pack("<hHH", 0, 0, 0)
    plcf_breaks += struct.pack("<hHH", -1, 0, 0)
    plcf_breaks_offset = 420

    separator_cp = field_text.index(b"\x14")
    end_cp = field_text.index(b"\x15")
    plcf_fields = struct.pack(
        "<4I",
        0,
        separator_cp,
        end_cp,
        len(header_textbox_document),
    )
    first_field_character = 0x14 if malformed_field else 0x13
    plcf_fields += bytes(
        (first_field_character, 0x21, 0x14, 0x00, 0x15, 0x00)
    )
    plcf_fields_offset = 460

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(main_text),
        ccp_headers=len(header_document),
        ccp_header_textboxes=len(header_textbox_document),
        clx_size=len(clx),
        section_plc=(plcf_sed_offset, len(plcf_sed)),
        header_plc=(plcf_hdd_offset, len(plcf_hdd)),
        header_shape_plc=(plcf_spa_hdr_offset, len(plcf_spa_hdr)),
        header_textbox_plc=(
            plcf_header_textboxes_offset,
            len(plcf_header_textboxes),
        ),
        header_textbox_field_plc=(plcf_fields_offset, len(plcf_fields)),
        header_textbox_break_plc=(plcf_breaks_offset, len(plcf_breaks)),
        cb_mac=1500,
    )
    word_document[text_fc : text_fc + len(all_text)] = all_text
    struct.pack_into("<h", word_document, sepx_fc, len(section_grpprl))
    word_document[
        sepx_fc + 2 : sepx_fc + 2 + len(section_grpprl)
    ] = section_grpprl

    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[
        plcf_sed_offset : plcf_sed_offset + len(plcf_sed)
    ] = plcf_sed
    table_stream[
        plcf_hdd_offset : plcf_hdd_offset + len(plcf_hdd)
    ] = plcf_hdd
    table_stream[
        plcf_spa_hdr_offset : plcf_spa_hdr_offset + len(plcf_spa_hdr)
    ] = plcf_spa_hdr
    table_stream[
        plcf_header_textboxes_offset :
        plcf_header_textboxes_offset + len(plcf_header_textboxes)
    ] = plcf_header_textboxes
    table_stream[
        plcf_breaks_offset : plcf_breaks_offset + len(plcf_breaks)
    ] = plcf_breaks
    table_stream[
        plcf_fields_offset : plcf_fields_offset + len(plcf_fields)
    ] = plcf_fields
    return _wrap_regular_word_streams(word_document, table_stream)


def build_word_cfb(
    *, encrypted: bool = False, uses_1table: bool = True
) -> bytes:
    compressed_text = b"Hello\r"
    unicode_text = "世界\r".encode("utf-16le")
    cps = (0, len(compressed_text), len(compressed_text) + len("世界\r"))
    compressed_fc = (1024 * 2) | 0x40000000
    unicode_fc = 1100
    plc_pcd = struct.pack("<3I", *cps)
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    plc_pcd += struct.pack("<HIH", 0, unicode_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=cps[-1],
        clx_size=len(clx),
        encrypted=encrypted,
        uses_1table=uses_1table,
    )
    word_document[1024 : 1024 + len(compressed_text)] = compressed_text
    word_document[1100 : 1100 + len(unicode_text)] = unicode_text
    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx

    sectors = [bytearray(SECTOR_SIZE) for _ in range(18)]
    for index in range(8):
        sectors[index][:] = word_document[index * 512 : (index + 1) * 512]
        sectors[8 + index][:] = table_stream[index * 512 : (index + 1) * 512]

    directory = bytearray(SECTOR_SIZE)
    directory[0:128] = _directory_entry("Root Entry", 5, child=1)
    directory[128:256] = _directory_entry(
        "WordDocument", 2, right=2, start=0, size=4096
    )
    table_name = "1Table" if uses_1table else "0Table"
    directory[256:384] = _directory_entry(table_name, 2, start=8, size=4096)
    sectors[16][:] = directory

    fat = [FREESECT] * 128
    for start in (0, 8):
        for sector_id in range(start, start + 7):
            fat[sector_id] = sector_id + 1
        fat[start + 7] = ENDOFCHAIN
    fat[16] = ENDOFCHAIN
    fat[17] = FATSECT
    struct.pack_into("<128I", sectors[17], 0, *fat)

    return _header(fat_sector=17, directory_sector=16) + b"".join(sectors)


def build_formatted_word_cfb() -> bytes:
    """A one-piece DOC with CHPX and PAPX FKPs for M3a tests."""

    text = b"Bold plain\rCentered\r"
    text_fc = 1024
    text_fc_end = text_fc + len(text)
    cps = (0, len(text))
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", *cps)
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    chpx_plc_offset = 128
    papx_plc_offset = 160
    chpx_plc = struct.pack("<3I", text_fc, text_fc_end, 4)
    papx_plc = struct.pack("<3I", text_fc, text_fc_end, 5)

    chpx_fkp = bytearray(SECTOR_SIZE)
    chpx_boundaries = (text_fc, text_fc + 4, text_fc + 5, text_fc + 10, text_fc_end)
    struct.pack_into("<5I", chpx_fkp, 0, *chpx_boundaries)
    chpx_fkp[20:24] = bytes((32, 0, 36, 0))
    bold_grpprl = struct.pack("<HB", 0x0835, 1)
    chpx_fkp[64] = len(bold_grpprl)
    chpx_fkp[65 : 65 + len(bold_grpprl)] = bold_grpprl
    rich_grpprl = b"".join(
        (
            struct.pack("<HB", 0x0836, 1),
            struct.pack("<HB", 0x2A42, 6),
            struct.pack("<HH", 0x4A43, 28),
        )
    )
    chpx_fkp[72] = len(rich_grpprl)
    chpx_fkp[73 : 73 + len(rich_grpprl)] = rich_grpprl
    chpx_fkp[-1] = 4

    papx_fkp = bytearray(SECTOR_SIZE)
    # Paragraph FKP runs include the paragraph mark at the end of each range.
    papx_boundaries = (text_fc, text_fc + 11, text_fc_end)
    struct.pack_into("<3I", papx_fkp, 0, *papx_boundaries)
    papx_fkp[12] = 0
    papx_fkp[25] = 32
    paragraph_grpprl = b"".join(
        (
            struct.pack("<HB", 0x2461, 1),
            struct.pack("<Hh", 0x845E, 720),
            struct.pack("<HH", 0xA413, 120),
            struct.pack("<HH", 0xA414, 240),
        )
    )
    papx_content = struct.pack("<H", 0) + paragraph_grpprl
    papx_fkp[64] = (len(papx_content) + 1) // 2
    papx_fkp[65 : 65 + len(papx_content)] = papx_content
    papx_fkp[-1] = 2

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=cps[-1],
        clx_size=len(clx),
        chpx_plc=(chpx_plc_offset, len(chpx_plc)),
        papx_plc=(papx_plc_offset, len(papx_plc)),
        cb_mac=3072,
    )
    word_document[text_fc:text_fc_end] = text
    word_document[4 * SECTOR_SIZE : 5 * SECTOR_SIZE] = chpx_fkp
    word_document[5 * SECTOR_SIZE : 6 * SECTOR_SIZE] = papx_fkp

    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[chpx_plc_offset : chpx_plc_offset + len(chpx_plc)] = chpx_plc
    table_stream[papx_plc_offset : papx_plc_offset + len(papx_plc)] = papx_plc

    sectors = [bytearray(SECTOR_SIZE) for _ in range(18)]
    for index in range(8):
        sectors[index][:] = word_document[index * 512 : (index + 1) * 512]
        sectors[8 + index][:] = table_stream[index * 512 : (index + 1) * 512]

    directory = bytearray(SECTOR_SIZE)
    directory[0:128] = _directory_entry("Root Entry", 5, child=1)
    directory[128:256] = _directory_entry(
        "WordDocument", 2, right=2, start=0, size=4096
    )
    directory[256:384] = _directory_entry("1Table", 2, start=8, size=4096)
    sectors[16][:] = directory

    fat = [FREESECT] * 128
    for start in (0, 8):
        for sector_id in range(start, start + 7):
            fat[sector_id] = sector_id + 1
        fat[start + 7] = ENDOFCHAIN
    fat[16] = ENDOFCHAIN
    fat[17] = FATSECT
    struct.pack_into("<128I", sectors[17], 0, *fat)

    return _header(fat_sector=17, directory_sector=16) + b"".join(sectors)


def build_table_word_cfb() -> bytes:
    """A one-row, two-cell Word 97 table with a TDefTable grid and borders."""

    text = b"Before\rA\x07B\x07\x07After\r"
    text_fc = 1024
    text_fc_end = text_fc + len(text)
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    papx_plc_offset = 128
    papx_plc = struct.pack("<3I", text_fc, text_fc_end, 4)
    papx_fkp = bytearray(SECTOR_SIZE)
    boundaries = (
        text_fc,
        text_fc + 7,
        text_fc + 9,
        text_fc + 11,
        text_fc + 12,
        text_fc_end,
    )
    struct.pack_into("<6I", papx_fkp, 0, *boundaries)
    bx_offset = 4 * len(boundaries)
    papx_fkp[bx_offset] = 0
    papx_fkp[bx_offset + 13] = 40
    papx_fkp[bx_offset + 26] = 40
    papx_fkp[bx_offset + 39] = 64
    papx_fkp[bx_offset + 52] = 0

    cell_content = struct.pack("<H", 0) + struct.pack("<HB", 0x2416, 1)
    papx_fkp[80] = 3
    papx_fkp[81 : 81 + len(cell_content)] = cell_content

    border = bytes((4, 1, 0, 0))
    tdef = struct.pack("<HB3h", 8, 2, 0, 1000, 2200)
    default_margin = struct.pack("<BBBBBH", 6, 0, 1, 0x0A, 3, 108)
    second_cell_margin = struct.pack("<BBBBBH", 6, 1, 2, 0x05, 3, 36)
    shading_value = 6 | (7 << 5) | (1 << 10)
    shading = struct.pack("<BHH", 4, shading_value, 0)
    row_grpprl = b"".join(
        (
            struct.pack("<HB", 0x2416, 1),
            struct.pack("<HB", 0x2417, 1),
            struct.pack("<HB", 0xD605, 24) + border * 6,
            struct.pack("<H", 0xD608) + tdef,
            struct.pack("<H", 0xD634) + default_margin,
            struct.pack("<H", 0xD632) + second_cell_margin,
            struct.pack("<H", 0xD609) + shading,
        )
    )
    row_content = struct.pack("<H", 0) + row_grpprl
    papx_fkp[128] = (len(row_content) + 1) // 2
    papx_fkp[129 : 129 + len(row_content)] = row_content
    papx_fkp[129 + len(row_content)] = 0
    papx_fkp[-1] = 5

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(text),
        clx_size=len(clx),
        papx_plc=(papx_plc_offset, len(papx_plc)),
        cb_mac=2560,
    )
    word_document[text_fc:text_fc_end] = text
    word_document[4 * SECTOR_SIZE : 5 * SECTOR_SIZE] = papx_fkp
    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[papx_plc_offset : papx_plc_offset + len(papx_plc)] = papx_plc

    sectors = [bytearray(SECTOR_SIZE) for _ in range(18)]
    for index in range(8):
        sectors[index][:] = word_document[index * 512 : (index + 1) * 512]
        sectors[8 + index][:] = table_stream[index * 512 : (index + 1) * 512]
    directory = bytearray(SECTOR_SIZE)
    directory[0:128] = _directory_entry("Root Entry", 5, child=1)
    directory[128:256] = _directory_entry(
        "WordDocument", 2, right=2, start=0, size=4096
    )
    directory[256:384] = _directory_entry("1Table", 2, start=8, size=4096)
    sectors[16][:] = directory
    fat = [FREESECT] * 128
    for start in (0, 8):
        for sector_id in range(start, start + 7):
            fat[sector_id] = sector_id + 1
        fat[start + 7] = ENDOFCHAIN
    fat[16] = ENDOFCHAIN
    fat[17] = FATSECT
    struct.pack_into("<128I", sectors[17], 0, *fat)
    return _header(fat_sector=17, directory_sector=16) + b"".join(sectors)


def build_nested_table_word_cfb() -> bytes:
    """A Word 97 table containing a one-cell depth-two nested table."""

    text = b"Before\rOuter\rInner\r\r\x07\x07After\r"
    text_fc = 1024
    text_fc_end = text_fc + len(text)
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    papx_plc_offset = 128
    papx_plc = struct.pack("<3I", text_fc, text_fc_end, 4)
    papx_fkp = bytearray(SECTOR_SIZE)
    boundaries = tuple(text_fc + value for value in (0, 7, 13, 19, 20, 21, 22, 28))
    struct.pack_into("<8I", papx_fkp, 0, *boundaries)
    bx_offset = 4 * len(boundaries)

    outer_cell = struct.pack("<HB", 0x2416, 1)
    inner_cell = b"".join(
        (
            struct.pack("<HB", 0x2416, 1),
            struct.pack("<Hi", 0x6649, 2),
            struct.pack("<HB", 0x244B, 1),
        )
    )
    inner_tdef = struct.pack("<HB2h", 6, 1, 0, 1800)
    inner_row = b"".join(
        (
            struct.pack("<HB", 0x2416, 1),
            struct.pack("<Hi", 0x6649, 2),
            struct.pack("<HB", 0x244C, 1),
            struct.pack("<H", 0xD608) + inner_tdef,
        )
    )
    outer_tdef = struct.pack("<HB2h", 6, 1, 0, 3000)
    outer_row = b"".join(
        (
            struct.pack("<HB", 0x2416, 1),
            struct.pack("<HB", 0x2417, 1),
            struct.pack("<H", 0xD608) + outer_tdef,
        )
    )

    def store_papx(offset: int, grpprl: bytes) -> int:
        content = struct.pack("<H", 0) + grpprl
        # A non-extended PAPX stores ``2 * cch - 1`` content bytes.
        papx_fkp[offset] = (len(content) + 2) // 2
        papx_fkp[offset + 1 : offset + 1 + len(content)] = content
        return offset // 2

    outer_cell_offset = store_papx(128, outer_cell)
    inner_cell_offset = store_papx(160, inner_cell)
    inner_row_offset = store_papx(208, inner_row)
    outer_row_offset = store_papx(288, outer_row)
    papx_offsets = (
        0,
        outer_cell_offset,
        inner_cell_offset,
        inner_row_offset,
        outer_cell_offset,
        outer_row_offset,
        0,
    )
    for index, papx_offset in enumerate(papx_offsets):
        papx_fkp[bx_offset + 13 * index] = papx_offset
    papx_fkp[-1] = len(papx_offsets)

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(text),
        clx_size=len(clx),
        papx_plc=(papx_plc_offset, len(papx_plc)),
        cb_mac=2560,
    )
    word_document[text_fc:text_fc_end] = text
    word_document[4 * SECTOR_SIZE : 5 * SECTOR_SIZE] = papx_fkp
    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[papx_plc_offset : papx_plc_offset + len(papx_plc)] = papx_plc

    sectors = [bytearray(SECTOR_SIZE) for _ in range(18)]
    for index in range(8):
        sectors[index][:] = word_document[index * 512 : (index + 1) * 512]
        sectors[8 + index][:] = table_stream[index * 512 : (index + 1) * 512]
    directory = bytearray(SECTOR_SIZE)
    directory[0:128] = _directory_entry("Root Entry", 5, child=1)
    directory[128:256] = _directory_entry(
        "WordDocument", 2, right=2, start=0, size=4096
    )
    directory[256:384] = _directory_entry("1Table", 2, start=8, size=4096)
    sectors[16][:] = directory
    fat = [FREESECT] * 128
    for start in (0, 8):
        for sector_id in range(start, start + 7):
            fat[sector_id] = sector_id + 1
        fat[start + 7] = ENDOFCHAIN
    fat[16] = ENDOFCHAIN
    fat[17] = FATSECT
    struct.pack_into("<128I", sectors[17], 0, *fat)
    return _header(fat_sector=17, directory_sector=16) + b"".join(sectors)


def build_mini_stream_cfb(payload: bytes = b"mini stream") -> bytes:
    if len(payload) > 64:
        raise ValueError("fixture payload must fit one mini sector")
    sectors = [bytearray(SECTOR_SIZE) for _ in range(4)]
    sectors[0][: len(payload)] = payload

    mini_fat = [FREESECT] * 128
    mini_fat[0] = ENDOFCHAIN
    struct.pack_into("<128I", sectors[1], 0, *mini_fat)

    directory = bytearray(SECTOR_SIZE)
    directory[0:128] = _directory_entry(
        "Root Entry", 5, child=1, start=0, size=64
    )
    directory[128:256] = _directory_entry(
        "Small", 2, start=0, size=len(payload)
    )
    sectors[2][:] = directory

    fat = [FREESECT] * 128
    fat[0] = ENDOFCHAIN
    fat[1] = ENDOFCHAIN
    fat[2] = ENDOFCHAIN
    fat[3] = FATSECT
    struct.pack_into("<128I", sectors[3], 0, *fat)

    return _header(
        fat_sector=3,
        directory_sector=2,
        mini_fat_sector=1,
        mini_fat_count=1,
    ) + b"".join(sectors)


def build_version4_cfb(payload: bytes | None = None) -> bytes:
    sector_size = 4096
    stream_payload = payload or (b"version four" + b"\0" * (sector_size - 12))
    if len(stream_payload) != sector_size:
        raise ValueError("version 4 fixture payload must be exactly 4096 bytes")

    header = bytearray(sector_size)
    header[:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<HHHHH", header, 24, 0x003E, 4, 0xFFFE, 12, 6)
    struct.pack_into(
        "<IIIIIIIII",
        header,
        40,
        1,
        1,
        1,
        0,
        0x1000,
        ENDOFCHAIN,
        0,
        ENDOFCHAIN,
        0,
    )
    difat = [FREESECT] * 109
    difat[0] = 2
    struct.pack_into("<109I", header, 76, *difat)

    sectors = [bytearray(sector_size) for _ in range(3)]
    sectors[0][:] = stream_payload
    directory = bytearray(sector_size)
    directory[0:128] = _directory_entry("Root Entry", 5, child=1)
    directory[128:256] = _directory_entry(
        "Big", 2, start=0, size=sector_size
    )
    sectors[1][:] = directory
    fat = [FREESECT] * (sector_size // 4)
    fat[0] = ENDOFCHAIN
    fat[1] = ENDOFCHAIN
    fat[2] = FATSECT
    struct.pack_into(f"<{len(fat)}I", sectors[2], 0, *fat)
    return bytes(header) + b"".join(sectors)
