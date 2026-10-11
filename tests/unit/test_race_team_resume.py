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
from test_race_team import CLEAN, MODEL, TWO, Racer, captured

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


if __name__ == "__main__":
    unittest.main()
