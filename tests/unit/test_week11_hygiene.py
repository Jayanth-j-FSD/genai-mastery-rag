"""Week 11: request logs and drill data never reach the public repository by accident."""
import os
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

    def test_nothing_is_tracked_under_data_except_the_corpus(self):
        if not os.path.exists(os.path.join(ROOT, ".git")):
            self.skipTest("a clean export has no git history to ask")
        out = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            self.skipTest("git could not list the files")
        tracked = [line for line in out.stdout.splitlines() if line.strip()]
        self.assertTrue(tracked)
        for path in tracked:
            self.assertTrue(path.startswith("data/corpus/"), f"{path} is tracked: only the corpus belongs in git under data/")


if __name__ == "__main__":
    unittest.main()
