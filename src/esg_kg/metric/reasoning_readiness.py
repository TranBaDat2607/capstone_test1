"""Reasoning-readiness metrics R1 / R1' / R7 / R1_trainable
(GRAPH_IMPROVEMENT_PLAN.md A2/A3).

These measure what the plan calls "agent readiness": can a `(subject,
relation, ?)` query be answered by a bounded-hop walk, with and without
routing through the issuer hub? Like Q7(c) in `report/quality.py`, each real
edge `(s, r, o)` is MASKED (that specific edge instance is hidden from the
walk) and `o` must be re-derived from `s` via an ALTERNATE route within
`R1_HOPS` undirected hops — without masking, the direct edge itself would
always trivially "reach" its own endpoint, making the metric vacuous.

  R1            = r1_reachability(edges, adj)
  R1' (hub-free) = r1_reachability(edges, adj, barred=hub_barred_indices(...))
  R1_trainable  = r1_reachability(edges, adj, excluded_relations=degenerate_relations)

R7 counts hub-free length-3 metapaths with support >= R7_MIN_SUPPORT — the
walkable, non-degenerate backbone a future path-reasoning layer would train on
(docs/SSRL_REASONING_LAYER.md, referenced but not present in this repo).

Both R1 and R7 are the same asymptotic cost class as Q7(c)/(d) in
`report/quality.py` (bounded-depth traversal over every node/edge), so callers
must gate them behind `--skip-slow` the same way.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Set, Tuple

from esg_kg.core.paths import REPO_ROOT

R1_HOPS = 3
R7_MIN_SUPPORT = 50

DEFAULT_DEGENERATE_RELATIONS = REPO_ROOT / "config" / "degenerate_relations.json"


def load_degenerate_relations(path: Path) -> Set[str]:
    """Relations to exclude from R1_trainable (A3). Empty set if the file
    doesn't exist — same graceful-degradation shape as
    `standards_registry_audit`'s `--standards-registry` guard."""
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("degenerate_relations", []))


def _masked_bfs_reachable(adj: List[List[Tuple[int, str]]], start: int, target: int,
                          hops: int, barred: FrozenSet[int], mask_pair: Tuple[int, int]) -> bool:
    """Is `target` reachable from `start` within `hops` undirected steps,
    skipping barred nodes and the specific `(mask_pair)` edge instance
    (either direction)? Same walk shape as `q7_traversability`'s Q7(c) block
    in `report/quality.py`, generalized with a `barred`-node skip for R1'."""
    frontier: Set[int] = {start}
    visited: Set[int] = {start}
    for _ in range(hops):
        nxt: Set[int] = set()
        found = False
        for u in frontier:
            for v, _lbl in adj[u]:
                if v in barred:
                    continue
                if (u, v) == mask_pair or (v, u) == mask_pair:
                    continue
                if v == target:
                    found = True
                    break
                if v not in visited:
                    visited.add(v)
                    nxt.add(v)
            if found:
                break
        if found:
            return True
        if not nxt:
            break
        frontier = nxt
    return False


def r1_reachability(edges: List[Dict[str, Any]], adj: List[List[Tuple[int, str]]],
                    hops: int = R1_HOPS, barred: FrozenSet[int] = frozenset(),
                    excluded_relations: FrozenSet[str] = frozenset()) -> Tuple[float, int, int]:
    """% of real edges `(s, r, o)` — excluding `excluded_relations` and any
    edge with a barred endpoint — that are still re-derivable: with THIS edge
    instance masked, is `o` reachable from `s` via an alternate route within
    `hops` undirected hops? Returns `(pct, ok, total)`.
    """
    total = ok = 0
    for e in edges:
        lbl = e["predicate"]
        if lbl in excluded_relations:
            continue
        s, o = e["subject"], e["object"]
        if s in barred or o in barred:
            continue
        total += 1
        if _masked_bfs_reachable(adj, s, o, hops, barred, (s, o)):
            ok += 1
    pct = round(ok / total * 100, 1) if total else 0.0
    return pct, ok, total


def r7_metapaths(adj: List[List[Tuple[int, str]]], barred: FrozenSet[int] = frozenset(),
                 min_support: int = R7_MIN_SUPPORT) -> List[Dict[str, Any]]:
    """Hub-free, no-immediate-backtrack length-3 undirected label sequences
    `(l1, l2, l3)`, counted by walk, kept when `support >= min_support`.

    Each undirected path is counted once per direction it's walked from (once
    from each end), so `support` is consistently ~2x the path count — fine
    for a relative threshold, not meant as an exact path census.
    """
    counts: Counter = Counter()
    n = len(adj)
    for s in range(n):
        if s in barred:
            continue
        for v1, l1 in adj[s]:
            if v1 in barred:
                continue
            for v2, l2 in adj[v1]:
                if v2 in barred or v2 == s:
                    continue
                for v3, l3 in adj[v2]:
                    if v3 in barred or v3 == v1:
                        continue
                    counts[(l1, l2, l3)] += 1
    return [{"metapath": list(k), "support": c}
            for k, c in sorted(counts.items(), key=lambda kv: -kv[1])
            if c >= min_support]
