"""Week 11, the improvement: take the lines a document repeats out of what the model is shown (CONTEXT_STRIP_MIN_REPEATS)."""
import hashlib
import json
import unittest
from unittest import mock

from _testkit import build_index, fake_response, isolated_index, patched_embeddings
from app import observability
from app.config import Settings, settings
from app.rag import generator, pipeline, store
from app.tracing import read_traces
from evals import runner

BLOCK = ["Northstar maintains this policy to provide consistent expectations.",
         "- Requests should normally be submitted through the employee portal.",
         "- The company may periodically review this rule."]
FACT = "- The standard probation period is 6 months."
OTHER_FACT = "- Casual leave is 6 days per calendar year."


def handbook_chunks(sections=12):
    """Twelve chunks of one document, each a heading, the same three boilerplate lines and, in two of them, a real fact."""
    chunks = []
    for number in range(sections):
        lines = [f"## Section {number}", *BLOCK]
        if number == 3:
            lines.append(FACT)
        if number == 7:
            lines.append(OTHER_FACT)
        chunks.append({"chunk_id": f"handbook.md#{number}", "source": "handbook.md", "text": "\n".join(lines)})
    return chunks


SMALL = [{"chunk_id": "policy.md#0", "source": "policy.md",
          "text": "## Notice\n" + BLOCK[0] + "\n- A permanent employee gives 30 days of written notice."}]


class LineRuleTests(unittest.TestCase):
    def test_a_line_counts_when_it_occurs_the_minimum_number_of_times_and_not_before(self):
        texts = ["a\nb", "a\nc", "a\nb"]
        self.assertEqual(generator.repeated_lines(texts, 3), {"a"})
        self.assertEqual(generator.repeated_lines(texts, 2), {"a", "b"})
        self.assertEqual(generator.repeated_lines(texts, 4), set())

    def test_spacing_does_not_make_two_copies_different_lines(self):
        self.assertEqual(generator.repeated_lines(["same  line", "same line", "  same line  "], 3), {"same line"})

    def test_a_heading_is_never_a_repeated_line_however_often_it_repeats(self):
        self.assertEqual(generator.repeated_lines(["# Same"] * 20 + ["body"] * 20, 5), {"body"})

    def test_blank_lines_are_never_counted(self):
        self.assertEqual(generator.repeated_lines(["\n\n\n\n\n\n"], 2), set())

    def test_removing_lines_keeps_everything_else_exactly_as_it_was(self):
        text = "keep one\n\nboiler\nkeep two\n  boiler  \n"
        self.assertEqual(generator.remove_lines(text, {"boiler"}), "keep one\n\nkeep two")

    def test_it_is_the_same_rule_the_index_side_strip_applies_to_a_whole_document(self):
        text = "\n".join(["## S", *BLOCK, "- fact"] * 11 + ["## Last", "- the one real fact"])
        for threshold in (2, 5, 11, 12):
            with self.subTest(threshold=threshold):
                self.assertEqual(generator.remove_lines(text, generator.repeated_lines([text], threshold)),
                                 pipeline.strip_repeated_lines(text, threshold))


class StripContextTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact", retrieval_mode="dense", top_k=4))
        self.enterContext(patched_embeddings())
        build_index(handbook_chunks() + SMALL)
        generator.forget_repeated_lines()

    def test_lines_repeated_in_the_document_come_out_and_the_facts_stay(self):
        chunks = [dict(c) for c in handbook_chunks() if c["chunk_id"].endswith(("#3", "#7"))]
        shown, removed = generator.strip_context(chunks, 10)
        text = "\n".join(c["text"] for c in shown)
        for line in BLOCK:
            self.assertNotIn(line, text)
        self.assertIn(FACT, text)
        self.assertIn(OTHER_FACT, text)
        self.assertIn("## Section 3", text)                         # headings stay: a passage still says what it is about
        self.assertEqual(removed, sum(len(c["text"]) for c in chunks) - sum(len(c["text"]) for c in shown))

    def test_a_chunk_with_nothing_left_is_dropped(self):
        pure = {"chunk_id": "handbook.md#0", "source": "handbook.md", "text": "\n".join(BLOCK)}
        shown, removed = generator.strip_context([pure], 10)
        self.assertEqual((shown, removed), ([], len(pure["text"])))

    def test_a_line_is_counted_in_its_own_document_only(self):
        # The boilerplate sentence also sits once in policy.md, which repeats nothing, so there it must stay.
        shown, removed = generator.strip_context([dict(SMALL[0])], 10)
        self.assertEqual((shown[0]["text"], removed), (SMALL[0]["text"], 0))

    def test_the_chunks_it_was_given_are_not_changed(self):
        chunks = [dict(c) for c in handbook_chunks()[:2]]
        before = json.dumps(chunks)
        generator.strip_context(chunks, 10)
        self.assertEqual(json.dumps(chunks), before)

    def test_nothing_is_stripped_when_no_line_repeats_enough(self):
        shown, removed = generator.strip_context([dict(c) for c in handbook_chunks()[:3]], 13)
        self.assertEqual(removed, 0)
        self.assertEqual([c["text"] for c in shown], [c["text"] for c in handbook_chunks()[:3]])

    def test_the_lines_are_counted_once_per_index_not_once_per_request(self):
        chunks = [dict(c) for c in handbook_chunks()[:2]]
        with mock.patch.object(store, "get_all_chunks", wraps=store.get_all_chunks) as spy:
            generator.strip_context(chunks, 10)
            generator.strip_context(chunks, 10)
        self.assertEqual(spy.call_count, 1)
        with mock.patch.object(store, "get_all_chunks", wraps=store.get_all_chunks) as spy:
            generator.strip_context(chunks, 5)                       # a different threshold is a different count
        self.assertEqual(spy.call_count, 1)

    def test_a_rebuilt_index_is_counted_again(self):
        chunks = [dict(c) for c in handbook_chunks()[:2]]
        generator.strip_context(chunks, 10)
        with mock.patch.object(store, "get_all_chunks", wraps=store.get_all_chunks) as spy:
            generator.forget_repeated_lines()                         # what pipeline.ingest() calls
            generator.strip_context(chunks, 10)
        self.assertEqual(spy.call_count, 1)


