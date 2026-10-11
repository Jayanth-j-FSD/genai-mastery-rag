"""Week 11: the free screen of the cost ideas (evals/context_savings.py, evals/bank.py, scripts/estimate_context_savings.py)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

from _testkit import ROOT, fake_response, isolated_index, patched_embeddings
from app.config import settings
from app.rag import generator
from evals import bank, checks, context_savings

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import estimate_context_savings                      # noqa: E402

HANDBOOK = "handbook.md"
POLICY = "policy.md"


def chunk(source, text, number=0, score=0.5):
    return {"chunk_id": f"{source}#{number}", "source": source, "text": text, "score": score}


def case(**fields):
    base = {"id": "case", "question": "How many days?", "expected_sources": [POLICY], "expect_contains": ["30 days"],
            "expect_all": [], "problem_type": "single-fact"}
    return {**base, **fields}


class PromptSizeTests(unittest.TestCase):
    def test_the_screen_measures_the_prompt_the_generator_really_sends(self):
        chunks = [chunk(POLICY, "A permanent employee gives 30 days of notice."), chunk(HANDBOOK, "## S\nsome text")]
        with mock.patch.object(settings, "min_relevance", 0.0), mock.patch("app.llm.chat", return_value=fake_response("30 days.")) as chat:
            generator.generate_answer("How many days?", chunks)
        system, user = (message["content"] for message in chat.call_args.args[0])
        self.assertEqual(context_savings.prompt_chars("How many days?", chunks), len(system) + len(user))


class FirstCopyOnlyTests(unittest.TestCase):
    def test_a_line_is_shown_once_per_document_in_the_first_passage_that_has_it(self):
        passages = [chunk(HANDBOOK, "## One\nsame line\nfact one", 1), chunk(HANDBOOK, "## Two\nsame line\nfact two", 2),
                    chunk(POLICY, "## Policy\nsame line", 3)]
        shown = context_savings.first_copy_only(passages)
        self.assertEqual([c["text"] for c in shown], ["## One\nsame line\nfact one", "## Two\nfact two", "## Policy\nsame line"])

    def test_a_passage_with_nothing_new_is_dropped_and_the_input_is_not_changed(self):
        passages = [chunk(HANDBOOK, "same line", 1), chunk(HANDBOOK, "same line", 2)]
        before = [dict(c) for c in passages]
        self.assertEqual([c["chunk_id"] for c in context_savings.first_copy_only(passages)], ["handbook.md#1"])
        self.assertEqual(passages, before)

    def test_a_line_repeated_inside_one_passage_is_shown_once(self):
        shown = context_savings.first_copy_only([chunk(HANDBOOK, "a\nb\na\nb\nc")])
        self.assertEqual(shown[0]["text"], "a\nb\nc")

    def test_headings_always_stay(self):
        shown = context_savings.first_copy_only([chunk(HANDBOOK, "## H\nx", 1), chunk(HANDBOOK, "## H\ny", 2)])
        self.assertEqual([c["text"] for c in shown], ["## H\nx", "## H\ny"])


class ScreenCaseTests(unittest.TestCase):
    def setUp(self):
        self.baseline = [chunk(HANDBOOK, "## S\nboilerplate\nboilerplate two", 1), chunk(POLICY, "A permanent employee gives 30 days of notice.", 2)]

    def test_an_idea_that_removes_only_boilerplate_loses_nothing_and_says_how_much_it_saved(self):
        shown = [dict(self.baseline[0], text="## S"), self.baseline[1]]
        result = context_savings.screen_case(case(), self.baseline, shown)
        self.assertEqual((result["lost_documents"], result["lost_facts"]), ([], []))
        self.assertGreater(result["saved"], 0)
        self.assertEqual(result["saved"], result["chars_before"] - result["chars_after"])
        self.assertAlmostEqual(result["saved_share"], result["saved"] / result["chars_before"])
        self.assertEqual((result["passages_before"], result["passages_after"]), (2, 2))

    def test_dropping_the_passage_that_holds_the_answer_loses_the_document(self):
        result = context_savings.screen_case(case(), self.baseline, self.baseline[:1])
        self.assertEqual(result["lost_documents"], [POLICY])
        self.assertEqual(result["lost_facts"], ["30 days"])

    def test_taking_the_fact_out_of_a_passage_that_stays_loses_the_fact_string(self):
        shown = [self.baseline[0], dict(self.baseline[1], text="A permanent employee gives notice.")]
        result = context_savings.screen_case(case(expected_sources=[POLICY]), self.baseline, shown)
        self.assertEqual(result["lost_facts"], ["30 days"])

    def test_a_case_that_needs_two_documents_loses_one_when_one_goes(self):
        both = case(expected_sources=[POLICY, "benefits.md"], expect_contains=[])
        baseline = self.baseline + [chunk("benefits.md", "Learning budget is $1,000.", 3)]
        result = context_savings.screen_case(both, baseline, baseline[:2])
        self.assertEqual(result["lost_documents"], ["benefits.md"])

    def test_a_string_that_was_only_ever_in_the_wrong_document_is_not_counted_as_lost(self):
        # the handbook's boilerplate happens to contain the word the case looks for; the policy never had it
        crowded = [chunk(HANDBOOK, "approval does not remove the employee's responsibility", 1)]
        result = context_savings.screen_case(case(expect_contains=["remove"]), crowded, [])
        self.assertEqual((result["lost_documents"], result["lost_facts"]), ([], []))

    def test_a_question_the_documents_cannot_answer_has_nothing_to_lose(self):
        result = context_savings.screen_case(case(expected_sources=[], expect_contains=[]), self.baseline, [])
        self.assertEqual((result["answerable"], result["lost_documents"], result["lost_facts"]), (False, [], []))
        self.assertEqual(result["chars_after"], len(generator.SYSTEM_PROMPT) + len(generator.user_prompt("How many days?", "")))

    def test_the_fact_strings_are_matched_the_way_the_answer_checks_match_them(self):
        self.assertTrue(checks.contains_phrase("**$1,000** a year", "$1000"))
        shown = [chunk(POLICY, "The budget is **$1,000** a year.")]
        result = context_savings.screen_case(case(expect_contains=["$1000"]), shown, shown)
        self.assertEqual(result["lost_facts"], [])


class AllCasesTests(unittest.TestCase):
    def test_every_idea_is_screened_on_its_own_copy_so_one_cannot_change_what_the_next_sees(self):
        pairs = [(case(), [chunk(POLICY, "A permanent employee gives 30 days of notice."), chunk(HANDBOOK, "x\ny", 2)])]

        def vandal(chunks):
            for c in chunks:
                c["text"] = ""                       # a candidate that wrecks the passages it is handed
            return chunks

        table = context_savings.screen_all(pairs, {"vandal": vandal, "keep": lambda chunks: chunks})
        self.assertGreater(table["vandal"][0]["saved"], 0)
        self.assertEqual(table["keep"][0]["saved"], 0)
        self.assertEqual(pairs[0][1][0]["text"], "A permanent employee gives 30 days of notice.")

    def test_the_summary_and_the_report_name_what_fails(self):
        rows = [{"id": "a", "problem_type": "x", "answerable": True, "chars_before": 100, "chars_after": 80, "saved": 20, "saved_share": 0.2,
                 "passages_before": 4, "passages_after": 4, "lost_documents": [], "lost_facts": []},
                {"id": "b", "problem_type": "x", "answerable": True, "chars_before": 200, "chars_after": 200, "saved": 0, "saved_share": 0.0,
                 "passages_before": 4, "passages_after": 3, "lost_documents": ["policy.md"], "lost_facts": ["30 days"]}]
        summary = context_savings.summarize(rows)
        self.assertEqual((summary["n"], summary["chars_before"], summary["chars_after"], summary["zero_saving"]), (2, 150, 140, 1))
        self.assertAlmostEqual(summary["mean_saved_share"], 0.1)
        self.assertEqual(summary["lost_documents"], {"b": ["policy.md"]})
        text = "\n".join(context_savings.format_report({"good idea": rows[:1], "bad idea": rows}, ["header"]))
        self.assertIn("header", text)
        self.assertRegex(text, r"good idea\s.*passes")
        self.assertRegex(text, r"bad idea\s.*FAILS")
        self.assertIn("bad idea: b no longer shows a passage with the answer from ['policy.md']", text)
        self.assertIn("bad idea: b no longer shows ['30 days']", text)


class BankTests(unittest.TestCase):
    def write(self, text):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        path = os.path.join(folder, "bank.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_comments_blank_lines_and_repeats_are_left_out_and_the_order_is_kept(self):
        path = self.write("# a comment\n\nFirst?\nsecond?\n  First?  \n\n# another\nThird?\n")
        self.assertEqual(bank.load_questions(path), ["First?", "second?", "Third?"])

    def test_the_real_bank_loads(self):
        questions = bank.load_questions()
        self.assertGreater(len(questions), 50)
        self.assertEqual(len(questions), len({q.lower() for q in questions}))

    def test_the_same_seed_draws_the_same_questions_and_another_seed_draws_others(self):
        questions = [f"question {number}?" for number in range(40)]
        self.assertEqual(bank.sample(questions, 10, 42), bank.sample(questions, 10, 42))
        self.assertNotEqual(bank.sample(questions, 10, 42), bank.sample(questions, 10, 7))

    def test_a_draw_can_leave_questions_out_and_never_asks_for_more_than_there_are(self):
        questions = ["A?", "b?", "C?"]
        self.assertEqual(sorted(bank.sample(questions, 10, 1, exclude=["a?"])), ["C?", "b?"])
        self.assertEqual(bank.sample(questions, 0, 1), [])
        self.assertEqual(bank.sample(questions, -5, 1), [])


class ScriptTests(unittest.TestCase):
    def run_script(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = estimate_context_savings.main(list(argv))
        return code, out.getvalue()

    def test_a_bad_setting_or_threshold_is_an_error_not_a_run(self):
        code, text = self.run_script("--set", "no_such_setting=1")
        self.assertEqual(code, 1)
        self.assertIn("Error", text)
        code, text = self.run_script("--min-repeats", "1")
        self.assertEqual(code, 1)
        self.assertIn("2 or more", text)

    def test_it_will_not_spend_api_quota_on_embeddings(self):
        with mock.patch.object(settings, "embed_provider", "openai"), mock.patch("app.rag.embedder.embed_texts") as embed:
            code, text = self.run_script("--only", "absent-bonus")
        self.assertEqual(code, 1)
        self.assertIn("EMBED_PROVIDER=local", text)
        embed.assert_not_called()

    def test_a_run_prints_the_three_ideas_and_one_line_per_question(self):
        corpus = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        with open(os.path.join(corpus, "policy.md"), "w", encoding="utf-8") as handle:
            handle.write("# Notice\nA permanent employee gives 30 days of written notice.\n")
        self.enterContext(isolated_index(corpus_dir=corpus, embed_provider="local", dense_search="exact", retrieval_mode="dense", top_k=4))
        self.enterContext(patched_embeddings())
        with mock.patch("app.llm.chat") as chat:
            code, text = self.run_script("--only", "absent-bonus", "code-err4032", "--per-case")
        chat.assert_not_called()                                    # a screen never calls the model
        self.assertEqual(code, 0)
        for needle in ("free screen: 2 eval questions", "A strip lines repeated 10+ times", "B retrieve 3 passages, not 4",
                       "C show each line once per document", "absent-bonus", "code-err4032", "no model calls"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
