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
    if any(k in p for k in ("xã hội", "xa hoi", "social", "s — social")):
        return "social"
    if any(k in p for k in ("quản trị", "quan tri", "governance", "universal", "g — governance")):
        return "governance"
    return "environment"


# 2026-08-07: EXPERIMENTAL relaxation, at the user's explicit request ("nới lỏng điều kiện,
# cho hiện mâu thuẫn") — surface appears_supported/appears_contradicted claims that have NO
# alignsWithIndicator edge (previously invisible in this view entirely, e.g. ACG's 3 real
# dividend/revenue contradictions). This REINTRODUCES pillar guessing that the module
# docstring above deliberately avoided ("each card's pillar comes precisely from the linked
# StandardIndicator.pillar — never guessed") — there is no indicator to read a pillar from
# for these claims, so the pillar below is a keyword guess over the claim's OWN text, and
# every such card is stamped standard_id="NGOÀI-KHUNG" so the UI can visibly flag it as
# unclassified rather than silently presenting a guess as if it were as reliable as an
# indicator-backed pillar.
_FALLBACK_PILLAR_KEYWORDS = {
    "environment": ["môi trường", "khí thải", "nước thải", "chất thải", "rác thải",
                     "năng lượng", "phát thải", "khí nhà kính", "tái chế", "ô nhiễm"],
    "social": ["người lao động", "nhân viên", "cộng đồng", "an toàn lao động", "phúc lợi",
               "đào tạo", "bình đẳng giới", "sức khỏe", "khách hàng", "nhân sự"],
    "governance": ["cổ tức", "hội đồng quản trị", "hđqt", "đại hội đồng cổ đông", "đhđcđ",
                   "ban điều hành", "btgđ", "ban giám đốc", "kiểm toán", "minh bạch",
                   "cổ đông", "quản trị"],
}


def _fallback_pillar_from_text(claim_text: str) -> str:
    t = str(claim_text or "").lower()
    for pillar, keywords in _FALLBACK_PILLAR_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return pillar
    return "governance"  # default bucket when no keyword matches


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

# 2026-08-07: OPTIONAL MATCH + a WHERE that also admits verified/contradicted claims with
# NO alignsWithIndicator edge — see _fallback_pillar_from_text above for why. Claims that
# are neither indicator-aligned NOR verified/contradicted are still excluded (unindicated
# "missing"/neutral claims stay out, or the "missing" column would explode from a handful
# to hundreds of un-triaged rows — not what was asked for).
_Q_CLAIMS = """
MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})
WHERE (c)-[:alignsWithIndicator]->(:StandardIndicator)
   OR c.assessment IN ['appears_supported', 'appears_contradicted']
OPTIONAL MATCH (c)-[:alignsWithIndicator]->(ind:StandardIndicator)
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
        year = _year_of(row.get("year"))
        gri = row.get("gri_id")

        if row.get("standard_id"):
            pillar_key = _pillar_key(row.get("pillar"))
            std_id = row["standard_id"]
            std_name = row.get("standard_name") or "Chỉ tiêu ESG"
        else:
            # relaxed match (2026-08-07): no StandardIndicator to read a pillar from —
            # keyword-guessed from the claim's own text, visibly flagged as such.
            pillar_key = _fallback_pillar_from_text(row.get("claim_text"))
            std_id = "NGOÀI-KHUNG"
            std_name = "Chưa gắn chỉ tiêu chuẩn hóa (pillar suy luận từ nội dung claim)"

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
