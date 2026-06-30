# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A **Graph-RAG pipeline for detecting greenwashing in Vietnamese listed companies**
(Construction / Building Materials / Real Estate sector). It ingests ESG statements
from annual reports and news, classifies them, extracts numeric KPIs, and builds a
**temporal ESG knowledge graph** so a company's *reported* ESG claims can be
cross-checked against its *real-world* conduct.

## `EmeraldMind/` is a read-only reference — NOT part of this project

`EmeraldMind/` is an external reference implementation. **Never edit it and never
treat its files as part of this codebase** (don't list, refactor, or count them as
project files). You may read it to understand intent: `src/` here ports
`EmeraldMind/src/EmeraldKG/` steps 1→2→3 closely, then 4 (entity resolution) as a
**deliberate redesign** — all adapted to take **labeled JSONL** input (not PDFs) and a
**single `GEMINI_API_KEY`** (not a multi-key pool). When porting more EmeraldKG stages,
keep prompts/validation/output conventions identical so stages stay drop-in compatible;
when a stage is redesigned instead of ported (like step 4), document why in `docs/`.

## Environment & conventions

- **Windows / PowerShell** host. `.rar`/`.7z` extraction in `crawl_data/extract_archives.py`
  shells out to external **UnRAR.exe / 7z.exe** (install WinRAR + 7-Zip separately).
- **Secrets:** copy `.env.example` → `.env` and set `GEMINI_API_KEY`. All `src/` LLM
  scripts load `.env` from the repo root regardless of cwd.
- **Layout principle (enforced):** code lives only in the package folders
  (`crawl_data/`, `data_processing/`, `esg_news_crawler/`, `src/`, `kpi_build/`).
  Everything else is `config/` (schema + dictionaries) or `data/`
  (`raw/` → `interim/` → `labeled/` → `outputs/`). **No data files inside code packages.**
- **Two execution styles — do not mix them:**
  - `data_processing/` and `esg_news_crawler/` are **packages**, run as modules:
    `python -m data_processing.extract_esg`.
  - `src/` scripts are **standalone files** run directly (`python src/extract_triplet_from_jsonl.py`);
    they import each other by module name relying on Python putting `src/` on `sys.path`.
    Run them from the repo root.
- **Sentence-level traceability** (`source_pdf`, `page`, `sentence_index`) is preserved
  through every stage so each graph node traces back to its source — keep it intact.
- **Torch is intentionally absent from `requirements.txt`.** The ViDeBERTa ESG classifier
  runs on GPU via `notebooks/kaggle_esg_classify.ipynb`; install torch locally only to
  test `data_processing/esg_classifier.py` on CPU.

## Pipeline architecture (the big picture)

Data flows left→right; each stage's output is the next stage's input.

**A. Ingestion → ESG sentences**
```
crawl_data/download_reports.py   → data/raw/annual_report/        (threaded, resumable, from config/company_annual_report.xlsx)
data_processing.prepare_sentences → data/interim/sentences/*.jsonl (every sentence, NO ESG filter)
   ├─ pdf_extractor.py     (PyMuPDF, keeps page numbers + Vietnamese diacritics)
   └─ sentence_splitter.py (underthesea, VN-aware segmentation)
ViDeBERTa-v3-ESG classifier      → data/labeled/                  (multi-label E/S/G/Neutral per sentence)
   (notebooks/kaggle_esg_classify.ipynb on GPU; data_processing/esg_classifier.py = same logic, CPU)
data_processing.extract_esg      → data/outputs/esg_extracted/    (trimmed Graph-RAG-ready records)
```

**B. News ingestion (parallel evidence channel)**
```
esg_news_crawler.run → data/outputs/news/<TICKER>.jsonl + coverage.csv
   companies → queries → Google News RSS / Bing / DuckDuckGo → fetch (disk-cached, rate-limited)
            → extract (trafilatura) → normalize (sentence-split into the annual-report schema)
```

**C. Labeled JSONL → temporal knowledge graph (`src/`, the EmeraldKG port)**
```
src/extract_kpi_from_jsonl.py    → kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json
   (per page: Gemini 2.5 Flash w/ structured output → typed KPIObservation records,
    only pages with ≥1 esg=true sentence are sent; uses kpi_definitions_construction.json)
src/extract_triplet_from_jsonl.py → graph_output/graphs/<pdf_stem>/page{N}.json  (+ _bugged.json, _malformed.txt)
   (per page: page text + page KPIs + config/schema.json → temporal triples → node/edge graph)
src/fix_invalid_triplets.py      → graph_output/validated/all_validated_triples.json (+ unfixable_triples.json)
   (Phase 1 offline: swap reversed edge directions + schema-validate;
    Phase 2 LLM: batch-repair invalid triples; Phase 3: aggregate)
src/build_issuer_registry.py     → config/issuer_registry.json                       (run-once bootstrap)
   (drafts the reporting company's name variants → aliases / exclusions / needs_review;
    re-running preserves human edits, --force rebuilds; a human confirms needs_review)
src/resolve_entities.py          → graph_output/resolved/resolved_graph.json (+ _stats.json)
   (step 4: collapse duplicate entity nodes into canonical entities, keeping temporal history.
    Stage A deterministic identity_keys merge + FROZEN issuer anchor (issuer_registry.json);
    Stage B VN-aware blocking (normalized signature + gemini-embedding-001 cosine);
    Stage C gemini-2.5-flash adjudication on ambiguous pairs (budgeted); Stage D consolidate)
src/load_graph_to_neo4j.py       → Neo4j (bolt://localhost:8687, db `neo4j`)            (step 5)
   (load the resolved {nodes,edges} graph as a property graph — NO LLM. Nodes keyed by
    array index (entities already resolved; not re-deduped); edges keep temporal_metadata and
    MERGE on a temporal _edge_key so multi-year edges stay distinct; temporal_versions become
    supersedes version-node chains for supersedes-legal classes, else a JSON property)
```

