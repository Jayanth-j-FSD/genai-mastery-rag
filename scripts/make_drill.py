"""Week 11, the support drill: build a request log with one wrong answer planted in it, and a vague complaint about it.

A support drill is practice for the day someone says "the assistant gave a customer a wrong answer last week" and all you
have is the log. This builds that log: about three thousand SYNTHETIC requests over four weeks, shaped exactly like the real ones, with
one notice-period answer that states a number no document states. You get a vague complaint (a topic, a rough window, which document
the answer cited, no number). Finding the request is your work. This script does not print where it is, and nothing it writes says.

Run:
    python scripts/make_drill.py                          # writes data/drill/<drill id>/ and tells you the id
    python scripts/find_requests.py --drill <drill id> --text notice --since ... --until ...     # narrow it down
    python scripts/check_drill.py <drill id> <request id>                                         # check your answer (five guesses)

What it writes into data/drill/<drill id>/ (untracked, nothing here is ever committed):
    requests.jsonl    the log, one request per line, every line marked "synthetic": true
    complaint.txt     what support was told
    drill-meta.json   when it was made, what is real and what is invented, and a commitment that lets check_drill.py tell whether a guess
                      is right without the answer being stored. It holds no hint about the planted request.
"""
import argparse
import os
import re
import shutil
import sys

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import BASE_DIR                           # noqa: E402
from app.console import display_path, make_output_safe    # noqa: E402
from evals import drill                                    # noqa: E402


def inside_drill_folder(path):
    """True when `path` is a folder under data/drill, so a drill can never be written over something else."""
    root, target = os.path.abspath(drill.DRILL_DIR), os.path.abspath(path)
    return target != root and os.path.commonpath([root, target]) == root


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a support drill: a synthetic request log with one planted wrong answer.")
    parser.add_argument("--n", type=int, default=3000, help="how many requests (default 3000)")
    parser.add_argument("--days", type=int, default=28, help="how many days they span (default 28)")
    parser.add_argument("--out", help="the folder to write, which must be under data/drill (default data/drill/<drill id>)")
    parser.add_argument("--seed", type=int, help="for tests only: makes the drill, and so the answer, reproducible; by default it is random")
    parser.add_argument("--force", action="store_true", help="replace a folder that already exists")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.n < 200 or args.days < 7:
        print("Error: a drill needs at least 200 requests over at least 7 days, or there is nothing to search.")
        return 1
    if args.out and not inside_drill_folder(args.out):
        print(f"Error: --out must be a folder under {display_path(drill.DRILL_DIR, BASE_DIR)}.")
        return 1
    try:
        built = drill.generate(seed=args.seed, n=args.n, days=args.days)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1
    drill_id = built["meta"]["drill_id"]
    out = args.out or os.path.join(drill.DRILL_DIR, drill_id)
    if os.path.exists(out) and not args.force:
        print(f"Error: {display_path(out, BASE_DIR)} already exists. Use --force to replace it, or pick another --out.")
        return 1
    if os.path.isdir(out) and inside_drill_folder(out):
        shutil.rmtree(out)
    drill.write(built, out)
    drill_id_for_commands = os.path.basename(os.path.normpath(out))
    print(f"SYNTHETIC drill {drill_id} written to {display_path(out, BASE_DIR)}: {built['meta']['n_records']} requests, "
          f"{built['meta']['window']['start'][:10]} to {built['meta']['window']['end'][:10]}.\n")
    print("The complaint:\n")
    print(re.sub(r"^", "    ", built["complaint"], flags=re.MULTILINE))
    print(f"Start with:  python scripts/find_requests.py --drill {drill_id_for_commands} --text notice")
    print(f"Check with:  python scripts/check_drill.py {drill_id_for_commands} <request id>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
