"""Week 10: the numbers for the team-versus-single-agent race (evals/team_report.py), checked on hand-built results."""
import json
import unittest

import _testkit
from evals import runner, team_report as report


def step(agent, handoff, prompt, completion, kind="tool", local_n=1, calls=()):
    return {"n": 1, "local_n": local_n, "kind": kind, "content": "", "tool_calls": list(calls), "seconds": 0.1,
            "tokens": {"prompt": prompt, "completion": completion}, "agent": agent, "handoff": handoff}


def search_call(query="notice period"):
    return {"name": "search_policies", "arguments": json.dumps({"query": query}), "observation": "[1] [source: a.md] text", "ok": True}


def record(task, arm, repeat, success=True, prompt=100, completion=10, calls=2, api=1.0, elapsed=3.0, wait=0.5,
           steps=None, team=None, finished=True, stop="final", answer="an answer", call_log=None, **more):
    row = {"task_id": task, "approach": arm, "repeat": repeat, "success": success, "finished": finished, "stop_reason": stop,
           "llm_calls": calls, "prompt_tokens": prompt, "completion_tokens": completion, "api_seconds": api,
           "elapsed_seconds": elapsed, "wait_seconds": wait, "steps": steps if steps is not None else [], "answer": answer}
    if team is not None:
        row["team"] = team
    if call_log is not None:
        row["call_log"] = call_log
    row.update(more)
    return row


def handoff(agent="researcher", step_number=1, state="finished", calls=2, api=1.0, stop="final", number=1):
    return {"handoff": number, "agent": agent, "state": state, "stop_reason": stop, "after_manager_step": step_number, "calls": calls, "api_seconds": api}


def crew(manager=(2, 200, 20), researcher=(2, 100, 10), calculator=(0, 0, 0), handoffs=None, warnings=(), errors=()):
    """The `team` field of a team record: per-agent (calls, prompt, completion) and the hand-offs."""
    def agent(values, count):
        return {"calls": values[0], "prompt_tokens": values[1], "completion_tokens": values[2], "api_seconds": 1.0, "wait_seconds": 0.0,
                "handoffs": count}
    return {"per_agent": {"manager": agent(manager, 0), "researcher": agent(researcher, 1), "calculator": agent(calculator, 0)},
            "handoffs": handoffs if handoffs is not None else [handoff()], "call_log": [], "warnings": list(warnings), "errors": list(errors)}


def call(served="m", attempts=1, wait=0.0, status="ok", prompt=10, completion=5, total=None, cached=None, reasoning=None):
    return {"served": served, "attempts": attempts, "wait_seconds": wait, "status": status, "prompt_tokens": prompt,
            "completion_tokens": completion, "total_tokens": total, "cached_tokens": cached, "reasoning_tokens": reasoning}


def race(runs, arms=("agent", "team"), complete=True, **meta):
    base = {"label": "t", "arms": list(arms), "tasks": sorted({r["task_id"] for r in runs}), "repeats": 3, "complete": complete,
            "models": {"agent": "m", "team": "m"}, "limits": {"max_steps": 8, "max_total_tokens": 40000, "timeout_seconds": 300.0}}
    base.update(meta)
    return {"meta": base, "runs": runs}


class StatisticsTests(unittest.TestCase):
    def test_the_wilson_interval_matches_the_textbook_values_and_stays_inside_zero_to_one(self):
        low, high = report.wilson(5, 10)
        self.assertAlmostEqual(low, 0.2366, places=3)
        self.assertAlmostEqual(high, 0.7634, places=3)
        self.assertEqual(report.wilson(0, 0), (0.0, 0.0))
        everything = report.wilson(10, 10)
        self.assertEqual(everything[1], 1.0)
        self.assertLess(everything[0], 1.0)
        self.assertEqual(report.wilson(0, 10)[0], 0.0)

    def test_more_runs_make_the_same_rate_less_uncertain(self):
        small, large = report.wilson(5, 10), report.wilson(50, 100)
        self.assertLess(large[1] - large[0], small[1] - small[0])

    def test_mean_and_median_of_nothing_are_zero_not_an_error(self):
        self.assertEqual((report.mean([]), report.median([])), (0.0, 0.0))
        self.assertEqual(report.median([3, 1, 2]), 2)
        self.assertEqual(report.median([4, 1, 2, 3]), 2.5)

    def test_the_exact_mcnemar_p_matches_the_binomial_sign_test(self):
        self.assertEqual(report.mcnemar_exact(0, 0), 1.0)
        self.assertAlmostEqual(report.mcnemar_exact(5, 0), 2 / 32)
        self.assertAlmostEqual(report.mcnemar_exact(0, 6), 2 / 64)
        self.assertEqual(report.mcnemar_exact(3, 3), 1.0)
        self.assertAlmostEqual(report.mcnemar_exact(1, 5), 2 * (1 + 6) / 64)
        self.assertAlmostEqual(report.mcnemar_exact(5, 1), report.mcnemar_exact(1, 5))             # it does not care which arm is which

    def test_five_discordant_pairs_can_never_reach_the_usual_threshold_and_six_can(self):
        self.assertGreater(report.mcnemar_exact(5, 0), 0.05)
        self.assertLess(report.mcnemar_exact(6, 0), 0.05)


