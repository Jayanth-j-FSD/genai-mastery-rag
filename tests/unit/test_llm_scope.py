"""Week 10: llm.call_scope(), the per-call record that says which piece of work spent what (no network)."""
import contextvars
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import _testkit
from app import llm
from test_llm import DAILY_BODY, RATE_LIMIT_BODY, FakeClient, LlmTestCase, status_error
from openai import BadRequestError, RateLimitError

USAGE_KEYS = {"calls", "prompt_tokens", "completion_tokens", "api_seconds", "wait_seconds"}


def reply(model=None, prompt_tokens=7, completion_tokens=3):
    """A fake chat reply, optionally naming the model the provider says answered."""
    response = _testkit.fake_response("ok", prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    if model:
        response.model = model
    return response


class RecordTests(LlmTestCase):
    def test_a_call_inside_a_scope_is_recorded_with_its_tokens_and_both_model_names(self):
        self.use(reply("served-name", 11, 4))
        with llm.call_scope("researcher") as scope:
            llm.chat([], model="asked-for")
        self.assertEqual(scope.label, "researcher")
        self.assertEqual(len(scope.calls), 1)
        record = scope.calls[0]
        self.assertEqual((record["model"], record["served"]), ("asked-for", "served-name"))
        self.assertEqual((record["prompt_tokens"], record["completion_tokens"]), (11, 4))
        self.assertEqual((record["status"], record["error"], record["attempts"]), ("ok", None, 1))

    def test_what_the_provider_says_about_total_cached_and_reasoning_tokens_is_kept_when_it_says_it(self):
        full = reply(prompt_tokens=100, completion_tokens=20)
        full.usage.total_tokens = 150                                              # 30 more than prompt plus completion: hidden thinking
        full.usage.prompt_tokens_details = SimpleNamespace(cached_tokens=40)
        full.usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=30)
        self.use(full, reply())
        with llm.call_scope("x") as scope:
            llm.chat([], model="m1")
            llm.chat([], model="m1")
        said, silent = scope.calls
        self.assertEqual((said["total_tokens"], said["cached_tokens"], said["reasoning_tokens"]), (150, 40, 30))
        self.assertEqual((silent["total_tokens"], silent["cached_tokens"], silent["reasoning_tokens"]), (None, None, None))

    def test_a_token_figure_that_is_not_a_whole_number_is_not_kept_as_one(self):
        odd = reply()
        odd.usage.total_tokens = "many"
        odd.usage.prompt_tokens_details = SimpleNamespace(cached_tokens=True)
        self.use(odd)
        with llm.call_scope("x") as scope:
            llm.chat([], model="m1")
        self.assertEqual((scope.calls[0]["total_tokens"], scope.calls[0]["cached_tokens"]), (None, None))

    def test_a_scope_keeps_the_extra_data_its_opener_gave_it(self):
        with llm.call_scope("researcher", handoff=2) as scope:
            pass
        self.assertEqual((scope.label, scope.extra), ("researcher", {"handoff": 2}))

    def test_a_call_outside_every_scope_is_counted_but_recorded_nowhere(self):
        self.use(reply(), reply())
        with llm.call_scope("a") as scope:
            llm.chat([], model="m1")
        llm.chat([], model="m1")
        self.assertEqual(len(scope.calls), 1)
        self.assertEqual(llm.usage_snapshot()["calls"], 2)

    def test_a_nested_scope_gets_its_own_calls_and_the_outer_one_keeps_the_rest(self):
        self.use(reply(prompt_tokens=1), reply(prompt_tokens=20), reply(prompt_tokens=300))
        with llm.call_scope("outer") as outer:
            llm.chat([], model="m1")
            with llm.call_scope("inner") as inner:
                llm.chat([], model="m1")
            llm.chat([], model="m1")
        self.assertEqual([c["prompt_tokens"] for c in outer.calls], [1, 300])
        self.assertEqual([c["prompt_tokens"] for c in inner.calls], [20])

    def test_the_scopes_add_up_to_the_process_wide_counters(self):
        self.use(reply(), reply(), reply())
        with llm.call_scope("outer") as outer:
            llm.chat([], model="m1")
            with llm.call_scope("inner") as inner:
                llm.chat([], model="m1")
                llm.chat([], model="m1")
        total = llm.usage_snapshot()
        for key in ("calls", "prompt_tokens", "completion_tokens"):
            self.assertEqual(outer.totals()[key] + inner.totals()[key], total[key], key)

    def test_totals_use_the_same_five_keys_as_the_counters_and_an_empty_scope_is_all_zero(self):
        self.assertEqual(set(llm.usage_snapshot()), USAGE_KEYS)
        with llm.call_scope("idle") as scope:
            pass
        self.assertEqual(scope.totals(), {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                          "api_seconds": 0.0, "wait_seconds": 0.0})

    def test_an_outer_scope_can_still_total_everything_done_under_it(self):
        self.use(reply(prompt_tokens=1), reply(prompt_tokens=20), reply(prompt_tokens=300))
        with llm.call_scope("outer") as outer:
            llm.chat([], model="m1")
            with llm.call_scope("inner", handoff=1) as inner:
                llm.chat([], model="m1")
            llm.chat([], model="m1")
        self.assertEqual(outer.children, [inner])
        self.assertEqual(outer.totals()["prompt_tokens"], 301)                              # its own calls only
        self.assertEqual(outer.totals(deep=True)["prompt_tokens"], 321)                     # and with everything under it
        self.assertEqual([(scope.label, call["prompt_tokens"]) for scope, call in outer.walk()],
                         [("outer", 1), ("inner", 20), ("outer", 300)])                     # in the order the calls finished
        self.assertEqual(outer.totals(deep=True)["calls"], llm.usage_snapshot()["calls"])

    def test_calls_are_numbered_in_the_order_they_finish_even_when_the_clock_does_not_move(self):
        self.use(reply(), reply(), reply())
        with llm.call_scope("a") as first, llm.call_scope("b") as second:
            llm.chat([], model="m1")
        with llm.call_scope("c") as third:
            llm.chat([], model="m1")
            llm.chat([], model="m1")
        numbers = [call["seq"] for scope in (second, third) for call in scope.calls]
        self.assertEqual(numbers, sorted(numbers))
        self.assertEqual(len(set(numbers)), 3)

    def test_a_scope_left_by_an_exception_stops_recording(self):
        self.use(reply(), reply())
        with self.assertRaises(ValueError):
            with llm.call_scope("broken") as scope:
                llm.chat([], model="m1")
                raise ValueError("boom")
        llm.chat([], model="m1")
        self.assertEqual(len(scope.calls), 1)


