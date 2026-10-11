"""Week 10: the manager and two specialists, driven by a scripted fake model (no network, no index)."""
import json
import unittest
from unittest import mock

import _testkit
from app import llm
from app.agent import loop, team
from app.agent.toolkit import calculator_tool, date_tool
from app.agent.tools import Tool
from test_agent_loop import FakeClient, LoopTestCase, asks, call, says

SOURCE = "Acme-Employment-Terms-2026.md"
QUESTION = "What is the notice period?"
IDK = "I don't know based on the provided documents."


def fake_search(query, top_k=3):
    return f"[1] [source: {SOURCE}] A permanent employee gives 30 calendar days of written notice."


SEARCH = Tool("search_policies", "search the documents",
              {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["query"]},
              fake_search)
TOOLS = [SEARCH, calculator_tool(), date_tool()]


def to_researcher(call_id, question="notice period for a permanent employee"):
    return call(call_id, "ask_policy_researcher", {"question": question})


def to_calculator(call_id, question="add 30 days to 2026-11-03"):
    return call(call_id, "ask_calculator", {"question": question})


def tool_names(request):
    return [spec["function"]["name"] for spec in request["tools"]]


class TeamTestCase(LoopTestCase):
    def run_team(self, script, tools=None, **kwargs):
        client = FakeClient(script)
        with mock.patch.object(llm, "_get_client", return_value=client):
            run = team.run_team(QUESTION, TOOLS if tools is None else tools, **kwargs)
        return run, client


class HandOffTests(TeamTestCase):
    def test_a_lookup_goes_from_the_manager_to_the_researcher_and_back(self):
        answer = f"It is 30 calendar days. [source: {SOURCE}]"
        run, client = self.run_team([
            asks(to_researcher("m1"), prompt=100, completion=10),
            asks(call("r1", "search_policies", {"query": "notice period"}), prompt=50, completion=5),
            says(f"30 calendar days. [source: {SOURCE}]", prompt=80, completion=12),
            says(answer, prompt=150, completion=14)])
        self.assertEqual(client.script, [])
        self.assertEqual((run.stop_reason, run.finished, run.answer), ("final", True, answer))
        self.assertEqual([(s["n"], s["agent"], s["local_n"]) for s in run.steps],
                         [(1, "manager", 1), (2, "researcher", 1), (3, "researcher", 2), (4, "manager", 2)])
        self.assertEqual([s["handoff"] for s in run.steps], [None, 1, 1, None])

    def test_the_specialist_sees_only_the_question_the_manager_sent_and_only_its_own_tools(self):
        _run, client = self.run_team([asks(to_researcher("m1")), says("30 calendar days"), says("done")])
        manager_first, researcher_first, manager_last = client.requests
        self.assertEqual(tool_names(manager_first), ["ask_policy_researcher", "ask_calculator", "remember"])
        self.assertEqual(tool_names(researcher_first), ["search_policies", "remember"])      # its own tools, and the loop's default notes tool
        self.assertEqual(researcher_first["messages"], [{"role": "system", "content": team.RESEARCHER_PROMPT},
                                                        {"role": "user", "content": "notice period for a permanent employee"}])
        self.assertNotIn(QUESTION, json.dumps(researcher_first["messages"]))      # never the manager's own conversation
        self.assertEqual(manager_last["messages"][-1], {"role": "tool", "tool_call_id": "m1", "content": "30 calendar days"})

    def test_the_calculator_gets_only_the_numbers_the_manager_sends_and_the_two_calculation_tools(self):
        run, client = self.run_team([
            asks(to_calculator("m1")),
            asks(call("c1", "add_days", {"date": "2026-11-03", "days": 30})),
            says("The date is 2026-12-03."), says("The notice ends on 3 December 2026.")])
        calculator_first = client.requests[1]
        self.assertEqual(tool_names(calculator_first), ["calculate", "add_days", "remember"])
        self.assertEqual(calculator_first["messages"], [{"role": "system", "content": team.CALCULATOR_PROMPT},
                                                        {"role": "user", "content": "add 30 days to 2026-11-03"}])
        self.assertTrue(run.steps[1]["tool_calls"][0]["observation"].startswith("2026-12-03"))

    def test_two_hand_offs_are_merged_in_time_order_each_right_after_the_manager_step_that_asked(self):
        run, _client = self.run_team([
            asks(to_researcher("m1")), says("30 calendar days"),
            asks(to_calculator("m2")), asks(call("c1", "add_days", {"date": "2026-11-03", "days": 30})), says("2026-12-03"),
            says("final")])
        self.assertEqual([(s["n"], s["agent"], s["handoff"]) for s in run.steps],
                         [(1, "manager", None), (2, "researcher", 1), (3, "manager", None),
                          (4, "calculator", 2), (5, "calculator", 2), (6, "manager", None)])
        self.assertEqual([(h["agent"], h["after_manager_step"], h["state"]) for h in run.team["handoffs"]],
                         [("researcher", 1, "finished"), ("calculator", 2, "finished")])

    def test_the_caller_is_told_about_every_step_as_it_finishes_tagged_with_its_agent(self):
        told = []
        run, _client = self.run_team([asks(to_researcher("m1")), says("30 calendar days"), says("done")], on_step=told.append)
        self.assertEqual([(s["n"], s["agent"], s["handoff"], s["local_n"]) for s in told],
                         [(1, "researcher", 1, 1), (2, "manager", None, 1), (3, "manager", None, 2)])     # the manager's step that asked comes after the work it caused
        self.assertEqual(len(told), len(run.steps))
        self.assertEqual([s["agent"] for s in run.steps], ["manager", "researcher", "manager"])           # the returned list is in request order

    def test_a_hand_off_asked_for_with_unreadable_arguments_is_refused_and_the_next_good_one_belongs_to_the_next_manager_step(self):
        run, _client = self.run_team([asks(call("m1", "ask_policy_researcher", "{not json")), asks(to_researcher("m2")),
                                      says("30 calendar days"), says("done")])
        self.assertFalse(run.steps[0]["tool_calls"][0]["ok"])
        self.assertEqual([(h["after_manager_step"], h["state"]) for h in run.team["handoffs"]], [(2, "finished")])
        self.assertEqual([s["agent"] for s in run.steps], ["manager", "manager", "researcher", "manager"])

    def test_after_three_hand_offs_the_manager_still_sees_every_source_the_researcher_named(self):
        sources = ["Acme-Leave-Policy-2026.md", "Acme-Employment-Terms-2026.md", "Northstar-Remote-Work-Policy-2026.md"]
        facts = [f"[source: {name}] " + "A long sentence that fills the space before the next fact so the whole answer is far past the memory limit. " * 3
                 for name in sources]
        run, client = self.run_team([
            asks(to_researcher("m1", "first thing")), says(facts[0]),
            asks(to_researcher("m2", "second thing")), says(facts[1]),
            asks(to_researcher("m3", "third thing")), says(facts[2]),
            says("done")])
        last = json.dumps(client.requests[-1]["messages"])
        for name in sources:
            self.assertIn(name, last)                                          # the oldest result was shortened, its source tag was not
        self.assertIn("[shortened]", last)                                     # and it really was shortened: the test proves what it says

    def test_a_blank_question_is_refused_without_running_a_specialist(self):
        run, client = self.run_team([asks(to_researcher("m1", question="   ")), says(IDK)])
        self.assertEqual(client.script, [])
        self.assertEqual(run.team["handoffs"], [])
        refused = run.steps[0]["tool_calls"][0]
        self.assertFalse(refused["ok"])
        self.assertTrue(refused["observation"].startswith("ERROR: question must be a non-empty string"))


