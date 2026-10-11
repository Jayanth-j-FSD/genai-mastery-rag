"""Week 10: a partial, oversized or empty race must never produce a verdict on the pre-registered prediction (evals/team_prediction.py)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from evals import runner, team_prediction as prediction
from test_team_prediction import TASKS, held, race, run

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import check_team_prediction          # noqa: E402

ABSOLUTE = ("P1", "P4", "P5", "P6", "P9")          # the rows that count runs or tasks: registered for 9 tasks x 3 repeats


def stopped_race(repeats=2, **changes):
    """A race the quota cut short: only the first `repeats` repeats exist and the file says it is not complete."""
    saved = race(**changes)
    saved["runs"] = [row for row in saved["runs"] if row["repeat"] <= repeats]
    saved["meta"].update(complete=False, stopped_because="the daily quota was used up")
    return saved


def text_of(saved, label="t"):
    rows, failed, dropped = prediction.check_prediction(saved)
    return "\n".join(prediction.format_prediction(rows, failed, dropped, label))


def statuses(rows):
    return {row["id"]: row["status"] for row in rows}


class PartialRaceTests(unittest.TestCase):
    def test_a_race_the_quota_cut_short_gets_a_partial_banner_that_says_how_many_of_the_registered_units_were_read(self):
        text = text_of(stopped_race())
        self.assertIn("PARTIAL", text)
        self.assertIn("read on 18 of 27 registered units", text)
        self.assertIn("the daily quota was used up", text)

    def test_the_rows_that_count_runs_or_tasks_are_marked_not_decidable_and_the_ratio_rows_still_report(self):
        rows, _failed, _dropped = prediction.check_prediction(stopped_race())
        for ident, status in statuses(rows).items():
            self.assertEqual(status, "partial" if ident in ABSOLUTE else "held", ident)
        self.assertTrue(all(row["held"] is None for row in rows if row["id"] in ABSOLUTE))
        self.assertIn("not decidable on a partial race", text_of(stopped_race()))

    def test_a_partial_race_never_prints_a_verdict_whatever_the_numbers_say(self):
        # an example: 13 passes against 18 on two repeats would need 13 here but 22 over the registered 27 units
        lost = lambda t, r: {"success": False} if (t, r) in {("t7-conflict", 1), ("t7-conflict", 2), ("t7-two-documents", 1),    # noqa: E731
                                                              ("t7-two-documents", 2), ("t7-cloud-two-sections", 1)} else {}
        rows, failed, _dropped = prediction.check_prediction(stopped_race(team=lost))
        self.assertIsNone(failed)
        self.assertEqual(statuses(rows)["P6"], "partial")
        text = text_of(stopped_race(team=lost))
        self.assertNotIn("FAILED", text)
        self.assertNotIn("did not fail", text)
        self.assertIn("No verdict on the prediction as a whole", text)

    def test_a_ratio_outside_its_band_on_a_partial_race_is_shown_but_gives_no_failed_verdict(self):
        saved = stopped_race(team=lambda t, r: {"tokens": (4000, 200)})                         # 10 times the agent's tokens: P2 is NOT HELD
        rows, failed, _dropped = prediction.check_prediction(saved)
        self.assertEqual(statuses(rows)["P2"], "not held")
        self.assertIsNone(failed)
        self.assertNotIn("FAILED", text_of(saved))

    def test_units_that_cover_fewer_tasks_than_the_file_says_are_not_the_registered_design(self):
        runs = []
        for repeat in range(1, 10):                          # 27 usable units over 3 tasks, in a file whose meta still says 9 tasks x 3 repeats
            for task in TASKS[:3]:
                runs += [run(task, "agent", repeat), run(task, "team", repeat, calls=6, tokens=(800, 40), api=6.0, handoffs=2)]
        saved = {"meta": {"label": "t", "arms": ["agent", "team"], "tasks": TASKS, "repeats": 3, "complete": True}, "runs": runs}
        self.assertIn("the usable units cover 3 task(s), not 9", text_of(saved))
        self.assertIsNone(prediction.check_prediction(saved)[1])

    def test_a_race_marked_incomplete_is_partial_even_when_every_unit_happens_to_be_there(self):
        saved = race()
        saved["meta"]["complete"] = False
        rows, failed, _dropped = prediction.check_prediction(saved)
        self.assertIsNone(failed)
        self.assertEqual(statuses(rows)["P6"], "partial")

    def test_a_race_with_more_than_the_registered_units_is_not_read_either(self):
        bigger = race()
        bigger["runs"] += [dict(row, repeat=4) for row in bigger["runs"] if row["repeat"] == 1]
        text = text_of(bigger)
        self.assertIn("read on 36 of 27 registered units", text)
        self.assertIsNone(prediction.check_prediction(bigger)[1])

    def test_one_unit_dropped_for_a_provider_error_leaves_26_units_and_so_no_verdict(self):
        hit = lambda t, r: {"error": True, "success": False} if (t, r) == ("t7-conflict", 1) else {}    # noqa: E731
        rows, failed, dropped = prediction.check_prediction(race(agent=hit))
        self.assertEqual((dropped["kept"], dropped["dropped_for_provider"]), (26, 1))
        self.assertIsNone(failed)
        self.assertEqual(statuses(rows)["P6"], "partial")
        self.assertIn("read on 26 of 27 registered units", text_of(race(agent=hit)))

    def test_a_race_of_the_wrong_number_of_tasks_is_not_the_registered_design_even_with_27_units(self):
        runs = []
        for repeat in range(1, 10):                          # 3 tasks x 9 repeats is 27 units too
            for task in TASKS[:3]:
                runs += [run(task, "agent", repeat), run(task, "team", repeat, calls=6, tokens=(800, 40), api=6.0, handoffs=2)]
        three_tasks = {"meta": {"label": "t", "arms": ["agent", "team"], "tasks": TASKS[:3], "repeats": 9, "complete": True}, "runs": runs}
        text = text_of(three_tasks)
        self.assertIn("PARTIAL", text)
        self.assertIn("3 tasks in the plan, not 9", text)
        self.assertIn("9 repeats, not 3", text)
        self.assertIsNone(prediction.check_prediction(three_tasks)[1])

    def test_a_race_that_is_exactly_the_registered_size_has_no_banner_and_still_gives_its_verdict(self):
        rows, failed, dropped = prediction.check_prediction(race())
        text = text_of(race())
        self.assertNotIn("PARTIAL", text)
        self.assertNotIn("registered units", text)
        self.assertIs(failed, False)
        self.assertTrue(all(row["status"] == "held" for row in rows))
        self.assertEqual(dropped["registered"], {"units": 27, "read": 27, "problems": []})
        self.assertIn("did not fail", text)
        self.assertIs(prediction.check_prediction(race(team=lambda t, r: {"calls": 13}))[1], True)       # a failure is still a verdict


class NothingToCheckTests(unittest.TestCase):
    def empty(self, arms=("agent", "team"), runs=()):
        return {"meta": {"label": "t", "arms": list(arms), "tasks": TASKS, "repeats": 3, "complete": False}, "runs": list(runs)}

    def assertCannotCheck(self, saved):
        self.assertEqual(prediction.check_prediction(saved), ([], False, None))
        text = text_of(saved)
        self.assertIn("Cannot check", text)
        for word in ("FAILED", "did not fail", "held"):
            self.assertNotIn(word, text)

    def test_both_arms_listed_but_no_run_at_all_cannot_be_checked(self):
        self.assertCannotCheck(self.empty())

    def test_an_arm_that_is_listed_but_has_no_run_cannot_be_checked(self):
        full = race()
        self.assertCannotCheck(self.empty(runs=[row for row in full["runs"] if row["approach"] == "agent"]))
        self.assertCannotCheck(self.empty(runs=[row for row in full["runs"] if row["approach"] == "team"]))

    def test_a_race_where_every_unit_ended_on_a_provider_error_has_no_usable_unit_and_cannot_be_checked(self):
        both = lambda t, r: {"error": True, "success": False}      # noqa: E731
        saved = race(agent=both, team=both)
        self.assertEqual(prediction.check_prediction(saved)[2], None)
        self.assertCannotCheck(saved)

    def test_the_explanation_says_why_there_is_nothing_to_check(self):
        both = lambda t, r: {"error": True, "success": False}      # noqa: E731
        self.assertIn("0 of 27 units", prediction.why_not_checkable(race(agent=both, team=both)))
        self.assertIn("no team arm", prediction.why_not_checkable({"meta": {"arms": ["agent"]}, "runs": []}))


class NoDataRowTests(unittest.TestCase):
    def test_a_ratio_whose_denominator_is_zero_says_no_data_and_is_neither_held_nor_not_held(self):
        rows, failed, _dropped = prediction.check_prediction(race(agent=lambda t, r: {"calls": 0, "opening": 0}))
        self.assertEqual((statuses(rows)["P1"], statuses(rows)["P8"]), ("no data", "no data"))
        self.assertIsNone(held(rows)["P1"])
        self.assertIsNone(failed)                            # P1 decides the verdict and has no number

    def test_rows_about_the_teams_hand_offs_say_no_data_when_no_team_run_carries_any(self):
        stripped = race()
        for row in stripped["runs"]:
            row.pop("team", None)
        rows, _failed, _dropped = prediction.check_prediction(stripped)
        self.assertEqual((statuses(rows)["P4"], statuses(rows)["P7"]), ("no data", "no data"))

    def test_the_unanswerable_task_row_says_no_data_when_the_team_never_ran_it(self):
        saved = stopped_race()
        saved["runs"] = [row for row in saved["runs"] if row["task_id"] != "t7-unanswerable"]
        rows, _failed, _dropped = prediction.check_prediction(saved)
        self.assertEqual(statuses(rows)["P10"], "no data")

    def test_a_decided_failure_still_shows_when_another_deciding_row_has_no_data(self):
        saved = race(agent=lambda t, r: {"calls": 0}, team=lambda t, r: {"success": False})
        rows, failed, _dropped = prediction.check_prediction(saved)
        self.assertEqual(statuses(rows)["P1"], "no data")
        self.assertEqual(statuses(rows)["P6"], "not held")
        self.assertIs(failed, True)


class CheckerScriptPartialTests(unittest.TestCase):
    def run_script(self, saved):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", folder))
        runner.save_results(saved, runner.results_path("race-p"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_team_prediction.main(["p"])
        return code, out.getvalue()

    def test_a_partial_race_exits_non_zero_and_prints_no_verdict(self):
        code, text = self.run_script(stopped_race())
        self.assertNotEqual(code, 0)
        self.assertIn("PARTIAL", text)
        self.assertNotIn("did not fail", text)
        self.assertNotIn("FAILED", text)

    def test_a_race_with_both_arms_listed_but_nothing_usable_exits_non_zero_and_says_why(self):
        code, text = self.run_script({"meta": {"label": "t", "arms": ["agent", "team"], "tasks": TASKS, "repeats": 3, "complete": False}, "runs": []})
        self.assertNotEqual(code, 0)
        self.assertIn("Cannot check", text)
        self.assertIn("0 of 0 units", text)

    def test_a_race_of_the_registered_size_still_exits_zero(self):
        code, text = self.run_script(race())
        self.assertEqual(code, 0)
        self.assertIn("did not fail", text)


if __name__ == "__main__":
    unittest.main()
