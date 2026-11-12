"""Week 5 tooling: sampling, the notes gate, grouping and ranking, as one chain."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from app import worksheet
from app.tracing import log_trace

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import ask_batch          # noqa: E402
import code_notes         # noqa: E402
import rank_problems      # noqa: E402
import sample_traces      # noqa: E402


def run(module, *args):
    """Run a script's main() with the given command line. Returns (exit code, printed text)."""
    out = io.StringIO()
    with mock.patch.object(sys, "argv", [module.__name__ + ".py", *args]), contextlib.redirect_stdout(out):
        code = module.main()
    return code, out.getvalue()


def fill(path, verdicts):
    """Write verdicts into a generated worksheet. verdicts: {trace_id: (verdict, note, severity)}."""
    lines = open(path, encoding="utf-8").read().splitlines()
    current, out = None, []
    for line in lines:
        if line.startswith("## trace "):
            current = line.split()[-1]
        if current in verdicts and line.startswith("- verdict:"):
            line = f"- verdict: {verdicts[current][0]}"
        elif current in verdicts and line.startswith("- note:"):
            line = f"- note: {verdicts[current][1]}"
        elif current in verdicts and line.startswith("- severity:"):
            line = f"- severity: {verdicts[current][2]}"
        out.append(line)
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")


class WeekFiveTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(_testkit.isolated_index())
        self.sheet = os.path.join(self.tmp, "worksheet.md")
        self.coded = os.path.join(self.tmp, "coded-notes.md")
        for number in range(12):
            log_trace(f"Question number {number}?", [{"source": "leave.md", "score": 0.5, "text": "t"}],
                      f"Answer {number}", number % 4 != 0)
        self.traces = _testkit.settings.traces_path


class SamplingTests(WeekFiveTestCase):
    def ids(self, path):
        return [b["trace_id"] for b in worksheet.parse(path)[0]]

    def test_the_same_seed_draws_the_same_sample_and_a_new_seed_a_different_one(self):
        run(sample_traces, "--n", "5", "--seed", "42", "--out", self.sheet)
        first = self.ids(self.sheet)
        run(sample_traces, "--n", "5", "--seed", "42", "--out", self.sheet, "--force")
        self.assertEqual(self.ids(self.sheet), first)
        run(sample_traces, "--n", "5", "--seed", "7", "--out", self.sheet, "--force")
        self.assertNotEqual(self.ids(self.sheet), first)

    def test_the_printed_reproduce_command_recreates_the_draw_even_after_more_traces_arrive(self):
        run(sample_traces, "--n", "5", "--seed", "42", "--out", self.sheet)
        original = self.ids(self.sheet)
        for number in range(8):                                   # the app keeps being used
            log_trace(f"Later question {number}?", [], "a", True)
        meta = worksheet.parse(self.sheet)[1]
        check = os.path.join(self.tmp, "worksheet-check.md")
        code, _ = run(sample_traces, "--n", "5", "--seed", meta["seed"], "--upto", meta["population"], "--out", check)
        self.assertEqual(code, 0)
        self.assertEqual(self.ids(check), original)               # same draw, from the same population

    def test_the_reproduce_hint_never_tells_you_to_overwrite_your_notes(self):
        run(sample_traces, "--n", "5", "--out", self.sheet)
        text = open(self.sheet, encoding="utf-8").read()
        hint = next(line for line in text.splitlines() if "Reproduce this exact draw" in line)
        self.assertNotIn("--force", hint)
        self.assertIn("--out", hint)
        self.assertIn("--upto", hint)

    def test_existing_notes_are_never_overwritten_without_force(self):
        run(sample_traces, "--n", "5", "--out", self.sheet)
        with open(self.sheet, "a", encoding="utf-8") as handle:
            handle.write("\nMY HANDWRITTEN NOTE\n")
        code, printed = run(sample_traces, "--n", "5", "--out", self.sheet)
        self.assertEqual(code, 1)
        self.assertIn("already exists", printed)
        self.assertIn("MY HANDWRITTEN NOTE", open(self.sheet, encoding="utf-8").read())

    def test_asking_for_more_than_exist_uses_all_and_says_it_is_a_census(self):
        code, printed = run(sample_traces, "--n", "50", "--out", self.sheet)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.ids(self.sheet)), 12)
        self.assertIn("census", printed)

    def test_bad_arguments_and_an_empty_log_are_refused(self):
        self.assertEqual(run(sample_traces, "--n", "0", "--out", self.sheet)[0], 1)
        self.assertEqual(run(sample_traces, "--n", "3", "--upto", "0", "--out", self.sheet)[0], 1)
        os.remove(self.traces)
        self.assertEqual(run(sample_traces, "--n", "3", "--out", self.sheet)[0], 1)

    def test_an_old_trace_without_an_id_is_filed_under_its_line_number(self):
        with open(self.traces, "w", encoding="utf-8") as handle:
            handle.write('{"question": "old one", "answer": "a", "grounded": true, "retrieved": []}\n')
            handle.write('{"question": "old two", "answer": "b", "grounded": true, "retrieved": []}\n')
        run(sample_traces, "--n", "2", "--out", self.sheet)
        self.assertEqual(sorted(self.ids(self.sheet)), ["line1", "line2"])           # not two blocks named "?"

    def test_a_multi_line_answer_stays_on_one_line_so_the_parser_keeps_all_of_it(self):
        log_trace("Q?", [], "First line\n- bullet one\n- bullet two", True)
        run(sample_traces, "--n", "50", "--out", self.sheet)
        block = [b for b in worksheet.parse(self.sheet)[0] if b["question"] == "Q?"][0]
        self.assertIn("bullet two", block["answer"])


