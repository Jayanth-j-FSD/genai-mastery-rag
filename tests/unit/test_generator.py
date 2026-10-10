"""app/rag/generator.py: grounding, citations and refusals, with the chat model faked."""
import unittest
from unittest import mock

import _testkit
from _testkit import fake_response
from app.config import settings
from app.rag import generator

CHUNKS = [
    {"text": "Employees receive 18 days of annual leave.", "source": "Acme-Leave-Policy-2026.md", "score": 0.61},
    {"text": "Employees may work remotely three days a week.", "source": "Remote.md", "score": 0.32},
]


def reply(text):
    return mock.patch("app.llm.chat", return_value=fake_response(text))


class GroundingTests(unittest.TestCase):
    def test_no_chunks_refuses_without_calling_the_model(self):
        with mock.patch("app.llm.chat") as chat:
            self.assertEqual(generator.generate_answer("anything", []), (generator.IDK, [], False))
            chat.assert_not_called()

    def test_weak_best_chunk_refuses_when_the_floor_is_on(self):
        with mock.patch.object(settings, "min_relevance", 0.9), mock.patch("app.llm.chat") as chat:
            self.assertEqual(generator.generate_answer("q", CHUNKS), (generator.IDK, [], False))
            chat.assert_not_called()

    def test_floor_off_by_default_lets_weak_chunks_through(self):
        with mock.patch.object(settings, "min_relevance", 0.0), reply("18 days. [source: Acme-Leave-Policy-2026.md]"):
            _, _, grounded = generator.generate_answer("q", CHUNKS)
        self.assertTrue(grounded)

    def test_a_real_answer_is_grounded_and_cites_only_what_it_used(self):
        with reply("You get 18 days. [source: Acme-Leave-Policy-2026.md]"):
            answer, sources, grounded = generator.generate_answer("How many leave days?", CHUNKS)
        self.assertTrue(grounded)
        self.assertEqual([(s.document, s.score) for s in sources], [("Acme-Leave-Policy-2026.md", 0.61)])
        self.assertIn("18 days", answer)

    def test_a_citation_by_file_name_matches_a_nested_source(self):
        chunks = [{"text": "x", "source": "policies/Leave.md", "score": 0.5}]
        with reply("Yes. [source: Leave.md]"):
            _, sources, _ = generator.generate_answer("q", chunks)
        self.assertEqual([s.document for s in sources], ["policies/Leave.md"])

    def test_without_a_clean_citation_all_retrieved_sources_are_shown_best_first(self):
        with reply("You get 18 days."):
            _, sources, grounded = generator.generate_answer("q", CHUNKS)
        self.assertTrue(grounded)
        self.assertEqual([s.document for s in sources], ["Acme-Leave-Policy-2026.md", "Remote.md"])

    def test_an_invented_citation_is_ignored(self):
        with reply("18 days. [source: Made-Up.md]"):
            _, sources, _ = generator.generate_answer("q", CHUNKS)
        self.assertNotIn("Made-Up.md", [s.document for s in sources])

    def test_refusal_is_ungrounded_and_has_no_sources(self):
        with reply(generator.IDK):
            answer, sources, grounded = generator.generate_answer("bonus?", CHUNKS)
        self.assertEqual((answer, sources, grounded), (generator.IDK, [], False))

    def test_curly_apostrophe_refusal_is_still_a_refusal(self):
        with reply("I don’t know based on the provided documents."):
            _, sources, grounded = generator.generate_answer("q", CHUNKS)
        self.assertFalse(grounded)
        self.assertEqual(sources, [])

    def test_dont_know_in_the_middle_of_an_answer_is_not_a_refusal(self):
        with reply("Most people don't know this, but it is 18 days. [source: Acme-Leave-Policy-2026.md]"):
            _, _, grounded = generator.generate_answer("q", CHUNKS)
        self.assertTrue(grounded)

    def test_an_empty_reply_counts_as_a_refusal(self):
        with reply("   "):
            self.assertEqual(generator.generate_answer("q", CHUNKS), (generator.IDK, [], False))

    def test_a_provider_reply_with_no_choices_counts_as_a_refusal(self):
        from types import SimpleNamespace
        with mock.patch("app.llm.chat", return_value=SimpleNamespace(choices=[], usage=None)):
            self.assertEqual(generator.generate_answer("q", CHUNKS), (generator.IDK, [], False))

    def test_none_content_does_not_crash(self):
        with mock.patch("app.llm.chat", return_value=fake_response(None)):
            self.assertEqual(generator.generate_answer("q", CHUNKS), (generator.IDK, [], False))


class PromptTests(unittest.TestCase):
    def test_prompt_carries_the_rules_the_sources_and_the_question(self):
        with mock.patch("app.llm.chat", return_value=fake_response("x")) as chat:
            generator.generate_answer("How many leave days?", CHUNKS)
        messages = chat.call_args.args[0] if chat.call_args.args else chat.call_args.kwargs["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        system, user = messages[0]["content"], messages[1]["content"]
        self.assertIn(generator.IDK, system)                                    # the exact refusal sentence
        self.assertIn("untrusted", system.lower())                              # the injection rule
        self.assertIn("[source: Acme-Leave-Policy-2026.md]", user)
        self.assertIn("Employees receive 18 days", user)
        self.assertIn("Question: How many leave days?", user)


class CitationParsingTests(unittest.TestCase):
    CHUNKS = [{"text": "x", "source": "A.md", "score": 0.5},
              {"text": "y", "source": "B.md", "score": 0.4},
              {"text": "z", "source": "C.md", "score": 0.3}]

    def cited(self, text, chunks=None):
        with reply(text):
            return [s.document for s in generator.generate_answer("q", chunks or self.CHUNKS)[1]]

    def test_one_citation_listing_two_documents_counts_both(self):
        self.assertEqual(self.cited("Both apply. [source: A.md, B.md]"), ["A.md", "B.md"])

    def test_semicolons_and_several_citations_can_be_mixed(self):
        self.assertEqual(self.cited("One. [source: A.md] Two. [source: B.md; C.md]"), ["A.md", "B.md", "C.md"])

    def test_a_document_cited_twice_is_listed_once(self):
        self.assertEqual(self.cited("[source: A.md] and again [source: A.md, A.md]"), ["A.md"])

    def test_a_file_name_that_contains_a_comma_still_matches_whole(self):
        chunks = [{"text": "x", "source": "Leave, 2026.md", "score": 0.5}]
        self.assertEqual(self.cited("Yes. [source: Leave, 2026.md]", chunks), ["Leave, 2026.md"])

    def test_the_citation_label_is_case_insensitive(self):
        self.assertEqual(self.cited("Yes. [Source: B.md]"), ["B.md"])


if __name__ == "__main__":
    unittest.main()