class RetryAndFailureTests(LlmTestCase):
    def test_a_retried_call_is_one_record_that_carries_the_attempts_and_the_waiting(self):
        self.use(status_error(RateLimitError, 429, RATE_LIMIT_BODY), reply())
        with llm.call_scope("x") as scope:
            llm.chat([], model="m1")
        self.assertEqual(len(scope.calls), 1)
        record = scope.calls[0]
        self.assertEqual((record["attempts"], record["status"]), (2, "ok"))
        self.assertAlmostEqual(record["wait_seconds"], 52.14, places=6)
        self.assertAlmostEqual(record["wait_seconds"], llm.usage_snapshot()["wait_seconds"], places=6)

    def test_a_rate_limit_pause_before_the_call_counts_as_waiting_for_that_call_only(self):
        self.use(*[reply() for _ in range(3)])
        with llm.call_scope("x") as scope:
            for _ in range(3):
                llm.chat([], model="m1", rpm=2)
        waits = [record["wait_seconds"] for record in scope.calls]
        self.assertEqual(waits[:2], [0.0, 0.0])
        self.assertGreater(waits[2], 59.0)

    def test_a_failed_call_is_recorded_as_an_error_with_no_tokens_and_still_raises(self):
        self.use(status_error(BadRequestError, 400, {"error": {"message": "bad"}}))
        with llm.call_scope("x") as scope:
            with self.assertRaises(BadRequestError):
                llm.chat([], model="m1")
        record = scope.calls[0]
        self.assertEqual((record["status"], record["error"]), ("error", "BadRequestError"))
        self.assertEqual((record["prompt_tokens"], record["completion_tokens"], record["served"]), (0, 0, None))
        self.assertEqual(scope.totals()["calls"], 0)                    # a failed call is not a call, as in the counters

    def test_the_daily_quota_stop_is_recorded_and_still_raised_as_quota_exhausted(self):
        self.use(status_error(RateLimitError, 429, DAILY_BODY))
        with llm.call_scope("x") as scope:
            with self.assertRaises(llm.QuotaExhausted):
                llm.chat([], model="m1")
        self.assertEqual((scope.calls[0]["status"], scope.calls[0]["error"]), ("error", "QuotaExhausted"))

    def test_the_limiter_returns_the_seconds_it_waited(self):
        self.assertEqual(llm._wait_for_slot("m1", 0), 0.0)
        self.assertEqual([llm._wait_for_slot("m2", 2), llm._wait_for_slot("m2", 2)], [0.0, 0.0])
        self.assertGreater(llm._wait_for_slot("m2", 2), 59.0)


