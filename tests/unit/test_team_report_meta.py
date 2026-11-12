"""Week 10: what the saved race file says about how it was run (resumes, arms added late, runs set aside, code history) and an empty reply as provider trouble."""
import unittest

import _testkit
from evals import team_prediction as prediction, team_report as report
from test_team_prediction import race as prediction_race
from test_team_report import crew, handoff, race, record

STARTED = "2026-10-12T10:00:00+05:30"


def small_race(**meta):
    """One task, both arms, one repeat, interleaved at 12 calls a minute, started on 12 October."""
    rows = [record("t1", "agent", 1), record("t1", "team", 1, team=crew())]
    return race(rows, interleaved=True, llm_rpm=12, started=STARTED, **meta)


def with_noise(**meta):
    rows = [record("t1", "agent", 1), record("t1", "team", 1, team=crew()), record("t1", "agent-2", 1)]
    return race(rows, arms=("agent", "team", "agent-2"), interleaved=True, llm_rpm=12, started=STARTED, **meta)


def text_of(saved):
    return "\n".join(report.format_report(saved))


def resume(at, arms_added=(), rpm=12, model="m", code=None):
    return {"at": at, "arms_added": list(arms_added), "rpm": rpm, "model": model, "code": code or {"git": "abc1234"}}


class ResumedRaceTests(unittest.TestCase):
    def test_a_race_resumed_twice_says_so_with_each_timestamp_and_what_the_session_added(self):
        text = text_of(small_race(resumed=[resume("2026-10-12T14:30:00+05:30"), resume("2026-10-13T09:00:00+05:30", arms_added=["agent-2"])]))
        self.assertIn("resumed 2 times:", text)
        self.assertIn("2026-10-12T14:30:00+05:30", text)
        self.assertIn("2026-10-13T09:00:00+05:30 (added agent-2; model m; 12 calls a minute)", text)

    def test_one_resume_is_not_called_times(self):
        self.assertIn("resumed 1 time:", text_of(small_race(resumed=[resume("2026-10-12T14:30:00+05:30")])))

    def test_a_resume_recorded_as_a_plain_timestamp_by_an_older_script_still_reads(self):
        text = text_of(small_race(resumed=["2026-10-12T14:30:00+05:30"]))
        self.assertIn("resumed 1 time: 2026-10-12T14:30:00+05:30", text)

    def test_a_race_that_was_never_resumed_prints_none_of_the_new_lines(self):
        for saved in (small_race(), small_race(resumed=[])):
            text = text_of(saved)
            for phrase in ("resumed", "set aside", "code history", "prediction document", "ran after the others"):
                self.assertNotIn(phrase, text)

    def test_sessions_at_different_rate_limits_and_a_session_on_another_model_are_warned_about(self):
        text = text_of(small_race(resumed=[resume("2026-10-12T14:30:00+05:30", rpm=6, model="other-model")]))
        self.assertIn("WARNING: the sessions ran at different rate limits (6 and 12 calls a minute)", text)
        self.assertIn("WARNING: the session at 2026-10-12T14:30:00+05:30 used model other-model, not m", text)
        quiet = text_of(small_race(resumed=[resume("2026-10-12T14:30:00+05:30")]))
        self.assertNotIn("WARNING", quiet)


class ArmsAddedLateTests(unittest.TestCase):
    def test_the_interleaving_sentence_names_the_arms_that_ran_after_the_others(self):
        text = text_of(with_noise(not_interleaved_arms=["agent-2"]))
        arms_line = next(line for line in text.splitlines() if line.startswith("arms:"))
        self.assertIn("runs interleaved, the order rotating", arms_line)
        self.assertIn("except agent-2, which ran after the others (added by a resume) and so were not interleaved with them", arms_line)

    def test_the_calibration_lines_say_the_noise_arm_ran_after_the_others_so_day_to_day_drift_is_in_it(self):
        text = text_of(with_noise(not_interleaved_arms=["agent-2"]))
        calibration = next(line for line in text.splitlines() if line.startswith("calibration, agent against agent-2"))
        self.assertIn("the same design twice", calibration)
        self.assertIn("this arm ran after the others, so day-to-day drift is in it", calibration)
        ratio_line = next(line for line in text.splitlines() if line.startswith("agent-2 / agent:"))
        self.assertIn("this arm ran after the others, so day-to-day drift is in it", ratio_line)

    def test_an_interleaved_noise_arm_gets_no_such_caveat(self):
        text = text_of(with_noise())
        self.assertNotIn("ran after the others", text)
        self.assertNotIn("day-to-day drift", text)

    def test_another_arm_added_late_does_not_put_the_caveat_on_the_noise_arm(self):
        text = text_of(with_noise(not_interleaved_arms=["workflow"]))
        calibration = next(line for line in text.splitlines() if line.startswith("calibration, agent against agent-2"))
        self.assertNotIn("day-to-day drift", calibration)
        self.assertIn("except workflow, which ran after the others", text)


