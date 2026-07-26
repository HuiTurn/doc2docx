from datetime import datetime, timezone
from pathlib import Path
import struct
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import CoreProperties, Document, Paragraph, TextRun
from doc2docx.oleps import read_summary_information
from doc2docx.ooxml import write_docx


CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
DC = "{http://purl.org/dc/elements/1.1/}"
DCTERMS = "{http://purl.org/dc/terms/}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
SUMMARY_FMTID = bytes.fromhex("e0859ff2f94f6810ab9108002b27b3d9")


def _lpstr(value: str, encoding: str = "cp1252") -> bytes:
    payload = value.encode(encoding) + b"\0"
    result = struct.pack("<HHI", 0x001E, 0, len(payload)) + payload
    return result + bytes((-len(result)) % 4)


def _filetime(value: datetime) -> bytes:
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    ticks = int((value - epoch).total_seconds() * 10_000_000)
    return struct.pack("<HHQ", 0x0040, 0, ticks)


def _summary_stream() -> bytes:
    properties = {
        0x01: struct.pack("<HHHH", 0x0002, 0, 1252, 0),
        0x02: _lpstr("Résumé title"),
        0x03: _lpstr("Binary formats"),
        0x04: _lpstr("Ada"),
        0x05: _lpstr("doc,conversion"),
        0x06: _lpstr("Regression metadata"),
        0x08: _lpstr("Grace"),
        0x09: _lpstr("7"),
        0x0C: _filetime(datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)),
        0x0D: _filetime(datetime(2021, 2, 3, 4, 5, 6, tzinfo=timezone.utc)),
    }
    table_size = 8 + len(properties) * 8
    payload = bytearray()
    entries: list[tuple[int, int]] = []
    for property_id, value in properties.items():
        entries.append((property_id, table_size + len(payload)))
        payload.extend(value)
    property_set_size = table_size + len(payload)
    property_set = bytearray(struct.pack("<II", property_set_size, len(properties)))
    for property_id, offset in entries:
        property_set.extend(struct.pack("<II", property_id, offset))
    property_set.extend(payload)
    header = struct.pack("<HHI16sI", 0xFFFE, 0, 0, bytes(16), 1)
    return header + SUMMARY_FMTID + struct.pack("<I", 48) + bytes(property_set)


def _summary_stream_with_word_style_padding() -> bytes:
    """Word pads VT_LPSTR payloads to 4 bytes inside the declared count."""

    def padded_lpstr(value: str) -> bytes:
        payload = value.encode("cp1252") + b"\0"
        payload += b"\0" * ((-len(payload)) % 4)
        return struct.pack("<HHI", 0x001E, 0, len(payload)) + payload

    properties = {
        0x01: struct.pack("<HHHH", 0x0002, 0, 1252, 0),
        0x02: padded_lpstr("doc2docx bilateral fixture"),
        0x03: padded_lpstr(""),
        0x04: padded_lpstr("Ada"),
        0x09: padded_lpstr("1"),
    }
    table_size = 8 + len(properties) * 8
    payload = bytearray()
    entries: list[tuple[int, int]] = []
    for property_id, value in properties.items():
        entries.append((property_id, table_size + len(payload)))
        payload.extend(value)
    property_set_size = table_size + len(payload)
    property_set = bytearray(struct.pack("<II", property_set_size, len(properties)))
    for property_id, offset in entries:
        property_set.extend(struct.pack("<II", property_id, offset))
    property_set.extend(payload)
    header = struct.pack("<HHI16sI", 0xFFFE, 0, 0, bytes(16), 1)
    return header + SUMMARY_FMTID + struct.pack("<I", 48) + bytes(property_set)


def _summary_stream_with_title_property(title_property: bytes) -> bytes:
    properties = {
        0x01: struct.pack("<HHHH", 0x0002, 0, 1252, 0),
        0x02: title_property,
    }
    table_size = 8 + len(properties) * 8
    payload = bytearray()
    entries: list[tuple[int, int]] = []
    for property_id, value in properties.items():
        entries.append((property_id, table_size + len(payload)))
        payload.extend(value)
        payload.extend(bytes((-len(payload)) % 4))
    property_set_size = table_size + len(payload)
    property_set = bytearray(struct.pack("<II", property_set_size, len(properties)))
    for property_id, offset in entries:
        property_set.extend(struct.pack("<II", property_id, offset))
    property_set.extend(payload)
    header = struct.pack("<HHI16sI", 0xFFFE, 0, 0, bytes(16), 1)
    return header + SUMMARY_FMTID + struct.pack("<I", 48) + bytes(property_set)


