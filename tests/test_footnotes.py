import struct
from pathlib import Path
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import (
    CharacterProperties,
    Comment,
    CommentRangeEnd,
    CommentRangeStart,
    CommentReference,
    Document,
    Endnote,
    EndnoteReference,
    Footnote,
    FootnoteReference,
    HeaderFooterStory,
    Paragraph,
    SectionProperties,
    TextRun,
)
from doc2docx.msdoc.footnotes import read_footnotes
from doc2docx.msdoc.pieces import Piece, PieceTable
from doc2docx.ooxml import write_docx


REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class FootnoteParsingTests(unittest.TestCase):
    def test_note_and_comment_relationship_ids_do_not_collide(self) -> None:
        document = Document(
            paragraphs=(
                Paragraph(
                    (
                        FootnoteReference(1),
                        EndnoteReference(1),
                        CommentRangeStart(0),
                        TextRun("Commented"),
                        CommentRangeEnd(0),
                        CommentReference(0),
                    )
                ),
            ),
            footnotes=(
                Footnote(1, (Paragraph((TextRun("Footnote"),)),)),
            ),
            endnotes=(
                Endnote(1, (Paragraph((TextRun("Endnote"),)),)),
            ),
            comments=(
                Comment(
                    0,
                    "Alice",
                    "AL",
                    (Paragraph((TextRun("Comment"),)),),
                ),
            ),
            sections=(
                SectionProperties(
                    0,
                    1,
                    default_header=HeaderFooterStory(
                        0,
                        1,
                        (Paragraph((TextRun("Header"),)),),
                    ),
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "both-notes.docx"
            write_docx(document, destination)
            with zipfile.ZipFile(destination) as package:
                relationships = ET.fromstring(
                    package.read("word/_rels/document.xml.rels")
                )
                names = set(package.namelist())

        note_relationships = [
            value
            for value in relationships.findall(f"{REL}Relationship")
            if value.get("Target")
            in {"footnotes.xml", "endnotes.xml", "comments.xml"}
        ]
        self.assertEqual(
            {value.get("Target") for value in note_relationships},
            {"footnotes.xml", "endnotes.xml", "comments.xml"},
        )
        self.assertEqual(len({value.get("Id") for value in note_relationships}), 3)
        all_relationships = relationships.findall(f"{REL}Relationship")
        self.assertEqual(
            len({value.get("Id") for value in all_relationships}),
            len(all_relationships),
        )
        self.assertTrue(
            {
                "word/footnotes.xml",
                "word/endnotes.xml",
                "word/comments.xml",
            }.issubset(names)
        )
        self.assertIn("word/header1.xml", names)

    @staticmethod
    def _piece_table() -> PieceTable:
        data = b"\x02\rA\r\r\r"
        return PieceTable((Piece(0, len(data), 0, True, 0),), data)

    def test_footnote_fib_parts_must_exist_together(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_footnotes(
                b"",
                self._piece_table(),
                ccp_text=2,
                ccp_footnotes=3,
                reference_offset=0,
                reference_size=0,
                text_offset=0,
                text_size=0,
                report=ConversionReport("missing-footnote-plcs.doc"),
            )

    def test_malformed_reference_plc_size_is_rejected(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_footnotes(
                b"\0" * 32,
                self._piece_table(),
                ccp_text=2,
                ccp_footnotes=3,
                reference_offset=0,
                reference_size=9,
                text_offset=16,
                text_size=12,
                report=ConversionReport("bad-footnote-reference-plc.doc"),
            )

    def test_duplicate_reference_and_text_cps_are_rejected(self) -> None:
        duplicate_references = struct.pack("<3I2H", 0, 0, 2, 1, 1)
        valid_text = struct.pack("<3I", 0, 2, 3)
        duplicate_text = struct.pack("<3I", 0, 0, 3)
        valid_reference = struct.pack("<2IH", 0, 2, 1)
        cases = (
            (duplicate_references + valid_text, len(duplicate_references)),
            (valid_reference + duplicate_text, len(valid_reference)),
        )

        for index, (table_stream, reference_size) in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(InvalidWordDocument):
                    read_footnotes(
                        table_stream,
                        self._piece_table(),
                        ccp_text=2,
                        ccp_footnotes=3,
                        reference_offset=0,
                        reference_size=reference_size,
                        text_offset=reference_size,
                        text_size=12,
                        report=ConversionReport("duplicate-footnote-cp.doc"),
                        character_properties_at=lambda _cp: CharacterProperties(
                            special=True
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
