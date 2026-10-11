"""Week 10: app/pricing.py turns tokens into dollars only with a price you state (no network)."""
import contextlib
import io
import os
import re
import sys
import unittest
from unittest import mock

import _testkit
from pydantic import ValidationError

from app import pricing
from app.config import Settings, settings

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import race_team           # noqa: E402

OPTION = re.compile(r"--[a-z][a-z-]*")


class CostTests(unittest.TestCase):
    def test_a_million_tokens_cost_exactly_the_stated_price_per_million(self):
        self.assertAlmostEqual(pricing.cost_of(1_000_000, 0, 0.10, 0.40), 0.10)
        self.assertAlmostEqual(pricing.cost_of(0, 1_000_000, 0.10, 0.40), 0.40)

    def test_input_and_output_are_priced_separately_and_added(self):
        self.assertAlmostEqual(pricing.cost_of(4_000, 1_000, 0.10, 0.40), 0.0004 + 0.0004)

    def test_with_no_price_the_cost_is_none_never_zero(self):
        with mock.patch.object(settings, "price_input_per_million", 0.0), \
                mock.patch.object(settings, "price_output_per_million", 0.0):
            self.assertIsNone(pricing.cost_of(5_000, 500))
            self.assertFalse(pricing.is_priced())

    def test_the_settings_are_the_default_and_an_argument_wins_over_them(self):
        with mock.patch.object(settings, "price_input_per_million", 1.0), \
                mock.patch.object(settings, "price_output_per_million", 2.0):
            self.assertAlmostEqual(pricing.cost_of(1_000_000, 1_000_000), 3.0)
            self.assertAlmostEqual(pricing.cost_of(1_000_000, 1_000_000, 10.0, 0.0), 10.0)
            self.assertTrue(pricing.is_priced())

    def test_a_negative_token_count_or_price_is_refused(self):
        with self.assertRaises(ValueError):
            pricing.cost_of(-1, 0, 1.0, 1.0)
        for bad in (-0.5, float("nan"), float("inf")):
            with self.subTest(price=bad), self.assertRaises(ValueError):
                pricing.cost_of(10, 10, bad, 1.0)

    def test_the_description_always_says_it_is_an_assumption(self):
        self.assertIn("assumption", pricing.describe_prices(0.10, 0.40))
        self.assertIn("$0.1 per million input tokens", pricing.describe_prices(0.10, 0.40))
        self.assertIn("no price stated", pricing.describe_prices(0.0, 0.0))


def race_team_options():
    """Every option scripts/race_team.py really has, read from its own --help."""
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        try:
            race_team.main(["--help"])
        except SystemExit:
            pass
    return set(OPTION.findall(shown.getvalue()))


def price_paragraph():
    """The comment lines directly above PRICE_INPUT_PER_MILLION in .env.example."""
    with open(os.path.join(_testkit.ROOT, ".env.example"), encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    index = next(number for number, line in enumerate(lines) if line.startswith("PRICE_INPUT_PER_MILLION="))
    block = []
    while index > 0 and lines[index - 1].startswith("#"):
        index -= 1
        block.insert(0, lines[index])
    return "\n".join(block)


class GuidanceTests(unittest.TestCase):
    """No Week 10 command reads the PRICE_* settings: dollars come only from the options of `race_team.py --show`."""

    def test_the_options_the_report_says_to_use_are_real_options_of_the_race_script(self):
        real = race_team_options()
        for option in ("--show", "--price-in", "--price-out", "--price-source"):
            self.assertIn(option, real)

    def test_the_no_price_hint_names_exactly_the_price_options_of_the_race_script_and_no_setting(self):
        hint = pricing.describe_prices(0.0, 0.0)
        self.assertTrue(hint.startswith("no price stated, so cost is not reported ("))
        named = set(OPTION.findall(hint))
        self.assertEqual(named, {"--show", "--price-in", "--price-out", "--price-source"})
        self.assertTrue(named <= race_team_options())
        self.assertIn("scripts/race_team.py", hint)
        self.assertTrue(os.path.exists(os.path.join(_testkit.ROOT, "scripts", "race_team.py")))
        self.assertNotIn("PRICE_", hint)

    def test_no_code_but_the_pricing_module_and_the_settings_reads_the_price_settings_which_is_what_the_readme_says(self):
        readers = []
        for folder in ("app", "evals", "scripts"):
            for directory, _dirs, names in os.walk(os.path.join(_testkit.ROOT, folder)):
                for name in names:
                    path = os.path.join(directory, name)
                    if name.endswith(".py"):
                        with open(path, encoding="utf-8") as handle:
                            if re.search(r"price_(input|output)_per_million|current_prices", handle.read()):
                                readers.append(os.path.relpath(path, _testkit.ROOT).replace(os.sep, "/"))
        self.assertEqual(sorted(readers), ["app/config.py", "app/pricing.py"])
        with open(os.path.join(_testkit.ROOT, "docs", "week10", "README.md"), encoding="utf-8") as handle:
            self.assertIn("read by no Week 10 command", " ".join(handle.read().split()))

    def test_the_env_example_says_the_race_report_ignores_the_two_price_settings_and_names_the_real_options(self):
        paragraph = price_paragraph()
        self.assertIn("No Week 10 command reads", paragraph)
        named = set(OPTION.findall(paragraph))
        self.assertTrue({"--show", "--price-in", "--price-out", "--price-source"} <= named)
        self.assertTrue(named <= race_team_options())
        self.assertNotIn("the reports then show tokens only", paragraph)             # the old promise that setting them changes a report


class SettingTests(unittest.TestCase):
    def test_the_prices_default_to_unpriced(self):
        fresh = Settings(_env_file=None)
        self.assertEqual((fresh.price_input_per_million, fresh.price_output_per_million), (0.0, 0.0))

    def test_a_bad_price_fails_at_startup(self):
        for bad in (-1, float("inf"), float("nan")):
            with self.subTest(price=bad), self.assertRaises(ValidationError):
                Settings(_env_file=None, price_input_per_million=bad)
        self.assertEqual(Settings(_env_file=None, price_output_per_million=0.4).price_output_per_million, 0.4)


if __name__ == "__main__":
    unittest.main()
