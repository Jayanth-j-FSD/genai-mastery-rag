"""Week 10: the repeats of a task are near-copies, so the report must say its pair-level p and its intervals are optimistic and add a task-level test."""
import unittest

import _testkit
from evals import team_report as report
from test_team_report import record, race

TASK_IDS = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9"]


def lost_two_tasks_race(extra_arms=()):
    """The case: the agent passes everything, the team fails t1 and t2 on every repeat."""
    rows = []
    for repeat in (1, 2, 3):
        for task in TASK_IDS:
            rows.append(record(task, "agent", repeat, True))
            rows.append(record(task, "team", repeat, task not in ("t1", "t2")))
            for arm in extra_arms:
                rows.append(record(task, arm, repeat, True))
    return race(rows, arms=("agent", "team", *extra_arms))


class TaskLevelPairingTests(unittest.TestCase):
    def test_two_tasks_failed_on_every_repeat_look_significant_by_pair_but_not_by_task(self):
        saved = lost_two_tasks_race()
        self.assertLess(report.paired(saved)["p"], 0.05)                    # 6 discordant pairs, all one way: p = 0.031
        by_task = report.paired_by_task(saved)
        self.assertEqual({key: by_task[key] for key in ("tasks", "more_agent", "more_team", "same")},
                         {"tasks": 9, "more_agent": 2, "more_team": 0, "same": 7})
        self.assertAlmostEqual(by_task["p"], 0.5)                           # 2 differing tasks can never reach 0.05

    def test_each_direction_is_counted_and_the_sign_test_is_two_sided(self):
        rows = []
        for task, agent_wins, team_wins in (("a", 3, 0), ("b", 2, 1), ("c", 0, 3), ("d", 1, 1), ("e", 0, 1)):
            for repeat in (1, 2, 3):
                rows.append(record(task, "agent", repeat, repeat <= agent_wins))
                rows.append(record(task, "team", repeat, repeat <= team_wins))
        by_task = report.paired_by_task(race(rows))
        self.assertEqual((by_task["more_agent"], by_task["more_team"], by_task["same"], by_task["tasks"]), (2, 2, 1, 5))
        self.assertEqual(by_task["p"], 1.0)

    def test_six_tasks_all_going_one_way_do_reach_the_usual_threshold_by_task(self):
        rows = []
        for task in TASK_IDS[:6]:
            rows += [record(task, "agent", 1, True), record(task, "team", 1, False)]
        by_task = report.paired_by_task(race(rows))
        self.assertEqual((by_task["more_agent"], by_task["more_team"]), (6, 0))
        self.assertAlmostEqual(by_task["p"], 2 / 2 ** 6)

    def test_a_task_only_one_arm_ran_is_not_counted_and_pass_counts_use_only_the_paired_repeats(self):
        rows = [record("a", "agent", 1, True), record("a", "team", 1, False),
                record("a", "agent", 2, False),                                    # no team run for repeat 2: left out of the task's counts
                record("b", "agent", 1, True)]                                      # task b has no team run at all
        by_task = report.paired_by_task(race(rows))
        self.assertEqual((by_task["tasks"], by_task["more_agent"], by_task["more_team"], by_task["same"]), (1, 1, 0, 0))

    def test_one_task_is_not_called_tasks(self):
        text = "\n".join(report.format_report(race([record("a", "agent", 1, True), record("a", "team", 1, False)])))
        self.assertIn("by task (1 task): agent passed more of the repeats on 1 task, team on 0, the same on 0", text)

    def test_with_no_differing_task_the_p_is_one(self):
        rows = [record("a", "agent", 1, True), record("a", "team", 1, True)]
        self.assertEqual(report.paired_by_task(race(rows))["p"], 1.0)
        self.assertEqual(report.paired_by_task(race([]))["tasks"], 0)

    def test_the_summary_carries_the_task_level_result_for_the_main_pair_the_calibration_and_the_clean_units(self):
        data = report.summary(lost_two_tasks_race(extra_arms=("agent-2",)))
        self.assertEqual(data["paired_by_task"]["more_agent"], 2)
        self.assertEqual(data["calibration"]["by_task"]["same"], 9)
        self.assertEqual(data["clean"]["paired_by_task"]["tasks"], 9)


class PairCaveatTests(unittest.TestCase):
    def text(self, **kwargs):
        return "\n".join(report.format_report(lost_two_tasks_race(**kwargs)))

    def test_the_task_level_line_prints_next_to_the_pair_line(self):
        lines = self.text().splitlines()
        pair = next(i for i, line in enumerate(lines) if line.startswith("paired by task and repeat (27 pairs)"))
        self.assertIn("by task (9 tasks): agent passed more of the repeats on 2 tasks, team on 0, the same on 7", lines[pair + 1])
        self.assertIn("exact sign test over the 2 differing task(s) p = 0.500", lines[pair + 1])
        self.assertIn("exact McNemar p = 0.031", lines[pair])

    def test_the_pair_line_says_it_treats_the_repeats_of_a_task_as_independent_so_it_is_optimistic(self):
        self.assertIn("treats the repeats of a task as independent, so it is optimistic", self.text().split("by task (9 tasks)")[0])

    def test_the_interval_column_carries_the_same_caveat(self):
        text = self.text()
        quality = text.split("QUALITY")[1].split("SPEED")[0]
        self.assertIn("95% interval treats every run as an independent trial", quality)
        self.assertIn("so it is optimistic", quality.split("95% interval treats every run")[1])

    def test_the_calibration_and_the_clean_unit_comparisons_get_the_task_level_line_too_and_the_calibration_keeps_its_pair_count(self):
        text = self.text(extra_arms=("agent-2",))
        calibration = next(line for line in text.splitlines() if line.startswith("calibration, agent against agent-2"))
        self.assertIn("(27 pairs)", calibration)
        self.assertIn("(the same design twice)", calibration)
        self.assertEqual(text.count("by task ("), 3)                                  # main, calibration, clean units
        self.assertIn("SENSITIVITY", text)

    def test_the_numbers_themselves_are_unchanged(self):
        pair = report.paired(lost_two_tasks_race())
        self.assertEqual((pair["pairs"], pair["only_agent"], pair["only_team"], pair["both"], pair["neither"]), (27, 6, 0, 21, 0))
        self.assertAlmostEqual(pair["p"], 2 / 2 ** 6)


if __name__ == "__main__":
    unittest.main()
