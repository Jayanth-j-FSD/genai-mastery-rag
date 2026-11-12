"""Week 10: the printed tables line up, an arm with no runs prints n/a, and the stops behind the numbers are shown (evals/team_report.py)."""
import re
import unittest

import _testkit
from evals import team_report as report
from test_team_report import call, crew, handoff, race, record, step


def full_race(**meta):
    """Two tasks, two repeats, the agent and the team, with call records and steps that add up."""
    rows = []
    for task in ("t1", "t2"):
        for repeat in (1, 2):
            rows.append(record(task, "agent", repeat, repeat == 1, 1234, 56, 2, steps=[step(None, None, 1234, 56)], call_log=[call("m")]))
            rows.append(record(task, "team", repeat, True, 4321, 78, 5, steps=[step("manager", None, 4000, 70), step("researcher", 1, 321, 8)],
                               team=dict(crew(), call_log=[call("m")])))
    return race(rows, interleaved=True, llm_rpm=12, **meta)


def lines_of(saved):
    return report.format_report(saved)


def section(lines, heading, count):
    """The `count` lines that follow the line starting with `heading`."""
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    return lines[start + 1:start + 1 + count]


def edges(line, labels):
    """Where each label ends in the line, found one after the other."""
    found, at = [], 0
    for label in labels:
        at = line.index(label, at)
        at += len(label)
        found.append(at)
    return found


class AlignmentTests(unittest.TestCase):
    def test_every_cell_of_the_quality_table_ends_where_its_heading_ends(self):
        header, agent, team = section(lines_of(full_race()), "QUALITY", 3)
        heading_ends = edges(header, ["arm", "runs", "success", "rate", "95% interval", "finished"])
        for row, cells in ((agent, ["agent", "4", "2/4", "50%", "]", "4/4"]), (team, ["team", "4", "4/4", "100%", "]", "4/4"])):
            self.assertEqual(edges(row, cells)[1:], heading_ends[1:], row)

    def test_the_success_column_in_particular_is_not_a_column_off(self):
        header, _agent, team = section(lines_of(full_race()), "QUALITY", 3)
        self.assertEqual(edges(team, ["team", "4", "4/4"])[2], edges(header, ["arm", "runs", "success"])[2])

    def test_the_cost_table_numbers_end_where_the_r_headings_end(self):
        lines = lines_of(full_race())
        start = next(i for i, line in enumerate(lines) if line.startswith("COST"))
        header, agent = lines[start + 1], lines[start + 2]
        ends = edges(header, [f"r={r} per run" for r in report.PRICE_RATIOS])
        self.assertEqual([match.end() for match in re.finditer(r"\d+", agent)], ends, (header, agent))

    def test_the_cost_headings_do_not_run_into_each_other(self):
        lines = lines_of(full_race())
        header = lines[next(i for i, line in enumerate(lines) if line.startswith("COST")) + 1]
        self.assertNotIn("per runr=", header)
        self.assertEqual(header.count("per run"), len(report.PRICE_RATIOS))
        self.assertTrue(all(len(piece) >= 1 for piece in header.split("per run")[:-1]))

    def test_the_per_pass_table_numbers_end_where_its_headings_end(self):
        lines = lines_of(full_race())
        start = next(i for i, line in enumerate(lines) if line.startswith("per pass"))
        header, agent = lines[start], lines[start + 1]
        ends = edges(header, [f"r={r}" for r in report.PRICE_RATIOS])
        self.assertEqual([match.end() for match in re.finditer(r"\d+", agent)], ends, (header, agent))

    def test_the_instrument_table_numbers_end_where_its_headings_end(self):
        header, agent = section(lines_of(full_race()), "INSTRUMENT", 2)
        ends = edges(header, ["arm", "calls", "recorded", "retried", "wait of retried", "errors", "total != p+c", "cached", "reasoning"])
        self.assertEqual(edges(agent, ["agent", "4", "4/4", "0", "0.0s", "0", "0", "0", "0"])[1:], ends[1:], agent)