class CorePropertyTests(unittest.TestCase):
    def test_reads_summary_information_strings_and_filetimes(self) -> None:
        report = ConversionReport("metadata.doc")

        properties = read_summary_information(_summary_stream(), report=report)

        self.assertEqual(properties.title, "Résumé title")
        self.assertEqual(properties.subject, "Binary formats")
        self.assertEqual(properties.creator, "Ada")
        self.assertEqual(properties.keywords, "doc,conversion")
        self.assertEqual(properties.description, "Regression metadata")
        self.assertEqual(properties.last_modified_by, "Grace")
        self.assertEqual(properties.revision, "7")
        self.assertEqual(properties.created, "2020-01-02T03:04:05Z")
        self.assertEqual(properties.modified, "2021-02-03T04:05:06Z")
        self.assertFalse(report.warnings)

    def test_truncates_word_style_lpstr_alignment_padding(self) -> None:
        report = ConversionReport("word-padded-metadata.doc")

        properties = read_summary_information(
            _summary_stream_with_word_style_padding(),
            report=report,
        )

        self.assertEqual(properties.title, "doc2docx bilateral fixture")
        self.assertIsNone(properties.subject)
        self.assertEqual(properties.creator, "Ada")
        self.assertEqual(properties.revision, "1")
        self.assertNotIn("\uFFFD", properties.title or "")
        self.assertFalse(report.warnings)

    def test_truncates_lpwstr_trailing_nulls(self) -> None:
        payload = "Wide title\0\0".encode("utf-16le")
        title_property = struct.pack("<HHI", 0x001F, 0, len(payload) // 2) + payload
        report = ConversionReport("wide-padded-metadata.doc")

        properties = read_summary_information(
            _summary_stream_with_title_property(title_property),
            report=report,
        )

        self.assertEqual(properties.title, "Wide title")
        self.assertFalse(report.warnings)

    def test_reports_nonzero_data_after_string_terminator(self) -> None:
        payload = b"Safe title\0ignored\0"
        title_property = struct.pack("<HHI", 0x001E, 0, len(payload)) + payload
        report = ConversionReport("embedded-null-metadata.doc")

        properties = read_summary_information(
            _summary_stream_with_title_property(title_property),
            report=report,
        )

        self.assertEqual(properties.title, "Safe title")
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["SUMMARY_INFORMATION_TEXT_REPAIRED"],
        )

    def test_writes_core_part_content_type_and_relationship(self) -> None:
        document = Document(
            (Paragraph((TextRun("metadata"),)),),
            core_properties=CoreProperties(
                title="Résumé title",
                creator="Ada",
                revision="7",
                created="2020-01-02T03:04:05Z",
                last_printed="2022-03-04T05:06:07Z",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "metadata.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                names = set(package.namelist())
                core = ET.fromstring(package.read("docProps/core.xml"))
                relationships = ET.fromstring(package.read("_rels/.rels"))
                content_types = package.read("[Content_Types].xml").decode()

        self.assertIn("docProps/core.xml", names)
        self.assertEqual(core.find(f"{DC}title").text, "Résumé title")
        self.assertEqual(core.find(f"{DC}creator").text, "Ada")
        self.assertEqual(core.find(f"{CP}revision").text, "7")
        self.assertEqual(
            core.find(f"{DCTERMS}created").text,
            "2020-01-02T03:04:05Z",
        )
        self.assertEqual(
            core.find(f"{CP}lastPrinted").text,
            "2022-03-04T05:06:07Z",
        )
        core_relationship = next(
            relationship
            for relationship in relationships.findall(f"{REL}Relationship")
            if relationship.get("Target") == "docProps/core.xml"
        )
        self.assertTrue(
            core_relationship.get("Type", "").endswith("/core-properties")
        )
        self.assertIn("/docProps/core.xml", content_types)

    def test_rejects_unbounded_or_duplicate_properties(self) -> None:
        original = _summary_stream()
        invalid_set_offset = bytearray(original)
        struct.pack_into("<I", invalid_set_offset, 44, len(original) + 4)

        duplicate = bytearray(original)
        property_set_offset = 48
        first_property_id = struct.unpack_from("<I", duplicate, 56)[0]
        struct.pack_into("<I", duplicate, 64, first_property_id)

        for payload in (bytes(invalid_set_offset), bytes(duplicate)):
            with self.subTest(size=len(payload)):
                with self.assertRaises(InvalidWordDocument):
                    read_summary_information(
                        payload,
                        report=ConversionReport("invalid.doc"),
                    )
