#!/usr/bin/env python3
"""
run_report.py — build one labelled evaluation report from the artifacts on disk.

Why this file exists
--------------------
`evalu/out/evaluation_report_{final,full,nc,quick}.*` were produced on
2026-08-07 by a driver that was never committed. So when the issuer
cross-contamination fix landed in `claims_vs_conduct.py` and step 07 was re-run
for all five tickers, the reports could not be refreshed — there was no command,
and the shipped `_final` report kept quoting pre-fix numbers (NC.1 = 28.76%
FAIL) over post-fix dossiers. This module is that missing command.

It is deliberately NOT `run_evaluation.py`. That runner writes the four-tier
`evalu/evaluation_report.*` (pipeline metrics + grounding + IAA + Likert) and
answers a different question. This one assembles the §2 component-metric table
plus the negative control — the 15 rows the `_final` report carries — and writes
them under a caller-chosen label so before/after snapshots can sit side by side.

Three rules it enforces
-----------------------
1. **A metric that cannot be measured is reported as unmeasured, with its
   reason — never dropped.** The prose (purpose / how_to_read / limitation) is
   taken from the metric function itself, called with an empty input, so an
   unmeasured row explains the same metric the measured row would. Copying that
   prose into a second literal here is how the two would drift.
2. **Ticker attribution comes from `loaders.load_dossiers()`, never from a
   local glob.** `negative_control` reads `d["_ticker"]`; a hand-rolled loader
   that concatenates the same files without stamping it makes NC.1 report 0.00%
   on dossiers that are in fact 100% clean — same shape, opposite conclusion, no
   error. Pinned by `test/test_evalu_run_report.py` group [3].
3. **Read-only.** Every input is opened through `loaders`, which never writes
   back; the only files this module creates live under `--out-dir`.

Offline: no LLM, no Neo4j, no network.

Run:
    python evalu/run_report.py --label final                 # all 15 metrics + .docx
    python evalu/run_report.py --label nc_postfix --quick    # fast: graph + dossiers only
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evalu import lexicon as lexicon_mod  # noqa: E402
from evalu import loaders, metrics, negative_control, report, rubric  # noqa: E402
from evalu.model import MetricResult  # noqa: E402

OUT_DIR = REPO_ROOT / "evalu" / "out"

# The row order of the report, published rather than left implicit: it is the
# contract `metric_spec.SPECS` must cover and the test asserts against.
METRIC_ORDER = ["M1.1r", "M1.2r", "M1.1n", "M1.2n",
                "M2.1", "M2.2", "M2.3",
                "M3.1", "M3.2",
                "M4.1", "M4.2",
                "M5.1", "M5.2",
                "NC.1", "NC.2"]

UNMEASURED = "KHÔNG ĐO ĐƯỢC"

CORPUS_REASON = (
    f"{UNMEASURED} ở chế độ nhanh — cần stream toàn bộ corpus đã gán nhãn "
    "(~380 MB / 874k câu báo cáo + 174k câu tin tức). Bỏ `--quick` để đo."
)
REPAIR_REASON = (
    f"{UNMEASURED} ở chế độ nhanh — cần đọc 3.957 file đồ thị theo trang trong "
    "graph_output/graphs/ và ghép với all_validated_triples.json. Bỏ `--quick` để đo."
)


def _unmeasured(result: MetricResult, reason: str) -> MetricResult:
    """Keep the metric's own prose; blank the numbers and say why."""
    return replace(result, value=None, numerator=None, denominator=None,
                   passed=None, details={"unmeasured_reason": reason})


def _suffixed(result: MetricResult, suffix: str, channel: str) -> MetricResult:
    """M1.1 measured twice — once per ingestion channel — needs distinct ids."""
    return replace(result,
                   metric_id=f"{result.metric_id}{suffix}",
                   name=f"{result.name} — {channel}")


def _ingestion(path: Path, lexicon, limit: Optional[int]):
    return metrics.ingestion_metrics(loaders.stream_jsonl(path, limit=limit), lexicon)


