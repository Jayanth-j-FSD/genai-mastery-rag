"""Week 6, experiment 2: strip lines repeated many times inside one document (BOILERPLATE_MIN_REPEATS)."""
import os
import tempfile
import unittest
from unittest import mock

import _testkit
from _testkit import isolated_index, patched_embeddings
from app.config import Settings, settings
from app.rag import pipeline, retriever, store

BLOCK = ["Northstar maintains this policy to provide consistent expectations.",
         "- Requests should normally be submitted through the employee portal.",
         "- The company may periodically review this rule."]
# Boilerplate that happens to use the words of one question, which is what crowds the real answer out.
QUESTION = "security incident report email"
CROWDING_BLOCK = ["Security incident report email procedure: report any security incident by email.",
                  "Security incident report email: the standard security incident report email form."]


def handbook(sections, facts):
    """A document shaped like the real handbook: every section is a heading, the same boilerplate block, then
    (for some) one real fact. facts: {section number: sentence}."""
    parts = ["# Handbook"]
    for number in range(sections):
        parts.append(f"## Section {number}")
        parts.extend(BLOCK)
        if number in facts:
            parts.append(f"- {facts[number]}")
    return "\n".join(parts)


class StripRepeatedLinesTests(unittest.TestCase):
    def test_lines_repeated_enough_are_removed_everywhere(self):
        text = handbook(12, {3: "The probation period is 6 months."})
        stripped = pipeline.strip_repeated_lines(text, 10)
        for line in BLOCK:
            self.assertNotIn(line, stripped)
        self.assertIn("The probation period is 6 months.", stripped)

    def test_headings_stay_even_when_they_repeat(self):
        text = "\n".join(["## Same heading", "boilerplate line"] * 12 + ["- a real fact"])
        stripped = pipeline.strip_repeated_lines(text, 5)
        self.assertEqual(stripped.count("## Same heading"), 12)
        self.assertNotIn("boilerplate line", stripped)
        self.assertIn("- a real fact", stripped)

    def test_lines_repeated_fewer_times_than_the_threshold_are_kept(self):
        text = "\n".join(["repeated twice", "repeated twice", "unique"])
        self.assertEqual(pipeline.strip_repeated_lines(text, 3), text)

    def test_whitespace_differences_do_not_hide_a_repeat(self):
        text = "\n".join(["same  words   here"] * 3 + ["  same words here  "] * 3 + ["keep me"])
        self.assertEqual(pipeline.strip_repeated_lines(text, 6).strip(), "keep me")

    def test_blank_lines_never_count_as_repeats_and_survive(self):
        text = "a\n\n\n\nb\n\n\nc"
        self.assertEqual(pipeline.strip_repeated_lines(text, 2), text)

    def test_empty_text(self):
        self.assertEqual(pipeline.strip_repeated_lines("", 3), "")


class SettingTests(unittest.TestCase):
    def test_it_is_off_by_default(self):
        self.assertEqual(Settings(_env_file=None).boilerplate_min_repeats, 0)

    def test_zero_or_at_least_two_is_valid_and_one_is_a_mistake(self):
        from pydantic import ValidationError
        self.assertEqual(Settings(_env_file=None, boilerplate_min_repeats=10).boilerplate_min_repeats, 10)
        self.assertEqual(Settings(_env_file=None, boilerplate_min_repeats=2).boilerplate_min_repeats, 2)
        for bad in (1, -3):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                Settings(_env_file=None, boilerplate_min_repeats=bad)


class BuildChunksTests(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(settings, "chunk_size", 300), mock.patch.object(settings, "chunk_overlap", 30)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.docs = [{"source": "handbook.md", "text": handbook(40, {7: "The probation period is 6 months."})},
                     {"source": "policy.md", "text": "Security incidents go to security@northwind.example within 1 hour."}]

    def test_the_boilerplate_dominated_document_collapses_to_its_real_content(self):
        with mock.patch.object(settings, "boilerplate_min_repeats", 0):
            plain = pipeline.build_chunks(self.docs)
        with mock.patch.object(settings, "boilerplate_min_repeats", 10):
            cleaned = pipeline.build_chunks(self.docs)
        self.assertGreater(len(plain), 20)
        self.assertLess(len(cleaned), 10)
        self.assertTrue(any("probation period is 6 months" in c["text"] for c in cleaned))
        self.assertFalse(any("maintains this policy" in c["text"] for c in cleaned))
        self.assertTrue(any(c["source"] == "policy.md" for c in cleaned))                # other documents are untouched

    def test_a_document_that_is_all_boilerplate_disappears_instead_of_leaving_an_empty_chunk(self):
        only = [{"source": "filler.md", "text": "\n".join(["same line"] * 20)}, self.docs[1]]
        with mock.patch.object(settings, "boilerplate_min_repeats", 5):
            self.assertEqual({c["source"] for c in pipeline.build_chunks(only)}, {"policy.md"})

    def test_the_original_documents_are_not_modified(self):
        before = [dict(d) for d in self.docs]
        with mock.patch.object(settings, "boilerplate_min_repeats", 10):
            pipeline.build_chunks(self.docs)
        self.assertEqual(self.docs, before)

    def test_it_composes_with_exact_duplicate_removal(self):
        # A paragraph that appears only twice is below the stripping threshold, so only the exact-duplicate
        # step can remove its second copy.
        twice = "A paragraph that appears exactly two times in this document, written out once more further below."
        docs = [{"source": "d.md", "text": "\n\n".join([twice, "Some other paragraph here.", twice])}]
        with mock.patch.object(settings, "chunk_size", 100), mock.patch.object(settings, "chunk_overlap", 0), \
                mock.patch.object(settings, "boilerplate_min_repeats", 10):
            with mock.patch.object(settings, "dedupe_chunks", False):
                one = pipeline.build_chunks(docs)
            with mock.patch.object(settings, "dedupe_chunks", True):
                both = pipeline.build_chunks(docs)
        self.assertEqual((len(one), len(both)), (3, 2))


class RetrievalTests(unittest.TestCase):
    """The mechanism itself: near-duplicate chunks fill every slot until the boilerplate is gone."""

    def setUp(self):
        base = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        corpus = os.path.join(base, "corpus")
        os.makedirs(corpus)
        with open(os.path.join(corpus, "handbook.md"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(["# Handbook"] + [f"## Security {n}\n" + "\n".join(CROWDING_BLOCK) for n in range(30)]))
        with open(os.path.join(corpus, "security-policy.md"), "w", encoding="utf-8") as handle:
            handle.write("Report a security incident to security@northwind.example within 1 hour.")
        self.enterContext(isolated_index(corpus_dir=corpus, dense_search="exact", retrieval_mode="dense",
                                         chunk_size=200, chunk_overlap=0, top_k=3))
        self.enterContext(patched_embeddings())

    def test_the_right_document_is_crowded_out_before_cleaning_and_found_after(self):
        question = QUESTION
        with mock.patch.object(settings, "boilerplate_min_repeats", 0):
            pipeline.ingest()
            crowded = retriever.retrieve(question, 3)
        self.assertEqual({c["source"] for c in crowded}, {"handbook.md"})                 # near-duplicates fill every slot
        with mock.patch.object(settings, "boilerplate_min_repeats", 10):
            pipeline.ingest()
            fixed = retriever.retrieve(question, 3)
        self.assertIn("security-policy.md", {c["source"] for c in fixed})


if __name__ == "__main__":
    unittest.main()
