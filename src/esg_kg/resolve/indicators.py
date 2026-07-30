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
  * It does not guess an indicator's `pillar`. That comes from the file entitled to say —
    kpi_definitions_construction.json for the Vietnamese vocabulary, config/gri_catalog.json for
    GRI — and an id neither covers keeps whatever pillar it already had. The substring chain this
    replaced ("6.1"/"6.2"/... => Môi trường, "6.6"/"6.7" => Xã hội, else Quản trị) mislabelled 7 of
    65 live indicator nodes: "TT96-6.6.1" contains BOTH "6.6" and "6.1" and the environmental
    branch ran first, so all five TT96-6.6.* labour indicators were filed under Môi trường, while
    QD2171-1 and QCVN09-1 fell through to Quản trị. The Evidence View takes a claim's E/S/G column
    straight from this property, so a guess here is visible to the reader.

WHY IT RESTAMPS RATHER THAN JUST STOPPING
Nodes are deduped by identity, so re-running never rewrites one that already exists — an indicator
carrying a wrong pillar would stay wrong short of rebuilding from step05, which reorders nodes and
invalidates the paid step07 dossiers. Correcting one property in place is allowed by the
append-only invariant above, so the repair costs nothing and breaks nothing. The restamp runs
BEFORE assert_append_only() and before the --dry-run return, so the invariant guards it and
--dry-run reports it.

  python src/step05c_link_standard_indicators.py --dry-run
  python src/step05c_link_standard_indicators.py

Run from the repo root, after step05b (provenance) and before step06 (Neo4j load):
  python src/run.py indicators --dry-run
  python src/run.py indicators
Equivalently, from inside src/:  python -m esg_kg.resolve.indicators --dry-run