def _page_graph_coverage() -> str:
    """How much of the per-page corpus M2.3 diffs against is actually present."""
    root = loaders.PAGE_GRAPHS_DIR
    if not root.exists():
        return "0 file trang"
    pages = sum(1 for p in root.glob("*/page*.json") if not p.name.endswith("_bugged.json"))
    return f"{pages:,} file trang / {sum(1 for _ in root.iterdir()):,} tài liệu có mặt trên đĩa"


def build_report(quick: bool = False,
                 corpus_limit: Optional[int] = None,
                 skip_repair: Optional[bool] = None) -> Dict[str, Any]:
    """
    Assemble the payload. `quick` skips the two heavy inputs (labelled corpora,
    per-page graphs); `corpus_limit` caps the JSONL streams instead of skipping
    them, which is what makes a fast non-vacuity check possible in the test.
    """
    started = time.perf_counter()
    if skip_repair is None:
        skip_repair = quick

    lexicon = lexicon_mod.build_lexicon()
    schema = loaders.load_schema()
    graph = loaders.load_resolved_graph()
    nodes = graph.get("nodes", [])
    dossiers, tickers = loaders.load_dossiers()

    results: List[MetricResult] = []

    # --- module 1: ingestion (two channels, one stream each) -----------------
    scanned: Dict[str, Any] = {}
    for suffix, channel, path in (("r", "báo cáo", loaders.REPORT_SENTENCES),
                                  ("n", "tin tức", loaders.NEWS_SENTENCES)):
        reason = CORPUS_REASON if quick else None
        if not quick:
            try:
                snr, prov = _ingestion(path, lexicon, corpus_limit)
                scanned[suffix] = f"{int(prov.denominator or 0):,}"
            except loaders.MissingArtifact as exc:
                # The corpora ship via Hugging Face, not Git (CLAUDE.md §Environment),
                # so a fresh or half-finished `datasync pull` leaves them absent. That
                # is a boundary of THIS run, not a property of the metric — say which
                # file is missing and how to get it, never emit a number for it.
                reason = (f"{UNMEASURED} — thiếu artifact: {exc}. "
                          "Lấy về bằng: python src/esg_kg/core/datasync.py pull")
        if reason:
            snr = _unmeasured(metrics.esg_signal_to_noise(iter(()), lexicon), reason)
            prov = _unmeasured(metrics.provenance_rate(iter(())), reason)
            scanned[suffix] = UNMEASURED
        results.append(_suffixed(snr, suffix, channel))
        results.append(_suffixed(prov, suffix, channel))

    # --- module 2: extraction ------------------------------------------------
    results.append(metrics.temporal_metadata_completeness(graph))
    results.append(metrics.schema_compliance_rate(graph, schema))

    triples_seen: Any = UNMEASURED
    if skip_repair:
        results.append(_unmeasured(metrics.value_preservation_guard([], []), REPAIR_REASON))
    else:
        try:
            triples = loaders.load_validated_triples()
            before, after, match_stats = loaders.repair_pairs(
                triples, loaders.identity_keys_map(schema))
            guard = metrics.value_preservation_guard(before, after)
            guard.details["match_stats"] = match_stats
            # A partial per-page corpus shrinks the denominator without saying so.
            # 100% over 7% of the pages and 100% over all of them are different
            # findings; the reader must be able to tell which one this is.
            guard.details["note"] = (
                f"Mẫu số chỉ gồm node ghép được cả hai phía — {_page_graph_coverage()}. "
                "Đọc kèm dòng 'Ghép node trước/sau sửa' bên trên: `chỉ có sau` lớn "
                "nghĩa là phía trang chưa được pull đủ, không phải node bị mất.")
            results.append(guard)
            triples_seen = f"{len(triples):,}"
        except loaders.MissingArtifact as exc:
            results.append(_unmeasured(
                metrics.value_preservation_guard([], []),
                f"{UNMEASURED} — thiếu artifact: {exc}. "
                "Lấy về bằng: python src/esg_kg/core/datasync.py pull"))

    # --- modules 3 & 4: resolution and the indicator axis --------------------
    results.append(metrics.timeless_identity_violation_rate(schema))
    results.append(metrics.cluster_conciseness(graph))
    results.append(metrics.indicator_alignment_coverage(graph))
    results.append(metrics.zero_report_self_praise_exclusion(graph))

    # --- module 5: cross-check ----------------------------------------------
    results.append(metrics.abstention_rate(dossiers))
    results.append(metrics.self_verification_exclusion_rate(dossiers))

    # --- negative control ----------------------------------------------------
    registry = loaders._read_json(REPO_ROOT / "config" / "issuer_registry.json")
    variants = negative_control.load_issuer_variants(registry)
    results.append(negative_control.evidence_attribution_audit(dossiers, nodes, variants))
    results.append(negative_control.same_feed_specificity(
        negative_control.citations_by_ticker(dossiers, nodes),
        negative_control.pool_by_ticker(nodes)))

    context = {
        "Từ vựng ESG neo được (M1.1)": f"{len(lexicon):,} cụm từ",
        "Số câu đã quét (báo cáo)": scanned["r"],
        "Số câu đã quét (tin tức)": scanned["n"],
        "Đồ thị đã phân giải": f"{len(nodes):,} node / {len(graph.get('edges', [])):,} cạnh",
        "Bộ ba đã kiểm định": triples_seen,
        "Hồ sơ đối soát": f"{len(dossiers):,} claim / {len(tickers)} mã CK",
        "Mã chứng khoán": ", ".join(tickers),
        "Thời gian chạy": f"{time.perf_counter() - started:.1f}s",
    }
    emitted = [m.metric_id for m in results]
    if emitted != METRIC_ORDER:                    # order is the published contract
        raise AssertionError(f"metric order drifted: {emitted} != {METRIC_ORDER}")
    return report.build_payload(results, context, rubric=rubric.rubric_spec())


