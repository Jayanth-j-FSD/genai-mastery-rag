"""Week 8: grading the path an agent took, with records built by hand (no model)."""
import json
import unittest

import _testkit  # noqa: F401  (puts the project root on sys.path)
from evals import trajectory

TASK = {"id": "t-notice", "question": "Resignation received on 3 November 2026. When does a 30 day notice period end?",
        "expected_tools": ["search_policies", "add_days"], "should_refuse": False}
SEARCH_RESULT = "[1] [source: terms.md] The notice period is 30 calendar days."


def call(name, arguments, observation="ok", ok=True, blocked=False):
    return {"name": name, "arguments": json.dumps(arguments), "observation": observation, "ok": ok, "blocked": blocked}


def record(calls, answer="It ends on 2026-12-03 [source: terms.md]", stop="final", success=True, **extra):
    steps = [{"n": i + 1, "kind": "tool", "tool_calls": [c]} for i, c in enumerate(calls)]
    base = {"task_id": "t-notice", "success": success, "stop_reason": stop, "answer": answer, "steps": steps,
            "prompt_tokens": 1000, "completion_tokens": 100, "llm_calls": len(calls) + 1, "api_seconds": 2.0}
    base.update(extra)
    return base


CLEAN = [call("search_policies", {"query": "notice period"}, SEARCH_RESULT),
         call("add_days", {"date": "2026-11-03", "days": 30}, "2026-12-03 (Thursday)")]


def modes(task, rec):
    return [item["mode"] for item in trajectory.detect_modes(task, rec)]


