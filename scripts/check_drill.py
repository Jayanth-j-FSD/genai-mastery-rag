"""Week 11, the support drill: check whether the request you found is the planted one. Five guesses.

Scripts/make_drill.py built a log with one wrong answer in it and did not say where. When you think you have found it, give
this the request id (the first 8 characters are enough). It tells you whether you are right without the answer being stored anywhere:
the drill kept a hash of a random salt, the planted request's id and the log itself, and this recomputes that hash for your guess. It
counts guesses (five, so it cannot be used to search the log by trial) and tells you how long it has been since the drill was made.

Run:
    python scripts/check_drill.py <drill id> <request id or its first 8 characters>

This is an honour system: the commitment can be brute-forced by anyone who wants to, and nothing stops you reading the code. The point is
the practice, so write down what you looked at before you ask.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import make_output_safe        # noqa: E402
from evals import drill                          # noqa: E402

MAX_WRONG = 5
MIN_PREFIX = 8


def load_drill(drill_id):
    """(folder, meta, requests text) of a drill, or raises FileNotFoundError / ValueError with something plain to say."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", drill_id):
        raise ValueError(f"not a drill id: {drill_id!r}")
    folder = os.path.join(drill.DRILL_DIR, drill_id)
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"there is no drill called {drill_id!r}; scripts/make_drill.py builds one")
    with open(os.path.join(folder, "drill-meta.json"), encoding="utf-8") as handle:
        meta = json.load(handle)
    with open(os.path.join(folder, "requests.jsonl"), "rb") as handle:
        text = handle.read().decode("utf-8").replace("\r\n", "\n")          # an editor that saved it with Windows line endings has not changed the log
    return folder, meta, text


def request_ids(text):
    ids = []
    for line in text.split("\n"):                      # split on newlines only: str.splitlines also splits on characters that can sit inside a JSON string
        try:
            ids.append(json.loads(line)["request_id"])
        except (ValueError, KeyError, TypeError):
            continue
    return ids


def read_guesses(folder):
    path = os.path.join(folder, "guesses.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    return {"guesses": [], "solved_at": None}


def save_guesses(folder, state):
    with open(os.path.join(folder, "guesses.json"), "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1)


def minutes_since(meta, now=None):
    return max(0, round(((now or datetime.now()) - datetime.fromisoformat(meta["generated_at"])).total_seconds() / 60))


def minutes_text(count):
    return f"{count} minute" + ("" if count == 1 else "s")


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(description="Check whether the request you found is the planted one.")
    parser.add_argument("drill_id", help="the drill id printed by make_drill.py")
    parser.add_argument("guess", help="the request id you found, or its first 8 characters")
    args = parser.parse_args(argv)
    make_output_safe()

    try:
        folder, meta, text = load_drill(args.drill_id)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}")
        return 1
    state = read_guesses(folder)
    wrong = sum(1 for g in state["guesses"] if not g["correct"])
    if state["solved_at"]:
        print(f"Already solved at {state['solved_at']}, in {len(state['guesses'])} guess(es).")
        return 0
    if wrong >= MAX_WRONG:
        print(f"No guesses left: {MAX_WRONG} wrong guesses were used. A drill is practice; read the log again, or build a new one.")
        return 1
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != meta.get("log_sha256", hashlib.sha256(text.encode("utf-8")).hexdigest()):
        print("requests.jsonl is not the log this drill was made with (it was edited, or saved by a tool that changed it), so no guess can be checked against it. "
              "This did not count as a guess; make a new drill.")
        return 1
    guess = args.guess.strip().lower()
    if len(guess) < MIN_PREFIX or not re.fullmatch(r"[0-9a-f]+", guess):
        print(f"Give at least the first {MIN_PREFIX} characters of a request id (hexadecimal). This did not count as a guess.")
        return 1
    matches = [request_id for request_id in request_ids(text) if request_id.startswith(guess)]       # the first 8 characters are unique in a drill
    if not matches:
        print("No request in this drill starts with that. It did not count as a guess.")
        return 1
    if any(g["guess"] == matches[0] for g in state["guesses"]):
        print("You already tried that one. It did not count again.")
        return 1
    correct = drill.commitment(meta["salt"], matches[0], text) == meta["commitment"]
    when = (now or datetime.now()).isoformat(timespec="seconds")
    state["guesses"].append({"at": when, "guess": matches[0], "correct": correct})
    if correct:
        state["solved_at"] = when
        save_guesses(folder, state)
        print(f"Correct: {matches[0]} is the planted request. It took {minutes_text(minutes_since(meta, now))} from the drill's creation, in {len(state['guesses'])} guess(es).\n"
              "Now write down what was wrong with the answer, and what you looked at to be sure it was wrong.")
        return 0
    save_guesses(folder, state)
    left = MAX_WRONG - (wrong + 1)
    print(f"Not that one. {left} guess(es) left. It has been {minutes_text(minutes_since(meta, now))} since the drill was made.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
