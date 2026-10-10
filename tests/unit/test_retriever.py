"""app/rag/retriever.py: dense (Week 3) and hybrid (Week 4) retrieval, with a fake embedder."""
import unittest
from unittest import mock

import _testkit
from _testkit import build_index, chunk, fake_embed, isolated_index, patched_embeddings
from app.config import settings
from app.rag import retriever, store


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))          # fake vectors are unit length


class DenseTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact"))
        self.enterContext(patched_embeddings())
        build_index([
            chunk("leave.md#0", "annual leave is 18 days per year"),
            chunk("notice.md#0", "permanent employees give 30 days written notice"),
            chunk("remote.md#0", "remote work up to three days per week"),
        ])

    def test_closest_chunk_first_with_the_documented_keys(self):
        hits = retriever.retrieve("how many days of annual leave", 2)
        self.assertEqual([h["source"] for h in hits][0], "leave.md")
        self.assertEqual(len(hits), 2)
        for key in ("text", "source", "score"):                                  # the Week 3 contract
            self.assertIn(key, hits[0])
        self.assertEqual(hits[0]["retrievers"], ["dense"])                       # Week 4 extras
        self.assertEqual((hits[0]["dense_rank"], hits[1]["dense_rank"]), (1, 2))
        self.assertEqual(hits[0]["score_kind"], "cosine")
        self.assertGreaterEqual(hits[0]["score"], hits[1]["score"])

    def test_score_is_the_cosine_similarity(self):
        question = "remote work three days"
        hit = retriever.retrieve(question, 1)[0]
        expected = cosine(fake_embed([question])[0], fake_embed([hit["text"]])[0])
        self.assertAlmostEqual(hit["score"], expected, places=3)

    def test_empty_question_or_zero_k_returns_nothing_and_embeds_nothing(self):
        with mock.patch("app.rag.retriever.embed_texts") as embed:
            self.assertEqual(retriever.retrieve("   ", 3), [])
            self.assertEqual(retriever.retrieve(None, 3), [])
            self.assertEqual(retriever.retrieve("leave", 0), [])
            embed.assert_not_called()

    def test_k_larger_than_the_corpus_returns_everything(self):
        self.assertEqual(len(retriever.retrieve("leave", 99)), 3)

    def test_empty_index_returns_nothing(self):
        store.reset_collection()
        self.assertEqual(retriever.retrieve("leave", 3), [])


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact"))
        self.enterContext(patched_embeddings())
        build_index([
            chunk("support.md#0", "Error ERR-4032 means the source connection timed out, retry after 60 seconds"),
            chunk("leave.md#0", "annual leave is 18 days per year"),
            chunk("remote.md#0", "remote work up to three days per week"),
            chunk("menu.md#0", "lunch menu pasta pizza salad"),
        ])

    def test_an_exact_code_is_found_and_tagged_with_both_searches(self):
        hits = retriever.retrieve_hybrid("what does ERR-4032 mean", 2)
        top = hits[0]
        self.assertEqual(top["source"], "support.md")
        self.assertIn("keyword", top["retrievers"])
        self.assertIn("rrf_score", top)
        self.assertIsInstance(top["score"], float)                               # always a cosine, never None

    def test_a_keyword_only_chunk_gets_a_real_cosine_score(self):
        # Each search contributes max(hybrid_candidates, top_k) = 2 candidates here. For the
        # question "zebra common", dense ranks D then E (shared word "common", short chunks) and
        # keyword ranks K then D (the rare word "zebra" outweighs the common one). So K is found
        # by keyword search only, and its score has to be computed rather than read from dense.
        corpus = [
            chunk("d.md#0", "common"),
            chunk("e.md#0", "common beta"),
            chunk("f.md#0", "common gamma"),
            chunk("g.md#0", "common delta"),
            chunk("h.md#0", "common eps"),
            chunk("k.md#0", "zebra one two three four five six seven eight nine"),
            chunk("n.md#0", "unrelated text here"),
        ]
        build_index(corpus)
        question = "zebra common"
        with mock.patch.object(settings, "hybrid_candidates", 1):
            hits = retriever.retrieve_hybrid(question, 2)
        by_source = {h["source"]: h for h in hits}
        self.assertEqual(set(by_source), {"d.md", "k.md"})
        self.assertEqual(by_source["k.md"]["retrievers"], ["keyword"])
        expected = round(cosine(fake_embed([question])[0], fake_embed([corpus[5]["text"]])[0]), 4)
        self.assertAlmostEqual(by_source["k.md"]["score"], expected, places=3)
        self.assertGreater(by_source["k.md"]["score"], 0.0)

    def test_empty_question_returns_nothing(self):
        self.assertEqual(retriever.retrieve_hybrid("", 3), [])
        self.assertEqual(retriever.retrieve_hybrid("leave", 0), [])

    def test_nothing_ingested_returns_nothing(self):
        store.reset_collection()
        _testkit.keyword.invalidate()
        self.assertEqual(retriever.retrieve_hybrid("leave", 3), [])


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact"))
        self.enterContext(patched_embeddings())
        build_index([chunk("leave.md#0", "annual leave is 18 days per year"), chunk("remote.md#0", "remote work three days")])

    def test_mode_picks_the_strategy(self):
        dense = retriever.retrieve_for_mode("leave days", 2, "dense")
        hybrid = retriever.retrieve_for_mode("leave days", 2, "hybrid")
        self.assertNotIn("rrf_score", dense[0])
        self.assertIn("rrf_score", hybrid[0])

    def test_no_mode_uses_the_configured_one(self):
        with mock.patch.object(settings, "retrieval_mode", "hybrid"):
            self.assertIn("rrf_score", retriever.retrieve_for_mode("leave days", 2)[0])
        with mock.patch.object(settings, "retrieval_mode", "dense"):
            self.assertNotIn("rrf_score", retriever.retrieve_for_mode("leave days", 2)[0])

    def test_unknown_mode_is_an_error(self):
        with self.assertRaises(ValueError):
            retriever.retrieve_for_mode("leave", 2, "semantic")

    def test_mode_is_case_and_space_insensitive(self):
        self.assertIn("rrf_score", retriever.retrieve_for_mode("leave days", 2, " Hybrid ")[0])


if __name__ == "__main__":
    unittest.main()
