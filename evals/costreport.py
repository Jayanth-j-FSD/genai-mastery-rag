"""Read a request log as a cost report: where the time and the tokens go, step by step, and what a request costs (Week 11).

One number for a whole request ("it took 3.2 seconds, it used 900 tokens") cannot tell you what to fix. The log keeps
a record per STEP (embedding the question, searching, asking the model), so this adds them up per step across many requests, and
splits the model step into the time spent at the provider and the time spent waiting for the rate limit, because on a free tier the
second can be most of it and no change to the prompt will shorten it. Tokens come first, because they are what the provider
reports; dollars are tokens times a price YOU state, with that price printed under every figure, because a price is an assumption.
Requests whose provider did not report tokens are left out of every token and dollar figure and counted, never averaged in as zero.
"""
import statistics

from app import pricing
from evals import logsearch

P95_MIN_REQUESTS = 100            # below this a 95th percentile is just the biggest few values, so it is not printed


def stats(values):
    """n, mean, median, max and (from 100 values up) the 95th percentile, or None when there is nothing to say."""
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    result = {"n": len(values), "mean": statistics.mean(values), "median": statistics.median(values), "max": values[-1], "p95": None}
    if len(values) >= P95_MIN_REQUESTS:
        result["p95"] = values[min(len(values) - 1, int(0.95 * len(values) + 0.999999) - 1)]       # nearest rank
    return result


def _answered(records):
    return [record for record in records if record["kind"] == "trace"]


def per_step(records, skip_cold=False):
    """One row per kind of step across the requests that recorded steps: how long it takes, and for the model step the split
    between the provider and the waiting and the tokens. `skip_cold` leaves out the first step of each kind in a process, which
    pays one-time costs (loading the embedding model, opening the index) that a long-running server pays once."""
    by_name, with_steps, cold = {}, 0, 0
    for record in _answered(records):
        spans = record["spans"]
        if not spans:
            continue
        with_steps += 1
        for span in spans:
            if span.get("cold"):
                cold += 1
                if skip_cold:
                    continue
            by_name.setdefault(span.get("name", "?"), []).append(span)
    total_time = sum(span.get("duration_ms") or 0 for spans in by_name.values() for span in spans)
    rows = []
    for name, spans in by_name.items():
        times = stats(span.get("duration_ms") for span in spans)
        row = {"name": name, "kind": spans[0].get("kind"), "time": times, "share": (sum(s.get("duration_ms") or 0 for s in spans) / total_time) if total_time else None,
               "provider": stats(s.get("provider_ms") for s in spans), "wait": stats(s.get("wait_ms") for s in spans),
               "prompt_tokens": stats(s.get("prompt_tokens") for s in spans), "completion_tokens": stats(s.get("completion_tokens") for s in spans),
               "attempts": stats(s.get("attempts") for s in spans if s.get("kind") == "model")}
        rows.append(row)
    return {"rows": sorted(rows, key=lambda r: -(r["time"]["mean"] * r["time"]["n"])), "requests_with_steps": with_steps,
            "requests_without_steps": len(_answered(records)) - with_steps, "cold_spans": cold, "skipped_cold": skip_cold}


def per_request(records, input_per_million=None, output_per_million=None):
    """Whole-request numbers: tokens, time, how much of the model time was waiting, and dollars at the prices stated (or None)."""
    answered = _answered(records)
    known = [r for r in answered if r["prompt_tokens"] is not None and r["completion_tokens"] is not None]
    priced = pricing.is_priced(logsearch.stated_price(input_per_million), logsearch.stated_price(output_per_million))
    costs = [logsearch.cost_of(r, input_per_million, output_per_million) for r in known] if priced else []
    both = [r for r in answered if r["provider_ms"] is not None and r["wait_ms"] is not None]
    provider, waited = sum(r["provider_ms"] for r in both), sum(r["wait_ms"] for r in both)
    return {"requests": len(answered), "errors": sum(1 for r in records if r["kind"] == "error"), "tokens_known": len(known),
            "prompt_tokens": stats(r["prompt_tokens"] for r in known), "completion_tokens": stats(r["completion_tokens"] for r in known),
            "total_ms": stats(r["total_ms"] for r in answered), "provider_ms": stats(r["provider_ms"] for r in both),
            "wait_ms": stats(r["wait_ms"] for r in both), "wait_share": (waited / (provider + waited)) if provider + waited else None,
            "priced": priced, "cost": stats(costs) if priced else None}


