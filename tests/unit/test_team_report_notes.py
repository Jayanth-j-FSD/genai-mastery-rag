"""Week 10: what the report's derived lines and notes claim is what the numbers support (evals/team_report.py)."""
import unittest

import _testkit
from evals import team_report as report
from test_team_report import call, crew, handoff, race, record, step


def text_of(saved, *prices):
    return "\n".join(report.format_report(saved, *prices))


def two_arm_race(agent_success=(True, True), **meta):
    rows = []
    for repeat, won in enumerate(agent_success, start=1):
        rows.append(record("t1", "agent", repeat, won, 100, 10, 2, steps=[step(None, None, 100, 10)], call_log=[call("m")]))
        rows.append(record("t1", "team", repeat, True, 300, 30, 5, steps=[step("manager", None, 100, 10), step("researcher", 1, 200, 20)],
                           team=dict(crew(), call_log=[call("m")])))
    return race(rows, interleaved=True, llm_rpm=12, **meta)


def closing(saved):
    return text_of(saved).split("Read before quoting a number:")[1]


class RequestsTests(unittest.TestCase):
    def test_every_attempt_in_the_per_call_records_counts_as_a_request_including_failed_calls(self):
        log = [call(attempts=1), call(attempts=3), call(status="error", attempts=4)]
        stats = report.arm_stats(race([record("a", "agent", 1, calls=2, call_log=log)], arms=("agent",)), "agent")
        self.assertEqual(stats["requests_mean"], 8.0)
        self.assertEqual(stats["calls_mean"], 2.0)                                  # the successful calls keep their own number
        self.assertAlmostEqual(stats["runs_per_day"], 500 / 8)

    def test_a_short_or_missing_call_log_never_lowers_the_count_below_the_successful_calls(self):
        short = record("a", "agent", 1, calls=5, call_log=[call(attempts=1)])
        none = record("a", "agent", 2, calls=5)
        self.assertEqual(report.arm_stats(race([short, none], arms=("agent",)), "agent")["requests_mean"], 5.0)

    def test_the_free_tier_line_is_marked_derived_says_what_a_request_is_and_names_the_quotas_basis(self):
        text = text_of(two_arm_race())
        line = next(line for line in text.splitlines() if line.startswith("free-tier cost"))
        self.assertIn("(derived;", line)
        explanation = text.splitlines()[text.splitlines().index(line) + 1]
        self.assertIn("every attempt in the per-call records", explanation)
        self.assertIn("lite-model figure measured in Week 8", explanation)
        self.assertIn("the model raced here, m,", explanation)


class NotesAndBoundsTests(unittest.TestCase):
    def test_the_instrument_note_says_cached_tokens_are_inside_the_prompt_counts_and_hidden_thinking_is_not(self):
        text = text_of(two_arm_race())
        self.assertIn("those are NOT in the token numbers below", text)
        self.assertIn("those tokens ARE inside the prompt counts below", text)
        self.assertNotIn("Neither is in the token numbers below", text)

    def test_the_cost_bound_is_for_one_input_price_and_one_output_price_and_says_cached_input_is_a_third(self):
        text = text_of(two_arm_race())
        self.assertIn("Whatever the prices, between", text)
        self.assertIn("for one input price and one output price", text)
        self.assertIn("a cheaper price for cached input is a third price", text)

    def test_the_cost_heading_claims_nothing_about_real_price_lists(self):
        text = text_of(two_arm_race())
        for claim in ("real price lists", "4 to 8", "typical of real"):
            self.assertNotIn(claim, text)
        self.assertIn("relative units", text)
        self.assertIn("No price is assumed", text)


class OverlapAndRereadTests(unittest.TestCase):
    def overlapping_race(self, seconds):
        two = crew(handoffs=[handoff("researcher", 1, api=seconds, number=1), handoff("calculator", 1, api=seconds, number=2)])
        return race([record("t1", "agent", 1), record("t1", "team", 1, team=two, steps=[step("manager", None, 100, 10)])])

    def test_the_overlap_line_says_elapsed_time_that_model_seconds_would_not_change_and_that_the_limiter_would_serialise(self):
        text = text_of(self.overlapping_race(2.0))
        line = next(line for line in text.splitlines() if line.startswith("derived: hand-offs the manager asked for in the same step"))
        self.assertIn("a run would have taken 2.0 seconds less elapsed time on average", line)
        self.assertIn("model seconds would not change", line)
        self.assertIn("rate limiter would serialise the calls anyway", line)
        self.assertNotIn("model seconds shorter", line)

    def test_two_hand_offs_asked_together_that_took_zero_seconds_are_not_called_one_at_a_time(self):
        line = next(line for line in text_of(self.overlapping_race(0.0)).splitlines() if line.startswith("derived: hand-offs the manager asked for"))
        self.assertIn("(1 of 1 runs asked for two or more at once)", line)
        self.assertNotIn("one at a time", line)

    def test_a_manager_that_asked_one_at_a_time_says_so(self):
        one_at_a_time = crew(handoffs=[handoff("researcher", 1, number=1), handoff("calculator", 2, number=2)])
        saved = race([record("t1", "agent", 1), record("t1", "team", 1, team=one_at_a_time)])
        self.assertIn("(the manager asked for one at a time)", text_of(saved))

    def test_the_reread_figure_is_an_upper_bound_because_memory_shortens_older_results(self):
        line = next(line for line in text_of(two_arm_race()).splitlines() if "re-reads the specialists' answers" in line)
        self.assertIn("at most about", line)
        self.assertIn("memory shortens older tool results", line)