class ChainTests(WeekFiveTestCase):
    def finished_worksheet(self):
        run(sample_traces, "--n", "12", "--out", self.sheet)
        ids = [b["trace_id"] for b in worksheet.parse(self.sheet)[0]]
        verdicts = {ids[0]: ("bad", "refused though the answer was present", "3"),
                    ids[1]: ("bad", "gave the wrong limit", "2"),
                    ids[2]: ("bad", "gave the wrong limit again", "1")}
        verdicts.update({i: ("ok", "", "") for i in ids[3:]})
        fill(self.sheet, verdicts)
        return ids

    def test_the_gate_refuses_until_every_trace_has_a_verdict(self):
        run(sample_traces, "--n", "12", "--out", self.sheet)
        code, printed = run(code_notes, "--in", self.sheet, "--out", self.coded)
        self.assertEqual(code, 1)
        self.assertIn("not finished", printed)
        self.assertFalse(os.path.exists(self.coded))

    def test_a_bad_verdict_needs_a_note_and_a_severity(self):
        ids = self.finished_worksheet()
        fill(self.sheet, {ids[0]: ("bad", "", "")})
        code, printed = run(code_notes, "--in", self.sheet, "--out", self.coded)
        self.assertEqual(code, 1)
        self.assertIn("no note", printed)
        self.assertIn("severity", printed)

    def test_no_failures_means_nothing_to_group(self):
        run(sample_traces, "--n", "12", "--out", self.sheet)
        ids = [b["trace_id"] for b in worksheet.parse(self.sheet)[0]]
        fill(self.sheet, {i: ("ok", "", "") for i in ids})
        code, printed = run(code_notes, "--in", self.sheet, "--out", self.coded)
        self.assertEqual(code, 1)
        self.assertIn("nothing to group", printed)

    def test_failures_are_carried_forward_with_a_blank_code_and_codes_are_not_overwritten(self):
        self.finished_worksheet()
        self.assertEqual(run(code_notes, "--in", self.sheet, "--out", self.coded)[0], 0)
        blocks = worksheet.parse(self.coded)[0]
        self.assertEqual(len(blocks), 3)
        self.assertTrue(all(b["code"] == "" for b in blocks))
        with open(self.coded, "a", encoding="utf-8") as handle:
            handle.write("\nMY CODES\n")
        code, printed = run(code_notes, "--in", self.sheet, "--out", self.coded)
        self.assertEqual(code, 1)
        self.assertIn("already exists", printed)
        self.assertIn("MY CODES", open(self.coded, encoding="utf-8").read())

    def test_missing_input_files_give_a_pointer_not_a_traceback(self):
        code, printed = run(code_notes, "--in", os.path.join(self.tmp, "nope.md"), "--out", self.coded)
        self.assertEqual(code, 1)
        self.assertIn("sample_traces.py", printed)
        code, printed = run(rank_problems, "--in", os.path.join(self.tmp, "nope.md"))
        self.assertEqual(code, 1)
        self.assertIn("code_notes.py", printed)

    def test_ranking_needs_a_code_on_every_failure_then_orders_by_impact(self):
        self.finished_worksheet()
        run(code_notes, "--in", self.sheet, "--out", self.coded)
        code, printed = run(rank_problems, "--in", self.coded)
        self.assertEqual(code, 1)
        self.assertIn("no code", printed)
        blocks = worksheet.parse(self.coded)[0]
        text = open(self.coded, encoding="utf-8").read().replace("- code: \n", "- code: @@\n")
        for block, name in zip(blocks, ["refused-though-present", "wrong-limit", "Wrong Limit"]):
            text = text.replace("- code: @@", f"- code: {name}", 1)
        open(self.coded, "w", encoding="utf-8").write(text)
        out_path = os.path.join(self.tmp, "ranked.md")
        with mock.patch.object(rank_problems, "DEFAULT_OUT", out_path):
            code, printed = run(rank_problems, "--in", self.coded, "--save")
        self.assertEqual(code, 0)
        # "wrong-limit" and "Wrong Limit" are one group (2 failures, severities 2+1=3); the single
        # severity-3 refusal has the same impact, so the more frequent group ranks first.
        self.assertLess(printed.index("wrong-limit"), printed.index("refused-though-present"))
        self.assertIn("Highest impact: wrong-limit (2 occurrence(s), impact 3)", printed)
        self.assertIn("Groups that occurred only once (1): refused-though-present", printed)
        self.assertTrue(os.path.exists(out_path))


