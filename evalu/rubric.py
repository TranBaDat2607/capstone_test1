"""
The expert-evaluation layer (Khung Đánh Giá Graph-RAG §3 and §4 step 4).

This module holds the *instrument* — the 4-dimension / 5-point Likert rubric,
the three expert panels, a blank annotation sheet generator, and the consensus
pipeline. It holds NO scores: none have been collected yet.

That separation is the point. The rubric can be reviewed, versioned and shipped
with the thesis before a single expert sits down, and `consensus()` can be
proven correct on synthetic ballots (test/test_evalu_rubric.py) rather than
debugged live during an annotation session.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from evalu.iaa import agreement_report

LIKERT_MIN, LIKERT_MAX = 1, 5

# --------------------------------------------------------------------------- #
# §3 — the three expert panels
# --------------------------------------------------------------------------- #
PANELS: Dict[str, Dict[str, Any]] = {
    "ceo": {
        "label": "Tổng Giám đốc (CEO / C-Suite)",
        "focus": "Chiến lược: rủi ro uy tín, rủi ro pháp lý, giá trị hỗ trợ ra quyết định",
        "weight_on": ["decision_utility"],
    },
    "hrd": {
        "label": "Giám đốc Nhân sự (HRD)",
        "focus": "Trụ cột S và một phần G: an toàn lao động, bình đẳng giới, đào tạo, an sinh",
        "weight_on": ["decision_utility"],
    },
    "esg_audit": {
        "label": "Chuyên gia Kiểm toán & ESG",
        "focus": "Kỹ thuật pháp lý: ánh xạ TT96/GRI, provenance cấp trang/câu, logic đối soát",
        "weight_on": ["grounding", "adjudication", "provenance"],
    },
}

# --------------------------------------------------------------------------- #
# §3 — the 4 rubric dimensions, anchored at levels 1 / 3 / 5
# --------------------------------------------------------------------------- #
@dataclass
class Dimension:
    key: str
    name_vi: str
    name_en: str
    anchor_1: str
    anchor_3: str
    anchor_5: str


DIMENSIONS: List[Dimension] = [
    Dimension(
        key="grounding",
        name_vi="Độ chính xác Căn cứ",
        name_en="Fact-Checking Precision & Grounding",
        anchor_1="Tuyên bố/bằng chứng bị suy diễn sai lệch hoàn toàn so với văn bản gốc; "
                 "xuất hiện ảo giác (hallucination).",
        anchor_3="Trích xuất đúng nội dung chính nhưng sót ngữ cảnh điều kiện hoặc "
                 "làm tròn con số sai lệch nhẹ.",
        anchor_5="Chính xác tuyệt đối từng con số, đơn vị tính, mốc thời gian và "
                 "ngữ cảnh điều kiện từ tài liệu gốc.",
    ),
    Dimension(
        key="adjudication",
        name_vi="Chất lượng Đối soát Chéo",
        name_en="Adjudication Quality",
        anchor_1="Đánh giá tư vấn sai bối cảnh (ví dụ gán appears_supported cho hai "
                 "thông tin mâu thuẫn).",
        anchor_3="Phân loại đúng hướng nhưng giải thích còn chung chung, thiếu chiều "
                 "sâu lập luận.",
        anchor_5="Lập luận sắc bén, chỉ rõ khoảng cách giữa Tuyên bố (T3) và Hành vi "
                 "(T2), phân biệt rõ dữ liệu lịch sử và mục tiêu.",
    ),
    Dimension(
        key="provenance",
        name_vi="Minh bạch Nguồn gốc",
        name_en="Provenance Transparency",
        anchor_1="Không thể truy xuất trích dẫn; link nguồn hỏng hoặc trỏ sai tài liệu/trang.",
        anchor_3="Trỏ đúng tài liệu nhưng lệch toạ độ trang hoặc đoạn văn.",
        anchor_5="Chính xác tuyệt đối tên tài liệu, số trang, số câu và URL gốc.",
    ),
    Dimension(
        key="decision_utility",
        name_vi="Giá trị Hỗ trợ Ra Quyết định",
        name_en="Decision Utility",
        anchor_1="Hồ sơ gây nhiễu, khiến người quản lý tốn thêm thời gian đọc lại tài liệu thô.",
        anchor_3="Tổng hợp thông tin cơ bản, rút ngắn 30-50% thời gian đọc hiểu nhưng "
                 "vẫn cần kiểm tra thủ công.",
        anchor_5="Hồ sơ sắc nét, làm nổi bật ngay các điểm mâu thuẫn cốt lõi; rút ngắn "
                 "đáng kể thời gian thẩm định.",
    ),
]

DIMENSION_KEYS = [d.key for d in DIMENSIONS]

# §4 step 4 — the adjudication panel weights disagreement resolution by expertise
PANEL_WEIGHTS: Dict[str, Dict[str, float]] = {
    "grounding": {"esg_audit": 2.0, "ceo": 1.0, "hrd": 1.0},
    "adjudication": {"esg_audit": 2.0, "ceo": 1.0, "hrd": 1.0},
    "provenance": {"esg_audit": 2.0, "ceo": 1.0, "hrd": 1.0},
    "decision_utility": {"esg_audit": 1.0, "ceo": 2.0, "hrd": 2.0},
}

DISAGREEMENT_SPREAD = 2      # §4 step 3: a Likert gap of >= 2 goes to the panel


@dataclass
class Ballot:
    """One expert's scores for one dossier."""
    claim_id: str
    rater_id: str
    panel: str
    scores: Dict[str, Optional[int]] = field(default_factory=dict)
    assessment_agrees: Optional[bool] = None
    note: str = ""