class PromptBreakdownTests(unittest.TestCase):
    def test_a_single_agent_pays_its_opening_once_and_everything_after_it_is_later(self):
        steps = [step(None, None, 100, 10), step(None, None, 150, 12), step(None, None, 210, 8)]
        self.assertEqual(report.prompt_breakdown(steps), {"opening": 100, "later": 360, "shrank": 0})

    def test_a_team_pays_an_opening_for_the_manager_and_one_for_every_hand_off(self):
        steps = [step("manager", None, 100, 10), step("researcher", 1, 60, 5), step("researcher", 1, 90, 9), step("manager", None, 200, 14)]
        breakdown = report.prompt_breakdown(steps)
        self.assertEqual((breakdown["opening"], breakdown["later"]), (100 + 60, 90 + 200))
        self.assertEqual(breakdown["opening"] + breakdown["later"], 100 + 60 + 90 + 200)             # the two parts add up to the prompt tokens

    def test_a_call_whose_prompt_is_smaller_than_the_one_before_is_counted_because_later_is_then_not_all_re_sent_text(self):
        self.assertEqual(report.prompt_breakdown([step(None, None, 100, 10), step(None, None, 50, 5)]), {"opening": 100, "later": 50, "shrank": 1})

    def test_a_step_with_no_model_call_behind_it_is_skipped(self):
        steps = [step(None, None, 100, 10), step(None, None, 0, 0, kind="error")]
        self.assertEqual(report.prompt_breakdown(steps), {"opening": 100, "later": 0, "shrank": 0})
        self.assertEqual(report.prompt_breakdown([]), {"opening": 0, "later": 0, "shrank": 0})


