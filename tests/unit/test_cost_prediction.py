"""Week 11: the pre-registered cost prediction (evals/cost_prediction.py, docs/week11/prediction.md, scripts/check_cost_prediction.py)."""
import contextlib
import copy
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from evals import cost_prediction as prediction, cost_run, runner

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import check_cost_prediction                             # noqa: E402

CONFLICTS = list(prediction.CONFLICT_QUESTIONS)
EVAL_IDS = [f"case-{number}" for number in range(38)] + CONFLICTS
ARMS = [{"name": "before", "overrides": {}}, {"name": "after", "overrides": {"context_strip_min_repeats": 10}}, {"name": "before-2", "overrides": {}}]


def row(question, arm, kind="eval", prompt=1000, completion=100, passed=True, sources=("a.md",), stripped=0, status="ok", known=True):
    return {"question_id": question, "kind": kind, "arm": arm, "status": status, "tokens_known": known,
            "prompt_tokens": prompt if known else None, "completion_tokens": completion if known else None, "passed": None if kind == "bank" else passed,
            "sources": list(sources), "chars": {"stripped": stripped}, "error_class": None}


def build(after_prompt=800, noise_prompt=None, after_completion=100, bank=0, bank_after=700, **changes):
    """A saved measurement: 41 eval questions and `bank` bank questions under the three arms. Every number can be changed per test."""
    rows = []
    for question in EVAL_IDS:
        rows.append(row(question, "before"))
        rows.append(row(question, "after", prompt=after_prompt, completion=after_completion, stripped=300))
        rows.append(row(question, "before-2", prompt=noise_prompt or 1000))
    for number in range(bank):
        rows += [row(f"bank-{number}", "before", kind="bank"), row(f"bank-{number}", "after", kind="bank", prompt=bank_after),
                 row(f"bank-{number}", "before-2", kind="bank")]
    meta = {"label": "t", "dry_run": False, "complete": True, "stopped_because": None, "arms": copy.deepcopy(ARMS),
            "n_questions": len(EVAL_IDS) + bank, "n_eval": len(EVAL_IDS), "n_bank": bank}
    meta.update(changes)
    return {"meta": meta, "rows": rows}


def verdict_row(results, item):
    return next(r for r in prediction.check_prediction(results)["rows"] if r["id"] == item)


class DocumentTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_testkit.ROOT, "docs", "week11", "prediction.md"), encoding="utf-8") as handle:
            self.document = " ".join(handle.read().split())
        self.module_text = " ".join(prediction.__doc__.split())

    def test_the_document_states_the_thresholds_the_module_checks_so_neither_can_drift_alone(self):
        text = self.document
        low, high = prediction.TOKEN_BANDS["eval"]
        self.assertIn(f"the mean after / before is between {low:.2f} and {high:.2f}", text)
        low, high = prediction.TOKEN_BANDS["bank"]
        self.assertIn(f"between {low:.2f} and {high:.2f} | ratio of mean prompt tokens", text)
        self.assertIn(f"at least {prediction.MIN_BANK_QUESTIONS} were asked", text)
        self.assertIn(f"on at least {prediction.SAME_PROMPT_SHARE:.0%} of the questions", text)
        self.assertIn(f"differ by less than {prediction.NOISE_MEAN_DIFFERENCE:.0%}", text)
        low, high = prediction.COMPLETION_BAND
        self.assertIn(f"mean after / before is between {low:.2f} and {high:.2f} | ratio of mean completion tokens", text)
        self.assertIn(f"at least {prediction.REACH_SHARE:.0%} of the eval requests", text)
        self.assertIn(f"{prediction.REGISTERED_EVAL_QUESTIONS} eval questions", text)
        self.assertIn("The prediction has FAILED if " + ", ".join(prediction.FAILS_IF[:-1]) + " or " + prediction.FAILS_IF[-1] + " does not hold", text)
        for question in prediction.CONFLICT_QUESTIONS:
            self.assertIn(question, text)
        for arm in prediction.REGISTERED_ARMS:
            self.assertIn(f"`{arm}`", text)

    def test_the_figures_quoted_from_the_free_screen_are_the_same_in_the_document_and_the_module(self):
        for figure in ("17.9%", "27.2%", "0.77 to 0.88", "0.65 to 0.82", "between 0.65 and 1.3"):
            self.assertIn(figure, self.document)
            self.assertIn(figure, self.module_text)
        self.assertIn("9.8%", self.document)                         # idea C, screened and not built

    def test_the_document_says_it_was_written_before_the_first_request_and_who_decides_to_ship(self):
        self.assertIn("before any request was sent to the model", self.document)
        self.assertIn("which is your decision", self.document)
        self.assertNotIn("—", self.document)


