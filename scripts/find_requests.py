"""Week 11, mentor check #1: find a specific past request in the logs, quickly, and read it step by step.

Support gets a vague complaint ("it told someone the wrong notice period, sometime last week, and it cited the employment
terms"). The log holds every request, so the work is narrowing: by words, by time, by which document the answer cited, by how slow or
costly it was, until a handful are left, then reading them one by one. Every filter you give must hold at once.

Run:
    python scripts/find_requests.py --text notice --since 2026-10-05 --until 2026-10-08
    python scripts/find_requests.py --text notice --cited Acme-Employment --distinct-answers     # how many different answers, and how often
    python scripts/find_requests.py --id 3f9ac210 --show                                          # one request, its steps as a table
    python scripts/find_requests.py --id 3f9ac210 --show --full                                   # and each passage in full, not cut to 90 characters
    python scripts/find_requests.py --status error                                                # the failed requests (errors.jsonl)
    python scripts/find_requests.py --slower-than 4000 --channel api
    python scripts/find_requests.py --drill DRILL_ID --text notice                                # the support drill's log (scripts/make_drill.py)
    python scripts/find_requests.py --text notice --costlier-than 0.002 --price-in 0.10 --price-out 0.40 --price-source "provider list, 2026-10"

It reads data/traces/traces.jsonl (answered requests) and errors.jsonl (failed ones) unless you name logs with --log. Lines written before
Week 11 are found too; they have no steps. Times are your machine's local time. Dollars appear only from the prices you state.
"""
import argparse
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.console import display_path, make_output_safe        # noqa: E402
from app.config import BASE_DIR                                  # noqa: E402
from evals import logsearch                                      # noqa: E402


def parse_when(text, end_of_range=False):
    """A date or a date and time ("2026-10-08", "2026-10-08 14:30", ISO) as a naive local datetime. A bare date means the start of
    that day for --since and the end of it for --until, so "--since 2026-10-08 --until 2026-10-08" is that whole day."""
    text = text.strip()
    try:
        moment = datetime.fromisoformat(text)
        if len(text) <= 10 and end_of_range:
            moment = moment.replace(hour=23, minute=59, second=59, microsecond=999999)
        return moment.astimezone().replace(tzinfo=None) if moment.tzinfo else moment
    except (ValueError, OverflowError, OSError):                # OSError and OverflowError: a year the machine's clock cannot convert
        raise ValueError(f"not a date or a time: {text!r} (use 2026-10-08 or 2026-10-08 14:30)") from None


