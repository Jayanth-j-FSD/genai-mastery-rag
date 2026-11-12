"""Week 10: every block in docs/week10/findings.md that says which command printed it must still equal that command's output."""
import contextlib
import io
import os
import re
import shlex
import sys
import unittest

import _testkit

ROOT = _testkit.ROOT
FINDINGS = os.path.join(ROOT, "docs", "week10", "findings.md")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_team_prediction          # noqa: E402
import race_team                      # noqa: E402

# "Command: `python scripts/race_team.py --show wk10`", a blank line, then a fenced block of what it printed.
BLOCK = re.compile(r"^Command: `(?P<command>[^`]+)`\n\n```text\n(?P<body>.*?)\n```", re.S | re.M)
SCRIPTS = {"scripts/race_team.py": race_team.main, "scripts/check_team_prediction.py": check_team_prediction.main}


def printed_by(command):
    parts = shlex.split(command)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = SCRIPTS[parts[1]](parts[2:])
    return code, out.getvalue()


def lines(text):
    return [line.rstrip() for line in text.strip().splitlines()]


def command_blocks(text):
    """[(command, what it printed)] for every block of the shape above in `text`."""
    return [(match["command"], match["body"]) for match in BLOCK.finditer(text)]


class BlockReaderTests(unittest.TestCase):
    """The reader of findings.md, tried on text of its own (it runs even while findings.md does not exist)."""

    def test_a_command_line_a_blank_line_and_a_fenced_block_make_one_block(self):
        text = "Numbers.\n\nCommand: `python scripts/race_team.py --show wk10`\n\n```text\nline one\nline two\n```\n\nMy reading.\n"
        self.assertEqual(command_blocks(text), [("python scripts/race_team.py --show wk10", "line one\nline two")])

    def test_numbers_typed_by_hand_with_no_command_above_them_make_no_block(self):
        self.assertEqual(command_blocks("The team used 4,200 tokens a run.\n\n```text\nagent 4200\n```\n"), [])


@unittest.skipUnless(os.path.exists(FINDINGS), "findings.md is written after the race")
class FindingsBlocksTests(unittest.TestCase):
    def blocks(self):
        with open(FINDINGS, encoding="utf-8") as handle:
            return command_blocks(handle.read())

    def test_the_file_holds_at_least_one_command_block_or_nothing_in_it_is_checked_against_a_command(self):
        self.assertTrue(self.blocks(), "findings.md has no 'Command: `...`' block, so none of its numbers is compared with what a command prints")

    def test_every_command_a_block_names_is_one_that_prints_without_a_model_call(self):
        for command, _body in self.blocks():
            parts = shlex.split(command)
            self.assertEqual(parts[0], "python", command)
            self.assertIn(parts[1], SCRIPTS, command)
            if parts[1] == "scripts/race_team.py":
                self.assertIn("--show", parts, f"{command} would run a race, not print one")
                self.assertNotIn("--save", parts, f"{command} would write a file")

    def test_every_block_is_what_its_command_prints_today(self):
        for command, body in self.blocks():
            code, printed = printed_by(command)
            self.assertEqual(code, 0, command)
            self.assertEqual(lines(printed), lines(body), f"findings.md is stale or was edited by hand: {command}")


if __name__ == "__main__":
    unittest.main()