class BandTests(unittest.TestCase):
    def test_p1_holds_on_the_edges_of_the_band_and_not_outside_it(self):
        for after, held in ((750, True), (900, True), (820, True), (740, False), (910, False)):
            with self.subTest(after=after):
                self.assertEqual(verdict_row(build(after_prompt=after), "P1")["held"], held)

    def test_p1_compares_the_ratio_as_it_is_printed(self):
        self.assertTrue(verdict_row(build(after_prompt=749), "P1")["held"])       # 0.749 prints as 0.75, which is inside the band
        self.assertIn("ratio 0.75", verdict_row(build(after_prompt=749), "P1")["evidence"])

    def test_p2_is_only_read_when_enough_bank_questions_were_asked(self):
        self.assertFalse(verdict_row(build(bank=10), "P2")["decidable"])
        for after, held in ((620, True), (850, True), (610, False), (860, False)):
            with self.subTest(after=after):
                self.assertEqual(verdict_row(build(bank=20, bank_after=after), "P2")["held"], held)
        self.assertFalse(verdict_row(build(bank=19), "P2")["decidable"])
        self.assertTrue(verdict_row(build(bank=20), "P2")["decidable"])

    def test_p4_completion_tokens_hold_on_the_edges_and_not_outside(self):
        for after, held in ((85, True), (115, True), (84, False), (116, False)):
            with self.subTest(after=after):
                self.assertEqual(verdict_row(build(after_completion=after), "P4")["held"], held)

    def test_p3_needs_the_same_prompt_on_95_percent_of_the_questions_and_means_within_one_percent(self):
        self.assertTrue(verdict_row(build(), "P3")["held"])
        results = build()
        for r in [r for r in results["rows"] if r["arm"] == "before-2"][:2]:      # 2 of 41 differ: 39 of 41 is 95.1%
            r["prompt_tokens"] = 1001
        self.assertTrue(verdict_row(results, "P3")["held"])
        for r in [r for r in results["rows"] if r["arm"] == "before-2"][:3]:      # 3 of 41 differ: 38 of 41 is 92.7%
            r["prompt_tokens"] = 1001
        self.assertFalse(verdict_row(results, "P3")["held"])
        self.assertFalse(verdict_row(build(noise_prompt=1011), "P3")["held"])      # every question differs, and by 1.1%

    def test_p3_sits_exactly_on_both_edges_at_95_percent_equal_and_a_one_percent_difference_of_means(self):
        # 41 eval and 19 bank questions: 60 in all, so three differing questions are exactly 5% and 57 equal ones exactly 95%
        for extra, held in ((199, True), (200, False), (300, False)):
            with self.subTest(extra=extra):
                results = build(bank=19)
                for r in [r for r in results["rows"] if r["arm"] == "before-2" and r["kind"] == "eval"][:3]:
                    r["prompt_tokens"] = 1000 + extra                     # three questions differ: 200 each is exactly 1.0% of the mean
                self.assertEqual(verdict_row(results, "P3")["held"], held)

    def test_p7_the_strip_must_reach_at_least_sixty_percent_of_the_eval_requests(self):
        for reached, held in ((25, True), (24, False)):
            with self.subTest(reached=reached):
                results = build()
                for r in [r for r in results["rows"] if r["arm"] == "after"][reached:]:
                    r["chars"]["stripped"] = 0
                self.assertEqual(verdict_row(results, "P7")["held"], held)


