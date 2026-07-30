#!/usr/bin/env python3
"""
Coverage for `esg_kg.metric.reasoning_readiness` (GRAPH_IMPROVEMENT_PLAN.md A2/A3):
R1 (masked-edge re-derivability within 3 undirected hops), R1' (R1 with hub nodes
barred), R7 (hub-free length-3 metapaths, support >= 50), R1_trainable (R1 minus
degenerate relations), and the `degenerate_relations.json` loader.

WHY A SEPARATE FILE, NOT test_esg_kg_equivalence.py
`esg_kg.metric` is new code (no `src/` original to compare against — there is no
equivalence arm to run), and the plan (GRAPH_IMPROVEMENT_PLAN.md A2) explicitly asks
for a small synthetic graph with HAND-COMPUTED answers rather than a golden-dict
capture, so a reader can verify every number in this file by counting hops on paper.
See `test_quality_hub_set.py` for the companion A1 (hub-cluster) coverage and for the
integration arm that drives these functions through `report/quality.py` on a synthetic
multi-issuer graph.

Offline: no LLM, no Neo4j, no network.

Run from the repo root:

    python test/test_reasoning_readiness_metrics.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.metric import reasoning_readiness as rr  # noqa: E402

DEGENERATE_RELATIONS_FILE = REPO / "config" / "degenerate_relations.json"


def _build_adj(n_nodes: int, edges: List[Tuple[int, int, str]]) -> List[List[Tuple[int, str]]]:
    """Undirected labeled adjacency list, same construction `q7_traversability`
    uses in `report/quality.py` (each edge appended to both endpoints)."""
    adj: List[List[Tuple[int, str]]] = [[] for _ in range(n_nodes)]
    for s, o, lbl in edges:
        adj[s].append((o, lbl))
        adj[o].append((s, lbl))
    return adj


def _edge_dicts(edges: List[Tuple[int, int, str]]) -> List[Dict[str, Any]]:
    return [{"subject": s, "object": o, "predicate": lbl} for s, o, lbl in edges]


# --------------------------------------------------------------------------- #
# A hand-computable graph (6 nodes, 7 edges) exercising every branch:
#
#   0 --ownsFacility--- 1 --locatedIn--- 2 --ownsFacility--- 3   (3 is a leaf/pocket)
#   |                                    |
#   +-------partnersWith-----------------+
#   0 --ownsFacility--- 4 --observedAtFacility--- 2
#   0 --reportsKPI----- 5                                        (5 is a leaf)
#
# Degrees: 0:4  1:2  2:4  3:1  4:2  5:1
#
# e1=(0,1,ownsFacility)        e2=(1,2,locatedIn)    e3=(0,2,partnersWith)
# e4=(2,3,ownsFacility)        e5=(4,2,observedAtFacility)
# e6=(4,0,ownsFacility)        e7=(0,5,reportsKPI)
#
# Hand-derivation (masked-BFS, hops=3, barred=set()):
#   e1(0,1): mask(0,1) -> 0 -[partnersWith]-> 2 -[locatedIn]-> 1   FOUND (2 hops)
#   e2(1,2): mask(1,2) -> 1 -[ownsFacility]-> 0 -[partnersWith]-> 2 FOUND (2 hops)
#   e3(0,2): mask(0,2) -> 0 -[ownsFacility]-> 1 -[locatedIn]-> 2   FOUND (2 hops)
#   e4(2,3): mask(2,3) -> node 3 has NO other edge                NOT FOUND (isolated pocket)
#   e5(4,2): mask(4,2) -> 4 -[ownsFacility]-> 0 -[partnersWith]-> 2 FOUND (2 hops, via hub 0)
#   e6(4,0): mask(4,0) -> 4 -[observedAtFacility]-> 2 -[partnersWith]-> 0 FOUND (2 hops)
#   e7(0,5): mask(0,5) -> node 5 has NO other edge                NOT FOUND (isolated pocket)
#
#   R1 (barred=set())          : ok=5 (e1,e2,e3,e5,e6), total=7 -> 71.4%
#   R1' (barred={0})           : edges touching node 0 (e1,e3,e6,e7) dropped from the
#                                 denominator entirely (an endpoint is barred) -> only
#                                 e2, e4, e5 remain as candidates (total=3). Re-run masked-BFS
#                                 with node 0 unwalkable:
#                                   e2(1,2): mask(1,2), barred={0} -> 1's only other edge
#                                     goes to 0, which is barred -> NOT FOUND
#                                   e4(2,3): unchanged, still NOT FOUND
#                                   e5(4,2): mask(4,2), barred={0} -> 4's only other edge
#                                     goes to 0, which is barred -> NOT FOUND
#                                 ok=0, total=3 -> 0.0%. This is the hub-routing case the
#                                 plan calls out: e5 is reachable via R1 (through hub 0) but
#                                 NOT via R1' (hub barred) — same bug §1.3 describes for Q7(d).
#   R1_trainable (excluded={"reportsKPI"}) : e7 dropped from the denominator (not because
#                                 of reachability, but because the relation itself is
#                                 excluded) -> total=6, ok=5 (same 5 as plain R1) -> 83.3%
# --------------------------------------------------------------------------- #
def hand_graph() -> Tuple[List[Tuple[int, int, str]], List[List[Tuple[int, str]]]]:
    raw_edges = [
        (0, 1, "ownsFacility"),   # e1
        (1, 2, "locatedIn"),      # e2
        (0, 2, "partnersWith"),   # e3
        (2, 3, "ownsFacility"),   # e4
        (4, 2, "observedAtFacility"),  # e5
        (4, 0, "ownsFacility"),   # e6
        (0, 5, "reportsKPI"),     # e7
    ]
    adj = _build_adj(6, raw_edges)
    return raw_edges, adj


def test_r1_reachability_matches_hand_derivation():
    raw_edges, adj = hand_graph()
    edges = _edge_dicts(raw_edges)

    pct, ok, total = rr.r1_reachability(edges, adj)
    assert (pct, ok, total) == (71.4, 5, 7), f"R1 = {(pct, ok, total)}, expected (71.4, 5, 7)"

    pct_prime, ok_prime, total_prime = rr.r1_reachability(edges, adj, barred=frozenset({0}))
    assert (pct_prime, ok_prime, total_prime) == (0.0, 0, 3), (
        f"R1' = {(pct_prime, ok_prime, total_prime)}, expected (0.0, 0, 3)")

    pct_train, ok_train, total_train = rr.r1_reachability(
        edges, adj, excluded_relations=frozenset({"reportsKPI"}))
    assert (pct_train, ok_train, total_train) == (83.3, 5, 6), (
        f"R1_trainable = {(pct_train, ok_train, total_train)}, expected (83.3, 5, 6)")


def test_r1_isolated_pocket_edge_is_not_reachable():
    """Directly isolates the e4 (2,3) case: masking the only edge that touches
    a leaf must NOT be re-derivable — this is what distinguishes R1 from a
    vacuous "the edge itself always proves reachability" metric."""
    raw_edges, adj = hand_graph()
    found = rr._masked_bfs_reachable(adj, start=2, target=3, hops=rr.R1_HOPS,
                                     barred=frozenset(), mask_pair=(2, 3))
    assert found is False


def test_r1_hub_routed_edge_differs_between_r1_and_r1_prime():
    """e5 (4,2) is reachable only by routing through node 0 — the case the plan
    (§1.3) says a single-max-degree hub definition gets wrong for Q7(d); this
    proves the same distinction holds for R1/R1' at the metric level."""
    raw_edges, adj = hand_graph()
    via_hub = rr._masked_bfs_reachable(adj, start=4, target=2, hops=rr.R1_HOPS,
                                       barred=frozenset(), mask_pair=(4, 2))
    hub_free = rr._masked_bfs_reachable(adj, start=4, target=2, hops=rr.R1_HOPS,
                                        barred=frozenset({0}), mask_pair=(4, 2))
    assert via_hub is True
    assert hub_free is False


