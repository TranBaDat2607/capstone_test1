#!/usr/bin/env python3
"""
Step 0 — graph quality report (docs/TEMPORAL_KG_DESIGN.md §4).

Measures the Q1–Q8 quality attributes of the resolved temporal knowledge graph
(`graph_output/resolved/resolved_graph.json`) fully offline (no LLM, no DB, no
writes outside --out-dir). Run it BEFORE and AFTER any schema/pipeline change so
every Phase-0 fix has a measured before/after snapshot:

    python src/run.py quality --label baseline
    ... apply changes, rebuild graph ...
    python src/run.py quality --label after-p1

(`python -m esg_kg.report.quality --label baseline`, run from `src/`, is
the same thing without the dispatcher. Output paths are anchored on the marker-
based REPO_ROOT, so neither form depends on the working directory.)

Attributes (see the design doc for definitions and thresholds):
  Q1 accuracy        — machine-checkable slice: Unicode NFC / broken-OCR names
  Q2 consistency     — schema-legal edges + P4 temporal invariants
                       + P1 lint (no time fields in T1 identity_keys)
  Q3 conciseness     — duplicate T1 entities per normalized name
  Q4 completeness    — conduct-side node counts (Controversy/Penalty/MediaReport)
  Q5 timeliness      — % edges with valid_from; date_uncertain coverage on news T2
  Q6 provenance      — source_type / source_id coverage
  Q7 traversability  — (a) median degree, (b) % leaves, (c) % edge-masked queries
                       answerable ≤3 hops, (d) % claims reaching conduct via a path
                       with ≥1 structural edge, (e) % T2 nodes with degree ≥ 2
  Q8 independence    — conduct evidence by channel/publisher

Outputs graph_output/quality/quality_report_<label>.{json,md}.

Moved verbatim from ``src/step00_graph_quality_report.py`` — the first whole
STAGE of the refactor (DESIGN.md §4 step 3), not just a helper. Only the import
block changed: the four symbols it used to borrow from sibling step files now
come from ``esg_kg.core``. Behaviour is asserted identical to the src/ original
in ``test/test_esg_kg_equivalence.py`` (constants, every Q1-Q8 metric, and the
rendered Markdown).

The tier map below (T1/T2/T3) is a CONTRACT, not a local detail:
``test/test_schema_contract.py`` imports it instead of re-declaring it, so
schema.json is always linted against exactly one definition of the tiers.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import unicodedata
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from esg_kg.core.console import ensure_utf8_stdout
from esg_kg.core.dates import ISO_DATE_RE, date_start_key, normalize_date_string
from esg_kg.core.naming import normalize_name
from esg_kg.core.paths import QUALITY_DIR, REPO_ROOT, RESOLVED_DIR, SCHEMA_PATH
from esg_kg.core.schema import load_schema_sets

from esg_kg.metric.hub import (
    compute_hub_clusters,
    fallback_single_node_cluster,
    hub_barred_indices,
    load_issuer_alias_index,
)
from esg_kg.metric.reasoning_readiness import (
    DEFAULT_DEGENERATE_RELATIONS,
    R1_HOPS,
    R7_MIN_SUPPORT,
    load_degenerate_relations,
    r1_reachability,
    r7_metapaths,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_GRAPH = RESOLVED_DIR / "resolved_graph.json"
DEFAULT_SCHEMA = SCHEMA_PATH
DEFAULT_OUT_DIR = QUALITY_DIR
DEFAULT_MAX_HOPS = 4
DEFAULT_STANDARDS_REGISTRY = REPO_ROOT / "config" / "standards_registry.json"
DEFAULT_ISSUER_REGISTRY = REPO_ROOT / "config" / "issuer_registry.json"

T1_CLASSES = {
    "Organization", "Person", "Facility", "Product", "Material", "Location",
    "Country", "Standard", "Regulation", "Authority", "Community",
    "ClaimKeyword", "Certification", "StandardIndicator",
}

REFERENCE_CLASSES = {"StandardIndicator"}
T2_CLASSES = {
    "KPIObservation", "Emission", "Waste", "Penalty", "Controversy",
    "MediaReport", "ThirdPartyVerification", "Investment", "Project",
    "Initiative", "CarbonOffsetProject",
}
T3_CLASSES = {"SustainabilityClaim", "Goal", "ScienceBasedTarget"}

TEMPORAL_IDENTITY_FIELDS = {
    "valid_from", "valid_to", "is_current", "recorded_at", "date", "year",
    "target_year", "baseline_year", "validity_period",
}

STRUCTURAL_EDGES = {
    "observedAtFacility", "locatedIn", "ownsFacility", "isIn", "partnersWith",
    "producedBy", "holdsCertification", "worksAt", "partOf", "owns",
    "manufacturedAt", "suppliedBy", "enforcedBy", "sourcedFrom", "investsIn",
    "investedIn", "ownedBy", "involvedIn",
}

CONDUCT_CLASSES = {"Controversy", "Penalty", "MediaReport"}

BROKEN_CHARS = {"Ƣ", "ƣ", "�"}


def node_name(node: Dict[str, Any]) -> str:
    p = node.get("properties", {})
    for k in ("name", "term", "title", "claim_id", "description"):
        if p.get(k):
            return str(p[k])
    return ""


def is_conduct(node: Dict[str, Any]) -> bool:
    cls = node.get("class")
    if cls in CONDUCT_CLASSES:
        return True
    return cls == "KPIObservation" and node.get("properties", {}).get("source_type") == "news"


def is_news_t2(node: Dict[str, Any]) -> bool:
    return (node.get("class") in {"KPIObservation", "Controversy", "Penalty", "MediaReport"}
            and node.get("properties", {}).get("source_type") == "news")


def pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def q1_accuracy(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    non_nfc = broken = 0
    examples: List[str] = []
    for nd in nodes:
        nm = node_name(nd)
        if not nm:
            continue
        bad = False
        if unicodedata.normalize("NFC", nm) != nm:
            non_nfc += 1
            bad = True
        if any(c in nm for c in BROKEN_CHARS):
            broken += 1
            bad = True
        if bad and len(examples) < 5:
            examples.append(nm[:80])
    return {
        "nodes_with_non_nfc_name": non_nfc,
        "nodes_with_broken_ocr_chars": broken,
        "examples": examples,
        "note": "manual 30–50 node sample audit is out of scope for this script",
    }


def q2_consistency(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
                   schema: Dict[str, Any]) -> Dict[str, Any]:
    _, _, edge_directions = load_schema_sets(schema)

    illegal_edges = 0
    for e in edges:
        s_cls = nodes[e["subject"]].get("class")
        o_cls = nodes[e["object"]].get("class")
        pairs = edge_directions.get(e["predicate"], [])
        if not pairs or not any(s == s_cls and t == o_cls for s, t in pairs):
            illegal_edges += 1

    bad_date_format = 0
    from_after_to = 0
    multi_current_chains = 0
    format_split_versions = 0
    missing_date_uncertain = 0

    def check_range(vf: Any, vt: Any) -> int:
        kf, kt = date_start_key(vf), date_start_key(vt)
        return 1 if kf and kt and kf > kt else 0

    def check_format(*values: Any) -> int:
        n = 0
        for v in values:
            if v in (None, ""):
                continue
            norm, ok = normalize_date_string(v)
            if not ok or (norm is not None and not ISO_DATE_RE.match(norm)) or str(v) != (norm or ""):
                n += 1
        return n

    for e in edges:
        tm = e.get("temporal_metadata") or {}
        bad_date_format += check_format(tm.get("valid_from"), tm.get("valid_to"), tm.get("recorded_at"))
        from_after_to += check_range(tm.get("valid_from"), tm.get("valid_to"))

    for nd in nodes:
        p = nd.get("properties", {})
        bad_date_format += check_format(p.get("valid_from"), p.get("valid_to"))
        from_after_to += check_range(p.get("valid_from"), p.get("valid_to"))
        if is_news_t2(nd) and not isinstance(p.get("date_uncertain"), bool):
            missing_date_uncertain += 1

        versions = nd.get("temporal_versions")
        if versions:
            n_current = sum(1 for v in versions if v.get("is_current") is True)
            n_open = sum(1 for v in versions if v.get("valid_to") in (None, ""))
            if n_current > 1 or (n_current == 0 and n_open > 0):
                multi_current_chains += 1
            seen: Dict[Tuple, int] = {}
            for v in versions:
                vp = v.get("properties", {})
                label = str(vp.get("name") or node_name({"properties": vp}))
                key = (date_start_key(v.get("valid_from")), date_start_key(v.get("valid_to")), label)
                seen[key] = seen.get(key, 0) + 1
            format_split_versions += sum(c - 1 for c in seen.values() if c > 1)
            for v in versions:
                bad_date_format += check_format(v.get("valid_from"), v.get("valid_to"))
                from_after_to += check_range(v.get("valid_from"), v.get("valid_to"))

    t1_identity_violations = []
    for n in schema.get("nodes", []):
        if n["class"] in T1_CLASSES:
            bad = sorted(set(n.get("identity_keys", [])) & TEMPORAL_IDENTITY_FIELDS)
            if bad:
                t1_identity_violations.append({"class": n["class"], "temporal_identity_keys": bad})

    violations = (illegal_edges + bad_date_format + from_after_to + multi_current_chains
                  + format_split_versions + missing_date_uncertain + len(t1_identity_violations))
    return {
        "schema_illegal_edges": illegal_edges,
        "non_canonical_date_values": bad_date_format,
        "valid_from_after_valid_to": from_after_to,
        "version_chains_not_exactly_one_is_current": multi_current_chains,
        "versions_split_only_by_date_format": format_split_versions,
        "news_t2_missing_date_uncertain": missing_date_uncertain,
        "t1_identity_keys_with_time_fields": t1_identity_violations,
        "total_violations": violations,
        "gate": "0 violations (proposal P4/Q2)",
    }


DEFAULT_MIN_DEGREE = 2


def standards_registry_audit(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
                             registry: Dict[str, Any],
                             min_degree: int = DEFAULT_MIN_DEGREE) -> Dict[str, Any]:
    """Names that look like one of the five reference documents but are not curated yet.

    Deduplicated by normalized name (degrees summed), because one spelling is one
    curation decision no matter how many nodes carry it. A mention is claimed by at
    most one document, so the same name never shows up under two keys.

    A registry entry's `canonical_name` counts as covered by definition — step04b used
    to flag its own canonical name as an unknown mention, because it writes that name,
    step05 stamps it onto the merged node, and the next scan reads it back as a stranger.
    """
    degree: Counter = Counter()
    for e in edges:
        degree[e["subject"]] += 1
        degree[e["object"]] += 1

    mentions: Dict[str, Dict[str, Any]] = {}
    for i, n in enumerate(nodes):
        if n.get("class") not in ("Standard", "Regulation"):
            continue
        name = str((n.get("properties") or {}).get("name") or "").strip()
        if not name:
            continue
        norm = normalize_name(name)
        if not norm:
            continue
        seen = mentions.setdefault(norm, {"name": name, "class": n["class"], "degree": 0})
        seen["degree"] += degree[i]

    covered = 0
    uncovered: List[Dict[str, Any]] = []
    claimed: Set[str] = set()

    for key, info in registry.items():
        known = {normalize_name(a) for a in info.get("aliases", [])}
        known.add(normalize_name(info.get("canonical_name", key)))
        known.discard("")
        excluded = {normalize_name(x["name"]) for x in info.get("exclusions", [])}
        hints = info.get("exclude_hints") or []
        patterns = [re.compile(p, re.IGNORECASE) for p in (info.get("match_patterns") or [])]

        for norm, m in mentions.items():
            if norm in claimed:
                continue
            if norm in known:
                covered += 1
                claimed.add(norm)
                continue
            if norm in excluded or any(h in norm for h in hints):
                claimed.add(norm)
                continue
            if not any(p.search(m["name"]) or p.search(norm) for p in patterns):
                continue
            claimed.add(norm)
            uncovered.append({
                "name": m["name"], "normalized": norm, "class": m["class"],
                "degree": m["degree"], "doc_key": key,
                "suggest": "include" if m["degree"] >= min_degree else "exclude",
            })

    uncovered.sort(key=lambda u: (-u["degree"], u["name"]))
    return {
        "documents": len(registry),
        "distinct_mentions": len(mentions),
        "covered_mentions": covered,
        "uncovered": uncovered,
        "note": ("uncovered = looks like one of the five reference documents but is neither "
                 "an alias nor a curated exclusion; edit config/standards_registry.json by "
                 "hand, then re-run step05 so the frozen anchor picks it up"),
    }


def q3_conciseness(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    per_class: Dict[str, Counter] = defaultdict(Counter)
    for nd in nodes:
        cls = nd.get("class")
        if cls in T1_CLASSES:
            key = normalize_name(node_name(nd))
            if key:
                per_class[cls][key] += 1
    dup_summary = {}
    total_surplus = 0
    for cls, counts in sorted(per_class.items()):
        surplus = sum(c - 1 for c in counts.values() if c > 1)
        total_surplus += surplus
        dup_summary[cls] = {
            "nodes": sum(counts.values()),
            "distinct_normalized_names": len(counts),
            "surplus_duplicate_nodes": surplus,
        }
    return {"per_class": dup_summary, "total_surplus_duplicate_t1_nodes": total_surplus}


def q4_completeness(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = Counter(nd["class"] for nd in nodes if nd.get("class") in CONDUCT_CLASSES)
    news_kpis = sum(1 for nd in nodes
                    if nd.get("class") == "KPIObservation"
                    and nd.get("properties", {}).get("source_type") == "news")
    return {
        "controversy": counts.get("Controversy", 0),
        "penalty": counts.get("Penalty", 0),
        "media_report": counts.get("MediaReport", 0),
        "news_kpi_observations": news_kpis,
        "gate": ">= 10 independent conduct nodes per pilot company",
    }


def q8_independence(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    publishers = Counter()
    by_channel = Counter()
    for nd in nodes:
        if is_conduct(nd):
            by_channel[nd.get("properties", {}).get("source_type", "unknown")] += 1
            if nd.get("class") == "MediaReport":
                publishers[str(nd.get("properties", {}).get("publisher", "") or "unknown")] += 1
    return {
        "conduct_nodes_by_source_type": dict(by_channel),
        "media_report_publishers": dict(publishers.most_common(15)),
        "note": "per-dossier PR/independent ratio is computed by step07's self-verification guard",
    }


def q5_timeliness(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    edges_with_from = sum(1 for e in edges if (e.get("temporal_metadata") or {}).get("valid_from"))
    t2_nodes = [nd for nd in nodes if nd.get("class") in T2_CLASSES]
    t2_with_from = sum(1 for nd in t2_nodes if nd.get("properties", {}).get("valid_from"))
    news_t2 = [nd for nd in nodes if is_news_t2(nd)]
    with_du = sum(1 for nd in news_t2 if isinstance(nd.get("properties", {}).get("date_uncertain"), bool))
    du_true = sum(1 for nd in news_t2 if nd.get("properties", {}).get("date_uncertain") is True)
    return {
        "edges_with_valid_from_pct": pct(edges_with_from, len(edges)),
        "t2_nodes_with_valid_from_pct": pct(t2_with_from, len(t2_nodes)),
        "news_t2_nodes": len(news_t2),
        "news_t2_with_date_uncertain_pct": pct(with_du, len(news_t2)),
        "news_t2_date_uncertain_true": du_true,
        "gate": "edges with valid_from >= 99%",
    }


def q6_provenance(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    with_source_type = sum(1 for nd in nodes if nd.get("properties", {}).get("source_type"))
    kpis = [nd for nd in nodes if nd.get("class") == "KPIObservation"]
    sid_re = re.compile(r".+_\d+_\d+$")
    kpi_with_sid = sum(1 for nd in kpis
                       if sid_re.match(str(nd.get("properties", {}).get("source_id", ""))))
    return {
        "nodes_with_source_type_pct": pct(with_source_type, len(nodes)),
        "kpi_nodes_with_parseable_source_id_pct": pct(kpi_with_sid, len(kpis)),
        "gate": "keep 100%; extend to reasoning_path per-edge provenance (P7)",
    }


def q7_traversability(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
                      max_hops: int, skip_slow: bool,
                      issuer_registry: Optional[Dict[str, Any]] = None,
                      degenerate_relations: Optional[Set[str]] = None) -> Dict[str, Any]:
    issuer_registry = issuer_registry or {}
    degenerate_relations = degenerate_relations or set()

    n = len(nodes)
    adj: List[List[Tuple[int, str]]] = [[] for _ in range(n)]
    pair_count: Counter = Counter()
    pair_label_count: Counter = Counter()
    for e in edges:
        s, o, lbl = e["subject"], e["object"], e["predicate"]
        adj[s].append((o, lbl))
        adj[o].append((s, lbl))
        pair_count[(min(s, o), max(s, o))] += 1
        pair_label_count[(min(s, o), max(s, o), lbl)] += 1

    degrees = [len(a) for a in adj]
    median_degree = statistics.median(degrees) if degrees else 0
    leaves = sum(1 for d in degrees if d == 1)
    isolated = sum(1 for d in degrees if d == 0)

    hub_candidates = [i for i in range(n) if nodes[i].get("class") not in REFERENCE_CLASSES]
    alias_index = load_issuer_alias_index(issuer_registry)
    hub_clusters = compute_hub_clusters(nodes, degrees, alias_index, node_name)
    if not hub_clusters:
        hub_clusters = fallback_single_node_cluster(nodes, degrees, hub_candidates, node_name)
    hubs = [
        {"ticker": ticker, "degree": c["degree"], "node_count": len(c["node_indices"]),
         "names": c["names"]}
        for ticker, c in sorted(hub_clusters.items(), key=lambda kv: -kv[1]["degree"])
    ]
    barred_hub = hub_barred_indices(hub_clusters)
    r5_max_hub_degree = max((c["degree"] for c in hub_clusters.values()), default=0)
    reference_idx = {i for i, nd in enumerate(nodes) if nd.get("class") in REFERENCE_CLASSES}

    t2_anchoring: Dict[str, Any] = {}
    t2_total = t2_anchored = 0
    per_cls: Dict[str, List[int]] = defaultdict(list)
    for i, nd in enumerate(nodes):
        if nd.get("class") in T2_CLASSES:
            per_cls[nd["class"]].append(i)
    for cls, idxs in sorted(per_cls.items()):
        anchored = sum(1 for i in idxs if degrees[i] >= 2)
        t2_total += len(idxs)
        t2_anchored += anchored
        t2_anchoring[cls] = {"nodes": len(idxs), "degree_ge_2_pct": pct(anchored, len(idxs))}
    t2_ge2_pct = pct(t2_anchored, t2_total)

    result: Dict[str, Any] = {
        "a_median_degree": median_degree,
        "b_leaf_nodes_pct": pct(leaves, n),
        "isolated_nodes": isolated,
        "hubs": hubs,
        "r5_max_hub_degree": r5_max_hub_degree,
        "e_t2_nodes_degree_ge_2_pct": t2_ge2_pct,
        "e_t2_anchoring_per_class": t2_anchoring,
        "gate": "Q7(e) >= 30% after P3 prompt fix; Q7(d) must rise clearly at 1->3 companies",
    }
    if skip_slow:
        result["c_masked_queries_answerable_pct"] = None
        result["d_claims_structural_path_to_conduct_pct"] = None
        result["r1_reachability_pct"] = None
        result["r1_edges_total"] = None
        result["r1_prime_hub_free_pct"] = None
        result["r1_prime_edges_total"] = None
        result["r1_trainable_pct"] = None
        result["r1_trainable_edges_total"] = None
        result["r1_trainable_excluded_relations"] = sorted(degenerate_relations)
        result["r7_metapaths_hub_free"] = None
        result["r7_min_support"] = R7_MIN_SUPPORT
        result["note"] = "(c)/(d)/R1/R1'/R7 skipped via --skip-slow"
        return result

    answerable = 0
    per_rel_total: Counter = Counter()
    per_rel_ok: Counter = Counter()
    for e in edges:
        s, o, lbl = e["subject"], e["object"], e["predicate"]
        per_rel_total[lbl] += 1
        pair = (min(s, o), max(s, o))
        masked_here = pair_label_count[(pair[0], pair[1], lbl)]
        if degrees[s] <= masked_here or degrees[o] <= masked_here:
            continue
        if pair_count[pair] > masked_here:
            answerable += 1
            per_rel_ok[lbl] += 1
            continue
        banned = (s, o)
        found = False
        frontier = {s}
        visited = {s}
        for _ in range(3):
            nxt: Set[int] = set()
            for u in frontier:
                for v, _lbl in adj[u]:
                    if (u, v) == banned or (v, u) == banned:
                        continue
                    if v == o:
                        found = True
                        break
                    if v not in visited:
                        visited.add(v)
                        nxt.add(v)
                if found:
                    break
            if found or not nxt:
                break
            frontier = nxt
        if found:
            answerable += 1
            per_rel_ok[lbl] += 1
    result["c_masked_queries_answerable_pct"] = pct(answerable, len(edges))
    result["c_per_relation_pct"] = {
        rel: pct(per_rel_ok[rel], tot)
        for rel, tot in sorted(per_rel_total.items(), key=lambda kv: -kv[1])
    }

    barred = barred_hub | reference_idx
    claim_idx = [i for i, nd in enumerate(nodes) if nd.get("class") == "SustainabilityClaim"]
    conduct_idx = {i for i, nd in enumerate(nodes) if is_conduct(nd)}
    reached = 0
    for c in claim_idx:
        start = (c, False)
        seen = {start}
        frontier = [start]
        ok = False
        for _ in range(max_hops):
            nxt_states: List[Tuple[int, bool]] = []
            for u, flag in frontier:
                for v, lbl in adj[u]:
                    if v in barred:
                        continue
                    nf = flag or (lbl in STRUCTURAL_EDGES)
                    if v in conduct_idx and nf:
                        ok = True
                        break
                    st = (v, nf)
                    if st not in seen:
                        seen.add(st)
                        nxt_states.append(st)
                if ok:
                    break
            if ok or not nxt_states:
                break
            frontier = nxt_states
        if ok:
            reached += 1
    result["d_claims_structural_path_to_conduct_pct"] = pct(reached, len(claim_idx))
    result["d_claims_total"] = len(claim_idx)
    result["d_max_hops"] = max_hops
    result["d_definition"] = ("hub-free path <= max_hops with >=1 structural edge; "
                              f"excluded hub clusters = {sorted(hub_clusters)}")

    r1_pct, _r1_ok, r1_total = r1_reachability(edges, adj, hops=R1_HOPS)
    r1p_pct, _r1p_ok, r1p_total = r1_reachability(edges, adj, hops=R1_HOPS, barred=barred)
    r1t_pct, _r1t_ok, r1t_total = r1_reachability(
        edges, adj, hops=R1_HOPS, excluded_relations=degenerate_relations)
    result["r1_reachability_pct"] = r1_pct
    result["r1_edges_total"] = r1_total
    result["r1_prime_hub_free_pct"] = r1p_pct
    result["r1_prime_edges_total"] = r1p_total
    result["r1_trainable_pct"] = r1t_pct
    result["r1_trainable_edges_total"] = r1t_total
    result["r1_trainable_excluded_relations"] = sorted(degenerate_relations)
    result["r7_metapaths_hub_free"] = r7_metapaths(adj, barred=barred, min_support=R7_MIN_SUPPORT)
    result["r7_min_support"] = R7_MIN_SUPPORT
    return result


def render_markdown(report: Dict[str, Any]) -> str:
    q = report
    lines = [
        f"# Graph quality report — {q['label']}",
        "",
        f"- generated: {q['generated_at']}",
        f"- graph: `{q['graph_file']}` (modified {q['graph_mtime']})",
        f"- size: {q['nodes']} nodes / {q['edges']} edges",
        "",
        "| # | Attribute | Key figures |",
        "|---|---|---|",
        (f"| Q1 | Accuracy | non-NFC names: {q['q1_accuracy']['nodes_with_non_nfc_name']}; "
         f"broken-OCR names: {q['q1_accuracy']['nodes_with_broken_ocr_chars']} |"),
        (f"| Q2 | Consistency | total violations: **{q['q2_consistency']['total_violations']}** "
         f"(illegal edges {q['q2_consistency']['schema_illegal_edges']}, "
         f"non-ISO dates {q['q2_consistency']['non_canonical_date_values']}, "
         f"from>to {q['q2_consistency']['valid_from_after_valid_to']}, "
         f"bad is_current chains {q['q2_consistency']['version_chains_not_exactly_one_is_current']}, "
         f"format-split versions {q['q2_consistency']['versions_split_only_by_date_format']}, "
         f"missing date_uncertain {q['q2_consistency']['news_t2_missing_date_uncertain']}, "
         f"T1 time-identity classes {len(q['q2_consistency']['t1_identity_keys_with_time_fields'])}) |"),
        (f"| Q3 | Conciseness | surplus duplicate T1 nodes: "
         f"{q['q3_conciseness']['total_surplus_duplicate_t1_nodes']}; Standard nodes: "
         f"{q['q3_conciseness']['per_class'].get('Standard', {}).get('nodes', 0)} |"),
        (f"| Q4 | Completeness | Controversy {q['q4_completeness']['controversy']} / "
         f"Penalty {q['q4_completeness']['penalty']} / "
         f"MediaReport {q['q4_completeness']['media_report']} / "
         f"news KPI {q['q4_completeness']['news_kpi_observations']} |"),
        (f"| Q5 | Timeliness | edges with valid_from: {q['q5_timeliness']['edges_with_valid_from_pct']}%; "
         f"T2 nodes with valid_from: {q['q5_timeliness']['t2_nodes_with_valid_from_pct']}%; "
         f"news T2 with date_uncertain: {q['q5_timeliness']['news_t2_with_date_uncertain_pct']}% |"),
        (f"| Q6 | Provenance | nodes with source_type: {q['q6_provenance']['nodes_with_source_type_pct']}%; "
         f"KPI with parseable source_id: {q['q6_provenance']['kpi_nodes_with_parseable_source_id_pct']}% |"),
        (f"| Q7 | Traversability | median degree {q['q7_traversability']['a_median_degree']}; "
         f"leaves {q['q7_traversability']['b_leaf_nodes_pct']}%; "
         f"masked-answerable {q['q7_traversability'].get('c_masked_queries_answerable_pct')}%; "
         f"claim→conduct structural {q['q7_traversability'].get('d_claims_structural_path_to_conduct_pct')}%; "
         f"T2 deg≥2 {q['q7_traversability']['e_t2_nodes_degree_ge_2_pct']}% |"),
        (f"| Q8 | Independence | conduct by channel: "
         f"{q['q8_independence']['conduct_nodes_by_source_type']} |"),
        "",
        "## Q7(e) anchoring per T2 class",
        "",
        "| class | nodes | degree ≥ 2 |",
        "|---|---|---|",
    ]
    for cls, row in q["q7_traversability"]["e_t2_anchoring_per_class"].items():
        lines.append(f"| {cls} | {row['nodes']} | {row['degree_ge_2_pct']}% |")

    q7 = q["q7_traversability"]
    lines += ["", "## Hub clusters (A1)", "",
              "| ticker | nodes | degree |", "|---|---|---|"]
    for h in q7["hubs"]:
        lines.append(f"| {h['ticker']} | {h['node_count']} | {h['degree']} |")
    lines += ["", f"R5 (max hub-cluster degree): {q7['r5_max_hub_degree']}"]

    lines += ["", "## Reasoning readiness (R1 / R1' / R7)", "",
              (f"- R1 (masked-edge re-derivable ≤ {R1_HOPS} hops): "
               f"{q7.get('r1_reachability_pct')}% ({q7.get('r1_edges_total')} edges)"),
              (f"- R1' (R1, hub-free): {q7.get('r1_prime_hub_free_pct')}% "
               f"({q7.get('r1_prime_edges_total')} edges)"),
              (f"- R1_trainable (R1, degenerate relations excluded): "
               f"{q7.get('r1_trainable_pct')}% ({q7.get('r1_trainable_edges_total')} edges; "
               f"excluded: {q7.get('r1_trainable_excluded_relations')})"),
              (f"- R7 (hub-free length-3 metapaths, support ≥ {q7.get('r7_min_support')}): "
               f"{len(q7['r7_metapaths_hub_free']) if q7.get('r7_metapaths_hub_free') else 0} metapath(s)")]

    if q["q2_consistency"]["t1_identity_keys_with_time_fields"]:
        lines += ["", "## P1 violations (time fields in T1 identity_keys)", ""]
        for v in q["q2_consistency"]["t1_identity_keys_with_time_fields"]:
            lines.append(f"- `{v['class']}`: {v['temporal_identity_keys']}")

    audit = q.get("standards_registry_audit")
    if audit:
        lines += ["", "## Standards registry coverage", "",
                  (f"{audit['covered_mentions']} of {audit['distinct_mentions']} distinct "
                   f"Standard/Regulation spellings are curated across "
                   f"{audit['documents']} reference documents.")]
        if audit["uncovered"]:
            lines += ["", "Looks like a reference document but is not curated yet "
                          "(edit `config/standards_registry.json`, then re-run step05):", "",
                      "| name | doc | class | degree | suggest |", "|---|---|---|---|---|"]
            for u in audit["uncovered"]:
                lines.append(f"| {u['name']} | {u['doc_key']} | {u['class']} | "
                             f"{u['degree']} | {u['suggest']} |")
        else:
            lines += ["", "No uncovered mentions."]
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ensure_utf8_stdout()
    p = argparse.ArgumentParser(description="Step 0 — offline Q1–Q8 quality report for the resolved graph.")
    p.add_argument("-g", "--graph", type=Path, default=DEFAULT_GRAPH)
    p.add_argument("-s", "--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("-o", "--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--label", type=str, default=datetime.now().strftime("%Y%m%d"),
                   help="Snapshot label used in output filenames (e.g. baseline, after-p1)")
    p.add_argument("--max-hops", type=int, default=DEFAULT_MAX_HOPS,
                   help="Path length budget for Q7(d) claim→conduct search")
    p.add_argument("--skip-slow", action="store_true",
                   help="Skip the BFS-heavy Q7(c)/(d) metrics")
    p.add_argument("--standards-registry", type=Path, default=DEFAULT_STANDARDS_REGISTRY,
                   help="Static registry of the five reference documents; audited, never written")
    p.add_argument("--issuer-registry", type=Path, default=DEFAULT_ISSUER_REGISTRY,
                   help="Issuer alias registry driving hub-cluster exclusion (A1)")
    p.add_argument("--degenerate-relations", type=Path, default=DEFAULT_DEGENERATE_RELATIONS,
                   help="Relations excluded from R1_trainable (A3)")
    args = p.parse_args()

    if not args.graph.exists():
        logger.error(f"Graph not found: {args.graph} (run step05_resolve_entities.py first)")
        return
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    logger.info(f"Loaded {len(nodes)} nodes / {len(edges)} edges from {args.graph}")

    mtime = datetime.fromtimestamp(args.graph.stat().st_mtime, tz=timezone.utc)
    report: Dict[str, Any] = {
        "label": args.label,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "graph_file": str(args.graph.relative_to(REPO_ROOT)) if args.graph.is_relative_to(REPO_ROOT) else str(args.graph),
        "graph_mtime": mtime.isoformat(timespec="seconds"),
        "nodes": len(nodes),
        "edges": len(edges),
    }
    report["q1_accuracy"] = q1_accuracy(nodes)
    report["q2_consistency"] = q2_consistency(nodes, edges, schema)
    report["q3_conciseness"] = q3_conciseness(nodes)
    report["q4_completeness"] = q4_completeness(nodes)
    report["q5_timeliness"] = q5_timeliness(nodes, edges)
    report["q6_provenance"] = q6_provenance(nodes)
    logger.info("Computing Q7 traversability (BFS metrics)...")
    issuer_registry: Dict[str, Any] = {}
    if args.issuer_registry.exists():
        issuer_registry = json.loads(args.issuer_registry.read_text(encoding="utf-8"))
    else:
        logger.warning(f"No issuer registry at {args.issuer_registry}; hub falls back to "
                       "the single highest-degree node.")
    degenerate_relations = load_degenerate_relations(args.degenerate_relations)
    report["q7_traversability"] = q7_traversability(
        nodes, edges, args.max_hops, args.skip_slow,
        issuer_registry=issuer_registry, degenerate_relations=degenerate_relations)
    report["q8_independence"] = q8_independence(nodes)
    if args.standards_registry.exists():
        registry = json.loads(args.standards_registry.read_text(encoding="utf-8"))
        report["standards_registry_audit"] = standards_registry_audit(nodes, edges, registry)
    else:
        logger.warning(f"No standards registry at {args.standards_registry}; skipping its audit.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / f"quality_report_{args.label}.json"
    md_path = args.out_dir / f"quality_report_{args.label}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    logger.info(f"Wrote {json_path} and {md_path}")
    print(render_markdown(report))


if __name__ == "__main__":
    main()
