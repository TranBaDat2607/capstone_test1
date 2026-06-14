# -*- coding: utf-8 -*-
"""DuckDuckGo search channel — free HTML endpoint, supports ``site:`` queries.

The ``html.duckduckgo.com`` endpoint returns plain result anchors
(``a.result__a``) whose hrefs are ``/l/?uddg=<urlencoded-real-url>`` redirects,
which we unwrap to the real article URL.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

from bs4 import BeautifulSoup

log = logging.getLogger("esg_news.ddg")

_URL = "https://html.duckduckgo.com/html/?q={q}&kl=vn-vi"


def _unwrap(href: str) -> str:
    """Resolve a DuckDuckGo ``/l/?uddg=`` redirect to the real URL."""
    if "uddg=" in href:
        u = parse_qs(urlsplit(href).query).get("uddg", [""])[0]
        if u:
            return unquote(u)
    if href.startswith("//"):
        return "https:" + href
    return href


def search(fetcher, query: str, num: int = 10, since_years: int = 5, **_) -> list[dict]:
    url = _URL.format(q=quote_plus(query))
    _, html = fetcher.get_text(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for a in soup.select("a.result__a"):
        href = _unwrap(a.get("href", ""))
        if not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        out.append({"url": href, "title": a.get_text(" ", strip=True), "channel": "ddg"})
        if len(out) >= num:
            break
    return out
