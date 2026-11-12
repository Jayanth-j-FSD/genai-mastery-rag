"""Week 11: app/observability.py, the spans of one request (no network, no index, no file input or output)."""
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import _testkit
from app import observability, pricing
from app.config import settings
from test_llm import LlmTestCase, status_error, FakeClient
from openai import RateLimitError


class FakeClock:
    """A clock the test moves by hand, so a duration is exactly what the test says it is."""

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ProviderTimeTests(unittest.TestCase):
    """provider_ms and wait_ms come from a coarser clock than the step's own duration, so they are never allowed to add up to more than the step took."""

    def close_model_span(self, took, provider, wait, kind="model"):
        clock = FakeClock()
        with observability.begin_request(clock=clock) as request:
            handle = request.open_span("generate", kind, {"provider_ms": provider, "wait_ms": wait})
            clock.advance(took)
            return request.close_span(handle)

    def test_provider_time_a_tick_longer_than_the_step_is_cut_to_the_step(self):
        span = self.close_model_span(took=0.030, provider=31.0, wait=0.0)             # 31 ms measured inside a step that took 30
        self.assertEqual((span["duration_ms"], span["provider_ms"], span["wait_ms"]), (30.0, 30.0, 0.0))

    def test_waiting_is_cut_to_what_is_left_of_the_step_after_the_provider_time(self):
        span = self.close_model_span(took=0.010, provider=8.0, wait=5.0)
        self.assertEqual((span["provider_ms"], span["wait_ms"]), (8.0, 2.0))
        self.assertLessEqual(span["provider_ms"] + span["wait_ms"], span["duration_ms"])

    def test_figures_that_already_fit_are_left_exactly_as_measured(self):
        span = self.close_model_span(took=0.010, provider=4.0, wait=3.0)
        self.assertEqual((span["provider_ms"], span["wait_ms"]), (4.0, 3.0))

    def test_a_step_that_is_not_a_model_call_is_left_alone(self):
        span = self.close_model_span(took=0.010, provider=31.0, wait=9.0, kind="retrieve")
        self.assertEqual((span["provider_ms"], span["wait_ms"]), (31.0, 9.0))

    def test_a_model_step_that_never_reached_the_recorder_has_no_provider_time_to_cut(self):
        span = self.close_model_span(took=0.010, provider=None, wait=None)
        self.assertEqual((span["provider_ms"], span["wait_ms"]), (None, None))


class ImportCostTests(unittest.TestCase):
    def modules_loaded_by(self, statement):
        script = "import sys\n" + statement + "\nprint('openai' in sys.modules)"
        run = subprocess.run([sys.executable, "-c", script], cwd=_testkit.ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr[-500:])
        return run.stdout.strip()

    def test_a_tool_that_only_reads_logs_does_not_load_the_providers_sdk(self):
        self.assertEqual(self.modules_loaded_by("import app.tracing"), "False")
        self.assertEqual(self.modules_loaded_by("import app.observability"), "False")
        self.assertEqual(self.modules_loaded_by("from evals import logsearch, costreport"), "False")

    def test_the_sdk_is_loaded_when_a_model_step_is_opened(self):
        script = "from app import observability\nwith observability.begin_request():\n    with observability.model_span('x'):\n        pass"
        self.assertEqual(self.modules_loaded_by(script), "True")


