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
├── config/                       # Configuration, schema & generated dictionaries
│   ├── schema.json               #   Graph-RAG node/edge schema (Organization, ESGClaim, …)
│   ├── company_annual_report.xlsx#   Master list of 115 companies (ticker, name, sector, URLs)
│   ├── vi_glosses.json           #   Hand-curated Vietnamese ESG terminology (for GRI mapper)
│   ├── esg_keywords_v2.json      #   ESG keyword dictionary      (generated)
│   ├── yake_candidates.json      #   YAKE keyword candidates     (generated)
│   └── candidates_review.csv     #   Human-review sheet          (generated)
│
├── data/                         # All data — NOT code
│   ├── raw/                      #   Inputs as collected
│   │   ├── annual_reports_sample/#     14 sample AAA annual reports (2010–2025)
│   │   ├── annual_report/        #     Downloaded reports (download_reports.py)
│   │   ├── crawled_annual_report/#     Crawled reports (crawler.py)
│   │   ├── crawl_data_news/      #     Crawled news (crawler_news.py)
│   │   ├── gri_standards/        #     Official GRI Standards PDFs (gri_loader.py input)
│   │   └── esg_source_documents/ #     Regulatory PDFs for keyword mining
│   ├── interim/                  #   Intermediate processing artifacts
│   │   ├── sentences/            #     Extracted/sentence-split JSONL + CSV
│   │   ├── news_sentences/       #     Sentence-split news
│   │   └── gri_taxonomy/         #     Parsed GRI taxonomy (gri_loader.py output)
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
│   ├── pipeline.py               #   Orchestrator: PDF → sentences → keyword/GRI filter → JSONL
│   ├── pdf_extractor.py          #   PyMuPDF text extraction (keeps page numbers, diacritics)
│   ├── sentence_splitter.py      #   Vietnamese-aware sentence segmentation (underthesea)
│   ├── esg_keywords.py           #   Keyword-dictionary matching
│   ├── gri_loader.py             #   Parse GRI Standards PDFs → taxonomy JSON
│   ├── gri_mapper.py             #   Map sentences → GRI disclosures (LaBSE embeddings)
│   ├── esg_classifier.py         #   Multi-label ViDeBERTa-v3-ESG classifier wrapper
│   ├── prepare_sentences.py      #   Extract every sentence (for Kaggle GPU classification)
│   ├── extract_keywords.py       #   YAKE candidate extraction from regulatory PDFs
│   ├── prune_candidates.py       #   Filter YAKE candidates → review CSV
│   ├── prune_rules.py            #   Rejection rules for keyword pruning
│   ├── compile_dictionary.py     #   Reviewed CSV → final keyword dictionary
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
download_reports.py            → data/raw/annual_report/
data_processing.pipeline       → data/interim/sentences/        (keyword + GRI filtered)
   ├─ pdf_extractor.py
   ├─ sentence_splitter.py
   ├─ esg_keywords.py
   └─ gri_mapper.py
data_processing.prepare_sentences → data/interim/sentences/     (every sentence, no filter)
notebooks/kaggle_esg_classify.ipynb  (ViDeBERTa-v3-ESG on GPU)  → data/labeled/
data_processing.extract_esg    → data/outputs/esg_extracted/    (Graph-RAG input)
```

### 2. News → ESG evidence
```
esg_news_crawler.run           → data/outputs/news/<TICKER>.jsonl + coverage.csv
   (companies → queries → Google News RSS / Bing / DuckDuckGo → fetch → extract → normalize)
```

### 3. ESG keyword dictionary (one-off, human-in-the-loop)
```
extract_keywords.py   → config/yake_candidates.json
prune_candidates.py   → config/candidates_review.csv   (human fills keep/pillar columns)
compile_dictionary.py → config/esg_keywords_v2.json    (used by esg_keywords.py)
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
