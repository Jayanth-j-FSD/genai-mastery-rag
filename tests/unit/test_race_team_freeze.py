"""Week 10: scripts/race_team.py freezes what a race ran on, read from a REAL git repository (neither git nor the stamp is replaced here)."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from app import llm
from evals import runner
from test_race_team import MODEL, TWO, Racer, captured

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import race_team           # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}       # a throwaway repository reads no configuration of the machine it runs on
IDENTITY = ["-c", "user.name=Tester", "-c", "user.email=tester@example.com", "-c", "commit.gpgsign=false"]
PREDICTION = "docs/week10/prediction.md"
CODE = ("app/__init__.py", "app/agent/team.py", "app/agent/loop.py", "app/agent/memory.py", "app/llm.py", "app/rag/retriever.py",
        "evals/__init__.py", "evals/checks.py", "evals/agent_tasks.py", "evals/race.py", "evals/team_prediction.py",
        "scripts/race_team.py", "scripts/pilot_team.py")
NOT_CODE = ("scripts/other.py", "evals/results/stray.py", "evals/cache/skipped.py")           # a script the race does not run, and what a race writes


def quota_at(call):
    return lambda n: llm.QuotaExhausted("the daily quota is used up") if n == call else None


class RealProject(unittest.TestCase):
    """A small project in a temporary folder with a real git repository: the code and the prediction are committed."""

    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.dict(os.environ, GIT_ENV))
        for relative in CODE + NOT_CODE:
            self.write(relative, "VALUE = 1\n")
        self.write(PREDICTION, "The prediction, written before the race.\n")
        self.write("data/corpus/a.md", "One document.\n")
        self.git("init", "-q")
        self.commit("the code and the prediction", everything=True)
        self.enterContext(mock.patch.object(race_team, "BASE_DIR", self.folder))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", os.path.join(self.folder, "evals", "results")))
        self.enterContext(mock.patch.object(race_team.settings, "corpus_dir", os.path.join(self.folder, "data", "corpus")))
        self.enterContext(mock.patch.object(race_team.pipeline, "require_index"))
        self.chunks = self.enterContext(mock.patch("app.rag.store.count_chunks", return_value=434))
        self.racer = Racer()
        self.enterContext(mock.patch.object(race_team.race, "run_one", self.racer))

    def write(self, relative, text):
        path = os.path.join(self.folder, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def git(self, *args):
        return subprocess.run(["git", *IDENTITY, *args], cwd=self.folder, capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, message, everything=False):
        """Commit the changes: what a race wrote under evals/results is left out, as it would be when the author commits code and documents."""
        self.git("add", "-A", *([] if everything else ["--", ".", ":(exclude)evals/results"]))
        self.git("commit", "-q", "-m", message)

    def race(self, *flags, label="t", model=MODEL):
        return captured(race_team.main, ["--label", label, "--only", *TWO, "--repeats", "2", *flags, "--model", model])

    def saved(self, label="t"):
        return runner.load_results("race-" + label)

    def result_file(self, label="t"):
        return runner.results_path("race-" + label)

    def quota_stop(self):
        """A race the quota cut short after three of its eight runs."""
        self.racer.outcome = quota_at(4)
        code, _text = self.race()
        self.assertEqual(code, 1)
        self.racer.outcome, self.racer.calls = None, []

    def untrack_prediction(self):
        self.git("rm", "-q", "--cached", PREDICTION)
        self.git("commit", "-q", "-m", "the prediction is not committed yet")


class ResultFilesAreNotCodeTests(RealProject):
    def test_a_races_own_result_and_cache_files_are_not_uncommitted_code(self):
        self.assertFalse(race_team.code_stamp()["dirty"])
        self.write("evals/results/race-x.json", "{}")
        self.write("evals/cache/answers.json", "{}")
        self.assertFalse(race_team.code_stamp()["dirty"])

    def test_a_change_to_code_still_counts_and_the_stamp_names_the_file(self):
        self.write("app/agent/team.py", "VALUE = 2\n")
        self.write("app/new_tool.py", "VALUE = 1\n")                                              # code nobody has committed yet
        stamp = race_team.code_stamp()
        self.assertTrue(stamp["dirty"])
        self.assertIn("app/agent/team.py", stamp["dirty_paths"])
        self.assertIn("app/new_tool.py", stamp["dirty_paths"])

    def test_a_race_that_stopped_on_the_quota_can_be_resumed_without_committing_its_result_file(self):
        self.quota_stop()
        self.assertTrue(os.path.exists(self.result_file()))
        code, text = self.race("--resume")
        self.assertEqual((code, len(self.racer.calls)), (0, 5), text)

    def test_a_forced_race_and_a_race_under_a_new_label_are_not_refused_because_of_an_earlier_result_file(self):
        self.assertEqual(self.race()[0], 0)
        code, text = self.race(label="u")
        self.assertEqual(code, 0, text)
        code, text = self.race("--force")
        self.assertEqual(code, 0, text)

    def test_uncommitted_code_is_refused_and_the_message_names_the_file(self):
        self.write("app/agent/memory.py", "VALUE = 2\n")
        code, text = self.race()
        self.assertEqual((code, "uncommitted changes" in text, "app/agent/memory.py" in text), (1, True, True))
        self.assertEqual(self.racer.calls, [])


class UnreadableGitTests(RealProject):
    def not_a_repository(self):
        other = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": os.path.dirname(other)}))     # git may not look above it
        self.enterContext(mock.patch.object(race_team, "BASE_DIR", other))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", other))

    def test_the_stamp_of_a_folder_git_cannot_read_is_unknown_never_clean_and_says_why(self):
        self.not_a_repository()
        stamp = race_team.code_stamp()
        self.assertEqual((stamp["git"], stamp["dirty"]), ("unknown", None))
        self.assertIn("not a git repository", stamp["git_problem"])

    def test_a_race_is_refused_when_git_cannot_be_read_and_the_message_says_what_git_said(self):
        self.not_a_repository()
        code, text = self.race()
        self.assertEqual((code, "git could not be read" in text, "not a git repository" in text), (1, True, True))
        self.assertEqual(self.racer.calls, [])

    def test_a_pilot_may_go_on_with_a_warning_when_git_cannot_be_read(self):
        self.not_a_repository()
        code, text = self.race(label="pilot-1")
        self.assertEqual(code, 0, text)
        self.assertIn("WARNING: git could not be read", text)

    def test_a_missing_git_program_is_unreadable_too(self):
        with mock.patch.object(race_team.subprocess, "run", side_effect=FileNotFoundError("no git")):
            stamp = race_team.code_stamp()
        self.assertEqual((stamp["git"], stamp["dirty"]), ("unknown", None))
        self.assertIn("FileNotFoundError", stamp["git_problem"])


class PredictionBeforeTheRaceTests(RealProject):
    def test_a_race_is_refused_while_the_prediction_is_not_committed_and_the_message_names_the_file(self):
        self.untrack_prediction()
        code, text = self.race()
        self.assertEqual((code, PREDICTION in text), (1, True))
        self.assertEqual(self.racer.calls, [])

    def test_a_race_is_refused_while_the_prediction_has_uncommitted_changes(self):
        self.write(PREDICTION, "A different prediction, written after looking.\n")
        code, text = self.race()
        self.assertEqual((code, PREDICTION in text, "uncommitted changes" in text), (1, True, True))

    def test_a_prediction_that_is_staged_but_not_committed_does_not_count(self):
        self.untrack_prediction()
        self.git("add", PREDICTION)
        code, text = self.race()
        self.assertEqual((code, PREDICTION in text), (1, True))

    def test_a_committed_prediction_lets_the_race_run_and_its_git_blob_hash_is_recorded(self):
        code, text = self.race()
        self.assertEqual(code, 0, text)
        self.assertEqual(self.saved()["meta"]["prediction_doc"], self.git("rev-parse", "HEAD:" + PREDICTION))

    def test_a_pilot_does_not_need_the_prediction(self):
        self.untrack_prediction()
        code, text = self.race(label="pilot-1")
        self.assertEqual(code, 0, text)
        self.assertIsNone(self.saved("pilot-1")["meta"]["prediction_doc"])

    def test_a_resume_is_refused_when_the_prediction_was_edited_and_committed_after_the_race_began(self):
        self.quota_stop()
        self.write(PREDICTION, "The prediction, rewritten once some runs were seen.\n")
        self.commit("edit the prediction")
        code, text = self.race("--resume")
        self.assertEqual((code, "prediction_doc" in text), (1, True))
        self.assertEqual(self.racer.calls, [])


class WhatTheStampCoversTests(RealProject):
    def test_every_python_file_under_app_and_evals_and_the_two_race_scripts_is_hashed_and_what_a_race_writes_is_not(self):
        files = race_team.code_files()
        self.assertEqual(sorted(files), sorted(CODE))
        self.assertTrue(all(len(digest) == 12 for digest in files.values()))

    def test_the_tree_fingerprint_moves_with_any_of_those_files_and_not_with_documents(self):
        before = race_team.code_stamp()["tree"]
        self.write("docs/notes.md", "A note.\n")
        self.assertEqual(race_team.code_stamp()["tree"], before)
        self.write("app/agent/memory.py", "VALUE = 2\n")
        self.assertNotEqual(race_team.code_stamp()["tree"], before)

    def test_a_resume_is_refused_after_a_commit_that_changed_a_file_the_old_stamp_did_not_list(self):
        self.quota_stop()
        self.write("app/agent/memory.py", "VALUE = 2\n")                                          # what the model is shown: not one of the seven stamped files
        self.commit("change how old results are shortened")
        code, text = self.race("--resume")
        self.assertEqual((code, "app/agent/memory.py" in text, "new label" in text), (1, True, True))
        self.assertEqual(self.racer.calls, [])

    def test_a_resume_after_a_documents_only_commit_keeps_the_first_stamp_and_records_the_second_in_a_history(self):
        first = self.git("rev-parse", "--short", "HEAD")
        self.quota_stop()
        self.write("docs/notes.md", "A note.\n")
        self.commit("a note")
        second = self.git("rev-parse", "--short", "HEAD")
        code, text = self.race("--resume")
        self.assertEqual(code, 0, text)
        meta = self.saved()["meta"]
        self.assertEqual(meta["code"]["git"], first)                                              # the commit the race began on is not overwritten
        self.assertEqual([entry["code"]["git"] for entry in meta["code_history"]], [second])
        self.assertTrue(meta["code_history"][0]["at"])

    def test_a_resume_with_nothing_left_to_run_does_not_rewrite_the_saved_race(self):
        self.assertEqual(self.race()[0], 0)
        self.write("docs/notes.md", "A note.\n")
        self.commit("a note")
        before = open(self.result_file(), "rb").read()
        self.racer.calls = []
        code, text = self.race("--resume")
        self.assertEqual((code, self.racer.calls), (0, []))
        self.assertIn("Nothing to resume", text)
        self.assertEqual(open(self.result_file(), "rb").read(), before)

    def test_the_saved_stamp_and_the_per_file_hashes_name_the_code_the_race_ran(self):
        self.assertEqual(self.race()[0], 0)
        meta = self.saved()["meta"]
        self.assertEqual(sorted(meta["code_files"]), sorted(CODE))
        self.assertEqual(meta["code"]["tree"], race_team.code_stamp()["tree"])
        self.assertEqual(meta["code_history"], [])


class SettingsAreFrozenTests(RealProject):
    CHANGES = {"llm_max_retries": 0, "llm_timeout_seconds": 5.0, "dense_search": "ann", "hybrid_candidates": 3, "rrf_k": 5, "bm25_k1": 3.0,
               "bm25_b": 0.5, "embed_provider": "a-different-provider"}

    def test_the_settings_that_change_what_a_run_does_are_recorded_with_the_index_size(self):
        self.assertEqual(self.race()[0], 0)
        recorded = self.saved()["meta"]["settings"]
        self.assertEqual(sorted(recorded), sorted([*self.CHANGES, "chunk_count"]))
        self.assertEqual(recorded["chunk_count"], 434)
        self.assertEqual(recorded["rrf_k"], race_team.settings.rrf_k)

    def test_a_resume_is_refused_when_any_one_of_them_changed_between_the_sessions(self):
        self.quota_stop()
        for name, value in self.CHANGES.items():
            with self.subTest(setting=name), mock.patch.object(race_team.settings, name, value):
                code, text = self.race("--resume")
                self.assertEqual((code, f"setting {name}" in text), (1, True))
        with self.subTest(setting="chunk_count"):
            self.chunks.return_value = 435                                                        # the index was rebuilt with another corpus
            code, text = self.race("--resume")
            self.assertEqual((code, "setting chunk_count" in text), (1, True))
        self.assertEqual(self.racer.calls, [])

    def test_a_saved_race_that_has_no_settings_recorded_can_still_be_resumed(self):
        self.quota_stop()
        saved = self.saved()
        for key in ("settings", "code_files", "prediction_doc", "code_history"):                  # a file saved before these were recorded
            saved["meta"].pop(key, None)
        runner.save_results(saved, self.result_file())
        code, text = self.race("--resume")
        self.assertEqual(code, 0, text)


if __name__ == "__main__":
    unittest.main()
