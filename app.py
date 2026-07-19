"""Greenwashing evidence explorer — demo UI (Streamlit).

A company-code lookup over the temporal ESG knowledge graph. Enter a ticker and the
app renders that issuer's **claim ledger**: every SustainabilityClaim beside the conduct
evidence that supports or contradicts it, plus an explicitly **advisory** assessment.

This is the web front-end for Step 7 (docs/SYSTEM_DESIGN.md §9, docs/CLAIM_LEDGER.md).
It reads ONLY from the Neo4j advisory layer that `src/step08_sync_crosscheck_to_neo4j.py`
wrote (claim `assessment`/`caveats`/`signals`/`score_*` + `llm_supports`/`llm_contradicts`/
`llm_flagged_support` edges). It makes **no** LLM call — deterministic, traceable,
same-input→same-evidence — and it never emits a greenwashing verdict
(SYSTEM_DESIGN §1.1: no ground truth ⇒ evidence + advisory opinion only). The per-claim
evidence-balance bar renders the step07b softmax distribution (docs/SOFTMAX_SCORING.md):
a normalized balance of the linked evidence, computed offline — NOT a greenwashing
probability, and labeled as such everywhere it appears.

Prereqs (same as step09):
    - Neo4j up (docker compose up -d) with the step-5 graph loaded.
    - `python src/step08_sync_crosscheck_to_neo4j.py` run once (free, no tokens).

Run from the repo root:
    streamlit run app.py
"""

import html as html_lib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
# src/ scripts import each other by bare module name (see CLAUDE.md); do the same here so we
# can reuse step09's pure helpers instead of re-deriving ordering / labels / review-queue logic.
sys.path.insert(0, str(REPO_ROOT / "src"))

from step09_report_claim_ledger import (  # noqa: E402  (path set above)
    ASSESSMENT_LABEL,
    ASSESSMENT_ORDER,
    CONDUCT_CLASSES,
    ROLE_BUCKET,
    build_header,
    is_review_queue,
    _sort_key,
    _truncate,
)

# Neo4j defaults — identical to step09_report_claim_ledger.py / the sync.
NEO4J_URI_DEFAULT = "bolt://localhost:8687"
NEO4J_USER_DEFAULT = "greenwashing"
NEO4J_PASSWORD_DEFAULT = "nammovuivui"

ASSESSMENT_META = {  # nhãn, emoji, css class — 3 nhóm đánh giá tham khảo (§1.1)
    "appears_contradicted": ("Có vẻ mâu thuẫn", "✗", "contradicted"),
    "appears_supported": ("Có vẻ được xác nhận", "✓", "supported"),
    "unverified_insufficient_evidence": ("Chưa xác minh / thiếu bằng chứng", "•", "unverified"),
}

# Nhãn hiển thị cho nguồn của claim (dữ liệu gốc vẫn là "report"/"news" — chỉ dịch phần hiển thị).
CLAIM_SOURCE_LABEL = {"report": "báo cáo", "news": "tin tức"}

# Bản dịch tiếng Việt cho lưu ý độ phủ (COVERAGE_CAVEAT gốc trong step09 giữ nguyên tiếng Anh
# vì đó là script CLI dùng chung — bản dịch chỉ áp dụng cho giao diện Streamlit này).
COVERAGE_CAVEAT_VI = ("Bằng chứng hành vi độc lập còn mỏng — việc không có mâu thuẫn KHÔNG "
                      "đồng nghĩa với việc công ty đã được minh oan (xem docs/SYSTEM_DESIGN.md §8.3).")