class PromptTests(unittest.TestCase):
    """What the model is really sent, with the setting off and on."""

    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact", retrieval_mode="dense", top_k=4))
        self.enterContext(patched_embeddings())
        self.enterContext(mock.patch.object(settings, "llm_rpm", 0))
        self.enterContext(mock.patch.object(settings, "min_relevance", 0.0))
        build_index(handbook_chunks() + SMALL)
        generator.forget_repeated_lines()
        self.chunks = [dict(c, score=0.5) for c in handbook_chunks() if c["chunk_id"].endswith(("#2", "#3"))]

    def prompt_of(self, chat):
        return chat.call_args.args[0][1]["content"]

    def test_off_by_default_so_the_prompt_is_exactly_what_it_was(self):
        self.assertEqual(Settings(_env_file=None).context_strip_min_repeats, 0)
        with mock.patch("app.llm.chat", return_value=fake_response("6 months. [source: handbook.md]")) as chat:
            generator.generate_answer("What is the probation period?", self.chunks)
        expected = "\n\n".join(f"[source: {c['source']}]\n{c['text']}" for c in self.chunks)
        self.assertEqual(self.prompt_of(chat), f"Context passages:\n{expected}\n\nQuestion: What is the probation period?")

    def test_on_the_model_is_not_shown_the_repeated_lines_but_is_shown_the_fact(self):
        with mock.patch.object(settings, "context_strip_min_repeats", 10), \
                mock.patch("app.llm.chat", return_value=fake_response("6 months. [source: handbook.md]")) as chat:
            answer, sources, grounded = generator.generate_answer("What is the probation period?", self.chunks)
        prompt = self.prompt_of(chat)
        for line in BLOCK:
            self.assertNotIn(line, prompt)
        self.assertIn(FACT, prompt)
        self.assertIn("[source: handbook.md]", prompt)
        self.assertEqual((grounded, [s.document for s in sources]), (True, ["handbook.md"]))

    def test_on_the_prompt_is_shorter_by_the_characters_it_says_it_removed(self):
        with mock.patch("app.llm.chat", return_value=fake_response("ok [source: handbook.md]")) as chat:
            generator.generate_answer("q?", self.chunks)
        off = len(self.prompt_of(chat))
        with mock.patch.object(settings, "context_strip_min_repeats", 10), \
                mock.patch("app.llm.chat", return_value=fake_response("ok [source: handbook.md]")) as chat:
            with observability.begin_request() as request:
                generator.generate_answer("q?", self.chunks)
        on = len(self.prompt_of(chat))
        stripped = request.notes["chars"]["stripped"]
        self.assertGreater(stripped, 0)
        self.assertEqual(off - on, stripped)                          # the log's figure is the real saving, character for character
        self.assertEqual(request.notes["chars"]["context"], on - len("Context passages:\n") - len("\n\nQuestion: q?"))

    def test_when_nothing_but_repeated_lines_is_left_it_refuses_without_asking_the_model(self):
        only_boilerplate = [dict(handbook_chunks()[0], text="\n".join(BLOCK), score=0.5)]
        with mock.patch.object(settings, "context_strip_min_repeats", 10), mock.patch("app.llm.chat") as chat:
            with observability.begin_request() as request:
                answer, sources, grounded = generator.generate_answer("q?", only_boilerplate)
        chat.assert_not_called()
        self.assertEqual((answer, sources, grounded), (generator.IDK, [], False))
        self.assertEqual(request.notes["refusal_cause"], "context_all_repeated")
        self.assertGreater(request.notes["chars"]["stripped"], 0)

    def test_the_sources_listed_are_documents_the_model_was_actually_shown(self):
        mixed = [dict(handbook_chunks()[0], text="\n".join(BLOCK), score=0.9), dict(SMALL[0], score=0.4)]
        with mock.patch.object(settings, "context_strip_min_repeats", 10), \
                mock.patch("app.llm.chat", return_value=fake_response("30 days.")) as chat:
            answer, sources, grounded = generator.generate_answer("How much notice?", mixed)
        self.assertNotIn("handbook.md", self.prompt_of(chat))        # that chunk was only boilerplate, so it was not sent
        self.assertEqual([s.document for s in sources], ["policy.md"])   # and it is not offered as a source either

    def test_the_trace_of_a_real_request_says_how_much_was_stripped(self):
        with mock.patch.object(settings, "context_strip_min_repeats", 10), mock.patch.object(settings, "top_k", 4), \
                mock.patch("app.llm.chat", return_value=fake_response("6 months. [source: handbook.md]")):
            pipeline.answer("standard probation period months")
        line = read_traces()[-1]
        self.assertGreater(line["chars"]["stripped"], 0)
        self.assertEqual(line["status"], "ok")