class SetAsideAndHistoryTests(unittest.TestCase):
    def test_runs_set_aside_after_an_outage_are_counted_in_the_header(self):
        runs = [{"task_id": "t1", "approach": "team", "repeat": 1}] * 3
        self.assertIn("3 runs were set aside after provider trouble (an error, a spent quota or an empty reply) and run again", text_of(small_race(set_aside_runs=runs)))
        self.assertIn("1 run was set aside after provider trouble", text_of(small_race(set_aside_runs=runs[:1])))
        self.assertNotIn("set aside", text_of(small_race(set_aside_runs=[])))

    def test_every_run_set_aside_is_listed_with_its_arm_task_cause_and_the_start_of_its_answer(self):
        runs = [{"task_id": "t1", "approach": "team", "repeat": 2, "stop_reason": "empty_reply", "answer": "",
                 "set_aside_because": "the run ended on empty_reply"},
                {"task_id": "t2", "approach": "agent", "repeat": 1, "stop_reason": "error", "answer": "  partial   answer\nover two lines ",
                 "set_aside_because": "the run ended on error"}]
        text = text_of(small_race(set_aside_runs=runs))
        self.assertIn("set aside: team t1 #2: the run ended on empty_reply; stopped on empty_reply; no answer", text)
        self.assertIn("set aside: agent t2 #1: the run ended on error; stopped on error; answer began: partial answer over two lines", text)

    def test_a_long_list_of_set_aside_runs_is_cut_and_says_how_many_more_the_file_holds(self):
        runs = [{"task_id": f"t{n}", "approach": "team", "repeat": 1, "stop_reason": "error"} for n in range(report.SET_ASIDE_SHOWN + 3)]
        text = text_of(small_race(set_aside_runs=runs))
        self.assertEqual(text.count("  set aside: "), report.SET_ASIDE_SHOWN)
        self.assertIn("... and 3 more, in the saved file under set_aside_runs", text)

    def test_the_code_history_counts_the_session_the_race_began_in_as_well_as_each_resume(self):
        began = {"git": "aaa1111", "loop.py": "h1"}
        resumed = [{"at": "2026-10-12T14:30:00+05:30", "code": {"git": "aaa1111", "loop.py": "h1"}}]
        text = text_of(small_race(code=began, code_history=resumed))
        self.assertIn("code history: 2 stamps", text)                                 # the first session and the one resume, not just the resume
        self.assertIn("the code was the same in every session", text)
        changed = [{"at": "2026-10-12T14:30:00+05:30", "code": {"git": "bbb2222", "loop.py": "h2"}}]
        self.assertIn("differs from the first stamp in: git, loop.py", text_of(small_race(code=began, code_history=changed)))   # one resume now compares something

    def test_a_banner_for_a_stopped_race_prints_only_plain_ascii_even_when_the_provider_wrote_something_else(self):
        text = text_of(small_race(complete=False, stopped_because="the provider said: " + chr(0x2026) + " caf" + chr(0xe9) + " " + chr(0x2192)))
        banner = next(line for line in text.splitlines() if line.startswith("PARTIAL: the race stopped early"))
        self.assertTrue(banner.isascii(), banner)
        self.assertIn("the provider said:", banner)

    def test_a_run_set_aside_by_an_older_script_with_no_reason_still_reads(self):
        text = text_of(small_race(set_aside_runs=[{"task_id": "t1", "approach": "team", "repeat": 1}]))
        self.assertIn("set aside: team t1 #1: no reason recorded", text)

    def test_a_session_that_accepted_a_code_change_says_so_with_the_files_and_does_not_claim_it_was_harmless(self):
        entry = dict(resume("2026-10-12T14:30:00+05:30"), accepted_changes={"app/rag/retriever.py": {"was": "aaa", "now": "bbb"}})
        text = text_of(small_race(resumed=[entry]))
        self.assertIn("accepted changes to app/rag/retriever.py", text)
        self.assertIn("NOTE: the session at 2026-10-12T14:30:00+05:30 carried on after a change to app/rag/retriever.py", text)
        self.assertIn("nothing here shows the change did not matter", text)
        self.assertNotIn("NOTE", text_of(small_race(resumed=[resume("2026-10-12T14:30:00+05:30")])))

    def test_the_code_history_lists_every_stamp_and_what_changed_between_sessions(self):
        history = [{"at": STARTED, "code": {"git": "aaa1111", "team.py": "h1", "loop.py": "h2"}},
                   {"at": "2026-10-12T14:30:00+05:30", "code": {"git": "bbb2222", "team.py": "h1", "loop.py": "h3"}}]
        text = text_of(small_race(code_history=history))
        self.assertIn("code history: 2 stamps", text)
        self.assertIn("git aaa1111", text)
        self.assertIn("git bbb2222", text)
        self.assertIn("the code was not the same in every session (differs from the first stamp in: git, loop.py)", text)

    def test_an_unchanged_code_history_says_nothing_changed(self):
        same = {"git": "aaa1111", "team.py": "h1"}
        text = text_of(small_race(code_history=[{"at": STARTED, "code": same}, {"at": "2026-10-12T14:30:00+05:30", "code": dict(same)}]))
        self.assertIn("code history: 2 stamps", text)
        self.assertIn("the same in every session", text)
        self.assertNotIn("was not the same", text)

    def test_the_prediction_document_hash_recorded_at_the_start_is_in_the_header(self):
        self.assertIn("prediction document (docs/week10/prediction.md): git blob 0123abcd, recorded when the race started", text_of(small_race(prediction_doc="0123abcd")))


