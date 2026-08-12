# News ingestion — the conduct channel

```bash
python -m esg_news_crawler.run --ticker AAA --limit 1
python -m esg_news_crawler.run                    # all companies
python -m data_processing.preprocess_news
```

Packages: `esg_news_crawler/` · `data_processing/preprocess_news.py` · Output:
`data/outputs/news/<TICKER>.jsonl` + `coverage.csv`, then
`data/interim/news_preprocessed/`

Reports are the **claim** side of the graph; independent news is the **conduct** side. This
subsystem produces the conduct side. Without it the cross-check has nothing to compare
against, and every claim comes back `unverified_insufficient_evidence`.

---

## 1. Pipeline

```
companies.py   load tickers + build identity phrase sets from the master xlsx
    ▼
queries.py     identity phrase × keyword OR-group  →  query list
    ▼
sources/       google_news_rss.py · bing.py · ddg.py      (free channels)
    ▼
dedup candidate URLs (fragment-stripped), drop SKIP_URL_SUBSTRINGS
    ▼
fetch.py       disk-cached, per-domain rate-limited, retrying
    ▼
extract.py     trafilatura → title / text / publish date
    ▼
normalize.py   sentence-split into the SAME schema as annual reports
    ▼
data/outputs/news/<TICKER>.jsonl  +  coverage.csv
```

**No ESG relevance filtering happens here.** Every extracted article is kept; the
downstream classifier and then the adjudicator decide what is evidence. Keywords are for
**retrieval only** — they exist to surface rare relevant articles, not to gate them.

That decision matters: a keyword gate at crawl time would quietly determine what
misconduct the system is capable of finding.

---

## 2. Retrieval strategy

### 2.1 Keyword groups

Four OR-groups, each becoming one query per identity phrase — wide coverage at a
manageable request count:

| Group | Terms |
|---|---|
| Sustainability claims | `ESG`, `phát triển bền vững`, `báo cáo phát triển bền vững`, `công trình xanh` |
| Environmental conduct | `môi trường`, `xả thải`, `ô nhiễm`, `xử phạt môi trường` |
| Emissions / transition | `phát thải`, `năng lượng tái tạo`, `Net Zero`, `giảm phát thải` |
| Social + governance | `tai nạn lao động`, `nợ bảo hiểm`, `thao túng`, `kiểm toán ngoại trừ` |

The last group is the one that finds most real contradictions: labour accidents, unpaid
insurance, market manipulation and qualified audit opinions are the misconduct that
actually gets reported about mid-cap Vietnamese issuers.

### 2.2 Curated domains

`SITE_DOMAINS` drives site-restricted queries across financial media (`cafef.vn`,
`vietstock.vn`, `tinnhanhchungkhoan.vn`, `vneconomy.vn`, `baodautu.vn`, `theleader.vn`,
`nhadautu.vn`, `ndh.vn`), national press (`vnexpress.net`, `tuoitre.vn`, `thanhnien.vn`,
`dantri.com.vn`, `plo.vn`, `laodong.vn`) and environment outlets
(`baotainguyenmoitruong.vn`, `moitruong.net.vn`).

`SKIP_URL_SUBSTRINGS` drops social platforms, video/gallery/tag paths and binary documents
outright.

### 2.3 Defaults

| Setting | Value | Reason |
|---|---|---|
| `DEFAULT_SINCE_YEARS` | 5 | ESG events are rare — a wide window is necessary |
| `DEFAULT_MAX_ARTICLES` | 40 per company, after dedup | |
| `DEFAULT_DOMAIN_DELAY` | 2.0 s between hits to the same domain | politeness, and avoiding blocks |
| `DEFAULT_TIMEOUT` / `DEFAULT_RETRIES` | 20 s / 3 | |

The fetcher caches to `data/outputs/news/_cache`, so re-runs are cheap and the crawl is
resumable. `--reset` ignores existing output.

---

## 3. `coverage.csv` is a deliverable, not a log

