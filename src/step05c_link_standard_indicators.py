"""Step 5c — materialize the TT96/GRI indicator axis (offline, NO LLM).

Design: docs/STANDARD_INDICATOR_AXIS.md §3, §5.3. Runs AFTER step05b, BEFORE step06.

WHAT IT DOES
Turns the 35-indicator vocabulary (a string property on KPIObservation, untraversable in Neo4j)
into first-class graph structure:

    (Regulation TT96) <--partOf-- (StandardIndicator TT96-6.1.1) <--measuredUnder-- (KPIObservation)
                                        |  --alignsWithIndicator--  (SustainabilityClaim / Goal / Initiative)
                                        |  --equivalentTo-->        (StandardIndicator GRI 305-1)

The StandardIndicator node is the JOIN POINT: a company's *claim* about an indicator and the
*conduct* KPIs measured under it hang off one node, so step07 can compare the two sides by walking
two hops instead of guessing from token overlap (docs/STANDARD_INDICATOR_AXIS.md §6).

HARD INVARIANT — APPEND ONLY
step06 keys Neo4j on array index (_node_key = "n{i}") and step07 dossiers reference nodes by
position, so this stage only APPENDS to nodes[]/edges[] and never reorders or replaces an
existing item — it may mutate an existing node's `properties` in place (e.g. stamping
self_reported_zero on a Penalty), but the objects at positions 0..n0 stay the same objects in
the same order. GraphPatch.assert_append_only() verifies this (by object id()) before writing.

WHAT IT WILL NOT DO
  * It does not guess a KPI's indicator — it reads the `kpi_id` step03c already assigned. Keeping
    that boundary means a wrong mapping is always traceable to step03c or the alias file.
  * Penalty nodes with amount==0 are self-reported "fined 0 times" compliance claims, NOT conduct
    evidence; wiring them under TT96-6.5.x would count a boast as a violation. They are flagged
    `self_reported_zero` and get NO measuredUnder edge (docs/STANDARD_INDICATOR_AXIS.md §5.3).
  * GRI equivalentTo edges are emitted only for crosswalk rows a human marked status=confirmed
    (the drafted rows sit in needs_review until reviewed); --trust-draft-crosswalk overrides for
    a demo.

  python src/step05c_link_standard_indicators.py --dry-run
  python src/step05c_link_standard_indicators.py
"""

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from step01_extract_kpi_from_jsonl import REPO_ROOT
from step03_fix_invalid_triplets import load_schema_sets
from step04_build_issuer_registry import normalize_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_RESOLVED = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_DEFS = REPO_ROOT / "kpi_definitions_construction.json"
DEFAULT_CROSSWALK = REPO_ROOT / "config" / "standard_crosswalk.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_STATS_OUT = REPO_ROOT / "graph_output" / "resolved" / "indicator_axis_stats.json"

TODAY = date.today().isoformat()

# indicator id prefix → (registry doc key, class it should be `partOf`)
DOC_OF_PREFIX = [
    ("TT96-", ("TT96", "Regulation")),
    ("QD2171", ("QD2171", "Regulation")),
    ("QCVN09", ("QCVN09", "Standard")),
    ("SSCIFC-", ("SSCIFC", "Standard")),
]
# fallback document names when the registry has not been built / a doc has no mention yet
DOC_CANONICAL = {
    "TT96": "Thông tư 96/2020/TT-BTC",
    "QD2171": "Quyết định 2171/QĐ-BXD",
    "QCVN09": "QCVN 09:2017/BXD",
    "SSCIFC": "Sổ tay hướng dẫn công bố thông tin ESG (SSC-IFC)",
    "GRI": "GRI Standards",
}


def doc_key_for(indicator_id: str) -> Optional[Tuple[str, str]]:
    for prefix, dockey in DOC_OF_PREFIX:
        if indicator_id.startswith(prefix):
            return dockey
    return None


def temporal_md(props: Dict[str, Any]) -> Dict[str, Any]:
    """Edge temporal_metadata: valid_from inherited from the observation, recorded_at = run day."""
    return {"valid_from": props.get("valid_from"),
            "valid_to": props.get("valid_to"),
            "recorded_at": TODAY}


