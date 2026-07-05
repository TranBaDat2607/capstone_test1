"""Step 6b / P5 — push the cross-check dossiers into Neo4j (NO LLM).

System context: docs/SYSTEM_DESIGN.md §6/§9 and docs/CLAIM_LEDGER.md.

Step 6 (step07_crosscheck_claims_vs_conduct.py) computes, for each claim, an advisory `assessment`
plus its supporting/contradicting evidence — and stores the FULL picture only in the JSON
dossier (graph_output/crosscheck/<ticker>_claim_assessments.json). Two things therefore never
reach Neo4j on their own:
  * the per-claim `assessment` / `caveats` / `signals` (they are computed summaries, not edges);
  * the KPIObservation-based contradictions (the schema has no legal Claim→KPIObservation
    contradiction edge, so §6 keeps them dossier-only).

This script closes that gap **without spending a single token**: it re-reads the dossier that
the paid LLM run already produced and MERGEs it into the graph as an explicitly-advisory layer,
so the ledger (Step 7) and Cypher can read everything from Neo4j alone. Re-running is safe
(idempotent MERGE on a stable `_adv_key`).

What it writes (all clearly namespaced / flagged so advisory ≠ extracted fact):
  * on each SustainabilityClaim node: `assessment`, `assessment_is_advisory=true`, `caveats`
    (list), `structural_contradiction`, `kpi_gap`, `crosscheck_ticker`.
  * advisory edges Claim→evidence node (matched on the loader's `_node_key = "n{index}"`):
      supporting_evidence            → `llm_supports`
      contradicting_evidence         → `llm_contradicts`   (incl. KPIObservation gaps)
      flagged_non_independent_support→ `llm_flagged_support`
    each carrying llm_suggested=true + confidence / rationale / provider / evidence_text /
    evidence_class / source_domain / date / year / independent / date_uncertain / role.

Run from the repo root (Neo4j from step 5 must be up):
  python src/step08_sync_crosscheck_to_neo4j.py --dry-run          # counts only, no write
  python src/step08_sync_crosscheck_to_neo4j.py                    # MERGE into Neo4j
  python src/step08_sync_crosscheck_to_neo4j.py --clear-advisory   # wipe prior advisory layer first
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CROSSCHECK_DIR = REPO_ROOT / "graph_output" / "crosscheck"

# Neo4j defaults — match src/step06_load_graph_to_neo4j.py + the crosscheck write-back.
NEO4J_URI_DEFAULT = "bolt://localhost:8687"
NEO4J_USER_DEFAULT = "greenwashing"
NEO4J_PASSWORD_DEFAULT = "nammovuivui"
SHARED_LABEL = "_Entity"

# Advisory relationship types (namespaced; never confused with extracted edges).
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


def build_rows(dossiers: List[Dict[str, Any]], ticker: str):
    """Turn dossiers into UNWIND-ready claim rows + per-rel-type edge rows."""
    claim_rows: List[Dict[str, Any]] = []
    edges: Dict[str, List[Dict[str, Any]]] = {rel: [] for rel in ROLE_REL.values()}
    for d in dossiers:
        ci = d.get("claim_node_index")
        if ci is None:
            continue
        ck = f"n{ci}"
        sig = d.get("signals") or {}
        claim_rows.append({
            "ck": ck,
            "assessment": d.get("assessment"),
            "caveats": d.get("caveats") or [],
            "struct": bool(sig.get("structural_contradiction")),
            "kpi_gap": sig.get("kpi_gap") not in (None, {}),
            "ticker": ticker.upper(),
        })
        for role, key in ROLE_KEY.items():
            for ev in d.get(key, []) or []:
                ei = ev.get("node_index")
                if ei is None:
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
                # Neo4j drops null-valued keys on SET += ; strip them so the map is clean.
                props = {k: v for k, v in props.items() if v is not None}
                edges[ROLE_REL[role]].append({
                    "ck": ck, "ek": f"n{ei}", "akey": f"{ci}-{role}-{ei}", "props": props,
                })
    return claim_rows, edges


def run(args: argparse.Namespace) -> None:
    path = args.input or (DEFAULT_CROSSCHECK_DIR / f"{args.ticker.lower()}_claim_assessments.json")
    if not path.exists():
        logger.error(f"No dossiers at {path}. Run Step 6 (crosscheck) first.")
        sys.exit(1)
    dossiers = load_dossiers(path)
    claim_rows, edges = build_rows(dossiers, args.ticker)
    n_edges = sum(len(v) for v in edges.values())
    logger.info(f"Dossiers: {len(dossiers)} claims → {len(claim_rows)} claim rows, "
                f"{n_edges} advisory edges "
                f"({', '.join(f'{rel}={len(rows)}' for rel, rows in edges.items())}).")

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
                s.run("MATCH ()-[r]->() WHERE r.llm_suggested = true DELETE r")
                s.run(f"MATCH (c:SustainabilityClaim {{crosscheck_ticker:$t}}) "
                      f"REMOVE c.assessment, c.assessment_is_advisory, c.caveats, "
                      f"c.structural_contradiction, c.kpi_gap, c.crosscheck_ticker",
                      t=args.ticker.upper())

            # 1) claim-node advisory properties
            claim_q = (
                f"UNWIND $rows AS r "
                f"MATCH (c:`{SHARED_LABEL}` {{_node_key: r.ck}}) "
                f"SET c.assessment = r.assessment, c.assessment_is_advisory = true, "
                f"    c.caveats = r.caveats, c.structural_contradiction = r.struct, "
                f"    c.kpi_gap = r.kpi_gap, c.crosscheck_ticker = r.ticker"
            )
            res = s.run(claim_q, rows=claim_rows).consume()
            logger.info(f"Claim props set on {res.counters.properties_set} properties "
                        f"({len(claim_rows)} claims).")

            # 2) advisory evidence edges, one MERGE per rel type
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
                "(python src/step09_report_claim_ledger.py).")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 6b / P5 — push the cross-check dossiers into Neo4j as an advisory "
                    "layer (no LLM, idempotent).")
    p.add_argument("--ticker", default="AAA", help="Issuer whose dossier to sync (default AAA).")
    p.add_argument("-i", "--input", type=Path, default=None,
                   help="Dossier JSON (default graph_output/crosscheck/<ticker>_claim_assessments.json).")
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
