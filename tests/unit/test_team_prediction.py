"""Week 10: the pre-registered prediction as arithmetic over a saved race (evals/team_prediction.py, scripts/check_team_prediction.py)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from evals import runner, team_prediction as prediction, team_report

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import check_team_prediction          # noqa: E402

TASKS = ["t7-single-lookup", "t7-carry-forward-sum", "t7-notice-end-date", "t7-leave-end-date", "t7-remote-eligibility",
         "t7-two-documents", "t7-conflict", "t7-cloud-two-sections", "t7-unanswerable"]
CALCULATION = {"t7-carry-forward-sum", "t7-notice-end-date", "t7-leave-end-date"}
IDK = "I don't know based on the provided documents."


def steps_for(arm, opening, handoffs=1):
    if arm == "agent":
        return [{"n": 1, "local_n": 1, "kind": "final", "content": "", "tool_calls": [], "seconds": 0.1, "tokens": {"prompt": opening, "completion": 5},
                 "agent": None, "handoff": None}]
    rows = [{"n": 1, "local_n": 1, "kind": "tool", "content": "", "tool_calls": [], "seconds": 0.1, "tokens": {"prompt": opening, "completion": 5},
             "agent": "manager", "handoff": None}]
    rows += [{"n": 2 + i, "local_n": 1, "kind": "final", "content": "", "tool_calls": [], "seconds": 0.1, "tokens": {"prompt": opening, "completion": 5},
              "agent": "researcher", "handoff": 1 + i} for i in range(handoffs)]
    return rows


def run(task, arm, repeat, success=True, calls=3, tokens=(400, 20), api=3.0, stop="final", answer="an answer", opening=100, handoffs=1, calc=None,
        overlap=False, error=False):
    row = {"task_id": task, "approach": arm, "repeat": repeat, "success": success, "finished": stop == "final", "stop_reason": "error" if error else stop,
           "llm_calls": calls, "prompt_tokens": tokens[0], "completion_tokens": tokens[1], "api_seconds": api, "elapsed_seconds": api * 3,
           "wait_seconds": 0.0, "answer": answer, "steps": steps_for(arm, opening, handoffs)}
    if arm == "team":
        used = (task in CALCULATION) if calc is None else calc
        agents = {name: {"calls": 1, "prompt_tokens": 0, "completion_tokens": 0, "api_seconds": 0.0, "handoffs": 0} for name in ("manager", "researcher", "calculator")}
        agents["calculator"]["handoffs"] = 1 if used else 0
        listing = [{"handoff": 1, "agent": "researcher", "state": "finished", "stop_reason": "final", "after_manager_step": 1, "calls": 2, "api_seconds": 1.0},
                   {"handoff": 2, "agent": "calculator" if used else "researcher", "state": "finished", "stop_reason": "final",
                    "after_manager_step": 1 if overlap else 2, "calls": 2, "api_seconds": 1.0}]
        row["team"] = {"per_agent": agents, "handoffs": listing, "call_log": [], "warnings": [], "errors": []}
    return row


def race(**changes):
    """A race in which every prediction holds, then whatever the keyword arguments change: team=..., agent=... as functions of the task."""
    runs = []
    for repeat in (1, 2, 3):
        for task in TASKS:
            answer = IDK if task == "t7-unanswerable" else "an answer"
            agent = {"answer": answer, **changes.get("agent", lambda t, r: {})(task, repeat)}
            crew = {"calls": 6, "tokens": (800, 40), "api": 6.0, "opening": 100, "handoffs": 2, "answer": answer,
                    **changes.get("team", lambda t, r: {})(task, repeat)}
            runs.append(run(task, "agent", repeat, **agent))
            runs.append(run(task, "team", repeat, **crew))
    return {"meta": {"label": "t", "arms": ["agent", "team"], "tasks": TASKS, "repeats": 3, "complete": True}, "runs": runs}


def held(rows):
    return {row["id"]: row["held"] for row in rows}


class PredictionTests(unittest.TestCase):
    def test_a_race_that_matches_every_sentence_holds_them_all_and_the_prediction_does_not_fail(self):
        rows, failed, dropped = prediction.check_prediction(race())
        self.assertEqual([row["id"] for row in rows], [f"P{n}" for n in range(1, 11)])
        self.assertTrue(all(row["held"] for row in rows), [row for row in rows if not row["held"]])
        self.assertFalse(failed)
        self.assertEqual((dropped["units"], dropped["kept"]), (27, 27))

    def test_p1_p2_p3_fail_when_the_team_is_outside_its_band_on_calls_tokens_or_model_seconds(self):
        for key, changes, ident in (("calls", {"calls": 13}, "P1"), ("tokens", {"tokens": (3000, 200)}, "P2"), ("seconds", {"api": 20.0}, "P3")):
            with self.subTest(band=key):
                rows, failed, _dropped = prediction.check_prediction(race(team=lambda t, r, changes=changes: changes))
                self.assertFalse(held(rows)[ident])
                self.assertTrue(failed)

    def test_p1_wants_more_calls_on_at_least_seven_tasks_not_just_a_good_ratio(self):
        agent = lambda t, r: {"calls": 3}                                     # noqa: E731
        six = lambda t, r: {"calls": 2} if t in TASKS[:3] else {}             # noqa: E731  the team makes 6 calls on six tasks, 2 on three: a ratio of 1.56
        seven = lambda t, r: {"calls": 2} if t in TASKS[:2] else {}           # noqa: E731
        rows, _failed, _dropped = prediction.check_prediction(race(team=six, agent=agent))
        p1 = next(row for row in rows if row["id"] == "P1")
        self.assertFalse(p1["held"])
        self.assertIn("1.56x", p1["evidence"])                                # the ratio alone is inside the band
        self.assertIn("more calls on 6 of 9 tasks", p1["evidence"])
        rows, _failed, _dropped = prediction.check_prediction(race(team=seven, agent=agent))
        self.assertTrue(held(rows)["P1"])

    def test_p4_wants_the_calculator_on_the_calculation_tasks_and_not_much_elsewhere(self):
        rows, _failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"calc": False}))
        self.assertFalse(held(rows)["P4"])
        rows, _failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"calc": True}))
        self.assertFalse(held(rows)["P4"])                                   # used everywhere: 18 other runs

    def test_p5_p6_fail_when_the_team_passes_clearly_fewer_runs(self):
        rows, failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"success": False} if t in CALCULATION else {}))
        self.assertFalse(held(rows)["P5"])
        self.assertFalse(held(rows)["P6"])                                   # 9 fewer passes
        self.assertTrue(failed)
        rows, failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"success": False} if (t, r) == ("t7-carry-forward-sum", 1) else {}))
        self.assertTrue(held(rows)["P5"] and held(rows)["P6"])               # one fewer is inside both margins
        self.assertFalse(failed)

    def test_p7_p8_p9_p10_report_what_they_say(self):
        rows, _failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"overlap": True}))
        self.assertFalse(held(rows)["P7"])
        rows, _failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"handoffs": 0, "opening": 100}))
        self.assertFalse(held(rows)["P8"])                                   # only the manager opens a conversation: opening equals the agent's
        rows, _failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"stop": "max_steps", "success": False} if t in TASKS[:2] else {}))
        self.assertFalse(held(rows)["P9"])
        rows, _failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"answer": "It is 10%."} if t == "t7-unanswerable" else {}))
        self.assertFalse(held(rows)["P10"])
        rows, _failed, _dropped = prediction.check_prediction(race(team=lambda t, r: {"calls": 14} if t == "t7-unanswerable" else {}))
        self.assertFalse(held(rows)["P10"])

    def test_a_unit_where_a_run_ended_on_a_provider_error_is_left_out_and_counted(self):
        rows, _failed, dropped = prediction.check_prediction(race(agent=lambda t, r: {"error": True, "success": False} if (t, r) == ("t7-conflict", 1) else {}))
        self.assertEqual((dropped["units"], dropped["kept"], dropped["dropped_for_provider"]), (27, 26, 1))
        self.assertTrue(all(row["status"] in ("held", "partial") for row in rows))        # 26 units is not the registered 27: the count rows wait

    def test_a_race_without_both_arms_cannot_be_checked(self):
        rows, failed, dropped = prediction.check_prediction({"meta": {"arms": ["agent"]}, "runs": []})
        self.assertEqual((rows, failed, dropped), ([], False, None))
        self.assertIn("Cannot check", prediction.format_prediction(rows, failed, dropped, "x")[0])

    def test_the_printout_says_held_or_not_held_and_never_a_verdict_about_which_design_to_use(self):
        rows, failed, dropped = prediction.check_prediction(race(team=lambda t, r: {"calls": 13}))
        text = "\n".join(prediction.format_prediction(rows, failed, dropped, "t"))
        self.assertIn("NOT HELD", text)
        self.assertIn("FAILED", text)
        self.assertIn("exploratory", text)
        for word in ("winner", "better", "worse", "should ship"):
            self.assertNotIn(word, text.lower())

    def test_the_registered_bands_and_margins_have_not_moved(self):
        self.assertEqual(prediction.BANDS, {"calls": (1.3, 3.0), "tokens": (0.8, 2.0), "model_seconds": (1.0, 3.0)})
        self.assertEqual((prediction.MORE_CALLS_ON_AT_LEAST, prediction.PASS_MARGIN_CALCULATION, prediction.PASS_MARGIN_ALL), (7, 2, 5))
        self.assertEqual(prediction.FAILS_IF, ("P1", "P2", "P3", "P6"))
        self.assertEqual(prediction.CALCULATION_TASKS if hasattr(prediction, "CALCULATION_TASKS") else prediction.CALCULATOR_TASKS,
                         ("t7-carry-forward-sum", "t7-notice-end-date", "t7-leave-end-date"))
        for task in prediction.CALCULATOR_TASKS:
            self.assertEqual(team_report.task_shape(task), "dependent")


class CheckerScriptTests(unittest.TestCase):
    def test_it_prints_the_prediction_for_a_saved_race_and_explains_a_missing_one(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", folder))
        runner.save_results(race(), runner.results_path("race-p"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_team_prediction.main(["p"])
        self.assertEqual(code, 0)
        self.assertIn("did not fail", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_team_prediction.main(["nope"])
        self.assertEqual((code, "No saved run" in out.getvalue()), (1, True))


if __name__ == "__main__":
    unittest.main()
