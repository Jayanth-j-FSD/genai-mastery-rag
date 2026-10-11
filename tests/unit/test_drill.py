"""Week 11: the support drill (evals/drill.py, scripts/make_drill.py, scripts/check_drill.py): a fair, solvable, honestly labelled puzzle."""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from _testkit import ROOT, fake_response, isolated_index, patched_embeddings
from app import llm, observability
from app.config import settings
from app.rag import generator, pipeline
from evals import drill, logsearch
from test_llm import FakeClient

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import check_drill                                          # noqa: E402
import make_drill                                           # noqa: E402

CORPUS = settings.corpus_dir if os.path.isdir(settings.corpus_dir) else os.path.join(ROOT, "data", "corpus")
_BUILT = {}


def built(seed=1, n=3000, days=28):
    """A drill, built once per seed in this process (building one takes a moment and several tests read the same one)."""
    key = (seed, n, days)
    if key not in _BUILT:
        _BUILT[key] = drill.generate(seed=seed, n=n, days=days, end=datetime(2026, 10, 12, 9), corpus_dir=CORPUS)
    return _BUILT[key]


def plant_of(result):
    return next(r for r in result["records"] if r["request_id"] == result["plant_id"])


class FairnessTests(unittest.TestCase):
    def test_exactly_one_notice_answer_is_wrong_by_the_rule_and_it_is_the_planted_one(self):
        result = built()
        wrong = drill.violations(result["records"], CORPUS)
        self.assertEqual([r["request_id"] for r in wrong], [result["plant_id"]])

    def test_the_planted_figure_is_stated_by_no_document(self):
        result = built()
        figure = int(re.search(r"(\d+) calendar days", plant_of(result)["answer"]).group(1))
        self.assertIn(figure, drill.PLANT_CANDIDATES)
        self.assertFalse(drill._whole_word_in(CORPUS, figure))
        for figures in drill.notice_figures_by_document(CORPUS).values():
            self.assertNotIn(figure, figures)

    def test_every_other_notice_answer_states_only_figures_the_documents_state_and_there_are_several_kinds(self):
        result = built()
        allowed = drill.notice_figures_by_document(CORPUS)
        answers = {}
        for record in result["records"]:
            if "notice" in record["question"].lower() and record["request_id"] != result["plant_id"]:
                answers[record["answer"]] = answers.get(record["answer"], 0) + 1
                for figure in re.findall(r"(\d+) calendar days", record["answer"]):
                    self.assertTrue(any(int(figure) in allowed[name] for name in record["sources"]), record["answer"])
        self.assertGreaterEqual(len(answers), 5)                              # 30 and 7 at Acme, 60 and 30 in the handbook, the conflict, the company's side
        self.assertGreaterEqual(min(answers.values()), 5)                     # so the planted one is the only answer that appears once

    def test_every_figure_the_decoys_state_is_in_the_documents_they_cite(self):
        drill.check_facts(CORPUS)                                             # raises if not
        allowed = drill.notice_figures_by_document(CORPUS)
        self.assertEqual(allowed[drill.ACME], {7, 30})
        self.assertEqual(allowed[drill.HANDBOOK], {30, 60})

    def test_every_phrase_a_template_relies_on_is_in_the_first_document_it_cites(self):
        texts = {doc["source"]: doc["text"].lower() for doc in drill.loader.load_documents(CORPUS)}
        for name, _weight, _questions, variants in drill.TOPICS:
            for _template, cited, phrase, _facts in variants:
                self.assertIn(phrase.lower(), texts[cited[0]], f"{name}: {phrase!r} is not in {cited[0]}")

    def test_refusals_are_only_on_questions_the_documents_cannot_answer_and_all_of_those_are_refused(self):
        result = built()
        for record in result["records"]:
            unanswerable = record["question"] in drill.UNANSWERABLE
            self.assertEqual(record["grounded"], not unanswerable, record["question"])
            if unanswerable:
                self.assertEqual((record["answer"], record["sources"], record["status"], record["refusal_cause"]), (generator.IDK, [], "refused", "model_idk"))
            else:
                self.assertNotIn("refusal_cause", record)
        self.assertGreater(sum(1 for r in result["records"] if not r["grounded"]), 100)

    def test_a_corpus_that_no_longer_says_what_the_decoys_say_stops_the_build(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        for doc in drill.loader.load_documents(CORPUS):
            text = doc["text"].replace("30 calendar days", "40 calendar days") if doc["source"] == drill.ACME else doc["text"]
            with open(os.path.join(folder, doc["source"]), "w", encoding="utf-8") as handle:
                handle.write(text)
        with self.assertRaises(RuntimeError) as caught:
            drill.generate(seed=1, n=300, corpus_dir=folder)
        self.assertIn("no longer says so", str(caught.exception))

    def test_without_the_handbook_there_is_nothing_to_crowd_the_answer_out_and_the_build_stops(self):
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        for doc in drill.loader.load_documents(CORPUS):
            if doc["source"] != drill.HANDBOOK:
                with open(os.path.join(folder, doc["source"]), "w", encoding="utf-8") as handle:
                    handle.write(doc["text"])
        with self.assertRaises(RuntimeError):
            drill.generate(seed=1, n=300, corpus_dir=folder)

    def test_when_every_candidate_figure_is_in_the_corpus_the_build_stops_instead_of_planting_a_right_answer(self):
        with mock.patch.object(drill, "PLANT_CANDIDATES", (30, 60, 7)):
            with self.assertRaises(RuntimeError) as caught:
                drill.generate(seed=1, n=300, corpus_dir=CORPUS)
        self.assertIn("PLANT_CANDIDATES", str(caught.exception))


class RuleTests(unittest.TestCase):
    """The wrongness rule on hand-made records, so each of its parts is pinned on its own."""

    def wrong(self, answer, sources, question="How much notice do I give?"):
        return bool(drill.violations([{"question": question, "answer": answer, "sources": sources, "request_id": "x"}], CORPUS))

    def test_every_figure_stated_must_be_one_the_cited_documents_state(self):
        self.assertFalse(self.wrong("30 calendar days. [source: Acme]", [drill.ACME]))
        self.assertFalse(self.wrong("Acme says 30 calendar days and the handbook 60 calendar days.", [drill.ACME, drill.HANDBOOK]))
        self.assertTrue(self.wrong("30 calendar days, or perhaps 99 calendar days.", [drill.ACME]))          # one wrong figure is enough

    def test_a_figure_that_only_another_document_states_is_wrong_for_the_document_that_was_cited(self):
        self.assertTrue(self.wrong("60 calendar days.", [drill.ACME]))                  # 60 is the handbook's, not Acme's
        self.assertFalse(self.wrong("60 calendar days.", [drill.HANDBOOK]))

    def test_an_answer_that_cites_nothing_cannot_back_up_a_figure(self):
        self.assertTrue(self.wrong("30 calendar days.", []))

    def test_only_notice_questions_with_a_figure_are_judged(self):
        self.assertFalse(self.wrong("99 calendar days.", [drill.ACME], question="How many days of annual leave?"))
        self.assertFalse(self.wrong(generator.IDK, [], question="What notice do I give?"))

    def test_a_generator_that_plants_the_wrong_number_of_wrong_answers_stops_the_build(self):
        for found in ([], [{"request_id": "a"}, {"request_id": "b"}]):
            with self.subTest(found=len(found)), mock.patch.object(drill, "violations", return_value=found):
                with self.assertRaises(RuntimeError) as caught:
                    drill.generate(seed=1, n=300, corpus_dir=CORPUS)
                self.assertIn("the generator is wrong", str(caught.exception))

    def test_an_id_whose_first_eight_digits_were_used_is_never_handed_out_again(self):
        class Fake:
            def __init__(self, *values):
                self.values = iter(values)

            def getrandbits(self, bits):
                return next(self.values)
        taken = set()
        self.assertEqual(drill._unique_id(Fake(0x1234567800000001), taken), "1234567800000001")
        second = Fake(0x1234567800000002, 0x9999999900000003)                           # the first one starts like the id above, so it is skipped
        self.assertEqual(drill._unique_id(second, taken), "9999999900000003")
        self.assertEqual(taken, {"12345678", "99999999"})


class SolvabilityTests(unittest.TestCase):
    def test_the_vague_complaint_narrows_three_thousand_requests_to_a_handful_and_the_wrong_answer_is_among_the_rare_ones(self):
        result = built()
        plant = plant_of(result)
        when = datetime.fromisoformat(plant["ts"])
        cited = plant["sources"][0]
        records = [logsearch.normalize(dict(r), "requests.jsonl", number, "trace") for number, r in enumerate(result["records"], start=1)]
        window = {"text": ["notice"], "cited": cited, "since": datetime.combine((when - timedelta(days=1)).date(), datetime.min.time()),
                  "until": datetime.combine((when + timedelta(days=1)).date(), datetime.max.time())}
        found = logsearch.search(records, window)
        self.assertGreaterEqual(len(found), 5)
        self.assertLessEqual(len(found), 150)
        self.assertIn(plant["request_id"], [r["id"] for r in found])
        groups = logsearch.distinct_answers(found)
        self.assertGreaterEqual(len(groups), 2)
        singles = [g for g in groups if g["count"] == 1]
        self.assertIn(plant["request_id"], [g["example"]["id"] for g in singles])
        self.assertLessEqual(len(singles), 5)                                  # a short list to read, but...
        wrong = [g["example"]["id"] for g in singles if drill.violations([g["example"]["raw"]], CORPUS)]
        self.assertEqual(wrong, [plant["request_id"]])                         # ...rarity alone is not the answer: the others are right, and only a figure checked against a document tells them apart

    def test_it_is_solvable_whatever_the_seed(self):
        for seed in range(20, 32):
            with self.subTest(seed=seed):
                result = built(seed=seed)
                plant = plant_of(result)
                when = datetime.fromisoformat(plant["ts"])
                records = [logsearch.normalize(dict(r), "requests.jsonl", number, "trace") for number, r in enumerate(result["records"], start=1)]
                found = logsearch.search(records, {"text": ["notice"], "cited": plant["sources"][0], "since": datetime.combine((when - timedelta(days=1)).date(), datetime.min.time()),
                                                   "until": datetime.combine((when + timedelta(days=1)).date(), datetime.max.time())})
                self.assertTrue(5 <= len(found) <= 150, len(found))
                singles = [g["example"]["id"] for g in logsearch.distinct_answers(found) if g["count"] == 1]
                self.assertIn(plant["request_id"], singles)
                self.assertLessEqual(len(singles), 6)
                self.assertEqual(len(drill.violations(result["records"], CORPUS)), 1)

    def test_the_complaint_names_the_window_and_the_document_but_not_the_number_or_the_request(self):
        result = built()
        plant, complaint = plant_of(result), result["complaint"]
        when = datetime.fromisoformat(plant["ts"])
        self.assertIn((when - timedelta(days=1)).strftime("%d %B"), complaint)
        self.assertIn((when + timedelta(days=1)).strftime("%d %B %Y"), complaint)
        self.assertIn("employment terms document" if plant["sources"][0] == drill.ACME else "employee handbook", complaint)
        self.assertNotIn(plant["request_id"], complaint)
        self.assertNotIn(plant["trace_id"], complaint)
        self.assertNotIn("calendar days", complaint)

    def test_the_planted_request_is_in_the_middle_of_the_window_in_the_afternoon(self):
        result = built()
        when = datetime.fromisoformat(plant_of(result)["ts"])
        start = datetime.fromisoformat(result["meta"]["window"]["start"])
        self.assertTrue(timedelta(days=9) <= when - start < timedelta(days=20))
        self.assertIn(when.hour, (13, 14, 15, 16))


class ShapeTests(unittest.TestCase):
    """A drill line has the same keys as a line the app writes, so a tool tested on one works on the other."""

    def setUp(self):
        corpus = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        with open(os.path.join(corpus, "policy.md"), "w", encoding="utf-8") as handle:
            handle.write("# Notice\nA permanent employee gives 30 calendar days of written notice.\n")
        self.enterContext(isolated_index(corpus_dir=corpus, embed_provider="local", dense_search="exact", retrieval_mode="dense", top_k=4))
        self.enterContext(patched_embeddings())
        self.enterContext(mock.patch.object(settings, "llm_rpm", 0))
        self.enterContext(mock.patch.object(settings, "min_relevance", 0.0))
        pipeline.ingest()

    def live(self, reply):
        with mock.patch.object(llm, "_get_client", return_value=FakeClient([fake_response(reply)])):
            pipeline.answer("How much notice?")
        with open(settings.traces_path, encoding="utf-8") as handle:
            return json.loads(handle.read().splitlines()[-1])

    def assert_same_shape(self, made, real):
        self.assertEqual(set(made) - {"synthetic", "origin"}, set(real))
        self.assertEqual(set(made["config"]), set(real["config"]))
        self.assertEqual(set(made["retrieved"][0]), set(real["retrieved"][0]))
        self.assertEqual(set(made["usage"]), set(real["usage"]))
        self.assertEqual(set(made["chars"]), set(real["chars"]))
        by_kind = lambda record: {span["kind"]: set(span) for span in record["spans"]}
        self.assertEqual(by_kind(made), by_kind(real))
        self.assertEqual([s["name"] for s in made["spans"]], [s["name"] for s in real["spans"]])
        self.assertEqual({type(v).__name__ for v in made["spans"][2].values() if v is not None}, {type(v).__name__ for v in real["spans"][2].values() if v is not None})

    def test_an_answered_drill_request_has_the_keys_of_a_real_one(self):
        result = built()
        made = next(r for r in result["records"] if r["grounded"])
        self.assert_same_shape(made, self.live("30 calendar days. [source: policy.md]"))

    def test_a_refused_drill_request_has_the_keys_of_a_real_one(self):
        result = built()
        made = next(r for r in result["records"] if not r["grounded"])
        self.assert_same_shape(made, self.live(generator.IDK))


class LabellingTests(unittest.TestCase):
    def test_every_record_says_it_is_synthetic_and_names_a_model_that_does_not_exist(self):
        for record in built()["records"]:
            self.assertIs(record["synthetic"], True)
            self.assertEqual(record["origin"], "drill-kit")
            self.assertEqual(record["config"]["llm_model"], drill.SYNTHETIC_MODEL)
            self.assertEqual(record["config"]["llm_model_served"], drill.SYNTHETIC_MODEL)
            self.assertEqual(record["spans"][2]["model_served"], drill.SYNTHETIC_MODEL)
            self.assertIsNone(record["spans"][2]["cost_usd"])                    # no price is invented either

    def test_ids_are_unique_even_when_shortened_and_the_trace_id_is_the_start_of_the_request_id(self):
        records = built()["records"]
        self.assertEqual(len({r["request_id"] for r in records}), len(records))
        self.assertEqual(len({r["trace_id"] for r in records}), len(records))
        for record in records[:300]:
            self.assertRegex(record["request_id"], r"^[0-9a-f]{16}$")
            self.assertEqual((record["trace_id"], len(record["trace_id"])), (record["request_id"][:8], 8))

    def test_times_are_absolute_inside_the_window_and_in_order(self):
        result = built()
        start, end = (datetime.fromisoformat(result["meta"]["window"][k]) for k in ("start", "end"))
        stamps = [r["ts_utc"] for r in result["records"]]
        self.assertEqual(stamps, sorted(stamps))
        for record in result["records"][:500]:
            self.assertTrue(start <= datetime.fromisoformat(record["ts"]) <= end + timedelta(seconds=1))
            self.assertRegex(record["started_at"], r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$")
        self.assertEqual(len(result["records"]), 3000)

    def test_the_steps_add_up_the_way_they_do_in_a_real_record(self):
        for record in built()["records"][:500]:
            spans = record["spans"]
            self.assertLessEqual(sum(s["duration_ms"] for s in spans), record["total_ms"])
            self.assertAlmostEqual(record["usage"]["provider_ms"], spans[2]["provider_ms"])
            self.assertEqual(record["usage"]["prompt_tokens"], spans[2]["prompt_tokens"])
            self.assertAlmostEqual(spans[2]["duration_ms"], spans[2]["provider_ms"] + spans[2]["wait_ms"], places=2)
            self.assertLessEqual(spans[0]["start_ms"] + spans[0]["duration_ms"], spans[1]["start_ms"])
            self.assertLessEqual(spans[1]["start_ms"] + spans[1]["duration_ms"], spans[2]["start_ms"])

    def test_the_passages_are_real_passages_of_the_corpus_and_the_one_with_the_answer_comes_first(self):
        texts = {doc["source"]: doc["text"] for doc in drill.loader.load_documents(CORPUS)}
        for record in built()["records"][:300]:
            for chunk in record["retrieved"]:
                self.assertIn(chunk["text"][:60], texts[chunk["source"]])
            scores = [c["score"] for c in record["retrieved"]]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertEqual([c["dense_rank"] for c in record["retrieved"]], [1, 2, 3, 4])
            if record["grounded"]:
                self.assertEqual(record["retrieved"][0]["source"], record["sources"][0])


class ReproducibilityTests(unittest.TestCase):
    def test_a_seed_gives_the_same_drill_and_no_seed_gives_a_different_one_every_time(self):
        a = drill.generate(seed=5, n=300, end=datetime(2026, 10, 12, 9), corpus_dir=CORPUS)
        b = drill.generate(seed=5, n=300, end=datetime(2026, 10, 12, 9), corpus_dir=CORPUS)
        c = drill.generate(seed=6, n=300, end=datetime(2026, 10, 12, 9), corpus_dir=CORPUS)
        self.assertEqual((a["requests_text"], a["plant_id"]), (b["requests_text"], b["plant_id"]))
        self.assertNotEqual(a["plant_id"], c["plant_id"])
        first = drill.generate(n=300, corpus_dir=CORPUS)
        second = drill.generate(n=300, corpus_dir=CORPUS)
        self.assertNotEqual(first["plant_id"], second["plant_id"])                 # randomness from the operating system


class CommitmentTests(unittest.TestCase):
    def test_the_commitment_recognises_the_planted_request_and_no_other_and_the_log_cannot_be_changed_afterwards(self):
        result = built()
        meta, text = result["meta"], result["requests_text"]
        self.assertEqual(drill.commitment(meta["salt"], result["plant_id"], text), meta["commitment"])
        other = next(r["request_id"] for r in result["records"] if r["request_id"] != result["plant_id"])
        self.assertNotEqual(drill.commitment(meta["salt"], other, text), meta["commitment"])
        self.assertNotEqual(drill.commitment(meta["salt"], result["plant_id"], text.replace("employee", "employe", 1)), meta["commitment"])

    def test_nothing_written_to_disk_says_where_the_answer_is(self):
        result = built()
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        out = os.path.join(folder, "d")
        drill.write(result, out)
        self.assertEqual(sorted(os.listdir(out)), ["complaint.txt", "drill-meta.json", "requests.jsonl"])
        for name in ("complaint.txt", "drill-meta.json"):
            with open(os.path.join(out, name), encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotIn(result["plant_id"], text)
            self.assertNotIn(result["plant_id"][:8], text)
        meta = json.load(open(os.path.join(out, "drill-meta.json"), encoding="utf-8"))
        self.assertTrue({"plant", "plant_id", "figure", "wrong", "answer"}.isdisjoint(meta))
        self.assertTrue(meta["synthetic"])
        self.assertIn("which requests were wrong", " ".join(meta["invented"]))
        with open(os.path.join(out, "requests.jsonl"), "rb") as handle:
            self.assertEqual(handle.read().decode("utf-8"), result["requests_text"])        # the bytes the commitment was made over

    def test_the_log_on_disk_reads_back_with_the_app_tools(self):
        result = built()
        folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        drill.write(result, folder)
        records, skipped, _took = logsearch.load([os.path.join(folder, "requests.jsonl")])
        self.assertEqual((len(records), skipped), (3000, 0))
        self.assertTrue(all(r["synthetic"] for r in records))


class MakeScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(drill, "DRILL_DIR", self.folder))

    def run_script(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = make_drill.main(list(argv))
        return code, out.getvalue()

    def test_it_writes_the_drill_says_it_is_synthetic_and_never_prints_the_answer(self):
        code, text = self.run_script("--n", "300", "--days", "7", "--seed", "3")
        self.assertEqual(code, 0, text)
        plant_id = drill.generate(seed=3, n=300, days=7, corpus_dir=CORPUS)["plant_id"]
        self.assertNotIn(plant_id, text)
        self.assertIn("SYNTHETIC", text)
        self.assertIn("The complaint:", text)
        self.assertIn("scripts/check_drill.py", text)
        (name,) = os.listdir(self.folder)
        self.assertTrue(name.startswith("drill-"))
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder, name))), ["complaint.txt", "drill-meta.json", "requests.jsonl"])

    def test_it_refuses_an_output_folder_outside_the_drill_folder_and_a_drill_too_small_to_search(self):
        outside = os.path.join(self.folder, "..", "elsewhere")
        code, text = self.run_script("--out", outside, "--n", "300", "--seed", "1")
        self.assertEqual(code, 1)
        self.assertIn("must be a folder under", text)
        self.assertEqual(self.run_script("--out", self.folder, "--n", "300")[0], 1)         # the drill folder itself is not a drill
        code, text = self.run_script("--n", "50")
        self.assertEqual(code, 1)
        self.assertIn("at least 200 requests", text)
        self.assertEqual(self.run_script("--days", "3")[0], 1)

    def test_it_will_not_overwrite_a_drill_unless_forced(self):
        out = os.path.join(self.folder, "mine")
        self.assertEqual(self.run_script("--out", out, "--n", "300", "--seed", "1")[0], 0)
        code, text = self.run_script("--out", out, "--n", "300", "--seed", "2")
        self.assertEqual(code, 1)
        self.assertIn("already exists", text)
        self.assertEqual(self.run_script("--out", out, "--n", "300", "--seed", "2", "--force")[0], 0)


class CheckScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.enterContext(mock.patch.object(drill, "DRILL_DIR", self.folder))
        self.result = drill.generate(seed=11, n=300, days=7, end=datetime(2026, 10, 12, 9), corpus_dir=CORPUS)
        drill.write(self.result, os.path.join(self.folder, "d1"))
        self.plant = self.result["plant_id"]
        self.wrongs = [r["request_id"] for r in self.result["records"] if r["request_id"] != self.plant]

    def run_script(self, *argv, now=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_drill.main(list(argv), now=now)
        return code, out.getvalue()

    def test_the_right_request_is_recognised_by_its_first_eight_characters_and_reports_the_time_taken(self):
        made = datetime.fromisoformat(self.result["meta"]["generated_at"])
        code, text = self.run_script("d1", self.plant[:8].upper(), now=made + timedelta(minutes=47))
        self.assertEqual(code, 0)
        self.assertIn("Correct", text)
        self.assertIn("47 minutes", text)
        self.assertIn("1 guess", text)
        self.assertIn("write down what was wrong", text)

    def test_a_wrong_request_is_not_it_and_the_guesses_are_counted(self):
        code, text = self.run_script("d1", self.wrongs[0])
        self.assertEqual(code, 1)
        self.assertIn("Not that one. 4 guess(es) left", text)
        self.assertIn("3 guess(es) left", self.run_script("d1", self.wrongs[1])[1])

    def test_after_five_wrong_guesses_not_even_the_right_one_is_checked(self):
        for wrong in self.wrongs[:5]:
            self.run_script("d1", wrong)
        code, text = self.run_script("d1", self.plant)
        self.assertEqual(code, 1)
        self.assertIn("No guesses left", text)

    def test_an_id_that_is_too_short_not_hexadecimal_or_not_in_the_drill_is_not_a_guess(self):
        for guess in ("abc", "zzzzzzzzzz", "0" * 16):
            with self.subTest(guess=guess):
                self.assertEqual(self.run_script("d1", guess)[0], 1)
        self.assertIn("4 guess(es) left", self.run_script("d1", self.wrongs[0])[1])                                      # still four left after the first real one

    def test_once_solved_it_says_so_and_a_missing_or_badly_named_drill_is_an_error(self):
        self.run_script("d1", self.plant)
        code, text = self.run_script("d1", self.wrongs[0])
        self.assertEqual(code, 0)
        self.assertIn("Already solved", text)
        self.assertEqual(self.run_script("nope", self.plant)[0], 1)
        code, text = self.run_script("../d1", self.plant)
        self.assertEqual(code, 1)
        self.assertIn("not a drill id", text)

    def test_a_log_that_was_changed_after_it_was_made_can_no_longer_confirm_the_answer(self):
        path = os.path.join(self.folder, "d1", "requests.jsonl")
        with open(path, "rb") as handle:
            raw = handle.read()
        with open(path, "wb") as handle:
            handle.write(raw.replace(b"employee", b"employe", 1))
        self.assertEqual(self.run_script("d1", self.plant)[0], 1)


if __name__ == "__main__":
    unittest.main()
