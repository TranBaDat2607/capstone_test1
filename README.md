# Greenwashing Detection — Graph-RAG System

A **Graph-RAG pipeline for detecting greenwashing in Vietnamese listed companies**
(Construction / Building Materials / Real Estate sector). It ingests ESG statements
from annual reports and news, classifies them, extracts numeric KPIs, and builds a
**temporal ESG knowledge graph** so a company's *reported* ESG claims can be
cross-checked against its *real-world* conduct — surfacing evidence and an advisory
LLM assessment, not a greenwashing score (no ground-truth labels exist).

---

## Project structure

```
capstone_test1/
├── config/                        # Schema + dictionaries — no data files here
│   ├── schema.json                #   ~28 node classes / ~50 edge labels (source of truth)
│   ├── company_annual_report.xlsx #   Master list of companies (ticker, name, sector, URLs)
│   ├── kpi_type_aliases.json      #   KPI-name canonicalization aliases (step03c)
│   ├── standards_registry.json    #   Static config: TT96/QĐ2171/QCVN09/SSC-IFC/GRI aliases
│   ├── standard_crosswalk.json    #   TT96 → GRI equivalence rows (step05c)
│   ├── gri_catalog.json           #   136 GRI indicator codes (built by gri/, committed)
│   └── issuer_registry.json       #   Reporting-company alias/exclusion registry (step04 output)
│
├── data/                          # raw → interim → labeled → outputs (git-ignored, HF-synced)
├── graph_output/                  # graphs/, validated/, resolved/, crosscheck/, quality/  (git-ignored, HF-synced)
├── kpi_output/                    # Per-page KPIObservation JSON (git-ignored, HF-synced)
├── data_version.json              # Pins the HF dataset revision this commit was built against (tracked in Git)
│
├── crawl_data/                    # Annual-report crawling & downloading
│   ├── crawler.py                 #   FPT IR site crawler (nodriver / undetected Chrome)
│   ├── crawler_news.py            #   Legacy/experimental FPT-specific news crawler (not the pipeline path)
│   ├── download_reports.py        #   Download reports from the master xlsx (threaded, resumable)
│   └── extract_archives.py        #   .rar/.7z extraction (shells out to UnRAR.exe / 7z.exe)
│
├── data_processing/               # ESG extraction & classification (packages, run with -m)
│   ├── pdf_extractor.py           #   PyMuPDF text extraction (keeps page numbers, diacritics)
│   ├── sentence_splitter.py       #   Vietnamese-aware sentence segmentation (underthesea)
│   ├── prepare_sentences.py       #   Extract every sentence → JSONL (no ESG filter)
│   ├── esg_classifier.py          #   Multi-label ViDeBERTa-v3-ESG classifier wrapper (CPU)
│   ├── extract_esg.py             #   Labeled JSONL → trimmed ESG records for Graph-RAG
│   └── preprocess_news.py         #   P1: normalize publish dates, drop boilerplate
│
├── esg_news_crawler/              # Multi-channel ESG news retrieval (conduct side)
│   ├── run.py                     #   Orchestrator (per company: query → search → fetch → split)
│   ├── companies.py               #   Load companies & build identity sets from xlsx
│   ├── queries.py                 #   Build retrieval queries (identity + ESG/controversy terms)
│   ├── fetch.py                   #   Disk-cached, rate-limited HTTP fetcher
│   ├── extract.py                 #   trafilatura: clean HTML → title/text/date
│   ├── normalize.py               #   Article → sentence-split JSONL (annual-report schema)
│   ├── config.py                  #   Keyword groups, domains, defaults
│   ├── sources/                   #   Search channels (Google News RSS, Bing, DuckDuckGo)
│   └── README.md                  #   News-crawler design & usage
│
├── src/                           # esg_kg package: labeled JSONL → temporal knowledge graph
│   ├── run.py                     #   Dispatcher — `python src/run.py <stage>` (--list shows all 16/16)
│   ├── PIPELINE.md                #   Canonical run order + design history
│   └── esg_kg/
│       ├── pipeline.py            #   STAGES / BLOCKS table (single source of truth for run.py)
│       ├── DESIGN.md              #   Refactor design doc + closeout record (§7)
│       ├── core/                  #   Shared helpers: paths, schema, naming, dates, identity,
│       │                          #     io_jsonl, llm (RateLimiter; Gemini default, DeepSeek/OpenAI
│       │                          #     opt-in), llm_cache, graph_patch, datasync
│       ├── kpi/                   #   extract (step01), canonicalize (step03c)
│       ├── graph/                 #   extract_triples (step02), fix_triples (step03),
│       │                          #     anchor_kpi (step03b), build_validated (BLOCK 03→03b→03c)
│       ├── registry/              #   issuer (step04)
│       ├── resolve/               #   entities (step05), provenance (step05b), indicators (step05c),
│       │                          #     align_claims (step05d, optional LLM), build_resolved (BLOCK 05→05b→05c)
│       ├── load/                  #   neo4j_load (step06), neo4j_sync (step08, advisory layer)
│       ├── crosscheck/            #   claims_vs_conduct (step07 — the analytical core)
│       └── report/                #   quality (step00, Q1–Q8), claim_ledger (step09)
│
├── kpi_build/                     # Run-once: builds kpi_definitions_construction.json (35 KPIs,
│                                  #   Circular 96/2020, QĐ2171, QCVN09, SSC-IFC, verbatim + source blocks)
├── gri/                           # Run-once: crawls 42 GRI Standards PDFs → config/gri_catalog.json
│
├── neo4j/                         # init.cypher (constraints) + crosscheck_queries.cypher (analyst queries)
├── docker-compose.yml             # Neo4j on bolt://localhost:8687
│
├── api/                           # ESG Evidence View backend — pure stdlib http.server
│   ├── main.py                    #   Serves REST endpoints + static frontend/ on :8000
│   └── evidence_service.py        #   All data access — reads LIVE Neo4j (required, no mock)
├── frontend/                      # 3-column TT96/GRI evidence view (index.html + css/ + js/) — frozen UI
│
├── test/                          # Plain-assert scripts (no pytest), offline/free — see CLAUDE.md
├── notebooks/                     # Jupyter notebooks for manual validation (GPU classify, PDF extraction)
├── docs/                          # Per-stage design docs — see "Documentation map" below
│
├── EmeraldMind/                   # External reference implementation — READ-ONLY, not part of this
│                                  #   project, excluded from Git (see CLAUDE.md)
├── requirements.txt
└── README.md                      # (this file)
```

