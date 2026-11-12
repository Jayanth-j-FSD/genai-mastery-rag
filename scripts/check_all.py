"""One command that says whether anything is broken.

Before a week is tagged, a reviewer needs more than "it worked on my machine".
This runs four checks, none of which touch the network, your index or your free-tier quota:

  1. compile   every Python file parses (a syntax slip fails here)
  2. imports   every app module and every script can be imported (a missing package or a typo
               in an import fails here, not in front of the reviewer)
  3. --help    every script that takes arguments can build its argument parser
  4. tests     the offline unit tests: a fake embedder, a stub model and a throwaway index

It exits 0 only if all four pass, so it can gate a tag.

Run:
    python scripts/check_all.py
    python scripts/check_all.py --verbose      # also print the full unit-test output
    python scripts/check_all.py --quick        # skip the --help check
    python scripts/check_all.py --strict       # fail if any test was skipped (nothing unchecked)
"""
import argparse
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.console import make_output_safe  # noqa: E402

# Quiet library warnings and keep Chroma from sending usage statistics during a check.
ENV = dict(os.environ, PYTHONWARNINGS="ignore", ANONYMIZED_TELEMETRY="False", PYTHONIOENCODING="utf-8")
SKIP_DIRS = {".git", ".venv", ".python312", "__pycache__", "node_modules", "data"}
COMPILE_BATCH = 30        # files per py_compile call: all of them in one command line overflows Windows' 32,767 characters in a deep folder

IMPORT_PROBE = r"""
import importlib, importlib.util, os, pkgutil, sys
root = sys.argv[1]
sys.path.insert(0, root)
failed, modules, scripts = [], 0, 0
import app
packages = [("app", app)]
if os.path.isdir(os.path.join(root, "evals")):
    import evals
    packages.append(("evals", evals))
for prefix, package in packages:
    for info in pkgutil.walk_packages(package.__path__, prefix + "."):
        try:
            importlib.import_module(info.name); modules += 1
        except Exception as exc:
            failed.append(f"{info.name}: {type(exc).__name__}: {exc}")
folder = os.path.join(root, "scripts")
for name in sorted(os.listdir(folder)):
    if not name.endswith(".py"):
        continue
    try:
        spec = importlib.util.spec_from_file_location("script_" + name[:-3], os.path.join(folder, name))
        spec.loader.exec_module(importlib.util.module_from_spec(spec)); scripts += 1
    except BaseException as exc:
        failed.append(f"scripts/{name}: {type(exc).__name__}: {exc}")
print(f"{modules} {scripts}")
for line in failed:
    print("FAIL " + line)
sys.exit(1 if failed else 0)
"""


def python_files():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]    # hidden folders (virtual environments, other working copies) are not the project's own code
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(folder, name)


def run(args, timeout=600):
    return subprocess.run(args, cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def check_compile():
    files = list(python_files())
    problems = []
    for start in range(0, len(files), COMPILE_BATCH):                  # one command line has a length limit on Windows, and a deep folder path eats it
        result = run([sys.executable, "-m", "py_compile", *files[start:start + COMPILE_BATCH]])
        if result.returncode != 0:
            problems.append(result.stderr.strip())
    return not problems, f"{len(files)} files", "\n".join(problems)


def check_imports():
    result = run([sys.executable, "-c", IMPORT_PROBE, ROOT])
    lines = result.stdout.strip().splitlines()
    failures = [line[5:] for line in lines if line.startswith("FAIL ")]
    counts = (lines[0].split() if lines and not lines[0].startswith("FAIL") else ["?", "?"])
    detail = "\n".join(failures) or result.stderr.strip()
    return result.returncode == 0 and not failures, f"{counts[0]} modules, {counts[1]} scripts", detail


def check_help():
    scripts_dir = os.path.join(ROOT, "scripts")
    # Only scripts that parse arguments: others (ingest.py) would run for real on `--help`.
    wanted = [name for name in sorted(os.listdir(scripts_dir)) if name.endswith(".py")
              and "argparse" in open(os.path.join(scripts_dir, name), encoding="utf-8").read()]
    failures = []
    for name in wanted:
        result = run([sys.executable, os.path.join("scripts", name), "--help"], timeout=120)
        if result.returncode != 0:
            failures.append(f"scripts/{name} --help exited {result.returncode}: {result.stderr.strip()[-300:]}")
    return not failures, f"{len(wanted)} scripts", "\n".join(failures)


def interpret_tests(output, returncode, strict, verbose):
    """Turn unittest's output into (ok, one-line summary, detail to show).

    A skipped test is not a failure, but it means something was not checked (for example the offline
    embedding model is not downloaded, so its tests are skipped). `strict` refuses to call that clean.
    """
    ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
    skipped = re.search(r"skipped=(\d+)", output)
    summary = f"{ran.group(1)} tests in {ran.group(2)}s" if ran else "no result"
    if skipped:
        summary += f" ({skipped.group(1)} skipped)"
    ok = returncode == 0 and ran is not None
    detail = output if (not ok or verbose) else ""
    if ok and strict and skipped:
        ok = False
        detail = (f"{skipped.group(1)} test(s) were skipped, which --strict does not accept: something was not "
                  "checked (for example the offline model is not downloaded: run scripts/download_model.py).")
    return ok, summary, detail


def check_tests(verbose, strict=False):
    result = run([sys.executable, "-m", "unittest", "discover", "-s", os.path.join("tests", "unit")], timeout=1200)
    return interpret_tests((result.stdout + result.stderr).strip(), result.returncode, strict, verbose)


def main():
    parser = argparse.ArgumentParser(description="Compile, import, --help and unit-test everything.")
    parser.add_argument("--verbose", action="store_true", help="print the full unit-test output")
    parser.add_argument("--quick", action="store_true", help="skip the --help check")
    parser.add_argument("--strict", action="store_true", help="fail if any unit test was skipped")
    args = parser.parse_args()
    make_output_safe()

    checks = [("compile", check_compile), ("imports", check_imports)]
    if not args.quick:
        checks.append(("--help", check_help))
    checks.append(("unit tests", lambda: check_tests(args.verbose, args.strict)))

    print("== check_all ==")
    failed = []
    for name, check in checks:
        try:
            ok, summary, detail = check()
        except subprocess.TimeoutExpired:
            ok, summary, detail = False, "timed out", ""
        except OSError as exc:                                         # a check that could not even start is a failed check, not a traceback
            ok, summary, detail = False, "could not run", f"{type(exc).__name__}: {exc}"
        print(f"[{'ok' if ok else 'FAIL'}] {name:<11} {summary}")
        if detail:
            print("      " + detail.replace("\n", "\n      "))
        if not ok:
            failed.append(name)

    if failed:
        print(f"\nNOT clean: {', '.join(failed)} failed.")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