class DetectModesTests(unittest.TestCase):
    def test_a_clean_run_shows_no_failure_mode(self):
        self.assertEqual(modes(TASK, record(CLEAN)), [])

    def test_an_identical_repeat_the_loop_had_to_warn_about_is_a_loop(self):
        calls = CLEAN + [call("search_policies", {"query": "notice period"}, "You already called search_policies with exactly these arguments", ok=False)]
        self.assertIn("loop", modes(TASK, record(calls)))

    def test_reaching_the_step_limit_is_a_loop_but_four_different_searches_are_only_over_calling(self):
        many = [call("search_policies", {"query": f"q{i}"}, SEARCH_RESULT) for i in range(4)] + CLEAN[1:]
        self.assertEqual(modes(TASK, record(many)), ["over-calling"])
        self.assertIn("loop", modes(TASK, record(CLEAN, stop="max_steps", answer=None, success=False)))
        three = [call("search_policies", {"query": f"q{i}"}, SEARCH_RESULT) for i in range(3)] + CLEAN[1:]
        self.assertNotIn("over-calling", modes(TASK, record(three)))

    def test_a_tool_the_task_does_not_need_is_a_wrong_tool_but_notes_are_not(self):
        extra = CLEAN + [call("calculate", {"expression": "3 + 30"}, "33")]
        self.assertIn("wrong-tool", modes(TASK, record(extra)))
        self.assertNotIn("wrong-tool", modes(TASK, record(CLEAN + [call("remember", {"fact": "30 days"}, "Saved note 1.")])))

    def test_an_allowed_extra_tool_is_not_a_wrong_tool_and_counts_as_a_good_choice(self):
        extra = CLEAN + [call("calculate", {"expression": "3 + 30"}, "33")]
        allowing = dict(TASK, allowed_tools=["calculate"])
        self.assertNotIn("wrong-tool", modes(allowing, record(extra)))
        self.assertEqual(trajectory.tool_choice_accuracy(allowing, record(extra)), 1.0)
        self.assertLess(trajectory.tool_choice_accuracy(TASK, record(extra)), 1.0)

    def test_a_right_answer_without_the_date_tool_is_a_skipped_tool(self):
        rec = record(CLEAN[:1], answer="It ends on 2026-12-03 [source: terms.md]")
        self.assertEqual(modes(TASK, rec), ["skipped-tool"])
        self.assertIn("add_days", trajectory.detect_modes(TASK, rec)[0]["detail"])

    def test_a_date_nobody_supplied_is_a_made_up_input(self):
        invented = [CLEAN[0], call("add_days", {"date": "2026-10-01", "days": 30}, "2026-10-31 (Saturday)")]
        self.assertIn("made-up-input", modes(TASK, record(invented)))

    def test_a_number_of_days_nobody_supplied_is_a_made_up_input(self):
        guessed = [call("search_policies", {"query": "x"}, "[1] [source: terms.md] Nothing about the length here."),
                   call("add_days", {"date": "2026-11-03", "days": 45}, "2026-12-18 (Friday)")]
        rec = record(guessed)
        self.assertIn("made-up-input", modes(TASK, rec))
        self.assertIn("45 days", trajectory.detect_modes(TASK, rec)[0]["detail"])

    def test_days_stated_in_the_question_or_an_earlier_result_or_calculation_are_grounded(self):
        from_question = [CLEAN[0], call("add_days", {"date": "2026-11-03", "days": 30}, "2026-12-03 (Thursday)")]
        self.assertNotIn("made-up-input", modes(TASK, record(from_question)))
        from_calculation = [call("calculate", {"expression": "4 * 7"}, "28"), call("add_days", {"date": "2026-11-03", "days": 28}, "2026-12-01 (Tuesday)")]
        self.assertNotIn("made-up-input", modes(dict(TASK, expected_tools=["calculate", "add_days"]), record(from_calculation)))
        negative = [CLEAN[0], call("add_days", {"date": "2026-11-03", "days": -30}, "2026-10-04 (Sunday)")]
        self.assertNotIn("made-up-input", modes(TASK, record(negative)))

    def test_a_date_from_an_earlier_result_is_not_made_up(self):
        chained = CLEAN + [call("add_days", {"date": "2026-12-03", "days": 1}, "2026-12-04 (Friday)")]
        self.assertNotIn("made-up-input", modes(TASK, record(chained)))

    def test_a_blocked_call_is_not_counted_as_a_made_up_input(self):
        blocked = [CLEAN[0], call("add_days", {"date": "2099-01-01", "days": 7}, "BLOCKED: ...", ok=False, blocked=True), CLEAN[1]]
        self.assertNotIn("made-up-input", modes(TASK, record(blocked)))

    def test_citing_a_document_that_was_never_retrieved_is_an_unverified_citation(self):
        self.assertIn("unverified-citation", modes(TASK, record(CLEAN, answer="Ends 2026-12-03 [source: invented.md]")))

    def test_one_tag_naming_several_retrieved_documents_is_not_an_unverified_citation(self):
        both = [call("search_policies", {"query": "x"}, "[1] [source: a.md] t\n[2] [source: b.md] t")] + CLEAN[1:]
        for answer in ("Ends 2026-12-03 [source: a.md, b.md]", "Ends 2026-12-03 [source: a.md; source: b.md]",
                       "Ends 2026-12-03 [source: a.md] and [source: b.md]"):
            with self.subTest(answer=answer):
                self.assertNotIn("unverified-citation", modes(TASK, record(both, answer=answer)))
        self.assertIn("unverified-citation", modes(TASK, record(both, answer="Ends 2026-12-03 [source: a.md, c.md]")))

    def test_citations_are_split_and_cleaned(self):
        self.assertEqual(trajectory.cited_documents("x [source: A.md; source: B.md] y [Source: C.md]"), ["A.md", "B.md", "C.md"])
        self.assertEqual(trajectory.cited_documents(None), [])

    def test_saying_i_dont_know_after_one_search_on_an_answerable_task_is_giving_up_quietly(self):
        giveup = record(CLEAN[:1], answer="I don't know based on the provided documents.", success=False)
        self.assertIn("gave-up-quietly", modes(TASK, giveup))
        refusal_task = dict(TASK, should_refuse=True, expected_tools=["search_policies"])
        self.assertNotIn("gave-up-quietly", modes(refusal_task, giveup))

    def test_two_searches_before_giving_up_is_not_quiet(self):
        tried = [call("search_policies", {"query": "a"}, "No passages found."), call("search_policies", {"query": "b"}, "No passages found.")]
        self.assertNotIn("gave-up-quietly", modes(TASK, record(tried, answer="I don't know based on the provided documents.", success=False)))

    def test_ending_on_a_limit_is_no_answer_and_a_blocked_legitimate_answer_is_a_false_block(self):
        self.assertIn("no-answer", modes(TASK, record(CLEAN, stop="token_budget", answer=None, success=False)))
        self.assertIn("blocked-answer", modes(TASK, record(CLEAN, stop="output_blocked", answer="I can't...", success=False)))
        refusal_task = dict(TASK, should_refuse=True)
        self.assertNotIn("blocked-answer", modes(refusal_task, record(CLEAN, stop="output_blocked", answer="I can't...")))


