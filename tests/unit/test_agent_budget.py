"""Week 8: the per-tool call budget (AGENT_MAX_CALLS_PER_TOOL), driven by the scripted fake model."""
import unittest
from unittest import mock

import _testkit  # noqa: F401  (puts the project root on sys.path)
from pydantic import ValidationError

from app.agent import loop
from app.agent.tools import Tool
from app.config import Settings, settings
from test_agent_loop import LoopTestCase, asks, call, says

RAN = []


def echo(text):
    RAN.append(text)
    return f"echo: {text}"


def other(text):
    RAN.append("other:" + text)
    return "other"


TOOLS = [Tool("echo", "echoes", {"type": "object", "properties": {"text": {"type": "string"}}}, echo),
         Tool("other", "another tool", {"type": "object", "properties": {"text": {"type": "string"}}}, other)]


class CallBudgetTests(LoopTestCase):
    def run_with(self, script, **kwargs):
        RAN.clear()
        return self.run_script(script, tools=TOOLS, use_memory=False, **kwargs)

    def test_a_call_over_the_cap_is_not_executed_and_the_model_is_told_to_answer_from_what_it_has(self):
        script = [asks(call("1", "echo", {"text": "a"})), asks(call("2", "echo", {"text": "b"})),
                  asks(call("3", "echo", {"text": "c"})), says("I don't know based on the provided documents.")]
        run, client = self.run_with(script, max_calls_per_tool=2)
        self.assertEqual(RAN, ["a", "b"])                                    # the third never ran
        third = run.steps[2]["tool_calls"][0]
        self.assertTrue(third["observation"].startswith("BUDGET: echo has already run 2 times"))
        self.assertIn("I don't know based on the provided documents.", third["observation"])
        self.assertEqual((third["ok"], third["blocked"]), (False, True))
        self.assertTrue(client.requests[3]["messages"][-1]["content"].startswith("BUDGET"))
        self.assertEqual(run.stop_reason, "final")

    def test_the_cap_is_per_tool_not_a_total(self):
        script = [asks(call("1", "echo", {"text": "a"})), asks(call("2", "other", {"text": "b"})),
                  asks(call("3", "echo", {"text": "c"})), asks(call("4", "other", {"text": "d"})), says("done")]
        self.run_with(script, max_calls_per_tool=2)
        self.assertEqual(RAN, ["a", "other:b", "c", "other:d"])

    def test_off_by_default_and_a_cap_of_zero_means_no_limit(self):
        script = [asks(call(str(i), "echo", {"text": str(i)})) for i in range(5)] + [says("done")]
        self.run_with(script)
        self.assertEqual(len(RAN), 5)
        self.assertEqual(settings.agent_max_calls_per_tool, 0)

    def test_the_setting_is_the_default_and_an_argument_overrides_it(self):
        script = [asks(call("1", "echo", {"text": "a"})), asks(call("2", "echo", {"text": "b"})), says("done")]
        with mock.patch.object(settings, "agent_max_calls_per_tool", 1):
            self.run_with(list(script))
            self.assertEqual(RAN, ["a"])
            self.run_with(list(script), max_calls_per_tool=5)
            self.assertEqual(RAN, ["a", "b"])

    def test_notes_to_memory_are_never_capped(self):
        script = [asks(call(str(i), "remember", {"fact": f"fact {i}"})) for i in range(3)] + [says("done")]
        RAN.clear()
        run, _ = self.run_script(script, tools=TOOLS, max_calls_per_tool=1)
        self.assertEqual(len(run.notes), 3)

    def test_an_identical_repeat_is_still_caught_by_the_repeat_guard_and_not_counted_as_a_run(self):
        script = [asks(call("1", "echo", {"text": "a"})), asks(call("2", "echo", {"text": "a"})), says("done")]
        run, _ = self.run_with(script, max_calls_per_tool=2)
        self.assertEqual(RAN, ["a"])
        self.assertTrue(run.steps[1]["tool_calls"][0]["observation"].startswith("You already called echo"))

    def test_a_model_that_keeps_asking_after_the_budget_is_spent_still_stops(self):
        script = [asks(call(str(i), "echo", {"text": str(i)})) for i in range(8)]
        run, _ = self.run_with(script, max_calls_per_tool=1)
        self.assertEqual(RAN, ["0"])
        self.assertEqual(run.stop_reason, "max_steps")                       # never converged, but it ran the tool once only


class SettingTests(unittest.TestCase):
    def test_default_is_off_and_a_negative_cap_is_rejected(self):
        self.assertEqual(Settings(_env_file=None).agent_max_calls_per_tool, 0)
        self.assertEqual(Settings(_env_file=None, agent_max_calls_per_tool=3).agent_max_calls_per_tool, 3)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, agent_max_calls_per_tool=-1)


if __name__ == "__main__":
    unittest.main()
