"""Week 10: scripts/race_team.py keeps what a race saved: --force never destroys a saved race, a resume picks the right file (no model calls)."""
import glob
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import _testkit
from app import llm
from evals import runner
from test_race_team import BLOB, CLEAN, MODEL, TWO, Racer, captured, setUpModule      # noqa: F401  (setUpModule keeps the real index closed)

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import race_team           # noqa: E402


class FakeClock(datetime):
    """race_team's clock: every reading is `step` later than the one before, so two races never share a start time."""
    now_value, step = datetime(2026, 10, 12, 9, 0, 0), timedelta(minutes=1)

    @classmethod
    def now(cls, tz=None):
        FakeClock.now_value += FakeClock.step
        return FakeClock.now_value


def quota_at(call):
    return lambda n: llm.QuotaExhausted("the daily quota is used up") if n == call else None


class SavedRaceCase(unittest.TestCase):
    """main() with a fake racer and a stamp that is always clean, writing into a temporary results folder."""

    def setUp(self):
        FakeClock.now_value, FakeClock.step = datetime(2026, 10, 12, 9, 0, 0), timedelta(minutes=1)
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.folder))
        self.enterContext(mock.patch.object(race_team, "BASE_DIR", self.folder))
        self.enterContext(mock.patch.object(race_team, "datetime", FakeClock))
        self.stamp = dict(CLEAN)
        self.enterContext(mock.patch.object(race_team, "code_stamp", side_effect=lambda *args: dict(self.stamp)))
        self.enterContext(mock.patch.object(race_team, "prediction_doc_state", return_value=(BLOB, None)))
        self.enterContext(mock.patch.object(race_team.pipeline, "require_index"))
        self.racer = Racer()
        self.enterContext(mock.patch.object(race_team.race, "run_one", self.racer))

    def race(self, *flags, label="t", model=MODEL):
        argv = ["--label", label, "--only", *TWO, "--repeats", "2", *flags]
        return captured(race_team.main, argv + (["--model", model] if model else []))

    def saved(self, label="t"):
        return runner.load_results("race-" + label)

    def files(self, pattern):
        return sorted(glob.glob(os.path.join(self.folder, pattern)))

    def partial_race(self):
        """A race the quota cut short after three of its eight runs."""
        self.racer.outcome = quota_at(4)
        self.race()
        self.racer.outcome, self.racer.calls = None, []


