"""The Week 6 scripts as a user uses them: run, compare, grade the judge, and make regressions."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from _testkit import fake_response, isolated_index, patched_embeddings
from app import worksheet
from app.rag import generator
from evals import judge, runner, validation
from test_evals_runner import DOCS, NO_REGRESSIONS, make_corpus

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import compare_evals       # noqa: E402
import list_runs           # noqa: E402
import make_judge_sheet    # noqa: E402
import make_regressions    # noqa: E402
import run_evals           # noqa: E402
import validate_judge      # noqa: E402


def call(module, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = module.main(list(args))
    return code, out.getvalue()


def judged_entry(case_id, answer, verdict, passed=True, ptype="single-fact", reason="because"):
    return {"id": case_id, "problem_type": ptype, "question": f"Question for {case_id}?", "reference": f"Reference {case_id}.",
            "answer": answer, "retrieved": [{"source": "A.md", "text": f"Context text for {case_id}."}],
            "passed": passed, "checks": [], "warnings": [],
            "judge": {"verdict": verdict, "reason": reason, "model": "judge-model"}}


def fixture_run(label, entries):
    return {"meta": {"label": label, "complete": True, "models": {"answer": "a", "judge": "judge-model"},
                     "settings": {"retrieval_mode": "dense"}, "chunk_count": 3, "overrides": {}}, "cases": entries}


class RunEvalsScriptTests(unittest.TestCase):
    def setUp(self):
        base = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        corpus = os.path.join(base, "corpus")
        make_corpus(corpus)
        self.enterContext(isolated_index(corpus_dir=corpus, dense_search="exact", retrieval_mode="dense", top_k=3,
                                         llm_model="answer-model", judge_model="judge-model", llm_rpm=0, judge_rpm=0))
        self.enterContext(patched_embeddings())
        self.enterContext(mock.patch.object(runner, "CACHE_DIR", os.path.join(base, "cache")))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", os.path.join(base, "results")))
        self.enterContext(mock.patch("app.llm.last_model", return_value="answer-model"))
        self.enterContext(mock.patch("evals.cases.REGRESSIONS_PATH", NO_REGRESSIONS))
        self.enterContext(mock.patch("app.llm.chat", side_effect=self.chat))
        self.results_dir = os.path.join(base, "results")

    def chat(self, messages, **kwargs):
        if messages[0]["content"] == judge.SYSTEM_PROMPT:
            return fake_response('{"reason": "fine", "verdict": "pass"}')
        if "bonus" in messages[-1]["content"].rsplit("Question:", 1)[-1].lower():
            return fake_response(generator.IDK)
        return fake_response("It means the connection timed out. [source: support-faq.md]")

    def test_one_command_runs_scores_prints_and_saves(self):
        code, out = call(run_evals, "--label", "t", "--only", "code-err4032", "absent-bonus")
        self.assertEqual(code, 0)
        for needle in ("Running 2 case(s)", "problem type", "ALL", "saved:", "[ok  ] code-err4032", "[ok  ] absent-bonus"):
            self.assertIn(needle, out)
        self.assertTrue(os.path.exists(os.path.join(self.results_dir, "t.json")))

    def test_the_default_command_with_no_arguments_runs_the_whole_set(self):
        code, out = call(run_evals, "--no-judge")
        self.assertEqual(code, 0)
        self.assertIn("Running 41 case(s)", out)
        self.assertTrue(os.path.exists(os.path.join(self.results_dir, "latest.json")))

    def test_failures_are_listed_with_the_reason(self):
        code, out = call(run_evals, "--only", "detail-parental-leave", "--no-judge")           # the stub never says 16 weeks
        self.assertEqual(code, 0)
        self.assertIn("did not pass both: 1", out)
        self.assertIn("detail-parental-leave (single-fact)", out)

    def test_min_score_turns_the_run_into_a_gate(self):
        self.assertEqual(call(run_evals, "--only", "absent-bonus", "--min-score", "1.0")[0], 0)
        code, out = call(run_evals, "--only", "detail-parental-leave", "--no-judge", "--min-score", "1.0")
        self.assertEqual(code, 2)
        self.assertIn("below the required 100%", out)

    def test_bad_arguments_are_explained_not_tracebacks(self):
        for args in (["--set", "nonsense=1"], ["--only", "no-such-case"], ["--set", "top_k=0"]):
            with self.subTest(args=args):
                code, out = call(run_evals, *args)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("Error:"))

    def test_an_override_changes_one_setting_for_the_run_only(self):
        from app.config import settings
        before = settings.top_k
        code, _ = call(run_evals, "--only", "absent-bonus", "--set", "top_k=1", "--label", "o", "--no-judge")
        self.assertEqual(code, 0)
        self.assertEqual(settings.top_k, before)
        self.assertEqual(runner.load_results("o")["meta"]["settings"]["top_k"], 1)

    def test_a_missing_judge_model_is_flagged_because_a_model_would_grade_itself(self):
        with mock.patch("app.config.settings.judge_model", ""):
            _, out = call(run_evals, "--only", "absent-bonus")
        self.assertIn("also judges its own answers", out)

    def test_clean_indexes_removes_the_private_indexes(self):
        call(run_evals, "--only", "absent-bonus", "--no-judge")
        code, out = call(run_evals, "--clean-indexes")
        self.assertEqual(code, 0)
        self.assertIn("Removed 1 private eval index(es)", out)

    def test_a_run_stopped_by_a_quota_exits_non_zero_with_the_partial_result_saved(self):
        from app import llm
        with mock.patch("app.llm.chat", side_effect=llm.QuotaExhausted("daily quota used up")):
            code, out = call(run_evals, "--label", "stopped", "--only", "code-err4032")
        self.assertEqual(code, 1)
        self.assertIn("STOPPED", out)
        self.assertFalse(runner.load_results("stopped")["meta"]["complete"])


class CompareScriptTests(unittest.TestCase):
    def test_compare_prints_the_table_and_names_the_cases(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, \
                mock.patch.object(runner, "RESULTS_DIR", tmp):
            runner.save_results(fixture_run("baseline", [judged_entry("a", "x", "fail", passed=False), judged_entry("b", "y", "pass")]))
            runner.save_results(fixture_run("after", [judged_entry("a", "x", "pass"), judged_entry("b", "y", "pass")]))
            code, out = call(compare_evals, "baseline", "after")
        self.assertEqual(code, 0)
        self.assertIn("fixed by the change    : 1  ['a']", out)
        self.assertIn("+50pt", out)

    def test_a_missing_run_points_at_how_to_make_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.object(runner, "RESULTS_DIR", tmp):
            code, out = call(compare_evals, "nope", "nada")
        self.assertEqual(code, 1)
        self.assertIn("run_evals.py --label baseline", out)

    def test_an_incomplete_run_is_flagged(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.object(runner, "RESULTS_DIR", tmp):
            partial = fixture_run("part", [judged_entry("a", "x", "pass")])
            partial["meta"].update(complete=False, stopped_because="quota")
            runner.save_results(partial)
            runner.save_results(fixture_run("full", [judged_entry("a", "x", "pass")]))
            _, out = call(compare_evals, "part", "full")
        self.assertIn("incomplete", out)

    def test_save_writes_a_generated_file_under_docs_week6(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.object(runner, "RESULTS_DIR", tmp), \
                mock.patch.object(compare_evals, "BASE_DIR", tmp):
            runner.save_results(fixture_run("b", [judged_entry("a", "x", "pass")]))
            runner.save_results(fixture_run("a", [judged_entry("a", "x", "pass")]))
            code, _ = call(compare_evals, "b", "a", "--save")
            written = open(os.path.join(tmp, "docs", "week6", "before-after.md"), encoding="utf-8").read()
        self.assertEqual(code, 0)
        self.assertIn("compare_evals.py b a --save", written)


class JudgeValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.tmp))
        entries = [judged_entry(f"c{i:02d}", f"Answer {i}.", "pass" if i % 3 else "fail", passed=bool(i % 4)) for i in range(1, 13)]
        runner.save_results(fixture_run("base", entries))
        self.sheet = os.path.join(self.tmp, "sheet.md")
        self.items = os.path.join(self.tmp, "items.json")

    def make(self, *extra):
        return call(make_judge_sheet, "--runs", "base", "--out", self.sheet, *extra)

    def grade(self, answers):
        """answers: {sheet id: 'ok'|'bad'}"""
        lines, current = open(self.sheet, encoding="utf-8").read().splitlines(), None
        out = []
        for line in lines:
            if line.startswith("## trace "):
                current = line.split()[-1]
            if line.startswith("- verdict:") and current in answers:
                line = f"- verdict: {answers[current]}"
            out.append(line)
        open(self.sheet, "w", encoding="utf-8").write("\n".join(out) + "\n")

    def hidden(self):
        return json.load(open(self.items, encoding="utf-8"))["items"]

    def test_the_sheet_is_blind_the_judges_verdicts_live_in_a_separate_file(self):
        code, out = self.make("--n", "8")
        self.assertEqual(code, 0)
        sheet = open(self.sheet, encoding="utf-8").read()
        for info in self.hidden().values():
            self.assertNotIn(info["judge_reason"], sheet)
        for leak in ("because", "judge-model", "pass", "fail"):
            self.assertNotIn(leak, sheet.lower().replace("verdict:", ""))
        self.assertIn("Context text for", sheet)                            # but the human sees what the judge saw
        self.assertIn("Reference c", sheet)
        self.assertEqual(len(self.hidden()), 8)
        self.assertIn("do not open it until you have graded", out)

    def test_the_sample_leads_with_the_flagged_answers_and_is_reproducible(self):
        self.make("--n", "6", "--seed", "7")
        first = sorted(self.hidden())
        flagged_in_sheet = [i for i in self.hidden().values() if i["judge_verdict"] == "fail" or not i["rules_passed"]]
        self.assertGreaterEqual(len(flagged_in_sheet), 3)                   # half of 6, at least
        self.make("--n", "6", "--seed", "7", "--force")
        self.assertEqual(sorted(self.hidden()), first)

    def test_an_existing_sheet_is_never_overwritten_without_force(self):
        self.make("--n", "6")
        with open(self.sheet, "a", encoding="utf-8") as handle:
            handle.write("\nMY GRADING\n")
        code, out = self.make("--n", "6")
        self.assertEqual(code, 1)
        self.assertIn("already exists", out)
        self.assertIn("MY GRADING", open(self.sheet, encoding="utf-8").read())

    def test_asking_for_more_than_exist_gives_what_exists(self):
        _, out = self.make("--n", "50")
        self.assertIn("only 12 judged answers exist", out)
        self.assertEqual(len(self.hidden()), 12)

    def test_runs_without_a_judge_cannot_make_a_sheet(self):
        runner.save_results(fixture_run("nojudge", [dict(judged_entry("z", "a", "pass"), judge=None)]))
        code, out = call(make_judge_sheet, "--runs", "nojudge", "--out", self.sheet)
        self.assertEqual(code, 1)
        self.assertIn("no judged answers", out)

    def test_validation_refuses_until_every_answer_is_graded(self):
        self.make("--n", "8")
        code, out = call(validate_judge, "--in", self.sheet)
        self.assertEqual(code, 1)
        self.assertIn("not finished", out)
        self.assertIn("verdict is ''", out)

    def test_perfect_agreement_is_trusted_and_a_judge_that_always_passes_is_not(self):
        self.make("--n", "12")
        hidden = self.hidden()
        self.grade({sheet_id: "ok" if info["judge_verdict"] == "pass" else "bad" for sheet_id, info in hidden.items()})
        code, out = call(validate_judge, "--in", self.sheet)
        self.assertEqual(code, 0)
        self.assertIn("agreement            : 100%", out)
        self.assertIn("Cohen's kappa        : 1.00", out)
        self.assertIn("the judge clears both bars", out)
        # now the human fails everything the judge fails AND some it passes: judge too lenient
        self.grade({sheet_id: "bad" for sheet_id in hidden})
        _, out = call(validate_judge, "--in", self.sheet)
        self.assertIn("judge too lenient", out)
        self.assertIn("disagreement(s)", out)
        self.assertIn("NOT yet trustworthy", out)                            # kappa is 0 here: no better than chance

    def test_all_identical_verdicts_cannot_be_judged(self):
        self.make("--n", "12")
        only_pass = {s: "ok" for s, info in self.hidden().items() if info["judge_verdict"] == "pass"}
        mapping = json.load(open(self.items, encoding="utf-8"))
        mapping["items"] = {s: info for s, info in mapping["items"].items() if info["judge_verdict"] == "pass"}
        json.dump(mapping, open(self.items, "w", encoding="utf-8"))
        self.grade(only_pass)
        # keep only the passing blocks in the sheet
        text = open(self.sheet, encoding="utf-8").read()
        head, *blocks = text.split("## trace ")
        kept = [b for b in blocks if b.split()[0] in only_pass]
        open(self.sheet, "w", encoding="utf-8").write(head + "".join("## trace " + b for b in kept))
        code, out = call(validate_judge, "--in", self.sheet)
        self.assertEqual(code, 0)
        self.assertIn("cannot be judged", out)

    def test_a_deleted_block_is_reported_not_quietly_ignored(self):
        self.make("--n", "6")
        self.grade({s: "ok" for s in sorted(self.hidden())})
        head, *blocks = open(self.sheet, encoding="utf-8").read().split("## trace ")
        open(self.sheet, "w", encoding="utf-8").write(head + "".join("## trace " + b for b in blocks[2:]))     # two blocks deleted
        code, out = call(validate_judge, "--in", self.sheet)
        self.assertEqual(code, 1)
        self.assertIn("missing from the sheet", out)

    def test_a_sheet_with_no_folder_in_its_path_can_be_written(self):
        here = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, here)
        code, _ = call(make_judge_sheet, "--runs", "base", "--out", "plain-sheet.md", "--n", "4")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "plain-sheet.md")))

    def test_a_sheet_that_does_not_match_its_items_file_is_refused(self):
        self.make("--n", "6")
        self.grade({s: "ok" for s in sorted(self.hidden())})                  # every block graded...
        mapping = json.load(open(self.items, encoding="utf-8"))
        mapping["items"].pop(sorted(mapping["items"])[0])                     # ...then the items file loses one
        json.dump(mapping, open(self.items, "w", encoding="utf-8"))
        code, out = call(validate_judge, "--in", self.sheet)
        self.assertEqual(code, 1)
        self.assertIn("was the sheet regenerated", out)

    def test_a_judge_reply_that_was_unreadable_is_left_out_and_reported(self):
        runner.save_results(fixture_run("withbad", [judged_entry("e1", "A.", "pass"), judged_entry("e2", "B.", "pass")]))
        run = runner.load_results("withbad")
        run["cases"][1]["judge"]["verdict"] = "error"
        items = validation.collect_items([run])
        self.assertEqual([i["entry"]["id"] for i in items], ["e1"])          # errors never reach the sheet

    def test_save_writes_a_generated_numbers_only_file(self):
        self.make("--n", "12")
        self.grade({s: "ok" if info["judge_verdict"] == "pass" else "bad" for s, info in self.hidden().items()})
        with mock.patch.object(validate_judge, "BASE_DIR", self.tmp):
            code, _ = call(validate_judge, "--in", self.sheet, "--save")
            written = open(os.path.join(self.tmp, "docs", "week6", "judge-validation-output.md"), encoding="utf-8").read()
        self.assertEqual(code, 0)
        self.assertIn("Numbers only", written)


CODED_NOTES = """# Week 5: coded notes

