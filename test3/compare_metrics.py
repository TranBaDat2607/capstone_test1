#!/usr/bin/env python3
"""
Dụng cụ đo dùng để so sánh nhánh Graph-RAG với nhánh RAG thường.

Cùng một câu `evidence_text` đưa vào hai hệ, mỗi hệ trả về một câu claim và một nhãn
quan hệ. Module này đo hai thứ đó:

  1. **Word matching** — `token_prf` (precision/recall/F1 trên token), `jaccard`,
     `rouge_l` (dựa trên chuỗi con chung dài nhất, nên CÓ nhìn thứ tự từ).
  2. **Ngữ nghĩa** — `cosine` trên vector nhúng.
  3. **Nhãn** — `confusion` + `label_agreement` (tỷ lệ đồng thuận thô + Cohen's kappa).
  4. **Thống kê** — `mcnemar_exact` (kiểm định ghép cặp) + `bootstrap_ci`.

Nguyên tắc dùng lại, không viết lại (agent khảo sát repo 2026-08-08):
  - Cohen's kappa lấy từ `evalu/iaa.py:132` — đã có bộ test theo ví dụ công bố, và
    quan trọng là nó trả `None` khi hệ số không xác định thay vì trả 0.0.
  - Chuẩn hoá tiếng Việt theo `evalu/evalu_labelfree.py:63` (`_tokens`): **GIỮ dấu**.
    Repo có hai lối chuẩn hoá — `evalu/lexicon.py:39 fold` thì BỎ dấu. Trộn hai lối
    làm "cùng một token" đổi nghĩa mà không báo lỗi, nên ở đây chọn hẳn lối giữ dấu:
    tiếng Việt bỏ dấu thì "phạt" và "phát" thành một.
  - McNemar, bootstrap CI, ROUGE, token-F1, cosine: repo KHÔNG có, phải viết ở đây.

Một quy ước xuyên suốt: **rỗng trả 0.0, không xác định trả None, không bao giờ trả một
con số đẹp cho một phép đo không làm được.** Hai câu rỗng không phải là "giống nhau
hoàn toàn" — đó là hai lần truy xuất thất bại, và cho nó 1.0 sẽ biến hỏng thành hoàn hảo.

Test: `python test3/test_compare_metrics.py` (offline, không LLM, không cần artifact).
"""

from __future__ import annotations

import math
import random
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evalu.iaa import cohen_kappa  # noqa: E402  — dùng lại, không viết lại

RELATIONS = ("supports", "contradicts", "irrelevant")

# Giữ dấu tiếng Việt. `à-ỹ` phủ dải chữ có dấu sau khi đã NFC.
_TOKEN_RE = re.compile(r"[0-9a-zà-ỹ]+", re.IGNORECASE)


# --------------------------------------------------------------------------
# chuẩn hoá văn bản
# --------------------------------------------------------------------------
def normalize_vn(text: Optional[str]) -> str:
    """NFC + thường hoá + gộp khoảng trắng. KHÔNG bỏ dấu (xem docstring đầu file)."""
    if not text:
        return ""
    return " ".join(unicodedata.normalize("NFC", str(text)).lower().split())


def tokens(text: Optional[str]) -> List[str]:
    """Danh sách token theo thứ tự xuất hiện — `rouge_l` cần thứ tự, `jaccard` thì không."""
    return _TOKEN_RE.findall(normalize_vn(text))


# --------------------------------------------------------------------------
# word matching
# --------------------------------------------------------------------------
def token_prf(a: Optional[str], b: Optional[str]) -> Dict[str, float]:
    """
    Precision/recall/F1 trên TÚI token (multiset), coi `a` là câu dự đoán, `b` là câu tham chiếu.

    Có hướng: một câu ngắn nằm gọn trong câu dài có precision cao, recall thấp. Đó là
    thông tin thật — hai nhánh trả câu dài ngắn khác nhau, và `jaccard` (đối xứng) sẽ
    giấu mất điều đó.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    overlap = sum((Counter(ta) & Counter(tb)).values())
    precision = overlap / len(ta)
    recall = overlap / len(tb)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def jaccard(a: Optional[str], b: Optional[str]) -> float:
    """|giao| / |hợp| trên TẬP token. Đối xứng, không nhìn thứ tự, không nhìn số lần lặp."""
    sa, sb = set(tokens(a)), set(tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _lcs_length(a: Sequence[str], b: Sequence[str]) -> int:
    """Độ dài chuỗi con chung dài nhất. Quy hoạch động 2 hàng — O(len(a)*len(b)) thời gian, O(len(b)) bộ nhớ."""
    if not a or not b:
        return 0
    previous = [0] * (len(b) + 1)
    for token_a in a:
        current = [0]
        for j, token_b in enumerate(b):
            current.append(previous[j] + 1 if token_a == token_b else max(previous[j + 1], current[j]))
        previous = current
    return previous[-1]


def rouge_l(a: Optional[str], b: Optional[str]) -> float:
    """
    ROUGE-L F1: dựa trên chuỗi con chung dài nhất, nên CÓ nhìn thứ tự từ.

    Đây là lý do giữ cả `rouge_l` lẫn `jaccard`: hai câu đảo hết trật tự từ vẫn cho
    `jaccard` = 1 nhưng `rouge_l` < 1. Với tiếng Việt — nghĩa phụ thuộc trật tự từ
    nhiều hơn tiếng Anh — khác biệt đó đáng giữ.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    lcs = _lcs_length(ta, tb)
    if lcs == 0:
        return 0.0
    precision, recall = lcs / len(ta), lcs / len(tb)
    return 2 * precision * recall / (precision + recall)


