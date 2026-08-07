"""
The 11 label-free component metrics of "Khung Đánh Giá Graph-RAG" §2.

Every function is a pure read: it takes already-loaded artifacts and returns a
MetricResult. Nothing here opens a file, calls an LLM, or touches Neo4j, so the
whole module is testable offline and can never perturb what it measures.

    module 1  ingestion & ESG classification
        M1.1  esg_signal_to_noise
        M1.2  provenance_rate
    module 2  triplet & KPI extraction
        M2.1  temporal_metadata_completeness
        M2.2  schema_compliance_rate
        M2.3  value_preservation_guard
    module 3  entity resolution
        M3.1  timeless_identity_violation_rate
        M3.2  cluster_conciseness
    module 4  indicator axis
        M4.1  indicator_alignment_coverage
        M4.2  zero_report_self_praise_exclusion
    module 5  cross-check
        M5.1  abstention_rate
        M5.2  self_verification_exclusion_rate

The T1/T2/T3 tier map and the P1 temporal-field list are IMPORTED from
esg_kg.report.quality, never re-declared here — a second copy would drift from
the schema lint the pipeline itself runs.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.core.naming import normalize_name          # noqa: E402
from esg_kg.report.quality import (                    # noqa: E402
    T1_CLASSES,
    T2_CLASSES,
    T3_CLASSES,
    TEMPORAL_IDENTITY_FIELDS,
)

from evalu.lexicon import LexiconMatcher               # noqa: E402
from evalu.model import MetricResult, ratio            # noqa: E402

# Properties an LLM repair pass may never rewrite (M2.3). Shape may be fixed;
# the measured quantity may not.
#
# `value_normalized` / `unit_normalized` are deliberately NOT here. They are
# OUTPUTS of the later canonicalize stage (step03c), which mints them from
# scratch by design. The before/after window this guard compares spans that
# stage, so protecting them made documented enrichment look like tampering:
# 3,521 of 5,096 "violations" in the first live run were canonicalize writing
# unit_normalized onto a node that legitimately had none.
PROTECTED_VALUE_FIELDS = ("value", "unit", "amount", "quantity", "target_value")

ALIGNABLE_CLASSES = {"SustainabilityClaim", "Goal", "Initiative"}

# The indicator-axis edges step05c mints. These are what make a node retrievable
# as conduct evidence on the TT96/GRI axis (M4.2) — unlike the structural edges
# step02 emits, which merely record that a disclosure was made.
CONDUCT_AXIS_EDGES = {"measuredUnder", "alignsWithIndicator"}
ABSTENTION_LABEL = "unverified_insufficient_evidence"
TIME_BEARING_CLASSES = T2_CLASSES | T3_CLASSES


# --------------------------------------------------------------------------- #
# module 1 — ingestion & ESG classification
# --------------------------------------------------------------------------- #
PROVENANCE_KEYS = ("source_pdf", "page", "sentence_index")


def _provenance_gaps(rec: Dict[str, Any]) -> List[str]:
    """Missing coordinates. `page=0` is a real coordinate, so test for None."""
    return [k for k in PROVENANCE_KEYS if rec.get(k) is None]


def _make_matcher(lexicon) -> LexiconMatcher:
    return lexicon if isinstance(lexicon, LexiconMatcher) else LexiconMatcher(lexicon)


def _snr_result(grounded: int, total: int, terms: int) -> MetricResult:
    return MetricResult(
        metric_id="M1.1",
        module="1. Thu thập & Phân loại ESG",
        name="ESG Signal-to-Noise Ratio",
        value=ratio(grounded, total),
        numerator=grounded,
        denominator=total,
        target="cao hơn = ít câu tiếp thị chung chung lọt qua bộ phân loại",
        purpose=("Bộ phân loại ViDeBERTa gán esg=true theo ngữ nghĩa câu, nên văn "
                 "tiếp thị rỗng ('hướng tới phát triển bền vững', 'tầm nhìn trở "
                 "thành doanh nghiệp hàng đầu') vẫn lọt qua. Chỉ số này đo phần "
                 "câu đã lọt qua mà còn neo được vào một cụm từ trong từ vựng "
                 "KPI/GRI có kiểm soát — tức phần thực sự dùng được cho các khâu sau."),
        how_to_read=("Thấp = nhiều câu vào pipeline nhưng không mang nội dung ESG "
                     "đo được, làm loãng đầu vào của khâu trích xuất KPI. Không có "
                     "ngưỡng chuẩn; dùng để so sánh giữa các lần chạy hoặc giữa hai "
                     "nguồn (báo cáo vs tin tức)."),
        limitation=("KHÔNG phải độ chính xác của bộ phân loại. Giá trị phụ thuộc "
                    "mạnh vào cách dựng từ vựng: đổi cách dựng làm con số nhảy từ "
                    "4% lên 50%. Đây là chỉ số yếu nhất trong bộ, không nên trích "
                    "dẫn như một kết quả độc lập."),
        details={"lexicon_terms": terms},
    )


def _provenance_result(intact: int, total: int, missing: Counter) -> MetricResult:
    return MetricResult(
        metric_id="M1.2",
        module="1. Thu thập & Phân loại ESG",
        name="Paragraph Source Provenance Rate",
        value=ratio(intact, total),
        numerator=intact,
        denominator=total,
        target="100%",
        passed=(total > 0 and intact == total),
        purpose=("Mỗi câu phải giữ nguyên toạ độ nguồn (source_pdf, page, "
                 "sentence_index) qua toàn bộ pipeline. Đây là điều kiện để mọi "
                 "node trong đồ thị truy ngược được về đúng trang, đúng câu trong "
                 "báo cáo gốc — nền tảng của toàn bộ tính minh bạch mà hệ thống "
                 "hứa hẹn với kiểm toán viên."),
        how_to_read=("Phải đạt 100%. Dưới 100% nghĩa là có tuyên bố hiển thị trên "
                     "giao diện mà không dẫn được về nguồn, tức mất khả năng kiểm chứng."),
        limitation=("Gần như tất yếu đạt 100% vì pipeline chỉ sao chép cơ học ba "
                    "trường này. Giá trị của nó là làm lưới chắn hồi quy, không "
                    "phải là bằng chứng chất lượng."),
        details={"missing_by_field": dict(missing)},
    )


def esg_signal_to_noise(records: Iterable[Dict[str, Any]], lexicon) -> MetricResult:
    """M1.1 — of the sentences the classifier accepted, how many are grounded."""
    matcher = _make_matcher(lexicon)
    total = grounded = 0
    for rec in records:
        if not rec.get("esg"):
            continue
        total += 1
        if matcher.matches(rec.get("text", "")):
            grounded += 1
    return _snr_result(grounded, total, matcher.size)


def provenance_rate(records: Iterable[Dict[str, Any]]) -> MetricResult:
    """M1.2 — every sentence keeps (source_pdf, page, sentence_index)."""
    total = intact = 0
    missing_by_field: Counter = Counter()
    for rec in records:
        total += 1
        gaps = _provenance_gaps(rec)
        if gaps:
            missing_by_field.update(gaps)
        else:
            intact += 1
    return _provenance_result(intact, total, missing_by_field)


def ingestion_metrics(records: Iterable[Dict[str, Any]], lexicon):
    """
    M1.1 + M1.2 in ONE pass over the record stream.

    The labelled corpus is ~380 MB / 874k sentences, so it is streamed and can
    be walked only once. The per-record predicates are shared with the two
    single-metric functions above, so this is a different traversal of the same
    logic, not a second copy of it.
    """
    matcher = _make_matcher(lexicon)
    esg_total = grounded = 0
    prov_total = prov_intact = 0
    missing_by_field: Counter = Counter()

    for rec in records:
        prov_total += 1
        gaps = _provenance_gaps(rec)
        if gaps:
            missing_by_field.update(gaps)
        else:
            prov_intact += 1

        if rec.get("esg"):
            esg_total += 1
            if matcher.matches(rec.get("text", "")):
                grounded += 1

    return (_snr_result(grounded, esg_total, matcher.size),
            _provenance_result(prov_intact, prov_total, missing_by_field))


# --------------------------------------------------------------------------- #
# module 2 — triplet & KPI extraction
# --------------------------------------------------------------------------- #
def temporal_metadata_completeness(graph: Dict[str, Any]) -> MetricResult:
    """
    M2.1 — edges carry the full (valid_from, valid_to, recorded_at) triple and
    T2/T3 nodes carry valid_from.

    Two deliberate rules:
      * `valid_to = None` means an OPEN interval, not a gap — presence of the key
        is what is checked, not truthiness. Penalising open intervals would push
        the pipeline to invent end dates.
      * T1 entity nodes are skipped entirely (P2: identity is timeless, history
        lives on edges and in temporal_versions).
    """
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    e_total = e_ok = 0
    gap_by_predicate: Counter = Counter()
    for e in edges:
        e_total += 1
        tm = e.get("temporal_metadata") or {}
        if all(k in tm for k in ("valid_from", "valid_to", "recorded_at")) \
                and tm.get("valid_from") is not None:
            e_ok += 1
        else:
            gap_by_predicate[e.get("predicate")] += 1

    n_total = n_ok = 0
    gap_by_class: Counter = Counter()
    for n in nodes:
        if n.get("class") not in TIME_BEARING_CLASSES:
            continue
        n_total += 1
        if (n.get("properties") or {}).get("valid_from") is not None:
            n_ok += 1
        else:
            gap_by_class[n.get("class")] += 1

    total = e_total + n_total
    ok = e_ok + n_ok
    return MetricResult(
        metric_id="M2.1",
        module="2. Trích xuất Triplet & KPI",
        name="Temporal Metadata Completeness",
        value=ratio(ok, total),
        numerator=ok,
        denominator=total,
        target="100%",
        passed=(total > 0 and ok == total),
        purpose=("Đo phần đồ thị thực sự tham gia được vào suy luận theo thời gian. "
                 "Một cạnh không có valid_from thì không trả lời được câu hỏi cốt lõi "
                 "của bài toán greenwashing: doanh nghiệp tuyên bố năm nào, hành vi "
                 "xảy ra năm nào, và khoảng cách giữa hai mốc đó là bao nhiêu."),
        how_to_read=("Phần hụt cho biết CHÍNH XÁC chỗ nào mất khả năng so sánh theo "
                     "thời gian — đọc `edge_gaps_by_predicate` và `node_gaps_by_class` "
                     "chứ đừng chỉ đọc con số tổng."),
        limitation=("Mẫu số lấy theo hợp đồng schema (mọi edge spec khai "
                    "temporal_properties, mọi lớp T2/T3 khai valid_from). Nếu một số "
                    "lớp cố ý để thời gian sống trên cạnh thay vì trên node thì phải "
                    "sửa schema, không phải sửa chỉ số."),
        details={"edges_total": e_total, "edges_complete": e_ok,
                 "nodes_total": n_total, "nodes_complete": n_ok,
                 "edge_gaps_by_predicate": dict(gap_by_predicate.most_common(15)),
                 "node_gaps_by_class": dict(gap_by_class.most_common(15)),
                 "note": ("Mẫu số lấy theo config/schema.json: mọi edge spec đều khai "
                          "temporal_properties và mọi lớp T2/T3 đều khai valid_from. "
                          "Phần hụt vì thế là sai lệch thật so với hợp đồng schema, "
                          "không phải giả định của phép đo.")},
    )


def schema_compliance_rate(graph: Dict[str, Any],
                           schema: Dict[str, Any]) -> MetricResult:
    """
    M2.2 — every edge's (predicate, source_class, target_class) is legal.

    An edge label may appear with SEVERAL legal class pairs; any match counts.
    """
    legal: Dict[str, Set[tuple]] = defaultdict(set)
    for spec in schema.get("edges", []):
        legal[spec.get("label")].add((spec.get("source_class"),
                                      spec.get("target_class")))

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    total = ok = 0
    violations: List[Dict[str, Any]] = []

    for i, e in enumerate(edges):
        total += 1
        pred = e.get("predicate")
        try:
            src = nodes[e["subject"]].get("class")
            dst = nodes[e["object"]].get("class")
        except (KeyError, IndexError, TypeError):
            violations.append({"edge_index": i, "predicate": pred,
                               "reason": "dangling_endpoint"})
            continue

        if pred not in legal:
            violations.append({"edge_index": i, "predicate": pred,
                               "source_class": src, "target_class": dst,
                               "reason": "unknown_predicate"})
        elif (src, dst) in legal[pred]:
            ok += 1
        else:
            violations.append({"edge_index": i, "predicate": pred,
                               "source_class": src, "target_class": dst,
                               "reason": "illegal_class_pair"})

    by_reason = Counter(v["reason"] for v in violations)
    return MetricResult(
        metric_id="M2.2",
        module="2. Trích xuất Triplet & KPI",
        name="Schema Compliance Rate",
        value=ratio(ok, total),
        numerator=ok,
        denominator=total,
        target="100% (0 vi phạm)",
        passed=(total > 0 and not violations),
        purpose=("Xác nhận mọi cạnh trong đồ thị là một bộ ba (predicate, lớp nguồn, "
                 "lớp đích) hợp lệ theo config/schema.json. Cạnh sai kiểu sẽ làm hỏng "
                 "mọi truy vấn Cypher viết theo schema, và làm khâu đối soát bỏ sót "
                 "hoặc lấy nhầm bằng chứng."),
        how_to_read="Phải là 100%. Bất kỳ vi phạm nào cũng là lỗi cần sửa ngay.",
        limitation=("GẦN NHƯ TẤT YẾU đạt 100%: fix_triples cưỡng chế schema và đẩy "
                    "cái không sửa được sang unfixable_triples.json. Đo độ tuân thủ "
                    "trên đầu ra của chính bộ validator thì không nói lên chất lượng. "
                    "Con số đáng báo cáo kèm là TỶ LỆ BỊ LOẠI (số bộ ba trong "
                    "unfixable_triples.json), hiện chưa được đưa vào báo cáo này."),
        details={"violations": violations[:200],
                 "violations_total": len(violations),
                 "by_reason": dict(by_reason)},
    )


def _value_key(v: Any) -> Any:
    """10 and 10.0 are the same measurement; "10" and 10 are not."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def value_preservation_guard(before: Sequence[Dict[str, Any]],
                             after: Sequence[Dict[str, Any]],
                             fields: Sequence[str] = PROTECTED_VALUE_FIELDS
                             ) -> MetricResult:
    """
    M2.3 — the LLM repair pass may fix a triple's SHAPE but never its numbers.

    Three failure modes are distinguished, because they have different causes:
      changed   a value or unit was rewritten (e.g. "tấn" -> "tons")
      dropped   a protected field present before is gone after
      invented  a protected field absent before appears after
    """
    after_by_id = {rec.get("id"): (rec.get("properties") or {}) for rec in after}

    total = ok = 0
    guarded_fields_seen = 0
    violations: List[Dict[str, Any]] = []
    for rec in before:
        rid = rec.get("id")
        props_before = rec.get("properties") or {}
        props_after = after_by_id.get(rid)
        if props_after is None:
            continue                       # not repaired at all -> nothing to check

        # Non-vacuity: a node with no protected field on EITHER side has nothing
        # to preserve. Counting it as a pass would let an entity-heavy graph
        # report 100% without a single number ever being checked.
        watched = [f for f in fields if f in props_before or f in props_after]
        if not watched:
            continue
        guarded_fields_seen += len(watched)

        total += 1
        local: List[Dict[str, Any]] = []
        for f in fields:
            b_has, a_has = f in props_before, f in props_after
            if b_has and a_has:
                if _value_key(props_before[f]) != _value_key(props_after[f]):
                    local.append({"id": rid, "field": f, "reason": "changed",
                                  "before": props_before[f], "after": props_after[f]})
            elif b_has and not a_has:
                local.append({"id": rid, "field": f, "reason": "dropped",
                              "before": props_before[f], "after": None})
            elif a_has and not b_has:
                local.append({"id": rid, "field": f, "reason": "invented",
                              "before": None, "after": props_after[f]})
        if local:
            violations.extend(local)
        else:
            ok += 1

    return MetricResult(
        metric_id="M2.3",
        module="2. Trích xuất Triplet & KPI",
        name="Value Preservation Guard",
        value=ratio(ok, total),
        numerator=ok,
        denominator=total,
        target="100% (LLM không được sửa giá trị/đơn vị)",
        passed=(total > 0 and not violations),
        purpose=("Khâu sửa lỗi ở step03 dùng LLM để chữa HÌNH DẠNG của bộ ba (sai lớp, "
                 "sai chiều cạnh, sai định dạng ngày). Nó tuyệt đối không được đụng vào "
                 "GIÁ TRỊ ĐO. Một mô hình được nhắc bằng tiếng Anh rất dễ 'sửa' 'tấn' "
                 "thành 'tons' hoặc làm tròn một con số — và sai lệch đó sẽ đi thẳng vào "
                 "hồ sơ đối soát mà không ai thấy. Chỉ số này so sánh từng trường giá trị "
                 "trước và sau khi sửa."),
        how_to_read=("Bất kỳ giá trị nào dưới 100% đều là lỗi nghiêm trọng: hệ thống đang "
                     "báo cáo con số mà doanh nghiệp không hề công bố. Đọc kèm "
                     "`guarded_fields_seen` để biết có bao nhiêu trường thực sự được đối "
                     "chiếu — 100% trên mẫu số rỗng thì vô nghĩa."),
        limitation=("Chỉ so được các node ghép được stable_id ở cả hai phía; số node lệch "
                    "được báo riêng ở `match_stats` thay vì bỏ qua âm thầm."),
        details={"violations": violations[:200],
                 "violations_total": len(violations),
                 "guarded_fields_seen": guarded_fields_seen,
                 "guarded_field_names": list(fields),
                 "by_reason": dict(Counter(v["reason"] for v in violations))},
    )