class SettingTests(unittest.TestCase):
    def test_zero_is_off_two_or_more_is_a_threshold_and_one_or_less_is_a_mistake(self):
        self.assertEqual(Settings(_env_file=None, context_strip_min_repeats=0).context_strip_min_repeats, 0)
        self.assertEqual(Settings(_env_file=None, context_strip_min_repeats=2).context_strip_min_repeats, 2)
        for bad in (1, -1, -10):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                Settings(_env_file=None, context_strip_min_repeats=bad)

    def test_the_eval_runner_can_override_it_like_any_other_setting(self):
        overrides = runner.parse_overrides(["context_strip_min_repeats=10"])
        self.assertEqual(overrides, {"context_strip_min_repeats": 10})
        with runner.overridden(overrides):
            self.assertEqual(settings.context_strip_min_repeats, 10)
        self.assertEqual(settings.context_strip_min_repeats, 0)


class EvalCacheKeyTests(unittest.TestCase):
    """An answer cached for the full context must never be served for a stripped one, and the old keys must stay valid."""

    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact", retrieval_mode="dense", top_k=4))
        self.enterContext(patched_embeddings())
        build_index(handbook_chunks() + SMALL)
        generator.forget_repeated_lines()
        self.chunks = [dict(c, score=0.5) for c in handbook_chunks() if c["chunk_id"].endswith(("#2", "#3"))]
        self.enterContext(mock.patch.object(settings, "min_relevance", 0.0))

    def old_key(self, question, chunks):
        parts = [settings.llm_model, generator.SYSTEM_PROMPT, question, [(c["source"], c["text"]) for c in chunks]]
        return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()

    def test_with_the_strip_off_the_key_is_exactly_what_it_was_before_week_11(self):
        self.assertEqual(runner._answer_key("q?", self.chunks), self.old_key("q?", self.chunks))

    def test_with_the_strip_on_the_key_is_a_different_one(self):
        off = runner._answer_key("q?", self.chunks)
        with mock.patch.object(settings, "context_strip_min_repeats", 10):
            on = runner._answer_key("q?", self.chunks)
        self.assertNotEqual(on, off)

    def test_the_key_changes_when_the_same_passages_would_be_shown_differently(self):
        with mock.patch.object(settings, "context_strip_min_repeats", 10):
            many = runner._answer_key("q?", self.chunks)              # the boilerplate repeats 12 times in this index, so it is taken out
            build_index(handbook_chunks(sections=4) + SMALL)           # an index where it repeats only 4 times, so nothing is
            generator.forget_repeated_lines()
            few = runner._answer_key("q?", self.chunks)
        self.assertNotEqual(many, few)

    def test_the_key_follows_what_the_model_is_shown_so_a_different_threshold_is_a_different_key(self):
        with mock.patch.object(settings, "context_strip_min_repeats", 10):
            ten = runner._answer_key("q?", self.chunks)
        with mock.patch.object(settings, "context_strip_min_repeats", 13):       # 12 sections, so nothing repeats 13 times
            thirteen = runner._answer_key("q?", self.chunks)
        self.assertNotEqual(ten, thirteen)


if __name__ == "__main__":
    unittest.main()
