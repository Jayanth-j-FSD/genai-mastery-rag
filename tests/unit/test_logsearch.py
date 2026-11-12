"""Week 11: finding a past request in the logs (evals/logsearch.py, scripts/find_requests.py)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from _testkit import ROOT, fake_response, isolated_index, patched_embeddings
from app import llm, observability, tracing
from app.config import settings
from app.rag import pipeline
from evals import costreport, drill, logsearch
from test_llm import FakeClient

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import find_requests                                       # noqa: E402

DOCS = {"leave.md": "# Leave\nEmployees receive 18 days of annual leave.\n",
        "notice.md": "# Notice\nA permanent employee gives 30 days of written notice.\n"}


def old_line(trace_id, ts, question, answer, grounded=True, retrieved=("notice.md",)):
    """A line as Weeks 3 to 5 wrote it: no request id, no steps, no timings."""
    return {"trace_id": trace_id, "ts": ts, "question": question, "retrieved": [{"source": s, "score": 0.5, "text": "t"} for s in retrieved],
            "answer": answer, "grounded": grounded, "config": {"llm_model": "m", "llm_model_served": "m"}}


class LogCase(unittest.TestCase):
    """A folder with a real traces.jsonl and errors.jsonl: requests answered by the real pipeline, one that failed, and old lines."""

    def setUp(self):
        corpus = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        for name, text in DOCS.items():
            with open(os.path.join(corpus, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        self.enterContext(isolated_index(corpus_dir=corpus, embed_provider="local", dense_search="exact", retrieval_mode="dense", top_k=2))
        self.enterContext(patched_embeddings())
        self.enterContext(mock.patch.object(settings, "llm_rpm", 0))
        self.enterContext(mock.patch.object(settings, "min_relevance", 0.0))
        self.enterContext(mock.patch.object(settings, "price_input_per_million", 0.0))
        self.enterContext(mock.patch.object(settings, "price_output_per_million", 0.0))
        pipeline.ingest()
        self.traces, self.errors = settings.traces_path, tracing.errors_path()

    def ask(self, question, reply, channel="api", caller=None, prompt_tokens=120, completion_tokens=9):
        client = FakeClient([fake_response(reply, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)])
        with mock.patch.object(llm, "_get_client", return_value=client), observability.channel(channel, caller=caller):
            pipeline.answer(question)
        return observability.last_request_id()

    def failing_request(self, question):
        with mock.patch("app.llm.chat", side_effect=RuntimeError("secret detail")), self.assertRaises(RuntimeError):
            pipeline.answer(question)
        return observability.last_request_id()

    def write_old(self, *records):
        os.makedirs(os.path.dirname(self.traces), exist_ok=True)
        with open(self.traces, "a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def load(self):
        return logsearch.load([self.traces, self.errors])[0]


class LoadTests(LogCase):
    def test_both_logs_are_read_and_a_failed_request_is_marked_as_one(self):
        good = self.ask("How much notice?", "30 days. [source: notice.md]")
        bad = self.failing_request("How many leave days?")
        records = self.load()
        self.assertEqual([(r["kind"], r["id"]) for r in records], [("trace", good), ("error", bad)])
        self.assertEqual(records[1]["status"], "error")
        self.assertEqual(records[1]["question"], "")                       # the error log never held the question

    def test_a_line_cut_off_by_a_crash_is_counted_not_fatal_and_a_missing_log_is_empty(self):
        self.ask("How much notice?", "30 days. [source: notice.md]")
        with open(self.traces, "a", encoding="utf-8") as handle:
            handle.write('{"trace_id": "torn\n')
            handle.write("[1, 2]\n")
        records, skipped, took = logsearch.load([self.traces, os.path.join(os.path.dirname(self.traces), "nothing.jsonl")])
        self.assertEqual((len(records), skipped), (1, 2))
        self.assertGreaterEqual(took, 0)

    def test_a_log_path_that_is_a_folder_or_cannot_be_read_is_reported_not_a_traceback(self):
        self.ask("How much notice?", "30 days. [source: notice.md]")
        folder = os.path.dirname(self.traces)
        with self.assertRaises(ValueError) as caught:
            logsearch.load([folder])
        self.assertIn("is not a log file", str(caught.exception))
        with mock.patch("builtins.open", side_effect=PermissionError("denied")), self.assertRaises(ValueError) as caught:
            logsearch.load([self.traces])
        self.assertIn("could not be read (PermissionError)", str(caught.exception))
        self.assertNotIn(str(ROOT), str(caught.exception))

    def test_a_line_that_is_json_but_not_the_shape_of_a_log_line_is_counted_not_fatal(self):
        self.ask("How much notice?", "30 days. [source: notice.md]")
        with open(self.traces, "a", encoding="utf-8") as handle:
            for odd in ({"question": "q", "usage": 5}, {"question": "q", "retrieved": 5}, {"question": "q", "retrieved": [5]}):
                handle.write(json.dumps(odd) + "\n")
        records, skipped, _took = logsearch.load([self.traces])
        self.assertEqual((len(records), skipped), (1, 3))

    def test_a_tag_that_names_a_file_in_another_folder_is_matched_to_the_retrieved_document_as_the_app_matches_it(self):
        line = dict(old_line("0a1b2c3d", "2026-10-08T10:00:00", "q?", "30 days [source: remote.md]", retrieved=("policies/remote.md",)), sources=["policies/remote.md"])
        record = logsearch.normalize(line, "t.jsonl", 1, "trace")
        self.assertEqual((record["cited"], record["listed"]), (["policies/remote.md"], ["policies/remote.md"]))
        self.assertEqual(len(logsearch.search([record], {"cited": "policies"})), 1)
        text = "\n".join(logsearch.show_lines(record))
        self.assertRegex(text, r"1\. cited policies/remote\.md")
        self.assertNotIn("listed", text.replace("retrieved", ""))                       # listed and cited agree, so there is nothing to explain
        unmatched = logsearch.normalize(dict(line, answer="x [source: other.md]"), "t.jsonl", 1, "trace")
        self.assertEqual(unmatched["cited"], ["other.md"])

    def test_a_line_from_before_week_11_is_found_by_its_short_trace_id_and_says_it_has_no_steps(self):
        self.write_old(old_line("0a1b2c3d", "2026-09-15T10:00:00", "old question?", "old answer [source: notice.md]"))
        (record,) = self.load()
        self.assertEqual((record["id"], record["status"], record["cited"], record["spans"]), ("0a1b2c3d", "ok", ["notice.md"], None))
        self.assertIn("no steps recorded", "\n".join(logsearch.show_lines(record)))

    def test_times_are_the_local_time_whichever_field_the_line_has(self):
        local = datetime(2026, 10, 8, 14, 30)
        as_utc = local.astimezone().astimezone(timezone.utc)
        for fields in ({"ts": local.isoformat()}, {"ts_utc": as_utc.isoformat(timespec="milliseconds")},
                       {"started_at": local.astimezone().isoformat(timespec="milliseconds")}):
            with self.subTest(fields=list(fields)):
                self.assertEqual(logsearch._parse_time(fields).replace(second=0, microsecond=0), local)
        for fixed in ("2026-10-08T14:30:00.000+09:00", "2026-10-08T14:30:00.000-07:00", "2026-10-08T09:00:00.000+00:00"):      # offsets the machine's own cannot equal all at once
            with self.subTest(fixed=fixed):
                self.assertEqual(logsearch._parse_time({"started_at": fixed}), datetime.fromisoformat(fixed).astimezone().replace(tzinfo=None))
                self.assertEqual(logsearch._parse_time({"ts_utc": fixed}), datetime.fromisoformat(fixed).astimezone().replace(tzinfo=None))
        self.assertIsNone(logsearch._parse_time({"ts": "not a time"}))
        self.assertIsNone(logsearch._parse_time({}))

    def test_the_documents_cited_are_the_ones_the_answer_names_in_its_tags_whatever_the_app_listed(self):
        self.assertEqual(logsearch.cited_documents({"sources": ["a.md"], "answer": "x [source: b.md]"}), ["b.md"])
        self.assertEqual(logsearch.cited_documents({"sources": ["a.md", "b.md"], "answer": "no tag at all"}), [])
        self.assertEqual(logsearch.listed_documents({"sources": ["a.md", "b.md"], "answer": "no tag at all"}), ["a.md", "b.md"])
        self.assertEqual(logsearch.listed_documents({"answer": "x [source: c.md]"}), ["c.md"])           # an old line has no sources key: the tags are all there is
        self.assertEqual(logsearch.cited_documents({"answer": "x [source: A.md, B.md] y [source: A.md]"}), ["A.md", "B.md"])
        self.assertEqual(logsearch.cited_documents({"answer": "no tags"}), [])
        self.assertEqual(logsearch.cited_documents({"answer": None}), [])


class FilterTests(LogCase):
    def setUp(self):
        super().setUp()
        self.notice = self.ask("How much notice must a permanent employee give?", "30 days. [source: notice.md]", channel="api", caller="desk")
        self.leave = self.ask("How many days of annual leave?", "18 days. [source: leave.md]", channel="cli")
        self.refused = self.ask("What is the bonus?", "I don't know based on the provided documents.", channel="api")
        self.failed = self.failing_request("Anything?")
        self.write_old(old_line("0a1b2c3d", "2026-09-15T10:00:00", "old notice question?", "60 days [source: handbook.md]", retrieved=("handbook.md",)))
        self.records = self.load()

    def ids(self, **criteria):
        return [r["id"] for r in logsearch.search(self.records, criteria)]

    def test_every_word_must_appear_in_the_question_or_the_answer(self):
        self.assertEqual(set(self.ids(text=["notice"])), {self.notice, "0a1b2c3d"})
        self.assertEqual(set(self.ids(text=["NOTICE", "30 days"])), {self.notice})
        self.assertEqual(self.ids(text=["notice", "bonus"]), [])

    def test_the_answer_can_be_searched_by_pattern(self):
        self.assertEqual(set(self.ids(answer_regex=r"\b(30|60) days")), {self.notice, "0a1b2c3d"})
        self.assertEqual(self.ids(answer_regex=r"^18 DAYS"), [self.leave])

    def test_the_time_window_is_inclusive_and_a_bare_date_includes_the_whole_day(self):
        self.assertEqual(self.ids(until=datetime(2026, 9, 15, 23, 59, 59)), ["0a1b2c3d"])
        self.assertEqual(self.ids(since=datetime(2026, 9, 15, 10, 0, 0), until=datetime(2026, 9, 15, 10, 0, 0)), ["0a1b2c3d"])
        self.assertEqual(self.ids(since=datetime(2026, 9, 15, 10, 0, 1), until=datetime(2026, 9, 16)), [])
        recent = self.ids(since=datetime.now() - timedelta(hours=1))
        self.assertEqual(set(recent), {self.notice, self.leave, self.refused, self.failed})

    def test_the_cited_and_retrieved_documents_narrow_independently(self):
        self.assertEqual(self.ids(cited="notice.md"), [self.notice])
        self.assertEqual(self.ids(cited="HANDBOOK"), ["0a1b2c3d"])
        self.assertEqual(self.ids(retrieved_from="handbook"), ["0a1b2c3d"])
        self.assertIn(self.leave, self.ids(retrieved_from="leave"))

    def test_status_and_grounded_tell_answered_from_refused_from_failed(self):
        self.assertEqual(self.ids(status="refused"), [self.refused])
        self.assertEqual(self.ids(status="error"), [self.failed])
        self.assertEqual(set(self.ids(status="ok")), {self.notice, self.leave, "0a1b2c3d"})
        self.assertEqual(self.ids(grounded=False), [self.refused])
        self.assertEqual(set(self.ids(grounded=True)), {self.notice, self.leave, "0a1b2c3d"})      # a failed request is neither

    def test_channel_and_id_prefix(self):
        self.assertEqual(set(self.ids(channel="api")), {self.notice, self.refused})
        self.assertEqual(self.ids(channel="unknown"), [self.failed])           # the failed request was made outside any channel
        self.assertEqual(self.ids(channel="cli"), [self.leave])
        self.assertEqual(self.ids(id=self.notice[:10]), [self.notice])
        self.assertEqual(self.ids(id=self.notice[:8]), [self.notice])                 # the short trace id finds it too
        self.assertEqual(self.ids(id="0a1b"), ["0a1b2c3d"])
        self.assertEqual(self.ids(id="zzzz"), [])
        self.assertEqual(self.ids(id=self.notice[3:9]), [])                          # a prefix, not any part of the id

    def test_a_short_id_prefix_lists_every_request_that_starts_with_it(self):
        records = [dict(self.records[0], id="ab12cd34" + "0" * 8, trace_id="ab12cd34"), dict(self.records[1], id="ab12ef56" + "0" * 8, trace_id="ab12ef56")]
        self.assertEqual(len(logsearch.search(records, {"id": "ab12"})), 2)
        self.assertEqual(len(logsearch.search(records, {"id": "ab12c"})), 1)

    def test_slower_than_reads_the_total_time_and_skips_lines_that_have_none(self):
        slow = dict(self.records[0], total_ms=5000.0)
        quick = dict(self.records[1], total_ms=40.0)
        none = dict(self.records[2], total_ms=None)
        self.assertEqual([r["id"] for r in logsearch.search([slow, quick, none], {"slower_than": 1000})], [slow["id"]])
        self.assertEqual([r["id"] for r in logsearch.search([slow, quick, none], {"slower_than": 5000.0})], [])         # strictly slower

    def test_costlier_than_uses_only_the_prices_given_and_skips_requests_whose_tokens_are_unknown(self):
        priced = dict(self.records[0], prompt_tokens=1000, completion_tokens=100)
        cheap = dict(self.records[1], prompt_tokens=10, completion_tokens=1)
        unknown = dict(self.records[2], prompt_tokens=None, completion_tokens=None)
        found = logsearch.search([priced, cheap, unknown], {"costlier_than": 0.0005, "input_per_million": 2.0, "output_per_million": 10.0})
        self.assertEqual([r["id"] for r in found], [priced["id"]])                      # 1000 x 2 + 100 x 10 = $0.003; the cheap one is $0.00003
        self.assertEqual(logsearch.search([priced], {"costlier_than": 0.0, "input_per_million": None, "output_per_million": None}), [])

    def test_a_cost_exactly_at_the_threshold_is_not_costlier_than_it(self):
        exact = dict(self.records[0], prompt_tokens=1000, completion_tokens=0)             # 1000 x $2 per million = $0.002
        self.assertEqual(logsearch.search([exact], {"costlier_than": 0.002, "input_per_million": 2.0, "output_per_million": 10.0}), [])
        self.assertEqual(len(logsearch.search([exact], {"costlier_than": 0.0019, "input_per_million": 2.0, "output_per_million": 10.0})), 1)

    def test_the_price_settings_are_never_read_so_one_log_prints_one_cost(self):
        priced = dict(self.records[0], prompt_tokens=1000, completion_tokens=100)
        with mock.patch.object(settings, "price_input_per_million", 99.0), mock.patch.object(settings, "price_output_per_million", 99.0):
            self.assertIsNone(logsearch.cost_of(priced, None, None))
            self.assertIn("no price stated", "\n".join(logsearch.show_lines(self.records[0])))

    def test_results_come_oldest_first_with_undated_lines_last(self):
        undated = dict(self.records[0], time=None, id="undated")
        ordered = [r["id"] for r in logsearch.search(self.records + [undated], {})]
        self.assertEqual(ordered[0], "0a1b2c3d")                                         # 2026-09-15 is the oldest
        self.assertEqual(ordered[-1], "undated")


class UncitedAnswerTests(LogCase):
    """When the model writes no [source: ...] tag the app lists every retrieved document as the sources: a search for what an answer cited must not find those."""

    def setUp(self):
        super().setUp()
        self.uncited = self.ask("How many days of annual leave?", "The leave is 18 days.")
        self.cited = self.ask("How much notice?", "30 days. [source: notice.md]")
        self.records = {r["id"]: r for r in self.load()}

    def test_an_answer_with_no_tag_cites_nothing_even_though_the_app_listed_documents(self):
        record = self.records[self.uncited]
        self.assertEqual(record["cited"], [])
        self.assertTrue(set(record["listed"]) >= {"leave.md"})
        self.assertTrue(len(record["listed"]) >= 1)

    def test_searching_by_cited_document_does_not_find_a_request_that_only_listed_it(self):
        found = [r["id"] for r in logsearch.search(list(self.records.values()), {"cited": "leave.md"})]
        self.assertEqual(found, [])
        self.assertEqual([r["id"] for r in logsearch.search(list(self.records.values()), {"cited": "notice.md"})], [self.cited])

    def test_show_says_the_answer_has_no_tag_and_what_the_app_listed_instead(self):
        text = "\n".join(logsearch.show_lines(self.records[self.uncited]))
        self.assertIn("(nothing: the answer has no [source: ...] tag)", text)
        self.assertIn("listed    ", text)
        self.assertNotIn(" cited leave.md", text)                                          # no passage is marked as cited
        self.assertNotIn("listed", "\n".join(logsearch.show_lines(self.records[self.cited])).replace("retrieved", ""))

    def test_the_failure_tool_replays_what_the_app_showed_as_sources(self):
        import failure_to_test
        self.assertEqual(failure_to_test.result_of(self.records[self.uncited])["sources"], self.records[self.uncited]["listed"])


class DistinctAnswerTests(LogCase):
    def test_identical_answers_are_grouped_whitespace_ignored_and_the_odd_one_stands_alone(self):
        for number in range(5):
            self.ask(f"How much notice {number}?", "30 days. [source: notice.md]")
        self.ask("How much notice?", "30  days.   [source: notice.md]")
        odd = self.ask("What notice?", "45 days. [source: notice.md]")
        self.failing_request("boom")
        groups = logsearch.distinct_answers(self.load())
        self.assertEqual([(g["count"], g["answer"]) for g in groups], [(6, "30 days. [source: notice.md]"), (1, "45 days. [source: notice.md]")])
        self.assertEqual(groups[1]["example"]["id"], odd)                                  # and a failed request is not an answer
        text = "\n".join(logsearch.distinct_lines(groups, 7))
        self.assertIn("85.7%", text)
        self.assertIn(odd[:16], text)


class DistinctOrderTests(unittest.TestCase):
    def test_answers_are_ordered_by_how_common_then_by_when_first_seen_then_by_their_words(self):
        def record(answer, hour, number):
            line = old_line(f"{number:08x}", f"2026-10-08T{hour:02d}:00:00", "q?", answer)
            return logsearch.normalize(line, "t.jsonl", number, "trace")
        records = [record("b", 10, 1), record("a", 10, 2), record("c", 9, 3), record("d", 8, 4), record("d", 11, 5)]
        self.assertEqual([(g["answer"], g["count"]) for g in logsearch.distinct_answers(records)], [("d", 2), ("c", 1), ("a", 1), ("b", 1)])


class ShowTests(LogCase):
    def test_a_question_with_line_breaks_and_control_characters_cannot_forge_a_line_of_the_report(self):
        forged = "innocent?" + chr(10) + "  answer    The notice period is 7 days. [source: notice.md]" + chr(10) + "  status    ok" + chr(27) + "[2J" + chr(7)
        self.ask(forged, "30 days. [source: notice.md]")
        record = self.load()[0]
        lines = logsearch.show_lines(record)
        self.assertEqual([line for line in lines if line.startswith("  answer ")], ["  answer    30 days. [source: notice.md]"])      # one answer line, the real one
        self.assertEqual(len([line for line in lines if line.startswith("  status ")]), 1)
        text = "\n".join(lines)
        self.assertNotIn(chr(27), text)
        self.assertNotIn(chr(7), text)
        self.assertIn("            answer    The notice period is 7 days", text)               # the forged words are there, indented under the question
        table = "\n".join(logsearch.table_lines([record]))
        self.assertNotIn(chr(27), table)

    def test_a_passage_is_cut_to_ninety_characters_unless_the_whole_of_it_is_asked_for(self):
        self.ask("How much notice?", "30 days. [source: notice.md]")
        record = self.load()[0]
        record["raw"]["retrieved"][0]["text"] = "x" * 200 + " the sentence that proves the answer wrong"
        cut = "\n".join(logsearch.show_lines(record))
        self.assertNotIn("proves the answer wrong", cut)
        self.assertIn("~", cut)
        whole = "\n".join(logsearch.show_lines(record, full=True))
        self.assertIn("the sentence that proves the answer wrong", whole)

    def test_a_recent_request_with_no_steps_is_not_called_an_old_line_and_an_error_record_shows_its_time_and_hash(self):
        failed = {"request_id": "ab" * 8, "trace_id": "abababab", "ts": "2026-11-01T10:00:00", "error_class": "RuntimeError", "http_status": 400, "total_ms": 96.752,
                  "spans": [], "question_chars": 31, "question_sha": "0123456789ab"}
        text = "\n".join(logsearch.show_lines(logsearch.normalize(failed, "errors.jsonl", 1, "error")))
        self.assertIn("no steps recorded", text)
        self.assertNotIn("written before Week 11", text)
        self.assertIn("96.752 ms in all", text)
        self.assertIn("31 characters, hash 0123456789ab", text)
        old = "\n".join(logsearch.show_lines(logsearch.normalize(old_line("0a1b2c3d", "2026-09-15T10:00:00", "q?", "a"), "t.jsonl", 1, "trace")))
        self.assertIn("(a line written before Week 11 has none)", old)

    def test_prices_stated_as_zero_are_said_to_be_zero_not_missing(self):
        self.ask("How much notice?", "30 days. [source: notice.md]")
        record = self.load()[0]
        self.assertIn("no price stated", "\n".join(logsearch.show_lines(record)))
        self.assertIn("the prices stated are not above 0", "\n".join(logsearch.show_lines(record, 0.0, 0.0)))
        self.assertEqual(logsearch.no_dollars_reason(None, None), "no price stated")
        self.assertEqual(logsearch.no_dollars_reason(0.0, None), "the prices stated are not above 0")

    def test_a_request_whose_provider_reported_no_tokens_has_unknown_tokens_all_the_way_to_the_report(self):
        reply = fake_response("30 days. [source: notice.md]")
        reply.usage = None
        with mock.patch.object(llm, "_get_client", return_value=FakeClient([reply])):
            pipeline.answer("How much notice?")
        self.ask("How many leave days?", "18 days. [source: leave.md]", prompt_tokens=500, completion_tokens=50)
        records = self.load()
        unknown = next(r for r in records if "notice" in r["question"])
        self.assertEqual((unknown["prompt_tokens"], unknown["completion_tokens"]), (None, None))          # never 0
        report = costreport.per_request(records, 2.0, 10.0)
        self.assertEqual((report["requests"], report["tokens_known"]), (2, 1))
        self.assertEqual(report["prompt_tokens"]["mean"], 500)                                             # the unknown one is not averaged in as zero
        self.assertEqual(report["cost"]["n"], 1)

    def test_a_request_is_shown_with_its_steps_provider_time_apart_from_waiting_tokens_and_cost_at_the_prices_given(self):
        request_id = self.ask("How much notice?", "30 days. [source: notice.md]", prompt_tokens=1000, completion_tokens=100)
        (record,) = self.load()
        text = "\n".join(logsearch.show_lines(record, 2.0, 10.0))
        for needle in (request_id, "How much notice?", "30 days. [source: notice.md]", "cited     notice.md", "embed_query", "search", "generate",
                       "provider", "waited", "1000/100", "$0.003000", "$0 (local)", "3 steps",
                       "1 model call(s), 1000 in / 100 out", "$2 per million input tokens and $10 per million output tokens"):
            self.assertIn(needle, text)
        self.assertRegex(text, r"\d\. cited notice\.md")                                    # the passage the answer cited is marked

    def test_without_prices_it_says_so_and_prints_no_dollars(self):
        self.ask("How much notice?", "30 days. [source: notice.md]")
        text = "\n".join(logsearch.show_lines(self.load()[0]))
        self.assertIn("no price stated", text)
        self.assertIn("no price", text)
        self.assertNotIn("$0.0", text)

    def test_a_request_whose_provider_reported_no_tokens_says_the_totals_are_a_lower_bound(self):
        reply = fake_response("30 days. [source: notice.md]")
        reply.usage = None
        with mock.patch.object(llm, "_get_client", return_value=FakeClient([reply])):
            pipeline.answer("How much notice?")
        text = "\n".join(logsearch.show_lines(self.load()[0], 2.0, 10.0))
        self.assertIn("a lower bound", text)

    def test_a_failed_request_shows_what_failed_and_the_steps_it_finished_but_no_text(self):
        failed = self.failing_request("secret question about salaries")
        record = next(r for r in self.load() if r["id"] == failed)
        text = "\n".join(logsearch.show_lines(record))
        self.assertIn("error RuntimeError (HTTP 400)", text)
        self.assertIn("not logged", text)
        self.assertIn("generate", text)
        self.assertNotIn("secret", text)


class BomTests(unittest.TestCase):
    def test_a_log_saved_with_a_byte_order_mark_still_shows_its_first_line(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        path = os.path.join(folder, "bom.jsonl")
        with open(path, "wb") as handle:
            handle.write(chr(0xFEFF).encode("utf-8") + json.dumps(old_line("0a1b2c3d", "2026-09-15T10:00:00", "first?", "a")).encode("utf-8") + b"\n")            # a byte order mark, the three bytes PowerShell 5 puts first in a file
        records, skipped, _took = logsearch.load([path])
        self.assertEqual((len(records), skipped), (1, 0))


class ScriptTests(LogCase):
    def run_script(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = find_requests.main(list(argv))
        return code, out.getvalue()

    def setUp(self):
        super().setUp()
        self.notice = self.ask("How much notice?", "30 days. [source: notice.md]")
        self.ask("How many leave days?", "18 days. [source: leave.md]")
        self.failing_request("boom")

    def test_the_default_run_reads_both_logs_and_says_how_many_it_scanned_and_how_fast(self):
        code, text = self.run_script("--text", "notice")
        self.assertEqual(code, 0)
        self.assertRegex(text, r"scanned 3 records in \d+ ms")
        self.assertIn("1 matched", text)
        self.assertIn(self.notice[:16], text)
        self.assertIn("--id <id> --show", text)

    def test_an_id_with_show_prints_the_request_in_full(self):
        code, text = self.run_script("--id", self.notice[:8], "--show", "--price-in", "1", "--price-out", "2", "--price-source", "a stated test price")
        self.assertEqual(code, 0)
        self.assertIn("steps", text)
        self.assertIn("prices: a stated test price", text)

    def test_show_refuses_to_print_everything_without_a_narrowing_filter(self):
        code, text = self.run_script("--show")
        self.assertEqual(code, 1)
        self.assertIn("narrow it first", text)

    def test_distinct_answers_replaces_the_list_with_counts(self):
        code, text = self.run_script("--distinct-answers")
        self.assertEqual(code, 0)
        self.assertIn("2 distinct answer(s) among 2 answered requests", text)

    def test_costlier_than_needs_both_prices_stated(self):
        code, text = self.run_script("--costlier-than", "0.001", "--price-in", "1")
        self.assertEqual(code, 1)
        self.assertIn("--price-in and --price-out", text)

    def test_every_malformed_value_is_an_error_line_not_a_traceback(self):
        for argv in (("--answer-regex", "(unclosed"), ("--price-in", "-1"), ("--price-out", "nan", "--costlier-than", "1", "--price-in", "1"),
                     ("--since", "9999-12-31T23:59:59-14:00"), ("--since", "last tuesday"), ("--slower-than", "-5")):
            with self.subTest(argv=argv):
                code, text = self.run_script(*argv)
                self.assertEqual(code, 1)
                self.assertIn("Error:", text)

    def test_a_limit_that_hides_matches_says_so_in_every_view(self):
        for number in range(4):
            self.ask(f"Another question {number}?", "18 days " + "x" * number + ". [source: leave.md]")
        code, text = self.run_script("--distinct-answers", "--limit", "1")
        self.assertIn("rarer answers not shown", text)
        code, text = self.run_script("--text", "Another", "--show", "--limit", "1")
        self.assertIn("older matches not shown", text)

    def test_a_bad_date_or_a_negative_limit_is_an_error_not_a_crash(self):
        self.assertEqual(self.run_script("--since", "last tuesday")[0], 1)
        code, text = self.run_script("--limit", "-1")
        self.assertEqual(code, 1)

    def test_only_the_newest_matches_are_listed_and_the_rest_are_counted(self):
        for number in range(4):
            self.ask(f"Another question {number}?", "18 days. [source: leave.md]")
        code, text = self.run_script("--limit", "2")
        self.assertIn("older matches not shown", text)
        code, text = self.run_script("--limit", "0")
        self.assertNotIn("older matches not shown", text)

    def test_a_synthetic_log_is_labelled_and_a_missing_log_is_an_error(self):
        log = os.path.join(os.path.dirname(self.traces), "drill.jsonl")
        with open(log, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(old_line("aabbccdd", "2026-10-01T09:00:00", "q?", "a"), synthetic=True)) + "\n")
        code, text = self.run_script("--log", log)
        self.assertEqual(code, 0)
        self.assertIn("SYNTHETIC LOG", text)
        code, text = self.run_script("--log", os.path.join(os.path.dirname(self.traces), "none.jsonl"))
        self.assertEqual(code, 1)
        self.assertIn("No log lines found", text)

    def test_a_real_log_is_not_labelled_synthetic(self):
        self.assertNotIn("SYNTHETIC", self.run_script("--text", "notice")[1])
        self.assertNotIn("DRY-RUN", self.run_script("--text", "notice")[1])

    def test_a_dry_run_log_is_labelled_so_dollars_on_it_are_not_read_as_real(self):
        log = os.path.join(os.path.dirname(self.traces), "dry.jsonl")
        with open(log, "w", encoding="utf-8") as handle:
            line = old_line("aabbccdd", "2026-10-01T09:00:00", "q?", "a")
            line["config"]["llm_model_served"] = "scripted-model"
            handle.write(json.dumps(line) + "\n")
        code, text = self.run_script("--log", log, "--id", "aabb", "--show", "--price-in", "1", "--price-out", "2")
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN LOG", text)

    def test_a_log_path_that_is_a_folder_is_an_error_line_without_the_path(self):
        code, text = self.run_script("--log", os.path.dirname(self.traces))
        self.assertEqual(code, 1)
        self.assertIn("is not a log file", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn(str(ROOT), text)

    def test_a_cited_name_that_matches_nothing_lists_the_documents_the_logs_cite(self):
        code, text = self.run_script("--cited", "handbook")
        self.assertEqual(code, 0)
        self.assertIn("0 matched", text)
        self.assertIn("The documents cited in these logs: leave.md, notice.md", text)

    def test_costlier_than_with_prices_of_zero_says_why_nothing_matched(self):
        code, text = self.run_script("--costlier-than", "0", "--price-in", "0", "--price-out", "0")
        self.assertEqual(code, 0)
        self.assertIn("Prices of 0 give every request a cost of $0", text)

    def test_full_prints_the_whole_passage_and_without_it_the_passage_is_cut(self):
        with open(self.traces, encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle.read().splitlines()]
        lines[0]["retrieved"][0]["text"] = "y" * 200 + " the distinguishing sentence"
        with open(self.traces, "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(line) + "\n" for line in lines))
        self.assertNotIn("distinguishing sentence", self.run_script("--id", self.notice[:8], "--show")[1])
        self.assertIn("distinguishing sentence", self.run_script("--id", self.notice[:8], "--show", "--full")[1])

    def test_the_drill_option_reads_the_drills_log_from_the_drill_folder(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        built = drill.generate(seed=2, n=300, days=14, end=datetime(2026, 10, 12, 9), corpus_dir=os.path.join(ROOT, "data", "corpus"))
        drill.write(built, os.path.join(folder, "d1"))
        with mock.patch.object(drill, "DRILL_DIR", folder):
            code, text = self.run_script("--drill", "d1", "--text", "notice", "--distinct-answers")
        self.assertEqual(code, 0, text)
        self.assertIn("SYNTHETIC LOG", text)
        self.assertIn("distinct answer(s)", text)
        with mock.patch.object(drill, "DRILL_DIR", folder):
            self.assertEqual(self.run_script("--drill", "nope")[0], 1)                   # a drill that does not exist is "no log lines", not a crash

    def test_only_the_newest_matches_are_the_ones_kept_by_limit(self):
        ids = [self.ask(f"Another question {number}?", "18 days. [source: leave.md]") for number in range(4)]
        code, text = self.run_script("--text", "Another", "--limit", "2")
        self.assertEqual(code, 0)
        self.assertIn(ids[3][:16], text)
        self.assertIn(ids[2][:16], text)
        self.assertNotIn(ids[1][:16], text)
        self.assertNotIn(ids[0][:16], text)
        code, text = self.run_script("--text", "Another", "--show", "--limit", "2")                 # the same in the view that prints requests in full
        self.assertEqual(code, 0)
        self.assertIn(ids[3], text)
        self.assertIn(ids[2], text)
        self.assertNotIn(ids[1], text)
        self.assertNotIn(ids[0], text)

    def test_the_date_parser_means_a_whole_day_for_until(self):
        self.assertEqual(find_requests.parse_when("2026-10-08"), datetime(2026, 10, 8, 0, 0))
        self.assertEqual(find_requests.parse_when("2026-10-08", end_of_range=True), datetime(2026, 10, 8, 23, 59, 59, 999999))
        self.assertEqual(find_requests.parse_when("2026-10-08 14:30", end_of_range=True), datetime(2026, 10, 8, 14, 30))


if __name__ == "__main__":
    unittest.main()
