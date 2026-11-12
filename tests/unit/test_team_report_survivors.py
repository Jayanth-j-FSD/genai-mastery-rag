"""Week 10: edges of the report and the prediction that a mutation pass showed nothing pinned (a tie in P1, a curly-apostrophe refusal, a floor, an equal prompt)."""
import unittest

import _testkit
from evals import team_prediction as prediction, team_report as report
from test_team_prediction import TASKS, held, race

CURLY = chr(0x2019)                                               # written by code so that no typographic character sits in this file


def step(agent, handoff, prompt, completion=5, calls=None):
    return {"agent": agent, "handoff": handoff, "tokens": {"prompt": prompt, "completion": completion}, "tool_calls": calls or []}


class P1TieTests(unittest.TestCase):
    def test_a_task_where_the_team_made_exactly_as_many_calls_as_the_agent_is_not_more_calls(self):
        agent = lambda t, r: {"calls": 3}                                            # noqa: E731
        team = lambda t, r: {"calls": 5} if t in TASKS[:6] else {"calls": 3}         # noqa: E731  six tasks with more calls, three exactly equal
        rows, _failed, _dropped = prediction.check_prediction(race(agent=agent, team=team))
        p1 = next(row for row in rows if row["id"] == "P1")
        self.assertIn("more calls on 6 of 9 tasks", p1["evidence"])
        self.assertFalse(p1["held"])                                                 # six is below the seven the prediction asks for: the ties must not count
        self.assertFalse(held(rows)["P1"])


class RefusalReadingTests(unittest.TestCase):
    def test_a_refusal_written_with_a_curly_apostrophe_is_still_a_refusal(self):
        for apostrophe in ("'", CURLY):
            with self.subTest(apostrophe=apostrophe):
                features = report.answer_features({"answer": f"I don{apostrophe}t know based on the provided documents.", "steps": []})
                self.assertTrue(features["refused"])
                self.assertFalse(features["answered_without_hand_off"])

    def test_a_refusal_after_a_search_is_not_a_refusal_without_searching_and_one_with_no_search_is(self):
        searched = [{"tool_calls": [{"name": "search_policies"}]}]
        refusal = "I don't know based on the provided documents."
        self.assertFalse(report.answer_features({"answer": refusal, "steps": searched})["refused_without_searching"])
        self.assertTrue(report.answer_features({"answer": refusal, "steps": []})["refused_without_searching"])
        self.assertFalse(report.answer_features({"answer": "30 days", "steps": []})["refused_without_searching"])       # an answer is not a refusal at all


class TokenAccountingEdgeTests(unittest.TestCase):
    def test_tokens_billed_beyond_the_steps_are_counted_and_never_negative(self):
        steps = [step("manager", None, 50, 10)]
        self.assertEqual(report.tokens_in_no_step({"steps": steps, "prompt_tokens": 80, "completion_tokens": 30}), 50)       # 110 billed, 60 in steps
        self.assertEqual(report.tokens_in_no_step({"steps": steps, "prompt_tokens": 20, "completion_tokens": 10}), 0)        # steps hold more than the run says: not -30
        self.assertEqual(report.tokens_in_no_step({"steps": [], "prompt_tokens": 80, "completion_tokens": 30}), 0)           # no step record: nothing to compare

    def test_a_prompt_that_stays_the_same_size_is_not_a_shrink_and_a_smaller_one_is(self):
        same = report.prompt_breakdown([step("manager", None, 100), step("manager", None, 100)])
        smaller = report.prompt_breakdown([step("manager", None, 100), step("manager", None, 90)])
        self.assertEqual((same["opening"], same["later"], same["shrank"]), (100, 100, 0))
        self.assertEqual((smaller["opening"], smaller["later"], smaller["shrank"]), (100, 90, 1))


if __name__ == "__main__":
    unittest.main()
