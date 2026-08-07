"""
Negative control for the claim↔conduct cross-check (the analytical core).

Why this exists
---------------
Every metric in `metrics.py` is a conformance check against the pipeline's own
design: it can confirm the code does what the code says, and nothing more. None
of them can FAIL in an interesting way, so none of them can support the claim
that the system works.

This module can. It asks one question with a clean null hypothesis and no labels:

    When the system cites a piece of news as evidence for company T's claim,
    is that news actually about company T?

The null is that retrieval carries no company signal at all — in which case the
share of T's evidence drawn from T's own news feed is just that feed's share of
the global pool. Observed >> chance means retrieval is company-specific.
Observed ~ chance means the "evidence" is topic matching, and every downstream
verdict inherits that.

How a conduct node is attributed
--------------------------------
The news crawler writes one file per ticker, and step02 stamps the resulting
nodes with `source_doc = "<TICKER>__<domain>__<hash>"`. The prefix is therefore
the feed the article was collected under. Annual-report nodes use a different
convention with no ticker prefix and are attributed to None rather than guessed.

Feed ≠ subject, so the audit separates two different things:
  * cross-feed          the article came from another company's feed
  * cross-feed AND unmentioned
                        ...and it never names the claimant either
Only the second is indefensible. Keeping them apart matters, because a fix that
simply drops all cross-feed evidence would also discard legitimate coverage of
company T that happened to be crawled under company U.

`mentions_claimant` deliberately reads only the fields the pipeline itself feeds
to the LLM (see claims_vs_conduct.node_text: for a MediaReport that is the title
alone). Searching text the adjudicator never saw would credit the system with
knowledge it did not have.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from evalu.model import MetricResult, ratio

# Fields node_text() may return for a conduct node, in its own precedence order.
NODE_TEXT_FIELDS = ("description", "title", "text", "result", "name", "term")

EVIDENCE_KINDS = ("supporting_evidence", "contradicting_evidence",
                  "flagged_non_independent_support")

_DSTROKE = str.maketrans({"đ": "d", "Đ": "d"})


def _fold(s: Optional[str]) -> str:
    s = (s or "").lower().translate(_DSTROKE)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


def attribute_ticker(node: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Ticker of the news feed a conduct node came from, or None.

    "AAA__baodautu.vn__6bef6bcbb6" -> "AAA".  Report-side names such as
    "AAA_2013" have no "__" separator and return None: they are annual-report
    documents, not news, and inventing an attribution for them would quietly
    mis-label the report side of the graph.
    """
    if not isinstance(node, dict):
        return None
    sd = (node.get("properties") or {}).get("source_doc") or ""
    if "__" not in sd:
        return None
    head = sd.split("__", 1)[0].strip().upper()
    return head or None


def node_text_blob(node: Dict[str, Any]) -> str:
    """The text the adjudicator actually saw, folded."""
    p = node.get("properties") or {}
    for k in NODE_TEXT_FIELDS:
        if p.get(k):
            return _fold(str(p[k]))
    return ""


def mentions_claimant(node: Dict[str, Any], variants: Iterable[str]) -> bool:
    blob = node_text_blob(node)
    if not blob:
        return False
    return any(v for v in (_fold(x) for x in variants) if v and v in blob)


