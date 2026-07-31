#!/usr/bin/env python3
"""
Behaviour tests for the new offline export stage `esg_kg.export.export_kgc`
(GRAPH_IMPROVEMENT_PLAN.md B4 — hub-cluster decomposition for an SSRL export view).

Offline: no LLM, no Neo4j, no network. Reuses the multi-issuer hub-cluster machinery
already built for A1 (`esg_kg.metric.hub`) instead of reimplementing hub detection, so
this stage's notion of "hub" always agrees with `report/quality.py`'s R5/Q7(d).

This stage NEVER writes to `graph_output/resolved/resolved_graph.json` — it reads it
read-only and produces a wholly separate derived artifact (`graph_output/export_kgc/`).
See docs/TEMPORAL_KG_DESIGN.md's P1/P2/P4/P6/P7 discussion referenced in
GRAPH_IMPROVEMENT_PLAN.md B4 for why that boundary matters.

Run from the repo root:

    python test/test_export_kgc.py
"""

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.export import export_kgc  # noqa: E402
from esg_kg.metric.hub import compute_hub_clusters, load_issuer_alias_index  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
RESOLVED_FILE = REPO / "graph_output" / "resolved" / "resolved_graph.json"
ISSUER_REGISTRY_FILE = REPO / "config" / "issuer_registry.json"

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


# --------------------------------------------------------------------------- #
# Synthetic 2-issuer fixture
# --------------------------------------------------------------------------- #

def build_fixture():
    """Two issuers: AAA (15 edges touching its hub node -> exceeds a threshold of
    10) and BBB (3 edges -> stays under threshold, must be left untouched).
    Mixes hub-as-subject and hub-as-object edges, across 3 distinct
    (year, predicate) groups for AAA, so bucketing has real structure to prove."""

    def org(name):
        return {"class": "Organization", "properties": {"name": name}, "temporal_versions": []}

    def leaf(name):
        return {"class": "SustainabilityClaim", "properties": {"name": name}, "temporal_versions": []}

    nodes = [org("Cong ty AAA"), org("Cong ty BBB")]
    nodes += [leaf(f"AAA leaf {i}") for i in range(15)]   # indices 2..16
    nodes += [leaf(f"BBB leaf {i}") for i in range(3)]    # indices 17..19

    def edge(s, p, o, valid_from):
        return {"subject": s, "predicate": p, "object": o,
                "temporal_metadata": {"valid_from": valid_from, "valid_to": None,
                                       "recorded_at": valid_from}}

    edges = []
    for i in range(2, 7):      # 2020 x claims -> hub 0 (leaf is subject): 5 edges
        edges.append(edge(i, "claims", 0, "2020-01-01"))
    for i in range(7, 11):     # 2021 x claims -> hub 0: 4 edges
        edges.append(edge(i, "claims", 0, "2021-03-01"))
    for i in range(11, 17):    # 2022 x reportsKPI, hub 0 is the SUBJECT: 6 edges
        edges.append(edge(0, "reportsKPI", i, "2022-05-01"))
    for i in range(17, 20):    # BBB: 3 edges, stays under threshold
        edges.append(edge(i, "claims", 1, "2023-01-01"))

    registry = {
        "AAA": {"ticker": "AAA", "canonical_name": "Cong ty AAA", "aliases": ["Cong ty AAA"],
                "exclusions": [], "needs_review": []},
        "BBB": {"ticker": "BBB", "canonical_name": "Cong ty BBB", "aliases": ["Cong ty BBB"],
                "exclusions": [], "needs_review": []},
    }
    return nodes, edges, registry


def clusters_for(nodes, edges, registry):
    degrees = export_kgc.compute_degrees(nodes, edges)
    alias_index = load_issuer_alias_index(registry)
    return compute_hub_clusters(nodes, degrees, alias_index, export_kgc.node_name)


def test_compute_degrees_matches_naive_count():
    nodes, edges, _ = build_fixture()
    degrees = export_kgc.compute_degrees(nodes, edges)
    assert degrees[0] == 15, degrees[0]   # hub AAA
    assert degrees[1] == 3, degrees[1]    # hub BBB


def test_over_threshold_cluster_is_bucketed_under_threshold_is_not():
    nodes, edges, registry = build_fixture()
    clusters = clusters_for(nodes, edges, registry)
    assert clusters["AAA"]["degree"] == 15
    assert clusters["BBB"]["degree"] == 3

    new_nodes, new_edges, stats = export_kgc.decompose_hub_clusters(
        nodes, edges, clusters, max_bucket_degree=10)

    bucket_nodes = [n for n in new_nodes if n["class"] == "HubBucket"]
    assert len(bucket_nodes) == 3, [n["properties"] for n in bucket_nodes]
    assert {n["properties"]["ticker"] for n in bucket_nodes} == {"AAA"}

    post_degrees = export_kgc.compute_degrees(new_nodes, new_edges)
    assert post_degrees[0] == 3, post_degrees[0]   # 1 bucketOf edge per bucket
    assert post_degrees[1] == 3, post_degrees[1]   # BBB untouched

    assert stats["per_cluster"]["AAA"]["original_degree"] == 15
    assert stats["per_cluster"]["AAA"]["bucket_count"] == 3
    assert "BBB" not in stats["per_cluster"]