> **Layout principle:** code lives only in the package folders (`crawl_data/`,
> `data_processing/`, `esg_news_crawler/`, `src/`, `kpi_build/`, `gri/`, plus the UI
> pair `api/` + `frontend/`). Everything else is `config/` (schema + dictionaries),
> `neo4j/` (constraints + analyst queries), or `data/` (raw → interim → labeled →
> outputs). No data files inside code packages, with two named exceptions
> (`kpi_build/`, `gri/`) that keep their source PDFs beside the code for traceability.

---

## Pipeline architecture

Data flows left → right; each stage's output is the next stage's input.

### A. Ingestion → ESG sentences
```
crawl_data/download_reports.py    → data/raw/annual_report/
data_processing.prepare_sentences → data/interim/sentences/*.jsonl (every sentence, no filter)
   ├─ pdf_extractor.py      (PyMuPDF, page numbers + diacritics)
   └─ sentence_splitter.py  (underthesea, VN-aware segmentation)
ViDeBERTa-v3-ESG classifier       → data/labeled/       (multi-label E/S/G/Neutral per sentence)
data_processing.extract_esg       → data/outputs/esg_extracted/   (Graph-RAG-ready records)
```

### B. News ingestion (parallel evidence channel — the "conduct" side)
```
esg_news_crawler.run  → data/outputs/news/<TICKER>.jsonl + coverage.csv
   companies → queries → Google News RSS / Bing / DuckDuckGo → fetch → extract (trafilatura) → normalize
ViDeBERTa-v3-ESG classifier        → data/labeled/news_labeled/
data_processing.preprocess_news    → data/interim/news_preprocessed/  (date-normalize, drop boilerplate)
```
Reports are the **claim** side ("what they say"); news is the **conduct** side ("what they do").
Both feed the same `esg_kg` graph-construction path and land in one temporal KG.

> **Full-sector labeling is done — use the full-corpus files, not a per-company one.**
> `data/labeled/classified/all_sentences_classified.jsonl` (197 companies) and
> `data/labeled/news_labeled/all_news_sentences_classified.jsonl` (115 tickers) are the
> current classifier output. `data/labeled/annual_labeled/` (AAA-only pilot) and the
> `aaa_news_classified*`/`aaa_all_sentences*` files were superseded and removed from the
> HF dataset 2026-08-02 — they duplicated AAA under a different filename convention. See
> `CLAUDE.md` for the full story before assuming only AAA is labeled/extracted.