class InstrumentLabelTests(unittest.TestCase):
    def test_retry_wait_is_labelled_for_what_it_sums_the_wait_of_retried_calls(self):
        text = text_of(two_arm_race())
        self.assertIn("wait of retried", text)
        self.assertNotIn("retry wait", text)
        self.assertIn("seconds of rate-limit pauses and back-off in calls that needed more than one attempt", text)

    def test_gaps_of_both_signs_are_not_netted_away_silently(self):
        log = [call(prompt=50, completion=50, total=120), call(prompt=50, completion=50, total=90)]       # +20 and -10
        saved = race([record("a", "agent", 1, call_log=log)], arms=("agent",))
        row = report.instrument_stats(saved, "agent")
        self.assertEqual((row["unexplained_tokens"], row["unexplained_abs"]), (10, 30))
        self.assertIn("agent: the provider's totals differ from prompt + completion in both directions (net +10, 30 in absolute value)", text_of(saved))

    def test_gaps_of_one_sign_print_no_extra_line(self):
        saved = race([record("a", "agent", 1, call_log=[call(prompt=50, completion=50, total=120)])], arms=("agent",))
        self.assertNotIn("in both directions", text_of(saved))


class TokensInNoStepTests(unittest.TestCase):
    """A provider reply with no choices is billed and counted, but the loop records its step with 0 tokens (Week 7 behaviour)."""

    def leaky(self):
        steps = [step(None, None, 300, 30), step(None, None, 0, 0, kind="error")]
        return race([record("a", "agent", 1, prompt=500, completion=50, steps=steps)], arms=("agent",))

    def test_the_tokens_a_run_was_billed_beyond_its_steps_are_counted(self):
        stats = report.arm_stats(self.leaky(), "agent")
        self.assertEqual((stats["no_step_tokens"], stats["no_step_runs"]), (220, 1))

    def test_the_report_prints_a_derived_line_only_for_an_arm_that_has_such_tokens(self):
        self.assertIn("derived: agent: 220 tokens over 1 run(s) were billed in model calls that left no step record", text_of(self.leaky()))
        self.assertNotIn("left no step record", text_of(two_arm_race()))

    def test_a_run_with_no_step_record_at_all_is_not_counted_as_all_tokens_in_no_step(self):
        stats = report.arm_stats(race([record("a", "agent", 1, prompt=500, completion=50)], arms=("agent",)), "agent")
        self.assertEqual((stats["no_step_tokens"], stats["no_step_runs"]), (0, 0))

    def test_the_conversations_docstring_no_longer_claims_a_zero_token_step_had_no_call_behind_it(self):
        self.assertNotIn("had no model call behind it", report.conversations.__doc__)


class ClosingParagraphTests(unittest.TestCase):
    def test_the_near_the_ceiling_sentence_prints_only_when_the_agent_rate_is_high(self):
        self.assertIn("only a loss can show", closing(two_arm_race((True, True))))
        self.assertNotIn("only a loss can show", closing(two_arm_race((True, False))))

    def test_the_run_count_is_the_measured_one_not_a_claim_that_the_runs_are_few(self):
        text = closing(two_arm_race((True, True)))
        self.assertIn("Each arm has 2 runs", text)
        self.assertNotIn("The runs are few", text)
        partial = race([record("a", "agent", 1), record("a", "agent", 2), record("a", "team", 1, team=crew())])
        self.assertIn("The arms have 2, 1 runs", closing(partial))

    def test_the_rate_limiter_sentence_is_only_there_when_the_race_recorded_a_rate_limit(self):
        self.assertIn("With a rate limit of 12 calls a minute, wall-clock time is mostly the shared rate limiter", closing(two_arm_race()))
        no_limit = two_arm_race()
        del no_limit["meta"]["llm_rpm"]
        self.assertNotIn("rate limiter", closing(no_limit))

    def test_the_sentences_that_do_not_depend_on_the_data_are_still_there(self):
        text = closing(two_arm_race())
        for kept in ("Parallel hand-offs were not tried", "Tokens are the provider's own counts", "The verdict is yours to write in docs/week10/findings.md"):
            self.assertIn(kept, text)


class PrintedAnswerTests(unittest.TestCase):
    """The FAILED RUNS block copies a model's words into a report that may be saved under docs/, which must stay plain ASCII."""
    CURLY = "I don" + chr(0x2019) + "t know " + chr(0x2014) + " " + chr(0x201C) + "quoted" + chr(0x201D) + " " + chr(0x2013) + " end" + chr(0x2026) + " " + chr(0x1F600)

    def saved(self):
        bad = record("a", "team", 1, False, answer=self.CURLY, team=crew())
        bad["failed_checks"] = ["missing " + chr(0x2018) + "16 weeks" + chr(0x2019)]
        return race([record("a", "agent", 1), bad])

    def test_typographic_quotes_and_dashes_are_printed_as_the_plain_ones_and_the_rest_as_a_question_mark(self):
        text = text_of(self.saved())
        self.assertTrue(all(ord(char) < 128 for char in text))
        self.assertIn("answer: I don't know - \"quoted\" - end... ?", text)
        self.assertIn("failed checks: missing '16 weeks'", text)

    def test_the_saved_data_keeps_the_answer_exactly_as_the_model_wrote_it(self):
        listed = report.failed_runs(self.saved(), ("agent", "team"))
        self.assertEqual(listed[0]["answer"], self.CURLY)


if __name__ == "__main__":
    unittest.main()
