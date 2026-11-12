"""Week 10: the team as a third runner in the race harness (evals/race.py) without disturbing the Week 7 race."""
import os
import sys
import unittest
from unittest import mock

import _testkit
from app import llm
from app.agent import team
from app.agent.toolkit import calculator_tool, date_tool
from app.agent.tools import Tool
from evals import race
from evals.agent_tasks import get_tasks
from test_agent_loop import FakeClient, asks, call, says

ACME = "Acme-Leave-Policy-2026.md"
WEEK_7_KEYS = {"task_id", "approach", "repeat", "success", "finished", "rules_passed", "stop_reason", "answer", "failed_checks", "warnings",
               "n_steps", "tool_calls", "llm_calls", "prompt_tokens", "completion_tokens", "api_seconds", "wait_seconds", "elapsed_seconds",
               "steps", "notes"}
TASK = get_tasks(["t7-single-lookup"])[0]                       # 16 weeks of paid parental leave, cited to the Acme leave policy


def search(query, top_k=3):
    return f"[1] [source: {ACME}] Eligible employees may take 16 weeks of paid parental leave."


TOOLS = [Tool("search_policies", "s", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, search),
         calculator_tool(), date_tool()]


def team_script():
    return [asks(call("m1", "ask_policy_researcher", {"question": "how long is paid parental leave"}), prompt=100, completion=10),
            asks(call("r1", "search_policies", {"query": "parental leave"}), prompt=50, completion=5),
            says(f"[source: {ACME}] 16 weeks of paid parental leave.", prompt=80, completion=12),
            says(f"There are 16 weeks of paid parental leave. [source: {ACME}]", prompt=150, completion=14)]


class TeamBranchTests(unittest.TestCase):
    def setUp(self):
        llm.reset_usage()
        self.enterContext(mock.patch.object(race.settings, "llm_rpm", 0))
        self.enterContext(mock.patch.object(race.settings, "llm_max_retries", 0))

    def run_team_one(self, script=None, **options):
        client = FakeClient(script or team_script())
        with mock.patch.object(llm, "_get_client", return_value=client):
            return race.run_one(TASK, "team", 1, TOOLS, **options), client

    def test_the_week_7_race_still_has_two_approaches_and_the_team_is_a_third_runner_beside_it(self):
        self.assertEqual(race.APPROACHES, ("agent", "workflow"))
        record, _client = self.run_team_one()
        self.assertEqual(record["approach"], "team")

    def test_a_team_run_is_scored_by_the_same_rule_checks_and_its_sources_come_from_the_researchers_search(self):
        record, client = self.run_team_one()
        self.assertEqual(client.script, [])
        self.assertTrue(record["success"])
        self.assertEqual((record["llm_calls"], record["prompt_tokens"], record["completion_tokens"]), (4, 380, 41))
        self.assertIn("search_policies", record["tool_calls"])
        self.assertIn("ask_policy_researcher", record["tool_calls"])

    def test_the_team_record_is_the_week_7_record_plus_one_key_and_the_others_have_no_such_key(self):
        record, _client = self.run_team_one()
        self.assertEqual(set(record) - WEEK_7_KEYS, {"team"})
        self.assertEqual(set(record["team"]), {"per_agent", "handoffs", "call_log", "warnings", "errors"})
        with mock.patch("app.agent.loop.run_agent", return_value=mock.Mock(finished=False, steps=[], usage={}, notes=[], stop_reason="x",
                                                                          answer=None)):
            self.assertEqual(set(race.run_one(TASK, "agent", 1, TOOLS)), WEEK_7_KEYS)

    def test_an_option_the_team_does_not_take_is_an_error_not_something_quietly_dropped(self):
        with self.assertRaises(ValueError) as caught:
            race.run_one(TASK, "team", 1, TOOLS, use_memory=False)
        self.assertIn("use_memory", str(caught.exception))

    def test_the_options_the_team_takes_reach_it(self):
        with mock.patch("app.agent.team.run_team") as running:
            running.return_value = mock.Mock(finished=False, steps=[], usage={}, notes=[], stop_reason="x", answer=None, team={})
            race.run_one(TASK, "team", 1, TOOLS, model="m", rpm=7, timeout_seconds=300, max_calls_per_tool=0, max_steps=5, max_total_tokens=999)
        options = running.call_args.kwargs
        self.assertEqual(options, {"model": "m", "rpm": 7, "timeout_seconds": 300, "max_calls_per_tool": 0, "max_steps": 5, "max_total_tokens": 999})

    def test_one_patch_of_the_loop_covers_the_agent_arm_and_every_agent_of_the_team(self):
        seen = []
        real = race.loop.run_agent

        def spy(*args, **kwargs):
            seen.append(kwargs.get("system_prompt"))
            return real(*args, **kwargs)

        client = FakeClient(team_script() + [says("ok")])
        with mock.patch.object(llm, "_get_client", return_value=client), mock.patch("app.agent.loop.run_agent", spy):
            race.run_one(TASK, "team", 1, TOOLS)
            race.run_one(TASK, "agent", 1, TOOLS)
        self.assertEqual(len(seen), 3)                                                          # manager, researcher, then the single agent


