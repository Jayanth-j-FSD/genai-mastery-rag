"""Week 11: what one real request writes to the logs, through pipeline.answer() and the API (fake embedder, stub model)."""
import json
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx
import openai
from fastapi.testclient import TestClient

from _testkit import fake_response, isolated_index, patched_embeddings
from app import llm, observability, pricing, tracing
from app.config import settings
from app.rag import generator, pipeline, store
from test_llm import FakeClient

DOCS = {"leave.md": "# Leave\nEmployees receive 18 days of annual leave.\n",
        "notice.md": "# Notice\nA permanent employee gives 30 days of written notice.\n"}
QUESTION = "How many days of annual leave?"
CITED = "18 days. [source: leave.md]"
OLD_KEYS = {"trace_id", "ts", "question", "retrieved", "answer", "grounded", "config"}


def status_error(error_class, status):
    request = httpx.Request("POST", "http://test.invalid")
    return error_class("provider said no", response=httpx.Response(status, request=request), body=None)


def lines_of(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle.read().splitlines() if line.strip()]


class IndexedCase(unittest.TestCase):
    """A two-document index in a throwaway folder, the fake embedder, and the log files that go with them."""

    def setUp(self):
        corpus = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.write_docs(corpus, DOCS)
        self.corpus = corpus
        self.enterContext(isolated_index(corpus_dir=corpus, dense_search="exact", retrieval_mode="dense", top_k=2))
        self.enterContext(patched_embeddings())
        self.enterContext(mock.patch.object(settings, "llm_rpm", 0))
        self.enterContext(mock.patch.object(settings, "min_relevance", 0.0))
        self.enterContext(mock.patch.object(settings, "price_input_per_million", 0.0))     # unpriced, whatever the real .env says
        self.enterContext(mock.patch.object(settings, "price_output_per_million", 0.0))
        pipeline.ingest()
        observability.forget_last_request()

    @staticmethod
    def write_docs(folder, docs):
        for name, text in docs.items():
            with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
                handle.write(text)

    def traces(self):
        return lines_of(settings.traces_path)

    def errors(self):
        return lines_of(tracing.errors_path())

    def answer_with(self, text=CITED, question=QUESTION, **kwargs):
        with mock.patch("app.llm.chat", return_value=fake_response(text)):
            return pipeline.answer(question, **kwargs)


class TraceContentTests(IndexedCase):
    def test_a_trace_line_names_the_request_the_steps_in_order_and_what_the_answer_cited(self):
        self.answer_with()
        (line,) = self.traces()
        self.assertTrue(OLD_KEYS <= set(line))                      # everything the older weeks read is still there
        self.assertRegex(line["request_id"], r"^[0-9a-f]{16}$")
        self.assertEqual(line["trace_id"], line["request_id"][:8])
        self.assertEqual([span["name"] for span in line["spans"]], ["embed_query", "search", "generate"])
        self.assertEqual([span["kind"] for span in line["spans"]], ["embed", "retrieve", "model"])
        self.assertEqual((line["status"], line["channel"], line["sources"]), ("ok", "unknown", ["leave.md"]))
        self.assertRegex(line["index_id"], r"^2:[0-9a-f]{12}$")
        self.assertEqual(set(line["chars"]), {"system", "context", "question", "stripped"})
        self.assertEqual(line["chars"]["question"], len(QUESTION))
        self.assertEqual(len(line["prompt_sha"]), 12)
        self.assertLessEqual(sum(span["duration_ms"] for span in line["spans"]), line["total_ms"])

    def test_the_local_embedding_span_says_it_cost_nothing_and_an_api_one_does_not_claim_to(self):
        with mock.patch.object(settings, "embed_provider", "local"):
            self.answer_with()
        with mock.patch.object(settings, "embed_provider", "openai"):
            self.answer_with()
        local, api = (line["spans"][0] for line in self.traces())
        self.assertEqual((local["provider"], local["cost_usd"], local["cost_basis"]), ("local", 0.0, "local"))
        self.assertEqual((api["provider"], api["cost_usd"], api["cost_basis"]), ("openai", None, "unknown"))

    def test_hybrid_search_shows_both_searches_as_their_own_steps(self):
        self.answer_with(mode="hybrid")
        self.assertEqual([span["name"] for span in self.traces()[0]["spans"]], ["embed_query", "search", "keyword_search", "generate"])

    def test_the_tokens_of_the_model_call_reach_the_line_and_add_up(self):
        client = FakeClient([fake_response(CITED, prompt_tokens=123, completion_tokens=17)])
        with mock.patch.object(llm, "_get_client", return_value=client):
            pipeline.answer(QUESTION)
        (line,) = self.traces()
        generate = line["spans"][-1]
        self.assertEqual((generate["prompt_tokens"], generate["completion_tokens"], generate["tokens_known"]), (123, 17, True))
        self.assertEqual(line["usage"]["prompt_tokens"], 123)
        self.assertEqual(line["usage"]["model_calls"], 1)
        self.assertIsNone(generate["cost_usd"])                     # no price was stated, so no dollars are claimed

    def test_the_channel_and_the_caller_are_on_the_line(self):
        with observability.channel("batch", caller="nightly"):
            self.answer_with()
        line = self.traces()[0]
        self.assertEqual((line["channel"], line["caller"]), ("batch", "nightly"))

    def test_the_result_is_still_the_four_documented_keys(self):
        result = self.answer_with()
        self.assertEqual(set(result), {"answer", "sources", "grounded", "retrieval_mode"})
        self.assertEqual(len(self.traces()[0]["trace_id"]), 8)


