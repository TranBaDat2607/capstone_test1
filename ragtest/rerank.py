"""
Listwise reranking with GLM.

The endpoint this project uses serves no rerank model — I checked its /v1/models listing:
chat models and two embedding models, nothing with "rerank" in the name — and torch is
deliberately absent from requirements.txt, so a local cross-encoder is out too. So the
chat model does the reranking: it sees the query and all candidates at once and returns a
permutation.

Listwise (one call, all candidates) rather than pointwise (one call per candidate)
because it is ~k times cheaper and lets the model compare candidates against each other,
which is the judgement that actually matters when several sentences of the same report
are near-duplicates.

The contract is deliberately narrow: the model may only PERMUTE. It cannot add a
candidate, drop one, or rewrite one — `parse_rerank_order` enforces that, and a reply it
cannot read degrades to the fusion order instead of raising. A reranker that silently
crashed would be worse than one that silently did nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .parsing import extract_json

SYSTEM = (
    "Bạn là công cụ xếp hạng lại (reranker) cho hệ thống truy xuất bằng chứng ESG "
    "tiếng Việt. Bạn chỉ được sắp xếp lại danh sách ứng viên đã cho — không thêm, "
    "không bớt, không sửa nội dung. Luôn trả lời bằng JSON hợp lệ."
)


def build_rerank_prompt(query: str, candidates: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "Câu tin tức (query):",
        f"  {query}",
        "",
        "Danh sách câu ESG trích từ báo cáo thường niên của công ty (ứng viên):",
    ]
    for index, candidate in enumerate(candidates):
        meta = f"{candidate.get('ticker')} · {candidate.get('source_pdf')} · trang {candidate.get('page')}"
        lines.append(f"  [{index}] ({meta}) {candidate.get('text')}")
    lines += [
        "",
        "Nhiệm vụ: xếp hạng lại các ứng viên theo mức độ LIÊN QUAN tới câu tin tức trên.",
        "Ứng viên liên quan nhất đứng đầu. Tiêu chí, theo thứ tự ưu tiên:",
        "  1. Cùng chủ đề ESG cụ thể (cùng sản phẩm, cùng chỉ tiêu, cùng hoạt động).",
        "  2. Cùng công ty và mốc thời gian gần nhau.",
        "  3. Câu là một tuyên bố/cam kết thực chất, không phải tiêu đề hay câu rập khuôn.",
        "",
        "Chỉ trả về JSON đúng định dạng sau, không kèm giải thích:",
        '  {"order": [<chỉ số ứng viên, liên quan nhất trước>]}',
        f"Danh sách phải là một hoán vị của các chỉ số 0..{max(len(candidates) - 1, 0)}.",
    ]
    return "\n".join(lines)


def parse_rerank_order(reply: Optional[str], n: int) -> tuple[List[int], bool]:
    """Coerce any reply into a permutation of range(n). Junk -> (input_order, False)."""
    if n <= 0:
        return [], True

    parsed = extract_json(reply)
    raw: Any = None
    if isinstance(parsed, dict):
        raw = parsed.get("order") or parsed.get("ranking") or parsed.get("indices")
    elif isinstance(parsed, list):
        raw = parsed

    order: List[int] = []
    seen = set()
    parse_ok = False
    if isinstance(raw, list) and raw:
        for item in raw:
            try:
                index = int(item)
            except (TypeError, ValueError):
                continue
            if 0 <= index < n and index not in seen:
                seen.add(index)
                order.append(index)
        if order:
            parse_ok = True

    order.extend(i for i in range(n) if i not in seen)
    return order, parse_ok


class LLMReranker:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    def rerank(self, query: str, candidates: Sequence[Dict[str, Any]],
               top_k: Optional[int] = None) -> tuple[List[Dict[str, Any]], bool]:
        """Return copies of `candidates`, reordered, each stamped with `rerank_rank`, plus parse_ok bool."""
        if not candidates:
            return [], True

        prompt = build_rerank_prompt(query, candidates)
        try:
            reply = self.client.complete(SYSTEM, prompt)
        except Exception as exc:  # noqa: BLE001 — a dead reranker must not kill the query
            print(f"  [rerank] LLM call failed ({type(exc).__name__}: {exc}); "
                  f"keeping the fusion order")
            reply = ""

        order, parse_ok = parse_rerank_order(reply, len(candidates))
        reranked = []
        for rank, index in enumerate(order):
            row = dict(candidates[index])
            row["rerank_rank"] = rank
            row["fusion_rank"] = index
            reranked.append(row)
        final_list = reranked[:top_k] if top_k else reranked
        return final_list, parse_ok

