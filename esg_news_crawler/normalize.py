# -*- coding: utf-8 -*-
"""Turn an extracted Article into sentence-split JSONL records.

Records mirror the annual-report classifier schema so news flows through the
EXACT same path:  source_pdf, page, sentence_index, text
...plus news metadata fields the classifier can ignore or use as features.

The sentence splitter is imported from the report pipeline itself
(``data_processing.sentence_splitter``) — guaranteeing identical segmentation.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# Make the sibling data_processing package importable when run from anywhere.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data_processing.sentence_splitter import split_sentences  # noqa: E402

from .companies import Company
from .extract import Article
from .fetch import domain_of


def _doc_id(ticker: str, url: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{ticker}__{domain_of(url)}__{h}"


def _mentions(company: Company, text_lower: str) -> bool:
    if company.ticker.lower() in text_lower:
        return True
    if company.full_name.lower() in text_lower:
        return True
    if company.short.lower() in text_lower:
        return True
    return False


def article_to_records(
    article: Article,
    company: Company,
    *,
    query: str,
    query_terms: list[str],
    channel: str,
    date_crawled: str,
) -> list[dict]:
    """One record per sentence. Title is emitted as sentence_index 0-style first
    record so the headline is preserved for the classifier."""
    doc_id = _doc_id(company.ticker, article.url)
    domain = domain_of(article.url)

    full_text = f"{article.title}\n\n{article.text}".strip()
    text_lower = full_text.lower()
    company_mentioned = _mentions(company, text_lower)
    matched = sorted({t for t in query_terms if t.lower() in text_lower})

    # Headline first, then body sentences — all through the report splitter.
    units: list[str] = []
    if article.title:
        units.append(article.title.strip())
    units.extend(split_sentences(article.text))

    meta = {
        "ticker": company.ticker,
        "company": company.full_name,
        "url": article.url,
        "source_domain": domain,
        "title": article.title,
        "publish_date": article.date,
        "date_crawled": date_crawled,
        "channel": channel,
        "query": query,
        "matched_terms": matched,
        "company_mentioned": company_mentioned,
    }

    records: list[dict] = []
    for i, sent in enumerate(units, start=1):
        rec = {"source_pdf": doc_id, "page": 1, "sentence_index": i, "text": sent}
        rec.update(meta)
        records.append(rec)
    return records
