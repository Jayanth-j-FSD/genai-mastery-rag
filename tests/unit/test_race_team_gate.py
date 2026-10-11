"""Week 10: the gate (scripts/check_all.py) compiles the project's own code, not hidden folders such as other working copies beside it (no model calls)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import check_all           # noqa: E402


class CompileWalkTests(unittest.TestCase):
    def test_hidden_folders_are_not_compiled_but_the_projects_own_folders_are(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        wanted = ["top.py", os.path.join("app", "inner.py"), os.path.join("tests", "unit", "test_x.py")]
        unwanted = [os.path.join(".copy-a", "app", "wip.py"), os.path.join(".copy-b", "wip.py"), os.path.join(".venv-old-path", "lib.py"),
                    os.path.join("data", "corpus", "d.py")]
        for relative in wanted + unwanted:
            path = os.path.join(folder, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("VALUE = 1\n")
        with mock.patch.object(check_all, "ROOT", folder):
            found = sorted(os.path.relpath(path, folder) for path in check_all.python_files())
        self.assertEqual(found, sorted(wanted))


if __name__ == "__main__":
    unittest.main()
