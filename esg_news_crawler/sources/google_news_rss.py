# -*- coding: utf-8 -*-
"""Google News RSS search channel.

RSS is XML (not blocked / no CAPTCHA), making it the most reliable free channel.
The catch: result links are encoded news.google.com redirects that must be
decoded to the real article URL via Google's batchexecute endpoint, with a
base64 fallback.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from urllib.parse import quote_plus

import feedparser
import requests

log = logging.getLogger("esg_news.google_news")

_RSS = "https://news.google.com/rss/search?q={q}&hl=vi&gl=VN&ceid=VN:vi"


def _decode_google_url(url: str, ua: str) -> str:
    """Resolve a news.google.com/rss/articles/... link to the real article URL."""
    if "news.google.com" not in url:
        return url
    # Primary: batchexecute
    try:
        r = requests.get(url, headers={"User-Agent": ua}, timeout=10)
        r.raise_for_status()
        from bs4 import BeautifulSoup
        el = BeautifulSoup(r.text, "html.parser").select_one("c-wiz[data-p]")
        if el:
            obj = json.loads(el.get("data-p").replace("%.@.", '["garturlreq",'))
            payload = {"f.req": json.dumps([[["Fbv4je", json.dumps(obj[:-6] + obj[-2:]), "null", "generic"]]])}
            pr = requests.post(
                "https://news.google.com/_/DotsSplashUi/data/batchexecute",
                headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8", "user-agent": ua},
                data=payload, timeout=10,
            )
            pr.raise_for_status()
            data = json.loads(pr.text.replace(")]}'", "").strip())
            real = json.loads(data[0][2])[1]
            if real and "google.com" not in real:
                return real
    except Exception as e:
        log.debug("batchexecute decode failed: %s", e)

    # Fallback: base64 inside /articles/<blob>
    m = re.search(r"/articles/([^?&]+)", url)
    if m:
        enc = m.group(1)
        enc += "=" * ((4 - len(enc) % 4) % 4)
        try:
            decoded = base64.urlsafe_b64decode(enc).decode("latin-1")
            for found in re.findall(r"https?://[a-zA-Z0-9._\-/:%?&=#~@!$'()*+,;]+", decoded):
                if "google." not in found:
                    return found
        except Exception:
            pass
    return url


def search(fetcher, query: str, num: int = 10, since_years: int = 5, **_) -> list[dict]:
    q = f"{query} when:{since_years}y"
    url = _RSS.format(q=quote_plus(q))
    final_url, content, _ = fetcher.get(url)
    if not content:
        return []
    feed = feedparser.parse(content)
    ua = fetcher._headers()["User-Agent"]
    out: list[dict] = []
    for entry in feed.entries[:num]:
        link = entry.get("link", "")
        if not link:
            continue
        real = _decode_google_url(link, ua)
        out.append({"url": real, "title": entry.get("title", ""), "channel": "google_news"})
    return out
