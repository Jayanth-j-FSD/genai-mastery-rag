"""The agent loop, driven by a scripted fake model so every stop condition and failure path can be forced."""
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import _testkit
from _testkit import fake_response
from app import llm
from app.agent import loop
from app.agent.memory import Memory
from app.agent.tools import Tool, ToolError
from app.config import settings


def call(call_id, name, arguments):
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return SimpleNamespace(id=call_id, type="function", function=SimpleNamespace(name=name, arguments=raw))


def asks(*calls, content=None, prompt=10, completion=5):
    return fake_response(content, tool_calls=list(calls), prompt_tokens=prompt, completion_tokens=completion)


def says(text, prompt=10, completion=5):
    return fake_response(text, prompt_tokens=prompt, completion_tokens=completion)


class FakeClient:
    """Plays back scripted responses; an Exception is raised instead. Records every request."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({"messages": [dict(m) for m in kwargs["messages"]], "tools": kwargs.get("tools"),
                              "model": kwargs["model"]})
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def echo(text):
    return f"echo: {text}"


def explode():
    raise RuntimeError("boom")


def picky(value):
    if value != "ok":
        raise ToolError("value must be exactly 'ok'")
    return "fine"


TOOLS = [
    Tool("echo", "echoes text", {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, echo),
    Tool("explode", "always fails", {"type": "object", "properties": {}}, explode),
    Tool("picky", "needs ok", {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}, picky),
]


class LoopTestCase(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(settings, "llm_rpm", 0), mock.patch.object(settings, "llm_max_retries", 0),
                        mock.patch.object(settings, "agent_max_steps", 6),
                        mock.patch.object(settings, "agent_max_total_tokens", 10000),
                        mock.patch.object(settings, "agent_timeout_seconds", 60.0)):
            patcher.start()
            self.addCleanup(patcher.stop)
        llm.reset_usage()

    def run_script(self, script, tools=None, **kwargs):
        client = FakeClient(script)
        with mock.patch.object(llm, "_get_client", return_value=client):
            run = loop.run_agent("What is the answer?", TOOLS if tools is None else tools, **kwargs)
        return run, client


class ProviderQuirkTests(LoopTestCase):
    def test_a_providers_extra_data_on_a_tool_call_is_echoed_back_unchanged(self):
        signed = call("c1", "echo", {"text": "hi"})
        signed.extra_content = {"google": {"thought_signature": "SIG"}}        # what Gemini's thinking models send
        run, client = self.run_script([asks(signed), says("done")], use_memory=False)
        self.assertEqual(run.stop_reason, "final")
        echoed = client.requests[1]["messages"][2]["tool_calls"][0]
        self.assertEqual(echoed["extra_content"], {"google": {"thought_signature": "SIG"}})
        self.assertEqual(echoed["function"]["name"], "echo")

    def test_a_tool_call_without_extra_data_is_echoed_without_the_key(self):
        _run, client = self.run_script([asks(call("c1", "echo", {"text": "hi"})), says("done")], use_memory=False)
        self.assertNotIn("extra_content", client.requests[1]["messages"][2]["tool_calls"][0])


class HappyPathTests(LoopTestCase):
    def test_one_tool_then_a_final_answer(self):
        run, client = self.run_script([asks(call("c1", "echo", {"text": "hi"})), says("It is hi. [source: x.md]")], use_memory=False)
        self.assertEqual((run.stop_reason, run.finished, run.answer), ("final", True, "It is hi. [source: x.md]"))
        self.assertEqual([s["kind"] for s in run.steps], ["tool", "final"])
        first = run.steps[0]["tool_calls"][0]
        self.assertEqual((first["name"], first["observation"], first["ok"]), ("echo", "echo: hi", True))
        roles = [m["role"] for m in client.requests[1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool"])               # the result goes back to the model
        self.assertEqual(client.requests[1]["messages"][3]["tool_call_id"], "c1")
        self.assertEqual(client.requests[1]["messages"][2]["tool_calls"][0]["function"]["name"], "echo")

    def test_a_question_that_needs_no_tool_is_answered_at_once(self):
        run, _ = self.run_script([says("I don't know based on the provided documents.")], use_memory=False)
        self.assertEqual((run.stop_reason, len(run.steps), run.steps[0]["kind"]), ("final", 1, "final"))

    def test_several_tool_calls_in_one_step_all_run_and_all_answer(self):
        run, client = self.run_script([asks(call("a", "echo", {"text": "1"}), call("b", "echo", {"text": "2"})), says("done")],
                                      use_memory=False)
        self.assertEqual([c["observation"] for c in run.steps[0]["tool_calls"]], ["echo: 1", "echo: 2"])
        tool_messages = [m for m in client.requests[1]["messages"] if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["a", "b"])

    def test_the_model_is_shown_the_tool_list_and_the_system_prompt(self):
        _, client = self.run_script([says("hi")], use_memory=False)
        self.assertEqual([t["function"]["name"] for t in client.requests[0]["tools"]], ["echo", "explode", "picky"])
        self.assertEqual(client.requests[0]["messages"][0]["content"], loop.SYSTEM_PROMPT)
        self.assertEqual(client.requests[0]["messages"][1]["content"], "What is the answer?")

    def test_usage_is_the_sum_of_the_steps(self):
        run, _ = self.run_script([asks(call("c", "echo", {"text": "x"}), prompt=100, completion=10), says("ok", prompt=200, completion=20)],
                                 use_memory=False)
        self.assertEqual((run.usage["calls"], run.usage["prompt_tokens"], run.usage["completion_tokens"]), (2, 300, 30))
        self.assertEqual([s["tokens"] for s in run.steps], [{"prompt": 100, "completion": 10}, {"prompt": 200, "completion": 20}])

    def test_on_step_sees_every_step_as_it_finishes(self):
        seen = []
        run, _ = self.run_script([asks(call("c", "echo", {"text": "x"})), says("ok")], use_memory=False, on_step=seen.append)
        self.assertEqual([s["n"] for s in seen], [1, 2])
        self.assertEqual(seen, run.steps)

    def test_an_empty_final_reply_counts_as_dont_know(self):
        run, _ = self.run_script([says("")], use_memory=False)
        self.assertEqual((run.stop_reason, run.answer), ("final", loop.IDK))


class ToolFailureTests(LoopTestCase):
    def observation(self, script, **kwargs):
        run, client = self.run_script(script, use_memory=False, **kwargs)
        return run.steps[0]["tool_calls"][0], run, client

    def test_invalid_json_arguments_come_back_as_an_error_the_model_can_read(self):
        first, run, _ = self.observation([asks(call("c", "echo", "{not json")), says("recovered")])
        self.assertFalse(first["ok"])
        self.assertIn("ERROR: the arguments were not valid JSON", first["observation"])
        self.assertEqual(run.stop_reason, "final")                                      # and the run carries on

    def test_arguments_that_are_not_an_object_are_refused(self):
        first, _, _ = self.observation([asks(call("c", "echo", "[1, 2]")), says("x")])
        self.assertIn("must be a JSON object", first["observation"])

    def test_an_unknown_tool_lists_the_ones_that_exist(self):
        first, _, _ = self.observation([asks(call("c", "delete_everything", {})), says("x")])
        self.assertIn("there is no tool called 'delete_everything'", first["observation"])
        self.assertIn("echo, explode, picky", first["observation"])

    def test_a_tool_error_is_shown_as_advice(self):
        first, _, _ = self.observation([asks(call("c", "picky", {"value": "no"})), says("x")])
        self.assertEqual((first["ok"], first["observation"]), (False, "ERROR: value must be exactly 'ok'"))

    def test_a_tool_that_crashes_does_not_end_the_run(self):
        first, run, _ = self.observation([asks(call("c", "explode", {})), says("x")])
        self.assertIn("ERROR: explode failed (RuntimeError)", first["observation"])
        self.assertEqual(run.stop_reason, "final")

    def test_a_missing_or_unexpected_argument_name_is_a_recoverable_error(self):
        missing, _, _ = self.observation([asks(call("c", "echo", {})), says("x")])
        self.assertIn("wrong arguments for echo", missing["observation"])
        extra, _, _ = self.observation([asks(call("c", "echo", {"text": "a", "color": "red"})), says("x")])
        self.assertIn("wrong arguments for echo", extra["observation"])


class StopConditionTests(LoopTestCase):
    def test_the_step_limit_ends_a_model_that_never_finishes(self):
        script = [asks(call(f"c{i}", "echo", {"text": str(i)})) for i in range(1, 10)]
        run, client = self.run_script(script, use_memory=False, max_steps=3)
        self.assertEqual((run.stop_reason, run.finished, run.answer, len(run.steps)), ("max_steps", False, None, 3))
        self.assertEqual(len(client.requests), 3)                                       # it really stopped asking

    def test_asking_for_the_same_thing_twice_gets_a_warning_and_three_times_ends_the_run(self):
        same = lambda i: asks(call(f"c{i}", "echo", {"text": "same"}))
        run, client = self.run_script([same(1), same(2), same(3), says("never reached")], use_memory=False)
        self.assertEqual(run.stop_reason, "repeated_call")
        self.assertEqual(len(run.steps), 3)
        second = run.steps[1]["tool_calls"][0]
        self.assertFalse(second["ok"])
        self.assertIn("You already called echo", second["observation"])
        self.assertIn("echo: same", second["observation"])                              # it is reminded of the result it already has

    def test_a_repeat_followed_by_a_new_request_is_forgiven(self):
        script = [asks(call("1", "echo", {"text": "a"})), asks(call("2", "echo", {"text": "a"})),
                  asks(call("3", "echo", {"text": "b"})), asks(call("4", "echo", {"text": "a"})), says("done")]
        run, _ = self.run_script(script, use_memory=False)
        self.assertEqual(run.stop_reason, "final")

    def test_the_token_budget_stops_the_run_before_the_next_call(self):
        run, client = self.run_script([asks(call("c", "echo", {"text": "x"}), prompt=900, completion=200), says("unreachable")],
                                      use_memory=False, max_total_tokens=1000)
        self.assertEqual((run.stop_reason, run.answer), ("token_budget", None))
        self.assertEqual(len(client.requests), 1)

    def test_the_wall_clock_timeout_stops_the_run(self):
        times = iter([0.0, 0.0, 0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0])
        run, client = self.run_script([asks(call("c", "echo", {"text": "x"})), says("unreachable")], use_memory=False,
                                      timeout_seconds=50, clock=lambda: next(times))
        self.assertEqual(run.stop_reason, "timeout")
        self.assertEqual(len(client.requests), 1)

    def test_every_run_records_why_it_stopped(self):
        reasons = {loop.run_agent.__name__}                                              # sanity: the function exists
        self.assertTrue(reasons)
        run, _ = self.run_script([says("ok")], use_memory=False)
        self.assertEqual(run.stop_reason, "final")
        self.assertGreaterEqual(run.elapsed_seconds, 0)

    def test_limits_default_to_the_settings(self):
        with mock.patch.object(settings, "agent_max_steps", 2):
            script = [asks(call(f"c{i}", "echo", {"text": str(i)})) for i in range(1, 6)]
            run, _ = self.run_script(script, use_memory=False)
        self.assertEqual((run.stop_reason, len(run.steps)), ("max_steps", 2))


class ProviderFailureTests(LoopTestCase):
    def test_a_provider_failure_ends_the_run_visibly_not_with_a_traceback(self):
        import httpx
        from openai import InternalServerError
        failure = InternalServerError("down", response=httpx.Response(503, request=httpx.Request("POST", "http://x")), body=None)
        run, _ = self.run_script([failure], use_memory=False)
        self.assertEqual((run.stop_reason, run.answer, run.steps[-1]["kind"]), ("error", None, "error"))
        self.assertIn("InternalServerError", run.steps[-1]["content"])

    def test_a_used_up_daily_quota_is_not_swallowed(self):
        with mock.patch.object(llm, "chat", side_effect=llm.QuotaExhausted("daily quota used up")):
            with self.assertRaises(llm.QuotaExhausted):
                loop.run_agent("q", TOOLS, use_memory=False)

    def test_a_reply_with_no_choices_is_an_error_step(self):
        run, _ = self.run_script([SimpleNamespace(choices=[], usage=None)], use_memory=False)
        self.assertEqual((run.stop_reason, run.steps[-1]["kind"]), ("error", "error"))
        self.assertIn("no reply", run.steps[-1]["content"])


class MemoryTests(LoopTestCase):
    def test_a_saved_note_is_shown_again_on_every_later_step(self):
        script = [asks(call("1", "remember", {"fact": "the carry-forward limit is 10 days"})),
                  asks(call("2", "echo", {"text": "x"})), says("done")]
        run, client = self.run_script(script, TOOLS)
        self.assertEqual(run.notes, ["the carry-forward limit is 10 days"])
        self.assertNotIn("Notes you saved", client.requests[0]["messages"][0]["content"])
        for later in client.requests[1:]:
            self.assertIn("the carry-forward limit is 10 days", later["messages"][0]["content"])

    def test_the_remember_tool_is_offered_only_when_memory_is_on(self):
        _, on = self.run_script([says("x")], TOOLS, use_memory=True)
        _, off = self.run_script([says("x")], TOOLS, use_memory=False)
        self.assertIn("remember", [t["function"]["name"] for t in on.requests[0]["tools"]])
        self.assertNotIn("remember", [t["function"]["name"] for t in off.requests[0]["tools"]])

    def test_old_tool_results_are_shortened_but_recent_ones_stay_whole(self):
        big = Tool("big", "returns a lot", {"type": "object", "properties": {"n": {"type": "string"}}, "required": ["n"]},
                   lambda n: f"result {n}: " + "word " * 100)
        script = [asks(call(str(i), "big", {"n": str(i)})) for i in range(1, 5)] + [says("done")]
        run, client = self.run_script(script, [big], max_steps=8)
        last_messages = client.requests[-1]["messages"]
        tool_contents = [m["content"] for m in last_messages if m["role"] == "tool"]
        self.assertEqual(len(tool_contents), 4)
        self.assertTrue(all(c.startswith("[shortened]") for c in tool_contents[:2]))
        self.assertFalse(any(c.startswith("[shortened]") for c in tool_contents[2:]))
        self.assertEqual(run.steps[0]["tool_calls"][0]["observation"].startswith("result 1"), True)   # the log keeps the full text

    def test_memory_limits(self):
        memory = Memory()
        for number in range(12):
            memory.remember(f"fact {number}")
        with self.assertRaises(ToolError):
            memory.remember("one too many")
        with self.assertRaises(ToolError):
            Memory().remember("   ")
        long_note = Memory()
        long_note.remember("x" * 1000)
        self.assertEqual(len(long_note.notes[0]), 300)

    def test_compact_leaves_short_results_and_non_tool_messages_alone(self):
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                    {"role": "tool", "content": "short"}, {"role": "tool", "content": "b " * 200},
                    {"role": "tool", "content": "c " * 200}, {"role": "tool", "content": "d " * 200}]
        Memory.compact(messages)
        self.assertEqual(messages[2]["content"], "short")
        self.assertTrue(messages[3]["content"].startswith("[shortened]"))
        self.assertFalse(messages[4]["content"].startswith("[shortened]"))
        self.assertEqual(messages[0]["content"], "s")


if __name__ == "__main__":
    unittest.main()