Per ticker: how many queries ran, how many candidate URLs were found, how many articles
were successfully extracted. This is the evidence behind the coverage caveat in
[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §8.3.

Thin coverage means *little external evidence was found*, not *the company is clean*. Every
company-level summary in the ledger displays these counts so absence of evidence is never
read as evidence of absence.

---

## 4. Classification, then preprocessing

Crawler output goes through the **same** ViDeBERTa-v3-ESG classifier as reports —
`data/labeled/news_labeled/all_news_sentences_classified.jsonl`, currently 115 tickers,
174,256 sentences, 77,229 marked `esg=true`.

Then `preprocess_news` does exactly two jobs, and only two:

### 4.1 Date normalization

News `publish_date` is unreliable: trafilatura emits placeholders like `2002-01-01`, some
values equal the crawl date, some are empty. The rule:

1. use `publish_date` when present and plausible (not a placeholder, not equal to the crawl
   date, within `[1990, current_year]`);
2. else parse a year from the URL or the article text;
3. else set `date_uncertain = true` and keep the crawl date only as a loose upper bound.

Adds `publish_date_normalized`, `publish_year`, `date_uncertain`. This is what the temporal
matching window in the cross-check aligns on, and `date_uncertain` propagates all the way
into the dossier caveats.

### 4.2 Boilerplate filtering

Drops rows using signals the crawler already emits — a failed `company_mentioned` check, or
near-empty text (`--min-chars`). It does **not** drop `esg=false` rows: the upstream ESG
gate is trusted downstream.

### 4.3 What it deliberately does not do

**No `source_domain` routing.** There is no independent / company-owned / aggregator
bucketing and no policy config file. Company PR mostly restates the annual report, so
routing it to the claim side would only create duplicate claims; the one risk routing
guarded against is handled by the self-verification guard at cross-check time
([SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §6.4).

Preprocessing is **non-destructive**: every original field is preserved, new fields are only
added. Sentence-level traceability must survive every stage.

---

## 5. Into the graph

```bash
python src/run.py extract_triples -i data/interim/news_preprocessed/... --source news
```

The news prompt produces `Controversy`, `MediaReport`, `Penalty`, observed
`KPIObservation` and `ThirdPartyVerification`, stamps `source_type=news`, and must decide
`date_uncertain` per fact. See
[TRIPLET_EXTRACTION_FROM_JSONL.md](TRIPLET_EXTRACTION_FROM_JSONL.md) §2.

---

## 6. `crawl_data/crawler_news.py` — the legacy standalone crawler

A separate, **FPT-specific** crawler that is *not* part of the pipeline above: not a `-m`
package, not wired into any stage. Treat it as a legacy/experimental tool.

It crawls four Vietnamese outlets (VnExpress, Tuổi Trẻ, Thanh Niên via Playwright for
client-side rendering, VietnamNet) plus Google site search for older 2010–2019 articles,
writing to `data/raw/crawl_data_news/{YEAR}/`.

Its design is worth knowing because the same four ideas were carried into
`esg_news_crawler`:

| Component | What it does |
|---|---|
| `DomainRateLimiter` | Per-domain semaphore + minimum delay (VnExpress 8 concurrent / 0.5 s; Google 1 concurrent / 3.0 s; others 3 / 1.0 s) |
| `ResponseCache` | SHA-1 of the URL as the cache filename; 24 h TTL for search pages, effectively permanent for article bodies |
| `ContentValidator` | Detects Cloudflare challenges, captchas and 403/502/503 by scanning `<title>` — deliberately **not** by grepping the body for "captcha", which false-positives on legitimate pages embedding social login scripts |
| `ThreadPoolExecutor` offload | Regex, BeautifulSoup, trafilatura and file writes run off the event loop so HTTP/2 connections are not starved |

Measured on a 2025–2026 range with three keywords: a sequential uncached version took
10–15 minutes and was prone to IP blocks; the concurrent cold run finished in 107.6 s
(~1.48 pages/s) and the warm run in 92.4 s at a 95% cache hit rate (195/205 requests served
from disk). Most of the remaining 92 s is the Playwright browser for Thanh Niên's
JavaScript search UI, which cannot be cached at the HTTP layer.

`python crawl_data/crawler_news.py --test` runs a quick benchmark.

---

## 7. Related

- [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §3 — the two-channel model and provenance tagging
- [PIPELINE_DIAGRAMS.md](PIPELINE_DIAGRAMS.md) §3 — the visual version
- `esg_news_crawler/README.md` — package-level usage
