from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import (
    Document,
    FontDefinition,
    Paragraph,
    ParagraphProperties,
    TextRun,
)
from doc2docx.msdoc.numbering import read_numbering
from doc2docx.msdoc.sprm import PropertyModifier, apply_paragraph_modifiers
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _level(
    *,
    level: int,
    number_format: int,
    text: tuple[int, ...],
    start: int = 1,
    left: int = 720,
    first_line: int = -360,
    font_index: int | None = None,
) -> bytes:
    placeholder_offsets = bytes(
        index + 1 if value <= level and number_format != 0x17 else 0
        for index, value in enumerate(text)
    )
    placeholder_offsets = bytes(value for value in placeholder_offsets if value)[:9]
    placeholder_offsets += bytes(9 - len(placeholder_offsets))
    paragraph = b"".join(
        (
            struct.pack("<Hh", 0x845E, left),
            struct.pack("<Hh", 0x8460, first_line),
        )
    )
    character = (
        struct.pack("<HH", 0x4A4F, font_index)
        + struct.pack("<HH", 0x4A51, font_index)
        if font_index is not None
        else b""
    )
    fixed = struct.pack(
        "<iBB9sBiiBBBB",
        start,
        number_format,
        0,
        placeholder_offsets,
        0,
        0,
        0,
        len(character),
        len(paragraph),
        0,
        0,
    )
    return fixed + paragraph + character + struct.pack(
        f"<H{len(text)}H", len(text), *text
    )


def _lstf(list_id: int, *, simple: bool = True) -> bytes:
    return struct.pack(
        "<iI9hBB",
        list_id,
        list_id,
        *(0x0FFF for _ in range(9)),
        1 if simple else 0,
        0,
    )


def _lfo(list_id: int, override_count: int) -> bytes:
    return struct.pack("<iiiBBBB", list_id, 0, 0, override_count, 0, 0, 0)


def _numbering_tables() -> tuple[bytes, int, int]:
    decimal = _level(level=0, number_format=0, text=(0, ord(".")))
    bullet = _level(
        level=0,
        number_format=0x17,
        text=(0xF0B7,),
        left=1080,
        font_index=0,
    )
    replacement = _level(
        level=0,
        number_format=4,
        text=(0, ord(")")),
        start=5,
    )
    plf_lst = struct.pack("<h", 2) + _lstf(101) + _lstf(202)
    list_region = plf_lst + decimal + bullet
    lfos = struct.pack("<I", 2) + _lfo(101, 1) + _lfo(202, 1)
    start_override = struct.pack("<I", 0) + struct.pack("<iI", 3, 0x10)
    format_override = (
        struct.pack("<I", 5) + struct.pack("<iI", 0, 0x20) + replacement
    )
    plf_lfo = lfos + start_override + format_override
    return list_region + plf_lfo, len(plf_lst), len(list_region)


