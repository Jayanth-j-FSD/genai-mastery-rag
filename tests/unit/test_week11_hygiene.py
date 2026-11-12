"""Week 11: request logs and drill data never reach the public repository by accident."""
import glob
import json
import os
import re
import subprocess
import unittest

import _testkit

ROOT = _testkit.ROOT


def ignored_lines():
    with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as handle:
        return {line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")}


class IgnoreTests(unittest.TestCase):
    def test_every_folder_that_holds_request_text_is_ignored(self):
        lines = ignored_lines()
        for folder in ("data/traces/", "data/chroma/", "data/drill/", "data/measure/"):
            self.assertIn(folder, lines, f"{folder} is not in .gitignore: a log would be committed by git add -A")

    def test_the_copies_a_resume_and_a_forced_run_keep_beside_a_result_are_ignored(self):
        lines = ignored_lines()
        for pattern in ("evals/results/*.replaced-*.json", "evals/results/*.incomplete.json"):
            self.assertIn(pattern, lines, f"{pattern} is not in .gitignore: git add evals/results would stage a stray file")

    def files_under_data(self):
        """The files git tracks under data/. In a clean export (git archive) there is no history to ask, but an export holds only
        tracked files, so what is on disk, less the folders .gitignore names (a test run may fill those), is the same list."""
        out = None
        if os.path.exists(os.path.join(ROOT, ".git")):
            out = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True, timeout=30)
        if out is not None and out.returncode == 0:
            return [line for line in out.stdout.splitlines() if line.strip()]
        ignored = tuple(line for line in ignored_lines() if line.startswith("data/") and line.endswith("/"))
        found = []
        for folder, _dirs, names in os.walk(os.path.join(ROOT, "data")):
            for name in names:
                path = os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, "/")
                if not path.startswith(ignored):
                    found.append(path)
        return found

    def test_nothing_is_tracked_under_data_except_the_corpus(self):
        tracked = self.files_under_data()
        self.assertTrue(tracked)
        for path in tracked:
            self.assertTrue(path.startswith("data/corpus/"), f"{path} is tracked: only the corpus belongs in git under data/")


# What the week adds is described for the person who reads it: what the code does and why. Nothing in it says who or what wrote it or reviewed it. The terms are
# built from pieces so that this file does not hold one on a single line.
NARRATION = re.compile("|".join([
    "cl" + "aude", "anthro" + "pic", "co-authored" + "-by", "coding " + "assistant", r"\bai " + "assistant", "indepen" + "dent rev" + "iew", "second " + "review",
    "first " + "review", "third " + "check", "fourth " + "look", "verification " + "review", r"\bmut" + r"ants?\b", r"\bskep" + r"tics?\b", r"\bl" + r"ens(es)?\b",
    r"\bstu" + "dent", "work" + "tree", "fix-" + "wt", "subag" + "ent", r"\brevie" + r"wers?\b", "in its " + "own count"]), re.IGNORECASE)
WEEK11_FILES = ("docs/week11/*.md", "app/observability.py", "evals/bank.py", "evals/context_savings.py", "evals/cost_prediction.py", "evals/cost_run.py",
                "evals/costreport.py", "evals/drill.py", "evals/logsearch.py", "scripts/check_cost_prediction.py", "scripts/check_drill.py", "scripts/cost_report.py",
                "scripts/estimate_context_savings.py", "scripts/failure_to_test.py", "scripts/find_requests.py", "scripts/make_drill.py", "scripts/measure_cost.py",
                "tests/fixtures/log_regressions/*.json", "tests/unit/test_observability.py", "tests/unit/test_trace_log.py", "tests/unit/test_logsearch.py",
                "tests/unit/test_costreport.py", "tests/unit/test_drill.py", "tests/unit/test_cost_prediction.py", "tests/unit/test_cost_run.py",
                "tests/unit/test_cost_run_resume.py", "tests/unit/test_logged_failures.py", "tests/unit/test_context_strip.py", "tests/unit/test_context_savings.py",
                "tests/unit/test_week11_hygiene.py")


def tracked_week11_files():
    """What this week commits that could carry text from a log or a machine: its documents, the fixtures, the saved measurements."""
    found = []
    for pattern in ("docs/week11/*.md", "tests/fixtures/**/*.json", "evals/results/cost-*.json", "evals/logged_failures.json"):
        found += glob.glob(os.path.join(ROOT, pattern), recursive=True)
    return sorted(set(found))


# A drive letter and a slash (the letter standing alone, so the "s:/" of a web address is not one), a file URL, a home folder.
MACHINE = re.compile("(?<![A-Za-z0-9_])[A-Za-z]:[" + chr(92) + chr(92) + "/]|file:///|/Users/|/home/")
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+\.(?!example\b)[\w.]+")        # an address, except one at a name ending in .example
CURLY_QUOTES = [chr(0x2018), chr(0x2019), chr(0x201C), chr(0x201D)]


TEXT_KEYS = {"answer", "question", "text", "retrieved", "passages"}


