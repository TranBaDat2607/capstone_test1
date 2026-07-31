"""Hub-CLUSTER identification (GRAPH_IMPROVEMENT_PLAN.md A1).

A single-company graph's "hub" is not one node — it is every node belonging to
one issuer's identity, including stray alias-matching duplicates that survived
entity resolution as separate nodes (see Q3 surplus-duplicate counting in
`report/quality.py`). Treating hub-exclusion as "the single globally
highest-degree node" is only correct by accident when there is exactly one
issuer in `config/issuer_registry.json`. Once a second company's graph is
merged in, each issuer forms its own separate high-degree star and none of
them is the single global max, so a path routed through issuer B's hub would
wrongly be counted as hub-free by the old definition (GRAPH_IMPROVEMENT_PLAN.md
§1.3). This module makes hub exclusion follow the REGISTRY (every node
matching an issuer alias) instead of a single `argmax(degree)`.

Deliberately reimplemented here rather than imported from
`esg_kg.resolve.entities.load_issuer_index`: that function is stage-local to
step05, and `report/quality.py` depends on no other stage (see its module
docstring) — the same reason `q7_traversability` doesn't import step05
directly today. The alias/exclusion logic mirrored below is small and stable.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Set

from esg_kg.core.naming import normalize_name

UNREGISTERED_KEY = "_unregistered"


def load_issuer_alias_index(registry: Dict[str, Any]) -> Dict[str, str]:
    """normalized alias/canonical name -> ticker, from an
    `issuer_registry.json`-shaped dict. An `exclusions` entry never resolves
    to its ticker, even if it also happens to be listed as an alias."""
    index: Dict[str, str] = {}
    for ticker, info in registry.items():
        excl = {normalize_name(e["name"]) for e in info.get("exclusions", [])}
        names = set(info.get("aliases", [])) | {info.get("canonical_name", ticker)}
        for alias in names:
            na = normalize_name(alias)
            if na and na not in excl:
                index[na] = ticker
    return index


def compute_hub_clusters(nodes: List[Dict[str, Any]], degrees: List[int],
                         alias_index: Dict[str, str],
                         node_name_fn: Callable[[Dict[str, Any]], str]) -> Dict[str, Dict[str, Any]]:
    """ticker -> {"node_indices": [...], "degree": <summed>, "names": [...]},
    for every `Organization` node whose normalized name matches a registry
    alias. Empty if `alias_index` is empty or matches nothing in `nodes`."""
    clusters: Dict[str, Dict[str, Any]] = {}
    for i, nd in enumerate(nodes):
        if nd.get("class") != "Organization":
            continue
        nm = normalize_name(node_name_fn(nd))
        ticker = alias_index.get(nm)
        if ticker is None:
            continue
        c = clusters.setdefault(ticker, {"node_indices": [], "degree": 0, "names": []})
        c["node_indices"].append(i)
        c["degree"] += degrees[i]
        c["names"].append(node_name_fn(nd)[:60])
    return clusters


def fallback_single_node_cluster(nodes: List[Dict[str, Any]], degrees: List[int],
                                 candidates: List[int],
                                 node_name_fn: Callable[[Dict[str, Any]], str]) -> Dict[str, Dict[str, Any]]:
    """The OLD behaviour (single global-max-degree node among `candidates`),
    wrapped as one cluster keyed `_unregistered`. Used when the registry is
    empty or doesn't cover this graph, so hub-dependent metrics still get a
    sane (non-empty) exclusion set instead of silently barring nothing."""
    if not candidates:
        return {}
    max_idx = max(candidates, key=lambda i: degrees[i])
    return {UNREGISTERED_KEY: {
        "node_indices": [max_idx],
        "degree": degrees[max_idx],
        "names": [node_name_fn(nodes[max_idx])[:60]],
    }}


def hub_barred_indices(clusters: Dict[str, Dict[str, Any]]) -> Set[int]:
    barred: Set[int] = set()
    for c in clusters.values():
        barred.update(c["node_indices"])
    return barred
