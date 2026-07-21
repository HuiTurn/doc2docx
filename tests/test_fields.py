from pathlib import Path
import struct
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import (
    CharacterProperties,
    Document,
    Field,
    FieldEndProperties,
    TextRun,
    parse_main_story,
)
from doc2docx.msdoc.fields import read_field_table
from doc2docx.msdoc.pieces import Piece, PieceTable
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _piece_table(text: str) -> PieceTable:
    payload = text.encode("latin1")
    return PieceTable((Piece(0, len(text), 0, True, 0),), payload)


def _plcf(records: tuple[tuple[int, int, int], ...], story_length: int) -> bytes:
    cps = tuple(cp for cp, _character, _flags in records) + (story_length,)
    data = bytes(
        value
        for _cp, character, flags in records
        for value in (character, flags)
    )
    return struct.pack(f"<{len(cps)}I", *cps) + data


class FieldTableTests(unittest.TestCase):
    def test_accepts_an_empty_plcf_for_an_empty_story(self) -> None:
        payload = struct.pack("<I", 0)

        fields = read_field_table(
            payload,
            _piece_table(""),
            offset=0,
            size=len(payload),
            story_length=0,
            story_cp_start=0,
            structure="PlcfFldMom",
            story_name="main",
            report=ConversionReport("empty.doc"),
        )

        self.assertEqual((fields.field_count, fields.character_count), (0, 0))

    def test_validates_field_list_and_preserves_locked_dirty_flags(self) -> None:
        text = "\x13 DATE \x141\x15\r"
        begin = text.index("\x13")
        separator = text.index("\x14")
        end = text.index("\x15")
        table = _plcf(
            (
                (begin, 0x13, 0x1F),
                (separator, 0x14, 0),
                (end, 0x15, 0x80 | 0x10 | 0x04),
            ),
            len(text),
        )
        report = ConversionReport("fields.doc")
        piece_table = _piece_table(text)
        fields = read_field_table(
            table,
            piece_table,
            offset=0,
            size=len(table),
            story_length=len(text),
            story_cp_start=0,
            structure="PlcfFldMom",
            story_name="main",
            report=report,
            character_properties_at=lambda _cp: CharacterProperties(special=True),
        )

        self.assertEqual((fields.field_count, fields.character_count), (1, 3))
        end_properties = fields.end_properties_at(end)
        assert end_properties is not None
        self.assertEqual(end_properties.field_type_code, 0x1F)
        self.assertTrue(end_properties.has_separator)
        self.assertTrue(end_properties.locked)
        self.assertTrue(end_properties.result_dirty)

        document = parse_main_story(
            text,
            report,
            field_end_properties_at=fields.end_properties_at,
        )
        field = document.paragraphs[0].inlines[0]
        self.assertIsInstance(field, Field)
        assert isinstance(field, Field)
        self.assertTrue(field.locked)
        self.assertTrue(field.dirty)
        self.assertFalse(report.warnings)

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "fields.docx"
            write_docx(Document(document.paragraphs), destination)
            with zipfile.ZipFile(destination) as package:
                root = ET.fromstring(package.read("word/document.xml"))
        begin_element = root.find(f".//{W}fldChar[@{W}fldCharType='begin']")
        assert begin_element is not None
        self.assertEqual(begin_element.get(f"{W}fldLock"), "1")
        self.assertEqual(begin_element.get(f"{W}dirty"), "1")

    def test_accepts_nested_field_flags(self) -> None:
        text = "\x13\x13\x15\x14\x15\r"
        table = _plcf(
            (
                (0, 0x13, 0x07),
                (1, 0x13, 0x1F),
                (2, 0x15, 0x40),
                (3, 0x14, 0),
                (4, 0x15, 0x80),
            ),
            len(text),
        )

        fields = read_field_table(
            table,
            _piece_table(text),
            offset=0,
            size=len(table),
            story_length=len(text),
            story_cp_start=0,
            structure="PlcfFldMom",
            story_name="main",
            report=ConversionReport("nested.doc"),
        )

        self.assertEqual((fields.field_count, fields.character_count), (2, 5))
        self.assertTrue(fields.end_properties_at(2).nested)
        self.assertFalse(fields.end_properties_at(4).nested)

    def test_rejects_malformed_field_plcs_and_end_flags(self) -> None:
        text = "\x13 DATE \x141\x15\r"
        begin = text.index("\x13")
        separator = text.index("\x14")
        end = text.index("\x15")
        valid = _plcf(
            (
                (begin, 0x13, 0x1F),
                (separator, 0x14, 0),
                (end, 0x15, 0x80),
            ),
            len(text),
        )
        missing_has_separator = _plcf(
            (
                (begin, 0x13, 0x1F),
                (separator, 0x14, 0),
                (end, 0x15, 0),
            ),
            len(text),
        )
        wrong_story_character = _plcf(
            (
                (begin + 1, 0x13, 0x1F),
                (separator, 0x14, 0),
                (end, 0x15, 0x80),
            ),
            len(text),
        )
        cases = (valid[:-1], missing_has_separator, wrong_story_character)
        for payload in cases:
            with self.subTest(size=len(payload)):
                with self.assertRaises(InvalidWordDocument):
                    read_field_table(
                        payload,
                        _piece_table(text),
                        offset=0,
                        size=len(payload),
                        story_length=len(text),
                        story_cp_start=0,
                        structure="PlcfFldMom",
                        story_name="main",
                        report=ConversionReport("invalid.doc"),
                    )

    def test_private_active_field_does_not_expose_its_cached_result(self) -> None:
        text = 'before \x13 DDEAUTO "cmd" "args" \x14secret\x15 after\r'
        end_cp = text.index("\x15")
        properties = FieldEndProperties(
            field_type_code=0x2E,
            private_result=True,
            has_separator=True,
        )
        report = ConversionReport("private.doc")

        document = parse_main_story(
            text,
            report,
            field_end_properties_at=(
                lambda cp: properties if cp == end_cp else None
            ),
        )

        self.assertEqual(
            document.paragraphs[0].inlines,
            (TextRun("before  after"),),
        )
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["FIELDS_FLATTENED", "ACTIVE_FIELDS_FLATTENED"],
        )

    def test_undeclared_safe_field_is_not_activated(self) -> None:
        report = ConversionReport("undeclared.doc")
        document = parse_main_story(
            "before \x13 DATE \x14cached\x15 after\r",
            report,
            field_end_properties_at=lambda _cp: None,
        )

        self.assertEqual(
            document.paragraphs[0].inlines,
            (TextRun("before cached after"),),
        )
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["FIELDS_FLATTENED", "UNDECLARED_FIELDS_FLATTENED"],
        )
