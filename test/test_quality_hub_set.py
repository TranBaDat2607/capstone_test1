#!/usr/bin/env python3
"""
Coverage for `esg_kg.metric.hub` (GRAPH_IMPROVEMENT_PLAN.md A1) and its wiring into
`esg_kg.report.quality.q7_traversability`.

WHY THIS EXISTS
`report/quality.py` used to define "the hub" as the single globally-highest-degree
node, and Q7(d) (claim -> conduct structural reachability) excluded only that one
node from its hub-free search. That is only correct by accident with ONE issuer in
`config/issuer_registry.json`: once a second company's graph is merged in, each
issuer forms its own separate high-degree star, so a path routed through issuer B's
hub is wrongly counted "hub-free" (GRAPH_IMPROVEMENT_PLAN.md §1.3's worked example).
This file builds a synthetic 2-issuer graph that reproduces exactly that bug and
proves `esg_kg.metric.hub` + the updated `q7_traversability` fix it: excluding the
WHOLE registry-driven hub set, not just the single max-degree node.

See `test_reasoning_readiness_metrics.py` for the companion A2/A3 coverage
(R1/R1'/R7/R1_trainable), which is deliberately a separate file (its own
hand-computable fixture, unrelated to issuer clustering).

Offline: no LLM, no Neo4j, no network.

Run from the repo root:

    python test/test_quality_hub_set.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.metric import hub as mhub  # noqa: E402
from esg_kg.report import quality  # noqa: E402


def rep(**kw):
    return dict(source_type="report", **kw)


def news(**kw):
    return dict(source_type="news", **kw)


ISSUER_REGISTRY = {
    "AVI": {"ticker": "AVI", "canonical_name": "CTCP An Vui",
            "aliases": ["CTCP An Vui", "An Vui"], "exclusions": [], "needs_review": []},
    "BMC": {"ticker": "BMC", "canonical_name": "CTCP Binh Minh",
            "aliases": ["CTCP Binh Minh", "Binh Minh"], "exclusions": [], "needs_review": []},
}


def two_issuer_graph() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Two issuer "stars": AVI (node 0, degree 4 -> the single global max degree
    node) and BMC (node 1, degree 2 -> NOT the global max).

    - Claim 7 reaches conduct node 6 ONLY by routing through hubB (node 1). The
      OLD single-max-degree definition never bars node 1, so this path is wrongly
      counted as hub-free. The NEW registry-driven definition bars both node 0
      AND node 1, so this path must be excluded.
    - Claim 8 reaches conduct node 10 via a route that never touches either hub
      (through independent Facility 9), so it must stay reachable under BOTH the
      old and new definitions — this is the non-vacuity guard: if the fixture
      only had claim 7, "0% reachable" could also mean the code is broken, not
      that it correctly discriminates hub-touching from hub-free paths.
    """
    nodes = [
        {"class": "Organization", "properties": rep(name="CTCP An Vui", valid_from="2020")},        # 0 hubA
        {"class": "Organization", "properties": rep(name="CTCP Binh Minh", valid_from="2020")},      # 1 hubB
        {"class": "Facility", "properties": rep(name="Nha may A1", valid_from="2020")},               # 2
        {"class": "Facility", "properties": rep(name="Nha may A2", valid_from="2020")},               # 3
        {"class": "Facility", "properties": rep(name="Nha may A3", valid_from="2020")},               # 4
        {"class": "KPIObservation", "properties": rep(name="KPI A", valid_from="2023",
                                                      source_id="AVI_2023_labeled_1_1")},              # 5
        {"class": "KPIObservation", "properties": news(name="KPI B", source_id="news-b")},            # 6 conduct
        {"class": "SustainabilityClaim", "properties": rep(claim_id="AVI-C-HUBB", valid_from="2023")},  # 7
        {"class": "SustainabilityClaim", "properties": rep(claim_id="AVI-C-FREE", valid_from="2023")},  # 8
        {"class": "Facility", "properties": rep(name="Nha may doc lap", valid_from="2020")},          # 9
        {"class": "KPIObservation", "properties": news(name="KPI C", source_id="news-c")},            # 10 conduct
    ]

    def ed(s, o, p, vf="2020"):
        return {"subject": s, "object": o, "predicate": p,
                "temporal_metadata": {"valid_from": vf, "valid_to": None, "recorded_at": vf}}

    edges = [
        ed(0, 2, "ownsFacility"),
        ed(0, 3, "ownsFacility"),
        ed(0, 4, "ownsFacility"),
        ed(0, 5, "reportsKPI"),
        ed(7, 1, "partOf"),                 # claim 7 -> hubB (structural)
        ed(1, 6, "observedAtFacility"),     # hubB -> conduct (structural)
        ed(8, 9, "observedAtFacility"),     # claim 8 -> independent facility (structural)
        ed(9, 10, "observedAtFacility"),    # independent facility -> conduct (structural)
    ]
    return nodes, edges