class TickingClient(FakeClient):
    """Every attempt takes the next number of seconds on the test's fake clock, then answers or fails as scripted."""

    def __init__(self, case, outcomes, seconds):
        super().__init__(outcomes)
        self.case, self.seconds = case, list(seconds)

    def _create(self, **kwargs):
        self.case.clock["now"] += self.seconds.pop(0)
        return super()._create(**kwargs)


class TimeTests(LlmTestCase):
    def use_ticking(self, outcomes, seconds):
        patcher = mock.patch.object(llm, "_get_client", return_value=TickingClient(self, outcomes, seconds))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_calls_seconds_are_the_time_inside_the_provider_and_equal_what_the_counters_kept(self):
        self.use_ticking([reply()], [2.5])
        with llm.call_scope("x") as scope:
            llm.chat([], model="m1")
        self.assertEqual(scope.calls[0]["seconds"], 2.5)
        self.assertEqual(scope.totals()["api_seconds"], llm.usage_snapshot()["api_seconds"])

    def test_a_retried_calls_seconds_cover_every_attempt_and_its_waiting_covers_every_pause(self):
        self.use_ticking([status_error(RateLimitError, 429, RATE_LIMIT_BODY), reply()], [1.5, 2.5])
        with llm.call_scope("x") as scope:
            llm.chat([], model="m1")
        record = scope.calls[0]
        self.assertEqual(record["attempts"], 2)
        self.assertAlmostEqual(record["seconds"], 4.0, places=6)                              # the failed attempt's 1.5 s and the good one's 2.5 s
        self.assertAlmostEqual(record["wait_seconds"], 52.14, places=6)
        counters = llm.usage_snapshot()
        self.assertEqual((scope.totals()["api_seconds"], scope.totals()["wait_seconds"]), (round(counters["api_seconds"], 3), round(counters["wait_seconds"], 3)))

    def test_a_failed_call_still_records_the_seconds_it_spent_in_the_provider(self):
        self.use_ticking([status_error(BadRequestError, 400, {"error": {"message": "bad"}})], [3.0])
        with llm.call_scope("x") as scope:
            with self.assertRaises(BadRequestError):
                llm.chat([], model="m1")
        self.assertEqual(scope.calls[0]["seconds"], 3.0)
        self.assertEqual(scope.totals()["api_seconds"], llm.usage_snapshot()["api_seconds"])

    def test_the_daily_quota_stop_records_the_seconds_the_failed_request_took(self):
        self.use_ticking([status_error(RateLimitError, 429, DAILY_BODY)], [4.0])
        with llm.call_scope("x") as scope:
            with self.assertRaises(llm.QuotaExhausted):
                llm.chat([], model="m1")
        self.assertEqual(scope.calls[0]["seconds"], 4.0)

    def test_a_call_is_stamped_with_the_wall_clock_time_it_began_not_a_stopwatch_reading(self):
        self.use(reply())
        before = time.time()
        with llm.call_scope("x") as scope:
            llm.chat([], model="m1")
        self.assertTrue(before <= scope.calls[0]["started_at"] <= time.time(), scope.calls[0]["started_at"])      # seconds since the epoch, as the docstring says


class ThreadTests(LlmTestCase):
    def run_in_thread(self, work, copy_context):
        context = contextvars.copy_context()
        thread = threading.Thread(target=(lambda: context.run(work)) if copy_context else work)
        thread.start()
        thread.join()

    def test_a_thread_started_with_a_copied_context_records_into_the_scope_that_started_it(self):
        self.use(reply())
        with llm.call_scope("parent") as scope:
            self.run_in_thread(lambda: llm.chat([], model="m1"), copy_context=True)
        self.assertEqual(len(scope.calls), 1)

    def test_a_thread_started_without_the_context_records_nothing(self):
        self.use(reply())
        with llm.call_scope("parent") as scope:
            self.run_in_thread(lambda: llm.chat([], model="m1"), copy_context=False)
        self.assertEqual(scope.calls, [])
        self.assertEqual(llm.usage_snapshot()["calls"], 1)              # the counters still saw it


if __name__ == "__main__":
    unittest.main()
