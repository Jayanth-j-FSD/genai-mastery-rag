"""Week 10: a pilot, not a race: run the single agent and the team on a few questions that are NOT race tasks.

Before the race counts, the team has to be shown to work at all, and its prompts may need fixing. Fixing a
prompt after seeing it fail on the race tasks would be tuning on the test set, so the shake-down uses other questions: ones
from the Week 5 question bank, with every race task (and any question close to one) left out. A pilot may run on code that is
not committed yet. It saves under a label that starts with `pilot-`, so it cannot pass for the race; it scores nothing (these
questions have no rule checks); and it prints what happened: each hand-off, the answer, the calls and the tokens. What it
measures sharpens the guess in `race_team.py --plan`: its team-to-agent ratio is applied to what the single agent makes on the race
tasks, because the pilot questions are easier. Every pilot made before the race is listed in docs/week10/CHANGES.md.

Run:
    python scripts/pilot_team.py --label pilot-1 --model gemini-3.1-flash-lite-preview          # 6 questions, both arms
    python scripts/pilot_team.py --label pilot-2 --model gemini-3.1-flash-lite-preview --n 4 --seed 7
    python scripts/pilot_team.py --label pilot-3 --model gemini-3.1-flash-lite-preview --n 0 --extra "A question of your own?"
    python scripts/pilot_team.py --show pilot-1                                                  # print a saved pilot: free
"""
import argparse
import math
import os
import random
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))        # the scripts folder, so race_team imports however this is started

import openai                                                # noqa: E402
from app import llm                                          # noqa: E402
from app.agent import loop, team                             # noqa: E402
from app.agent.tools import default_tools                    # noqa: E402
from app.config import BASE_DIR, settings                    # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from app.rag import pipeline                                 # noqa: E402
from evals import runner                                     # noqa: E402
from evals.agent_tasks import PATH_PROBES, TASKS             # noqa: E402
import race_team                                             # noqa: E402  (the same folder: its code stamp says which code the pilot ran)

QUESTIONS = os.path.join(BASE_DIR, "tests", "trace_questions.txt")
TOO_CLOSE = 0.6                  # words in common (as a share of all the words either has) beyond which a question counts as a race task


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def load_questions(path):
    """The questions in a file: one per line, blank lines and # comments skipped."""
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]


def too_close_to_a_race_task(question):
    """True when the question is a race task or nearly one (most of its words are the task's words)."""
    mine = words(question)
    for task in TASKS + PATH_PROBES:
        theirs = words(task["question"])
        if mine and theirs and len(mine & theirs) / len(mine | theirs) >= TOO_CLOSE:
            return True
    return False


def choose(questions, n, seed):
    """(chosen, left out): n questions picked with a seed from those that are not race tasks, and the ones that were left out."""
    kept = [question for question in questions if not too_close_to_a_race_task(question)]
    left_out = [question for question in questions if question not in kept]
    picked = random.Random(seed).sample(kept, min(n, len(kept)))
    return picked, left_out


def summarize_run(question, arm, run, scope=None):
    crew = getattr(run, "team", None) or {}
    answer = run.answer or ""
    calls = run.usage.get("calls", 0)
    log = [call for _owner, call in scope.walk()] if scope is not None else []         # every call of the run, the team's specialists included
    return {"question": question, "arm": arm, "stop_reason": run.stop_reason, "answer": answer, "calls": calls,
            "requests": race_team.requests_from(log, calls, run.stop_reason == "error"),         # what the quota counts: retried and failed attempts too
            "tokens": run.usage.get("prompt_tokens", 0) + run.usage.get("completion_tokens", 0), "steps": len(run.steps),
            "refused": answer.lower().replace("\u2019", "'").startswith("i don't know"), "served_model": llm.last_model(),
            "handoffs": [{"agent": h["agent"], "question": h["question"], "state": h["state"], "calls": h["calls"], "answer_chars": h["answer_chars"]}
                         for h in crew.get("handoffs", [])]}


def run_pair(question, index, model, timeout):
    """The single agent and the team on one question, the order alternating so neither always goes first."""
    options = {"model": model, "timeout_seconds": timeout, "max_calls_per_tool": 0}
    runners = [("agent", lambda: loop.run_agent(question, default_tools(), **options)),
               ("team", lambda: team.run_team(question, default_tools(), **options))]
    if index % 2:
        runners.reverse()
    results = []
    for arm, start in runners:
        llm.reset_last_model()
        with llm.call_scope(arm) as scope:
            run = start()
        results.append(summarize_run(question, arm, run, scope))
    return sorted(results, key=lambda row: row["arm"])


