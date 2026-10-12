"""Week 11: a real failure found in the log becomes a permanent test (scripts/failure_to_test.py, the logged-failures channel, the fixtures)."""
import contextlib
import glob
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from _testkit import ROOT, isolated_index
from app.config import settings
from evals import cases, checks, runner, screen

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import download_model                                       # noqa: E402
import failure_to_test                                      # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "log_regressions")
NO_REGRESSIONS = os.path.join(tempfile.gettempdir(), "no-such-regressions.json")


def case(**fields):
    base = {"id": "c", "question": "How much notice?", "problem_type": "t", "origin": "week11:c", "expected_sources": ["notice.md"], "expect_contains": [],
            "expect_all": [], "should_refuse": False, "needs_expected": False, "whole_words": True}
    return {**base, **fields}


def result(answer, sources=("notice.md",), grounded=True):
    return {"answer": answer, "grounded": grounded, "sources": list(sources), "retrieved": []}


class ForbidCheckTests(unittest.TestCase):
    def test_a_forbidden_phrase_in_the_answer_fails_the_case(self):
        checked = checks.check_case(case(forbid_contains=["45"], expect_contains=["30 days"]), result("The notice is 45 days. [source: notice.md]"))
        names = {c["name"]: c["passed"] for c in checked[0]}
        self.assertFalse(names["avoids_forbidden_phrase"])
        self.assertFalse(checked[1])

    def test_a_forbidden_phrase_matches_whole_words_and_ignores_markdown_and_case(self):
        forbid = case(forbid_contains=["45 days"])
        self.assertTrue(checks.check_case(forbid, result("It is 145 days."))[1])           # 145 is not 45
        self.assertFalse(checks.check_case(forbid, result("It is **45 DAYS**."))[1])
        self.assertTrue(checks.check_case(forbid, result("It is 30 days."))[1])

    def test_the_known_limit_a_denial_that_quotes_the_wrong_figure_fails_too(self):
        self.assertFalse(checks.check_case(case(forbid_contains=["45 days"]), result("It is not 45 days."))[1])

    def test_a_case_without_the_key_is_scored_exactly_as_before(self):
        plain = case(expect_contains=["30 days"])
        self.assertEqual([c["name"] for c in checks.check_case(plain, result("30 days"))[0]], ["refusal", "cites_expected_source", "has_expected_fact"])
        self.assertEqual([c["name"] for c in checks.check_case(case(forbid_contains=[]), result("30 days"))[0]], ["refusal", "cites_expected_source"])

    def test_the_check_applies_even_when_the_case_expects_a_refusal_or_has_no_expectations_yet(self):
        refuse = case(should_refuse=True, expected_sources=[], forbid_contains=["45"])
        self.assertFalse(checks.check_case(refuse, result("45", sources=(), grounded=False))[1])
        pending = case(needs_expected=True, expected_sources=[], forbid_contains=["45"])
        self.assertIn("avoids_forbidden_phrase", [c["name"] for c in checks.check_case(pending, result("fine"))[0]])


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.path = os.path.join(self.folder, cases.LOGGED_FAILURES_NAME)

    def write(self, *logged):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"cases": list(logged)}, handle)

    def test_no_file_means_no_cases(self):
        self.assertEqual(cases.load_logged_failures(self.path), [])

    def test_a_case_gets_its_origin_type_and_whole_word_matching_unless_it_says_otherwise(self):
        self.write({"id": "a", "question": "q?", "expected_sources": ["x.md"]}, {"id": "b", "question": "q?", "expected_sources": ["x.md"], "origin": "log-demo:b",
                                                                                 "problem_type": "mine", "whole_words": False})
        first, second = cases.load_logged_failures(self.path)
        self.assertEqual((first["origin"], first["problem_type"], first["whole_words"]), ("week11:a", "logged-failure", True))
        self.assertEqual((second["origin"], second["problem_type"], second["whole_words"]), ("log-demo:b", "mine", False))

    def test_a_case_that_expects_nothing_is_refused_so_it_cannot_become_a_silent_refusal_case(self):
        self.write({"id": "a", "question": "q?"})
        with self.assertRaises(ValueError) as caught:
            cases.load_logged_failures(self.path)
        self.assertIn("scored as a refusal", str(caught.exception))
        self.write({"id": "a", "question": "q?", "should_refuse": True})
        self.assertEqual(len(cases.load_logged_failures(self.path)), 1)

    def test_a_case_needs_an_id_and_a_question(self):
        for bad in ({"question": "q?", "expected_sources": ["x.md"]}, {"id": "a", "question": "  ", "expected_sources": ["x.md"]}):
            with self.subTest(bad=bad):
                self.write(bad)
                with self.assertRaises(ValueError):
                    cases.load_logged_failures(self.path)

    def test_the_cases_come_after_the_weeks_before_them_and_are_scored_by_the_rules(self):
        self.write({"id": "logged-a", "question": "A new question?", "expected_sources": ["notice.md"], "expect_contains": ["30 days"], "forbid_contains": ["45"]})
        everything = cases.all_cases(os.path.join(self.folder, "regressions.json"))
        self.assertEqual(everything[-1]["id"], "logged-a")
        self.assertEqual(len(everything), len(cases.all_cases(NO_REGRESSIONS)) + 1)
        added = everything[-1]
        self.assertEqual((added["should_refuse"], added["needs_expected"], added["origin"]), (False, False, "week11:logged-a"))
        self.assertFalse(checks.check_case(added, result("45 days"))[1])
        self.assertTrue(checks.check_case(added, result("30 days. [source: notice.md]"))[1])

    def test_pointing_the_regressions_elsewhere_switches_the_logged_failures_off_with_them(self):
        self.write({"id": "logged-a", "question": "A new question?", "expected_sources": ["notice.md"]})
        self.assertEqual(cases.logged_failures_path(os.path.join(self.folder, "regressions.json")), self.path)
        self.assertEqual(len(cases.all_cases(NO_REGRESSIONS)), 41)                 # the pinned eval set is unchanged
        with mock.patch("evals.cases.REGRESSIONS_PATH", os.path.join(self.folder, "regressions.json")):
            self.assertIn("logged-a", [c["id"] for c in cases.all_cases()])

    def test_a_duplicate_id_is_refused_like_any_other_duplicate(self):
        self.write({"id": "absent-bonus", "question": "q?", "expected_sources": ["x.md"]})
        with self.assertRaises(ValueError):
            cases.all_cases(os.path.join(self.folder, "regressions.json"))


