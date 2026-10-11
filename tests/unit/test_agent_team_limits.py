"""Week 10: what the team does when a specialist fails, when the budget runs out and when it is set up wrongly."""
import contextlib
import unittest
from unittest import mock

from openai import RateLimitError

import _testkit
from app import llm
from app.agent import loop, team
from app.agent.toolkit import calculator_tool, date_tool
from app.agent.tools import Tool
from test_agent_loop import FakeClient, asks, call, says
from test_agent_team import IDK, QUESTION, SEARCH, TOOLS, TeamTestCase, tool_names, to_calculator, to_researcher
from evals.agent_tasks import PATH_PROBES, TASKS
from test_llm import DAILY_BODY, status_error


@contextlib.contextmanager
def watching_the_team():
    """Collect the _Team that run_team makes, so a test can read the log it kept even when the run raised instead of returning."""
    made, real = [], team._Team

    def make(*args, **kwargs):
        made.append(real(*args, **kwargs))
        return made[-1]

    with mock.patch.object(team, "_Team", make):
        yield made


class FailureTests(TeamTestCase):
    def test_a_specialist_that_cannot_finish_comes_back_as_an_error_the_manager_can_react_to(self):
        run, _client = self.run_team([asks(to_researcher("m1")), says(""), says(IDK)])
        handoff = run.team["handoffs"][0]
        self.assertEqual((handoff["state"], handoff["stop_reason"], handoff["answer"]), ("not_finished", "empty_reply", None))
        asked = run.steps[0]["tool_calls"][0]
        self.assertFalse(asked["ok"])
        self.assertTrue(asked["observation"].startswith("ERROR: the researcher could not finish (it stopped on: empty_reply)"))
        self.assertEqual((run.stop_reason, run.answer), ("final", IDK))             # the manager recovered and said so
        self.assertEqual([(s["agent"], s["kind"]) for s in run.steps],
                         [("manager", "tool"), ("researcher", "error"), ("manager", "final")])

    def test_a_provider_failure_inside_a_specialist_is_a_failed_hand_off_not_a_crash(self):
        run, _client = self.run_team([asks(to_researcher("m1")), RuntimeError("provider down"), says(IDK)])
        self.assertEqual((run.team["handoffs"][0]["state"], run.team["handoffs"][0]["stop_reason"]), ("not_finished", "error"))
        self.assertIn("RuntimeError: provider down", run.steps[1]["content"])
        self.assertEqual(run.stop_reason, "final")

    def test_the_manager_stops_on_its_own_step_limit_and_keeps_the_hand_off_it_made(self):
        run, _client = self.run_team([asks(to_researcher("m1")), says("30 calendar days")], max_steps=1)
        self.assertEqual(run.stop_reason, "max_steps")
        self.assertIsNone(run.answer)
        self.assertEqual([s["agent"] for s in run.steps], ["manager", "researcher"])

    def test_asking_the_same_specialist_the_same_thing_again_is_stopped_by_the_loops_repeat_guard(self):
        run, client = self.run_team([asks(to_researcher("m1")), says("30 calendar days"),
                                     asks(to_researcher("m2")), asks(to_researcher("m3"))])
        self.assertEqual(run.stop_reason, "repeated_call")
        self.assertEqual(len(run.team["handoffs"]), 1)                                # the specialist ran once, not three times
        self.assertEqual(client.script, [])


class QuotaTests(TeamTestCase):
    def test_a_daily_quota_stop_inside_a_specialist_is_raised_even_if_the_manager_could_still_answer(self):
        script = [asks(to_researcher("m1")), status_error(RateLimitError, 429, DAILY_BODY), says("answering anyway")]
        with self.assertRaises(llm.QuotaExhausted):
            self.run_team(script)

    def test_a_daily_quota_stop_in_the_managers_own_call_is_raised_too(self):
        script = [asks(to_researcher("m1")), status_error(RateLimitError, 429, DAILY_BODY), status_error(RateLimitError, 429, DAILY_BODY)]
        with self.assertRaises(llm.QuotaExhausted):
            self.run_team(script)

    def test_the_manager_is_told_not_to_ask_again_when_a_specialist_hits_the_quota(self):
        client = FakeClient([asks(to_researcher("m1")), status_error(RateLimitError, 429, DAILY_BODY), says("answering anyway")])
        with mock.patch.object(llm, "_get_client", return_value=client):
            with self.assertRaises(llm.QuotaExhausted):
                team.run_team(QUESTION, TOOLS)
        told = client.requests[-1]["messages"][-1]
        self.assertEqual(told["role"], "tool")
        self.assertIn("daily quota is used up", told["content"])


