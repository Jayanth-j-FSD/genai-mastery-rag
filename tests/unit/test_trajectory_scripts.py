"""scripts/run_trajectories.py as a user uses it, with the agent run replaced by saved records (no model, no index)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from app.agent.defense import Defense
from app.config import settings
from evals import race, runner

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import run_trajectories    # noqa: E402

TASK_ID = "t7-notice-end-date"          # a real task: it needs search_policies then add_days


def call_record(name, arguments, observation="ok"):
    return {"name": name, "arguments": json.dumps(arguments), "observation": observation, "ok": True, "blocked": False}


def agent_run(repeat, clean=True):
    """A finished run of TASK_ID. A clean one searches then computes; the other skips the date tool."""
    calls = [call_record("search_policies", {"query": "notice"}, "[1] [source: Acme-Employment-Terms-2026.md] 30 calendar days of written notice"),
             call_record("add_days", {"date": "2026-11-03", "days": 30}, "2026-12-03 (Thursday)")]
    steps = [{"n": i + 1, "kind": "tool", "content": "", "tool_calls": [c], "seconds": 1.0, "tokens": {"prompt": 100, "completion": 10}}
             for i, c in enumerate(calls if clean else calls[:1])]
    return {"task_id": TASK_ID, "approach": "agent", "repeat": repeat, "success": True, "finished": True, "rules_passed": True,
            "stop_reason": "final", "answer": "It ends on 3 December 2026 [source: Acme-Employment-Terms-2026.md]",
            "failed_checks": [], "warnings": [], "n_steps": len(steps), "tool_calls": [c["name"] for c in calls],
            "llm_calls": 3, "prompt_tokens": 600, "completion_tokens": 60, "api_seconds": 3.0, "wait_seconds": 0.0,
            "elapsed_seconds": 3.5, "steps": steps, "notes": []}


def saved_run(label, runs, complete=True, stopped=None):
    return {"meta": {"label": label, "complete": complete, "stopped_because": stopped, "repeats": 1, "overrides": {}, "defense": False},
            "runs": runs}


class RunTrajectoriesScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.tmp))
        self.enterContext(mock.patch.object(run_trajectories.pipeline, "require_index"))

    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_trajectories.main(list(args))
        return code, out.getvalue()

    def fake_race(self, runs, complete=True):
        return mock.patch.object(run_trajectories.race, "run_race", return_value=saved_run("x", runs, complete))

    def test_a_run_is_graded_printed_and_saved_with_its_settings_recorded(self):
        with self.fake_race([agent_run(1), agent_run(2, clean=False)]) as racing:
            code, out = self.call("--label", "demo", "--repeats", "1", "--only", TASK_ID, "--set", "agent_max_calls_per_tool=3")
        self.assertEqual(code, 0)
        self.assertIn("trajectory clean (no failure mode)    1/2", out)
        self.assertIn("skipped-tool", out)
        self.assertIn("saved:", out)
        saved = runner.load_results("trajectories-demo")
        self.assertEqual(saved["meta"]["overrides"], {"agent_max_calls_per_tool": 3})
        self.assertEqual(len(saved["graded"]), 2)
        self.assertEqual(racing.call_args.kwargs["repeats"], 1)

    def test_a_forced_run_that_is_cut_short_says_the_old_complete_run_was_kept(self):
        runner.save_results(saved_run("old", [agent_run(1), agent_run(2)]), runner.results_path("trajectories-old"))
        with self.fake_race([agent_run(1)], complete=False):
            code, out = self.call("--label", "old", "--only", TASK_ID, "--force")
        self.assertEqual(code, 1)
        self.assertIn("WARNING: 'old' already had a complete saved run, so it was kept", out)
        self.assertEqual(len(runner.load_results("trajectories-old")["runs"]), 2)

    def test_a_cut_short_run_with_no_older_run_to_keep_prints_no_warning(self):
        with self.fake_race([agent_run(1)], complete=False):
            code, out = self.call("--label", "fresh", "--only", TASK_ID)
        self.assertEqual(code, 1)
        self.assertNotIn("WARNING", out)

    def test_a_run_cut_short_exits_non_zero_but_is_still_saved(self):
        with self.fake_race([agent_run(1)], complete=False):
            code, _ = self.call("--label", "cut", "--only", TASK_ID)
        self.assertEqual(code, 1)
        self.assertEqual(len(runner.load_results("trajectories-cut")["runs"]), 1)

    def test_defense_switches_on_the_three_layers(self):
        with self.fake_race([agent_run(1)]) as racing:
            code, out = self.call("--label", "guarded", "--only", TASK_ID, "--defense")
        self.assertEqual(code, 0)
        self.assertIn("defences ON", out)
        self.assertIsInstance(racing.call_args.kwargs["defense"], Defense)
        self.assertTrue(runner.load_results("trajectories-guarded")["meta"]["defense"])

    def test_show_prints_a_saved_run_and_says_when_it_was_partial(self):
        with self.fake_race([agent_run(1), agent_run(2, clean=False)], complete=False):
            self.call("--label", "partial", "--only", TASK_ID)
        code, out = self.call("--show", "partial")
        self.assertEqual(code, 0)
        self.assertIn("a PARTIAL run", out)
        self.assertIn("trajectories 'partial': 2 run(s)", out)
        self.assertIn("runs with a failure mode:", out)
        self.assertEqual(self.call("--show", "missing")[0], 1)

    def test_a_saved_race_is_regraded_for_free_into_a_new_label(self):
        runner.save_results(saved_run("old", [agent_run(1), dict(agent_run(2), approach="workflow")]), runner.results_path("race-old"))
        with mock.patch.object(run_trajectories.race, "run_race") as racing:
            code, out = self.call("--grade", "race-old", "--label", "regraded", "--only", TASK_ID)
        self.assertEqual(code, 0)
        racing.assert_not_called()
        self.assertIn("trajectories 'regraded': 1 run(s)", out)                      # only the agent's runs are graded
        self.assertTrue(os.path.exists(runner.results_path("trajectories-regraded")))

    def test_a_saved_run_is_regraded_in_place_and_keeps_its_settings_and_its_partial_flag(self):
        stale = dict(saved_run("old", [agent_run(1), agent_run(2, clean=False)], complete=False, stopped="quota"),
                     summary={"trajectory_ok": 99, "outcome_ok": 99, "modes": {}})
        stale["meta"]["overrides"] = {"agent_max_calls_per_tool": 3}
        runner.save_results(stale, runner.results_path("trajectories-old"))
        with mock.patch.object(run_trajectories.race, "run_race") as racing:
            code, out = self.call("--regrade", "old")
        self.assertEqual(code, 0)
        racing.assert_not_called()
        self.assertIn("re-graded in place", out)
        self.assertIn("trajectory clean 99 -> 1", out)
        saved = runner.load_results("trajectories-old")
        self.assertEqual((saved["meta"]["complete"], saved["meta"]["overrides"]), (False, {"agent_max_calls_per_tool": 3}))
        self.assertIn("regraded", saved["meta"])
        self.assertEqual((saved["summary"]["trajectory_ok"], len(saved["runs"])), (1, 2))
        self.assertEqual(self.call("--regrade", "missing")[0], 1)

    def test_bad_arguments_are_explained_not_tracebacks(self):
        for args, fragment in ((["--repeats", "0"], "--repeats must be 1 or greater"), (["--only", "t7-nope"], "unknown task id"),
                               (["--set", "no_such_setting=1"], "no_such_setting")):
            with self.subTest(args=args), mock.patch.object(run_trajectories.race, "run_race") as racing:
                code, out = self.call(*args)
            self.assertEqual(code, 1)
            self.assertIn(fragment, out)
            racing.assert_not_called()


class InterleaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.tmp))
        self.enterContext(mock.patch.object(run_trajectories.pipeline, "require_index"))
        self.calls = []

    def fake_run(self, stop_on_call=None, errors=False, errors_on=(), interrupt_on_call=None):
        """A stand-in for race.run_race: one agent run per call, noting which arm ran and the cap in force."""
        def run(tasks, approaches=("agent",), repeats=1, label="x", say=print, **options):
            self.calls.append((label, settings.agent_max_calls_per_tool))
            say("[ok  ] some-task               agent     run 1/1  2 call(s)")
            if interrupt_on_call == len(self.calls):
                raise KeyboardInterrupt
            if stop_on_call == len(self.calls):
                return {"meta": {"label": label, "complete": False, "stopped_because": "the free daily quota for this model is used up"}, "runs": []}
            record = agent_run(1)
            if errors or len(self.calls) in errors_on:
                record = dict(record, stop_reason="error", success=False,
                              steps=[{"n": 1, "kind": "error", "content": "RateLimitError: slow down", "tool_calls": []}])
            return {"meta": {"label": label, "complete": True, "stopped_because": None}, "runs": [record]}
        return mock.patch.object(run_trajectories.race, "run_race", side_effect=run)

    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_trajectories.main(list(args))
        return code, out.getvalue()

    def test_an_arm_is_a_label_with_optional_settings(self):
        self.assertEqual(run_trajectories.parse_arm("a"), ("a", {}))
        self.assertEqual(run_trajectories.parse_arm("b:agent_max_calls_per_tool=3"), ("b", {"agent_max_calls_per_tool": 3}))
        with self.assertRaises(ValueError):
            run_trajectories.parse_arm(":agent_max_calls_per_tool=3")

    def test_the_arms_take_turns_on_every_task_and_repeat_and_each_is_saved_under_its_own_label(self):
        with self.fake_run():
            code, out = self.call("--interleave", "a", "b:agent_max_calls_per_tool=3", "c", "--only", TASK_ID, "--repeats", "2")
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, [("b", 3), ("c", 0), ("a", 0), ("c", 0), ("a", 0), ("b", 3)])     # the first arm rotates
        for label in "abc":
            saved = runner.load_results("trajectories-" + label)
            self.assertEqual(sorted(r["repeat"] for r in saved["runs"]), [1, 2])
            self.assertEqual(saved["meta"]["interleaved_with"], [other for other in "abc" if other != label])
            self.assertTrue(saved["meta"]["complete"])
        self.assertEqual(runner.load_results("trajectories-b")["meta"]["overrides"], {"agent_max_calls_per_tool": 3})
        self.assertEqual(runner.load_results("trajectories-a")["meta"]["overrides"], {})
        self.assertIn("trajectories 'b': 2 run(s)", out)
        self.assertIn("b               [ok  ] some-task               agent     repeat 2/2", out)       # the real repeat, not "run 1/1"

    def test_a_quota_that_ends_part_way_leaves_the_arms_balanced_and_the_files_partial(self):
        with self.fake_run(stop_on_call=3):
            code, out = self.call("--interleave", "a", "b", "c", "--only", TASK_ID, "--repeats", "2")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 3)                                            # it stopped at once, not after the repeats
        for label in "bc":                                                              # the two arms that ran before the cut-off
            saved = runner.load_results("trajectories-" + label)
            self.assertEqual((len(saved["runs"]), saved["meta"]["complete"]), (1, False))
            self.assertIn("daily quota", saved["meta"]["stopped_because"])
        self.assertIn("'a': no run finished, nothing saved", out)
        self.assertFalse(os.path.exists(runner.results_path("trajectories-a")))

    def test_a_provider_outage_stops_the_whole_interleaved_job_and_the_files_are_partial_not_complete(self):
        with self.fake_run(errors=True):
            code, out = self.call("--interleave", "a", "b", "--only", TASK_ID, "--repeats", "5")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), run_trajectories.race.MAX_ERRORS_IN_A_ROW)           # not all 10 slots
        self.assertIn("runs in a row ended on a provider error", out)
        for label in "ab":
            saved = runner.load_results("trajectories-" + label)
            self.assertFalse(saved["meta"]["complete"])
            self.assertIn("provider error", saved["meta"]["stopped_because"])

    def test_one_error_between_good_runs_is_not_an_outage(self):
        with self.fake_run(errors_on={2}):
            code, _ = self.call("--interleave", "a", "b", "--only", TASK_ID, "--repeats", "2")
        self.assertEqual((code, len(self.calls)), (0, 4))

    def test_what_has_finished_is_saved_after_every_task_so_an_interruption_loses_nothing(self):
        with self.fake_run(interrupt_on_call=5), self.assertRaises(KeyboardInterrupt):
            self.call("--interleave", "a", "b", "--only", TASK_ID, "--repeats", "3")
        for label in "ab":
            saved = runner.load_results("trajectories-" + label)
            self.assertEqual(len(saved["runs"]), 2)                                         # repeats 1 and 2 were finished and saved
            self.assertFalse(saved["meta"]["complete"])
            self.assertTrue(saved["meta"]["stopped_because"].startswith("interrupted"))

    def test_each_arm_records_the_cap_that_was_really_in_force_and_when_the_job_ran(self):
        with self.fake_run():
            self.call("--interleave", "a", "b:agent_max_calls_per_tool=3", "--only", TASK_ID, "--repeats", "1")
        a, b = (runner.load_results("trajectories-" + label)["meta"] for label in "ab")
        self.assertEqual((a["agent_max_calls_per_tool"], b["agent_max_calls_per_tool"]), (0, 3))
        self.assertLessEqual(a["started"], a["finished"])
        self.assertEqual(a["started"], b["started"])

    def test_a_saved_label_is_never_overwritten_unless_forced(self):
        with self.fake_run():
            self.assertEqual(self.call("--interleave", "a", "b", "--only", TASK_ID, "--repeats", "1")[0], 0)
            code, out = self.call("--interleave", "a", "c", "--only", TASK_ID, "--repeats", "1")
            self.assertEqual(code, 1)
            self.assertIn("'a' is already saved", out)
            self.assertFalse(os.path.exists(runner.results_path("trajectories-c")))          # nothing ran, not even the new arm
            self.assertEqual(self.call("--interleave", "a", "c", "--only", TASK_ID, "--repeats", "1", "--force")[0], 0)

    def test_a_forced_job_that_finishes_removes_the_leftover_progress_file_and_replaces_the_old_run(self):
        runner.save_results(saved_run("a", [agent_run(1), agent_run(2)]), runner.results_path("trajectories-a"))
        with self.fake_run():
            code, _ = self.call("--interleave", "a", "b", "--only", TASK_ID, "--repeats", "1", "--force")
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.load_results("trajectories-a")["runs"]), 1)               # the new job's single run replaced the old two
        self.assertFalse(os.path.exists(runner.results_path("trajectories-a")[:-5] + ".incomplete.json"))

    def test_a_forced_job_that_is_cut_short_says_the_old_complete_run_was_kept(self):
        runner.save_results(dict(saved_run("a", [agent_run(1), agent_run(2)]), meta={"label": "a", "complete": True}),
                            runner.results_path("trajectories-a"))
        with self.fake_run(stop_on_call=3):                                                   # repeat 1 finished for both arms, then the quota ends
            code, out = self.call("--interleave", "a", "b", "--only", TASK_ID, "--repeats", "2", "--force")
        self.assertEqual(code, 1)
        self.assertIn("WARNING: 'a' already had a complete saved run, so it was kept", out)
        self.assertEqual(len(runner.load_results("trajectories-a")["runs"]), 2)               # still the old complete file
        self.assertTrue(os.path.exists(runner.results_path("trajectories-a")[:-5] + ".incomplete.json"))

    def test_show_lists_every_call_a_defence_or_the_budget_refused_by_name(self):
        record = agent_run(1)
        record["steps"][0]["tool_calls"].append({"name": "add_days", "arguments": "{}", "observation": "BLOCKED: the date was not stated",
                                                 "ok": False, "blocked": True})
        with mock.patch.object(run_trajectories.race, "run_race", return_value=saved_run("x", [record])):
            self.call("--label", "refused", "--only", TASK_ID)
        code, out = self.call("--show", "refused")
        self.assertEqual(code, 0)
        self.assertIn("calls refused before they ran:", out)
        self.assertIn("add_days (guard): BLOCKED: the date was not stated", out)
        self.assertIn("calls refused before they ran: 1 by the guard", out)

    def test_a_plain_run_records_its_cap_and_also_refuses_to_replace_a_saved_label(self):
        racing = mock.patch.object(run_trajectories.race, "run_race", return_value=saved_run("x", [agent_run(1)]))
        with racing:
            self.assertEqual(self.call("--label", "solo", "--only", TASK_ID, "--set", "agent_max_calls_per_tool=3")[0], 0)
            self.assertEqual(runner.load_results("trajectories-solo")["meta"]["agent_max_calls_per_tool"], 3)
            code, out = self.call("--label", "solo", "--only", TASK_ID)
        self.assertEqual(code, 1)
        self.assertIn("already saved", out)

    def test_bad_arms_are_explained_and_nothing_runs(self):
        for args, fragment in ((["--interleave", "only-one"], "two or more arms"), (["--interleave", "a", "a"], "different labels"),
                               (["--interleave", "a", "b", "--repeats", "0"], "--repeats must be 1 or greater"),
                               (["--interleave", "a", "b:no_such_setting=1"], "no_such_setting")):
            with self.subTest(args=args), self.fake_run() as racing:
                code, out = self.call(*args)
            self.assertEqual(code, 1)
            self.assertIn(fragment, out)
            racing.assert_not_called()


if __name__ == "__main__":
    unittest.main()
