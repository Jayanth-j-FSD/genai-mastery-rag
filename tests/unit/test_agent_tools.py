"""The agent's tools: search, exact arithmetic and exact dates. They run on input a MODEL wrote, so they must
refuse anything odd with advice the model can act on, and never execute anything."""
import unittest
from unittest import mock

import _testkit
from _testkit import build_index, chunk, isolated_index, patched_embeddings
from app.agent import tools
from app.agent.tools import ToolError, add_days, calculate, default_tools, search_policies
from app.config import settings


class CalculateTests(unittest.TestCase):
    def test_ordinary_arithmetic_is_exact(self):
        for expression, expected in (("25 - 10", "15"), ("14 - 10", "4"), ("2 + 3 * 4", "14"), ("(2 + 3) * 4", "20"),
                                     ("7 // 2", "3"), ("7 % 4", "3"), ("2 ** 10", "1024"), ("-5 + 8", "3"), ("+4", "4")):
            with self.subTest(expression=expression):
                self.assertEqual(calculate(expression), expected)

    def test_division_gives_a_float_rounded_for_reading(self):
        self.assertEqual(calculate("18 * 3 / 12"), "4.5")
        self.assertEqual(calculate("1 / 3"), "0.333333")
        self.assertEqual(calculate("10 / 2"), "5.0")

    def test_whitespace_is_ignored(self):
        self.assertEqual(calculate("  3   +   4 "), "7")

    def test_nothing_but_arithmetic_is_accepted(self):
        for hostile in ("__import__('os').system('echo hi')", "open('x')", "().__class__", "abs(-3)", "'a' + 'b'",
                        "[1, 2]", "x + 1", "1 if True else 2", "lambda: 1", "True + 1", "2 < 3", "not 1",
                        "1; import os", "exec('1')", "(1).real", "1j"):
            with self.subTest(expression=hostile), self.assertRaises(ToolError):
                calculate(hostile)

    def test_errors_are_advice_the_model_can_act_on(self):
        with self.assertRaises(ToolError) as caught:
            calculate("fourteen minus ten")
        self.assertIn("digits", str(caught.exception))
        with self.assertRaises(ToolError) as caught:
            calculate("abs(1)")
        self.assertIn("(14 - 10) * 2", str(caught.exception))

    def test_division_by_zero_and_huge_numbers_are_refused_not_crashes(self):
        for expression, fragment in (("1 / 0", "zero"), ("5 // 0", "zero"), ("5 % 0", "zero"), ("0 ** -1", "zero"),
                                     ("9 ** 9 ** 9", "exponent"), ("2 ** 101", "exponent"),
                                     ("((10 ** 100) ** 100) ** 100", "large")):
            with self.subTest(expression=expression), self.assertRaises(ToolError) as caught:
                calculate(expression)
            self.assertIn(fragment, str(caught.exception))

    def test_empty_none_wrong_type_and_overlong_input(self):
        for bad in ("", "   ", None, 12, ["1"], "1+" * 150):
            with self.subTest(bad=bad), self.assertRaises(ToolError):
                calculate(bad)


class AddDaysTests(unittest.TestCase):
    def test_the_two_task_dates(self):
        self.assertEqual(add_days("2026-11-03", 30), "2026-12-03 (Thursday)")
        self.assertEqual(add_days("2027-01-04", 9), "2027-01-13 (Wednesday)")

    def test_months_years_leap_days_and_going_backwards(self):
        self.assertEqual(add_days("2026-12-31", 1), "2027-01-01 (Friday)")
        self.assertEqual(add_days("2028-02-28", 1), "2028-02-29 (Tuesday)")                  # a leap year
        self.assertEqual(add_days("2027-02-28", 1), "2027-03-01 (Monday)")
        self.assertEqual(add_days("2026-03-01", -1), "2026-02-28 (Saturday)")
        self.assertEqual(add_days("2026-05-05", 0), "2026-05-05 (Tuesday)")

    def test_days_may_arrive_as_a_number_or_a_numeric_string(self):
        self.assertEqual(add_days("2026-01-01", "10"), add_days("2026-01-01", 10))

    def test_bad_dates_and_days_give_advice(self):
        for date in ("03/11/2026", "2026-13-01", "2026-02-30", "tomorrow", "", None, 20261103):
            with self.subTest(date=date), self.assertRaises(ToolError):
                add_days(date, 1)
        for days in ("soon", None, [1], 1.5 if False else "x"):
            with self.subTest(days=days), self.assertRaises(ToolError):
                add_days("2026-01-01", days)
        with self.assertRaises(ToolError) as caught:
            add_days("not a date", 1)
        self.assertIn("YYYY-MM-DD", str(caught.exception))

    def test_absurd_ranges_are_refused(self):
        with self.assertRaises(ToolError):
            add_days("2026-01-01", 100000)
        with self.assertRaises(ToolError):
            add_days("9999-12-31", 5)


class SearchPoliciesTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(isolated_index(dense_search="exact", retrieval_mode="dense"))
        self.enterContext(patched_embeddings())
        build_index([chunk("leave.md#0", "Employees receive 18 days of annual leave per calendar year. " + "annual leave days " * 80),
                     chunk("notice.md#0", "A permanent employee gives 30 calendar days of written notice."),
                     chunk("remote.md#0", "Remote work is allowed after 60 days of service.")])

    def test_passages_are_numbered_and_name_their_source(self):
        text = search_policies("annual leave days", 2)
        lines = text.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("[1] [source: leave.md] Employees receive 18 days"))
        self.assertTrue(lines[1].startswith("[2] [source: "))

    def test_long_passages_are_cut_so_one_result_cannot_eat_the_budget(self):
        first = search_policies("annual leave days", 1)
        self.assertLessEqual(len(first), 740)
        self.assertTrue(first.endswith("..."))

    def test_top_k_is_clamped_and_may_arrive_as_a_string(self):
        self.assertEqual(len(search_policies("leave", 99).splitlines()), 3)          # only 3 chunks exist; the cap is 6
        self.assertEqual(len(search_policies("leave", 0).splitlines()), 1)           # at least one
        self.assertEqual(len(search_policies("leave", "2").splitlines()), 2)

    def test_default_top_k_is_three(self):
        self.assertEqual(len(search_policies("leave").splitlines()), 3)

    def test_bad_arguments_give_advice(self):
        for bad_query in ("", "   ", None, 7):
            with self.subTest(query=bad_query), self.assertRaises(ToolError):
                search_policies(bad_query)
        with self.assertRaises(ToolError) as caught:
            search_policies("leave", "many")
        self.assertIn("between 1 and 6", str(caught.exception))

    def test_nothing_indexed_says_so(self):
        _testkit.store.reset_collection()
        self.assertIn("No passages found", search_policies("anything"))

    def test_it_uses_the_configured_retrieval_mode(self):
        with mock.patch.object(settings, "retrieval_mode", "hybrid"), \
                mock.patch.object(tools.retriever, "retrieve_for_mode", wraps=tools.retriever.retrieve_for_mode) as spy:
            search_policies("annual leave")
        self.assertEqual(spy.call_args.args[2], "hybrid")


class ToolDefinitionTests(unittest.TestCase):
    def test_the_spec_has_the_shape_the_provider_expects(self):
        for tool in default_tools():
            with self.subTest(tool=tool.name):
                spec = tool.spec()
                self.assertEqual(spec["type"], "function")
                self.assertEqual(spec["function"]["name"], tool.name)
                self.assertEqual(spec["function"]["parameters"]["type"], "object")
                self.assertTrue(set(spec["function"]["parameters"]["required"]) <= set(spec["function"]["parameters"]["properties"]))

    def test_there_are_three_tools_with_distinct_names(self):
        names = [t.name for t in default_tools()]
        self.assertEqual(names, ["search_policies", "calculate", "add_days"])

    def test_descriptions_say_when_to_use_the_tool_and_when_not_to(self):
        by_name = {t.name: t.description for t in default_tools()}
        self.assertIn("EVERY fact about a policy", by_name["search_policies"])
        self.assertIn("Do not use it for arithmetic", by_name["search_policies"])
        self.assertIn("instead of working it out in your head", by_name["calculate"])
        self.assertIn("Never count days on a calendar yourself", by_name["add_days"])

    def test_every_tool_is_read_only(self):
        # A tool can only read: none of these functions writes a file, a database row or a network request.
        import inspect
        for tool in default_tools():
            source = inspect.getsource(tool.function)
            for forbidden in ("open(", "write(", ".add(", "reset_collection", "requests.", "urllib", "subprocess", "os.system"):
                self.assertNotIn(forbidden, source, f"{tool.name} must stay read-only")


if __name__ == "__main__":
    unittest.main()
