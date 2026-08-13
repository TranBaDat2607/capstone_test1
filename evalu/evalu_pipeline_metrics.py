#!/usr/bin/env python3
"""
evalu_pipeline_metrics.py — the 11 label-free pipeline control metrics from evalu.pdf.

Every number here is read off an artifact on disk. There are no default values,
no benchmark fallbacks and no simulated inputs: a metric that cannot be computed
returns ``measured=False`` with a reason, and the renderer prints that instead of
a score. This is the whole design constraint — an earlier version of this file
fell back to hardcoded "benchmark" numbers when a query came up empty, and
because its graph queries used field names no writer in this repo emits
(``class_name``/``relation``/``source`` rather than ``class``/``predicate``/
``subject``), *every* graph query came up empty. The report was therefore made
entirely of stand-in constants that read as results. Guarded by
``test/test_evalu_metrics.py``.

Where the pipeline already computes a metric, this module SOURCES it from
``esg_kg.report.quality`` (step00) rather than reimplementing it. That stage is
covered by ``test/test_esg_kg_equivalence.py`` and is what the thesis reports
elsewhere; a second private copy of the same formula would be free to drift from
it, and the two numbers would disagree in the same document.

Offline: no LLM, no Neo4j, no network.
Run:  python evalu/evalu_pipeline_metrics.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.report import quality  # noqa: E402

GRAPH_OUTPUT = REPO_ROOT / "graph_output"
RESOLVED_GRAPH = GRAPH_OUTPUT / "resolved" / "resolved_graph.json"
CROSSCHECK = GRAPH_OUTPUT / "crosscheck" / "aaa_claim_assessments.json"
PROVENANCE_STATS = GRAPH_OUTPUT / "resolved" / "provenance_patch_stats.json"
INDICATOR_STATS = GRAPH_OUTPUT / "resolved" / "indicator_axis_stats.json"
SCHEMA = REPO_ROOT / "config" / "schema.json"
LABELED_DIR = REPO_ROOT / "data" / "labeled"
KPI_DEFS = REPO_ROOT / "kpi_definitions_construction.json"
GRI_CATALOG = REPO_ROOT / "config" / "gri_catalog.json"

# The labeled corpus splits into two populations that must not be averaged: the
# AAA pilot the knowledge graph was built from (13 annual reports + 40 news
# articles), and the 1,216-document sector sweep that has been classified but
# never extracted. Only the first says anything about the graph being evaluated.
#
# "Built from" is approximate on the news side and deliberately not rounded off
# in the report: 40 news articles were labeled, 30 reached graph_output/graphs/,
# and 16 still carry a source_doc in the resolved graph. The SNR denominator is
# the LABELED population, which is the one the classifier was actually run on.
IN_GRAPH_LABEL_DIRS = ("annual_labeled", "news_labeled")

# Classes that can carry an alignsWithIndicator edge (step05c keyword tier +
# step05d LLM tier both emit for exactly these three).
ALIGNABLE_CLASSES = ("SustainabilityClaim", "Goal", "Initiative")

# A number followed by a unit is the cheapest defensible operationalisation of
# "grounded" for the SNR metric: marketing prose ("cam kết phát triển bền vững")
# has ESG vocabulary but no measurement attached to it.
NUMERIC_UNIT_RE = re.compile(
    r"\d[\d.,]*\s*(%|tấn|tan|kwh|mwh|gj|m3|m³|kg|lít|lit|tỷ|ty|triệu|trieu|"
    r"đồng|dong|vnd|usd|người|nguoi|giờ|gio|ngày|ngay|lần|lan|ha|km|co2|co2e)",
    re.IGNORECASE,
)


def _result(key: str, metric: str, *, measured: bool, score: Optional[float],
            numerator: Optional[int], denominator: Optional[int], source: str,
            note: str, **extra: Any) -> Dict[str, Any]:
    """The single result shape. `measured=False` forces `score=None` — the point
    of the flag is that an unmeasured metric cannot be mistaken for a passing
    one, so it must not be able to carry a number at all."""
    out = {
        "key": key,
        "metric": metric,
        "measured": measured,
        "score": None if not measured else (round(score, 4) if score is not None else None),
        "numerator": numerator,
        "denominator": denominator,
        "source": source,
        "note": note,
    }
    out.update(extra)
    return out


class PipelineEvaluator:
    """The 11 metrics of evalu.pdf §1-§5, measured on artifacts on disk."""

    def __init__(self, repo_root: Path = REPO_ROOT):
        self.repo_root = repo_root
        self.graph = self._load(RESOLVED_GRAPH) or {}
        self.nodes: List[Dict[str, Any]] = self.graph.get("nodes", [])
        self.edges: List[Dict[str, Any]] = self.graph.get("edges", [])
        self.dossiers = self._load(CROSSCHECK) or []
        self.schema = self._load(SCHEMA) or {}
        self.provenance_stats = self._load(PROVENANCE_STATS) or {}
        self.indicator_stats = self._load(INDICATOR_STATS) or {}
        # step00's own numbers, computed once and reused, so this module and the
        # thesis's quality report cannot disagree about the same quantity.
        self._q2 = quality.q2_consistency(self.nodes, self.edges, self.schema) if self.nodes else {}
        self._q3 = quality.q3_conciseness(self.nodes) if self.nodes else {}
        self._q5 = quality.q5_timeliness(self.nodes, self.edges) if self.nodes else {}
        self._q6 = quality.q6_provenance(self.nodes) if self.nodes else {}

    @staticmethod
    def _load(path: Path) -> Any:
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------------------------ #
    # Stage 1 — ingestion & ESG classification
    # ------------------------------------------------------------------ #
    def eval_esg_snr(self) -> Dict[str, Any]:
        """1. ESG Signal-to-Noise Ratio.

        evalu.pdf defines the numerator as sentences carrying "grounded" ESG
        terminology, which is not a measurable predicate as written — "grounded"
        has no operational definition and no lexicon in this repo backs it. It is
        narrowed here to something reproducible and stated on the report: a
        sentence classified `esg=true` counts as signal when it carries a NUMBER
        WITH A UNIT, or a controlled-vocabulary term from the two indicator files
        the pipeline already treats as authoritative (35 TT96/QĐ2171/QCVN09/
        SSC-IFC KPIs + 136 GRI codes). Generic commitment prose scores as noise,
        which is the discrimination the metric is for.
        """
        jsonls = sorted(LABELED_DIR.glob("*/*.jsonl"))
        if not jsonls:
            return _result("esg_snr", "ESG Signal-to-Noise Ratio (SNR)",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="data/labeled/*/*.jsonl",
                           note="Sentence-level SNR over ViDeBERTa esg=true output.",
                           reason="không có JSONL đã gán nhãn trên đĩa (chạy datasync pull)")

        lexicon = self._esg_lexicon()
        per_file: Dict[str, Any] = {}
        in_graph = {"esg_true": 0, "grounded": 0}
        sector = {"esg_true": 0, "grounded": 0}
        # Kept apart so the report can show what each half of the rule caught. A
        # single blended number would hide a lexicon that contributes nothing.
        by_signal = {"numeric_unit_only": 0, "lexicon_only": 0, "both": 0}
        # "Grounded" is a threshold, and the score moves with where it is put. A
        # looser reading (any digit at all) is carried alongside so the report can
        # state a BAND rather than assert one definition as the truth — the strict
        # rule scores a governance fact like "HĐQT có 4 thành viên độc lập" as
        # noise, which is arguable either way.
        loose_grounded = 0

        for path in jsonls:
            n_esg = n_grounded = 0
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if not rec.get("esg"):
                        continue
                    n_esg += 1
                    text = (rec.get("text") or "").lower()
                    has_num = bool(NUMERIC_UNIT_RE.search(text))
                    has_term = any(t in text for t in lexicon)
                    if path.parent.name in IN_GRAPH_LABEL_DIRS and any(c.isdigit() for c in text):
                        loose_grounded += 1
                    if has_num or has_term:
                        n_grounded += 1
                        key = ("both" if has_num and has_term
                               else "numeric_unit_only" if has_num else "lexicon_only")
                        by_signal[key] += 1
            scope = "in_graph" if path.parent.name in IN_GRAPH_LABEL_DIRS else "sector_sweep"
            per_file[path.name] = {"scope": scope, "esg_true": n_esg, "grounded": n_grounded,
                                   "snr": round(n_grounded / n_esg, 4) if n_esg else None}
            bucket = in_graph if scope == "in_graph" else sector
            bucket["esg_true"] += n_esg
            bucket["grounded"] += n_grounded

        # Headline scope = the corpus the graph was built from. The sector sweep
        # is classified but never extracted, so its SNR describes a corpus this
        # evaluation is not about.
        denom = in_graph["esg_true"]
        return _result("esg_snr", "ESG Signal-to-Noise Ratio (SNR)",
                       measured=True,
                       score=in_graph["grounded"] / denom if denom else None,
                       numerator=in_graph["grounded"], denominator=denom,
                       source="data/labeled/{annual_labeled,news_labeled}/*.jsonl",
                       note=("Tín hiệu = câu esg=true có con số KÈM ĐƠN VỊ, hoặc có thuật ngữ thuộc "
                             "bộ từ vựng kiểm soát (TT96/GRI). Nhiễu = văn cam kết chung chung "
                             "không kèm phép đo nào. Phạm vi là 53 tài liệu của pilot AAA "
                             "(13 báo cáo thường niên + 40 bài báo); "
                             "corpus quét ngành báo cáo riêng."),
                       per_file=per_file, lexicon_size=len(lexicon),
                       signal_breakdown=by_signal,
                       sensitivity_any_number={
                           "grounded": loose_grounded, "esg_true": denom,
                           "snr": round(loose_grounded / denom, 4) if denom else None,
                           "definition": "any digit anywhere in the sentence (upper bound)"},
                       sector_sweep_scope=dict(
                           sector,
                           snr=round(sector["grounded"] / sector["esg_true"], 4)
                           if sector["esg_true"] else None))

    def _esg_lexicon(self) -> List[str]:
        """Controlled vocabulary, taken from the two files the pipeline already
        treats as authoritative — never hand-typed here, so the metric moves when
        the vocabulary does."""
        terms: set[str] = set()

        # kpi_definitions_construction.json is a flat LIST of 35 KPI records.
        for item in (self._load(KPI_DEFS) or []):
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                terms.add(item["name"].lower())

        # gri_catalog.json is keyed BY indicator code, so the codes themselves
        # ("GRI 305-1") are vocabulary too — and unlike the long English titles
        # they actually appear in Vietnamese report sentences.
        gri = self._load(GRI_CATALOG) or {}
        if isinstance(gri, dict):
            for code, item in gri.items():
                terms.add(str(code).lower())
                if isinstance(item, dict):
                    for field in ("title_vi", "title_en"):
                        v = item.get(field)
                        if isinstance(v, str) and len(v) >= 6:
                            terms.add(v.lower())

        # Drop anything too short to be discriminative as a substring.
        return sorted(t for t in terms if len(t) >= 6)

    def eval_paragraph_provenance_rate(self) -> Dict[str, Any]:
        """2. Paragraph Source Provenance Rate — sentence-level traceability
        survives into the resolved graph.

        Sourced from step00's Q6 plus step05b's own stamping stats, because those
        two disagree in an informative way: Q6 counts nodes carrying ANY
        provenance marker, while step05b reports which claim/evidence nodes it
        could actually resolve back to a page. The gap is the real coverage."""
        if not self.nodes:
            return _result("paragraph_provenance_rate", "Paragraph Source Provenance Rate",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="graph_output/resolved/resolved_graph.json",
                           note="", reason="khong co resolved_graph.json tren dia")

        per_class = self.provenance_stats.get("per_class", {})
        stamped = sum(v.get("stamped", 0) for v in per_class.values())
        unmatched = sum(v.get("unmatched", 0) for v in per_class.values())
        total = stamped + unmatched
        return _result("paragraph_provenance_rate", "Paragraph Source Provenance Rate",
                       measured=True, score=stamped / total if total else None,
                       numerator=stamped, denominator=total,
                       source="esg_kg.report.quality.q6_provenance + provenance_patch_stats.json",
                       note=("Tỷ lệ node mang dấu vết nguồn mà step05b truy ngược được về đúng tài "
                             "liệu + số trang."),
                       nodes_with_source_type_pct=self._q6.get("nodes_with_source_type_pct"),
                       kpi_parseable_source_id_pct=self._q6.get("kpi_nodes_with_parseable_source_id_pct"),
                       unmatched_by_class={k: v["unmatched"] for k, v in per_class.items()
                                           if v.get("unmatched")})

    # ------------------------------------------------------------------ #
    # Stage 2 — triplet & KPI extraction
    # ------------------------------------------------------------------ #
    def eval_temporal_metadata_completeness(self) -> Dict[str, Any]:
        """3. Temporal Metadata Completeness — sourced from step00's Q5."""
        if not self._q5:
            return _result("temporal_metadata_completeness", "Temporal Metadata Completeness",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="esg_kg.report.quality.q5_timeliness", note="",
                           reason="khong co resolved_graph.json tren dia")
        edges_pct = self._q5["edges_with_valid_from_pct"]
        with_from = round(edges_pct / 100 * len(self.edges))
        return _result("temporal_metadata_completeness", "Temporal Metadata Completeness (C_temporal)",
                       measured=True, score=edges_pct / 100,
                       numerator=with_from, denominator=len(self.edges),
                       source="esg_kg.report.quality.q5_timeliness",
                       note=("Số cạnh mang temporal_metadata.valid_from. Trong đồ thị ĐÃ RESOLVE, "
                             "thời gian sống trên cạnh và node T2 (P2), nên thực thể T1 đúng ra "
                             "phải phi thời gian và không nằm trong mẫu số."),
                       t2_nodes_with_valid_from_pct=self._q5["t2_nodes_with_valid_from_pct"],
                       news_t2_with_date_uncertain_pct=self._q5["news_t2_with_date_uncertain_pct"])

    def eval_schema_compliance_rate(self) -> Dict[str, Any]:
        """4. Schema Compliance Rate — sourced from step00's Q2, which validates
        each edge against the legal (source_class, target_class) pairs in
        config/schema.json rather than merely checking the label is a string."""
        if not self._q2:
            return _result("schema_compliance", "Schema Compliance Rate",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="esg_kg.report.quality.q2_consistency", note="",
                           reason="khong co resolved_graph.json tren dia")
        illegal = self._q2["schema_illegal_edges"]
        return _result("schema_compliance", "Schema Compliance Rate (C_schema)",
                       measured=True, score=(len(self.edges) - illegal) / len(self.edges),
                       numerator=len(self.edges) - illegal, denominator=len(self.edges),
                       source="esg_kg.report.quality.q2_consistency",
                       note="Số cạnh có bộ ba (lớp chủ thể, vị từ, lớp đối tượng) hợp lệ theo schema.",
                       violations_breakdown={
                           "schema_illegal_edges": illegal,
                           "non_canonical_date_values": self._q2["non_canonical_date_values"],
                           "valid_from_after_valid_to": self._q2["valid_from_after_valid_to"],
                           "version_chains_not_exactly_one_is_current":
                               self._q2["version_chains_not_exactly_one_is_current"],
                           "news_t2_missing_date_uncertain": self._q2["news_t2_missing_date_uncertain"],
                           "total_violations": self._q2["total_violations"],
                       })

    def eval_value_preservation_guard(self) -> Dict[str, Any]:
        """5. Value Preservation Guard — NOT MEASURABLE from artifacts on disk.

        The guard itself exists and is enforced: `preserve_property_values` in
        `src/esg_kg/graph/fix_triples.py` restores any property value the phase-2
        repair LLM tried to rewrite, and `test/test_step03_llm_value_guard.py`
        drives a deliberately tampering stub through the real `process_all_files`
        to prove it is wired in, not merely defined.

        What does not exist is a RATE. The counter (`blocked_values`) is logged
        as a warning and then dropped; it is not written to any stats file, so no
        artifact carries it. Reconstructing it would mean re-running the paid
        phase-2 repair. Reporting 1.0 here — as the previous version did, by
        hashing a value and comparing it to itself, which is true for every input
        — would be an invented number, so this stays unmeasured.
        """
        return _result("value_preservation_guard", "Value Preservation Guard",
                       measured=False, score=None, numerator=None, denominator=None,
                       source="src/esg_kg/graph/fix_triples.py::preserve_property_values",
                       note=("Cơ chế có thật và được test/test_step03_llm_value_guard.py bảo vệ "
                             "(pass/fail), nhưng không tồn tại một tỷ lệ nào để báo cáo."),
                       reason=("Bộ đếm số giá trị bị chặn chỉ được ghi ra log, không bao giờ lưu vào "
                               "file stats. Muốn có tỷ lệ thì phải chạy lại bước sửa lỗi LLM "
                               "step03 phase 2 (có tính phí). Đã kiểm chứng như một bất biến, "
                               "không phải như một tỷ lệ."),
                       verified_by_test="test/test_step03_llm_value_guard.py")

    # ------------------------------------------------------------------ #
    # Stage 3 — entity resolution
    # ------------------------------------------------------------------ #
    def eval_timeless_identity_violation_rate(self) -> Dict[str, Any]:
        """6. Timeless Identity Violation Rate (P1) — sourced from step00's Q2.

        Note the level this is checked at: `identity_keys` is declared per CLASS
        in config/schema.json and never appears on a node instance, so scanning
        node properties for it (as the previous version did) reports 0 violations
        on every conceivable input, including a schema that violates P1 outright.
        """
        if not self._q2:
            return _result("timeless_identity_violation", "Timeless Identity Violation Rate",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="esg_kg.report.quality.q2_consistency", note="",
                           reason="khong co resolved_graph.json tren dia")
        offenders = self._q2["t1_identity_keys_with_time_fields"]
        n_t1_classes = len(quality.T1_CLASSES)
        return _result("timeless_identity_violation", "Timeless Identity Violation Rate (V_identity)",
                       measured=True, score=len(offenders) / n_t1_classes,
                       numerator=len(offenders), denominator=n_t1_classes,
                       source="esg_kg.report.quality.q2_consistency (schema-level P1 lint)",
                       note=("Số lớp thực thể T1 có trường thời gian nằm trong identity_keys. "
                             "Mục tiêu là 0 — định danh T1 bắt buộc phi thời gian (P1)."),
                       offending_classes=offenders)

    def eval_cluster_conciseness(self) -> Dict[str, Any]:
        """7. Cluster Conciseness — sourced from step00's Q3.

        Measures UNDER-merging only: one canonical entity that survived as more
        than one node. Over-merging (two distinct entities collapsed into one) is
        not measurable without labels and is NOT reported here, despite evalu.pdf
        listing both under one metric name."""
        if not self._q3:
            return _result("cluster_conciseness", "Cluster Conciseness",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="esg_kg.report.quality.q3_conciseness", note="",
                           reason="khong co resolved_graph.json tren dia")
        per_class = self._q3["per_class"]
        surplus = self._q3["total_surplus_duplicate_t1_nodes"]
        t1_total = sum(v["nodes"] for v in per_class.values())
        return _result("cluster_conciseness", "Cluster Conciseness (C_concise)",
                       measured=True, score=(t1_total - surplus) / t1_total if t1_total else None,
                       numerator=t1_total - surplus, denominator=t1_total,
                       source="esg_kg.report.quality.q3_conciseness",
                       note=("CHỈ đo vỡ cụm (under-merging): các node T1 trùng tên sau chuẩn hoá qua "
                             "Stage A/B/C/D. Gộp nhầm (over-merging) cần nhãn nên KHÔNG đo ở đây."),
                       surplus_duplicate_nodes=surplus,
                       worst_classes={k: v["surplus_duplicate_nodes"]
                                      for k, v in sorted(per_class.items(),
                                                         key=lambda kv: -kv[1]["surplus_duplicate_nodes"])
                                      if v["surplus_duplicate_nodes"]})

    # ------------------------------------------------------------------ #
    # Stage 4 — indicator axis
    # ------------------------------------------------------------------ #
    def eval_indicator_alignment_coverage(self) -> Dict[str, Any]:
        """8. Standard Indicator Alignment Coverage — share of alignable claim-side
        nodes carrying an alignsWithIndicator edge to a TT96/GRI indicator."""
        if not self.nodes:
            return _result("indicator_alignment_coverage", "Standard Indicator Alignment Coverage",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="graph_output/resolved/resolved_graph.json", note="",
                           reason="khong co resolved_graph.json tren dia")

        aligned = {e["subject"] for e in self.edges if e.get("predicate") == "alignsWithIndicator"}
        per_class: Dict[str, Dict[str, int]] = {}
        hit = total = 0
        for i, nd in enumerate(self.nodes):
            cls = nd.get("class")
            if cls not in ALIGNABLE_CLASSES:
                continue
            bucket = per_class.setdefault(cls, {"aligned": 0, "total": 0})
            bucket["total"] += 1
            total += 1
            if i in aligned:
                bucket["aligned"] += 1
                hit += 1
        for bucket in per_class.values():
            bucket["pct"] = round(100 * bucket["aligned"] / bucket["total"], 1)

        # Method mix, read off the edges themselves. step05c stamps the keyword
        # tier; step05d (optional, LLM) stamps alignment_method=llm.
        methods: Dict[str, int] = {}
        for e in self.edges:
            if e.get("predicate") != "alignsWithIndicator":
                continue
            m = (e.get("properties") or {}).get("alignment_method") or "keyword"
            methods[m] = methods.get(m, 0) + 1

        kpi_nodes = [i for i, n in enumerate(self.nodes) if n.get("class") == "KPIObservation"]
        measured_under = {e["subject"] for e in self.edges if e.get("predicate") == "measuredUnder"}
        kpi_hit = len(set(kpi_nodes) & measured_under)

        return _result("indicator_alignment_coverage", "Standard Indicator Alignment Coverage",
                       measured=True, score=hit / total if total else None,
                       numerator=hit, denominator=total,
                       source="graph_output/resolved/resolved_graph.json",
                       note=("Số node Claim/Goal/Initiative có cạnh alignsWithIndicator. Trục KPI "
                             "(measuredUnder) báo cáo riêng — nó lấy từ kpi_id của bước "
                             "canonicalize, không phải từ khớp cụm từ."),
                       per_class=per_class, method_mix=methods,
                       kpi_measured_under={"aligned": kpi_hit, "total": len(kpi_nodes),
                                           "pct": round(100 * kpi_hit / len(kpi_nodes), 1)
                                           if kpi_nodes else None})

    def eval_zero_report_exclusion(self) -> Dict[str, Any]:
        """9. Zero-Report Self-Praise Exclusion — a Penalty with amount == 0 is a
        self-reported "we were fined 0 times" and must be flagged, never turned
        into a conduct edge.

        This is an INVARIANT (pass/fail), not a rate: the whole graph holds 4
        such nodes, so a percentage over that denominator carries no statistical
        weight and is reported as a count."""
        if not self.nodes:
            return _result("zero_report_exclusion", "Zero-Report Self-Praise Exclusion",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="graph_output/resolved/resolved_graph.json", note="",
                           reason="khong co resolved_graph.json tren dia")

        zero_penalties = [n for n in self.nodes
                          if n.get("class") == "Penalty"
                          and (n.get("properties") or {}).get("amount") == 0]
        tagged = [p for p in zero_penalties
                  if (p.get("properties") or {}).get("self_reported_zero") is True]
        # The invariant's real teeth: a flagged zero must have produced no
        # conduct edge. Counting the tag alone would pass even if the edge leaked.
        zero_idx = {i for i, n in enumerate(self.nodes)
                    if n.get("class") == "Penalty"
                    and (n.get("properties") or {}).get("amount") == 0}
        conduct_edges_from_zero = sum(
            1 for e in self.edges
            if e["subject"] in zero_idx or e["object"] in zero_idx
            if e.get("predicate") in ("measuredUnder", "alignsWithIndicator"))

        return _result("zero_report_exclusion", "Zero-Report Self-Praise Exclusion",
                       measured=True,
                       score=len(tagged) / len(zero_penalties) if zero_penalties else None,
                       numerator=len(tagged), denominator=len(zero_penalties),
                       source="graph_output/resolved/resolved_graph.json + indicator_axis_stats.json",
                       note=("BẤT BIẾN, không phải tỷ lệ — toàn đồ thị chỉ có 4 node Penalty với "
                             "amount = 0. Báo cáo dưới dạng đếm."),
                       indicator_edges_leaked_from_zero_penalty=conduct_edges_from_zero,
                       stats_file_count=self.indicator_stats.get("penalty_self_reported_zero"),
                       verified_by_test="test/test_indicator_axis.py")

    # ------------------------------------------------------------------ #
    # Stage 5 — claim vs conduct cross-check
    # ------------------------------------------------------------------ #
    def eval_evidence_asymmetry_abstention(self) -> Dict[str, Any]:
        """10. Evidence Asymmetry & Abstention Rate — share of claims the system
        declined to judge for want of independent conduct-side evidence.

        High is honest, not bad: it reflects how thin the news channel is, and
        abstaining is the designed behaviour when there is nothing to check
        against. It measures the CORPUS, not the model."""
        if not self.dossiers:
            return _result("evidence_asymmetry_abstention", "Evidence Asymmetry & Abstention Rate",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="graph_output/crosscheck/aaa_claim_assessments.json", note="",
                           reason="khong co file dossier tren dia")

        by_assessment: Dict[str, int] = {}
        for d in self.dossiers:
            a = d.get("assessment")
            by_assessment[a] = by_assessment.get(a, 0) + 1
        unverified = by_assessment.get("unverified_insufficient_evidence", 0)
        with_evidence = sum(1 for d in self.dossiers
                            if (d.get("supporting_evidence") or d.get("contradicting_evidence")
                                or d.get("flagged_non_independent_support")))
        return _result("evidence_asymmetry_abstention", "Evidence Asymmetry & Abstention Rate",
                       measured=True, score=unverified / len(self.dossiers),
                       numerator=unverified, denominator=len(self.dossiers),
                       source="graph_output/crosscheck/aaa_claim_assessments.json",
                       note=("Từ chối kết luận là hành vi được thiết kế khi thiếu bằng chứng độc "
                             "lập. Chỉ số này đo độ mỏng của kho dữ liệu, không đo chất lượng model."),
                       by_assessment=by_assessment,
                       claims_with_any_evidence=with_evidence)

    def eval_self_verification_exclusion(self) -> Dict[str, Any]:
        """11. Self-Verification Exclusion Rate — share of 'supports' verdicts
        dropped because the evidence came from the company's own domain.

        Read from the dossiers, where the guard records its decision per evidence
        item (`flagged_non_independent_support`). It is NOT readable from the
        edges: the guard's whole effect is that the edge is never written, so
        counting edges finds nothing and reports a perfect score."""
        if not self.dossiers:
            return _result("self_verification_exclusion", "Self-Verification Exclusion Rate",
                           measured=False, score=None, numerator=None, denominator=None,
                           source="graph_output/crosscheck/aaa_claim_assessments.json", note="",
                           reason="khong co file dossier tren dia")

        flagged = sum(len(d.get("flagged_non_independent_support") or []) for d in self.dossiers)
        independent = sum(len(d.get("supporting_evidence") or []) for d in self.dossiers)
        total_support = flagged + independent
        claims_affected = sum(1 for d in self.dossiers
                              if d.get("flagged_non_independent_support"))
        return _result("self_verification_exclusion", "Self-Verification Exclusion Rate",
                       measured=True,
                       score=flagged / total_support if total_support else None,
                       numerator=flagged, denominator=total_support,
                       source="graph_output/crosscheck/aaa_claim_assessments.json",
                       note=("Tỷ lệ phán quyết 'supports' của LLM bị từ chối cấp cạnh verifiedBy vì "
                             "domain của bằng chứng thuộc về chính doanh nghiệp."),
                       independent_support_kept=independent,
                       claims_affected=claims_affected)

    # ------------------------------------------------------------------ #
    def run_all(self) -> Dict[str, Dict[str, Any]]:
        return {
            "stage_1_ingestion": {
                "esg_snr": self.eval_esg_snr(),
                "paragraph_provenance_rate": self.eval_paragraph_provenance_rate(),
            },
            "stage_2_extraction": {
                "temporal_metadata_completeness": self.eval_temporal_metadata_completeness(),
                "schema_compliance": self.eval_schema_compliance_rate(),
                "value_preservation_guard": self.eval_value_preservation_guard(),
            },
            "stage_3_entity_resolution": {
                "timeless_identity_violation": self.eval_timeless_identity_violation_rate(),
                "cluster_conciseness": self.eval_cluster_conciseness(),
            },
            "stage_4_indicator_axis": {
                "indicator_alignment_coverage": self.eval_indicator_alignment_coverage(),
                "zero_report_exclusion": self.eval_zero_report_exclusion(),
            },
            "stage_5_crosscheck": {
                "evidence_asymmetry_abstention": self.eval_evidence_asymmetry_abstention(),
                "self_verification_exclusion": self.eval_self_verification_exclusion(),
            },
        }


if __name__ == "__main__":
    print(json.dumps(PipelineEvaluator().run_all(), indent=2, ensure_ascii=False))
