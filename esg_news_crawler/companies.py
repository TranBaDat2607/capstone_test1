# -*- coding: utf-8 -*-
"""Load companies from company_annual_report.xlsx and build identity sets.

Each company yields a few identity phrases used to retrieve news:
  - the ticker (only ever paired with a disambiguator, never searched alone)
  - the full legal name
  - a cleaned short / brand name
  - subsidiary/associate companies (from config/subsidiaries/<TICKER>.json,
    written by crawl_data/extract_subsidiaries.py) — news about a subsidiary
    rarely names the parent, so these widen recall for conduct evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

DEFAULT_SUBSIDIARIES_DIR = Path(__file__).resolve().parent.parent / "config" / "subsidiaries"

# Prefixes/suffixes that carry no search signal — stripped to get a short name.
_PREFIXES = [
    "Tổng Công ty cổ phần ",
    "Tổng công ty cổ phần ",
    "Tổng Công ty ",
    "Tổng công ty ",
    "CTCP - Tổng Công ty ",
    "Công ty Tài chính Tổng hợp Cổ phần ",
    "CTCP Tập đoàn ",
    "Tập đoàn ",
    "CTCP ",
    "Công ty cổ phần ",
    "Công ty ",
]
_SUFFIXES = [" - CTCP", " CTCP"]


def short_name(full_name: str) -> str:
    """Reduce a full legal name to a searchable short/brand name."""
    name = full_name.strip()
    if name.startswith("Ngân hàng TMCP "):
        return "Ngân hàng " + name[len("Ngân hàng TMCP "):]
    for p in _PREFIXES:
        if name.startswith(p):
            name = name[len(p):]
            break
    for s in _SUFFIXES:
        if name.endswith(s):
            name = name[: -len(s)]
            break
    return name.strip()


def _is_name_ambiguous(s: str) -> bool:
    """True when a short name is too generic to search on its own (e.g. "47",
    "Số 5", "Miền Đông") — such names must be paired with a disambiguator."""
    if len(s) <= 3:
        return True
    if s.replace("-", "").replace(" ", "").isdigit():
        return True
    # one short word, no proper-noun signal
    words = s.split()
    if len(words) == 1 and len(s) <= 6:
        return True
    return False


@dataclass
class Subsidiary:
    """One row from config/subsidiaries/<TICKER>.json — a subsidiary or
    associate company extracted from the parent's annual report. Has no
    ticker of its own; disambiguated against the PARENT's ticker when its
    short name is too generic (see queries.subsidiary_queries)."""
    name: str
    relationship: str = "subsidiary"   # "subsidiary" | "associate"
    confidence: str = "needs_review"   # "high" | "needs_review"
    short: str = field(default="")

    def __post_init__(self):
        if not self.short:
            self.short = short_name(self.name)

    @property
    def is_ambiguous(self) -> bool:
        return _is_name_ambiguous(self.short)


def load_subsidiaries(
    ticker: str, subsidiaries_dir: str | Path = DEFAULT_SUBSIDIARIES_DIR
) -> list[Subsidiary]:
    """Read config/subsidiaries/<TICKER>.json if it exists. A missing file or
    an empty "companies" list are both normal (not every ticker has run
    through extraction yet, or genuinely has no subsidiaries) — return []."""
    path = Path(subsidiaries_dir) / f"{ticker}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[Subsidiary] = []
    for row in data.get("companies", []):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        out.append(Subsidiary(
            name=name,
            relationship=row.get("relationship") or "subsidiary",
            confidence=row.get("confidence") or "needs_review",
        ))
    return out


@dataclass
class Company:
    ticker: str
    full_name: str
    sector: str = ""
    short: str = field(default="")
    subsidiaries: list[Subsidiary] = field(default_factory=list)

    def __post_init__(self):
        if not self.short:
            self.short = short_name(self.full_name)

    @property
    def is_short_name_ambiguous(self) -> bool:
        """True when the short name is too generic to search on its own
        (e.g. "47", "Số 5", "Miền Đông") — such names must be paired with the
        ticker or sector word to disambiguate."""
        return _is_name_ambiguous(self.short)


def load_companies(
    xlsx_path: str | Path,
    subsidiaries_dir: str | Path = DEFAULT_SUBSIDIARIES_DIR,
) -> list[Company]:
    """Read the workbook. Ticker cells are merged-down (only the first row of a
    company group is populated), so we forward-fill ticker + name."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    companies: list[Company] = []
    seen: set[str] = set()
    for ws in wb.worksheets:
        sector = ws.title.strip()
        for row in ws.iter_rows(min_row=2, values_only=True):
            ticker = (row[0] or "").strip() if row and row[0] else ""
            name = (row[1] or "").strip() if len(row) > 1 and row[1] else ""
            if not ticker or not name:
                continue
            if ticker in seen:
                continue
            seen.add(ticker)
            companies.append(Company(
                ticker=ticker, full_name=name, sector=sector,
                subsidiaries=load_subsidiaries(ticker, subsidiaries_dir),
            ))
    wb.close()
    return companies


if __name__ == "__main__":  # quick smoke test
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "company_annual_report.xlsx"
    cs = load_companies(path)
    print(f"{len(cs)} companies")
    for c in cs[:20]:
        flag = " [AMBIGUOUS]" if c.is_short_name_ambiguous else ""
        print(f"  {c.ticker:5} | {c.short!r:35} <- {c.full_name}{flag}")
        if c.subsidiaries:
            print(f"        + {len(c.subsidiaries)} subsidiaries/associates")
