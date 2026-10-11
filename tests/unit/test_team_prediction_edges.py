"""Week 10: every pre-registered threshold is inclusive exactly as its sentence says, pinned at the edge and one step either side (evals/team_prediction.py)."""
import unittest

import _testkit
from evals import team_prediction as prediction, team_report
from test_team_prediction import CALCULATION, TASKS, race

ALL_CELLS = [(task, repeat) for repeat in (1, 2, 3) for task in TASKS]
CALC_CELLS = [(task, repeat) for task in sorted(CALCULATION) for repeat in (1, 2, 3)]          # the 9 runs of the three calculation tasks
OTHER_CELLS = [(task, repeat) for task in TASKS if task not in CALCULATION for repeat in (1, 2, 3)]        # the other 18


def first(cells, n, **change):
    """A per-run override that applies `change` to the first n of `cells` and to nothing else."""
    chosen = set(cells[:n])
    return lambda task, repeat: dict(change) if (task, repeat) in chosen else {}


def calculator_use(on=9, elsewhere=0):
    """The team asks the calculator in `on` of the 9 calculation-task runs and in `elsewhere` of the other 18."""
    used = set(CALC_CELLS[:on]) | set(OTHER_CELLS[:elsewhere])
    return lambda task, repeat: {"calc": (task, repeat) in used}


def row_of(saved, ident):
    rows, _failed, _dropped = prediction.check_prediction(saved)
    return next(row for row in rows if row["id"] == ident)


class BandEdgeTests(unittest.TestCase):
    """P1 to P3 and P8 compare the value at the two decimals the evidence prints, so what is printed is what was tested."""

    def calls(self, team):
        return race(agent=lambda t, r: {"calls": 1000}, team=lambda t, r: {"calls": team})

    def test_p1_calls_ratio_is_held_at_both_edges_and_not_held_just_outside_them(self):
        for team, expected in ((1300, True), (1290, False), (3000, True), (3010, False)):
            with self.subTest(team_calls=team):
                self.assertIs(row_of(self.calls(team), "P1")["held"], expected)

    def test_a_ratio_that_prints_as_1_30_is_held_and_one_that_prints_as_1_29_is_not(self):
        held_row, failed_row = row_of(self.calls(1299), "P1"), row_of(self.calls(1294), "P1")
        self.assertTrue(held_row["held"])
        self.assertIn("1.30x", held_row["evidence"])
        self.assertFalse(failed_row["held"])
        self.assertIn("1.29x", failed_row["evidence"])

    def test_a_ratio_that_prints_as_3_00_is_held_and_one_that_prints_as_3_01_is_not(self):
        held_row, failed_row = row_of(self.calls(3004), "P1"), row_of(self.calls(3006), "P1")
        self.assertTrue(held_row["held"])
        self.assertIn("3.00x", held_row["evidence"])
        self.assertFalse(failed_row["held"])
        self.assertIn("3.01x", failed_row["evidence"])

    def test_the_evidence_says_the_comparison_used_the_two_decimals_shown(self):
        self.assertIn("compared at the two decimals shown", row_of(self.calls(1300), "P1")["evidence"])

    def test_p2_tokens_ratio_edges(self):
        agent = lambda t, r: {"tokens": (900, 100)}                                                # noqa: E731  1000 tokens a run
        for team, expected in (((720, 80), True), ((711, 79), False), ((1800, 200), True), ((1809, 201), False)):
            with self.subTest(team_tokens=team):
                self.assertIs(row_of(race(agent=agent, team=lambda t, r, team=team: {"tokens": team}), "P2")["held"], expected)

    def test_p3_model_seconds_ratio_edges(self):
        agent = lambda t, r: {"api": 100.0}                                                        # noqa: E731
        for team, expected in ((100.0, True), (99.0, False), (300.0, True), (301.0, False)):
            with self.subTest(team_seconds=team):
                self.assertIs(row_of(race(agent=agent, team=lambda t, r, team=team: {"api": team}), "P3")["held"], expected)

    def test_p8_opening_ratio_is_held_at_1_5_not_at_1_49_and_held_when_it_prints_as_1_50(self):
        # the team opens three conversations of 100 tokens (the manager and two hand-offs) against the agent's one
        for agent_opening, expected in ((200, True), (201, False), (200.5, True)):
            with self.subTest(agent_opening=agent_opening):
                saved = race(agent=lambda t, r, o=agent_opening: {"opening": o})
                self.assertIs(row_of(saved, "P8")["held"], expected)
        self.assertIn("1.50x", row_of(race(agent=lambda t, r: {"opening": 200.5}), "P8")["evidence"])


