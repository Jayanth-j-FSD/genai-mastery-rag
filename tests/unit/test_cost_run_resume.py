"""Week 11: the one-shot live measurement survives a stop, a failed request, a wrong setup and a converted failure (evals/cost_run.py, scripts/measure_cost.py)."""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import openai

import test_cost_run
from _testkit import ROOT
from app import llm
from app.config import settings
from app.rag import pipeline
from evals import cases, cost_prediction, cost_run, runner
from test_llm import DAILY_BODY, status_error

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import measure_cost                                       # noqa: E402

Citing, CASES = test_cost_run.Citing, test_cost_run.CASES


def quota():
    return status_error(openai.RateLimitError, 429, DAILY_BODY)


def refuse():
    return status_error(openai.BadRequestError, 400, {"error": {"message": "no"}})


class ResumeTests(test_cost_run.MeasureCase):
    def first_part(self, fail_with, **kwargs):
        with mock.patch.object(settings, "llm_max_retries", 0):
            return self.run_with(Citing(fail_with=fail_with), **kwargs)[0]

    def test_a_quota_stop_then_a_resume_asks_only_what_is_missing_and_keeps_what_was_answered(self):
        first = self.first_part([None, None, None, quota()])
        self.assertEqual((len(first["rows"]), first["meta"]["complete"]), (3, False))
        again = Citing()
        resumed, _ = self.run_with(again, prior=first)
        self.assertTrue(resumed["meta"]["complete"])
        self.assertEqual(len(resumed["rows"]), 9)
        self.assertEqual(len(again.calls), 6)                                        # nine requests in all, three were already answered
        self.assertEqual(len({(r["question_id"], r["arm"]) for r in resumed["rows"]}), 9)
        self.assertEqual([r["request_id"] for r in resumed["rows"][:3]], [r["request_id"] for r in first["rows"]])        # the kept rows are the first part's, untouched
        self.assertEqual(len(resumed["meta"]["resumed"]), 1)
        self.assertEqual(resumed["meta"]["resumed"][0]["kept_rows"], 3)
        self.assertEqual(resumed["meta"]["calls_spent"], first["meta"]["calls_spent"] + 6)
        self.assertEqual(resumed["meta"]["started"], first["meta"]["started"])

    def test_requests_that_failed_are_set_aside_in_the_result_and_asked_again(self):
        first = self.first_part([None, refuse(), None, None, refuse(), None, None, None, None])
        self.assertEqual((len(first["rows"]), first["meta"]["complete"], sum(r["status"] == "error" for r in first["rows"])), (9, False, 2))
        again = Citing()
        resumed, _ = self.run_with(again, prior=first)
        self.assertTrue(resumed["meta"]["complete"])
        self.assertEqual(len(again.calls), 2)
        self.assertEqual(len(resumed["rows"]), 9)
        self.assertTrue(all(r["status"] == "ok" for r in resumed["rows"]))
        self.assertEqual([r["error_class"] for r in resumed["meta"]["set_aside_rows"]], ["BadRequestError", "BadRequestError"])

    def test_a_second_resume_keeps_the_history_of_the_first(self):
        first = self.first_part([None, None, quota()])
        second = self.first_part([None, quota()], prior=first)
        third, _ = self.run_with(Citing(), prior=second)
        self.assertEqual(len(third["meta"]["resumed"]), 2)
        self.assertTrue(third["meta"]["complete"])
        self.assertEqual(len(third["rows"]), 9)

    def test_the_failed_requests_of_every_session_stay_in_the_history_of_the_result(self):
        first = self.first_part([None, refuse(), None, None, None, None, None, None, None])
        self.assertEqual(sum(r["status"] == "error" for r in first["rows"]), 1)
        second = self.first_part([refuse()], prior=first)                          # the one failed request fails again
        self.assertEqual((len(second["meta"]["set_aside_rows"]), sum(r["status"] == "error" for r in second["rows"])), (1, 1))
        third, _ = self.run_with(Citing(), prior=second)
        self.assertTrue(third["meta"]["complete"])
        self.assertEqual(len(third["meta"]["set_aside_rows"]), 2)                   # the first failure and the second one, both kept
        self.assertEqual(len(third["meta"]["resumed"]), 2)

    def test_the_budget_of_a_resume_counts_its_own_requests(self):
        first = self.first_part([None, None, None, quota()])
        resumed, _ = self.run_with(Citing(), prior=first, max_calls=2)
        self.assertFalse(resumed["meta"]["complete"])
        self.assertEqual(len(resumed["rows"]), 3 + 2)
        self.assertIn("--max-calls", resumed["meta"]["stopped_because"])

    def test_a_measurement_that_changed_since_cannot_be_carried_on(self):
        first = self.first_part([None, quota()])
        changes = {"model_requested": lambda m: m.update(model_requested="another-model"),
                   "arms": lambda m: m["arms"][1]["overrides"].update(top_k=3),
                   "question_set": lambda m: m.update(question_set="0" * 12),
                   "settings": lambda m: m["settings"].update(top_k=9),
                   "dry_run": lambda m: m.update(dry_run=True)}
        for key, change in changes.items():
            with self.subTest(key=key):
                prior = copy.deepcopy(first)
                change(prior["meta"])
                with self.assertRaises(ValueError) as caught:
                    self.run_with(Citing(), prior=prior)
                self.assertIn("cannot resume", str(caught.exception))
        with mock.patch.object(cost_run, "code_stamp", return_value={"git": "another", "dirty": False}):
            with self.assertRaises(ValueError) as caught:
                self.run_with(Citing(), prior=first)
        self.assertIn("another commit", str(caught.exception))


