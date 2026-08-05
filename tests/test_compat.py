import unittest

from doc2docx.diagnostics import Severity
from doc2docx.model import BreakType, SectionBreakType


class CompatibilityTests(unittest.TestCase):
    def test_string_enums_retain_strenum_behavior(self) -> None:
        for member, value in (
            (Severity.WARNING, "warning"),
            (BreakType.PAGE, "page"),
            (SectionBreakType.NEXT_COLUMN, "nextColumn"),
        ):
            with self.subTest(member=member):
                self.assertIsInstance(member, str)
                self.assertEqual(member.value, value)
                self.assertEqual(str(member), value)
                self.assertEqual(f"{member}", value)


if __name__ == "__main__":
    unittest.main()
