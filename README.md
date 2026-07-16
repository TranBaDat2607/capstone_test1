# Greenwashing Detection — Graph-RAG System

An AI **Graph-RAG** pipeline for detecting corporate **greenwashing** in Vietnamese
companies. It extracts ESG (Environmental / Social / Governance) statements from
**annual reports** and **news articles**, classifies them, and prepares the
evidence for knowledge-graph construction — so a company's *reported* ESG claims
can be cross-checked against its *real-world* conduct.

---

## Project structure

```
capstone_test1/
├── config/                       # Configuration & schema
│   ├── schema.json               #   Graph-RAG node/edge schema (Organization, ESGClaim, …)
│   └── company_annual_report.xlsx#   Master list of 115 companies (ticker, name, sector, URLs)
│
├── data/                         # All data — NOT code
│   ├── raw/                      #   Inputs as collected
│   │   ├── annual_reports_sample/#     14 sample AAA annual reports (2010–2025)
│   │   ├── annual_report/        #     Downloaded reports (download_reports.py)
│   │   ├── crawled_annual_report/#     Crawled reports (crawler.py)
│   │   └── crawl_data_news/      #     Crawled news (crawler_news.py)
│   ├── interim/                  #   Intermediate processing artifacts
│   │   ├── sentences/            #     Extracted/sentence-split JSONL + CSV
│   │   └── news_sentences/       #     Sentence-split news
│   ├── labeled/                  #   Labeled ESG sentences (model/human)
│   └── outputs/                  #   Final artifacts for the graph step
│       ├── esg_extracted/        #     Filtered ESG records (extract_esg.py)
│       └── news/                 #     Per-company news JSONL + coverage.csv + _cache/
│
├── crawl_data/                   # Annual-report crawling & downloading
│   ├── crawler.py                #   FPT IR site crawler (nodriver / undetected Chrome)
│   ├── crawler_news.py           #   Legacy news crawler
│   ├── download_reports.py       #   Download reports from the master xlsx (threaded, resumable)
│   └── extract_archives.py       #   Unzip/unrar/7z extraction
│
├── data_processing/              # ESG extraction & classification pipeline
│   ├── pdf_extractor.py          #   PyMuPDF text extraction (keeps page numbers, diacritics)
│   ├── sentence_splitter.py      #   Vietnamese-aware sentence segmentation (underthesea)
│   ├── prepare_sentences.py      #   Extract every sentence → JSONL (no ESG filter)
│   ├── esg_classifier.py         #   Multi-label ViDeBERTa-v3-ESG classifier wrapper
│   └── extract_esg.py            #   Labeled JSONL → trimmed ESG records for Graph-RAG
│
├── esg_news_crawler/             # Multi-channel ESG news retrieval
│   ├── run.py                    #   Orchestrator (per company: query → search → fetch → split)
│   ├── companies.py              #   Load companies & build identity sets from xlsx
│   ├── queries.py                #   Build retrieval queries (identity + ESG/controversy terms)
│   ├── fetch.py                  #   Disk-cached, rate-limited HTTP fetcher
│   ├── extract.py                #   trafilatura: clean HTML → title/text/date
│   ├── normalize.py              #   Article → sentence-split JSONL (annual-report schema)
│   ├── config.py                 #   Keyword groups, domains, defaults
│   ├── sources/                  #   Search channels (Google News RSS, Bing, DuckDuckGo)
│   └── README.md                 #   News-crawler design & usage
│
├── notebooks/
│   └── kaggle_esg_classify.ipynb #   Kaggle GPU: batched ViDeBERTa-v3-ESG inference
│
├── test/
│   └── test_pdf_extraction.ipynb #   Validates PyMuPDF extraction
│
├── requirements.txt
└── README.md                     # (this file)
```

> **Layout principle:** code lives in the package folders (`crawl_data/`,
> `data_processing/`, `esg_news_crawler/`); everything else is split into
> `config/` (configuration & dictionaries) and `data/` (raw → interim → labeled →
> outputs). No data files live inside code packages.