class CountEdgeTests(unittest.TestCase):
    def test_p1_wants_more_calls_on_seven_tasks_and_not_six(self):
        agent = lambda t, r: {"calls": 3}                                                          # noqa: E731
        for lower_on, expected in ((2, True), (3, False)):                                         # the team makes fewer calls than the agent on this many tasks
            with self.subTest(tasks_with_fewer_calls=lower_on):
                lower = lambda t, r, n=lower_on: {"calls": 2} if t in TASKS[:n] else {}            # noqa: E731
                self.assertIs(row_of(race(team=lower, agent=agent), "P1")["held"], expected)

    def test_p4_wants_the_calculator_in_at_least_6_of_the_9_calculation_runs(self):
        for used, expected in ((6, True), (5, False), (9, True)):
            with self.subTest(calculation_runs_with_the_calculator=used):
                self.assertIs(row_of(race(team=calculator_use(on=used)), "P4")["held"], expected)

    def test_p4_allows_the_calculator_in_at_most_4_of_the_other_18_runs(self):
        for used, expected in ((4, True), (5, False), (0, True)):
            with self.subTest(other_runs_with_the_calculator=used):
                self.assertIs(row_of(race(team=calculator_use(elsewhere=used)), "P4")["held"], expected)

    def test_p5_wants_the_team_within_2_passes_of_the_agent_on_the_calculation_tasks(self):
        for failures, expected in ((2, True), (3, False), (0, True)):
            with self.subTest(team_failures_on_calculation_runs=failures):
                self.assertIs(row_of(race(team=first(CALC_CELLS, failures, success=False)), "P5")["held"], expected)

    def test_p6_wants_the_team_within_5_passes_of_the_agent_over_all_runs(self):
        for failures, expected in ((5, True), (6, False), (0, True)):
            with self.subTest(team_failures_elsewhere=failures):
                saved = race(team=first(OTHER_CELLS, failures, success=False))
                self.assertIs(row_of(saved, "P6")["held"], expected)
                rows, failed, _dropped = prediction.check_prediction(saved)
                self.assertIs(failed, not expected)                                                 # P6 decides the verdict

    def test_p7_wants_one_hand_off_at_a_time_in_at_least_70_percent_of_the_team_runs(self):
        for overlapping, expected in ((8, True), (9, False), (0, True)):                           # 19 of 27 is 70.4%, 18 of 27 is 66.7%
            with self.subTest(runs_with_overlapping_hand_offs=overlapping):
                self.assertIs(row_of(race(team=first(ALL_CELLS, overlapping, overlap=True)), "P7")["held"], expected)
        self.assertIn("19 of 27 team runs (70.4%; needs 70%)", row_of(race(team=first(ALL_CELLS, 8, overlap=True)), "P7")["evidence"])

    def test_p9_allows_at_most_3_team_runs_that_end_on_a_limit(self):
        for stops, expected in ((3, True), (4, False), (0, True)):
            with self.subTest(team_runs_on_a_limit=stops):
                saved = race(team=first(ALL_CELLS, stops, stop="max_steps", success=False))
                self.assertIs(row_of(saved, "P9")["held"], expected)

    def test_p9_allows_at_most_2_single_agent_runs_that_end_on_a_limit(self):
        for stops, expected in ((2, True), (3, False), (0, True)):
            with self.subTest(agent_runs_on_a_limit=stops):
                saved = race(agent=first(ALL_CELLS, stops, stop="timeout", success=False))
                self.assertIs(row_of(saved, "P9")["held"], expected)

    def test_p10_allows_at_most_12_model_calls_on_the_unanswerable_task(self):
        for calls, expected in ((12, True), (13, False)):
            with self.subTest(calls=calls):
                saved = race(team=lambda t, r, c=calls: {"calls": c} if t == "t7-unanswerable" else {})
                self.assertIs(row_of(saved, "P10")["held"], expected)

    def test_p10_wants_every_one_of_the_three_unanswerable_runs_refused(self):
        everyone = race()
        one_answers = race(team=lambda t, r: {"answer": "It is 10%."} if (t, r) == ("t7-unanswerable", 1) else {})
        self.assertTrue(row_of(everyone, "P10")["held"])
        self.assertFalse(row_of(one_answers, "P10")["held"])
        self.assertIn("refused 2 of 3", row_of(one_answers, "P10")["evidence"])


