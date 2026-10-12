"""Week 10: scripts/race_team.py in the places a long live race goes wrong: two races at once, Ctrl-C, an empty reply that repeats, a hint
for runs that hit provider trouble, and a resume after a harmless edit (no model calls)."""
import os
import sys
import time
import unittest
from unittest import mock

import _testkit
from evals import team_report
from test_race_team import MODEL, TWO, Racer, captured, setUpModule                  # noqa: F401  (setUpModule keeps the real index closed)
import test_race_team_freeze as real
import test_race_team_resume as saved_races

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import race_team           # noqa: E402


class GitProblemTextTests(unittest.TestCase):
    def test_the_reason_git_could_not_be_read_never_carries_the_project_path_into_the_stamp(self):
        where = str(race_team.BASE_DIR).replace("\\", "/")                      # git prints forward slashes
        with mock.patch.dict(race_team.GIT_PROBLEM, {"text": f"fatal: detected dubious ownership in repository at '{where}'"}), \
                mock.patch.object(race_team, "uncommitted_code", return_value=None), mock.patch.object(race_team, "git", return_value=None):
            stamp = race_team.code_stamp({})
        self.assertIn("dubious ownership", stamp["git_problem"])
        self.assertNotIn(where, stamp["git_problem"])
        self.assertIn("<project>", stamp["git_problem"])


class CtrlC(Racer):
    """Stands in for race.run_one and raises KeyboardInterrupt on its n-th call, as Ctrl-C does in the middle of a run."""

    def __init__(self, at):
        super().__init__()
        self.at = at

    def __call__(self, task, approach, repeat, tools, **options):
        if len(self.calls) + 1 == self.at:
            self.calls.append((task["id"], approach, repeat, options))
            raise KeyboardInterrupt
        return super().__call__(task, approach, repeat, tools, **options)


class EmptyReplyOutageTests(saved_races.SavedRaceCase):
    def test_an_empty_reply_that_repeats_is_an_outage_like_an_error(self):
        self.racer.outcome = lambda n: {"success": False, "stop": "empty_reply", "calls": 0}
        code, text = self.race()
        self.assertEqual(code, 1)
        self.assertIn(f"{race_team.race.MAX_ERRORS_IN_A_ROW} runs in a row ended on a provider error", text)
        self.assertEqual(len(self.saved()["runs"]), race_team.race.MAX_ERRORS_IN_A_ROW)

    def test_a_specialist_that_keeps_returning_an_empty_reply_stops_the_team_arm_alone(self):
        crew = {"per_agent": {}, "handoffs": [{"agent": "researcher", "state": "not_finished", "stop_reason": "empty_reply"}], "warnings": [], "errors": []}
        self.racer.outcome = lambda n: {"team": crew} if self.racer.calls[-1][1] == "team" else None
        code, text = self.race()
        self.assertEqual(code, 1)
        self.assertIn(f"{race_team.race.MAX_ERRORS_IN_A_ROW} runs in a row ended on a provider error in the team arm", text)

    def test_the_runner_and_the_report_agree_on_what_provider_trouble_is(self):
        for stop in ("error", "quota_exhausted", "empty_reply", "final", "max_steps"):
            record = {"stop_reason": stop, "team": {"handoffs": []}}
            self.assertEqual(race_team.provider_trouble(record), team_report.provider_trouble(record), stop)
        record = {"stop_reason": "final", "team": {"handoffs": [{"stop_reason": "empty_reply"}]}}
        self.assertTrue(race_team.provider_trouble(record))


class LockTests(saved_races.SavedRaceCase):
    def lock(self, label="t"):
        return os.path.join(self.folder, f"race-{label}.lock")

    def hold(self, age=0, label="t"):
        """A lock file as another race leaves it, last touched `age` seconds ago."""
        with open(self.lock(label), "w", encoding="utf-8") as handle:
            handle.write("pid 1\n")
        stamp = time.time() - age
        os.utime(self.lock(label), (stamp, stamp))

    def test_a_race_that_is_running_blocks_a_second_one_under_the_same_label(self):
        self.hold(age=5)
        code, text = self.race()
        self.assertEqual(code, 1)
        self.assertIn("already be running", text)
        self.assertIn("--break-lock", text)
        self.assertEqual(self.racer.calls, [])
        self.assertTrue(os.path.exists(self.lock()))                                              # it was not ours to remove
        self.assertEqual(self.files("race-t*.json"), [])

    def test_a_lock_nobody_has_touched_for_ten_minutes_is_taken_over_and_removed_after_the_race(self):
        self.hold(age=3600)
        code, text = self.race()
        self.assertEqual(code, 0, text)
        self.assertIn("stale", text)
        self.assertFalse(os.path.exists(self.lock()))

    def test_a_stale_lock_beside_a_result_written_a_moment_ago_is_still_busy(self):
        self.partial_race()
        self.hold(age=3600)
        code, text = self.race("--resume")
        self.assertEqual((code, "already be running" in text, self.racer.calls), (1, True, []))
        stamp = time.time() - 3600
        os.utime(os.path.join(self.folder, "race-t.json"), (stamp, stamp))                        # now the whole label has been quiet
        self.assertEqual(self.race("--resume")[0], 0)

    def test_break_lock_takes_a_fresh_lock_when_the_person_says_the_other_race_is_gone(self):
        self.hold(age=5)
        code, text = self.race("--break-lock")
        self.assertEqual(code, 0, text)
        self.assertFalse(os.path.exists(self.lock()))

    def test_the_lock_goes_when_a_race_is_cut_short_and_when_it_is_resumed(self):
        self.partial_race()
        self.assertFalse(os.path.exists(self.lock()))
        self.assertEqual(self.race("--resume")[0], 0)
        self.assertFalse(os.path.exists(self.lock()))

    def test_a_race_that_crashes_before_it_finishes_still_removes_its_lock(self):
        with mock.patch.object(race_team, "run_plan", side_effect=ValueError("broken")):
            with self.assertRaises(ValueError):
                self.race()
        self.assertFalse(os.path.exists(self.lock()))

    def test_another_label_has_its_own_lock_and_a_saved_race_can_be_shown_while_one_runs(self):
        self.assertEqual(self.race()[0], 0)
        self.hold(age=5)
        self.assertEqual(self.race(label="u")[0], 0)
        code, text = captured(race_team.main, ["--show", "t"])
        self.assertEqual(code, 0, text)
        self.assertTrue(os.path.exists(self.lock()))


