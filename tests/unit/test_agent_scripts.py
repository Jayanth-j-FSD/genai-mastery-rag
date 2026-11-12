"""The Week 7 scripts as a user runs them (one watched run, the race) and the step printer they share."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from app.agent import display
from app.agent.loop import AgentRun
from evals import race, runner

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import race_agent          # noqa: E402
import run_agent           # noqa: E402


def captured(function, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = function(*args)
    return result, out.getvalue()


def step(kind="tool", calls=(), content=""):
    return {"n": 1, "kind": kind, "content": content, "tool_calls": list(calls), "seconds": 1.3,
            "tokens": {"prompt": 100, "completion": 20}}


def tool_call(arguments='{"query": "notice period"}', observation="[1] [source: a.md] text", ok=True):
    return {"name": "search_policies", "arguments": arguments, "observation": observation, "ok": ok}


class ShowStepTests(unittest.TestCase):
    def test_a_final_step_says_so_and_what_it_cost(self):
        self.assertEqual(captured(display.show_step, step("final"))[1].strip(), "[step 1] FINAL ANSWER  (120 tokens, 1.3s)")

    def test_an_error_step_shows_the_message(self):
        self.assertIn("[step 1] ERROR  InternalServerError: down", captured(display.show_step, step("error", content="InternalServerError: down"))[1])

    def test_a_tool_step_shows_what_the_model_said_the_call_the_result_and_the_cost(self):
        text = captured(display.show_step, step("tool", [tool_call()], content="I will search"))[1]
        for needle in ("model says: I will search", 'CALL   search_policies({"query": "notice period"})',
                       "RESULT [1] [source: a.md] text", "(120 tokens, 1.3s)"):
            self.assertIn(needle, text)

    def test_a_refused_call_is_marked(self):
        self.assertIn("<-- the tool refused", captured(display.show_step, step("tool", [tool_call(ok=False, observation="ERROR: bad")]))[1])

    def test_arguments_that_are_not_json_or_arrive_as_an_object_still_print(self):
        self.assertIn("search_policies({not json)", captured(display.show_step, step("tool", [tool_call(arguments="{not json")]))[1])
        self.assertIn("search_policies({'query': 'x'})", captured(display.show_step, step("tool", [tool_call(arguments={"query": "x"})]))[1])

    def test_a_long_result_is_cut_to_one_readable_line(self):
        text = captured(display.show_step, step("tool", [tool_call(observation="word " * 200)]))[1]
        line = [row for row in text.splitlines() if "RESULT" in row][0]
        self.assertTrue(line.endswith("..."))
        self.assertLess(len(line), 260)


def finished_run(answer="16 weeks. [source: a.md]", reason="final"):
    return AgentRun(question="q", answer=answer, stop_reason=reason, steps=[step("final")], elapsed_seconds=2.0, model="m",
                    usage={"calls": 1, "prompt_tokens": 100, "completion_tokens": 20, "api_seconds": 1.0})


class RunAgentScriptTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(run_agent.pipeline, "require_index"))
        self.enterContext(mock.patch.object(run_agent, "default_tools", return_value=[]))

    def test_a_finished_run_prints_the_model_the_answer_and_why_it_stopped(self):
        with mock.patch.object(run_agent.loop, "run_agent", return_value=finished_run()) as agent:
            code, text = captured(run_agent.main, ["--model", "test-model", "How", "many", "weeks?"])
        self.assertEqual(code, 0)
        for needle in ("Question: How many weeks?", "Model: test-model", "ANSWER:", "16 weeks.", "stopped because: final"):
            self.assertIn(needle, text)
        self.assertEqual(agent.call_args.args[0], "How many weeks?")

    def test_a_run_stopped_on_a_limit_says_there_is_no_answer_and_exits_2(self):
        with mock.patch.object(run_agent.loop, "run_agent", return_value=finished_run(None, "max_steps")):
            code, text = captured(run_agent.main, ["q"])
        self.assertEqual(code, 2)
        self.assertIn("NO ANSWER", text)
        self.assertIn("stopped because: max_steps", text)

    def test_the_workflow_flag_runs_the_fixed_recipe(self):
        with mock.patch.object(run_agent.workflow, "run_workflow", return_value=finished_run()) as flow, \
                mock.patch.object(run_agent.loop, "run_agent") as agent:
            code, _ = captured(run_agent.main, ["--workflow", "q"])
        self.assertEqual(code, 0)
        flow.assert_called_once()
        agent.assert_not_called()

    def test_a_limit_of_zero_is_refused_instead_of_quietly_becoming_the_default(self):
        for flag in ("--max-steps", "--max-tokens", "--timeout"):
            with self.subTest(flag=flag), mock.patch.object(run_agent.loop, "run_agent") as agent:
                code, text = captured(run_agent.main, [flag, "0", "q"])
            self.assertEqual(code, 1)
            self.assertIn(f"{flag} must be greater than 0", text)
            agent.assert_not_called()

    def test_a_missing_index_is_explained_not_a_traceback(self):
        with mock.patch.object(run_agent.pipeline, "require_index", side_effect=RuntimeError("no index yet, run ingest")):
            code, text = captured(run_agent.main, ["q"])
        self.assertEqual(code, 1)
        self.assertIn("Error: no index yet", text)


SOURCES = ("[1] [source: Acme-Leave-Policy-2026.md] 18 days\n[2] [source: Synthetic_HR_Policy_RAG_Test_Dataset.md] 24 days")


def race_record(repeat, answer):
    return {"task_id": "t7-conflict", "approach": "agent", "repeat": repeat, "success": True, "finished": True,
            "rules_passed": True, "failed_checks": [], "warnings": [], "stop_reason": "final", "answer": answer,
            "llm_calls": 2, "prompt_tokens": 100, "completion_tokens": 10, "api_seconds": 1.0,
            "steps": [{"tool_calls": [{"name": "search_policies", "ok": True, "observation": SOURCES}]}]}


def saved_race(complete=True):
    both = "18 days [source: Acme-Leave-Policy-2026.md]. 24 days [source: Synthetic_HR_Policy_RAG_Test_Dataset.md]"
    return {"meta": {"label": "t", "repeats": 2, "tasks": ["t7-conflict"], "approaches": ["agent"], "complete": complete,
                     "models": {"agent": "m", "workflow": "m"}},
            "runs": [race_record(1, both), race_record(2, "18 and 24 days [source: Acme-Leave-Policy-2026.md]")]}


class RaceAgentScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.folder))
        self.enterContext(mock.patch.object(race_agent, "BASE_DIR", self.folder))          # --save must not touch the real docs
        runner.save_results(saved_race(), runner.results_path("race-t"))

    def test_show_prints_a_saved_race_without_any_model_call(self):
        code, text = captured(race_agent.main, ["--show", "t"])
        self.assertEqual(code, 0)
        self.assertIn("race 't'", text)
        self.assertNotIn("RE-SCORED", text)

    def test_show_with_rescore_prints_both_tables_and_what_changed(self):
        code, text = captured(race_agent.main, ["--show", "t", "--rescore"])
        self.assertEqual(code, 0)
        for needle in ("AS RACED", "RE-SCORED", "1 run(s) changed result", "run 2  pass -> FAIL"):
            self.assertIn(needle, text)

    def test_saving_a_rescored_view_writes_both_tables_and_the_command_that_made_them(self):
        code, _ = captured(race_agent.main, ["--show", "t", "--rescore", "--save"])
        self.assertEqual(code, 0)
        with open(os.path.join(self.folder, "docs", "week7", "race-results.md"), encoding="utf-8") as handle:
            saved = handle.read()
        for needle in ("AS RACED", "RE-SCORED", "--show t --rescore --save"):
            self.assertIn(needle, saved)

    def test_an_unknown_saved_race_is_a_clear_error(self):
        code, text = captured(race_agent.main, ["--show", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("Error: No saved run", text)

    def test_bad_repeats_and_unknown_tasks_are_explained(self):
        code, text = captured(race_agent.main, ["--repeats", "0"])
        self.assertEqual((code, "--repeats must be 1 or greater" in text), (1, True))
        with mock.patch.object(race_agent.pipeline, "require_index"):
            code, text = captured(race_agent.main, ["--only", "t7-no-such-task"])
        self.assertEqual((code, "unknown task id" in text), (1, True))

    def test_a_race_is_saved_under_its_own_label_and_an_incomplete_one_exits_non_zero(self):
        for complete, expected in ((True, 0), (False, 1)):
            label = f"fresh-{'complete' if complete else 'partial'}"
            with self.subTest(complete=complete), mock.patch.object(race_agent.pipeline, "require_index"), \
                    mock.patch.object(race_agent.race, "run_race", return_value=saved_race(complete)):
                self.assertFalse(os.path.exists(runner.results_path("race-" + label)))
                code, text = captured(race_agent.main, ["--label", label, "--repeats", "2", "--only", "t7-conflict"])
            self.assertEqual(code, expected)
            self.assertIn("saved:", text)
            self.assertTrue(os.path.exists(runner.results_path("race-" + label)))

    def test_a_complete_saved_race_is_never_replaced_without_force(self):
        with mock.patch.object(race_agent.pipeline, "require_index"), \
                mock.patch.object(race_agent.race, "run_race", return_value=saved_race(True)) as racing:
            code, text = captured(race_agent.main, ["--label", "t", "--only", "t7-conflict"])      # "t" is saved and complete
            self.assertEqual(code, 1)
            self.assertIn("already saved", text)
            racing.assert_not_called()
            code, _ = captured(race_agent.main, ["--label", "t", "--only", "t7-conflict", "--force"])
            self.assertEqual(code, 0)
            racing.assert_called_once()

    def test_a_partial_saved_race_may_be_raced_again_without_force(self):
        runner.save_results(saved_race(False), runner.results_path("race-partial"))
        with mock.patch.object(race_agent.pipeline, "require_index"), \
                mock.patch.object(race_agent.race, "run_race", return_value=saved_race(True)) as racing:
            code, _ = captured(race_agent.main, ["--label", "partial", "--only", "t7-conflict"])
        self.assertEqual(code, 0)
        racing.assert_called_once()

    def test_rescore_without_show_is_an_error_and_never_starts_a_race(self):
        with mock.patch.object(race_agent.pipeline, "require_index"), mock.patch.object(race_agent.race, "run_race") as racing:
            code, text = captured(race_agent.main, ["--rescore"])
        self.assertEqual(code, 1)
        self.assertIn("needs --show", text)
        racing.assert_not_called()


if __name__ == "__main__":
    unittest.main()