class InternalErrorTests(TeamTestCase):
    def test_a_bug_in_the_hand_off_code_is_recorded_with_its_type_and_the_manager_is_told_the_specialist_failed(self):
        real = loop.run_agent

        def breaks_for_the_researcher(question, tools, **kwargs):
            if kwargs.get("system_prompt") == team.RESEARCHER_PROMPT:
                raise KeyError("bug")
            return real(question, tools, **kwargs)

        client = FakeClient([asks(to_researcher("m1")), says(IDK)])
        with mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(loop, "run_agent", breaks_for_the_researcher):
            run = team.run_team(QUESTION, TOOLS)
        self.assertEqual(run.team["errors"], [{"agent": "researcher", "type": "KeyError"}])
        self.assertEqual([(h["agent"], h["state"], h["stop_reason"]) for h in run.team["handoffs"]], [("researcher", "not_finished", "internal_error")])
        self.assertEqual(run.team["per_agent"]["researcher"]["handoffs"], 1)                  # the hand-off is counted, not lost
        told = run.steps[0]["tool_calls"][0]
        self.assertFalse(told["ok"])
        self.assertIn("failed unexpectedly (KeyError)", told["observation"])
        self.assertEqual(run.stop_reason, "final")


class UsageTests(TeamTestCase):
    SCRIPT = [asks(to_researcher("m1"), prompt=100, completion=10),
              asks(call("r1", "search_policies", {"query": "notice"}), prompt=50, completion=5),
              says("30 days", prompt=80, completion=12), says("final", prompt=150, completion=14)]

    def test_every_agents_calls_and_tokens_are_counted_apart_and_add_up(self):
        run, _client = self.run_team(list(self.SCRIPT))
        per_agent = run.team["per_agent"]
        manager, researcher = per_agent["manager"], per_agent["researcher"]
        self.assertEqual((manager["calls"], manager["prompt_tokens"], manager["completion_tokens"]), (2, 250, 24))
        self.assertEqual((researcher["calls"], researcher["prompt_tokens"], researcher["completion_tokens"]), (2, 130, 17))
        self.assertEqual(per_agent["calculator"]["calls"], 0)
        self.assertEqual((researcher["handoffs"], per_agent["calculator"]["handoffs"]), (1, 0))
        self.assertEqual((run.usage["calls"], run.usage["prompt_tokens"], run.usage["completion_tokens"]), (4, 380, 41))

    def test_the_teams_own_total_matches_the_process_counters_so_nothing_is_missing(self):
        run, _client = self.run_team(list(self.SCRIPT))
        process = llm.usage_snapshot()
        self.assertEqual((run.usage["calls"], run.usage["prompt_tokens"], run.usage["completion_tokens"]),
                         (process["calls"], process["prompt_tokens"], process["completion_tokens"]))
        self.assertEqual((run.notes, run.team["warnings"], run.team["errors"]), ([], [], []))

    def test_a_call_made_outside_the_team_while_it_runs_is_reported_as_a_mismatch(self):
        stray = _testkit.fake_response("x", prompt_tokens=7, completion_tokens=3)

        def meddle(query, top_k=3):                      # a call from outside any agent, in the middle of this run
            with llm.call_scope("somebody-else"):
                llm.chat([], model="m1")
            return "[1] [source: x.md] text"

        tools = [Tool("search_policies", "s", SEARCH.parameters, meddle), calculator_tool(), date_tool()]
        run, _client = self.run_team([asks(to_researcher("m1")), asks(call("r1", "search_policies", {"query": "q"})), stray,
                                      says("a"), says("b")], tools=tools)
        self.assertEqual(len(run.team["warnings"]), 1)
        self.assertIn("usage mismatch", run.team["warnings"][0])
        self.assertEqual(run.notes, [])                                       # notes stay the manager's own saved notes
        self.assertEqual(run.usage["calls"], llm.usage_snapshot()["calls"])    # the run's usage is what the process counters moved by
        self.assertEqual(sum(row["calls"] for row in run.team["per_agent"].values()) + 1, run.usage["calls"])

    def test_every_model_call_is_in_the_call_log_tagged_with_its_agent_and_hand_off(self):
        run, _client = self.run_team(list(self.SCRIPT))
        log = run.team["call_log"]
        self.assertEqual([(call["agent"], call["handoff"]) for call in log],
                         [("manager", None), ("researcher", 1), ("researcher", 1), ("manager", None)])
        self.assertEqual(len(log), run.usage["calls"])
        self.assertEqual(sum(call["prompt_tokens"] for call in log), run.usage["prompt_tokens"])
        self.assertTrue(all(call["status"] == "ok" for call in log))

    def test_a_hand_off_record_keeps_who_what_and_how_it_ended_and_how_long_the_answer_was(self):
        run, _client = self.run_team(list(self.SCRIPT))
        handoff = run.team["handoffs"][0]
        self.assertEqual((handoff["agent"], handoff["question"], handoff["state"], handoff["stop_reason"]),
                         ("researcher", "notice period for a permanent employee", "finished", "final"))
        self.assertEqual((handoff["answer"], handoff["answer_chars"]), ("30 days", 7))
        self.assertEqual((handoff["calls"], handoff["prompt_tokens"], handoff["completion_tokens"]), (2, 130, 17))

    def test_the_step_tokens_add_up_to_the_usage_tokens(self):
        run, _client = self.run_team(list(self.SCRIPT))
        self.assertEqual(sum(s["tokens"]["prompt"] for s in run.steps), run.usage["prompt_tokens"])
        self.assertEqual(sum(s["tokens"]["completion"] for s in run.steps), run.usage["completion_tokens"])

    def test_a_specialist_that_breaks_after_it_has_called_the_model_still_has_its_calls_counted_and_no_mismatch_is_raised(self):
        real = loop.run_agent

        def breaks_after_one_call(question, tools, **kwargs):
            if kwargs.get("system_prompt") == team.RESEARCHER_PROMPT:
                llm.chat([{"role": "user", "content": question}], model="m")          # a real call inside the specialist's scope
                raise KeyError("bug after the call")
            return real(question, tools, **kwargs)

        client = FakeClient([asks(to_researcher("m1")), says("one call, then the bug", prompt=40, completion=4), says(IDK)])
        with mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(loop, "run_agent", breaks_after_one_call):
            run = team.run_team(QUESTION, TOOLS)
        self.assertEqual(run.team["per_agent"]["researcher"]["calls"], 1)
        self.assertEqual(run.team["warnings"], [])                                       # the agents' own calls still add up to the process counters
        self.assertEqual(run.usage["prompt_tokens"], 10 + 40 + 10)

    def test_each_run_starts_with_a_clean_record(self):
        first, _ = self.run_team(list(self.SCRIPT))
        second, _ = self.run_team(list(self.SCRIPT))
        self.assertEqual(len(first.team["handoffs"]), len(second.team["handoffs"]))
        self.assertEqual(second.team["handoffs"][0]["handoff"], 1)
        self.assertEqual(second.usage["calls"], 4)


if __name__ == "__main__":
    unittest.main()
