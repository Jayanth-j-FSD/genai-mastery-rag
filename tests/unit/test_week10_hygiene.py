"""Week 10: what the repository publishes must stay plain: no stray dashes, no machine paths, no addresses, no key-shaped text."""
import glob
import os
import re
import unittest

import _testkit

ROOT = _testkit.ROOT
WEEK_10_NAMES = ("team", "pricing", "llm_scope", "week10", "pilot")          # a file whose name has one of these words is Week 10's
CHANGED_EXISTING = ("app/agent/display.py", "app/llm.py", "scripts/run_agent.py", "tests/unit/test_agent_scripts.py", ".env.example")
NEW_CODE = ("app/agent/team.py", "app/pricing.py", "evals/team_report.py", "evals/team_prediction.py", "scripts/race_team.py",
            "scripts/pilot_team.py", "scripts/check_team_prediction.py")


def week_10_files():
    """Every Week 10 file (code and tests, found by name) and the existing files Week 10 changed, as paths relative to the project."""
    found = set(CHANGED_EXISTING)
    for folder in ("app", "evals", "scripts", "tests/unit"):
        for path in glob.glob(os.path.join(ROOT, folder, "**", "*.py"), recursive=True):
            if any(word in os.path.basename(path) for word in WEEK_10_NAMES):
                found.add(os.path.relpath(path, ROOT).replace(os.sep, "/"))
    return sorted(found)


DOCS = sorted(glob.glob(os.path.join(ROOT, "docs", "week10", "*.md")))
RESULTS = sorted(glob.glob(os.path.join(ROOT, "evals", "results", "race-wk10*.json")) + glob.glob(os.path.join(ROOT, "evals", "results", "pilot-*.json")))
DASHES = "\u2014\u2013"
CURLY = "\u2018\u2019\u201c\u201d"
DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.(?!example\b)[A-Za-z][\w.-]*")
KEYS = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class HygieneTests(unittest.TestCase):
    def test_the_week_10_documents_exist_so_this_test_is_not_scanning_nothing(self):
        self.assertTrue(any(path.endswith("README.md") for path in DOCS))

    def test_no_week_10_document_has_a_long_dash_or_a_curly_quote(self):
        for path in DOCS:
            text = read(path)
            for glyph in DASHES + CURLY:
                self.assertNotIn(glyph, text, f"{os.path.basename(path)} has U+{ord(glyph):04X}")

    def test_the_scan_covers_the_tests_and_the_existing_files_week_10_changed_not_only_the_new_code(self):
        files = week_10_files()
        for relative in ("app/agent/team.py", "app/llm.py", "app/agent/display.py", ".env.example", "tests/unit/test_agent_team.py",
                         "tests/unit/test_llm_scope.py", "tests/unit/test_week10_hygiene.py", "tests/unit/test_pricing.py"):
            self.assertIn(relative, files)
        self.assertTrue(set(NEW_CODE) <= set(files))

    def test_no_week_10_file_has_a_long_dash_or_a_curly_quote(self):
        for relative in week_10_files():
            text = read(os.path.join(ROOT, relative))
            for glyph in DASHES + CURLY:                                           # an escape such as \\u2019 in source is not the glyph itself
                self.assertNotIn(glyph, text, f"{relative} has U+{ord(glyph):04X}")

    def test_the_new_code_has_no_long_dash_and_no_curly_quote(self):
        for relative in NEW_CODE:
            text = read(os.path.join(ROOT, relative))
            for glyph in DASHES + CURLY:                                           # an escape such as \\u2019 in source is not the glyph itself
                self.assertNotIn(glyph, text, f"{relative} has U+{ord(glyph):04X}")

    def test_nothing_published_names_a_drive_or_a_file_url(self):
        for path in [os.path.join(ROOT, relative) for relative in NEW_CODE] + DOCS + RESULTS:
            text = read(path)
            self.assertIsNone(DRIVE_PATH.search(text), f"{os.path.basename(path)} has a machine path")
            self.assertNotIn("file:" + "//" + "/", text, os.path.basename(path))

    def test_the_documents_and_saved_results_hold_no_email_address_outside_the_sample_domain_and_no_key_shaped_text(self):
        for path in DOCS + RESULTS:
            text = read(path)
            self.assertIsNone(EMAIL.search(text), f"{os.path.basename(path)} has an email address: {EMAIL.search(text)}")
            self.assertIsNone(KEYS.search(text), f"{os.path.basename(path)} has key-shaped text")

    def test_the_code_never_spells_a_key(self):
        for relative in NEW_CODE:
            self.assertIsNone(KEYS.search(read(os.path.join(ROOT, relative))), relative)

    def test_a_saved_race_or_pilot_has_no_key_value_or_project_path_in_it(self):
        from app.config import settings
        key = settings.openai_api_key
        for path in RESULTS:
            text = read(path)
            if key and len(key) >= 8:
                self.assertNotIn(key, text, os.path.basename(path))
            self.assertNotIn(str(_testkit.ROOT), text, os.path.basename(path))
            self.assertNotIn(str(_testkit.ROOT).replace("\\", "\\\\"), text, os.path.basename(path))


if __name__ == "__main__":
    unittest.main()