class ForceKeepsEvidenceTests(SavedRaceCase):
    def test_force_over_a_partial_race_with_the_quota_still_out_keeps_the_partial_runs_aside(self):
        self.partial_race()
        self.racer.outcome = quota_at(1)
        code, text = self.race("--force")
        self.assertEqual(code, 1)
        aside = self.files("race-t.replaced-*.json")
        self.assertEqual(len(aside), 1)
        kept = runner.load_results(aside[0])
        self.assertEqual((len(kept["runs"]), kept["meta"]["complete"]), (3, False))
        self.assertIn(os.path.basename(aside[0]), text)                                           # it says where the old race went
        self.assertEqual(len(self.saved()["runs"]), 0)                                            # the forced race is the one at the label now

    def test_force_over_a_partial_race_that_then_runs_keeps_the_old_runs_aside_and_saves_the_new_race(self):
        self.partial_race()
        self.racer.outcome = lambda n: {"answer": "second race"}
        code, _text = self.race("--force")
        self.assertEqual(code, 0)
        self.assertEqual({run["answer"] for run in self.saved()["runs"]}, {"second race"})
        kept = runner.load_results(self.files("race-t.replaced-*.json")[0])
        self.assertEqual((len(kept["runs"]), {run["answer"] for run in kept["runs"]}), (3, {"an answer"}))

    def test_force_over_a_complete_race_leaves_it_in_place_while_the_new_one_is_cut_short_and_moves_it_aside_once_it_is_replaced(self):
        self.race()                                                                               # a complete race of eight runs
        self.racer.outcome = lambda n: llm.QuotaExhausted("used up") if n == 12 else {"answer": "second race"}
        self.race("--force")                                                                      # cut short after three runs
        self.assertEqual(self.files("race-t.replaced-*.json"), [])                                # nothing moved: the complete race is still the saved one
        self.assertEqual({run["answer"] for run in self.saved()["runs"]}, {"an answer"})
        self.racer.outcome = lambda n: {"answer": "third race"}
        code, _text = self.race("--force")
        self.assertEqual(code, 0)
        self.assertEqual({run["answer"] for run in self.saved()["runs"]}, {"third race"})
        complete = [runner.load_results(path) for path in self.files("race-t.replaced-*.json")]
        self.assertEqual([(len(old["runs"]), old["meta"]["complete"], {run["answer"] for run in old["runs"]}) for old in complete],
                         [(8, True, {"an answer"})])
        progress = [runner.load_results(path) for path in self.files("race-t.incomplete.replaced-*.json")]
        self.assertEqual([{run["answer"] for run in old["runs"]} for old in progress], [{"second race"}])   # the cut-short forced race is kept too

    def test_force_keeps_the_leftover_of_an_earlier_cut_short_resume_aside_instead_of_overwriting_it(self):
        self.race()
        self.racer.outcome, self.racer.calls = quota_at(3), []
        self.race("--resume", "--noise")                                                          # two noise runs saved beside the complete race
        self.assertEqual(len(runner.load_results(os.path.join(self.folder, "race-t.incomplete.json"))["runs"]), 10)
        self.racer.outcome, self.racer.calls = quota_at(2), []
        self.race("--force")
        kept = runner.load_results(self.files("race-t.incomplete.replaced-*.json")[0])
        self.assertEqual(len(kept["runs"]), 10)

    def test_two_forced_races_in_the_same_second_never_overwrite_each_others_kept_file(self):
        FakeClock.step = timedelta(0)                                                             # the clock stands still: the names would collide
        self.partial_race()
        self.racer.outcome = lambda n: llm.QuotaExhausted("used up")
        self.race("--force")
        self.race("--force")
        aside = self.files("race-t.replaced-*.json")
        self.assertEqual(sorted(len(runner.load_results(path)["runs"]) for path in aside), [0, 3])

    def test_a_saved_race_that_cannot_be_moved_aside_stops_the_forced_race_before_it_starts(self):
        self.partial_race()
        with mock.patch("os.replace", side_effect=PermissionError("locked")), mock.patch.object(runner.time, "sleep"):
            code, text = self.race("--force")
        self.assertEqual((code, "could not move" in text), (1, True))
        self.assertEqual(self.racer.calls, [])                                                    # nothing ran, so nothing was overwritten
        self.assertEqual(len(self.saved()["runs"]), 3)


class WhichFileToResumeTests(SavedRaceCase):
    def test_a_leftover_beside_a_race_that_was_deleted_by_hand_is_not_taken_for_newer_progress(self):
        self.race()                                                                               # race A: complete
        self.racer.outcome, self.racer.calls = quota_at(3), []
        self.race("--resume", "--noise")                                                          # cut short: A plus two noise runs, in the leftover
        leftover = os.path.join(self.folder, "race-t.incomplete.json")
        self.assertTrue(os.path.exists(leftover))
        os.remove(os.path.join(self.folder, "race-t.json"))                                       # deleted by hand to start fresh
        self.racer.outcome, self.racer.calls = quota_at(4), []
        self.race()                                                                               # race B: three runs, then the quota
        self.racer.outcome, self.racer.calls = None, []
        code, _text = self.race("--resume")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.racer.calls), 5)                                                # B had three of its eight runs, not the leftover's ten of twelve
        self.assertEqual(self.saved()["meta"]["arms"], ["agent", "team"])
        self.assertTrue(os.path.exists(leftover))                                                 # another race's progress is not deleted by B finishing

    def test_a_resume_after_a_forced_race_was_cut_short_carries_on_the_forced_race_and_keeps_the_old_complete_one_aside(self):
        self.race()                                                                               # A: complete, answers "an answer"
        self.racer.outcome, self.racer.calls = (lambda n: llm.QuotaExhausted("used up") if n == 4 else {"answer": "forced"}), []
        self.race("--force")                                                                      # B cut short: its progress is in the leftover
        self.racer.outcome, self.racer.calls = (lambda n: {"answer": "forced"}), []
        code, _text = self.race("--resume")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.racer.calls), 5)                                                # B's eight runs, three done
        self.assertEqual({run["answer"] for run in self.saved()["runs"]}, {"forced"})
        old = runner.load_results(self.files("race-t.replaced-*.json")[0])
        self.assertEqual((len(old["runs"]), {run["answer"] for run in old["runs"]}), (8, {"an answer"}))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "race-t.incomplete.json")))     # B's leftover was its own progress: finished, so removed