class QualityTests(unittest.TestCase):
    def flip(self, results, question, arm, passed):
        for r in results["rows"]:
            if r["question_id"] == question and r["arm"] == arm:
                r["passed"] = passed

    def test_p5_a_question_that_passes_before_and_fails_after_breaks_the_prediction(self):
        results = build()
        self.flip(results, "case-3", "after", False)
        self.assertFalse(verdict_row(results, "P5")["held"])
        check = prediction.check_prediction(results)
        self.assertEqual((check["verdict"], check["failed"]), ("FAILED", ["P5"]))

    def test_p5_a_question_that_also_differs_between_the_two_untouched_arms_is_noise(self):
        results = build()
        self.flip(results, "case-3", "after", False)
        self.flip(results, "case-3", "before-2", False)
        self.assertTrue(verdict_row(results, "P5")["held"])
        self.assertIn("set aside as noise", verdict_row(results, "P5")["evidence"])

    def test_p5_a_question_that_starts_failing_and_ends_passing_is_not_a_regression(self):
        results = build()
        self.flip(results, "case-3", "before", False)
        self.flip(results, "case-3", "before-2", False)
        self.assertTrue(verdict_row(results, "P5")["held"])

    def test_p6_a_document_cited_before_and_not_after_breaks_the_prediction(self):
        results = build()
        for r in results["rows"]:
            if r["question_id"] == CONFLICTS[0]:
                r["sources"] = ["a.md", "b.md"] if r["arm"] != "after" else ["a.md"]
        self.assertFalse(verdict_row(results, "P6")["held"])
        self.assertIn("b.md", verdict_row(results, "P6")["evidence"])
        self.assertEqual(prediction.check_prediction(results)["failed"], ["P6"])

    def test_p6_citing_more_after_than_before_loses_nothing(self):
        results = build()
        for r in results["rows"]:
            if r["question_id"] == CONFLICTS[1] and r["arm"] == "after":
                r["sources"] = ["a.md", "b.md"]
        self.assertTrue(verdict_row(results, "P6")["held"])

    def test_p6_a_conflict_question_that_errored_leaves_the_measurement_partial_and_gives_no_verdict(self):
        results = build()
        for r in results["rows"]:
            if r["question_id"] == CONFLICTS[2] and r["arm"] == "after":
                r.update(status="error", tokens_known=False, prompt_tokens=None, completion_tokens=None)
        check = prediction.check_prediction(results)
        self.assertIsNone(verdict_row(results, "P6")["held"])
        self.assertIsNone(check["verdict"])
        self.assertTrue(any("40 of 41" in reason for reason in check["partial"]))

    def test_p6_needs_all_three_conflict_questions_not_just_two(self):
        results = build()
        for r in results["rows"]:
            if r["question_id"] == CONFLICTS[0]:
                r["question_id"] = "other-" + r["question_id"]          # 41 complete questions, but only two of the three P6 reads
        check = prediction.check_prediction(results)
        self.assertIsNone(check["verdict"])
        self.assertFalse(verdict_row(results, "P6")["decidable"])
        self.assertIn("2 of the 3", verdict_row(results, "P6")["evidence"])

    def test_p6_when_the_conflict_questions_are_not_in_the_measurement_it_is_undecided_not_failed(self):
        results = build()
        for r in results["rows"]:
            if r["question_id"] in CONFLICTS:
                r["question_id"] = "other-" + r["question_id"]          # 41 complete questions, but not the three P6 reads
        check = prediction.check_prediction(results)
        self.assertIsNone(check["verdict"])
        self.assertTrue(any("P6" in reason for reason in check["partial"]))
        self.assertFalse(verdict_row(results, "P6")["decidable"])


class VerdictTests(unittest.TestCase):
    def test_everything_held_means_the_prediction_did_not_fail_and_nothing_says_to_ship(self):
        check = prediction.check_prediction(build(bank=30))
        self.assertEqual((check["verdict"], check["failed"]), ("did not fail", []))
        self.assertTrue(all(r["held"] for r in check["rows"]))
        text = "\n".join(prediction.format_prediction(check))
        self.assertIn("did not fail", text)
        self.assertIn("your decision", text)

    def test_p1_out_of_band_fails_the_prediction(self):
        check = prediction.check_prediction(build(after_prompt=950))
        self.assertEqual((check["verdict"], check["failed"]), ("FAILED", ["P1"]))
        self.assertIn("FAILED (P1 did not hold)", "\n".join(prediction.format_prediction(check)))

    def test_p2_p3_p4_and_p7_failing_is_reported_but_does_not_fail_the_prediction(self):
        results = build(bank=30, bank_after=950, after_completion=50, noise_prompt=1100)
        for r in [r for r in results["rows"] if r["arm"] == "after" and r["kind"] == "eval"]:
            r["chars"]["stripped"] = 0
        check = prediction.check_prediction(results)
        self.assertEqual(check["verdict"], "did not fail")
        self.assertEqual([r["id"] for r in check["rows"] if r["held"] is False], ["P2", "P3", "P4", "P7"])


