# -*- coding: utf-8 -*-
"""Generate retrieval queries per company.

Queries widen recall so the rare ESG / controversy articles surface above the
stock-price noise. They do NOT filter — every article retrieved is kept and
handed to the downstream model.
"""

from __future__ import annotations

from dataclasses import dataclass

from .companies import Company, Subsidiary
from .config import KEYWORD_GROUPS


@dataclass
class Query:
    text: str               # the actual search string
    terms: list[str]        # keyword-group terms it carries ([] for plain identity)
    kind: str               # "plain" | "keyword" | "site" | "subsidiary" | "subsidiary_keyword"
    subsidiary_name: str = ""          # set when this targets a subsidiary/associate,
    subsidiary_relationship: str = ""  # not the parent — "subsidiary" | "associate"


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


def _subsidiary_identity(c: Company, sub: Subsidiary) -> str:
    """Identity phrase for a subsidiary query. A subsidiary has no ticker of
    its own, so an ambiguous short name (e.g. "Số 5") is disambiguated with
    the PARENT's ticker instead."""
    if sub.is_ambiguous:
        return f"{sub.short} {c.ticker}".strip()
    return sub.short


def subsidiary_queries(c: Company) -> list[Query]:
    """Queries per subsidiary/associate company found in the parent's annual
    report (config/subsidiaries/<TICKER>.json — see
    companies.load_subsidiaries): one plain-identity query, plus one per
    KEYWORD_GROUPS entry (same pattern as base_queries) to catch ESG/
    controversy stories that only name the subsidiary/plant/site, never the
    parent group — e.g. an environmental fine on a production subsidiary.

    NOTE on volume: this is a full cartesian product (1 + len(KEYWORD_GROUPS)
    queries per subsidiary), and some tickers have 20+ subsidiaries — e.g.
    AAA's 16 subsidiaries become 16 * 5 = 80 subsidiary queries on top of its
    6 base queries. Each query fans out to up to 3 search channels in
    gather_candidates. Consider --limit / a smaller run first to gauge
    runtime before a full 115-ticker pass.

    Every query is tagged with subsidiary_name/subsidiary_relationship so
    the origin is traceable — the article itself is still filed under the
    PARENT ticker, since gather_candidates runs one Company at a time."""
    out: list[Query] = []
    for sub in c.subsidiaries:
        ident = _subsidiary_identity(c, sub)
        out.append(Query(
            text=ident, terms=[], kind="subsidiary",
            subsidiary_name=sub.name, subsidiary_relationship=sub.relationship,
        ))
        for group in KEYWORD_GROUPS:
            or_expr = " OR ".join(group)
            out.append(Query(
                text=f"{ident} ({or_expr})", terms=list(group), kind="subsidiary_keyword",
                subsidiary_name=sub.name, subsidiary_relationship=sub.relationship,
            ))
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
        for q in subsidiary_queries(c):
            print(f"  [{q.kind:10}] {q.text}  <- {q.subsidiary_name} ({q.subsidiary_relationship})")
