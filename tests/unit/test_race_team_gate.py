"""Week 10: the gate (scripts/check_all.py) compiles the project's own code, not hidden folders such as other working copies beside it (no model calls)."""
import contextlib
import io
import os
import subprocess
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


class Finished:
    """What check_all.run returns: a finished process."""

    def __init__(self, returncode=0, stderr=""):
        self.returncode, self.stderr = returncode, stderr


class CompileBatchTests(unittest.TestCase):
    def test_the_files_are_compiled_in_batches_so_a_deep_folder_path_cannot_overflow_the_command_line(self):
        files = [f"/deep/{n}.py" for n in range(check_all.COMPILE_BATCH * 2 + 5)]
        calls = []
        with mock.patch.object(check_all, "python_files", return_value=iter(files)), \
                mock.patch.object(check_all, "run", side_effect=lambda args, timeout=600: calls.append(args) or Finished()):
            ok, summary, detail = check_all.check_compile()
        self.assertEqual((ok, summary, detail), (True, f"{len(files)} files", ""))
        self.assertEqual([len(args) - 3 for args in calls], [check_all.COMPILE_BATCH, check_all.COMPILE_BATCH, 5])      # python -m py_compile, then the files
        self.assertEqual([path for args in calls for path in args[3:]], files)                                          # every file once, in order

    def test_a_file_that_does_not_compile_fails_the_check_and_every_batch_is_still_tried(self):
        files = [f"/deep/{n}.py" for n in range(check_all.COMPILE_BATCH + 1)]
        outcomes = iter([Finished(1, "SyntaxError in the first batch"), Finished(1, "SyntaxError in the second")])
        with mock.patch.object(check_all, "python_files", return_value=iter(files)), mock.patch.object(check_all, "run", side_effect=lambda *a, **k: next(outcomes)):
            ok, _summary, detail = check_all.check_compile()
        self.assertFalse(ok)
        self.assertIn("first batch", detail)
        self.assertIn("the second", detail)

    def test_a_check_that_cannot_even_start_is_a_fail_line_and_not_a_traceback(self):
        out = io.StringIO()
        broken = mock.Mock(side_effect=OSError("[WinError 206] The filename or extension is too long"))
        with mock.patch.object(check_all, "check_compile", broken), mock.patch.object(check_all, "check_imports", return_value=(True, "ok", "")), \
                mock.patch.object(sys, "argv", ["check_all.py", "--quick"]), mock.patch.object(check_all, "check_tests", return_value=(True, "ok", "")), \
                contextlib.redirect_stdout(out):
            code = check_all.main()
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] compile", out.getvalue())
        self.assertIn("WinError 206", out.getvalue())


if __name__ == "__main__":
    unittest.main()
