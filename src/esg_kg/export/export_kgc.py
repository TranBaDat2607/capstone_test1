#!/usr/bin/env python3
"""
Step 11 (partial) — hub-cluster decomposition into an SSRL export view
(GRAPH_IMPROVEMENT_PLAN.md B4).

The issuer hub (AAA: degree 9,511, 66% of all edges) is why `R5` (max-degree gate,
<=500 in docs/TEMPORAL_KG_DESIGN.md) fails, and scaling to more companies does not fix
it (each company just adds its own star). This stage reduces max degree for an SSRL/RL
training VIEW by grouping a hub cluster's edges into synthetic `HubBucket` nodes keyed
by (year, predicate), WITHOUT ever touching `resolved_graph.json` or Neo4j:

    core/graph_patch.py's `assert_append_only` and step06's array-index keying both
    depend on resolved_graph.json's node order never being restructured in place —
    the same boundary docs/TEMPORAL_KG_DESIGN.md's P6 already established for
    inverse (`_inv`) edges: dataset-level transforms live in the export tier only.

Reuses the multi-issuer hub-cluster machinery A1 already built (`esg_kg.metric.hub`)
rather than reimplementing hub detection, so this stage's notion of "hub" always
agrees with `report/quality.py`'s R5/Q7(d). Only clusters whose *summed* degree
exceeds `--max-bucket-degree` get decomposed; smaller companies/clusters pass through
unchanged.

v1 buckets only by (year, predicate) — no third key. Some buckets can still exceed
the threshold (e.g. a single big year x relation combination); `--stats-out` reports
this honestly (`buckets_over_threshold`, `threshold_met`) instead of forcing a fit.

`HubBucket` is a dataset-construction artifact, not a T1/T2/T3 entity
(docs/TEMPORAL_KG_DESIGN.md §2) — it is deliberately never added to
`config/schema.json`, which stays the source of truth for the real graph only.

Run AFTER `build_resolved` (needs a resolved_graph.json to exist). Read-only against
its input; writes a wholly separate artifact:

    python src/run.py export_kgc --dry-run   # preview stats, write nothing
    python src/run.py export_kgc             # write graph_output/export_kgc/
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from esg_kg.core.paths import CONFIG_DIR, GRAPH_OUTPUT_DIR, RESOLVED_DIR
from esg_kg.metric.hub import (
    compute_hub_clusters,
    fallback_single_node_cluster,
    load_issuer_alias_index,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = RESOLVED_DIR / "resolved_graph.json"
DEFAULT_ISSUER_REGISTRY = CONFIG_DIR / "issuer_registry.json"
DEFAULT_MAX_BUCKET_DEGREE = 500  # matches the R5 gate in docs/TEMPORAL_KG_DESIGN.md
DEFAULT_OUTPUT_DIR = GRAPH_OUTPUT_DIR / "export_kgc"
DEFAULT_OUTPUT = DEFAULT_OUTPUT_DIR / "export_graph.json"
DEFAULT_STATS_OUT = DEFAULT_OUTPUT_DIR / "export_kgc_stats.json"


def node_name(node: Dict[str, Any]) -> str:
    """Local copy of report/quality.py's display-name fallback chain — duplicated
    rather than imported, same precedent as metric/hub.py (see its module docstring):
    this stage must not depend on another stage's internals."""
    p = node.get("properties", {})
    for k in ("name", "term", "title", "claim_id", "description"):
        if p.get(k):
            return str(p[k])
    return ""


