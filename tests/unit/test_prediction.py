"""The pre-registered budget prediction as arithmetic over saved runs (synthetic runs, no model)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from evals import prediction, runner
from evals.agent_tasks import get_tasks

TASKS = get_tasks(None, include_probes=True)
TASK_ID = "t7-single-lookup"                  # needs one search and nothing else
GOOD_ANSWER = "16 weeks [source: Acme-Leave-Policy-2026.md]"
SEARCH_RESULT = "[1] [source: Acme-Leave-Policy-2026.md] Eligible employees may take 16 weeks of paid parental leave."


def run(repeat, searches=1, tokens=1000, success=True, stop="final", answer=GOOD_ANSWER):
    calls = [{"name": "search_policies", "arguments": json.dumps({"query": f"q{i}"}), "observation": SEARCH_RESULT,
              "ok": True, "blocked": False} for i in range(searches)]
    return {"task_id": TASK_ID, "approach": "agent", "repeat": repeat, "success": success, "stop_reason": stop,
            "answer": answer, "steps": [{"n": n, "tool_calls": [c]} for n, c in enumerate(calls, 1)],
            "prompt_tokens": tokens, "completion_tokens": 0, "llm_calls": searches + 1, "api_seconds": 1.0}


def check(before, after, noise=None):
    rows, failed, pairs = prediction.check_budget_prediction(before, after, TASKS, noise)
    return {row["number"]: row["held"] for row in rows}, failed, pairs


def tokens_line(before, after, noise=None):
    rows, _, _ = prediction.check_budget_prediction(before, after, TASKS, noise)
    return next(row["measured"] for row in rows if row["number"] == 3)


class PredictionTests(unittest.TestCase):
    def test_a_fix_that_does_what_was_predicted_holds_on_every_judged_row_and_does_not_fail(self):
        before = [run(n, searches=4, tokens=2000) for n in (1, 2, 3)]                  # over-calling, expensive
        after = [run(n, searches=3, tokens=1900) for n in (1, 2, 3)]                   # capped, 5% cheaper
        held, failed, pairs = check(before, after)
        self.assertEqual((held, failed, pairs), ({1: True, 2: True, 3: None, 4: True, 5: True, 6: None}, False, 3))

    def test_a_change_in_tokens_is_reported_and_never_passes_or_fails_the_fix(self):
        before = [run(n, 4, 2000) for n in (1, 2)]
        for tokens in (1990, 1000, 2500):                                              # a tiny saving, a huge one, a rise
            with self.subTest(tokens=tokens):
                held, failed, _ = check(before, [run(n, 3, tokens) for n in (1, 2)])
                self.assertIsNone(held[3])
                self.assertFalse(failed)

    def test_the_token_change_is_read_against_the_noise_floor_of_two_identical_runs(self):
        before = [run(n, 4, 2000) for n in (1, 2)]
        noisy = [run(n, 4, 2200) for n in (1, 2)]                                      # an identical run that came out 10% dearer
        inside = tokens_line(before, [run(n, 3, 1900) for n in (1, 2)], noisy)           # a 5% saving
        self.assertIn("not distinguishable from noise", inside)
        self.assertIn("differ by 10.0%", inside)
        self.assertIn("larger than the noise floor", tokens_line(before, [run(n, 3, 1000) for n in (1, 2)], noisy))
        self.assertIn("larger than the noise floor", tokens_line(before, [run(n, 3, 1990) for n in (1, 2)], before))    # zero noise
        self.assertIn("no A/A run given", tokens_line(before, [run(n, 3, 1900) for n in (1, 2)]))

    def test_the_failure_rule_boundaries_are_exactly_two_runs(self):
        before = [run(n) for n in (1, 2, 3, 4)]
        lost_two = [run(1), run(2), run(3, success=False), run(4, success=False)]
        lost_three = [run(1), run(2, success=False), run(3, success=False), run(4, success=False)]
        self.assertFalse(check(before, lost_two)[1])
        self.assertTrue(check(before, lost_three)[1])
        unfinished_two = [run(1), run(2), run(3, stop="max_steps"), run(4, stop="max_steps")]
        unfinished_three = [run(1), run(2, stop="max_steps"), run(3, stop="max_steps"), run(4, stop="max_steps")]
        self.assertFalse(check(before, unfinished_two)[1])
        self.assertTrue(check(before, unfinished_three)[1])

    def test_the_noise_floor_uses_only_the_pairs_the_identical_runs_both_completed(self):
        before = [run(1, 4, 2000), run(2, 4, 4000)]
        partial_noise = [run(1, 4, 2000)]                                              # the second repeat never ran
        self.assertIn("differ by 0.0%", tokens_line(before, [run(n, 3, 1900) for n in (1, 2)], partial_noise))

    def test_more_than_two_fewer_right_answers_fails_the_fix(self):
        before = [run(n, success=True) for n in (1, 2, 3, 4)]
        self.assertTrue(check(before, [run(1), run(2), run(3, success=False), run(4, success=False)])[0][2])      # lost 2: allowed
        held, failed, _ = check(before, [run(1), run(2, success=False), run(3, success=False), run(4, success=False)])
        self.assertFalse(held[2])
        self.assertTrue(failed)

    def test_more_than_two_finished_runs_now_ending_without_an_answer_fails_the_fix(self):
        before = [run(n) for n in (1, 2, 3, 4)]
        after = [run(n, stop="max_steps") for n in (1, 2, 3)] + [run(4)]
        held, failed, _ = check(before, after)
        self.assertFalse(held[4])
        self.assertTrue(failed)

    def test_a_run_that_was_already_unfinished_is_not_newly_unfinished(self):
        before = [run(n, stop="max_steps") for n in (1, 2, 3)]
        held, _, _ = check(before, [run(n, stop="max_steps") for n in (1, 2, 3)])
        self.assertTrue(held[4])

    def test_a_change_in_unverified_citations_is_reported_but_does_not_by_itself_fail_the_fix(self):
        before = [run(n, 4, 2000) for n in (1, 2)]
        after = [run(1, 3, 1900), run(2, 3, 1900, answer="16 weeks [source: Ghost.md]")]
        held, failed, _ = check(before, after)
        self.assertFalse(held[5])
        self.assertFalse(failed)

    def test_only_the_pairs_both_runs_completed_are_checked(self):
        _, _, pairs = check([run(n) for n in (1, 2, 3)], [run(2), run(3), run(4)])
        self.assertEqual(pairs, 2)

    def test_runs_with_nothing_in_common_cannot_be_checked(self):
        rows, failed, pairs = prediction.check_budget_prediction([run(1)], [run(2)], TASKS)
        self.assertEqual((rows, failed, pairs), ([], False, 0))
        self.assertIn("cannot be checked", prediction.format_prediction(rows, failed, pairs)[0])

    def test_the_report_names_each_prediction_and_the_verdict(self):
        before = [run(n, 4, 2000) for n in (1, 2, 3, 4)]
        after = [run(1, 3, 1990)] + [run(n, 3, 1990, success=False) for n in (2, 3, 4)]       # three right answers lost
        rows, failed, pairs = prediction.check_budget_prediction(before, after, TASKS, before)
        text = "\n".join(prediction.format_prediction(rows, failed, pairs, "before-final", "after-final"))
        for needle in ("4 (task, repeat) pairs", "'before-final'", "'after-final'", "over-calling goes to 0", "HELD", "DID NOT HOLD",
                       "REPORTED, NOT JUDGED", "noise floor", "withdrawn", "THE FIX FAILED."):
            self.assertIn(needle, text)


class SecondReviewPredictionTests(unittest.TestCase):
    def test_the_effect_and_the_noise_are_read_on_the_pairs_all_three_runs_completed(self):
        before = [run(1, 4, 2000), run(2, 4, 4000)]
        after = [run(1, 3, 1000), run(2, 3, 2000)]
        noise = [run(2, 4, 4400)]                              # the first repeat of the noise run never ran
        text = tokens_line(before, after, noise)
        self.assertIn("read on the 1 pair(s) all three runs completed", text)
        self.assertIn("4000 before, 2000 after", text)         # the effect uses repeat 2 only, the pair the noise run has
        self.assertIn("differ by 10.0%", text)
        self.assertIn("larger than the noise floor", text)

    def test_with_no_pair_all_three_runs_completed_the_noise_floor_is_said_to_be_unknown(self):
        text = tokens_line([run(1, 4, 2000)], [run(1, 3, 1900)], [run(2, 4, 2100)])
        self.assertIn("no pair that all three runs completed", text)

    def test_the_setup_check_says_when_the_runs_do_not_differ_only_in_the_cap(self):
        def meta(cap, model="m", **extra):
            return dict({"models": {"agent": model}, "agent_max_calls_per_tool": cap, "complete": True, "retrieval_mode": "dense",
                         "limits": {"max_steps": 8}, "tasks": ["a"], "top_k_workflow": 4}, **extra)      # the fields every real run records
        self.assertEqual(prediction.check_setup(meta(0), meta(3), meta(0)), [])
        self.assertIn("different models", "; ".join(prediction.check_setup(meta(0), meta(3, "other"), meta(0))))
        self.assertIn("tests nothing", "; ".join(prediction.check_setup(meta(0), meta(0), meta(0))))
        self.assertIn("should have no cap", "; ".join(prediction.check_setup(meta(0), meta(3), meta(2))))
        self.assertIn("not recorded", "; ".join(prediction.check_setup({"models": {"agent": "m"}}, meta(3))))
        self.assertIn("defences on", "; ".join(prediction.check_setup(meta(0), meta(3, defense=True))))
        partial = prediction.check_setup(meta(0), meta(3, complete=False, stopped_because="quota"))
        self.assertIn("partial (quota)", "; ".join(partial))

    def test_a_pair_in_which_a_run_ended_on_a_provider_error_is_left_out_of_the_verdict_and_counted(self):
        before = [run(n) for n in (1, 2, 3, 4)]
        after = [run(1)] + [run(n, success=False, stop="error") for n in (2, 3, 4)]          # three 503s, not three wrong answers
        rows, failed, pairs = prediction.check_budget_prediction(before, after, TASKS)
        self.assertEqual((failed, pairs), (False, 1))
        measured = {row["number"]: row["measured"] for row in rows}
        self.assertIn("3 pair(s) left out: a run ended on a provider error", measured[2])
        self.assertIn("3 pair(s) left out: a run ended on a provider error", measured[4])
        noisy_before = [run(1, success=False, stop="error"), run(2), run(3), run(4)]          # an error on the 'before' side leaves its pair out too
        self.assertEqual(prediction.check_budget_prediction(noisy_before, [run(n) for n in (1, 2, 3, 4)], TASKS)[2], 3)

    def test_the_noise_is_read_on_the_pairs_all_three_runs_completed_not_on_every_pair_the_noise_run_shares_with_before(self):
        before = [run(1, 4, 1000), run(2, 4, 2000)]
        after = [run(2, 3, 1900)]                                                              # only repeat 2 has all three runs
        noise = [run(1, 4, 1000), run(2, 4, 2200)]                                             # 0% apart on repeat 1, 10% on repeat 2
        text = tokens_line(before, after, noise)
        self.assertIn("differ by 10.0%", text)                                                # on repeat 2 alone, not the 6.7% of both repeats
        self.assertIn("1 pair(s) all three runs completed", text)

    def test_the_setup_check_also_compares_the_other_settings_and_the_task_list(self):
        def meta(**extra):
            return dict({"models": {"agent": "m"}, "agent_max_calls_per_tool": 0, "complete": True, "retrieval_mode": "dense",
                         "tasks": ["a", "b"], "limits": {"max_steps": 8}, "top_k_workflow": 4, "overrides": {}}, **extra)
        after = meta(agent_max_calls_per_tool=3)
        self.assertEqual(prediction.check_setup(meta(), after, meta()), [])
        self.assertIn("differ in retrieval_mode", "; ".join(prediction.check_setup(meta(), dict(after, retrieval_mode="hybrid"))))
        self.assertIn("differ in tasks", "; ".join(prediction.check_setup(meta(), dict(after, tasks=["a"]))))
        other = prediction.check_setup(meta(overrides={"top_k": 3}), dict(after, overrides={"agent_max_calls_per_tool": 3, "top_k": 4}))
        self.assertIn("other settings differently", "; ".join(other))
        same = prediction.check_setup(meta(overrides={"top_k": 3}), dict(after, overrides={"agent_max_calls_per_tool": 3, "top_k": 3}))
        self.assertEqual(same, [])

    def test_the_report_leads_with_the_setup_warnings_when_there_are_any(self):
        rows, failed, pairs = prediction.check_budget_prediction([run(1)], [run(1)], TASKS)
        text = "\n".join(prediction.format_prediction(rows, failed, pairs, warnings=["the runs used different models"]))
        self.assertIn("SETUP WARNINGS", text)
        self.assertLess(text.index("SETUP WARNINGS"), text.index("1. over-calling goes to 0"))


class ThirdCheckPredictionTests(unittest.TestCase):
    def test_a_provider_error_in_the_noise_run_does_not_move_the_noise_floor(self):
        before = [run(n, 4, 1000) for n in (1, 2, 3, 4)]
        after = [run(n, 3, 800) for n in (1, 2, 3, 4)]                                                 # a 20% saving
        noise = [run(1, 4, 0, success=False, stop="error")] + [run(n, 4, 1000) for n in (2, 3, 4)]     # one 503 in the A/A run
        text = tokens_line(before, after, noise)
        self.assertIn("differ by 0.0%", text)                      # the three pairs that completed are identical
        self.assertIn("read on the 3 pair(s)", text)
        self.assertIn("larger than the noise floor", text)

    def test_when_every_pair_is_left_out_the_report_says_why_and_still_shows_the_setup_warnings(self):
        before = [run(n) for n in (1, 2)]
        after = [run(n, success=False, stop="error") for n in (1, 2)]
        rows, failed, pairs = prediction.check_budget_prediction(before, after, TASKS)
        self.assertEqual((rows, failed, pairs), ([], False, 0))
        self.assertEqual(prediction.left_out_pairs(before, after, TASKS), 2)
        text = "\n".join(prediction.format_prediction(rows, failed, pairs, warnings=["the 'after' run is partial (outage)"], left_out=2))
        self.assertIn("cannot be checked", text)
        self.assertIn("2 shared pair(s) were left out because a run ended on a provider error", text)
        self.assertIn("partial (outage)", text)

    def test_the_setup_check_compares_limits_and_the_workflow_top_k_and_names_a_field_a_run_did_not_record(self):
        def meta(**extra):
            return dict({"models": {"agent": "m"}, "agent_max_calls_per_tool": 0, "complete": True, "retrieval_mode": "dense",
                         "tasks": ["a"], "limits": {"max_steps": 8}, "top_k_workflow": 4, "overrides": {}}, **extra)
        after = meta(agent_max_calls_per_tool=3)
        self.assertEqual(prediction.check_setup(meta(), after, meta()), [])
        self.assertIn("differ in limits", "; ".join(prediction.check_setup(meta(), dict(after, limits={"max_steps": 4}))))
        self.assertIn("differ in top_k_workflow", "; ".join(prediction.check_setup(meta(), dict(after, top_k_workflow=3))))
        older = {key: value for key, value in after.items() if key != "limits"}
        self.assertIn("limits was not recorded for the after run(s)", "; ".join(prediction.check_setup(meta(), older)))


class FourthLookPredictionTests(unittest.TestCase):
    def test_a_field_recorded_as_none_is_still_a_recorded_value_that_can_differ(self):
        def meta(**extra):
            return dict({"models": {"agent": "m"}, "agent_max_calls_per_tool": 0, "complete": True, "retrieval_mode": "dense",
                         "tasks": ["a"], "limits": {"max_steps": 8}, "top_k_workflow": 4, "overrides": {}}, **extra)
        said = "; ".join(prediction.check_setup(meta(), dict(meta(agent_max_calls_per_tool=3), limits=None)))
        self.assertIn("differ in limits", said)
        self.assertNotIn("was not recorded", said)

    def test_a_report_with_no_pair_left_out_does_not_mention_any(self):
        self.assertNotIn("left out", "\n".join(prediction.format_prediction([], False, 0)))


class CheckPredictionScriptTests(unittest.TestCase):
    def call(self, *args):
        sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
        import check_prediction
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_prediction.main(list(args))
        return code, out.getvalue()

    def test_saved_runs_are_checked_with_an_optional_noise_run_and_a_missing_one_is_an_error(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.object(runner, "RESULTS_DIR", tmp):
            for label, runs in (("a", [run(n, 4, 2000) for n in (1, 2)]), ("b", [run(n, 3, 1900) for n in (1, 2)]),
                                ("c", [run(n, 4, 2100) for n in (1, 2)])):
                runner.save_results({"meta": {"label": label, "complete": True}, "runs": runs}, runner.results_path("trajectories-" + label))
            code, out = self.call("a", "b")
            self.assertEqual(code, 0)
            self.assertIn("SETUP WARNINGS", out)                    # these synthetic files record no cap
            self.assertIn("Pre-registered prediction for the call budget", out)
            self.assertIn("the fix did not fail", out)
            self.assertIn("no A/A run given", out)
            code, out = self.call("a", "b", "--noise", "c")
            self.assertEqual(code, 0)
            self.assertIn("not distinguishable from noise", out)
            for args in (("a", "missing"), ("a", "b", "--noise", "missing")):
                code, out = self.call(*args)
                self.assertEqual(code, 1)
                self.assertIn("Error", out)


if __name__ == "__main__":
    unittest.main()
