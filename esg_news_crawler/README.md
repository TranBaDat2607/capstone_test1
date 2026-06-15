# ESG News Crawler

Crawls Vietnamese news for the 115 companies in `config/company_annual_report.xlsx` and
emits **sentence-split JSONL** that flows through the *same* classifier path as the
annual reports — to be used as external evidence for greenwashing detection
(report ESG claims vs. real-world conduct).

## Design choices

- **Free scraping only** — no API keys. Channels: Google News RSS (most reliable),
  Bing (web + news), DuckDuckGo HTML (incl. `site:` queries to reach portals).
- **No relevance filtering.** Every extracted article is kept; a downstream model
  decides what is evidence. ESG/controversy keywords are used **only to retrieve**
  the rare relevant articles a bare ticker search would bury.
- **Retrieval beats sparsity by breadth**: per company we run plain-identity +
  ESG/controversy keyword queries across all channels, then rank candidates with
  free signals (does the search-result title name the company? is it a keyword
  hit?) so company-specific news rises and generic topical ESG news only fills
  leftover slots.
- **Robust extraction** via `trafilatura` (clean body + **publish date** + title
  across any domain) — far sturdier than per-site parsers.
- Reuses the report pipeline's own `data_processing.sentence_splitter` →
  identical sentence segmentation.

## Output

`data/outputs/news/<TICKER>.jsonl`, one sentence per line. The first four fields
match the annual-report schema exactly; the rest are news metadata / features:

```json
{"source_pdf":"AAA__vietnamnet.vn__1a2b3c4d5e","page":1,"sentence_index":1,
 "text":"Khai sai thuế, Nhựa An Phát Xanh bị xử lý hơn 1,7 tỷ đồng",
 "ticker":"AAA","company":"CTCP Nhựa An Phát Xanh","url":"https://...",
 "source_domain":"vietnamnet.vn","title":"...","publish_date":"2024-08-14",
 "date_crawled":"2026-06-14T10:50:00","channel":"google_news",
 "query":"AAA cổ phiếu","matched_terms":[],"company_mentioned":true}
```

- `source_pdf` is the article doc-id (`<TICKER>__<domain>__<hash>`) — the grouping key.
- `company_mentioned` / `matched_terms` are **soft features** for your model, not filters.
- `publish_date` lets you align a news item to a report year.

`data/outputs/news/coverage.csv` — per company: `candidates, fetched_ok, articles,
sentences, top_domains`. **Important for greenwashing:** thin coverage means
"little external evidence found", not "company is clean" — track it explicitly.

## Usage

```bash
pip install -r esg_news_crawler/requirements.txt

# one company (validation)
python -m esg_news_crawler.run --ticker AAA --max-articles 14 --no-site

# a few companies
python -m esg_news_crawler.run --limit 5

# all 115 (resumable — re-running skips tickers whose .jsonl exists)
python -m esg_news_crawler.run

# options
#   --max-articles N    cap per company (default 40)
#   --since-years N     recency window for Google News (default 5)
#   --no-site           skip site:-restricted queries (faster, less recall)
#   --reset             re-crawl even if output exists
#   --no-cache          bypass the HTML cache
```

Raw HTML is cached under `data/outputs/news/_cache/`, so re-runs and resume are
cheap and polite (per-domain rate limiting + backoff on 403/429 are built in).

## Notes / known limits

- A few portal *data* pages (e.g. Vietstock financial-report pages) can slip
  through with a wrong date or boilerplate text — harmless noise your model can
  drop via `company_mentioned` / short text.
- Google News link decoding uses Google's `batchexecute` endpoint; if Google
  changes it, a base64 fallback still recovers most URLs.
- This is polite scraping for research. Keep delays reasonable for the full run.
