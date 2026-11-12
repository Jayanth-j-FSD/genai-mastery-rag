"""Week 10: scripts/pilot_team.py: a shake-down on questions that are not race tasks (no model calls)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import _testkit
from app import llm
from evals import runner
from evals.agent_tasks import PATH_PROBES, TASKS

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import pilot_team          # noqa: E402

BANK = os.path.join(_testkit.ROOT, "tests", "trace_questions.txt")
STAMP = {"git": "abc1234", "dirty": True}


def captured(function, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = function(*args)
    return result, out.getvalue()


def fake_run(answer="An answer.", calls=2, stop="final", handoffs=()):
    crew = {"handoffs": [dict({"agent": "researcher", "question": "q", "state": "finished", "calls": 2, "answer_chars": 10}, **h) for h in handoffs]}
    return SimpleNamespace(answer=answer, stop_reason=stop, usage={"calls": calls, "prompt_tokens": 100, "completion_tokens": 10}, steps=[1, 2], team=crew)


class SelectionTests(unittest.TestCase):
    def test_a_race_task_and_a_question_that_is_almost_one_are_left_out_but_a_different_question_stays(self):
        task = TASKS[0]["question"]
        self.assertTrue(pilot_team.too_close_to_a_race_task(task))
        self.assertTrue(pilot_team.too_close_to_a_race_task(task.replace("available", "offered")))
        self.assertFalse(pilot_team.too_close_to_a_race_task("How long is a password reset link valid?"))
        self.assertFalse(pilot_team.too_close_to_a_race_task(""))

    def test_no_question_the_pilot_can_pick_from_the_real_bank_is_a_race_task_or_close_to_one(self):
        picked, left_out = pilot_team.choose(pilot_team.load_questions(BANK), 100, 1)
        self.assertTrue(picked)
        self.assertTrue(left_out)                                                           # the bank does overlap the race tasks
        for question in picked:
            self.assertFalse(pilot_team.too_close_to_a_race_task(question), question)
        race_questions = {task["question"] for task in TASKS + PATH_PROBES}
        self.assertFalse(race_questions & set(picked))

    def test_the_same_seed_picks_the_same_questions_and_another_seed_picks_others(self):
        questions = pilot_team.load_questions(BANK)
        self.assertEqual(pilot_team.choose(questions, 6, 1)[0], pilot_team.choose(questions, 6, 1)[0])
        self.assertNotEqual(pilot_team.choose(questions, 6, 1)[0], pilot_team.choose(questions, 6, 2)[0])

    def test_the_question_file_skips_comments_and_blank_lines(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        path = os.path.join(folder, "q.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("# a comment\n\nFirst question?\n   Second question?  \n# another\n")
        self.assertEqual(pilot_team.load_questions(path), ["First question?", "Second question?"])


class RunTests(unittest.TestCase):
    def test_both_arms_run_on_the_question_and_the_order_alternates(self):
        order = []

        def agent(question, tools, **options):
            order.append("agent")
            return fake_run()

        def crew(question, tools, **options):
            order.append("team")
            return fake_run(handoffs=[{"agent": "calculator"}])

        with mock.patch.object(pilot_team.loop, "run_agent", agent), mock.patch.object(pilot_team.team, "run_team", crew):
            first = pilot_team.run_pair("q?", 0, "m", 300.0)
            second = pilot_team.run_pair("q?", 1, "m", 300.0)
        self.assertEqual(order, ["agent", "team", "team", "agent"])
        self.assertEqual([row["arm"] for row in first], ["agent", "team"])
        self.assertEqual(first[1]["handoffs"][0]["agent"], "calculator")
        self.assertEqual((first[0]["calls"], first[0]["tokens"], second[0]["refused"]), (2, 110, False))

    def test_every_run_gets_the_same_model_timeout_and_no_per_tool_cap(self):
        seen = []
        with mock.patch.object(pilot_team.loop, "run_agent", lambda q, t, **o: seen.append(o) or fake_run()), \
                mock.patch.object(pilot_team.team, "run_team", lambda q, t, **o: seen.append(o) or fake_run()):
            pilot_team.run_pair("q?", 0, "model-y", 200.0)
        self.assertEqual(seen, [{"model": "model-y", "timeout_seconds": 200.0, "max_calls_per_tool": 0}] * 2)

    def test_a_pair_counts_the_requests_each_arm_sent_retried_attempts_included(self):
        def agent(question, tools, **options):
            llm._record_call(0.1, 0.1, 0.0, 4, "m", "served", 100, 10)                      # one call that took four requests
            return fake_run(calls=1)

        def crew(question, tools, **options):
            for _ in range(2):
                llm._record_call(0.1, 0.1, 0.0, 1, "m", "served", 50, 5)
            return fake_run(calls=2)

        with mock.patch.object(pilot_team.loop, "run_agent", agent), mock.patch.object(pilot_team.team, "run_team", crew):
            rows = pilot_team.run_pair("q?", 0, "m", 300.0)
        self.assertEqual([(row["arm"], row["calls"], row["requests"]) for row in rows], [("agent", 1, 4), ("team", 2, 2)])

    def test_a_run_that_ended_on_a_provider_error_is_at_least_one_request(self):
        with mock.patch.object(pilot_team.loop, "run_agent", lambda q, t, **o: fake_run(calls=0, stop="error")), \
                mock.patch.object(pilot_team.team, "run_team", lambda q, t, **o: fake_run(calls=0, stop="error")):
            rows = pilot_team.run_pair("q?", 0, "m", 300.0)
        self.assertEqual([row["requests"] for row in rows], [1, 1])

    def test_a_refusal_is_noticed(self):
        with mock.patch.object(pilot_team.loop, "run_agent", lambda q, t, **o: fake_run(answer="I don't know based on the provided documents.")), \
                mock.patch.object(pilot_team.team, "run_team", lambda q, t, **o: fake_run()):
            rows = pilot_team.run_pair("q?", 0, "m", 300.0)
        self.assertEqual([row["refused"] for row in rows], [True, False])


class MainTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.folder))
        self.enterContext(mock.patch.object(pilot_team.pipeline, "require_index"))
        self.enterContext(mock.patch.object(pilot_team.race_team, "code_stamp", return_value=STAMP))
        self.pairs = []
        self.enterContext(mock.patch.object(pilot_team, "run_pair", side_effect=self.fake_pair))

    def fake_pair(self, question, index, model, timeout):
        self.pairs.append(question)
        return [{"question": question, "arm": "agent", "stop_reason": "final", "answer": "a", "calls": 3, "tokens": 300, "steps": 3, "refused": False,
                 "served_model": "m", "handoffs": []},
                {"question": question, "arm": "team", "stop_reason": "final", "answer": "b", "calls": 7, "tokens": 700, "steps": 6, "refused": False,
                 "served_model": "m", "handoffs": [{"agent": "researcher", "question": "q", "state": "finished", "calls": 2, "answer_chars": 5}]}]

    def test_a_pilot_is_saved_with_the_code_it_ran_on_and_the_questions_it_left_out(self):
        code, text = captured(pilot_team.main, ["--label", "pilot-t", "--model", "m", "--n", "3"])
        self.assertEqual(code, 0)
        saved = runner.load_results("pilot-t")
        self.assertEqual((len(saved["runs"]), saved["meta"]["complete"], saved["meta"]["code"]), (6, True, "abc1234 plus uncommitted changes"))
        self.assertTrue(saved["meta"]["left_out_as_race_tasks_or_close_to_one"])
        for needle in ("agent: 3.0 calls", "team: 7.0 calls", "hand-off to the researcher", "saved:"):
            self.assertIn(needle, text)
        self.assertEqual(len(self.pairs), 3)
        self.assertFalse(set(self.pairs) & {task["question"] for task in TASKS})

    def test_a_question_of_your_own_is_run_and_listed_as_ad_hoc_and_one_that_is_a_race_task_is_refused(self):
        code, text = captured(pilot_team.main, ["--label", "pilot-x", "--model", "m", "--n", "0", "--extra", "My allowance is 12 days and I used 5: how many are left?"])
        self.assertEqual(code, 0)
        self.assertEqual(self.pairs, ["My allowance is 12 days and I used 5: how many are left?"])
        saved = runner.load_results("pilot-x")
        self.assertEqual(saved["meta"]["ad_hoc_questions"], ["My allowance is 12 days and I used 5: how many are left?"])
        self.assertIn("ad hoc questions (not from the bank): 1", text)
        code, text = captured(pilot_team.main, ["--label", "pilot-y", "--model", "m", "--extra", TASKS[0]["question"]])
        self.assertEqual((code, "must not be run on the test set" in text), (1, True))

    def test_zero_bank_questions_is_only_allowed_with_a_question_of_your_own(self):
        code, text = captured(pilot_team.main, ["--label", "pilot-z", "--model", "m", "--n", "0"])
        self.assertEqual((code, "0 only with --extra" in text), (1, True))

    def test_the_label_must_start_with_pilot_and_the_model_must_be_named_and_not_an_alias(self):
        for argv, needle in ((["--label", "race-x", "--model", "m"], "pilot-"), ([], "pilot-"), (["--label", "pilot-x"], "--model"),
                             (["--label", "pilot-x", "--model", "gemini-flash-lite-latest"], "alias"),
                             (["--label", "pilot-x", "--model", "m", "--n", "-1"], "--n")):
            with self.subTest(argv=argv):
                code, text = captured(pilot_team.main, argv)
                self.assertEqual((code, needle in text), (1, True))
        self.assertEqual(self.pairs, [])

    def test_a_saved_pilot_is_never_replaced_because_every_pilot_is_part_of_the_record(self):
        captured(pilot_team.main, ["--label", "pilot-t", "--model", "m", "--n", "1"])
        code, text = captured(pilot_team.main, ["--label", "pilot-t", "--model", "m", "--n", "1"])
        self.assertEqual((code, "already saved" in text), (1, True))

    def test_a_used_up_quota_saves_what_finished_and_says_so(self):
        calls = {"n": 0}

        def pair(question, index, model, timeout):
            calls["n"] += 1
            if calls["n"] == 2:
                raise llm.QuotaExhausted("the daily quota is used up")
            return self.fake_pair(question, index, model, timeout)

        with mock.patch.object(pilot_team, "run_pair", side_effect=pair):
            code, text = captured(pilot_team.main, ["--label", "pilot-q", "--model", "m", "--n", "4"])
        self.assertEqual(code, 1)
        self.assertIn("STOPPED: the daily quota is used up", text)
        saved = runner.load_results("pilot-q")
        self.assertEqual((len(saved["runs"]), saved["meta"]["complete"]), (2, False))

    def test_the_call_budget_stops_a_pilot_cleanly(self):
        code, text = captured(pilot_team.main, ["--label", "pilot-m", "--model", "m", "--n", "5", "--max-calls", "15"])
        self.assertEqual(code, 1)
        self.assertIn("--max-calls 15 reached", text)
        self.assertEqual(len(runner.load_results("pilot-m")["runs"]), 4)                  # 10 calls a question: two questions then 20 >= 15

    def test_the_call_budget_counts_requests_so_retries_stop_a_pilot_sooner(self):
        def pair(question, index, model, timeout):
            rows = self.fake_pair(question, index, model, timeout)
            rows[0]["requests"], rows[1]["requests"] = 9, 11                                  # 20 requests for what is 10 calls
            return rows

        with mock.patch.object(pilot_team, "run_pair", side_effect=pair):
            code, text = captured(pilot_team.main, ["--label", "pilot-r", "--model", "m", "--n", "5", "--max-calls", "15"])
        self.assertEqual(code, 1)
        self.assertIn("--max-calls 15 reached (20 requests used)", text)
        self.assertEqual(len(runner.load_results("pilot-r")["runs"]), 2)                      # one question: by calls (10) it would have run a second

    def test_a_timeout_that_is_not_a_finite_number_is_refused(self):
        for value in ("nan", "inf"):
            with self.subTest(timeout=value):
                code, text = captured(pilot_team.main, ["--label", "pilot-n", "--model", "m", "--timeout", value])
                self.assertEqual((code, "--timeout greater than 0" in text), (1, True))
        self.assertEqual(self.pairs, [])

    def test_show_prints_a_saved_pilot_and_explains_a_missing_one(self):
        captured(pilot_team.main, ["--label", "pilot-t", "--model", "m", "--n", "1"])
        code, text = captured(pilot_team.main, ["--show", "pilot-t"])
        self.assertEqual(code, 0)
        self.assertIn("=== pilot 'pilot-t'", text)
        code, text = captured(pilot_team.main, ["--show", "pilot-nope"])
        self.assertEqual((code, "No saved run" in text), (1, True))


if __name__ == "__main__":
    unittest.main()
