"""Week 8: how far the leak window sits above what honest answers share with the system prompt.

The output validator withholds an answer that repeats `LEAK_WINDOW` characters of the agent's system
prompt in a row, because that is what a prompt leak looks like. A window that is too short withholds honest answers
that happen to reuse a phrase of the prompt ("the company policy documents"). This reads saved runs, finds the
longest stretch each distinct answer shares with the prompt, and prints how close honest answers come to the window
and how far the answers of the prompt-leak attacks are above it, so the number is measured and not guessed. It calls
no model.

Run:
    python scripts/calibrate_leak_window.py
    python scripts/calibrate_leak_window.py --only trajectories-before injection-final
    python scripts/calibrate_leak_window.py --with-workflow          # also the workflow answers of a saved race
"""
import argparse
import glob
import json
import os
import sys
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent import defense, loop                           # noqa: E402
from app.console import make_output_safe                      # noqa: E402
from evals import runner                                      # noqa: E402

PREFIXES = ("trajectories-", "race-", "injection-")


def squash(text):
    """Whitespace and case do not count, as in the validator."""
    return " ".join((text or "").split()).lower()


def longest_shared(prompt, text):
    """The length of the longest stretch of characters the text shares with the (already squashed) prompt."""
    answer = squash(text)
    return SequenceMatcher(None, prompt, answer, autojunk=False).find_longest_match(0, len(prompt), 0, len(answer)).size


def saved_stems():
    """Every saved run file this script reads by default, by name without .json."""
    folder = os.path.dirname(runner.results_path("x"))
    names = sorted(os.path.basename(path)[:-len(".json")] for path in glob.glob(os.path.join(folder, "*.json")))
    return [name for name in names if name.startswith(PREFIXES) and not name.endswith(".incomplete")]


def distinct_texts(stems, with_workflow=False):
    """({squashed text: text} for honest runs, the same for the prompt-leak attacks), each distinct text once.

    Honest runs are the agent runs of trajectory and race files and every injection run except the prompt-leak
    attacks; for an injection run both the answer and the draft the validator withheld count."""
    honest, leaks = {}, {}
    for stem in stems:
        with open(runner.results_path(stem), encoding="utf-8") as handle:
            data = json.load(handle)
        for run in data.get("runs", []):
            if stem.startswith("injection-"):
                target = leaks if "prompt-leak" in run.get("attack_id", "") else honest
                texts = [run.get("answer"), run.get("draft_answer")]
            elif run.get("approach", "agent") != "agent" and not with_workflow:
                continue
            else:
                target, texts = honest, [run.get("answer")]
            for text in texts:
                if text:
                    target.setdefault(squash(text), text)
    return honest, leaks


def main(argv=None):
    parser = argparse.ArgumentParser(description="Show how far the leak window sits above what honest answers share with the system prompt.")
    parser.add_argument("--only", nargs="+", metavar="FILE", help="saved result files to read, by name without .json "
                                                                   "(default: every trajectories-, race- and injection- file)")
    parser.add_argument("--with-workflow", action="store_true", help="also read the workflow approach's answers in a saved race")
    args = parser.parse_args(argv)
    make_output_safe()
    stems = args.only or saved_stems()
    try:
        honest, leaks = distinct_texts(stems, args.with_workflow)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    prompt = loop.SYSTEM_PROMPT + defense.PROMPT_ADDITION
    as_validated = squash(prompt.replace(defense.REFUSAL_SENTENCE, ""))          # the validator takes the plain refusal out first
    with_refusal = squash(prompt)
    honest_scores = sorted((longest_shared(as_validated, text) for text in honest.values()), reverse=True)
    refusal_scores = sorted((longest_shared(with_refusal, text) for text in honest.values()), reverse=True)
    leak_scores = sorted((longest_shared(as_validated, text) for text in leaks.values()), reverse=True)
    window = defense.LEAK_WINDOW
    print(f"Read {len(stems)} saved file(s); the leak window is {window} characters.")
    print(f"Honest answers: {len(honest)} distinct texts (agent answers and withheld drafts, whitespace and case ignored)")
    print(f"  longest stretch shared with the system prompt: {honest_scores[0] if honest_scores else 0} characters")
    print(f"  texts sharing 30 or more: {sum(1 for score in honest_scores if score >= 30)}; sharing {window} or more: "
          f"{sum(1 for score in honest_scores if score >= window)}")
    print(f"  with the plain refusal sentence left in the prompt instead: longest {refusal_scores[0] if refusal_scores else 0}, "
          f"sharing 30 or more: {sum(1 for score in refusal_scores if score >= 30)}")
    print(f"Prompt-leak attacks: {len(leaks)} distinct texts; longest stretches shared: {leak_scores[:5] or 'none saved'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
