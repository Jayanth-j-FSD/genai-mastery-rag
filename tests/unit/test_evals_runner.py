"""The eval runner: private index, caching by exact input, overrides, and stopping safely."""
import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

import _testkit
from _testkit import fake_response, isolated_index, patched_embeddings
from app import llm
from app.config import settings
from app.rag import generator, pipeline, store
from evals import judge, runner

NO_REGRESSIONS = os.path.join(tempfile.gettempdir(), "no-such-regressions.json")
DOCS = {
    "support-faq.md": "ERR-4032 means the data source connection timed out. Retry after 60 seconds and check Settings > Connections.",
    "benefits.md": "A pension match of 5 percent. The pension match starts after 3 months of employment.",
    "Acme-Leave-Policy-2026.md": "Eligible employees may take 16 weeks of paid parental leave after the birth of a child.",
}
THREE = ["code-err4032", "absent-bonus", "detail-parental-leave"]


def make_corpus(directory, docs=DOCS):
    os.makedirs(directory, exist_ok=True)
    for name, text in docs.items():
        with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
            handle.write(text)


class RunnerCase(unittest.TestCase):
    def setUp(self):
        base = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.corpus, self.cache = os.path.join(base, "corpus"), os.path.join(base, "cache")
        make_corpus(self.corpus)
        self.enterContext(isolated_index(corpus_dir=self.corpus, dense_search="exact", retrieval_mode="dense", top_k=3,
                                         llm_model="answer-model", judge_model="judge-model", llm_rpm=0, judge_rpm=0))
        self.enterContext(patched_embeddings())
        self.enterContext(mock.patch.object(runner, "CACHE_DIR", self.cache))
        self.calls = []
        self.enterContext(mock.patch("app.llm.chat", side_effect=self.chat))
        # llm.last_model() is process-global state that a mocked chat never updates.
        self.enterContext(mock.patch("app.llm.last_model", return_value="answer-model"))
        self.main_collection = settings.collection

    def chat(self, messages, **kwargs):
        self.calls.append((kwargs.get("model"), messages[0]["content"][:20]))
        question = messages[-1]["content"].rsplit("Question:", 1)[-1]       # the context holds every document, so key on the question only
        if messages[0]["content"] == judge.SYSTEM_PROMPT:
            return fake_response('{"reason": "fine", "verdict": "pass"}')
        if "bonus" in question.lower():
            return fake_response(generator.IDK)
        if "ERR-4032" in question:
            return fake_response("It means the connection timed out. [source: support-faq.md]")
        return fake_response("It is 16 weeks. [source: Acme-Leave-Policy-2026.md]")

    def run_three(self, **kwargs):
        selected = runner.select_cases(only=THREE, regressions_path=NO_REGRESSIONS)
        return runner.run_cases(selected, say=lambda *_: None, **kwargs)