# --------------------------------------------------------------------------- page + style
st.set_page_config(
    page_title="Trình khám phá Bằng chứng Greenwashing",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      * { font-family: "Segoe UI", -apple-system, "Helvetica Neue", Roboto, Arial, sans-serif; }
      .block-container { padding-top: 2rem; max-width: 1180px; }
      .gw-title { font-size: 2rem; font-weight: 700; margin-bottom: .2rem; line-height: 1.3; }
      .gw-sub   { color: #52606d; font-size: 1rem; line-height: 1.6; margin-bottom: 1.1rem; }

      .advisory-banner {
        background: #fff8e1; border: 1px solid #f0d58a; color: #6b4f00;
        border-radius: 8px; padding: .75rem 1rem; font-size: .92rem; line-height: 1.55;
        margin-bottom: 1rem;
      }
      .coverage-caveat {
        background: #eef2f7; border-left: 4px solid #94a3b8; color: #3a4653;
        border-radius: 6px; padding: .65rem .9rem; font-size: .9rem; line-height: 1.55;
        margin: .3rem 0 1.2rem 0;
      }

      /* metric chips */
      .chips { display: flex; gap: .7rem; flex-wrap: wrap; margin: .2rem 0 .7rem 0; }
      .chip { border-radius: 10px; padding: .6rem 1rem; min-width: 130px; border: 1px solid; }
      .chip .n { font-size: 1.6rem; font-weight: 700; line-height: 1.2; }
      .chip .l { font-size: .78rem; letter-spacing: .01em; opacity: .9; margin-top: .1rem; }
      .chip.total       { background:#f3f4f6; border-color:#d1d5db; color:#374151; }
      .chip.contradicted{ background:#fdecea; border-color:#f5b7b1; color:#a93226; }
      .chip.supported   { background:#eafaf1; border-color:#a9dfbf; color:#1e8449; }
      .chip.unverified  { background:#f4f6f7; border-color:#d5dbdb; color:#5d6d7e; }

      /* claim card */
      .claim-card {
        border: 1px solid #e5e7eb; border-left-width: 5px; border-radius: 10px;
        padding: 1rem 1.15rem; margin-bottom: 1rem; background: #ffffff;
        box-shadow: 0 1px 3px rgba(15, 23, 42, .05);
      }
      .claim-card.contradicted { border-left-color: #c0392b; }
      .claim-card.supported    { border-left-color: #1e8449; }
      .claim-card.unverified   { border-left-color: #b0b7bd; }
      .claim-head { display:flex; justify-content:space-between; gap:1rem; align-items:baseline;
                    flex-wrap: wrap; }
      .claim-id { font-family: ui-monospace, monospace; font-size: .82rem; color:#5d6d7e; }
      .claim-text { font-size: 1.08rem; font-weight: 600; line-height: 1.55;
                    margin: .45rem 0 .65rem 0; color:#1f2937; }

      .badge { border-radius: 999px; padding: .18rem .7rem; font-size: .78rem; font-weight:700;
               white-space: nowrap; }
      .badge.contradicted { background:#fdecea; color:#a93226; }
      .badge.supported    { background:#eafaf1; color:#1e8449; }
      .badge.unverified   { background:#eef1f3; color:#5d6d7e; }

      .evi { border-radius: 7px; padding: .65rem .9rem; margin: .5rem 0; font-size: .93rem; }
      .evi.c { background:#fdf0ee; border-left:3px solid #c0392b; }
      .evi.s { background:#eef8f2; border-left:3px solid #1e8449; }
      .evi.f { background:#fef6e7; border-left:3px solid #d68910; }
      .evi .meta { font-size: .78rem; color:#5d6d7e; margin-bottom: .4rem; }

      /* claim (báo cáo) vs bằng chứng độc lập — so sánh rõ ràng trong từng khối */
      .cmp { margin: .25rem 0; }
      .cmp-label { font-size: .72rem; font-weight: 700; text-transform: uppercase;
                   letter-spacing: .02em; margin-bottom: .15rem; }
      .claim-side .cmp-label    { color: #6b7280; }
      .evidence-side .cmp-label { color: #374151; }
      .cmp-text { font-size: .93rem; line-height: 1.55; color: #374151; }
      .vs { font-size: .8rem; font-weight: 700; margin: .3rem 0; padding-left: .1rem; }
      .vs.c { color: #a93226; }
      .vs.s { color: #1e8449; }
      .vs.f { color: #b8860b; }

      .evi .rat  { font-size: .85rem; color:#5d6d7e; font-style: italic; line-height: 1.5;
                   margin-top:.45rem; padding-top:.35rem; border-top: 1px dashed rgba(0,0,0,.08); }

      .caveats { font-size: .84rem; color:#52606d; line-height: 1.6; margin-top:.65rem; }
      .caveats li { margin: .15rem 0; }
      .sig { font-size: .8rem; color:#78828c; line-height: 1.5; margin-top:.4rem; }

      /* evidence-balance bar (step07b) — đỏ | xám | xanh: hai cực tách nhau bằng ô trung
         tính ở giữa (CVD-safe, validator-checked); nhãn chữ + giá trị bên dưới nên không
         bao giờ chỉ dựa vào màu. */
      .score-wrap { margin: .1rem 0 .55rem 0; }
      .score-title { font-size: .72rem; font-weight: 700; text-transform: uppercase;
                     letter-spacing: .02em; color: #6b7280; margin-bottom: .25rem; }
      .score-title .score-note { font-weight: 400; text-transform: none; color: #8a939b; }
      .score-bar { display: flex; gap: 2px; height: 10px; border-radius: 5px;
                   overflow: hidden; background: #f3f4f6; }
      .score-seg.c { background: #c0392b; }
      .score-seg.a { background: #94a3b8; }
      .score-seg.s { background: #1e8449; }
      .score-legend { display: flex; gap: .9rem; flex-wrap: wrap; font-size: .78rem;
                      color: #5d6d7e; margin-top: .3rem; }
      .score-legend .dot { display: inline-block; width: 8px; height: 8px;
                           border-radius: 2px; margin-right: .3rem; vertical-align: baseline; }
      .score-legend .dot.c { background: #c0392b; }
      .score-legend .dot.a { background: #94a3b8; }
      .score-legend .dot.s { background: #1e8449; }
      .score-dis { color: #b8860b; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- Neo4j access
@st.cache_resource(show_spinner=False)
def get_driver():
    """One shared driver for the app session. Mirrors step09's connect() config."""
    from neo4j import GraphDatabase

    load_dotenv(REPO_ROOT / ".env")
    uri = os.getenv("NEO4J_URI", NEO4J_URI_DEFAULT)
    user = os.getenv("NEO4J_USER", NEO4J_USER_DEFAULT)
    pwd = os.getenv("NEO4J_PASSWORD", NEO4J_PASSWORD_DEFAULT)
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    driver.verify_connectivity()  # raises if the DB is down — caught by the caller
    return driver


def _database() -> Optional[str]:
    return os.getenv("NEO4J_DATABASE") or None


@st.cache_data(show_spinner=False)
def list_tickers() -> List[str]:
    """Tickers that have an advisory layer (crosscheck_ticker set by the sync)."""
    driver = get_driver()
    with driver.session(database=_database()) as s:
        rows = s.run(
            "MATCH (c:SustainabilityClaim) WHERE c.crosscheck_ticker IS NOT NULL "
            "RETURN DISTINCT c.crosscheck_ticker AS t ORDER BY t"
        )
        tickers = [r["t"] for r in rows if r["t"]]
    return tickers or ["AAA"]


@st.cache_data(show_spinner=True)
def load_dossiers(ticker: str) -> Tuple[str, List[Dict[str, Any]], Dict[str, int]]:
    """Return (issuer_name, dossiers, conduct_pool).

    Queries mirror step09_report_claim_ledger.load_from_neo4j / crosscheck_queries.cypher,
    but return gracefully (empty) instead of sys.exit so the UI can show guidance. The
    dossier shape matches the P4 dossier so step09's build_header / _sort_key work as-is.
    """
    t = ticker.upper()
    driver = get_driver()
    with driver.session(database=_database()) as s:
        name_row = s.run(
            "MATCH (o:Organization {ticker:$t}) RETURN o.name AS name LIMIT 1", t=t
        ).single()
        issuer_name = name_row["name"] if name_row and name_row["name"] else ticker

        claim_rows = list(s.run(
            "MATCH (c:SustainabilityClaim {crosscheck_ticker:$t}) "
            "RETURN c._node_key AS key, c.claim_id AS claim_id, c.description AS text, "
            "       c.date AS year, c.source_type AS src, c.assessment AS assessment, "
            "       c.caveats AS caveats, c.structural_contradiction AS struct, "
            "       c.kpi_gap AS kpi_gap, "
            "       c.score_contradicted AS score_c, c.score_supported AS score_s, "
            "       c.score_abstain AS score_a, c.score_disagrees_with_assessment AS score_dis, "
            "       c.source_doc AS source_doc, c.source_page AS source_page, "
            "       c.source AS source_free",
            t=t))

        edge_rows = list(s.run(
            "MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})-[x]->(e) "
            "WHERE x.llm_suggested = true "
            "RETURN c._node_key AS key, x.role AS role, x.evidence_class AS class, "
            "       x.evidence_text AS text, x.year AS year, "
            "       x.date AS date, x.confidence AS confidence, x.rationale AS rationale, "
            "       x.provider AS provider, x.independent AS independent, "
            "       x.date_uncertain AS date_uncertain, "
            # provenance lives on the evidence node itself (step05b patch / step02 stamp).
            # x.source_domain is often an empty string (not null), so coalesce alone would
            # keep '' and drop the real news domain — treat '' as missing.
            "       coalesce(CASE WHEN x.source_domain <> '' THEN x.source_domain END, "
            "                e.source_domain) AS source_domain, "
            "       e.source_doc AS e_source_doc, e.source_page AS e_source_page, "
            "       e.article_title AS e_article_title",
            t=t))

        conduct_pool: Dict[str, int] = {}
        for row in s.run(
                "MATCH (n) WHERE n.source_type='news' AND "
                "any(l IN labels(n) WHERE l IN $classes) "
                "RETURN [l IN labels(n) WHERE l <> '_Entity'][0] AS cls, count(*) AS c",
                classes=CONDUCT_CLASSES):
            conduct_pool[row["cls"]] = row["c"]

    dossiers: Dict[str, Dict[str, Any]] = {}
    for r in claim_rows:
        dossiers[r["key"]] = {
            "claim_id": r["claim_id"], "claim_text": r["text"], "year": r["year"],
            "claim_source_type": r["src"] or "report", "assessment": r["assessment"],
            "supporting_evidence": [], "contradicting_evidence": [],
            "flagged_non_independent_support": [],
            "signals": {"structural_contradiction": bool(r["struct"]),
                        "kpi_gap": bool(r["kpi_gap"])},
            "caveats": list(r["caveats"] or []),
            # step07b evidence-balance scores (docs/SOFTMAX_SCORING.md); None before enrichment.
            "assessment_scores": ({"contradicted": r["score_c"], "supported": r["score_s"],
                                   "abstain": r["score_a"]} if r["score_c"] is not None else None),
            "score_disagrees_with_assessment": bool(r["score_dis"]),
            "source_doc": r["source_doc"], "source_page": r["source_page"],
            "source_free": r["source_free"],
        }
    for r in edge_rows:
        d = dossiers.get(r["key"])
        if not d:
            continue
        bucket = ROLE_BUCKET.get(r["role"])
        if not bucket:
            continue
        d[bucket].append({
            "class": r["class"], "text": r["text"], "source_domain": r["source_domain"],
            "year": r["year"], "date": r["date"], "confidence": r["confidence"],
            "rationale": r["rationale"], "provider": r["provider"],
            "independent": r["independent"], "date_uncertain": r["date_uncertain"],
            "source_doc": r["e_source_doc"], "source_page": r["e_source_page"],
            "article_title": r["e_article_title"],
        })
    return issuer_name, list(dossiers.values()), conduct_pool


# --------------------------------------------------------------------------- render helpers
def esc(text: Any) -> str:
    return html_lib.escape(str(text if text is not None else ""))


def _ev_year(ev: Dict[str, Any]) -> str:
    return str(ev.get("year") or ev.get("date") or "?")


def provenance_label(source_doc: Any, source_page: Any, article_title: Any,
                     source_domain: Any, fallback: str = "") -> str:
    """Nguồn tham chiếu, HTML-escaped: '📰 <tên bài báo> · <domain>' cho tin tức,
    '📄 <tên báo cáo> · tr. <trang>' cho báo cáo; fallback (vd c.source) khi node
    chưa được đóng dấu provenance (step05b)."""
    if article_title:
        label = f"📰 {esc(_truncate(str(article_title), 80))}"
        if source_domain:
            label += f" · {esc(source_domain)}"
        return label
    if source_doc:
        label = f"📄 {esc(source_doc)}"
        if source_page is not None:
            label += f" · tr. {esc(source_page)}"
        return label
    return esc(fallback) if fallback else ""


# kind -> (nhãn kết nối giữa báo cáo và bằng chứng, nhãn phía bằng chứng)
CONNECTOR = {
    "c": ("⚡ mâu thuẫn với", "🔎 Bằng chứng độc lập cho thấy"),
    "s": ("✓ được xác nhận bởi", "🔎 Bằng chứng độc lập xác nhận"),
    "f": ("⚑ có vẻ khớp với", "🔎 Nguồn không độc lập cho thấy"),
}


def evidence_html(claim_text: str, ev: Dict[str, Any], kind: str, maxlen: int, note: str = "") -> str:
    conf = ev.get("confidence")
    conf_s = f"độ tin cậy {float(conf):.2f}" if conf is not None else "độ tin cậy ?"
    dom = ev.get("source_domain") or ""
    src_ref = provenance_label(ev.get("source_doc"), ev.get("source_page"),
                               ev.get("article_title"), dom)
    # the news branch already prints the domain — don't repeat it
    dom_s = "" if (src_ref and ev.get("article_title")) else (f" · {esc(dom)}" if dom else "")
    src_ref_s = f" · {src_ref}" if src_ref else ""
    unc = " · ngày không chắc chắn" if ev.get("date_uncertain") else ""
    prov = ev.get("provider")
    prov_s = f" · {esc(prov)}" if prov else ""
    meta = (f"{esc(ev.get('class', '?'))} · {conf_s} · {esc(_ev_year(ev))}"
            f"{unc}{dom_s}{src_ref_s}{prov_s}{note}")

    connector_label, evidence_label = CONNECTOR.get(kind, CONNECTOR["f"])
    claim_row = (f'<div class="cmp claim-side">'
                 f'<div class="cmp-label">📄 Báo cáo nói</div>'
                 f'<div class="cmp-text">"{esc(_truncate(claim_text, min(maxlen, 220)))}"</div>'
                 f'</div>')
    connector_row = f'<div class="vs {kind}">{connector_label}</div>'
    evidence_row = (f'<div class="cmp evidence-side">'
                    f'<div class="cmp-label">{evidence_label}</div>'
                    f'<div class="cmp-text">"{esc(_truncate(ev.get("text", ""), maxlen))}"</div>'
                    f'</div>')

    rat = ev.get("rationale")
    rat_html = (f'<div class="rat">💭 Nhận định của LLM: '
                f'{esc(_truncate(rat, maxlen + 120))}</div>') if rat else ""
    return (f'<div class="evi {kind}">'
            f'<div class="meta">{meta}</div>'
            f'{claim_row}{connector_row}{evidence_row}'
            f'{rat_html}</div>')


# Thứ tự đoạn: đỏ | xám | xanh — abstain (trung tính) nằm giữa hai cực, đúng layout
# diverging và tách đỏ khỏi xanh cho người mù màu (validator: ΔE deutan 5.0 → 17.9).
SCORE_SEGMENTS = (
    ("contradicted", "mâu thuẫn", "c"),
    ("abstain", "chưa đủ bằng chứng", "a"),
    ("supported", "xác nhận", "s"),
)


def score_bar_html(d: Dict[str, Any]) -> str:
    """Evidence-balance bar (step07b). Empty string when the dossier isn't enriched yet."""
    scores = d.get("assessment_scores") or {}
    if scores.get("contradicted") is None:
        return ""
    segs, legend = [], []
    for key, label, cls in SCORE_SEGMENTS:
        v = float(scores.get(key) or 0.0)
        if v > 0.001:
            segs.append(f'<div class="score-seg {cls}" style="flex:{v:.4f}"></div>')
        legend.append(f'<span><span class="dot {cls}"></span>{esc(label)} {v:.2f}</span>')
    dis = ('<span class="score-dis">⚖ điểm lệch với nhãn — bằng chứng trái chiều</span>'
           if d.get("score_disagrees_with_assessment") else "")
    tooltip = ("Phân bố cân bằng bằng chứng đã liên kết cho tuyên bố này (softmax offline, "
               "tái lập được — docs/SOFTMAX_SCORING.md). KHÔNG phải xác suất greenwashing.")
    return (f'<div class="score-wrap" title="{esc(tooltip)}">'
            f'<div class="score-title">Cân bằng bằng chứng '
            f'<span class="score-note">— không phải xác suất greenwashing</span></div>'
            f'<div class="score-bar">{"".join(segs)}</div>'
            f'<div class="score-legend">{"".join(legend)}{dis}</div></div>')


def claim_card_html(d: Dict[str, Any], maxlen: int) -> str:
    assessment = d.get("assessment", "unverified_insufficient_evidence")
    _label, _emoji, cls = ASSESSMENT_META.get(
        assessment, ("Chưa xác minh / thiếu bằng chứng", "•", "unverified"))
    badge = f'<span class="badge {cls}">{_emoji} {esc(_label)} · tham khảo</span>'
    src = CLAIM_SOURCE_LABEL.get(d.get("claim_source_type", "report"), d.get("claim_source_type", "report"))
    src_ref = provenance_label(d.get("source_doc"), d.get("source_page"), None, None,
                               fallback=d.get("source_free") or "")
    src_ref_s = f" · {src_ref}" if src_ref else ""
    head = (f'<div class="claim-head">'
            f'<span class="claim-id">{esc(d.get("claim_id", "?"))} · '
            f'{esc(d.get("year", "?"))} · nguồn={esc(src)}{src_ref_s}</span>'
            f'{badge}</div>')
    text = f'<div class="claim-text">{esc(_truncate(d.get("claim_text", ""), maxlen))}</div>'
    score_bar = score_bar_html(d)

    claim_text = d.get("claim_text", "")
    evi = []
    for ev in d.get("contradicting_evidence", []):
        evi.append(evidence_html(claim_text, ev, "c", maxlen))
    for ev in d.get("supporting_evidence", []):
        evi.append(evidence_html(claim_text, ev, "s", maxlen))
    for ev in d.get("flagged_non_independent_support", []):
        evi.append(evidence_html(claim_text, ev, "f", maxlen,
                                  note=" · miền của công ty — không được tính"))
    evi_html = "".join(evi) or '<div class="sig">Không có bằng chứng hành vi liên kết.</div>'

    sig = d.get("signals", {}) or {}
    sig_html = (f'<div class="sig">tín hiệu: mâu thuẫn cấu trúc='
                f'{"có" if sig.get("structural_contradiction") else "không"} · '
                f'khoảng trống KPI={"có" if sig.get("kpi_gap") else "không"}</div>')

    caveats = d.get("caveats", []) or []
    cav_html = ""
    if caveats:
        items = "".join(f"<li>{esc(c)}</li>" for c in caveats)
        cav_html = f'<div class="caveats"><b>Lưu ý:</b><ul>{items}</ul></div>'

    return (f'<div class="claim-card {cls}">{head}{text}{score_bar}{evi_html}{sig_html}{cav_html}</div>')


def chip(n: int, label: str, cls: str) -> str:
    return f'<div class="chip {cls}"><div class="n">{n}</div><div class="l">{esc(label)}</div></div>'


# --------------------------------------------------------------------------- app body
st.markdown('<div class="gw-title">🌿 Trình khám phá Bằng chứng Greenwashing</div>',
            unsafe_allow_html=True)
st.markdown('<div class="gw-sub">Các tuyên bố ESG mà công ty <b>công bố</b> có đứng vững trước '
            'bằng chứng <b>độc lập</b> về những gì công ty thực sự đã làm hay không? '
            'Nhập mã công ty để xem lại bằng chứng.</div>', unsafe_allow_html=True)

# Connect up front; fail with clear guidance rather than a stack trace.
try:
    get_driver()
    conn_ok = True
except Exception as e:  # noqa: BLE001
    conn_ok = False
    st.error(
        "**Không thể kết nối tới Neo4j.** Hãy khởi động database (bước 5) và nạp graph trước.\n\n"
        f"```\ndocker compose up -d\n```\n\nURI `{os.getenv('NEO4J_URI', NEO4J_URI_DEFAULT)}` "
        f"— chi tiết lỗi: `{e}`")
    st.stop()

tickers = list_tickers()

with st.sidebar:
    st.header("Công ty")
    ticker = st.selectbox("Mã công ty (ticker)", tickers, index=0)
    if st.button("↻ Làm mới từ Neo4j", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.header("Bộ lọc")
    view = st.radio(
        "Hiển thị",
        ["Có tín hiệu (mặc định)", "Có vẻ mâu thuẫn", "Có vẻ được xác nhận",
         "Chưa xác minh / thiếu bằng chứng", "Tất cả", "Hàng đợi cần xem xét"],
        help="Có tín hiệu = mâu thuẫn + được xác nhận (giống mặc định của CLI). "
             "Hàng đợi cần xem xét = có mâu thuẫn nhưng KHÔNG có xác minh độc lập.",
    )
    query = st.text_input("Tìm trong nội dung tuyên bố", "").strip().lower()
    limit = st.slider("Số tuyên bố tối đa hiển thị", 10, 500, 50, step=10)
    maxlen = st.slider("Giới hạn độ dài văn bản (ký tự)", 120, 1000, 320, step=20)

    st.divider()
    st.caption("Chế độ chỉ xem của lớp tham khảo (advisory) trong Neo4j "
               "(`src/step08_sync_crosscheck_to_neo4j.py`). Không gọi LLM, không có kết luận "
               "cuối cùng; thanh cân bằng bằng chứng là lớp advisory tính offline "
               "(`src/step07b_enrich_dossiers.py`), không phải xác suất greenwashing.")

name, dossiers, conduct_pool = load_dossiers(ticker)

if not dossiers:
    st.warning(
        f"Không tìm thấy tuyên bố nào đã được đánh giá cho **{ticker}** trong Neo4j.\n\n"
        "Hãy chạy đồng bộ cross-check một lần (miễn phí, không tốn token):\n\n"
        "```\npython src/step08_sync_crosscheck_to_neo4j.py --ticker "
        f"{ticker}\n```")
    st.stop()

header = build_header(ticker, name, dossiers, conduct_pool)
counts = header["counts"]

# --- issuer header -----------------------------------------------------------------------
st.subheader(f"{ticker} — {name}")
st.markdown(
    '<div class="chips">'
    + chip(header["total"], "tuyên bố", "total")
    + chip(counts["appears_contradicted"], "có vẻ mâu thuẫn", "contradicted")
    + chip(counts["appears_supported"], "có vẻ được xác nhận", "supported")
    + chip(counts["unverified_insufficient_evidence"], "chưa xác minh / thiếu bằng chứng", "unverified")
    + "</div>",
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="advisory-banner">⚠ <b>Chỉ mang tính tham khảo.</b> Không có kết luận '
    'greenwashing — mỗi đánh giá là một ý kiến do LLM hỗ trợ, dành cho con người xem xét lại; '
    'không tồn tại nhãn chuẩn (ground-truth) nào (xem <code>docs/SYSTEM_DESIGN.md</code> §1.1). '
    'Thanh <b>cân bằng bằng chứng</b> trên mỗi tuyên bố là phân bố chuẩn hóa của bằng chứng '
    'đã liên kết (tính offline, tái lập được — <code>docs/SOFTMAX_SCORING.md</code>), '
    '<b>không phải</b> xác suất greenwashing. Mọi mục đều dẫn tới nguồn để bạn tự kiểm chứng.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="coverage-caveat">🛈 <b>Bằng chứng hành vi độc lập về công ty:</b> '
    f'{esc(header["conduct_bits"])}. &nbsp; {esc(COVERAGE_CAVEAT_VI)}</div>',
    unsafe_allow_html=True,
)

# --- filter + sort -----------------------------------------------------------------------
VIEW_TO_ASSESSMENT = {
    "Có vẻ mâu thuẫn": "appears_contradicted",
    "Có vẻ được xác nhận": "appears_supported",
    "Chưa xác minh / thiếu bằng chứng": "unverified_insufficient_evidence",
}

if view == "Hàng đợi cần xem xét":
    selected = [d for d in dossiers if is_review_queue(d)]
elif view == "Tất cả":
    selected = list(dossiers)
elif view in VIEW_TO_ASSESSMENT:
    selected = [d for d in dossiers if d.get("assessment") == VIEW_TO_ASSESSMENT[view]]
else:  # Có tín hiệu (mặc định)
    selected = [d for d in dossiers
                if d.get("assessment") in ("appears_contradicted", "appears_supported")]

if query:
    selected = [d for d in selected if query in (d.get("claim_text") or "").lower()
                or query in (d.get("claim_id") or "").lower()]

selected.sort(key=_sort_key)
total_matched = len(selected)
shown = selected[:limit]

if view == "Hàng đợi cần xem xét":
    st.markdown(f"#### Hàng đợi cần xem xét — mâu thuẫn nhưng không có xác minh độc lập "
                f"({total_matched})")
else:
    st.markdown(f"#### Tuyên bố ({total_matched} khớp bộ lọc này"
                + (f", đang hiển thị {len(shown)}" if total_matched > len(shown) else "") + ")")

if not shown:
    st.info("Không có tuyên bố nào khớp bộ lọc này.")
else:
    st.markdown("".join(claim_card_html(d, maxlen) for d in shown), unsafe_allow_html=True)
    if total_matched > len(shown):
        st.caption(f"… còn {total_matched - len(shown)} tuyên bố chưa hiển thị — tăng "
                   "“Số tuyên bố tối đa hiển thị” ở thanh bên.")

st.divider()
st.caption("Greenwashing Graph-RAG · bằng chứng + ý kiến tham khảo, không phải kết luận cuối cùng · "
           "dữ liệu đọc trực tiếp từ Neo4j · docs/SYSTEM_DESIGN.md")