class PartialTests(unittest.TestCase):
    def test_a_dry_run_gets_no_verdict(self):
        check = prediction.check_prediction(build(dry_run=True))
        self.assertIn("dry run", check["cannot_check"])
        self.assertIsNone(check["verdict"])

    def test_a_measurement_that_stopped_early_gets_a_partial_banner_and_no_verdict(self):
        check = prediction.check_prediction(build(complete=False, stopped_because="the provider's daily quota is used up"))
        self.assertIsNone(check["verdict"])
        self.assertTrue(any("daily quota" in reason for reason in check["partial"]))
        self.assertTrue(all(r["held"] is None and r["decidable"] is False for r in check["rows"]))      # nothing is read as held or not held
        text = "\n".join(prediction.format_prediction(check))
        self.assertIn("PARTIAL", text)
        self.assertIn("not decidable", text)
        self.assertNotIn("FAILED", text)
        self.assertNotIn("did not fail", text)

    def test_fewer_eval_questions_than_registered_is_partial(self):
        check = prediction.check_prediction(build(n_eval=30))
        self.assertIsNone(check["verdict"])
        self.assertTrue(any("registered for 41" in reason for reason in check["partial"]))

    def test_a_question_an_arm_did_not_answer_makes_the_measurement_partial(self):
        results = build()
        results["rows"] = [r for r in results["rows"] if not (r["question_id"] == "case-0" and r["arm"] == "after")]
        check = prediction.check_prediction(results)
        self.assertIsNone(check["verdict"])
        self.assertTrue(any("40 of 41" in reason for reason in check["partial"]))

    def test_other_arms_or_other_settings_than_the_registered_ones_cannot_be_checked(self):
        renamed = build()
        renamed["meta"]["arms"][1]["name"] = "strip"
        self.assertIn("registered arms", prediction.check_prediction(renamed)["cannot_check"])
        changed = build()
        changed["meta"]["arms"][1]["overrides"] = {"context_strip_min_repeats": 6}
        self.assertIn("the strip at 10", prediction.check_prediction(changed)["cannot_check"])
        unfair = build()
        unfair["meta"]["arms"][2]["overrides"] = {"top_k": 3}
        self.assertIn("registered arms change nothing", prediction.check_prediction(unfair)["cannot_check"])

    def test_requests_without_the_providers_token_counts_are_left_out_not_counted_as_zero(self):
        results = build()
        for r in results["rows"]:
            if r["question_id"] == "case-0" and r["arm"] == "before":
                r.update(tokens_known=False, prompt_tokens=None, completion_tokens=None)
        check = prediction.check_prediction(results)
        self.assertIsNone(check["verdict"])                         # that question is no longer answered by every arm with token counts
        self.assertTrue(any("40 of 41" in reason for reason in check["partial"]))


class ScriptTests(unittest.TestCase):
    def run_script(self, results, label="t"):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        out = io.StringIO()
        with mock.patch.object(runner, "RESULTS_DIR", folder), contextlib.redirect_stdout(out):
            if results is not None:
                cost_run.save_aggregate(results, cost_run.results_path(label))
            code = check_cost_prediction.main([label])
        return code, out.getvalue()

    def test_a_complete_measurement_prints_every_prediction_and_exits_zero(self):
        code, text = self.run_script(build(bank=30))
        self.assertEqual(code, 0)
        for item in ("P1", "P2", "P3", "P4", "P5", "P6", "P7"):
            self.assertIn(item, text)
        self.assertIn("did not fail", text)

    def test_a_partial_or_missing_measurement_exits_non_zero(self):
        self.assertEqual(self.run_script(build(complete=False))[0], 1)
        code, text = self.run_script(None, label="nothing-here")
        self.assertEqual(code, 1)
        self.assertIn("Error", text)

    def test_a_failed_prediction_is_a_result_not_an_error(self):
        code, text = self.run_script(build(after_prompt=990))
        self.assertEqual(code, 0)
        self.assertIn("FAILED", text)


if __name__ == "__main__":
    unittest.main()
