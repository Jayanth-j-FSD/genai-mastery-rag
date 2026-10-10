"""app/llm.py: the rate limiter, the retries and the usage counters (no network)."""
import unittest
from unittest import mock

import httpx
from openai import APIConnectionError, BadRequestError, InternalServerError, RateLimitError

import _testkit
from app import llm
from app.config import settings


def status_error(error_class, status, body):
    """Build a real OpenAI SDK error the way the SDK would raise it."""
    request = httpx.Request("POST", "http://test.invalid/chat")
    response = httpx.Response(status, request=request, json=body)
    return error_class(f"Error code: {status} - {body}", response=response, body=body)


RATE_LIMIT_BODY = {"error": {"message": "Quota exceeded. Please retry in 51.14s.", "status": "RESOURCE_EXHAUSTED",
                             "details": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}}
DAILY_BODY = {"error": {"message": "Quota exceeded.", "status": "RESOURCE_EXHAUSTED",
                        "details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}


class FakeClient:
    """Plays back a list of outcomes: an exception is raised, anything else is returned."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        from types import SimpleNamespace
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class LlmTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = {"now": 1000.0}
        self.sleeps = []

        def fake_sleep(seconds):
            self.sleeps.append(seconds)
            self.clock["now"] += seconds

        for patcher in (
            mock.patch.object(llm.time, "sleep", fake_sleep),
            mock.patch.object(llm.time, "monotonic", lambda: self.clock["now"]),
            mock.patch.object(settings, "llm_rpm", 0),
            mock.patch.object(settings, "llm_max_retries", 3),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        llm._call_times.clear()
        llm.reset_usage()

    def use(self, *outcomes):
        client = FakeClient(outcomes)
        patcher = mock.patch.object(llm, "_get_client", return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client


class RetryTests(LlmTestCase):
    def test_success_returns_response_and_counts_usage(self):
        client = self.use(_testkit.fake_response("hello", prompt_tokens=11, completion_tokens=4))
        response = llm.chat([{"role": "user", "content": "hi"}], model="m1")
        self.assertEqual(response.choices[0].message.content, "hello")
        self.assertEqual(client.calls[0]["model"], "m1")
        self.assertEqual(client.calls[0]["temperature"], 0)           # deterministic by default
        usage = llm.usage_snapshot()
        self.assertEqual((usage["calls"], usage["prompt_tokens"], usage["completion_tokens"]), (1, 11, 4))

    def test_model_defaults_to_llm_model_setting(self):
        client = self.use(_testkit.fake_response())
        llm.chat([])
        self.assertEqual(client.calls[0]["model"], settings.llm_model)

    def test_rate_limit_waits_the_hinted_time_then_succeeds(self):
        client = self.use(status_error(RateLimitError, 429, RATE_LIMIT_BODY), _testkit.fake_response("done"))
        response = llm.chat([], model="m1")
        self.assertEqual(response.choices[0].message.content, "done")
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(self.sleeps, [52.14])                          # the 51.14s hint plus 1s margin
        self.assertEqual(llm.usage_snapshot()["calls"], 1)              # a failed attempt is not a call

    def test_rate_limit_without_hint_waits_30_seconds(self):
        self.use(status_error(RateLimitError, 429, {"error": {"message": "slow down"}}), _testkit.fake_response())
        llm.chat([], model="m1")
        self.assertEqual(self.sleeps, [30.0])

    def test_daily_quota_is_not_retried(self):
        client = self.use(status_error(RateLimitError, 429, DAILY_BODY))
        with self.assertRaises(llm.QuotaExhausted):
            llm.chat([], model="m1")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_server_error_backs_off_then_succeeds(self):
        client = self.use(status_error(InternalServerError, 503, {"error": {"message": "high demand"}}),
                          status_error(InternalServerError, 503, {"error": {"message": "high demand"}}),
                          _testkit.fake_response("ok"))
        llm.chat([], model="m1")
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(self.sleeps, [5, 10])                          # exponential backoff

    def test_connection_error_is_retried(self):
        client = self.use(APIConnectionError(request=httpx.Request("POST", "http://test.invalid")),
                          _testkit.fake_response())
        llm.chat([], model="m1")
        self.assertEqual(len(client.calls), 2)

    def test_bad_request_is_raised_immediately(self):
        client = self.use(status_error(BadRequestError, 400, {"error": {"message": "bad"}}))
        with self.assertRaises(BadRequestError):
            llm.chat([], model="m1")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_gives_up_after_max_retries_and_raises_the_original_error(self):
        errors = [status_error(InternalServerError, 503, {"error": {"message": "x"}}) for _ in range(4)]
        client = self.use(*errors)
        with self.assertRaises(InternalServerError):
            llm.chat([], model="m1")
        self.assertEqual(len(client.calls), 4)                          # 1 try + 3 retries

    def test_missing_key_gives_a_clear_error(self):
        with mock.patch.object(settings, "openai_api_key", ""), mock.patch.object(llm, "_client", None):
            with self.assertRaises(RuntimeError) as ctx:
                llm._get_client()
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))


class LimiterTests(LlmTestCase):
    def test_third_call_in_a_minute_waits_when_limit_is_two(self):
        self.use(*[_testkit.fake_response() for _ in range(3)])
        for _ in range(3):
            llm.chat([], model="m1", rpm=2)
        self.assertEqual(len(self.sleeps), 1)
        self.assertGreater(self.sleeps[0], 59.0)                        # waited out most of the minute
        self.assertGreater(llm.usage_snapshot()["wait_seconds"], 59.0)

    def test_limit_is_per_model(self):
        self.use(*[_testkit.fake_response() for _ in range(4)])
        for model in ("a", "a", "b", "b"):
            llm.chat([], model=model, rpm=2)
        self.assertEqual(self.sleeps, [])                               # two calls each, nobody waited

    def test_zero_means_no_limit(self):
        self.use(*[_testkit.fake_response() for _ in range(10)])
        for _ in range(10):
            llm.chat([], model="m1", rpm=0)
        self.assertEqual(self.sleeps, [])

    def test_old_calls_leave_the_window(self):
        self.use(*[_testkit.fake_response() for _ in range(3)])
        llm.chat([], model="m1", rpm=2)
        llm.chat([], model="m1", rpm=2)
        self.clock["now"] += 61                                         # a minute passes
        llm.chat([], model="m1", rpm=2)
        self.assertEqual(self.sleeps, [])


class UsageTests(LlmTestCase):
    def test_usage_since_reports_only_the_new_work(self):
        self.use(*[_testkit.fake_response(prompt_tokens=10, completion_tokens=2) for _ in range(3)])
        llm.chat([], model="m1")
        before = llm.usage_snapshot()
        llm.chat([], model="m1")
        llm.chat([], model="m1")
        delta = llm.usage_since(before)
        self.assertEqual((delta["calls"], delta["prompt_tokens"], delta["completion_tokens"]), (2, 20, 4))

    def test_reset_zeroes_everything(self):
        self.use(_testkit.fake_response())
        llm.chat([], model="m1")
        llm.reset_usage()
        self.assertEqual(llm.usage_snapshot(),
                         {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "api_seconds": 0.0, "wait_seconds": 0.0})

    def test_response_without_usage_does_not_crash(self):
        from types import SimpleNamespace
        self.use(SimpleNamespace(choices=[], usage=None))
        llm.chat([], model="m1")
        self.assertEqual(llm.usage_snapshot()["calls"], 1)


if __name__ == "__main__":
    unittest.main()