def _degrees(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[int]:
    degrees = [0] * len(nodes)
    for e in edges:
        degrees[e["subject"]] += 1
        degrees[e["object"]] += 1
    return degrees


def test_load_issuer_alias_index_maps_every_alias_to_its_ticker():
    idx = mhub.load_issuer_alias_index(ISSUER_REGISTRY)
    assert idx[quality.normalize_name("CTCP An Vui")] == "AVI"
    assert idx[quality.normalize_name("An Vui")] == "AVI"
    assert idx[quality.normalize_name("CTCP Binh Minh")] == "BMC"
    assert idx[quality.normalize_name("Binh Minh")] == "BMC"


def test_load_issuer_alias_index_excludes_named_exclusions():
    registry = {
        "AVI": {"canonical_name": "CTCP An Vui", "aliases": ["CTCP An Vui", "An Vui Steel"],
                "exclusions": [{"name": "An Vui Steel", "reason": "unrelated company, name overlap"}]},
    }
    idx = mhub.load_issuer_alias_index(registry)
    assert quality.normalize_name("An Vui Steel") not in idx
    assert idx[quality.normalize_name("CTCP An Vui")] == "AVI"


def test_load_issuer_alias_index_on_empty_registry_is_empty():
    assert mhub.load_issuer_alias_index({}) == {}


def test_compute_hub_clusters_groups_by_ticker():
    nodes, edges = two_issuer_graph()
    degrees = _degrees(nodes, edges)
    assert degrees[0] > degrees[1], "fixture precondition: node 0 is the single global max"

    idx = mhub.load_issuer_alias_index(ISSUER_REGISTRY)
    clusters = mhub.compute_hub_clusters(nodes, degrees, idx, quality.node_name)
    assert set(clusters) == {"AVI", "BMC"}
    assert clusters["AVI"]["node_indices"] == [0]
    assert clusters["BMC"]["node_indices"] == [1]
    assert clusters["AVI"]["degree"] == degrees[0]
    assert clusters["BMC"]["degree"] == degrees[1]


def test_compute_hub_clusters_on_unmatched_registry_is_empty():
    nodes, edges = two_issuer_graph()
    degrees = _degrees(nodes, edges)
    assert mhub.compute_hub_clusters(nodes, degrees, {}, quality.node_name) == {}


def test_fallback_single_node_cluster_picks_the_global_max():
    nodes, edges = two_issuer_graph()
    degrees = _degrees(nodes, edges)
    clusters = mhub.fallback_single_node_cluster(nodes, degrees, list(range(len(nodes))), quality.node_name)
    assert set(clusters) == {mhub.UNREGISTERED_KEY}
    assert clusters[mhub.UNREGISTERED_KEY]["node_indices"] == [0]


def test_fallback_single_node_cluster_on_no_candidates_is_empty():
    nodes, edges = two_issuer_graph()
    degrees = _degrees(nodes, edges)
    assert mhub.fallback_single_node_cluster(nodes, degrees, [], quality.node_name) == {}


def test_hub_barred_indices_unions_every_cluster():
    nodes, edges = two_issuer_graph()
    degrees = _degrees(nodes, edges)
    idx = mhub.load_issuer_alias_index(ISSUER_REGISTRY)
    clusters = mhub.compute_hub_clusters(nodes, degrees, idx, quality.node_name)
    assert mhub.hub_barred_indices(clusters) == {0, 1}


def test_q7_traversability_bars_the_whole_registry_not_just_the_global_max():
    nodes, edges = two_issuer_graph()

    old_equivalent = quality.q7_traversability(nodes, edges, max_hops=4, skip_slow=False)
    assert old_equivalent["d_claims_structural_path_to_conduct_pct"] == 100.0, (
        "fixture precondition: with only node 0 barred, BOTH claims must look "
        "reachable -- this reproduces the bug GRAPH_IMPROVEMENT_PLAN.md section 1.3 describes")

    new_result = quality.q7_traversability(nodes, edges, max_hops=4, skip_slow=False,
                                           issuer_registry=ISSUER_REGISTRY)
    assert new_result["d_claims_structural_path_to_conduct_pct"] == 50.0, (
        "with the full issuer registry barred, only the hub-free claim (8) should "
        "still be reachable -- the hub-routed claim (7) must now be excluded")
    assert new_result["r1_prime_edges_total"] < old_equivalent["r1_prime_edges_total"], (
        "R1' must consider FEWER edges once the second issuer's hub is also barred "
        "(every edge touching node 1 is now dropped from the denominator too)")

    assert {h["ticker"] for h in old_equivalent["hubs"]} == {mhub.UNREGISTERED_KEY}
    assert {h["ticker"] for h in new_result["hubs"]} == {"AVI", "BMC"}
    assert new_result["r5_max_hub_degree"] == max(
        c["degree"] for c in mhub.compute_hub_clusters(
            nodes, _degrees(nodes, edges), mhub.load_issuer_alias_index(ISSUER_REGISTRY),
            quality.node_name).values())


def test_q7_traversability_hubs_list_is_sorted_by_degree_descending():
    nodes, edges = two_issuer_graph()
    result = quality.q7_traversability(nodes, edges, max_hops=4, skip_slow=False,
                                       issuer_registry=ISSUER_REGISTRY)
    degrees_in_order = [h["degree"] for h in result["hubs"]]
    assert degrees_in_order == sorted(degrees_in_order, reverse=True)
    assert result["hubs"][0]["ticker"] == "AVI"  # the higher-degree cluster


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}\n     {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} test group(s) passed.")
    raise SystemExit(1 if failed else 0)