def load_issuer_variants(registry: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Ticker -> folded name variants, from config/issuer_registry.json."""
    body = registry.get("issuers", registry)
    out: Dict[str, Set[str]] = {}
    for key, val in body.items():
        if not isinstance(val, dict):
            continue
        ticker = str(val.get("ticker") or key).upper()
        names: Set[str] = {ticker}
        for f in ("canonical_name", "name", "short_name"):
            if isinstance(val.get(f), str):
                names.add(val[f])
        for f in ("aliases", "variants"):
            names.update(x for x in (val.get(f) or []) if isinstance(x, str))
        folded = {_fold(n) for n in names}
        out[ticker] = {n for n in folded if len(n) >= 3}
    return out


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #
def evidence_attribution_audit(dossiers: Sequence[Dict[str, Any]],
                               nodes: Sequence[Dict[str, Any]],
                               variants: Dict[str, Set[str]]) -> MetricResult:
    """
    NC.1 — of the evidence the system actually cited, how much is about the
    company whose claim it was cited against.

    The metric value is the SAME-FEED share. `by_kind` reports supporting and
    contradicting separately, because contradictions are the system's headline
    output: a cross-company contradiction is a false greenwashing signal
    attached to a named, real company.
    """
    same = cross = cross_unmentioned = unattributed = 0
    by_kind: Dict[str, Counter] = defaultdict(Counter)
    examples: List[Dict[str, Any]] = []

    for d in dossiers:
        claim_ticker = str(d.get("_ticker") or "").upper()
        claim_variants = variants.get(claim_ticker, {_fold(claim_ticker)})
        for kind in EVIDENCE_KINDS:
            for ev in (d.get(kind) or []):
                xi = ev.get("node_index")
                if not isinstance(xi, int) or not (0 <= xi < len(nodes)):
                    continue
                node = nodes[xi]
                ev_ticker = attribute_ticker(node)
                if ev_ticker is None:
                    unattributed += 1
                    by_kind[kind]["unattributed"] += 1
                    continue
                by_kind[kind]["total"] += 1
                if ev_ticker == claim_ticker:
                    same += 1
                    by_kind[kind]["same_feed"] += 1
                    continue
                cross += 1
                by_kind[kind]["cross_feed"] += 1
                named = mentions_claimant(node, claim_variants)
                if not named:
                    cross_unmentioned += 1
                    by_kind[kind]["cross_feed_unmentioned"] += 1
                    if len(examples) < 25:
                        examples.append({
                            "claim_ticker": claim_ticker,
                            "evidence_ticker": ev_ticker,
                            "kind": kind,
                            "assessment": d.get("assessment"),
                            "claim": (d.get("claim_text") or "")[:160],
                            "evidence": (ev.get("text") or "")[:160],
                        })

    cited = same + cross
    return MetricResult(
        metric_id="NC.1",
        module="Negative control — quy thuộc bằng chứng",
        name="Same-Company Evidence Rate",
        value=ratio(same, cited),
        numerator=same,
        denominator=cited,
        target="100% (bằng chứng phải nói về chính doanh nghiệp bị xét)",
        passed=(cited > 0 and cross == 0),
        purpose=("Đây là phép kiểm CÓ THỂ LÀM HỆ THỐNG TRƯỢT — khác với toàn bộ nhóm "
                 "M1-M5, vốn chỉ đối chiếu hệ thống với thiết kế của chính nó. Nó hỏi "
                 "một câu duy nhất: khi hệ thống trích một bản tin làm bằng chứng cho "
                 "tuyên bố của doanh nghiệp T, bản tin đó có thật sự nói về T không? "
                 "Nếu không, mọi kết luận phía sau đều vô giá trị, bất kể LLM lập luận "
                 "hay đến đâu."),
        how_to_read=("Đọc `cross_feed_unmentioned` trước tiên: đó là số bằng chứng vừa "
                     "đến từ feed công ty khác, vừa không hề nhắc tên doanh nghiệp đang "
                     "xét trong phần text mà LLM thực sự nhìn thấy. Đặc biệt chú ý dòng "
                     "`contradicting_evidence` trong `by_kind` — mâu thuẫn là đầu ra "
                     "chính của hệ thống, nên một mâu thuẫn chéo công ty là một cáo buộc "
                     "greenwashing sai gán cho một doanh nghiệp có thật, nêu đích danh."),
        limitation=("Quy thuộc dựa trên tiền tố ticker trong source_doc, tức 'bài này "
                    "được crawl dưới feed của ai'. Một bài trong feed công ty khác mà "
                    "có nhắc tên doanh nghiệp đang xét thì VẪN hợp lệ — hai trường hợp "
                    "được tách riêng, không gộp làm một."),
        details={
            "cited_total": cited,
            "same_feed": same,
            "cross_feed": cross,
            "cross_feed_unmentioned": cross_unmentioned,
            "unattributed_nodes": unattributed,
            "by_kind": {k: dict(v) for k, v in by_kind.items()},
            "examples": examples,
            "note": ("cross_feed_unmentioned là con số quyết định: bài đến từ feed "
                     "công ty khác VÀ không hề nhắc tên doanh nghiệp đang xét trong "
                     "phần text mà LLM thực sự nhìn thấy."),
        },
    )


# --------------------------------------------------------------------------- #
# specificity against the chance null
# --------------------------------------------------------------------------- #
def same_feed_specificity(cited_by_ticker: Dict[str, Tuple[int, int]],
                          pool_by_ticker: Dict[str, int]) -> MetricResult:
    """
    NC.2 — observed same-feed rate vs the rate expected if evidence were drawn
    uniformly at random from the global conduct pool.

    `cited_by_ticker`: ticker -> (same_feed_citations, total_citations)
    `pool_by_ticker` : ticker -> number of conduct nodes in that ticker's feed

    lift = observed / expected.  lift ~ 1 means retrieval is indistinguishable
    from drawing at random with respect to company — the null cannot be
    rejected, and no downstream verdict can be read as company-specific.
    """
    pool_total = sum(pool_by_ticker.values())
    by_ticker: Dict[str, Dict[str, Any]] = {}
    tot_same = tot_cited = 0
    exp_sum = 0.0

    for ticker, (same, total) in sorted(cited_by_ticker.items()):
        if not total:
            continue
        expected_rate = ratio(pool_by_ticker.get(ticker, 0), pool_total) or 0.0
        observed_rate = same / total
        by_ticker[ticker] = {
            "cited": total,
            "same_feed": same,
            "observed_rate": observed_rate,
            "expected_rate": expected_rate,
            "expected_count": expected_rate * total,
            "lift": (observed_rate / expected_rate) if expected_rate else None,
        }
        tot_same += same
        tot_cited += total
        exp_sum += expected_rate * total

    overall_expected = ratio(exp_sum, tot_cited)
    overall_observed = ratio(tot_same, tot_cited)
    lift = ((overall_observed / overall_expected)
            if (overall_observed is not None and overall_expected) else None)

    return MetricResult(
        metric_id="NC.2",
        module="Negative control — độ đặc hiệu theo công ty",
        name="Same-Feed Specificity vs Chance",
        value=overall_observed,
        numerator=tot_same,
        denominator=tot_cited,
        target="lift >> 1 (nếu ~1 thì truy hồi không mang tín hiệu công ty nào)",
        passed=(lift is not None and lift >= 2.0),
        purpose=("Biến NC.1 thành một phép kiểm giả thuyết có đối chứng. Giả thuyết "
                 "không: bằng chứng được rút NGẪU NHIÊN từ kho conduct toàn cục, không "
                 "phụ thuộc doanh nghiệp. Dưới giả thuyết đó, tỷ lệ bằng chứng của công "
                 "ty T đến từ feed của T đúng bằng tỷ trọng feed đó trong kho. So sánh "
                 "quan sát với kỳ vọng cho biết truy hồi có mang tín hiệu công ty hay "
                 "chỉ đang khớp chủ đề."),
        how_to_read=("lift = quan sát / kỳ vọng.  lift ≈ 1 nghĩa là KHÔNG bác bỏ được "
                     "giả thuyết không: truy hồi không phân biệt được với bốc ngẫu "
                     "nhiên, và không kết luận nào phía sau được phép đọc như 'đặc thù "
                     "cho doanh nghiệp này'. lift ≥ 2 mới coi là có tín hiệu thật. "
                     "lift < 1 là tệ hơn cả ngẫu nhiên."),
        limitation=("Kho conduct hiện rất nhỏ (44 node / 5 mã), nên lift theo từng mã "
                    "có phương sai lớn — đọc con số tổng, và đọc `by_ticker` như dấu "
                    "hiệu định tính chứ đừng như ước lượng điểm."),
        details={
            "observed_rate": overall_observed,
            "expected_rate_by_chance": overall_expected,
            "lift": lift,
            "pool_by_ticker": dict(sorted(pool_by_ticker.items())),
            "pool_total": pool_total,
            "by_ticker": by_ticker,
            "null_hypothesis": ("bằng chứng được rút ngẫu nhiên đều từ kho conduct "
                                "toàn cục, không phụ thuộc công ty"),
        },
    )


def pool_by_ticker(nodes: Sequence[Dict[str, Any]],
                   conduct_classes: Iterable[str] = ("Controversy", "Penalty",
                                                     "MediaReport")) -> Dict[str, int]:
    """Size of each ticker's news conduct feed, as the retrieval sees it."""
    classes = set(conduct_classes)
    counts: Counter = Counter()
    for n in nodes:
        if n.get("class") not in classes:
            continue
        if (n.get("properties") or {}).get("source_type") != "news":
            continue
        t = attribute_ticker(n)
        if t:
            counts[t] += 1
    return dict(counts)


def citations_by_ticker(dossiers: Sequence[Dict[str, Any]],
                        nodes: Sequence[Dict[str, Any]]) -> Dict[str, Tuple[int, int]]:
    """ticker -> (same-feed citations, total attributable citations)."""
    acc: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for d in dossiers:
        claim_ticker = str(d.get("_ticker") or "").upper()
        for kind in EVIDENCE_KINDS:
            for ev in (d.get(kind) or []):
                xi = ev.get("node_index")
                if not isinstance(xi, int) or not (0 <= xi < len(nodes)):
                    continue
                t = attribute_ticker(nodes[xi])
                if t is None:
                    continue
                acc[claim_ticker][1] += 1
                if t == claim_ticker:
                    acc[claim_ticker][0] += 1
    return {k: (v[0], v[1]) for k, v in acc.items()}