<!-- sample_size: 20 -->

## trace aaa111

**Question:** How many weeks of parental leave?

**Answer:** I don't know based on the provided documents.

- verdict: bad
- note: refused though the answer was in the leave policy
- severity: 3
- code: Refused Though Answerable

## trace bbb222

**Question:** What is the bonus?

**Answer:** The bonus is 10 percent.

- verdict: bad
- note: invented a number for something absent
- severity: 3
- code: made-up-answer
"""


class RegressionScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.notes = os.path.join(self.tmp, "coded-notes.md")
        self.out = os.path.join(self.tmp, "regressions.json")

    def write(self, text):
        open(self.notes, "w", encoding="utf-8").write(text)

    def test_every_failure_becomes_a_case_named_by_the_students_own_group(self):
        self.write(CODED_NOTES)
        code, out = call(make_regressions, "--in", self.notes, "--out", self.out)
        self.assertEqual(code, 0)
        cases = json.load(open(self.out, encoding="utf-8"))["cases"]
        self.assertEqual([c["id"] for c in cases], ["w5-aaa111", "w5-bbb222"])
        self.assertEqual([c["problem_type"] for c in cases], ["refused-though-answerable", "made-up-answer"])
        self.assertEqual(cases[0]["origin"], "week5:aaa111")
        self.assertEqual(cases[0]["your_note"], "refused though the answer was in the leave policy")
        self.assertEqual((cases[0]["expected_sources"], cases[0]["should_refuse"]), ([], False))

    def test_expectations_are_left_for_the_student_to_fill_in(self):
        self.write(CODED_NOTES)
        call(make_regressions, "--in", self.notes, "--out", self.out)
        from evals import cases as eval_cases
        merged = {c["id"]: c for c in eval_cases.all_cases(self.out)}
        self.assertTrue(merged["w5-aaa111"]["needs_expected"])
        data = json.load(open(self.out, encoding="utf-8"))
        data["cases"][0].update(expected_sources=["Acme-Leave-Policy-2026.md"], expect_contains=["16 weeks"])
        data["cases"][1]["should_refuse"] = True
        json.dump(data, open(self.out, "w", encoding="utf-8"))
        filled = {c["id"]: c for c in eval_cases.all_cases(self.out)}
        self.assertFalse(filled["w5-aaa111"]["needs_expected"])
        self.assertTrue(filled["w5-bbb222"]["should_refuse"])

    def test_it_never_overwrites_expectations_you_filled_in(self):
        self.write(CODED_NOTES)
        call(make_regressions, "--in", self.notes, "--out", self.out)
        with open(self.out, "a", encoding="utf-8") as handle:
            handle.write("\nMY EXPECTATIONS")
        code, out = call(make_regressions, "--in", self.notes, "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("already exists", out)
        self.assertIn("MY EXPECTATIONS", open(self.out, encoding="utf-8").read())
        self.assertEqual(call(make_regressions, "--in", self.notes, "--out", self.out, "--force")[0], 0)

    def test_failures_without_a_group_name_are_refused(self):
        self.write(CODED_NOTES.replace("- code: made-up-answer", "- code: "))
        code, out = call(make_regressions, "--in", self.notes, "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("no group name yet", out)
        self.assertIn("bbb222", out)

    def test_no_notes_and_no_failures_each_get_a_pointer(self):
        code, out = call(make_regressions, "--in", os.path.join(self.tmp, "missing.md"), "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("Week 5", out)
        self.write("# notes\n\n## trace ok1\n\n**Question:** q\n\n- verdict: ok\n")
        code, out = call(make_regressions, "--in", self.notes, "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("nothing to turn into a test", out)

    def test_the_week5_parser_and_this_converter_agree_on_what_a_failure_is(self):
        self.write(CODED_NOTES)
        blocks, _ = worksheet.parse(self.notes)
        self.assertEqual(len(make_regressions.build_cases(blocks)), len(worksheet.failures(blocks)))


class ListRunsScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.tmp))
        for label in ("b-run", "a-run"):                                   # saved in this order on purpose
            runner.save_results(fixture_run(label, [judged_entry("c1", "A.", "pass")]))

    def test_runs_are_listed_alphabetically_and_a_given_order_is_kept(self):
        code, out = call(list_runs)
        self.assertEqual(code, 0)
        self.assertLess(out.index("a-run"), out.index("b-run"))
        code, out = call(list_runs, "b-run", "a-run")
        self.assertLess(out.index("b-run"), out.index("a-run"))

    def test_files_that_are_not_eval_runs_are_skipped_not_a_crash(self):
        runner.save_results({"meta": {"label": "race", "complete": True, "approaches": []}, "runs": []}, runner.results_path("race-race"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, out = call(list_runs)
        self.assertEqual(code, 0)
        self.assertIn("a-run", out)
        self.assertNotIn("race-race", out)
        self.assertNotIn("are not eval runs", out)                       # stdout stays a clean table
        self.assertIn("1 saved file(s) are not eval runs", err.getvalue())
        code, out = call(list_runs, "race-race")
        self.assertEqual(code, 1)
        self.assertIn("is not an eval run", out)

    def test_an_unknown_label_and_an_empty_folder_are_clear_errors(self):
        code, out = call(list_runs, "nope")
        self.assertEqual(code, 1)
        self.assertIn("Error", out)
        for name in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, name))
        code, out = call(list_runs)
        self.assertEqual(code, 1)
        self.assertIn("No saved runs", out)


if __name__ == "__main__":
    unittest.main()
