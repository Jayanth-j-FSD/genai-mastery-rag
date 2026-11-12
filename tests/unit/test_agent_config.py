"""Week 7: the agent's stop-condition settings."""
import unittest

import _testkit  # noqa: F401  (puts the project root on sys.path)
from pydantic import ValidationError

from app.config import Settings


class AgentSettingsTests(unittest.TestCase):
    def test_the_defaults_bound_a_run_three_ways(self):
        settings = Settings(_env_file=None)
        self.assertEqual((settings.agent_max_steps, settings.agent_max_total_tokens, settings.agent_timeout_seconds),
                         (8, 40000, 120.0))

    def test_each_limit_can_be_overridden(self):
        settings = Settings(_env_file=None, agent_max_steps=3, agent_max_total_tokens=5000, agent_timeout_seconds=10)
        self.assertEqual((settings.agent_max_steps, settings.agent_max_total_tokens, settings.agent_timeout_seconds), (3, 5000, 10.0))

    def test_a_limit_that_would_end_every_run_at_once_is_rejected(self):
        for field, value in (("agent_max_steps", 0), ("agent_max_total_tokens", 0), ("agent_max_steps", -1),
                             ("agent_timeout_seconds", 0), ("agent_timeout_seconds", -5)):
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                Settings(_env_file=None, **{field: value})


if __name__ == "__main__":
    unittest.main()
