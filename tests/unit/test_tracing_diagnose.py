"""Request logging (Weeks 3 and 4) and the failure classifier (Week 4)."""
import contextlib
import io
import json
import os
import unittest
from unittest import mock

import _testkit
from app.config import settings
from app.rag import diagnose
from app.tracing import log_trace, read_traces

CHUNK = {"text": "Employees receive 18 days.", "source": "leave.md", "score": 0.61, "retrievers": ["dense"],
         "dense_rank": 1, "keyword_rank": None, "keyword_score": None}


class TracingTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(_testkit.isolated_index())

    def test_a_trace_is_one_json_line_with_the_full_record(self):
        log_trace("How many days?", [CHUNK], "18 days", True, retrieval_mode="dense")
        with open(settings.traces_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["question"], "How many days?")
        self.assertEqual(record["retrieved"][0]["source"], "leave.md")
        self.assertEqual(record["retrieved"][0]["text"], "Employees receive 18 days.")
        self.assertEqual(record["config"]["retrieval_mode"], "dense")
        self.assertEqual(len(record["trace_id"]), 8)
        self.assertTrue(record["grounded"])

    def test_non_ascii_text_is_kept_readable(self):
        log_trace("café?", [], "résumé", True)
        with open(settings.traces_path, encoding="utf-8") as handle:
            self.assertIn("résumé", handle.read())

    def test_logging_never_raises_even_when_the_path_is_unusable(self):
        blocker = os.path.join(os.path.dirname(settings.traces_path), "blocker")
        os.makedirs(os.path.dirname(blocker), exist_ok=True)
        with open(blocker, "w") as handle:
            handle.write("a file where a folder is needed")
        with mock.patch.object(settings, "traces_path", os.path.join(blocker, "traces.jsonl")), \
                contextlib.redirect_stdout(io.StringIO()) as printed:
            log_trace("q", [], "a", True)                      # must not raise
        self.assertIn("trace log failed", printed.getvalue())  # it says so instead of failing

    def test_reading_skips_bad_lines_and_numbers_the_good_ones(self):
        os.makedirs(os.path.dirname(settings.traces_path), exist_ok=True)
        with open(settings.traces_path, "w", encoding="utf-8") as handle:
            handle.write('{"question": "one"}\n\nnot json\n[1, 2]\n{"question": "two"}\n{"question": "tw')
        traces = read_traces()
        self.assertEqual([t["question"] for t in traces], ["one", "two"])
        self.assertEqual([t["line_no"] for t in traces], [1, 5])           # real file line numbers

    def test_limit_returns_the_newest_and_zero_means_no_limit(self):
        for number in range(5):
            log_trace(f"q{number}", [], "a", True)
        self.assertEqual([t["question"] for t in read_traces(limit=2)], ["q3", "q4"])
        self.assertEqual(len(read_traces(limit=0)), 5)
        self.assertEqual(len(read_traces(limit=-1)), 5)

    def test_no_log_yet_reads_as_empty(self):
        self.assertEqual(read_traces(), [])


def classify(case, chunks, answer=("", [], True), **kwargs):
    with mock.patch("app.rag.diagnose.retriever.retrieve_for_mode", return_value=chunks), \
            mock.patch("app.rag.diagnose.generator.generate_answer", return_value=answer):
        return diagnose.classify(case, **kwargs)


class DiagnoseTests(unittest.TestCase):
    CASE = {"question": "How many days?", "expected_sources": ["leave.md"], "expect_contains": ["18 days"]}

    def test_pass_when_the_right_document_came_and_the_answer_has_the_fact(self):
        result = classify(self.CASE, [CHUNK], ("You get 18 days.", [], True))
        self.assertEqual((result["kind"], result["expected_rank"], result["matched"]), ("PASS", 1, "18 days"))

    def test_retrieval_failure_when_the_right_document_never_arrived(self):
        other = dict(CHUNK, source="other.md")
        result = classify(self.CASE, [other], ("I think 24 days.", [], True))
        self.assertEqual(result["kind"], "RETRIEVAL")
        self.assertIn("other.md", result["why"])
        self.assertIn("It answered", result["why"])

    def test_generation_failure_when_the_right_document_came_but_the_answer_is_wrong(self):
        result = classify(self.CASE, [CHUNK], ("You get 24 days.", [], True))
        self.assertEqual(result["kind"], "GENERATION")

    def test_generation_failure_when_it_refused_despite_having_the_facts(self):
        result = classify(self.CASE, [CHUNK], (diagnose.generator.IDK, [], False))
        self.assertEqual(result["kind"], "GENERATION")
        self.assertIn("refused", result["why"])

    def test_numbers_match_with_or_without_thousands_separators(self):
        case = {"question": "q", "expected_sources": ["b.md"], "expect_contains": ["$1,000"]}
        result = classify(case, [dict(CHUNK, source="b.md")], ("The budget is $1000.", [], True))
        self.assertEqual(result["kind"], "PASS")

    def test_empty_expected_sources_means_the_correct_behaviour_is_refusal(self):
        case = {"question": "bonus?", "expected_sources": [], "expect_contains": []}
        self.assertEqual(classify(case, [CHUNK], (diagnose.generator.IDK, [], False))["kind"], "PASS")
        self.assertEqual(classify(case, [CHUNK], ("It is 10%.", [], True))["kind"], "GENERATION")

    def test_without_the_model_retrieval_success_is_not_called_a_pass(self):
        result = classify(self.CASE, [CHUNK], call_model=False)
        self.assertEqual(result["kind"], "RETRIEVAL OK")
        self.assertIn("not graded", result["why"])
        self.assertIsNone(result["answer"])

    def test_without_the_model_a_refusal_case_cannot_be_graded(self):
        case = {"question": "bonus?", "expected_sources": [], "expect_contains": []}
        self.assertIsNone(classify(case, [CHUNK], call_model=False)["kind"])

    def test_k_defaults_to_top_k_and_can_be_overridden(self):
        self.assertEqual(classify(self.CASE, [CHUNK], ("18 days", [], True))["k"], settings.top_k)
        self.assertEqual(classify(self.CASE, [CHUNK], ("18 days", [], True), k=2)["k"], 2)

    def test_snippet_flattens_and_truncates(self):
        self.assertEqual(diagnose.snippet("a\n\n b   c"), "a b c")
        self.assertEqual(len(diagnose.snippet("x" * 500, limit=50)), 50)


if __name__ == "__main__":
    unittest.main()
