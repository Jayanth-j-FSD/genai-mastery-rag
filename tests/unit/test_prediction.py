"""The pre-registered budget prediction as arithmetic over two saved runs (synthetic runs, no model)."""
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


def check(before, after):
    rows, failed, pairs = prediction.check_budget_prediction(before, after, TASKS)
    return {row["number"]: row["held"] for row in rows}, failed, pairs


class PredictionTests(unittest.TestCase):
    def test_a_fix_that_does_what_was_predicted_holds_on_every_row_and_does_not_fail(self):
        before = [run(n, searches=4, tokens=2000) for n in (1, 2, 3)]                  # over-calling, expensive
        after = [run(n, searches=3, tokens=1900) for n in (1, 2, 3)]                   # capped, 5% cheaper
        held, failed, pairs = check(before, after)
        self.assertEqual((held, failed, pairs), ({1: True, 2: True, 3: True, 4: True, 5: True}, False, 3))

    def test_too_small_a_token_saving_fails_the_fix(self):
        held, failed, _ = check([run(n, 4, 2000) for n in (1, 2)], [run(n, 3, 1990) for n in (1, 2)])
        self.assertFalse(held[3])
        self.assertTrue(failed)

    def test_a_saving_beyond_the_predicted_range_is_not_a_failure(self):
        held, failed, _ = check([run(n, 4, 2000) for n in (1, 2)], [run(n, 3, 1500) for n in (1, 2)])      # 25% cheaper
        self.assertFalse(held[3])                                                                          # outside the range predicted
        self.assertFalse(failed)                                                                           # but not a failure rule

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
        rows, failed, pairs = prediction.check_budget_prediction([run(n, 4, 2000) for n in (1, 2)],
                                                                 [run(n, 3, 1990) for n in (1, 2)], TASKS)
        text = "\n".join(prediction.format_prediction(rows, failed, pairs, "before-final", "after-final"))
        for needle in ("2 (task, repeat) pairs", "'before-final'", "'after-final'", "over-calling goes to 0", "HELD",
                       "DID NOT HOLD", "THE FIX FAILED."):
            self.assertIn(needle, text)


class CheckPredictionScriptTests(unittest.TestCase):
    def call(self, *args):
        sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
        import check_prediction
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_prediction.main(list(args))
        return code, out.getvalue()

    def test_two_saved_runs_are_checked_and_a_missing_one_is_an_error(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.object(runner, "RESULTS_DIR", tmp):
            for label, runs in (("a", [run(n, 4, 2000) for n in (1, 2)]), ("b", [run(n, 3, 1900) for n in (1, 2)])):
                runner.save_results({"meta": {"label": label, "complete": True}, "runs": runs}, runner.results_path("trajectories-" + label))
            code, out = self.call("a", "b")
            self.assertEqual(code, 0)
            self.assertIn("Pre-registered prediction for the call budget", out)
            self.assertIn("the fix did not fail", out)
            code, out = self.call("a", "missing")
            self.assertEqual(code, 1)
            self.assertIn("Error", out)


if __name__ == "__main__":
    unittest.main()