class QuotaStopTests(TeamTestCase):
    def test_a_second_hand_off_in_the_step_where_the_quota_ran_out_is_refused_and_makes_no_provider_request(self):
        client = FakeClient([asks(to_researcher("m1"), to_calculator("m2")), status_error(RateLimitError, 429, DAILY_BODY),
                             status_error(RateLimitError, 429, DAILY_BODY), status_error(RateLimitError, 429, DAILY_BODY)])
        with mock.patch.object(llm, "_get_client", return_value=client), watching_the_team() as made:
            with self.assertRaises(llm.QuotaExhausted):
                team.run_team(QUESTION, TOOLS)
        asked_by = [request["messages"][0]["content"] for request in client.requests]
        self.assertEqual(asked_by, [team.MANAGER_PROMPT, team.RESEARCHER_PROMPT, team.MANAGER_PROMPT])      # no request from the calculator
        heard_first, heard_second = [message["content"] for message in client.requests[-1]["messages"][-2:]]
        self.assertIn("daily quota is used up", heard_first)
        self.assertIn("calculator was not started", heard_second)
        self.assertIn("Do not ask again", heard_second)
        self.assertEqual([(h["handoff"], h["agent"], h["state"], h["stop_reason"], h["calls"]) for h in made[0].handoffs],
                         [(1, "researcher", "not_finished", "quota_exhausted", 0), (2, "calculator", "refused", "quota_exhausted", 0)])

    def test_the_hand_off_the_quota_stopped_is_closed_with_the_time_it_spent_before_the_run_is_raised(self):
        now = {"t": 0.0}

        class TickingClient(FakeClient):                 # every model request takes 15 seconds on the fake clock, a failed one too
            def _create(self, **kwargs):
                now["t"] += 15.0
                return super()._create(**kwargs)

        client = TickingClient([asks(to_researcher("m1")), status_error(RateLimitError, 429, DAILY_BODY), status_error(RateLimitError, 429, DAILY_BODY)])
        with mock.patch.object(llm, "_get_client", return_value=client), watching_the_team() as made:
            with self.assertRaises(llm.QuotaExhausted):
                team.run_team(QUESTION, TOOLS, clock=lambda: now["t"])
        record = made[0].handoffs[0]
        self.assertEqual((record["state"], record["stop_reason"], record["seconds"]), ("not_finished", "quota_exhausted", 15.0))
        self.assertEqual(len(made[0].handoffs), 1)


