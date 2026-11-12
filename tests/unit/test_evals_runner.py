"""The eval runner: private index, caching by exact input, overrides, and stopping safely."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import httpx
import openai

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
        other_provider = "local" if settings.embed_provider != "local" else "openai"       # differs from whatever .env set
        with mock.patch.object(settings, "embed_provider", other_provider):
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


class RelevanceFloorCacheTests(RunnerCase):
    """With MIN_RELEVANCE on, the generator may refuse without calling the model, so the floor decides the answer."""

    CHUNKS = [{"source": "a.md", "text": "t", "score": 0.3}]

    def test_the_floor_joins_the_key_only_when_it_is_on_so_earlier_keys_stay_valid(self):
        old = json.dumps([settings.llm_model, generator.SYSTEM_PROMPT, "q", [("a.md", "t")]], ensure_ascii=False)
        base = runner._answer_key("q", self.CHUNKS)
        self.assertEqual(base, hashlib.sha256(old.encode("utf-8")).hexdigest())
        with mock.patch.object(settings, "min_relevance", 0.9):
            floored = runner._answer_key("q", self.CHUNKS)
        with mock.patch.object(settings, "min_relevance", 0.5):
            other = runner._answer_key("q", self.CHUNKS)
        self.assertEqual(len({base, floored, other}), 3)

    def test_a_model_answer_cached_without_a_floor_is_not_served_when_a_floor_would_refuse(self):
        self.run_three(label="open")
        self.calls.clear()
        with mock.patch.object(settings, "min_relevance", 0.99):
            floored = self.run_three(label="floored")
        parental = next(c for c in floored["cases"] if c["id"] == "detail-parental-leave")
        self.assertEqual(parental["answer"], generator.IDK)
        self.assertFalse(parental["cached"]["answer"])
        self.assertEqual([call for call in self.calls if call[0] is None], [], "the answer model should not have been called")

    def test_a_refusal_cached_under_a_floor_is_not_served_once_the_floor_is_off(self):
        with mock.patch.object(settings, "min_relevance", 0.99):
            self.run_three(label="floored")
        open_run = self.run_three(label="open")
        parental = next(c for c in open_run["cases"] if c["id"] == "detail-parental-leave")
        self.assertIn("16 weeks", parental["answer"])

    def test_an_answer_given_without_a_model_call_does_not_claim_the_previous_calls_model(self):
        with mock.patch("app.llm.reset_last_model") as reset:
            runner.answer_one("q", self.CHUNKS, runner.JsonCache(os.path.join(self.cache, "x.json"), False))
        reset.assert_called_once()


class SaveAndFailureTests(RunnerCase):
    def label_path(self, label):
        return os.path.join(self.cache, "results", f"{label}.json")

    def test_an_incomplete_run_never_replaces_a_complete_one(self):
        path = self.label_path("keep")
        complete = {"meta": {"label": "keep", "complete": True}, "cases": [{"id": "a"}]}
        incomplete = {"meta": {"label": "keep", "complete": False}, "cases": []}
        self.assertEqual(runner.save_results(complete, path), path)
        saved_to = runner.save_results(incomplete, path)
        self.assertTrue(saved_to.endswith("keep.incomplete.json"))
        self.assertEqual(runner.load_results(path)["cases"], [{"id": "a"}])

    def test_a_write_that_fails_part_way_leaves_the_earlier_file_whole(self):
        path = self.label_path("whole")
        runner.save_results({"meta": {"label": "whole", "complete": True}, "cases": [{"id": "a"}]}, path)
        with mock.patch.object(runner.json, "dump", side_effect=OSError("the disk filled up")):
            with self.assertRaises(OSError):
                runner.save_results({"meta": {"label": "whole", "complete": True}, "cases": [{"id": "b"}]}, path)
        self.assertEqual(runner.load_results(path)["cases"], [{"id": "a"}])
        self.assertFalse(os.path.exists(path + ".tmp"))

    def test_a_rename_another_program_is_holding_is_tried_again(self):
        path = self.label_path("held")
        real, calls = os.replace, []

        def held_twice(source, target):
            calls.append(target)
            if len(calls) < 3:
                raise PermissionError("another program has the file open")
            return real(source, target)

        with mock.patch("os.replace", held_twice), mock.patch.object(runner, "time") as fake_time:
            runner.save_results({"meta": {"label": "held", "complete": True}, "cases": [{"id": "a"}]}, path)
        self.assertEqual(len(calls), 3)
        self.assertEqual(fake_time.sleep.call_count, 2)                      # it waited between the tries
        self.assertEqual(runner.load_results(path)["cases"], [{"id": "a"}])

    def test_the_finished_run_is_kept_in_the_temporary_file_whatever_stops_the_rename(self):
        for label, failure in (("a Ctrl-C", KeyboardInterrupt()), ("an error that is not a permission error", OSError("the volume went away"))):
            with self.subTest(label):
                path = self.label_path("kept" + str(len(label)))
                with mock.patch("os.replace", side_effect=failure), mock.patch.object(runner, "time"):
                    with self.assertRaises(type(failure)) as caught:
                        runner.save_results({"meta": {"label": "kept", "complete": True}, "cases": [{"id": "a"}]}, path)
                with open(path + ".tmp", encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["cases"], [{"id": "a"}])
                if isinstance(failure, OSError):
                    self.assertIn(path + ".tmp", str(caught.exception))

    def test_a_rename_that_stays_refused_keeps_the_finished_run_in_the_temporary_file_and_says_so(self):
        path = self.label_path("stuck")
        with mock.patch("os.replace", side_effect=PermissionError("held")), mock.patch.object(runner, "time"):
            with self.assertRaises(PermissionError) as caught:
                runner.save_results({"meta": {"label": "stuck", "complete": True}, "cases": [{"id": "a"}]}, path)
        self.assertIn(path + ".tmp", str(caught.exception))
        with open(path + ".tmp", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["cases"], [{"id": "a"}])

    def test_an_incomplete_run_is_saved_normally_when_nothing_complete_exists(self):
        path = self.label_path("fresh")
        self.assertEqual(runner.save_results({"meta": {"label": "fresh", "complete": False}, "cases": []}, path), path)

    def test_a_provider_failure_after_the_retries_stops_the_run_and_keeps_what_finished(self):
        def flaky(messages, **kwargs):
            if "bonus" in messages[-1]["content"].lower():
                raise openai.APIConnectionError(request=httpx.Request("POST", "http://provider.invalid"))
            return self.chat(messages, **kwargs)

        with mock.patch("app.llm.chat", side_effect=flaky):
            results = self.run_three(label="flaky")
        self.assertFalse(results["meta"]["complete"])
        self.assertIn("the provider failed (APIConnectionError)", results["meta"]["stopped_because"])
        self.assertEqual([c["id"] for c in results["cases"]], ["code-err4032", "detail-parental-leave"])     # it stopped at absent-bonus


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

    def test_a_method_name_is_not_a_setting(self):
        with self.assertRaises(ValueError):
            runner.parse_overrides(["copy=1"])

    def test_a_value_the_validators_tidy_up_is_applied_in_its_tidy_form(self):
        with runner.overridden({"embed_provider": "Local", "dense_search": "ANN"}):
            self.assertEqual((settings.embed_provider, settings.dense_search), ("local", "ann"))

    def test_an_unknown_name_is_refused_and_nothing_else_is_changed(self):
        before = settings.top_k
        with self.assertRaises(ValueError):
            with runner.overridden({"top_k": before + 1, "copy": 1}):
                pass
        self.assertEqual(settings.top_k, before)

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
