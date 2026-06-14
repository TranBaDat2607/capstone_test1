# -*- coding: utf-8 -*-
"""Generate retrieval queries per company.

Queries widen recall so the rare ESG / controversy articles surface above the
stock-price noise. They do NOT filter — every article retrieved is kept and
handed to the downstream model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .companies import Company
from .config import KEYWORD_GROUPS


@dataclass
class Query:
    text: str               # the actual search string
    terms: list[str]        # keyword-group terms it carries ([] for plain identity)
    kind: str               # "plain" | "keyword" | "site"


def _kw_identity(c: Company) -> str:
    """Identity phrase used for keyword combos. Ambiguous short names
    (e.g. "47", "CIC") get the ticker appended to disambiguate."""
    if c.is_short_name_ambiguous:
        return f"{c.short} {c.ticker}".strip()
    return c.short


def base_queries(c: Company) -> list[Query]:
    """Per-company queries routed through every search channel."""
    out: list[Query] = []

    # General coverage (no keyword) — full name + ticker market news.
    out.append(Query(text=c.full_name, terms=[], kind="plain"))
    out.append(Query(text=f"{c.ticker} cổ phiếu", terms=[], kind="plain"))

    # Keyword retrieval: identity × each OR-group.
    ident = _kw_identity(c)
    for group in KEYWORD_GROUPS:
        or_expr = " OR ".join(group)
        out.append(Query(text=f"{ident} ({or_expr})", terms=list(group), kind="keyword"))

    return out


def site_queries(c: Company, domains: list[str]) -> list[Query]:
    """site:-restricted queries (routed through DuckDuckGo / Bing) to reach
    portals whose own on-site search is flaky. One per domain, carrying the
    first (claims) keyword group as a light ESG nudge."""
    ident = _kw_identity(c)
    nudge = " OR ".join(KEYWORD_GROUPS[0])
    out: list[Query] = []
    for d in domains:
        out.append(
            Query(text=f"site:{d} {ident} ({nudge})", terms=list(KEYWORD_GROUPS[0]), kind="site")
        )
    return out


if __name__ == "__main__":
    from .companies import load_companies
    cs = load_companies("company_annual_report.xlsx")
    for c in (cs[0], cs[13]):  # AAA, C47 (ambiguous)
        print(f"=== {c.ticker} {c.short!r} ===")
        for q in base_queries(c):
            print(f"  [{q.kind:7}] {q.text}")