# --------------------------------------------------------------------------- #
# module 3 — entity resolution
# --------------------------------------------------------------------------- #
def timeless_identity_violation_rate(schema: Dict[str, Any]) -> MetricResult:
    """
    M3.1 — P1: no T1 class may carry a time field in identity_keys.

    T2 observation classes legitimately key on time (one KPIObservation per
    year), so they are out of scope rather than exempt-by-exception.
    """
    violations: List[Dict[str, Any]] = []
    t1_seen = 0
    for spec in schema.get("nodes", []):
        cls = spec.get("class")
        if cls not in T1_CLASSES:
            continue
        t1_seen += 1
        bad = sorted(set(spec.get("identity_keys") or []) & TEMPORAL_IDENTITY_FIELDS)
        if bad:
            violations.append({"class": cls, "fields": bad})

    return MetricResult(
        metric_id="M3.1",
        module="3. Phân giải Thực thể",
        name="Timeless Identity Violation Rate",
        value=ratio(len(violations), t1_seen),
        numerator=len(violations),
        denominator=t1_seen,
        target="0 vi phạm",
        passed=(not violations),
        higher_is_better=False,
        purpose=("Nguyên tắc P1: danh tính của thực thể T1 (Doanh nghiệp, Nhà máy, "
                 "Người...) phải VĨNH CỬU. Nếu identity_keys chứa trường thời gian, "
                 "cùng một công ty sẽ bị tách thành nhiều thực thể khác nhau theo từng "
                 "năm — lịch sử vỡ vụn, và mọi so sánh nhiều năm trở nên vô nghĩa."),
        how_to_read="Phải bằng 0. Một vi phạm cũng đủ làm hỏng phân giải thực thể.",
        limitation=("Đây là lint trên một file config viết tay, tức một unit test chứ "
                    "không phải phép đánh giá hệ thống. Giá trị 0 là kỳ vọng mặc định, "
                    "không phải thành tích. test/test_schema_contract.py đã kiểm điều này."),
        details={"violations": violations, "t1_classes_checked": t1_seen},
    )


