"""Find a past request in the logs, and read it step by step (Week 11).

Support gets a vague complaint ("it told someone the wrong notice period, sometime last week, citing the
employment terms"). The log holds every request, so the work is narrowing: by words, by time, by which document the answer
cited, by how slow or how costly it was, until a handful are left, then reading those one by one. This is the narrowing, kept
apart from the command line so it can be tested.

It reads both logs the app writes: traces.jsonl (requests that were answered) and errors.jsonl (requests that failed), and it
reads lines written before Week 11 as well: they have no request id (the short trace id is used), no steps and no timings, and
the report says "no steps recorded" instead of guessing. Times are the machine's local time: the log's `ts` is local, and the
newer `started_at` and `ts_utc` are converted to it, so a `--since` means the same thing for every line.
"""
import json
import os
import re
import time
from collections import Counter
from datetime import datetime

from app import pricing, tracing
from app.config import BASE_DIR, settings
from app.console import display_path

_TAG = re.compile(r"\[source:\s*([^\]]+?)\s*\]", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")          # everything a terminal could act on, except a tab and a newline
TEXT_WIDTH = 60


def _plain(text):
    """Text from a log with the control characters taken out: an escape sequence in a question must not reach the terminal."""
    return _CONTROL.sub("", str(text))


# ---------------------------------------------------------------------------- reading

def _parse_time(record):
    """The request's start as a naive local datetime, from whichever of started_at, ts_utc and ts the line has, or None."""
    for key in ("started_at", "ts_utc"):
        value = record.get(key)
        if value:
            try:
                return datetime.fromisoformat(value).astimezone().replace(tzinfo=None)
            except (ValueError, TypeError):
                pass
    try:
        return datetime.fromisoformat(record["ts"]) if record.get("ts") else None
    except (ValueError, TypeError):
        return None


def listed_documents(record):
    """The documents the app LISTED as sources for the answer: the logged `sources` when the line has them, else what the tags say. When the model
    wrote no citation tag the app lists every retrieved document, so this is not the same as what the answer cited."""
    if isinstance(record.get("sources"), list):
        return [str(name) for name in record["sources"]]
    return cited_documents(record)


def cited_documents(record):
    """The documents the answer itself cited: the names in its [source: ...] tags, the same for a line of any age."""
    names = []
    for group in _TAG.findall(record.get("answer") or ""):
        for name in [part.strip() for part in re.split(r"[;,]", group) if part.strip()] or [group.strip()]:
            if name not in names:
                names.append(name)
    return names


def resolve_cited(names, retrieved_sources):
    """The names a tag gives, as the app matches them to what was retrieved (the same name, or the same file name in another folder)."""
    resolved = []
    for name in names:
        match = next((source for source in retrieved_sources if source == name or os.path.basename(source) == os.path.basename(name)), name)
        if match not in resolved:
            resolved.append(match)
    return resolved


def normalize(record, path, line_no, kind):
    """One log line as the flat record the filters read. `raw` keeps the line as written, for --show."""
    usage = record.get("usage") or {}
    answer = record.get("answer")
    retrieved_sources = [chunk.get("source", "") for chunk in record.get("retrieved") or []]
    if kind == "error":
        status = "error"
    else:
        status = record.get("status") or ("ok" if record.get("grounded") else "refused")
    return {"kind": kind, "path": path, "line_no": line_no, "id": record.get("request_id") or record.get("trace_id") or "",
            "trace_id": record.get("trace_id") or "", "time": _parse_time(record), "question": record.get("question") or "",
            "answer": answer if isinstance(answer, str) else "", "grounded": record.get("grounded"), "status": status,
            "cited": resolve_cited(cited_documents(record), retrieved_sources) if kind == "trace" else [],
            "listed": listed_documents(record) if kind == "trace" else [], "retrieved_sources": retrieved_sources,
            "channel": record.get("channel") or "", "caller": record.get("caller") or "", "total_ms": record.get("total_ms"),
            "prompt_tokens": usage.get("prompt_tokens") if usage.get("tokens_known") else None,
            "completion_tokens": usage.get("completion_tokens") if usage.get("tokens_known") else None,
            "provider_ms": usage.get("provider_ms"), "wait_ms": usage.get("wait_ms"), "spans": record.get("spans"),
            "synthetic": bool(record.get("synthetic")), "raw": record}


def load(paths):
    """Read the given logs. Returns (records, lines that could not be read, milliseconds taken). A missing file is an empty log. A path that is not a file, or
    that cannot be read, raises ValueError saying so; a line that is not JSON or not the shape of a log line is counted, never fatal."""
    began, records, skipped = time.perf_counter(), [], 0
    for path in paths:
        kind = "error" if os.path.basename(path).startswith("errors") else "trace"
        if not os.path.exists(path):
            continue
        if not os.path.isfile(path):
            raise ValueError(f"{display_path(path, BASE_DIR)} is not a log file (name the file, for example .../traces.jsonl)")
        try:
            with open(path, encoding="utf-8-sig", errors="ignore") as handle:         # utf-8-sig: a byte order mark must not hide the first line
                for line_no, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        skipped += 1                          # a line cut off by a crash: counted, never fatal
                        continue
                    if not isinstance(record, dict):
                        skipped += 1
                        continue
                    try:
                        records.append(normalize(record, path, line_no, kind))
                    except (AttributeError, TypeError, ValueError):
                        skipped += 1                          # well-formed JSON of a shape no log line has (a number where a block should be)
        except OSError as exc:
            raise ValueError(f"{display_path(path, BASE_DIR)} could not be read ({type(exc).__name__})") from None
    return records, skipped, (time.perf_counter() - began) * 1000


def default_paths(log=None, drill=None):
    """Which logs to read: the ones named, or the drill's, or the app's own traces and errors logs."""
    from evals import drill as drill_kit                 # imported here: the drill module reads this one's neighbours, not the other way round
    if log:
        return list(log)
    if drill:
        return [os.path.join(drill_kit.DRILL_DIR, drill, "requests.jsonl")]
    return [settings.traces_path, tracing.errors_path()]


def banners(records):
    """Lines to print above a result when the log is not real traffic: a synthetic (drill) log, or the log of a dry run (a scripted provider answered)."""
    lines = []
    if any(record["synthetic"] for record in records):
        lines.append("SYNTHETIC LOG: these records were generated by scripts/make_drill.py for practice, so the figures are invented. They are not real requests.")
    served = {(record["raw"].get("config") or {}).get("llm_model_served") for record in records if record["kind"] == "trace"} - {None}
    if served and served <= {"scripted-model"}:
        lines.append("DRY-RUN LOG: a scripted provider answered these, so the tokens and times are NOT measurements (and any dollars are arithmetic on invented tokens).")
    return lines


def no_dollars_reason(input_per_million, output_per_million):
    """Why no dollars are shown: nothing was stated, or what was stated is not above 0 (a free tier costs $0, which is a fact and not a missing price)."""
    if input_per_million is None and output_per_million is None:
        return "no price stated"
    return "the prices stated are not above 0"


# ---------------------------------------------------------------------------- filtering

def stated_price(price):
    """A price as stated. None means not stated, which is 0.0 here, never the PRICE_* setting: the search shows dollars only
    from prices given to it, so the same log never prints two different costs on two machines."""
    return 0.0 if price is None else price


def cost_of(record, input_per_million, output_per_million):
    """Dollars at the prices given, or None when the request's tokens are unknown or no price was given."""
    if record["prompt_tokens"] is None or record["completion_tokens"] is None:
        return None
    return pricing.cost_of(record["prompt_tokens"], record["completion_tokens"], stated_price(input_per_million), stated_price(output_per_million))


def matches(record, criteria):
    """True when the record meets every filter that is set. An unset filter (None or empty) does not narrow anything."""
    haystack = f"{record['question']}\n{record['answer']}".lower()
    if any(word.lower() not in haystack for word in criteria.get("text") or []):
        return False
    if criteria.get("answer_regex") and not re.search(criteria["answer_regex"], record["answer"], re.IGNORECASE):
        return False
    when = record["time"]
    if criteria.get("since") and (when is None or when < criteria["since"]):
        return False
    if criteria.get("until") and (when is None or when > criteria["until"]):
        return False
    if criteria.get("cited") and not any(criteria["cited"].lower() in name.lower() for name in record["cited"]):
        return False
    if criteria.get("retrieved_from") and not any(criteria["retrieved_from"].lower() in name.lower() for name in record["retrieved_sources"]):
        return False
    if criteria.get("status") and record["status"] != criteria["status"]:
        return False
    if criteria.get("grounded") is not None and record["grounded"] is not criteria["grounded"]:
        return False
    if criteria.get("channel") and record["channel"] != criteria["channel"]:
        return False
    if criteria.get("id") and not record["id"].startswith(criteria["id"]):         # a request id starts with its 8-digit trace id, so both work
        return False
    if criteria.get("slower_than") is not None and (record["total_ms"] is None or record["total_ms"] <= criteria["slower_than"]):
        return False
    if criteria.get("costlier_than") is not None:
        cost = cost_of(record, criteria.get("input_per_million"), criteria.get("output_per_million"))
        if cost is None or cost <= criteria["costlier_than"]:
            return False
    return True


def search(records, criteria):
    """The records that meet every filter, oldest first (records without a time sort last, in file order)."""
    found = [record for record in records if matches(record, criteria)]
    return sorted(found, key=lambda r: (r["time"] is None, r["time"] or datetime.min, r["path"], r["line_no"]))


def distinct_answers(records):
    """Group identical answers (whitespace ignored): [{"answer", "count", "first", "last", "example"}], most common first.
    Ties are broken by the earliest time, so the order does not depend on how the dict happened to fill."""
    groups = {}
    for record in (r for r in records if r["kind"] == "trace"):          # a failed request has no answer to group
        key = " ".join(record["answer"].split())
        group = groups.setdefault(key, {"answer": key, "count": 0, "first": record["time"], "last": record["time"], "example": record})
        group["count"] += 1
        if record["time"] is not None:
            group["first"] = record["time"] if group["first"] is None else min(group["first"], record["time"])
            group["last"] = record["time"] if group["last"] is None else max(group["last"], record["time"])
    return sorted(groups.values(), key=lambda g: (-g["count"], g["first"] or datetime.max, g["answer"]))


# ---------------------------------------------------------------------------- printing

def _clip(text, width):
    text = " ".join(_plain(text).split())
    return text if width is None or len(text) <= width else text[:width - 1] + "~"


def _field(name, text):
    """`  name      text` with every later line of the text indented under the text, so a question or an answer with line breaks cannot forge a labelled line."""
    label = f"  {name:<10}"
    return label + ("\n" + " " * len(label)).join(_plain(text).replace("\r", "").split("\n"))


def _when(record):
    return record["time"].strftime("%Y-%m-%d %H:%M") if record["time"] else "unknown time"


def table_lines(records):
    """One line per record: id, time, status, the question and the answer clipped, and the documents the answer cited."""
    lines = [f"{'id':<17}{'time':<17}{'status':<9}{'question':<{TEXT_WIDTH}}  {'answer':<{TEXT_WIDTH}}  cited"]
    for record in records:
        lines.append(f"{record['id'][:16]:<17}{_when(record):<17}{record['status']:<9}{_clip(record['question'], TEXT_WIDTH):<{TEXT_WIDTH}}  "
                     f"{_clip(record['answer'] or '(failed, no answer)', TEXT_WIDTH):<{TEXT_WIDTH}}  {', '.join(record['cited']) or '-'}")
    return lines


def distinct_lines(groups, total):
    lines = [f"{'count':>6}  {'share':>6}  {'first seen':<17}{'example id':<17}answer"]
    for group in groups:
        first = group["first"].strftime("%Y-%m-%d %H:%M") if group["first"] else "unknown"
        lines.append(f"{group['count']:>6}  {group['count'] / total:>6.1%}  {first:<17}{group['example']['id'][:16]:<17}{_clip(group['answer'], 100)}")
    return lines


def show_lines(record, input_per_million=None, output_per_million=None, full=False):
    """Everything the log holds about one request, with its steps as a table: what each step took, tokens, and cost at the prices given. A passage is
    cut to 90 characters unless `full` (the sentence that proves an answer wrong can be further in)."""
    raw = record["raw"]
    lines = [f"request {record['id']}  ({record['kind']} line {record['line_no']} of {os.path.basename(record['path'])})",
             f"  time      {_when(record)}   channel {record['channel'] or '-'}" + (f"   caller {record['caller']}" if record["caller"] else ""),
             f"  status    {record['status']}" + (f"   refusal cause {raw['refusal_cause']}" if raw.get("refusal_cause") else "")
             + (f"   error {raw['error_class']} (HTTP {raw.get('http_status')})" if record["kind"] == "error" else ""),
             _field("question", record["question"] or (f"(not logged: an error record keeps only its length and a hash) {raw.get('question_chars')} characters, hash {raw.get('question_sha')}"
                                                        if record["kind"] == "error" else "(not logged)"))]
    if record["kind"] == "trace":
        lines.append(_field("answer", record["answer"]))
        lines.append(_field("cited", ", ".join(record["cited"]) or "(nothing: the answer has no [source: ...] tag)"))
        if record["listed"] != record["cited"]:
            why = ("the app lists every retrieved document when the answer cites none" if not record["cited"] else "what the app showed the user as sources")
            lines.append(_field("listed", ", ".join(record["listed"]) or "(nothing)") + f"   ({why})")
        retrieved = raw.get("retrieved") or []
        lines.append(f"  retrieved {len(retrieved)} passages" + ("" if not retrieved else ":"))
        cited = {name.lower() for name in record["cited"]}
        for number, chunk in enumerate(retrieved, start=1):
            mark = "cited" if str(chunk.get("source", "")).lower() in cited else "     "
            lines.append(f"    {number}. {mark} {_clip(chunk.get('source', '?'), None)}  score {chunk.get('score')}  {_clip(chunk.get('text', ''), None if full else 90)}")
        config = raw.get("config") or {}
        lines.append(f"  model     asked {config.get('llm_model')}, answered by {config.get('llm_model_served')}   index {raw.get('index_id') or '-'}")
        if raw.get("chars"):
            chars = raw["chars"]
            lines.append(f"  prompt    {chars.get('system')} instructions + {chars.get('context')} passages + {chars.get('question')} question characters, {chars.get('stripped')} stripped")
    spans = raw.get("spans")
    if not spans:
        lines.append("  steps     no steps recorded" + ("" if raw.get("request_id") else " (a line written before Week 11 has none)"))
        if raw.get("total_ms") is not None:
            lines.append(f"  took      {raw.get('total_ms')} ms in all")
        return lines
    lines.append(f"  steps     {len(spans)} steps in {raw.get('total_ms')} ms")
    lines.append(f"    {'step':<16}{'kind':<10}{'start':>9}{'took':>9}{'provider':>10}{'waited':>9}{'tokens in/out':>15}{'cost':>12}  status")
    for span in spans:
        tokens = "-" if span.get("prompt_tokens") is None else f"{span.get('prompt_tokens')}/{span.get('completion_tokens')}"
        cost = "-"
        if span.get("kind") == "model" and span.get("prompt_tokens") is not None:
            dollars = pricing.cost_of(span["prompt_tokens"], span.get("completion_tokens") or 0, stated_price(input_per_million), stated_price(output_per_million))
            cost = "no price" if dollars is None else f"${dollars:.6f}"
        elif span.get("cost_usd") == 0.0:
            cost = "$0 (local)"
        provider = "-" if span.get("provider_ms") is None else f"{span['provider_ms']:.0f} ms"
        waited = "-" if span.get("wait_ms") is None else f"{span['wait_ms']:.0f} ms"
        lines.append(f"    {span.get('name', '?'):<16}{span.get('kind', '?'):<10}{span.get('start_ms', 0):>7.0f}ms{span.get('duration_ms', 0):>7.0f}ms"
                     f"{provider:>10}{waited:>9}{tokens:>15}{cost:>12}  {span.get('status')}"
                     + (f" {span.get('error')}" if span.get("error") else ""))
    usage = raw.get("usage")
    if usage:
        lines.append(f"  totals    {usage.get('model_calls')} model call(s), {usage.get('prompt_tokens')} in / {usage.get('completion_tokens')} out tokens"
                     + ("" if usage.get("tokens_known") else " (a lower bound: the provider did not report every call)")
                     + f", {usage.get('provider_ms')} ms at the provider, {usage.get('wait_ms')} ms waiting")
    priced = pricing.is_priced(stated_price(input_per_million), stated_price(output_per_million))
    lines.append("  cost      " + (pricing.describe_prices(stated_price(input_per_million), stated_price(output_per_million)) if priced
                                  else f"{no_dollars_reason(input_per_million, output_per_million)} (pass --price-in and --price-out above 0 to see dollars)"))
    return lines