### C. Labeled JSONL → temporal knowledge graph (`src/esg_kg`, all 16/16 stages)

Run via `python src/run.py <stage>` from the repo root (`--list` shows every stage):

```
quality          (step00) → graph_output/quality/          — offline Q1–Q8 diagnostics, run before/after any change
extract          (step01) → kpi_output/                    — per-page KPIObservation extraction (Gemini/OpenAI)
extract_triples  (step02) → graph_output/graphs/            — page text + KPIs → temporal triples/graph
build_validated  BLOCK: fix_triples → anchor_kpi → canonicalize, writes all_validated_triples.json once
                     fix_triples   (step03)  — repair invalid triples, canonicalize dates
                     anchor_kpi    (step03b) — gazetteer-anchor KPIObservation → Facility (offline)
                     canonicalize  (step03c) — assign kpi_id from the 35-indicator vocabulary
issuer           (step04) → config/issuer_registry.json     — reporting-company alias registry (run-once)
build_resolved   BLOCK: entities → provenance → indicators, writes resolved_graph.json once
                     entities      (step05)  — collapse duplicate entity nodes (Stage A–D)
                     provenance    (step05b) — stamp source_doc/source_page back onto nodes
                     indicators    (step05c) — materialize the TT96/GRI indicator axis
align_claims     (step05d, optional LLM) → patches resolved_graph.json — topic-align remaining claims
neo4j_load       (step06) → Neo4j                            — load the resolved graph as a property graph
claims_vs_conduct (step07) → graph_output/crosscheck/        — the analytical core: claim↔conduct adjudication
neo4j_sync       (step08) → Neo4j advisory layer              — push dossiers onto claim nodes (no LLM)
claim_ledger     (step09) → stdout + graph_output/crosscheck/*.md — per-company claim ledger (reads Neo4j only)
```

Full per-stage flags and design rationale: `src/PIPELINE.md`, `src/esg_kg/DESIGN.md`, `docs/SYSTEM_DESIGN.md`.

### D. KPI vocabulary & GRI catalog (run-once provenance builders)
```
kpi_build/   → kpi_definitions_construction.json         (repo ROOT, not config/ — see core/paths.py:KPI_DEFS_PATH)
             (35 KPIs, Circular 96/2020 + QĐ2171 + QCVN09 + SSC-IFC, verbatim)
gri/         → config/gri_catalog.json                    (136 GRI indicator codes, built from 42 GRI
             Standards PDFs that are NOT redistributed here — see gri/README.md and NOTICE.md)
```

### E. ESG Evidence View UI (`api/` + `frontend/` — the demo surface)
A pure-stdlib `http.server` (`api/main.py`) serving REST endpoints backed by
**live Neo4j** (`api/evidence_service.py` — Neo4j is required, no mock data) plus the
static `frontend/` at `http://localhost:8000`. Shows only claims linked to a
`StandardIndicator` via `alignsWithIndicator`, so each card's E/S/G pillar comes from
the graph, not a guess.

---

## What you can run without data access

Read this before cloning with expectations. The pipeline's generated data
(`data/`, `graph_output/`, `kpi_output/`) is **not in this repository**. It ships through a
**private** Hugging Face dataset repo (~19 GB, revision pinned in `data_version.json`) that
requires an invitation to the `nammovuivui-capstone` org. There is no public mirror, because
the corpus is built from company annual reports and crawled news articles that are not ours
to redistribute (see [`NOTICE.md`](NOTICE.md)).

So, honestly, from a bare `git clone`:

| You want to | Works? | What you need |
| --- | --- | --- |
| Run the test suite (`python test/run_all.py`) | **Yes** | `pip install -r requirements.txt -r requirements-test.txt`. Data-backed arms run against the synthetic fixtures in `test/fixtures/` and say so; arms needing real corpus scale skip with a reason. |
| Read the code, schema and design docs | **Yes** | nothing |
| Rebuild the KPI vocabulary (`kpi_build/`) | **Yes** | network access to the Vietnamese regulator sites |
| Rebuild the GRI catalog (`gri/`) | **Yes** | download the GRI Standards PDFs yourself — [`gri/README.md`](gri/README.md) |
| Run any stage C pipeline stage | **No** | the private dataset **and** a paid `GEMINI_API_KEY` |
| Load Neo4j / run the Evidence View UI | **No** | a resolved graph, which needs the dataset |
| Reproduce the reported evaluation figures | **No** | the pinned 19 GB snapshot; see [`docs/EVALUATION_BASELINE.md`](docs/EVALUATION_BASELINE.md) |

