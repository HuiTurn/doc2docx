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
    ccp_comments: int = 0,
    ccp_endnotes: int = 0,
    ccp_headers: int = 0,
    ccp_textboxes: int = 0,
    ccp_header_textboxes: int = 0,
    section_plc: tuple[int, int] = (0, 0),
    footnote_ref_plc: tuple[int, int] = (0, 0),
    footnote_text_plc: tuple[int, int] = (0, 0),
    comment_ref_plc: tuple[int, int] = (0, 0),
    comment_text_plc: tuple[int, int] = (0, 0),
    comment_owners: tuple[int, int] = (0, 0),
    comment_bookmark_tags: tuple[int, int] = (0, 0),
    comment_bookmark_starts: tuple[int, int] = (0, 0),
    comment_bookmark_ends: tuple[int, int] = (0, 0),
    endnote_ref_plc: tuple[int, int] = (0, 0),
    endnote_text_plc: tuple[int, int] = (0, 0),
    header_plc: tuple[int, int] = (0, 0),
    main_shape_plc: tuple[int, int] = (0, 0),
    header_shape_plc: tuple[int, int] = (0, 0),
    dgg_info: tuple[int, int] = (0, 0),
    main_textbox_plc: tuple[int, int] = (0, 0),
    main_textbox_field_plc: tuple[int, int] = (0, 0),
    main_textbox_break_plc: tuple[int, int] = (0, 0),
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
    fib_rg_lw[7] = ccp_comments
    fib_rg_lw[8] = ccp_endnotes
    fib_rg_lw[9] = ccp_textboxes
    fib_rg_lw[10] = ccp_header_textboxes
    struct.pack_into("<22I", fib, position, *fib_rg_lw)
    position += 22 * 4
    struct.pack_into("<H", fib, position, 93)
    position += 2
    pairs = [(0, 0)] * 93
    pairs[2] = footnote_ref_plc
    pairs[3] = footnote_text_plc
    pairs[4] = comment_ref_plc
    pairs[5] = comment_text_plc
    pairs[6] = section_plc
    pairs[11] = header_plc
    pairs[12] = chpx_plc
    pairs[13] = papx_plc
    pairs[31] = dop
    pairs[33] = (0, clx_size)
    pairs[36] = comment_owners
    pairs[37] = comment_bookmark_tags
    pairs[40] = main_shape_plc
    pairs[41] = header_shape_plc
    pairs[42] = comment_bookmark_starts
    pairs[43] = comment_bookmark_ends
    pairs[46] = endnote_ref_plc
    pairs[47] = endnote_text_plc
    pairs[50] = dgg_info
    pairs[56] = main_textbox_plc
    pairs[57] = main_textbox_field_plc
    pairs[58] = header_textbox_plc
    pairs[59] = header_textbox_field_plc
    pairs[75] = main_textbox_break_plc
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


def _officeart_record(
    version: int,
    instance: int,
    record_type: int,
    payload: bytes,
) -> bytes:
    return struct.pack(
        "<HHI",
        (instance << 4) | version,
        record_type,
        len(payload),
    ) + payload


def _header_textbox_officeart(shape_id: int, *, main_shape: bool = False) -> bytes:
    drawing_group_data = _officeart_record(
        0,
        0,
        0xF006,
        struct.pack("<4I", 2048, 1, 2, 2),
    )
    drawing_group = _officeart_record(0xF, 0, 0xF000, drawing_group_data)
    main_drawing = _officeart_record(
        0xF,
        0,
        0xF002,
        _officeart_record(0, 1, 0xF008, struct.pack("<2I", 0, 2048)),
    )
    shape_properties = b"".join(
        struct.pack("<HI", identifier, value)
        for identifier, value in (
            (0x0081, 0),
            (0x0082, 0),
            (0x0083, 0),
            (0x0084, 0),
            (0x01BF, 0x00110001),
            (0x01FF, 0x00080000),
        )
    )
    shape = _officeart_record(
        0xF,
        0,
        0xF004,
        _officeart_record(
            2,
            202,
            0xF00A,
            struct.pack("<2I", shape_id, 0x00000A00),
        )
        + _officeart_record(3, 6, 0xF00B, shape_properties),
    )
    header_drawing = _officeart_record(
        0xF,
        0,
        0xF002,
        _officeart_record(0, 2, 0xF008, struct.pack("<2I", 1, shape_id))
        + shape,
    )
    if main_shape:
        return drawing_group + b"\x01" + main_drawing + b"\x00" + header_drawing
    return drawing_group + b"\x00" + main_drawing + b"\x01" + header_drawing


