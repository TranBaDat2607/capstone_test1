"""
Build the claim-side corpus for ragtest out of the ESG sentences already on disk.

Input is `data/outputs/esg_extracted/esg_all_records.jsonl` — the output of
`data_processing.extract_esg`, 282,195 sentences from 1,095 annual-report PDFs, each
carrying the ViDeBERTa E/S/G labels and its (source_pdf, page, sentence_index) location.
Nothing here re-runs that stage; it only reads, filters and cleans.

Three filters, in order:

  1. company     keep only the 5 tickers the project actually uses. `source_pdf` is
                 "TICKER_YEAR.pdf", so it is the only carrier of company identity — and
                 the per-company filter is the biggest single accuracy lever at query
                 time, because a claim from another company is never the right answer.
  2. label       an unlabeled sentence is not an ESG claim.
  3. boilerplate bare page numbers and decorative fragments carry no claim, and repeated
                 cover-page banners are deduped so one banner cannot occupy the whole
                 top-k for any query that mentions the company name.

Traceability (source_pdf, page, sentence_index) is carried through, per CLAUDE.md, so a
retrieved claim can be cited back to a report page.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# The 5 companies in use — the ones with crosscheck dossiers in graph_output/crosscheck/.
TICKERS: Tuple[str, ...] = ("AAA", "ACC", "ACG", "ADP", "AGG")

_TICKER_RE = re.compile(r"^([A-Z]{3})_")
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_MIN_ALPHA_TOKENS = 3


def parse_ticker_year(source_pdf: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """("AAA_2013_v2.pdf") -> ("AAA", 2013). Anything that is not TICKER_... -> (None, None).

    Never guesses: a news slug or a standards PDF has no ticker, and inventing one would
    silently file another company's sentence under a project company.
    """
    if not source_pdf or not isinstance(source_pdf, str):
        return None, None
    match = _TICKER_RE.match(source_pdf)
    if not match:
        return None, None
    ticker = match.group(1)
    year_match = _YEAR_RE.search(source_pdf[len(ticker):])
    return ticker, int(year_match.group(0)) if year_match else None


def is_boilerplate(text: Optional[str]) -> bool:
    """True for fragments that cannot carry a claim: empty, letterless, or near-wordless."""
    if not text or not text.strip():
        return True
    normalized = unicodedata.normalize("NFC", text)
    alpha_tokens = [t for t in re.findall(r"\w+", normalized, re.UNICODE)
                    if any(ch.isalpha() for ch in t)]
    return len(alpha_tokens) < _MIN_ALPHA_TOKENS


def _as_int(value: Any) -> Any:
    """page/sentence_index arrive as int (reports) or str (news) — normalize for the id."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return str(value).strip()


def doc_id(record: Dict[str, Any]) -> str:
    """A readable, stable id that IS the provenance: 'AAA_2013.pdf#p15#s3'.

    Readable on purpose — it is printed in the GLM verdict prompt, so a matched claim can
    be traced to a report page straight out of the model's answer.
    """
    return (f"{record.get('source_pdf')}"
            f"#p{_as_int(record.get('page'))}"
            f"#s{_as_int(record.get('sentence_index'))}")


def _dedup_key(ticker: str, text: str) -> Tuple[str, str]:
    collapsed = re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().lower()
    return ticker, collapsed


def _sort_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    page, sentence = _as_int(row.get("page")), _as_int(row.get("sentence_index"))
    return (row["ticker"], str(row.get("source_pdf")),
            (0, page) if isinstance(page, int) else (1, str(page)),
            (0, sentence) if isinstance(sentence, int) else (1, str(sentence)))


def build_corpus(records: Iterable[Dict[str, Any]],
                 tickers: Sequence[str] = TICKERS) -> List[Dict[str, Any]]:
    """Filter -> clean -> dedup -> deterministic order.

    The order must not depend on input order: embeddings are cached by row position, so a
    reshuffle would invalidate the whole cached matrix.
    """
    allowed = set(tickers)
    rows: List[Dict[str, Any]] = []
    for record in records:
        if not record.get("labels"):
            continue
        ticker, year = parse_ticker_year(record.get("source_pdf"))
        if ticker not in allowed:
            continue
        text = record.get("text") or ""
        if is_boilerplate(text):
            continue
        rows.append({
            "doc_id": doc_id(record),
            "text": unicodedata.normalize("NFC", text).strip(),
            "ticker": ticker,
            "year": year,
            "source_pdf": record.get("source_pdf"),
            "page": _as_int(record.get("page")),
            "sentence_index": _as_int(record.get("sentence_index")),
            "labels": list(record.get("labels") or []),
        })

    rows.sort(key=_sort_key)

    deduped: List[Dict[str, Any]] = []
    seen_text: set = set()
    seen_id: set = set()
    for row in rows:
        key = _dedup_key(row["ticker"], row["text"])
        if key in seen_text or row["doc_id"] in seen_id:
            continue
        seen_text.add(key)
        seen_id.add(row["doc_id"])
        deduped.append(row)
    return deduped


def load_records(path: Path) -> Iterable[Dict[str, Any]]:
    """Stream the 145 MB JSONL rather than loading it whole."""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def build_from_file(path: Path, tickers: Sequence[str] = TICKERS) -> List[Dict[str, Any]]:
    return build_corpus(load_records(path), tickers=tickers)