def compute_degrees(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[int]:
    """Undirected degree per node index. No shared helper exists for this anywhere
    in core/ — every consumer (report/quality.py) recomputes it inline; this stage
    does the same rather than inventing a shared abstraction for a second caller."""
    degrees = [0] * len(nodes)
    for e in edges:
        degrees[e["subject"]] += 1
        degrees[e["object"]] += 1
    return degrees


def _year_of(edge: Dict[str, Any]) -> str:
    tm = edge.get("temporal_metadata") or {}
    for key in ("valid_from", "recorded_at"):
        v = tm.get(key)
        if v and len(str(v)) >= 4 and str(v)[:4].isdigit():
            return str(v)[:4]
    return "unknown"


def decompose_hub_clusters(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    clusters: Dict[str, Dict[str, Any]],
    max_bucket_degree: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Pure function, no file I/O. Only clusters whose summed degree exceeds
    `max_bucket_degree` are decomposed; everything else passes through by
    reference, unmodified (same node/edge dict objects, same array positions for
    every pre-existing node — new HubBucket nodes are only ever appended)."""
    to_bucket = {t: c for t, c in clusters.items() if c["degree"] > max_bucket_degree}
    hub_index_to_ticker: Dict[int, str] = {}
    for ticker, c in to_bucket.items():
        for idx in c["node_indices"]:
            hub_index_to_ticker[idx] = ticker

    new_nodes: List[Dict[str, Any]] = list(nodes)
    new_edges: List[Dict[str, Any]] = []
    bucket_index: Dict[Tuple[str, str, str], int] = {}
    hub_bucket_pairs: set = set()  # (hub_node_index, bucket_node_index)

    def get_or_create_bucket(ticker: str, year: str, predicate: str) -> int:
        key = (ticker, year, predicate)
        idx = bucket_index.get(key)
        if idx is None:
            idx = len(new_nodes)
            new_nodes.append({
                "class": "HubBucket",
                "properties": {
                    "ticker": ticker,
                    "year": year,
                    "predicate": predicate,
                    "member_count": 0,
                    "is_synthetic": True,
                    "source_type": "structural_bucket",
                },
                "temporal_versions": [],
            })
            bucket_index[key] = idx
        return idx

    if not to_bucket:
        new_edges = list(edges)
    else:
        for e in edges:
            s, p, o = e["subject"], e["predicate"], e["object"]
            s_ticker = hub_index_to_ticker.get(s)
            o_ticker = hub_index_to_ticker.get(o)
            if s_ticker is None and o_ticker is None:
                new_edges.append(e)
                continue

            new_e = dict(e)
            year = _year_of(e)
            if s_ticker is not None:
                b = get_or_create_bucket(s_ticker, year, p)
                new_e["subject"] = b
                new_e["original_subject"] = s
                new_nodes[b]["properties"]["member_count"] += 1
                hub_bucket_pairs.add((s, b))
            if o_ticker is not None:
                b = get_or_create_bucket(o_ticker, year, p)
                new_e["object"] = b
                new_e["original_object"] = o
                new_nodes[b]["properties"]["member_count"] += 1
                hub_bucket_pairs.add((o, b))
            new_e["is_synthetic"] = True
            new_edges.append(new_e)

        for hub_idx, bucket_idx in sorted(hub_bucket_pairs):
            year = new_nodes[bucket_idx]["properties"]["year"]
            new_edges.append({
                "subject": bucket_idx,
                "predicate": "bucketOf",
                "object": hub_idx,
                "is_synthetic": True,
                "temporal_metadata": {
                    "valid_from": year if year != "unknown" else None,
                    "valid_to": None,
                    "recorded_at": None,
                },
            })

    stats = _build_stats(nodes, edges, new_nodes, new_edges, clusters, to_bucket, max_bucket_degree)
    return new_nodes, new_edges, stats


def _build_stats(
    nodes, edges, new_nodes, new_edges, clusters, to_bucket, max_bucket_degree,
) -> Dict[str, Any]:
    old_degrees = compute_degrees(nodes, edges)
    new_degrees = compute_degrees(new_nodes, new_edges)

    per_cluster: Dict[str, Any] = {}
    for ticker, c in to_bucket.items():
        bucket_props = [n["properties"] for n in new_nodes
                         if n["class"] == "HubBucket" and n["properties"]["ticker"] == ticker]
        sizes = [p["member_count"] for p in bucket_props]
        per_cluster[ticker] = {
            "original_degree": c["degree"],
            "bucket_count": len(bucket_props),
            "max_bucket_size": max(sizes) if sizes else 0,
            "buckets_over_threshold": sum(1 for s in sizes if s > max_bucket_degree),
        }

    max_degree_before = max(old_degrees) if old_degrees else 0
    max_degree_after = max(new_degrees) if new_degrees else 0
    return {
        "clusters_considered": len(clusters),
        "clusters_bucketed": len(to_bucket),
        "per_cluster": per_cluster,
        "max_degree_before": max_degree_before,
        "max_degree_after": max_degree_after,
        "threshold": max_bucket_degree,
        "threshold_met": max_degree_after <= max_bucket_degree,
    }


def run(args: argparse.Namespace) -> Dict[str, Any]:
    if not args.input.exists():
        raise SystemExit(
            f"input not found: {args.input}\n"
            "Run `python src/run.py build_resolved` first."
        )
    graph = json.loads(args.input.read_text(encoding="utf-8"))
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])

    registry: Dict[str, Any] = {}
    if args.issuer_registry.exists():
        registry = json.loads(args.issuer_registry.read_text(encoding="utf-8"))

    degrees = compute_degrees(nodes, edges)
    alias_index = load_issuer_alias_index(registry)
    clusters = compute_hub_clusters(nodes, degrees, alias_index, node_name)
    if not clusters:
        candidates = list(range(len(nodes)))
        clusters = fallback_single_node_cluster(nodes, degrees, candidates, node_name)

    new_nodes, new_edges, stats = decompose_hub_clusters(nodes, edges, clusters, args.max_bucket_degree)

    logger.info("export_kgc stats:\n" + json.dumps(stats, indent=2, ensure_ascii=False))

    if args.dry_run:
        logger.info("Dry run — nothing written.")
        return stats

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"nodes": new_nodes, "edges": new_edges}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats


def main() -> None:
    p = argparse.ArgumentParser(
        description="B4: offline hub-cluster decomposition into an SSRL export view. "
                     "Read-only against resolved_graph.json — writes a wholly separate "
                     "artifact, never patches the canonical graph or Neo4j."
    )
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--issuer-registry", type=Path, default=DEFAULT_ISSUER_REGISTRY)
    p.add_argument("--max-bucket-degree", type=int, default=DEFAULT_MAX_BUCKET_DEGREE)
    p.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--stats-out", type=Path, default=DEFAULT_STATS_OUT)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