def norm(s: Any) -> str:
    return normalize_name(s)


# --------------------------------------------------------------------------- #
class GraphPatch:
    """Append-only view over the resolved graph. Tracks how many nodes/edges existed before so
    the invariant can be asserted, and dedups appended nodes by identity so re-running is a no-op."""

    def __init__(self, graph: Dict[str, Any], entity_classes, edge_labels, edge_dirs):
        self.graph = graph
        self.nodes: List[Dict[str, Any]] = graph["nodes"]
        self.edges: List[Dict[str, Any]] = graph["edges"]
        self.n_nodes0 = len(self.nodes)
        self.n_edges0 = len(self.edges)
        # Identity snapshot of the existing prefix: the object id() of each node/edge dict at
        # positions 0..n0. We only ever .append() new items and mutate existing `properties` in
        # place, so these objects must stay the SAME objects in the SAME order — that is the
        # invariant step06 (_node_key = "n{i}") and the step07 dossiers depend on. Snapshotting
        # id() lets assert_append_only() catch any accidental reorder/replace while still allowing
        # a property mutation (e.g. stamping self_reported_zero on a Penalty).
        self._prefix_node_ids = [id(n) for n in self.nodes]
        self._prefix_edge_ids = [id(e) for e in self.edges]
        self.entity_classes = entity_classes
        self.edge_labels = edge_labels
        self.edge_dirs = edge_dirs

        # index existing nodes by (class, identity-name) so we neither duplicate an indicator
        # nor a document node across runs
        self._by_id: Dict[Tuple[str, str], int] = {}
        for i, n in enumerate(self.nodes):
            self._register(i)

        # existing edges as a set of (subject, predicate, object) so we don't re-add
        self._edgeset = {(e.get("subject"), e.get("predicate"), e.get("object"))
                         for e in self.edges}
        self.dropped_invalid = 0

    def assert_append_only(self) -> None:
        """The prefix (first n0 nodes/edges) must be the same objects in the same order —
        only appends past n0 and in-place property mutation are allowed."""
        assert len(self.nodes) >= self.n_nodes0 and len(self.edges) >= self.n_edges0, \
            "step05c must not shrink the node/edge arrays"
        assert [id(n) for n in self.nodes[:self.n_nodes0]] == self._prefix_node_ids, \
            "step05c reordered or replaced an existing node — breaks _node_key/dossier positions"
        assert [id(e) for e in self.edges[:self.n_edges0]] == self._prefix_edge_ids, \
            "step05c reordered or replaced an existing edge"

    def _key(self, node: Dict[str, Any]) -> Tuple[str, str]:
        cls = node.get("class", "")
        p = node.get("properties") or {}
        ident = p.get("id") if cls == "StandardIndicator" else p.get("name")
        return (cls, norm(ident))

    def _register(self, idx: int) -> None:
        self._by_id.setdefault(self._key(self.nodes[idx]), idx)

    def find(self, cls: str, ident: str) -> Optional[int]:
        return self._by_id.get((cls, norm(ident)))

    def ensure_node(self, node: Dict[str, Any]) -> Tuple[int, bool]:
        """Return (index, created)."""
        key = self._key(node)
        if key in self._by_id:
            return self._by_id[key], False
        idx = len(self.nodes)
        self.nodes.append(node)
        self._by_id[key] = idx
        return idx, True

    def add_edge(self, s_idx: int, predicate: str, o_idx: int,
                 temporal_metadata: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> bool:
        """Append an index-based edge after checking the schema DIRECTION only.

        We do NOT reuse step03's validate_triple here: it also requires valid_from/valid_to/
        is_current on both endpoints, which is correct at the extraction stage but wrong on the
        RESOLVED graph, where step05 deliberately strips those fields off T1/T3 entity nodes
        (time lives on edges + temporal_versions, P2). The real constraint this stage must honour
        is the legal (source_class, target_class) pair — exactly the gap diagnosis C5 identified."""
        s_cls = self.nodes[s_idx].get("class")
        o_cls = self.nodes[o_idx].get("class")
        if predicate not in self.edge_labels:
            self.dropped_invalid += 1
            logger.warning(f"Dropping {predicate}: label not in schema")
            return False
        pairs = self.edge_dirs.get(predicate, [])
        if pairs and not any(s == s_cls and t == o_cls for s, t in pairs):
            self.dropped_invalid += 1
            logger.warning(f"Dropping invalid direction {s_cls} -{predicate}-> {o_cls}")
            return False
        sig = (s_idx, predicate, o_idx)
        if sig in self._edgeset:
            return False
        edge = {"subject": s_idx, "predicate": predicate, "object": o_idx,
                "temporal_metadata": temporal_metadata, "anchor_method": "offline_indicator_map"}
        if extra:
            edge.update(extra)
        self.edges.append(edge)
        self._edgeset.add(sig)
        return True


# --------------------------------------------------------------------------- #
def make_indicator_node(d: Dict[str, Any]) -> Dict[str, Any]:
    src = d.get("source") or {}
    return {"class": "StandardIndicator",
            "properties": {"id": d["id"], "name": d.get("name"),
                           "definition": d.get("definition"), "pillar": d.get("pillar"),
                           "section": src.get("section"),
                           "source_document": src.get("document"),
                           "valid_from": None, "valid_to": None, "is_current": True}}


def make_doc_node(dockey: str, kind: str, canonical: str) -> Dict[str, Any]:
    return {"class": kind,
            "properties": {"name": canonical, "valid_from": None, "valid_to": None,
                           "is_current": True}}


def make_gri_node(code: str, name: Optional[str]) -> Dict[str, Any]:
    return {"class": "StandardIndicator",
            "properties": {"id": code, "name": name or code, "definition": None,
                           "pillar": None, "section": None, "source_document": "GRI Standards",
                           "valid_from": None, "valid_to": None, "is_current": True}}


def run(args: argparse.Namespace) -> None:
    for path, hint in ((args.input, "run step05_resolve_entities.py then step05b first"),
                       (args.defs, "kpi_definitions_construction.json missing")):
        if not path.exists():
            logger.error(f"Input not found: {path} ({hint}).")
            return

    graph = json.loads(args.input.read_text(encoding="utf-8"))
    defs = json.loads(args.defs.read_text(encoding="utf-8"))
    crosswalk = json.loads(args.crosswalk.read_text(encoding="utf-8")) if args.crosswalk.exists() else {}
    entity_classes, edge_labels, edge_dirs = load_schema_sets(
        json.loads(args.schema.read_text(encoding="utf-8")))

    gp = GraphPatch(graph, entity_classes, edge_labels, edge_dirs)
    stats: Dict[str, Any] = {"created_nodes": Counter(), "created_edges": Counter(),
                             "measured_by_indicator": Counter(), "aligned_by_indicator": Counter(),
                             "penalty_self_reported_zero": 0, "unmapped_kpi_ids": Counter()}

    # 1) indicator nodes + partOf → document node
    ind_idx: Dict[str, int] = {}
    for d in defs:
        node = make_indicator_node(d)
        idx, created = gp.ensure_node(node)
        ind_idx[d["id"]] = idx
        if created:
            stats["created_nodes"]["StandardIndicator"] += 1

        dk = doc_key_for(d["id"])
        if dk:
            dockey, kind = dk
            canonical = DOC_CANONICAL.get(dockey, dockey)
            # `find` can legitimately return index 0, so test `is None` explicitly rather
            # than `a or b` (0 is falsy — it would skip a real match at node 0).
            doc_i = gp.find("Regulation", canonical)
            if doc_i is None:
                doc_i = gp.find("Standard", canonical)
            if doc_i is None:
                doc_i, dcreated = gp.ensure_node(make_doc_node(dockey, kind, canonical))
                if dcreated:
                    stats["created_nodes"][f"doc:{kind}"] += 1
            if gp.add_edge(idx, "partOf", doc_i, temporal_md(node["properties"])):
                stats["created_edges"]["partOf"] += 1

    valid_ids = set(ind_idx)

    # 2) measuredUnder from KPIObservation.kpi_id
    for i, n in enumerate(gp.nodes[:gp.n_nodes0]):
        cls = n.get("class")
        p = n.get("properties") or {}
        if cls == "KPIObservation":
            kid = p.get("kpi_id")
            if not kid:
                continue
            if kid not in valid_ids:
                stats["unmapped_kpi_ids"][kid] += 1
                continue
            if gp.add_edge(i, "measuredUnder", ind_idx[kid], temporal_md(p)):
                stats["created_edges"]["measuredUnder"] += 1
                stats["measured_by_indicator"][kid] += 1
        elif cls == "Emission":
            # Emission is a GHG observation → TT96-6.1.1 (Scope 1+2 total).
            tgt = ind_idx.get("TT96-6.1.1")
            if tgt is not None and gp.add_edge(i, "measuredUnder", tgt, temporal_md(p)):
                stats["created_edges"]["measuredUnder"] += 1
                stats["measured_by_indicator"]["TT96-6.1.1"] += 1
        elif cls == "Penalty":
            amount = p.get("amount")
            pid = str(p.get("penalty_id") or "")
            if (amount in (0, 0.0)) or pid.endswith("_0times") or "_0times" in pid:
                # self-reported "fined 0 times" — a compliance CLAIM, not conduct evidence
                p["self_reported_zero"] = True
                stats["penalty_self_reported_zero"] += 1
                continue
            pen_ind = "TT96-6.5.2" if amount else "TT96-6.5.1"
            tgt = ind_idx.get(pen_ind)
            if tgt is not None and gp.add_edge(i, "measuredUnder", tgt, temporal_md(p)):
                stats["created_edges"]["measuredUnder"] += 1
                stats["measured_by_indicator"][pen_ind] += 1

    # 3) equivalentTo TT96 → GRI (confirmed crosswalk rows only)
    if not args.no_gri:
        for row in crosswalk.get("confirmed", []):
            confirmed = row.get("status") == "confirmed" or args.trust_draft_crosswalk
            if not confirmed:
                continue
            tt = row.get("tt96")
            if tt not in ind_idx:
                continue
            for j, gri in enumerate(row.get("gri") or []):
                gname = row.get("gri_name")
                gidx, gcreated = gp.ensure_node(make_gri_node(gri, gname))
                if gcreated:
                    stats["created_nodes"]["StandardIndicator(GRI)"] += 1
                    # a GRI code is part of the GRI standard
                    doc_i = gp.find("Standard", DOC_CANONICAL["GRI"])
                    if doc_i is None:
                        doc_i, _ = gp.ensure_node(
                            make_doc_node("GRI", "Standard", DOC_CANONICAL["GRI"]))
                        stats["created_nodes"]["doc:Standard"] += 1
                    if gp.add_edge(gidx, "partOf", doc_i, temporal_md({})):
                        stats["created_edges"]["partOf"] += 1
                if gp.add_edge(ind_idx[tt], "equivalentTo", gidx, temporal_md({}),
                               extra={"confidence": row.get("confidence")}):
                    stats["created_edges"]["equivalentTo"] += 1

    # 4) alignsWithIndicator (keyword tier) for Claim/Goal/Initiative
    if not args.no_align:
        kw = build_keyword_index(defs)
        for i, n in enumerate(gp.nodes[:gp.n_nodes0]):
            cls = n.get("class")
            if cls not in ("SustainabilityClaim", "Goal", "Initiative"):
                continue
            p = n.get("properties") or {}
            text = " ".join(str(p.get(k) or "") for k in ("description", "name", "title"))
            hit = match_keyword(text, kw)
            if hit and hit in ind_idx:
                if gp.add_edge(i, "alignsWithIndicator", ind_idx[hit], temporal_md(p),
                               extra={"alignment_method": "keyword"}):
                    stats["created_edges"]["alignsWithIndicator"] += 1
                    stats["aligned_by_indicator"][hit] += 1

    added_nodes = len(gp.nodes) - gp.n_nodes0
    added_edges = len(gp.edges) - gp.n_edges0
    # invariant: existing prefix is the same objects in the same order (properties may be
    # mutated in place, e.g. self_reported_zero on a Penalty).
    gp.assert_append_only()

    def _c(counter):
        return dict(counter.most_common()) if isinstance(counter, Counter) else counter
    report = {
        "nodes_before": gp.n_nodes0, "nodes_after": len(gp.nodes), "nodes_added": added_nodes,
        "edges_before": gp.n_edges0, "edges_after": len(gp.edges), "edges_added": added_edges,
        "created_nodes": _c(stats["created_nodes"]),
        "created_edges": _c(stats["created_edges"]),
        "penalty_self_reported_zero": stats["penalty_self_reported_zero"],
        "dropped_invalid": gp.dropped_invalid,
        "measured_by_indicator": _c(stats["measured_by_indicator"]),
        "aligned_by_indicator": _c(stats["aligned_by_indicator"]),
        "unmapped_kpi_ids": _c(stats["unmapped_kpi_ids"]),
    }
    logger.info(f"Nodes {gp.n_nodes0} → {len(gp.nodes)} (+{added_nodes}); "
                f"edges {gp.n_edges0} → {len(gp.edges)} (+{added_edges}).")
    logger.info(f"created_edges: {report['created_edges']}")
    logger.info(f"penalty self_reported_zero (no conduct edge): {report['penalty_self_reported_zero']}")

    if args.dry_run:
        logger.info("--dry-run: nothing written.")
        return

    args.input.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {args.input} and {args.stats_out}. "
                f"Next: python src/step06_load_graph_to_neo4j.py --clear")