class CtrlCTests(saved_races.SavedRaceCase):
    def test_ctrl_c_saves_the_runs_that_finished_names_the_cause_and_leaves_a_race_that_resumes(self):
        with mock.patch.object(race_team.race, "run_one", CtrlC(3)):
            code, text = self.race()
        self.assertEqual(code, 1)
        saved = self.saved()
        self.assertEqual((len(saved["runs"]), saved["meta"]["complete"]), (2, False))
        self.assertIn("Ctrl-C", saved["meta"]["stopped_because"])
        self.assertIn("STOPPED: interrupted", text)
        self.assertIn("--resume", text)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "race-t.lock")))
        self.assertEqual(self.race("--resume")[0], 0)
        self.assertEqual(len(self.saved()["runs"]), 8)


class ResumeHintTests(saved_races.SavedRaceCase):
    def test_a_finished_race_with_a_run_that_hit_provider_trouble_says_how_to_run_it_again(self):
        self.racer.outcome = lambda n: {"success": False, "stop": "error", "calls": 0} if n == 2 else None
        code, text = self.race()
        self.assertEqual(code, 0)
        self.assertIn("1 run ended on provider trouble", text)
        self.assertIn("python scripts/race_team.py --label t --model model-x --only t7-single-lookup t7-conflict --repeats 2 --resume", text)
        self.assertIn("about 2 requests", text)                                                   # a clean fake run is two requests

    def test_the_hint_runs_the_command_it_prints(self):
        self.racer.outcome = lambda n: {"success": False, "stop": "error", "calls": 0} if n == 2 else None
        self.race()
        self.racer.outcome, self.racer.calls = None, []
        code, _text = self.race("--resume")
        self.assertEqual((code, len(self.racer.calls)), (0, 1))
        self.assertEqual(len(self.saved()["meta"]["set_aside_runs"]), 1)

    def test_a_clean_race_prints_no_hint(self):
        code, text = self.race()
        self.assertEqual(code, 0)
        self.assertNotIn("once the provider is working", text)


class AcceptChangedTests(real.RealProject):
    def edit_and_commit(self, relative="app/rag/retriever.py"):
        self.write(relative, "VALUE = 1  # a comment, which cannot change what a run does\n")
        self.commit("a comment")

    def test_a_resume_after_a_code_change_is_refused_and_says_how_to_accept_a_harmless_one(self):
        self.quota_stop()
        self.edit_and_commit()
        code, text = self.race("--resume")
        self.assertEqual(code, 1)
        for phrase in ("app/rag/retriever.py", "--accept-changed", "new label"):
            self.assertIn(phrase, text)
        self.assertEqual(self.racer.calls, [])

    def test_naming_the_changed_file_lets_the_resume_go_on_and_records_what_was_accepted(self):
        self.quota_stop()
        before = self.saved()["meta"]["code_files"]["app/rag/retriever.py"]
        self.edit_and_commit()
        code, text = self.race("--resume", "--accept-changed", "app/rag/retriever.py")
        self.assertEqual(code, 0, text)
        saved = self.saved()
        accepted = saved["meta"]["resumed"][-1]["accepted_changes"]
        self.assertEqual(list(accepted), ["app/rag/retriever.py"])
        self.assertEqual(accepted["app/rag/retriever.py"]["was"], before)
        self.assertNotEqual(accepted["app/rag/retriever.py"]["now"], before)
        self.assertIn("accepted", "\n".join(team_report.format_report(saved)))                  # the report shows it

    def test_a_stamped_file_can_be_accepted_by_its_path_and_a_windows_path_is_read_too(self):
        self.quota_stop()
        self.edit_and_commit("app/agent/team.py")
        self.assertEqual(self.race("--resume", "--accept-changed", "app\\agent\\team.py")[0], 0)

    def test_a_path_that_did_not_change_is_refused_and_nothing_runs(self):
        self.quota_stop()
        self.edit_and_commit()
        code, text = self.race("--resume", "--accept-changed", "app/llm.py")
        self.assertEqual((code, "app/llm.py" in text, "not among" in text, self.racer.calls), (1, True, True, []))

    def test_only_code_can_be_accepted_not_a_setting_or_the_tasks(self):
        self.quota_stop()
        self.edit_and_commit()
        code, text = self.race("--resume", "--accept-changed", "app/rag/retriever.py", "--timeout", "100")
        self.assertEqual((code, "cannot be resumed" in text, self.racer.calls), (1, True, []))

    def test_accept_changed_without_resume_is_an_error(self):
        code, text = self.race("--accept-changed", "app/rag/retriever.py")
        self.assertEqual((code, "--resume" in text, self.racer.calls), (1, True, []))


if __name__ == "__main__":
    unittest.main()
