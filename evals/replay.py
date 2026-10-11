"""Week 8: would the defences have blocked legitimate work? Feed SAVED runs through them, offline.

A defence that stops attacks but also stops honest answers is no use. This takes runs that were made with
the defences OFF (so every call ran and every answer was shown) and asks what the defences would have done to each one:
refuse a call, cut text out of a document, or withhold the final answer. It is free: no model, no index, no network.
A run that was made WITH the defences on cannot be replayed, because its observations were already screened.
"""
from app.agent import loop
from app.agent.defense import PROMPT_ADDITION, Defense


def replay_run(record, question, trusted_contacts, system_prompt=None):
    """What the three defences would have done to one saved agent run, in the order the loop applies them."""
    prompt = system_prompt or loop.SYSTEM_PROMPT + PROMPT_ADDITION
    defense = Defense(trusted_contacts=trusted_contacts, system_prompt=prompt)
    defense.begin(question, prompt)
    refused = []
    for step in record.get("steps", []):
        defense.step = step.get("n", 0)
        for call in step.get("tool_calls", []):
            if call.get("blocked"):                  # a call something else already refused never ran
                continue
            arguments, problem = loop._parse_arguments(call.get("arguments"))
            refusal = None if problem else defense.check_call(call["name"], arguments)
            if refusal:
                refused.append({"step": step.get("n"), "tool": call["name"], "why": refusal})
            defense.screen(call.get("observation", ""), call["name"])
    answer = record.get("answer")
    withheld = defense.validate(answer) if answer else None
    removed = [event["detail"] for event in defense.events if event["layer"] == "sanitize"]
    return {"task_id": record["task_id"], "repeat": record.get("repeat"), "refused_calls": refused, "sanitized": removed,
            "withheld": withheld}


def replay_runs(records, tasks, trusted_contacts):
    """Replay every agent run whose task is known."""
    questions = {task["id"]: task["question"] for task in tasks}
    return [replay_run(r, questions[r["task_id"]], trusted_contacts) for r in records
            if r.get("approach", "agent") == "agent" and r["task_id"] in questions]


def summarize_replay(rows):
    return {"runs": len(rows), "runs_with_refused_call": sum(1 for r in rows if r["refused_calls"]),
            "calls_refused": sum(len(r["refused_calls"]) for r in rows),
            "answers_withheld": sum(1 for r in rows if r["withheld"]),
            "runs_sanitized": sum(1 for r in rows if r["sanitized"])}


def format_replay(label, rows):
    total = summarize_replay(rows)
    lines = [f"Defences replayed over '{label}': {total['runs']} saved run(s) made with the defences off", "",
             f"  calls the guard would have refused        {total['calls_refused']} (in {total['runs_with_refused_call']} run(s))",
             f"  answers the validator would have withheld {total['answers_withheld']}",
             f"  runs where the sanitizer cut text out     {total['runs_sanitized']}"]
    for row in rows:
        where = f"{row['task_id']} run {row['repeat']}"
        lines += [f"    refused  {where}: {call['why']}" for call in row["refused_calls"]]
        lines += [f"    cut      {where}: {text}" for text in row["sanitized"]]
        if row["withheld"]:
            lines.append(f"    withheld {where}: {row['withheld']}")
    return lines
