"""Step 7 / P5 — the per-company claim ledger, read entirely from Neo4j.

System context: docs/SYSTEM_DESIGN.md §9 and docs/CLAIM_LEDGER.md.

This is the final presentation stage. It reads the advisory cross-check layer that
`esg_kg.load.neo4j_sync` (step08) wrote into Neo4j (claim `assessment`/`caveats`/`signals`
props + `llm_supports` / `llm_contradicts` / `llm_flagged_support` evidence edges) and renders
a human-readable claim ledger. It makes **no** LLM call and reads **only** from Neo4j — the
JSON dossier is no longer touched here (it lives one step upstream, in the sync).

Prereq: run the sync once (free, no tokens):
    python src_module/run.py neo4j_sync

Non-negotiable framing (SYSTEM_DESIGN §1.1): evidence + an explicitly advisory opinion,
never a greenwashing verdict. The step07b evidence-balance scores, when present, are
rendered with the same caveat (normalized evidence weights, not probabilities).

Run from the repo root:
    python src_module/run.py claim_ledger                       # AAA ledger (contradicted + supported)
    python src_module/run.py claim_ledger --review-queue        # contradiction, no independent verification
    python src_module/run.py claim_ledger --assessment all --markdown
    python src_module/run.py claim_ledger --claim-id AAA_SC_001

MIGRATED FROM ``src/step09_report_claim_ledger.py`` (2026-07-29), verbatim except the
docstring and the import block: ``REPO_ROOT`` now comes from ``esg_kg.core.paths`` (the same
swap every leaf stage has made since step01), even though this stage imports nothing else
from a sibling — it never was a hub, per PIPELINE.md §2.1 ("không import stage nào"). No
logic line differs. This is the FIRST Neo4j-READ stage to migrate (``neo4j_load``/step06 and
``neo4j_sync``/step08 only ever write): ``load_from_neo4j`` consumes what Neo4j hands back
and builds dossier dicts from it, so ``test/test_esg_kg_claim_ledger.py`` cannot get away
with a fake driver that merely records calls — it feeds both trees an identical queue of
canned rows and compares both the Cypher sent AND the dossiers assembled from those rows.
There is also no real-corpus arm here, unlike every prior migration: this stage reads only
Neo4j, and CLAUDE.md's TDD rule requires tests to stay offline, so the strongest available
coverage is the pure rendering/sorting functions (which carry the bulk of the stage's actual
logic) plus the canned-driver arm.
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from esg_kg.core.paths import REPO_ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "crosscheck"   # markdown output location only

# Neo4j defaults — match esg_kg.load.neo4j_load + the sync.
NEO4J_URI_DEFAULT = "bolt://localhost:8687"
NEO4J_USER_DEFAULT = "greenwashing"
NEO4J_PASSWORD_DEFAULT = "nammovuivui"

# Conduct-side classes counted for the coverage header (mirrors the crosscheck conduct pool).
CONDUCT_CLASSES = ["Controversy", "Penalty", "MediaReport", "KPIObservation", "ThirdPartyVerification"]
COVERAGE_CAVEAT = ("Thin independent conduct — absence of contradiction is NOT exoneration "
                   "(docs/SYSTEM_DESIGN.md §8.3).")

ASSESSMENT_ORDER = {
    "appears_contradicted": 0,
    "appears_supported": 1,
    "unverified_insufficient_evidence": 2,
}
ASSESSMENT_LABEL = {
    "appears_contradicted": "appears_contradicted",
    "appears_supported": "appears_supported",
    "unverified_insufficient_evidence": "unverified/insufficient",
}
# advisory edge role -> dossier evidence bucket
ROLE_BUCKET = {
    "support": "supporting_evidence",
    "contradict": "contradicting_evidence",
    "flagged": "flagged_non_independent_support",
}


# --------------------------------------------------------------------------- helpers
def _force_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # py3.7+, Windows PowerShell needs this
    except Exception:
        pass


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ev_year(ev: Dict[str, Any]) -> str:
    y = ev.get("year")
    if y:
        return str(y)
    d = ev.get("date")
    return str(d) if d else "?"


def is_review_queue(d: Dict[str, Any]) -> bool:
    """Schema payoff (SYSTEM_DESIGN §4.1/§9.2): contradiction AND no independent support."""
    return (d.get("assessment") == "appears_contradicted"
            and not d.get("supporting_evidence"))


def _sort_key(d: Dict[str, Any]):
    order = ASSESSMENT_ORDER.get(d.get("assessment"), 3)

    def _max_conf(items):
        return max((float(e.get("confidence") or 0.0) for e in items), default=0.0)

    if d.get("assessment") == "appears_contradicted":
        conf = _max_conf(d.get("contradicting_evidence", []))
    else:
        conf = _max_conf(d.get("supporting_evidence", []))
    year = d.get("year") or 0
    return (order, -conf, -int(year) if str(year).lstrip("-").isdigit() else 0)


# --------------------------------------------------------------------------- Neo4j read
def connect(args: argparse.Namespace):
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j driver not installed (pip install neo4j).")
        sys.exit(1)
    load_dotenv(REPO_ROOT / ".env")
    uri = args.uri or os.getenv("NEO4J_URI", NEO4J_URI_DEFAULT)
    user = args.user or os.getenv("NEO4J_USER", NEO4J_USER_DEFAULT)
    pwd = args.password or os.getenv("NEO4J_PASSWORD", NEO4J_PASSWORD_DEFAULT)
    database = args.database or os.getenv("NEO4J_DATABASE") or None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        driver.verify_connectivity()
    except Exception as e:
        logger.error(f"Cannot connect to Neo4j at {uri} ({e}). Is the step-5 DB up "
                     f"(docker compose up -d)?")
        sys.exit(1)
    return driver, database


def load_from_neo4j(driver, database: Optional[str], ticker: str):
    """Return (issuer_name, dossiers, conduct_pool). dossiers mimic the P4 dossier shape so
    the renderers below are source-agnostic."""
    t = ticker.upper()
    with driver.session(database=database) as s:
        name_row = s.run("MATCH (o:Organization {ticker:$t}) RETURN o.name AS name LIMIT 1",
                         t=t).single()
        issuer_name = (name_row["name"] if name_row and name_row["name"] else ticker)

        claim_rows = list(s.run(
            "MATCH (c:SustainabilityClaim {crosscheck_ticker:$t}) "
            "RETURN c._node_key AS key, c.claim_id AS claim_id, c.description AS text, "
            "       c.date AS year, c.source_type AS src, c.assessment AS assessment, "
            "       c.caveats AS caveats, c.structural_contradiction AS struct, c.kpi_gap AS kpi_gap, "
            "       c.score_contradicted AS score_c, c.score_supported AS score_s, "
            "       c.score_abstain AS score_a, c.score_disagrees_with_assessment AS score_dis, "
            "       c.source_doc AS source_doc, c.source_page AS source_page",
            t=t))
        if not claim_rows:
            logger.error(f"No claims with an assessment for ticker '{t}' in Neo4j. "
                         f"Run: python src_module/run.py neo4j_sync --ticker {t}")
            sys.exit(1)

        edge_rows = list(s.run(
            "MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})-[x]->(e) "
            "WHERE x.llm_suggested = true "
            "RETURN c._node_key AS key, x.role AS role, x.evidence_class AS class, "
            "       x.evidence_text AS text, x.source_domain AS source_domain, x.year AS year, "
            "       x.date AS date, x.confidence AS confidence, x.rationale AS rationale, "
            "       x.provider AS provider, x.independent AS independent, "
            "       x.date_uncertain AS date_uncertain, "
            # provenance lives on the evidence node itself (step05b patch / step02 stamp)
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

    # Assemble dossier-shaped dicts.
    dossiers: Dict[str, Dict[str, Any]] = {}
    for r in claim_rows:
        dossiers[r["key"]] = {
            "claim_id": r["claim_id"], "claim_text": r["text"], "year": r["year"],
            "claim_source_type": r["src"] or "report", "assessment": r["assessment"],
            "supporting_evidence": [], "contradicting_evidence": [],
            "flagged_non_independent_support": [],
            "signals": {"structural_contradiction": bool(r["struct"]), "kpi_gap": bool(r["kpi_gap"])},
            "caveats": list(r["caveats"] or []),
            # step07b evidence-balance scores (docs/SOFTMAX_SCORING.md); absent pre-enrichment.
            "assessment_scores": ({"contradicted": r["score_c"], "supported": r["score_s"],
                                   "abstain": r["score_a"]} if r["score_c"] is not None else None),
            "score_disagrees_with_assessment": bool(r["score_dis"]),
            "source_doc": r["source_doc"], "source_page": r["source_page"],
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


# --------------------------------------------------------------------------- rendering
def build_header(ticker: str, name: str, dossiers: List[Dict[str, Any]],
                 conduct_pool: Dict[str, int]) -> Dict[str, Any]:
    counts = {k: 0 for k in ASSESSMENT_ORDER}
    for d in dossiers:
        a = d.get("assessment", "unverified_insufficient_evidence")
        counts[a] = counts.get(a, 0) + 1
    conduct_bits = ", ".join(f"{v} {k}" for k, v in
                             sorted(conduct_pool.items(), key=lambda kv: -kv[1])) or "none"
    return {"ticker": ticker, "name": name, "total": len(dossiers), "counts": counts,
            "conduct_bits": conduct_bits}


def render_header_text(h: Dict[str, Any]) -> str:
    c = h["counts"]
    return "\n".join([
        "=" * 88,
        f"{h['ticker']} — {h['name']}",
        (f"  claims: {h['total']}  |  appears_supported: {c['appears_supported']}"
         f"  |  appears_contradicted: {c['appears_contradicted']}"
         f"  |  unverified/insufficient: {c['unverified_insufficient_evidence']}"),
        f"  ⚠ Independent conduct on the issuer: {h['conduct_bits']}.",
        f"    {COVERAGE_CAVEAT}",
        "  Advisory only — no greenwashing verdict; each assessment is an LLM-assisted "
        "opinion for human review, and the evidence-balance scores are normalized "
        "evidence weights, not probabilities.",
        f"  (source: Neo4j advisory layer — run src_module/run.py neo4j_sync to refresh)",
        "=" * 88,
    ])


def _source_ref(item: Dict[str, Any]) -> str:
    """Human-readable source reference: article title for news, 'doc p.N' for reports.
    Empty when the node was never provenance-stamped (step05b)."""
    title = item.get("article_title")
    if title:
        return _truncate(str(title), 80)
    doc = item.get("source_doc")
    if not doc:
        return ""
    page = item.get("source_page")
    return f"{doc} p.{page}" if page is not None else str(doc)


def render_entry_text(d: Dict[str, Any], maxlen: int) -> str:
    ref = _source_ref(d)
    ref = f"  [{ref}]" if ref else ""
    out = [
        f"CLAIM  {d.get('claim_id', '?')}   [{d.get('year', '?')}, source={d.get('claim_source_type', 'report')}]{ref}",
        f'  "{_truncate(d.get("claim_text", ""), maxlen)}"',
        f"  ASSESSMENT: {d.get('assessment', '?')} (advisory)",
    ]
    for ev in d.get("contradicting_evidence", []):
        out += _evidence_lines_text("✗", ev, maxlen)
    for ev in d.get("supporting_evidence", []):
        out += _evidence_lines_text("✓", ev, maxlen)
    for ev in d.get("flagged_non_independent_support", []):
        out += _evidence_lines_text("⚑", ev, maxlen, suffix=" [company domain — not counted]")
    scores = d.get("assessment_scores")
    if scores:
        dis = "  (argmax disagrees with assessment — mixed evidence)" \
            if d.get("score_disagrees_with_assessment") else ""
        out.append(f"  scores: contradicted={scores['contradicted']:.2f} · "
                   f"supported={scores['supported']:.2f} · abstain={scores['abstain']:.2f} "
                   f"(evidence balance, not a greenwashing probability){dis}")
    sig = d.get("signals", {}) or {}
    out.append(f"  signals: structural_contradiction={str(bool(sig.get('structural_contradiction'))).lower()}; "
               f"kpi_gap={'yes' if sig.get('kpi_gap') else 'none'}")
    caveats = d.get("caveats", []) or []
    if caveats:
        out.append("  caveats:")
        out += [f"     - {cv}" for cv in caveats]
    return "\n".join(out)


def _evidence_lines_text(mark: str, ev: Dict[str, Any], maxlen: int, suffix: str = "") -> List[str]:
    dom = ev.get("source_domain") or ""
    dom = f", {dom}" if dom else ""
    conf = ev.get("confidence")
    conf = f"conf {float(conf):.2f}" if conf is not None else "conf ?"
    unc = " (date uncertain)" if ev.get("date_uncertain") else ""
    ref = _source_ref(ev)
    ref = f"; {ref}" if ref else ""
    head = f"  {mark} {ev.get('class', '?')}  ({conf}, {_ev_year(ev)}{unc}{dom}{ref}){suffix}"
    lines = [head, f'     "{_truncate(ev.get("text", ""), maxlen)}"']
    if ev.get("rationale"):
        lines.append(f"     rationale: {_truncate(ev['rationale'], maxlen + 120)}")
    return lines


def render_markdown(h: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]], maxlen: int) -> str:
    c = h["counts"]
    md = [
        f"# {h['ticker']} claim ledger — {h['name']}",
        "",
        "> **Advisory only** — no greenwashing verdict. Every assessment is an "
        "LLM-assisted opinion for human review; there is no ground-truth label "
        "(see `docs/SYSTEM_DESIGN.md` §1.1). Evidence-balance scores are normalized "
        "evidence weights (`docs/SOFTMAX_SCORING.md`), not probabilities. "
        "Source: Neo4j advisory layer.",
        "",
        "| assessment | count |",
        "|---|---|",
        f"| appears_contradicted | {c['appears_contradicted']} |",
        f"| appears_supported | {c['appears_supported']} |",
        f"| unverified/insufficient | {c['unverified_insufficient_evidence']} |",
        f"| **total claims** | {h['total']} |",
        "",
        f"**Independent conduct on the issuer:** {h['conduct_bits']}.  ",
        f"⚠ {COVERAGE_CAVEAT}",
        "",
    ]
    for assessment in ("appears_contradicted", "appears_supported", "unverified_insufficient_evidence"):
        items = groups.get(assessment, [])
        if not items:
            continue
        md += [f"## {ASSESSMENT_LABEL[assessment]} ({len(items)})", ""]
        for d in items:
            md += _entry_markdown(d, maxlen)
    return "\n".join(md).rstrip() + "\n"


def _entry_markdown(d: Dict[str, Any], maxlen: int) -> List[str]:
    cref = _source_ref(d)
    cref = f" — _{cref}_" if cref else ""
    md = [
        f"### `{d.get('claim_id', '?')}` — [{d.get('year', '?')}, {d.get('claim_source_type', 'report')}]{cref}",
        "",
        f"> {_truncate(d.get('claim_text', ''), maxlen)}",
        "",
        f"**Assessment:** {d.get('assessment', '?')} (advisory)",
        "",
    ]
    for mark, key, note in (("✗", "contradicting_evidence", ""),
                            ("✓", "supporting_evidence", ""),
                            ("⚑", "flagged_non_independent_support",
                             " _(company domain — not counted)_")):
        for ev in d.get(key, []):
            dom = ev.get("source_domain") or ""
            dom = f", {dom}" if dom else ""
            conf = ev.get("confidence")
            conf = f"conf {float(conf):.2f}" if conf is not None else "conf ?"
            ref = _source_ref(ev)
            ref = f"; {ref}" if ref else ""
            md.append(f"- {mark} **{ev.get('class', '?')}** ({conf}, {_ev_year(ev)}{dom}{ref}){note}: "
                      f"\"{_truncate(ev.get('text', ''), maxlen)}\"")
            if ev.get("rationale"):
                md.append(f"    - _rationale:_ {_truncate(ev['rationale'], maxlen + 120)}")
    scores = d.get("assessment_scores")
    if scores:
        dis = " — **argmax disagrees with assessment** (mixed evidence)" \
            if d.get("score_disagrees_with_assessment") else ""
        md.append(f"- _scores (evidence balance, not a greenwashing probability):_ "
                  f"contradicted={scores['contradicted']:.2f} · supported={scores['supported']:.2f} "
                  f"· abstain={scores['abstain']:.2f}{dis}")
    sig = d.get("signals", {}) or {}
    md.append(f"- _signals:_ structural_contradiction="
              f"{str(bool(sig.get('structural_contradiction'))).lower()}, "
              f"kpi_gap={'yes' if sig.get('kpi_gap') else 'none'}")
    for cv in d.get("caveats", []) or []:
        md.append(f"- _caveat:_ {cv}")
    md.append("")
    return md


# --------------------------------------------------------------------------- main
def run(args: argparse.Namespace) -> None:
    driver, database = connect(args)
    try:
        name, dossiers, conduct_pool = load_from_neo4j(driver, database, args.ticker)
    finally:
        driver.close()
    header = build_header(args.ticker, name, dossiers, conduct_pool)

    if args.claim_id:
        selected = [d for d in dossiers if d.get("claim_id") == args.claim_id]
        if not selected:
            logger.error(f"No claim with id '{args.claim_id}'.")
            sys.exit(1)
    elif args.review_queue:
        selected = [d for d in dossiers if is_review_queue(d)]
    elif args.assessment == "all":
        selected = list(dossiers)
    elif args.assessment:
        selected = [d for d in dossiers if d.get("assessment") == args.assessment]
    else:
        selected = [d for d in dossiers
                    if d.get("assessment") in ("appears_contradicted", "appears_supported")]

    selected.sort(key=_sort_key)
    if args.limit:
        selected = selected[: args.limit]

    print(render_header_text(header))
    if args.review_queue:
        print(f"\nREVIEW QUEUE — claims with contradicting evidence and NO independent "
              f"verification ({len(selected)}):\n")
    for d in selected:
        print()
        print(render_entry_text(d, args.maxlen))
    if not selected:
        print("\n(no claims match this filter)")
    if not args.claim_id and not args.review_queue and args.assessment not in (
            "all", "unverified_insufficient_evidence"):
        uv = header["counts"]["unverified_insufficient_evidence"]
        print(f"\n… plus {uv} unverified/insufficient claims not shown "
              f"(use --assessment all or --assessment unverified_insufficient_evidence).")

    if args.markdown is not None:
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for d in selected:
            groups[d.get("assessment", "unverified_insufficient_evidence")].append(d)
        md_path = Path(args.markdown) if args.markdown else (
            DEFAULT_OUT_DIR / f"{args.ticker.lower()}_claim_ledger.md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown(header, groups, args.maxlen), encoding="utf-8")
        logger.info(f"Wrote Markdown ledger → {md_path} ({len(selected)} claims)")


def main() -> None:
    _force_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Step 7 / P5 — render the per-company claim ledger from the Neo4j advisory "
                    "layer (read-only; run src_module/run.py neo4j_sync first).")
    p.add_argument("--ticker", default="AAA", help="Issuer to render (default AAA).")
    p.add_argument("--assessment",
                   choices=["appears_contradicted", "appears_supported",
                            "unverified_insufficient_evidence", "all"],
                   help="Show only this assessment bucket (default: contradicted + supported).")
    p.add_argument("--review-queue", action="store_true",
                   help="Only claims with contradiction and no independent verification.")
    p.add_argument("--claim-id", help="Render a single claim by its claim_id (full text).")
    p.add_argument("--limit", type=int, help="Cap the number of entries printed.")
    p.add_argument("--maxlen", type=int, default=300,
                   help="Truncate claim/evidence text to this many chars (default 300).")
    p.add_argument("--markdown", nargs="?", const="", default=None,
                   help="Also write a Markdown ledger (optional path; "
                        "default graph_output/crosscheck/<ticker>_claim_ledger.md).")
    p.add_argument("--uri", default=None, help="Neo4j URI (default env NEO4J_URI).")
    p.add_argument("--user", default=None, help="Neo4j user (default env NEO4J_USER).")
    p.add_argument("--password", default=None, help="Neo4j password (default env NEO4J_PASSWORD).")
    p.add_argument("--database", default=None, help="Neo4j database (default env NEO4J_DATABASE).")
    args = p.parse_args()
    if args.claim_id:
        args.maxlen = max(args.maxlen, 100000)  # never truncate a single-claim view
    run(args)


if __name__ == "__main__":
    main()
