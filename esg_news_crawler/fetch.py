# -*- coding: utf-8 -*-
"""Shared HTTP fetcher: disk-cached, per-domain rate-limited, UA-rotating.

One Fetcher is shared across every search channel and article download so the
cache and politeness (per-domain delay + backoff on 403/429/503) apply
uniformly. Raw response bytes are cached under ``cache_dir`` keyed by a hash of
the URL, making re-runs and resume cheap.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .config import (
    DEFAULT_DOMAIN_DELAY,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    USER_AGENTS,
)

log = logging.getLogger("esg_news.fetch")


def domain_of(url: str) -> str:
    """Return the bare host (without a leading ``www.``) for a URL."""
    host = urlsplit(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


class Fetcher:
    """Caching, polite HTTP GET helper.

    ``get``      -> (final_url, content_bytes | None, status)
    ``get_text`` -> (final_url, html_str | None)
    """

    def __init__(self, cache_dir: str | Path | None = None, use_cache: bool = True,
                 domain_delay: float = DEFAULT_DOMAIN_DELAY,
                 timeout: int = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES):
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.use_cache and self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.domain_delay = domain_delay
        self.timeout = timeout
        self.retries = retries
        self._last_hit: dict[str, float] = {}
        self._session = requests.Session()

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "vi,en-US;q=0.8,en;q=0.6",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _cache_path(self, url: str) -> Path | None:
        if not (self.use_cache and self.cache_dir):
            return None
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.bin"

    def _throttle(self, url: str) -> None:
        """Sleep just enough to honour the per-domain minimum delay."""
        dom = domain_of(url)
        last = self._last_hit.get(dom)
        if last is not None:
            wait = self.domain_delay - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[dom] = time.time()

    def get(self, url: str) -> tuple[str, bytes | None, int]:
        """Fetch raw bytes for ``url``. Returns (final_url, content|None, status).
        Cache hits short-circuit the network and report status 200."""
        cache_path = self._cache_path(url)
        if cache_path and cache_path.exists():
            return url, cache_path.read_bytes(), 200

        last_status = 0
        for attempt in range(1, self.retries + 1):
            self._throttle(url)
            try:
                r = self._session.get(
                    url, headers=self._headers(),
                    timeout=self.timeout, allow_redirects=True,
                )
            except requests.RequestException as e:
                log.debug("get error (%d/%d) %s: %s", attempt, self.retries, url[:90], e)
                time.sleep(min(2 ** attempt, 10))
                continue

            last_status = r.status_code
            if r.status_code in (403, 429, 503):
                back = min(2 ** attempt, 15)
                log.debug("status %d backoff %ss %s", r.status_code, back, url[:90])
                time.sleep(back)
                continue
            if r.ok:
                content = r.content
                if cache_path:
                    try:
                        cache_path.write_bytes(content)
                    except OSError:
                        pass
                return r.url, content, r.status_code
            # other 4xx/5xx — don't hammer, give up on this URL
            break

        return url, None, last_status

    def get_text(self, url: str) -> tuple[str, str | None]:
        """Fetch and decode HTML to ``str``. Returns (final_url, html|None).
        Vietnamese news is overwhelmingly UTF-8; latin-1 is a never-fail
        fallback that still lets trafilatura attempt extraction."""
        final_url, content, _ = self.get(url)
        if not content:
            return final_url, None
        try:
            return final_url, content.decode("utf-8")
        except UnicodeDecodeError:
            return final_url, content.decode("latin-1")