def test_multi_company_independence_no_cross_ticker_buckets():
    """No bucket/edge minted for AAA is ever referenced by BBB's edges, and vice
    versa — the property that matters once a second real company is scaled in."""
    nodes, edges, registry = build_fixture()
    clusters = clusters_for(nodes, edges, registry)
    new_nodes, new_edges, _ = export_kgc.decompose_hub_clusters(
        nodes, edges, clusters, max_bucket_degree=10)

    aaa_bucket_indices = {i for i, n in enumerate(new_nodes)
                           if n["class"] == "HubBucket" and n["properties"]["ticker"] == "AAA"}
    bbb_node_indices = {1, 17, 18, 19}
    for e in new_edges:
        if e["subject"] in bbb_node_indices or e["object"] in bbb_node_indices:
            assert e["subject"] not in aaa_bucket_indices, e
            assert e["object"] not in aaa_bucket_indices, e


def test_input_is_never_mutated_and_output_is_deterministic():
    nodes, edges, registry = build_fixture()
    nodes_before = copy.deepcopy(nodes)
    edges_before = copy.deepcopy(edges)
    clusters = clusters_for(nodes, edges, registry)

    new_nodes_1, new_edges_1, stats_1 = export_kgc.decompose_hub_clusters(
        nodes, edges, clusters, max_bucket_degree=10)
    assert nodes == nodes_before, "input nodes list was mutated"
    assert edges == edges_before, "input edges list was mutated"

    new_nodes_2, new_edges_2, stats_2 = export_kgc.decompose_hub_clusters(
        nodes, edges, clusters, max_bucket_degree=10)
    assert json.dumps(new_nodes_1, sort_keys=True) == json.dumps(new_nodes_2, sort_keys=True)
    assert json.dumps(new_edges_1, sort_keys=True) == json.dumps(new_edges_2, sort_keys=True)
    assert stats_1 == stats_2


def test_synthetic_flags_present_on_new_nodes_and_edges_only():
    nodes, edges, registry = build_fixture()
    clusters = clusters_for(nodes, edges, registry)
    new_nodes, new_edges, _ = export_kgc.decompose_hub_clusters(
        nodes, edges, clusters, max_bucket_degree=10)

    for n in new_nodes:
        if n["class"] == "HubBucket":
            assert n["properties"]["is_synthetic"] is True
        else:
            assert "is_synthetic" not in n.get("properties", {})

    n_synthetic_edges = 0
    for e in new_edges:
        if e.get("predicate") == "bucketOf":
            assert e["is_synthetic"] is True
            n_synthetic_edges += 1
        elif e.get("is_synthetic"):
            n_synthetic_edges += 1
            assert "original_subject" in e or "original_object" in e

    # 15 rerouted AAA edges + 3 bucketOf summary edges = 18 synthetic edges total
    assert n_synthetic_edges == 18, n_synthetic_edges

    untouched = [e for e in new_edges if e["subject"] in (17, 18, 19)]
    assert len(untouched) == 3
    for e in untouched:
        assert "is_synthetic" not in e


def test_hubbucket_never_added_to_real_schema():
    """HubBucket is a dataset-construction artifact scoped to this one export
    view, not a T1/T2/T3 entity (docs/TEMPORAL_KG_DESIGN.md §2) — it must never
    leak into config/schema.json, the source of truth for the real graph."""
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    raw = json.dumps(schema)
    assert "HubBucket" not in raw


# --------------------------------------------------------------------------- #
# Real AAA corpus (skips gracefully if the HF snapshot isn't pulled locally)
# --------------------------------------------------------------------------- #

def test_real_corpus_reduces_max_degree_and_never_touches_the_input_file():
    if not RESOLVED_FILE.exists():
        _skip("test_real_corpus_reduces_max_degree_and_never_touches_the_input_file",
              "graph_output/resolved/resolved_graph.json not present locally (pull via datasync)")
        return

    before_bytes = RESOLVED_FILE.read_bytes()

    with tempfile.TemporaryDirectory() as tmp:
        args = argparse.Namespace(
            input=RESOLVED_FILE,
            issuer_registry=ISSUER_REGISTRY_FILE,
            max_bucket_degree=500,
            output=Path(tmp) / "export_graph.json",
            stats_out=Path(tmp) / "export_kgc_stats.json",
            dry_run=False,
        )
        report = export_kgc.run(args)

    after_bytes = RESOLVED_FILE.read_bytes()
    assert after_bytes == before_bytes, "stage must never write back to its input file"

    assert report["max_degree_before"] > 5000, report["max_degree_before"]
    assert report["max_degree_after"] < report["max_degree_before"] * 0.2, report
    print(f"     (real AAA corpus: max degree {report['max_degree_before']} -> "
          f"{report['max_degree_after']}, threshold_met={report['threshold_met']})")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
    if _skips:
        print(f"{len(_skips)} arm(s) skipped (missing local artifacts):")
        for s in _skips:
            print(f"  - {s}")
