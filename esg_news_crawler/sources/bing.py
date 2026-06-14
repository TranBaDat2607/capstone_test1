# -*- coding: utf-8 -*-
"""Bing search channel — free HTML scrape, no API key.

Bing returns clean result blocks (``li.b_algo``) and usually links straight to
the article; occasionally it wraps the link in a ``/ck/a?...&u=a1<base64>``
redirect, which we decode back to the real URL.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import parse_qs, quote_plus, urlsplit

from bs4 import BeautifulSoup

log = logging.getLogger("esg_news.bing")

_URL = "https://www.bing.com/search?q={q}&setlang=vi&cc=VN&count={n}"


def _unwrap(href: str) -> str:
    """Resolve a Bing ``/ck/a`` click-tracking redirect to the real URL."""
    if "bing.com/ck/a" not in href:
        return href
    u = parse_qs(urlsplit(href).query).get("u", [""])[0]
    if u.startswith("a1"):
        b = u[2:]
        b += "=" * ((4 - len(b) % 4) % 4)
        try:
            return base64.urlsafe_b64decode(b).decode("utf-8", "ignore")
        except Exception:
            return href
    return href


def search(fetcher, query: str, num: int = 10, since_years: int = 5, **_) -> list[dict]:
    url = _URL.format(q=quote_plus(query), n=max(num, 10))
    _, html = fetcher.get_text(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a or not a.get("href"):
            continue
        href = _unwrap(a["href"])
        if not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        out.append({"url": href, "title": a.get_text(" ", strip=True), "channel": "bing"})
        if len(out) >= num:
            break
    return out