class ArmStatsTests(unittest.TestCase):
    RUNS = [record("a", "agent", 1, True, prompt=100, completion=10, calls=2, api=1.0, elapsed=4.0, wait=1.0),
            record("a", "agent", 2, True, prompt=200, completion=20, calls=4, api=3.0, elapsed=9.0, wait=2.0),
            record("a", "agent", 3, False, prompt=300, completion=30, calls=9, api=5.0, elapsed=14.0, wait=3.0, finished=False, stop="max_steps")]

    def test_the_four_numbers_are_computed_per_arm(self):
        row = report.arm_stats(race(self.RUNS), "agent")
        self.assertEqual((row["runs"], row["success"], row["finished"]), (3, 2, 2))
        self.assertAlmostEqual(row["success_rate"], 2 / 3)
        self.assertEqual((row["calls_mean"], row["calls_max"], row["calls_over_8"], row["calls_over_12"]), (5.0, 9, 1, 0))
        self.assertEqual((row["prompt_mean"], row["completion_mean"], row["tokens_mean"], row["tokens_median"], row["tokens_max"]), (200, 20, 220, 220, 330))
        self.assertEqual((row["model_seconds_mean"], row["model_seconds_max"], row["elapsed_mean"], row["wait_mean"]), (3.0, 5.0, 9.0, 2.0))
        self.assertEqual(row["stop_reasons"], {"final": 2, "max_steps": 1})
        self.assertEqual((row["limit_stops"], row["provider_trouble"]), (1, 0))
        self.assertAlmostEqual(row["runs_per_day"], 500 / 5.0)

    def test_with_no_price_the_cost_is_none_and_with_one_it_is_tokens_times_price(self):
        results = race(self.RUNS)
        self.assertIsNone(report.arm_stats(results, "agent")["cost_mean"])
        row = report.arm_stats(results, "agent", 1.0, 2.0)                 # dollars per million tokens
        self.assertAlmostEqual(row["cost_mean"], (200 * 1.0 + 20 * 2.0) / 1e6)
        self.assertAlmostEqual(row["cost_per_success"], (600 * 1.0 + 60 * 2.0) / 1e6 / 2)

    def test_cost_per_success_is_none_when_nothing_succeeded(self):
        results = race([record("a", "agent", 1, False)])
        self.assertIsNone(report.arm_stats(results, "agent", 1.0, 1.0)["cost_per_success"])

    def test_an_arm_with_no_runs_is_all_zero_not_a_crash(self):
        row = report.arm_stats(race([]), "team")
        self.assertEqual((row["runs"], row["success_rate"], row["tokens_mean"], row["calls_max"]), (0, 0.0, 0.0, 0))

    def test_costs_in_relative_units_weight_output_tokens_by_the_ratio_for_every_ratio_in_the_grid(self):
        row = report.arm_stats(race([record("a", "agent", 1, prompt=100, completion=10), record("a", "agent", 2, prompt=300, completion=30)]), "agent")
        self.assertEqual(report.PRICE_RATIOS, (1, 2, 4, 8, 20))
        self.assertEqual(row["units_mean"], {1: 220.0, 2: 240.0, 4: 280.0, 8: 360.0, 20: 600.0})       # (100 + r * 10) and (300 + r * 30), averaged
        self.assertEqual(row["units_per_success"][4], 280.0)
        self.assertEqual(row["tokens_per_success"], 220.0)

    def test_the_answer_features_count_refusals_without_a_search_and_team_answers_without_a_hand_off(self):
        searched = [step("manager", None, 10, 1, calls=[search_call()])]
        rows = [record("a", "team", 1, answer="I don't know based on the provided documents.", team=crew(handoffs=[])),
                record("a", "team", 2, answer="16 weeks. [source: a.md] [source: b.md]", team=crew(handoffs=[])),
                record("a", "team", 3, answer="16 weeks. [source: a.md]", team=crew(), steps=searched)]
        row = report.arm_stats(race(rows, arms=("team",)), "team")
        self.assertEqual((row["refused"], row["refused_without_searching"], row["answered_without_hand_off"]), (1, 1, 1))
        self.assertAlmostEqual(row["documents_mean"], (0 + 2 + 1) / 3)
        self.assertIsNone(report.arm_stats(race(rows, arms=("team",)), "agent")["answered_without_hand_off"])


class RunKindTests(unittest.TestCase):
    def test_a_limit_stop_is_a_limit_stop_whether_it_was_the_manager_or_a_specialist_that_hit_it(self):
        self.assertTrue(report.hit_limit(record("a", "agent", 1, stop="timeout")))
        self.assertTrue(report.hit_limit(record("a", "team", 1, team=crew(handoffs=[handoff(stop="max_steps", state="not_finished")]))))
        self.assertTrue(report.hit_limit(record("a", "team", 1, team=crew(handoffs=[handoff(stop="budget", state="refused")]))))
        self.assertFalse(report.hit_limit(record("a", "team", 1, team=crew())))

    def test_provider_trouble_covers_errors_quota_warnings_internal_errors_and_a_failed_usage_check(self):
        self.assertTrue(report.provider_trouble(record("a", "agent", 1, stop="error")))
        self.assertTrue(report.provider_trouble(record("a", "team", 1, team=crew(handoffs=[handoff(stop="quota_exhausted", state="not_finished")]))))
        self.assertTrue(report.provider_trouble(record("a", "team", 1, team=crew(warnings=["usage mismatch"]))))
        self.assertTrue(report.provider_trouble(record("a", "team", 1, team=crew(errors=[{"agent": "researcher", "type": "KeyError"}]))))
        self.assertTrue(report.provider_trouble(record("a", "agent", 1, usage_warning="usage mismatch")))
        self.assertFalse(report.provider_trouble(record("a", "team", 1, team=crew())))


