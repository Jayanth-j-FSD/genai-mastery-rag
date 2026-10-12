"""Week 11: measure what a request costs, with and without an idea, on the same questions in the same minutes.

"it should be cheaper" is a guess until the same questions have been asked both ways. This asks every question
once per ARM (an arm is a name and the settings it changes: `before` changes nothing, `after` turns the idea on) through the
real answer path, `pipeline.answer`, so every request is logged exactly as a user's would be, spans and tokens included. Three
things keep the comparison honest:

  Interleaved. For each question all arms are asked one after another, and the order rotates from question to question. If the
  provider gets slower or a model is swapped behind an alias halfway through, every arm feels it equally instead of the last one.
  An A/A arm. `before` is asked twice (`before` and `before-2`). The difference between two arms that are the SAME is the noise
  floor, and a difference smaller than it is not a result.
  Scored as it goes. For an eval question the answer is checked by the same free rules as Week 6, so "cheaper" is never read
  without "and did it still answer correctly".

Each arm's raw log goes to data/measure/<label>/<arm>/traces.jsonl (untracked: it holds questions, passages and answers). What is
saved for the repository is one small file, evals/results/cost-<label>.json, with a row per request and NO text: tokens, times,
status, which documents were cited. A dry run answers from a scripted stand-in for the provider, costs no quota, and says so
everywhere it writes.
"""
import contextlib
import hashlib
import json
import os
import re
import statistics
import subprocess
from datetime import datetime
from types import SimpleNamespace

import openai

from app import llm, observability, pricing, tracing
from app.config import BASE_DIR, settings
from app.rag import generator, pipeline, store
from evals import checks, runner

MEASURE_DIR = os.path.join(BASE_DIR, "data", "measure")
MAX_CONSECUTIVE_ERRORS = 3
DEFAULT_ARMS = ["before", "after:context_strip_min_repeats=10", "before-2"]


class Stop(Exception):
    """The run cannot go on (a daily quota, or the provider failing again and again); what finished is kept."""


# ---------------------------------------------------------------------------- the arms and the plan

def parse_arm(text):
    """"after:context_strip_min_repeats=10,top_k=3" -> ("after", {"context_strip_min_repeats": 10, "top_k": 3}). An arm with no
    settings is the unchanged app. The overrides are checked here, so a typo fails before any quota is spent."""
    name, _, rest = text.partition(":")
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ValueError(f"an arm name is letters, digits, dots, dashes and underscores, got {name!r}")
    overrides = runner.parse_overrides([pair for pair in rest.split(",") if pair.strip()])
    with runner.overridden(overrides):
        pass
    return name, overrides


def parse_arms(texts):
    arms = [parse_arm(text) for text in texts]
    names = [name for name, _ in arms]
    if len(arms) < 2:
        raise ValueError("a comparison needs at least two arms")
    if len(set(names)) != len(names):
        raise ValueError(f"arm names must be different, got {names}")
    return arms


def rotation(arms, index):
    """The arms in the order they are asked for question number `index`: the list turned by one more place for each question."""
    turn = index % len(arms)
    return arms[turn:] + arms[:turn]


def make_items(cases, bank_questions):
    """The questions to ask: the eval cases (they carry the rules that score an answer), then stand-in traffic from the bank."""
    items = [{"id": case["id"], "kind": "eval", "question": case["question"], "case": case} for case in cases]
    items += [{"id": f"bank-{number}", "kind": "bank", "question": question, "case": None}
              for number, question in enumerate(bank_questions, start=1)]
    return items


def question_set_hash(items):
    """A short fingerprint of the questions and their order, so two results can be refused when they did not ask the same ones."""
    return observability.sha12("\n".join(f"{item['id']}|{item['question']}" for item in items))


# ---------------------------------------------------------------------------- the provider stand-in for a dry run

