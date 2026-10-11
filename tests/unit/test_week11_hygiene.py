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


if __name__ == "__main__":
    unittest.main()
