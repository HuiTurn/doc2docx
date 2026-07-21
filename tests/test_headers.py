import unittest
from unittest.mock import Mock

from doc2docx.diagnostics import ConversionReport
from doc2docx.errors import InvalidWordDocument
from doc2docx.model import SectionProperties
from doc2docx.msdoc import read_document_settings, read_header_footer_stories


class HeaderFooterParsingTests(unittest.TestCase):
    def test_dop_facing_pages_flag_is_read(self) -> None:
        settings = read_document_settings(b"\x01\x00", offset=0, size=2)
        self.assertTrue(settings.even_and_odd_headers)

    def test_truncated_dop_is_rejected(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_document_settings(b"\x01", offset=0, size=1)

    def test_plcf_hdd_must_have_six_stories_per_section(self) -> None:
        with self.assertRaises(InvalidWordDocument):
            read_header_footer_stories(
                bytes(52),
                Mock(cp_end=100),
                (SectionProperties(0, 1),),
                offset=0,
                size=52,
                ccp_headers=2,
                header_story_cp_start=1,
                report=ConversionReport("malformed-headers.doc"),
            )


if __name__ == "__main__":
    unittest.main()