def cluster_conciseness(graph: Dict[str, Any]) -> MetricResult:
    """
    M3.2 — residual duplicate rate among T1 entities after Stage A/B/C/D.

    Two nodes of the SAME class whose names normalise to one signature are
    counted as an unmerged pair. Cross-class collisions are ignored on purpose:
    a Facility and an Organization may legitimately share a name.

    This is a lower bound on under-merging, not a verdict — normalize_name is
    the pipeline's own key, so anything it cannot tell apart is something the
    resolver had every opportunity to merge and did not.
    """
    buckets: Dict[tuple, List[int]] = defaultdict(list)
    t1_nodes = 0
    for i, n in enumerate(graph.get("nodes", [])):
        cls = n.get("class")
        if cls not in T1_CLASSES:
            continue
        t1_nodes += 1
        name = (n.get("properties") or {}).get("name")
        sig = normalize_name(name)
        if not sig:
            continue
        buckets[(cls, sig)].append(i)

    clusters = [{"class": cls, "signature": sig, "size": len(idx),
                 "node_indexes": idx[:20]}
                for (cls, sig), idx in buckets.items() if len(idx) > 1]
    clusters.sort(key=lambda c: -c["size"])
    residual = sum(c["size"] - 1 for c in clusters)

    return MetricResult(
        metric_id="M3.2",
        module="3. Phân giải Thực thể",
        name="Oversimplification & Cluster Conciseness",
        value=ratio(residual, t1_nodes),
        numerator=residual,
        denominator=t1_nodes,
        target="thấp hơn = ít thực thể trùng còn sót sau hợp nhất",
        higher_is_better=False,
        purpose=("Sau khi phân giải thực thể (Stage A/B/C/D), cùng một doanh nghiệp "
                 "không được còn tồn tại dưới nhiều node. Thực thể bị vỡ làm loãng "
                 "bằng chứng: tuyên bố treo vào node này, tin tức treo vào node kia, "
                 "và khâu đối soát không bao giờ nối được hai bên."),
        how_to_read=("Càng thấp càng tốt. Đọc `clusters` để thấy chính xác cặp nào "
                     "chưa gộp."),
        limitation=("QUAN TRỌNG — con số này là CẬN DƯỚI và dễ gây yên tâm sai. Nó dùng "
                    "chính normalize_name mà bộ phân giải dùng, nên chỉ thấy được thứ "
                    "resolver lẽ ra gộp được bằng khoá của chính nó. Nó MÙ với thất bại "
                    "thật: 'Công ty CP Nhựa An Phát' vs 'An Phát Holdings' sẽ không bị "
                    "phát hiện. Mức trùng lặp thật gần như chắc chắn cao hơn nhiều."),
        details={"t1_nodes": t1_nodes,
                 "residual_duplicates": residual,
                 "clusters": clusters[:50],
                 "clusters_total": len(clusters)},
    )