class RequestTests(unittest.TestCase):
    def test_a_request_has_a_sixteen_digit_id_and_its_first_eight_are_the_trace_id(self):
        with observability.begin_request() as request:
            pass
        self.assertRegex(request.request_id, r"^[0-9a-f]{16}$")
        self.assertEqual(request.trace_id, request.request_id[:8])
        self.assertEqual(len(request.trace_id), 8)             # the older log lines have always had an 8-digit trace id

    def test_two_requests_never_share_an_id(self):
        with observability.begin_request() as first:
            pass
        with observability.begin_request() as second:
            pass
        self.assertNotEqual(first.request_id, second.request_id)

    def test_the_request_is_current_inside_the_block_and_gone_after_it_but_its_id_stays_readable(self):
        self.assertIsNone(observability.current())
        with observability.begin_request() as request:
            self.assertIs(observability.current(), request)
        self.assertIsNone(observability.current())
        self.assertEqual(observability.last_request_id(), request.request_id)    # an error handler needs it afterwards

    def test_a_request_that_fails_still_closes_and_leaves_its_id(self):
        with self.assertRaises(ValueError):
            with observability.begin_request() as request:
                raise ValueError("boom")
        self.assertIsNone(observability.current())
        self.assertEqual(observability.last_request_id(), request.request_id)

    def test_forgetting_the_last_request_clears_only_the_remembered_id(self):
        with observability.begin_request():
            pass
        observability.forget_last_request()
        self.assertIsNone(observability.last_request_id())

    def test_the_channel_says_how_the_request_arrived_and_resets_after_the_block(self):
        with observability.begin_request() as before:
            pass
        with observability.channel("api", caller="support-desk"):
            with observability.begin_request() as inside:
                pass
        with observability.begin_request() as after:
            pass
        self.assertEqual((before.channel, before.caller), ("unknown", None))
        self.assertEqual((inside.channel, inside.caller), ("api", "support-desk"))
        self.assertEqual((after.channel, after.caller), ("unknown", None))

    def test_requests_in_two_threads_do_not_see_each_others_channel_or_spans(self):
        seen, barrier = {}, threading.Barrier(2)

        def work(name):
            with observability.channel(name):
                with observability.begin_request() as request:
                    barrier.wait(timeout=5)                     # both requests are open at the same moment
                    with observability.span(f"step-of-{name}", "retrieve"):
                        pass
                    barrier.wait(timeout=5)
                    seen[name] = (request.channel, [span["name"] for span in request.spans])

        threads = [threading.Thread(target=work, args=(name,)) for name in ("one", "two")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(seen, {"one": ("one", ["step-of-one"]), "two": ("two", ["step-of-two"])})


class SpanTests(unittest.TestCase):
    def test_spans_are_timed_in_order_and_do_not_overlap(self):
        clock = FakeClock()
        with observability.begin_request(clock=clock) as request:
            with observability.span("embed_query", "embed"):
                clock.advance(0.010)
            with observability.span("search", "retrieve", mode="dense"):
                clock.advance(0.025)
            clock.advance(0.005)                                # time spent between steps belongs to no span
        first, second = request.spans
        self.assertEqual((first["name"], first["start_ms"], first["duration_ms"]), ("embed_query", 0.0, 10.0))
        self.assertEqual((second["name"], second["start_ms"], second["duration_ms"]), ("search", 10.0, 25.0))
        self.assertEqual(second["mode"], "dense")               # what the caller said about the step is kept on it
        self.assertEqual([span["span_id"] for span in request.spans], [1, 2])
        self.assertLessEqual(sum(span["duration_ms"] for span in request.spans), request.total_ms())
        self.assertEqual(request.total_ms(), 40.0)
        self.assertLessEqual(first["start_ms"] + first["duration_ms"], second["start_ms"])

    def test_the_real_clock_measures_milliseconds_not_zero_and_not_seconds(self):
        with observability.begin_request() as request:
            with observability.span("nap", "retrieve"):
                time.sleep(0.02)
        duration = request.spans[0]["duration_ms"]
        self.assertGreaterEqual(duration, 10)                   # a 20 ms sleep, with room for a coarse timer
        self.assertLess(duration, 2000)                          # and not a figure in seconds or microseconds by mistake

    def test_a_span_outside_a_request_does_nothing_and_changes_nothing(self):
        with observability.span("orphan", "retrieve") as handle:
            result = 21 * 2
        self.assertIsNone(handle)
        self.assertEqual(result, 42)
        with observability.model_span("orphan-model") as handle:
            result = "still runs"
        self.assertIsNone(handle)
        self.assertEqual(result, "still runs")
        observability.note(anything="ignored")                  # no request, no effect, no error

    def test_a_failing_step_keeps_its_span_with_the_error_type_and_the_error_goes_on(self):
        with self.assertRaises(KeyError):
            with observability.begin_request() as request:
                with observability.span("search", "retrieve"):
                    raise KeyError("secret-looking-text")
        (span,) = request.spans
        self.assertEqual((span["status"], span["error"]), ("error", "KeyError"))
        self.assertNotIn("secret-looking-text", repr(request.spans))      # the type is logged, never the message

    def test_the_first_span_of_a_kind_is_marked_cold_and_the_next_is_not(self):
        with mock.patch.object(observability, "_seen_kinds", set()):
            with observability.begin_request() as request:
                with observability.span("a", "embed"):
                    pass
                with observability.span("b", "embed"):
                    pass
        self.assertEqual([span["cold"] for span in request.spans], [True, False])

    def test_notes_and_the_finished_record(self):
        with observability.begin_request() as request:
            observability.note(refusal_cause="no_chunks", index_id="434:abc")
            with observability.span("search", "retrieve"):
                pass
        extras = observability.record_extras(request, status="refused")
        self.assertEqual((extras["request_id"], extras["channel"], extras["status"]), (request.request_id, "unknown", "refused"))
        self.assertEqual((extras["refusal_cause"], extras["index_id"]), ("no_chunks", "434:abc"))
        self.assertEqual(len(extras["spans"]), 1)
        self.assertEqual(extras["usage"]["model_calls"], 0)
        self.assertNotIn("caller", extras)                       # no caller was named, so no empty key

    def test_what_an_error_record_keeps_of_a_request_has_no_text_in_it(self):
        with observability.begin_request() as request:
            observability.note(sources=["leave.md"], chars={"question": 12})
            with observability.span("search", "retrieve", query_text="how many days of leave", top_k=4):
                pass
        kept = observability.snapshot(request)
        self.assertEqual(set(kept["spans"][0]), {"span_id", "name", "kind", "start_ms", "duration_ms", "status", "error"})
        self.assertNotIn("how many days", repr(kept))
        self.assertNotIn("leave.md", repr(kept))                  # not even the notes: an error record names steps, not content


class ModelSpanTests(LlmTestCase):
    """The model span, through the real llm.chat with a scripted client (the rate limiter and the sleeps run on a fake clock)."""

    def setUp(self):
        super().setUp()
        self.request_clock = lambda: self.clock["now"]            # the request reads the same fake time the limiter does
        self.enterContext(mock.patch.object(settings, "price_input_per_million", 0.0))         # unpriced unless a test says so, whatever a .env holds
        self.enterContext(mock.patch.object(settings, "price_output_per_million", 0.0))

    def span_of(self, request):
        (span,) = request.model_spans()
        return span

    def test_a_model_call_records_its_provider_time_its_tokens_and_the_model_that_answered(self):
        from app import llm
        reply = _testkit.fake_response("ok", prompt_tokens=120, completion_tokens=30)
        reply.model = "served-model"
        client = self.use(reply)

        original = client.chat.completions.create

        def slow_create(**kwargs):
            self.clock["now"] += 2.5                               # the provider takes 2.5 seconds
            return original(**kwargs)
        client.chat.completions.create = slow_create
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("generate", requested_model="asked-model"):
                llm.chat([], model="asked-model")
        span = self.span_of(request)
        self.assertEqual((span["model_requested"], span["model_served"]), ("asked-model", "served-model"))
        self.assertEqual((span["prompt_tokens"], span["completion_tokens"], span["tokens_known"]), (120, 30, True))
        self.assertEqual((span["provider_ms"], span["wait_ms"], span["attempts"]), (2500.0, 0.0, 1))
        self.assertEqual(span["duration_ms"], 2500.0)
        self.assertEqual(request.usage(), {"model_calls": 1, "prompt_tokens": 120, "completion_tokens": 30, "tokens_known": True,
                                           "provider_ms": 2500.0, "wait_ms": 0.0})

    def test_waiting_for_the_rate_limit_is_kept_apart_from_the_provider_time(self):
        from app import llm
        self.use(_testkit.fake_response("first"), _testkit.fake_response("second"))
        with mock.patch.object(settings, "llm_rpm", 1):
            with observability.begin_request(clock=self.request_clock) as request:
                with observability.model_span("one"):
                    llm.chat([], model="m")                       # the limiter has room for the first call
                with observability.model_span("two"):
                    llm.chat([], model="m")                       # and makes the second wait out the minute
        first, second = request.model_spans()
        self.assertEqual(first["wait_ms"], 0.0)
        self.assertGreater(second["wait_ms"], 59000)              # about a minute, spent sleeping, not at the provider
        self.assertEqual(second["provider_ms"], 0.0)
        self.assertAlmostEqual(second["duration_ms"], second["provider_ms"] + second["wait_ms"], places=3)

    def test_a_retry_is_counted_and_its_back_off_is_waiting(self):
        from app import llm
        busy = status_error(RateLimitError, 429, {"error": {"message": "Quota exceeded. Please retry in 7s.", "status": "RESOURCE_EXHAUSTED",
                                                            "details": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}})
        self.use(busy, _testkit.fake_response("worked second time"))
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("generate"):
                llm.chat([], model="m")
        span = self.span_of(request)
        self.assertEqual(span["attempts"], 2)
        self.assertGreaterEqual(span["wait_ms"], 7000)
        self.assertEqual(span["status"], "ok")

    def test_a_failed_call_keeps_its_span_with_the_error_type_and_no_token_figures(self):
        from app import llm
        self.use(status_error(RateLimitError, 429, {"error": {"message": "nope", "status": "RESOURCE_EXHAUSTED",
                                                              "details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}))
        with self.assertRaises(llm.QuotaExhausted):
            with observability.begin_request(clock=self.request_clock) as request:
                with observability.model_span("generate"):
                    llm.chat([], model="m")
        span = self.span_of(request)
        self.assertEqual((span["status"], span["error"]), ("error", "QuotaExhausted"))
        self.assertEqual(span["attempts"], 1)                      # the daily cap ends the call at the first attempt: no retry could help
        self.assertFalse(span["tokens_known"])
        self.assertIsNone(span["prompt_tokens"])                   # no usage came back, so none is claimed
        self.assertIsNone(span["cost_usd"])

    def test_usage_that_lacks_the_prompt_count_is_unknown_not_a_zero(self):
        from app import llm
        reply = _testkit.fake_response("ok")
        reply.usage = SimpleNamespace(completion_tokens=5)           # the completion was counted, the prompt was not
        self.use(reply)
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("generate"):
                llm.chat([], model="m")
        span = self.span_of(request)
        self.assertEqual((span["tokens_known"], span["prompt_tokens"], span["completion_tokens"]), (False, None, None))
        self.assertFalse(request.usage()["tokens_known"])

    def test_the_time_a_failed_attempt_spent_at_the_provider_counts_with_the_one_that_answered(self):
        from app import llm
        busy = status_error(RateLimitError, 429, {"error": {"message": "Quota exceeded. Please retry in 7s.", "status": "RESOURCE_EXHAUSTED",
                                                            "details": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}})
        client = self.use(busy, _testkit.fake_response("worked second time"))
        original, spent = client.chat.completions.create, iter([2.0, 1.0])

        def timed_create(**kwargs):
            self.clock["now"] += next(spent)                          # the first attempt takes 2 seconds to fail, the second 1 to answer
            return original(**kwargs)
        client.chat.completions.create = timed_create
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("generate"):
                llm.chat([], model="m")
        span = self.span_of(request)
        self.assertEqual((span["attempts"], span["provider_ms"]), (2, 3000.0))
        self.assertGreaterEqual(span["wait_ms"], 7000)
        self.assertEqual(request.usage()["provider_ms"], 3000.0)

    def test_an_error_record_keeps_the_provider_time_the_waiting_and_the_tries_of_a_model_step(self):
        from app import llm
        self.use(_testkit.fake_response("ok"))
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("generate"):
                self.clock["now"] += 0.5
                llm.chat([], model="m")
        kept = observability.snapshot(request)["spans"][0]
        full = self.span_of(request)
        self.assertEqual((kept["provider_ms"], kept["wait_ms"], kept["attempts"]), (full["provider_ms"], full["wait_ms"], full["attempts"]))
        self.assertIn("wait_ms", kept)

    def test_a_reply_with_no_usage_block_is_unknown_not_free(self):
        from app import llm
        reply = _testkit.fake_response("ok")
        reply.usage = None                                          # a provider that sends no usage block
        self.use(reply)
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("generate"):
                llm.chat([], model="m")
        span = self.span_of(request)
        self.assertFalse(span["tokens_known"])
        self.assertIsNone(span["prompt_tokens"])
        self.assertIsNone(span["completion_tokens"])
        self.assertFalse(request.usage()["tokens_known"])           # the request's sums are then lower bounds, and say so

    def test_the_request_tokens_are_the_sum_of_its_model_spans(self):
        from app import llm
        self.use(_testkit.fake_response("a", prompt_tokens=10, completion_tokens=1),
                 _testkit.fake_response("b", prompt_tokens=20, completion_tokens=2))
        with observability.begin_request(clock=self.request_clock) as request:
            for name in ("one", "two"):
                with observability.model_span(name):
                    llm.chat([], model="m")
        usage = request.usage()
        self.assertEqual((usage["model_calls"], usage["prompt_tokens"], usage["completion_tokens"]), (2, 30, 3))

    def test_cost_is_filled_only_when_a_price_is_stated_and_the_prices_travel_with_it(self):
        from app import llm
        self.use(_testkit.fake_response("a", prompt_tokens=1000, completion_tokens=100),
                 _testkit.fake_response("b", prompt_tokens=1000, completion_tokens=100))
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("unpriced"):
                llm.chat([], model="m")
            with mock.patch.object(settings, "price_input_per_million", 2.0), mock.patch.object(settings, "price_output_per_million", 10.0):
                with observability.model_span("priced"):
                    llm.chat([], model="m")
        unpriced, priced = request.model_spans()
        self.assertIsNone(unpriced["cost_usd"])                    # unknown is not free
        self.assertNotIn("prices", unpriced)
        self.assertAlmostEqual(priced["cost_usd"], (1000 * 2.0 + 100 * 10.0) / 1_000_000, places=9)
        self.assertEqual((priced["prices"]["input_per_million"], priced["prices"]["output_per_million"]), (2.0, 10.0))
        self.assertEqual(priced["prices"]["note"], pricing.ASSUMPTION)

    def test_a_span_that_holds_two_calls_adds_them_up_and_is_unknown_if_either_did_not_report(self):
        from app import llm
        silent = _testkit.fake_response("b")
        silent.usage = None
        self.use(_testkit.fake_response("a", prompt_tokens=10, completion_tokens=1), silent)
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("two-calls"):
                llm.chat([], model="m")
                llm.chat([], model="m")
        span = self.span_of(request)
        self.assertEqual(span["attempts"], 2)
        self.assertFalse(span["tokens_known"])
        self.assertIsNone(span["prompt_tokens"])

    def test_a_usage_block_with_no_counts_is_unknown_not_zero(self):
        from types import SimpleNamespace
        from app import llm
        for usage in (SimpleNamespace(), SimpleNamespace(prompt_tokens=None, completion_tokens=None), SimpleNamespace(prompt_tokens=5, completion_tokens=None)):
            with self.subTest(usage=vars(usage)):
                reply = _testkit.fake_response("ok")
                reply.usage = usage
                self.use(reply)
                with observability.begin_request(clock=self.request_clock) as request:
                    with observability.model_span("generate"):
                        llm.chat([], model="m")
                span = self.span_of(request)
                self.assertFalse(span["tokens_known"])
                self.assertIsNone(span["prompt_tokens"])
                self.assertIsNone(span["cost_usd"])

    def test_a_call_that_never_reaches_the_recorder_leaves_an_honest_unknown(self):
        with observability.begin_request(clock=self.request_clock) as request:
            with observability.model_span("replaced-by-a-test"):
                pass
        span = self.span_of(request)
        self.assertEqual((span["attempts"], span["tokens_known"], span["cost_usd"]), (0, False, None))


class NeverRaiseTests(unittest.TestCase):
    """Rule 1 of the module: a bug in the log must not turn an answer into an error."""

    def test_a_span_whose_bookkeeping_breaks_still_runs_the_step(self):
        with mock.patch.object(observability.RequestLog, "open_span", side_effect=RuntimeError("log bug")):
            with observability.begin_request() as request:
                with observability.span("search", "retrieve") as handle:
                    result = "the step still ran"
        self.assertIsNone(handle)
        self.assertEqual(result, "the step still ran")
        self.assertEqual(request.spans, [])

    def test_a_span_that_breaks_while_closing_does_not_change_the_error_the_step_raised(self):
        with mock.patch.object(observability.RequestLog, "close_span", side_effect=RuntimeError("log bug")):
            with self.assertRaises(ZeroDivisionError):
                with observability.begin_request():
                    with observability.span("search", "retrieve"):
                        1 / 0

    def test_a_request_whose_log_cannot_be_built_runs_without_one(self):
        with mock.patch.object(observability, "RequestLog", side_effect=RuntimeError("log bug")):
            with observability.begin_request() as request:
                result = "answered"
        self.assertIsNone(request)
        self.assertEqual(result, "answered")

    def test_a_model_span_whose_price_lookup_breaks_still_returns_the_reply(self):
        from app import llm
        scripted = FakeClient([_testkit.fake_response("fine", prompt_tokens=5, completion_tokens=2)])
        with mock.patch.object(llm, "_get_client", return_value=scripted), \
                mock.patch.object(pricing, "cost_of", side_effect=RuntimeError("pricing bug")), \
                mock.patch.object(settings, "llm_rpm", 0), mock.patch.object(llm.time, "sleep"):
            with observability.begin_request() as request:
                with observability.model_span("generate"):
                    reply = llm.chat([], model="m")
        self.assertEqual(reply.choices[0].message.content, "fine")
        (span,) = request.model_spans()
        self.assertEqual(span["status"], "ok")                      # the call is logged even though its cost could not be

    def test_a_note_that_cannot_be_stored_is_dropped_quietly(self):
        with observability.begin_request() as request:
            request.notes = None                                    # something stomped on the notes
            observability.note(refusal_cause="no_chunks")           # must not raise

    def test_guarded_says_once_and_returns_the_default(self):
        said = []
        with mock.patch.object(observability, "_warned", set()), mock.patch("builtins.print", side_effect=lambda *a, **k: said.append(a)):
            first = observability.guarded("somewhere", lambda: 1 / 0, default="fallback")
            second = observability.guarded("somewhere", lambda: 1 / 0, default="fallback")
        self.assertEqual((first, second), ("fallback", "fallback"))
        self.assertEqual(len(said), 1)                              # said once per place, not once per request


if __name__ == "__main__":
    unittest.main()
