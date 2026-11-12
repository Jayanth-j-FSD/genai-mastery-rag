"""Week 11: the cost measurement (evals/cost_run.py, scripts/measure_cost.py), end to end on a small corpus with a scripted provider."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import openai

from _testkit import ROOT, isolated_index, patched_embeddings
from app import llm, observability
from app.config import settings
from app.rag import generator
from evals import bank, cost_prediction, cost_run, runner
from test_llm import DAILY_BODY, status_error

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import measure_cost                                       # noqa: E402

BLOCK = ["Northstar maintains this policy to provide consistent expectations.",
         "- Requests should normally be submitted through the employee portal.",
         "- The company may periodically review this rule."]
HANDBOOK = "\n".join(["# Handbook"] + [line for number in range(14) for line in (f"## Section {number}", *BLOCK)])
POLICY = "# Notice\nA permanent employee gives 30 days of written notice.\n"


def lines_of(path):
    with open(path, encoding="utf-8") as handle:
        return [line for line in handle.read().splitlines() if line.strip()]


def case(case_id, question, expected=("policy.md",), contains=("30 days",)):
    return {"id": case_id, "question": question, "expected_sources": list(expected), "expect_contains": list(contains), "expect_all": [],
            "should_refuse": not expected, "needs_expected": False, "problem_type": "single-fact", "origin": "test"}


CASES = [case("notice", "How much notice does a permanent employee give?"), case("review", "How often is this rule reviewed?"),
         case("bonus", "What is the annual bonus?", expected=(), contains=())]


class Citing(cost_run.ScriptedClient):
    """A provider stand-in whose answer can depend on the arm (read from the settings at the moment of the call)."""

    def __init__(self, answers=None, fail_with=None, report_usage=True):
        super().__init__("served-model")
        self.answers, self.fail_with, self.report_usage, self.calls = answers or {}, list(fail_with or []), report_usage, []

    def _create(self, model=None, messages=None, **kwargs):
        self.calls.append(settings.context_strip_min_repeats)
        if self.fail_with:
            outcome = self.fail_with.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        text = self.answers.get(settings.context_strip_min_repeats, "The notice is 30 days. [source: policy.md]")
        reply = SimpleNamespace(content=text, tool_calls=None)
        prompt = " ".join(m["content"] for m in messages)
        usage = SimpleNamespace(prompt_tokens=len(prompt) // 4, completion_tokens=7) if self.report_usage else None
        return SimpleNamespace(model=self.model, choices=[SimpleNamespace(message=reply, finish_reason="stop")], usage=usage)


class MeasureCase(unittest.TestCase):
    def setUp(self):
        corpus = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        for name, text in (("handbook.md", HANDBOOK), ("policy.md", POLICY)):
            with open(os.path.join(corpus, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        self.out = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(isolated_index(corpus_dir=corpus, embed_provider="local", dense_search="exact", retrieval_mode="dense", top_k=5))      # five is every chunk of this corpus, so what is asked never depends on the fake embedder
        self.enterContext(patched_embeddings())
        self.enterContext(mock.patch.object(settings, "llm_rpm", 0))
        self.enterContext(mock.patch.object(settings, "min_relevance", 0.0))
        self.enterContext(mock.patch.object(settings, "context_strip_min_repeats", 0))
        self.enterContext(mock.patch.object(settings, "price_input_per_million", 0.0))
        self.enterContext(mock.patch.object(settings, "price_output_per_million", 0.0))
        self.arms = cost_run.parse_arms(cost_run.DEFAULT_ARMS)

    def run_with(self, client, items=None, **kwargs):
        saves = []
        with mock.patch.object(llm, "_get_client", return_value=client):
            results = cost_run.run(items or cost_run.make_items(CASES, []), kwargs.pop("arms", self.arms), "t", "served-model", self.out,
                                   save=lambda r: saves.append(len(r["rows"])), say=lambda *a: None, **kwargs)
        return results, saves


class ArmTests(unittest.TestCase):
    def test_an_arm_is_a_name_and_the_settings_it_changes(self):
        self.assertEqual(cost_run.parse_arm("before"), ("before", {}))
        self.assertEqual(cost_run.parse_arm("after:context_strip_min_repeats=10"), ("after", {"context_strip_min_repeats": 10}))
        self.assertEqual(cost_run.parse_arm("x:top_k=3,context_strip_min_repeats=10")[1], {"top_k": 3, "context_strip_min_repeats": 10})

    def test_a_typo_or_a_bad_value_fails_before_any_quota_is_spent(self):
        for bad in ("after:no_such_setting=1", "after:context_strip_min_repeats=1", "bad name:top_k=3", ":top_k=3", "a/b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                cost_run.parse_arm(bad)

    def test_a_comparison_needs_two_arms_with_different_names(self):
        with self.assertRaises(ValueError):
            cost_run.parse_arms(["before"])
        with self.assertRaises(ValueError):
            cost_run.parse_arms(["before", "before"])
        self.assertEqual([name for name, _ in cost_run.parse_arms(cost_run.DEFAULT_ARMS)], ["before", "after", "before-2"])

    def test_the_order_rotates_so_every_arm_is_asked_first_equally_often(self):
        arms = cost_run.parse_arms(["a", "b", "c"])
        orders = [[name for name, _ in cost_run.rotation(arms, index)] for index in range(6)]
        self.assertEqual(orders[0], ["a", "b", "c"])
        self.assertEqual(orders[1], ["b", "c", "a"])
        self.assertEqual(orders[3], orders[0])
        self.assertEqual(sorted(order[0] for order in orders[:3]), ["a", "b", "c"])

    def test_the_question_set_fingerprint_changes_with_the_text_and_the_order(self):
        items = cost_run.make_items(CASES, ["bank question?"])
        self.assertEqual(cost_run.question_set_hash(items), cost_run.question_set_hash(cost_run.make_items(CASES, ["bank question?"])))
        self.assertNotEqual(cost_run.question_set_hash(items), cost_run.question_set_hash(items[::-1]))
        self.assertNotEqual(cost_run.question_set_hash(items), cost_run.question_set_hash(cost_run.make_items(CASES, ["another?"])))
        self.assertEqual([item["id"] for item in items][-1], "bank-1")


class RunTests(MeasureCase):
    def test_every_question_is_asked_under_every_arm_interleaved_and_logged_like_a_users_request(self):
        client = Citing()
        results, saves = self.run_with(client)
        rows = results["rows"]
        self.assertEqual(len(rows), 9)
        self.assertEqual([(r["question_id"], r["arm"]) for r in rows][:6],
                         [("notice", "before"), ("notice", "after"), ("notice", "before-2"),
                          ("review", "after"), ("review", "before-2"), ("review", "before")])      # the order turns by one each question
        self.assertTrue(results["meta"]["complete"])
        self.assertEqual((results["meta"]["n_questions"], results["meta"]["n_eval"], results["meta"]["n_bank"]), (3, 3, 0))
        self.assertEqual(saves, [3, 6, 9, 9])                                                       # saved after each question, and at the end
        for arm in ("before", "after", "before-2"):
            lines = [json.loads(line) for line in lines_of(os.path.join(self.out, arm, "traces.jsonl"))]
            self.assertEqual(len(lines), 3)
            self.assertTrue(all(line["channel"] == "measure" and line["caller"] == arm for line in lines))

    def test_the_same_arm_twice_asks_for_the_same_tokens_and_the_idea_asks_for_fewer(self):
        results, _ = self.run_with(Citing())
        by = {(r["question_id"], r["arm"]): r for r in results["rows"]}
        for question in ("notice", "review", "bonus"):
            self.assertEqual(by[question, "before"]["prompt_tokens"], by[question, "before-2"]["prompt_tokens"])
            self.assertLess(by[question, "after"]["prompt_tokens"], by[question, "before"]["prompt_tokens"])
            self.assertGreater(by[question, "after"]["chars"]["stripped"], 0)
            self.assertEqual(by[question, "before"]["chars"]["stripped"], 0)
        summary = cost_run.summarize_arms(results["rows"])
        self.assertLess(summary["after"]["mean_prompt_tokens"], summary["before"]["mean_prompt_tokens"])
        self.assertEqual(summary["before"]["mean_prompt_tokens"], summary["before-2"]["mean_prompt_tokens"])
        self.assertEqual(results["meta"]["models_served"], ["served-model"])

    def test_a_provider_that_reports_no_usage_gives_unknown_tokens_not_zero(self):
        results, _ = self.run_with(Citing(report_usage=False), items=cost_run.make_items(CASES[:1], []))
        for row in results["rows"]:
            self.assertEqual((row["tokens_known"], row["prompt_tokens"], row["completion_tokens"]), (False, None, None))
        self.assertIsNone(cost_run.summarize_arms(results["rows"])["before"]["mean_prompt_tokens"])
        self.assertIn("-", "\n".join(cost_run.format_summary(results)).splitlines()[3])        # the table shows a dash, not 0.0

    def test_an_eval_question_is_scored_by_the_free_rules_and_stand_in_traffic_is_not(self):
        items = cost_run.make_items(CASES[:1], ["Who approves leave?"])
        results, _ = self.run_with(Citing(), items=items)
        by = {(r["question_id"], r["arm"]): r for r in results["rows"]}
        self.assertTrue(by["notice", "before"]["passed"])
        self.assertIsNone(by["bank-1", "before"]["passed"])

    def test_a_pass_that_becomes_a_fail_under_an_arm_is_found(self):
        items = cost_run.make_items(CASES[:2], [])
        results, _ = self.run_with(Citing(answers={10: "I am not sure. [source: policy.md]"}), items=items,
                                   arms=cost_run.parse_arms(["before", "after:context_strip_min_repeats=10"]))
        moved = cost_run.flips(results["rows"], "before", "after")
        self.assertEqual((moved["pass_to_fail"], moved["fail_to_pass"], moved["compared"]), (["notice", "review"], [], 2))

    def test_the_saved_rows_hold_no_question_answer_or_passage_text(self):
        results, _ = self.run_with(Citing())
        raw = json.dumps(results)
        for text in ("How much notice", "The notice is 30 days", "permanent employee gives", "Northstar maintains", "annual bonus"):
            self.assertNotIn(text, raw)
        self.assertEqual(len(results["rows"][0]["question_sha"]), 12)

    def test_the_prices_stated_are_recorded_as_an_assumption_and_no_dollars_are_invented(self):
        results, _ = self.run_with(Citing())
        prices = results["meta"]["prices"]
        self.assertEqual((prices["input_per_million"], prices["output_per_million"]), (0.0, 0.0))
        self.assertIn("no price stated", prices["described"])
        self.assertNotIn("cost_usd", results["rows"][0])

    def test_the_budget_of_model_calls_stops_the_run_and_says_so(self):
        results, saves = self.run_with(Citing(), max_calls=4)
        self.assertFalse(results["meta"]["complete"])
        self.assertEqual(len(results["rows"]), 4)
        self.assertIn("--max-calls", results["meta"]["stopped_because"])
        self.assertEqual(results["meta"]["calls_spent"], 4)

    def test_a_used_up_daily_quota_stops_the_run_keeps_what_finished_and_names_the_cause(self):
        client = Citing(fail_with=[None, None, None, status_error(openai.RateLimitError, 429, DAILY_BODY)])
        results, _ = self.run_with(client)
        self.assertFalse(results["meta"]["complete"])
        self.assertIn("daily quota", results["meta"]["stopped_because"])
        self.assertEqual(len(results["rows"]), 3)
        failed_arm = results["meta"]["arms"][1]["name"]                  # the fourth request is the first of the second question: the order has turned once
        self.assertEqual(failed_arm, "after")
        self.assertEqual(len(lines_of(os.path.join(self.out, failed_arm, "errors.jsonl"))), 1)   # the failed request is in the error log

    def test_three_failures_in_a_row_stop_the_run_but_a_success_between_them_resets_the_count(self):
        def refuse():
            return status_error(openai.BadRequestError, 400, {"error": {"message": "no"}})
        with mock.patch.object(settings, "llm_max_retries", 0):
            results, _ = self.run_with(Citing(fail_with=[refuse(), refuse(), refuse()]))
        self.assertEqual([r["status"] for r in results["rows"]], ["error", "error", "error"])
        self.assertIn("3 requests in a row", results["meta"]["stopped_because"])
        self.assertEqual(results["rows"][0]["error_class"], "BadRequestError")
        self.assertIsNone(results["rows"][0]["prompt_tokens"])
        with mock.patch.object(settings, "llm_max_retries", 0):
            again, _ = self.run_with(Citing(fail_with=[refuse(), refuse(), None, refuse(), refuse(), None]))
        self.assertEqual(len(again["rows"]), 9)                        # a success between failures keeps the run going to the end
        self.assertEqual([r["status"] == "error" for r in again["rows"]][:6], [True, True, False, True, True, False])
        self.assertFalse(again["meta"]["complete"])                    # but a measurement with failed requests is not complete: --resume asks those again
        self.assertIn("--resume", again["meta"]["stopped_because"])

    def test_an_error_is_never_averaged_into_the_tokens(self):
        rows = [{"arm": "a", "status": "ok", "tokens_known": True, "prompt_tokens": 100, "completion_tokens": 10, "provider_ms": 5, "wait_ms": 0,
                 "passed": True, "grounded": True, "chars": {"stripped": 4}},
                {"arm": "a", "status": "error", "tokens_known": False, "prompt_tokens": None, "completion_tokens": None, "provider_ms": None,
                 "wait_ms": None, "passed": None, "grounded": None, "chars": None},
                {"arm": "a", "status": "ok", "tokens_known": False, "prompt_tokens": None, "completion_tokens": None, "provider_ms": 7, "wait_ms": 0,
                 "passed": False, "grounded": False, "chars": {"stripped": 0}},
                {"arm": "a", "status": "ok", "tokens_known": False, "prompt_tokens": None, "completion_tokens": None, "provider_ms": None, "wait_ms": None,
                 "passed": None, "grounded": True, "chars": None}]
        summary = cost_run.summarize_arms(rows)["a"]
        self.assertEqual((summary["requests"], summary["errors"], summary["tokens_known"], summary["mean_prompt_tokens"]), (4, 1, 1, 100))
        self.assertEqual((summary["scored"], summary["passed"], summary["mean_provider_ms"]), (2, 1, 6))        # a missing figure is left out, not counted as 0
        self.assertEqual(summary["mean_chars_stripped"], 2)

    def test_a_request_that_left_no_line_in_its_log_stops_the_run_cleanly_and_is_counted_against_the_budget(self):
        with mock.patch.object(cost_run, "_trace_of", return_value=None):
            results, saves = self.run_with(Citing())
        meta = results["meta"]
        self.assertEqual(results["rows"], [])
        self.assertFalse(meta["complete"])
        self.assertIn("left no line", meta["stopped_because"])
        self.assertIn("--resume", meta["stopped_because"])
        self.assertNotIn(self.out, meta["stopped_because"])                       # no machine path in what is saved
        self.assertEqual(meta["calls_spent"], 1)                                  # the paid request is counted, not lost
        self.assertEqual(saves, [0])                                              # and the normal final save happened

    def test_a_request_that_needed_a_retry_is_counted_by_the_requests_it_sent(self):
        busy = status_error(openai.InternalServerError, 503, {"error": {"message": "busy"}})
        client = Citing(fail_with=[busy])
        item = cost_run.make_items(CASES[:1], [])[0]
        with mock.patch.object(settings, "llm_max_retries", 2), mock.patch.object(llm.time, "sleep"), mock.patch.object(llm, "_get_client", return_value=client):
            row, requests = cost_run.ask_once(item, "before", {}, self.out, "served-model")
        self.assertEqual((row["status"], row["attempts"], requests), ("ok", 2, 2))      # one 503, then the answer: two provider requests, not one
        self.assertEqual(len(client.calls), 2)

    def test_the_budget_of_a_run_counts_the_retries_of_the_requests_that_answered(self):
        busy = status_error(openai.InternalServerError, 503, {"error": {"message": "busy"}})
        client = Citing(fail_with=[busy])
        with mock.patch.object(settings, "llm_max_retries", 2), mock.patch.object(llm.time, "sleep"):
            results, _ = self.run_with(client, items=cost_run.make_items(CASES[:1], []))
        self.assertEqual(len(results["rows"]), 3)
        self.assertEqual(len(client.calls), 4)                                           # three arms and one retry
        self.assertEqual(results["meta"]["calls_spent"], 4)

    def test_a_correct_refusal_passes_and_an_answer_to_an_unanswerable_question_fails(self):
        items = cost_run.make_items(CASES, [])
        refusing, _ = self.run_with(Citing(answers={0: generator.IDK, 10: generator.IDK}), items=items)
        by = {(r["question_id"], r["arm"]): r for r in refusing["rows"]}
        self.assertEqual((by["bonus", "before"]["grounded"], by["bonus", "before"]["passed"]), (False, True))      # a refusal where the documents are silent is right
        self.assertFalse(by["notice", "before"]["passed"])                                                          # a refusal where they answer is not
        answering, _ = self.run_with(Citing(), items=items)
        by = {(r["question_id"], r["arm"]): r for r in answering["rows"]}
        self.assertTrue(by["notice", "before"]["passed"])
        self.assertFalse(by["bonus", "before"]["passed"])
        summary = cost_run.summarize_arms(refusing["rows"])["before"]
        self.assertEqual((summary["refused"], summary["passed"], summary["scored"]), (3, 1, 3))

    def test_a_resumed_run_says_so_in_its_summary(self):
        results, _ = self.run_with(Citing())
        self.assertNotIn("resumed", "\n".join(cost_run.format_summary(results)))
        results["meta"]["resumed"] = [{"at": "x", "kept_rows": 3, "set_aside_rows": 1, "max_calls": 400}]
        results["meta"]["set_aside_rows"] = [{"error_class": "BadRequestError"}]
        self.assertIn("resumed 1 time(s); 1 failed row(s) were set aside and asked again", "\n".join(cost_run.format_summary(results)))

    def test_the_summary_says_when_it_is_a_dry_run_and_lists_the_differences_against_the_first_arm(self):
        results, _ = self.run_with(Citing(), dry_run=True)
        text = "\n".join(cost_run.format_summary(results))
        self.assertIn("DRY RUN", text)
        self.assertIn("NOT measurements", text)
        for name in ("before", "after", "before-2"):
            self.assertIn(name, text)
        self.assertIn("after against before on 3 eval questions", text)
        live = dict(results, meta=dict(results["meta"], dry_run=False))
        self.assertNotIn("DRY RUN", "\n".join(cost_run.format_summary(live)))
        self.assertIn("model served-model", "\n".join(cost_run.format_summary(live)))


class BankDrawTests(unittest.TestCase):
    def test_the_bank_questions_never_repeat_an_eval_question_and_the_same_seed_gives_the_same_ones(self):
        cases = runner.select_cases(None, base_only=True)
        eval_questions = {case["question"].lower() for case in cases}
        everything = bank.sample(bank.load_questions(), 30, 42)
        self.assertTrue(eval_questions & {question.lower() for question in everything})          # the Week 5 bank does overlap the eval set, so the exclusion matters
        drawn = bank.draw(cases, 30, 42)
        self.assertEqual(len(drawn), 30)
        self.assertEqual(eval_questions & {question.lower() for question in drawn}, set())
        self.assertEqual(drawn, bank.draw(cases, 30, 42))
        self.assertNotEqual(drawn, bank.draw(cases, 30, 43))

    def test_the_measurement_and_the_free_screen_draw_their_bank_the_same_way(self):
        import estimate_context_savings
        seen = []

        def spy(cases, count, seed, path=None):
            seen.append((len(cases), count, seed))
            raise ValueError("stop here, the draw is what is being looked at")
        with mock.patch.object(bank, "draw", side_effect=spy), mock.patch.object(settings, "embed_provider", "local"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                measure_cost.main(["--label", "t", "--dry-run", "--bank", "30", "--seed", "42"])
            estimate_context_savings.main(["--bank", "30", "--seed", "42"])
        self.assertEqual(seen, [(41, 30, 42), (41, 30, 42)])


class AggregateTests(unittest.TestCase):
    def test_the_file_is_named_after_the_label_and_a_stopped_run_never_replaces_a_complete_one(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        with mock.patch.object(runner, "RESULTS_DIR", folder):
            path = cost_run.results_path("w11 final!")
            self.assertTrue(path.endswith("cost-w11-final-.json"))
            self.assertFalse(cost_run.aggregate_exists("w11 final!"))
            cost_run.save_aggregate({"meta": {"complete": True, "label": "x"}, "rows": []}, path)
            kept = cost_run.save_aggregate({"meta": {"complete": False, "label": "x"}, "rows": [1]}, path)
            self.assertTrue(kept.endswith(".incomplete.json"))
            self.assertEqual(cost_run.load_aggregate(path)["rows"], [])
            self.assertTrue(cost_run.aggregate_exists("w11 final!"))

    def test_the_code_stamp_names_a_commit_and_whether_files_changed(self):
        stamp = cost_run.code_stamp()
        self.assertEqual(set(stamp), {"git", "dirty", "answer_code"})
        self.assertRegex(stamp["answer_code"], r"^[0-9a-f]{12}$")


class ScriptTests(MeasureCase):
    def run_script(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(cost_run, "MEASURE_DIR", self.out), \
                mock.patch.object(runner, "RESULTS_DIR", os.path.join(self.out, "results")):
            code = measure_cost.main(list(argv))
        return code, out.getvalue()

    def test_a_dry_run_asks_no_provider_and_says_it_is_a_dry_run_everywhere(self):
        with mock.patch.object(llm, "_get_client", side_effect=AssertionError("the real provider must not be used in a dry run")):
            code, text = self.run_script("--label", "t", "--dry-run", "--only", "absent-bonus", "code-err4032")
        self.assertEqual(code, 0, text)
        self.assertIn("DRY RUN", text)
        saved = cost_run.load_aggregate(os.path.join(self.out, "dry-t", "cost-dry.json"))
        self.assertTrue(saved["meta"]["dry_run"])
        self.assertEqual(saved["meta"]["label"], "dry-t")
        self.assertEqual(len(saved["rows"]), 6)

    def test_a_real_run_under_settings_other_than_the_registered_ones_is_refused_before_anything_is_written(self):
        with mock.patch.object(settings, "retrieval_mode", "hybrid"), mock.patch.object(settings, "embed_provider", "openai"):
            code, text = self.run_script("--label", "t", "--model", "served-model", "--only", "absent-bonus")
        self.assertEqual(code, 1)
        for difference in ("retrieval_mode is hybrid (registered dense)", "embed_provider is openai (registered local)", "top_k is 5 (registered 4)"):
            self.assertIn(difference, text)
        self.assertIn("--allow-unregistered", text)
        self.assertFalse(os.path.exists(os.path.join(self.out, "t")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "results")))

    def test_a_dry_run_is_not_held_to_the_registered_settings_and_a_registered_real_run_is_not_refused(self):
        with mock.patch.object(llm, "_get_client", side_effect=AssertionError("no provider in a dry run")):
            self.assertEqual(self.run_script("--label", "t", "--dry-run", "--only", "absent-bonus")[0], 0)
        with contextlib.ExitStack() as stack:
            for name, value in cost_prediction.REGISTERED_SETTINGS.items():
                stack.enter_context(mock.patch.object(settings, name, value))
            with mock.patch.object(llm, "_get_client", return_value=Citing()):
                code, text = self.run_script("--label", "t2", "--model", "served-model", "--only", "absent-bonus")
        self.assertEqual(code, 0, text)
        self.assertNotIn("NOT the registered", text)

    def test_a_dry_run_never_waits_for_the_rate_limit_even_when_one_is_set(self):
        with mock.patch.object(settings, "llm_rpm", 3), mock.patch.object(llm.time, "sleep", side_effect=AssertionError("a dry run must not wait")):
            code, text = self.run_script("--label", "t", "--dry-run", "--only", "absent-bonus", "code-err4032")      # 6 requests, more than the 3 a minute allowed
        self.assertEqual(code, 0, text)

    def test_limit_keeps_only_the_first_questions_and_the_seed_defaults_to_42(self):
        code, text = self.run_script("--label", "t", "--dry-run", "--only", "absent-bonus", "code-err4032", "exact-policy-id", "--limit", "2")
        self.assertEqual(code, 0, text)
        saved = cost_run.load_aggregate(os.path.join(self.out, "dry-t", "cost-dry.json"))
        self.assertEqual((saved["meta"]["n_questions"], len(saved["rows"])), (2, 6))
        first_two = [case["id"] for case in runner.select_cases(["absent-bonus", "code-err4032", "exact-policy-id"], base_only=True)][:2]
        self.assertEqual(sorted({row["question_id"] for row in saved["rows"]}), sorted(first_two))             # the first two, not the last two
        asked = []

        def spy(cases, count, seed, path=None):
            asked.append(seed)
            raise ValueError("stop")
        with mock.patch.object(bank, "draw", side_effect=spy), self.assertRaises(ValueError):
            self.run_script("--label", "t3", "--dry-run", "--bank", "5")
        self.assertEqual(asked, [42])

    def test_a_real_run_needs_a_named_model_and_never_an_unnamed_one(self):
        code, text = self.run_script("--label", "t")
        self.assertEqual(code, 1)
        self.assertIn("--model is required", text)

    def test_it_refuses_a_bad_arm_a_bad_setting_and_a_budget_it_would_pass(self):
        self.assertEqual(self.run_script("--label", "t", "--dry-run", "--arm", "only-one")[0], 1)
        self.assertEqual(self.run_script("--label", "t", "--dry-run", "--arm", "a", "--arm", "b:nope=1")[0], 1)
        self.assertEqual(self.run_script("--label", "t", "--dry-run", "--set", "no_such=1")[0], 1)
        code, text = self.run_script("--label", "t", "--dry-run", "--only", "absent-bonus", "--max-calls", "2")
        self.assertEqual(code, 1)
        self.assertIn("over --max-calls 2", text)

    def test_it_refuses_to_overwrite_a_label_unless_forced(self):
        self.assertEqual(self.run_script("--label", "t", "--dry-run", "--only", "absent-bonus")[0], 0)
        code, text = self.run_script("--label", "t", "--dry-run", "--only", "absent-bonus")
        self.assertEqual(code, 1)
        self.assertIn("already exists", text)
        self.assertEqual(self.run_script("--label", "t", "--dry-run", "--only", "absent-bonus", "--force")[0], 0)

    def test_a_real_run_through_a_scripted_client_saves_the_aggregate_under_the_results_folder(self):
        client = Citing()
        with mock.patch.object(llm, "_get_client", return_value=client):
            code, text = self.run_script("--label", "t", "--model", "served-model", "--only", "absent-bonus", "code-err4032", "--allow-unregistered")
        self.assertEqual(code, 0, text)
        self.assertIn("NOT the registered conditions", text)
        self.assertIn("top_k is 5 (registered 4)", text)
        saved = cost_run.load_aggregate(os.path.join(self.out, "results", "cost-t.json"))
        self.assertEqual(saved["meta"]["settings"]["top_k"], 5)
        self.assertIsNone(cost_prediction.check_prediction(saved)["verdict"])                       # such a measurement can never give a verdict
        self.assertFalse(saved["meta"]["dry_run"])
        self.assertEqual(saved["meta"]["model_requested"], "served-model")
        self.assertEqual(len(saved["rows"]), 6)
        self.assertIn("model served-model", text)


if __name__ == "__main__":
    unittest.main()