def build_header_textbox_word_cfb(
    *,
    malformed_field: bool = False,
    officeart_style: bool = False,
) -> bytes:
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
        (first_field_character, 0x21, 0x14, 0x00, 0x15, 0x80)
    )
    plcf_fields_offset = 460

    dgg_info = _header_textbox_officeart(shape_id) if officeart_style else b""
    dgg_info_offset = 520

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(main_text),
        ccp_headers=len(header_document),
        ccp_header_textboxes=len(header_textbox_document),
        clx_size=len(clx),
        section_plc=(plcf_sed_offset, len(plcf_sed)),
        header_plc=(plcf_hdd_offset, len(plcf_hdd)),
        header_shape_plc=(plcf_spa_hdr_offset, len(plcf_spa_hdr)),
        dgg_info=(dgg_info_offset, len(dgg_info)) if dgg_info else (0, 0),
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
    if dgg_info:
        table_stream[dgg_info_offset : dgg_info_offset + len(dgg_info)] = dgg_info
    return _wrap_regular_word_streams(word_document, table_stream)


def build_main_textbox_word_cfb(
    *,
    malformed_anchor: bool = False,
    missing_break_table: bool = False,
    officeart_style: bool = False,
    page_field: bool = False,
) -> bytes:
    """A DOC whose main story contains one floating text box."""

    anchor = b"!" if malformed_anchor else b"\x08"
    main_text = b"Before" + anchor + b"After\r"
    anchor_cp = 6
    field_text = b"\x13 PAGE \\* MERGEFORMAT \x141\x15"
    textbox_content = field_text if page_field else b"Inside textbox"
    textbox_range = textbox_content + b"\r\r"
    textbox_document = textbox_range + b"\r"
    all_text = main_text + textbox_document

    text_fc = 1024
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(all_text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    shape_id = 1025
    plcf_spa = struct.pack("<2I", anchor_cp, len(main_text))
    plcf_spa += struct.pack(
        "<I4iHI",
        shape_id,
        720,
        360,
        3600,
        1440,
        0x0070,
        0,
    )
    plcf_spa_offset = 128

    textbox_cps = (0, len(textbox_range), len(textbox_document))
    plcf_textboxes = struct.pack("<3I", *textbox_cps)
    plcf_textboxes += struct.pack(
        "<iiHiII",
        1,
        0,
        0,
        -1,
        shape_id,
        0,
    )
    plcf_textboxes += struct.pack(
        "<iiHiII",
        -1,
        0,
        1,
        0,
        0,
        0,
    )
    plcf_textboxes_offset = 200

    plcf_breaks = struct.pack("<3I", *textbox_cps)
    plcf_breaks += struct.pack("<hHH", 0, 0, 0)
    plcf_breaks += struct.pack("<hHH", -1, 0, 0)
    plcf_breaks_offset = 280
    plcf_fields = b""
    plcf_fields_offset = 320
    if page_field:
        separator_cp = field_text.index(b"\x14")
        end_cp = field_text.index(b"\x15")
        plcf_fields = struct.pack(
            "<4I",
            0,
            separator_cp,
            end_cp,
            len(textbox_document),
        )
        plcf_fields += bytes((0x13, 0x21, 0x14, 0x00, 0x15, 0x80))
    dgg_info = (
        _header_textbox_officeart(shape_id, main_shape=True)
        if officeart_style
        else b""
    )
    dgg_info_offset = 380

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(main_text),
        ccp_textboxes=len(textbox_document),
        clx_size=len(clx),
        main_shape_plc=(plcf_spa_offset, len(plcf_spa)),
        main_textbox_plc=(plcf_textboxes_offset, len(plcf_textboxes)),
        main_textbox_field_plc=(
            (plcf_fields_offset, len(plcf_fields)) if plcf_fields else (0, 0)
        ),
        main_textbox_break_plc=(
            (0, 0)
            if missing_break_table
            else (plcf_breaks_offset, len(plcf_breaks))
        ),
        dgg_info=(dgg_info_offset, len(dgg_info)) if dgg_info else (0, 0),
        cb_mac=2048,
    )
    word_document[text_fc : text_fc + len(all_text)] = all_text

    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[plcf_spa_offset : plcf_spa_offset + len(plcf_spa)] = plcf_spa
    table_stream[
        plcf_textboxes_offset : plcf_textboxes_offset + len(plcf_textboxes)
    ] = plcf_textboxes
    if not missing_break_table:
        table_stream[
            plcf_breaks_offset : plcf_breaks_offset + len(plcf_breaks)
        ] = plcf_breaks
    if plcf_fields:
        table_stream[
            plcf_fields_offset : plcf_fields_offset + len(plcf_fields)
        ] = plcf_fields
    if dgg_info:
        table_stream[dgg_info_offset : dgg_info_offset + len(dgg_info)] = dgg_info
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