class MetricsTests(unittest.TestCase):
    def test_tool_choice_accuracy_is_the_share_of_calls_to_needed_tools_ignoring_notes(self):
        rec = record(CLEAN + [call("calculate", {"expression": "1+1"}), call("remember", {"fact": "x"})])
        self.assertEqual(trajectory.tool_choice_accuracy(TASK, rec), 2 / 3)
        self.assertEqual(trajectory.tool_choice_accuracy(TASK, record([])), 0.0)
        self.assertEqual(trajectory.tool_choice_accuracy(dict(TASK, expected_tools=[]), record([])), 1.0)

    def test_order_is_checked_on_first_use_of_the_needed_tools(self):
        self.assertTrue(trajectory.order_ok(TASK, record(CLEAN)))
        self.assertFalse(trajectory.order_ok(TASK, record(CLEAN[::-1])))
        self.assertTrue(trajectory.order_ok(TASK, record(CLEAN[:1])))

    def test_the_gap_table_counts_each_cell_of_outcome_by_path(self):
        graded = [{"outcome_ok": True, "trajectory_ok": True}, {"outcome_ok": True, "trajectory_ok": False},
                  {"outcome_ok": True, "trajectory_ok": False}, {"outcome_ok": False, "trajectory_ok": True},
                  {"outcome_ok": False, "trajectory_ok": False}]
        self.assertEqual(trajectory.gap_table(graded), {"right-answer-right-path": 1, "right-answer-wrong-path": 2,
                                                         "wrong-answer-right-path": 1, "wrong-answer-wrong-path": 1})

    def test_modes_are_ranked_by_runs_affected_then_by_wrong_answers(self):
        graded = [{"outcome_ok": True, "modes": ["skipped-tool"]}, {"outcome_ok": False, "modes": ["skipped-tool", "loop"]},
                  {"outcome_ok": False, "modes": ["loop"]}, {"outcome_ok": True, "modes": ["wrong-tool"]}]
        ranked = trajectory.rank_modes(graded)
        self.assertEqual([(r["mode"], r["runs"], r["also_wrong_answer"]) for r in ranked],
                         [("loop", 2, 2), ("skipped-tool", 2, 1), ("wrong-tool", 1, 0)])

    def test_a_run_counts_once_per_mode_however_often_it_did_it(self):
        self.assertEqual(trajectory.mode_counts([{"modes": ["loop", "loop"]}]), {"loop": 1})

    def test_cost_is_reported_as_mean_median_p95_p99_and_max(self):
        records = [{"prompt_tokens": n * 100, "completion_tokens": 0, "llm_calls": n, "api_seconds": float(n)} for n in range(1, 11)]
        stats = trajectory.cost_summary(records)["tokens"]
        self.assertEqual((stats["mean"], stats["p50"], stats["p95"], stats["p99"], stats["max"]), (550.0, 500, 1000, 1000, 1000))
        self.assertEqual(trajectory.cost_summary([])["tokens"]["max"], 0.0)


class GradeAndReportTests(unittest.TestCase):
    def test_grade_combines_outcome_and_path(self):
        graded = trajectory.grade(TASK, record(CLEAN[:1]))
        self.assertTrue(graded["outcome_ok"])
        self.assertFalse(graded["trajectory_ok"])
        self.assertEqual(graded["modes"], ["skipped-tool"])

    def test_grade_all_skips_records_of_unknown_tasks(self):
        graded = trajectory.grade_all([record(CLEAN), dict(record(CLEAN), task_id="other")], [TASK])
        self.assertEqual(len(graded), 1)

    def test_the_report_and_the_comparison_print_without_error_and_show_the_gap(self):
        runs = [record(CLEAN), record(CLEAN[:1])]
        graded = trajectory.grade_all(runs, [TASK])
        summary = trajectory.summarize(graded, runs)
        text = "\n".join(trajectory.format_report(summary, "demo"))
        self.assertIn("right-answer-wrong-path", text)
        self.assertIn("skipped-tool", text)
        better = trajectory.summarize(trajectory.grade_all([record(CLEAN)], [TASK]), [record(CLEAN)])
        compared = "\n".join(trajectory.format_compare(summary, better, "before", "after"))
        self.assertIn("mode: skipped-tool", compared)


if __name__ == "__main__":
    unittest.main()