def build_criteria(args):
    if args.answer_regex:
        try:
            re.compile(args.answer_regex)
        except re.error as exc:
            raise ValueError(f"--answer-regex is not a regular expression ({exc})") from None
    for name, value in (("--price-in", args.price_in), ("--price-out", args.price_out), ("--costlier-than", args.costlier_than), ("--slower-than", args.slower_than)):
        if value is not None and not 0 <= value < float("inf"):
            raise ValueError(f"{name} must be 0 or more")
    criteria = {"text": args.text, "answer_regex": args.answer_regex, "cited": args.cited, "retrieved_from": args.retrieved_from,
                "status": args.status, "channel": args.channel, "id": args.id, "slower_than": args.slower_than,
                "costlier_than": args.costlier_than, "input_per_million": args.price_in, "output_per_million": args.price_out,
                "grounded": None if args.grounded is None else args.grounded == "yes"}
    if args.since:
        criteria["since"] = parse_when(args.since)
    if args.until:
        criteria["until"] = parse_when(args.until, end_of_range=True)
    return criteria


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find a past request in the logs and read it step by step.")
    parser.add_argument("--text", action="append", default=[], metavar="WORD", help="a word or phrase in the question or the answer (repeatable: all must appear)")
    parser.add_argument("--answer-regex", metavar="PATTERN", help="a regular expression the answer must match, e.g. '(\\d+) (calendar )?days'")
    parser.add_argument("--since", metavar="WHEN", help="started at or after this time (2026-10-08 or 2026-10-08 14:30)")
    parser.add_argument("--until", metavar="WHEN", help="started at or before this time (a bare date includes that whole day)")
    parser.add_argument("--cited", metavar="DOC", help="the answer cited a document whose name contains this")
    parser.add_argument("--retrieved-from", metavar="DOC", help="a retrieved passage came from a document whose name contains this")
    parser.add_argument("--status", choices=["ok", "refused", "error"], help="ok = answered, refused = said it does not know, error = failed")
    parser.add_argument("--grounded", choices=["yes", "no"], help="yes = the app answered from the documents")
    parser.add_argument("--channel", help="how the request arrived: api, cli, batch or measure")
    parser.add_argument("--id", metavar="PREFIX", help="the start of a request id or trace id (every match is listed)")
    parser.add_argument("--slower-than", type=float, metavar="MS", help="took longer than this many milliseconds in all")
    parser.add_argument("--costlier-than", type=float, metavar="USD", help="cost more than this at the prices you state (needs --price-in and --price-out)")
    parser.add_argument("--price-in", type=float, metavar="USD", help="dollars per million input tokens (an assumption you state)")
    parser.add_argument("--price-out", type=float, metavar="USD", help="dollars per million output tokens (an assumption you state)")
    parser.add_argument("--price-source", metavar="TEXT", help="where the prices come from, printed beside every dollar figure")
    parser.add_argument("--distinct-answers", action="store_true", help="instead of the list, group identical answers and count them")
    parser.add_argument("--show", action="store_true", help="print every matching request in full, with its steps (use with --id)")
    parser.add_argument("--full", action="store_true", help="with --show: print each retrieved passage in full instead of its first 90 characters")
    parser.add_argument("--limit", type=int, default=50, help="show at most this many (the newest); 0 means all (default 50)")
    parser.add_argument("--log", action="append", metavar="PATH", help="read this log instead of the default traces and errors logs (repeatable)")
    parser.add_argument("--drill", metavar="DRILL_ID", help="read the support drill's log, data/drill/DRILL_ID/requests.jsonl")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.limit < 0:
        print("Error: --limit must be 0 or more.")
        return 1
    if args.costlier_than is not None and (args.price_in is None or args.price_out is None):
        print("Error: --costlier-than needs --price-in and --price-out: dollars come only from prices you state.")
        return 1
    if args.show and not (args.id or args.text or args.since or args.until or args.cited):
        print("Error: --show prints every match in full, so narrow it first (for example --id 3f9ac210).")
        return 1
    try:
        criteria = build_criteria(args)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    paths = logsearch.default_paths(args.log, args.drill)
    try:
        records, skipped, took = logsearch.load(paths)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    if not records:
        print("No log lines found in: " + ", ".join(display_path(path, BASE_DIR) for path in paths))
        return 1
    print(f"scanned {len(records)} records in {took:.0f} ms" + (f" ({skipped} lines could not be read)" if skipped else "")
          + " from " + ", ".join(display_path(path, BASE_DIR) for path in paths))
    for line in logsearch.banners(records):
        print(line)
    found = logsearch.search(records, criteria)
    undated = sum(1 for record in found if record["time"] is None)
    print(f"{len(found)} matched" + (f" ({undated} with no readable time)" if undated else ""))
    if not found:
        if args.cited:
            names = sorted({name for record in records for name in record["cited"]})
            print(f"No request cited a document whose name contains {args.cited!r}. The documents cited in these logs: {', '.join(names) or '(none)'}.")
        if args.costlier_than is not None and not (args.price_in or args.price_out):
            print("Prices of 0 give every request a cost of $0, so none is costlier; state the prices above 0 you want to test.")
        return 0

    if args.show:
        shown = found[-args.limit:] if args.limit else found
        for record in shown:
            print()
            print("\n".join(logsearch.show_lines(record, args.price_in, args.price_out, full=args.full)))
        if len(shown) < len(found):
            print(f"\n({len(found) - len(shown)} older matches not shown; narrow the search or use --limit 0)")
        if args.price_in is not None or args.price_out is not None:
            print(f"\nprices: {args.price_source or '(source not stated)'}")
        return 0
    if args.distinct_answers:
        groups = logsearch.distinct_answers(found)
        print(f"{len(groups)} distinct answer(s) among {sum(g['count'] for g in groups)} answered requests\n")
        shown_groups = groups[:args.limit] if args.limit else groups
        print("\n".join(logsearch.distinct_lines(shown_groups, sum(g["count"] for g in groups))))
        if len(shown_groups) < len(groups):
            print(f"\n({len(groups) - len(shown_groups)} rarer answers not shown; use --limit 0)")
        return 0
    shown = found[-args.limit:] if args.limit else found
    print()
    print("\n".join(logsearch.table_lines(shown)))
    if len(shown) < len(found):
        print(f"\n({len(found) - len(shown)} older matches not shown; narrow the search or use --limit 0)")
    print("\nRead one in full with: python scripts/find_requests.py --id <id> --show")
    return 0


if __name__ == "__main__":
    sys.exit(main())