class RefusalCauseTests(IndexedCase):
    def cause(self):
        (line,) = self.traces()
        self.assertEqual(line["status"], "refused")
        return line["refusal_cause"]

    def test_nothing_retrieved(self):
        with mock.patch.object(pipeline.retriever, "retrieve_for_mode", return_value=[]), mock.patch("app.llm.chat") as chat:
            result = pipeline.answer(QUESTION)
        chat.assert_not_called()
        self.assertFalse(result["grounded"])
        self.assertEqual(self.cause(), "no_chunks")

    def test_the_best_chunk_is_below_the_relevance_floor(self):
        with mock.patch.object(settings, "min_relevance", 0.999), mock.patch("app.llm.chat") as chat:
            pipeline.answer("completely unrelated words here")
        chat.assert_not_called()
        self.assertEqual(self.cause(), "below_min_relevance")

    def test_the_model_replied_with_nothing(self):
        self.answer_with(text="")
        self.assertEqual(self.cause(), "empty_reply")

    def test_the_model_itself_said_it_does_not_know(self):
        self.answer_with(text=generator.IDK)
        self.assertEqual(self.cause(), "model_idk")

    def test_a_refusal_with_no_known_reason_says_unknown_instead_of_guessing(self):
        with mock.patch.object(generator, "generate_answer", return_value=(generator.IDK, [], False)):
            pipeline.answer(QUESTION)
        self.assertEqual(self.cause(), "unknown")

    def test_an_answered_question_has_no_refusal_cause(self):
        self.answer_with()
        self.assertNotIn("refusal_cause", self.traces()[0])


class IndexIdTests(IndexedCase):
    def index_id(self):
        self.answer_with()
        return self.traces()[-1]["index_id"]

    def test_the_same_index_has_the_same_id_every_time(self):
        self.assertEqual(self.index_id(), self.index_id())

    def test_a_changed_number_in_a_policy_changes_the_id_even_though_the_length_does_not(self):
        before = self.index_id()
        self.write_docs(self.corpus, {"leave.md": "# Leave\nEmployees receive 24 days of annual leave.\n"})
        pipeline.ingest()                                            # ingest forgets the cached id
        self.assertNotEqual(self.index_id(), before)


