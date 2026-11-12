"""The scripts that touch the index or the network: they must restore, verify and report, never half-finish."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from app.config import settings

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import check_all           # noqa: E402
import compare_chunks      # noqa: E402
import download_model      # noqa: E402


def run_main(module, *args):
    out = io.StringIO()
    with mock.patch.object(sys, "argv", [module.__name__ + ".py", *args]), contextlib.redirect_stdout(out):
        code = module.main()
    return code, out.getvalue()


class ChunkExperimentTests(unittest.TestCase):
    """compare_chunks re-indexes twice. Whatever happens, the index must go back to the .env settings."""

    def setUp(self):
        self.original = (settings.chunk_size, settings.chunk_overlap)
        self.restores = []

        def fake_ingest():
            self.restores.append((settings.chunk_size, settings.chunk_overlap))
            return {"chunks": 1}
        self.enterContext(mock.patch.object(compare_chunks, "ingest", fake_ingest))
        self.enterContext(mock.patch.object(compare_chunks, "retrieve", return_value=[]))
        self.addCleanup(lambda: (setattr(settings, "chunk_size", self.original[0]),
                                 setattr(settings, "chunk_overlap", self.original[1])))

    def test_a_normal_run_restores_the_original_settings_last(self):
        code, out = run_main(compare_chunks)
        self.assertEqual(code, 0)
        self.assertEqual(self.restores[-1], self.original)
        self.assertEqual(len(self.restores), 3)                              # two experiments and the restore
        self.assertIn("Index restored", out)

    def test_ctrl_c_in_the_middle_still_restores_the_index_and_still_stops_the_script(self):
        calls = {"n": 0}

        def interrupted(chunk_size, chunk_overlap):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt
            return {"chunks": 1}, []
        with mock.patch.object(compare_chunks, "_run_config", interrupted):
            with self.assertRaises(KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
                with mock.patch.object(sys, "argv", ["compare_chunks.py"]):
                    compare_chunks.main()
        self.assertEqual(self.restores, [self.original])                      # the restore ran exactly once, with the .env values
        self.assertEqual((settings.chunk_size, settings.chunk_overlap), self.original)

    def test_an_unexpected_error_in_the_middle_also_restores_before_it_propagates(self):
        def broken(chunk_size, chunk_overlap):
            raise OSError("disk went away")
        with mock.patch.object(compare_chunks, "_run_config", broken):
            with self.assertRaises(OSError), contextlib.redirect_stdout(io.StringIO()):
                with mock.patch.object(sys, "argv", ["compare_chunks.py"]):
                    compare_chunks.main()
        self.assertEqual(self.restores, [self.original])

    def test_a_clear_runtime_error_is_reported_and_the_exit_code_is_one(self):
        def refusing(chunk_size, chunk_overlap):
            raise RuntimeError("No readable documents")
        with mock.patch.object(compare_chunks, "_run_config", refusing):
            code, out = run_main(compare_chunks)
        self.assertEqual(code, 1)
        self.assertIn("Error: No readable documents", out)
        self.assertEqual(self.restores, [self.original])

    def test_a_restore_that_fails_is_reported_loudly_and_never_called_a_success(self):
        outcomes = iter([{"chunks": 1}, {"chunks": 1}])

        def ingest_then_fail():
            try:
                return next(outcomes)
            except StopIteration:
                raise OSError("could not write the index")
        with mock.patch.object(compare_chunks, "ingest", ingest_then_fail):
            code, out = run_main(compare_chunks)
        self.assertEqual(code, 1)
        self.assertIn("WARNING: the index could NOT be restored", out)
        self.assertNotIn("Index restored to your .env config", out)


class DownloadModelTests(unittest.TestCase):
    def test_the_download_is_pinned_to_one_immutable_revision_and_every_file_has_a_checksum(self):
        self.assertRegex(download_model.REVISION, r"^[0-9a-f]{40}$")
        self.assertIn(download_model.REVISION, download_model.BASE_URL)
        self.assertNotIn("/main/", download_model.BASE_URL)
        self.assertEqual(len(download_model.FILES), 6)
        for name, (size, sha256) in download_model.FILES.items():
            with self.subTest(file=name):
                self.assertGreater(size, 0)
                self.assertRegex(sha256, r"^[0-9a-f]{64}$")

    def test_a_file_is_complete_only_when_both_size_and_checksum_match(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "f.bin")
            with open(path, "wb") as handle:
                handle.write(b"abc")
            import hashlib
            good = hashlib.sha256(b"abc").hexdigest()
            self.assertTrue(download_model._is_complete(path, 3, good))
            self.assertFalse(download_model._is_complete(path, 4, good))                  # wrong size
            self.assertFalse(download_model._is_complete(path, 3, "0" * 64))               # same size, wrong content
            self.assertFalse(download_model._is_complete(os.path.join(tmp, "missing"), 3, good))

    def test_a_download_with_the_wrong_content_is_deleted_and_reported(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            def corrupt(name, destination):
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with open(destination, "wb") as handle:
                    handle.write(b"not the real file")
            with mock.patch.object(download_model, "_download", corrupt):
                code, out = run_main(download_model, "--dir", tmp)
            self.assertEqual(code, 1)
            self.assertIn("wrong, so it was deleted", out)
            self.assertFalse(os.path.exists(os.path.join(tmp, "onnx", "model.onnx")))

    def test_a_network_failure_is_a_clear_message_not_a_traceback(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with mock.patch.object(download_model, "_download", side_effect=OSError("no route to host")):
                code, out = run_main(download_model, "--dir", tmp)
        self.assertEqual(code, 1)
        self.assertIn("could not download", out)

    @unittest.skipUnless(os.path.exists(os.path.join(download_model.model_dir(), "onnx", "model.onnx")),
                         "model not downloaded")
    def test_the_model_on_this_machine_matches_the_pinned_checksums(self):
        for name, (size, sha256) in download_model.FILES.items():
            with self.subTest(file=name):
                self.assertTrue(download_model._is_complete(os.path.join(download_model.model_dir(), *name.split("/")), size, sha256))


class CheckAllTests(unittest.TestCase):
    OK = "....\n----------------------------------------------------------------------\nRan 4 tests in 0.5s\n\nOK"
    SKIPPED = "..s.\n----------------------------------------------------------------------\nRan 4 tests in 0.5s\n\nOK (skipped=1)"
    FAILED = "..F.\n----------------------------------------------------------------------\nRan 4 tests in 0.5s\n\nFAILED (failures=1)"

    def test_a_clean_run_passes(self):
        ok, summary, _ = check_all.interpret_tests(self.OK, 0, strict=False, verbose=False)
        self.assertTrue(ok)
        self.assertEqual(summary, "4 tests in 0.5s")

    def test_skipped_tests_pass_normally_but_are_named(self):
        ok, summary, _ = check_all.interpret_tests(self.SKIPPED, 0, strict=False, verbose=False)
        self.assertTrue(ok)
        self.assertIn("1 skipped", summary)

    def test_strict_mode_refuses_to_call_a_run_with_skipped_tests_clean(self):
        ok, summary, detail = check_all.interpret_tests(self.SKIPPED, 0, strict=True, verbose=False)
        self.assertFalse(ok)
        self.assertIn("skipped", detail)

    def test_a_failing_run_always_fails_and_shows_its_output(self):
        ok, _, detail = check_all.interpret_tests(self.FAILED, 1, strict=False, verbose=False)
        self.assertFalse(ok)
        self.assertIn("FAILED (failures=1)", detail)

    def test_no_result_at_all_is_a_failure(self):
        ok, summary, _ = check_all.interpret_tests("", 1, strict=False, verbose=False)
        self.assertFalse(ok)
        self.assertIn("no result", summary)


if __name__ == "__main__":
    unittest.main()
