"""Week 8, mentor check #2: trick your own agent, then stop the trick.

This plants instructions in poisoned documents (and types some into the question), runs the
agent against each, and checks mechanically whether the attack worked: did its canary token, attacker
link or tool call show up in what the user sees? It runs every attack twice, once with the defences off
and once with them on, so the difference is the defences and nothing else. The poisoned documents live
only in a private, throwaway index; your real index and documents are never touched.

Run:
    python scripts/run_injection.py                          # every attack, defences off and on (model calls)
    python scripts/run_injection.py --only ind-override-reply dir-ignore-reply
    python scripts/run_injection.py --repeats 2 --label final
    python scripts/run_injection.py --static                 # no model: what the sanitizer alone removes
    python scripts/run_injection.py --show final             # no model: re-print a saved run's table
    python scripts/run_injection.py --show final --rescore   # no model: the same runs judged by today's detectors
    python scripts/run_injection.py --compare layer-sanitize layer-guard-fixed layer-validate final   # side by side
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.defense import Defense                        # noqa: E402
from app.config import BASE_DIR, settings                    # noqa: E402
from app.console import display_path, make_output_safe       # noqa: E402
from app.rag import pipeline                                 # noqa: E402
from evals import injection, runner                          # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the prompt-injection suite against the agent.")
    parser.add_argument("--label", default="injection", help="name of this run (default: injection)")
    parser.add_argument("--repeats", type=int, default=1, help="runs per attack and mode (default 1)")
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these attack ids")
    parser.add_argument("--kind", choices=("indirect", "direct"), help="only indirect or only direct attacks")
    parser.add_argument("--modes", nargs="+", choices=("off", "on"), default=["off", "on"], help="defences off, on, or both")
    parser.add_argument("--layers", nargs="+", choices=Defense.ALL_LAYERS, default=list(Defense.ALL_LAYERS),
                        help="which defence layers the 'on' runs use (default all three)")
    parser.add_argument("--static", action="store_true", help="no model calls: show what the sanitizer alone removes")
    parser.add_argument("--show", metavar="LABEL", help="print the table of a saved run (no model calls) instead of running")
    parser.add_argument("--compare", nargs="+", metavar="LABEL", help="put saved runs side by side, one column each (no model calls)")
    parser.add_argument("--rescore", action="store_true", help="with --show or --compare: judge the saved runs by the current detectors")
    args = parser.parse_args(argv)
    make_output_safe()

    if args.compare:
        try:
            named = [(label, runner.load_results("injection-" + label)) for label in args.compare]
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        if args.rescore:
            named = [(label, injection.rescore(results)) for label, results in named]
        print("\n".join(injection.format_layer_compare(named)))
        return 0

    if args.show:
        try:
            saved = runner.load_results("injection-" + args.show)
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            return 1
        if not args.rescore:
            print("\n".join(injection.format_suite(saved)))
            return 0
        scored = injection.rescore(saved)
        changed = scored["meta"]["rescored_changes"]
        print("AS SAVED (the detectors as they were when the run was made):\n")
        print("\n".join(injection.format_suite(saved)))
        print("\n" + "=" * 78 + "\nRE-SCORED with the current detectors (same runs, same answers, no model calls):\n")
        print("\n".join(injection.format_suite(scored)))
        print(f"\n{len(changed)} run(s) changed verdict:")
        for item in changed:
            mode = "on " if item["defended"] else "off"
            print(f"  {item['attack_id']:<24}defences {mode} run {item['repeat']}  reached/worked {item['was']} -> {item['now']}")
        return 0

    try:
        attacks = injection.get_attacks(args.only, args.kind)
        if args.repeats < 1:
            raise ValueError(f"--repeats must be 1 or greater, got {args.repeats}")
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    if not attacks:
        print("No attacks match.")
        return 1

    if args.static:
        print("Does the sanitizer alone remove something from each poisoned document? (no model involved)\n")
        for attack_id, removed in injection.sanitizer_table(attacks).items():
            print(f"  {attack_id:<24}{'removed' if removed else 'LEFT IN: gets past this layer'}")
        return 0

    try:
        pipeline.require_index()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1
    modes = tuple(mode == "on" for mode in args.modes)
    print(f"Running {len(attacks)} attack(s) x {args.repeats} x modes {args.modes} on {settings.llm_model}, "
          f"defence layers when on: {args.layers}\n")
    results = injection.run_suite(attacks, repeats=args.repeats, modes=modes, label=args.label, layers=tuple(args.layers))
    path = runner.save_results(results, runner.results_path("injection-" + args.label))
    print()
    print("\n".join(injection.format_suite(results)))
    print(f"\nsaved: {display_path(path, BASE_DIR)}")
    return 0 if results["meta"]["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