class BudgetTests(TeamTestCase):
    def test_the_specialist_is_handed_only_what_is_left_of_the_teams_token_budget(self):
        run, client = self.run_team([
            asks(to_researcher("m1"), prompt=60, completion=10),                                    # the manager spends 70 of 100
            asks(call("r1", "search_policies", {"query": "x"}), prompt=40, completion=5)],         # the researcher passes the 30 left
            max_total_tokens=100)
        self.assertEqual(client.script, [])
        self.assertEqual(run.team["handoffs"][0]["stop_reason"], "token_budget")
        self.assertEqual(run.stop_reason, "token_budget")                                          # and the manager is out of budget too
        self.assertEqual(run.usage["prompt_tokens"] + run.usage["completion_tokens"], 115)

    def test_a_second_hand_off_in_the_same_step_is_refused_once_the_budget_is_spent(self):
        run, _client = self.run_team([
            asks(to_researcher("m1"), to_calculator("m2"), prompt=60, completion=10),
            says("30 calendar days", prompt=40, completion=5)], max_total_tokens=100)
        self.assertEqual([(h["agent"], h["state"]) for h in run.team["handoffs"]], [("researcher", "finished"), ("calculator", "refused")])
        refused = run.steps[0]["tool_calls"][1]
        self.assertFalse(refused["ok"])
        self.assertTrue(refused["observation"].startswith("ERROR: the team's token or time budget is spent"))
        self.assertEqual(run.team["per_agent"]["calculator"]["handoffs"], 0)                      # it never ran

    def test_a_budget_refusal_is_followed_by_no_model_call_so_it_promises_the_manager_nothing(self):
        run, client = self.run_team([
            asks(to_researcher("m1"), to_calculator("m2"), prompt=60, completion=10),
            says("30 calendar days", prompt=40, completion=5)], max_total_tokens=100)
        self.assertEqual(len(client.requests), 2)                                                   # the manager never gets to read the refusal
        self.assertEqual((run.stop_reason, run.answer), ("token_budget", None))
        self.assertEqual(run.steps[0]["tool_calls"][1]["observation"], "ERROR: the team's token or time budget is spent, so nothing more can be handed over.")

    def test_a_hand_off_asked_for_after_the_time_ran_out_is_refused_like_one_asked_for_after_the_tokens_ran_out(self):
        now = {"t": 0.0}

        def slow_search(query, top_k=3):
            now["t"] += 100.0
            return "[1] [source: x.md] text"

        tools = [Tool("search_policies", "s", SEARCH.parameters, slow_search), calculator_tool(), date_tool()]
        run, client = self.run_team([asks(to_researcher("m1"), to_calculator("m2")), asks(call("r1", "search_policies", {"query": "x"}))],
                                    tools=tools, timeout_seconds=60, clock=lambda: now["t"])
        self.assertEqual([(h["agent"], h["state"], h["stop_reason"]) for h in run.team["handoffs"]],
                         [("researcher", "not_finished", "timeout"), ("calculator", "refused", "budget")])
        self.assertEqual(client.script, [])
        self.assertEqual((run.stop_reason, run.answer), ("timeout", None))                         # and the manager makes no further call
        self.assertEqual(run.team["per_agent"]["calculator"]["handoffs"], 0)

    def test_the_specialist_run_is_given_exactly_the_time_and_tokens_that_are_left(self):
        now, given = {"t": 0.0}, []

        class TickingClient(FakeClient):                     # every model call takes 15 seconds
            def _create(self, **kwargs):
                now["t"] += 15.0
                return super()._create(**kwargs)

        def spy(*args, **kwargs):
            given.append(kwargs)
            return real_run_agent(*args, **kwargs)

        real_run_agent = loop.run_agent
        client = TickingClient([asks(to_researcher("m1"), prompt=60, completion=10), says("30 calendar days", prompt=20, completion=5),
                                says("done", prompt=30, completion=5)])
        with mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(loop, "run_agent", spy):
            team.run_team(QUESTION, TOOLS, max_total_tokens=1000, timeout_seconds=100, clock=lambda: now["t"])
        manager_options, researcher_options = given[0], given[1]
        self.assertEqual((manager_options["max_total_tokens"], manager_options["timeout_seconds"]), (1000, 100))
        self.assertEqual(researcher_options["max_total_tokens"], 1000 - 70)             # what the manager's first call left
        self.assertEqual(researcher_options["timeout_seconds"], 100 - 15)               # what the clock left after it

    def test_the_specialists_get_their_own_step_limits_and_every_loop_gets_the_per_tool_cap(self):
        given = []
        real_run_agent = loop.run_agent

        def spy(*args, **kwargs):
            given.append(kwargs)
            return real_run_agent(*args, **kwargs)

        client = FakeClient([asks(to_researcher("m1"), to_calculator("m2")), says("30 days"), says("2026-12-03"), says("done")])
        with mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(loop, "run_agent", spy):
            team.run_team(QUESTION, TOOLS, max_calls_per_tool=3)
        manager_options, researcher_options, calculator_options = given
        self.assertEqual((researcher_options["max_steps"], calculator_options["max_steps"]), (8, 4))
        self.assertEqual(manager_options["max_steps"], 6)                                       # the manager's own limit: the setting the test case sets
        self.assertEqual({options["max_calls_per_tool"] for options in given}, {3})

    def test_the_time_and_token_limit_a_specialist_is_handed_is_what_is_left(self):
        now = {"t": 0.0}

        def slow_search(query, top_k=3):
            now["t"] += 100.0
            return "[1] [source: x.md] text"

        tools = [Tool("search_policies", "s", SEARCH.parameters, slow_search), calculator_tool(), date_tool()]
        run, _client = self.run_team([asks(to_researcher("m1")), asks(call("r1", "search_policies", {"query": "x"}))],
                                     tools=tools, timeout_seconds=60, clock=lambda: now["t"])
        self.assertEqual(run.team["handoffs"][0]["stop_reason"], "timeout")
        self.assertEqual(run.stop_reason, "timeout")