class StructureNotSecondsTests(unittest.TestCase):
    """P7 asks whether the manager asked for hand-offs together, which is read from the hand-offs, not from the seconds they took."""

    def zero_second_overlap(self, runs=27):
        saved = race()
        chosen = [row for row in saved["runs"] if row["approach"] == "team"][:runs]
        for row in chosen:
            row["team"]["handoffs"] = [dict(h, after_manager_step=1, api_seconds=0.0) for h in row["team"]["handoffs"]]
        return saved

    def test_two_hand_offs_in_one_manager_step_count_as_overlapping_even_when_both_took_zero_seconds(self):
        saved = self.zero_second_overlap()
        team = next(row for row in saved["runs"] if row["approach"] == "team")
        self.assertEqual(team_report.overlap_saving(team), 0.0)                                      # the seconds say nothing
        self.assertTrue(team_report.asked_side_by_side(team))
        held_row = row_of(saved, "P7")
        self.assertFalse(held_row["held"])
        self.assertIn("0 of 27 team runs", held_row["evidence"])

    def test_a_refused_hand_off_in_the_same_step_is_not_one_the_manager_got_to_run_beside_the_other(self):
        saved = race()
        team = next(row for row in saved["runs"] if row["approach"] == "team")
        team["team"]["handoffs"][1] = dict(team["team"]["handoffs"][1], after_manager_step=team["team"]["handoffs"][0]["after_manager_step"], state="refused")
        self.assertFalse(team_report.asked_side_by_side(team))

    def test_hand_offs_in_different_steps_and_runs_without_any_are_one_at_a_time(self):
        saved = race()
        team = next(row for row in saved["runs"] if row["approach"] == "team")
        self.assertFalse(team_report.asked_side_by_side(team))
        self.assertFalse(team_report.asked_side_by_side(dict(team, team=dict(team["team"], handoffs=[]))))
        self.assertFalse(team_report.asked_side_by_side({}))

    def test_a_hand_off_with_no_step_number_is_not_guessed_into_a_group(self):
        saved = race()
        team = next(row for row in saved["runs"] if row["approach"] == "team")
        team["team"]["handoffs"] = [{"state": "finished", "api_seconds": 1.0}, {"state": "finished", "api_seconds": 1.0}]
        self.assertFalse(team_report.asked_side_by_side(team))


class LimitStopsOfTheRunTests(unittest.TestCase):
    """P9 says runs END on a limit: a run whose manager still answered after a specialist hit its cap is not one."""

    def recovered(self, n):
        """n team runs in which the researcher hit its step cap and the manager answered anyway."""
        saved = race()
        for row in [row for row in saved["runs"] if row["approach"] == "team"][:n]:
            row["team"]["handoffs"][0] = dict(row["team"]["handoffs"][0], state="not_finished", stop_reason="max_steps")
        return saved

    def test_four_runs_whose_manager_recovered_from_a_capped_specialist_do_not_end_on_a_limit(self):
        p9 = row_of(self.recovered(4), "P9")
        self.assertTrue(p9["held"])
        self.assertIn("team 0 (at most 3)", p9["evidence"])
        self.assertIn("4 more team run(s) had a hand-off stop on a limit and ended another way (not counted)", p9["evidence"])

    def test_the_arm_stats_keep_limit_stops_as_it_was_and_add_the_runs_own_count_beside_it(self):
        stats = team_report.arm_stats(self.recovered(4), "team")
        self.assertEqual((stats["limit_stops"], stats["own_limit_stops"]), (4, 0))

    def test_a_run_whose_own_stop_is_a_limit_counts_even_when_no_hand_off_did(self):
        saved = race(team=first(ALL_CELLS, 4, stop="token_budget", success=False))
        self.assertFalse(row_of(saved, "P9")["held"])
        self.assertEqual(team_report.arm_stats(saved, "team")["own_limit_stops"], 4)

    def test_the_sensitivity_view_still_drops_a_unit_where_any_agent_hit_a_limit(self):
        _kept, dropped = team_report.clean_units(self.recovered(4))
        self.assertEqual((dropped["kept"], dropped["dropped_for_limits"]), (23, 4))


if __name__ == "__main__":
    unittest.main()