def format_pilot(saved):
    """The pilot as printable lines: each question, what each arm did, and the calls per run."""
    meta, lines = saved["meta"], []
    lines.append(f"=== pilot '{meta['label']}': {len({row['question'] for row in saved['runs']})} question(s) on {meta['model']}, code {meta['code']} ===")
    for question in dict.fromkeys(row["question"] for row in saved["runs"]):
        lines += ["", f"Q: {question}"]
        for row in (r for r in saved["runs"] if r["question"] == question):
            lines.append(f"  {row['arm']:<6}{row['calls']:>3} calls, {row['tokens']:>6} tokens, {row['steps']} steps, stopped: {row['stop_reason']}"
                         + (f"  ({row['requests']} requests)" if row.get("requests", row["calls"]) != row["calls"] else "")      # an older pilot has no count
                         + ("  (refused)" if row["refused"] else ""))
            for handoff in row["handoffs"]:
                lines.append(f"        hand-off to the {handoff['agent']} ({handoff['state']}, {handoff['calls']} calls): {handoff['question']}")
            lines.append(f"        answer: {' '.join(row['answer'].split())[:260]}")
    for arm in ("agent", "team"):
        rows = [row for row in saved["runs"] if row["arm"] == arm]
        if rows:
            lines.append(f"\n{arm}: {sum(row['calls'] for row in rows) / len(rows):.1f} calls and {sum(row['tokens'] for row in rows) / len(rows):.0f} tokens a run over {len(rows)} run(s)")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="Shake the team down on questions that are not race tasks.")
    parser.add_argument("--label", help="name of this pilot: it must start with pilot-")
    parser.add_argument("--model", help="chat model by its exact name (never an alias)")
    parser.add_argument("--n", type=int, default=6, help="how many bank questions (default 6; 0 with --extra)")
    parser.add_argument("--extra", action="append", default=[], metavar="QUESTION",
                        help="a question of your own, as well (listed in the pilot as ad hoc; refused if it is a race task or close to one). "
                             "The bank has no question that needs a calculation, so this is how the calculator gets shaken down")
    parser.add_argument("--seed", type=int, default=1, help="seed for picking the questions (default 1)")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds a run may take (default 300)")
    parser.add_argument("--max-calls", type=int, default=None, help="stop after this many REQUESTS to the provider, retried and failed ones included")
    parser.add_argument("--questions", default=QUESTIONS, help="question file (default tests/trace_questions.txt)")
    parser.add_argument("--show", metavar="LABEL", help="print a saved pilot instead of running one")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.show:
        try:
            print("\n".join(format_pilot(runner.load_results(args.show))))
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        return 0
    if not args.label or not args.label.startswith("pilot-"):
        print("Error: give the pilot a label that starts with pilot- (it must not be able to pass for the race).")
        return 1
    if not args.model or args.model.endswith("-latest"):
        print("Error: name the model with --model, by its exact name (an alias that moves is refused).")
        return 1
    if args.n < 0 or (args.n == 0 and not args.extra) or not 0 < args.timeout < math.inf or (args.max_calls is not None and args.max_calls < 1):
        print("Error: --n must be 1 or greater (0 only with --extra), --max-calls 1 or greater and --timeout greater than 0 and finite.")
        return 1
    for extra in args.extra:
        if too_close_to_a_race_task(extra):
            print(f"Error: '{extra}' is a race task or close to one: a pilot must not be run on the test set.")
            return 1
    path = runner.results_path(args.label)
    if os.path.exists(path):
        print(f"Error: a pilot is already saved as {display_path(path, BASE_DIR)}. Use another label: every pilot is part of the record.")
        return 1
    try:
        pipeline.require_index()
        picked, left_out = choose(load_questions(args.questions), args.n, args.seed)
        picked = picked + list(args.extra)
    except (RuntimeError, OSError) as exc:
        print(f"Error: {exc}")
        return 1
    if not picked:
        print("Error: no question is left after leaving out the race tasks and the questions close to them.")
        return 1
    if args.extra:
        print(f"ad hoc questions (not from the bank): {len(args.extra)}")

    stamp = race_team.code_stamp()
    meta = {"label": args.label, "model": args.model, "seed": args.seed, "n": len(picked), "timeout_seconds": args.timeout,
            "started": datetime.now().astimezone().isoformat(timespec="seconds"),
            "code": f"{stamp['git']}{' plus uncommitted changes' if stamp['dirty'] else ''}", "code_stamp": stamp,
            "ad_hoc_questions": list(args.extra), "left_out_as_race_tasks_or_close_to_one": left_out, "complete": False, "stopped_because": None}
    results = {"meta": meta, "runs": []}
    print(f"Pilot '{args.label}': {len(picked) - len(args.extra)} question(s) from the Week 5 bank and {len(args.extra)} of your own, "
          f"{len(left_out)} bank question(s) left out as race tasks or close to one, on {args.model}\n")
    calls_used = 0
    for index, question in enumerate(picked):
        if args.max_calls is not None and calls_used >= args.max_calls:
            meta["stopped_because"] = f"--max-calls {args.max_calls} reached ({calls_used} requests used)"
            break
        try:
            rows = run_pair(question, index, args.model, args.timeout)
        except llm.QuotaExhausted as exc:
            meta["stopped_because"] = str(exc)[:300]
            break
        except openai.OpenAIError as exc:
            meta["stopped_because"] = f"the provider failed ({type(exc).__name__})"
            break
        results["runs"].extend(rows)
        calls_used += sum(row.get("requests", row["calls"]) for row in rows)
        runner.save_results(dict(results, meta=dict(meta, complete=False)), path)
    meta["complete"] = meta["stopped_because"] is None
    runner.save_results(results, path)
    print("\n".join(format_pilot(results)))
    if meta["stopped_because"]:
        print(f"\nSTOPPED: {meta['stopped_because']}")
    print(f"\nsaved: {display_path(path, BASE_DIR)}")
    return 0 if meta["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
