#!/usr/bin/env python3
"""
Step 0 — graph quality report (docs/TEMPORAL_KG_DESIGN.md §4).

Measures the Q1–Q8 quality attributes of the resolved temporal knowledge graph
(`graph_output/resolved/resolved_graph.json`) fully offline (no LLM, no DB, no
writes outside --out-dir). Run it BEFORE and AFTER any schema/pipeline change so
every Phase-0 fix has a measured before/after snapshot:

    python src/step00_graph_quality_report.py --label baseline
    ... apply changes, rebuild graph ...
    python src/step00_graph_quality_report.py --label after-p1

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

# Later pipeline stages import shared helpers from earlier ones; step00 is a
# diagnostics tool over the whole pipeline, so it may reach forward too.
from step01_extract_kpi_from_jsonl import REPO_ROOT
from step03_fix_invalid_triplets import (
    ISO_DATE_RE,
    date_start_key,
    load_schema_sets,
    normalize_date_string,
)
from step04_build_issuer_registry import normalize_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_GRAPH = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "quality"
DEFAULT_MAX_HOPS = 4  # for Q7(d) claim→conduct search

# --------------------------------------------------------------------------- #
# The three node tiers (TEMPORAL_KG_DESIGN.md §2). T1 identity is timeless (P1);
# T2 events own their valid_from (P2); T3 assertions get one node per utterance.
# Certification sits between T1/T3 and is treated as T1 (type-of-certificate);
# the holding period lives on the holdsCertification edge.
# --------------------------------------------------------------------------- #
T1_CLASSES = {
    "Organization", "Person", "Facility", "Product", "Material", "Location",
    "Country", "Standard", "Regulation", "Authority", "Community",
    "ClaimKeyword", "Certification",
}
T2_CLASSES = {
    "KPIObservation", "Emission", "Waste", "Penalty", "Controversy",
    "MediaReport", "ThirdPartyVerification", "Investment", "Project",
    "Initiative", "CarbonOffsetProject",
}
T3_CLASSES = {"SustainabilityClaim", "Goal", "ScienceBasedTarget"}

# Fields that must never appear in a T1 class's identity_keys (P1: identity is
# timeless — new classes are linted against this, not just the four fixed ones).
TEMPORAL_IDENTITY_FIELDS = {
    "valid_from", "valid_to", "is_current", "recorded_at", "date", "year",
    "target_year", "baseline_year", "validity_period",
}

# Edge labels that carry structural (non-star, non-keyword) information — the
# walkable backbone of SSRL_REASONING_LAYER.md §2.2/§6.1. A claim→conduct path
# counts for Q7(d) only if it uses at least one of these.
STRUCTURAL_EDGES = {
    "observedAtFacility", "locatedIn", "ownsFacility", "isIn", "partnersWith",
    "producedBy", "holdsCertification", "worksAt", "partOf", "owns",
    "manufacturedAt", "suppliedBy", "enforcedBy", "sourcedFrom", "investsIn",
    "investedIn", "ownedBy", "involvedIn",
}

CONDUCT_CLASSES = {"Controversy", "Penalty", "MediaReport"}

# Broken-PDF-extraction indicators seen in real names ("MÔI TRƢỜNG": Ơ-horn
# came out as U+01A2/U+01A3; U+FFFD is the generic replacement char).
BROKEN_CHARS = {"Ƣ", "ƣ", "�"}


# --------------------------------------------------------------------------- #
# Small accessors.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Q1 — accuracy (machine-checkable slice).
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Q2 — consistency: schema-legal edges + P4 temporal invariants + P1 lint.
# --------------------------------------------------------------------------- #
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

    # P4 invariant scan
    bad_date_format = 0          # date present but not canonical ISO
    from_after_to = 0            # valid_from > valid_to (both parseable)
    multi_current_chains = 0     # temporal_versions with != exactly-one is_current
    format_split_versions = 0    # version pairs identical up to date spelling
    missing_date_uncertain = 0   # news T2 node without the required bool

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
            # P4: at most one current version; a chain with an open version must
            # have exactly one. An all-closed chain legitimately has none.
            if n_current > 1 or (n_current == 0 and n_open > 0):
                multi_current_chains += 1
            seen: Dict[Tuple, int] = {}
            for v in versions:
                vp = v.get("properties", {})
                key = (date_start_key(v.get("valid_from")), date_start_key(v.get("valid_to")),
                       str(vp.get("name", "")))
                seen[key] = seen.get(key, 0) + 1
            format_split_versions += sum(c - 1 for c in seen.values() if c > 1)
            for v in versions:
                bad_date_format += check_format(v.get("valid_from"), v.get("valid_to"))
                from_after_to += check_range(v.get("valid_from"), v.get("valid_to"))

    # P1 lint on the schema itself: T1 identity must be timeless.
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


# --------------------------------------------------------------------------- #
# Q3 — conciseness: one T1 entity = one node.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Q4 / Q8 — conduct-side completeness and independence.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Q5 / Q6 — timeliness and provenance.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Q7 — traversability (the reasoning-readiness attribute this thesis defines).
# --------------------------------------------------------------------------- #
def q7_traversability(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
                      max_hops: int, skip_slow: bool) -> Dict[str, Any]:
    n = len(nodes)
    adj: List[List[Tuple[int, str]]] = [[] for _ in range(n)]  # undirected, labeled
    pair_count: Counter = Counter()        # parallel edges per node pair (any label)
    pair_label_count: Counter = Counter()  # parallel edges per (pair, label)
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

    max_deg_idx = max(range(n), key=lambda i: degrees[i]) if n else 0
    hub = {"class": nodes[max_deg_idx].get("class"), "name": node_name(nodes[max_deg_idx])[:60],
           "degree": degrees[max_deg_idx]} if n else {}

    # (e) % T2 nodes with degree >= 2, per class
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
        "largest_hub": hub,
        "e_t2_nodes_degree_ge_2_pct": t2_ge2_pct,
        "e_t2_anchoring_per_class": t2_anchoring,
        "gate": "Q7(e) >= 30% after P3 prompt fix; Q7(d) must rise clearly at 1->3 companies",
    }
    if skip_slow:
        result["c_masked_queries_answerable_pct"] = None
        result["d_claims_structural_path_to_conduct_pct"] = None
        result["note"] = "(c)/(d) skipped via --skip-slow"
        return result

    # (c) % edges still answerable <= 3 hops after masking that FACT — masking
    # (s, r, o) also masks its parallel same-relation duplicates (multi-year
    # edges), so an alternate route must use a different relation or a longer path.
    answerable = 0
    per_rel_total: Counter = Counter()
    per_rel_ok: Counter = Counter()
    for e in edges:
        s, o, lbl = e["subject"], e["object"], e["predicate"]
        per_rel_total[lbl] += 1
        pair = (min(s, o), max(s, o))
        masked_here = pair_label_count[(pair[0], pair[1], lbl)]
        if degrees[s] <= masked_here or degrees[o] <= masked_here:
            continue  # masking the fact orphans an endpoint -> unanswerable
        if pair_count[pair] > masked_here:
            answerable += 1  # direct edge of a DIFFERENT relation survives (1-hop path)
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

    # (d) % claims that reach a conduct node via a path with >= 1 structural edge,
    # EXCLUDING the issuer hub node. Rationale (SSRL doc §2.1, proposal P5): every
    # node is 2 hops from every other node through the ~9.5k-degree issuer, so
    # through-hub reachability is saturated and carries zero discriminating
    # information — the walker can even bounce claim→hub→Facility→hub→conduct and
    # launder a "structural" flag. Only hub-free structural paths measure real
    # alternate routes; pure-keyword paths never count (hasKeyword is not structural).
    claim_idx = [i for i, nd in enumerate(nodes) if nd.get("class") == "SustainabilityClaim"]
    conduct_idx = {i for i, nd in enumerate(nodes) if is_conduct(nd)}
    reached = 0
    for c in claim_idx:
        # state = (node, has_structural_edge_so_far)
        start = (c, False)
        seen = {start}
        frontier = [start]
        ok = False
        for _ in range(max_hops):
            nxt_states: List[Tuple[int, bool]] = []
            for u, flag in frontier:
                for v, lbl in adj[u]:
                    if v == max_deg_idx:
                        continue  # issuer hub excluded from (d) paths
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
                              f"excluded hub = node {max_deg_idx} ({hub.get('name', '')!r})")
    return result


# --------------------------------------------------------------------------- #
# Report rendering.
# --------------------------------------------------------------------------- #
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
    if q["q2_consistency"]["t1_identity_keys_with_time_fields"]:
        lines += ["", "## P1 violations (time fields in T1 identity_keys)", ""]
        for v in q["q2_consistency"]["t1_identity_keys_with_time_fields"]:
            lines.append(f"- `{v['class']}`: {v['temporal_identity_keys']}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
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
    report["q7_traversability"] = q7_traversability(nodes, edges, args.max_hops, args.skip_slow)
    report["q8_independence"] = q8_independence(nodes)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / f"quality_report_{args.label}.json"
    md_path = args.out_dir / f"quality_report_{args.label}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    logger.info(f"Wrote {json_path} and {md_path}")
    print(render_markdown(report))


if __name__ == "__main__":
    main()