def _pairs(records_a, records_b):
    """Pair the k-th time a question was asked in A with the k-th time in B. Returns (pairs, questions only in one of the logs)."""
    def by_question(records):
        table = {}
        for record in _answered(records):
            table.setdefault(" ".join(record["question"].lower().split()), []).append(record)
        return table
    a, b = by_question(records_a), by_question(records_b)
    pairs = [(x, y) for question in a for x, y in zip(a[question], b.get(question, []))]
    unmatched = sum(len(v) for v in a.values()) + sum(len(v) for v in b.values()) - 2 * len(pairs)
    return pairs, unmatched


def _models(records):
    served = {r["raw"].get("config", {}).get("llm_model_served") for r in _answered(records)} - {None}
    asked = {r["raw"].get("config", {}).get("llm_model") for r in _answered(records)} - {None}
    return asked, served


def compare(records_a, records_b, input_per_million=None, output_per_million=None):
    """Two logs of the same questions side by side. Refuses (returns {"refused": reason}) when they were not answered by the same
    models, because then a difference in tokens or time may be the model and not the change being measured."""
    (asked_a, served_a), (asked_b, served_b) = _models(records_a), _models(records_b)
    if asked_a != asked_b or served_a != served_b:
        return {"refused": f"the two logs were answered by different models (asked {sorted(asked_a)} vs {sorted(asked_b)}, answered by {sorted(served_a)} vs {sorted(served_b)}), "
                           "so a difference could be the model; compare logs of one model"}
    pairs, unmatched = _pairs(records_a, records_b)
    usable = [(x, y) for x, y in pairs if all(r["prompt_tokens"] is not None and r["completion_tokens"] is not None for r in (x, y))]
    if not usable:
        return {"refused": "no question was answered in both logs with the provider's token counts"}
    priced = pricing.is_priced(logsearch.stated_price(input_per_million), logsearch.stated_price(output_per_million))

    def side(index):
        records = [pair[index] for pair in usable]
        return {"prompt_tokens": statistics.mean(r["prompt_tokens"] for r in records), "completion_tokens": statistics.mean(r["completion_tokens"] for r in records),
                "total_ms": _mean_or_none(r["total_ms"] for r in records), "provider_ms": _mean_or_none(r["provider_ms"] for r in records),
                "wait_ms": _mean_or_none(r["wait_ms"] for r in records),
                "cost": statistics.mean(logsearch.cost_of(r, input_per_million, output_per_million) for r in records) if priced else None}
    return {"refused": None, "pairs": len(pairs), "usable": len(usable), "unmatched": unmatched, "a": side(0), "b": side(1), "priced": priced,
            "models": sorted(served_a)}


def _mean_or_none(values):
    values = [value for value in values if value is not None]
    return statistics.mean(values) if values else None


# ---------------------------------------------------------------------------- printing

def _ms(value):
    return "-" if value is None else f"{value:,.0f}"