class InstrumentTests(unittest.TestCase):
    def test_served_models_retries_errors_and_hidden_tokens_come_from_the_per_call_records(self):
        log = [call("m-served", attempts=1, prompt=100, completion=10, total=110),
               call("m-served", attempts=2, wait=5.5, prompt=50, completion=5, total=75, cached=20, reasoning=20),
               call("m-served", status="error", prompt=0, completion=0)]
        row = report.instrument_stats(race([record("a", "agent", 1, call_log=log), record("a", "agent", 2)]), "agent")
        self.assertEqual((row["runs"], row["calls"], row["recorded"], row["served"]), (2, 3, 1, ["m-served"]))
        self.assertEqual((row["retried"], row["retry_wait"], row["errors"]), (1, 5.5, 1))
        self.assertEqual((row["total_reported"], row["unexplained_tokens"], row["cached_tokens"], row["reasoning_tokens"]), (2, 20, 20, 20))

    def test_the_team_keeps_its_call_log_inside_team_and_the_other_arms_beside_the_run(self):
        team_run = record("a", "team", 1, team=dict(crew(), call_log=[call("x"), call("x")]))
        self.assertEqual(report.instrument_stats(race([team_run], arms=("team",)), "team")["calls"], 2)

    def test_the_served_model_the_script_noted_for_a_run_counts_when_there_is_no_call_log(self):
        row = report.instrument_stats(race([record("a", "agent", 1, served_model="from-the-script")]), "agent")
        self.assertEqual(row["served"], ["from-the-script"])

    def test_arms_served_by_different_models_are_flagged(self):
        rows = [record("a", "agent", 1, call_log=[call("one")]), record("a", "team", 1, team=dict(crew(), call_log=[call("two")]))]
        self.assertTrue(report.summary(race(rows))["served_models_differ"])
        same = [record("a", "agent", 1, call_log=[call("one")]), record("a", "team", 1, team=dict(crew(), call_log=[call("one")]))]
        self.assertFalse(report.summary(race(same))["served_models_differ"])

    def test_warnings_and_internal_errors_are_counted_per_arm(self):
        rows = [record("a", "team", 1, team=crew(warnings=["usage mismatch"], errors=[{"agent": "researcher", "type": "KeyError"}])),
                record("a", "agent", 1, usage_warning="x")]
        data = report.summary(race(rows))
        self.assertEqual((data["instrument"]["team"]["warnings"], data["instrument"]["team"]["internal_errors"], data["instrument"]["agent"]["warnings"]), (1, 1, 1))
        self.assertEqual(data["internal_errors"], 1)


class TeamViewTests(unittest.TestCase):
    def test_per_agent_totals_and_shares_add_up_and_the_hand_off_endings_are_counted(self):
        rows = [record("a", "team", 1, team=crew(manager=(2, 200, 20), researcher=(2, 100, 10))),
                record("a", "team", 2, team=crew(manager=(3, 300, 30), researcher=(1, 50, 5), calculator=(2, 40, 4),
                                                 handoffs=[handoff("researcher"), handoff("calculator", state="not_finished", stop="max_steps")]))]
        view = report.per_agent_stats(race(rows, arms=("team",)))
        self.assertEqual(view["runs"], 2)
        self.assertEqual((view["agents"]["manager"]["calls"], view["agents"]["manager"]["tokens"]), (5, 550))
        self.assertEqual(view["agents"]["researcher"]["tokens"], 165)
        self.assertAlmostEqual(sum(row["token_share"] for row in view["agents"].values()), 1.0)
        self.assertEqual(view["handoff_states"], {"calculator:not_finished": 1, "researcher:finished": 2})

    def test_pairing_counts_the_same_task_and_repeat_under_both_arms_and_gives_the_exact_p(self):
        rows = [record("a", "agent", 1, True), record("a", "team", 1, True),
                record("a", "agent", 2, True), record("a", "team", 2, False),
                record("b", "agent", 1, False), record("b", "team", 1, True),
                record("b", "agent", 2, False), record("b", "team", 2, False),
                record("c", "agent", 1, True)]                                    # no team run: not a pair
        pairs = report.paired(race(rows))
        self.assertEqual({key: pairs[key] for key in ("both", "only_agent", "only_team", "neither", "pairs", "unpaired")},
                         {"both": 1, "only_agent": 1, "only_team": 1, "neither": 1, "pairs": 4, "unpaired": ["c repeat 1"]})
        self.assertEqual(pairs["p"], 1.0)

    def test_cells_only_one_arm_ran_are_listed_not_hidden(self):
        pairs = report.paired(race([record("a", "agent", 1), record("a", "team", 1), record("a", "agent", 2)]))
        self.assertEqual((pairs["pairs"], pairs["unpaired"]), (1, ["a repeat 2"]))

    def test_per_task_grid_lists_every_arm_that_ran_the_task(self):
        rows = [record("a", "agent", 1, True, prompt=100, completion=0, calls=2), record("a", "agent", 2, False, prompt=300, completion=0, calls=4),
                record("a", "team", 1, True, prompt=1000, completion=0, calls=9)]
        grid = report.per_task(race(rows), ("agent", "team"))
        self.assertEqual(grid["a"]["agent"], {"ok": 1, "runs": 2, "calls": 3.0, "tokens": 200.0})
        self.assertEqual(grid["a"]["team"]["tokens"], 1000.0)

    def test_the_team_by_task_view_averages_hand_offs_and_calls_per_run(self):
        rows = [record("a", "team", 1, team=crew(manager=(2, 0, 0), researcher=(2, 0, 0), calculator=(0, 0, 0))),
                record("a", "team", 2, team=crew(manager=(4, 0, 0), researcher=(2, 0, 0), calculator=(2, 0, 0)))]
        rows[1]["team"]["per_agent"]["calculator"]["handoffs"] = 1
        view = report.team_by_task(race(rows, arms=("team",)))["a"]
        self.assertEqual((view["runs"], view["calls"]["manager"], view["calls"]["calculator"]), (2, 3.0, 1.0))
        self.assertEqual((view["handoffs"]["researcher"], view["handoffs"]["calculator"]), (1.0, 0.5))

    def test_calls_per_hand_off_say_how_many_model_calls_a_specialist_needs(self):
        rows = [record("a", "team", 1, team=crew(researcher=(6, 0, 0), calculator=(4, 0, 0)))]
        rows[0]["team"]["per_agent"]["calculator"]["handoffs"] = 2
        agents = report.per_agent_stats(race(rows, arms=("team",)))["agents"]
        self.assertEqual((agents["researcher"]["calls_per_handoff"], agents["calculator"]["calls_per_handoff"], agents["manager"]["calls_per_handoff"]), (6.0, 2.0, None))


