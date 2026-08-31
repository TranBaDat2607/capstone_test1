"""Step 6b / P5 — push the cross-check dossiers into Neo4j (NO LLM).

System context: docs/SYSTEM_DESIGN.md §6/§9 and docs/CLAIM_LEDGER.md.

Step 6 (`esg_kg.crosscheck.claims_vs_conduct`) computes, for each claim, an advisory
`assessment` plus its supporting/contradicting evidence — and stores the FULL picture
only in the JSON dossier (graph_output/crosscheck/<ticker>_claim_assessments.json). Two
things therefore never reach Neo4j on their own:
  * the per-claim `assessment` / `caveats` / `signals` (they are computed summaries, not edges);
  * the KPIObservation-based contradictions (the schema has no legal Claim->KPIObservation
    contradiction edge, so §6 keeps them dossier-only).

This script closes that gap **without spending a single token**: it re-reads the dossier that
the paid LLM run already produced and MERGEs it into the graph as an explicitly-advisory layer,
so the ledger (Step 7) and Cypher can read everything from Neo4j alone. Re-running is safe
(idempotent MERGE on a stable `_adv_key`).

What it writes (all clearly namespaced / flagged so advisory != extracted fact):
  * on each SustainabilityClaim node: `assessment`, `assessment_is_advisory=true`, `caveats`
    (list), `structural_contradiction`, `kpi_gap`, `crosscheck_ticker` — plus, when
    step07b_enrich_dossiers.py has run, the evidence-balance scores `score_contradicted` /
    `score_supported` / `score_abstain` and `score_disagrees_with_assessment`
    (docs/SOFTMAX_SCORING.md — a normalized evidence balance, NOT a greenwashing probability).
  * advisory edges Claim->evidence node (matched on the loader's `_node_key = "n{index}"`,
    but resolved via a STABLE id first — see below):
      supporting_evidence            -> `llm_supports`
      contradicting_evidence         -> `llm_contradicts`   (incl. KPIObservation gaps)
      flagged_non_independent_support-> `llm_flagged_support`
    each carrying llm_suggested=true + confidence / rationale / provider / evidence_text /
    evidence_class / source_domain / date / year / independent / date_uncertain / role.

Node resolution — why this is not just `f"n{node_index}"`:
  The dossier records `claim_node_index` / `node_index`, which are POSITIONS in the resolved
  graph's node array. Any step05 re-run that changes clustering (e.g. a new frozen anchor
  merging duplicate mentions) shifts those positions, and a purely positional sync would then
  silently bind every advisory edge to the WRONG node — no error, just a corrupt layer.
  So we resolve in three tiers and count which one fired:
    1. "stable_id"  — claims by their unique `claim_id` (SustainabilityClaim.identity_keys);
                      evidence by the `stable_id` step07 records (newer dossiers).
    2. "text"       — evidence by (class, node_text[:400]); ambiguous texts are NOT used,
                      because a wrong bind is worse than falling back.
    3. "positional" — the original `node_index`, for dossiers predating the above.
  A high positional share means the dossier is out of phase with the graph; re-run step 6.

Run from the repo root (Neo4j from step 5 must be up):
  python src/run.py neo4j_sync --dry-run          # counts only, no write
  python src/run.py neo4j_sync                    # MERGE into Neo4j
  python src/run.py neo4j_sync --clear-advisory   # wipe prior advisory layer first

MIGRATED FROM ``src/step08_sync_crosscheck_to_neo4j.py`` (2026-07-29), verbatim except the
docstring and the import block: ``REPO_ROOT`` now comes from ``esg_kg.core.paths`` (the
same swap every leaf stage has made since step01) and ``node_text`` now comes from
``esg_kg.crosscheck.claims_vs_conduct`` (moved there 2026-07-28 — that move is what
unblocked this stage; PIPELINE.md §2.1). No logic line differs. This is the first
Neo4j-touching stage to migrate: it has no ``_Provider`` layer to stand in front of the
real client the way ``_OpenAIProvider``/``google.genai.Client`` did for earlier paid
stages, so ``test/test_esg_kg_neo4j_sync.py`` stubs the installed ``neo4j`` package's
``GraphDatabase`` attribute directly and compares every Cypher string + parameter dict
both trees send, on the real 1,093-dossier / 10,425-node corpus, without touching a live
database.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from esg_kg.core.paths import REPO_ROOT
from esg_kg.crosscheck.claims_vs_conduct import node_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_CROSSCHECK_DIR = REPO_ROOT / "graph_output" / "crosscheck"
DEFAULT_RESOLVED = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"

FALLBACK_WARN_RATIO = 0.05

NEO4J_URI_DEFAULT = "bolt://localhost:8687"
NEO4J_USER_DEFAULT = "greenwashing"
NEO4J_PASSWORD_DEFAULT = "changeme"
SHARED_LABEL = "_Entity"

ROLE_REL = {
    "support": "llm_supports",
    "contradict": "llm_contradicts",
    "flagged": "llm_flagged_support",
}
ROLE_KEY = {
    "support": "supporting_evidence",
    "contradict": "contradicting_evidence",
    "flagged": "flagged_non_independent_support",
}


def load_dossiers(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_key_index(graph: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[Tuple[str, str], str]]:
    """Stable-id indexes into the resolved graph, both valued by `_node_key` ("n{i}").

    Returns (by_claim_id, by_text). `by_text` deliberately DROPS ambiguous keys: node_text is
    truncated to the same 400 chars the dossier stores, so two nodes can collide, and binding
    an advisory edge to the wrong one is worse than falling back to the recorded index.
    """
    by_claim_id: Dict[str, str] = {}
    text_hits: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for i, n in enumerate(graph.get("nodes", [])):
        cls = n.get("class") or ""
        key = f"n{i}"
        if cls == "SustainabilityClaim":
            cid = (n.get("properties") or {}).get("claim_id")
            if cid:
                by_claim_id.setdefault(str(cid), key)
        text = node_text(n)[:400]
        if text:
            text_hits[(cls, text)].append(key)
    by_text = {k: keys[0] for k, keys in text_hits.items() if len(keys) == 1}
    return by_claim_id, by_text


def resolve_claim(d: Dict[str, Any], by_claim_id: Dict[str, str]) -> Tuple[Optional[str], str]:
    cid = d.get("claim_id")
    if cid and str(cid) in by_claim_id:
        return by_claim_id[str(cid)], "stable_id"
    ci = d.get("claim_node_index")
    return (f"n{ci}", "positional") if ci is not None else (None, "unresolved")


def resolve_evidence(ev: Dict[str, Any], by_text: Dict[Tuple[str, str], str]) -> Tuple[Optional[str], str]:
    key = (ev.get("class") or "", (ev.get("text") or "")[:400])
    if key[1] and key in by_text:
        return by_text[key], "text"
    ei = ev.get("node_index")
    return (f"n{ei}", "positional") if ei is not None else (None, "unresolved")


def build_rows(dossiers: List[Dict[str, Any]], ticker: str,
               by_claim_id: Optional[Dict[str, str]] = None,
               by_text: Optional[Dict[Tuple[str, str], str]] = None):
    """Turn dossiers into UNWIND-ready claim rows + per-rel-type edge rows.

    Also returns a Counter of how each row was resolved (see the module docstring).
    """
    by_claim_id = by_claim_id or {}
    by_text = by_text or {}
    how: Counter = Counter()
    claim_rows: List[Dict[str, Any]] = []
    edges: Dict[str, List[Dict[str, Any]]] = {rel: [] for rel in ROLE_REL.values()}
    for d in dossiers:
        ck, ck_how = resolve_claim(d, by_claim_id)
        how[f"claim_{ck_how}"] += 1
        if ck is None:
            continue
        sig = d.get("signals") or {}
        scores = d.get("assessment_scores") or {}
        claim_rows.append({
            "ck": ck,
            "assessment": d.get("assessment"),
            "caveats": d.get("caveats") or [],
            "struct": bool(sig.get("structural_contradiction")),
            "kpi_gap": sig.get("kpi_gap") not in (None, {}),
            "ticker": ticker.upper(),
            "score_contradicted": scores.get("contradicted"),
            "score_supported": scores.get("supported"),
            "score_abstain": scores.get("abstain"),
            "score_disagrees": d.get("score_disagrees_with_assessment"),
        })
        for role, key in ROLE_KEY.items():
            for ev in d.get(key, []) or []:
                ek, ek_how = resolve_evidence(ev, by_text)
                how[f"evidence_{ek_how}"] += 1
                if ek is None:
                    continue
                props = {
                    "llm_suggested": True,
                    "role": role,
                    "evidence_class": ev.get("class"),
                    "evidence_text": ev.get("text"),
                    "source_domain": ev.get("source_domain") or "",
                    "date": ev.get("date"),
                    "year": ev.get("year"),
                    "confidence": ev.get("confidence"),
                    "rationale": ev.get("rationale"),
                    "provider": ev.get("provider"),
                    "independent": ev.get("independent",
                                          True if role == "support" else
                                          (False if role == "flagged" else None)),
                    "date_uncertain": bool(ev.get("date_uncertain")),
                }
                props = {k: v for k, v in props.items() if v is not None}
                edges[ROLE_REL[role]].append({
                    "ck": ck, "ek": ek, "akey": f"{ck}-{role}-{ek}", "props": props,
                })
    return claim_rows, edges, how


def run(args: argparse.Namespace) -> None:
    path = args.input or (DEFAULT_CROSSCHECK_DIR / f"{args.ticker.lower()}_claim_assessments.json")
    if not path.exists():
        logger.error(f"No dossiers at {path}. Run Step 6 (crosscheck) first.")
        sys.exit(1)
    dossiers = load_dossiers(path)

    by_claim_id: Dict[str, str] = {}
    by_text: Dict[Tuple[str, str], str] = {}
    if args.resolved.exists():
        graph = json.loads(args.resolved.read_text(encoding="utf-8"))
        by_claim_id, by_text = build_key_index(graph)
        logger.info(f"Stable-id index from {args.resolved.name}: "
                    f"{len(by_claim_id)} claim_id(s), {len(by_text)} unambiguous text key(s).")
    else:
        logger.warning(f"No resolved graph at {args.resolved} — falling back to positional "
                       f"node_index only. This is only safe if step05 has not been re-run "
                       f"since the dossier was written.")

    claim_rows, edges, how = build_rows(dossiers, args.ticker, by_claim_id, by_text)
    n_edges = sum(len(v) for v in edges.values())
    logger.info(f"Dossiers: {len(dossiers)} claims → {len(claim_rows)} claim rows, "
                f"{n_edges} advisory edges "
                f"({', '.join(f'{rel}={len(rows)}' for rel, rows in edges.items())}).")
    logger.info(f"Node resolution: {dict(sorted(how.items()))}")

    positional = how["claim_positional"] + how["evidence_positional"]
    total = sum(v for k, v in how.items() if not k.endswith("_unresolved"))
    if total and positional / total > FALLBACK_WARN_RATIO:
        logger.warning(
            f"{positional}/{total} ({positional / total:.0%}) of rows resolved POSITIONALLY. "
            f"If step05 was re-run after this dossier was written, those rows point at the "
            f"wrong nodes — re-run step07 (crosscheck) rather than trusting this sync.")
    if how["claim_unresolved"] or how["evidence_unresolved"]:
        logger.warning(f"Skipped {how['claim_unresolved']} claim(s) and "
                       f"{how['evidence_unresolved']} evidence row(s) with no usable id.")

    if args.dry_run:
        logger.info("--dry-run: nothing written.")
        return

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

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        with driver.session(database=database) as s:
            if args.clear_advisory:
                logger.info("Clearing prior advisory layer …")
                cks = [r["ck"] for r in claim_rows]
                cleared = s.run(
                    f"MATCH (c:`{SHARED_LABEL}`)-[r]->() "
                    f"WHERE c._node_key IN $cks AND r.llm_suggested = true DELETE r",
                    cks=cks).consume()
                logger.info(f"Cleared {cleared.counters.relationships_deleted} prior "
                            f"advisory edge(s) for ticker {args.ticker.upper()}.")
                s.run(f"MATCH (c:SustainabilityClaim {{crosscheck_ticker:$t}}) "
                      f"REMOVE c.assessment, c.assessment_is_advisory, c.caveats, "
                      f"c.structural_contradiction, c.kpi_gap, c.crosscheck_ticker, "
                      f"c.score_contradicted, c.score_supported, c.score_abstain, "
                      f"c.score_disagrees_with_assessment",
                      t=args.ticker.upper())

            claim_q = (
                f"UNWIND $rows AS r "
                f"MATCH (c:`{SHARED_LABEL}` {{_node_key: r.ck}}) "
                f"SET c.assessment = r.assessment, c.assessment_is_advisory = true, "
                f"    c.caveats = r.caveats, c.structural_contradiction = r.struct, "
                f"    c.kpi_gap = r.kpi_gap, c.crosscheck_ticker = r.ticker, "
                f"    c.score_contradicted = r.score_contradicted, "
                f"    c.score_supported = r.score_supported, "
                f"    c.score_abstain = r.score_abstain, "
                f"    c.score_disagrees_with_assessment = r.score_disagrees"
            )
            res = s.run(claim_q, rows=claim_rows).consume()
            logger.info(f"Claim props set on {res.counters.properties_set} properties "
                        f"({len(claim_rows)} claims).")

            if not args.clear_advisory:
                cks = [r["ck"] for r in claim_rows]
                cleared = s.run(
                    f"MATCH (c:`{SHARED_LABEL}`)-[x]->() "
                    f"WHERE c._node_key IN $cks AND x.llm_suggested = true DELETE x",
                    cks=cks).consume()
                logger.info(f"Cleared {cleared.counters.relationships_deleted} prior advisory "
                            f"edge(s) on {len(cks)} re-synced claim(s).")

            for rel, rows in edges.items():
                if not rows:
                    continue
                edge_q = (
                    f"UNWIND $rows AS r "
                    f"MATCH (c:`{SHARED_LABEL}` {{_node_key: r.ck}}), "
                    f"      (e:`{SHARED_LABEL}` {{_node_key: r.ek}}) "
                    f"MERGE (c)-[x:`{rel}` {{_adv_key: r.akey}}]->(e) "
                    f"SET x += r.props"
                )
                res = s.run(edge_q, rows=rows).consume()
                logger.info(f"  {rel}: MERGEd {res.counters.relationships_created} new "
                            f"(+updated existing) from {len(rows)} rows.")
    finally:
        driver.close()
    logger.info("Sync complete. The ledger + Cypher can now read everything from Neo4j "
                "(python src/run.py claim_ledger).")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 6b / P5 — push the cross-check dossiers into Neo4j as an advisory "
                    "layer (no LLM, idempotent).")
    p.add_argument("--ticker", default="AAA", help="Issuer whose dossier to sync (default AAA).")
    p.add_argument("-i", "--input", type=Path, default=None,
                   help="Dossier JSON (default graph_output/crosscheck/<ticker>_claim_assessments.json).")
    p.add_argument("--resolved", type=Path, default=DEFAULT_RESOLVED,
                   help="Resolved graph used to resolve claims/evidence by stable id instead "
                        "of array position (default graph_output/resolved/resolved_graph.json).")
    p.add_argument("--uri", default=None, help="Neo4j URI (default env NEO4J_URI).")
    p.add_argument("--user", default=None, help="Neo4j user (default env NEO4J_USER).")
    p.add_argument("--password", default=None, help="Neo4j password (default env NEO4J_PASSWORD).")
    p.add_argument("--database", default=None, help="Neo4j database (default env NEO4J_DATABASE).")
    p.add_argument("--clear-advisory", action="store_true",
                   help="Delete the prior advisory layer (llm_suggested edges + advisory claim "
                        "props for this ticker) before writing.")
    p.add_argument("--dry-run", action="store_true", help="Compute + print counts; write nothing.")
    run(p.parse_args())


if __name__ == "__main__":
    main()
