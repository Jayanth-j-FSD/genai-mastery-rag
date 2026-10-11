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
        self.assertEqual((run.question, run.stop_reason, run.finished, run.answer), (QUESTION, "final", True, answer))
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
                         [(2, "researcher", 1, 1), (1, "manager", None, 1), (3, "manager", None, 2)])     # the manager's step that asked comes after the work it caused, under the number it has in the saved run
        self.assertEqual(len(told), len(run.steps))
        self.assertEqual([s["agent"] for s in run.steps], ["manager", "researcher", "manager"])           # the returned list is in request order

    def test_every_step_the_caller_is_told_is_the_same_step_the_saved_run_holds_under_the_same_number(self):
        told = []
        run, _client = self.run_team([
            asks(to_researcher("m1"), to_calculator("m2")), says("30 calendar days"),
            asks(call("c1", "add_days", {"date": "2026-11-03", "days": 30})), says("2026-12-03"),
            asks(to_researcher("m3", "second thing")), says("another fact"), says("final")], on_step=told.append)
        self.assertEqual([s["n"] for s in run.steps], list(range(1, 8)))
        self.assertEqual(sorted(told, key=lambda s: s["n"]), run.steps)               # the console and the saved file cannot disagree about a step

    def test_every_hand_off_belongs_to_a_manager_step_that_is_saved_and_no_step_that_was_told_is_lost_even_when_the_run_is_cut_short(self):
        shapes = [([asks(to_researcher("m1")), says("30 calendar days")], dict(max_steps=1)),                      # the manager stops right after the hand-off
                  ([asks(to_researcher("m1"), prompt=60, completion=10), says("30 days", prompt=40, completion=5)], dict(max_total_tokens=100)),
                  ([asks(to_researcher("m1")), RuntimeError("provider down"), says(IDK)], {}),                   # the specialist fails, the manager goes on
                  ([asks(to_researcher("m1"), to_calculator("m2")), says("30 days"), says("2026-12-03"), says(IDK)], {})]
        for script, options in shapes:
            with self.subTest(options=options):
                told = []
                run, _client = self.run_team(script, on_step=told.append, **options)
                manager_steps = [s for s in run.steps if s["agent"] == "manager"]
                for handoff in run.team["handoffs"]:
                    self.assertLessEqual(handoff["after_manager_step"], len(manager_steps))
                self.assertEqual(len(run.steps), len(told))

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

    def test_the_question_is_handed_over_and_recorded_without_the_spaces_around_it(self):
        run, client = self.run_team([asks(to_researcher("m1", "  notice period  ")), says("30 calendar days"), says("done")])
        self.assertEqual(client.requests[1]["messages"][1], {"role": "user", "content": "notice period"})
        self.assertEqual(run.team["handoffs"][0]["question"], "notice period")

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


