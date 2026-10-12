"""Week 11, mentor check #4: turn a real failure found in the request log into a permanent test.

A bug you fixed and did not pin down comes back. The cheapest insurance is to keep the failure itself: the question, the
answer the app really gave, and what a right answer must say. This takes one logged request, you say what a correct answer looks like,
and it writes (1) a case in evals/logged_failures.json, which scripts/run_evals.py then runs with the other eval cases, and (2) a fixture
in tests/fixtures/log_regressions/, which an OFFLINE unit test replays in both directions: the logged bad answer must FAIL the case and a
correct answer must PASS it. A case that its own logged answer passes would guard nothing, so the tool refuses to write one.

Nothing is written without --yes, so you can look first. What it writes holds only: the question, the failing answer, the documents it
cited and retrieved (names and scores, not their text), the request id, the date and the model. It never wipes or reorders what is
already in the file; it adds one case.

Run (you decide what is right: the tool cannot):
    python scripts/failure_to_test.py 503834ae --expect-source Acme-Employment-Terms-2026.md --expect-contains "30 calendar days" \\
        --corrected-from 34356af6 --why "it said it did not know, but two documents answer"
    python scripts/failure_to_test.py <id> --expect-source X.md --expect-contains "30 calendar days" --forbid "45 calendar days" --corrected-answer "30 calendar days [source: X.md]" --yes
    python scripts/failure_to_test.py <id> --refuse --corrected-from <a good refusal's id>          # the documents cannot answer it

It tells you whether the failure was RETRIEVAL (the passage with the answer never reached the model) or GENERATION (it was there and
the answer was still wrong): the first is fixed by changing what is retrieved, the second by changing what the model is told.
"""
import argparse
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR, settings                          # noqa: E402
from app.console import display_path, make_output_safe             # noqa: E402
from app.rag import loader                                          # noqa: E402
from evals import cases, checks, logsearch, runner                  # noqa: E402

FIXTURES_DIR = os.path.join(BASE_DIR, "tests", "fixtures", "log_regressions")
ID_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")                  # an id names a file: no folders, no dots first


def corpus_documents():
    """{document name: its text} for the documents of the corpus: what an expected source and an expected phrase are checked against."""
    return {doc["source"]: doc["text"] for doc in loader.load_documents(settings.corpus_dir)}


def classify(case, retrieved):
    """(kind, sentence): RETRIEVAL when no passage of an expected document holding one of the case's phrases was among those the model saw, GENERATION when one was
    and the answer was wrong anyway. The phrase is matched the way the checks match it (whole words, markdown ignored), so a passage holding 17 calendar days is not
    taken for one holding 7. A refusal case has no passage to look for, and a case with no phrase cannot say what the passage should hold."""
    if case["should_refuse"]:
        return None, "a refusal was expected, so there is no passage to look for"
    facts = list(case.get("expect_contains") or []) + list(case.get("expect_all") or [])
    if not facts:
        return None, "unknown: the case has no phrase saying what the passage should hold"
    whole = bool(case.get("whole_words"))
    for chunk in retrieved:
        if chunk["source"] in case["expected_sources"] and any(checks.contains_phrase(chunk["text"], fact, whole) for fact in facts):
            return "GENERATION", "GENERATION, the passage was there and the answer was still wrong"
    return "RETRIEVAL", "RETRIEVAL, the passage with the answer was not among those the model saw"


def replay_problems(live, fixture):
    """What is wrong with a live case compared with the fixture that was made with it: the fixture's logged answer must still fail the LIVE case, its
    correct answer must still pass it, and the live case must still say what the fixture's copy says. [] when all is well."""
    problems = []
    if checks.check_case(live, fixture["failing_result"])[1]:
        problems.append("the case now passes the logged wrong answer, so it no longer guards against the failure")
    if not checks.check_case(live, fixture["corrected_result"])[1]:
        problems.append("the case now fails the correct answer")
    for key in ("expected_sources", "expect_contains", "expect_all", "forbid_contains"):
        if list(live.get(key) or []) != list(fixture["case"].get(key) or []):
            problems.append(f"{key} differs from the fixture's copy of the case")
    if bool(live.get("should_refuse")) != bool(fixture["case"].get("should_refuse")):
        problems.append("should_refuse differs from the fixture's copy of the case")
    return problems