# --------------------------------------------------------------------------- #
# module 4 — indicator axis
# --------------------------------------------------------------------------- #
def indicator_alignment_coverage(graph: Dict[str, Any]) -> MetricResult:
    """M4.1 — share of Claim/Goal/Initiative nodes reaching a StandardIndicator."""
    nodes = graph.get("nodes", [])
    aligned: Set[int] = set()
    for e in graph.get("edges", []):
        if e.get("predicate") == "alignsWithIndicator":
            aligned.add(e.get("subject"))

    total = hit = 0
    by_class: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for i, n in enumerate(nodes):
        cls = n.get("class")
        if cls not in ALIGNABLE_CLASSES:
            continue
        total += 1
        by_class[cls][1] += 1
        if i in aligned:
            hit += 1
            by_class[cls][0] += 1

    return MetricResult(
        metric_id="M4.1",
        module="4. Ánh xạ Trục Chỉ tiêu",
        name="Standard Indicator Alignment Coverage",
        value=ratio(hit, total),
        numerator=hit,
        denominator=total,
        target="cao hơn = độ phủ TT96/GRI tốt hơn",
        purpose=("Chỉ những tuyên bố có cạnh alignsWithIndicator mới hiển thị được trên "
                 "giao diện ESG Evidence View, vì cột trụ cột E/S/G đọc trực tiếp từ "
                 "StandardIndicator.pillar. Chỉ số này đo phần tuyên bố thực sự vào được "
                 "trục chỉ tiêu TT96/GRI — phần còn lại vô hình với người dùng cuối."),
        how_to_read=("Thấp = nhiều tuyên bố nằm ngoài tầm nhìn của giao diện. Đọc "
                     "`by_class` để biết hụt ở Claim, Goal hay Initiative."),
        limitation=("CHỈ CÓ ĐỘ PHỦ, KHÔNG CÓ ĐỘ CHÍNH XÁC. Một bộ khớp ngu hơn, gán bừa "
                    "chỉ tiêu cho mọi tuyên bố, sẽ đạt 100%. Vì vậy 'cao hơn' KHÔNG "
                    "đương nhiên là 'tốt hơn'. Muốn dùng được con số này thì phải kiểm "
                    "tay một mẫu ~50 cạnh để có vế precision đi kèm."),
        details={"by_class": {k: {"aligned": v[0], "total": v[1]}
                              for k, v in sorted(by_class.items())}},
    )