def test_r1_reachability_on_empty_edges_is_zero_not_a_crash():
    pct, ok, total = rr.r1_reachability([], [[]])
    assert (pct, ok, total) == (0.0, 0, 0)


# --------------------------------------------------------------------------- #
# R7: two disjoint families of independent length-3 chains
#   main:  60 copies of  A --relA--> B --relB--> C --relC--> D   (fresh nodes each copy)
#   minor: 10 copies of  A --relX--> B --relY--> C --relZ--> D   (fresh nodes each copy)
#
# Each chain contributes exactly one occurrence of (relA,relB,relC) [walked from
# its A end] and one of (relC,relB,relA) [walked from its D end] — verified by
# hand for a single chain in the module docstring's r7_metapaths note. So:
#   support(relA,relB,relC) == support(relC,relB,relA) == 60   (>= min_support=50 -> kept)
#   support(relX,relY,relZ) == support(relZ,relY,relX) == 10   (<  min_support=50 -> dropped)
# --------------------------------------------------------------------------- #
def chain_family_graph(n_main: int, n_minor: int) -> List[List[Tuple[int, str]]]:
    edges: List[Tuple[int, int, str]] = []
    next_node = 0

    def add_chain(labels: Tuple[str, str, str]) -> None:
        nonlocal next_node
        a, b, c, d = next_node, next_node + 1, next_node + 2, next_node + 3
        next_node += 4
        edges.append((a, b, labels[0]))
        edges.append((b, c, labels[1]))
        edges.append((c, d, labels[2]))

    for _ in range(n_main):
        add_chain(("relA", "relB", "relC"))
    for _ in range(n_minor):
        add_chain(("relX", "relY", "relZ"))

    return _build_adj(next_node, edges)


