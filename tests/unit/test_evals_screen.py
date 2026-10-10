"""Week 6: the retrieval-only screen (which cases can a retrieval change possibly fix?)."""
import unittest

import _testkit  # noqa: F401  (puts the project root on sys.path)
from evals import screen


def chunk(source, text):
    return {"source": source, "text": text}


CASE = {"id": "c1", "expected_sources": ["policy.md"], "expect_contains": ["1 hour", "incident"], "expect_all": []}


class FirstUsefulRankTests(unittest.TestCase):
    def test_the_first_chunk_from_an_expected_document_with_a_fact_counts(self):
        chunks = [chunk("handbook.md", "nothing useful"), chunk("policy.md", "Report an Incident to security."),
                  chunk("policy.md", "within 1 hour")]
        self.assertEqual(screen.first_useful_rank(chunks, CASE), 2)

    def test_the_right_document_but_the_wrong_section_does_not_count(self):
        chunks = [chunk("policy.md", "Passwords rotate every 90 days."), chunk("policy.md", "Report within 1 hour.")]
        self.assertEqual(screen.first_useful_rank(chunks, CASE), 2)

    def test_a_fact_in_the_wrong_document_does_not_count(self):
        self.assertIsNone(screen.first_useful_rank([chunk("handbook.md", "report an incident in 1 hour")], CASE))

    def test_whitespace_and_case_are_ignored(self):
        self.assertEqual(screen.first_useful_rank([chunk("policy.md", "WITHIN   1  HOUR")], CASE), 1)

    def test_a_case_without_fact_strings_accepts_any_chunk_of_an_expected_document(self):
        bare = {"id": "c2", "expected_sources": ["policy.md"]}
        self.assertEqual(screen.first_useful_rank([chunk("x.md", "a"), chunk("policy.md", "anything")], bare), 2)

    def test_no_chunks_means_no_rank(self):
        self.assertIsNone(screen.first_useful_rank([], CASE))

    def test_expect_all_phrases_count_as_facts_too(self):
        case = {"id": "c3", "expected_sources": ["p.md"], "expect_all": ["Key Vault"], "expect_contains": []}
        self.assertEqual(screen.first_useful_rank([chunk("p.md", "use azure key vault")], case), 1)


class HitCountsTests(unittest.TestCase):
    def test_counts_cases_within_each_k(self):
        ranks = {"a": 1, "b": 4, "c": 5, "d": None, "e": 10}
        self.assertEqual(screen.hit_counts(ranks, (4, 6, 10)), {4: 2, 6: 3, 10: 4})


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.table = {"dense": {"a": 1, "b": None, "c": 7}, "hybrid": {"a": 1, "b": 2, "c": 6}}
        self.lines = screen.format_screen(self.table, (4, 6, 10), {"dense": 432, "hybrid": 432})

    def test_the_summary_rows_show_chunks_and_hits(self):
        dense = next(line for line in self.lines if line.startswith("dense"))
        self.assertIn("432", dense)
        self.assertEqual(dense.split()[-3:], ["1", "1", "2"])           # hits within the top 4, 6 and 10

    def test_cases_outside_the_top_k_are_listed_with_their_ranks(self):
        row_b = next(line for line in self.lines if line.startswith("b "))
        row_c = next(line for line in self.lines if line.startswith("c "))
        self.assertEqual(row_b.split(), ["b", "-", "2"])               # not in the top 10 under dense, 2nd under hybrid
        self.assertEqual(row_c.split(), ["c", "7", "6"])
        table_rows = self.lines[next(i for i, line in enumerate(self.lines) if line.startswith("case ")):]
        self.assertFalse(any(line.startswith("a ") for line in table_rows))     # case a is a hit everywhere, so it is not listed

    def test_nothing_weak_says_so(self):
        lines = screen.format_screen({"dense": {"a": 1}}, (4,), {"dense": 10})
        self.assertIn("(none)", lines)


if __name__ == "__main__":
    unittest.main()