class RankHelpersTests(unittest.TestCase):
    def block(self, trace_id, code, severity="2", verdict="bad"):
        return {"trace_id": trace_id, "verdict": verdict, "code": code, "severity": severity,
                "note": "n", "question": "q", "answer": "a", "refused": ""}

    def test_grouping_ignores_case_and_spacing_in_names(self):
        groups = rank_problems._group([self.block("a", "Wrong Doc"), self.block("b", "wrong-doc", "3")])
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]["count"], groups[0]["impact"], groups[0]["worst"]), (2, 5, 3))

    def test_possible_accidental_splits_are_flagged(self):
        groups = rank_problems._group([self.block("a", "wrong-doc"), self.block("b", "wrong-document"),
                                       self.block("c", "refused-answerable")])
        pairs = [(left, right) for left, right, _ in rank_problems._near_duplicates(groups)]
        self.assertIn(("wrong-doc", "wrong-document"), pairs)
        self.assertFalse(any("refused-answerable" in pair for pair in pairs))

    def test_validation_names_every_problem(self):
        problems = rank_problems._validate([self.block("a", ""), self.block("b", "x", "9"),
                                            self.block("c", "y", verdict="ok")])
        self.assertEqual(len(problems), 3)
        self.assertEqual(rank_problems._validate([]), ["No `## trace <id>` blocks found — is this the right file?"])


class QuestionBankTests(unittest.TestCase):
    def test_comments_and_blank_lines_are_skipped(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "q.txt")
            open(path, "w", encoding="utf-8").write("# comment\n\nFirst?\n  Second?  \n# another\n")
            self.assertEqual(ask_batch.load_questions(path), ["First?", "Second?"])
            with self.assertRaises(FileNotFoundError):
                ask_batch.load_questions(os.path.join(tmp, "missing.txt"))

    def test_the_shipped_question_bank_is_large_enough_to_be_a_sample_not_a_census(self):
        self.assertGreaterEqual(len(ask_batch.load_questions(ask_batch.DEFAULT_QUESTIONS)), 40)


if __name__ == "__main__":
    unittest.main()