def build_footnote_word_cfb(
    *,
    missing_special: bool = False,
    malformed_reference_character: bool = False,
    malformed_text_end: bool = False,
    custom_mark: bool = False,
) -> bytes:
    """A one-footnote DOC with strict PlcffndRef/PlcffndTxt structures."""

    reference_character = b"*" if custom_mark else b"\x02"
    if malformed_reference_character:
        reference_character = b"!"
    main_text = b"Body" + reference_character + b" text\r"
    reference_cp = 4
    footnote_content = b"\x02Footnote text\r"
    if malformed_text_end:
        footnote_content = b"\x02Footnote textX"
    # The final footnote-document character is outside every PlcffndTxt range.
    footnote_document = footnote_content + b"\r"
    # A secondary document also requires one paragraph mark beyond all parts.
    all_text = main_text + footnote_document + b"\r"

    text_fc = 1024
    text_fc_end = text_fc + len(all_text)
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(all_text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    footnote_ref_offset = 128
    footnote_text_offset = 160
    chpx_plc_offset = 192
    footnote_ref = struct.pack(
        "<2IH",
        reference_cp,
        len(main_text),
        0 if custom_mark else 1,
    )
    footnote_text = struct.pack(
        "<3I",
        0,
        len(footnote_document) - 1,
        len(footnote_document),
    )
    chpx_plc = struct.pack("<3I", text_fc, text_fc_end, 4)

    chpx_fkp = bytearray(SECTOR_SIZE)
    footnote_marker_cp = len(main_text)
    boundaries = (
        text_fc,
        text_fc + reference_cp,
        text_fc + reference_cp + 1,
        text_fc + footnote_marker_cp,
        text_fc + footnote_marker_cp + 1,
        text_fc_end,
    )
    struct.pack_into("<6I", chpx_fkp, 0, *boundaries)
    if not missing_special and not custom_mark:
        chpx_fkp[24:29] = bytes((0, 32, 0, 32, 0))
        special_grpprl = struct.pack("<HB", 0x0855, 1)
        chpx_fkp[64] = len(special_grpprl)
        chpx_fkp[65 : 65 + len(special_grpprl)] = special_grpprl
    chpx_fkp[-1] = 5

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(main_text),
        ccp_footnotes=len(footnote_document),
        clx_size=len(clx),
        footnote_ref_plc=(footnote_ref_offset, len(footnote_ref)),
        footnote_text_plc=(footnote_text_offset, len(footnote_text)),
        chpx_plc=(chpx_plc_offset, len(chpx_plc)),
        cb_mac=5 * SECTOR_SIZE,
    )
    word_document[text_fc:text_fc_end] = all_text
    word_document[4 * SECTOR_SIZE : 5 * SECTOR_SIZE] = chpx_fkp

    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[
        footnote_ref_offset : footnote_ref_offset + len(footnote_ref)
    ] = footnote_ref
    table_stream[
        footnote_text_offset : footnote_text_offset + len(footnote_text)
    ] = footnote_text
    table_stream[chpx_plc_offset : chpx_plc_offset + len(chpx_plc)] = chpx_plc
    return _wrap_regular_word_streams(word_document, table_stream)