def measurement_problems(saved):
    """What a saved measurement holds that it must not: the text of a question, an answer or a passage in any row (the failed rows set aside too), or a place
    on this machine in the words that say why it stopped."""
    meta, problems = saved.get("meta") or {}, []
    for row in list(saved.get("rows") or []) + list(meta.get("set_aside_rows") or []):
        if TEXT_KEYS & set(row):
            problems.append(f"a row holds text: {sorted(TEXT_KEYS & set(row))}")
    if MACHINE.search(str(meta.get("stopped_because") or "")):
        problems.append("stopped_because names a place on a machine")
    return problems


class DocumentHygieneTests(unittest.TestCase):
    def test_a_web_address_is_not_a_place_on_a_machine_but_a_drive_a_file_url_and_a_home_folder_are(self):
        for fine in ("https://ai.google.dev/gemini-api/docs/pricing", "http://example.org/a", "see https://x.test and ftp://y.test"):
            self.assertIsNone(MACHINE.search(fine), fine)
        for bad in ("C:" + chr(92) + "Users" + chr(92) + "x", "d:/work/x", "a path (C:/x)", "file:///tmp/x", "/Users/someone/x", "/home/someone/x"):
            self.assertIsNotNone(MACHINE.search(bad), bad)

    def test_an_address_at_a_name_ending_in_example_is_allowed_and_any_other_is_not(self):
        self.assertIsNone(ADDRESS.search("report it to security@northwind.example within an hour"))
        self.assertIsNotNone(ADDRESS.search("write to someone@company.com"))

    def test_no_em_dash_machine_path_file_url_or_personal_address_in_what_the_week_commits(self):
        paths = tracked_week11_files()
        self.assertTrue(any(p.endswith("prediction.md") for p in paths))
        for path in paths:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            name = os.path.relpath(path, ROOT)
            self.assertNotIn(chr(0x2014), text, f"{name} has an em dash")
            self.assertNotIn(chr(0x2013), text, f"{name} has an en dash")
            for quote in CURLY_QUOTES:
                self.assertNotIn(quote, text, f"{name} has a curly quote (U+{ord(quote):04X})")
            self.assertIsNone(MACHINE.search(text), f"{name} names a place on a machine")
            self.assertIsNone(ADDRESS.search(text), f"{name} holds an address")

    def test_what_the_week_adds_does_not_say_who_or_what_wrote_or_reviewed_it(self):
        checked = 0
        for pattern in WEEK11_FILES:
            for path in glob.glob(os.path.join(ROOT, *pattern.split("/"))):
                with open(path, encoding="utf-8") as handle:
                    for number, line in enumerate(handle.read().splitlines(), start=1):
                        self.assertIsNone(NARRATION.search(line), f"{os.path.relpath(path, ROOT)}:{number} narrates how the code was made")
                checked += 1
        self.assertGreater(checked, 25)                                                   # the list names files that exist, or this checks nothing

    def test_the_check_for_narration_finds_what_it_is_for_and_leaves_ordinary_words_alone(self):
        for narrated in ("Written by " + "Cl" + "aude", "a second " + "review found", "the stu" + "dent writes", "hand-made mut" + "ants", "a fresh work" + "tree"):
            self.assertIsNotNone(NARRATION.search(narrated), narrated)
        for ordinary in ("a correct answer written by hand", "an answer the user can review", "wrong answers differ by status", "a step of the request log"):
            self.assertIsNone(NARRATION.search(ordinary), ordinary)

    def test_nothing_in_the_agent_machinery_reads_the_drill(self):
        agent = os.path.join(ROOT, "app", "agent")
        for name in os.listdir(agent):
            if name.endswith(".py"):
                with open(os.path.join(agent, name), encoding="utf-8") as handle:
                    self.assertNotIn("drill", handle.read().lower(), f"app/agent/{name} mentions the drill")

    def test_a_saved_measurement_holds_numbers_and_names_only(self):
        for path in glob.glob(os.path.join(ROOT, "evals", "results", "cost-*.json")):
            with open(path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(measurement_problems(saved), [], os.path.basename(path))

    def test_the_check_on_a_saved_measurement_finds_text_in_a_row_in_a_set_aside_row_and_a_path_in_the_stop_reason(self):
        clean = {"meta": {"stopped_because": "the budget of 400 model calls (--max-calls) is spent", "set_aside_rows": [{"question_id": "q", "error_class": "BadRequestError"}]},
                 "rows": [{"question_id": "q", "prompt_tokens": 10}]}
        self.assertEqual(measurement_problems(clean), [])
        for change in ({"rows": [{"question_id": "q", "answer": "30 days"}]}, {"rows": [{"retrieved": []}]},
                       {"meta": dict(clean["meta"], set_aside_rows=[{"question": "text"}])},
                       {"meta": dict(clean["meta"], stopped_because="the app could not answer: model not found under " + "C:" + chr(92) + "Users" + chr(92) + "x")}):
            with self.subTest(change=list(change)):
                self.assertTrue(measurement_problems(dict(clean, **change)))


if __name__ == "__main__":
    unittest.main()
