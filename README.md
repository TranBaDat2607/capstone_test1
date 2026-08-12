# Greenwashing Detection — Graph-RAG System

A **Graph-RAG pipeline for surfacing greenwashing evidence about Vietnamese listed
companies** (Construction / Building Materials / Real Estate). It ingests ESG statements
from annual reports and independent news, classifies them, extracts numeric KPIs, and
builds a **temporal ESG knowledge graph** so a company's *reported* claims can be
cross-checked against its *real-world* conduct.

The output is **evidence plus an explicitly advisory assessment — never a greenwashing
score or label.** No ground-truth greenwashing dataset exists for Vietnamese companies, so
claiming a verdict would imply a truth the project does not have. See
[`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md) §1.1.

📖 **[Documentation index →](docs/README.md)**

---

## Onboarding — new team member, start here

Generated data (`data/`, `graph_output/`, `kpi_output/`) is **not in Git**. It ships via a
private Hugging Face dataset repo, so you do **not** re-run the expensive stages: LLM
extraction costs money, ESG labeling needs a GPU, and the news crawl is not reproducible.

```bash
# 1. Code + dependencies
git clone <this-repo-url> && cd capstone_test1
pip install -r requirements.txt

# 2. Secrets — never shared through Git or the dataset repo; use your OWN keys
cp .env.example .env          # then fill in GEMINI_API_KEY

# 3. Data — lands the exact snapshot this commit was built against.
#    Ask the maintainer to invite you to the `nammovuivui-capstone` org first: the repo is
#    private and Hugging Face returns 404 (not 403) if you are not a member.
hf auth login                  # or put HF_TOKEN in .env; a read token is enough
python src/esg_kg/core/datasync.py pull

# 4. Neo4j — rebuilt locally, NOT downloaded (a live DB volume cannot be copied safely)
docker compose up -d
docker cp neo4j/init.cypher greenwashing-kg:/tmp/init.cypher      # one-time bootstrap
docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui -d system -f /tmp/init.cypher
python src/run.py neo4j_load --clear
```

Verify: `python src/run.py claim_ledger` renders the AAA claim ledger.

**How data and code stay in sync.** `data_version.json` is tracked in Git and pins the
dataset revision, so `git checkout <old-commit>` followed by a `pull` restores the data that
commit was built against. `datasync.py status` shows pinned versus local state.

**Publishing a snapshot** (needs org `write`):

```bash
git pull                                                # surface a pin conflict in Git, not on the Hub
python src/esg_kg/core/datasync.py push --dry-run
python src/esg_kg/core/datasync.py push
git add data_version.json && git commit -m "data: refresh snapshot" && git push
```

> A push whose pin is not committed is **invisible**: the Hub has the new data,
> `data_version.json` still points at the old revision, and the team keeps pulling stale
> data with no error. Full details in [`docs/DATA_SYNC.md`](docs/DATA_SYNC.md).

---

## Quick start

```bash
# A. Annual report → labeled ESG sentences
python -m data_processing.prepare_sentences \
    --input  "data/raw/annual_reports_sample/AAA_Baocaothuongnien_2025.pdf" \
    --output "data/interim/sentences/aaa_sentences.jsonl"
python -m data_processing.extract_esg

# B. News evidence for one company (the conduct side)
python -m esg_news_crawler.run --ticker AAA --limit 1
python -m data_processing.preprocess_news

# C. Labeled JSONL → temporal knowledge graph
python src/run.py --list                                  # every stage + status
python src/run.py quality --label baseline                 # offline Q1–Q8 snapshot
python src/run.py extract -i <labeled.jsonl>               # → kpi_output/
python src/run.py extract_triples -i <report_labeled.jsonl>            # claim side
python src/run.py extract_triples -i <news_preprocessed.jsonl> --source news
python src/run.py build_validated --dry-run                 # then without --dry-run
python src/run.py issuer                                    # run-once; hand-confirm needs_review
python src/run.py build_resolved --dry-run                  # then without --dry-run
docker compose up -d
python src/run.py neo4j_load --clear
python src/run.py claims_vs_conduct                         # LLM adjudication (mandatory)
python src/run.py neo4j_sync
python src/run.py claim_ledger

# ESG Evidence View UI (reads live Neo4j)
python api/main.py                                          # http://localhost:8000
```

Run `quality --label after-<change>` when you are done and compare the two reports. The
stage is offline and free.

---

## Pipeline at a glance

```
A. Reports ──▶ sentences ──▶ ESG labels ──▶ ESG records ─┐
                                                          ├──▶ C. esg_kg ──▶ Neo4j ──▶ ledger + UI
B. News    ──▶ articles  ──▶ ESG labels ──▶ preprocessed ─┘
```

Reports are the **claim** side ("what they say"); news is the **conduct** side ("what they
do"). Both are stamped `source_type` and land in one temporal graph, which is what makes
the comparison structural rather than circular.

### The 16 stages

| Stage | Id | Cost | Output |
|---|---|---|---|
| `quality` | 00 | free | Q1–Q8 + R1/R5/R7 report |
| `extract` | 01 | Gemini | `kpi_output/` |
| `extract_triples` | 02 | Gemini/DeepSeek | `graph_output/graphs/` |
| `fix_triples` · `anchor_kpi` · `canonicalize` | 03 / 03b / 03c | Gemini (phase 2 only) | `all_validated_triples.json` |
| **`build_validated`** | block | | 03 → 03b → 03c, written **once** |
| `issuer` | 04 | free | `config/issuer_registry.json` |
| `entities` · `provenance` · `indicators` | 05 / 05b / 05c | optional | `resolved_graph.json` |
| **`build_resolved`** | block | | 05 → 05b → 05c, written **once** |
| `align_claims` | 05d | Gemini/DeepSeek | optional indicator alignment |
| `export_kgc` | 11 | free | separate export view |
| `neo4j_load` | 06 | free | Neo4j base graph |
| `claims_vs_conduct` | 07 | **mandatory LLM** | advisory dossiers |
| `neo4j_sync` | 08 | free | Neo4j advisory layer |
| `claim_ledger` | 09 | free | per-company ledger |

**Always run the blocks.** `build_validated` and `build_resolved` exist because their
member stages each read *and* write the same artifact — running the first alone silently
destroys what the later ones added, including results that were paid for.

---

## Project structure

```
capstone_test1/
├── config/                         # Schema + dictionaries — no data files here
│   ├── schema.json                 #   28 node classes / 48 edge labels (source of truth)
│   ├── company_annual_report.xlsx  #   Master company list (ticker, name, sector, URLs)
│   ├── issuer_registry.json        #   Issuer alias/exclusion registry (stage 04, hand-confirmed)
│   ├── standards_registry.json     #   Static config: TT96/QĐ2171/QCVN09/SSC-IFC/GRI name variants
│   ├── kpi_type_aliases.json       #   KPI canonicalization aliases + unit rules (stage 03c)
│   ├── standard_crosswalk.json     #   TT96 → GRI equivalence rows (stage 05c)
│   ├── gri_catalog.json            #   136 GRI codes (built by gri/, committed)
│   ├── degenerate_relations.json   #   Relations excluded from R1_trainable
│   └── subsidiaries/               #   Extracted ownership tables, 108 tickers — NOT yet wired in
│
├── kpi_definitions_construction.json   # The 35-indicator vocabulary (built by kpi_build/)
├── data_version.json               # Pins the HF dataset revision (tracked in Git)
│
├── data/                           # raw → interim → labeled → outputs   (git-ignored, HF-synced)
├── graph_output/                   # graphs, validated, resolved, crosscheck, quality, export_kgc
├── kpi_output/                     # per-page KPIObservation JSON
│
├── crawl_data/                     # Report crawling & downloading
│   ├── download_reports.py         #   Threaded, resumable, from the master xlsx
│   ├── extract_archives.py         #   .rar/.7z (shells out to UnRAR.exe / 7z.exe)
│   ├── crawler.py                  #   FPT IR site crawler (nodriver)
│   └── crawler_news.py             #   Legacy FPT-specific news crawler (not the pipeline path)
│
├── data_processing/                # run with -m
│   ├── pdf_extractor.py            #   PyMuPDF — keeps page numbers and diacritics
│   ├── sentence_splitter.py        #   underthesea, VN-aware
│   ├── prepare_sentences.py        #   Every sentence → JSONL (no ESG filter)
│   ├── esg_classifier.py           #   ViDeBERTa-v3-ESG wrapper (CPU)
│   ├── extract_esg.py              #   Labeled JSONL → trimmed ESG records
│   └── preprocess_news.py          #   Date normalization + boilerplate drop
│
├── esg_news_crawler/               # Multi-channel ESG news retrieval (conduct side)
│   ├── run.py  companies.py  queries.py  fetch.py  extract.py  normalize.py  config.py
│   └── sources/                    #   Google News RSS · Bing · DuckDuckGo
│
├── src/                            # The esg_kg package tree
│   ├── run.py                      #   Dispatcher — `python src/run.py <stage>`
│   ├── PIPELINE.md                 #   Canonical run order
│   └── esg_kg/
│       ├── pipeline.py             #   STAGES / BLOCKS table (single source of truth)
│       ├── DESIGN.md               #   Refactor record
│       ├── core/                   #   paths · schema · naming · dates · identity · io_jsonl
│       │                           #     llm · llm_cache · graph_patch · datasync · console
│       ├── kpi/                    #   extract (01) · canonicalize (03c)
│       ├── graph/                  #   extract_triples (02) · fix_triples (03) · anchor_kpi (03b)
│       │                           #     build_validated (block)
│       ├── registry/               #   issuer (04)
│       ├── resolve/                #   entities (05) · provenance (05b) · indicators (05c)
│       │                           #     align_claims (05d) · build_resolved (block)
│       ├── load/                   #   neo4j_load (06) · neo4j_sync (08)
│       ├── crosscheck/             #   claims_vs_conduct (07)
│       ├── export/                 #   export_kgc (11)
│       ├── metric/                 #   hub · reasoning_readiness (R1/R5/R7)
│       └── report/                 #   quality (00) · claim_ledger (09)
│
├── kpi_build/                      # Run-once: builds kpi_definitions_construction.json
├── gri/                            # Run-once: 42 GRI PDFs → config/gri_catalog.json
│
├── neo4j/                          # init.cypher + crosscheck_queries.cypher
├── docker-compose.yml              # Neo4j 5 Enterprise — bolt :8687, browser :8474
│
├── api/                            # ESG Evidence View backend — pure stdlib http.server
│   ├── main.py                     #   REST endpoints + static frontend on :8000
│   └── evidence_service.py         #   ALL data access — live Neo4j (required, no mock)
├── frontend/                       # 3-column TT96/GRI view (index.html + css/ + js/) — frozen
│
├── test/                           # 38 plain-assert scripts, offline and free
├── notebooks/                      # Jupyter notebooks for manual validation
├── docs/                           # See docs/README.md
└── EmeraldMind/                    # Read-only external reference — NOT part of this project
```

> **Layout principle:** code lives only in the package folders (`crawl_data/`,
> `data_processing/`, `esg_news_crawler/`, `src/`, `kpi_build/`, `gri/`, plus the UI pair
> `api/` + `frontend/`). Everything else is `config/`, `neo4j/`, or `data/`. No data files
> inside code packages, with two named exceptions — `kpi_build/` and `gri/` — which are
> run-once provenance builders that keep their sources beside the code so a claim can be
> traced back to a page.

---

## Configuration

Copy `.env.example` → `.env` at the repo root. Every stage loads it regardless of the
working directory; it is git-ignored and must never be committed.

```dotenv
GEMINI_API_KEY=...              # required
GEMINI_MODEL=gemini-2.5-flash-lite     # optional — one constant drives every LLM stage
DEEPSEEK_API_KEY=...            # optional, for --provider deepseek
OPENAI_API_KEY=...              # optional, for --provider-order openai
LLM_PROVIDER=gemini             # default provider for stages that accept one
HF_TOKEN=...                    # or use `hf auth login`
NEO4J_URI=bolt://localhost:8687
```

Gemini is the working default. DeepSeek and OpenAI are **swappable alternatives you opt
into**, not an automatic fallback cascade. `extract`, `fix_triples` and `entities` are
Gemini-only, because they use Gemini-specific context caching. See
[`docs/LLM_PROVIDERS_AND_CACHING.md`](docs/LLM_PROVIDERS_AND_CACHING.md).

### Deliberately unlisted dependencies

Some packages are imported lazily and left out of `requirements.txt` so a bare clone still
runs:

| Package | Used by | Without it |
|---|---|---|
| `torch` | `data_processing/esg_classifier.py` | Classification runs on GPU via the Kaggle notebook instead |
| `huggingface_hub` | `core/datasync.py` | The sync tool must work before pipeline deps are installed |
| `rapidfuzz` | `canonicalize` fuzzy tier | The tier is disabled with a warning; everything else runs |

`.rar`/`.7z` extraction shells out to external **UnRAR.exe / 7z.exe** — install WinRAR and
7-Zip separately (Windows / PowerShell host).

---

## Useful flags

```
--dry-run          offline preview on most stages (NOT free on claims_vs_conduct)
--doc / --limit-docs / --all       scope a run
--all-pages        do not restrict to ESG-labelled pages
quality            --label <name>, --skip-slow, --max-hops, --issuer-registry
extract_triples    --source report|news, --provider gemini|deepseek, --no-context-cache
fix_triples        --renormalize (date pass only, no LLM)
canonicalize       --aliases, --fuzzy-threshold, --no-goals
entities           --no-llm (Stages A+B.1 only), --similarity-threshold, --max-llm-pairs
indicators         --crosswalk, --no-gri, --no-align, --trust-draft-crosswalk
align_claims       --max-llm-pairs, --provider gemini|deepseek
export_kgc         --max-bucket-degree (default 500)
neo4j_load         --clear, --no-versions, --database, --strict
claims_vs_conduct  --max-llm-pairs, --provider-order, --top-k, --embed, --to-neo4j
neo4j_sync         --clear-advisory
claim_ledger       --review-queue, --assessment, --claim-id, --markdown
```

---

## Testing

No pytest harness and no linter — tests are plain `assert` scripts under `test/`, run
offline and free (no LLM, no database, no network):

```bash
python test/test_schema_contract.py        # after ANY schema edit
python test/test_temporal_invariants.py    # after touching 03/03b/03c/05/05b/05c/08
python test/test_esg_kg_equivalence.py     # after touching a core/ helper
```

New code is **test-first**: red → green → refactor, with no production code landing without
a failing test that demanded it. Full suite map in [`docs/TESTING.md`](docs/TESTING.md).

Paid integration tests exist but are gated behind `RUN_LLM_INTEGRATION_TESTS=1` /
`RUN_LLM_SYSTEM_TEST=1`. Never verify a change by re-running a paid stage.

---

## Documentation

Start at [`docs/README.md`](docs/README.md). The three most-read documents:

- [`docs/SYSTEM_DESIGN.md`](docs/SYSTEM_DESIGN.md) — the end-to-end design and the
  no-ground-truth constraint behind every decision
- [`docs/SCHEMA_EXPLAINED.md`](docs/SCHEMA_EXPLAINED.md) +
  [`docs/TEMPORAL_KG_DESIGN.md`](docs/TEMPORAL_KG_DESIGN.md) — read before touching the
  schema
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — what is not built, and what was rejected on purpose

`CLAUDE.md` holds the working rules for this codebase; `src/PIPELINE.md` and
`src/esg_kg/DESIGN.md` hold the run order and the refactor record.