class RunTests(RunnerCase):
    def test_every_case_is_scored_by_the_rules_and_the_judge(self):
        results = self.run_three(label="t")
        by_id = {c["id"]: c for c in results["cases"]}
        self.assertEqual(set(by_id), set(THREE))
        self.assertEqual(len(results["cases"]), 3)
        self.assertTrue(all(c["passed"] for c in results["cases"]),
                        [(c["id"], [k for k in c["checks"] if not k["passed"]]) for c in results["cases"] if not c["passed"]])
        self.assertTrue(all(c["judge"]["verdict"] == "pass" for c in results["cases"]))
        first = results["cases"][0]
        for key in ("question", "answer", "grounded", "sources", "retrieved", "checks", "passed", "judge", "usage",
                    "problem_type", "reference", "cached", "warnings"):
            self.assertIn(key, first)
        self.assertTrue(first["retrieved"][0]["text"])                       # the judge and the human need the context
        self.assertFalse(by_id["absent-bonus"]["grounded"])                  # the absent topic was refused

    def test_the_meta_block_records_what_produced_the_numbers(self):
        meta = self.run_three(label="t", overrides={"top_k": 3})["meta"]
        self.assertEqual((meta["label"], meta["complete"], meta["n_cases"], meta["chunk_count"]), ("t", True, 3, 3))
        self.assertEqual(meta["models"], {"answer": "answer-model", "judge": "judge-model", "answer_served": "answer-model"})
        self.assertEqual((meta["settings"]["retrieval_mode"], meta["settings"]["dense_search"]), ("dense", "exact"))
        self.assertEqual(meta["overrides"], {"top_k": 3})
        self.assertEqual(meta["cache_hits"], {"answers": 0, "judge": 0})

    def test_no_judge_means_no_judge_calls(self):
        results = self.run_three(label="t", with_judge=False)
        self.assertTrue(all(c["judge"] is None for c in results["cases"]))
        self.assertEqual(len(self.calls), 3)
        self.assertIsNone(results["meta"]["models"]["judge"])

    def test_the_judge_uses_the_judge_model_and_the_answerer_its_own(self):
        self.run_three(label="t")
        self.assertEqual({model for model, _ in self.calls}, {"judge-model", None})   # generator passes no model: llm uses the default

    def test_a_second_identical_run_costs_nothing(self):
        self.run_three(label="one")
        made = len(self.calls)
        second = self.run_three(label="two")
        self.assertEqual(len(self.calls), made)
        self.assertEqual(second["meta"]["cache_hits"], {"answers": 3, "judge": 3})
        self.assertTrue(all(c["cached"] == {"answer": True, "judge": True} for c in second["cases"]))

    def test_a_changed_context_is_never_served_a_stale_answer(self):
        self.run_three(label="one")
        made = len(self.calls)
        with runner.overridden({"top_k": 1}):
            changed = runner.run_cases(runner.select_cases(only=THREE, regressions_path=NO_REGRESSIONS),
                                       label="two", say=lambda *_: None)
        self.assertGreater(len(self.calls), made)                             # at least one case had a different context
        self.assertEqual(changed["meta"]["settings"]["top_k"], 1)

    def test_no_cache_asks_the_models_again(self):
        self.run_three(label="one")
        made = len(self.calls)
        self.run_three(label="two", use_cache=False)
        self.assertEqual(len(self.calls), 2 * made)

    def test_a_judge_reply_that_cannot_be_read_is_recorded_as_an_error_and_not_cached(self):
        def garbled(messages, **kwargs):
            if messages[0]["content"] == judge.SYSTEM_PROMPT:
                return fake_response("I think it is fine")
            return self.chat(messages, **kwargs)
        with mock.patch("app.llm.chat", side_effect=garbled):
            first = self.run_three(label="t")
        self.assertTrue(all(c["judge"]["verdict"] == "error" for c in first["cases"]))
        second = self.run_three(label="t2")                                    # the working chat is back
        self.assertTrue(all(c["judge"]["verdict"] == "pass" for c in second["cases"]))

    def test_a_daily_quota_stops_the_run_and_keeps_what_finished(self):
        seen = []
        def dying(messages, **kwargs):
            if len(self.calls) >= 3:
                raise llm.QuotaExhausted("daily quota used up")
            return self.chat(messages, **kwargs)
        with mock.patch("app.llm.chat", side_effect=dying):
            results = runner.run_cases(runner.select_cases(only=THREE, regressions_path=NO_REGRESSIONS),
                                       label="partial", say=seen.append)
        self.assertFalse(results["meta"]["complete"])
        self.assertIn("daily quota", results["meta"]["stopped_because"])
        self.assertLess(len(results["cases"]), 3)
        self.assertTrue(any("STOPPED" in line for line in seen))
        resumed = self.run_three(label="resumed")                              # the cache makes resuming cheap
        self.assertTrue(resumed["meta"]["complete"])
        self.assertGreater(resumed["meta"]["cache_hits"]["answers"], 0)

    def test_results_round_trip_through_a_file(self):
        results = self.run_three(label="Before: top-k 2/3!")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = runner.save_results(results, runner.results_path(results["meta"]["label"], tmp))
            self.assertTrue(path.endswith("Before-top-k-2-3-.json"))
            self.assertEqual(runner.load_results(path), results)
            with self.assertRaises(FileNotFoundError):
                runner.load_results(os.path.join(tmp, "missing"))