def blank_sheet(claim_ids: Sequence[str], rater_id: str, panel: str) -> Dict[str, Any]:
    """A ready-to-fill annotation sheet — the artifact an expert receives."""
    if panel not in PANELS:
        raise ValueError(f"unknown panel {panel!r}; expected one of {sorted(PANELS)}")
    return {
        "schema": "evalu.rubric/v1",
        "rater_id": rater_id,
        "panel": panel,
        "panel_label": PANELS[panel]["label"],
        "scale": {"min": LIKERT_MIN, "max": LIKERT_MAX},
        "dimensions": [asdict(d) for d in DIMENSIONS],
        "instructions": (
            "Chấm độc lập, KHÔNG thảo luận trước với chuyên gia khác (§4 bước 1 — "
            "tránh authority bias). Để trống (null) nếu bạn không đủ căn cứ cho một "
            "khía cạnh; ô trống được xử lý đúng cách bởi Krippendorff's alpha."
        ),
        "ballots": [
            {"claim_id": cid, "rater_id": rater_id, "panel": panel,
             "scores": {k: None for k in DIMENSION_KEYS},
             "assessment_agrees": None, "note": ""}
            for cid in claim_ids
        ],
    }


def _ballots_from(obj: Any) -> List[Ballot]:
    raw = obj.get("ballots", obj) if isinstance(obj, dict) else obj
    out = []
    for b in raw:
        out.append(Ballot(
            claim_id=b["claim_id"], rater_id=b["rater_id"], panel=b.get("panel", ""),
            scores={k: b.get("scores", {}).get(k) for k in DIMENSION_KEYS},
            assessment_agrees=b.get("assessment_agrees"), note=b.get("note", ""),
        ))
    return out


def load_ballots(paths: Sequence[Path]) -> List[Ballot]:
    ballots: List[Ballot] = []
    for p in paths:
        ballots.extend(_ballots_from(json.loads(Path(p).read_text(encoding="utf-8"))))
    return ballots