def result_of(record):
    """A logged request as the dict the rule checks read."""
    return {"answer": record["answer"], "grounded": bool(record["grounded"]), "sources": list(record["listed"]),      # what the app showed as sources: what the eval reads
            "retrieved": [{"source": chunk.get("source", ""), "text": chunk.get("text", "")} for chunk in record["raw"].get("retrieved") or []]}


def trim(result):
    """What the fixture keeps of a result: no passage text, only which documents were retrieved and how well they scored."""
    scores = [{"source": chunk.get("source", ""), "score": chunk.get("score")} for chunk in result.get("scored") or []]
    return {"answer": result["answer"], "grounded": result["grounded"], "sources": result["sources"],
            "retrieved": scores or [{"source": chunk["source"], "score": None} for chunk in result["retrieved"]]}


def find_one(records, prefix, what):
    """The single answered request whose id starts with `prefix`, or (None, why)."""
    found = [record for record in records if record["kind"] == "trace" and record["id"].startswith(prefix)]
    if not found:
        return None, f"no answered request starts with {prefix!r} ({what})"
    if len(found) > 1:
        return None, f"{len(found)} requests start with {prefix!r}; give more characters ({what})"
    return found[0], None


def bare_numbers(phrases):
    return [phrase for phrase in phrases if re.fullmatch(r"\s*\d+([.,]\d+)?\s*", phrase)]


def normalized_case(raw_case, existing_cases):
    """The case as all_cases will see it, validated together with the cases already in the file AND with every case the eval set already has
    (so a duplicate id, even one in the real regressions file, or a case with no expectations is refused before anything is written).
    Returns (case, error)."""
    taken = {case["id"] for case in cases.all_cases(base_only=True)} | {case["id"] for case in cases.load_regressions()}
    if raw_case["id"] in taken:
        return None, f"the case id {raw_case['id']!r} is already used by a case of the eval set; pick another --id"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        with open(os.path.join(folder, cases.LOGGED_FAILURES_NAME), "w", encoding="utf-8") as handle:
            json.dump({"cases": existing_cases + [raw_case]}, handle)
        try:
            everything = cases.all_cases(os.path.join(folder, "regressions.json"))
        except ValueError as exc:
            return None, str(exc)
    return next(case for case in everything if case["id"] == raw_case["id"]), None


