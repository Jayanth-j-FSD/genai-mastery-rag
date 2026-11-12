"""The labelled question sets must stay true to the documents they point at.

An eval set is only worth anything if its "right answers" really are in the
documents. These tests read the real corpus and fail when a case, a question list or the chunk
comparison drifts away from it. That is exactly how the Week 4 set went stale after the
documents changed, without anyone noticing.
"""
import os
import re
import unittest

import _testkit
from app.config import settings
from app.rag import diagnose, loader

sys_path_scripts = os.path.join(_testkit.ROOT, "scripts")
import sys                                       # noqa: E402
sys.path.insert(0, sys_path_scripts)
import compare_chunks                            # noqa: E402

from tests import eval_set                       # noqa: E402

CORPUS = {doc["source"]: doc["text"] for doc in loader.load_documents(settings.corpus_dir)}
NORMALISED = {name: diagnose._normalize(text.replace("*", "")) for name, text in CORPUS.items()}


def read(relative):
    with open(os.path.join(_testkit.ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class EvalSetTests(unittest.TestCase):
    def test_every_expected_source_is_a_real_corpus_file(self):
        for case in eval_set.CASES:
            for source in case["expected_sources"]:
                with self.subTest(case=case["id"], source=source):
                    self.assertIn(source, CORPUS)

    def test_every_in_corpus_answer_phrase_really_appears_in_an_expected_document(self):
        for case in eval_set.in_corpus_cases():
            with self.subTest(case=case["id"]):
                self.assertTrue(case["expect_contains"], "an in-corpus case needs an accepted phrase")
                found = [phrase for phrase in case["expect_contains"]
                         if any(diagnose._normalize(phrase) in NORMALISED[source] for source in case["expected_sources"])]
                self.assertTrue(found, f"none of {case['expect_contains']} appears in {case['expected_sources']}")

    def test_cases_with_bare_number_answers_have_evidence_that_is_still_in_the_documents(self):
        # "12" or "60" can match almost any document, so the phrase check above proves little for those
        # cases. Their `evidence` sentences state the fact itself and must still be in an expected source.
        for case in eval_set.in_corpus_cases():
            phrases = case["expect_contains"]
            if phrases and all(any(ch.isdigit() for ch in p) and len(p) <= 6 for p in phrases):
                with self.subTest(case=case["id"]):
                    self.assertTrue(case.get("evidence"), "a bare-number case needs evidence sentences")
            for sentence in case.get("evidence", []):
                with self.subTest(case=case["id"], evidence=sentence):
                    self.assertTrue(any(diagnose._normalize(sentence) in NORMALISED[s] for s in case["expected_sources"]))

    def test_refusal_cases_really_are_absent_from_every_document(self):
        refusals = eval_set.refusal_cases()
        self.assertGreaterEqual(len(refusals), 4)
        for case in refusals:
            self.assertTrue(case.get("absent_terms"), f"{case['id']} must list absent_terms")
            for term in case["absent_terms"]:
                with self.subTest(case=case["id"], term=term):
                    hits = [name for name, text in NORMALISED.items() if term.lower() in text]
                    self.assertEqual(hits, [], f"{term!r} appears in {hits}, so this is no longer an absent topic")

    def test_the_case_mix_matches_the_prediction_written_before_the_first_run(self):
        # docs/week4/findings.md section 1 predicts about "the six exact-string questions" and
        # "the four paraphrase questions". The replacements kept those counts.
        favours = [case["favours"] for case in eval_set.in_corpus_cases()]
        self.assertEqual(favours.count("keyword"), 6)
        self.assertEqual(favours.count("dense"), 4)

    def test_cases_have_the_fields_the_scripts_read(self):
        for case in eval_set.CASES:
            with self.subTest(case=case["id"]):
                for key in ("id", "question", "expected_sources", "expect_contains", "favours", "why_hard"):
                    self.assertIn(key, case)
                self.assertIn(case["favours"], ("keyword", "dense", "either"))
                self.assertTrue(case["question"].strip())

    def test_the_original_ids_that_were_kept_are_still_there(self):
        ids = {case["id"] for case in eval_set.CASES}
        kept = {"code-err4032", "exact-security-email", "exact-settings-path", "acronym-mfa", "paraphrase-usb",
                "paraphrase-hacked", "paraphrase-receipt-window", "paraphrase-retirement",
                "ambiguous-home-office", "ambiguous-leave-days", "absent-bonus"}
        self.assertEqual(kept - ids, set())


class QuestionListTests(unittest.TestCase):
    def test_the_hand_checklist_only_names_files_that_exist(self):
        named = set(re.findall(r"[\w.-]+\.md\b", read("tests/questions.md")))
        unknown = {name for name in named if name not in CORPUS and name not in {"questions.md"}}
        self.assertEqual(unknown, set())

    def test_compare_chunks_uses_exactly_the_checklist_questions_in_order(self):
        rows = re.findall(r"^\| (\d+) \| (.+?) \| yes \| (\S+\.md)", read("tests/questions.md"), re.MULTILINE)
        self.assertEqual([(question, source) for _, question, source in rows], compare_chunks.CASES)

    def test_compare_chunks_expected_sources_exist(self):
        for _, source in compare_chunks.CASES:
            self.assertIn(source, CORPUS)

    def test_the_trace_question_bank_is_a_real_population_and_has_no_duplicates(self):
        questions = [line.strip() for line in read("tests/trace_questions.txt").splitlines()
                     if line.strip() and not line.startswith("#")]
        self.assertGreaterEqual(len(questions), 60)
        self.assertEqual(len(questions), len(set(questions)))

    def test_the_trace_question_bank_asks_about_every_track_document(self):
        text = read("tests/trace_questions.txt").lower()
        for topic in ("parental", "notice", "remote", "azure", "probation", "casual leave"):
            self.assertIn(topic, text)


class NexoraAnswerKeyTests(unittest.TestCase):
    def test_the_answer_key_is_not_inside_the_corpus(self):
        nexora = CORPUS["Nexora_Tech_Azure_Cloud_Data_Access_Policy.md"]
        for leak in ("RAG Evaluation", "Expected behavior", "Hallucination Test"):
            self.assertNotIn(leak, nexora)

    def test_the_questions_and_key_were_kept_outside_it(self):
        key = read("tests/nexora_eval_questions.md")
        self.assertIn("Hallucination Test", key)
        self.assertIn("Azure Key Vault", key)
        self.assertEqual(len(re.findall(r"^\| \d+ \|", key, re.MULTILINE)), 14)


if __name__ == "__main__":
    unittest.main()
