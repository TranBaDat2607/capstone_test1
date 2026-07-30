"""io_jsonl — reconstructing per-page text from the sentence-level labeled JSONL.

Extracted verbatim from ``src/step01_extract_kpi_from_jsonl.py``: ``load_pages_from_jsonl``,
``build_page_text``, ``page_has_esg``, ``select_documents``, ``parse_company_year_from_filename``.

WHY THESE FIVE, AND WHY NOW
``src/step02_extract_triplet_from_jsonl.py:43-50`` imports all five from step01 at once —
step02 needs the same page reconstruction step01 does, so the two stages were reaching
across a sibling file for it. This module is what lets step02 stop doing that once it
migrates; it falls out of the step01 slice rather than being a prerequisite for it (the
same shape ``core/identity.py`` fell out of the step03b slice — PIPELINE.md §2.1, point 3).

All five are pure: no network, no LLM, no globals besides the module ``logger``. Behaviour
is asserted equivalent to the ``src/`` originals in ``test/test_esg_kg_extract.py``.

The bodies are duplicated in ``src/`` while the refactor is in flight (Model A — the old
tree must keep running and cannot import from here); that arm retires only when the
``src/`` twin is deleted (DESIGN.md §5.3).
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def parse_company_year_from_filename(pdf_filename: str) -> Tuple[str, str]:
    """Extract company name and year from a source_pdf filename (same logic as step 1)."""
    basename = os.path.splitext(pdf_filename)[0]

    year_match = re.search(r"(\d{4})$", basename)
    if year_match:
        year = year_match.group(1)
        company_part = basename[: year_match.start()].rstrip("_-")
        company = re.sub(r"[_\-\s]+$", "", company_part)
        return company, year

    parts = basename.split("_")
    if len(parts) >= 2:
        for i in range(len(parts) - 1, -1, -1):
            if re.match(r"^\d{4}$", parts[i]):
                year = parts[i]
                company = "_".join(parts[:i])
                return company, year

    logger.warning(f"Could not parse company and year from filename: {pdf_filename}")
    return os.path.splitext(pdf_filename)[0], "unknown"


def load_pages_from_jsonl(path: Path) -> "collections.OrderedDict":
    """
    Group rows into { source_pdf: { page: [ (sentence_index, text, esg), ... ] } },
    preserving first-seen document order.
    """
    docs: "collections.OrderedDict[str, Dict[int, List[Tuple[int, str, bool]]]]" = collections.OrderedDict()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            src = row.get("source_pdf", "unknown.pdf")
            page = int(row.get("page", 0))
            sidx = int(row.get("sentence_index", 0))
            text = row.get("text", "") or ""
            esg = bool(row.get("esg", False))
            docs.setdefault(src, {}).setdefault(page, []).append((sidx, text, esg))
    return docs


def build_page_text(rows: List[Tuple[int, str, bool]]) -> str:
    """Join all sentences on a page, ordered by sentence_index."""
    ordered = sorted(rows, key=lambda r: r[0])
    return " ".join(t.strip() for _, t, _ in ordered if t.strip())


def page_has_esg(rows: List[Tuple[int, str, bool]]) -> bool:
    return any(esg for _, _, esg in rows)


def select_documents(docs: "collections.OrderedDict", args) -> List[str]:
    names = list(docs.keys())
    if args.doc:
        matched = [n for n in names if args.doc in n]
        if not matched:
            logger.error(f"No source_pdf matches --doc '{args.doc}'. Available: {names}")
        return matched
    if args.all:
        return names
    if args.limit_docs:
        return names[: args.limit_docs]
    # Default: cheap first run — just the first document.
    logger.info("No scope flag given; defaulting to the first document. Use --all / --limit-docs / --doc.")
    return names[:1]


__all__ = [
    "parse_company_year_from_filename",
    "load_pages_from_jsonl",
    "build_page_text",
    "page_has_esg",
    "select_documents",
]