def build_endnote_word_cfb(
    *,
    missing_special: bool = False,
    malformed_reference_character: bool = False,
    malformed_text_end: bool = False,
    custom_mark: bool = False,
) -> bytes:
    """A one-endnote DOC with strict PlcfendRef/PlcfendTxt structures."""

    reference_character = b"*" if custom_mark else b"\x02"
    if malformed_reference_character:
        reference_character = b"!"
    main_text = b"Body" + reference_character + b" text\r"
    reference_cp = 4
    endnote_content = b"\x02Endnote text\r"
    if malformed_text_end:
        endnote_content = b"\x02Endnote textX"
    endnote_document = endnote_content + b"\r"
    all_text = main_text + endnote_document + b"\r"

    text_fc = 1024
    text_fc_end = text_fc + len(all_text)
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(all_text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    endnote_ref_offset = 128
    endnote_text_offset = 160
    chpx_plc_offset = 192
    endnote_ref = struct.pack(
        "<2IH",
        reference_cp,
        len(main_text),
        0 if custom_mark else 1,
    )
    endnote_text = struct.pack(
        "<3I",
        0,
        len(endnote_document) - 1,
        len(endnote_document),
    )
    chpx_plc = struct.pack("<3I", text_fc, text_fc_end, 4)

    chpx_fkp = bytearray(SECTOR_SIZE)
    endnote_marker_cp = len(main_text)
    boundaries = (
        text_fc,
        text_fc + reference_cp,
        text_fc + reference_cp + 1,
        text_fc + endnote_marker_cp,
        text_fc + endnote_marker_cp + 1,
        text_fc_end,
    )
    struct.pack_into("<6I", chpx_fkp, 0, *boundaries)
    if not missing_special and not custom_mark:
        chpx_fkp[24:29] = bytes((0, 32, 0, 32, 0))
        special_grpprl = struct.pack("<HB", 0x0855, 1)
        chpx_fkp[64] = len(special_grpprl)
        chpx_fkp[65 : 65 + len(special_grpprl)] = special_grpprl
    chpx_fkp[-1] = 5

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(main_text),
        ccp_endnotes=len(endnote_document),
        clx_size=len(clx),
        endnote_ref_plc=(endnote_ref_offset, len(endnote_ref)),
        endnote_text_plc=(endnote_text_offset, len(endnote_text)),
        chpx_plc=(chpx_plc_offset, len(chpx_plc)),
        cb_mac=5 * SECTOR_SIZE,
    )
    word_document[text_fc:text_fc_end] = all_text
    word_document[4 * SECTOR_SIZE : 5 * SECTOR_SIZE] = chpx_fkp

    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[
        endnote_ref_offset : endnote_ref_offset + len(endnote_ref)
    ] = endnote_ref
    table_stream[
        endnote_text_offset : endnote_text_offset + len(endnote_text)
    ] = endnote_text
    table_stream[chpx_plc_offset : chpx_plc_offset + len(chpx_plc)] = chpx_plc
    return _wrap_regular_word_streams(word_document, table_stream)


