#!/usr/bin/env python3
"""Run every offline test and print one summary table.

The suite is deliberately made of plain ``assert`` scripts rather than pytest
(see CONTRIBUTING.md), which is fine for running one file while you work on it
but gives no aggregate signal: before this existed, "run the tests" meant
invoking forty files by hand and eyeballing forty exit codes. CI needs a single
command with a single exit code, and so does anyone evaluating the project.

Adds nothing to how a test decides pass/fail -- each file is still the authority
on itself, executed in its own process exactly as ``python test/<name>.py``
would. This only collects results.

Two things it surfaces that a bare loop would not:

**Coverage source.** ``graph_output/`` is git-ignored and lives in a private
dataset repo, so on a clone the real-corpus arms fall back to the synthetic
fixtures in ``test/fixtures/`` (see ``test/_fixture_paths.py``). Every such arm
prints ``[fixture]`` or ``[real]``, and the totals are rolled up here. A green
run against fixtures is not the same claim as a green run against the real
corpus, and the summary says which one you got.

**Deliberate skips.** Arms that need real corpus *scale* refuse to run on
fixtures instead of lowering their thresholds. Those are counted, not hidden --
a suite that quietly stopped checking things is the failure mode this guards.

Paid tests (``test_esg_kg_integration_llm.py``, ``test_esg_kg_system_llm.py``)
make real billed API calls and no-op unless their env var is set. They are
reported as NOOP and never counted as failures; this runner does not set those
variables for you.

Offline, no LLM/Neo4j/network. Run from the repo root:

    python test/run_all.py
    python test/run_all.py -v          # also echo each file's own output
    python test/run_all.py -k issuer   # only files matching a substring
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEST_DIR = REPO / "test"

PAID_TESTS = {
    "test_esg_kg_integration_llm.py": "RUN_LLM_INTEGRATION_TESTS",
    "test_esg_kg_system_llm.py": "RUN_LLM_SYSTEM_TEST",
}

_FIXTURE_RE = re.compile(r"\[fixture\]")
_REAL_RE = re.compile(r"\[real\]")
_SKIP_RE = re.compile(r"^SKIP\b", re.MULTILINE)


class Result:
    def __init__(self, name, status, seconds, fixture, real, skips, output):
        self.name = name
        self.status = status          # PASS | FAIL | NOOP
        self.seconds = seconds
        self.fixture = fixture
        self.real = real
        self.skips = skips
        self.output = output


def run_one(path: Path) -> Result:
    name = path.name
    env_var = PAID_TESTS.get(name)
    if env_var and not os.environ.get(env_var):
        return Result(name, "NOOP", 0.0, 0, 0, 0,
                      f"skipped: set {env_var}=1 to run (makes real, billed API calls)")

    start = time.time()
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    elapsed = time.time() - start
    out = (proc.stdout or "") + (proc.stderr or "")
    return Result(
        name,
        "PASS" if proc.returncode == 0 else "FAIL",
        elapsed,
        len(_FIXTURE_RE.findall(out)),
        len(_REAL_RE.findall(out)),
        len(_SKIP_RE.findall(out)),
        out,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Run every offline test, print a summary.")
    ap.add_argument("-k", "--filter", default="",
                    help="only run test files whose name contains this substring")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="echo each test file's own output as it runs")
    args = ap.parse_args()

    files = sorted(p for p in TEST_DIR.glob("test_*.py")
                   if args.filter in p.name)
    if not files:
        print(f"no test files match {args.filter!r}")
        return 1

    print(f"Running {len(files)} test file(s) with {sys.executable}\n")
    results = []
    for path in files:
        r = run_one(path)
        results.append(r)
        mark = {"PASS": "ok", "FAIL": "FAIL", "NOOP": "--"}[r.status]
        print(f"  {mark:>4}  {r.name:<46} {r.seconds:5.1f}s")
        if args.verbose or r.status == "FAIL":
            for line in r.output.rstrip().splitlines():
                print(f"        | {line}")

    failed = [r for r in results if r.status == "FAIL"]
    noop = [r for r in results if r.status == "NOOP"]
    fixture_arms = sum(r.fixture for r in results)
    real_arms = sum(r.real for r in results)
    skipped_arms = sum(r.skips for r in results)
    total_time = sum(r.seconds for r in results)

    print("\n" + "=" * 68)
    print(f"  files      : {len(results) - len(noop)} run, {len(failed)} failed, "
          f"{len(noop)} no-op (paid, env-gated)")
    print(f"  arms       : {real_arms} on real corpus, {fixture_arms} on fixtures, "
          f"{skipped_arms} skipped")
    print(f"  time       : {total_time:.1f}s")

    if fixture_arms and not real_arms:
        print("\n  NOTE: every data-backed arm ran against test/fixtures/, not the real\n"
              "  corpus. That is expected on a clone -- graph_output/ ships through a\n"
              "  private dataset repo. Run `python src/esg_kg/core/datasync.py pull`\n"
              "  for full coverage; the skipped arms above need real corpus scale.")
    print("=" * 68)

    if failed:
        print("\nFAILED:")
        for r in failed:
            print(f"  - {r.name}")
        return 1
    print("\nall green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
