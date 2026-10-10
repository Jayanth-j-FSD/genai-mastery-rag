"""Week 4 pieces: BM25 keyword search and Reciprocal Rank Fusion."""
import unittest
from unittest import mock

import _testkit
from app.config import settings
from app.rag import fusion, keyword


def docs(*texts):
    return [{"chunk_id": f"d{i}#0", "text": text, "source": f"d{i}.md"} for i, text in enumerate(texts)]


class TokenizeTests(unittest.TestCase):
    def test_compound_codes_keep_the_whole_and_the_parts(self):
        self.assertEqual(keyword.tokenize("ERR-4032"), ["err-4032", "err", "4032"])

    def test_path_like_words_split_on_slash_and_dot(self):
        tokens = keyword.tokenize("Settings/Connections")
        self.assertIn("settings/connections", tokens)
        self.assertIn("settings", tokens)

    def test_lowercases_and_drops_punctuation(self):
        self.assertEqual(keyword.tokenize("Hello, World!"), ["hello", "world"])

    def test_none_and_empty_give_no_tokens(self):
        self.assertEqual(keyword.tokenize(None), [])
        self.assertEqual(keyword.tokenize(""), [])


class Bm25Tests(unittest.TestCase):
    def test_the_chunk_with_the_rare_exact_code_ranks_first(self):
        index = keyword.Bm25Index(docs(
            "meals are limited to forty dollars per day",
            "Error ERR-4032 means the source connection timed out",
            "reset links are valid for thirty minutes",
        ))
        hits = index.search("what is ERR-4032", 3)
        self.assertEqual(hits[0]["chunk_id"], "d1#0")
        self.assertGreater(hits[0]["keyword_score"], 0)

    def test_chunks_sharing_no_word_are_left_out_not_scored_zero(self):
        index = keyword.Bm25Index(docs("alpha beta", "gamma delta"))
        self.assertEqual([h["chunk_id"] for h in index.search("alpha", 5)], ["d0#0"])

    def test_empty_question_empty_index_and_zero_k_return_nothing(self):
        index = keyword.Bm25Index(docs("alpha beta"))
        self.assertEqual(index.search("", 3), [])
        self.assertEqual(index.search("alpha", 0), [])
        self.assertEqual(keyword.Bm25Index([]).search("alpha", 3), [])

    def test_common_words_never_push_a_score_below_zero(self):
        index = keyword.Bm25Index(docs("the the the", "the cat", "the dog", "the bird"))
        for hit in index.search("the", 4):
            self.assertGreater(hit["keyword_score"], 0)

    def test_equal_scores_keep_chunk_order(self):
        index = keyword.Bm25Index(docs("same words", "same words", "same words"))
        self.assertEqual([h["chunk_id"] for h in index.search("same", 3)], ["d0#0", "d1#0", "d2#0"])

    def test_a_repeated_word_helps_but_saturates(self):
        index = keyword.Bm25Index(docs("zebra", "zebra zebra", "zebra " * 40 + "filler", "other text here"))
        scores = {h["chunk_id"]: h["keyword_score"] for h in index.search("zebra", 4)}
        self.assertGreater(scores["d1#0"], 0)
        self.assertLess(scores["d2#0"], scores["d0#0"] * 3)             # 40x the repeats is not 40x the score

    def test_k1_and_b_come_from_settings(self):
        index = keyword.Bm25Index(docs("zebra " + "word " * 30, "zebra", "other"))
        with mock.patch.object(settings, "bm25_b", 0.0):
            flat = {h["chunk_id"]: h["keyword_score"] for h in index.search("zebra", 3)}
        with mock.patch.object(settings, "bm25_b", 1.0):
            normalised = {h["chunk_id"]: h["keyword_score"] for h in index.search("zebra", 3)}
        self.assertGreater(flat["d0#0"], normalised["d0#0"])            # b=1 penalises the long chunk more


class CacheTests(unittest.TestCase):
    def test_index_rebuilds_when_the_chunk_count_changes(self):
        with _testkit.isolated_index():
            _testkit.build_index([_testkit.chunk("a#0", "alpha one")])
            self.assertEqual(len(keyword.search("alpha", 5)), 1)
            _testkit.build_index([_testkit.chunk("a#0", "alpha one"), _testkit.chunk("b#0", "alpha two")])
            self.assertEqual(len(keyword.search("alpha", 5)), 2)

    def test_nothing_ingested_gives_an_empty_result(self):
        with _testkit.isolated_index():
            self.assertEqual(keyword.search("alpha", 5), [])


class FusionTests(unittest.TestCase):
    def test_a_chunk_found_by_both_searches_wins(self):
        fused = fusion.fuse({"dense": ["a", "b"], "keyword": ["b", "c"]}, 60)
        self.assertEqual([f["key"] for f in fused], ["b", "a", "c"])
        self.assertAlmostEqual(fused[0]["rrf_score"], 1 / 62 + 1 / 61, places=5)
        self.assertEqual(fused[0]["ranks"], {"dense": 2, "keyword": 1})

    def test_a_key_repeated_inside_one_list_counts_once(self):
        fused = fusion.fuse({"dense": ["a", "a", "a"]}, 60)
        self.assertEqual(len(fused), 1)
        self.assertAlmostEqual(fused[0]["rrf_score"], 1 / 61, places=5)

    def test_ties_break_by_best_rank_then_key(self):
        fused = fusion.fuse({"dense": ["x"], "keyword": ["y"]}, 60)
        self.assertEqual([f["key"] for f in fused], ["x", "y"])         # same score, same rank, key order

    def test_negative_k_is_clamped_instead_of_dividing_by_zero(self):
        fused = fusion.fuse({"dense": ["a"]}, -5)
        self.assertAlmostEqual(fused[0]["rrf_score"], 1.0, places=5)

    def test_empty_and_blank_inputs(self):
        self.assertEqual(fusion.fuse({}, 60), [])
        self.assertEqual(fusion.fuse(None, 60), [])
        self.assertEqual(fusion.fuse({"dense": ["", None, "a"]}, 60)[0]["key"], "a")

    def test_the_same_input_always_gives_the_same_order(self):
        lists = {"dense": ["c", "a", "b"], "keyword": ["b", "c", "a"]}
        self.assertEqual(fusion.fuse(lists, 60), fusion.fuse(lists, 60))


if __name__ == "__main__":
    unittest.main()