def zero_report_self_praise_exclusion(graph: Dict[str, Any]) -> MetricResult:
    """
    M4.2 — a self-reported "fined 0 times" must be flagged and must NOT become
    conduct evidence.

    Denominator is Penalty nodes with amount == 0 only; a real fine is a
    different object entirely.

    "Conduct edge" means an INDICATOR-AXIS edge (step05c's `measuredUnder` /
    `alignsWithIndicator`) — the wiring that would let a self-congratulatory
    "fined 0 times" be retrieved as evidence of good conduct. The structural
    `Organization -subjectToPenalty-> Penalty` edge that step02 emits is NOT
    conduct: it only records that the company made the disclosure, and every
    zero-penalty legitimately has one.
    """
    nodes = graph.get("nodes", [])
    incident: Counter = Counter()
    for e in graph.get("edges", []):
        if e.get("predicate") not in CONDUCT_AXIS_EDGES:
            continue
        incident[e.get("subject")] += 1
        incident[e.get("object")] += 1

    total = ok = 0
    violations: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if n.get("class") != "Penalty":
            continue
        props = n.get("properties") or {}
        amount = props.get("amount")
        if amount is None or _value_key(amount) != 0.0:
            continue
        total += 1

        if not props.get("self_reported_zero"):
            violations.append({"node_index": i, "reason": "missing_self_reported_zero"})
        elif incident.get(i):
            violations.append({"node_index": i, "reason": "has_conduct_edge",
                               "degree": incident[i]})
        else:
            ok += 1

    return MetricResult(
        metric_id="M4.2",
        module="4. Ánh xạ Trục Chỉ tiêu",
        name="Zero-Report Self-Praise Exclusion",
        value=ratio(ok, total),
        numerator=ok,
        denominator=total,
        target="100%",
        passed=(total == 0 or not violations),
        purpose=("Trong báo cáo thường niên, câu 'Số lần bị xử phạt vi phạm: 0' là "
                 "doanh nghiệp TỰ KHAI, không phải bằng chứng độc lập. Nếu hệ thống "
                 "biến nó thành cạnh conduct trên trục chỉ tiêu, nó sẽ tự động khuếch "
                 "đại lời tự khen thành 'đã được xác minh' — đúng kiểu sai lầm mà một "
                 "công cụ chống greenwashing tuyệt đối không được mắc."),
        how_to_read=("Phải 100%. Mỗi Penalty amount=0 phải được gắn cờ "
                     "self_reported_zero VÀ không có cạnh measuredUnder/"
                     "alignsWithIndicator."),
        limitation=("Cỡ mẫu cực nhỏ (thường chỉ 1-2 node trong toàn đồ thị). Đây là "
                    "phép kiểm hồi quy, không phải một thống kê."),
        details={"violations": violations[:200],
                 "violations_total": len(violations),
                 "by_reason": dict(Counter(v["reason"] for v in violations))},
    )