def reliability_matrix(ballots: Sequence[Ballot], dimension: str
                       ) -> tuple[List[List[Optional[int]]], List[str]]:
    """units x raters matrix for one rubric dimension, gaps preserved as None."""
    raters = sorted({b.rater_id for b in ballots})
    units = sorted({b.claim_id for b in ballots})
    index = {(b.claim_id, b.rater_id): b.scores.get(dimension) for b in ballots}
    matrix = [[index.get((u, r)) for r in raters] for u in units]
    return matrix, raters


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> Optional[float]:
    """
    §4 step 4's weighted median. Ties resolve to the midpoint of the two
    straddling values, which keeps the result inside the observed range.
    """
    pairs = sorted((v, w) for v, w in zip(values, weights) if v is not None and w > 0)
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    running = 0.0
    for i, (v, w) in enumerate(pairs):
        running += w
        if running > total / 2:
            return float(v)
        if running == total / 2:
            nxt = pairs[i + 1][0] if i + 1 < len(pairs) else v
            return (v + nxt) / 2.0
    return float(pairs[-1][0])


def consensus(ballots: Sequence[Ballot]) -> Dict[str, Any]:
    """
    §4 steps 2-4: agreement coefficients per dimension, the disagreement queue,
    and a weighted-median consensus score per claim.
    """
    per_dimension: Dict[str, Any] = {}
    for dim in DIMENSION_KEYS:
        matrix, raters = reliability_matrix(ballots, dim)
        rated = [row for row in matrix if sum(1 for v in row if v is not None) >= 2]
        per_dimension[dim] = {
            "raters": raters,
            "units_scored": len(rated),
            "agreement": agreement_report(rated, ordinal=True) if rated else None,
        }

    by_claim: Dict[str, List[Ballot]] = {}
    for b in ballots:
        by_claim.setdefault(b.claim_id, []).append(b)

    consensus_scores: Dict[str, Dict[str, Any]] = {}
    review_queue: List[Dict[str, Any]] = []
    for cid, group in sorted(by_claim.items()):
        row: Dict[str, Any] = {}
        for dim in DIMENSION_KEYS:
            vals, wts = [], []
            for b in group:
                v = b.scores.get(dim)
                if v is None:
                    continue
                vals.append(v)
                wts.append(PANEL_WEIGHTS.get(dim, {}).get(b.panel, 1.0))
            row[dim] = weighted_median(vals, wts)
            if len(vals) >= 2 and (max(vals) - min(vals)) >= DISAGREEMENT_SPREAD:
                review_queue.append({
                    "claim_id": cid, "dimension": dim,
                    "spread": max(vals) - min(vals),
                    "scores": {b.rater_id: b.scores.get(dim) for b in group},
                    "reason": "likert_spread",
                })
        verdicts = {b.assessment_agrees for b in group if b.assessment_agrees is not None}
        if len(verdicts) > 1:
            review_queue.append({"claim_id": cid, "dimension": "assessment",
                                 "reason": "verdict_conflict",
                                 "scores": {b.rater_id: b.assessment_agrees
                                            for b in group}})
        present = [v for v in row.values() if v is not None]
        row["overall"] = statistics.fmean(present) if present else None
        consensus_scores[cid] = row

    return {
        "n_ballots": len(ballots),
        "n_claims": len(by_claim),
        "n_raters": len({b.rater_id for b in ballots}),
        "per_dimension": per_dimension,
        "consensus_scores": consensus_scores,
        "review_queue": review_queue,
        "review_queue_size": len(review_queue),
    }


def rubric_spec() -> Dict[str, Any]:
    """The instrument itself, for the report and the thesis appendix."""
    return {
        "schema": "evalu.rubric/v1",
        "scale": {"min": LIKERT_MIN, "max": LIKERT_MAX,
                  "anchors": {1: "Unacceptable", 3: "Acceptable / Moderate",
                              5: "Excellent / Production-Ready"}},
        "panels": PANELS,
        "dimensions": [asdict(d) for d in DIMENSIONS],
        "panel_weights": PANEL_WEIGHTS,
        "disagreement_spread": DISAGREEMENT_SPREAD,
        "iaa": {
            "headline": "gwet_ac2",
            "why": ("Phân bố nhãn lệch mạnh về unverified_insufficient_evidence khiến "
                    "chance-agreement của Kappa tiệm cận 1 và hệ số sụp về 0 "
                    "(prevalence paradox). Gwet neo chance theo prevalence nên bền vững."),
            "threshold": 0.61,
            "threshold_source": "Landis & Koch — substantial agreement",
        },
    }
