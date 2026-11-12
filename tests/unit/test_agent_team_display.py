"""Week 10: the live display of a team run and the saved record must agree about every step (no network)."""
import contextlib
import io
import re
import unittest

import _testkit
from app.agent import display
from test_agent_loop import asks, call, says
from test_agent_team import TeamTestCase, to_calculator, to_researcher


def label(step):
    return step["agent"] if step["handoff"] is None else f"{step['agent']} #{step['handoff']}"


class LiveNumbersTests(TeamTestCase):
    def test_the_step_numbers_printed_live_are_the_numbers_the_saved_run_gives_those_steps(self):
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            run, _client = self.run_team([
                asks(to_researcher("m1"), to_calculator("m2")), says("30 calendar days"),
                asks(call("c1", "add_days", {"date": "2026-11-03", "days": 30})), says("2026-12-03"),
                asks(to_researcher("m3", "second thing")), says("another fact"), says("final")], on_step=display.show_team_step)
        printed = [(who, int(number)) for who, number in re.findall(r"--- (.+?) ---\n\[step (\d+)\]", shown.getvalue())]
        self.assertEqual(len(printed), len(run.steps))
        self.assertEqual(sorted(printed, key=lambda pair: pair[1]), [(label(step), step["n"]) for step in run.steps])

    def test_the_manager_step_that_handed_work_over_is_printed_after_the_steps_it_caused_under_its_earlier_number(self):
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            self.run_team([asks(to_researcher("m1")), says("30 calendar days"), says("done")], on_step=display.show_team_step)
        printed = [(who, int(number)) for who, number in re.findall(r"--- (.+?) ---\n\[step (\d+)\]", shown.getvalue())]
        self.assertEqual(printed, [("researcher #1", 2), ("manager", 1), ("manager", 3)])
        self.assertIn("Steps arrive as they finish", display.show_team_step.__doc__)            # and the printer says why the numbers can look out of order
        self.assertIn("saved run", display.show_team_step.__doc__)


if __name__ == "__main__":
    unittest.main()