class DerivedNumbersTests(unittest.TestCase):
    def manager_steps(self):
        first, last = step("manager", None, 100, 10, local_n=1), step("manager", None, 200, 14, local_n=2, kind="final")
        return first, last

    def test_a_hand_off_that_carried_the_whole_conversation_would_have_re_sent_the_managers_prompt_on_every_specialist_call(self):
        first, last = self.manager_steps()
        steps = [first, step("researcher", 1, 60, 5), step("researcher", 1, 90, 9), last]
        record_ = {"steps": steps, "team": crew(handoffs=[handoff(step_number=1, calls=2)])}
        self.assertEqual(report.forwarded_context_extra(record_), 100 * 2)                 # the manager's prompt at step 1, twice
        self.assertEqual(report.forwarded_context_extra({"steps": steps, "team": crew(handoffs=[handoff(step_number=1, state="refused", calls=0)])}), 0)
        self.assertEqual(report.forwarded_context_extra({"steps": steps}), 0)             # not a team run

    def test_the_manager_re_reads_each_specialist_answer_on_every_manager_call_after_the_one_that_asked(self):
        first, last = self.manager_steps()
        answer = step("researcher", 1, 90, 25, kind="final")                               # a 25-token answer
        record_ = {"steps": [first, step("researcher", 1, 60, 5), answer, last], "team": crew(handoffs=[handoff(step_number=1)])}
        self.assertEqual(report.handoff_answers_reread(record_), 25 * 1)                  # one later manager call (local step 2)
        self.assertEqual(report.handoff_answers_reread({"steps": [first, answer, last]}), 0)

    def test_hand_offs_asked_for_in_one_step_could_have_overlapped_and_the_saving_is_the_sum_minus_the_longest(self):
        same_step = {"team": crew(handoffs=[handoff("researcher", 1, api=2.0, number=1), handoff("calculator", 1, api=3.0, number=2)])}
        self.assertAlmostEqual(report.overlap_saving(same_step), 2.0)
        one_at_a_time = {"team": crew(handoffs=[handoff("researcher", 1, api=2.0), handoff("calculator", 2, api=3.0)])}
        self.assertEqual(report.overlap_saving(one_at_a_time), 0)
        refused = {"team": crew(handoffs=[handoff("researcher", 1, api=2.0), handoff("calculator", 1, state="refused", api=9.0)])}
        self.assertEqual(report.overlap_saving(refused), 0)
        self.assertEqual(report.overlap_saving({}), 0.0)

    def test_a_search_that_repeats_an_earlier_one_in_the_same_run_counts_even_across_hand_offs(self):
        steps = [step("researcher", 1, 10, 1, calls=[search_call("Notice  Period")]), step("researcher", 2, 10, 1, calls=[search_call("notice period")]),
                 step("researcher", 2, 10, 1, calls=[search_call("sick leave")])]
        self.assertEqual(report.duplicate_searches({"steps": steps}), 1)
        self.assertEqual(report.duplicate_searches({"steps": []}), 0)

    def test_every_task_has_a_dependency_shape_and_the_nine_split_three_ways_three_times(self):
        shapes = {task_id: report.task_shape(task_id) for task_id in (
            "t7-single-lookup", "t7-carry-forward-sum", "t7-notice-end-date", "t7-leave-end-date", "t7-remote-eligibility",
            "t7-two-documents", "t7-conflict", "t7-cloud-two-sections", "t7-unanswerable")}
        self.assertEqual([task for task, shape in shapes.items() if shape == "dependent"],
                         ["t7-carry-forward-sum", "t7-notice-end-date", "t7-leave-end-date"])
        self.assertEqual([task for task, shape in shapes.items() if shape == "independent"],
                         ["t7-two-documents", "t7-conflict", "t7-cloud-two-sections"])
        self.assertEqual([task for task, shape in shapes.items() if shape == "single"],
                         ["t7-single-lookup", "t7-remote-eligibility", "t7-unanswerable"])
        self.assertEqual(report.task_shape("not-a-task"), "unknown")

    def test_every_failed_run_is_listed_with_its_checks_and_the_start_of_its_answer(self):
        bad = record("a", "team", 2, False, stop="max_steps", finished=False)
        bad.update(failed_checks=["missing 16 weeks"], answer="x" * 500)
        listed = report.failed_runs(race([record("a", "team", 1, True), bad, record("b", "agent", 1, False)]), ("agent", "team"))
        self.assertEqual([(row["arm"], row["task"], row["repeat"]) for row in listed], [("agent", "b", 1), ("team", "a", 2)])
        self.assertEqual(listed[1]["failed_checks"], ["missing 16 weeks"])
        self.assertEqual(len(listed[1]["answer"]), 200)


