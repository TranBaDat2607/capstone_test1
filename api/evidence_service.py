"""Evidence Service for ESG Evidence View — REAL DATA from Neo4j.

Reads the advisory layer written by the pipeline (step06 base graph + step08 sync)
instead of hard-coded demo data. Only claims that carry an `alignsWithIndicator` edge
are shown, so each card's ESG pillar (Môi trường / Xã hội / Quản trị) comes precisely
from the linked `StandardIndicator.pillar` — never guessed.

Columns:
  - verified     ← claims with assessment == "appears_supported"
  - contradicted ← claims with assessment == "appears_contradicted"
  - missing      ← deferred (kept empty for now)

Neo4j is REQUIRED. If it is unreachable, the query helpers raise RuntimeError with a
clear message (start it with `docker compose up -d` and run step06/step08).
"""

import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

NEO4J_URI_DEFAULT = "bolt://localhost:8687"
NEO4J_USER_DEFAULT = "greenwashing"
NEO4J_PASSWORD_DEFAULT = "nammovuivui"

# pillar string (on StandardIndicator) → UI tab key
PILLARS = [
    ("environment", "Môi trường", "🌿"),
    ("social", "Xã hội", "👥"),
    ("governance", "Quản trị", "🏛"),
]


# --------------------------------------------------------------------------- #
# Neo4j connection (lazy, cached) — same defaults/env as step09.
# --------------------------------------------------------------------------- #
_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        uri = os.getenv("NEO4J_URI", NEO4J_URI_DEFAULT)
        user = os.getenv("NEO4J_USER", NEO4J_USER_DEFAULT)
        pwd = os.getenv("NEO4J_PASSWORD", NEO4J_PASSWORD_DEFAULT)
        # notifications_min_severity=OFF silences harmless "relationship type does not
        # exist" warnings for equivalentTo (no GRI crosswalk edges loaded yet).
        drv = GraphDatabase.driver(uri, auth=(user, pwd), notifications_min_severity="OFF")
        try:
            drv.verify_connectivity()
        except Exception as e:  # noqa: BLE001 — surface a clear operator message
            raise RuntimeError(
                f"Không thể kết nối Neo4j tại {uri}. Hãy chạy `docker compose up -d`, "
                f"nạp graph (step06 --clear) và sync advisory (step08). Chi tiết: {e}"
            ) from e
        _driver = drv
    return _driver


def _database() -> Optional[str]:
    return os.getenv("NEO4J_DATABASE") or None


def _run(cypher: str, **params) -> List[Dict[str, Any]]:
    drv = _get_driver()
    with drv.session(database=_database()) as session:
        return [r.data() for r in session.run(cypher, **params)]


def _year_of(raw: Any) -> str:
    """Extract a 4-digit year from a date string like '2018' or '2018-01-01'."""
    s = str(raw or "").strip()
    return s[:4] if len(s) >= 4 and s[:4].isdigit() else s


def _pillar_key(pillar: Any) -> str:
    p = str(pillar or "").lower()
    if "xã hội" in p or "xa hoi" in p:
        return "social"
    if "quản trị" in p or "quan tri" in p:
        return "governance"
    return "environment"  # default incl. "Môi trường"


# --------------------------------------------------------------------------- #
# Cypher
# --------------------------------------------------------------------------- #
_Q_TICKERS = """
MATCH (c:SustainabilityClaim)-[:alignsWithIndicator]->(:StandardIndicator)
WHERE c.crosscheck_ticker IS NOT NULL
RETURN DISTINCT c.crosscheck_ticker AS ticker
ORDER BY ticker
"""

_Q_ISSUER_NAME = "MATCH (o:Organization {ticker:$t}) RETURN o.name AS name LIMIT 1"

_Q_YEARS = """
MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})-[:alignsWithIndicator]->(:StandardIndicator)
RETURN DISTINCT c.date AS date
"""

_Q_CLAIMS = """
MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})-[:alignsWithIndicator]->(ind:StandardIndicator)
OPTIONAL MATCH (ind)-[:equivalentTo]->(gri:StandardIndicator)
RETURN c._node_key AS key, c.description AS claim_text, c.date AS year,
       c.assessment AS assessment, c.source_doc AS source_doc, c.source_page AS source_page,
       ind.id AS standard_id, ind.name AS standard_name, ind.pillar AS pillar,
       head(collect(gri.id)) AS gri_id
"""

_Q_EVIDENCE = """
MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})-[x]->(e)
WHERE x.llm_suggested = true
RETURN c._node_key AS key, x.role AS role, x.provider AS provider,
       coalesce(CASE WHEN x.source_domain <> '' THEN x.source_domain END, e.source_domain) AS source_domain,
       x.rationale AS rationale, x.evidence_text AS text
"""