def write_json(path, data):
    """Write through a temporary file and one replace, so a crash never leaves half a file where a good one was. ASCII only (non-ASCII characters
    are written as escapes): a real answer with a dash or a curly quote in it must not put one into a committed file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=True)
        handle.write("\n")
    runner.replace_file(path + ".tmp", path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Turn one logged failure into a permanent test.")
    parser.add_argument("request", help="the id of the failing request (the first 8 characters are enough)")
    parser.add_argument("--id", help="the case id (default log-<the request id's first 8 characters>)")
    parser.add_argument("--expect-source", action="append", default=[], metavar="DOC", help="a document that legitimately answers it (repeatable)")
    parser.add_argument("--expect-contains", action="append", default=[], metavar="PHRASE", help="a phrase of which a correct answer has at least one (repeatable)")
    parser.add_argument("--expect-all", action="append", default=[], metavar="PHRASE", help="a phrase every correct answer must contain (repeatable)")
    parser.add_argument("--forbid", action="append", default=[], metavar="PHRASE", help="a phrase a correct answer must NOT contain, such as the wrong figure (repeatable)")
    parser.add_argument("--refuse", action="store_true", help="the documents cannot answer it: the right reply is I don't know")
    parser.add_argument("--reference", default="", help="one sentence saying what the correct answer is")
    parser.add_argument("--problem-type", default="logged-failure", help="the kind of problem, for the per-type scores")
    parser.add_argument("--corrected-from", metavar="ID", help="quote the answer of another real logged request as the correct answer")
    parser.add_argument("--corrected-answer", metavar="TEXT", help="a hand-written correct answer (when no logged answer is right)")
    parser.add_argument("--why", help="why this failure is real, in your own words (kept in the fixture)")
    parser.add_argument("--log", action="append", metavar="PATH", help="read this request log (repeatable); default: the app's traces and errors logs")
    parser.add_argument("--drill", metavar="DRILL_ID", help="read a drill's log (needs --allow-synthetic)")
    parser.add_argument("--allow-synthetic", action="store_true", help="accept a request from a synthetic log (the drill); its case is marked week11-drill")
    parser.add_argument("--cases", default=None, help="the cases file to add to (default evals/logged_failures.json)")
    parser.add_argument("--fixtures", default=FIXTURES_DIR, help="the fixtures folder (default tests/fixtures/log_regressions)")
    parser.add_argument("--worked-example", action="store_true", help="mark the fixture as the shipped worked example, drafted by the tool, to be reviewed by you")
    parser.add_argument("--yes", action="store_true", help="write it (without this, only show what would be written)")
    args = parser.parse_args(argv)
    make_output_safe()

    records, _skipped, _took = logsearch.load(logsearch.default_paths(args.log, args.drill))
    record, why_not = find_one(records, args.request, "the failing request")
    if record is None:
        print(f"Error: {why_not}")
        return 1
    if record["synthetic"] and not args.allow_synthetic:
        print("Error: that request is from a synthetic log (the drill): a practice failure is not a real one. Pass --allow-synthetic to turn it into a case anyway.")
        return 1
    if args.refuse and (args.expect_source or args.expect_contains or args.expect_all):
        print("Error: --refuse means the documents cannot answer it, so there is no document or phrase to expect.")
        return 1
    if not args.refuse and not args.expect_source:
        print("Error: say what a correct answer cites: --expect-source DOC (or --refuse if the documents cannot answer it).")
        return 1
    if not args.refuse and not (args.expect_contains or args.expect_all):
        print("Error: say a phrase a correct answer states (--expect-contains or --expect-all). A case that only forbids one wording or names a document passes every "
              "other wrong answer, so it would guard against that one sentence and nothing more.")
        return 1
    if args.id and not ID_OK.fullmatch(args.id):
        print("Error: --id names a file: letters, digits, dots, dashes and underscores, starting with a letter or a digit.")
        return 1
    if bool(args.corrected_from) == bool(args.corrected_answer):
        print("Error: give exactly one of --corrected-from ID (an answer from the log) and --corrected-answer TEXT (written by hand): "
              "the test proves itself by passing a right answer and failing the wrong one.")
        return 1

    case_id = args.id or f"log-{args.request[:8]}"
    if not ID_OK.fullmatch(case_id):
        print("Error: the request prefix does not make a usable case id; give --id.")
        return 1
    documents = corpus_documents()
    unknown = [name for name in args.expect_source if name not in documents]
    if unknown:
        print(f"Error: {unknown} is not a document of the corpus, so no live run could ever cite it and the case would fail for ever. The documents are: {sorted(documents)}.")
        return 1
    origin = f"week11-drill:{case_id}" if record["synthetic"] else f"week11:{case_id}"
    raw_case = {"id": case_id, "question": record["question"], "problem_type": args.problem_type, "origin": origin, "expected_sources": args.expect_source,
                "expect_contains": args.expect_contains, "expect_all": args.expect_all, "forbid_contains": args.forbid, "should_refuse": args.refuse,
                "whole_words": True, "reference": args.reference}
    cases_path = args.cases or cases.logged_failures_path()
    existing, existing_document = [], {}
    if os.path.exists(cases_path):
        with open(cases_path, encoding="utf-8") as handle:
            existing_document = json.load(handle)
        existing = existing_document.get("cases", [])
    fixture_path = os.path.join(args.fixtures, f"{case_id}.json")
    if os.path.exists(fixture_path):
        print(f"Error: a fixture for {case_id!r} already exists ({display_path(fixture_path, BASE_DIR)}); pick another --id.")
        return 1
    case, error = normalized_case(raw_case, existing)
    if error:
        print(f"Error: {error}")
        return 1

    # Replay BEFORE writing anything: a case the logged answer passes would guard nothing.
    failing = result_of(record)
    failing_checks, passed, warnings = checks.check_case(case, failing)
    if passed:
        print("Error: the case does not fail the answer the app really gave, so it would not have caught this failure. What the checks said:")
        for check in failing_checks:
            print(f"  {check['name']}: {check['detail']}")
        print("Add what makes the logged answer wrong: a --expect-contains phrase it lacks, a --forbid phrase it says, or the document it should have cited.")
        return 1
    if args.corrected_from:
        good, why_not = find_one(records, args.corrected_from, "the correct answer")
        if good is None:
            print(f"Error: {why_not}")
            return 1
        corrected = result_of(good)
        corrected["scored"] = good["raw"].get("retrieved") or []
    else:
        corrected = {"answer": args.corrected_answer, "grounded": not args.corrected_answer.strip().lower().replace(chr(0x2019), "'").startswith("i don't know"),
                     "sources": logsearch.cited_documents({"answer": args.corrected_answer}), "retrieved": failing["retrieved"]}
    corrected_checks, corrected_passes, _ = checks.check_case(case, corrected)
    if not corrected_passes:
        print("Error: the answer you gave as correct does not pass the case, so the case and the answer disagree:")
        for check in corrected_checks:
            if not check["passed"]:
                print(f"  {check['name']}: {check['detail']}")
        return 1

    kind, kind_sentence = classify(case, failing["retrieved"])
    failing["scored"] = record["raw"].get("retrieved") or []
    fixture = {"id": case_id, "kind": kind, "case": raw_case, "failing_result": trim(failing), "corrected_result": trim(corrected),
               "failing_checks": [c["name"] for c in failing_checks if not c["passed"]],
               "logged": {"request_id": record["id"], "date": record["time"].date().isoformat() if record["time"] else None,
                          "model_served": (record["raw"].get("config") or {}).get("llm_model_served"),
                          # where the correct answer came from: a request of the log, and whether it answered this question, or the hand that wrote it
                          "corrected": {"from": good["id"] if args.corrected_from else None, "by_hand": bool(args.corrected_answer),
                                        "same_question": bool(args.corrected_from) and " ".join(good["question"].lower().split()) == " ".join(record["question"].lower().split())}},
               "why": args.why, "drafted_by": "the failure tool, to be reviewed by you" if args.worked_example else "converted with scripts/failure_to_test.py",
               "worked_example": bool(args.worked_example)}

    print(f"case {case_id}: {record['question']}")
    print(f"  the logged answer ({record['time'] or 'no time'}): {record['answer']}")
    print("  it fails: " + "; ".join(f"{c['name']} ({c['detail']})" for c in failing_checks if not c["passed"]))
    print(f"  a correct answer passes: {corrected['answer'][:120]}")
    print("  what kind of failure: " + kind_sentence)
    if args.corrected_from and not fixture["logged"]["corrected"]["same_question"]:
        print("  note: the correct answer is borrowed from a request that asked a different question; the fixture says so")
    if (args.expect_contains or args.expect_all) and not any(checks.contains_phrase(documents[name], phrase, True) for name in args.expect_source for phrase in args.expect_contains + args.expect_all):
        print("  warning: none of the expected documents contains any expected phrase as written, so a correct live answer may not be able to pass; check the wording against the documents")
    for phrase in bare_numbers(args.expect_contains + args.expect_all + args.forbid):
        print(f"  warning: {phrase.strip()!r} is a bare number; it matches any sentence that has it, so add the unit (for example '{phrase.strip()} calendar days')")
    if any(" ".join(existing_case["question"].lower().split()) == " ".join(record["question"].lower().split()) for existing_case in cases.all_cases()):
        print("  warning: the eval set already asks this exact question; the new case will be a second case on it")
    if not args.yes:
        print(f"\nNothing written. Run again with --yes to add the case to {display_path(cases_path, BASE_DIR)} and the fixture to {display_path(args.fixtures, BASE_DIR)}.")
        return 0
    print("  note: --yes copies the logged question and both answers into files you may commit; read them first.")
    write_json(fixture_path, fixture)                              # the fixture first: a case with no fixture is the worse half-written state
    try:
        write_json(cases_path, {**existing_document, "cases": existing + [raw_case]})
    except OSError:
        os.remove(fixture_path)
        raise
    print(f"\nwritten: {display_path(cases_path, BASE_DIR)} and {display_path(fixture_path, BASE_DIR)}.\n"
          f"Run it live with:  python scripts/run_evals.py --only {case_id} --label w11-{case_id} --no-cache --set llm_model=<the model>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
