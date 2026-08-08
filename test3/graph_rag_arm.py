#!/usr/bin/env python3
"""
Nhánh Graph-RAG: cho một câu bằng chứng (node conduct), trả về các claim của cùng
doanh nghiệp, xếp hạng bằng ĐÚNG cơ chế truy xuất của step07 chạy ngược chiều.

step07 (`esg_kg/crosscheck/claims_vs_conduct.py:586-660`) đi chiều claim → conduct qua
hai tầng. Ở đây đi ngược, evidence → claim, giữ nguyên hai tầng đó:

  **Tầng 1 — trục chỉ tiêu (2 bước nhảy trên đồ thị).**
      evidence --measuredUnder--> StandardIndicator <--alignsWithIndicator-- claim
  Tầng này bỏ qua cổng trùng token, vì một claim và một KPI cùng chỉ tiêu có thể không
  chung chữ nào ("giảm phát thải" vs "12.450 tCO2e"). Điểm cộng `INDICATOR_BOOST` cố ý
  rất lớn để cặp nối qua chỉ tiêu luôn xếp trên cặp chỉ trùng token.

  **Tầng 2 — trùng token chủ đề tiếng Việt**, có cổng `min_overlap` và cửa sổ thời gian.

Đây là chỗ đồ thị làm được việc mà RAG vector/BM25 thuần không làm được: tầng 1 là một
phép nối cấu trúc, không phải phép đo giống nhau về chữ.

Ba quy tắc bắt buộc, mỗi cái đều có test canh:
  - **Dùng lại helper của step07, không viết bản sao.** `topic_tokens`, `node_text`,
    `node_year`, `date_uncertain`, `claim_keywords` đều import từ stage. Viết lại một
    bản na ná là đo một hệ na ná, không phải đo hệ thật (`evalu/retrieval_eval.py:30-32`).
  - **Khoanh theo issuer.** Claim chỉ lấy từ `Organization --claims--> SustainabilityClaim`
    của đúng mã đó. Rò rỉ sang doanh nghiệp khác là lỗi mà chỉ hệ đồ thị mới mắc được
    (nhảy qua công ty con), BM25 không mắc — `AGENT_AB_EVALUATION.md` §6.2 gọi là "rò rỉ thật".
  - **Cùng cửa sổ thời gian** như step07 (`--window-before/--window-after`).

Test: `python test3/test_graph_rag_arm.py` (offline).
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from esg_kg.crosscheck.claims_vs_conduct import (  # noqa: E402
    CONDUCT_CLASSES,
    DEFAULT_MIN_TOPIC_OVERLAP,
    Graph,
    claim_keywords,
    date_uncertain,
    node_text,
    node_ticker,
    node_year,
    props,
    topic_tokens,
)

CLAIM_CLASS = "SustainabilityClaim"

# Cùng hằng số step07 dùng (claims_vs_conduct.py:605). Cố ý rất lớn: cặp nối qua chỉ
# tiêu phải luôn xếp trên cặp chỉ trùng token, không bao giờ để điểm token vượt lên.
INDICATOR_BOOST = 1000

# Mặc định của step07 (claims_vs_conduct.py:869 và các --window-* của nó). window_after
# rộng tới 50 năm là CÓ CHỦ Ý ở stage gốc, không phải lỗi — giữ nguyên để nhánh này
# không vô tình nghiêm khắc hơn hệ thật.
DEFAULT_WINDOW_BEFORE = 1
DEFAULT_WINDOW_AFTER = 50


class GraphArm:
    """Truy xuất evidence → claim trên resolved_graph.json. Không LLM, không mạng."""

    def __init__(self, graph_data: Dict[str, Any]):
        self.g = Graph(graph_data)
        self._kw = claim_keywords(self.g)

        # issuer (ticker) -> các claim của issuer đó
        self._claims_by_ticker: Dict[str, List[int]] = defaultdict(list)
        for i, n in enumerate(self.g.nodes):
            if n.get("class") != "Organization":
                continue
            ticker = (props(n).get("ticker") or "").upper()
            if not ticker:
                continue
            for pred, obj in self.g.out.get(i, []):
                if pred == "claims" and self.g.cls(obj) == CLAIM_CLASS:
                    self._claims_by_ticker[ticker].append(obj)
        for ticker, idxs in self._claims_by_ticker.items():
            self._claims_by_ticker[ticker] = sorted(set(idxs))

        # token chủ đề của từng claim, tính một lần
        self._claim_tokens: Dict[int, set] = {}
        for idxs in self._claims_by_ticker.values():
            for ci in idxs:
                if ci not in self._claim_tokens:
                    self._claim_tokens[ci] = topic_tokens(node_text(self.g.nodes[ci]),
                                                          self._kw.get(ci))

        # trục chỉ tiêu, dựng theo cả hai chiều để tra ngược được
        self._claims_of_indicator: Dict[int, List[int]] = defaultdict(list)
        for ci in self._claim_tokens:
            for pred, obj in self.g.out.get(ci, []):
                if pred == "alignsWithIndicator":
                    self._claims_of_indicator[obj].append(ci)

    # ---- tra cứu ----
    def tickers(self) -> List[str]:
        return sorted(self._claims_by_ticker)

    def claims_for_ticker(self, ticker: str) -> List[int]:
        return self._claims_by_ticker.get((ticker or "").upper(), [])

    def conduct_nodes(self) -> List[int]:
        """Các node conduct phía tin tức — cùng định nghĩa step07 dùng (:576-577)."""
        return [i for i, n in enumerate(self.g.nodes)
                if n.get("class") in CONDUCT_CLASSES
                and props(n).get("source_type") == "news"]

    def ticker_of(self, node_index: int) -> Optional[str]:
        return node_ticker(self.g.nodes[node_index])

    def indicators_of(self, node_index: int) -> List[int]:
        """Chỉ tiêu mà node bằng chứng này được đo dưới (bước nhảy 1 của tầng 1)."""
        return [obj for pred, obj in self.g.out.get(node_index, []) if pred == "measuredUnder"]

    # ---- truy xuất ----
    def retrieve(self, evidence_index: int, ticker: str,
                 top_k: int = 10,
                 min_overlap: int = DEFAULT_MIN_TOPIC_OVERLAP,
                 window_before: int = DEFAULT_WINDOW_BEFORE,
                 window_after: int = DEFAULT_WINDOW_AFTER,
                 claim_year_override: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Các claim ứng viên cho một node bằng chứng, tốt nhất trước.

        `claim_year_override` chỉ dùng để test cửa sổ thời gian — đặt năm claim thành
        một giá trị đã biết thay vì đọc từ node.
        """
        candidates = self.claims_for_ticker(ticker)
        if not candidates:
            return []

        xnode = self.g.nodes[evidence_index]
        xtokens = topic_tokens(node_text(xnode))
        xyear = node_year(xnode)
        x_uncertain = date_uncertain(xnode)

        def in_window(ci: int) -> bool:
            # Cùng luật step07 (:635-637): ngày không chắc thì KHÔNG lọc theo thời gian —
            # nêu ra rồi gắn cờ, chứ không âm thầm loại.
            cyear = claim_year_override if claim_year_override is not None \
                else node_year(self.g.nodes[ci])
            if cyear is None or xyear is None or x_uncertain:
                return True
            return cyear - window_before <= xyear <= cyear + window_after

        scored: Dict[int, tuple] = {}   # ci -> (score, tier)

        # tầng 2: trùng token chủ đề
        for ci in candidates:
            overlap = len(xtokens & self._claim_tokens.get(ci, set()))
            if overlap < min_overlap or not in_window(ci):
                continue
            scored[ci] = (overlap, "token_overlap")

        # tầng 1: trục chỉ tiêu — bỏ qua cổng token, giữ cửa sổ thời gian
        allowed = set(candidates)
        for si in self.indicators_of(evidence_index):
            for ci in self._claims_of_indicator.get(si, []):
                if ci not in allowed or not in_window(ci):
                    continue
                base = scored[ci][0] if ci in scored else 0
                scored[ci] = (base + INDICATOR_BOOST, "indicator")

        ranked = sorted(scored.items(),
                        key=lambda kv: (-kv[1][0], node_year(self.g.nodes[kv[0]]) or 0, kv[0]))
        return [{"node_index": ci,
                 "claim_text": node_text(self.g.nodes[ci]),
                 "score": score,
                 "tier": tier}
                for ci, (score, tier) in ranked[:top_k]]
