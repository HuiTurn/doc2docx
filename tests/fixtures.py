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
    chpx_plc: tuple[int, int] = (0, 0),
    papx_plc: tuple[int, int] = (0, 0),
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
    struct.pack_into("<22I", fib, position, *fib_rg_lw)
    position += 22 * 4
    struct.pack_into("<H", fib, position, 93)
    position += 2
    pairs = [(0, 0)] * 93
    pairs[12] = chpx_plc
    pairs[13] = papx_plc
    pairs[33] = (0, clx_size)
    for fc, lcb in pairs:
        struct.pack_into("<II", fib, position, fc, lcb)
        position += 8
    return bytes(fib)


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
