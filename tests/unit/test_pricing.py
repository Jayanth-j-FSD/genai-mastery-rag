"""Week 10: app/pricing.py turns tokens into dollars only with a price you state (no network)."""
import unittest
from unittest import mock

import _testkit
from pydantic import ValidationError

from app import pricing
from app.config import Settings, settings


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