def text_similarity(a: Optional[str], b: Optional[str]) -> Dict[str, float]:
    """Gói word-matching cho một dòng sheet. Luôn đủ 5 khoá, luôn là số, không bao giờ None."""
    prf = token_prf(a, b)
    return {
        "token_precision": prf["precision"],
        "token_recall": prf["recall"],
        "token_f1": prf["f1"],
        "jaccard": jaccard(a, b),
        "rouge_l": rouge_l(a, b),
    }


# --------------------------------------------------------------------------
# ngữ nghĩa
# --------------------------------------------------------------------------
def cosine(u: Optional[Sequence[float]], v: Optional[Sequence[float]]) -> Optional[float]:
    """
    Cosine giữa hai vector nhúng, hoặc None nếu không tính được.

    Vector 0 trả None chứ không trả 0.0: "không tính được" khác "trực giao". Đây cũng
    là quy ước của `evalu/iaa.py` cho hệ số không xác định.
    """
    if u is None or v is None or len(u) != len(v) or not len(u):
        return None
    dot = sum(x * y for x, y in zip(u, v))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    if nu == 0.0 or nv == 0.0:
        return None
    return max(-1.0, min(1.0, dot / (nu * nv)))


# --------------------------------------------------------------------------
# nhãn quan hệ
# --------------------------------------------------------------------------
def confusion(a: Sequence[str], b: Sequence[str],
              labels: Sequence[str] = RELATIONS) -> Dict[str, Dict[str, int]]:
    """Ma trận nhầm lẫn labels×labels: hàng = nhãn của hệ A, cột = nhãn của hệ B."""
    if len(a) != len(b):
        raise ValueError(f"hai danh sách nhãn lệch độ dài: {len(a)} vs {len(b)}")
    matrix = {ra: {rb: 0 for rb in labels} for ra in labels}
    for la, lb in zip(a, b):
        if la in matrix and lb in matrix[la]:
            matrix[la][lb] += 1
    return matrix


def label_agreement(a: Sequence[str], b: Sequence[str],
                    labels: Sequence[str] = RELATIONS) -> Dict[str, Any]:
    """
    Mức đồng thuận nhãn giữa hai hệ: tỷ lệ thô, Cohen's kappa, và ma trận nhầm lẫn.

    Coi mỗi hệ là một "rater" — `EVALUATION_WITHOUT_LABELS.md` §5 ghi rõ đây là cách
    dùng hợp lệ chứ không phải mẹo: hệ số agreement định nghĩa cho tập rater bất kỳ.

    Kappa quan trọng hơn tỷ lệ thô: hai hệ cùng trả `irrelevant` cho 90% số dòng sẽ
    cho tỷ lệ thô 0.9 dù cả hai chẳng phân biệt được gì. Kappa trừ đi phần đồng thuận
    do may rủi. Khi cả hai hệ trả một nhãn duy nhất thì kappa KHÔNG xác định — hàm trả
    None (kế thừa `evalu.iaa.cohen_kappa`), không trả 0.0.
    """
    if len(a) != len(b):
        raise ValueError(f"hai danh sách nhãn lệch độ dài: {len(a)} vs {len(b)}")
    n = len(a)
    if n == 0:
        return {"n": 0, "agreement": None, "cohen_kappa": None,
                "confusion": confusion([], [], labels)}
    agree = sum(1 for la, lb in zip(a, b) if la == lb)
    return {
        "n": n,
        "agreement": agree / n,
        "cohen_kappa": cohen_kappa([[la, lb] for la, lb in zip(a, b)]),
        "confusion": confusion(a, b, labels),
    }


# --------------------------------------------------------------------------
# thống kê
# --------------------------------------------------------------------------
def mcnemar_exact(b: int, c: int) -> float:
    """
    McNemar chính xác (nhị thức hai phía) trên hai ô lệch của bảng ghép cặp.

    `b` = số ca hệ A đúng / hệ B sai, `c` = ngược lại. Chỉ hai ô này mang thông tin —
    ca hai hệ hành xử giống nhau bị loại khỏi kiểm định, và đó chính là chỗ thiết kế
    ghép cặp ăn điểm (`AGENT_AB_EVALUATION.md` §5.2). Hệ quả thực tế: **lực kiểm định
    phụ thuộc `b + c`, không phụ thuộc tổng số dòng** — b+c ≈ 25 mới đủ (§9.4).
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def bootstrap_ci(values: Sequence[float], reps: int = 10000, alpha: float = 0.05,
                 seed: int = 42) -> Tuple[Optional[float], Optional[float]]:
    """
    Khoảng tin cậy phần trăm cho TRUNG BÌNH của `values`, lấy mẫu lặp lại có hoàn lại.

    Có `seed` để hai lần chạy cho đúng một khoảng — repo yêu cầu số đo tái lập được
    (`evalu_labelfree.py` cũng ghim seed vào output). Mẫu rỗng trả (None, None).
    """
    data = [float(v) for v in values if v is not None]
    if not data:
        return (None, None)
    rng = random.Random(seed)
    n = len(data)
    means = []
    for _ in range(reps):
        means.append(sum(data[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[max(0, int((alpha / 2) * reps) - 1)]
    hi = means[min(reps - 1, int((1 - alpha / 2) * reps))]
    return (lo, hi)


def wilson_ci(k: int, n: int, z: float = 1.96) -> Optional[Tuple[float, float]]:
    """Khoảng tin cậy Wilson cho một tỷ lệ — dùng cho specificity/coverage (tỷ lệ nhị phân)."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