class SetupTests(TeamTestCase):
    def test_it_refuses_to_start_without_the_tools_the_specialists_need(self):
        with self.assertRaises(ValueError) as caught:
            team.run_team(QUESTION, [calculator_tool(), date_tool()])
        self.assertIn("researcher", str(caught.exception))
        self.assertIn("search_policies", str(caught.exception))

    def test_every_agent_has_a_card_and_an_unknown_one_is_an_error(self):
        for name in team.AGENTS:
            card = team.agent_summary(name)
            self.assertEqual(card["name"], name)
            for key in ("skills", "description", "input", "output"):
                self.assertTrue(card[key], (name, key))
        self.assertEqual(team.agent_summary("researcher")["skills"], ["search_policies"])
        self.assertEqual(team.agent_summary("calculator")["skills"], ["calculate", "add_days"])
        with self.assertRaises(ValueError):
            team.agent_summary("intern")

    def test_the_manager_is_offered_one_tool_per_specialist_and_each_description_is_the_one_in_that_specialists_card(self):
        _run, client = self.run_team([says(IDK)])
        offered = {spec["function"]["name"]: spec["function"]["description"] for spec in client.requests[0]["tools"]
                   if spec["function"]["name"] != "remember"}
        self.assertEqual(offered, {team.SPECIALISTS[name]["tool"]: team.agent_summary(name)["description"] for name in team.SPECIALISTS})
        self.assertEqual(client.requests[0]["messages"][0]["content"], team.MANAGER_PROMPT)

    def test_the_prompts_name_the_tools_they_rely_on(self):
        for tool in ("ask_policy_researcher", "ask_calculator"):
            self.assertIn(tool, team.MANAGER_PROMPT)
        self.assertIn("search_policies", team.RESEARCHER_PROMPT)
        for tool in ("calculate", "add_days"):
            self.assertIn(tool, team.CALCULATOR_PROMPT)
        for prompt in (team.MANAGER_PROMPT, team.RESEARCHER_PROMPT):
            self.assertIn(IDK, prompt)                                       # the refusal sentence the rule checks look for

    def test_every_sentence_the_team_borrows_from_the_single_agent_is_still_word_for_word_in_its_prompt(self):
        for name, sentence in team.FROM_SINGLE.items():
            with self.subTest(sentence=name):
                self.assertIn(sentence, loop.SYSTEM_PROMPT)

    def test_each_team_prompt_carries_the_borrowed_sentences_that_belong_to_it(self):
        for sentence in ("final", "idk", "disagree", "untrusted"):
            self.assertIn(team.FROM_SINGLE[sentence], team.MANAGER_PROMPT)
        for sentence in ("memory", "search", "idk", "disagree", "untrusted"):
            self.assertIn(team.FROM_SINGLE[sentence], team.RESEARCHER_PROMPT)
        self.assertIn(team.FROM_SINGLE["tools"], team.CALCULATOR_PROMPT)

    def test_the_researcher_is_told_to_search_a_second_time_before_it_says_the_documents_lack_the_answer(self):
        self.assertIn("Never say the documents lack the answer after a single search", team.RESEARCHER_PROMPT)
        self.assertLess(team.RESEARCHER_PROMPT.index("single search"), team.RESEARCHER_PROMPT.index(team.FROM_SINGLE["idk"]))   # before the refusal rule

    def test_the_researcher_is_told_to_start_every_line_with_its_source_so_shortening_cannot_cut_a_citation_off(self):
        self.assertIn("Start every line with the document it came from as [source: <document name>]", team.RESEARCHER_PROMPT)

    def test_no_team_prompt_or_hand_off_description_leans_on_a_race_task(self):
        words = [spec["description"] for spec in team.SPECIALISTS.values()] + [team.MANAGER_PROMPT, team.RESEARCHER_PROMPT, team.CALCULATOR_PROMPT]
        text = " ".join(words).lower()
        for task in TASKS + PATH_PROBES:
            self.assertNotIn(task["question"].lower(), text, task["id"])
            for fact in task.get("source_facts", []):
                self.assertNotIn(fact.lower(), text, task["id"])
        for example in ("2026-11-03", "3 november", "permanent employee", "carry forward", "parental leave", "7 calendar days"):
            self.assertNotIn(example, text)

    def test_every_agent_runs_the_loop_with_its_defaults_so_the_scratchpad_is_not_a_difference_from_the_single_agent(self):
        _run, client = self.run_team([asks(to_researcher("m1")), says("30 days"), says("done")])
        for request in client.requests:
            self.assertEqual(tool_names(request)[-1], "remember")


if __name__ == "__main__":
    unittest.main()
