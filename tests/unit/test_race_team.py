"""Week 10: scripts/race_team.py: the interleaved plan, the frozen-code rules, saving, resuming, stopping and the report paths (no model calls)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest import mock

import _testkit
from app import llm
from evals import race, runner
from evals.agent_tasks import get_tasks

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import race_team           # noqa: E402

TWO = ["t7-single-lookup", "t7-conflict"]
CLEAN = {"git": "abc1234", "dirty": False, **{key: "0123456789ab" for key in race_team.CODE_KEYS}}
MODEL = "model-x"


def captured(function, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = function(*args)
    return result, out.getvalue()


def fake_record(task, approach, repeat, success=True, stop="final", team=None, calls=2, steps=None, answer="an answer"):
    record = {"task_id": task["id"], "approach": approach, "repeat": repeat, "success": success, "finished": stop == "final",
              "rules_passed": success, "stop_reason": stop, "answer": answer, "failed_checks": [], "warnings": [], "n_steps": 2,
              "tool_calls": [], "llm_calls": calls, "prompt_tokens": 100, "completion_tokens": 10, "api_seconds": 1.0, "wait_seconds": 0.0,
              "elapsed_seconds": 2.0, "steps": steps if steps is not None else [], "notes": []}
    if team is not None:
        record["team"] = team
    return record


class Racer:
    """Stands in for race.run_one: records what it was asked and returns a plain record (a script can change `outcome`)."""

    def __init__(self, outcome=None):
        self.calls, self.outcome = [], outcome

    def __call__(self, task, approach, repeat, tools, **options):
        self.calls.append((task["id"], approach, repeat, options))
        if self.outcome:
            outcome = self.outcome(len(self.calls))
            if isinstance(outcome, Exception):
                raise outcome
            if outcome:
                return fake_record(task, approach, repeat, **outcome)
        return fake_record(task, approach, repeat)


class PlanTests(unittest.TestCase):
    def test_every_task_gets_every_arm_in_every_repeat_and_repeats_come_first(self):
        tasks = get_tasks(TWO)
        plan = race_team.build_plan(tasks, 2, ["agent", "team"])
        self.assertEqual(len(plan), 2 * 2 * 2)
        self.assertEqual([repeat for repeat, _task, _arm in plan], [1, 1, 1, 1, 2, 2, 2, 2])            # repeat-major
        self.assertEqual(Counter((repeat, task["id"]) for repeat, task, _arm in plan), Counter({(r, t): 2 for r in (1, 2) for t in TWO}))

    def test_the_arm_order_rotates_so_no_arm_always_goes_first(self):
        plan = race_team.build_plan(get_tasks(), 3, ["agent", "team", "agent-2"])
        leaders = Counter(plan[i][2] for i in range(0, len(plan), 3))                                    # the first run of every (repeat, task)
        self.assertEqual(sorted(leaders.values()), [9, 9, 9])

    def test_the_arms_are_agent_then_team_with_the_optional_extras_after(self):
        self.assertEqual(race_team.arm_list(), ["agent", "team"])
        self.assertEqual(race_team.arm_list(noise=True, with_workflow=True), ["agent", "team", "agent-2", "workflow"])


class RunPlanTests(unittest.TestCase):
    def results(self, arms=("agent", "team"), repeats=2, runs=None):
        meta = race_team.make_meta("t", get_tasks(TWO), repeats, list(arms), "m", "now")
        return {"meta": meta, "runs": runs or []}

    def go(self, results, racer, repeats=2, arms=("agent", "team"), tasks=TWO, **kwargs):
        saved = []
        stopped = race_team.run_plan(race_team.build_plan(get_tasks(tasks), repeats, list(arms)), results, [], kwargs.pop("options", {}),
                                     lambda r: saved.append(len(r["runs"])), say=lambda *_: None, run_one=racer, **kwargs)
        return stopped, saved

    def test_it_runs_the_plan_saving_after_every_run(self):
        results, racer = self.results(), Racer()
        stopped, saved = self.go(results, racer)
        self.assertIsNone(stopped)
        self.assertEqual(len(results["runs"]), 8)
        self.assertEqual(saved, list(range(1, 9)))

    def test_what_is_already_in_the_results_is_not_run_again(self):
        tasks = get_tasks(TWO)
        done = [fake_record(tasks[0], "agent", 1), fake_record(tasks[0], "team", 1)]
        results, racer = self.results(runs=list(done)), Racer()
        self.go(results, racer)
        self.assertEqual(len(racer.calls), 6)
        self.assertNotIn((tasks[0]["id"], "agent", 1), [(t, a, r) for t, a, r, _ in racer.calls])

    def test_the_noise_arm_runs_the_agent_and_is_recorded_under_its_own_name(self):
        results, racer = self.results(arms=("agent", "team", "agent-2"), repeats=1), Racer()
        self.go(results, racer, repeats=1, arms=("agent", "team", "agent-2"), tasks=TWO[:1])
        self.assertEqual(sorted(approach for _t, approach, _r, _o in racer.calls), ["agent", "agent", "team"])      # agent-2 runs the AGENT
        self.assertEqual(sorted(run["approach"] for run in results["runs"]), ["agent", "agent-2", "team"])

    def test_the_options_reach_every_run(self):
        results, racer = self.results(repeats=1), Racer()
        self.go(results, racer, repeats=1, tasks=TWO[:1], options={"model": "m-x", "timeout_seconds": 300.0, "max_calls_per_tool": 0})
        self.assertEqual({tuple(sorted(options.items())) for *_rest, options in racer.calls},
                         {(("max_calls_per_tool", 0), ("model", "m-x"), ("timeout_seconds", 300.0))})

    def test_the_model_the_provider_names_is_kept_with_the_run(self):
        def racer(task, approach, repeat, tools, **options):
            llm._last_model["name"] = "served-name"
            return fake_record(task, approach, repeat)
        results = self.results(repeats=1)
        self.go(results, racer, repeats=1, arms=("agent",), tasks=TWO[:1])
        self.assertEqual(results["runs"][0]["served_model"], "served-name")
        llm.reset_last_model()

    def test_a_used_up_quota_stops_the_race_and_keeps_what_finished(self):
        results = self.results()
        stopped, _saved = self.go(results, Racer(lambda n: llm.QuotaExhausted("the daily quota is used up") if n == 3 else None))
        self.assertIn("daily quota", stopped)
        self.assertEqual(len(results["runs"]), 2)

    def test_a_string_of_provider_errors_is_an_outage_but_one_error_between_good_runs_is_not(self):
        results = self.results()
        stopped, _saved = self.go(results, Racer(lambda n: {"success": False, "stop": "error"}))
        self.assertIn(f"{race.MAX_ERRORS_IN_A_ROW} runs in a row ended on a provider error", stopped)
        self.assertEqual(len(results["runs"]), race.MAX_ERRORS_IN_A_ROW)
        results = self.results()
        stopped, _saved = self.go(results, Racer(lambda n: {"success": False, "stop": "error"} if n % 2 else None))
        self.assertIsNone(stopped)

    def test_a_specialist_that_hit_a_provider_error_counts_toward_an_outage_too(self):
        team = {"per_agent": {}, "handoffs": [{"agent": "researcher", "state": "not_finished", "stop_reason": "error"}]}
        self.assertTrue(race_team.provider_trouble(fake_record(get_tasks(TWO)[0], "team", 1, team=team)))
        self.assertFalse(race_team.provider_trouble(fake_record(get_tasks(TWO)[0], "team", 1, team={"per_agent": {}, "handoffs": []})))

    def test_a_crash_in_one_run_stops_with_the_reason_and_keeps_the_earlier_runs(self):
        results = self.results()
        stopped, _saved = self.go(results, Racer(lambda n: RuntimeError("index locked") if n == 2 else None))
        self.assertIn("a run failed unexpectedly (RuntimeError): index locked", stopped)
        self.assertEqual(len(results["runs"]), 1)

    def test_it_stops_when_the_call_budget_for_the_session_is_used(self):
        results, racer = self.results(), Racer()
        stopped, _saved = self.go(results, racer, max_calls=5)                                     # each fake run is 2 calls: 2, 4, 6
        self.assertIn("--max-calls 5 reached (6 model calls used", stopped)
        self.assertEqual(len(results["runs"]), 3)

    def test_a_run_whose_usage_does_not_add_up_stops_the_race_loudly_after_saving_it(self):
        crew = {"per_agent": {}, "handoffs": [], "warnings": ["usage mismatch: 3 calls against 4"], "errors": []}
        results = self.results()
        stopped, saved = self.go(results, Racer(lambda n: {"team": crew} if n == 2 else None))
        self.assertIn("did not add up to the process counters: usage mismatch", stopped)
        self.assertEqual((len(results["runs"]), saved[-1]), (2, 2))                                   # the odd run is kept for the record

    def test_a_hand_off_that_failed_on_a_bug_stops_the_race_loudly(self):
        crew = {"per_agent": {}, "handoffs": [], "warnings": [], "errors": [{"agent": "researcher", "type": "KeyError"}]}
        stopped, _saved = self.go(self.results(), Racer(lambda n: {"team": crew} if n == 1 else None))
        self.assertIn("a hand-off failed on a bug in the team code (KeyError in the researcher)", stopped)


class InstrumentTests(unittest.TestCase):
    def test_a_single_agent_run_gets_the_same_per_call_record_the_team_keeps(self):
        def real_calls(task, approach, repeat, tools, **options):
            llm._usage["calls"] += 1                                      # the counters a real run would have moved
            llm._usage["prompt_tokens"] += 100
            llm._usage["completion_tokens"] += 10
            llm._record_call(1.0, 0.5, 0.0, 1, "m", "served", 100, 10)
            return fake_record(task, approach, repeat, calls=1)
        llm.reset_usage()
        record = race_team.run_scoped("agent", get_tasks(TWO)[0], 1, [], {}, real_calls)
        self.assertEqual([(call["agent"], call["handoff"], call["served"], call["prompt_tokens"]) for call in record["call_log"]], [("agent", None, "served", 100)])
        self.assertNotIn("usage_warning", record)

    def test_calls_the_run_reported_but_the_records_do_not_show_are_flagged(self):
        def lying(task, approach, repeat, tools, **options):
            llm._record_call(1.0, 0.5, 0.0, 1, "m", "served", 100, 10)
            return fake_record(task, approach, repeat, calls=3)          # reports 3 calls, 300 tokens more than the one that was recorded
        record = race_team.run_scoped("agent", get_tasks(TWO)[0], 1, [], {}, lying)
        self.assertIn("usage mismatch: the per-call records add up to 1 calls", record["usage_warning"])

    def test_a_run_that_made_no_model_call_has_nothing_to_cross_check(self):
        record = race_team.run_scoped("agent", get_tasks(TWO)[0], 1, [], {}, lambda *a, **k: fake_record(get_tasks(TWO)[0], "agent", 1))
        self.assertEqual(record["call_log"], [])
        self.assertNotIn("usage_warning", record)

    def test_the_team_keeps_its_own_call_log_and_is_not_given_a_second_one(self):
        crew = {"per_agent": {}, "handoffs": [], "call_log": [], "warnings": [], "errors": []}
        record = race_team.run_scoped("team", get_tasks(TWO)[0], 1, [], {}, lambda t, a, r, tools, **k: fake_record(t, a, r, team=crew))
        self.assertNotIn("call_log", record)


class FrozenCodeTests(unittest.TestCase):
    def test_the_stamp_names_the_commit_whether_the_code_was_clean_and_a_hash_of_every_stamped_file(self):
        with mock.patch.object(race_team, "git", side_effect=lambda *args: {"rev-parse": "abc1234", "status": ""}[args[0]]):
            stamp = race_team.code_stamp()
        self.assertEqual((stamp["git"], stamp["dirty"]), ("abc1234", False))
        for key in race_team.CODE_KEYS:
            self.assertRegex(stamp[key], r"^[0-9a-f]{12}$")

    def test_uncommitted_changes_are_dirty_and_an_unreadable_git_is_unknown_not_clean(self):
        with mock.patch.object(race_team, "git", side_effect=lambda *args: {"rev-parse": "abc1234", "status": " M app/x.py"}[args[0]]):
            self.assertTrue(race_team.code_stamp()["dirty"])
        with mock.patch.object(race_team, "git", return_value=None):
            stamp = race_team.code_stamp()
        self.assertEqual((stamp["git"], stamp["dirty"]), ("unknown", None))

    def test_a_file_hash_ignores_the_line_endings_a_checkout_chose(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        for name, data in (("lf.txt", b"a\nb\n"), ("crlf.txt", b"a\r\nb\r\n")):
            with open(os.path.join(folder, name), "wb") as handle:
                handle.write(data)
        with mock.patch.object(race_team, "BASE_DIR", folder):
            self.assertEqual(race_team.file_sha("lf.txt"), race_team.file_sha("crlf.txt"))
            self.assertIsNone(race_team.file_sha("missing.txt"))

    def test_the_corpus_fingerprint_lists_every_document_with_a_hash_and_skips_hidden_files(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        for name, text in (("a.md", "one"), ("b.md", "two"), (".uploaded_documents.json", "{}")):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        with mock.patch.object(race_team.settings, "corpus_dir", folder):
            fingerprint = race_team.corpus_fingerprint()
        self.assertEqual(sorted(fingerprint), ["a.md", "b.md"])
        self.assertNotEqual(fingerprint["a.md"], fingerprint["b.md"])

    def test_every_arm_records_what_it_was_run_with_so_the_differences_are_visible(self):
        meta = race_team.make_meta("t", get_tasks(TWO), 3, ["agent", "team", "agent-2"], "m", "now", 300.0)
        self.assertEqual(meta["arms"], meta["approaches"])
        self.assertEqual(meta["tasks"], TWO)
        self.assertEqual((meta["noise_arm"], meta["interleaved"], meta["models"]), ("agent-2", True, {"agent": "m", "team": "m", "agent-2": "m"}))
        self.assertEqual(meta["config"]["agent"], meta["config"]["agent-2"])                  # the noise arm is the same agent
        crew = meta["config"]["team"]
        self.assertEqual((crew["memory"], meta["config"]["agent"]["memory"]), ("on", "on"))     # memory is not a difference between the arms
        self.assertEqual((crew["calls per tool cap"], meta["config"]["agent"]["calls per tool cap"], meta["limits"]["agent_max_calls_per_tool"]), (0, 0, 0))
        self.assertEqual((crew["manager steps"], crew["researcher steps"], crew["calculator steps"]), (8, 8, 4))
        self.assertEqual(meta["limits"]["timeout_seconds"], 300.0)
        for key in ("manager prompt sha", "researcher prompt sha", "calculator prompt sha"):
            self.assertRegex(crew[key], r"^[0-9a-f]{12}$")
        self.assertIsNone(race_team.make_meta("t", get_tasks(TWO), 1, ["agent", "team"], "m", "now")["noise_arm"])

    def test_the_cap_table_has_a_row_for_every_agent_of_every_arm(self):
        rows = race_team.caps_table(["agent", "team"], 300.0)
        self.assertEqual([(row["arm"], row["agent"], row["steps"]) for row in rows],
                         [("agent", "agent", 8), ("team", "manager", 8), ("team", "researcher", 8), ("team", "calculator", 4)])
        self.assertEqual({row["calls per tool"] for row in rows}, {0})
        self.assertEqual((rows[0]["tokens"], rows[1]["tokens"]), (40000, "shared"))

    def test_changing_a_prompt_changes_its_recorded_hash(self):
        before = race_team.arm_config("team")["manager prompt sha"]
        with mock.patch.object(race_team.team, "MANAGER_PROMPT", "something else"):
            self.assertNotEqual(race_team.arm_config("team")["manager prompt sha"], before)


class ScrubTests(unittest.TestCase):
    def test_a_key_and_the_project_path_never_reach_what_is_saved(self):
        with mock.patch.object(race_team.settings, "openai_api_key", "sentinel-key-123456"):
            text = f"failed with key sentinel-key-123456 in {race_team.BASE_DIR}/app/x.py " + "x" * 500
            scrubbed = race_team.scrub_text(text)
        self.assertNotIn("sentinel-key-123456", scrubbed)
        self.assertNotIn(str(race_team.BASE_DIR), scrubbed)
        self.assertIn("<key>", scrubbed)
        self.assertIn("<project>", scrubbed)
        self.assertLessEqual(len(scrubbed), 300)

    def test_provider_error_text_in_the_steps_is_scrubbed_but_other_steps_are_left_alone(self):
        record = {"steps": [{"kind": "error", "content": f"boom at {race_team.BASE_DIR}/x"}, {"kind": "final", "content": f"{race_team.BASE_DIR}"}]}
        race_team.scrub_record(record)
        self.assertEqual(record["steps"][0]["content"], "boom at <project>/x")
        self.assertEqual(record["steps"][1]["content"], str(race_team.BASE_DIR))

    def test_a_saved_race_holds_neither_the_key_nor_the_path_even_when_the_run_that_stopped_it_carried_both(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", folder))
        self.enterContext(mock.patch.object(race_team, "code_stamp", return_value=CLEAN))
        self.enterContext(mock.patch.object(race_team.pipeline, "require_index"))
        self.enterContext(mock.patch.object(race_team.settings, "openai_api_key", "sentinel-key-123456"))
        racer = Racer(lambda n: RuntimeError(f"index at {race_team.BASE_DIR} with key sentinel-key-123456"))
        self.enterContext(mock.patch.object(race_team.race, "run_one", racer))
        code, _text = captured(race_team.main, ["--label", "leak", "--model", MODEL, "--only", *TWO])
        self.assertEqual(code, 1)
        with open(runner.results_path("race-leak"), encoding="utf-8") as handle:
            saved = handle.read()
        self.assertNotIn("sentinel-key-123456", saved)
        self.assertNotIn(str(race_team.BASE_DIR).replace("\\", "\\\\"), saved)                   # as JSON writes a Windows path
        self.assertNotIn(str(race_team.BASE_DIR), saved)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.folder))
        self.enterContext(mock.patch.object(race_team, "BASE_DIR", self.folder))              # --save must not touch the real docs
        self.stamp = dict(CLEAN)
        self.enterContext(mock.patch.object(race_team, "code_stamp", side_effect=lambda: dict(self.stamp)))
        self.enterContext(mock.patch.object(race_team.pipeline, "require_index"))
        self.racer = Racer()
        self.enterContext(mock.patch.object(race_team.race, "run_one", self.racer))

    def race(self, *flags, label="t", model=MODEL):
        argv = ["--label", label, "--only", *TWO, "--repeats", "2", *flags]
        return captured(race_team.main, argv + (["--model", model] if model else []))

    def saved(self, label="t"):
        return runner.load_results("race-" + label)

    def test_a_race_is_saved_complete_with_its_stamp_and_prints_the_report(self):
        code, text = self.race()
        self.assertEqual(code, 0)
        done = self.saved()
        self.assertEqual((len(done["runs"]), done["meta"]["complete"]), (8, True))
        self.assertEqual((done["meta"]["code"]["git"], done["meta"]["code"]["dirty"]), ("abc1234", False))
        self.assertTrue(done["meta"]["corpus"])
        for needle in ("QUALITY", "COST", "CAPS", "saved:", "corpus:"):
            self.assertIn(needle, text)

    def test_the_model_must_be_named_and_an_alias_that_moves_is_refused(self):
        code, text = self.race(model=None)
        self.assertEqual((code, "--model" in text), (1, True))
        code, text = self.race(model="gemini-flash-lite-latest")
        self.assertEqual((code, "alias that moves" in text), (1, True))
        self.assertEqual(self.racer.calls, [])

    def test_every_arm_gets_the_same_model_the_same_timeout_and_no_per_tool_cap(self):
        self.race("--timeout", "200")
        self.assertEqual({tuple(sorted(options.items())) for *_rest, options in self.racer.calls},
                         {(("max_calls_per_tool", 0), ("model", MODEL), ("timeout_seconds", 200.0))})
        self.assertEqual(self.saved()["meta"]["limits"]["timeout_seconds"], 200.0)

    def test_a_race_on_uncommitted_code_is_refused_and_only_a_pilot_may_run_on_it(self):
        self.stamp["dirty"] = True
        code, text = self.race()
        self.assertEqual((code, "uncommitted changes" in text), (1, True))
        self.assertEqual(self.racer.calls, [])
        code, text = self.race("--allow-dirty")
        self.assertEqual((code, "pilot- prefix" in text), (1, True))
        code, text = self.race("--allow-dirty", label="pilot-1")
        self.assertEqual(code, 0)
        self.assertIn("UNCOMMITTED changes: a pilot", text)
        self.assertTrue(self.saved("pilot-1")["meta"]["code"]["dirty"])

    def test_an_unreadable_git_is_a_warning_not_a_silent_clean_stamp(self):
        self.stamp["dirty"] = None
        code, text = self.race()
        self.assertEqual(code, 0)
        self.assertIn("git could not be read", text)

    def test_a_saved_label_is_refused_unless_resume_or_force_says_what_to_do(self):
        self.race()
        before = len(self.racer.calls)
        code, text = self.race()
        self.assertEqual(code, 1)
        self.assertIn("already saved", text)
        self.assertEqual(len(self.racer.calls), before)                                           # nothing ran

    def test_force_starts_over_and_replaces_the_saved_race_when_the_new_one_finishes(self):
        self.race()
        code, _text = self.race("--force")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.racer.calls), 16)
        self.assertEqual(len(self.saved()["runs"]), 8)

    def test_a_forced_race_that_is_cut_short_leaves_the_older_complete_one_in_place_and_says_so(self):
        self.race()
        self.racer.outcome = lambda n: llm.QuotaExhausted("used up") if n == 12 else None        # the fourth call of the forced race
        code, text = self.race("--force")
        self.assertEqual(code, 1)
        self.assertIn("already had a complete saved race, so it was kept", text)
        self.assertEqual(len(self.saved()["runs"]), 8)                                            # the old complete race
        self.assertTrue(os.path.exists(os.path.join(self.folder, "race-t.incomplete.json")))

    def test_a_race_cut_short_saves_what_finished_and_exits_non_zero_and_resume_finishes_only_the_rest(self):
        self.racer.outcome = lambda n: llm.QuotaExhausted("the daily quota is used up") if n == 4 else None
        code, text = self.race()
        self.assertEqual(code, 1)
        self.assertIn("Carry on with --resume", text)
        partial = self.saved()
        self.assertEqual((len(partial["runs"]), partial["meta"]["complete"]), (3, False))
        self.racer.outcome, self.racer.calls = None, []
        code, _text = self.race("--resume")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.racer.calls), 5)                                                # eight in the plan, three were done
        done = self.saved()
        self.assertEqual((len(done["runs"]), done["meta"]["complete"], len(done["meta"]["resumed"])), (8, True, 1))

    def test_resume_adds_the_noise_arm_to_a_finished_race_without_redoing_anything_or_leaving_a_stray_file(self):
        self.race()
        self.racer.calls = []
        code, _text = self.race("--resume", "--noise")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.racer.calls), 4)                                                # only the new arm's four runs
        done = self.saved()
        self.assertEqual(Counter(run["approach"] for run in done["runs"]), Counter({"agent": 4, "team": 4, "agent-2": 4}))
        self.assertEqual(done["meta"]["arms"], ["agent", "team", "agent-2"])
        self.assertFalse(os.path.exists(os.path.join(self.folder, "race-t.incomplete.json")))

    def test_resume_of_a_finished_race_that_is_cut_short_again_keeps_the_new_progress_for_the_next_resume(self):
        self.race()
        self.racer.outcome = lambda n: llm.QuotaExhausted("used up") if n == 3 else None
        self.racer.calls = []
        code, _text = self.race("--resume", "--noise")
        self.assertEqual(code, 1)
        self.assertTrue(self.saved()["meta"]["complete"])                                         # the finished race is untouched
        self.assertTrue(os.path.exists(os.path.join(self.folder, "race-t.incomplete.json")))
        self.racer.outcome, self.racer.calls = None, []
        code, _text = self.race("--resume", "--noise")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.racer.calls), 2)                                                # four noise runs, two were saved in the stray file
        self.assertEqual(len(self.saved()["runs"]), 12)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "race-t.incomplete.json")))

    def test_resume_refuses_when_the_code_a_prompt_the_limits_or_the_model_changed_since_the_race_began(self):
        self.race()
        self.stamp["team.py"] = "ffffffffffff"
        code, text = self.race("--resume")
        self.assertEqual((code, "team.py" in text, "new label" in text), (1, True, True))
        self.stamp["team.py"] = CLEAN["team.py"]
        code, text = self.race("--resume", "--timeout", "100")
        self.assertEqual((code, "limits" in text), (1, True))
        code, text = self.race("--resume", model="other-model")
        self.assertEqual((code, "models" in text), (1, True))
        with mock.patch.dict(race_team.team.SPECIALISTS["researcher"], {"prompt": "a new prompt"}):
            code, text = self.race("--resume")
        self.assertEqual((code, "config of team" in text), (1, True))

    def test_resume_is_fine_when_only_the_commit_moved_because_documents_were_committed_in_between(self):
        self.racer.outcome = lambda n: llm.QuotaExhausted("used up") if n == 4 else None
        self.race()
        self.stamp["git"] = "def5678"
        self.racer.outcome, self.racer.calls = None, []
        code, _text = self.race("--resume")
        self.assertEqual(code, 0)
        self.assertEqual(self.saved()["meta"]["code"]["git"], "def5678")

    def test_resume_refuses_a_different_set_of_tasks_or_repeats_and_a_missing_race(self):
        self.race()
        code, text = captured(race_team.main, ["--label", "t", "--only", "t7-conflict", "--repeats", "2", "--model", MODEL, "--resume"])
        self.assertEqual((code, "tasks" in text), (1, True))
        code, text = self.race("--resume", label="nothing-here")
        self.assertEqual((code, "no saved race to resume" in text), (1, True))
        code, text = self.race("--resume", "--force")
        self.assertEqual((code, "pick one" in text), (1, True))

    def test_the_call_budget_stops_the_race_cleanly_and_it_can_be_resumed(self):
        code, text = self.race("--max-calls", "5")
        self.assertEqual(code, 1)
        self.assertIn("--max-calls 5 reached", text)
        self.assertEqual(len(self.saved()["runs"]), 3)

    def test_a_label_is_required_and_bad_numbers_and_stray_show_flags_are_explained(self):
        for argv, needle in ((["--only", *TWO], "--label"), (["--label", "x", "--model", MODEL, "--repeats", "0"], "--repeats and --max-calls"),
                             (["--label", "x", "--model", MODEL, "--timeout", "0"], "--timeout greater than 0"),
                             (["--label", "x", "--model", MODEL, "--price-in", "1"], "needs --show"),
                             (["--label", "x", "--model", MODEL, "--price-source", "s"], "needs --show"),
                             (["--label", "x", "--model", MODEL, "--rescore"], "needs --show"),
                             (["--show", "x", "--price-out", "-1"], "must be 0 or more"), (["--pilot", "p"], "goes with --plan")):
            with self.subTest(argv=argv):
                code, text = captured(race_team.main, argv)
                self.assertEqual((code, needle in text), (1, True))

    def test_an_unknown_task_is_explained_and_nothing_is_saved(self):
        code, text = captured(race_team.main, ["--label", "x", "--model", MODEL, "--only", "t7-no-such-task"])
        self.assertEqual((code, "unknown task id" in text), (1, True))
        self.assertFalse(os.path.exists(runner.results_path("race-x")))


class PlanCommandTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.folder))
        self.enterContext(mock.patch.object(race_team.settings, "llm_rpm", 12))        # the minutes line needs a limit, which only some .env files set

    def saved_week_7(self):
        runs = [{"approach": "agent", "llm_calls": 3, "tool_calls": ["search_policies", "calculate"], "task_id": "a", "repeat": 1},
                {"approach": "agent", "llm_calls": 4, "tool_calls": ["search_policies", "search_policies", "add_days"], "task_id": "b", "repeat": 1},
                {"approach": "agent", "llm_calls": 1, "tool_calls": [], "task_id": "c", "repeat": 1}]
        runner.save_results({"meta": {"label": "race", "complete": True}, "runs": runs}, runner.results_path("race-race"))

    def test_the_team_estimate_is_a_model_of_the_hand_offs_on_the_saved_tool_mix_and_says_so(self):
        lean, high = race_team.estimate_team_calls({"runs": [{"approach": "agent", "tool_calls": ["search_policies", "calculate"]}]})
        self.assertEqual((lean, high), ((1 + 2) + 2 + 2, (2 + 1) + 4))       # two hand-offs: manager 3, researcher 2, calculator 2; or per tool call: manager 3 + 4
        self.assertEqual(race_team.estimate_team_calls({"runs": []}), (None, None))
        no_tools = race_team.estimate_team_calls({"runs": [{"approach": "agent", "tool_calls": []}]})
        self.assertEqual(no_tools, (1.0, 1.0))                                # the manager answers alone

    def test_the_plan_prints_runs_calls_and_minutes_with_an_estimate_labelled_as_one(self):
        self.saved_week_7()
        code, text = captured(race_team.main, ["--plan", "--only", *TWO, "--repeats", "2", "--noise"])
        self.assertEqual(code, 0)
        for needle in ("3 arm(s) (agent, team, agent-2)", "= 12 runs", "measured over 3 runs", "an ESTIMATE", "minutes at 12 calls a minute", "--max-calls"):
            self.assertIn(needle, text)

    def test_with_no_rate_limit_the_plan_still_gives_the_calls_but_no_minutes(self):
        self.saved_week_7()
        with mock.patch.object(race_team.settings, "llm_rpm", 0):
            code, text = captured(race_team.main, ["--plan", "--only", *TWO, "--repeats", "2", "--noise"])
        self.assertEqual(code, 0)
        self.assertRegex(text, r"about \d+ model calls in all\. ")                              # the sentence goes straight on: no minutes in between
        self.assertNotIn("minutes at", text)

    def test_a_saved_pilot_replaces_the_estimate_with_calls_per_run_measured_on_questions_that_are_not_race_tasks(self):
        self.saved_week_7()
        pilot = {"meta": {"label": "pilot-1"}, "runs": [{"arm": "agent", "calls": 3}, {"arm": "team", "calls": 7}, {"arm": "team", "calls": 9}]}
        runner.save_results(pilot, runner.results_path("pilot-1"))
        code, text = captured(race_team.main, ["--plan", "--pilot", "pilot-1"])
        self.assertEqual(code, 0)
        self.assertIn("team: 8.0 model calls a run, measured on 2 pilot question(s) that are not race tasks", text)
        self.assertNotIn("ESTIMATE", text)
        code, text = captured(race_team.main, ["--plan", "--pilot", "pilot-nope"])
        self.assertEqual((code, "no usable pilot" in text), (1, True))


class ShowTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.folder))
        self.enterContext(mock.patch.object(race_team, "BASE_DIR", self.folder))
        tasks = get_tasks(TWO)
        runs = [fake_record(task, arm, repeat) for repeat in (1, 2) for task in tasks for arm in ("agent", "team")]
        meta = race_team.make_meta("s", tasks, 2, ["agent", "team"], "m", "now")
        meta.update(complete=True)
        runner.save_results({"meta": meta, "runs": runs}, runner.results_path("race-s"))

    def test_show_prints_the_report_without_any_model_call(self):
        with mock.patch.object(race_team.race, "run_one") as racing:
            code, text = captured(race_team.main, ["--show", "s"])
        self.assertEqual(code, 0)
        racing.assert_not_called()
        for needle in ("QUALITY", "SPEED", "TOKENS", "COST", "CAPS", "no price stated"):
            self.assertIn(needle, text)

    def test_the_prices_you_state_add_dollars_labelled_as_an_assumption_with_their_source(self):
        code, text = captured(race_team.main, ["--show", "s", "--price-in", "0.10", "--price-out", "0.40", "--price-source", "the price page, 2026-10-12"])
        self.assertEqual(code, 0)
        for needle in ("per passing run", "assumption", "source: the price page, 2026-10-12"):
            self.assertIn(needle, text)

    def test_prices_need_both_numbers_and_their_source_and_a_source_alone_means_nothing(self):
        for argv, needle in ((["--price-in", "1"], "state both"), (["--price-in", "1", "--price-out", "2"], "--price-source"),
                             (["--price-source", "x"], "goes with")):
            with self.subTest(argv=argv):
                code, text = captured(race_team.main, ["--show", "s", *argv])
                self.assertEqual((code, needle in text), (1, True))

    def test_a_price_setting_in_the_environment_never_puts_dollars_into_a_report(self):
        with mock.patch.object(race_team.settings, "price_input_per_million", 5.0), \
                mock.patch.object(race_team.settings, "price_output_per_million", 9.0):
            code, text = captured(race_team.main, ["--show", "s"])
        self.assertEqual(code, 0)
        self.assertIn("no price stated", text)
        self.assertNotIn("per passing run", text)

    def test_show_with_rescore_prints_both_views_and_what_changed(self):
        code, text = captured(race_team.main, ["--show", "s", "--rescore"])
        self.assertEqual(code, 0)
        for needle in ("AS RACED", "RE-SCORED", "run(s) changed result"):
            self.assertIn(needle, text)

    def test_save_writes_the_report_and_the_command_that_prints_it_again(self):
        code, _text = captured(race_team.main, ["--show", "s", "--price-in", "1", "--price-out", "2", "--price-source", "a source", "--save"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.folder, "docs", "week10", "race-results.md"), encoding="utf-8") as handle:
            written = handle.read()
        self.assertIn('python scripts/race_team.py --show s --price-in 1.0 --price-out 2.0 --price-source "a source" --save', written)
        self.assertIn("QUALITY", written)
        for glyph in ("\u2014", "\u2013"):                                                       # no dashes the project does not use
            self.assertNotIn(glyph, written)

    def test_an_unknown_saved_race_is_a_clear_error(self):
        code, text = captured(race_team.main, ["--show", "nope"])
        self.assertEqual((code, "No saved run" in text), (1, True))


if __name__ == "__main__":
    unittest.main()
