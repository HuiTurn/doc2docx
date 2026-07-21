import struct
import unittest

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.msdoc.sections import read_sections


class SectionParsingTests(unittest.TestCase):
    def test_later_section_sprm_wins(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HH", 0xB01F, 10000),
                struct.pack("<HH", 0xB01F, 12000),
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1100),
                struct.pack("<Hh", 0x9023, 1200),
                struct.pack("<Hh", 0x9024, 1300),
                struct.pack("<Hi", 0x7030, -4096),
                struct.pack("<HH", 0x9031, 312),
                struct.pack("<HH", 0x5032, 2),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("fixture.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=2052,
            report=report,
        )

        self.assertEqual(sections[0].page_width_twips, 12000)
        self.assertEqual(sections[0].header_distance_twips, 720)
        self.assertEqual(sections[0].document_grid_type, "lines")
        self.assertEqual(sections[0].document_grid_line_pitch_twips, 312)
        self.assertEqual(sections[0].document_grid_character_space, -4096)
        self.assertFalse(report.warnings)

    def test_incomplete_document_grid_is_reported_and_omitted(self) -> None:
        grpprl = b"".join(
            (
                struct.pack("<HH", 0xB021, 1000),
                struct.pack("<HH", 0xB022, 1000),
                struct.pack("<Hh", 0x9023, 1000),
                struct.pack("<Hh", 0x9024, 1000),
                struct.pack("<HH", 0x5032, 2),
            )
        )
        word_document = bytearray(128)
        struct.pack_into("<h", word_document, 32, len(grpprl))
        word_document[34 : 34 + len(grpprl)] = grpprl
        plcf_sed = struct.pack("<2I", 0, 5)
        plcf_sed += struct.pack("<HiHI", 0, 32, 0, 0)
        report = ConversionReport("fixture.doc")

        sections = read_sections(
            plcf_sed,
            bytes(word_document),
            offset=0,
            size=len(plcf_sed),
            main_story_cp_count=5,
            document_lid=2052,
            report=report,
        )

        self.assertIsNone(sections[0].document_grid_type)
        self.assertEqual(
            [warning.code for warning in report.warnings],
            ["SECTION_GRID_INCOMPLETE"],
        )

    def test_malformed_plcf_sed_size_is_rejected(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_sections(
                bytes(19),
                bytes(64),
                offset=0,
                size=19,
                main_story_cp_count=1,
                document_lid=1033,
                report=ConversionReport("malformed.doc"),
            )

    def test_truncated_sepx_is_rejected(self) -> None:
        plcf_sed = struct.pack("<2I", 0, 1)
        plcf_sed += struct.pack("<HiHI", 0, 63, 0, 0)
        with self.assertRaises(InvalidWordDocument):
            read_sections(
                plcf_sed,
                bytes(64),
                offset=0,
                size=len(plcf_sed),
                main_story_cp_count=1,
                document_lid=1033,
                report=ConversionReport("truncated.doc"),
            )


if __name__ == "__main__":
    unittest.main()
