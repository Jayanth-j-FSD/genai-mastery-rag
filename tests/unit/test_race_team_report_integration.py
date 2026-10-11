"""Week 10: what the race script saves is what the report and the prediction check print (a race stopped, resumed with the noise arm, then read)."""
import os
import sys
import unittest

import _testkit
from test_race_team import BLOB, captured
from test_race_team_resume import SavedRaceCase, race_team

sys.path.insert(0, os.path.join(_testkit.ROOT, "scripts"))
import check_team_prediction        # noqa: E402


class StoppedThenResumedTests(SavedRaceCase):
    """The race script writes the keys of a resume (resumed, not_interleaved_arms, code_history, prediction_doc) and the report reads them:
    each was written by a different piece of code, so only a race that goes through both can show they agree on the names."""

    def setUp(self):
        super().setUp()
        self.partial_race()                                          # the quota cut it short after three runs
        self.assertEqual(self.race("--resume", "--noise")[0], 0)

    def show(self):
        code, text = captured(race_team.main, ["--show", "t"])
        self.assertEqual(code, 0)
        return text

    def test_the_saved_race_holds_the_keys_the_resume_writes(self):
        meta = self.saved()["meta"]
        self.assertEqual(len(meta["resumed"]), 1)
        self.assertTrue(set(meta["resumed"][0]) >= {"at", "arms_added", "rpm", "model", "code"})
        self.assertEqual(meta["resumed"][0]["arms_added"], ["agent-2"])
        self.assertEqual(meta["not_interleaved_arms"], ["agent-2"])
        self.assertEqual(meta["prediction_doc"], BLOB)
        self.assertIn("code_history", meta)

    def test_the_report_says_the_race_was_resumed_and_which_arm_did_not_run_with_the_others(self):
        text = self.show()
        self.assertIn("resumed 1 time", text)
        self.assertIn("added agent-2", text)
        self.assertIn("agent-2, which ran after the others (added by a resume) and so were not interleaved with them", text)
        self.assertIn("this arm ran after the others, so day-to-day drift is in it", text)     # the calibration line carries the caveat

    def test_the_report_names_the_prediction_document_the_race_was_started_under_and_the_code_history(self):
        text = self.show()
        self.assertIn("prediction document (docs/week10/prediction.md): git blob " + BLOB, text)
        self.assertIn("code history", text)

    def test_the_prediction_check_gives_no_verdict_on_a_race_that_stopped_and_was_resumed_on_two_tasks(self):
        code, text = captured(check_team_prediction.main, ["t"])
        self.assertEqual(code, 1)
        self.assertIn("PARTIAL: read on", text)
        self.assertIn("No verdict on the prediction as a whole", text)
        self.assertNotIn("FAILED", text.replace("FAILED RUNS", ""))
        self.assertIn("prediction document recorded with this race: git blob " + BLOB, text)


if __name__ == "__main__":
    unittest.main()