class ScriptedClient:
    """Stands in for the provider in a dry run: it cites the first source in the prompt and reports tokens as a quarter of the
    characters. Everything else, retrieval, the strip, the spans, the logs, is the real code."""

    def __init__(self, model="scripted-model"):
        self.model = model
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, **kwargs):
        prompt = " ".join(message["content"] for message in messages or [])
        cited = re.search(r"\[source:\s*([^\]]+?)\s*\]", (messages or [{"content": ""}])[-1]["content"])
        text = f"Scripted answer. [source: {cited.group(1)}]" if cited else generator.IDK
        reply = SimpleNamespace(content=text, tool_calls=None)
        return SimpleNamespace(model=self.model, choices=[SimpleNamespace(message=reply, finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=max(1, len(prompt) // 4), completion_tokens=max(1, len(text) // 4)))


@contextlib.contextmanager
def scripted_provider():
    """Replace the provider with the scripted stand-in for the length of the block."""
    original, client = llm._get_client, ScriptedClient()
    llm._get_client = lambda: client
    try:
        yield client
    finally:
        llm._get_client = original


# ---------------------------------------------------------------------------- one request, and the row it leaves

def code_stamp():
    """Which code made the measurement: the short commit, and whether files had changed since it. None where git cannot say."""
    def git(*args):
        try:
            out = subprocess.run(["git", *args], cwd=BASE_DIR, capture_output=True, text=True, timeout=20)
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    status = git("status", "--porcelain")
    return {"git": git("rev-parse", "--short", "HEAD") or "unknown", "dirty": None if status is None else bool(status)}


def _trace_of(request_id, path):
    """The log line of this request, found by its id (the newest lines first), or None."""
    for line in reversed(tracing.read_traces(path=path)):
        if line.get("request_id") == request_id:
            return line
    return None


def _error_of(request_id, path):
    for record in reversed(tracing.read_errors(path=os.path.join(os.path.dirname(path), "errors.jsonl"))):
        if record.get("request_id") == request_id:
            return record
    return None


def scored(item, line):
    """Did the answer pass the free Week 6 rules? True or False for an eval question, None for stand-in traffic."""
    if item["case"] is None:
        return None
    result = {"answer": line.get("answer", ""), "grounded": bool(line.get("grounded")), "sources": list(line.get("sources") or []),
              "retrieved": [{"source": chunk.get("source"), "text": chunk.get("text", "")} for chunk in line.get("retrieved", [])]}
    return checks.check_case(item["case"], result)[1]


def row_from_trace(item, arm, line):
    """The row kept for one answered request: numbers and names, no text."""
    usage = line.get("usage", {})
    generate = next((span for span in line.get("spans", []) if span.get("kind") == "model"), {})
    known = bool(usage.get("tokens_known"))
    return {"question_id": item["id"], "kind": item["kind"], "arm": arm, "question_sha": observability.sha12(item["question"]),
            "request_id": line.get("request_id"), "status": line.get("status"), "grounded": line.get("grounded"),
            "passed": scored(item, line), "refusal_cause": line.get("refusal_cause"), "sources": list(line.get("sources") or []),
            "model_calls": usage.get("model_calls"), "tokens_known": known,
            "prompt_tokens": usage.get("prompt_tokens") if known else None,
            "completion_tokens": usage.get("completion_tokens") if known else None,
            "provider_ms": usage.get("provider_ms"), "wait_ms": usage.get("wait_ms"), "total_ms": line.get("total_ms"),
            "attempts": generate.get("attempts"), "cold": generate.get("cold"), "model_served": generate.get("model_served"),
            "chars": line.get("chars"), "error_class": None}


def row_from_error(item, arm, request_id, exc, record):
    """The row kept for a request that failed: what failed, never why in words."""
    return {"question_id": item["id"], "kind": item["kind"], "arm": arm, "question_sha": observability.sha12(item["question"]),
            "request_id": request_id, "status": "error", "grounded": None, "passed": None, "refusal_cause": None, "sources": [],
            "model_calls": None, "tokens_known": False, "prompt_tokens": None, "completion_tokens": None, "provider_ms": None,
            "wait_ms": None, "total_ms": (record or {}).get("total_ms"), "attempts": None, "cold": None, "model_served": None,
            "chars": None, "error_class": type(exc).__name__}


_PATH = re.compile(r"[A-Za-z]:[" + chr(92) + chr(92) + "/][^\\s'\"]*|/(?:Users|home)/[^\\s'\"]*")


def plain(message, limit=200):
    """One of the app's own messages, safe to print and to save: absolute paths replaced, cut short, on one line."""
    return " ".join(_PATH.sub("<path>", str(message)).split())[:limit]


def requests_of(record):
    """How many provider requests a failed request sent: the tries of its model step, at least one (a failure before any call still cost nothing,
    but counting it as one keeps the budget from ever under-counting)."""
    tries = sum(span.get("attempts") or 0 for span in (record or {}).get("spans", []) if span.get("kind") == "model")
    return max(1, tries)


def ask_once(item, arm, overrides, out_dir, model, answer=None):
    """Ask one question under one arm's settings, with this arm's own log. Returns (row, requests sent).
    Raises Stop when the daily quota is gone, or when the app itself cannot answer (no key, nothing indexed): that is a setup problem
    to fix, not a provider failure to count. Any failure of the provider is a row with status "error"."""
    answer = answer or pipeline.answer
    path = os.path.join(out_dir, arm, "traces.jsonl")
    settings_for_request = {**overrides, "llm_model": model, "traces_path": path}
    observability.forget_last_request()
    with runner.overridden(settings_for_request), runner.isolated_index(), observability.channel("measure", caller=arm):
        try:
            answer(item["question"])
        except llm.QuotaExhausted as exc:
            request_id = observability.last_request_id()
            raise Stop(f"the provider's daily quota is used up ({exc})") from exc
        except openai.OpenAIError as exc:
            request_id = observability.last_request_id()
            record = _error_of(request_id, path)
            return row_from_error(item, arm, request_id, exc, record), requests_of(record)
        except RuntimeError as exc:                          # the app's own words (see app/): stop at the first, and say what it said
            raise Stop(f"the app could not answer: {plain(exc)}") from exc
    request_id = observability.last_request_id()
    line = _trace_of(request_id, path)
    if line is None:
        raise RuntimeError(f"the request {request_id} left no line in {path}: the log is what a measurement reads, so there is nothing to measure")
    spent = sum(span.get("attempts") or 0 for span in line.get("spans", []) if span.get("kind") == "model")
    return row_from_trace(item, arm, line), spent


# ---------------------------------------------------------------------------- the run

def make_meta(label, model, arms, items, dry_run, max_calls, started):
    shaping = {"retrieval_mode": settings.retrieval_mode, "top_k": settings.top_k, "dense_search": settings.dense_search,
               "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap, "embed_provider": settings.embed_provider,
               "min_relevance": settings.min_relevance, "boilerplate_min_repeats": getattr(settings, "boilerplate_min_repeats", 0),
               "context_strip_min_repeats": getattr(settings, "context_strip_min_repeats", 0)}          # the base: an arm that changes it says so in its overrides
    input_price, output_price = pricing.current_prices()
    return {"label": label, "kind": "cost", "dry_run": dry_run, "started": started, "finished": None, "complete": False,
            "stopped_because": None, "model_requested": model, "models_served": [], "arms": [{"name": n, "overrides": o} for n, o in arms],
            "n_questions": len(items), "n_eval": sum(1 for item in items if item["kind"] == "eval"),
            "n_bank": sum(1 for item in items if item["kind"] == "bank"), "question_set": question_set_hash(items),
            "max_calls": max_calls, "calls_spent": 0, "settings": shaping, "chunk_count": None, "code": code_stamp(),
            "prices": {"input_per_million": input_price, "output_per_million": output_price,
                       "described": pricing.describe_prices(), "note": pricing.ASSUMPTION}}


def resumable(prior, results):
    """Why a saved measurement cannot be carried on as the one being built, or None when it can. Everything that decides what a request
    asks or answers must be the same, or the rows of the two sessions would not be comparable."""
    old, new = prior["meta"], results["meta"]
    for key in ("model_requested", "arms", "question_set", "settings", "dry_run"):
        if old.get(key) != new.get(key):
            return f"the {key.replace('_', ' ')} differs from the saved measurement's"
    if (old.get("code") or {}).get("git") != (new.get("code") or {}).get("git"):
        return "the code is another commit than the one the first part ran on"
    return None


def run(items, arms, label, model, out_dir, max_calls=400, dry_run=False, answer=None, save=None, say=print, prior=None):
    """Ask every question under every arm, interleaved, and return {"meta", "rows"}. `save(results)` is called after each question,
    so a stop leaves everything that finished. Stops when the call budget would be passed, on the daily quota, after
    MAX_CONSECUTIVE_ERRORS provider failures in a row, or on Ctrl-C; the result then says why, and is marked incomplete.

    `prior` is a saved measurement to carry on (see resumable): its answered requests are kept and not asked again, its failed ones
    are set aside in the meta and asked again, so one failed request never forfeits a whole measurement. The budget counts this
    session's requests only; calls_spent is the total."""
    results = {"meta": make_meta(label, model, arms, items, dry_run, max_calls, datetime.now().isoformat(timespec="seconds")), "rows": []}
    served, errors_in_a_row, spent, before = set(), 0, 0, 0
    if prior:
        why_not = resumable(prior, results)
        if why_not:
            raise ValueError(f"cannot resume: {why_not}")
        kept = [row for row in prior["rows"] if row["status"] != "error"]
        failed = [row for row in prior["rows"] if row["status"] == "error"]
        results["rows"] = kept
        before = prior["meta"].get("calls_spent") or 0
        results["meta"].update(started=prior["meta"]["started"], set_aside_rows=(prior["meta"].get("set_aside_rows") or []) + failed,
                               resumed=(prior["meta"].get("resumed") or []) + [{"at": datetime.now().isoformat(timespec="seconds"), "kept_rows": len(kept),
                                                                                "set_aside_rows": len(failed), "max_calls": max_calls}])
        served = {row.get("model_served") for row in kept}
    done = {(row["question_id"], row["arm"]) for row in results["rows"]}
    try:
        for index, item in enumerate(items):
            asked_here = []
            for name, overrides in rotation(arms, index):
                if (item["id"], name) in done:
                    continue
                if spent >= max_calls:
                    raise Stop(f"the budget of {max_calls} model calls (--max-calls) is spent")
                row, calls = ask_once(item, name, overrides, out_dir, model, answer)
                spent += calls
                results["meta"]["calls_spent"] = before + spent
                results["rows"].append(row)
                asked_here.append(row)
                served.add(row.get("model_served"))
                errors_in_a_row = errors_in_a_row + 1 if row["status"] == "error" else 0
                if errors_in_a_row >= MAX_CONSECUTIVE_ERRORS:
                    raise Stop(f"the provider failed {MAX_CONSECUTIVE_ERRORS} requests in a row ({row['error_class']})")
            if asked_here:
                say(f"[{index + 1:>3}/{len(items)}] {item['id']:<34}" + "  ".join(f"{r['arm']}={_cell(r)}" for r in asked_here))
                if save:
                    save(results)
    except (Stop, KeyboardInterrupt) as stop:
        reason = "interrupted (Ctrl-C)" if isinstance(stop, KeyboardInterrupt) else str(stop)
        results["meta"]["stopped_because"] = reason
        say(f"\nSTOPPED: {reason}\nWhat finished is saved; the arms of the question in progress may be incomplete. Carry on with --resume.")
    else:
        results["meta"]["complete"] = not any(row["status"] == "error" for row in results["rows"])
        if not results["meta"]["complete"]:
            results["meta"]["stopped_because"] = "every question was asked, but some requests failed: --resume asks those again"
    results["meta"]["calls_spent"] = before + spent
    results["meta"]["models_served"] = sorted(name for name in served if name)
    results["meta"]["finished"] = datetime.now().isoformat(timespec="seconds")
    with runner.isolated_index() as (_collection, count):
        results["meta"]["chunk_count"] = count
    if save:
        save(results)
    return results


def _cell(row):
    """One request as a few characters for the progress line: its prompt tokens, then + or - for a passed or failed eval check."""
    if row["status"] == "error":
        return f"ERROR({row['error_class']})"
    tokens = "?" if row["prompt_tokens"] is None else row["prompt_tokens"]
    return f"{tokens}tok" + ("" if row["passed"] is None else ("+" if row["passed"] else "-"))


def _number(value, width, places=0):
    return f"{'-':>{width}}" if value is None else f"{value:>{width}.{places}f}"


# ---------------------------------------------------------------------------- reading a run

def _mean(values):
    values = [value for value in values if value is not None]
    return statistics.mean(values) if values else None


def summarize_arms(rows):
    """{arm: numbers} for a run. Tokens are averaged only over the requests whose provider reported them."""
    by_arm = {}
    for row in rows:
        by_arm.setdefault(row["arm"], []).append(row)
    summary = {}
    for arm, arm_rows in by_arm.items():
        answered = [row for row in arm_rows if row["status"] != "error"]
        counted = [row for row in answered if row["tokens_known"]]
        summary[arm] = {"requests": len(arm_rows), "errors": len(arm_rows) - len(answered), "tokens_known": len(counted),
                        "mean_prompt_tokens": _mean(row["prompt_tokens"] for row in counted),
                        "mean_completion_tokens": _mean(row["completion_tokens"] for row in counted),
                        "mean_provider_ms": _mean(row["provider_ms"] for row in answered),
                        "mean_wait_ms": _mean(row["wait_ms"] for row in answered),
                        "refused": sum(1 for row in answered if row.get("grounded") is False),
                        "scored": sum(1 for row in answered if row["passed"] is not None),
                        "passed": sum(1 for row in answered if row["passed"] is True),
                        "mean_chars_stripped": _mean((row["chars"] or {}).get("stripped") for row in answered)}
    return summary


def flips(rows, base, other):
    """The eval questions whose rule check differs between two arms: {"pass_to_fail": [ids], "fail_to_pass": [ids], "compared": n}.
    A question counts only when both arms answered it."""
    asked = {}
    for row in rows:
        if row["status"] != "error" and row["passed"] is not None and row["arm"] in (base, other):
            asked.setdefault(row["question_id"], {})[row["arm"]] = row["passed"]
    both = {question: arms for question, arms in asked.items() if base in arms and other in arms}
    return {"pass_to_fail": sorted(q for q, a in both.items() if a[base] and not a[other]),
            "fail_to_pass": sorted(q for q, a in both.items() if not a[base] and a[other]), "compared": len(both)}


def format_summary(results):
    """Printable lines: one line per arm, then the rule-check differences of every arm against the first."""
    meta, rows = results["meta"], results["rows"]
    summary, names = summarize_arms(rows), [arm["name"] for arm in meta["arms"]]
    lines = [("DRY RUN: the provider was a scripted stand-in, so the tokens and times below are NOT measurements" if meta.get("dry_run")
              else f"model {meta['model_requested']}" + (f" (served: {', '.join(meta['models_served'])})" if meta["models_served"] else ""))
             + f", {meta['n_questions']} questions x {len(names)} arms, {meta['calls_spent']} model calls",
             "", f"{'arm':<14}{'requests':>9}{'errors':>7}{'refused':>8}{'prompt tok':>12}{'compl tok':>11}{'provider ms':>12}{'wait ms':>9}{'stripped':>10}{'passed':>9}"]
    for name in names:
        row = summary.get(name)
        if not row:
            continue
        lines.append(f"{name:<14}{row['requests']:>9}{row['errors']:>7}{row['refused']:>8}{_number(row['mean_prompt_tokens'], 12, 1)}{_number(row['mean_completion_tokens'], 11, 1)}"
                     f"{_number(row['mean_provider_ms'], 12)}{_number(row['mean_wait_ms'], 9)}{_number(row['mean_chars_stripped'], 10)}"
                     f"{str(row['passed']) + ' of ' + str(row['scored']):>9}")
    for name in names[1:]:
        moved = flips(rows, names[0], name)
        lines.append(f"\n{name} against {names[0]} on {moved['compared']} eval questions both answered: "
                     f"pass to fail {moved['pass_to_fail'] or 'none'}; fail to pass {moved['fail_to_pass'] or 'none'}")
    return lines


def save_aggregate(results, path):
    """Write the saved file, through the same incomplete-beside-complete protocol every other result uses."""
    return runner.save_results(results, path)


def results_path(label):
    return os.path.join(runner.RESULTS_DIR, f"cost-{runner.safe_label(label)}.json")


def load_aggregate(label_or_path):
    """A saved measurement by label or by path. A dry run's file lives beside its raw logs, so a label starting with dry- finds it there."""
    candidates = [label_or_path, results_path(label_or_path), os.path.join(MEASURE_DIR, runner.safe_label(label_or_path), "cost-dry.json")]
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
    raise FileNotFoundError(f"No saved measurement called {label_or_path!r} (looked for {os.path.basename(candidates[1])})")


def aggregate_exists(label):
    return os.path.exists(results_path(label)) or os.path.exists(results_path(label)[:-len(".json")] + ".incomplete.json")


def digest(path):
    """sha256 of a file, short: what a pre-registration records about the result it is checked against."""
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()[:12]