class ScriptWrapperTests(unittest.TestCase):
    """scripts/race_team.run_scoped around the real runners: the same per-call instrument under both arms."""

    def setUp(self):
        llm.reset_usage()
        self.enterContext(mock.patch.object(race.settings, "llm_rpm", 0))
        self.enterContext(mock.patch.object(race.settings, "llm_max_retries", 0))
        sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
        import race_team
        self.race_team = race_team

    def test_a_team_run_keeps_one_call_log_tagged_by_agent_that_adds_up_to_what_the_run_reports(self):
        client = FakeClient(team_script())
        with mock.patch.object(llm, "_get_client", return_value=client):
            record = self.race_team.run_scoped("team", TASK, 1, TOOLS, {}, race.run_one)
        log = record["team"]["call_log"]
        self.assertEqual([(call["agent"], call["handoff"]) for call in log], [("manager", None), ("researcher", 1), ("researcher", 1), ("manager", None)])
        self.assertEqual((len(log), sum(call["prompt_tokens"] for call in log)), (record["llm_calls"], record["prompt_tokens"]))
        self.assertNotIn("call_log", record)
        self.assertNotIn("usage_warning", record)
        self.assertEqual(record["team"]["warnings"], [])

    def test_a_single_agent_run_gets_a_call_log_from_the_same_instrument_and_it_adds_up_too(self):
        client = FakeClient([asks(call("a1", "search_policies", {"query": "parental leave"}), prompt=50, completion=5),
                             says(f"There are 16 weeks of paid parental leave. [source: {ACME}]", prompt=80, completion=12)])
        with mock.patch.object(llm, "_get_client", return_value=client):
            record = self.race_team.run_scoped("agent", TASK, 1, TOOLS, {}, race.run_one)
        self.assertEqual([(call["agent"], call["handoff"], call["status"]) for call in record["call_log"]], [("agent", None, "ok")] * 2)
        self.assertEqual((record["llm_calls"], record["prompt_tokens"], record["completion_tokens"]), (2, 130, 17))
        self.assertNotIn("usage_warning", record)
        self.assertTrue(record["success"])

    def test_the_workflow_is_measured_by_the_same_instrument(self):
        client = FakeClient([says(f"16 weeks of paid parental leave. [source: {ACME}]", prompt=900, completion=20)])
        with mock.patch.object(llm, "_get_client", return_value=client), \
                mock.patch("app.agent.workflow.retriever.retrieve_for_mode", return_value=[{"source": ACME, "text": "16 weeks of paid parental leave"}]):
            record = self.race_team.run_scoped("workflow", TASK, 1, TOOLS, {}, race.run_one)
        self.assertEqual([(call["agent"], call["prompt_tokens"]) for call in record["call_log"]], [("workflow", 900)])
        self.assertNotIn("usage_warning", record)


class ThreeArmFileTests(unittest.TestCase):
    def three_arms(self):
        def run(arm, ok):
            return {"task_id": "t7-single-lookup", "approach": arm, "repeat": 1, "success": ok, "finished": True, "rules_passed": ok,
                    "stop_reason": "final", "answer": f"16 weeks of paid parental leave. [source: {ACME}]", "failed_checks": [], "warnings": [],
                    "n_steps": 2, "tool_calls": [], "llm_calls": 2, "prompt_tokens": 100, "completion_tokens": 10, "api_seconds": 1.0,
                    "wait_seconds": 0.0, "elapsed_seconds": 2.0, "notes": [],
                    "steps": [{"n": 1, "kind": "tool", "content": "", "seconds": 0.1, "tokens": {"prompt": 0, "completion": 0},
                               "tool_calls": [{"name": "search_policies", "arguments": "{}", "ok": True,
                                               "observation": f"[1] [source: {ACME}] Eligible employees may take 16 weeks of paid parental leave."}]}]}
        meta = {"label": "t", "repeats": 1, "tasks": ["t7-single-lookup"], "approaches": ["agent", "team", "agent-2"], "arms": ["agent", "team", "agent-2"],
                "complete": True, "models": {"agent": "m", "team": "m", "agent-2": "m"}}
        return {"meta": meta, "runs": [run("agent", True), run("team", True), run("agent-2", False)]}

    def test_the_week_7_summary_and_rescore_still_work_on_a_file_with_a_team_and_a_noise_arm(self):
        results = self.three_arms()
        summary = race.summarize(results)
        self.assertEqual(set(summary["approaches"]), {"agent", "team", "agent-2"})            # the noise arm does not merge into the agent's row
        self.assertEqual((summary["approaches"]["agent"]["success"], summary["approaches"]["agent-2"]["success"]), (1, 0))
        self.assertIn("agent-2", "\n".join(race.format_summary(results)))
        rescored = race.rescore(results)
        self.assertEqual({run["approach"] for run in rescored["runs"]}, {"agent", "team", "agent-2"})
        self.assertTrue(rescored["meta"]["rescored"])


if __name__ == "__main__":
    unittest.main()