class PathTests(unittest.TestCase):
    def hand_off_call(self):
        return {"name": "ask_policy_researcher", "arguments": json.dumps({"question": "q"}), "observation": "ans", "ok": True}

    def test_a_teams_manager_calls_are_dropped_for_the_grader_and_the_specialists_calls_stay_in_order(self):
        steps = [step("manager", None, 10, 1, calls=[self.hand_off_call()]), step("researcher", 1, 10, 1, calls=[search_call("a")]),
                 step("researcher", 1, 10, 1, calls=[search_call("b")]), step("manager", None, 10, 1, local_n=2, kind="final")]
        view = report.path_view(record("t", "team", 1, steps=steps, team=crew()))
        self.assertEqual([[call["name"] for call in s["tool_calls"]] for s in view["steps"]], [[], ["search_policies"], ["search_policies"], []])
        self.assertEqual(len(steps[0]["tool_calls"]), 1)                                        # the saved record itself is not changed
        plain = record("t", "agent", 1, steps=steps)
        self.assertIs(report.path_view(plain), plain)

    def test_the_week_8_grader_is_run_on_every_arm_and_the_table_adds_up(self):
        found = dict(search_call("leave"), observation="[1] [source: Acme-Leave-Policy-2026.md] 16 weeks of paid parental leave")
        searched = [step(None, None, 10, 1, calls=[found])]
        rows = [record("t7-single-lookup", "agent", 1, True, steps=searched, answer="16 weeks. [source: Acme-Leave-Policy-2026.md]"),
                record("t7-single-lookup", "agent", 2, True, steps=[], answer="16 weeks."),            # right answer, no search: the wrong path
                record("t7-single-lookup", "team", 1, False, steps=[step("manager", None, 10, 1, calls=[self.hand_off_call()]),
                                                                    step("researcher", 1, 10, 1, calls=[found])], team=crew())]
        paths = report.path_stats(race(rows), ("agent", "team"))
        self.assertEqual(paths["agent"]["runs"], 2)
        self.assertEqual(paths["agent"]["gap"]["right-answer-wrong-path"], 1)
        self.assertEqual(paths["agent"]["modes"].get("skipped-tool"), 1)
        self.assertEqual(paths["team"]["runs"], 1)
        self.assertEqual(sum(paths["team"]["gap"].values()), 1)
        self.assertNotIn("wrong-tool", paths["team"]["modes"])                                    # the hand-off tool is not a wrong tool

    def test_the_report_says_the_path_section_is_exploratory_and_was_written_for_one_agent(self):
        text = "\n".join(report.format_report(race([record("t7-single-lookup", "agent", 1)], arms=("agent",))))
        self.assertIn("PATH", text)
        self.assertIn("exploratory", text)
        self.assertIn("written for ONE agent", text)