The fixtures exist so the test suite is a real check rather than a decorative one for anyone
without data access — not as a stand-in for the corpus. If you are evaluating this project,
`python test/run_all.py` is the part you can actually execute.

## Onboarding (project team — requires private data access)

> This section assumes membership of the `nammovuivui-capstone` Hugging Face org and your own
> paid API keys. It is not a public setup path; see "What you can run without data access"
> above for that.

Generated data (`data/`, `graph_output/`, `kpi_output/` — ~342 MB) is **not in Git**.
It ships via a private Hugging Face dataset repo (`nammovuivui-capstone` org), so you do
**not** re-run the expensive stages: LLM extraction costs money, ESG labeling needs a
GPU, and the news crawl isn't reproducible. Four steps to a working setup:

```bash
# 1. Code + dependencies
git clone <this-repo-url> && cd capstone_test1
pip install -r requirements.txt

# 2. Secrets — never shared through Git or the dataset repo; use your OWN keys
cp .env.example .env      # then fill in GEMINI_API_KEY (optionally OPENAI_API_KEY — see CLAUDE.md)

# 3. Data — lands the exact snapshot this commit was built against
#    Ask the maintainer to invite you to the `nammovuivui-capstone` org first (private repo,
#    HF returns 404 either way if you're not invited); a fine-grained HF token needs org scope.
hf auth login             # or put HF_TOKEN in .env (a read token is enough)
python src/esg_kg/core/datasync.py pull

# 4. Neo4j — rebuilt locally, NOT downloaded (a live DB volume can't be copied safely)
docker compose up -d
python src/run.py neo4j_load --clear    # a few minutes, no LLM
```

Verify: `python src/run.py claim_ledger` should render the AAA claim ledger.

**How data and code stay in sync.** `data_version.json` (tracked in Git) pins the
dataset revision, so `git checkout <old-commit> && python src/esg_kg/core/datasync.py pull`
restores the data that commit was built against. `python src/esg_kg/core/datasync.py status`
shows pinned vs. local state and warns on drift.

**Publishing a new snapshot** (needs `write` in the org):

```bash
git pull                                                # surface a pin conflict here, not on the Hub
python src/esg_kg/core/datasync.py push --dry-run       # inspect what would go up
python src/esg_kg/core/datasync.py push                 # needs an HF *Write* token scoped to the org
git add data_version.json && git commit -m "data: refresh snapshot" && git push
```

A push whose pin isn't committed is the failure mode to avoid: the Hub has your new
data, `data_version.json` still points at the old revision, and the team keeps pulling
stale data with no error. Announce the push so nobody rebuilds on a snapshot you replaced.

---

## Quick start

```bash
pip install -r requirements.txt

# A. Annual report → labeled ESG sentences
python -m data_processing.prepare_sentences \
    --input  "data/raw/annual_report/Xây dựng - VLXD - BĐS/AAA - Nhựa An Phát Xanh/AAA_2024.pdf" \
    --output "data/interim/sentences/aaa_sentences.jsonl"
python -m data_processing.extract_esg

# B. News evidence for one company (conduct side)
python -m esg_news_crawler.run --ticker AAA --limit 1
python -m data_processing.preprocess_news

# C. Labeled JSONL → temporal knowledge graph
python src/run.py --list                                 # every stage + status
python src/run.py quality --label baseline                # offline Q1–Q8 snapshot
python src/run.py extract -i <labeled.jsonl>               # → kpi_output/
python src/run.py extract_triples -i <report_labeled.jsonl>
python src/run.py build_validated --dry-run                # then without --dry-run
python src/run.py issuer
python src/run.py build_resolved --dry-run                 # then without --dry-run
docker compose up -d
python src/run.py neo4j_load --clear
python src/run.py claims_vs_conduct                        # → graph_output/crosscheck/ (LLM, mandatory)
python src/run.py neo4j_sync
python src/run.py claim_ledger

# ESG Evidence View UI (reads live Neo4j)
python api/main.py                                         # http://localhost:8000
```