def write_report(payload: Dict[str, Any],
                 out_dir: Path = OUT_DIR,
                 label: str = "latest",
                 docx: bool = False,
                 focused: bool = False) -> Dict[str, Path]:
    """
    `focused=True` additionally writes the paper-shaped Evaluation section
    (setup → definitions with equations → results → hypothesis test → threats to
    validity). It renders from THIS payload, so the two documents cannot report
    different numbers for the same run.
    """
    written = report.write(payload, Path(out_dir), label=label)
    if focused:
        from evalu import metric_spec
        path = Path(out_dir) / f"evaluation_{label}_focused.md"
        path.write_text(metric_spec.render_focused(payload), encoding="utf-8")
        written["focused"] = path
    if docx:
        from evalu import export_docx  # lazy: python-docx is optional (§4.4)
        target = Path(out_dir) / f"evaluation_report_{label}.docx"
        written["docx"] = export_docx.export(written["markdown"], target)
        if focused:
            written["focused_docx"] = export_docx.export(
                written["focused"], Path(out_dir) / f"evaluation_{label}_focused.docx")
    return written


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="latest",
                    help="output name: evaluation_report_<label>.{json,md,docx}")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--quick", action="store_true",
                    help="skip the labelled corpora and the per-page graph diff "
                         "(M1.x / M2.3 are reported as unmeasured, not dropped)")
    ap.add_argument("--corpus-limit", type=int, default=None,
                    help="cap each labelled corpus at N records instead of skipping it")
    ap.add_argument("--docx", action="store_true", help="also export .docx")
    ap.add_argument("--focused", action="store_true",
                    help="also write the paper-shaped Evaluation section "
                         "(định nghĩa + công thức + kết quả + threats to validity)")
    args = ap.parse_args(argv)

    payload = build_report(quick=args.quick, corpus_limit=args.corpus_limit)
    written = write_report(payload, Path(args.out_dir), label=args.label,
                           docx=args.docx, focused=args.focused)

    print(f"\nevaluation_report_{args.label} — {payload['context']['Thời gian chạy']}")
    for m in payload["component_metrics"]:
        status = "PASS" if m["passed"] else ("FAIL" if m["passed"] is False else "info")
        print(f"  {m['metric_id']:<6} {m['pct'] or UNMEASURED:>10}  {status:<4} {m['name']}")
    for kind, path in written.items():
        print(f"  -> {kind}: {path}")
    return 0


if __name__ == "__main__":
    from esg_kg.core.console import ensure_utf8_stdout  # noqa: E402

    sys.path.insert(0, str(REPO_ROOT / "src"))
    ensure_utf8_stdout()
    sys.exit(main())
