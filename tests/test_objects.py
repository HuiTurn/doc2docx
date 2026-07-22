from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile

from doc2docx.cfb import CompoundFile, DirectoryEntry, ObjectType
from doc2docx.cfb.constants import ENDOFCHAIN, NOSTREAM
from doc2docx.cfb.writer import write_compound_storage
from doc2docx.diagnostics import ConversionReport
from doc2docx.model import (
    CharacterProperties,
    Document,
    EmbeddedObject,
    InlinePicture,
    Paragraph,
    StoryCharacter,
    parse_main_story,
)
from doc2docx.msdoc.objects import read_embedded_objects
from doc2docx.ooxml import write_docx


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
O = "{urn:schemas-microsoft-com:office:office}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"


def _entry(name: str, object_type: ObjectType, entry_id: int) -> DirectoryEntry:
    return DirectoryEntry(
        entry_id,
        name,
        object_type,
        1,
        NOSTREAM,
        NOSTREAM,
        NOSTREAM,
        bytes((entry_id,)) + b"\0" * 15,
        0,
        0,
        0,
        ENDOFCHAIN,
        0,
    )


def _source_with_object_pool() -> bytes:
    return write_compound_storage(
        _entry("Root Entry", ObjectType.ROOT_STORAGE, 0),
        (
            ("ObjectPool", _entry("ObjectPool", ObjectType.STORAGE, 1), None),
            ("ObjectPool/_123", _entry("_123", ObjectType.STORAGE, 2), None),
            (
                "ObjectPool/_123/Contents",
                _entry("Contents", ObjectType.STREAM, 3),
                b"embedded payload",
            ),
        ),
    )


class EmbeddedObjectTests(unittest.TestCase):
    def test_matches_separator_picture_location_and_exports_storage(self) -> None:
        report = ConversionReport("objects.doc")
        characters = (StoryCharacter("\x14", 7, 8),)
        properties = CharacterProperties(picture_location=123, special=True)

        values = read_embedded_objects(
            CompoundFile(_source_with_object_pool()),
            characters,
            report=report,
            character_properties_at=lambda _cp: properties,
        )

        self.assertEqual(len(values.objects), 1)
        self.assertIs(values.object_at(7), values.objects[0])
        embedded = CompoundFile(values.objects[0].data)
        self.assertEqual(embedded.open_stream("Contents"), b"embedded payload")
        self.assertFalse(report.warnings)

    def test_embed_field_uses_confirmed_object_and_cached_preview(self) -> None:
        text = "\x13 EMBED Package \x14\x01\x15\r"
        separator_cp = text.index("\x14")
        preview_cp = text.index("\x01")
        preview = InlinePicture(
            1,
            0,
            b"preview",
            "png",
            "image/png",
            914400,
            457200,
        )
        template = EmbeddedObject(1, 123, _source_with_object_pool())
        report = ConversionReport("objects.doc")

        document = parse_main_story(
            text,
            report,
            embedded_object_at=(
                lambda cp: template if cp == separator_cp else None
            ),
            inline_picture_at=lambda cp: preview if cp == preview_cp else None,
        )

        value = document.paragraphs[0].inlines[0]
        self.assertIsInstance(value, EmbeddedObject)
        assert isinstance(value, EmbeddedObject)
        self.assertIs(value.preview, preview)
        self.assertEqual(value.prog_id, "Package")
        self.assertFalse(report.warnings)

    def test_packages_object_storage_relationship_and_preview(self) -> None:
        preview = InlinePicture(
            1,
            0,
            b"preview",
            "png",
            "image/png",
            914400,
            457200,
        )
        embedded = EmbeddedObject(
            1,
            123,
            CompoundFile(_source_with_object_pool()).export_storage(
                "ObjectPool/_123"
            ),
            prog_id="Package",
            preview=preview,
        )
        document = Document(
            (Paragraph((embedded,)),),
            pictures=(preview,),
            embedded_objects=(embedded,),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "objects.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                payload = package.read("word/embeddings/oleObject1.bin")
                relationships = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                content_types = ET.fromstring(package.read("[Content_Types].xml"))
                document_xml = ET.fromstring(package.read("word/document.xml"))

        self.assertEqual(
            CompoundFile(payload).open_stream("Contents"),
            b"embedded payload",
        )
        relationship = next(
            item
            for item in relationships.findall(f"{REL}Relationship")
            if item.get("Type", "").endswith("/oleObject")
        )
        self.assertEqual(relationship.get("Id"), "rIdOleObject1")
        self.assertEqual(relationship.get("Target"), "embeddings/oleObject1.bin")
        binary_default = next(
            item
            for item in content_types.findall(f"{CT}Default")
            if item.get("Extension") == "bin"
        )
        self.assertIn("oleObject", binary_default.get("ContentType", ""))
        ole_object = document_xml.find(f".//{O}OLEObject")
        assert ole_object is not None
        self.assertEqual(ole_object.get(f"{R}id"), "rIdOleObject1")
        self.assertEqual(ole_object.get("ProgID"), "Package")
        self.assertIsNotNone(document_xml.find(f".//{W}object"))


if __name__ == "__main__":
    unittest.main()