# --------------------------------------------------------------------------- #
# module 5 — cross-check
# --------------------------------------------------------------------------- #
def abstention_rate(dossiers: Sequence[Dict[str, Any]]) -> MetricResult:
    """
    M5.1 — share of claims the system declined to judge.

    A HIGH value is not a defect: with thin independent news coverage, abstaining
    is the honest outcome. It is reported as a property of the evidence base, so
    higher_is_better is left deliberately False and no target is set.
    """
    by_assessment = Counter(d.get("assessment") for d in dossiers)
    total = len(dossiers)
    abstained = by_assessment.get(ABSTENTION_LABEL, 0)
    return MetricResult(
        metric_id="M5.1",
        module="5. Đối soát Chéo",
        name="Evidence Asymmetry & Abstention Rate",
        value=ratio(abstained, total),
        numerator=abstained,
        denominator=total,
        target="mô tả độ mỏng của kho bằng chứng — không phải chỉ tiêu cần tối ưu",
        higher_is_better=False,
        purpose=("Đo phần tuyên bố mà hệ thống TỪ CHỐI kết luận vì không đủ bằng chứng "
                 "độc lập. Trong một hệ hỗ trợ ra quyết định, biết im lặng đúng lúc là "
                 "một tính năng: thà không nói còn hơn quy kết sai cho một doanh nghiệp "
                 "có thật, nêu đích danh."),
        how_to_read=("Đây là thuộc tính của DỮ LIỆU, không phải của thuật toán. Cao "
                     "nghĩa là kho tin tức độc lập quá mỏng. Cách sửa là crawl thêm tin, "
                     "KHÔNG PHẢI nới lỏng ngưỡng phán quyết — nới ngưỡng chỉ đổi im lặng "
                     "trung thực lấy tiếng ồn."),
        limitation=("Đừng bao giờ trình bày như chỉ tiêu cần giảm. Một hệ thống dễ dãi "
                    "hơn sẽ có abstention thấp hơn mà chất lượng tệ hơn."),
        details={"by_assessment": {k: v for k, v in by_assessment.most_common()}},
    )


