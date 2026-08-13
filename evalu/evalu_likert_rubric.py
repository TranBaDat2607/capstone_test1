#!/usr/bin/env python3
"""
evalu_likert_rubric.py — 5-Point Likert Expert Rubric Evaluator

Defines the Likert 5-Point Rubric dimensions from evalu.docx:
1. Fact-Checking Precision & Grounding (Độ chính xác Căn cứ)
2. Adjudication Quality (Chất lượng Đối soát Chéo)
3. Provenance Transparency (Minh bạch Nguồn gốc)
4. Decision Utility (Giá trị Hỗ trợ Ra Quyết định)

Provides evaluation data structures, rubric criteria definitions, and automated scoring handlers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


RUBRIC_SPEC = {
    "dimensions": [
        {
            "id": "grounding_precision",
            "name": "1. Độ chính xác Căn cứ (Fact-Checking Precision & Grounding)",
            "levels": {
                1: "Unacceptable: Tuyên bố hoặc bằng chứng bị suy diễn sai lệch hoàn toàn so với văn bản gốc; xuất hiện ảo giác (hallucination).",
                3: "Acceptable: Thông tin trích xuất đúng nội dung chính nhưng bị sót ngữ cảnh điều kiện hoặc làm tròn con số sai lệch nhẹ.",
                5: "Excellent: Trích xuất chính xác tuyệt đối từng con số, đơn vị tính, mốc thời gian và ngữ cảnh điều kiện từ tài liệu gốc."
            }
        },
        {
            "id": "adjudication_quality",
            "name": "2. Chất lượng Đối soát Chéo (Adjudication Quality)",
            "levels": {
                1: "Unacceptable: Đánh giá tư vấn sai bối cảnh (ví dụ: gán nhãn appears_supported cho hai thông tin mâu thuẫn).",
                3: "Acceptable: Phân loại tư vấn đúng hướng nhưng phần giải thích bằng ngôn ngữ tự nhiên còn chung chung, thiếu chiều sâu.",
                5: "Excellent: Lập luận đối soát sắc bén, chỉ rõ khoảng cách gap giữa Claim và Conduct, phân biệt rõ dữ liệu lịch sử và mục tiêu."
            }
        },
        {
            "id": "provenance_transparency",
            "name": "3. Minh bạch Nguồn gốc (Provenance Transparency)",
            "levels": {
                1: "Unacceptable: Không thể truy xuất trích dẫn; link nguồn hỏng hoặc chỉ tới sai tài liệu/trang.",
                3: "Acceptable: Chỉ tới đúng tài liệu nhưng tọa độ trang hoặc đoạn văn bị lệch (lệch 1-2 trang).",
                5: "Excellent: Cung cấp chính xác tuyệt đối tên tài liệu, số trang, số câu và URL gốc; giao diện hiển thị trực quan 3 cột."
            }
        },
        {
            "id": "decision_utility",
            "name": "4. Giá trị Hỗ trợ Ra Quyết định (Decision Utility)",
            "levels": {
                1: "Unacceptable: Hồ sơ bằng chứng gây nhiễu, khiến người quản lý tốn thêm thời gian đọc lại toàn bộ tài liệu thô.",
                3: "Acceptable: Giúp tổng hợp thông tin cơ bản, rút ngắn 30-50% thời gian đọc hiểu nhưng vẫn cần kiểm tra lại thủ công.",
                5: "Excellent: Tổng hợp hồ sơ sắc nét, làm nổi bật ngay các điểm mâu thuẫn cốt lõi; rút ngắn >70% thời gian thẩm định."
            }
        }
    ]
}


class LikertRubricEvaluator:
    """Manages expert annotation rubrics and aggregates Likert 5-point scores."""

    def __init__(self, spec: Dict[str, Any] = RUBRIC_SPEC):
        self.spec = spec

    def aggregate_expert_scores(self, annotations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregates Likert scores across expert raters for all 4 dimensions."""
        dim_scores: Dict[str, List[int]] = {dim["id"]: [] for dim in self.spec["dimensions"]}

        for ann in annotations:
            ratings = ann.get("ratings", {})
            for dim_id in dim_scores:
                if dim_id in ratings:
                    val = ratings[dim_id]
                    if isinstance(val, int) and 1 <= val <= 5:
                        dim_scores[dim_id].append(val)

        summary = {}
        overall_scores = []
        for dim_id, scores in dim_scores.items():
            if scores:
                avg = sum(scores) / len(scores)
                overall_scores.extend(scores)
                summary[dim_id] = {
                    "average": round(avg, 2),
                    "min": min(scores),
                    "max": max(scores),
                    "ratings_count": len(scores)
                }
            else:
                summary[dim_id] = {"average": 0.0, "ratings_count": 0}

        overall_avg = sum(overall_scores) / len(overall_scores) if overall_scores else 0.0
        return {
            "overall_likert_average": round(overall_avg, 2),
            "dimensions_summary": summary,
            "total_expert_annotations": len(annotations)
        }

    def generate_rubric_template(self) -> Dict[str, Any]:
        """Generates a blank annotation template for experts."""
        return {
            "annotator_id": "EXPERT_ID_HERE",
            "annotator_role": "auditor|esg_specialist|ceo|hrd",
            "dossier_id": "DOSSIER_ID_HERE",
            "ratings": {
                "grounding_precision": 5,
                "adjudication_quality": 5,
                "provenance_transparency": 5,
                "decision_utility": 5
            },
            "comments": "Optional feedback on adjudication quality"
        }


if __name__ == "__main__":
    evaluator = LikertRubricEvaluator()
    sample_annotations = [
        {"annotator_role": "auditor", "ratings": {"grounding_precision": 5, "adjudication_quality": 4, "provenance_transparency": 5, "decision_utility": 5}},
        {"annotator_role": "esg_specialist", "ratings": {"grounding_precision": 4, "adjudication_quality": 5, "provenance_transparency": 4, "decision_utility": 4}},
        {"annotator_role": "ceo", "ratings": {"grounding_precision": 4, "adjudication_quality": 3, "provenance_transparency": 5, "decision_utility": 4}}
    ]

    res = evaluator.aggregate_expert_scores(sample_annotations)
    print(json.dumps(res, indent=2, ensure_ascii=False))