# --------------------------------------------------------------------------- #
# Keyword tier — unambiguous only (one candidate indicator or nothing).
# --------------------------------------------------------------------------- #
KEYWORDS: Dict[str, List[str]] = {
    "TT96-6.1.1": ["phát thải khí nhà kính", "khí nhà kính", "ghg", "co2", "carbon"],
    "TT96-6.3.1": ["tiêu thụ năng lượng", "tiêu thụ điện", "energy consumption"],
    "TT96-6.3.2": ["tiết kiệm năng lượng", "tiết kiệm điện", "energy saving"],
    "TT96-6.4.1": ["tiêu thụ nước", "sử dụng nước", "water consumption", "water use"],
    "TT96-6.4.2": ["tái sử dụng nước", "nước tái chế", "water recycl"],
    "TT96-6.6.3": ["đào tạo nhân viên", "đào tạo lao động", "employee training"],
    "TT96-6.6.4": ["giờ đào tạo", "training hours"],
    "TT96-6.7.1": ["hoạt động cộng đồng", "vì cộng đồng", "community program"],
    "TT96-6.7.2": ["đóng góp cộng đồng", "đầu tư cộng đồng", "community investment", "từ thiện"],
    "SSCIFC-S5": ["an toàn lao động", "occupational safety", "tai nạn lao động"],
    "SSCIFC-S6": ["đa dạng", "bình đẳng giới", "diversity", "gender"],
    "SSCIFC-E7": ["tái chế chất thải", "tái chế rác", "waste recycl"],
}


def build_keyword_index(defs: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    valid = {d["id"] for d in defs}
    return {k: [p.lower() for p in v] for k, v in KEYWORDS.items() if k in valid}


def match_keyword(text: str, kw: Dict[str, List[str]]) -> Optional[str]:
    t = text.lower()
    hits = {ind for ind, phrases in kw.items() if any(p in t for p in phrases)}
    return next(iter(hits)) if len(hits) == 1 else None   # unambiguous only


def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 5c — materialize the TT96/GRI indicator axis (offline, no LLM).")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_RESOLVED,
                   help="Resolved graph JSON (patched in place, append-only).")
    p.add_argument("--defs", type=Path, default=DEFAULT_DEFS)
    p.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    p.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--no-gri", action="store_true", help="Skip equivalentTo → GRI edges.")
    p.add_argument("--no-align", action="store_true", help="Skip the keyword alignsWithIndicator tier.")
    p.add_argument("--trust-draft-crosswalk", action="store_true",
                   help="Emit GRI edges for draft crosswalk rows too (demo only; bypasses review).")
    p.add_argument("--stats-out", type=Path, default=DEFAULT_STATS_OUT)
    p.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    run(p.parse_args())


if __name__ == "__main__":
    main()
