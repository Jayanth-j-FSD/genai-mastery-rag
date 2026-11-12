"""Week 11: request logs and drill data never reach the public repository by accident."""
import glob
import json
import os
import re
import subprocess
import unittest

import _testkit

ROOT = _testkit.ROOT


def ignored_lines():
    with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as handle:
        return {line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")}


class IgnoreTests(unittest.TestCase):
    def test_every_folder_that_holds_request_text_is_ignored(self):
        lines = ignored_lines()
        for folder in ("data/traces/", "data/chroma/", "data/drill/", "data/measure/"):
            self.assertIn(folder, lines, f"{folder} is not in .gitignore: a log would be committed by git add -A")

    def test_the_copies_a_resume_and_a_forced_run_keep_beside_a_result_are_ignored(self):
        lines = ignored_lines()
        for pattern in ("evals/results/*.replaced-*.json", "evals/results/*.incomplete.json"):
            self.assertIn(pattern, lines, f"{pattern} is not in .gitignore: git add evals/results would stage a stray file")

    def files_under_data(self):
        """The files git tracks under data/. In a clean export (git archive) there is no history to ask, but an export holds only
        tracked files, so what is on disk, less the folders .gitignore names (a test run may fill those), is the same list."""
        out = None
        if os.path.exists(os.path.join(ROOT, ".git")):
            out = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if out is not None and out.returncode == 0:
            return [line for line in out.stdout.splitlines() if line.strip()]
        ignored = tuple(line for line in ignored_lines() if line.startswith("data/") and line.endswith("/"))
        found = []
        for folder, _dirs, names in os.walk(os.path.join(ROOT, "data")):
            for name in names:
                path = os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, "/")
                if not path.startswith(ignored):
                    found.append(path)
        return found

    def test_nothing_is_tracked_under_data_except_the_corpus(self):
        tracked = self.files_under_data()
        self.assertTrue(tracked)
        for path in tracked:
            self.assertTrue(path.startswith("data/corpus/"), f"{path} is tracked: only the corpus belongs in git under data/")


def tracked_week11_files():
    """What this week commits that could carry text from a log or a machine: its documents, the fixtures, the saved measurements."""
    found = []
    for pattern in ("docs/week11/*.md", "tests/fixtures/**/*.json", "evals/results/cost-*.json", "evals/logged_failures.json"):
        found += glob.glob(os.path.join(ROOT, pattern), recursive=True)
    return sorted(set(found))


# A drive letter and a slash (the letter standing alone, so the "s:/" of a web address is not one), a file URL, a home folder.
MACHINE = re.compile("(?<![A-Za-z0-9_])[A-Za-z]:[" + chr(92) + chr(92) + "/]|file:///|/Users/|/home/")
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+\.(?!example\b)[\w.]+")        # an address, except one at a name ending in .example
CURLY_QUOTES = [chr(0x2018), chr(0x2019), chr(0x201C), chr(0x201D)]


class DocumentHygieneTests(unittest.TestCase):
    def test_a_web_address_is_not_a_place_on_a_machine_but_a_drive_a_file_url_and_a_home_folder_are(self):
        for fine in ("https://ai.google.dev/gemini-api/docs/pricing", "http://example.org/a", "see https://x.test and ftp://y.test"):
            self.assertIsNone(MACHINE.search(fine), fine)
        for bad in ("C:" + chr(92) + "Users" + chr(92) + "x", "d:/work/x", "a path (C:/x)", "file:///tmp/x", "/Users/someone/x", "/home/someone/x"):
            self.assertIsNotNone(MACHINE.search(bad), bad)

    def test_an_address_at_a_name_ending_in_example_is_allowed_and_any_other_is_not(self):
        self.assertIsNone(ADDRESS.search("report it to security@northwind.example within an hour"))
        self.assertIsNotNone(ADDRESS.search("write to someone@company.com"))

    def test_no_em_dash_machine_path_file_url_or_personal_address_in_what_the_week_commits(self):
        paths = tracked_week11_files()
        self.assertTrue(any(p.endswith("prediction.md") for p in paths))
        for path in paths:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            name = os.path.relpath(path, ROOT)
            self.assertNotIn(chr(0x2014), text, f"{name} has an em dash")
            self.assertNotIn(chr(0x2013), text, f"{name} has an en dash")
            for quote in CURLY_QUOTES:
                self.assertNotIn(quote, text, f"{name} has a curly quote (U+{ord(quote):04X})")
            self.assertIsNone(MACHINE.search(text), f"{name} names a place on a machine")
            self.assertIsNone(ADDRESS.search(text), f"{name} holds an address")

    def test_nothing_in_the_agent_machinery_reads_the_drill(self):
        agent = os.path.join(ROOT, "app", "agent")
        for name in os.listdir(agent):
            if name.endswith(".py"):
                with open(os.path.join(agent, name), encoding="utf-8") as handle:
                    self.assertNotIn("drill", handle.read().lower(), f"app/agent/{name} mentions the drill")

    def test_a_saved_measurement_holds_numbers_and_names_only(self):
        for path in glob.glob(os.path.join(ROOT, "evals", "results", "cost-*.json")):
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            for row in saved["rows"]:
                self.assertTrue({"answer", "question", "text", "retrieved", "passages"}.isdisjoint(row), os.path.basename(path))


if __name__ == "__main__":
    unittest.main()
