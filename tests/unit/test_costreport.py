"""Week 11: the cost report (evals/costreport.py, scripts/cost_report.py): per step, per request, side by side, at stated prices."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from _testkit import ROOT
from app.config import settings
from evals import cost_run, costreport, logsearch, runner

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import cost_report                                          # noqa: E402


def span(name, kind, took, provider=None, wait=None, prompt=None, completion=None, cold=False, attempts=None):
    return {"name": name, "kind": kind, "duration_ms": took, "start_ms": 0, "status": "ok", "cold": cold, "provider_ms": provider, "wait_ms": wait,
            "prompt_tokens": prompt, "completion_tokens": completion, "attempts": attempts}


def request(question="How much notice?", prompt=1000, completion=100, embed=10.0, search=20.0, provider=500.0, wait=1500.0, cold=False,
            model="m", served="m", synthetic=False, known=True):
    """One logged request as the app writes it, normalized the way the readers see it."""
    spans = [span("embed_query", "embed", embed, cold=cold), span("search", "retrieve", search),
             span("generate", "model", provider + wait, provider=provider, wait=wait, prompt=prompt if known else None,
                  completion=completion if known else None, attempts=1)]
    raw = {"trace_id": "aabbccdd", "request_id": "aabbccdd" + "0" * 8, "ts": "2026-10-08T10:00:00", "question": question, "answer": "a [source: x.md]",
           "grounded": True, "retrieved": [], "config": {"llm_model": model, "llm_model_served": served}, "spans": spans,
           "total_ms": embed + search + provider + wait, "status": "ok", "synthetic": synthetic,
           "usage": {"model_calls": 1, "prompt_tokens": prompt if known else 0, "completion_tokens": completion if known else 0, "tokens_known": known,
                     "provider_ms": provider, "wait_ms": wait}}
    return logsearch.normalize(raw, "log.jsonl", 1, "trace")


def old_request():
    return logsearch.normalize({"trace_id": "0a1b2c3d", "ts": "2026-09-15T10:00:00", "question": "old?", "answer": "a", "grounded": True, "retrieved": []}, "log.jsonl", 2, "trace")


class StatsTests(unittest.TestCase):
    def test_the_numbers_of_a_list(self):
        result = costreport.stats([4, 1, 3, None, 2])
        self.assertEqual((result["n"], result["mean"], result["median"], result["max"], result["p95"]), (4, 2.5, 2.5, 4, None))
        self.assertIsNone(costreport.stats([]))
        self.assertIsNone(costreport.stats([None]))

    def test_a_95th_percentile_is_only_given_from_a_hundred_values_up(self):
        self.assertIsNone(costreport.stats(list(range(1, 100)))["p95"])
        self.assertEqual(costreport.stats(list(range(1, 101)))["p95"], 95)
        self.assertEqual(costreport.stats(list(range(1, 201)))["p95"], 190)


class PerStepTests(unittest.TestCase):
    def test_each_step_is_summed_across_requests_with_the_model_time_split_and_ordered_by_total_time(self):
        report = costreport.per_step([request(provider=400, wait=600, prompt=1000), request(provider=600, wait=1400, prompt=2000)])
        names = [row["name"] for row in report["rows"]]
        self.assertEqual(names, ["generate", "search", "embed_query"])
        generate = report["rows"][0]
        self.assertEqual((generate["time"]["n"], generate["time"]["mean"], generate["provider"]["mean"], generate["wait"]["mean"]), (2, 1500.0, 500.0, 1000.0))
        self.assertEqual((generate["prompt_tokens"]["mean"], generate["completion_tokens"]["mean"], generate["attempts"]["mean"]), (1500, 100, 1))
        self.assertAlmostEqual(sum(row["share"] for row in report["rows"]), 1.0)
        self.assertIsNone(report["rows"][1]["provider"])                       # a search has no provider time

    def test_a_request_without_steps_is_counted_not_guessed_at(self):
        report = costreport.per_step([request(), old_request()])
        self.assertEqual((report["requests_with_steps"], report["requests_without_steps"]), (1, 1))
        self.assertIn("1 older ones did not", "\n".join(costreport.step_lines(report)))
        self.assertIn("no step was recorded", "\n".join(costreport.step_lines(costreport.per_step([old_request()]))))

    def test_when_every_step_was_a_cold_start_and_they_are_left_out_the_table_says_so(self):
        first = request()
        for step in first["spans"]:
            step["cold"] = True
        report = costreport.per_step([first], skip_cold=True)
        self.assertEqual(report["rows"], [])
        text = "\n".join(costreport.step_lines(report))
        self.assertIn("a cold start", text)
        self.assertIn("a request that failed before its first step", "\n".join(costreport.step_lines(costreport.per_step([old_request()]))))

    def test_cold_start_steps_are_counted_and_can_be_left_out(self):
        records = [request(embed=900.0, cold=True), request(embed=10.0), request(embed=12.0)]
        kept = costreport.per_step(records)
        left_out = costreport.per_step(records, skip_cold=True)
        embed = lambda report: next(row for row in report["rows"] if row["name"] == "embed_query")["time"]
        self.assertEqual((embed(kept)["n"], round(embed(kept)["mean"])), (3, 307))
        self.assertEqual((embed(left_out)["n"], embed(left_out)["mean"]), (2, 11.0))
        self.assertEqual(kept["cold_spans"], 1)
        self.assertIn("and are left out", "\n".join(costreport.step_lines(left_out)))
        self.assertIn("--skip-cold leaves them out", "\n".join(costreport.step_lines(kept)))

    def test_a_failed_request_has_no_answer_steps_in_the_table(self):
        failed = logsearch.normalize({"request_id": "x" * 16, "error_class": "RuntimeError", "spans": [{"name": "search", "kind": "retrieve", "duration_ms": 5}]}, "e.jsonl", 1, "error")
        self.assertEqual(costreport.per_step([failed])["rows"], [])


class PerRequestTests(unittest.TestCase):
    def test_tokens_time_and_the_share_of_the_model_time_spent_waiting(self):
        report = costreport.per_request([request(prompt=1000, wait=1500.0, provider=500.0), request(prompt=3000, wait=500.0, provider=500.0)])
        self.assertEqual((report["requests"], report["tokens_known"]), (2, 2))
        self.assertEqual((report["prompt_tokens"]["mean"], report["prompt_tokens"]["median"]), (2000, 2000))
        self.assertAlmostEqual(report["wait_share"], 2000 / 3000)                  # 2000 ms waiting of 3000 ms of model time
        self.assertFalse(report["priced"])
        self.assertIsNone(report["cost"])

    def test_requests_whose_provider_reported_no_tokens_are_left_out_not_averaged_in_as_zero(self):
        report = costreport.per_request([request(prompt=1000), request(known=False), old_request()], 2.0, 10.0)
        self.assertEqual((report["requests"], report["tokens_known"]), (3, 1))
        self.assertEqual(report["prompt_tokens"]["mean"], 1000)
        self.assertEqual(report["cost"]["n"], 1)
        self.assertAlmostEqual(report["cost"]["mean"], (1000 * 2.0 + 100 * 10.0) / 1_000_000)
        text = "\n".join(costreport.request_lines(report, "a stated source", 2.0, 10.0))
        self.assertIn("not counted as zero", text)
        self.assertIn("prices from: a stated source", text)
        self.assertIn("$2 per million input tokens and $10 per million output tokens", text)

    def test_without_prices_there_are_no_dollars_and_the_price_settings_are_never_read(self):
        with mock.patch.object(settings, "price_input_per_million", 99.0), mock.patch.object(settings, "price_output_per_million", 99.0):
            report = costreport.per_request([request()])
        self.assertFalse(report["priced"])
        self.assertIn("no price stated", "\n".join(costreport.request_lines(report)))

    def test_failed_requests_are_counted_apart(self):
        failed = logsearch.normalize({"request_id": "x" * 16, "error_class": "RuntimeError"}, "e.jsonl", 1, "error")
        report = costreport.per_request([request(), failed])
        self.assertEqual((report["requests"], report["errors"]), (1, 1))
        self.assertIn("1 failed", "\n".join(costreport.request_lines(report)))

    def test_with_nothing_to_average_it_says_no_data(self):
        text = "\n".join(costreport.request_lines(costreport.per_request([old_request()], 2.0, 10.0), None, 2.0, 10.0))
        self.assertIn("no data", text)
        self.assertIn("(source not stated)", text)


class CompareTests(unittest.TestCase):
    def test_the_same_questions_are_paired_and_the_ratio_is_b_over_a(self):
        a = [request("q1", prompt=1000), request("q2", prompt=2000)]
        b = [request("Q2 ", prompt=1000), request("q1", prompt=500)]                 # the order and the spacing differ, the questions do not
        result = costreport.compare(a, b, 2.0, 10.0)
        self.assertEqual((result["pairs"], result["usable"], result["unmatched"]), (2, 2, 0))
        self.assertEqual((result["a"]["prompt_tokens"], result["b"]["prompt_tokens"]), (1500, 750))
        self.assertAlmostEqual(result["b"]["cost"] / result["a"]["cost"], (750 * 2 + 100 * 10) / (1500 * 2 + 100 * 10))
        text = "\n".join(costreport.compare_lines(result, "before", "after", "a stated source", 2.0, 10.0))
        self.assertIn("0.50", text)
        self.assertIn("from: a stated source", text)

    def test_the_kth_time_a_question_was_asked_is_paired_with_the_kth_time(self):
        result = costreport.compare([request("q", prompt=100), request("q", prompt=300)], [request("q", prompt=200), request("q", prompt=400)])
        self.assertEqual((result["pairs"], result["a"]["prompt_tokens"], result["b"]["prompt_tokens"]), (2, 200, 300))

    def test_pairing_the_first_with_the_first_and_not_with_the_last_decides_which_pairs_are_usable(self):
        a = [request("q", prompt=100), request("q", known=False)]                         # the second time it was asked in A, the provider reported nothing
        b = [request("q", prompt=200), request("q", prompt=400)]
        result = costreport.compare(a, b)
        self.assertEqual((result["pairs"], result["usable"], result["a"]["prompt_tokens"], result["b"]["prompt_tokens"]), (2, 1, 100, 200))
        self.assertEqual(result["unmatched"], 0)

    def test_a_question_asked_in_only_one_log_is_counted_not_paired(self):
        result = costreport.compare([request("q1"), request("only a")], [request("q1"), request("only b"), request("only b 2")])
        self.assertEqual((result["pairs"], result["unmatched"]), (1, 3))

    def test_logs_answered_by_different_models_are_refused(self):
        result = costreport.compare([request(served="model-a")], [request(served="model-b")])
        self.assertIn("different models", result["refused"])
        self.assertIn("different models", "\n".join(costreport.compare_lines(result, "a", "b")))
        self.assertIn("different models", costreport.compare([request(model="asked-a")], [request(model="asked-b")])["refused"])

    def test_pairs_without_the_providers_token_counts_are_dropped_and_none_left_is_refused(self):
        result = costreport.compare([request("q1"), request("q2", known=False)], [request("q1"), request("q2")])
        self.assertEqual((result["pairs"], result["usable"]), (2, 1))
        self.assertIn("no question was answered", costreport.compare([request(known=False)], [request(known=False)])["refused"])


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.folder))          # nothing in a test may be saved into the real results folder
        self.enterContext(mock.patch.object(cost_run, "MEASURE_DIR", self.folder))

    def write_log(self, name, records):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(dict(record["raw"], synthetic=record["synthetic"])) + "\n")
        return path

    def run_script(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cost_report.main(list(argv))
        return code, out.getvalue()

    def test_a_log_is_reported_request_first_then_step_by_step(self):
        log = self.write_log("traces.jsonl", [request(), request(prompt=2000)])
        code, text = self.run_script("--log", log, "--price-in", "2", "--price-out", "10", "--price-source", "a stated source")
        self.assertEqual(code, 0)
        for needle in ("2 answered requests", "prompt tokens", "model ms waiting", "waiting is 75% of the model time", "dollars per request",
                       "prices from: a stated source", "step by step", "embed_query", "generate"):
            self.assertIn(needle, text)

    def test_a_synthetic_log_is_refused_unless_asked_for(self):
        log = self.write_log("drill.jsonl", [request(synthetic=True)])
        code, text = self.run_script("--log", log)
        self.assertEqual(code, 1)
        self.assertIn("invented", text)
        self.assertEqual(self.run_script("--log", log, "--include-synthetic")[0], 0)

    def test_two_logs_are_compared_and_a_model_mismatch_is_an_error(self):
        a = self.write_log("a.jsonl", [request("q1", prompt=1000)])
        b = self.write_log("b.jsonl", [request("q1", prompt=500)])
        code, text = self.run_script("--compare", a, b)
        self.assertEqual(code, 0)
        self.assertIn("0.50", text)
        c = self.write_log("c.jsonl", [request("q1", served="other")])
        code, text = self.run_script("--compare", a, c)
        self.assertEqual(code, 1)
        self.assertIn("cannot compare", text)

    def test_a_missing_or_empty_log_is_an_error(self):
        code, text = self.run_script("--log", os.path.join(self.folder, "nothing.jsonl"))
        self.assertEqual(code, 1)
        self.assertIn("No log lines found", text)

    def test_a_negative_price_is_refused(self):
        self.assertEqual(self.run_script("--price-in", "-1")[0], 1)

    def test_a_saved_measurement_is_shown_with_dollars_only_at_stated_prices(self):
        rows = [{"question_id": "q", "kind": "eval", "arm": arm, "status": "ok", "tokens_known": True, "prompt_tokens": tokens, "completion_tokens": 100,
                 "passed": True, "provider_ms": 5.0, "wait_ms": 0.0, "chars": {"stripped": 0}} for arm, tokens in (("before", 1000), ("after", 800))]
        results = {"meta": {"label": "t", "dry_run": False, "complete": True, "model_requested": "m", "models_served": ["m"], "n_questions": 1,
                            "calls_spent": 2, "arms": [{"name": "before", "overrides": {}}, {"name": "after", "overrides": {"context_strip_min_repeats": 10}}]}, "rows": rows}
        cost_run.save_aggregate(results, cost_run.results_path("t"))
        code, text = self.run_script("--show", "t")
        self.assertEqual(code, 0)
        self.assertIn("no price stated", text)
        code, text = self.run_script("--show", "t", "--price-in", "2", "--price-out", "10", "--price-source", "a stated source")
        self.assertIn("from: a stated source", text)
        self.assertIn("$0.003000", text)                                            # 1000 x 2 + 100 x 10 = $0.003
        self.assertIn("$0.002600", text)
        results["meta"]["dry_run"] = True
        cost_run.save_aggregate(results, cost_run.results_path("dry-t"))
        self.assertIn("no dollars for a dry run", self.run_script("--show", "dry-t", "--price-in", "2", "--price-out", "10")[1])

    def test_a_synthetic_log_read_on_request_carries_its_banner_alone_or_beside_a_real_one(self):
        drill_log = self.write_log("drill.jsonl", [request(synthetic=True)])
        code, text = self.run_script("--log", drill_log, "--include-synthetic")
        self.assertEqual(code, 0)
        self.assertEqual(text.count("SYNTHETIC LOG"), 1)
        self.assertIn("invented", text)
        mixed = self.write_log("mixed.jsonl", [request(synthetic=True), request()])
        self.assertEqual(self.run_script("--log", mixed, "--include-synthetic")[1].count("SYNTHETIC LOG"), 1)        # one synthetic line is enough to warn
        real = self.write_log("real.jsonl", [request(), request(prompt=2000)])
        self.assertNotIn("SYNTHETIC LOG", self.run_script("--log", real)[1])
        self.assertNotIn("DRY-RUN LOG", self.run_script("--log", real)[1])

    def test_a_scripted_provider_log_carries_the_dry_run_banner_whatever_else_it_holds(self):
        dry = self.write_log("dry.jsonl", [request(model="scripted-model", served="scripted-model")])
        code, text = self.run_script("--log", dry, "--price-in", "2", "--price-out", "10")
        self.assertEqual(code, 0)
        self.assertEqual(text.count("DRY-RUN LOG"), 1)
        self.assertIn("NOT measurements", text)
        mixed = self.write_log("mixed.jsonl", [request(model="scripted-model", served="scripted-model"), request()])
        self.assertNotIn("DRY-RUN LOG", self.run_script("--log", mixed)[1])             # only a log answered by nothing but the stand-in is a dry run's

    def test_two_logs_compared_print_each_banner_once_not_once_per_log(self):
        a = self.write_log("a.jsonl", [request("q1", model="scripted-model", served="scripted-model")])
        b = self.write_log("b.jsonl", [request("q1", prompt=500, model="scripted-model", served="scripted-model")])
        code, text = self.run_script("--compare", a, b)
        self.assertEqual(code, 0)
        self.assertEqual(text.count("DRY-RUN LOG"), 1)
        sa = self.write_log("sa.jsonl", [request("q1", synthetic=True)])
        sb = self.write_log("sb.jsonl", [request("q1", synthetic=True, prompt=500)])
        self.assertEqual(self.run_script("--compare", sa, sb)[0], 1)                      # refused without --include-synthetic
        code, text = self.run_script("--compare", sa, sb, "--include-synthetic")
        self.assertEqual((code, text.count("SYNTHETIC LOG")), (0, 1))

    def test_a_log_path_that_is_a_folder_is_an_error_line(self):
        code, text = self.run_script("--log", self.folder)
        self.assertEqual(code, 1)
        self.assertIn("is not a log file", text)

    def test_prices_of_zero_are_not_called_a_missing_price(self):
        log = self.write_log("traces.jsonl", [request()])
        text = self.run_script("--log", log, "--price-in", "0", "--price-out", "0")[1]
        self.assertIn("the prices stated are not above 0", text)
        self.assertNotIn("no price stated", text)
        self.assertIn("no price stated", self.run_script("--log", log)[1])

    def test_a_stopped_measurement_kept_beside_an_older_one_is_found_and_the_way_on_is_named(self):
        results = {"meta": {"label": "inc", "dry_run": False, "complete": False, "model_requested": "m", "models_served": [], "n_questions": 1, "calls_spent": 1,
                            "arms": [{"name": "before", "overrides": {}}]}, "rows": []}
        cost_run.save_aggregate(results, os.path.join(runner.RESULTS_DIR, "cost-inc.incomplete.json"))
        code, text = self.run_script("--show", "inc")
        self.assertEqual(code, 1)
        self.assertIn("The measurement is incomplete", text)
        self.assertIn("measure_cost.py --label inc --resume", text)

    def test_a_saved_measurement_is_priced_only_from_the_prices_given_never_from_the_price_settings(self):
        rows = [{"question_id": "q", "kind": "eval", "arm": "before", "status": "ok", "tokens_known": True, "prompt_tokens": 1000, "completion_tokens": 100,
                 "passed": True, "provider_ms": 5.0, "wait_ms": 0.0, "chars": {"stripped": 0}}]
        results = {"meta": {"label": "p", "dry_run": False, "complete": True, "model_requested": "m", "models_served": ["m"], "n_questions": 1, "calls_spent": 1,
                            "arms": [{"name": "before", "overrides": {}}]}, "rows": rows}
        cost_run.save_aggregate(results, cost_run.results_path("p"))
        with mock.patch.object(settings, "price_input_per_million", 99.0), mock.patch.object(settings, "price_output_per_million", 99.0):
            text = self.run_script("--show", "p", "--price-in", "2")[1]
        self.assertIn("$0.002000", text)                                                  # 1000 tokens at $2 per million, and the output left unpriced, not priced at 99

    def test_an_unknown_measurement_is_an_error(self):
        code, text = self.run_script("--show", "not-a-label")
        self.assertEqual(code, 1)
        self.assertIn("No saved measurement", text)


if __name__ == "__main__":
    unittest.main()