class CleanUnitsTests(unittest.TestCase):
    def rows(self):
        return [record("a", "agent", 1), record("a", "team", 1),                                                       # clean
                record("a", "agent", 2), record("a", "team", 2, stop="max_steps", finished=False, success=False),    # a limit
                record("b", "agent", 1, stop="error", finished=False, success=False), record("b", "team", 1),         # the provider
                record("b", "agent", 2)]                                                                              # incomplete: no team run

    def test_units_where_any_run_hit_a_limit_or_the_provider_or_where_an_arm_is_missing_are_dropped_and_counted(self):
        kept, dropped = report.clean_units(race(self.rows()))
        self.assertEqual(dropped, {"units": 4, "kept": 1, "dropped_for_limits": 1, "dropped_for_provider": 1, "incomplete": 1})
        self.assertEqual({(run["task_id"], run["repeat"], run["approach"]) for run in kept["runs"]}, {("a", 1, "agent"), ("a", 1, "team")})
        self.assertEqual(kept["meta"]["arms"], ["agent", "team"])

    def test_the_sensitivity_section_says_how_many_units_it_kept(self):
        text = "\n".join(report.format_report(race(self.rows())))
        self.assertIn("SENSITIVITY", text)
        self.assertIn("1 of 4 units kept: 1 dropped for limits, 1 for the provider, 1 incomplete", text)

    def test_a_provider_problem_wins_over_a_limit_so_a_unit_is_counted_once(self):
        rows = [record("a", "agent", 1, stop="error", finished=False, success=False), record("a", "team", 1, stop="max_steps", finished=False, success=False)]
        _kept, dropped = report.clean_units(race(rows))
        self.assertEqual((dropped["dropped_for_provider"], dropped["dropped_for_limits"]), (1, 0))


class CostBoundTests(unittest.TestCase):
    BASE = {"prompt_mean": 100.0, "completion_mean": 10.0}
    OTHER = {"prompt_mean": 300.0, "completion_mean": 15.0}

    def test_the_ratio_is_bracketed_by_the_input_and_output_token_ratios(self):
        self.assertEqual(report.cost_ratio_bounds(self.BASE, self.OTHER), (1.5, 3.0))

    def test_whatever_the_prices_the_real_cost_ratio_lies_inside_the_bounds(self):
        low, high = report.cost_ratio_bounds(self.BASE, self.OTHER)
        for price_in, price_out in ((0.1, 0.4), (1.0, 0.0), (0.0, 1.0), (5.0, 1.0), (0.01, 100.0)):
            real = (price_in * 300 + price_out * 15) / (price_in * 100 + price_out * 10)
            self.assertTrue(low - 1e-9 <= real <= high + 1e-9, (price_in, price_out, real))

    def test_a_baseline_with_nothing_to_divide_by_gives_no_bound(self):
        self.assertIsNone(report.cost_ratio_bounds({"prompt_mean": 0.0, "completion_mean": 1.0}, self.OTHER))