---

## Pipelines

### 1. Annual reports → ESG records
```
download_reports.py                  → data/raw/annual_report/
data_processing.prepare_sentences    → data/interim/sentences/   (every sentence, no filter)
   ├─ pdf_extractor.py
   └─ sentence_splitter.py
notebooks/kaggle_esg_classify.ipynb  (ViDeBERTa-v3-ESG on GPU)   → data/labeled/
   └─ esg_classifier.py              (same logic, runnable locally on CPU)
data_processing.extract_esg          → data/outputs/esg_extracted/  (Graph-RAG input)
```

The ViDeBERTa-v3-ESG model is the ESG detector — every sentence is classified, with
no keyword/GRI pre-filter.

### 2. News → ESG evidence
```
esg_news_crawler.run           → data/outputs/news/<TICKER>.jsonl + coverage.csv
   (companies → queries → Google News RSS / Bing / DuckDuckGo → fetch → extract → normalize)
```

---

## Onboarding (new team member — start here)

The generated data (`data/`, `graph_output/`, `kpi_output/` — ~330 MB) is **not in Git**.
It ships via a private Hugging Face dataset repo, so you do **not** re-run the expensive
stages: the LLM extraction costs money, the ESG labeling needs a GPU, and the news crawl
is not reproducible (the web moves). Four steps to a working setup:

```bash
# 1. Code + dependencies
git clone https://github.com/TranBaDat2607/capstone_test1.git && cd capstone_test1
pip install -r requirements.txt

# 2. Secrets — never shared through Git or the dataset repo; use your OWN keys
cp .env.example .env      # then fill in GEMINI_API_KEY (see CLAUDE.md)

# 3. Data — lands the exact snapshot this commit was built against
huggingface-cli login     # or put HF_TOKEN in .env (read token is enough)
python src/data_sync.py pull

# 4. Neo4j — rebuilt locally, NOT downloaded (a live DB volume cannot be copied safely)
docker compose up -d
python src/step06_load_graph_to_neo4j.py --clear    # a few minutes, no LLM
```

Verify: `python src/step09_report_claim_ledger.py` should render the AAA claim ledger.

**How data and code stay in sync.** `data_version.json` (tracked in Git) pins the dataset
revision, so `git checkout <old-commit> && python src/data_sync.py pull` restores the data
that commit was built against — that pin is what keeps the thesis baseline vs after-phase0
numbers reproducible. `python src/data_sync.py status` shows the pinned vs local state and
warns when they have drifted apart.

**Maintainer only** — after rebuilding the graph, publish the new snapshot and commit the pin:

```bash
python src/data_sync.py push --dry-run     # inspect what would go up
python src/data_sync.py push               # needs an HF write token
git add data_version.json && git commit -m "data: refresh snapshot"
```

---

## Quick start

```bash
pip install -r requirements.txt

# Extract sentences from the sample annual reports
python -m data_processing.prepare_sentences \
    --input  "data/raw/annual_reports_sample/AAA_Baocaothuongnien_2025.pdf" \
    --output "data/interim/sentences/aaa_sentences.jsonl"

# Filter labeled ESG sentences into Graph-RAG-ready records
python -m data_processing.extract_esg

# Crawl ESG news for one company
python -m esg_news_crawler.run --ticker AAA --limit 1
```

The `extract_esg` output schema (one JSON object per line in
`data/outputs/esg_extracted/esg_all_records.jsonl`):

```json
{"source_file": "...", "source_pdf": "...", "page": 1, "sentence_index": 1,
 "text": "...", "labels": ["Governance"], "scores": {"Neutral": 0.08, "...": "..."}}
```

Sentence-level traceability (`source_pdf`, `page`, `sentence_index`) is preserved
end-to-end so every graph node can be traced back to its source.
