"""Settings validation, the ingest/answer pipeline, and the HTTP layer's error mapping."""
import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

import httpx
import openai
from fastapi.testclient import TestClient
from pydantic import ValidationError

import _testkit
from _testkit import fake_response, isolated_index, patched_embeddings
from app import llm
from app.config import Settings, settings
from app.rag import pipeline, store
from app.tracing import log_trace, read_traces


def make(**values):
    return Settings(_env_file=None, **values)         # ignore the real .env so tests are repeatable


class SettingsTests(unittest.TestCase):
    def test_defaults_are_valid_and_dense_search_is_exact(self):
        defaults = make()
        self.assertEqual((defaults.dense_search, defaults.chunk_size, defaults.chunk_overlap), ("exact", 800, 120))

    def test_names_are_normalised(self):
        self.assertEqual(make(embed_provider=" LOCAL ").embed_provider, "local")
        self.assertEqual(make(retrieval_mode="Dense").retrieval_mode, "dense")
        self.assertEqual(make(dense_search=" ANN ").dense_search, "ann")

    def test_typos_fail_at_startup(self):
        for bad in ({"embed_provider": "locall"}, {"retrieval_mode": "semantic"}, {"dense_search": "fast"}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                make(**bad)

    def test_overlap_must_be_smaller_than_the_chunk_size(self):
        with self.assertRaises(ValidationError) as caught:
            make(chunk_size=100, chunk_overlap=100)
        self.assertIn("chunk_overlap", str(caught.exception))
        make(chunk_size=100, chunk_overlap=99)           # one less is fine

    def test_counts_and_limits_reject_nonsense(self):
        for bad in ({"top_k": 0}, {"hybrid_candidates": 0}, {"eval_k": 0}, {"rrf_k": -1}, {"bm25_b": 1.5},
                    {"bm25_k1": -0.1}, {"llm_rpm": -1}, {"llm_max_retries": -1}, {"chunk_size": 0},
                    {"chunk_overlap": -1}, {"llm_timeout_seconds": 0}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                make(**bad)

    def test_zero_means_off_for_the_rate_limits(self):
        self.assertEqual((make(llm_rpm=0).llm_rpm, make(embed_rpm=0).embed_rpm), (0, 0))


DOCS = {"leave.md": "# Leave\nEmployees receive 18 days of annual leave.\n",
        "notice.md": "# Notice\nA permanent employee gives 30 days of written notice.\n"}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        corpus = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        for name, text in DOCS.items():
            with open(os.path.join(corpus, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        self.corpus = corpus
        self.enterContext(isolated_index(corpus_dir=corpus, dense_search="exact", retrieval_mode="dense", top_k=2))
        self.enterContext(patched_embeddings())

    def test_ingest_reports_documents_chunks_and_per_file_counts(self):
        result = pipeline.ingest()
        self.assertEqual((result["documents"], result["chunks"]), (2, 2))
        self.assertEqual(result["per_source"], {"leave.md": 1, "notice.md": 1})
        self.assertEqual(store.count_chunks(), 2)

    def test_ingesting_twice_does_not_duplicate_chunks(self):
        pipeline.ingest()
        pipeline.ingest()
        self.assertEqual(store.count_chunks(), 2)

    def test_a_failed_embedding_leaves_the_old_index_intact(self):
        pipeline.ingest()
        with mock.patch("app.rag.embedder.embed_texts", side_effect=RuntimeError("rate limited")):
            with self.assertRaises(RuntimeError):
                pipeline.ingest()
        self.assertEqual(store.count_chunks(), 2)           # still searchable, not silently emptied

    def test_an_empty_corpus_is_a_clear_error(self):
        with isolated_index(corpus_dir=self.corpus + "-missing"), patched_embeddings():
            with self.assertRaises(RuntimeError) as caught:
                pipeline.ingest()
        self.assertIn("No readable documents", str(caught.exception))

    def test_answer_returns_the_documented_shape_and_logs_a_trace(self):
        pipeline.ingest()
        with mock.patch("app.llm.chat", return_value=fake_response("18 days. [source: leave.md]")):
            result = pipeline.answer("How many days of annual leave?")
        self.assertEqual(set(result), {"answer", "sources", "grounded", "retrieval_mode"})
        self.assertTrue(result["grounded"])
        self.assertEqual([s["document"] for s in result["sources"]], ["leave.md"])
        traces = read_traces()
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["config"]["dense_search"], "exact")
        self.assertEqual(traces[0]["config"]["embed_provider"], settings.embed_provider)

    def test_a_refusal_is_ungrounded_and_still_traced(self):
        pipeline.ingest()
        with mock.patch("app.llm.chat", return_value=fake_response(pipeline.generator.IDK)):
            result = pipeline.answer("What is the bonus?")
        self.assertEqual((result["grounded"], result["sources"]), (False, []))
        self.assertEqual(len(read_traces()), 1)

    def test_an_empty_question_makes_no_model_call(self):
        pipeline.ingest()
        with mock.patch("app.llm.chat") as chat:
            result = pipeline.answer("   ")
        chat.assert_not_called()
        self.assertEqual(result["answer"], "Please ask a question.")

    def test_asking_before_ingesting_is_an_error_not_a_fake_refusal(self):
        with mock.patch("app.llm.chat") as chat:
            with self.assertRaises(RuntimeError) as caught:
                pipeline.answer("How many days of annual leave?")
        self.assertIn("scripts/ingest.py", str(caught.exception))
        chat.assert_not_called()
        self.assertEqual(read_traces(), [])

    def test_mode_can_be_forced_per_question_and_really_reaches_retrieval(self):
        pipeline.ingest()
        with mock.patch("app.llm.chat", return_value=fake_response("18 days [source: leave.md]")), \
                mock.patch.object(pipeline.retriever, "retrieve_for_mode",
                                  wraps=pipeline.retriever.retrieve_for_mode) as spy:
            result = pipeline.answer("annual leave days", mode="hybrid")
        self.assertEqual(result["retrieval_mode"], "hybrid")
        self.assertEqual(spy.call_args.args[2], "hybrid")                 # not merely echoed back

    def test_the_trace_names_the_model_that_answered_and_none_when_no_call_was_made(self):
        pipeline.ingest()

        def chat(messages, **kwargs):
            llm._last_model["name"] = "served-model"
            return fake_response("18 days [source: leave.md]")
        with mock.patch("app.llm.chat", side_effect=chat):
            pipeline.answer("annual leave days")
        self.assertEqual(read_traces()[-1]["config"]["llm_model_served"], "served-model")
        llm._last_model["name"] = "stale-from-an-earlier-question"
        with mock.patch.object(settings, "min_relevance", 0.99), mock.patch("app.llm.chat") as chat_again:
            pipeline.answer("completely unrelated words here")
        chat_again.assert_not_called()                                     # refused by the relevance floor
        self.assertIsNone(read_traces()[-1]["config"]["llm_model_served"])   # and the stale name is NOT reused


def status_error(error_class, status):
    request = httpx.Request("POST", "http://test.invalid")
    return error_class("provider said no", response=httpx.Response(status, request=request), body=None)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_index())
        from app.main import app
        self.client = TestClient(app)

    def ask(self, **body):
        return self.client.post("/ask", json={"question": "How many days?", **body})

    def test_health(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")

    def test_a_good_answer_has_the_documented_fields(self):
        payload = {"answer": "18 days", "sources": [{"document": "leave.md", "score": 0.6}],
                   "grounded": True, "retrieval_mode": "dense"}
        with mock.patch("app.main.run_answer", return_value=payload):
            response = self.ask()
        self.assertEqual((response.status_code, response.json()), (200, payload))

    def test_an_unknown_mode_is_rejected_with_422(self):
        self.assertEqual(self.ask(mode="semantic").status_code, 422)

    def test_failures_become_clear_http_errors_not_bare_500s(self):
        cases = [
            (RuntimeError("No documents are indexed yet."), 400),
            (llm.QuotaExhausted("daily quota used up"), 429),
            (status_error(openai.RateLimitError, 429), 429),
            (status_error(openai.InternalServerError, 503), 502),
            (status_error(openai.AuthenticationError, 401), 502),
            (openai.APIConnectionError(request=httpx.Request("POST", "http://test.invalid")), 502),
        ]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__), mock.patch("app.main.run_answer", side_effect=error):
                response = self.ask()
                self.assertEqual(response.status_code, expected)
                self.assertTrue(response.json()["detail"])

    def test_ingest_endpoint_reports_a_problem_as_400(self):
        with mock.patch("app.main.run_ingest", side_effect=RuntimeError("No readable documents")):
            response = self.client.post("/ingest")
        self.assertEqual((response.status_code, response.json()["detail"]), (400, "No readable documents"))

    def test_inspect_shows_traces_and_escapes_html_in_them(self):
        log_trace("<script>alert(1)</script> question?", [{"source": "a.md", "score": 0.5, "text": "t"}],
                  "I don't know based on the provided documents.", False)
        page = self.client.get("/inspect").text
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("refused", page)

    def test_inspect_with_no_traces_says_so(self):
        self.assertIn("No traces logged yet", self.client.get("/inspect").text)

    def test_inspect_can_filter_to_refusals(self):
        log_trace("answered?", [], "yes", True)
        log_trace("refused?", [], "I don't know", False)
        page = self.client.get("/inspect?ungrounded=true").text
        self.assertIn("refused?", page)
        self.assertNotIn("answered?", page)


if __name__ == "__main__":
    unittest.main()
