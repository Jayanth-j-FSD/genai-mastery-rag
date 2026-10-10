"""app/console.py: the small helpers that keep the scripts from crashing on Windows."""
import io
import os
import sys
import unittest

import _testkit  # noqa: F401
from app import console


class ConsoleTests(unittest.TestCase):
    def test_an_unencodable_character_prints_as_a_replacement_instead_of_crashing(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        original = sys.stdout
        sys.stdout = stream
        try:
            console.make_output_safe()
            print("limit ≥ 10 → ok")             # neither character exists in cp1252
            stream.flush()
        finally:
            sys.stdout = original
        self.assertIn(b"limit ? 10 ? ok", stream.buffer.getvalue())

    def test_a_stream_that_cannot_be_reconfigured_is_left_alone(self):
        original = sys.stdout
        sys.stdout = io.StringIO()                           # has no reconfigure()
        try:
            console.make_output_safe()                       # must not raise
        finally:
            sys.stdout = original

    def test_display_path_is_relative_when_possible(self):
        base = os.path.abspath(os.sep + "project")
        self.assertEqual(console.display_path(os.path.join(base, "docs", "x.md"), base), os.path.join("docs", "x.md"))

    @unittest.skipUnless(os.name == "nt", "different drives only exist on Windows")
    def test_display_path_survives_a_different_drive(self):
        self.assertEqual(console.display_path(r"C:\temp\x.md", r"D:\project"), r"C:\temp\x.md")


if __name__ == "__main__":
    unittest.main()
