# -*- coding: utf-8 -*-
"""Extract clean article text + metadata from raw HTML using trafilatura.

trafilatura handles arbitrary Vietnamese news domains (boilerplate removal,
publish-date and title extraction) far more robustly than per-site parsers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import trafilatura

log = logging.getLogger("esg_news.extract")


@dataclass
class Article:
    url: str
    title: str
    text: str
    date: str          # 'YYYY-MM-DD' or '' if unknown
    sitename: str
    author: str = ""


def extract_article(url: str, html: str) -> Article | None:
    """Return an Article, or None if no usable main text was found."""
    if not html:
        return None
    try:
        data = trafilatura.extract(
            html,
            url=url,
            output_format="json",
            with_metadata=True,
            include_comments=False,
            include_tables=False,
            favor_recall=True,          # sparse domains: keep more text
            deduplicate=True,
        )
    except Exception as e:
        log.warning("trafilatura failed on %s: %s", url[:90], e)
        return None
    if not data:
        return None

    import json
    try:
        d = json.loads(data)
    except Exception:
        return None

    text = (d.get("text") or "").strip()
    if not text:
        return None

    return Article(
        url=d.get("source") or url,
        title=(d.get("title") or "").strip(),
        text=text,
        date=(d.get("date") or "").strip(),
        sitename=(d.get("sitename") or "").strip(),
        author=(d.get("author") or "").strip(),
    )
