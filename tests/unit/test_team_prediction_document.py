"""Week 10: docs/week10/prediction.md states the thresholds evals/team_prediction.py checks, so neither can drift alone."""
import os
import sys
import unittest

import _testkit
from evals import runner, team_prediction as prediction

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import race_team                                         # noqa: E402


class PredictionDocumentTests(unittest.TestCase):
    def test_the_document_states_the_thresholds_the_module_checks_so_neither_can_drift_alone(self):
        with open(os.path.join(_testkit.ROOT, "docs", "week10", "prediction.md"), encoding="utf-8") as handle:
            text = " ".join(handle.read().split())
        low, high = prediction.BANDS["calls"]
        self.assertIn(f"between {low} and {high} times the single agent's model calls per run", text)
        self.assertIn(f"more of them on at least {prediction.MORE_CALLS_ON_AT_LEAST} of the 9 tasks", text)
        low, high = prediction.BANDS["tokens"]
        self.assertIn(f"between {low} and {high} times the single agent's total tokens per run", text)
        low, high = prediction.BANDS["model_seconds"]
        self.assertIn(f"between {low} and {high} times the single agent's model seconds per run", text)
        self.assertIn(f"in at least {prediction.CALCULATOR_MIN_ON_THEM} of the 9 runs", text)
        self.assertIn(f"in at most {prediction.CALCULATOR_MAX_ELSEWHERE} of the other 18", text)
        self.assertIn(f"as many runs as the single agent minus {prediction.PASS_MARGIN_CALCULATION}", text)
        self.assertIn(f"as many runs as the single agent minus {prediction.PASS_MARGIN_ALL}", text)
        self.assertIn(f"at least {prediction.ONE_AT_A_TIME_SHARE:.0%} of the team's runs", text)
        self.assertIn(f"at least {prediction.OPENING_FACTOR} times the single agent's", text)
        self.assertIn(f"at most {prediction.MAX_LIMIT_STOPS['team']} team runs and at most {prediction.MAX_LIMIT_STOPS['agent']} single-agent runs", text)
        self.assertIn(f"never needs more than {prediction.MAX_CALLS_UNANSWERABLE} model calls", text)
        self.assertIn("The prediction has FAILED if " + ", ".join(prediction.FAILS_IF[:-1]) + " or " + prediction.FAILS_IF[-1] + " does not hold", text)
        for task in prediction.CALCULATOR_TASKS:
            self.assertIn(task, text)

    def test_the_range_the_prediction_quotes_from_the_plan_is_the_range_the_plan_computes(self):
        lean, high = race_team.estimate_team_calls(runner.load_results("race-race"))
        quoted = f"{lean:.1f} to {high:.1f} team calls a run"
        with open(os.path.join(_testkit.ROOT, "docs", "week10", "prediction.md"), encoding="utf-8") as handle:
            document = " ".join(handle.read().split())
        self.assertIn(quoted, document)
        self.assertIn(quoted, " ".join(prediction.__doc__.split()))
        self.assertNotIn("4.5 to 8.4", document)                  # the figure an earlier draft quoted and the plan never printed
        self.assertNotIn("4.5 to 8.4", " ".join(prediction.__doc__.split()))


if __name__ == "__main__":
    unittest.main()