class ReportTests(unittest.TestCase):
    def full_race(self, **meta):
        rows = []
        for repeat in (1, 2):
            rows += [record("t1", "agent", repeat, True, 100, 10, 2, steps=[step(None, None, 100, 10)], call_log=[call("m")]),
                     record("t1", "team", repeat, repeat == 1, 300, 30, 5, finished=repeat == 1, stop="final" if repeat == 1 else "max_steps",
                            steps=[step("manager", None, 100, 10), step("researcher", 1, 200, 20)], team=dict(crew(), call_log=[call("m")])),
                     record("t1", "agent-2", repeat, True, 110, 11, 2, steps=[step(None, None, 110, 11)], call_log=[call("m")])]
        return race(rows, arms=("agent", "team", "agent-2"), interleaved=True, llm_rpm=12, **meta)

    def test_the_report_has_every_section(self):
        text = "\n".join(report.format_report(self.full_race()))
        for heading in ("INSTRUMENT", "QUALITY", "SPEED", "TOKENS", "COST", "DOLLARS", "THE TEAM, BY AGENT", "THE TEAM, BY TASK", "PER TASK",
                        "BEHAVIOUR", "SENSITIVITY", "FAILED RUNS", "paired by task and repeat", "exact McNemar p", "calibration, agent against agent-2",
                        "had every hand-off carried the manager's whole conversation", "re-reads the specialists' answers", "free-tier cost"):
            self.assertIn(heading, text)
        self.assertIn("runs interleaved", text)
        self.assertIn("The verdict is yours", text)

    def test_the_report_never_calls_a_winner_and_never_keys_a_claim_to_one_noise_gap(self):
        text = "\n".join(report.format_report(self.full_race())).lower()
        for word in ("winner", "better than", "worse than", "outperform", "beats ", "noise floor"):
            self.assertNotIn(word, text)
        for glyph in ("\u2014", "\u2013", "\u2019", "\u201c", "\u201d"):
            self.assertNotIn(glyph, text)

    def test_without_a_price_it_says_so_and_still_gives_the_bounds_and_the_requests(self):
        text = "\n".join(report.format_report(self.full_race()))
        self.assertIn("DOLLARS   prices: no price stated", text)
        self.assertIn("Whatever the prices, between 3.00x and 3.00x", text)
        self.assertIn("relative units", text)
        self.assertIn("r=20 3.00x", text)
        self.assertIn("5.0 requests a run, 100 runs in a 500-request day", text)

    def test_with_a_price_it_shows_dollars_calls_them_an_assumption_and_says_where_the_price_came_from(self):
        text = "\n".join(report.format_report(self.full_race(), 0.10, 0.40, "the provider's price page on 2026-10-12"))
        self.assertIn("per passing run", text)
        self.assertIn("assumption", text)
        self.assertIn("$0.1 per million input tokens", text)
        self.assertIn("source: the provider's price page on 2026-10-12", text)

    def test_a_partial_race_says_so_first(self):
        text = "\n".join(report.format_report(self.full_race(complete=False, stopped_because="quota used up")))
        self.assertIn("PARTIAL: the race stopped early (quota used up)", text)

    def test_an_internal_error_is_called_out_and_the_reader_is_told_not_to_read_the_numbers(self):
        race_ = self.full_race()
        race_["runs"][1]["team"]["errors"] = [{"agent": "researcher", "type": "KeyError"}]
        text = "\n".join(report.format_report(race_))
        self.assertIn("INTERNAL ERRORS: 1", text)
        self.assertIn("race again before reading any number below", text)

    def test_arms_served_by_different_models_get_a_warning(self):
        race_ = self.full_race()
        race_["runs"][1]["team"]["call_log"] = [call("other-model")]
        self.assertIn("WARNING: the arms were served by different models", "\n".join(report.format_report(race_)))

    def test_the_summary_carries_the_ratios_the_pairs_and_the_calibration(self):
        data = report.summary(self.full_race())
        self.assertAlmostEqual(data["team_over_agent"]["calls"], 2.5)
        self.assertAlmostEqual(data["team_over_agent"]["tokens"], 3.0)
        self.assertEqual(data["paired"]["pairs"], 2)
        self.assertEqual(data["calibration"]["paired"]["pairs"], 2)
        self.assertEqual(data["calibration"]["paired"]["p"], 1.0)

    def test_a_race_without_a_team_arm_still_reports(self):
        text = "\n".join(report.format_report(race([record("t1", "agent", 1)], arms=("agent",))))
        self.assertIn("QUALITY", text)
        self.assertNotIn("THE TEAM, BY AGENT", text)

    def test_the_week_7_race_file_in_the_repo_still_reads_so_old_results_are_not_stranded(self):
        saved = runner.load_results("race-race")
        text = "\n".join(report.format_report(saved))
        self.assertIn("agent", text)
        self.assertIn("workflow", text)
        self.assertIn("not recorded", text)                                          # that race predates the per-call records


if __name__ == "__main__":
    unittest.main()
