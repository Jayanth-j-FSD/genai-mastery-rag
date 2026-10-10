"""Week 6: the one-table view of every saved run (evals.report.format_runs, scripts/list_runs.py)."""
import unittest

import _testkit  # noqa: F401  (puts the project root on sys.path)
from evals import report


def run(label, overrides, outcomes, chunks=432):
    """A saved run with one case per outcome: (passed the rules, judge verdict or None)."""
    cases = [{"id": f"c{i}", "problem_type": "t", "passed": passed, "checks": [], "judge": ({"verdict": verdict} if verdict else None)}
             for i, (passed, verdict) in enumerate(outcomes)]
    return {"meta": {"label": label, "overrides": overrides, "chunk_count": chunks}, "cases": cases}


BASELINE = run("baseline", {}, [(True, "pass"), (True, "pass"), (False, "fail"), (True, "pass")])
CHANGED = run("wide", {"retrieval_mode": "hybrid", "top_k": 6}, [(True, "pass"), (True, "pass"), (True, "pass"), (True, "fail")], chunks=34)


class FormatRunsTests(unittest.TestCase):
    def test_a_plain_table_has_one_row_per_run_with_case_counts(self):
        lines = report.format_runs([BASELINE, CHANGED])
        self.assertEqual(len(lines), 3)
        baseline_cells, changed_cells = lines[1].split(), lines[2].split()
        self.assertEqual(baseline_cells[0], "baseline")
        self.assertEqual(baseline_cells[-3:], ["3/4", "3/4", "3/4"])         # rules, judge, both
        self.assertEqual(changed_cells[-3:], ["4/4", "3/4", "3/4"])          # passed every rule, judge failed one, so both = 3

    def test_the_baseline_says_nothing_was_changed(self):
        self.assertIn("nothing", report.format_runs([BASELINE])[1])

    def test_the_changed_settings_are_listed(self):
        self.assertIn("retrieval_mode=hybrid, top_k=6", report.format_runs([CHANGED])[1])

    def test_markdown_output_is_a_table(self):
        lines = report.format_runs([BASELINE, CHANGED], markdown=True)
        self.assertTrue(lines[0].startswith("| run |"))
        self.assertEqual(lines[1], "|---|---|---|---|---|---|")
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(line.startswith("|") and line.endswith("|") for line in lines))

    def test_a_run_without_the_judge_says_so_and_both_equals_rules(self):
        unjudged = run("fast", {}, [(True, None), (False, None)])
        cells = report.format_runs([unjudged])[1]
        self.assertIn("not run", cells)
        self.assertTrue(cells.rstrip().endswith("1/2"))

    def test_chunk_counts_are_shown(self):
        self.assertIn("34", report.format_runs([CHANGED])[1])


if __name__ == "__main__":
    unittest.main()
