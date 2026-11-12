"""Week 10: the derived numbers in the race report say what they are (a floor and a ceiling, documents counted once) and never read a price setting."""
import unittest
from unittest import mock

import _testkit
from app.config import settings
from evals import team_report as report
from test_team_report import crew, handoff, race, record, step


def manager_steps():
    """Manager prompts of 100, 160 and 200 tokens: the 60 between the first two is conversation history the manager picked up."""
    return [step("manager", None, 100, 10, local_n=1), step("manager", None, 160, 12, local_n=2), step("manager", None, 200, 14, local_n=3, kind="final")]


def two_hand_offs():
    first, second, last = manager_steps()
    steps = [first, step("researcher", 1, 60, 5), step("researcher", 1, 90, 9), second, step("calculator", 2, 40, 4), step("calculator", 2, 50, 5), last]
    return {"steps": steps, "team": crew(handoffs=[handoff("researcher", 1, calls=2, number=1), handoff("calculator", 2, calls=2, number=2)])}


class ForwardedContextTests(unittest.TestCase):
    def test_the_ceiling_is_the_managers_whole_prompt_at_each_asking_step_times_the_specialists_calls(self):
        self.assertEqual(report.forwarded_context_extra(two_hand_offs()), 100 * 2 + 160 * 2)

    def test_the_floor_is_only_the_history_the_manager_had_picked_up_by_then_times_the_specialists_calls(self):
        self.assertEqual(report.forwarded_context_floor(two_hand_offs()), (100 - 100) * 2 + (160 - 100) * 2)

    def test_the_floor_is_never_negative_and_never_above_the_ceiling(self):
        shrunk = two_hand_offs()
        shrunk["steps"][3] = step("manager", None, 80, 12, local_n=2)             # a later prompt smaller than the first (memory shortened it)
        self.assertEqual(report.forwarded_context_floor(shrunk), 0)
        for saved in (two_hand_offs(), shrunk):
            self.assertLessEqual(report.forwarded_context_floor(saved), report.forwarded_context_extra(saved))

    def test_a_refused_hand_off_and_a_run_without_a_team_add_nothing_to_either_number(self):
        refused = two_hand_offs()
        refused["team"] = crew(handoffs=[handoff(step_number=2, state="refused", calls=0)])
        self.assertEqual((report.forwarded_context_extra(refused), report.forwarded_context_floor(refused)), (0, 0))
        self.assertEqual((report.forwarded_context_extra({"steps": []}), report.forwarded_context_floor({"steps": []})), (0, 0))

    def test_a_manager_with_no_first_step_gives_a_floor_of_zero_not_a_guess(self):
        saved = two_hand_offs()
        saved["steps"] = [row for row in saved["steps"] if not (row["agent"] == "manager" and row["local_n"] == 1)]
        self.assertEqual(report.forwarded_context_floor(saved), 0)

    def test_the_report_prints_both_ends_and_calls_the_line_an_estimate_not_a_lower_bound(self):
        row = record("a", "team", 1, prompt=1000, completion=100, **two_hand_offs())
        text = "\n".join(report.format_report(race([record("a", "agent", 1), row])))
        self.assertIn("had every hand-off carried the manager's whole conversation", text)
        self.assertIn("between 120 and 520 more prompt tokens per run (12% to 52% on top of its 1000)", text)
        self.assertIn("not a lower bound", text)
        self.assertNotIn("at least 520", text)

    def test_the_arm_stats_keep_the_old_key_and_add_the_floor_beside_it(self):
        row = record("a", "team", 1, prompt=1000, completion=100, **two_hand_offs())
        stats = report.arm_stats(race([row], arms=("team",)), "team")
        self.assertEqual((stats["forwarded_extra_mean"], stats["forwarded_floor_mean"]), (520, 120))


class DocumentsCitedTests(unittest.TestCase):
    def documents(self, answer):
        return report.answer_features({"answer": answer, "steps": []})["documents"]

    def test_one_tag_listing_two_documents_counts_two_whichever_way_it_is_written(self):
        self.assertEqual(self.documents("16 weeks. [source: A.md; source: B.md]"), 2)
        self.assertEqual(self.documents("16 weeks. [source: A.md, B.md]"), 2)
        self.assertEqual(self.documents("16 weeks. [source: A.md; B.md]"), 2)

    def test_the_same_document_cited_twice_counts_once(self):
        self.assertEqual(self.documents("one [source: A.md] and again [source: A.md]"), 1)
        self.assertEqual(self.documents("[source: A.md; source: A.md]"), 1)

    def test_no_citation_and_no_answer_count_zero(self):
        self.assertEqual(self.documents("no tags here"), 0)
        self.assertEqual(self.documents(None), 0)

    def test_the_arm_mean_counts_documents_not_strings(self):
        rows = [record("a", "agent", 1, answer="[source: A.md; source: B.md]"), record("a", "agent", 2, answer="[source: A.md]")]
        self.assertAlmostEqual(report.arm_stats(race(rows, arms=("agent",)), "agent")["documents_mean"], 1.5)

    def test_the_saved_week_7_race_counts_the_same_documents_for_both_arms_as_the_defence_reader_does(self):
        from app.agent.defense import source_names
        from evals import runner
        saved = runner.load_results("race-race")
        for arm in ("agent", "workflow"):
            answers = [run["answer"] for run in saved["runs"] if run["approach"] == arm]
            expected = sum(len(source_names(answer)) for answer in answers) / len(answers)
            self.assertAlmostEqual(report.arm_stats(saved, arm)["documents_mean"], expected)


class PriceSettingTests(unittest.TestCase):
    """Someone who fills in PRICE_* in .env must not change a saved report or turn two tests red: the report states its own prices."""
    RUNS = [record("a", "agent", 1, True, prompt=100, completion=10), record("a", "agent", 2, True, prompt=200, completion=20)]

    def priced_settings(self):
        self.enterContext(mock.patch.object(settings, "price_input_per_million", 0.1))
        self.enterContext(mock.patch.object(settings, "price_output_per_million", 0.4))

    def test_arm_stats_without_a_price_says_not_stated_even_when_the_settings_have_prices(self):
        self.priced_settings()
        self.assertIsNone(report.arm_stats(race(self.RUNS), "agent")["cost_mean"])
        self.assertIsNone(report.arm_stats(race(self.RUNS), "agent")["cost_per_success"])

    def test_the_summary_and_the_report_without_a_price_ignore_the_settings_too(self):
        self.priced_settings()
        data = report.summary(race(self.RUNS, arms=("agent",)))
        self.assertFalse(data["priced"])
        self.assertIn("no price stated", data["prices"])
        text = "\n".join(report.format_report(race(self.RUNS, arms=("agent",))))
        self.assertIn("DOLLARS   prices: no price stated", text)
        self.assertNotIn("per passing run", text)

    def test_a_price_given_as_an_argument_still_works_whatever_the_settings_say(self):
        self.priced_settings()
        row = report.arm_stats(race(self.RUNS), "agent", 1.0, 2.0)
        self.assertAlmostEqual(row["cost_mean"], (150 * 1.0 + 15 * 2.0) / 1e6)
        self.assertIn("$1 per million input tokens", report.summary(race(self.RUNS, arms=("agent",)), 1.0, 2.0)["prices"])

    def test_only_one_price_stated_leaves_the_other_not_stated_not_filled_from_the_settings(self):
        self.priced_settings()
        data = report.summary(race(self.RUNS, arms=("agent",)), 1.0, None)
        self.assertIn("$0 per million output tokens", data["prices"])


if __name__ == "__main__":
    unittest.main()