class NoRunsTests(unittest.TestCase):
    def saved(self):
        return race([record("a", "agent", 1), record("a", "agent", 2, False)], arms=("agent", "team"))

    def text(self):
        return "\n".join(report.format_report(self.saved()))

    def test_an_arm_listed_with_no_runs_never_prints_zeros_as_if_it_had_been_measured(self):
        text = self.text()
        for zeros in ("0.00x", "0.0 requests a run", "between 0.00x", "$0.00000"):
            self.assertNotIn(zeros, text)

    def test_every_table_row_for_that_arm_says_n_a_no_runs(self):
        rows = [line for line in self.text().splitlines() if line.startswith("team ") and "n/a (no runs)" in line]
        self.assertGreaterEqual(len(rows), 7)                       # instrument, quality, speed, tokens, the two cost tables, behaviour, path

    def test_the_ratios_between_the_arms_are_n_a_and_there_is_no_cost_bound(self):
        data = report.summary(self.saved())
        self.assertIsNone(data["cost_ratio_bounds"])
        ratios = data["team_over_agent"]
        self.assertTrue(all(ratios[key] is None for key in ("calls", "tokens", "prompt", "completion", "model_seconds", "elapsed")))
        self.assertTrue(all(value is None for value in ratios["units"].values()))
        text = self.text()
        self.assertIn("calls n/a, tokens n/a, model seconds n/a", text)
        self.assertNotIn("Whatever the prices", text)

    def test_the_free_tier_line_says_n_a_for_that_arm_and_still_counts_the_other(self):
        text = self.text()
        self.assertIn("team n/a (no runs)", text.split("free-tier cost")[1])
        self.assertIn("agent 2.0 requests a run, 250 runs in a 500-request day", text)

    def test_arm_stats_itself_still_returns_zeros_for_such_an_arm_not_a_crash(self):
        row = report.arm_stats(self.saved(), "team")
        self.assertEqual((row["runs"], row["success_rate"], row["tokens_mean"], row["calls_max"]), (0, 0.0, 0.0, 0))
        self.assertIsNone(report.cost_ratio_bounds({"prompt_mean": 5.0, "completion_mean": 1.0, "runs": 3}, dict(row, runs=0)))

    def test_a_calibration_arm_with_no_runs_gives_no_ratio_either(self):
        saved = race([record("a", "agent", 1)], arms=("agent", "team", "agent-2"))
        self.assertIn("agent-2 / agent:  calls n/a", "\n".join(report.format_report(saved)))


class StopsShownTests(unittest.TestCase):
    def stopped_race(self):
        """Team: one run that ended on a limit itself, two where a researcher hit its cap and the manager answered, one provider error."""
        rows = [record("t1", "agent", 1), record("t1", "agent", 2), record("t1", "agent", 3), record("t1", "agent", 4),
                record("t1", "team", 1, stop="max_steps", finished=False, success=False, team=crew()),
                record("t1", "team", 2, team=crew(handoffs=[handoff(stop="max_steps", state="not_finished")])),
                record("t1", "team", 3, team=crew(handoffs=[handoff(stop="max_steps", state="not_finished"), handoff("calculator", 2, number=2)])),
                record("t1", "team", 4, stop="error", finished=False, success=False, team=crew())]
        return race(rows)

    def test_the_hand_offs_are_counted_by_agent_state_and_stop_reason(self):
        rows = [record("a", "team", 1, team=crew(handoffs=[handoff(), handoff("calculator", 2, number=2, state="not_finished", stop="max_steps")])),
                record("a", "team", 2, team=crew(handoffs=[handoff(stop="empty_reply", state="not_finished")]))]
        view = report.per_agent_stats(race(rows, arms=("team",)))
        self.assertEqual(view["handoff_stops"], {"calculator:not_finished:max_steps": 1, "researcher:finished:final": 1, "researcher:not_finished:empty_reply": 1})
        self.assertEqual(view["handoff_states"], {"calculator:not_finished": 1, "researcher:finished": 1, "researcher:not_finished": 1})

    def test_the_report_prints_the_specialists_stop_reasons(self):
        text = "\n".join(report.format_report(self.stopped_race()))
        self.assertIn("hand-offs by stop reason (agent:state:stop reason): ", text)
        self.assertIn("'researcher:not_finished:max_steps': 2", text)

    def test_the_stops_table_gives_each_arm_its_own_limit_stops_the_runs_any_agent_capped_and_the_provider_trouble(self):
        lines = report.format_report(self.stopped_race())
        header, agent, team = section(lines, "STOPS", 3)
        self.assertEqual(agent.split(), ["agent", "0", "0", "0"])
        self.assertEqual(team.split(), ["team", "1", "3", "1"])
        self.assertEqual(edges(team, ["team", "1"])[1], edges(header, ["arm", "own limit"])[1])

    def test_the_arm_stats_keep_their_numbers(self):
        stats = report.arm_stats(self.stopped_race(), "team")
        self.assertEqual((stats["limit_stops"], stats["own_limit_stops"], stats["provider_trouble"]), (3, 1, 1))


if __name__ == "__main__":
    unittest.main()