def step_lines(report):
    """The per-step table. Times are milliseconds."""
    if not report["rows"]:
        return ["no step was recorded in these logs (a line written before Week 11 has none)"]
    lines = [f"{report['requests_with_steps']} requests recorded their steps" + (f"; {report['requests_without_steps']} older ones did not" if report["requests_without_steps"] else ""),
             f"{'step':<16}{'kind':<10}{'n':>6}{'mean ms':>10}{'median':>9}{'max':>9}{'p95':>9}{'share':>8}{'provider':>10}{'waited':>9}{'tokens in':>11}{'out':>7}"]
    for row in report["rows"]:
        time = row["time"]
        lines.append(f"{row['name']:<16}{str(row['kind']):<10}{time['n']:>6}{_ms(time['mean']):>10}{_ms(time['median']):>9}{_ms(time['max']):>9}{_ms(time['p95']):>9}"
                     f"{'-' if row['share'] is None else format(row['share'], '.0%'):>8}"
                     f"{_ms(row['provider']['mean']) if row['provider'] else '-':>10}{_ms(row['wait']['mean']) if row['wait'] else '-':>9}"
                     f"{_ms(row['prompt_tokens']['mean']) if row['prompt_tokens'] else '-':>11}{_ms(row['completion_tokens']['mean']) if row['completion_tokens'] else '-':>7}")
    if report["cold_spans"]:
        lines.append(f"{report['cold_spans']} steps were the first of their kind in a process (cold start)" + (" and are left out" if report["skipped_cold"] else " and are included; --skip-cold leaves them out"))
    return lines


def request_lines(report, price_source=None, input_per_million=None, output_per_million=None):
    """Whole-request numbers, tokens first, then time, then dollars with the prices printed under them."""
    def row(label, value, places=1):
        if value is None:
            return f"  {label:<26}no data"
        number = f",.{places}f"
        parts = [f"mean {format(value['mean'], number)}", f"median {format(value['median'], number)}", f"max {format(value['max'], number)}"]             + ([f"p95 {format(value['p95'], number)}"] if value["p95"] is not None else [])
        return f"  {label:<26}{', '.join(parts)}   (n {value['n']})"
    lines = [f"{report['requests']} answered requests" + (f", {report['errors']} failed" if report["errors"] else "")
             + f"; the provider reported tokens for {report['tokens_known']}" + ("" if report["tokens_known"] == report["requests"] else " (the rest are left out of every token and dollar figure, not counted as zero)"),
             row("prompt tokens", report["prompt_tokens"]), row("completion tokens", report["completion_tokens"]),
             row("total ms", report["total_ms"]), row("model ms at the provider", report["provider_ms"]), row("model ms waiting", report["wait_ms"])]
    if report["wait_share"] is not None:
        lines.append(f"  waiting is {report['wait_share']:.0%} of the model time (rate limit and back-off; a shorter prompt does not shorten it)")
    if report["priced"]:
        lines += [row("dollars per request", report["cost"], places=6),
                  "  " + pricing.describe_prices(logsearch.stated_price(input_per_million), logsearch.stated_price(output_per_million)),
                  f"  prices from: {price_source or '(source not stated)'}"]
    else:
        lines.append("  no price stated, so no dollars (pass --price-in, --price-out and --price-source)")
    return lines


def compare_lines(result, label_a, label_b, price_source=None, input_per_million=None, output_per_million=None):
    if result["refused"]:
        return [f"cannot compare: {result['refused']}"]
    a, b = result["a"], result["b"]
    lines = [f"{result['usable']} of {result['pairs']} paired questions had token counts in both logs" + (f"; {result['unmatched']} requests had no partner" if result["unmatched"] else "")
             + f"; model {', '.join(result['models']) or 'not recorded'}",
             f"{'':<20}{label_a[:22]:>24}{label_b[:22]:>24}{'b / a':>9}"]
    for key, name in (("prompt_tokens", "prompt tokens"), ("completion_tokens", "completion tokens"), ("total_ms", "total ms"), ("provider_ms", "provider ms"), ("wait_ms", "waiting ms")):
        x, y = a[key], b[key]
        lines.append(f"{name:<20}{'-' if x is None else format(x, ',.1f'):>24}{'-' if y is None else format(y, ',.1f'):>24}"
                     f"{'-' if not x or y is None else format(y / x, '.2f'):>9}")
    if result["priced"]:
        lines.append(f"{'dollars per request':<20}{a['cost']:>24.6f}{b['cost']:>24.6f}{(b['cost'] / a['cost']) if a['cost'] else float('nan'):>9.2f}")
        lines.append(pricing.describe_prices(logsearch.stated_price(input_per_million), logsearch.stated_price(output_per_million)) + f"; from: {price_source or '(source not stated)'}")
    return lines