The `src/` scripts share helpers by importing across files: later stages import
`REPO_ROOT`, `build_page_text`, `load_pages_from_jsonl`, `RateLimiter`, `load_schema_sets`,
`normalize_name`, etc. from the earlier ones (`extract_kpi_from_jsonl`,
`extract_triplet_from_jsonl`, `fix_invalid_triplets`, `build_issuer_registry`). Changing a
shared helper's signature affects every downstream stage.

**D. KPI definition builder (`kpi_build/`, run-once provenance pipeline)**
Stages `01_…`→`06_…` download official Vietnamese ESG regulations (Circular 96/2020,
QĐ 2171, QCVN 09, SSC-IFC guide) and extract them **verbatim** into
`kpi_definitions_construction.json` (35 KPIs, each carrying a `source` block). This file
is the controlled KPI vocabulary consumed by stage C's KPI extractor. It rarely needs
rebuilding; treat it as generated data.

## The graph schema (`config/schema.json`)

The single source of truth for the knowledge graph: ~28 node classes (Organization,
KPIObservation, Emission, SustainabilityClaim, Controversy, …) and ~50 directed edge
labels. Key invariants the `src/` validation relies on:
- **Every node carries temporal props** `valid_from`, `valid_to`, `is_current`; every
  edge carries `temporal_metadata` (`valid_from`, `valid_to`, `recorded_at`).
- Each node has `identity_keys` used to compute a stable entity id (for dedup/versioning).
  Observation classes (`KPIObservation`, `Emission`, `Waste`) are versioned per-observation;
  entities are versioned only when properties change (linked via `supersedes` edges).
- An edge label may appear with **multiple legal (source_class, target_class) pairs**;
  the validator treats any matching pair as valid and auto-swaps reversed directions.
See `docs/SCHEMA_EXPLAINED.md` for the rationale.

## Common commands

```bash
pip install -r requirements.txt

# A. Annual report → labeled ESG sentences
python -m data_processing.prepare_sentences \
    --input  "data/raw/annual_reports_sample/AAA_Baocaothuongnien_2025.pdf" \
    --output "data/interim/sentences/aaa_sentences.jsonl"
python -m data_processing.extract_esg            # labeled JSONL → esg_extracted records

# B. News evidence for one company
python -m esg_news_crawler.run --ticker AAA --limit 1

# C. Labeled JSONL → temporal KG (run from repo root, in order)
python src/extract_kpi_from_jsonl.py     -i <labeled.jsonl>            # → kpi_output/
python src/extract_triplet_from_jsonl.py -i <labeled.jsonl>            # → graph_output/graphs/
python src/fix_invalid_triplets.py                                    # → graph_output/validated/
python src/build_issuer_registry.py                                   # → config/issuer_registry.json (run-once; then hand-confirm needs_review)
python src/resolve_entities.py                                        # → graph_output/resolved/ (step 4: entity resolution)
python src/load_graph_to_neo4j.py --dry-run                           # step 5: preview planned counts, no DB
docker compose up -d                                                 # start Neo4j on :8687 (then run neo4j/init.cypher once — see docs)
python src/load_graph_to_neo4j.py --clear                            # → Neo4j (wipe + load; needs the instance running)

# Useful src/ flags: --doc <substr>, --limit-docs N, --all (scope);
#   --all-pages (don't restrict to ESG pages); --dry-run (fix/resolve/load steps: offline only, no LLM/DB/writes);
#   resolve: --no-llm (Stages A+B.1 only), --similarity-threshold, --max-llm-pairs (budget the LLM adjudication);
#   load: --clear (wipe first), --no-versions (canonical only), --database, --strict (env: NEO4J_URI/USER/PASSWORD)
```

There is no automated test suite or linter configured. `test/` and `notebooks/`
contain Jupyter notebooks for manual validation (e.g. `test/test_pdf_extraction.ipynb`),
not unit tests.

## Documentation map

`docs/` holds per-stage design notes worth reading before modifying a stage:
`SCHEMA_EXPLAINED.md`, `KPI_EXTRACTION_FROM_JSONL.md`, `TRIPLET_EXTRACTION_FROM_JSONL.md`,
`TRIPLET_VALIDATION.md`, `ENTITY_RESOLUTION.md` (step 4 — why it's a redesign, not a port),
`GRAPH_LOAD_NEO4J.md` (step 5 — Neo4j load; also a redesign),
`KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`, `VIETNAM_IMPROVEMENT_PLAN.md`. The root
`ENTITY_RESOLUTION_PLAN.md` is the step-4 engineering checklist. `README.md` (root),
`esg_news_crawler/README.md`, and `kpi_build/README.md` cover their respective subsystems.