def _list_names(*values: str) -> bytes:
    payload = bytearray(struct.pack("<HHH", 0xFFFF, len(values), 0))
    for value in values:
        encoded = value.encode("utf-16le")
        payload.extend(struct.pack("<H", len(encoded) // 2))
        payload.extend(encoded)
    return bytes(payload)


class NumberingTests(unittest.TestCase):
    def _read(self):
        table, list_size, lfo_offset = _numbering_tables()
        names = _list_names("CustomOutline", "")
        names_offset = len(table)
        return read_numbering(
            table + names,
            list_offset=0,
            list_size=list_size,
            lfo_offset=lfo_offset,
            lfo_size=names_offset - lfo_offset,
            ccp_text=20,
            fonts=(FontDefinition(0, "Symbol"),),
            report=ConversionReport("lists.doc"),
            list_names_offset=names_offset,
            list_names_size=len(names),
        )

    def test_reads_list_levels_and_lfo_overrides(self) -> None:
        numbering = self._read()

        self.assertEqual(len(numbering.abstracts), 2)
        self.assertEqual(numbering.abstracts[0].name, "CustomOutline")
        self.assertIsNone(numbering.abstracts[1].name)
        decimal, bullet = (value.levels[0] for value in numbering.abstracts)
        self.assertEqual((decimal.number_format, decimal.text), ("decimal", "%1."))
        self.assertEqual(decimal.paragraph_properties.left_indent_twips, 720)
        self.assertEqual(decimal.paragraph_properties.first_line_indent_twips, -360)
        self.assertEqual((bullet.number_format, bullet.text), ("bullet", "\uf0b7"))
        self.assertEqual(bullet.character_properties.ascii_font, "Symbol")
        self.assertEqual(numbering.instances[0].overrides[0].start, 3)
        replacement = numbering.instances[1].overrides[0].replacement
        assert replacement is not None
        self.assertEqual(
            (replacement.start, replacement.number_format, replacement.text),
            (5, "lowerLetter", "%1)"),
        )

    def test_writes_numbering_part_relationship_and_paragraph_bindings(self) -> None:
        numbering = self._read()
        document = Document(
            (
                Paragraph(
                    (TextRun("Three"),),
                    ParagraphProperties(numbering_id=1, numbering_level=0),
                ),
                Paragraph(
                    (TextRun("Bullet"),),
                    ParagraphProperties(numbering_id=2, numbering_level=0),
                ),
                Paragraph(
                    (TextRun("Skipped"),),
                    ParagraphProperties(numbering_suppressed=True),
                ),
            ),
            numbering=numbering,
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "lists.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                names = set(package.namelist())
                document_root = ET.fromstring(package.read("word/document.xml"))
                numbering_root = ET.fromstring(package.read("word/numbering.xml"))
                relationships = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                content_types = package.read("[Content_Types].xml").decode()

        self.assertIn("word/numbering.xml", names)
        self.assertIn("/word/numbering.xml", content_types)
        relationship = next(
            value
            for value in relationships.findall(f"{REL}Relationship")
            if value.get("Target") == "numbering.xml"
        )
        self.assertTrue(relationship.get("Type", "").endswith("/numbering"))
        num_ids = [
            value.get(f"{W}val")
            for value in document_root.findall(f".//{W}numPr/{W}numId")
        ]
        self.assertEqual(num_ids, ["1", "2", "0"])
        level_texts = [
            value.get(f"{W}val")
            for value in numbering_root.findall(f".//{W}abstractNum/{W}lvl/{W}lvlText")
        ]
        self.assertEqual(level_texts, ["%1.", "\uf0b7"])
        self.assertEqual(
            numbering_root.find(f".//{W}abstractNum/{W}name").get(f"{W}val"),
            "CustomOutline",
        )
        self.assertEqual(
            numbering_root.find(f".//{W}startOverride").get(f"{W}val"),
            "3",
        )
        replacement = numbering_root.find(f".//{W}lvlOverride/{W}lvl/{W}numFmt")
        assert replacement is not None
        self.assertEqual(replacement.get(f"{W}val"), "lowerLetter")

    def test_applies_positive_negative_and_suppressed_list_sprms(self) -> None:
        properties, unsupported = apply_paragraph_modifiers(
            (
                PropertyModifier(0x260A, b"\x02"),
                PropertyModifier(0x460B, struct.pack("<h", -3)),
            ),
            style_id=4,
        )
        self.assertEqual(unsupported, set())
        self.assertEqual(properties.numbering_level, 2)
        self.assertEqual(properties.numbering_id, 3)
        self.assertFalse(properties.numbering_suppressed)

        suppressed, unsupported = apply_paragraph_modifiers(
            (
                PropertyModifier(0x260A, b"\x0c"),
                PropertyModifier(0x460B, b"\0\0"),
            ),
            style_id=None,
        )
        self.assertEqual(unsupported, set())
        self.assertTrue(suppressed.numbering_suppressed)
        self.assertTrue(suppressed.numbering_skipped)
        self.assertIsNone(suppressed.numbering_id)

        skipped_list, unsupported = apply_paragraph_modifiers(
            (
                PropertyModifier(0x260A, b"\x0c"),
                PropertyModifier(0x460B, struct.pack("<h", 2)),
            ),
            style_id=None,
        )
        self.assertEqual(unsupported, set())
        self.assertEqual(skipped_list.numbering_id, 2)
        self.assertFalse(skipped_list.numbering_suppressed)
        self.assertTrue(skipped_list.numbering_skipped)

    def test_rejects_malformed_list_structures(self) -> None:
        table, list_size, lfo_offset = _numbering_tables()
        cases = (
            (table, list_size - 1, lfo_offset, len(table) - lfo_offset),
            (
                table[:lfo_offset]
                + table[lfo_offset : lfo_offset + 4]
                + struct.pack("<i", 999)
                + table[lfo_offset + 8 :],
                list_size,
                lfo_offset,
                len(table) - lfo_offset,
            ),
            (table + b"\0", list_size, lfo_offset, len(table) - lfo_offset + 1),
        )
        for payload, fixed_size, override_offset, override_size in cases:
            with self.subTest(size=len(payload), fixed_size=fixed_size):
                with self.assertRaises(InvalidWordDocument):
                    read_numbering(
                        payload,
                        list_offset=0,
                        list_size=fixed_size,
                        lfo_offset=override_offset,
                        lfo_size=override_size,
                        ccp_text=20,
                        fonts=(FontDefinition(0, "Symbol"),),
                        report=ConversionReport("bad-lists.doc"),
                    )

    def test_ignores_extra_list_names_with_a_diagnostic(self) -> None:
        table, list_size, lfo_offset = _numbering_tables()
        names = _list_names("First", "Second", "Extra")
        names_offset = len(table)
        report = ConversionReport("extra-list-name.doc")

        numbering = read_numbering(
            table + names,
            list_offset=0,
            list_size=list_size,
            lfo_offset=lfo_offset,
            lfo_size=names_offset - lfo_offset,
            ccp_text=20,
            fonts=(FontDefinition(0, "Symbol"),),
            report=report,
            list_names_offset=names_offset,
            list_names_size=len(names),
        )

        self.assertEqual(
            [abstract.name for abstract in numbering.abstracts],
            ["First", "Second"],
        )
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["EXTRA_LIST_NAMES_IGNORED"],
        )

    def test_rejects_malformed_list_name_tables(self) -> None:
        table, list_size, lfo_offset = _numbering_tables()
        malformed_tables = (
            struct.pack("<HHH", 0, 0, 0),
            struct.pack("<HHH", 0xFFFF, 0, 1),
            struct.pack("<HHH", 0xFFFF, 1, 0) + struct.pack("<H", 256),
            _list_names("Name", "name"),
            _list_names("Name")[:-1],
            _list_names("Name") + b"\0",
        )
        for names in malformed_tables:
            with self.subTest(names=names):
                names_offset = len(table)
                with self.assertRaises(InvalidWordDocument):
                    read_numbering(
                        table + names,
                        list_offset=0,
                        list_size=list_size,
                        lfo_offset=lfo_offset,
                        lfo_size=names_offset - lfo_offset,
                        ccp_text=20,
                        fonts=(FontDefinition(0, "Symbol"),),
                        report=ConversionReport("bad-list-names.doc"),
                        list_names_offset=names_offset,
                        list_names_size=len(names),
                    )


if __name__ == "__main__":
    unittest.main()