def test_r7_metapaths_applies_the_support_threshold():
    adj = chain_family_graph(n_main=60, n_minor=10)
    result = rr.r7_metapaths(adj, min_support=rr.R7_MIN_SUPPORT)
    by_key = {tuple(m["metapath"]): m["support"] for m in result}

    assert by_key.get(("relA", "relB", "relC")) == 60
    assert by_key.get(("relC", "relB", "relA")) == 60
    assert ("relX", "relY", "relZ") not in by_key, "10 < min_support=50 must be dropped"
    assert ("relZ", "relY", "relX") not in by_key


def test_r7_metapaths_hub_free_excludes_barred_start_and_intermediate_nodes():
    """Barring node 0 of a single chain (its 'hub') must remove the metapath
    that starts there or passes through it, without erroring on other chains."""
    adj = chain_family_graph(n_main=60, n_minor=0)
    barred_result = rr.r7_metapaths(adj, barred=frozenset({0}), min_support=1)
    unbarred_result = rr.r7_metapaths(adj, barred=frozenset(), min_support=1)
    by_key_barred = {tuple(m["metapath"]): m["support"] for m in barred_result}
    by_key_unbarred = {tuple(m["metapath"]): m["support"] for m in unbarred_result}
    # node 0 only ever appears as the START of one chain's (relA,relB,relC) walk,
    # so barring it must drop exactly one occurrence from that metapath's support.
    assert by_key_barred[("relA", "relB", "relC")] == by_key_unbarred[("relA", "relB", "relC")] - 1


def test_r7_metapaths_on_empty_adj_is_empty_not_a_crash():
    assert rr.r7_metapaths([]) == []


# --------------------------------------------------------------------------- #
# A3: config/degenerate_relations.json loader
# --------------------------------------------------------------------------- #
def test_load_degenerate_relations_missing_file_returns_empty_set():
    missing = REPO / "config" / "does_not_exist_degenerate_relations.json"
    assert not missing.exists()
    assert rr.load_degenerate_relations(missing) == set()


def test_load_degenerate_relations_reads_the_real_config_file():
    assert DEGENERATE_RELATIONS_FILE.exists(), (
        "config/degenerate_relations.json must exist and be tracked in git "
        "(GRAPH_IMPROVEMENT_PLAN.md A3)")
    got = rr.load_degenerate_relations(DEGENERATE_RELATIONS_FILE)
    assert "reportsKPI" in got
    assert isinstance(got, set)


def test_default_degenerate_relations_path_is_repo_relative():
    assert rr.DEFAULT_DEGENERATE_RELATIONS == REPO / "config" / "degenerate_relations.json"


def test_constants_match_the_plan_document():
    assert rr.R1_HOPS == 3
    assert rr.R7_MIN_SUPPORT == 50


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
