"""
The prompt that turns retrieved candidates into an answer: does this news sentence match
a claim this company made in its annual report, and how?

The verdict vocabulary (supports / contradicts / irrelevant) is deliberately the same one
step07's crosscheck uses, so a result saved here can be lined up against the pipeline's
own dossiers later without a translation step.

Two properties the prompt is built around:

  * every candidate is printed with its `doc_id` ("AAA_2013.pdf#p15#s3"), and the model
    answers with those ids. That is what makes an answer citable back to a report page —
    and `parse_verdict` drops any id that was not in the candidate list, so a hallucinated
    citation cannot reach the saved results.
  * "irrelevant" is offered as a first-class answer and the prompt says so explicitly.
    Without it a model asked "which candidate matches?" will always pick one, and a
    retriever that returns nothing useful would score as if it had succeeded.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from .parsing import extract_json

RELATIONS = ("supports", "contradicts", "irrelevant")

SYSTEM = (
    "Bạn là trợ lý phân tích ESG cho doanh nghiệp niêm yết Việt Nam. Bạn đối chiếu một "
    "câu tin tức (hành vi thực tế) với các câu tuyên bố ESG trích từ báo cáo thường niên "
    "của chính công ty đó (điều họ nói). Bạn chỉ được dùng các ứng viên được cung cấp, "
    "không suy diễn thêm dữ kiện. Luôn trả lời bằng Câu claim  hợp lệ."
)


def build_verdict_prompt(query: str, candidates: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "Câu tin tức cần đối chiếu:",
        f"  {query}",
        "",
        "Các câu tuyên bố ESG ứng viên (trích từ báo cáo thường niên):",
    ]
    for candidate in candidates:
        meta = (f"{candidate.get('ticker')} · năm {candidate.get('year')} · "
                f"{candidate.get('source_pdf')} trang {candidate.get('page')}")
        lines.append(f"  - id={candidate.get('doc_id')} ({meta})")
        lines.append(f"    {candidate.get('text')}")
    lines += [
        "",
        "Nhiệm vụ:",
        "  1. Chọn các ứng viên thực sự nói về CÙNG nội dung ESG với câu tin tức.",
        "     Nếu không ứng viên nào phù hợp, để danh sách rỗng — đừng chọn bừa.",
        "  2. Xác định quan hệ giữa tin tức và các tuyên bố đã chọn:",
        "       supports     — tin tức xác nhận/củng cố tuyên bố",
        "       contradicts  — tin tức mâu thuẫn với tuyên bố",
        "       irrelevant   — không có ứng viên nào liên quan",
        "  3. Trích nguyên văn đoạn trong ứng viên làm bằng chứng.",
        "",
        "Chỉ trả về JSON đúng định dạng sau, không kèm giải thích ngoài JSON:",
        "  {",
        '    "matched_doc_ids": ["<id ứng viên>", ...],',
        '    "relation": "supports" | "contradicts" | "irrelevant",',
        '    "confidence": <số thực 0..1>,',
        '    "evidence": "<trích dẫn nguyên văn từ ứng viên>",',
        '    "reason": "<một hai câu giải thích bằng tiếng Việt>"',
        "  }",
    ]
    return "\n".join(lines)


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(confidence, 0.0), 1.0)


def parse_verdict(reply: Optional[str], valid_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Read the verdict, refusing anything the candidate list does not back.

    Never raises. A reply that is empty, prose, or JSON that is not an object comes back
    as `parse_ok=False` / `relation="irrelevant"` — the same defect class CLAUDE.md
    records for step07's `_parse_verdict`, which called .get() on whatever json.loads
    returned and crashed on "[]".
    """
    allowed: Optional[Set[str]] = set(valid_ids) if valid_ids is not None else None
    refused = {
        "matched_doc_ids": [],
        "relation": "irrelevant",
        "confidence": 0.0,
        "evidence": "",
        "reason": "",
        "parse_ok": False,
    }

    parsed = extract_json(reply)
    if not isinstance(parsed, dict):
        return refused

    raw_ids = parsed.get("matched_doc_ids")
    matched: List[str] = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            doc = str(item).strip()
            if not doc or doc in matched:
                continue
            if allowed is not None and doc not in allowed:
                continue  # hallucinated citation — never let it reach the saved results
            matched.append(doc)

    relation = parsed.get("relation")
    relation = relation if relation in RELATIONS else "irrelevant"
    if not matched:
        relation = "irrelevant"

    return {
        "matched_doc_ids": matched,
        "relation": relation,
        "confidence": _coerce_confidence(parsed.get("confidence")),
        "evidence": str(parsed.get("evidence") or ""),
        "reason": str(parsed.get("reason") or ""),
        "parse_ok": True,
    }


class VerdictAnswerer:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def answer(self, query: str, candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        if not candidates:
            return parse_verdict(None, valid_ids=set())
        prompt = build_verdict_prompt(query, candidates)
        try:
            reply = self.client.complete(SYSTEM, prompt)
        except Exception as exc:  # noqa: BLE001
            print(f"  [verdict] LLM call failed ({type(exc).__name__}: {exc})")
            reply = ""
        return parse_verdict(reply, valid_ids={c.get("doc_id") for c in candidates})
