"""Print an agent run as it happens (Week 7 mentor check #1: every step visible).

The loop calls `on_step` after each step with a plain dictionary (what the model said, which
tools it called with which arguments, what came back, what it cost). `show_step` prints that dictionary in a
readable form. It lives here, not in a script, so every script that runs an agent shows steps the same way.
"""
import json


def _flat(text, limit):
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "..."


def show_step(step):
    """Print one finished step: what the model chose, what came back, what it cost."""
    cost = f"{step['tokens']['prompt'] + step['tokens']['completion']} tokens, {step['seconds']:.1f}s"
    if step["kind"] == "error":
        print(f"[step {step['n']}] ERROR  {step['content']}  ({cost})")
        return
    if step["kind"] == "final":
        print(f"[step {step['n']}] FINAL ANSWER  ({cost})")
        return
    if step["kind"] == "blocked":
        print(f"[step {step['n']}] FINAL ANSWER WITHHELD by the defences  ({cost})")
        return
    if step["content"]:
        print(f"[step {step['n']}] model says: {_flat(step['content'], 160)}")
    for call in step["tool_calls"]:
        try:
            arguments = json.dumps(json.loads(call["arguments"]), ensure_ascii=False) if isinstance(call["arguments"], str) else call["arguments"]
        except (json.JSONDecodeError, TypeError):
            arguments = call["arguments"]
        mark = "" if call["ok"] else "  <-- the tool refused"
        if call.get("blocked"):
            mark = "  <-- refused before it ran (the result says by what)"
        print(f"[step {step['n']}] CALL   {call['name']}({_flat(arguments, 110)}){mark}")
        print(f"          RESULT {_flat(call['observation'], 220)}")
    print(f"          ({cost})")