class IndexTests(RunnerCase):
    def test_the_main_index_is_never_touched(self):
        pipeline.ingest()                                                      # a real main index with 3 chunks
        before = store.count_chunks()
        self.run_three(label="t")
        self.assertEqual(settings.collection, self.main_collection)
        self.assertEqual(store.count_chunks(), before)
        names = [getattr(c, "name", c) for c in store._get_client().list_collections()]
        self.assertIn(self.main_collection, names)
        self.assertTrue(any(str(name).startswith("eval_") for name in names))

    def test_the_private_index_is_built_once_and_reused(self):
        with mock.patch.object(pipeline, "ingest", wraps=pipeline.ingest) as spy:
            self.run_three(label="one")
            self.run_three(label="two")
        self.assertEqual(spy.call_count, 1)

    def test_the_index_name_follows_the_settings_and_the_documents(self):
        docs = runner.loader.load_documents(self.corpus)
        base = runner.index_key(docs)
        self.assertEqual(base, runner.index_key(docs))
        with mock.patch.object(settings, "chunk_size", 300):
            self.assertNotEqual(base, runner.index_key(docs))
        with mock.patch.object(settings, "embed_provider", "openai"):
            self.assertNotEqual(base, runner.index_key(docs))
        changed = [dict(doc, text=doc["text"] + " More.") for doc in docs]
        self.assertNotEqual(base, runner.index_key(changed))

    def test_cleaning_removes_only_the_eval_indexes(self):
        pipeline.ingest()
        self.run_three(label="t")
        self.assertGreaterEqual(runner.clean_indexes(), 1)
        names = [str(getattr(c, "name", c)) for c in store._get_client().list_collections()]
        self.assertEqual([name for name in names if name.startswith("eval_")], [])
        self.assertIn(self.main_collection, names)
        self.assertEqual(store.count_chunks(), 3)

    def test_an_empty_corpus_is_a_clear_error(self):
        with isolated_index(corpus_dir=os.path.join(self.corpus, "nothing-here")):
            with self.assertRaises(RuntimeError):
                with runner.isolated_index():
                    pass


class OverrideAndSelectionTests(unittest.TestCase):
    def test_values_take_the_type_of_the_setting_they_replace(self):
        self.assertEqual(runner.parse_overrides(["top_k=2", "min_relevance=0.3", "retrieval_mode=hybrid"]),
                         {"top_k": 2, "min_relevance": 0.3, "retrieval_mode": "hybrid"})
        self.assertEqual(runner.parse_overrides([]), {})
        self.assertEqual(runner.parse_overrides(None), {})

    def test_a_mistyped_name_or_value_is_an_error_not_a_silent_no_op(self):
        for bad in ("top_kk=2", "top_k", "=3", "top_k=abc"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                runner.parse_overrides([bad])

    def test_overrides_apply_inside_the_block_and_always_come_back(self):
        original = settings.top_k
        with runner.overridden({"top_k": original + 5}):
            self.assertEqual(settings.top_k, original + 5)
        self.assertEqual(settings.top_k, original)
        with self.assertRaises(RuntimeError):
            with runner.overridden({"top_k": original + 1}):
                raise RuntimeError("boom")
        self.assertEqual(settings.top_k, original)

    def test_an_override_that_fails_validation_is_refused_and_restored(self):
        original = settings.top_k
        with self.assertRaises(ValueError):
            with runner.overridden({"top_k": 0}):
                pass
        self.assertEqual(settings.top_k, original)

    def test_cases_can_be_picked_by_id_type_or_count(self):
        everything = runner.select_cases(regressions_path=NO_REGRESSIONS)
        self.assertEqual(len(everything), 41)
        self.assertEqual([c["id"] for c in runner.select_cases(only=["absent-bonus"], regressions_path=NO_REGRESSIONS)], ["absent-bonus"])
        self.assertEqual({c["problem_type"] for c in runner.select_cases(types=["absent-topic"], regressions_path=NO_REGRESSIONS)}, {"absent-topic"})
        self.assertEqual(len(runner.select_cases(limit=5, regressions_path=NO_REGRESSIONS)), 5)
        with self.assertRaises(ValueError):
            runner.select_cases(only=["no-such-case"], regressions_path=NO_REGRESSIONS)


class CacheTests(unittest.TestCase):
    def test_values_survive_a_restart_and_a_damaged_file_is_just_empty(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "sub", "cache.json")
            cache = runner.JsonCache(path)
            cache.put("k", {"v": 1})
            self.assertEqual(runner.JsonCache(path).get("k"), {"v": 1})
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            self.assertIsNone(runner.JsonCache(path).get("k"))

    def test_a_disabled_cache_stores_and_returns_nothing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "cache.json")
            cache = runner.JsonCache(path, enabled=False)
            cache.put("k", 1)
            self.assertIsNone(cache.get("k"))
            self.assertFalse(os.path.exists(path))

    def test_hits_are_counted(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = runner.JsonCache(os.path.join(tmp, "c.json"))
            cache.put("k", 1)
            cache.get("k")
            cache.get("missing")
            self.assertEqual(cache.hits, 1)


if __name__ == "__main__":
    unittest.main()
