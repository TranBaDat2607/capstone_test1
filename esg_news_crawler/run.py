# -*- coding: utf-8 -*-
"""ESG news crawler — orchestrator.

Pipeline per company:
  generate queries -> run free search channels -> dedup candidate URLs ->
  fetch (cached) -> extract clean text + date -> sentence-split ->
  write <TICKER>.jsonl  (+ append to coverage.csv)

No ESG relevance filtering: every extracted article is kept. The downstream
model decides what is evidence.

Usage:
  python -m esg_news_crawler.run --xlsx company_annual_report.xlsx --ticker AAA
  python -m esg_news_crawler.run --limit 5 --max-articles 20
  python -m esg_news_crawler.run                 # all 115 companies
  python -m esg_news_crawler.run --reset          # ignore existing output
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urldefrag

from .companies import Company, load_companies
from .config import (
    DEFAULT_CACHE_DIR,
    DEFAULT_MAX_ARTICLES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SINCE_YEARS,
    SITE_DOMAINS,
    SKIP_URL_SUBSTRINGS,
)
from .extract import extract_article
from .fetch import Fetcher, domain_of
from .normalize import article_to_records
from .queries import base_queries, site_queries
from .sources import bing, ddg, google_news_rss

log = logging.getLogger("esg_news")

# Non-article portal / data pages worth skipping on top of config list.
_EXTRA_SKIP = ["/du-lieu/", "studocu", "staticfile.hsx", "static2.vietstock", "/Handlers/"]


def _canonical(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/")


def _should_skip(url: str) -> bool:
    low = url.lower()
    return any(s in low for s in SKIP_URL_SUBSTRINGS) or any(s in low for s in _EXTRA_SKIP)


def gather_candidates(fetcher, company: Company, *, num: int, since_years: int,
                      use_site: bool) -> list[dict]:
    """Run all channels for all queries; return deduped candidate dicts."""
    queries = base_queries(company)
    if use_site:
        queries += site_queries(company, SITE_DOMAINS)

    by_url: dict[str, dict] = {}
    for q in queries:
        channels = [("ddg", ddg.search)] if q.kind == "site" else [
            ("google_news", google_news_rss.search),
            ("bing", bing.search),
            ("ddg", ddg.search),
        ]
        for cname, cfunc in channels:
            try:
                results = cfunc(fetcher, q.text, num=num, since_years=since_years)
            except Exception as e:
                log.warning("  channel %s failed on %r: %s", cname, q.text[:50], e)
                continue
            for r in results:
                url = r.get("url", "")
                if not url.startswith("http") or _should_skip(url):
                    continue
                key = _canonical(url)
                if key in by_url:
                    continue
                by_url[key] = {
                    "url": url,
                    "title": r.get("title", ""),
                    "channel": r.get("channel", cname),
                    "query": q.text,
                    "terms": q.terms,
                    "kind": q.kind,
                }
    # Rank candidates with FREE signals (no extra fetch):
    #   1) does the search-result title name the company?  (on-target for this company)
    #   2) is it an ESG/controversy-keyword hit?            (the evidence we want)
    # Company-specific articles rise; generic topical ESG news sinks to fill
    # only leftover slots under --max-articles. Nothing is dropped here.
    names = [company.ticker.lower(), company.short.lower(), company.full_name.lower()]

    def rank(c: dict) -> tuple:
        t = c["title"].lower()
        names_hit = any(n and n in t for n in names)
        kw_hit = c["kind"] in ("keyword", "site")
        return (0 if names_hit else 1, 0 if kw_hit else 1)

    return sorted(by_url.values(), key=rank)


def crawl_company(fetcher, company: Company, *, out_dir: Path, max_articles: int,
                  since_years: int, use_site: bool) -> dict:
    log.info("[%s] %s", company.ticker, company.short)
    candidates = gather_candidates(
        fetcher, company, num=10, since_years=since_years, use_site=use_site
    )
    log.info("  %d candidate URLs", len(candidates))

    now = datetime.now().isoformat(timespec="seconds")
    records: list[dict] = []
    seen_titles: set[str] = set()
    n_articles = 0
    n_fetch_ok = 0
    by_domain: dict[str, int] = {}

    for cand in candidates:
        if n_articles >= max_articles:
            break
        _, html = fetcher.get_text(cand["url"])
        if not html:
            continue
        n_fetch_ok += 1
        art = extract_article(cand["url"], html)
        if not art or len(art.text) < 120:        # drop empty / stub pages
            continue
        tkey = (art.title or art.url).strip().lower()
        if tkey in seen_titles:
            continue
        seen_titles.add(tkey)

        recs = article_to_records(
            art, company,
            query=cand["query"], query_terms=cand["terms"],
            channel=cand["channel"], date_crawled=now,
        )
        records.extend(recs)
        n_articles += 1
        d = domain_of(art.url)
        by_domain[d] = by_domain.get(d, 0) + 1

    out_path = out_dir / f"{company.ticker}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    log.info("  -> %d articles, %d sentences -> %s", n_articles, len(records), out_path.name)
    return {
        "ticker": company.ticker,
        "company": company.full_name,
        "candidates": len(candidates),
        "fetched_ok": n_fetch_ok,
        "articles": n_articles,
        "sentences": len(records),
        "top_domains": ";".join(f"{k}:{v}" for k, v in sorted(by_domain.items(), key=lambda x: -x[1])[:5]),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", default="config/company_annual_report.xlsx")
    ap.add_argument("--ticker", action="append", help="Only crawl this ticker (repeatable).")
    ap.add_argument("--limit", type=int, default=None, help="Crawl only the first N companies.")
    ap.add_argument("--max-articles", type=int, default=DEFAULT_MAX_ARTICLES)
    ap.add_argument("--since-years", type=int, default=DEFAULT_SINCE_YEARS)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-site", action="store_true", help="Skip site:-restricted queries (faster).")
    ap.add_argument("--reset", action="store_true", help="Re-crawl even if <TICKER>.jsonl exists.")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    companies = load_companies(args.xlsx)
    if args.ticker:
        wanted = {t.upper() for t in args.ticker}
        companies = [c for c in companies if c.ticker.upper() in wanted]
    if args.limit:
        companies = companies[: args.limit]
    if not companies:
        log.error("No companies matched.")
        return 1

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(cache_dir=args.cache_dir, use_cache=not args.no_cache)

    cov_path = out_dir / "coverage.csv"
    cov_rows: list[dict] = []
    log.info("Crawling %d companies -> %s", len(companies), out_dir)

    for i, c in enumerate(companies, 1):
        out_path = out_dir / f"{c.ticker}.jsonl"
        if out_path.exists() and not args.reset:
            log.info("[%d/%d] skip %s (exists)", i, len(companies), c.ticker)
            continue
        log.info("[%d/%d] %s", i, len(companies), c.ticker)
        try:
            cov_rows.append(crawl_company(
                fetcher, c, out_dir=out_dir, max_articles=args.max_articles,
                since_years=args.since_years, use_site=not args.no_site,
            ))
        except KeyboardInterrupt:
            log.warning("interrupted — partial coverage saved")
            break
        except Exception as e:
            log.error("  failed %s: %s", c.ticker, e, exc_info=True)

    # Append/refresh coverage.csv
    if cov_rows:
        fields = ["ticker", "company", "candidates", "fetched_ok", "articles", "sentences", "top_domains"]
        write_header = not cov_path.exists()
        with open(cov_path, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            if write_header:
                w.writeheader()
            w.writerows(cov_rows)
        log.info("coverage -> %s", cov_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
