#!/usr/bin/env python3
"""
test_evalu_run_report.py — the labeled-report driver (`evalu/run_report.py`).

Why this file exists
--------------------
`evalu/out/evaluation_report_{final,full,nc,quick}.*` were produced on
2026-08-07 by a driver that was never committed. When the issuer
cross-contamination fix landed in `claims_vs_conduct.py` and step 07 was re-run
for all five tickers, the reports could not be regenerated — there was no
command. The numbers in the shipped `_final` report are therefore from BEFORE
the fix (NC.1 = 28.76% FAIL) while the dossiers on disk are from AFTER it, and
`docs/PROJECT_OVERVIEW.md` §16.1(e) cites an `evaluation_report_nc_postfix.json`
that exists in no commit and on no disk.

This test pins the driver that closes that gap. Three of its groups guard
mistakes that were actually made while diagnosing the above:

  * **[3] the `_ticker` trap.** `negative_control.evidence_attribution_audit`
    reads `d["_ticker"]` to know which company a dossier belongs to.
    `loaders.load_dossiers()` injects it; a hand-rolled loader that concatenates
    the same files does not — and NC.1 then silently reports 0.00% (every
    citation counted as cross-company) on dossiers that are in fact 100% clean.
    Same shape, opposite conclusion, no error. The counter-arm proves the field
    is load-bearing rather than decorative.

  * **[2] quick mode must not DROP a metric.** `run_evaluation.py`'s docstring
    states the rule: a metric that could not be measured is printed as
    unmeasured, with its reason, never omitted. A missing row reads as an
    oversight; "KHÔNG ĐO ĐƯỢC — needs the 380 MB corpus" reads as a boundary.
    The non-vacuity arm runs the same metrics WITH a small corpus slice, so
    "quick has all 15 ids" cannot pass by the two modes being identical.

  * **[4] the report may never perturb what it measures.** `evalu/__init__.py`
    promises every module reads `graph_output/` strictly read-only. Asserted by
    sha256 over the inputs, before and after a real run.

Offline: reads artifacts already on disk, writes only into a temp directory.
No LLM, no Neo4j, no network.
Run:  python test/test_evalu_run_report.py
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.core.console import ensure_utf8_stdout  # noqa: E402

ensure_utf8_stdout()

from evalu import loaders, negative_control, run_report  # noqa: E402

checks = 0
failures: list[str] = []


def check(cond: bool, label: str) -> bool:
    global checks
    checks += 1
    ok = bool(cond)
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        failures.append(label)
    return ok


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# The contract the shipped `_final` report established. Hard-coded on purpose:
# reading it back out of the file the driver overwrites would make the test
# agree with whatever it just wrote.
EXPECTED_IDS = ["M1.1r", "M1.2r", "M1.1n", "M1.2n",
                "M2.1", "M2.2", "M2.3",
                "M3.1", "M3.2",
                "M4.1", "M4.2",
                "M5.1", "M5.2",
                "NC.1", "NC.2"]

# Metrics that need an input too big to stream in quick mode: the 380 MB labelled
# corpora (M1.x) and the 3,957 per-page graph files M2.3 diffs against.
CORPUS_BOUND = {"M1.1r", "M1.2r", "M1.1n", "M1.2n", "M2.3"}


# ---------------------------------------------------------------------------
print("\n[1] metric roster, order, and report envelope")
# ---------------------------------------------------------------------------
quick = run_report.build_report(quick=True)

ids = [m["metric_id"] for m in quick["component_metrics"]]
check(ids == EXPECTED_IDS, f"15 metrics in the documented order (got {len(ids)})")
check(quick.get("schema") == "evalu.report/v1", "payload declares evalu.report/v1")
check(isinstance(quick.get("context"), dict) and len(quick["context"]) >= 6,
      "context table is populated")
check(quick["context"].get("Mã chứng khoán"), "context names the tickers measured")
check(quick.get("expert_rubric"), "rubric spec is carried (tier-3 scaffolding)")
check(quick.get("expert_evaluation") is None,
      "no expert ballots are invented when none were collected")

by_id = {m["metric_id"]: m for m in quick["component_metrics"]}
check(by_id["M5.1"]["denominator"] == 464,
      f"M5.1 measures all 464 dossiers (got {by_id['M5.1']['denominator']})")


# ---------------------------------------------------------------------------
print("\n[2] quick mode marks metrics unmeasured — it never drops them")
# ---------------------------------------------------------------------------
for mid in sorted(CORPUS_BOUND):
    m = by_id[mid]
    check(m["value"] is None, f"{mid} reports no value in quick mode")
    check(bool((m.get("details") or {}).get("unmeasured_reason")),
          f"{mid} carries a stated reason instead of a silent gap")

# Non-vacuity: the same metrics DO produce numbers when their input is supplied.
# A small slice keeps the test fast while proving the two modes differ. The
# labelled corpora ship via Hugging Face, so whichever channel is on THIS disk
# is the one the arm runs on; if neither is, the synthetic group below still
# guarantees the assertion is not vacuous.
CHANNELS = {"r": loaders.REPORT_SENTENCES, "n": loaders.NEWS_SENTENCES}
present = [s for s, p in CHANNELS.items() if p.exists()]
sliced = run_report.build_report(corpus_limit=4000, skip_repair=True)
sliced_by_id = {m["metric_id"]: m for m in sliced["component_metrics"]}
check([m["metric_id"] for m in sliced["component_metrics"]] == EXPECTED_IDS,
      "full mode reports the same 15 metrics")
for suffix in present:
    check(sliced_by_id[f"M1.2{suffix}"]["denominator"] == 4000,
          f"corpus_limit is honoured for channel {suffix} "
          f"(got {sliced_by_id[f'M1.2{suffix}']['denominator']})")
    check(sliced_by_id[f"M1.1{suffix}"]["value"] is not None,
          f"M1.1{suffix} is measurable once the corpus is read — quick mode's None is a "
          "boundary, not the metric always being empty")
for suffix in set(CHANNELS) - set(present):
    reason = (sliced_by_id[f"M1.1{suffix}"].get("details") or {}).get("unmeasured_reason", "")
    check(sliced_by_id[f"M1.1{suffix}"]["value"] is None and "datasync" in reason,
          f"absent corpus {suffix} degrades to unmeasured and names how to fetch it, "
          "instead of crashing the run or reporting 0")
if not present:
    print("  NOTE no labelled corpus on this disk — see group [2b]")


# ---------------------------------------------------------------------------
print("\n[2b] a missing artifact is a boundary, never a crash and never a zero")
# ---------------------------------------------------------------------------
# Always runs, whatever this disk holds: point the loader at a path that cannot
# exist and assert the run survives with an honest row.
saved = loaders.REPORT_SENTENCES
try:
    loaders.REPORT_SENTENCES = REPO_ROOT / "data" / "labeled" / "__no_such_corpus__.jsonl"
    degraded = run_report.build_report(corpus_limit=1000, skip_repair=True)
finally:
    loaders.REPORT_SENTENCES = saved
deg_by_id = {m["metric_id"]: m for m in degraded["component_metrics"]}
check([m["metric_id"] for m in degraded["component_metrics"]] == EXPECTED_IDS,
      "all 15 rows survive a missing input")
for mid in ("M1.1r", "M1.2r"):
    d = deg_by_id[mid].get("details") or {}
    check(deg_by_id[mid]["value"] is None, f"{mid} reports no value, not 0.0")
    check("__no_such_corpus__" in d.get("unmeasured_reason", ""),
          f"{mid} names the artifact that was missing")
check(deg_by_id["M5.1"]["value"] is not None,
      "one missing input does not blank the metrics that were measurable")


# ---------------------------------------------------------------------------
print("\n[3] NC.1 ticker attribution is load-bearing (the `_ticker` trap)")
# ---------------------------------------------------------------------------
nc1 = by_id["NC.1"]
det = nc1.get("details") or {}
check((nc1.get("denominator") or 0) > 0,
      f"NC.1 has citations to audit (denominator={nc1.get('denominator')})")
check(det.get("cited_total") == nc1.get("denominator"),
      "NC.1 details agree with its own denominator")

dossiers, tickers = loaders.load_dossiers()
check(all(d.get("_ticker") for d in dossiers),
      "loaders.load_dossiers stamps _ticker on every dossier")
check(len(tickers) == 5, f"five tickers found on disk (got {len(tickers)})")

graph = loaders.load_resolved_graph()
registry = json.loads((REPO_ROOT / "config" / "issuer_registry.json").read_text(encoding="utf-8"))
variants = negative_control.load_issuer_variants(registry)

stripped = copy.deepcopy(dossiers)
for d in stripped:
    d.pop("_ticker", None)
blind = negative_control.evidence_attribution_audit(stripped, graph["nodes"], variants)
check(blind.value != nc1["value"],
      f"without _ticker the same dossiers score differently ({blind.value} vs "
      f"{nc1['value']}) — the field changes the verdict, so the driver must supply it")


# ---------------------------------------------------------------------------
print("\n[4] a report run never perturbs what it measures")
# ---------------------------------------------------------------------------
watched = [REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"]
watched += sorted((REPO_ROOT / "graph_output" / "crosscheck").glob("*_claim_assessments.json"))
before = {p: sha256(p) for p in watched}

tmp = Path(tempfile.mkdtemp(prefix="evalu_report_"))
try:
    written = run_report.write_report(quick, tmp, label="unittest")
    check(all(sha256(p) == before[p] for p in watched),
          f"{len(watched)} measured artifacts are byte-identical after the run")

    # ---------------------------------------------------------------------
    print("\n[5] writes are scoped to the out directory")
    # ---------------------------------------------------------------------
    produced = sorted(p.name for p in tmp.iterdir())
    check(produced == ["evaluation_report_unittest.json",
                       "evaluation_report_unittest.md"],
          f"exactly the two labelled files are written (got {produced})")
    check(written["json"].parent == tmp and written["markdown"].parent == tmp,
          "returned paths point inside the requested directory")

    md = written["markdown"].read_text(encoding="utf-8")
    for mid in EXPECTED_IDS:
        if not check(f"| {mid} |" in md, f"{mid} appears as a row in the Markdown"):
            break
    check("KHÔNG ĐO ĐƯỢC" in md or "—" in md,
          "unmeasured metrics are visible in the rendered table")

    # ---------------------------------------------------------------------
    print("\n[6] determinism — same inputs, same payload")
    # ---------------------------------------------------------------------
    again = run_report.build_report(quick=True)
    a = json.dumps(quick, ensure_ascii=False, sort_keys=True, default=str)
    b = json.dumps(again, ensure_ascii=False, sort_keys=True, default=str)
    a = a.replace(quick["generated_at"], "<TS>").replace(
        str(quick["context"].get("Thời gian chạy")), "<T>")
    b = b.replace(again["generated_at"], "<TS>").replace(
        str(again["context"].get("Thời gian chạy")), "<T>")
    check(a == b, "two runs agree on every field except the timestamp and runtime")
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
print("\n[7] focused view: no metric may be shown without its formula")
# ---------------------------------------------------------------------------
# The full report explains each metric in prose. The focused view answers four
# questions per row — what it is, the formula, what it is built from, why it is
# needed — and then the number. A row rendered without a formula is the failure
# this group exists to prevent: a bare percentage is exactly what a reader
# cannot check.
from evalu import metric_spec  # noqa: E402

check(run_report.METRIC_ORDER == EXPECTED_IDS,
      "the driver publishes its metric order rather than leaving it implicit")

for mid in run_report.METRIC_ORDER:
    spec = metric_spec.SPECS.get(mid)
    if not check(bool(spec), f"{mid} has a spec entry"):
        continue
    for fieldname in ("what", "formula", "built_from", "why"):
        check(len(spec.get(fieldname, "").strip()) > 10,
              f"{mid}.{fieldname} is filled in")

focused = metric_spec.render_focused(quick)
for mid in EXPECTED_IDS:
    if not check(mid in focused, f"{mid} appears in the focused view"):
        break
check(metric_spec.SPECS["M5.1"]["formula"] in focused,
      "the formula itself is rendered, not just referenced")
check("96.55%" in focused or "96,55%" in focused,
      "the live number travels with the formula (M5.1 = 96.55%)")
check("KHÔNG ĐO ĐƯỢC" in focused,
      "an unmeasured row keeps its formula and says it was not measured")

# A metric with no spec must stop the render, not print a naked number.
saved_spec = metric_spec.SPECS.pop("M5.1")
try:
    raised = False
    try:
        metric_spec.render_focused(quick)
    except KeyError:
        raised = True
    check(raised, "a metric with no formula raises instead of rendering bare")
finally:
    metric_spec.SPECS["M5.1"] = saved_spec


print(f"\n{'=' * 60}")
if failures:
    print(f"FAILED — {len(failures)}/{checks} checks failed:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"OK — {checks}/{checks} checks passed")
