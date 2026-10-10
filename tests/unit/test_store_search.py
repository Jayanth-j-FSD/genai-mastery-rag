"""app/rag/store.py: exact search must be exact and deterministic (the R-10 fix)."""
import unittest
from unittest import mock

import numpy as np

import _testkit
from _testkit import build_index, chunk, fake_embed, isolated_index
from app.config import settings
from app.rag import store


class ExactSearchTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact"))

    def test_nearest_chunk_comes_first_with_cosine_distance(self):
        build_index([chunk("a#0", "alpha beta gamma"), chunk("b#0", "delta epsilon zeta"), chunk("c#0", "alpha beta delta")])
        result = store.query(fake_embed(["alpha beta gamma"])[0], 3)
        self.assertEqual(result["ids"][0][0], "a#0")
        self.assertAlmostEqual(result["distances"][0][0], 0.0, places=5)      # identical text: distance 0
        self.assertEqual(result["distances"][0], sorted(result["distances"][0]))

    def test_result_has_the_shape_the_retriever_reads(self):
        build_index([chunk("a#0", "alpha beta"), chunk("b#0", "gamma delta")])
        result = store.query(fake_embed(["alpha"])[0], 2)
        for key in ("ids", "documents", "metadatas", "distances"):
            self.assertEqual(len(result[key]), 1)                              # one list per query
            self.assertEqual(len(result[key][0]), 2)
        self.assertEqual(result["metadatas"][0][0], {"source": "a"})
        self.assertEqual(result["documents"][0][0], "alpha beta")

    def test_equal_scores_are_ordered_by_id_not_by_insertion(self):
        build_index([chunk("b#0", "same words here"), chunk("a#0", "same words here"), chunk("c#0", "unrelated")])
        vector = fake_embed(["same words here"])[0]
        self.assertEqual(store.query(vector, 2)["ids"][0], ["a#0", "b#0"])
        self.assertEqual(store.query(vector, 2)["ids"][0], ["a#0", "b#0"])      # and repeatably

    def test_top_k_larger_than_the_corpus_returns_everything(self):
        build_index([chunk("a#0", "one"), chunk("b#0", "two")])
        self.assertEqual(len(store.query(fake_embed(["one"])[0], 50)["ids"][0]), 2)

    def test_empty_index_returns_empty_lists(self):
        store.reset_collection()
        result = store.query(fake_embed(["anything"])[0], 3)
        self.assertEqual(result["ids"], [[]])
        self.assertEqual(result["distances"], [[]])

    def test_wrong_vector_size_explains_that_a_re_ingest_is_needed(self):
        build_index([chunk("a#0", "alpha")])
        with self.assertRaises(RuntimeError) as ctx:
            store.query([0.1] * 10, 1)
        self.assertIn("re-ingest", str(ctx.exception).lower())

    def test_matches_brute_force_on_random_vectors(self):
        rng = np.random.default_rng(7)
        vectors = rng.normal(size=(200, 32))
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        store.reset_collection()
        store.add_chunks([chunk(f"d{i:03d}#0", f"text {i}") for i in range(200)], vectors.tolist())
        for query in rng.normal(size=(20, 32)):
            query /= np.linalg.norm(query)
            expected = [f"d{i:03d}#0" for i in np.argsort(1 - vectors @ query)[:5]]
            self.assertEqual(store.query(query.tolist(), 5)["ids"][0], expected)

    def test_vectors_that_are_not_unit_length_are_still_compared_by_angle(self):
        store.reset_collection()
        store.add_chunks([chunk("a#0", "x"), chunk("b#0", "y")], [[10.0, 0.0], [0.0, 0.5]])
        result = store.query([0.0, 3.0], 2)
        self.assertEqual(result["ids"][0], ["b#0", "a#0"])
        self.assertAlmostEqual(result["distances"][0][0], 0.0, places=5)


class AnnSwitchTests(unittest.TestCase):
    def test_ann_setting_still_uses_chromas_own_index(self):
        with isolated_index(dense_search="ann"):
            build_index([chunk("a#0", "alpha beta"), chunk("b#0", "gamma delta")])
            result = store.query(fake_embed(["alpha beta"])[0], 2)
            self.assertEqual(result["ids"][0][0], "a#0")
            self.assertEqual(len(result["distances"][0]), 2)

    def test_default_setting_is_exact(self):
        from app.config import Settings
        self.assertEqual(Settings(_env_file=None).dense_search, "exact")


if __name__ == "__main__":
    unittest.main()
