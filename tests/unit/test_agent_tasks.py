"""Week 7: the agent race tasks are grounded in the real corpus (no model, no network).

A task whose expected fact is no longer in its document would make the race measure nothing, so each
fact is looked up in the document it names, and the tasks are checked against the tools that exist.
"""
import re
import unittest

import _testkit  # noqa: F401  (puts the project root on sys.path)
from app.agent.tools import default_tools
from app.config import settings
from app.rag import loader
from evals import agent_tasks


def normalise(text):
    """Lower-case, one space between words, markdown emphasis and unusual dashes removed."""
    text = text.lower().replace("\u2011", "-").replace("\u2013", "-")
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", text)).strip()


ALL = agent_tasks.TASKS + agent_tasks.PATH_PROBES


class TaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {doc["source"]: normalise(doc["text"]) for doc in loader.load_documents(settings.corpus_dir)}

    def test_ids_are_unique(self):
        ids = [task["id"] for task in ALL]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_expected_source_exists_in_the_corpus(self):
        for task in ALL:
            for source in task["expected_sources"]:
                self.assertIn(source, self.docs, f"{task['id']} names a document that is not in the corpus")

    def test_every_source_fact_is_in_one_of_the_expected_documents(self):
        for task in ALL:
            for fact in task.get("source_facts", []):
                holders = [source for source in task["expected_sources"] if normalise(fact) in self.docs[source]]
                self.assertTrue(holders, f"{task['id']}: {fact!r} is not in {task['expected_sources']}")

    def test_answerable_tasks_have_facts_to_check_and_a_source(self):
        for task in ALL:
            if task["should_refuse"]:
                continue
            self.assertTrue(task["expected_sources"], task["id"])
            self.assertTrue(task["expect_all"] or task["expect_contains"], f"{task['id']} has nothing to check in the answer")
            self.assertTrue(task.get("source_facts"), f"{task['id']} has no source fact to keep it honest")

    def test_the_unanswerable_task_really_is_unanswerable(self):
        refusals = [task for task in agent_tasks.TASKS if task["should_refuse"]]
        self.assertTrue(refusals)
        for task in refusals:
            self.assertEqual(task["expected_sources"], [])
            for term in task["absent_terms"]:
                self.assertFalse([s for s, text in self.docs.items() if term in text],
                                 f"{task['id']}: {term!r} is in the corpus, so the question is answerable")

    def test_expected_tools_are_tools_the_agent_has(self):
        available = {tool.name for tool in default_tools()}
        for task in ALL:
            self.assertTrue(task["expected_tools"], task["id"])
            self.assertLessEqual(set(task["expected_tools"]) | set(task.get("allowed_tools", [])), available, task["id"])

    def test_the_mix_covers_one_lookup_arithmetic_dates_two_documents_conflict_and_absence(self):
        tools_wanted = [set(task["expected_tools"]) for task in agent_tasks.TASKS]
        self.assertTrue(any(t == {"search_policies"} for t in tools_wanted))
        self.assertTrue(any("calculate" in t for t in tools_wanted))
        self.assertTrue(any("add_days" in t for t in tools_wanted))
        self.assertTrue(any(len(task["expected_sources"]) > 1 for task in agent_tasks.TASKS))
        self.assertTrue(any(task["should_refuse"] for task in agent_tasks.TASKS))

    def test_get_tasks_returns_copies_filters_and_rejects_unknown_ids(self):
        everything = agent_tasks.get_tasks()
        self.assertEqual(len(everything), len(agent_tasks.TASKS))
        everything[0]["question"] = "changed"
        self.assertNotEqual(agent_tasks.TASKS[0]["question"], "changed")
        self.assertEqual([t["id"] for t in agent_tasks.get_tasks(["t7-unanswerable"])], ["t7-unanswerable"])
        self.assertEqual(len(agent_tasks.get_tasks()), len(agent_tasks.TASKS))                    # the race is unchanged
        self.assertEqual(len(agent_tasks.get_tasks(include_probes=True)), len(ALL))
        self.assertEqual([t["id"] for t in agent_tasks.get_tasks(["t8-probation-notice"])], ["t8-probation-notice"])
        with self.assertRaises(ValueError):
            agent_tasks.get_tasks(["nope"])


if __name__ == "__main__":
    unittest.main()
