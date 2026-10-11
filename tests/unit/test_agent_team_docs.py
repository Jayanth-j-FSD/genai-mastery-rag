"""Week 10: what the README and the docstrings of the team say about the team must be true of the code they describe."""
import os
import re
import unittest

import _testkit
from app.agent import team
from test_agent_loop import asks, says
from test_agent_team import IDK, TeamTestCase, tool_names, to_researcher

ROOT = _testkit.ROOT
README = os.path.join(ROOT, "docs", "week10", "README.md")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class DocumentedFactsTests(TeamTestCase):
    def test_the_teamrun_docstring_names_every_key_of_the_team_record_a_real_run_has(self):
        run, _client = self.run_team([asks(to_researcher("m1")), says("30 days"), says("done")])
        self.assertEqual(len(run.team), 5)
        for key in run.team:
            self.assertIn(f"`{key}`", team.TeamRun.__doc__)

    def test_the_readme_names_every_tool_the_manager_is_offered_besides_the_hand_offs(self):
        _run, client = self.run_team([says(IDK)])
        offered = tool_names(client.requests[0])
        extra = [name for name in offered if name not in {spec["tool"] for spec in team.SPECIALISTS.values()}]
        self.assertEqual(extra, ["remember"])                                    # the loop's own scratchpad tool, which every agent keeps
        bullet = next(line for line in read(README).splitlines() if line.startswith("- The **manager**"))
        for name in extra:
            self.assertIn(name, bullet)


class AgentCardTests(unittest.TestCase):
    def test_no_running_code_calls_agent_summary_which_is_what_its_docstring_and_the_readme_say(self):
        callers = []
        for folder in ("app", "evals", "scripts"):
            for directory, _dirs, names in os.walk(os.path.join(ROOT, folder)):
                for name in names:
                    path = os.path.join(directory, name)
                    if name.endswith(".py") and re.search(r"(?<!def )\bagent_summary\(", read(path)):
                        callers.append(os.path.relpath(path, ROOT).replace(os.sep, "/"))
        self.assertEqual(callers, [])

    def test_the_readme_does_not_say_the_agent_card_words_the_hand_off_tools(self):
        text = " ".join(read(README).split())                      # one line, so a sentence the README wraps is still found
        self.assertNotIn("used to word the hand-off tools", text)
        self.assertIn("nothing in the running team calls it", text)


if __name__ == "__main__":
    unittest.main()