class ResumeRecordTests(SavedRaceCase):
    def test_every_resume_is_recorded_with_its_time_rate_limit_model_code_and_the_arms_it_added(self):
        with mock.patch.object(race_team.settings, "llm_rpm", 12):
            self.partial_race()
        with mock.patch.object(race_team.settings, "llm_rpm", 30):                              # another session, another rate limit: not a reason to refuse
            code, text = self.race("--resume")
        self.assertEqual(code, 0, text)
        meta = self.saved()["meta"]
        self.assertEqual(meta["llm_rpm"], 12)                                                     # what the race began with
        self.assertEqual(len(meta["resumed"]), 1)
        entry = meta["resumed"][0]
        self.assertEqual(set(entry), {"at", "arms_added", "rpm", "model", "code"})
        self.assertEqual((entry["arms_added"], entry["rpm"], entry["model"], entry["code"]), ([], 30, MODEL, self.stamp))
        self.assertTrue(entry["at"])
        self.assertEqual(meta["not_interleaved_arms"], [])

    def test_an_arm_added_by_a_resume_is_named_because_it_ran_after_the_others(self):
        self.assertEqual(self.race()[0], 0)
        self.assertEqual(self.race("--resume", "--noise")[0], 0)
        self.assertEqual(self.race("--resume", "--workflow")[0], 0)
        meta = self.saved()["meta"]
        self.assertEqual([entry["arms_added"] for entry in meta["resumed"]], [["agent-2"], ["workflow"]])
        self.assertEqual(meta["not_interleaved_arms"], ["agent-2", "workflow"])

    def test_a_fresh_race_lists_no_resume_and_no_arm_that_ran_apart(self):
        self.assertEqual(self.race("--noise")[0], 0)
        meta = self.saved()["meta"]
        self.assertEqual((meta["resumed"], meta["not_interleaved_arms"]), ([], []))

    def test_a_resume_that_has_nothing_to_run_adds_no_entry(self):
        self.assertEqual(self.race()[0], 0)
        self.assertEqual(self.race("--resume")[0], 0)
        self.assertEqual(self.saved()["meta"]["resumed"], [])

    def test_a_resume_of_a_file_saved_with_plain_time_stamps_keeps_them_and_adds_the_new_kind(self):
        self.partial_race()
        saved = self.saved()
        saved["meta"]["resumed"] = ["2026-10-12T08:00:00+00:00"]                                  # how the first version of this script recorded a resume
        runner.save_results(saved, os.path.join(self.folder, "race-t.json"))
        self.assertEqual(self.race("--resume")[0], 0)
        resumed = self.saved()["meta"]["resumed"]
        self.assertEqual(resumed[0], {"at": "2026-10-12T08:00:00+00:00"})
        self.assertEqual(set(resumed[1]), {"at", "arms_added", "rpm", "model", "code"})


