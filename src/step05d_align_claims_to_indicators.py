"""Step 5d — align claims/goals to indicators the keyword tier could not resolve (LLM, budgeted).

Design: docs/STANDARD_INDICATOR_AXIS.md §5.4. Optional stage; the pipeline is complete without
it — step05c's keyword tier already emits the unambiguous `alignsWithIndicator` edges, and this
stage only raises coverage on the ambiguous remainder.

WHAT IT IS (and is NOT)
It is TOPIC CLASSIFICATION: "which TT96/SSC-IFC indicator, if any, is this claim about?" The edge
it writes (`alignsWithIndicator`, `alignment_method=llm`) is a base-graph fact, the same kind
step05c writes by keyword — NOT a supports/contradicts judgement. Adjudicating whether the claim
is honoured stays in step07's advisory layer (docs/STANDARD_INDICATOR_AXIS.md §2.4).

Separated from step05c so each stage is cleanly "NO LLM" or "LLM": step05c stays free and
re-runnable, step05d is the one place that spends money here. `alignment_method` on every edge
lets step10 measure keyword-tier vs LLM-tier precision independently.

Append-only over the resolved graph, like step05c. Budgeted by --max-llm-pairs.

  python src/step05d_align_claims_to_indicators.py --dry-run      # counts candidates, no LLM
  python src/step05d_align_claims_to_indicators.py --max-llm-pairs 200
"""

import argparse
import json
import logging
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from step01_extract_kpi_from_jsonl import REPO_ROOT
from step03_fix_invalid_triplets import load_schema_sets
from step05c_link_standard_indicators import GraphPatch, temporal_md
from step07_crosscheck_claims_vs_conduct import _OpenAIProvider, RateLimiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_RESOLVED = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_DEFS = REPO_ROOT / "kpi_definitions_construction.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_STATS_OUT = REPO_ROOT / "graph_output" / "resolved" / "indicator_align_llm_stats.json"

ALIGN_CLASSES = ("SustainabilityClaim", "Goal", "Initiative")
TODAY = date.today().isoformat()

SYSTEM = (
    "You classify a Vietnamese company ESG statement against a fixed list of disclosure "
    "indicators (Circular 96/2020/TT-BTC and the SSC-IFC ESG guide). Choose the ONE indicator "
    "the statement is primarily about, or \"none\" if it is generic / not about any of them. "
    "Do not guess — 'none' is the right answer for boilerplate. Return only JSON: "
    "{\"indicator_id\": \"TT96-6.1.1\"|...|\"none\", \"confidence\": 0-1}."
)


def build_prompt(text: str, defs: List[Dict[str, Any]]) -> str:
    catalog = "\n".join(f"- {d['id']}: {d['name']} ({d['pillar']})" for d in defs)
    return (f"INDICATORS:\n{catalog}\n\nSTATEMENT:\n\"{text[:600]}\"\n\n"
            "Which single indicator is this statement primarily about?")


def node_text(props: Dict[str, Any]) -> str:
    return " ".join(str(props.get(k) or "") for k in ("description", "name", "title")).strip()


def parse_reply(raw: str, valid_ids: set) -> Optional[str]:
    try:
        out = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            out = json.loads(m.group(0))
        except Exception:
            return None
    # Valid JSON of the wrong SHAPE ('[]', '"txt"', '42') must be refused like any other
    # unusable reply. Without this the `.get` below raised AttributeError, and since run()
    # writes the graph only after the loop and catches nothing here, one odd reply discarded
    # every adjudication already paid for in that run.
    if not isinstance(out, dict):
        return None
    ind = out.get("indicator_id")
    return ind if ind in valid_ids else None


def run(args: argparse.Namespace) -> None:
    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run step05c first).")
        return
    graph = json.loads(args.input.read_text(encoding="utf-8"))
    defs = json.loads(args.defs.read_text(encoding="utf-8"))
    entity_classes, edge_labels, edge_dirs = load_schema_sets(
        json.loads(args.schema.read_text(encoding="utf-8")))
    gp = GraphPatch(graph, entity_classes, edge_labels, edge_dirs)
    valid_ids = {d["id"] for d in defs}
    ind_idx = {(gp.nodes[i]["properties"] or {}).get("id"): i
               for i in range(len(gp.nodes)) if gp.nodes[i].get("class") == "StandardIndicator"}
    missing = [k for k in valid_ids if k not in ind_idx]
    if missing:
        logger.warning(f"{len(missing)} indicator node(s) absent — run step05c first. Missing e.g. {missing[:3]}")

    # candidates = align-classes with NO existing alignsWithIndicator edge (keyword or prior LLM)
    already = {e["subject"] for e in gp.edges if e.get("predicate") == "alignsWithIndicator"}
    candidates: List[int] = []
    for i in range(gp.n_nodes0):
        if gp.nodes[i].get("class") in ALIGN_CLASSES and i not in already:
            if node_text(gp.nodes[i].get("properties") or {}):
                candidates.append(i)
    logger.info(f"{len(candidates)} unaligned {ALIGN_CLASSES} node(s); "
                f"{len(already)} already aligned. Budget {args.max_llm_pairs}.")

    if args.dry_run:
        logger.info("--dry-run: no LLM calls, nothing written.")
        return

    provider = _OpenAIProvider(args.openai_model, args.rate_limit)
    if not provider.enabled:
        logger.error("No OpenAI provider (need OPENAI_API_KEY in .env) — step05d requires an LLM.")
        return

    stats: Counter = Counter()
    per_indicator: Counter = Counter()
    for i in candidates[: args.max_llm_pairs]:
        text = node_text(gp.nodes[i]["properties"])
        try:
            raw = provider.call(SYSTEM, build_prompt(text, defs))
            provider.calls += 1
        except Exception as e:
            provider.failures += 1
            logger.warning(f"LLM call failed on node {i} ({e}).")
            if provider.failures >= 3 and provider.calls == 0:
                logger.error("3 failures, 0 successes — aborting.")
                break
            continue
        ind = parse_reply(raw, valid_ids)
        stats["adjudicated"] += 1
        if not ind or ind not in ind_idx:
            stats["none_or_absent"] += 1
            continue
        if gp.add_edge(i, "alignsWithIndicator", ind_idx[ind], temporal_md(gp.nodes[i]["properties"]),
                       extra={"alignment_method": "llm"}):
            stats["edges_added"] += 1
            per_indicator[ind] += 1

    report = {"candidates": len(candidates), "adjudicated": stats["adjudicated"],
              "edges_added": stats["edges_added"], "none_or_absent": stats["none_or_absent"],
              "dropped_invalid": gp.dropped_invalid,
              "by_indicator": dict(per_indicator.most_common()),
              "llm_calls": provider.calls, "llm_failures": provider.failures}
    logger.info(f"Added {stats['edges_added']} llm alignsWithIndicator edge(s) "
                f"from {stats['adjudicated']} adjudication(s).")

    args.input.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {args.input} and {args.stats_out}. Next: step06 --clear, then step07.")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 5d — LLM claim/goal → indicator alignment for the ambiguous remainder.")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_RESOLVED)
    p.add_argument("--defs", type=Path, default=DEFAULT_DEFS)
    p.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--max-llm-pairs", type=int, default=200, help="Max LLM classifications this run.")
    p.add_argument("--openai-model", default="gpt-4o-mini")
    p.add_argument("--rate-limit", type=int, default=60)
    p.add_argument("--stats-out", type=Path, default=DEFAULT_STATS_OUT)
    p.add_argument("--dry-run", action="store_true", help="Count candidates; no LLM, no write.")
    run(p.parse_args())


if __name__ == "__main__":
    main()