def self_verification_exclusion_rate(dossiers: Sequence[Dict[str, Any]]
                                     ) -> MetricResult:
    """
    M5.2 — share of would-be supporting evidence dropped for coming from the
    company's own domain.

    Denominator is (kept independent support + flagged own-domain support). With
    neither, the rate is undefined, not 0 — see MetricResult.value.
    """
    kept = flagged = 0
    domains: Counter = Counter()
    for d in dossiers:
        kept += len(d.get("supporting_evidence") or [])
        for item in (d.get("flagged_non_independent_support") or []):
            flagged += 1
            if isinstance(item, dict) and item.get("domain"):
                domains[item["domain"]] += 1

    return MetricResult(
        metric_id="M5.2",
        module="5. Đối soát Chéo",
        name="Self-Verification Exclusion Rate",
        value=ratio(flagged, kept + flagged),
        numerator=flagged,
        denominator=kept + flagged,
        target="bằng chứng xác nhận phải đến từ nguồn độc lập",
        higher_is_better=False,
        purpose=("Doanh nghiệp không được tự xác nhận mình. Nếu 'bằng chứng độc lập' "
                 "cho tuyên bố của AAA lại đến từ aaa.com.vn thì đó vẫn là báo cáo tự "
                 "công bố, chỉ đổi định dạng. Chỉ số này đo phần bằng chứng bị guard "
                 "loại vì đến từ domain của chính doanh nghiệp."),
        how_to_read=("Giá trị 0 có HAI cách hiểu trái ngược nhau: (a) không có bằng "
                     "chứng tự công bố nào lọt vào — tốt; hoặc (b) guard là code chết, "
                     "chưa từng chạy. Phải kiểm bằng cách khác mới phân biệt được."),
        limitation=("Trên dữ liệu hiện tại guard chưa kích hoạt lần nào, nên chỉ số này "
                    "KHÔNG chứng minh được là guard hoạt động. Nó chỉ ghi nhận rằng "
                    "chưa có tình huống nào cần đến nó."),
        details={"kept_independent": kept, "flagged_own_domain": flagged,
                 "top_domains": domains.most_common(10)},
    )


ALL_METRICS = [
    "esg_signal_to_noise", "provenance_rate",
    "temporal_metadata_completeness", "schema_compliance_rate",
    "value_preservation_guard",
    "timeless_identity_violation_rate", "cluster_conciseness",
    "indicator_alignment_coverage", "zero_report_self_praise_exclusion",
    "abstention_rate", "self_verification_exclusion_rate",
]
