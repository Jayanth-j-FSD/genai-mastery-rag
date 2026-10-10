"""The fixed workflow, the race that compares it with the agent, and the integrity of the task set."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import _testkit
from _testkit import build_index, chunk, fake_response, isolated_index, patched_embeddings
from app import llm
from app.agent import loop, workflow
from app.agent.loop import AgentRun
from app.agent.tools import add_days, calculate
from app.config import settings
from app.rag import diagnose, loader
from evals import checks, race
from evals.agent_tasks import TASKS, get_tasks

CORPUS = {d["source"]: d["text"] for d in loader.load_documents(settings.corpus_dir)}
NORMALISED = {name: diagnose._normalize(text.replace("*", "")) for name, text in CORPUS.items()}


class FakeClient:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact", retrieval_mode="dense"))
        self.enterContext(patched_embeddings())
        build_index([chunk("leave.md#0", "Employees receive 18 days of annual leave per calendar year."),
                     chunk("notice.md#0", "A permanent employee gives 30 calendar days of written notice."),
                     chunk("remote.md#0", "Remote work is allowed after 60 days of service.")])
        for patcher in (mock.patch.object(settings, "llm_rpm", 0), mock.patch.object(settings, "llm_max_retries", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)
        llm.reset_usage()

    def run_workflow(self, script, **kwargs):
        client = FakeClient(script)
        with mock.patch.object(llm, "_get_client", return_value=client):
            return workflow.run_workflow("How many days of annual leave?", **kwargs), client

    def test_it_retrieves_once_and_asks_the_model_exactly_once(self):
        run, client = self.run_workflow([fake_response("18 days. [source: leave.md]", prompt_tokens=300, completion_tokens=20)])
        self.assertEqual((run.stop_reason, run.finished, run.answer), ("final", True, "18 days. [source: leave.md]"))
        self.assertEqual([s["kind"] for s in run.steps], ["retrieve", "final"])
        self.assertEqual(len(client.requests), 1)                                        # one model call, no tools offered
        self.assertNotIn("tools", client.requests[0])
        self.assertEqual((run.usage["calls"], run.usage["prompt_tokens"]), (1, 300))

    def test_the_retrieve_step_looks_like_a_search_so_both_approaches_can_be_scored_alike(self):
        run, _ = self.run_workflow([fake_response("ok")])
        call = run.steps[0]["tool_calls"][0]
        self.assertEqual((call["name"], call["ok"]), ("search_policies", True))
        retrieved = race.retrieved_from_steps(run)
        self.assertEqual({c["source"] for c in retrieved}, {"leave.md", "notice.md", "remote.md"})

    def test_the_prompt_carries_the_rules_the_passages_and_the_question(self):
        _, client = self.run_workflow([fake_response("ok")])
        system, user = client.requests[0]["messages"]
        self.assertIn("show the working", system["content"])
        self.assertIn(loop.IDK, system["content"])
        self.assertIn("untrusted", system["content"].lower())
        self.assertIn("[1] [source:", user["content"])
        self.assertTrue(user["content"].rstrip().endswith("Question: How many days of annual leave?"))

    def test_it_looks_at_six_passages_by_default_and_can_be_told_otherwise(self):
        with mock.patch.object(workflow.retriever, "retrieve_for_mode", wraps=workflow.retriever.retrieve_for_mode) as spy:
            self.run_workflow([fake_response("ok")])
            self.run_workflow([fake_response("ok")], top_k=2)
        self.assertEqual([c.args[1] for c in spy.call_args_list], [6, 2])

    def test_an_empty_reply_is_a_failure_not_a_refusal(self):
        run, _ = self.run_workflow([fake_response("")])
        self.assertEqual((run.stop_reason, run.answer, run.finished, run.steps[-1]["kind"]), ("empty_reply", None, False, "error"))
        self.assertIn("empty reply", run.steps[-1]["content"])

    def test_a_reply_with_no_choices_is_an_error_like_it_is_in_the_agent(self):
        run, _ = self.run_workflow([SimpleNamespace(choices=[], usage=None)])
        self.assertEqual((run.stop_reason, run.answer, run.steps[-1]["kind"]), ("error", None, "error"))
        self.assertIn("no reply", run.steps[-1]["content"])

    def test_the_recorded_search_arguments_are_valid_json_even_with_quotes_in_the_question(self):
        run, _ = self.run_workflow([fake_response("ok")])
        self.assertEqual(json.loads(run.steps[0]["tool_calls"][0]["arguments"]), {"query": "How many days of annual leave?"})
        quoted = 'What is the "probation" period?'
        with mock.patch.object(llm, "_get_client", return_value=FakeClient([fake_response("ok")])):
            run = workflow.run_workflow(quoted)
        self.assertEqual(json.loads(run.steps[0]["tool_calls"][0]["arguments"]), {"query": quoted})

    def test_a_provider_failure_is_recorded_not_raised_and_a_quota_is_not_swallowed(self):
        import httpx
        from openai import InternalServerError
        failure = InternalServerError("down", response=httpx.Response(503, request=httpx.Request("POST", "http://x")), body=None)
        run, _ = self.run_workflow([failure])
        self.assertEqual((run.stop_reason, run.answer, run.steps[-1]["kind"]), ("error", None, "error"))
        with mock.patch.object(llm, "chat", side_effect=llm.QuotaExhausted("used up")):
            with self.assertRaises(llm.QuotaExhausted):
                workflow.run_workflow("q")

    def test_nothing_indexed_still_gives_an_answer_record(self):
        _testkit.store.reset_collection()
        run, client = self.run_workflow([fake_response(loop.IDK)])
        self.assertIn("No passages found", run.steps[0]["tool_calls"][0]["observation"])
        self.assertIn("(no passages were found)", client.requests[0]["messages"][1]["content"])


def agent_run(answer, observation="", reason="final", calls=1, prompt=100, completion=10, api=1.0):
    steps = []
    if observation:
        steps.append({"n": 1, "kind": "tool", "content": "", "seconds": 0.1, "tokens": {"prompt": 0, "completion": 0},
                      "tool_calls": [{"name": "search_policies", "arguments": "{}", "observation": observation, "ok": True}]})
    steps.append({"n": len(steps) + 1, "kind": "final" if answer else "error", "content": answer or "", "tool_calls": [],
                  "seconds": 0.1, "tokens": {"prompt": 0, "completion": 0}})
    return AgentRun(question="q", answer=answer, stop_reason=reason, steps=steps, elapsed_seconds=2.0,
                    usage={"calls": calls, "prompt_tokens": prompt, "completion_tokens": completion, "api_seconds": api, "wait_seconds": 0.0})


LEAVE = "[1] [source: Acme-Leave-Policy-2026.md] Eligible employees may take 16 weeks of paid parental leave."
TASK = {"id": "t", "question": "How many weeks?", "expected_sources": ["Acme-Leave-Policy-2026.md"], "expect_contains": [],
        "expect_all": ["16 weeks"], "should_refuse": False}


class RaceHelperTests(unittest.TestCase):
    def test_passages_are_rebuilt_from_the_search_results_and_deduplicated(self):
        run = agent_run("x", observation=LEAVE + "\n" + LEAVE + "\n[2] [source: b.md] Second passage.")
        self.assertEqual(race.retrieved_from_steps(run), [
            {"source": "Acme-Leave-Policy-2026.md", "text": "Eligible employees may take 16 weeks of paid parental leave."},
            {"source": "b.md", "text": "Second passage."}])

    def test_a_failed_search_contributes_no_passages(self):
        run = agent_run("x", observation=LEAVE)
        run.steps[0]["tool_calls"][0]["ok"] = False
        self.assertEqual(race.retrieved_from_steps(run), [])

    def test_only_documents_that_were_really_retrieved_can_be_cited(self):
        retrieved = [{"source": "A.md", "text": "t"}, {"source": "dir/B.md", "text": "t"}]
        self.assertEqual(race.cited_sources("x [source: A.md] [source: B.md; Made-Up.md]", retrieved), ["A.md", "dir/B.md"])
        self.assertEqual(race.cited_sources("[source: Never-Retrieved.md]", retrieved), [])
        self.assertEqual(race.cited_sources(None, retrieved), [])

    def test_a_dont_know_answer_is_ungrounded_and_a_stopped_run_has_no_answer(self):
        self.assertFalse(race.to_result(agent_run("I don't know based on the provided documents."))["grounded"])
        self.assertFalse(race.to_result(agent_run("I don’t know based on the provided documents."))["grounded"])
        self.assertTrue(race.to_result(agent_run("16 weeks. [source: Acme-Leave-Policy-2026.md]", LEAVE))["grounded"])
        stopped = race.to_result(agent_run(None, reason="max_steps"))
        self.assertEqual((stopped["answer"], stopped["grounded"]), ("", False))

    def test_percentiles_use_the_nearest_rank_method(self):
        self.assertEqual(race.percentile([], 95), 0.0)
        self.assertEqual(race.percentile([5], 95), 5)
        self.assertEqual(race.percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(race.percentile(list(range(1, 101)), 95), 95)
        self.assertEqual(race.percentile(list(range(1, 101)), 99), 99)
        self.assertEqual(race.percentile([3, 1, 2], 100), 3)


class RunOneTests(unittest.TestCase):
    def run_one(self, run, approach="agent", task=TASK):
        target = "app.agent.loop.run_agent" if approach == "agent" else "app.agent.workflow.run_workflow"
        with mock.patch(target, return_value=run):
            return race.run_one(task, approach, 1, tools=[])

    def test_a_finished_run_that_passes_the_rules_is_a_success(self):
        record = self.run_one(agent_run("It is 16 weeks. [source: Acme-Leave-Policy-2026.md]", LEAVE, calls=3, prompt=500, completion=50, api=2.5))
        self.assertTrue(record["success"])
        self.assertEqual((record["llm_calls"], record["prompt_tokens"], record["completion_tokens"], record["api_seconds"]), (3, 500, 50, 2.5))
        self.assertEqual((record["approach"], record["task_id"], record["tool_calls"]), ("agent", "t", ["search_policies"]))

    def test_a_wrong_answer_fails_with_the_reason(self):
        record = self.run_one(agent_run("It is 12 weeks. [source: Acme-Leave-Policy-2026.md]", LEAVE))
        self.assertFalse(record["success"])
        self.assertTrue(record["finished"])
        self.assertTrue(any("16 weeks" in reason or "missing" in reason for reason in record["failed_checks"]))

    def test_a_run_stopped_on_a_limit_is_never_a_success(self):
        record = self.run_one(agent_run(None, LEAVE, reason="max_steps"))
        self.assertEqual((record["success"], record["finished"], record["stop_reason"]), (False, False, "max_steps"))

    def test_refusing_an_unanswerable_task_is_a_success_and_answering_it_is_not(self):
        absent = {"id": "a", "question": "bonus?", "expected_sources": [], "expect_contains": [], "expect_all": [], "should_refuse": True}
        self.assertTrue(self.run_one(agent_run("I don't know based on the provided documents."), task=absent)["success"])
        self.assertFalse(self.run_one(agent_run("It is 10%."), task=absent)["success"])

    def test_the_workflow_is_run_through_the_same_scoring(self):
        record = self.run_one(agent_run("16 weeks. [source: Acme-Leave-Policy-2026.md]", LEAVE), approach="workflow")
        self.assertEqual((record["approach"], record["success"]), ("workflow", True))

    def test_an_unknown_approach_is_an_error(self):
        with self.assertRaises(ValueError):
            race.run_one(TASK, "magic", 1, tools=[])

    def test_the_full_step_log_is_kept_for_week_8(self):
        record = self.run_one(agent_run("16 weeks. [source: Acme-Leave-Policy-2026.md]", LEAVE))
        self.assertEqual(len(record["steps"]), 2)
        self.assertEqual(record["steps"][0]["tool_calls"][0]["name"], "search_policies")


class RunRaceTests(unittest.TestCase):
    def fake_runs(self, task, approach, repeat, tools, **options):
        good = approach == "workflow" or repeat != 2
        return {"task_id": task["id"], "approach": approach, "repeat": repeat, "success": good, "finished": True,
                "stop_reason": "final", "llm_calls": 5 if approach == "agent" else 1, "prompt_tokens": 1000 if approach == "agent" else 200,
                "completion_tokens": 100, "api_seconds": 6.0 if approach == "agent" else 1.0}

    def test_every_task_is_run_the_requested_number_of_times_with_both_approaches(self):
        with mock.patch.object(race, "run_one", side_effect=self.fake_runs):
            results = race.run_race(get_tasks(["t7-single-lookup", "t7-conflict"]), repeats=3, say=lambda *_: None, tools=[])
        self.assertEqual(len(results["runs"]), 2 * 3 * 2)
        self.assertEqual(results["meta"]["tasks"], ["t7-single-lookup", "t7-conflict"])
        self.assertTrue(results["meta"]["complete"])
        self.assertEqual(results["meta"]["repeats"], 3)

    def test_summary_totals_and_the_per_task_grid(self):
        with mock.patch.object(race, "run_one", side_effect=self.fake_runs):
            results = race.run_race(get_tasks(["t7-single-lookup", "t7-conflict"]), repeats=3, say=lambda *_: None, tools=[])
        summary = race.summarize(results)
        agent, flow = summary["approaches"]["agent"], summary["approaches"]["workflow"]
        self.assertEqual((agent["runs"], agent["success"], flow["success"]), (6, 4, 6))        # the agent "fails" repeat 2 only
        self.assertEqual((agent["calls_mean"], flow["calls_mean"]), (5.0, 1.0))
        self.assertEqual((agent["tokens_mean"], flow["tokens_mean"]), (1100.0, 300.0))
        self.assertEqual(summary["grid"]["t7-conflict"]["agent"], [2, 3])
        self.assertEqual(summary["costs"]["t7-conflict"]["agent"], {"calls": 5.0, "tokens": 1100.0})
        self.assertEqual(summary["costs"]["t7-conflict"]["workflow"], {"calls": 1.0, "tokens": 300.0})
        text = "\n".join(race.format_summary(results))
        for needle in ("approach", "agent", "workflow", "t7-single-lookup", "model s avg", "yours: write it", "agent ok", "workflow ok"):
            self.assertIn(needle, text)

    def test_a_used_up_quota_saves_what_finished_and_says_so(self):
        outcomes = [self.fake_runs(get_tasks(["t7-single-lookup"])[0], "agent", 1, []), llm.QuotaExhausted("daily quota used up")]
        said = []
        with mock.patch.object(race, "run_one", side_effect=outcomes):
            results = race.run_race(get_tasks(["t7-single-lookup"]), repeats=2, say=said.append, tools=[])
        self.assertFalse(results["meta"]["complete"])
        self.assertIn("daily quota", results["meta"]["stopped_because"])
        self.assertEqual(len(results["runs"]), 1)
        self.assertTrue(any("STOPPED" in line for line in said))

    def test_only_the_chosen_approaches_run(self):
        with mock.patch.object(race, "run_one", side_effect=self.fake_runs):
            results = race.run_race(get_tasks(["t7-conflict"]), approaches=("workflow",), repeats=2, say=lambda *_: None, tools=[])
        self.assertEqual({r["approach"] for r in results["runs"]}, {"workflow"})


class TaskSetTests(unittest.TestCase):
    def test_ids_are_unique_and_the_unknown_id_is_an_error(self):
        ids = [t["id"] for t in TASKS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(get_tasks()), 9)
        with self.assertRaises(ValueError):
            get_tasks(["t7-no-such-task"])
        self.assertEqual([t["id"] for t in get_tasks(["t7-conflict"])], ["t7-conflict"])

    def test_every_task_has_what_the_rule_checks_need(self):
        for task in TASKS:
            with self.subTest(task=task["id"]):
                for key in ("id", "question", "expected_sources", "expect_contains", "expect_all", "should_refuse", "expected_tools", "why"):
                    self.assertIn(key, task)
                self.assertEqual(task["should_refuse"], not task["expected_sources"])
                self.assertTrue(task["expected_tools"])
                if not task["should_refuse"]:
                    self.assertTrue(task["expect_contains"] or task["expect_all"])

    def test_the_sentences_each_answer_is_built_from_are_really_in_the_documents(self):
        for task in TASKS:
            for fact in task.get("source_facts", []):
                with self.subTest(task=task["id"], fact=fact):
                    self.assertTrue(any(diagnose._normalize(fact) in NORMALISED[s] for s in task["expected_sources"]))
            if task["should_refuse"]:
                for term in task["absent_terms"]:
                    with self.subTest(task=task["id"], absent=term):
                        self.assertFalse(any(term in text for text in NORMALISED.values()))
            else:
                self.assertTrue(task.get("source_facts"), f"{task['id']} needs source_facts")
            for source in task["expected_sources"]:
                self.assertIn(source, CORPUS)

    def test_the_expected_numbers_and_dates_are_what_the_tools_compute(self):
        by_id = {t["id"]: t for t in TASKS}
        self.assertEqual(calculate("25 - 10"), "15")                                    # t7-carry-forward-sum: 15 above the limit of 10
        self.assertIn("15", by_id["t7-carry-forward-sum"]["expect_all"])
        self.assertTrue(add_days("2026-11-03", 30).startswith("2026-12-03"))             # t7-notice-end-date
        self.assertTrue(add_days("2026-11-03", 29).startswith("2026-12-02"))             # counting the first day
        accepted = by_id["t7-notice-end-date"]["expect_contains"]
        self.assertTrue("2026-12-03" in accepted and "2026-12-02" in accepted)
        self.assertTrue(add_days("2027-01-04", 9).startswith("2027-01-13"))               # t7-leave-end-date: 10 days, 4th is day 1
        self.assertIn("2027-01-13", by_id["t7-leave-end-date"]["expect_contains"])
        self.assertLess(45, 60)                                                          # t7-remote-eligibility: not eligible yet

    def test_the_rule_checks_accept_a_correct_answer_and_reject_a_plain_wrong_one_for_every_task(self):
        # A task nobody can pass, or everybody passes, would make the race meaningless.
        sample_answers = {
            "t7-single-lookup": "16 weeks of paid parental leave.",
            "t7-carry-forward-sum": "You can carry forward 10 days; 15 are above the limit.",
            "t7-notice-end-date": "The notice period ends on 3 December 2026.",
            "t7-leave-end-date": "Your last day of leave is 13 January 2027.",
            "t7-remote-eligibility": "Not yet: after 60 days of service, then up to three days a week.",
            "t7-two-documents": "7 calendar days of notice on probation, and 12 paid sick days.",
            "t7-conflict": "The Acme policy says 18 days and the handbook says 24 days.",
            "t7-cloud-two-sections": "No, least privilege applies; keep access keys in Azure Key Vault.",
        }
        for task in TASKS:
            with self.subTest(task=task["id"]):
                if task["should_refuse"]:
                    good = {"answer": "I don't know based on the provided documents.", "grounded": False, "sources": [], "retrieved": []}
                    bad = {"answer": "It is 20 percent.", "grounded": True, "sources": [], "retrieved": []}
                else:
                    sources = list(task["expected_sources"])
                    good = {"answer": sample_answers[task["id"]], "grounded": True, "sources": sources, "retrieved": []}
                    bad = {"answer": "I am not sure about that at all.", "grounded": True, "sources": sources, "retrieved": []}
                self.assertTrue(checks.check_case(dict(task, needs_expected=False), good)[1])
                self.assertFalse(checks.check_case(dict(task, needs_expected=False), bad)[1])


if __name__ == "__main__":
    unittest.main()
