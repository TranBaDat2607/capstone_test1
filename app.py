"""Greenwashing evidence explorer — demo UI (Streamlit).

A company-code lookup over the temporal ESG knowledge graph. Enter a ticker and the
app renders that issuer's **claim ledger**: every SustainabilityClaim beside the conduct
evidence that supports or contradicts it, plus an explicitly **advisory** assessment.

This is the web front-end for Step 7 (docs/SYSTEM_DESIGN.md §9, docs/CLAIM_LEDGER.md).
It reads ONLY from the Neo4j advisory layer that `src/step08_sync_crosscheck_to_neo4j.py`
wrote (claim `assessment`/`caveats`/`signals` + `llm_supports`/`llm_contradicts`/
`llm_flagged_support` edges). It makes **no** LLM call — deterministic, traceable,
same-input→same-evidence — and it never emits a greenwashing score or verdict
(SYSTEM_DESIGN §1.1: no ground truth ⇒ evidence + advisory opinion only).

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
    COVERAGE_CAVEAT,
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

ASSESSMENT_META = {  # label, emoji, css class — the three advisory buckets (§1.1)
    "appears_contradicted": ("Appears contradicted", "✗", "contradicted"),
    "appears_supported": ("Appears supported", "✓", "supported"),
    "unverified_insufficient_evidence": ("Unverified / insufficient", "•", "unverified"),
}

# --------------------------------------------------------------------------- page + style
st.set_page_config(
    page_title="Greenwashing Evidence Explorer",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; max-width: 1150px; }
      .gw-title { font-size: 1.9rem; font-weight: 700; margin-bottom: .1rem; }
      .gw-sub   { color: #6b7280; font-size: .95rem; margin-bottom: 1rem; }

      .advisory-banner {
        background: #fff8e1; border: 1px solid #f0d58a; color: #7a5c00;
        border-radius: 8px; padding: .6rem .9rem; font-size: .88rem; margin-bottom: 1rem;
      }
      .coverage-caveat {
        background: #eef2f7; border-left: 4px solid #94a3b8; color: #475569;
        border-radius: 6px; padding: .55rem .8rem; font-size: .85rem; margin: .3rem 0 1.1rem 0;
      }

      /* metric chips */
      .chips { display: flex; gap: .6rem; flex-wrap: wrap; margin: .2rem 0 .6rem 0; }
      .chip { border-radius: 10px; padding: .55rem .9rem; min-width: 120px; border: 1px solid; }
      .chip .n { font-size: 1.5rem; font-weight: 700; line-height: 1; }
      .chip .l { font-size: .74rem; text-transform: uppercase; letter-spacing: .03em; opacity: .8; }
      .chip.total       { background:#f3f4f6; border-color:#d1d5db; color:#374151; }
      .chip.contradicted{ background:#fdecea; border-color:#f5b7b1; color:#a93226; }
      .chip.supported   { background:#eafaf1; border-color:#a9dfbf; color:#1e8449; }
      .chip.unverified  { background:#f4f6f7; border-color:#d5dbdb; color:#5d6d7e; }

      /* claim card */
      .claim-card {
        border: 1px solid #e5e7eb; border-left-width: 5px; border-radius: 10px;
        padding: .85rem 1.05rem; margin-bottom: .9rem; background: #ffffff;
      }
      .claim-card.contradicted { border-left-color: #c0392b; }
      .claim-card.supported    { border-left-color: #1e8449; }
      .claim-card.unverified   { border-left-color: #b0b7bd; }
      .claim-head { display:flex; justify-content:space-between; gap:1rem; align-items:baseline; }
      .claim-id { font-family: ui-monospace, monospace; font-size: .8rem; color:#6b7280; }
      .claim-text { font-size: 1.02rem; font-weight: 600; margin: .35rem 0 .55rem 0; color:#1f2937; }

      .badge { border-radius: 999px; padding: .12rem .6rem; font-size: .74rem; font-weight:600;
               white-space: nowrap; }
      .badge.contradicted { background:#fdecea; color:#a93226; }
      .badge.supported    { background:#eafaf1; color:#1e8449; }
      .badge.unverified   { background:#eef1f3; color:#5d6d7e; }

      .evi { border-radius: 7px; padding: .5rem .7rem; margin: .4rem 0; font-size: .9rem; }
      .evi.c { background:#fdf0ee; border-left:3px solid #c0392b; }
      .evi.s { background:#eef8f2; border-left:3px solid #1e8449; }
      .evi.f { background:#fef6e7; border-left:3px solid #d68910; }
      .evi .meta { font-size: .76rem; color:#6b7280; margin-bottom: .15rem; }
      .evi .txt  { color:#374151; }
      .evi .rat  { font-size: .82rem; color:#6b7280; font-style: italic; margin-top:.2rem; }

      .caveats { font-size: .8rem; color:#6b7280; margin-top:.55rem; }
      .caveats li { margin: .05rem 0; }
      .sig { font-size: .78rem; color:#8a94a0; margin-top:.35rem; }
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
            "       c.kpi_gap AS kpi_gap",
            t=t))

        edge_rows = list(s.run(
            "MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})-[x]->(e) "
            "WHERE x.llm_suggested = true "
            "RETURN c._node_key AS key, x.role AS role, x.evidence_class AS class, "
            "       x.evidence_text AS text, x.source_domain AS source_domain, x.year AS year, "
            "       x.date AS date, x.confidence AS confidence, x.rationale AS rationale, "
            "       x.provider AS provider, x.independent AS independent, "
            "       x.date_uncertain AS date_uncertain",
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
        })
    return issuer_name, list(dossiers.values()), conduct_pool


# --------------------------------------------------------------------------- render helpers
def esc(text: Any) -> str:
    return html_lib.escape(str(text if text is not None else ""))


def _ev_year(ev: Dict[str, Any]) -> str:
    return str(ev.get("year") or ev.get("date") or "?")


def evidence_html(ev: Dict[str, Any], kind: str, maxlen: int, note: str = "") -> str:
    conf = ev.get("confidence")
    conf_s = f"conf {float(conf):.2f}" if conf is not None else "conf ?"
    dom = ev.get("source_domain") or ""
    dom_s = f" · {esc(dom)}" if dom else ""
    unc = " · date uncertain" if ev.get("date_uncertain") else ""
    prov = ev.get("provider")
    prov_s = f" · {esc(prov)}" if prov else ""
    meta = (f"{esc(ev.get('class', '?'))} · {conf_s} · {esc(_ev_year(ev))}"
            f"{unc}{dom_s}{prov_s}{note}")
    rat = ev.get("rationale")
    rat_html = f'<div class="rat">↳ {esc(_truncate(rat, maxlen + 120))}</div>' if rat else ""
    return (f'<div class="evi {kind}">'
            f'<div class="meta">{meta}</div>'
            f'<div class="txt">"{esc(_truncate(ev.get("text", ""), maxlen))}"</div>'
            f'{rat_html}</div>')


def claim_card_html(d: Dict[str, Any], maxlen: int) -> str:
    assessment = d.get("assessment", "unverified_insufficient_evidence")
    _label, _emoji, cls = ASSESSMENT_META.get(
        assessment, ("Unverified / insufficient", "•", "unverified"))
    badge = f'<span class="badge {cls}">{_emoji} {esc(_label)} · advisory</span>'
    head = (f'<div class="claim-head">'
            f'<span class="claim-id">{esc(d.get("claim_id", "?"))} · '
            f'{esc(d.get("year", "?"))} · source={esc(d.get("claim_source_type", "report"))}</span>'
            f'{badge}</div>')
    text = f'<div class="claim-text">{esc(_truncate(d.get("claim_text", ""), maxlen))}</div>'

    evi = []
    for ev in d.get("contradicting_evidence", []):
        evi.append(evidence_html(ev, "c", maxlen))
    for ev in d.get("supporting_evidence", []):
        evi.append(evidence_html(ev, "s", maxlen))
    for ev in d.get("flagged_non_independent_support", []):
        evi.append(evidence_html(ev, "f", maxlen, note=" · company domain — not counted"))
    evi_html = "".join(evi) or '<div class="sig">No linked conduct evidence.</div>'

    sig = d.get("signals", {}) or {}
    sig_html = (f'<div class="sig">signals: structural_contradiction='
                f'{str(bool(sig.get("structural_contradiction"))).lower()} · '
                f'kpi_gap={"yes" if sig.get("kpi_gap") else "none"}</div>')

    caveats = d.get("caveats", []) or []
    cav_html = ""
    if caveats:
        items = "".join(f"<li>{esc(c)}</li>" for c in caveats)
        cav_html = f'<div class="caveats"><b>Caveats:</b><ul>{items}</ul></div>'

    return (f'<div class="claim-card {cls}">{head}{text}{evi_html}{sig_html}{cav_html}</div>')


def chip(n: int, label: str, cls: str) -> str:
    return f'<div class="chip {cls}"><div class="n">{n}</div><div class="l">{esc(label)}</div></div>'


# --------------------------------------------------------------------------- app body
st.markdown('<div class="gw-title">🌿 Greenwashing Evidence Explorer</div>',
            unsafe_allow_html=True)
st.markdown('<div class="gw-sub">Do a company\'s <b>reported</b> ESG claims hold up against '
            '<b>independent</b> evidence of what it actually did? '
            'Enter a company code to review the evidence.</div>', unsafe_allow_html=True)

# Connect up front; fail with clear guidance rather than a stack trace.
try:
    get_driver()
    conn_ok = True
except Exception as e:  # noqa: BLE001
    conn_ok = False
    st.error(
        "**Cannot connect to Neo4j.** Start the step-5 database and load the graph first.\n\n"
        f"```\ndocker compose up -d\n```\n\nURI `{os.getenv('NEO4J_URI', NEO4J_URI_DEFAULT)}` "
        f"— details: `{e}`")
    st.stop()

tickers = list_tickers()

with st.sidebar:
    st.header("Company")
    ticker = st.selectbox("Company code (ticker)", tickers, index=0)
    if st.button("↻ Refresh from Neo4j", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.header("Filters")
    view = st.radio(
        "Show",
        ["Signal-bearing (default)", "Appears contradicted", "Appears supported",
         "Unverified / insufficient", "All", "Review queue"],
        help="Signal-bearing = contradicted + supported (mirrors the CLI default). "
             "Review queue = contradiction with NO independent verification (the schema payoff).",
    )
    query = st.text_input("Search claim text", "").strip().lower()
    limit = st.slider("Max claims shown", 10, 500, 50, step=10)
    maxlen = st.slider("Truncate text (chars)", 120, 1000, 320, step=20)

    st.divider()
    st.caption("Read-only view of the Neo4j advisory layer "
               "(`src/step08_sync_crosscheck_to_neo4j.py`). No LLM call, no score, no verdict.")

name, dossiers, conduct_pool = load_dossiers(ticker)

if not dossiers:
    st.warning(
        f"No assessed claims found for **{ticker}** in Neo4j.\n\n"
        "Run the cross-check sync once (free, no tokens):\n\n"
        "```\npython src/step08_sync_crosscheck_to_neo4j.py --ticker "
        f"{ticker}\n```")
    st.stop()

header = build_header(ticker, name, dossiers, conduct_pool)
counts = header["counts"]

# --- issuer header -----------------------------------------------------------------------
st.subheader(f"{ticker} — {name}")
st.markdown(
    '<div class="chips">'
    + chip(header["total"], "claims", "total")
    + chip(counts["appears_contradicted"], "appears contradicted", "contradicted")
    + chip(counts["appears_supported"], "appears supported", "supported")
    + chip(counts["unverified_insufficient_evidence"], "unverified / insufficient", "unverified")
    + "</div>",
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="advisory-banner">⚠ <b>Advisory only.</b> No greenwashing score or verdict — '
    'each assessment is an LLM-assisted opinion for human review; there is no ground-truth label '
    '(see <code>docs/SYSTEM_DESIGN.md</code> §1.1). Every item links to its source for '
    'verification.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="coverage-caveat">🛈 <b>Independent conduct on the issuer:</b> '
    f'{esc(header["conduct_bits"])}. &nbsp; {esc(COVERAGE_CAVEAT)}</div>',
    unsafe_allow_html=True,
)

# --- filter + sort -----------------------------------------------------------------------
VIEW_TO_ASSESSMENT = {
    "Appears contradicted": "appears_contradicted",
    "Appears supported": "appears_supported",
    "Unverified / insufficient": "unverified_insufficient_evidence",
}

if view == "Review queue":
    selected = [d for d in dossiers if is_review_queue(d)]
elif view == "All":
    selected = list(dossiers)
elif view in VIEW_TO_ASSESSMENT:
    selected = [d for d in dossiers if d.get("assessment") == VIEW_TO_ASSESSMENT[view]]
else:  # Signal-bearing (default)
    selected = [d for d in dossiers
                if d.get("assessment") in ("appears_contradicted", "appears_supported")]

if query:
    selected = [d for d in selected if query in (d.get("claim_text") or "").lower()
                or query in (d.get("claim_id") or "").lower()]

selected.sort(key=_sort_key)
total_matched = len(selected)
shown = selected[:limit]

if view == "Review queue":
    st.markdown(f"#### Review queue — contradiction with no independent verification "
                f"({total_matched})")
else:
    st.markdown(f"#### Claims ({total_matched} match this filter"
                + (f", showing {len(shown)}" if total_matched > len(shown) else "") + ")")

if not shown:
    st.info("No claims match this filter.")
else:
    st.markdown("".join(claim_card_html(d, maxlen) for d in shown), unsafe_allow_html=True)
    if total_matched > len(shown):
        st.caption(f"… {total_matched - len(shown)} more not shown — raise “Max claims shown” "
                   "in the sidebar.")

st.divider()
st.caption("Greenwashing Graph-RAG · evidence + advisory opinion, never a verdict · "
           "data read live from Neo4j · docs/SYSTEM_DESIGN.md")