def build_comment_word_cfb(
    *,
    insertion_point: bool = False,
    missing_special: bool = False,
    malformed_reference_character: bool = False,
    malformed_text_marker: bool = False,
    malformed_text_end: bool = False,
    invalid_author_index: bool = False,
    missing_bookmark_table: bool = False,
) -> bytes:
    """A one-comment DOC with legacy author and annotation bookmark tables."""

    reference_character = b"!" if malformed_reference_character else b"\x05"
    main_text = b"Some text" + reference_character + b"\r"
    reference_cp = 9
    comment_marker = b"!" if malformed_text_marker else b"\x05"
    comment_content = comment_marker + b"Comment body\r"
    if malformed_text_end:
        comment_content = comment_marker + b"Comment bodyX"
    comment_document = comment_content + b"\r"
    all_text = main_text + comment_document + b"\r"

    text_fc = 1024
    text_fc_end = text_fc + len(all_text)
    compressed_fc = (text_fc * 2) | 0x40000000
    plc_pcd = struct.pack("<2I", 0, len(all_text))
    plc_pcd += struct.pack("<HIH", 0, compressed_fc, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd

    comment_ref_offset = 128
    comment_text_offset = 192
    owners_offset = 224
    bookmark_tags_offset = 256
    bookmark_starts_offset = 288
    bookmark_ends_offset = 320
    chpx_plc_offset = 352

    initials = "AL".encode("utf-16le")
    initials_buffer = struct.pack("<H", 2) + initials + b"\0" * (18 - len(initials))
    bookmark_tag = 0xFFFFFFFF if insertion_point else 1234
    atrd = initials_buffer + struct.pack(
        "<HHHI",
        1 if invalid_author_index else 0,
        0,
        0,
        bookmark_tag,
    )
    comment_ref = struct.pack("<2I", reference_cp, len(main_text)) + atrd
    comment_text = struct.pack(
        "<3I",
        0,
        len(comment_document) - 1,
        len(comment_document),
    )
    author_name = "Alice".encode("utf-16le")
    owners = struct.pack("<H", 5) + author_name

    bookmark_tags = struct.pack(
        "<HHHHHII",
        0xFFFF,
        1,
        10,
        0,
        0x0100,
        1234,
        0xFFFFFFFF,
    )
    bookmark_starts = struct.pack("<2IHH", 5, len(main_text) + 1, 0, 0)
    bookmark_ends = struct.pack("<2I", 9, len(main_text) + 1)

    chpx_plc = struct.pack("<3I", text_fc, text_fc_end, 4)
    chpx_fkp = bytearray(SECTOR_SIZE)
    comment_marker_cp = len(main_text)
    boundaries = (
        text_fc,
        text_fc + reference_cp,
        text_fc + reference_cp + 1,
        text_fc + comment_marker_cp,
        text_fc + comment_marker_cp + 1,
        text_fc_end,
    )
    struct.pack_into("<6I", chpx_fkp, 0, *boundaries)
    if not missing_special:
        chpx_fkp[24:29] = bytes((0, 32, 0, 32, 0))
        special_grpprl = struct.pack("<HB", 0x0855, 1)
        chpx_fkp[64] = len(special_grpprl)
        chpx_fkp[65 : 65 + len(special_grpprl)] = special_grpprl
    chpx_fkp[-1] = 5

    include_bookmarks = not insertion_point
    tag_pair = (
        (bookmark_tags_offset, len(bookmark_tags)) if include_bookmarks else (0, 0)
    )
    start_pair = (
        (bookmark_starts_offset, len(bookmark_starts))
        if include_bookmarks
        else (0, 0)
    )
    end_pair = (
        (bookmark_ends_offset, len(bookmark_ends))
        if include_bookmarks and not missing_bookmark_table
        else (0, 0)
    )

    word_document = bytearray(4096)
    word_document[:1024] = _build_fib(
        ccp_text=len(main_text),
        ccp_comments=len(comment_document),
        clx_size=len(clx),
        comment_ref_plc=(comment_ref_offset, len(comment_ref)),
        comment_text_plc=(comment_text_offset, len(comment_text)),
        comment_owners=(owners_offset, len(owners)),
        comment_bookmark_tags=tag_pair,
        comment_bookmark_starts=start_pair,
        comment_bookmark_ends=end_pair,
        chpx_plc=(chpx_plc_offset, len(chpx_plc)),
        cb_mac=5 * SECTOR_SIZE,
    )
    word_document[text_fc:text_fc_end] = all_text
    word_document[4 * SECTOR_SIZE : 5 * SECTOR_SIZE] = chpx_fkp

    table_stream = bytearray(4096)
    table_stream[: len(clx)] = clx
    table_stream[
        comment_ref_offset : comment_ref_offset + len(comment_ref)
    ] = comment_ref
    table_stream[
        comment_text_offset : comment_text_offset + len(comment_text)
    ] = comment_text
    table_stream[owners_offset : owners_offset + len(owners)] = owners
    if include_bookmarks:
        table_stream[
            bookmark_tags_offset : bookmark_tags_offset + len(bookmark_tags)
        ] = bookmark_tags
        table_stream[
            bookmark_starts_offset : bookmark_starts_offset
            + len(bookmark_starts)
        ] = bookmark_starts
        table_stream[
            bookmark_ends_offset : bookmark_ends_offset + len(bookmark_ends)
        ] = bookmark_ends
    table_stream[chpx_plc_offset : chpx_plc_offset + len(chpx_plc)] = chpx_plc
    return _wrap_regular_word_streams(word_document, table_stream)


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