class OneModelOneDayTests(unittest.TestCase):
    def closing(self, **meta):
        return text_of(small_race(**meta)).split("Read before quoting a number:")[1]

    def test_a_race_on_one_calendar_date_says_one_model_on_one_day_and_never_a_quota_reset(self):
        for meta in ({}, {"resumed": [resume("2026-10-12T14:30:00+05:30")]}, {"resumed": ["2026-10-12T23:59:00+05:30"]}):
            with self.subTest(meta=meta):
                closing = self.closing(**meta)
                self.assertIn("one model on one day", closing)
                self.assertNotIn("quota reset", closing)

    def test_a_race_whose_timestamps_fall_on_two_dates_says_so_without_claiming_a_quota_reset(self):
        closing = self.closing(resumed=[resume("2026-10-13T09:00:00+05:30")])
        self.assertIn("ran on 2 calendar dates (local time: 2026-10-12, 2026-10-13)", closing)
        self.assertNotIn("quota reset", closing)                                       # the quota resets at midnight Pacific, which these local dates do not show
        self.assertNotIn("one model on one day", closing)

    def test_a_timestamp_that_is_not_a_date_is_ignored_not_a_crash(self):
        closing = self.closing(resumed=["not a date", {"at": None}, {}])
        self.assertIn("one model on one day", closing)


class PredictionDocumentTests(unittest.TestCase):
    def check(self, saved):
        rows, failed, dropped = prediction.check_prediction(saved)
        return "\n".join(prediction.format_prediction(rows, failed, dropped, "t"))

    def test_the_prediction_check_prints_the_document_hash_the_race_recorded(self):
        saved = prediction_race()
        saved["meta"]["prediction_doc"] = "0123abcd"
        self.assertIn("prediction document recorded with this race: git blob 0123abcd", self.check(saved))

    def test_a_race_without_one_prints_no_such_line(self):
        self.assertNotIn("prediction document", self.check(prediction_race()))


class EmptyReplyTests(unittest.TestCase):
    """An empty reply (no text and no tool request) is provider trouble: its unit leaves the clean set and the prediction's usable units."""

    def test_a_run_that_ended_on_an_empty_reply_is_provider_trouble_not_a_limit(self):
        stopped = record("a", "agent", 1, stop="empty_reply", finished=False, success=False)
        self.assertTrue(report.provider_trouble(stopped))
        self.assertFalse(report.hit_limit(stopped))
        self.assertIn("empty_reply", report.TROUBLE_STOPS)

    def test_a_hand_off_that_ended_on_an_empty_reply_is_provider_trouble_too(self):
        run = record("a", "team", 1, team=crew(handoffs=[handoff(stop="empty_reply", state="not_finished")]))
        self.assertTrue(report.provider_trouble(run))

    def test_the_unit_with_an_empty_reply_is_dropped_for_the_provider_in_the_clean_set(self):
        rows = [record("a", "agent", 1), record("a", "team", 1, stop="empty_reply", finished=False, success=False), record("b", "agent", 1), record("b", "team", 1)]
        kept, dropped = report.clean_units(race(rows))
        self.assertEqual((dropped["kept"], dropped["dropped_for_provider"], dropped["dropped_for_limits"]), (1, 1, 0))
        self.assertEqual({run["task_id"] for run in kept["runs"]}, {"b"})

    def test_the_prediction_does_not_read_a_unit_with_an_empty_reply(self):
        hit = lambda t, r: {"stop": "empty_reply", "success": False} if (t, r) == ("t7-conflict", 1) else {}       # noqa: E731
        _rows, _failed, dropped = prediction.check_prediction(prediction_race(agent=hit))
        self.assertEqual((dropped["kept"], dropped["dropped_for_provider"]), (26, 1))

    def test_the_clean_set_is_documented_as_dropping_empty_replies(self):
        self.assertIn("empty reply", report.clean_units.__doc__)
        self.assertIn("an empty reply", text_of(small_race()))


if __name__ == "__main__":
    unittest.main()