class ProviderTroubleIsRunAgainTests(SavedRaceCase):
    def outage(self):
        """The provider fails the first three requests, so the race stops as an outage with three error runs saved."""
        self.racer.outcome = lambda n: {"success": False, "stop": "error", "calls": 0} if n <= 3 else None
        code, text = self.race()
        self.assertEqual(code, 1)
        self.assertIn("runs in a row ended on a provider error", text)
        self.racer.outcome, self.racer.calls = None, []

    def test_the_runs_that_caused_an_outage_stop_are_set_aside_on_resume_and_run_again(self):
        self.outage()
        before = self.saved()["runs"]
        code, text = self.race("--resume")
        self.assertEqual(code, 0, text)
        done = self.saved()
        self.assertEqual(len(self.racer.calls), 8)                                                # all eight runs: the three error runs are not counted as done
        self.assertEqual([run["stop_reason"] for run in done["runs"]], ["final"] * 8)
        self.assertIn("Set aside 3 run(s)", text)
        aside = done["meta"]["set_aside_runs"]
        self.assertEqual(len(aside), 3)
        self.assertEqual([{key: value for key, value in run.items() if key != "set_aside_because"} for run in aside], before)     # kept as they were
        self.assertTrue(all("error" in run["set_aside_because"] for run in aside))

    def test_a_run_that_only_failed_its_checks_is_a_result_and_stays(self):
        self.racer.outcome = lambda n: {"success": False} if n == 2 else None
        self.assertEqual(self.race()[0], 0)
        self.racer.outcome, self.racer.calls = None, []
        self.assertEqual(self.race("--resume", "--noise")[0], 0)
        done = self.saved()
        self.assertEqual(len(self.racer.calls), 4)                                                # only the new arm's runs
        self.assertNotIn("set_aside_runs", done["meta"])
        self.assertEqual(sum(not run["success"] for run in done["runs"]), 1)

    def test_a_specialist_that_hit_a_provider_error_makes_the_run_trouble_too(self):
        crew = {"per_agent": {}, "handoffs": [{"agent": "researcher", "state": "not_finished", "stop_reason": "error"}], "warnings": [], "errors": []}
        self.racer.outcome = lambda n: {"team": crew} if n == 2 else None
        self.assertEqual(self.race()[0], 0)
        self.racer.outcome, self.racer.calls = None, []
        self.assertEqual(self.race("--resume")[0], 0)
        self.assertEqual(len(self.racer.calls), 1)                                                # the one run with a failed hand-off, run again
        self.assertEqual(len(self.saved()["meta"]["set_aside_runs"]), 1)

    def test_a_second_resume_adds_to_the_runs_already_set_aside(self):
        self.outage()
        self.racer.outcome, self.racer.calls = lambda n: {"success": False, "stop": "error", "calls": 0} if n == 1 else None, []
        self.race("--resume")                                                                     # one more error run, then fine
        self.racer.outcome, self.racer.calls = None, []
        self.assertEqual(self.race("--resume")[0], 0)
        self.assertEqual(len(self.saved()["meta"]["set_aside_runs"]), 4)


class NotAWeek10RaceTests(SavedRaceCase):
    def test_a_saved_file_that_is_not_a_week_10_race_is_explained_and_not_a_traceback(self):
        week_7 = {"meta": {"label": "w7", "complete": False, "approaches": ["agent", "workflow"]}, "runs": [{"approach": "agent", "task_id": "x", "repeat": 1}]}
        runner.save_results(week_7, runner.results_path("race-w7"))
        code, text = self.race("--resume", label="w7")
        self.assertEqual((code, "not a Week 10 race" in text), (1, True))

    def test_the_label_race_is_reserved_for_the_week_7_anchor_that_the_plan_reads(self):
        code, text = self.race(label="race")
        self.assertEqual((code, "reserved" in text, self.racer.calls), (1, True, []))


if __name__ == "__main__":
    unittest.main()