DOCS = {"notice.md": "A permanent employee gives 30 calendar days of written notice. The wrong figure is 45 calendar days.", "x.md": "x right and also ninety days"}


class ScriptTests(unittest.TestCase):
    BAD_ANSWER = "I don't know based on the provided documents."
    GOOD_ANSWER = "A permanent employee gives 30 calendar days of written notice. [source: notice.md]"

    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.log = os.path.join(self.folder, "traces.jsonl")
        self.cases_path = os.path.join(self.folder, "logged_failures.json")
        self.fixtures = os.path.join(self.folder, "fixtures")
        self.enterContext(mock.patch.object(failure_to_test, "corpus_documents", return_value=DOCS))      # the documents of a corpus, so no test depends on the real one
        self.lines = [
            self.line("aaaa1111", "How much notice must I give?", self.BAD_ANSWER, False, [("handbook.md", 0.22, "Requests should normally be submitted through the portal."),
                                                                                         ("handbook.md", 0.22, "Requests should normally be submitted through the portal.")]),
            self.line("bbbb2222", "How much notice must I give?", self.GOOD_ANSWER, True, [("notice.md", 0.55, "A permanent employee gives 30 calendar days of written notice.")]),
            self.line("cccc3333", "How much notice must I give?", "The notice is 45 calendar days. [source: notice.md]", True,
                      [("notice.md", 0.55, "A permanent employee gives 30 calendar days of written notice.")]),
            self.line("dddd4444", "What is the bonus?", self.BAD_ANSWER, False, [("handbook.md", 0.2, "boilerplate")]),
            dict(self.line("eeee5555", "A drill question?", "30 calendar days", True, [("notice.md", 0.5, "t")]), synthetic=True),
        ]
        with open(self.log, "w", encoding="utf-8") as handle:
            for line in self.lines:
                handle.write(json.dumps(line) + "\n")

    @staticmethod
    def line(trace_id, question, answer, grounded, retrieved):
        return {"trace_id": trace_id, "ts": "2026-10-01T10:00:00", "question": question, "answer": answer, "grounded": grounded,
                "retrieved": [{"source": s, "score": score, "text": text} for s, score, text in retrieved], "config": {"llm_model_served": "model-x"}}

    def run_script(self, *argv):
        out = io.StringIO()
        base = ["--log", self.log, "--cases", self.cases_path, "--fixtures", self.fixtures]
        with contextlib.redirect_stdout(out):
            code = failure_to_test.main(base + list(argv))
        return code, out.getvalue()

    def fixture(self, case_id):
        with open(os.path.join(self.fixtures, f"{case_id}.json"), encoding="utf-8") as handle:
            return json.load(handle)

    GOOD = ["--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--corrected-from", "bbbb2222"]

    def test_a_logged_failure_becomes_a_case_and_a_fixture_that_prove_themselves_in_both_directions(self):
        code, text = self.run_script("aaaa1111", *self.GOOD, "--why", "it said it did not know", "--yes")
        self.assertEqual(code, 0, text)
        (written,) = cases.load_logged_failures(self.cases_path)
        self.assertEqual((written["id"], written["origin"], written["expected_sources"], written["expect_contains"]), ("log-aaaa1111", "week11:log-aaaa1111", ["notice.md"], ["30 calendar days"]))
        fixture = self.fixture("log-aaaa1111")
        normalized, error = failure_to_test.normalized_case(fixture["case"], [])
        self.assertIsNone(error)
        self.assertFalse(checks.check_case(normalized, fixture["failing_result"])[1])
        self.assertTrue(checks.check_case(normalized, fixture["corrected_result"])[1])
        self.assertEqual(fixture["failing_checks"], ["refusal", "cites_expected_source", "has_expected_fact"])
        self.assertEqual((fixture["logged"]["request_id"], fixture["logged"]["date"], fixture["logged"]["model_served"]), ("aaaa1111", "2026-10-01", "model-x"))
        self.assertEqual(fixture["logged"]["corrected"], {"from": "bbbb2222", "by_hand": False, "same_question": True})
        self.assertEqual((fixture["why"], fixture["worked_example"]), ("it said it did not know", False))
        self.assertEqual(fixture["drafted_by"], "converted with scripts/failure_to_test.py")
        self.assertFalse(os.path.exists(self.cases_path + ".tmp"))

    def test_nothing_is_written_without_yes(self):
        code, text = self.run_script("aaaa1111", *self.GOOD)
        self.assertEqual(code, 0)
        self.assertIn("Nothing written", text)
        self.assertFalse(os.path.exists(self.cases_path) or os.path.exists(self.fixtures))

    def test_it_says_whether_the_failure_was_retrieval_or_generation(self):
        self.assertIn("RETRIEVAL, the passage with the answer was not among those the model saw", self.run_script("aaaa1111", *self.GOOD)[1])
        code, text = self.run_script("cccc3333", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--forbid", "45 calendar days", "--corrected-from", "bbbb2222")
        self.assertIn("GENERATION, the passage was there and the answer was still wrong", text)
        self.assertEqual(code, 0)

    def test_a_wrong_figure_is_pinned_with_forbid_and_the_fixture_keeps_no_passage_text(self):
        self.assertEqual(self.run_script("cccc3333", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--forbid", "45 calendar days",
                                         "--corrected-from", "bbbb2222", "--yes")[0], 0)
        raw = json.dumps(self.fixture("log-cccc3333"))
        self.assertNotIn('"text"', raw)
        self.assertNotIn("written notice", raw.split('"failing_result"')[1].split('"corrected_result"')[0])      # no passage text in the failing part
        self.assertEqual(self.fixture("log-cccc3333")["kind"], "GENERATION")
        self.assertEqual(self.fixture("log-cccc3333")["failing_checks"], ["has_expected_fact", "avoids_forbidden_phrase"])    # no 30 in it, and a 45 that is forbidden
        for entry in self.fixture("log-cccc3333")["failing_result"]["retrieved"]:
            self.assertEqual(set(entry), {"source", "score"})

    def test_a_refusal_that_should_have_been_given_is_pinned_the_other_way_round(self):
        code, text = self.run_script("cccc3333", "--refuse", "--corrected-from", "dddd4444", "--yes")
        self.assertEqual(code, 0, text)
        fixture = self.fixture("log-cccc3333")
        self.assertIsNone(fixture["kind"])
        self.assertEqual(fixture["failing_checks"], ["refusal"])

    def test_a_case_the_logged_answer_passes_is_refused_because_it_would_guard_nothing(self):
        code, text = self.run_script("bbbb2222", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--corrected-answer", self.GOOD_ANSWER, "--yes")
        self.assertEqual(code, 1)
        self.assertIn("does not fail the answer the app really gave", text)
        self.assertFalse(os.path.exists(self.cases_path))

    def test_an_answer_offered_as_correct_that_fails_the_case_is_refused(self):
        code, text = self.run_script("aaaa1111", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--corrected-answer", "It is about a month.", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("does not pass the case", text)

    def test_the_right_answer_must_come_from_the_log_or_from_the_hand_but_not_both_or_neither(self):
        for extra in ([], ["--corrected-from", "bbbb2222", "--corrected-answer", self.GOOD_ANSWER]):
            code, text = self.run_script("aaaa1111", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", *extra)
            self.assertEqual(code, 1)
            self.assertIn("exactly one of --corrected-from", text)

    def test_it_insists_on_saying_what_a_correct_answer_cites_or_that_there_is_none(self):
        self.assertIn("--expect-source DOC", self.run_script("aaaa1111", "--corrected-from", "bbbb2222")[1])
        self.assertIn("no document or phrase to expect", self.run_script("aaaa1111", "--refuse", "--expect-source", "notice.md", "--corrected-from", "bbbb2222")[1])

    def test_an_unknown_or_ambiguous_request_or_a_failed_one_is_an_error(self):
        self.assertIn("no answered request starts with 'zzzz'", self.run_script("zzzz", *self.GOOD)[1])
        with open(self.log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.line("aaaa9999", "Another?", "x", True, [("x.md", 0.5, "t")])) + "\n")
        code, text = self.run_script("aaaa", *self.GOOD)
        self.assertEqual(code, 1)
        self.assertIn("2 requests start with 'aaaa'", text)
        code, text = self.run_script("aaaa1111", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--corrected-from", "zzzz")
        self.assertEqual(code, 1)
        self.assertIn("the correct answer", text)
        with open(os.path.join(self.folder, "errors.jsonl"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"request_id": "9999aaaa" + "0" * 8, "error_class": "RuntimeError", "spans": []}) + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = failure_to_test.main(["--log", os.path.join(self.folder, "errors.jsonl"), "9999aaaa", "--expect-source", "x.md", "--corrected-answer", "x"])
        self.assertEqual(code, 1)                                                      # a failed request has no answer to turn into a test
        self.assertIn("no answered request starts with", out.getvalue())

    def test_a_synthetic_request_is_refused_unless_allowed_and_then_it_is_marked_as_practice(self):
        code, text = self.run_script("eeee5555", "--expect-source", "x.md", "--expect-contains", "ninety", "--corrected-answer", "ninety days [source: x.md]")
        self.assertEqual(code, 1)
        self.assertIn("synthetic log", text)
        self.assertEqual(self.run_script("eeee5555", "--allow-synthetic", "--expect-source", "x.md", "--expect-contains", "ninety",
                                         "--corrected-answer", "ninety days [source: x.md]", "--yes")[0], 0)
        self.assertEqual(self.fixture("log-eeee5555")["case"]["origin"], "week11-drill:log-eeee5555")

    def test_a_case_that_only_forbids_one_wording_is_refused_because_it_would_guard_nothing_else(self):
        code, text = self.run_script("cccc3333", "--expect-source", "notice.md", "--forbid", "45 calendar days", "--corrected-from", "bbbb2222", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("say a phrase a correct answer states", text)
        self.assertFalse(os.path.exists(self.cases_path))

    def test_an_expected_source_that_is_not_a_document_of_the_corpus_is_refused(self):
        code, text = self.run_script("aaaa1111", "--expect-source", "ghost.md", "--expect-contains", "30 calendar days", "--corrected-from", "bbbb2222", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("is not a document of the corpus", text)

    def test_it_warns_when_no_expected_document_holds_an_expected_phrase(self):
        text = self.run_script("aaaa1111", "--expect-source", "notice.md", "--expect-contains", "ninety days", "--corrected-answer", "ninety days [source: notice.md]")[1]
        self.assertIn("none of the expected documents contains any expected phrase", text)
        self.assertNotIn("none of the expected documents", self.run_script("aaaa1111", *self.GOOD)[1])

    def test_the_case_id_names_a_file_so_it_cannot_climb_out_of_the_fixtures_folder(self):
        for bad in ("../outside", "a/b", ".hidden", "a b"):
            with self.subTest(id=bad):
                code, text = self.run_script("aaaa1111", *self.GOOD, "--id", bad, "--yes")
                self.assertEqual(code, 1)
                self.assertIn("--id names a file", text)
        self.assertFalse(os.path.exists(self.fixtures))

    def test_a_real_answer_with_a_dash_or_a_curly_quote_reaches_the_files_only_as_escapes(self):
        dashed = "The notice is " + chr(0x2014) + " as the policy says " + chr(0x2019) + "s " + "45 calendar days [source: notice.md]"
        with open(self.log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.line("dddd0000", "How much notice for a dash?", dashed, True, [("notice.md", 0.5, "t")]), ensure_ascii=False) + chr(10))
        code, text = self.run_script("dddd0000", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--forbid", "45 calendar days",
                                     "--corrected-from", "bbbb2222", "--yes")
        self.assertEqual(code, 0, text)
        for path in (self.cases_path, os.path.join(self.fixtures, "log-dddd0000.json")):
            with open(path, "rb") as handle:
                raw = handle.read().decode("ascii")                                       # raises if any byte is not ASCII
            self.assertNotIn(chr(0x2014), raw)
        self.assertEqual(self.fixture("log-dddd0000")["failing_result"]["answer"], dashed)      # and it reads back exactly

    def test_a_case_file_that_cannot_be_written_leaves_no_fixture_behind(self):
        calls = []
        real = failure_to_test.write_json

        def flaky(path, data):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(path, data)
        with mock.patch.object(failure_to_test, "write_json", flaky):
            with self.assertRaises(OSError):
                self.run_script("aaaa1111", *self.GOOD, "--yes")
        self.assertEqual(os.listdir(self.fixtures) if os.path.exists(self.fixtures) else [], [])
        self.assertFalse(os.path.exists(self.cases_path))

    def test_the_cases_file_keeps_any_other_keys_it_holds_and_can_have_a_bare_file_name(self):
        with open(self.cases_path, "w", encoding="utf-8") as handle:
            json.dump({"note": "kept", "cases": []}, handle)
        self.assertEqual(self.run_script("aaaa1111", *self.GOOD, "--yes")[0], 0)
        with open(self.cases_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["note"], "kept")
        original = os.getcwd()
        os.chdir(self.folder)
        self.addCleanup(os.chdir, original)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = failure_to_test.main(["--log", self.log, "--cases", "bare.json", "--fixtures", self.fixtures, "cccc3333", "--expect-source", "notice.md",
                                         "--expect-contains", "30 calendar days", "--forbid", "45 calendar days", "--corrected-from", "bbbb2222", "--yes"])
        self.assertEqual(code, 0, out.getvalue())
        self.assertTrue(os.path.exists(os.path.join(self.folder, "bare.json")))

    def test_the_fixture_says_where_the_correct_answer_came_from_and_whether_it_answered_the_same_question(self):
        self.run_script("cccc3333", "--refuse", "--corrected-from", "dddd4444", "--yes")
        self.assertEqual(self.fixture("log-cccc3333")["logged"]["corrected"], {"from": "dddd4444", "by_hand": False, "same_question": False})
        self.run_script("aaaa1111", "--expect-source", "notice.md", "--expect-contains", "ninety", "--corrected-answer", "ninety days [source: notice.md]", "--yes")
        self.assertEqual(self.fixture("log-aaaa1111")["logged"]["corrected"], {"from": None, "by_hand": True, "same_question": False})

    def test_it_tells_you_that_the_files_it_writes_hold_real_text(self):
        self.assertIn("copies the logged question and both answers into files you may commit", self.run_script("aaaa1111", *self.GOOD, "--yes")[1])

    def test_a_case_id_already_used_in_the_eval_set_is_refused_with_its_own_message(self):
        code, text = self.run_script("aaaa1111", *self.GOOD, "--id", "absent-bonus", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("is already used by a case of the eval set", text)

    def test_it_adds_to_what_is_there_and_never_wipes_or_reuses_an_id(self):
        self.assertEqual(self.run_script("aaaa1111", *self.GOOD, "--yes")[0], 0)
        self.assertEqual(self.run_script("cccc3333", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--forbid", "45 calendar days",
                                         "--corrected-from", "bbbb2222", "--yes")[0], 0)
        self.assertEqual([c["id"] for c in cases.load_logged_failures(self.cases_path)], ["log-aaaa1111", "log-cccc3333"])
        code, text = self.run_script("aaaa1111", *self.GOOD, "--yes")
        self.assertEqual(code, 1)
        self.assertIn("already exists", text)
        code, text = self.run_script("dddd4444", "--id", "absent-bonus", "--refuse", "--corrected-from", "dddd4444", "--yes")
        self.assertEqual(code, 1)                                                    # that id is in the eval set already (and the logged answer is right for it)
        self.assertEqual(len(cases.load_logged_failures(self.cases_path)), 2)

    def test_it_warns_about_a_bare_number_and_about_a_question_the_eval_set_already_asks(self):
        text = self.run_script("cccc3333", "--expect-source", "notice.md", "--expect-contains", "30 calendar days", "--forbid", "45", "--corrected-from", "bbbb2222")[1]
        self.assertIn("'45' is a bare number", text)
        known = cases.all_cases(NO_REGRESSIONS)[0]["question"]
        with open(self.log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.line("ffff6666", known, "wrong", True, [("x.md", 0.5, "t")])) + "\n")
        self.assertIn("already asks this exact question", self.run_script("ffff6666", "--expect-source", "x.md", "--expect-contains", "right", "--corrected-answer", "right [source: x.md]")[1])


class ClassifyTests(unittest.TestCase):
    """RETRIEVAL or GENERATION, decided the way the checks match a phrase (whole words, markdown and thousands separators ignored)."""

    def kind(self, passage, *phrases, source="doc.md", expected=("doc.md",), refuse=False, whole=True):
        case = {"expected_sources": list(expected), "expect_contains": list(phrases), "expect_all": [], "should_refuse": refuse, "whole_words": whole}
        return failure_to_test.classify(case, [{"source": source, "text": passage}])[0]

    def test_a_passage_of_the_right_document_that_does_not_hold_the_phrase_is_a_retrieval_failure(self):
        self.assertEqual(self.kind("Requests should normally be submitted through the portal.", "60 calendar days"), "RETRIEVAL")
        self.assertEqual(self.kind("The notice period is 60 calendar days for confirmed employees.", "60 calendar days"), "GENERATION")

    def test_a_longer_number_is_not_the_number_it_ends_with(self):
        self.assertEqual(self.kind("Notice is 17 calendar days here.", "7 calendar days"), "RETRIEVAL")
        self.assertEqual(self.kind("Notice is 7 calendar days here.", "7 calendar days"), "GENERATION")

    def test_a_thousands_separator_and_emphasis_do_not_hide_the_phrase(self):
        self.assertEqual(self.kind("The budget is INR 30,000 a year.", "30000"), "GENERATION")
        self.assertEqual(self.kind("The notice is **60 calendar days**.", "60 calendar days"), "GENERATION")

    def test_a_passage_of_another_document_does_not_count(self):
        self.assertEqual(self.kind("60 calendar days", "60 calendar days", source="other.md"), "RETRIEVAL")

    def test_a_refusal_case_has_no_passage_to_look_for_and_a_case_with_no_phrase_cannot_say(self):
        self.assertEqual(self.kind("anything", refuse=True, expected=()), None)
        self.assertEqual(self.kind("anything"), None)
        self.assertIn("no phrase", failure_to_test.classify({"expected_sources": ["d.md"], "expect_contains": [], "expect_all": [], "should_refuse": False}, [])[1])


class ForbidMatchingTests(unittest.TestCase):
    def test_emphasis_with_underscores_does_not_hide_a_forbidden_figure(self):
        forbid = case(forbid_contains=["45 calendar days"], expect_contains=["30 calendar days"])
        for answer in ("It is _45 calendar days_.", "It is __45 calendar days__.", "It is **45 calendar days**.", "It is 45 CALENDAR DAYS"):
            with self.subTest(answer=answer):
                self.assertFalse(checks.check_case(forbid, result(answer + " 30 calendar days [source: notice.md]"))[1])
        self.assertTrue(checks.check_case(forbid, result("It is 30 calendar days. [source: notice.md]"))[1])


class FixtureGuardTests(unittest.TestCase):
    """The permanent part: every fixture in the repository is replayed offline, in both directions, on every run of the suite."""

    def fixtures(self):
        paths = sorted(glob.glob(os.path.join(FIXTURES, "*.json")))
        self.assertTrue(paths, "tests/fixtures/log_regressions holds at least the worked example")
        for path in paths:
            with open(path, encoding="utf-8") as handle:
                yield path, json.load(handle)

    def test_the_logged_bad_answer_fails_its_case_and_the_correct_answer_passes_it(self):
        for path, fixture in self.fixtures():
            with self.subTest(fixture=os.path.basename(path)):
                normalized, error = failure_to_test.normalized_case(fixture["case"], [])
                self.assertIsNone(error)
                failing, passed, _ = checks.check_case(normalized, fixture["failing_result"])
                self.assertFalse(passed, "the logged answer passes its own case: the case guards nothing")
                self.assertEqual([c["name"] for c in failing if not c["passed"]], fixture["failing_checks"])
                self.assertTrue(checks.check_case(normalized, fixture["corrected_result"])[1])

    def test_small_changes_to_the_answers_do_not_change_the_verdict(self):
        for path, fixture in self.fixtures():
            with self.subTest(fixture=os.path.basename(path)):
                normalized, _ = failure_to_test.normalized_case(fixture["case"], [])
                for variant in (lambda a: a.upper(), lambda a: "  " + a.replace(" ", "  ") + "\n", lambda a: "**" + a + "**"):
                    bad = dict(fixture["failing_result"], answer=variant(fixture["failing_result"]["answer"]))
                    good = dict(fixture["corrected_result"], answer=variant(fixture["corrected_result"]["answer"]))
                    self.assertFalse(checks.check_case(normalized, bad)[1])
                    self.assertTrue(checks.check_case(normalized, good)[1])

    def test_a_fixture_keeps_only_the_fields_that_are_safe_to_commit(self):
        allowed = {"id", "kind", "case", "failing_result", "corrected_result", "failing_checks", "logged", "why", "drafted_by", "worked_example"}
        for path, fixture in self.fixtures():
            with self.subTest(fixture=os.path.basename(path)):
                self.assertEqual(set(fixture), allowed)
                self.assertEqual(set(fixture["logged"]), {"request_id", "date", "model_served", "corrected"})
                for side in ("failing_result", "corrected_result"):
                    self.assertEqual(set(fixture[side]), {"answer", "grounded", "sources", "retrieved"})
                    for chunk in fixture[side]["retrieved"]:
                        self.assertEqual(set(chunk), {"source", "score"})                      # names and scores, never the passage text
                self.assertIn(fixture["kind"], ("RETRIEVAL", "GENERATION", None))

    def test_every_case_in_the_logged_failures_file_has_a_fixture_that_replays_it_against_the_live_case(self):
        path = cases.logged_failures_path()
        if not os.path.exists(path):
            return                                              # no failure has been converted yet: nothing to pair with a fixture
        live_cases = {case["id"]: case for case in cases.all_cases()}
        for logged in cases.load_logged_failures(path):
            with self.subTest(case=logged["id"]):
                fixture_path = os.path.join(FIXTURES, f"{logged['id']}.json")
                self.assertTrue(os.path.exists(fixture_path), f"{logged['id']} has no fixture: it is a test nothing replays offline")
                with open(fixture_path, encoding="utf-8") as handle:
                    fixture = json.load(handle)
                self.assertEqual(fixture["case"]["question"], logged["question"])
                self.assertEqual(failure_to_test.replay_problems(live_cases[logged["id"]], fixture), [])

    def test_a_live_case_that_was_loosened_after_the_fixture_was_made_is_caught(self):
        fixture = {"case": {"expected_sources": ["notice.md"], "expect_contains": ["30 calendar days"], "expect_all": [], "forbid_contains": ["45 calendar days"], "should_refuse": False},
                   "failing_result": {"answer": "It is 45 calendar days. [source: notice.md]", "grounded": True, "sources": ["notice.md"], "retrieved": []},
                   "corrected_result": {"answer": "It is 30 calendar days. [source: notice.md]", "grounded": True, "sources": ["notice.md"], "retrieved": []}}
        live = dict(case(expected_sources=["notice.md"], expect_contains=["30 calendar days"], forbid_contains=["45 calendar days"]))
        self.assertEqual(failure_to_test.replay_problems(live, fixture), [])
        self.assertTrue(any("passes the logged wrong answer" in p for p in failure_to_test.replay_problems(dict(live, forbid_contains=[], expect_contains=["days"]), fixture)))
        self.assertTrue(any("fails the correct answer" in p for p in failure_to_test.replay_problems(dict(live, expect_contains=["ninety"]), fixture)))
        self.assertTrue(any("forbid_contains differs" in p for p in failure_to_test.replay_problems(dict(live, forbid_contains=["46 calendar days"]), fixture)))
        self.assertTrue(any("should_refuse differs" in p for p in failure_to_test.replay_problems(dict(live, should_refuse=True), fixture)))

    def test_the_worked_example_says_it_was_drafted_by_the_tool_and_is_for_you_to_review(self):
        with open(os.path.join(FIXTURES, "log-demo-notice-idk.json"), encoding="utf-8") as handle:
            example = json.load(handle)
        self.assertTrue(example["worked_example"])
        self.assertIn("to be reviewed by you", example["drafted_by"])
        self.assertEqual((example["logged"]["request_id"], example["kind"]), ("503834ae", "RETRIEVAL"))


@unittest.skipUnless(os.path.exists(os.path.join(download_model.model_dir(), "onnx", "model.onnx")), "the local embedding model is not downloaded (python scripts/download_model.py)")
class RetrievalGuardTests(unittest.TestCase):
    """For a failure of the RETRIEVAL kind: does retrieval, as the app is configured today, put the passage with the answer in front of the model?
    Real local embedding, exact search, the real corpus. It proves the failure is not back; the generation half is the live eval's job."""

    def test_the_passage_that_a_retrieval_failure_missed_is_retrieved_now(self):
        from app.rag import retriever
        for path in sorted(glob.glob(os.path.join(FIXTURES, "*.json"))):
            with open(path, encoding="utf-8") as handle:
                fixture = json.load(handle)
            if fixture["kind"] != "RETRIEVAL":
                continue
            normalized, _ = failure_to_test.normalized_case(fixture["case"], [])
            with self.subTest(fixture=os.path.basename(path)):
                # a temporary index folder, so the project's own data/chroma is never touched by a test
                with isolated_index(embed_provider="local", dense_search="exact", retrieval_mode="dense", top_k=4, boilerplate_min_repeats=0, dedupe_chunks=False):
                    with runner.isolated_index():
                        chunks = retriever.retrieve_for_mode(normalized["question"], settings.top_k, settings.retrieval_mode)
                self.assertIsNotNone(screen.first_useful_rank(chunks, normalized), "the passage with the answer is not among the top results again")


if __name__ == "__main__":
    unittest.main()
