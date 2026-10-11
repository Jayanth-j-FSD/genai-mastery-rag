"""Week 11: the trace log and the error log (app/tracing.py): what a line holds, the append lock, failed requests, old lines."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import httpx
import openai

import _testkit
from app import llm, observability, tracing
from app.config import settings

ROOT = _testkit.ROOT

OLD_KEYS = {"trace_id", "ts", "question", "retrieved", "answer", "grounded", "config"}      # a line as Weeks 3 to 5 wrote it

CHILD_APPEND = """
import json, sys
sys.path.insert(0, sys.argv[1])
from app.tracing import append_line
path, tag, count = sys.argv[2], sys.argv[3], int(sys.argv[4])
for i in range(count):
    append_line(path, json.dumps({"tag": tag, "i": i, "pad": "x" * 6000}), timeout=30)
"""

CHILD_HOLD = """
import sys
sys.path.insert(0, sys.argv[1])
from app import tracing
with tracing._process_lock(sys.argv[2] + ".lock", 10):
    print("locked", flush=True)
    sys.stdin.readline()
"""


def status_error(error_class, status):
    request = httpx.Request("POST", "http://test.invalid")
    return error_class("provider said no", response=httpx.Response(status, request=request), body=None)


class LogTestCase(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.folder = folder
        self.traces = os.path.join(folder, "traces", "traces.jsonl")
        self.errors = os.path.join(folder, "traces", "errors.jsonl")
        self.enterContext(mock.patch.object(settings, "traces_path", self.traces))

    def lines(self, path):
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle.read().splitlines() if line.strip()]


class TraceLineTests(LogTestCase):
    def test_outside_a_request_the_line_is_exactly_what_it_was_before_week_11(self):
        tracing.log_trace("How many days?", [{"source": "leave.md", "score": 0.6, "text": "18 days"}], "18 days", True)
        (line,) = self.lines(self.traces)
        self.assertEqual(set(line), OLD_KEYS)
        self.assertEqual(len(line["trace_id"]), 8)

    def test_inside_a_request_the_line_gains_the_new_keys_and_keeps_every_old_one(self):
        with observability.channel("api", caller="desk"):
            with observability.begin_request() as request:
                with observability.span("search", "retrieve"):
                    pass
                tracing.log_trace("How many days?", [], "18 days", True)
        (line,) = self.lines(self.traces)
        self.assertTrue(OLD_KEYS <= set(line))
        self.assertEqual(line["request_id"], request.request_id)
        self.assertEqual(line["trace_id"], request.request_id[:8])    # one id, shown short in the older tools
        self.assertEqual((line["channel"], line["caller"], line["status"]), ("api", "desk", "ok"))
        self.assertEqual([span["name"] for span in line["spans"]], ["search"])
        for key in ("started_at", "ts_utc", "total_ms", "usage"):
            self.assertIn(key, line)

    def test_a_refusal_is_marked_refused(self):
        with observability.begin_request():
            tracing.log_trace("Bonus?", [], "I don't know based on the provided documents.", False)
        self.assertEqual(self.lines(self.traces)[0]["status"], "refused")

    def test_a_log_extras_bug_leaves_the_old_line_instead_of_losing_the_trace(self):
        with mock.patch.object(observability, "record_extras", side_effect=RuntimeError("log bug")):
            with observability.begin_request() as request:
                tracing.log_trace("How many days?", [], "18 days", True)
        (line,) = self.lines(self.traces)
        self.assertEqual(set(line), OLD_KEYS)
        self.assertEqual(line["trace_id"], request.trace_id)

    def test_a_write_that_fails_never_reaches_the_caller(self):
        with mock.patch.object(tracing, "append_line", side_effect=OSError("disk full")):
            tracing.log_trace("q", [], "a", True)                    # must not raise

    def test_a_log_held_by_another_process_drops_the_line_counts_it_and_does_not_raise(self):
        before = tracing.dropped_records()
        with mock.patch.object(tracing, "append_line", side_effect=tracing.LogBusy("held")):
            tracing.log_trace("q", [], "a", True)
        self.assertEqual(tracing.dropped_records(), before + 1)

    def test_lines_written_before_week_11_and_after_it_read_together(self):
        os.makedirs(os.path.dirname(self.traces))
        old = {"trace_id": "0a1b2c3d", "ts": "2026-09-15T10:00:00", "question": "old?", "retrieved": [], "answer": "a",
               "grounded": True, "config": {"retrieval_mode": "dense"}}
        with open(self.traces, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(old) + "\n" + json.dumps(dict(old, trace_id="1b2c3d4e", question="old two?")) + "\n")
        with observability.begin_request():
            tracing.log_trace("new?", [], "a", True)
        traces = tracing.read_traces()
        self.assertEqual([t["question"] for t in traces], ["old?", "old two?", "new?"])
        self.assertEqual([t["line_no"] for t in traces], [1, 2, 3])
        self.assertNotIn("request_id", traces[0])                    # an old line stays a complete record without it

    def test_read_traces_can_read_another_log_of_the_same_format(self):
        other = os.path.join(self.folder, "other.jsonl")
        with open(other, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"question": "from another log"}) + "\n")
        self.assertEqual([t["question"] for t in tracing.read_traces(path=other)], ["from another log"])
        self.assertEqual(tracing.read_traces(), [])                  # the default log is untouched and still empty


class AppendTests(LogTestCase):
    def test_a_line_cut_off_before_its_newline_does_not_swallow_the_next_line(self):
        os.makedirs(os.path.dirname(self.traces))
        with open(self.traces, "wb") as handle:
            handle.write(b'{"trace_id": "torn')                      # a process was killed in the middle of a write
        tracing.append_line(self.traces, json.dumps({"question": "after the tear"}))
        self.assertEqual([t["question"] for t in tracing.read_traces()], ["after the tear"])

    def test_threads_never_write_into_each_other(self):
        errors = []

        def work(tag):
            try:
                for i in range(25):
                    tracing.append_line(self.traces, json.dumps({"tag": tag, "i": i, "pad": "y" * 4000}))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(tag,)) for tag in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        self.assertEqual(errors, [])
        written = self.lines(self.traces)
        self.assertEqual(sorted((line["tag"], line["i"]) for line in written), [(t, i) for t in range(8) for i in range(25)])

    def test_processes_never_write_into_each_other(self):
        children = [subprocess.Popen([sys.executable, "-c", CHILD_APPEND, ROOT, self.traces, str(tag), "30"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE) for tag in range(4)]
        outputs = [child.communicate(timeout=120) for child in children]
        self.assertEqual([child.returncode for child in children], [0, 0, 0, 0], outputs)
        written = self.lines(self.traces)                            # every line parses: none was torn or glued to another
        self.assertEqual(sorted((int(line["tag"]), line["i"]) for line in written), [(t, i) for t in range(4) for i in range(30)])

    def test_a_lock_held_by_another_process_makes_the_writer_give_up_and_the_log_recovers_after(self):
        os.makedirs(os.path.dirname(self.traces))
        holder = subprocess.Popen([sys.executable, "-c", CHILD_HOLD, ROOT, self.traces], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            with self.assertRaises(tracing.LogBusy):
                tracing.append_line(self.traces, json.dumps({"question": "blocked"}), timeout=0.3)
            before = tracing.dropped_records()
            tracing.log_trace("also blocked", [], "a", True)         # the caller of log_trace sees no error at all
        finally:
            holder.stdin.close()
            holder.wait(timeout=30)
            holder.stdout.close()
            holder.stderr.close()
        self.assertEqual(tracing.dropped_records(), before + 1)
        tracing.append_line(self.traces, json.dumps({"question": "free again"}), timeout=5)
        self.assertEqual([t["question"] for t in tracing.read_traces()], ["free again"])


class ErrorLogTests(LogTestCase):
    def failed_request(self, exc, question="How many days of leave do I have?"):
        """Run a request that spent one step and then failed with `exc`, and log it the way the pipeline does."""
        try:
            with observability.channel("cli"):
                with observability.begin_request() as request:
                    with observability.span("embed_query", "embed"):
                        pass
                    raise exc
        except Exception as raised:
            tracing.log_error(request, raised, question)
        return request

    def test_the_error_log_sits_beside_the_trace_log(self):
        self.assertEqual(tracing.errors_path(), self.errors)

    def test_a_failed_request_is_logged_with_its_id_its_steps_and_the_kind_of_failure(self):
        request = self.failed_request(RuntimeError("No documents are indexed yet."))
        (record,) = self.lines(self.errors)
        self.assertEqual((record["request_id"], record["trace_id"]), (request.request_id, request.trace_id))
        self.assertEqual((record["error_class"], record["http_status"], record["channel"]), ("RuntimeError", 400, "cli"))
        self.assertEqual([span["name"] for span in record["spans"]], ["embed_query"])
        self.assertEqual(record["question_chars"], len("How many days of leave do I have?"))
        self.assertEqual(len(record["question_sha"]), 12)
        self.assertFalse(os.path.exists(self.traces))                # a failure is not a trace

    def test_the_error_log_never_holds_the_message_or_the_question(self):
        question = "What is the salary of the CFO, Jane Example?"
        secret = "sk-live-9f8e7d6c5b4a3210 in the provider's reply"
        self.failed_request(status_error(openai.AuthenticationError, 401), question)
        self.failed_request(RuntimeError(secret), question)
        with open(self.errors, encoding="utf-8") as handle:
            raw = handle.read()
        self.assertNotIn("sk-live", raw)
        self.assertNotIn("provider said no", raw)
        self.assertNotIn("CFO", raw)
        self.assertNotIn("Jane", raw)
        for record in self.lines(self.errors):
            self.assertTrue({"question", "message", "detail", "error", "text"}.isdisjoint(record), sorted(record))

    def test_the_same_question_has_the_same_short_hash_so_a_known_question_can_be_matched(self):
        self.failed_request(RuntimeError("a"), "Same question?")
        self.failed_request(RuntimeError("b"), "Same question?")
        first, second = self.lines(self.errors)
        self.assertEqual(first["question_sha"], second["question_sha"])
        self.assertNotEqual(first["request_id"], second["request_id"])

    def test_a_request_with_no_log_writes_nothing_and_raises_nothing(self):
        tracing.log_error(None, RuntimeError("x"), "q")
        self.assertFalse(os.path.exists(self.errors))

    def test_an_error_log_that_cannot_be_written_never_reaches_the_caller(self):
        with mock.patch.object(tracing, "append_line", side_effect=OSError("disk full")):
            self.failed_request(RuntimeError("x"))                   # must not raise
        with mock.patch.object(tracing, "append_line", side_effect=tracing.LogBusy("held")):
            before = tracing.dropped_records()
            self.failed_request(RuntimeError("x"))
        self.assertEqual(tracing.dropped_records(), before + 1)

    def test_errors_are_read_the_same_way_as_traces(self):
        self.failed_request(RuntimeError("a"))
        self.assertEqual([record["line_no"] for record in tracing.read_errors()], [1])
        self.assertEqual(tracing.read_errors(path=os.path.join(self.folder, "missing.jsonl")), [])


class StatusTests(unittest.TestCase):
    """The status the error log records must be the one the API really sent, or the log lies about what the caller saw."""

    CASES = [
        RuntimeError("No documents are indexed yet."),
        llm.QuotaExhausted("daily quota used up"),
        status_error(openai.RateLimitError, 429),
        status_error(openai.InternalServerError, 503),
        status_error(openai.AuthenticationError, 401),
        openai.APIConnectionError(request=httpx.Request("POST", "http://test.invalid")),
    ]

    def test_status_for_is_what_the_api_answers_with(self):
        from fastapi import HTTPException
        from app.main import _run
        for exc in self.CASES:
            with self.subTest(error=type(exc).__name__):
                with self.assertRaises(HTTPException) as caught:
                    _run(lambda: (_ for _ in ()).throw(exc))
                self.assertEqual(tracing.status_for(exc), caught.exception.status_code)

    def test_a_failure_the_api_does_not_map_has_no_status_and_is_not_mapped(self):
        from app.main import _run
        exc = ValueError("a bug")
        self.assertIsNone(tracing.status_for(exc))
        with self.assertRaises(ValueError):
            _run(lambda: (_ for _ in ()).throw(exc))


if __name__ == "__main__":
    unittest.main()