class CrashedSpecialistTests(TeamTestCase):
    def test_a_specialist_that_dies_after_making_calls_still_shows_them_in_its_hand_off_record_and_its_steps_in_the_run(self):
        def crashes_on_a_researcher_step(step):             # a bug in the caller's display, say: the loop has already finished that step
            if step["agent"] == "researcher":
                raise ValueError("the display broke")

        told = []
        run, client = self.run_team([
            asks(to_researcher("m1"), prompt=100, completion=10),
            asks(call("r1", "search_policies", {"query": "notice"}), prompt=80, completion=8),
            says(IDK, prompt=60, completion=6)], on_step=lambda step: (told.append(step), crashes_on_a_researcher_step(step)))
        self.assertEqual(client.script, [])
        handoff = run.team["handoffs"][0]
        self.assertEqual((handoff["state"], handoff["stop_reason"]), ("not_finished", "internal_error"))
        self.assertEqual((handoff["calls"], handoff["prompt_tokens"], handoff["completion_tokens"]), (1, 80, 8))
        researcher = run.team["per_agent"]["researcher"]
        self.assertEqual((researcher["calls"], researcher["prompt_tokens"], researcher["completion_tokens"], researcher["handoffs"]), (1, 80, 8, 1))
        self.assertEqual([(s["n"], s["agent"], s["handoff"]) for s in run.steps], [(1, "manager", None), (2, "researcher", 1), (3, "manager", None)])
        self.assertEqual(sum(s["tokens"]["prompt"] for s in run.steps), run.usage["prompt_tokens"])          # no model call is missing from the steps
        self.assertEqual([(c["agent"], c["handoff"], c["prompt_tokens"]) for c in run.team["call_log"]],
                         [("manager", None, 100), ("researcher", 1, 80), ("manager", None, 60)])
        self.assertEqual(sorted(told, key=lambda s: s["n"]), run.steps)                                    # what was told is what was saved
        self.assertEqual((run.team["errors"], run.team["warnings"]), ([{"agent": "researcher", "type": "ValueError"}], []))
        self.assertIn("failed unexpectedly (ValueError)", run.steps[0]["tool_calls"][0]["observation"])

    def test_a_hand_off_that_breaks_before_it_is_written_down_is_still_written_down_as_not_finished(self):
        client = FakeClient([asks(to_researcher("m1")), says(IDK)])
        with mock.patch.object(llm, "_get_client", return_value=client), \
                mock.patch.object(team._Team, "tokens_used", side_effect=KeyError("bug")):
            run = team.run_team(QUESTION, TOOLS)
        self.assertEqual([(h["agent"], h["state"], h["stop_reason"], h["calls"]) for h in run.team["handoffs"]], [("researcher", "not_finished", "internal_error", 0)])
        self.assertEqual(run.team["errors"], [{"agent": "researcher", "type": "KeyError"}])
        self.assertEqual(run.team["per_agent"]["researcher"]["handoffs"], 1)


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

    def test_a_stray_call_that_reported_no_tokens_is_still_reported_as_a_mismatch(self):
        stray = _testkit.fake_response("x", prompt_tokens=0, completion_tokens=0)

        def meddle(query, top_k=3):                      # one more call than the agents made, and it counted no tokens
            with llm.call_scope("somebody-else"):
                llm.chat([], model="m1")
            return "[1] [source: x.md] text"

        tools = [Tool("search_policies", "s", SEARCH.parameters, meddle), calculator_tool(), date_tool()]
        run, _client = self.run_team([asks(to_researcher("m1")), asks(call("r1", "search_policies", {"query": "q"})), stray,
                                      says("a"), says("b")], tools=tools)
        self.assertEqual(len(run.team["warnings"]), 1)
        self.assertEqual(run.usage["prompt_tokens"], sum(row["prompt_tokens"] for row in run.team["per_agent"].values()))      # the tokens agree: only the calls do not

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
        handoff = run.team["handoffs"][0]
        self.assertEqual((handoff["state"], handoff["stop_reason"]), ("not_finished", "internal_error"))
        self.assertEqual((handoff["calls"], handoff["prompt_tokens"], handoff["completion_tokens"]), (1, 40, 4))   # the hand-off record agrees with the per-agent total

    def test_an_agents_seconds_over_several_hand_offs_are_summed_without_float_noise(self):
        now, seconds = {"t": 0.0}, iter([0.5, 0.1, 0.5, 0.2, 0.5])

        class TickingClient(FakeClient):
            def _create(self, **kwargs):
                now["t"] += next(seconds)
                return super()._create(**kwargs)

        client = TickingClient([asks(to_researcher("m1", "first thing")), says("fact one"), asks(to_researcher("m2", "second thing")),
                                says("fact two"), says("done")])
        with mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(llm.time, "monotonic", lambda: now["t"]):
            run = team.run_team(QUESTION, TOOLS, clock=lambda: now["t"])
        per_agent = run.team["per_agent"]
        self.assertEqual((per_agent["manager"]["api_seconds"], per_agent["researcher"]["api_seconds"]), (1.5, 0.3))      # 0.1 + 0.2 is 0.30000000000000004 until it is rounded
        self.assertEqual(run.usage["api_seconds"], 1.8)

    def test_the_seconds_a_rate_limit_made_each_hand_off_wait_are_kept_in_its_record(self):
        now = {"t": 1000.0}

        def sleep(seconds):
            now["t"] += seconds

        llm._call_times.clear()
        self.addCleanup(llm._call_times.clear)
        client = FakeClient(list(self.SCRIPT))
        with mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(llm.time, "monotonic", lambda: now["t"]), \
                mock.patch.object(llm.time, "sleep", sleep):
            run = team.run_team(QUESTION, TOOLS, rpm=2, clock=lambda: now["t"])        # the third call of the four has to wait for a slot
        waited = run.team["handoffs"][0]["wait_seconds"]
        self.assertGreater(waited, 59.0)
        self.assertEqual(waited, run.team["per_agent"]["researcher"]["wait_seconds"])
        self.assertEqual(run.team["per_agent"]["manager"]["wait_seconds"], 0.0)
        self.assertEqual(run.usage["wait_seconds"], waited)

    def test_a_difference_in_tokens_alone_between_the_agents_and_the_process_counters_is_reported_as_a_mismatch(self):
        def drifts(query, top_k=3):                      # the process counters move by tokens, with no call and no agent to blame
            llm._usage["prompt_tokens"] += 5
            return "[1] [source: x.md] text"

        tools = [Tool("search_policies", "s", SEARCH.parameters, drifts), calculator_tool(), date_tool()]
        run, _client = self.run_team([asks(to_researcher("m1")), asks(call("r1", "search_policies", {"query": "q"})), says("a"), says("b")], tools=tools)
        self.assertEqual(len(run.team["warnings"]), 1)
        self.assertIn("usage mismatch", run.team["warnings"][0])
        self.assertEqual(run.usage["calls"], sum(row["calls"] for row in run.team["per_agent"].values()))      # the calls agree: only the tokens do not

    def test_the_seconds_each_agent_and_hand_off_spent_in_the_model_add_up_to_the_teams_total(self):
        now, seconds = {"t": 0.0}, iter([1.0, 2.0, 4.0, 8.0])

        class TickingClient(FakeClient):                 # every model call takes the next number of seconds on the fake clock
            def _create(self, **kwargs):
                now["t"] += next(seconds)
                return super()._create(**kwargs)

        client = TickingClient(list(self.SCRIPT))
        with mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(llm.time, "monotonic", lambda: now["t"]):
            run = team.run_team(QUESTION, TOOLS, clock=lambda: now["t"])
        per_agent = run.team["per_agent"]
        self.assertEqual((per_agent["manager"]["api_seconds"], per_agent["researcher"]["api_seconds"]), (9.0, 6.0))
        self.assertEqual(run.team["handoffs"][0]["api_seconds"], 6.0)
        self.assertEqual(run.usage["api_seconds"], 15.0)
        self.assertEqual(run.elapsed_seconds, 15.0)                                     # the team's own clock, start to finish
        self.assertEqual([c["seconds"] for c in run.team["call_log"]], [1.0, 2.0, 4.0, 8.0])
        self.assertEqual(run.team["warnings"], [])

    def test_the_notes_in_the_run_are_the_managers_own_and_the_model_is_the_one_every_agent_was_asked_for(self):
        run, client = self.run_team([
            asks(call("n1", "remember", {"fact": "manager note"})), asks(to_researcher("m1")),
            asks(call("r1", "remember", {"fact": "researcher note"})), says("30 days"), says("done")], model="model-x")
        self.assertEqual(run.notes, ["manager note"])
        self.assertEqual(run.model, "model-x")
        self.assertEqual({request["model"] for request in client.requests}, {"model-x"})

    def test_each_run_starts_with_a_clean_record(self):
        first, _ = self.run_team(list(self.SCRIPT))
        second, _ = self.run_team(list(self.SCRIPT))
        self.assertEqual(len(first.team["handoffs"]), len(second.team["handoffs"]))
        self.assertEqual(second.team["handoffs"][0]["handoff"], 1)
        self.assertEqual(second.usage["calls"], 4)


if __name__ == "__main__":
    unittest.main()
