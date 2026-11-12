"""Week 10: smaller guards of scripts/race_team.py and scripts/check_team_prediction.py found in review (no model calls)."""
import argparse
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from evals import runner, team_prediction
from evals.agent_tasks import get_tasks
from test_race_team import TWO, Racer, captured, setUpModule                          # noqa: F401  (setUpModule keeps the real index closed)
import test_race_team_freeze as real
import test_race_team_resume as saved_races
from test_team_prediction import race as prediction_race

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import check_team_prediction           # noqa: E402
import race_team                       # noqa: E402

EN_DASH = chr(0x2013)                                                               # written by code so that no typographic character sits in this file


class PriceSourceTests(unittest.TestCase):
    def args(self, source):
        return argparse.Namespace(price_in=1.0, price_out=2.0, price_source=source)

    def test_a_double_quote_in_the_source_is_refused_because_it_would_break_the_command_that_save_writes(self):
        with self.assertRaises(ValueError) as caught:
            race_team.prices_from(self.args('the "list" price'))
        self.assertIn("double quote", str(caught.exception))
        self.assertEqual(race_team.prices_from(self.args("the list price on 12 October")), (1.0, 2.0, "the list price on 12 October"))


class ShowSaveTests(saved_races.SavedRaceCase):
    def test_a_typographic_dash_in_the_price_source_never_reaches_the_generated_document(self):
        self.assertEqual(self.race()[0], 0)
        code, _text = captured(race_team.main, ["--show", "t", "--price-in", "1", "--price-out", "2", "--price-source", f"list price {EN_DASH} 12 October", "--save"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.folder, "docs", "week10", "race-results.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("list price - 12 October", text)
        self.assertNotIn(EN_DASH, text)


class OutageMessageTests(unittest.TestCase):
    def results(self):
        return {"meta": race_team.make_meta("t", get_tasks(TWO), 2, ["agent", "team"], "m", "now"), "runs": []}

    def go(self, results, racer):
        plan = race_team.build_plan(get_tasks(TWO), 2, ["agent", "team"])
        return race_team.run_plan(plan, results, [], {}, lambda r: None, say=lambda *_: None, run_one=racer), None

    def test_the_last_error_named_in_an_outage_is_the_last_error_step_not_an_answer_the_manager_gave_after_it(self):
        steps = [{"kind": "error", "content": "RuntimeError: provider down"}, {"kind": "final", "content": "I could not find it"}]
        stopped, _saved = self.go(self.results(), Racer(lambda n: {"success": False, "stop": "error", "steps": steps}))
        self.assertIn("provider down", stopped)
        self.assertNotIn("I could not find it", stopped)

    def test_a_run_with_no_error_step_says_its_stop_reason_instead(self):
        stopped, _saved = self.go(self.results(), Racer(lambda n: {"success": False, "stop": "error", "steps": []}))
        self.assertIn("stop reason error, no detail recorded", stopped)


class FirstSessionWithNoUsableRunTests(saved_races.SavedRaceCase):
    def test_a_race_that_saved_no_usable_run_says_what_to_do_since_a_resume_refuses_a_changed_model(self):
        self.racer.outcome = lambda n: {"success": False, "stop": "error", "calls": 0}
        code, text = self.race()
        self.assertEqual(code, 1)
        self.assertIn("No usable run was saved", text)
        self.assertIn("--force", text)

    def test_a_race_that_saved_a_usable_run_just_says_to_resume(self):
        self.racer.outcome = lambda n: {"success": False, "stop": "error", "calls": 0} if n > 1 else None
        _code, text = self.race()
        self.assertIn("Carry on with --resume once the cause is gone.", text)
        self.assertNotIn("No usable run", text)


class StaleIndexTests(saved_races.SavedRaceCase):
    def test_an_index_that_does_not_hold_the_chunks_the_corpus_gives_is_warned_about_before_the_race(self):
        with mock.patch.object(race_team.runner, "expected_chunk_count", return_value=500), mock.patch.object(race_team.store, "count_chunks", return_value=434):
            code, text = self.race()
        self.assertEqual(code, 0)
        self.assertIn("WARNING: the index holds 434 chunks but the corpus gives 500", text)
        self.assertIn("scripts/ingest.py", text)

    def test_an_index_that_matches_gets_no_warning(self):
        with mock.patch.object(race_team.runner, "expected_chunk_count", return_value=434), mock.patch.object(race_team.store, "count_chunks", return_value=434):
            self.assertNotIn("index holds", self.race()[1])

    def test_a_corpus_that_cannot_be_read_is_not_a_crash(self):
        with mock.patch.object(race_team.loader, "load_documents", side_effect=OSError("locked")):
            self.assertIsNone(race_team.index_problem())


class RefusalTextTests(real.RealProject):
    def test_the_dirty_refusal_names_the_line_ending_case_and_the_scripts_folder(self):
        self.write("app/agent/memory.py", "VALUE = 2\n")
        code, text = self.race()
        self.assertEqual(code, 1)
        self.assertIn("git add", text)
        self.assertIn("scripts/", text)


class NeverAcceptedTests(real.RealProject):
    def test_the_thresholds_what_counts_as_a_pass_and_what_is_asked_cannot_be_accepted_after_the_race_began(self):
        for path in race_team.NEVER_ACCEPTED:
            with self.subTest(path=path):
                self.quota_stop()
                self.write(path, "VALUE = 2  # edited after the race began\n")
                self.commit("edit " + path)
                code, text = self.race("--resume", "--accept-changed", path)
                self.assertEqual((code, self.racer.calls), (1, []))
                self.assertIn("cannot name " + path, text)
                self.assertIn("pre-registered", text)
                self.git("reset", "-q", "--hard", "HEAD~1")                                  # back to the code the next case starts from
                os.remove(self.result_file())

    def test_the_three_files_are_exactly_the_ones_that_decide_the_numbers_not_the_ones_that_only_print_them(self):
        self.assertEqual(set(race_team.NEVER_ACCEPTED), {"evals/team_prediction.py", "evals/checks.py", "evals/agent_tasks.py"})
        self.assertTrue(set(race_team.NEVER_ACCEPTED) <= set(race_team.STAMPED_FILES))


class PredictionDriftTests(unittest.TestCase):
    META = {"prediction_doc": "aaa111", "code": {"team_prediction.py": "hash1"}}

    def test_a_prediction_that_is_what_the_race_recorded_has_nothing_to_say(self):
        self.assertEqual(team_prediction.drift_notes(self.META, "aaa111", "hash1"), ([], []))

    def test_an_edited_document_or_edited_thresholds_are_named_with_both_hashes(self):
        changed, unverified = team_prediction.drift_notes(self.META, "bbb222", "hash2")
        self.assertEqual(unverified, [])
        self.assertEqual(len(changed), 2)
        self.assertIn("aaa111 then, bbb222 now", changed[0])
        self.assertIn("hash1 then, hash2 now", changed[1])

    def test_a_value_that_cannot_be_read_is_unverified_and_not_called_changed(self):
        changed, unverified = team_prediction.drift_notes(self.META, None, None)
        self.assertEqual(changed, [])
        self.assertEqual(len(unverified), 2)

    def test_a_race_that_recorded_nothing_is_not_compared(self):
        self.assertEqual(team_prediction.drift_notes({}, "x", "y"), ([], []))
        self.assertEqual(team_prediction.drift_notes(None, "x", "y"), ([], []))


class CheckerScriptDriftTests(unittest.TestCase):
    def run_check(self, meta, now):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", folder))
        saved = prediction_race()
        saved["meta"].update(meta)
        runner.save_results(saved, runner.results_path("race-p"))
        out = io.StringIO()
        with mock.patch.object(check_team_prediction, "current_prediction_state", return_value=now), contextlib.redirect_stdout(out):
            code = check_team_prediction.main(["p"])
        return code, out.getvalue()

    def test_a_prediction_edited_after_the_race_gives_a_warning_and_no_clean_verdict(self):
        code, text = self.run_check({"prediction_doc": "aaa111", "code": {"team_prediction.py": "hash1"}}, ("bbb222", "hash1"))
        self.assertEqual(code, 1)
        self.assertIn("WARNING: docs/week10/prediction.md is not the document recorded", text)
        self.assertIn("No clean verdict", text)

    def test_an_unchanged_prediction_keeps_its_clean_verdict(self):
        code, text = self.run_check({"prediction_doc": "aaa111", "code": {"team_prediction.py": "hash1"}}, ("aaa111", "hash1"))
        self.assertEqual(code, 0)
        self.assertNotIn("WARNING", text)

    def test_a_prediction_that_could_not_be_compared_says_so_and_keeps_the_verdict(self):
        code, text = self.run_check({"prediction_doc": "aaa111"}, (None, None))
        self.assertEqual(code, 0)
        self.assertIn("NOTE: the committed prediction document could not be read", text)

    def test_a_corrupt_race_file_is_an_error_line_and_not_a_traceback(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", folder))
        with open(runner.results_path("race-bad"), "w", encoding="utf-8") as handle:
            handle.write('{"meta": {"label": ')                                               # cut off by a crash
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_team_prediction.main(["bad"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
