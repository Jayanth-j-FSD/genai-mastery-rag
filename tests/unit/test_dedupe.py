"""Week 6's one improvement: drop exact-duplicate chunks within a document (DEDUPE_CHUNKS)."""
import os
import tempfile
import unittest
from unittest import mock

import _testkit
from _testkit import isolated_index, patched_embeddings
from app.config import settings
from app.rag import pipeline, retriever, store

BOILERPLATE = "security email policy incident report."
FACT = "security@northwind.example is for incident reports."


def write_docs(directory, docs):
    os.makedirs(directory, exist_ok=True)
    for name, text in docs.items():
        with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
            handle.write(text)


class BuildChunksTests(unittest.TestCase):
    def setUp(self):
        # A chunk size just above one paragraph, so every paragraph becomes its own chunk.
        for patcher in (mock.patch.object(settings, "chunk_size", 60), mock.patch.object(settings, "chunk_overlap", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.doc = {"source": "a.md", "text": "\n\n".join([BOILERPLATE] * 5 + ["The unique fact is 42."])}

    def test_it_is_off_by_default_and_then_nothing_changes(self):
        from app.config import Settings
        self.assertFalse(Settings(_env_file=None).dedupe_chunks)
        with mock.patch.object(settings, "dedupe_chunks", False):
            self.assertEqual(len(pipeline.build_chunks([self.doc])), 6)

    def test_exact_copies_inside_one_document_are_dropped_and_the_first_copy_is_kept(self):
        with mock.patch.object(settings, "dedupe_chunks", True):
            kept = pipeline.build_chunks([self.doc])
        self.assertEqual([c["text"] for c in kept], [BOILERPLATE, "The unique fact is 42."])
        self.assertEqual(kept[0]["chunk_id"], "a.md#0")                      # the first copy, with its original id
        self.assertEqual(len({c["chunk_id"] for c in kept}), len(kept))

    def test_whitespace_differences_do_not_hide_a_duplicate(self):
        doc = {"source": "a.md", "text": "Same   words\nhere.\n\nSame words here.\n\nOther text."}
        # Small enough that no two paragraphs are merged into one chunk (they are 18, 16 and 11 characters).
        with mock.patch.object(settings, "dedupe_chunks", True), mock.patch.object(settings, "chunk_size", 20):
            kept = pipeline.build_chunks([doc])
        self.assertEqual(len(kept), 2)                                         # the second paragraph is the first one reflowed

    def test_the_same_text_in_two_documents_is_kept_in_both(self):
        docs = [{"source": "a.md", "text": BOILERPLATE}, {"source": "b.md", "text": BOILERPLATE}]
        with mock.patch.object(settings, "dedupe_chunks", True):
            self.assertEqual([c["source"] for c in pipeline.build_chunks(docs)], ["a.md", "b.md"])

    def test_different_text_is_never_dropped(self):
        doc = {"source": "a.md", "text": "\n\n".join(f"Paragraph number {i} says something new." for i in range(5))}
        with mock.patch.object(settings, "dedupe_chunks", True):
            self.assertEqual(len(pipeline.build_chunks([doc])), 5)


class IngestTests(unittest.TestCase):
    def setUp(self):
        base = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        corpus = os.path.join(base, "corpus")
        write_docs(corpus, {"handbook.md": "\n\n".join([BOILERPLATE] * 8 + [FACT]), "other.md": "A different document entirely."})
        self.enterContext(isolated_index(corpus_dir=corpus, dense_search="exact", retrieval_mode="dense",
                                         chunk_size=60, chunk_overlap=0, top_k=3))
        self.enterContext(patched_embeddings())

    def test_the_result_reports_how_many_copies_were_dropped_and_the_index_matches(self):
        with mock.patch.object(settings, "dedupe_chunks", False):
            plain = pipeline.ingest()
        self.assertEqual((plain["chunks"], plain["duplicates_dropped"], store.count_chunks()), (10, 0, 10))
        with mock.patch.object(settings, "dedupe_chunks", True):
            deduped = pipeline.ingest()
        self.assertEqual((deduped["chunks"], deduped["duplicates_dropped"], store.count_chunks()), (3, 7, 3))
        self.assertEqual(deduped["per_source"], {"handbook.md": 2, "other.md": 1})

    def test_copies_no_longer_fill_every_slot_so_the_chunk_that_answers_is_found(self):
        question = "security email incident"
        with mock.patch.object(settings, "dedupe_chunks", False):
            pipeline.ingest()
            crowded = retriever.retrieve(question, 3)
        self.assertEqual([c["text"] for c in crowded], [BOILERPLATE] * 3)         # three identical copies, the answer is crowded out
        with mock.patch.object(settings, "dedupe_chunks", True):
            pipeline.ingest()
            fixed = retriever.retrieve(question, 3)
        self.assertEqual(sum(c["text"] == BOILERPLATE for c in fixed), 1)         # one copy at most
        self.assertIn(FACT, [c["text"] for c in fixed])                           # and the answer now reaches the model


if __name__ == "__main__":
    unittest.main()