Moved verbatim from src/step05c_link_standard_indicators.py (Model A: that file still
exists and still runs). What differs: the docstring, the import block, and the removal of
GraphPatch/temporal_md/norm/TODAY, which moved to esg_kg.core.graph_patch so the migrated
step05d can import them from the kernel rather than from a sibling stage. The logic below
is unchanged, and test/test_esg_kg_equivalence.py runs both trees on the real graph to
keep it that way.
"""

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from esg_kg.core.graph_patch import GraphPatch, temporal_md
from esg_kg.core.paths import REPO_ROOT
from esg_kg.core.schema import load_schema_sets

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_RESOLVED = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_DEFS = REPO_ROOT / "kpi_definitions_construction.json"
DEFAULT_CROSSWALK = REPO_ROOT / "config" / "standard_crosswalk.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_STATS_OUT = REPO_ROOT / "graph_output" / "resolved" / "indicator_axis_stats.json"

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


GRI_CATALOG_PATH = REPO_ROOT / "config" / "gri_catalog.json"


def load_gri_catalog(path: Path) -> Dict[str, Any]:
    """Read config/gri_catalog.json. Absent or unreadable degrades to {} — the GRI
    tier is optional and a missing catalog must not take the whole stage down.

    Loaded once per run() and passed down explicitly. It used to be a module-global
    memo, which meant tests could neither vary it nor stop it leaking between them.
    """
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a broken catalog degrades, never aborts
        logger.warning(f"Could not read GRI catalog at {path}; continuing without it.")
        return {}


def make_gri_node(code: str, name: Optional[str], catalog: Dict[str, Any]) -> Dict[str, Any]:
    """A GRI indicator node. `pillar` comes from the catalog or stays None.

    It is deliberately NOT guessed from the shape of the code. The guess this
    replaced ("Môi trường" if "30"/"101"/"102"/"103" in code else "Xã hội" if "40"
    in code else "Quản trị") disagreed with the catalog it was supposed to back up,
    and a wrong pillar is worse than a missing one: the Evidence View files the
    claim under the wrong E/S/G column instead of leaving it unplaced.
    """
    cat_entry = catalog.get(code) or {}
    node_name = cat_entry.get("title_vi") or cat_entry.get("title_en") or name or code
    definition = cat_entry.get("definition_vi") or f"Chỉ số {code}: {node_name}"
    return {"class": "StandardIndicator",
            "properties": {"id": code, "name": node_name, "definition": definition,
                           "pillar": cat_entry.get("pillar"), "section": None,
                           "source_document": "GRI Standards",
                           "valid_from": None, "valid_to": None, "is_current": True}}


def pillar_authority(defs: List[Dict[str, Any]], catalog: Dict[str, Any]) -> Dict[str, str]:
    """indicator id -> pillar, from the two files that are entitled to say.

    `kpi_definitions_construction.json` owns the Vietnamese vocabulary (TT96, SSC-IFC,
    QĐ2171, QCVN09); `config/gri_catalog.json` owns GRI. Anything else has no entry,
    and an indicator with no entry keeps whatever pillar it already had.
    """
    authority = {d["id"]: d.get("pillar") for d in defs if d.get("id") and d.get("pillar")}
    for code, entry in (catalog or {}).items():
        if entry.get("pillar"):
            authority.setdefault(code, entry["pillar"])
    return authority


def restamp_pillars(nodes: List[Dict[str, Any]], authority: Dict[str, str]) -> Counter:
    """Correct `pillar` on StandardIndicator nodes from the authority. Returns what changed.

    Why a restamp and not just "stop overwriting": the stage dedups nodes by identity,
    so re-running never rewrites a node that already exists. Indicators already carrying
    a wrong pillar would stay wrong forever short of rebuilding from step05 — which
    reorders nodes and invalidates the paid step07 dossiers. Mutating one property in
    place is explicitly allowed by GraphPatch.assert_append_only(), so node order and
    dossier positions survive.

    Never invents a value: an id the authority does not cover is left alone. The loop
    this replaced defaulted to "Quản trị", which is how QD2171-1 and QCVN09-1 — both
    environmental — ended up filed under governance.
    """
    changed: Counter = Counter()
    for n in nodes:
        if n.get("class") != "StandardIndicator":
            continue
        p = n.setdefault("properties", {})
        truth = authority.get(p.get("id"))
        if truth and p.get("pillar") != truth:
            changed[f"{p.get('id')}: {p.get('pillar')} -> {truth}"] += 1
            p["pillar"] = truth
    return changed


def link_indicator_axis(graph: Dict[str, Any], defs: List[Dict[str, Any]],
                        crosswalk: Dict[str, Any], catalog: Dict[str, Any],
                        entity_classes, edge_labels, edge_dirs, *,
                        no_gri: bool = False, no_align: bool = False,
                        trust_draft_crosswalk: bool = False) -> Dict[str, Any]:
    """Stage 05c, pure: mutates `graph` in place via GraphPatch, returns the report dict.

    Writes NOTHING — split out of `run()` so the resolve BLOCK
    (`esg_kg/resolve/build_resolved.py`, DESIGN.md §5.7) can chain 05 -> 05b -> 05c in
    memory with no intermediate `resolved_graph.json` write between them. Pure
    extraction: no logic line differs from what `run()` used to do inline; `run()` below
    now just does argparse + file I/O + calling this function.
    """
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
    if not no_gri:
        for row in crosswalk.get("confirmed", []):
            confirmed = row.get("status") == "confirmed" or trust_draft_crosswalk
            if not confirmed:
                continue
            tt = row.get("tt96")
            if tt not in ind_idx:
                continue
            for j, gri in enumerate(row.get("gri") or []):
                gname = row.get("gri_name")
                gidx, gcreated = gp.ensure_node(make_gri_node(gri, gname, catalog))
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
    if not no_align:
        kw = build_keyword_index(defs, catalog)
        for i, n in enumerate(gp.nodes[:gp.n_nodes0]):
            cls = n.get("class")
            if cls not in ("SustainabilityClaim", "Goal", "Initiative"):
                continue
            p = n.get("properties") or {}
            text = " ".join(str(p.get(k) or "") for k in ("description", "name", "title"))
            hit = match_keyword(text, kw)
            if hit:
                if hit in ind_idx:
                    tgt_idx = ind_idx[hit]
                elif hit.startswith("GRI"):
                    tgt_idx, _ = gp.ensure_node(make_gri_node(hit, None, catalog))
                else:
                    tgt_idx = None

                if tgt_idx is not None:
                    axis_type = "gri_fallback" if str(hit).startswith("GRI") else "tt96"
                    if gp.add_edge(i, "alignsWithIndicator", tgt_idx, temporal_md(p),
                                   extra={"alignment_method": "keyword", "indicator_axis": axis_type}):
                        stats["created_edges"]["alignsWithIndicator"] += 1
                        stats["aligned_by_indicator"][hit] += 1

    # 5) pillar: correct every indicator node from the authority that owns it. Runs BEFORE
    # assert_append_only() and before the --dry-run return, so the invariant guards it and
    # --dry-run reports it. (It used to sit after both, unguarded and unreported.)
    pillar_changes = restamp_pillars(graph["nodes"], pillar_authority(defs, catalog))

    added_nodes = len(gp.nodes) - gp.n_nodes0
    added_edges = len(gp.edges) - gp.n_edges0
    # invariant: existing prefix is the same objects in the same order (properties may be
    # mutated in place, e.g. self_reported_zero on a Penalty, or a corrected pillar).
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
        "pillar_restamped": sum(pillar_changes.values()),
        "pillar_changes": _c(pillar_changes),
    }
    return report


def run(args: argparse.Namespace) -> None:
    for path, hint in ((args.input, "run step05_resolve_entities.py then step05b first"),
                       (args.defs, "kpi_definitions_construction.json missing")):
        if not path.exists():
            logger.error(f"Input not found: {path} ({hint}).")
            return

    graph = json.loads(args.input.read_text(encoding="utf-8"))
    defs = json.loads(args.defs.read_text(encoding="utf-8"))
    crosswalk = json.loads(args.crosswalk.read_text(encoding="utf-8")) if args.crosswalk.exists() else {}
    catalog = load_gri_catalog(getattr(args, "gri_catalog", GRI_CATALOG_PATH))
    entity_classes, edge_labels, edge_dirs = load_schema_sets(
        json.loads(args.schema.read_text(encoding="utf-8")))

    report = link_indicator_axis(
        graph, defs, crosswalk, catalog, entity_classes, edge_labels, edge_dirs,
        no_gri=args.no_gri, no_align=args.no_align,
        trust_draft_crosswalk=args.trust_draft_crosswalk)

    logger.info(f"Nodes {report['nodes_before']} → {report['nodes_after']} (+{report['nodes_added']}); "
                f"edges {report['edges_before']} → {report['edges_after']} (+{report['edges_added']}).")
    logger.info(f"created_edges: {report['created_edges']}")
    logger.info(f"penalty self_reported_zero (no conduct edge): {report['penalty_self_reported_zero']}")
    logger.info(f"pillar corrected from the authority: {report['pillar_restamped']}"
                + (f" {report['pillar_changes']}" if report['pillar_changes'] else ""))

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
    # Environmental (Môi trường)
    "TT96-6.1.1": ["phát thải khí nhà kính", "khí nhà kính", "ghg", "co2", "carbon", "phát thải", "scope 1", "scope 2", "kiểm kê khí nhà kính"],
    "TT96-6.3.1": ["tiêu thụ năng lượng", "tiêu thụ điện", "năng lượng", "điện năng", "energy consumption", "tiêu thụ nhiên liệu", "xăng dầu"],
    "TT96-6.3.2": ["tiết kiệm năng lượng", "tiết kiệm điện", "tái tạo", "năng lượng mặt trời", "energy saving", "hiệu quả năng lượng", "xanh hóa"],
    "TT96-6.4.1": ["tiêu thụ nước", "sử dụng nước", "nguồn nước", "water consumption", "water use", "lượng nước sử dụng"],
    "TT96-6.4.2": ["tái sử dụng nước", "nước tái chế", "nước thải", "water recycl", "tuần hoàn nước", "nước làm mát"],
    "SSCIFC-E7": ["tái chế chất thải", "tái chế rác", "chất thải", "rác thải", "waste recycl", "rác thải nhựa", "tự hủy sinh học", "aneco", "sản xuất tinh gọn", "rác thải nguy hại"],
    "GRI 301-1": ["nguyên vật liệu", "nguyên liệu", "bao bì", "hạt nhựa", "nhựa tái chế", "nhựa sinh học", "vật liệu hạt"],
    "GRI 305-5": ["giảm phát thải", "giảm khí nhà kính", "giảm co2", "cắt giảm phát thải"],

    # Social (Xã hội)
    "TT96-6.6.1": ["tỷ lệ lao động", "người lao động", "chính sách nhân sự", "chế độ đãi ngộ", "môi trường làm việc", "thu nhập trung bình", "tiền lương"],
    "TT96-6.6.3": ["đào tạo nhân viên", "đào tạo lao động", "bồi dưỡng", "huấn luyện", "employee training", "đào tạo chuyên môn", "nâng cao tay nghề", "khóa đào tạo"],
    "TT96-6.6.4": ["giờ đào tạo", "training hours"],
    "TT96-6.7.1": ["hoạt động cộng đồng", "vì cộng đồng", "xã hội", "tài trợ", "community program", "an sinh xã hội", "từ thiện", "người nghèo", "covid-19"],
    "TT96-6.7.2": ["đóng góp cộng đồng", "đầu tư cộng đồng", "community investment", "tài trợ học bổng", "xây nhà tình nghĩa"],
    "SSCIFC-S5": ["an toàn lao động", "sức khỏe lao động", "occupational safety", "tai nạn lao động", "bảo hộ", "pccc", "phòng cháy chữa cháy", "vệ sinh lao động"],
    "SSCIFC-S6": ["đa dạng", "bình đẳng giới", "tỷ lệ nữ", "phụ nữ", "diversity", "gender", "cơ cấu giới tính", "nữ quản lý"],
    "GRI 401-1": ["tuyển dụng", "nhân sự mới", "tỷ lệ nghỉ việc", "biến động lao động"],
    "GRI 403-6": ["chăm sóc sức khỏe", "khám sức khỏe", "bảo hiểm y tế", "phúc lợi lao động", "bảo hiểm xã hội"],

    # Governance (Quản trị)
    "GRI 2-1": ["cơ cấu tổ chức", "thông tin tổ chức", "mô hình doanh nghiệp", "công ty mẹ", "công ty con"],
    "GRI 2-9": ["hội đồng quản trị", "hđqt", "ban điều hành", "ban giám đốc", "thành viên hđqt", "cơ cấu quản trị", "nữ hđqt", "độc lập hđqt"],
    "GRI 2-12": ["vai trò của hđqt", "quản trị công ty", "giám sát chiến lược", "chiến lược esg", "ủy ban quản trị"],
    "GRI 2-14": ["giám sát công bố thông tin", "hđqt giám sát", "board oversight", "báo cáo thông tin", "minh bạch thông tin"],
    "GRI 2-23": ["cam kết chính sách", "quy tắc ứng xử", "chuẩn mực đạo đức", "văn hóa doanh nghiệp"],
    "GRI 2-27": ["tuân thủ pháp luật", "xử phạt", "phạt vi phạm", "quản lý môi trường", "tuân thủ quy định"],
    "GRI 2-29": ["quan hệ nhà đầu tư", "ir department", "bộ phận ir", "stakeholder engagement", "cổ đông", "đại hội đồng cổ đông", "đối thoại cổ đông"],
    "GRI 201-1": ["giá trị kinh tế", "doanh thu", "lợi nhuận", "đóng góp ngân sách", "thuế", "nộp ngân sách", "tài chính"],
    "GRI 203-1": ["tác động kinh tế gián tiếp", "đầu tư cơ sở hạ tầng", "indirect economic impact", "phát triển địa phương", "cơ sở hạ tầng"],
    "GRI 205-1": ["chống tham nhũng", "anti-corruption", "đạo đức kinh doanh", "phòng chống tham nhũng", "liêm chính", "rủi ro tham nhũng"],
    "GRI 205-2": ["truyền thông và đào tạo về chống tham nhũng", "quy tắc ứng xử chống tham nhũng", "chính sách liêm chính"],
}


def build_keyword_index(defs: List[Dict[str, Any]], catalog: Dict[str, Any]) -> Dict[str, List[str]]:
    kw_index = {k: [p.lower() for p in v] for k, v in KEYWORDS.items()}
    # Add items from gri_catalog
    for code, info in catalog.items():
        if code not in kw_index:
            title_vi = info.get("title_vi", "").lower()
            title_en = info.get("title_en", "").lower()
            phrases = []
            if len(title_vi) > 10:
                phrases.append(title_vi)
            if len(title_en) > 10:
                phrases.append(title_en)
            if phrases:
                kw_index[code] = phrases
    return kw_index


def match_keyword(text: str, kw: Dict[str, List[str]]) -> Optional[str]:
    t = text.lower()
    matched_candidates = []
    for ind, phrases in kw.items():
        for p in phrases:
            if p in t:
                matched_candidates.append((len(p), ind))
    if not matched_candidates:
        return None
    matched_candidates.sort(key=lambda x: x[0], reverse=True)
    return matched_candidates[0][1]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 5c — materialize the TT96/GRI indicator axis (offline, no LLM).")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_RESOLVED,
                   help="Resolved graph JSON (patched in place, append-only).")
    p.add_argument("--defs", type=Path, default=DEFAULT_DEFS)
    p.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    p.add_argument("--gri-catalog", type=Path, default=GRI_CATALOG_PATH,
                   help="GRI indicator catalog (titles + pillar); rebuild with gri/build_gri_catalog.py")
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
