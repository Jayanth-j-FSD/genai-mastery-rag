"""Week 6 building blocks: the cases, the rule checks, the judge, the agreement maths and the report."""
import json
import os
import tempfile
import unittest
from unittest import mock

import _testkit
from _testkit import fake_response
from app.config import settings
from app.rag import diagnose, loader
from evals import agreement, cases, checks, judge, report

CORPUS = {doc["source"]: doc["text"] for doc in loader.load_documents(settings.corpus_dir)}
NORMALISED = {name: diagnose._normalize(text.replace("*", "")) for name, text in CORPUS.items()}
NO_REGRESSIONS = os.path.join(tempfile.gettempdir(), "no-such-regressions.json")


def n(text):
    return diagnose._normalize(text.replace("*", ""))


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.cases = cases.all_cases(NO_REGRESSIONS)

    def test_the_set_is_week_fours_32_plus_nine_new_nexora_cases(self):
        self.assertEqual(len(self.cases), 41)
        self.assertEqual(sum(1 for c in self.cases if c["origin"] == "week4"), 32)
        self.assertEqual(sum(1 for c in self.cases if c["origin"] == "week6"), 9)
        self.assertEqual(len({c["id"] for c in self.cases}), 41)

    def test_every_case_has_a_problem_type_and_every_base_case_a_reference(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertNotEqual(case["problem_type"], "other")
                self.assertTrue(case["reference"], "a human-written reference is needed for the judge")

    def test_refusal_cases_are_exactly_the_absent_topics(self):
        refusals = {c["id"] for c in self.cases if c["should_refuse"]}
        self.assertEqual(refusals, {"absent-bonus", "absent-dress-code", "absent-azure-subscription-id",
                                    "absent-azure-admin-limit"})

    def test_the_new_cases_expected_phrases_really_appear_in_their_documents(self):
        for case in (c for c in self.cases if c["origin"] == "week6"):
            for source in case["expected_sources"]:
                self.assertIn(source, CORPUS)
            for phrase in case["expect_all"]:                       # every required phrase must be in a source
                with self.subTest(case=case["id"], phrase=phrase):
                    self.assertTrue(any(n(phrase) in NORMALISED[s] for s in case["expected_sources"]))
            if case["expect_contains"]:                              # of the alternatives, at least one must be
                with self.subTest(case=case["id"], any_of=case["expect_contains"]):
                    self.assertTrue(any(n(p) in NORMALISED[s] for p in case["expect_contains"] for s in case["expected_sources"]))

    def test_every_reference_states_the_facts_the_rule_checks_look_for(self):
        for case in self.cases:
            if case["should_refuse"]:
                continue
            reference = n(case["reference"])
            with self.subTest(case=case["id"]):
                for phrase in case["expect_all"]:
                    self.assertIn(n(phrase), reference)
                if case["expect_contains"]:
                    self.assertTrue(any(n(p) in reference for p in case["expect_contains"]))

    def test_problem_types_group_the_cases_into_a_handful_of_kinds(self):
        types = {c["problem_type"] for c in self.cases}
        self.assertEqual(types, {"exact-string", "paraphrase", "single-fact", "conflicting-documents",
                                 "careful-reading", "list-answer", "crowded-handbook", "absent-topic"})


class RegressionLoadingTests(unittest.TestCase):
    def write(self, tmp, payload):
        path = os.path.join(tmp, "regressions.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cases": payload}, handle)
        return path

    def test_week5_failures_are_merged_and_flagged_until_their_expectations_are_filled_in(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = self.write(tmp, [
                {"id": "w5-a1", "question": "q1", "problem_type": "wrong-doc", "origin": "week5:a1"},
                {"id": "w5-a2", "question": "q2", "problem_type": "made-up", "origin": "week5:a2", "should_refuse": True},
                {"id": "w5-a3", "question": "q3", "problem_type": "wrong-doc", "origin": "week5:a3",
                 "expected_sources": ["Acme-Leave-Policy-2026.md"], "expect_contains": ["16 weeks"]},
            ])
            merged = {c["id"]: c for c in cases.all_cases(path)}
        self.assertEqual(len(merged), 44)
        self.assertTrue(merged["w5-a1"]["needs_expected"])
        self.assertFalse(merged["w5-a1"]["should_refuse"])
        self.assertFalse(merged["w5-a2"]["needs_expected"])
        self.assertTrue(merged["w5-a2"]["should_refuse"])
        self.assertFalse(merged["w5-a3"]["needs_expected"])

    def test_a_missing_file_means_no_regressions_yet(self):
        self.assertEqual(cases.load_regressions(NO_REGRESSIONS), [])

    def test_a_regression_id_that_clashes_with_a_base_case_is_refused(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = self.write(tmp, [{"id": "code-err4032", "question": "q", "problem_type": "x", "origin": "week5:z"}])
            with self.assertRaises(ValueError):
                cases.all_cases(path)


def case(**overrides):
    base = {"id": "c1", "question": "How many weeks of parental leave?", "expected_sources": ["Acme-Leave-Policy-2026.md"],
            "expect_contains": ["16 weeks"], "expect_all": [], "should_refuse": False}
    base.update(overrides)
    return base


def result(answer="Eligible employees may take 16 weeks. [source: Acme-Leave-Policy-2026.md]", grounded=True,
           sources=("Acme-Leave-Policy-2026.md",), text="Eligible employees may take 16 weeks of paid parental leave."):
    return {"answer": answer, "grounded": grounded, "sources": list(sources),
            "retrieved": [{"source": "Acme-Leave-Policy-2026.md", "text": text}]}


class CheckTests(unittest.TestCase):
    def test_a_correct_cited_answer_passes_every_rule(self):
        found, passed, warnings = checks.check_case(case(), result())
        self.assertTrue(passed)
        self.assertEqual([c["name"] for c in found], ["refusal", "cites_expected_source", "has_expected_fact"])
        self.assertEqual(warnings, [])

    def test_refusing_an_answerable_question_fails(self):
        found, passed, _ = checks.check_case(case(), result("I don't know based on the provided documents.", False, []))
        self.assertFalse(passed)
        self.assertIn("refused a question the documents do answer", found[0]["detail"])

    def test_answering_an_absent_topic_fails_and_refusing_it_passes(self):
        absent = case(id="absent", expected_sources=[], expect_contains=[], should_refuse=True)
        self.assertFalse(checks.check_case(absent, result("It is 10%.", True, []))[1])
        self.assertTrue(checks.check_case(absent, result("I don't know based on the provided documents.", False, []))[1])

    def test_citing_the_wrong_document_fails(self):
        found, passed, _ = checks.check_case(case(), result(sources=("benefits.md",)))
        self.assertFalse(passed)
        self.assertIn("benefits.md", found[1]["detail"])

    def test_any_one_expected_phrase_is_enough_but_all_of_expect_all_are_needed(self):
        lenient = case(expect_contains=["16 weeks", "sixteen weeks"])
        self.assertTrue(checks.check_case(lenient, result("It is sixteen weeks. [source: Acme-Leave-Policy-2026.md]"))[1])
        listy = case(expect_contains=[], expect_all=["development", "testing", "production"])
        self.assertTrue(checks.check_case(listy, result("Development, Testing and Production."))[1])
        found, passed, _ = checks.check_case(listy, result("Development and Production."))
        self.assertFalse(passed)
        self.assertIn("testing", found[2]["detail"])

    def test_matching_ignores_case_markdown_and_thousands_separators(self):
        money = case(expect_contains=["$1,000"], expected_sources=["benefits.md"])
        self.assertTrue(checks.check_case(money, result("The budget is **$1000** per year.", sources=("benefits.md",)))[1])

    def test_a_case_with_no_expected_phrases_is_scored_on_refusal_and_source_only(self):
        found, passed, _ = checks.check_case(case(expect_contains=[]), result("Whatever it says. [source: x]"))
        self.assertEqual([c["name"] for c in found], ["refusal", "cites_expected_source"])
        self.assertTrue(passed)

    def test_a_number_the_model_was_never_shown_is_warned_about(self):
        _, passed, warnings = checks.check_case(case(), result("It is 16 weeks, or about 112 days. [source: Acme-Leave-Policy-2026.md]"))
        self.assertTrue(passed)                                     # a warning is not a failure
        self.assertIn("112", warnings[0])

    def test_numbers_in_the_question_or_a_citation_are_not_warnings(self):
        extra = checks.invented_numbers(result("In 2026 it is 16 weeks. [source: Acme-Leave-Policy-2026.md]"),
                                        "Is it 2026 and how many weeks?")
        self.assertEqual(extra, [])
        self.assertEqual(checks.invented_numbers(result("See [source: Acme-Leave-Policy-2026.md]."), "q"), [])

    def test_the_numbers_that_number_a_list_are_not_invented_figures(self):
        answer = "The four levels are:\n1. Public\n2. Internal\n  3) Confidential\n(4) Restricted"
        self.assertEqual(checks.invented_numbers(result(answer), "What are the levels?"), [])
        self.assertEqual(checks.invented_numbers(result("It is 5 days"), "What are the levels?"), ["5"])    # a real figure still counts

    def test_a_week5_failure_without_expectations_says_so_and_only_checks_refusal(self):
        pending = case(expected_sources=[], expect_contains=[], needs_expected=True)
        found, passed, warnings = checks.check_case(pending, result())
        self.assertEqual([c["name"] for c in found], ["refusal"])
        self.assertTrue(passed)
        self.assertIn("no expected facts yet", warnings[0])


class JudgeTests(unittest.TestCase):
    def test_parse_reads_clean_fenced_and_chatty_replies(self):
        self.assertEqual(judge.parse_verdict('{"reason": "faithful", "verdict": "pass"}'),
                         {"verdict": "pass", "reason": "faithful"})
        fenced = 'Here you go:\n```json\n{"reason": "invented 24", "verdict": "FAIL"}\n```'
        self.assertEqual(judge.parse_verdict(fenced)["verdict"], "fail")

    def test_unreadable_replies_are_errors_never_guesses(self):
        for text in ("", None, "pass", "the answer looks fine", '{"verdict": "maybe"}', '{"reason": "x"}', "{broken json}"):
            with self.subTest(text=text):
                self.assertEqual(judge.parse_verdict(text)["verdict"], "error")

    def test_the_prompt_shows_the_context_with_sources_and_the_reference_only_when_given(self):
        retrieved = [{"source": "A.md", "text": "Alpha fact."}, {"source": "B.md", "text": "Beta fact."}]
        with_reference = judge.build_prompt("Q?", retrieved, "An answer.", "The reference.")
        self.assertIn("[source: A.md]\nAlpha fact.", with_reference)
        self.assertIn("REFERENCE:\nThe reference.", with_reference)
        self.assertTrue(with_reference.rstrip().endswith("ANSWER:\nAn answer."))
        self.assertNotIn("REFERENCE", judge.build_prompt("Q?", retrieved, "An answer."))
        self.assertIn("(nothing was retrieved)", judge.build_prompt("Q?", [], "An answer."))

    def test_the_rubric_asks_for_reason_first_and_covers_absence_and_conflicts(self):
        prompt = judge.SYSTEM_PROMPT
        self.assertLess(prompt.index('"reason"'), prompt.index('"verdict"'))
        for idea in ("Faithful", "Responsive", "Honest about absence", "Conflicts"):
            self.assertIn(idea, prompt)

    def test_the_cache_key_changes_with_anything_that_could_change_the_verdict(self):
        retrieved = [{"source": "A.md", "text": "t"}]
        base = judge.cache_key("m1", "q", retrieved, "a", "r")
        self.assertEqual(base, judge.cache_key("m1", "q", retrieved, "a", "r"))
        for changed in (judge.cache_key("m2", "q", retrieved, "a", "r"), judge.cache_key("m1", "q2", retrieved, "a", "r"),
                        judge.cache_key("m1", "q", [{"source": "A.md", "text": "t2"}], "a", "r"),
                        judge.cache_key("m1", "q", retrieved, "a2", "r"), judge.cache_key("m1", "q", retrieved, "a", "r2")):
            self.assertNotEqual(base, changed)
        with mock.patch.object(judge, "RUBRIC_VERSION", "2"):
            self.assertNotEqual(base, judge.cache_key("m1", "q", retrieved, "a", "r"))

    def test_judge_answer_uses_the_judge_model_its_own_limit_and_zero_temperature(self):
        with mock.patch("app.llm.chat", return_value=fake_response('{"reason": "ok", "verdict": "pass"}')) as chat, \
                mock.patch.object(settings, "judge_model", "judge-x"), mock.patch.object(settings, "judge_rpm", 9):
            verdict = judge.judge_answer("Q?", [], "A.")
        self.assertEqual((verdict["verdict"], verdict["model"]), ("pass", "judge-x"))
        self.assertEqual((chat.call_args.kwargs["model"], chat.call_args.kwargs["rpm"], chat.call_args.kwargs["temperature"]),
                         ("judge-x", 9, 0))

    def test_without_a_judge_model_the_answer_model_judges_and_the_answer_limit_applies(self):
        with mock.patch.object(settings, "judge_model", ""), mock.patch.object(settings, "judge_rpm", 0), \
                mock.patch.object(settings, "llm_model", "answerer"), mock.patch.object(settings, "llm_rpm", 5):
            self.assertEqual(judge.judge_model(), "answerer")
            with mock.patch("app.llm.chat", return_value=fake_response('{"reason": "r", "verdict": "fail"}')) as chat:
                judge.judge_answer("Q?", [], "A.")
        self.assertEqual(chat.call_args.kwargs["rpm"], 5)


class AgreementTests(unittest.TestCase):
    def pairs(self, both_pass, both_fail, harsh, lenient):
        return ([("pass", "pass")] * both_pass + [("fail", "fail")] * both_fail
                + [("pass", "fail")] * harsh + [("fail", "pass")] * lenient)

    def test_perfect_agreement_is_kappa_one(self):
        stats = agreement.agreement_stats(self.pairs(10, 10, 0, 0))
        self.assertEqual((stats["percent"], stats["kappa"]), (1.0, 1.0))

    def test_a_worked_example(self):
        # 20 both pass, 15 both fail, 5 judge too harsh, 10 judge too lenient: po 0.7, pe 0.5, kappa 0.4
        stats = agreement.agreement_stats(self.pairs(20, 15, 5, 10))
        self.assertAlmostEqual(stats["percent"], 0.7)
        self.assertAlmostEqual(stats["kappa"], 0.4)
        self.assertEqual((stats["judge_harsh"], stats["judge_lenient"]), (5, 10))
        self.assertAlmostEqual(stats["human_pass_rate"], 0.5)
        self.assertAlmostEqual(stats["judge_pass_rate"], 0.6)

    def test_always_saying_pass_looks_good_on_percent_but_kappa_exposes_it(self):
        # 19 of 20 answers are good and the judge passes everything: 95% agreement, kappa 0.
        stats = agreement.agreement_stats(self.pairs(19, 0, 0, 1))
        self.assertAlmostEqual(stats["percent"], 0.95)
        self.assertAlmostEqual(stats["kappa"], 0.0)
        self.assertFalse(agreement.is_trustworthy(stats))

    def test_identical_verdicts_everywhere_leave_kappa_undefined_and_untrusted(self):
        stats = agreement.agreement_stats(self.pairs(10, 0, 0, 0))
        self.assertIsNone(stats["kappa"])
        self.assertFalse(agreement.is_trustworthy(stats))
        self.assertIn("undefined", agreement.kappa_label(None))

    def test_no_pairs_is_handled(self):
        stats = agreement.agreement_stats([])
        self.assertEqual((stats["n"], stats["percent"], stats["kappa"]), (0, None, None))
        self.assertFalse(agreement.is_trustworthy(stats))

    def test_the_trust_bars_need_both_agreement_and_kappa(self):
        good = agreement.agreement_stats(self.pairs(20, 20, 2, 2))
        self.assertTrue(agreement.is_trustworthy(good))
        self.assertFalse(agreement.is_trustworthy(good, min_kappa=0.95))
        self.assertFalse(agreement.is_trustworthy(good, min_agreement=0.99))

    def test_kappa_labels(self):
        self.assertEqual(agreement.kappa_label(-0.1), "worse than chance")
        self.assertEqual(agreement.kappa_label(0.5), "moderate")
        self.assertEqual(agreement.kappa_label(0.7), "substantial")
        self.assertEqual(agreement.kappa_label(0.95), "almost perfect")


def entry(case_id, ptype, passed, verdict=None):
    return {"id": case_id, "problem_type": ptype, "passed": passed, "checks": [{"name": "refusal", "passed": passed, "detail": f"{case_id} detail"}],
            "judge": None if verdict is None else {"verdict": verdict, "reason": f"{case_id} reason"}, "warnings": []}


def run(label, entries):
    return {"meta": {"label": label, "models": {"answer": "a", "judge": "j"}, "settings": {"retrieval_mode": "dense"},
                     "chunk_count": 10}, "cases": entries}


class ReportTests(unittest.TestCase):
    def test_summary_counts_rules_judge_and_both_per_type(self):
        data = run("r", [entry("a", "x", True, "pass"), entry("b", "x", True, "fail"), entry("c", "y", False, "pass"),
                         entry("d", "y", True, "error")])
        summary = report.summarize(data)
        self.assertEqual(summary["by_type"]["x"], {"n": 2, "rules": 2, "judged": 2, "judge_pass": 1, "judge_error": 0, "both": 1})
        self.assertEqual(summary["by_type"]["y"], {"n": 2, "rules": 1, "judged": 2, "judge_pass": 1, "judge_error": 1, "both": 0})
        self.assertEqual(summary["overall"]["n"], 4)

    def test_without_a_judge_the_headline_is_the_rules_alone(self):
        summary = report.summarize(run("r", [entry("a", "x", True), entry("b", "x", False)]))
        self.assertEqual(report.headline(summary["overall"]), 0.5)

    def test_the_text_report_names_the_failing_cases_and_why(self):
        text = "\n".join(report.format_summary(run("r", [entry("a", "x", True, "pass"), entry("b", "x", True, "fail")])))
        self.assertIn("problem type", text)
        self.assertIn("b (x)", text)
        self.assertIn("judge: b reason", text)
        self.assertNotIn("a (x)", text)

    def test_compare_finds_fixed_broken_and_still_failing_cases(self):
        before = run("before", [entry("a", "x", False), entry("b", "x", True), entry("c", "y", False), entry("d", "y", True)])
        after = run("after", [entry("a", "x", True), entry("b", "x", False), entry("c", "y", False), entry("d", "y", True)])
        result = report.compare(before, after)
        self.assertEqual((result["fixed"], result["regressed"], result["still_failing"]), (["a"], ["b"], ["c"]))
        self.assertEqual(result["types"]["x"], {"n": 2, "before": 1, "after": 1})
        self.assertEqual(result["total"], {"n": 4, "before": 2, "after": 2})

    def test_compare_only_counts_cases_present_in_both_runs_and_says_which_were_left_out(self):
        result = report.compare(run("b", [entry("a", "x", True), entry("only-old", "x", True)]),
                                run("a", [entry("a", "x", True), entry("only-new", "x", True)]))
        self.assertEqual((result["only_before"], result["only_after"], result["total"]["n"]), (["only-old"], ["only-new"], 1))

    def test_the_comparison_text_has_the_table_the_lists_and_an_honest_caveat(self):
        text = "\n".join(report.format_compare(run("baseline", [entry("a", "x", False)]), run("after", [entry("a", "x", True)])))
        for needle in ("before 'baseline' vs after 'after'", "+100pt", "fixed by the change    : 1", "one case moves the overall score by 100.0%"):
            self.assertIn(needle, text)

    def test_comparing_runs_with_nothing_in_common_does_not_crash(self):
        text = "\n".join(report.format_compare(run("b", [entry("a", "x", True)]), run("a", [entry("z", "x", True)])))
        self.assertIn("No cases in common", text)


if __name__ == "__main__":
    unittest.main()