class FailureTests(IndexedCase):
    def test_a_failed_request_goes_to_the_error_log_and_the_error_goes_on_unchanged(self):
        boom = RuntimeError("secret-token-123 leaked by the provider")
        with mock.patch("app.llm.chat", side_effect=boom):
            with self.assertRaises(RuntimeError) as caught:
                pipeline.answer(QUESTION)
        self.assertIs(caught.exception, boom)
        self.assertEqual(self.traces(), [])                          # no answer, so no trace
        (record,) = self.errors()
        self.assertEqual((record["error_class"], record["http_status"], record["channel"]), ("RuntimeError", 400, "unknown"))
        self.assertEqual(record["request_id"], observability.last_request_id())
        by_name = {span["name"]: span for span in record["spans"]}
        self.assertEqual(by_name["generate"]["status"], "error")     # the step that failed is the one marked
        self.assertEqual(by_name["search"]["status"], "ok")
        with open(tracing.errors_path(), encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn("secret-token", raw)
        self.assertNotIn("annual leave", raw)

    def test_asking_before_anything_is_indexed_is_logged_as_a_failed_request_with_no_steps(self):
        store.reset_collection()
        with mock.patch("app.llm.chat") as chat:
            with self.assertRaises(RuntimeError):
                pipeline.answer(QUESTION)
        chat.assert_not_called()
        (record,) = self.errors()
        self.assertEqual((record["spans"], record["http_status"]), ([], 400))
        self.assertEqual(self.traces(), [])

    def test_a_provider_failure_is_logged_with_the_status_the_api_would_have_sent(self):
        for error, status in ((llm.QuotaExhausted("daily"), 429), (status_error(openai.RateLimitError, 429), 429),
                              (status_error(openai.InternalServerError, 503), 502)):
            with self.subTest(error=type(error).__name__), mock.patch("app.llm.chat", side_effect=error):
                with self.assertRaises(type(error)):
                    pipeline.answer(QUESTION)
                self.assertEqual(self.errors()[-1]["http_status"], status)

    def test_an_empty_question_makes_no_request_at_all(self):
        with mock.patch("app.llm.chat") as chat:
            result = pipeline.answer("   ")
        chat.assert_not_called()
        self.assertEqual(result["answer"], "Please ask a question.")
        self.assertEqual((self.traces(), self.errors(), observability.last_request_id()), ([], [], None))


class LoggingNeverBreaksAnsweringTests(IndexedCase):
    """Each of these breaks a different part of the logging and checks that the user still gets the answer."""

    def assert_still_answers(self):
        result = self.answer_with()
        self.assertEqual(set(result), {"answer", "sources", "grounded", "retrieval_mode"})
        self.assertTrue(result["grounded"])
        return result

    def test_the_request_log_cannot_be_built(self):
        with mock.patch.object(observability, "RequestLog", side_effect=RuntimeError("log bug")):
            self.assert_still_answers()
        (line,) = self.traces()
        self.assertEqual(set(line), OLD_KEYS)                        # the trace is still written, as the older weeks wrote it

    def test_a_step_cannot_be_recorded(self):
        with mock.patch.object(observability.RequestLog, "open_span", side_effect=RuntimeError("log bug")):
            self.assert_still_answers()
        self.assertEqual(len(self.traces()), 1)

    def test_the_price_lookup_breaks(self):
        client = FakeClient([fake_response(CITED, prompt_tokens=5, completion_tokens=2)])
        with mock.patch.object(llm, "_get_client", return_value=client), \
                mock.patch.object(pricing, "cost_of", side_effect=RuntimeError("pricing bug")):
            result = pipeline.answer(QUESTION)
        self.assertTrue(result["grounded"])
        self.assertEqual(len(self.traces()), 1)

    def test_the_extra_keys_cannot_be_built(self):
        with mock.patch.object(observability, "record_extras", side_effect=RuntimeError("log bug")):
            self.assert_still_answers()
        self.assertEqual(set(self.traces()[0]), OLD_KEYS)

    def test_the_index_id_cannot_be_computed(self):
        with mock.patch.object(pipeline, "_index_id", side_effect=RuntimeError("log bug")):
            self.assert_still_answers()
        self.assertIsNone(self.traces()[0]["index_id"])

    def test_the_outcome_note_breaks(self):
        with mock.patch.object(pipeline, "_note_outcome", side_effect=RuntimeError("log bug")):
            self.assert_still_answers()

    def test_the_log_file_cannot_be_written(self):
        with mock.patch.object(tracing, "append_line", side_effect=OSError("disk full")):
            self.assert_still_answers()
        self.assertEqual(self.traces(), [])

    def test_the_error_log_cannot_be_written_and_the_real_error_still_comes_out(self):
        boom = RuntimeError("the real failure")
        with mock.patch("app.llm.chat", side_effect=boom), mock.patch.object(tracing, "append_line", side_effect=OSError("disk full")):
            with self.assertRaises(RuntimeError) as caught:
                pipeline.answer(QUESTION)
        self.assertIs(caught.exception, boom)                        # not the OSError from the log


class ConcurrencyTests(IndexedCase):
    def test_two_requests_at_the_same_moment_keep_their_own_channel_id_and_steps(self):
        barrier = threading.Barrier(2)

        def chat(messages, **kwargs):
            barrier.wait(timeout=10)                                 # both requests are inside their model call together
            return fake_response(CITED)

        errors = []

        def work(name):
            try:
                with observability.channel(name):
                    pipeline.answer(f"{QUESTION} ({name})")
            except Exception as exc:
                errors.append(exc)

        with mock.patch("app.llm.chat", side_effect=chat):
            threads = [threading.Thread(target=work, args=(name,)) for name in ("alpha", "beta")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        self.assertEqual(errors, [])
        by_channel = {line["channel"]: line for line in self.traces()}
        self.assertEqual(set(by_channel), {"alpha", "beta"})
        self.assertNotEqual(by_channel["alpha"]["request_id"], by_channel["beta"]["request_id"])
        for name, line in by_channel.items():
            self.assertIn(f"({name})", line["question"])
            self.assertEqual([span["name"] for span in line["spans"]], ["embed_query", "search", "generate"])


class ApiRequestIdTests(IndexedCase):
    def setUp(self):
        super().setUp()
        from app.main import app
        self.client = TestClient(app)

    def ask(self, question=QUESTION, headers=None, **body):
        return self.client.post("/ask", json={"question": question, **body}, headers=headers or {})

    def test_an_answer_carries_the_id_of_the_logged_request_in_a_header_and_the_body_is_unchanged(self):
        with mock.patch("app.llm.chat", return_value=fake_response(CITED)):
            response = self.ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"answer", "sources", "grounded", "retrieval_mode"})
        header = response.headers["X-Request-ID"]
        self.assertRegex(header, r"^[0-9a-f]{16}$")
        (line,) = self.traces()
        self.assertEqual((line["request_id"], line["channel"]), (header, "api"))

    def test_every_error_carries_the_id_of_the_request_that_failed(self):
        cases = [(RuntimeError("No documents are indexed yet."), 400), (llm.QuotaExhausted("daily"), 429),
                 (status_error(openai.RateLimitError, 429), 429), (status_error(openai.InternalServerError, 503), 502),
                 (status_error(openai.AuthenticationError, 401), 502),
                 (openai.APIConnectionError(request=httpx.Request("POST", "http://test.invalid")), 502)]
        for error, status in cases:
            with self.subTest(error=type(error).__name__), mock.patch("app.llm.chat", side_effect=error):
                response = self.ask()
                self.assertEqual(response.status_code, status)
                record = self.errors()[-1]
                self.assertEqual(response.headers["X-Request-ID"], record["request_id"])
                self.assertEqual(record["http_status"], status)       # the log says what the caller really saw

    def test_asking_before_anything_is_indexed_still_gives_an_id_to_quote(self):
        store.reset_collection()
        response = self.ask()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers["X-Request-ID"], self.errors()[-1]["request_id"])

    def test_an_empty_question_makes_no_request_so_it_has_no_id_and_does_not_borrow_the_last_one(self):
        with mock.patch("app.llm.chat", return_value=fake_response(CITED)):
            first = self.ask()
        self.assertIn("X-Request-ID", first.headers)
        empty = self.ask(question="   ")
        self.assertEqual(empty.status_code, 200)
        self.assertNotIn("X-Request-ID", empty.headers)

    def test_an_endpoint_run_in_a_context_that_already_answered_something_does_not_borrow_its_id(self):
        from fastapi import Response
        from app.main import ask_endpoint
        from app.models import AskRequest
        self.addCleanup(observability.forget_last_request)
        observability._last_id.set("0123456789abcdef")                # what an earlier request in this same context left behind
        response = Response()
        ask_endpoint(AskRequest(question="   "), SimpleNamespace(headers={}), response)
        self.assertNotIn("X-Request-ID", response.headers)

    def test_two_requests_get_two_ids(self):
        with mock.patch("app.llm.chat", return_value=fake_response(CITED)):
            ids = {self.ask().headers["X-Request-ID"] for _ in range(3)}
        self.assertEqual(len(ids), 3)

    def test_the_caller_header_is_logged_trimmed_and_absent_when_not_sent(self):
        with mock.patch("app.llm.chat", return_value=fake_response(CITED)):
            self.ask(headers={"X-Caller-ID": "support-desk"})
            self.ask(headers={"X-Caller-ID": "x" * 200})
            self.ask()
        named, long, nameless = self.traces()
        self.assertEqual(named["caller"], "support-desk")
        self.assertEqual(long["caller"], "x" * 64)
        self.assertNotIn("caller", nameless)

    def test_a_broken_request_log_does_not_turn_an_answer_into_an_error(self):
        with mock.patch.object(observability.RequestLog, "open_span", side_effect=RuntimeError("log bug")), \
                mock.patch("app.llm.chat", return_value=fake_response(CITED)):
            response = self.ask()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"answer", "sources", "grounded", "retrieval_mode"})

    def test_a_request_log_that_cannot_be_built_means_no_header_not_an_error(self):
        with mock.patch.object(observability, "RequestLog", side_effect=RuntimeError("log bug")), \
                mock.patch("app.llm.chat", return_value=fake_response(CITED)):
            response = self.ask()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("X-Request-ID", response.headers)


if __name__ == "__main__":
    unittest.main()