class StopTests(test_cost_run.MeasureCase):
    def raising(self, exception, at):
        """A stand-in for pipeline.answer that fails on its `at`-th call and is the real one before it."""
        calls = []

        def answer(question):
            calls.append(question)
            if len(calls) == at:
                raise exception
            return pipeline.answer(question)
        return answer

    def test_a_failure_of_the_app_itself_stops_at_the_first_request_and_says_what_it_said(self):
        message = "Local embedding model not found under 'C:" + chr(92) + "Users" + chr(92) + "someone" + chr(92) + ".cache' (run download_model)"
        results, _ = self.run_with(Citing(), answer=self.raising(RuntimeError(message), 1))
        self.assertEqual(results["rows"], [])
        self.assertFalse(results["meta"]["complete"])
        reason = results["meta"]["stopped_because"]
        self.assertTrue(reason.startswith("the app could not answer: Local embedding model not found"))
        self.assertIn("<path>", reason)
        self.assertNotIn("someone", reason)                                          # a machine path never reaches a file that is committed
        self.assertNotIn("provider", reason)

    def test_a_missing_key_is_said_as_a_missing_key_not_as_a_provider_failure(self):
        results, _ = self.run_with(Citing(), answer=self.raising(RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."), 1))
        self.assertIn("OPENAI_API_KEY is not set", results["meta"]["stopped_because"])
        self.assertEqual(results["rows"], [])

    def test_ctrl_c_keeps_what_finished_and_says_it_was_interrupted(self):
        results, saves = self.run_with(Citing(), answer=self.raising(KeyboardInterrupt(), 5))
        self.assertEqual(results["meta"]["stopped_because"], "interrupted (Ctrl-C)")
        self.assertFalse(results["meta"]["complete"])
        self.assertEqual(len(results["rows"]), 4)
        self.assertEqual(saves[-1], 4)                                                # the last save holds what finished

    def test_plain_shortens_one_line_and_hides_drive_and_home_paths(self):
        self.assertEqual(cost_run.plain("a  b" + chr(10) + "c"), "a b c")
        self.assertEqual(cost_run.plain("see /home/me/x/y now"), "see <path> now")
        self.assertEqual(len(cost_run.plain("x" * 500)), 200)

    def test_a_failed_request_is_counted_by_the_requests_it_sent_not_as_one(self):
        item = cost_run.make_items(CASES[:1], [])[0]
        busy = status_error(openai.InternalServerError, 503, {"error": {"message": "busy"}})
        client = Citing(fail_with=[busy, busy, busy])
        with mock.patch.object(settings, "llm_max_retries", 2), mock.patch.object(llm, "_get_client", return_value=client), mock.patch.object(llm.time, "sleep"):
            row, requests = cost_run.ask_once(item, "before", {}, self.out, "served-model")
        self.assertEqual((row["status"], row["error_class"], requests), ("error", "InternalServerError", 3))
        self.assertEqual(len(client.calls), 3)                                        # three real requests

    def test_a_failure_before_any_call_counts_as_one_so_the_budget_never_under_counts(self):
        self.assertEqual(cost_run.requests_of(None), 1)
        self.assertEqual(cost_run.requests_of({"spans": [{"kind": "retrieve"}]}), 1)
        self.assertEqual(cost_run.requests_of({"spans": [{"kind": "model", "attempts": 4}]}), 4)

    def test_the_error_record_of_a_failed_request_keeps_the_tries_and_times_of_its_model_step_and_no_text(self):
        item = cost_run.make_items(CASES[:1], [])[0]
        busy = status_error(openai.InternalServerError, 503, {"error": {"message": "secret detail in a provider error"}})
        with mock.patch.object(settings, "llm_max_retries", 1), mock.patch.object(llm, "_get_client", return_value=Citing(fail_with=[busy, busy])), mock.patch.object(llm.time, "sleep"):
            cost_run.ask_once(item, "before", {}, self.out, "served-model")
        with open(os.path.join(self.out, "before", "errors.jsonl"), encoding="utf-8") as handle:
            raw = handle.read()
        record = json.loads(raw.splitlines()[0])
        model_span = next(span for span in record["spans"] if span["kind"] == "model")
        self.assertEqual(model_span["attempts"], 2)
        self.assertIn("provider_ms", model_span)
        self.assertNotIn("secret detail", raw)
        self.assertNotIn("How much notice", raw)


class RefusedColumnTests(unittest.TestCase):
    def test_the_summary_counts_the_answers_that_were_refusals_because_the_bank_has_no_rule_check(self):
        row = {"arm": "a", "status": "ok", "tokens_known": True, "prompt_tokens": 1, "completion_tokens": 1, "provider_ms": 1, "wait_ms": 0,
               "passed": None, "chars": None}
        rows = [dict(row, grounded=False), dict(row, grounded=True), dict(row, grounded=False, status="error")]
        self.assertEqual(cost_run.summarize_arms(rows)["a"]["refused"], 1)                # an error is not a refusal


class ScriptTests(test_cost_run.MeasureCase):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", os.path.join(self.out, "results")))
        self.enterContext(mock.patch.object(cost_run, "MEASURE_DIR", os.path.join(self.out, "measure")))

    def run_script(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = measure_cost.main(list(argv))
        return code, out.getvalue()

    LIVE = ["--label", "t", "--model", "served-model", "--only", "absent-bonus", "code-err4032"]

    def test_the_measurement_always_asks_the_base_cases_even_when_failures_have_been_converted(self):
        folder = os.path.join(self.out, "logged")
        os.makedirs(folder)
        with open(os.path.join(folder, cases.LOGGED_FAILURES_NAME), "w", encoding="utf-8") as handle:
            json.dump({"cases": [{"id": "log-converted", "question": "A new question?", "expected_sources": ["x.md"], "expect_contains": ["x"]}]}, handle)
        with mock.patch.object(cases, "REGRESSIONS_PATH", os.path.join(folder, "regressions.json")):
            self.assertIn("log-converted", [c["id"] for c in cases.all_cases()])
            self.assertEqual(len(cases.all_cases(base_only=True)), 41)
            self.assertNotIn("log-converted", [c["id"] for c in runner.select_cases(base_only=True)])
            code, text = self.run_script("--label", "t", "--dry-run", "--only", "log-converted")
        self.assertEqual(code, 1)
        self.assertIn("unknown case id", text)

    def test_the_free_screen_asks_the_base_cases_too(self):
        import estimate_context_savings
        folder = os.path.join(self.out, "logged2")
        os.makedirs(folder)
        with open(os.path.join(folder, cases.LOGGED_FAILURES_NAME), "w", encoding="utf-8") as handle:
            json.dump({"cases": [{"id": "log-converted", "question": "A new question?", "expected_sources": ["x.md"], "expect_contains": ["x"]}]}, handle)
        with mock.patch.object(cases, "REGRESSIONS_PATH", os.path.join(folder, "regressions.json")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = estimate_context_savings.main(["--only", "log-converted"])
        self.assertEqual(code, 1)
        self.assertIn("unknown case id", out.getvalue())

    def test_a_strip_already_on_in_the_settings_is_refused_because_every_arm_would_strip(self):
        with mock.patch.object(settings, "context_strip_min_repeats", 10):
            code, text = self.run_script(*self.LIVE)
        self.assertEqual(code, 1)
        self.assertIn("would strip too", text)
        self.assertEqual(self.run_script(*self.LIVE[:4], "--arm", "before:context_strip_min_repeats=0", "--arm", "after:context_strip_min_repeats=10",
                                         "--only", "absent-bonus", "--dry-run")[0], 0)           # naming it in every arm is allowed

    def test_the_prediction_cannot_be_checked_on_a_measurement_that_started_with_the_strip_on(self):
        results = build_measurement()
        results["meta"]["settings"] = {"context_strip_min_repeats": 10}
        self.assertIn("already on", cost_prediction.check_prediction(results)["cannot_check"])

    def test_a_label_that_would_name_a_folder_outside_its_own_is_refused(self):
        for bad in (".", "..", "_x", "a/b", "a b"):
            with self.subTest(label=bad):
                self.assertEqual(self.run_script("--label", bad, "--dry-run")[0], 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "measure")))

    def test_a_dry_run_with_embeddings_from_the_api_is_refused_because_it_would_spend_quota(self):
        with mock.patch.object(settings, "embed_provider", "openai"):
            code, text = self.run_script("--label", "t", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("EMBED_PROVIDER=local", text)

    def test_resume_and_force_together_or_resume_with_nothing_saved_are_errors(self):
        self.assertIn("pick one", self.run_script(*self.LIVE, "--resume", "--force")[1])
        code, text = self.run_script(*self.LIVE, "--resume")
        self.assertEqual(code, 1)
        self.assertIn("no saved measurement", text)

    def test_a_quota_stop_in_the_script_is_carried_on_by_resume_and_the_stopped_result_is_kept_aside(self):
        stopped = Citing(fail_with=[None, None, None, quota()])
        with mock.patch.object(llm, "_get_client", return_value=stopped), mock.patch.object(settings, "llm_max_retries", 0):
            code, text = self.run_script(*self.LIVE)
        self.assertEqual(code, 1)
        self.assertIn("Carry on with --resume", text)
        saved = cost_run.load_aggregate(cost_run.results_path("t"))
        self.assertEqual((len(saved["rows"]), saved["meta"]["complete"]), (3, False))
        again = Citing()
        with mock.patch.object(llm, "_get_client", return_value=again):
            code, text = self.run_script(*self.LIVE, "--resume")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(again.calls), 3)                                         # six requests in all, three were done
        self.assertIn("3 answered requests are kept, 0 failed ones are asked again", text)
        self.assertIn("moved aside", text)
        done = cost_run.load_aggregate(cost_run.results_path("t"))
        self.assertEqual((len(done["rows"]), done["meta"]["complete"]), (6, True))
        self.assertEqual(len([n for n in os.listdir(os.path.join(self.out, "results")) if ".replaced-" in n]), 1)
        code, text = self.run_script(*self.LIVE, "--resume")
        self.assertEqual((code, "Nothing to resume" in text), (0, True))

    def test_force_moves_the_old_result_aside_instead_of_deleting_it(self):
        with mock.patch.object(llm, "_get_client", return_value=Citing()):
            self.assertEqual(self.run_script(*self.LIVE)[0], 0)
            code, text = self.run_script(*self.LIVE)
            self.assertEqual(code, 1)
            self.assertIn("--resume to carry it on", text)
            self.assertEqual(self.run_script(*self.LIVE, "--force")[0], 0)
        aside = [n for n in os.listdir(os.path.join(self.out, "results")) if ".replaced-" in n]
        self.assertEqual(len(aside), 1)
        self.assertEqual(len(cost_run.load_aggregate(os.path.join(self.out, "results", aside[0]))["rows"]), 6)
        self.assertTrue(os.path.isdir(os.path.join(self.out, "measure", "t", "before")))

    def test_a_result_that_cannot_be_saved_does_not_end_the_run(self):
        with mock.patch.object(llm, "_get_client", return_value=Citing()), mock.patch.object(cost_run, "save_aggregate", side_effect=PermissionError("locked")):
            code, text = self.run_script(*self.LIVE)
        self.assertEqual(code, 0)
        self.assertIn("could not save (PermissionError)", text)
        self.assertIn("[  2/2]", text)                                                # every question was still asked


def build_measurement():
    import test_cost_prediction
    return test_cost_prediction.build()


if __name__ == "__main__":
    unittest.main()