See `CLAUDE.md`'s "Common commands" for the full flag reference (`--dry-run`, `--no-llm`,
`--label`, etc.) and `src/PIPELINE.md` for stage-by-stage detail.

Provider selection is per stage, not global: `extract_triples` and `align_claims` take
`--provider gemini|deepseek`; `claims_vs_conduct` takes `--provider-order`
(`gemini|deepseek|openai`); and `extract`, `fix_triples` and `entities` are Gemini-only with
no provider flag at all.

The `extract_esg` output schema (one JSON object per line in
`data/outputs/esg_extracted/esg_all_records.jsonl`):

```json
{"source_file": "...", "source_pdf": "...", "page": 1, "sentence_index": 1,
 "text": "...", "labels": ["Governance"], "scores": {"Neutral": 0.08, "...": "..."}}
```

Sentence-level traceability (`source_pdf`, `page`, `sentence_index`) is preserved
through every stage, so every graph node can be traced back to its source.

---

## Testing

No pytest harness — tests are plain `assert` scripts under `test/`, run offline and free
(no LLM, no database, no network). Everything is runnable on a bare clone:

```bash
pip install -r requirements.txt -r requirements-test.txt
python test/run_all.py                 # everything: one exit code, one summary table
python test/run_all.py -k issuer       # just the files matching a substring
python test/test_temporal_invariants.py   # or any single file, directly
```

`run_all.py` reports how many assertions ran against the **real corpus** versus the
synthetic **fixtures** in `test/fixtures/`, because those are different claims. On a clone
without private data access every data-backed arm runs on fixtures, and arms that genuinely
need real corpus scale skip with a stated reason rather than lowering their thresholds.
[`test/README.md`](test/README.md) documents every file and its re-run trigger.

New code follows test-first (red → green → refactor) — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Documentation map

Start with `docs/SYSTEM_DESIGN.md` for the end-to-end design (claims vs. conduct, the
temporal KG, the advisory-not-a-score framing). Per-stage docs: `SCHEMA_EXPLAINED.md`,
`TEMPORAL_KG_DESIGN.md`, `KPI_EXTRACTION_FROM_JSONL.md`, `TRIPLET_EXTRACTION_FROM_JSONL.md`,
`TRIPLET_VALIDATION.md`, `PROVENANCE_PATCH.md`, `ENTITY_RESOLUTION.md`,
`GRAPH_LOAD_NEO4J.md`, `CLAIM_CONDUCT_CROSSCHECK.md`, `CLAIM_LEDGER.md`,
`ESG_EVIDENCE_VIEW.md`, `REAL_DATA_INTEGRATION_GUIDE.md`, `STANDARD_INDICATOR_AXIS.md`,
`GRI_SCHEMA_DOCUMENTATION.md`, `KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`,
`PIPELINE_DIAGRAMS.md`, `PIPELINE_UNIFIED.md`, `PROJECT_OVERVIEW.md`.
[`docs/README.md`](docs/README.md) indexes every document and says which are current, which
are frozen historical records, and which are unimplemented proposals.

Two documents are worth reading before changing anything: `docs/PROJECT_HISTORY.md` (closed
decisions — the refactor, the removed stages, the LLM-provider timeline) and
`docs/EVALUATION_BASELINE.md` (the frozen measurement snapshot; read it before quoting any
figure). Many docs are written in Vietnamese.

`CLAUDE.md` at the repo root is an **operating manual for AI coding agents**, not user
documentation. It is accurate and detailed about pipeline internals, but it is written to
instruct an agent and carries a lot of internal decision history; a human reader should
start with `docs/SYSTEM_DESIGN.md`.

---

## License and citation

Source code is MIT licensed — see [`LICENSE`](LICENSE). **That covers this project's code
only.** GRI Standards, the Vietnamese regulatory texts quoted in
`kpi_definitions_construction.json`, the annual reports and the crawled news articles each
retain their own terms; [`NOTICE.md`](NOTICE.md) sets out what is and is not covered.

If you reference this work, cite it via [`CITATION.cff`](CITATION.cff) (GitHub's "Cite this
repository" button reads that file).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). The two conventions that surprise people: tests are
plain `assert` scripts and test-first is mandatory, and paid LLM prompt templates are pinned
byte-for-byte by guard tests — a reworded prompt still "works" while silently changing every
verdict, which is exactly why the pin exists.

To report a security issue, see [`SECURITY.md`](SECURITY.md).
