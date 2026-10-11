"""The leak-window calibration script: how close honest saved answers come to the window, and how far a leak is above it."""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

import _testkit
from app.agent import defense, loop
from evals import runner

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import calibrate_leak_window                                     # noqa: E402


class CalibrateLeakWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(runner, "RESULTS_DIR", self.tmp))

    def save(self, stem, runs):
        with open(os.path.join(self.tmp, stem + ".json"), "w", encoding="utf-8") as handle:
            json.dump({"meta": {"label": stem}, "runs": runs}, handle)

    def call(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = calibrate_leak_window.main(list(args))
        return code, out.getvalue()

    def test_honest_answers_stay_under_the_window_and_a_prompt_leak_is_far_above_it(self):
        plain = calibrate_leak_window.squash(loop.SYSTEM_PROMPT.replace(defense.REFUSAL_SENTENCE, ""))
        phrase = plain[20:55].strip()                               # about 35 characters the prompt really contains
        self.save("trajectories-a", [{"approach": "agent", "answer": f"Per the rules: {phrase}."},
                                     {"approach": "workflow", "answer": "x " + plain[0:45]}])
        self.save("injection-b", [{"attack_id": "dir-prompt-leak", "answer": plain},
                                  {"attack_id": "ind-other", "answer": "Fine.", "draft_answer": f"Draft: {phrase}"}])
        code, out = self.call()
        self.assertEqual(code, 0)
        self.assertIn("Honest answers: 3 distinct texts", out)          # the workflow answer is not an agent answer
        self.assertIn(f"sharing {defense.LEAK_WINDOW} or more: 0", out)
        self.assertIn("texts sharing 30 or more: 2", out)
        leak = re.search(r"Prompt-leak attacks: 1 distinct texts; longest stretches shared: \[(\d+)\]", out)
        self.assertIsNotNone(leak, out)
        self.assertGreater(int(leak.group(1)), defense.LEAK_WINDOW)

    def test_only_reads_the_named_files_and_with_workflow_adds_the_workflow_answers(self):
        self.save("trajectories-a", [{"approach": "agent", "answer": "one"}, {"approach": "workflow", "answer": "two"}])
        self.save("trajectories-b", [{"approach": "agent", "answer": "three"}])
        self.assertIn("Honest answers: 1 distinct texts", self.call("--only", "trajectories-a")[1])
        self.assertIn("Honest answers: 2 distinct texts", self.call("--only", "trajectories-a", "--with-workflow")[1])
        self.assertIn("Honest answers: 2 distinct texts", self.call()[1])

    def test_files_that_are_not_trajectory_race_or_injection_runs_are_not_read_by_default(self):
        self.save("baseline", [{"approach": "agent", "answer": "a week 6 case"}])
        self.save("trajectories-a", [{"approach": "agent", "answer": "one"}])
        out = self.call()[1]
        self.assertIn("Read 1 saved file(s)", out)
        self.assertIn("Honest answers: 1 distinct texts", out)

    def test_a_missing_file_is_a_one_line_error(self):
        code, out = self.call("--only", "trajectories-missing")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