# --------------------------------------------------------------------------- #
# Company registry (real, from Neo4j)
# --------------------------------------------------------------------------- #
def _available_years(ticker: str) -> List[str]:
    years = sorted(
        {y for r in _run(_Q_YEARS, t=ticker) if (y := _year_of(r.get("date")))},
        reverse=True,
    )
    if not years:
        return []
    year_range = f"{years[-1]} - {years[0]}" if len(years) > 1 else years[0]
    # combined range first, then each individual year (matches the UI's year selector)
    return ([year_range] + years) if len(years) > 1 else years


def get_company_info(ticker: str) -> Dict[str, Any]:
    t = ticker.upper()
    rows = _run(_Q_ISSUER_NAME, t=t)
    name = rows[0]["name"] if rows and rows[0].get("name") else f"Công ty {t}"
    years = _available_years(t)
    return {
        "ticker": t,
        "name": name,
        "short": name,
        "industry": "",
        "year_range": years[0] if years else "",
        "available_years": years,
    }


def get_companies(query: str = "") -> List[Dict[str, Any]]:
    """List issuers that have at least one indicator-aligned claim (from Neo4j)."""
    companies = [get_company_info(r["ticker"]) for r in _run(_Q_TICKERS)]
    if not query:
        return companies
    q = query.strip().lower()
    return [c for c in companies if q in c["ticker"].lower() or q in c["name"].lower()]


# --------------------------------------------------------------------------- #
# Evidence (3-column view)
# --------------------------------------------------------------------------- #
def _pick_evidence(evid_rows: List[Dict[str, Any]], want_role: str) -> Dict[str, str]:
    """Choose the first evidence row matching the role; build verifier/finding."""
    row = next((e for e in evid_rows if e.get("role") == want_role), None)
    if row is None:
        return {"verifier": "Đối chiếu tự động (LLM)", "finding": ""}
    verifier = row.get("source_domain") or row.get("provider") or "Đối chiếu tự động (LLM)"
    finding = row.get("rationale") or row.get("text") or ""
    return {"verifier": verifier, "finding": finding}


def get_evidence(ticker: str, selected_year: Optional[str] = None) -> Dict[str, Any]:
    """Return the 3-column ESG evidence breakdown for a ticker, from real Neo4j data."""
    t = ticker.upper()
    comp = get_company_info(t)

    # evidence edges grouped per claim key
    evid_by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in _run(_Q_EVIDENCE, t=t):
        evid_by_key[e["key"]].append(e)

    # empty pillar buckets
    buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        key: {"verified": [], "contradicted": [], "missing": []} for key, _, _ in PILLARS
    }

    seen_keys = set()  # a claim may align to >1 indicator; keep the first
    for row in _run(_Q_CLAIMS, t=t):
        key = row["key"]
        if key in seen_keys:
            continue
        seen_keys.add(key)

        assessment = row.get("assessment")
        pillar_key = _pillar_key(row.get("pillar"))
        year = _year_of(row.get("year"))
        std_id = row.get("standard_id") or "TT96-ESG"
        std_name = row.get("standard_name") or "Chỉ tiêu ESG"
        gri = row.get("gri_id")

        if assessment in ("appears_supported", "appears_contradicted"):
            column = "verified" if assessment == "appears_supported" else "contradicted"
            role = "support" if assessment == "appears_supported" else "contradict"
            src_doc = row.get("source_doc") or "BCTN AAA"
            src_page = row.get("source_page")
            claim_source = f"{src_doc}, trang {src_page}" if src_page is not None else str(src_doc)
            buckets[pillar_key][column].append({
                "year": year,
                "standard_id": std_id,
                "standard_name": std_name,
                "gri_equivalent": gri,
                "claim_quote": row.get("claim_text") or "",
                "claim_source": claim_source,
                "verification": _pick_evidence(evid_by_key.get(key, []), role),
            })
        else:
            # unverified aligned claim → ⚠️ column: company disclosed this indicator but
            # no independent evidence was found to cross-check it.
            buckets[pillar_key]["missing"].append({
                "year": year,
                "standard_id": std_id,
                "standard_name": std_name,
                "gri_equivalent": gri,
                "requirement": row.get("claim_text") or "",
                "note": "Chưa tìm thấy bằng chứng độc lập để đối chiếu tuyên bố này (unverified).",
            })

    # year filter (reuse the demo's semantics: range / "all" → no filter)
    def filter_by_year(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not selected_year or " - " in selected_year or selected_year == comp.get("year_range"):
            return items
        return [it for it in items if str(it.get("year")) == str(selected_year)]

    tabs: Dict[str, Any] = {}
    for key, label, icon in PILLARS:
        v = filter_by_year(buckets[key]["verified"])
        c = filter_by_year(buckets[key]["contradicted"])
        m = filter_by_year(buckets[key]["missing"])
        tabs[key] = {
            "label": label,
            "icon": icon,
            "verified": v,
            "contradicted": c,
            "missing": m,
            "counts": {
                "verified": len(v),
                "contradicted": len(c),
                "missing": len(m),
                "total": len(v) + len(c) + len(m),
            },
        }

    return {
        "company": comp,
        "selected_year": selected_year or comp.get("year_range"),
        "tabs": tabs,
    }
