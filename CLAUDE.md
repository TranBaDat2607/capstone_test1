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
It is **excluded from git** (`.gitignore` → `EmeraldMind/`) — it has its own `.git`
repo and secrets, so it is never committed or pushed with this project.

## Environment & conventions

- **Windows / PowerShell** host. `.rar`/`.7z` extraction in `crawl_data/extract_archives.py`
  shells out to external **UnRAR.exe / 7z.exe** (install WinRAR + 7-Zip separately).
- **Generated data is distributed via Hugging Face, not Git** (`src/data_sync.py`, not a
  pipeline step): `data/`, `graph_output/`, `kpi_output/` are git-ignored (~342 MB) and ship
  as an HF dataset repo. The pushed revision is **pinned in `data_version.json`, which IS
  tracked in Git** — so a checkout recovers the data that went with that code, which is what
  makes the baseline vs after-Phase-0 comparison reproducible. Never re-run an expensive stage
  to get data a teammate already pushed; `pull` it. Needs `huggingface_hub` (imported lazily,
  deliberately not in `requirements.txt` so the tool works on a bare clone) and `HF_TOKEN` in
  `.env` (or `hf auth login`). The repo lives in the `nammovuivui-capstone` **org**, not a personal
  namespace — HF has no collaborator feature for user-owned repos, so an org is the only way to
  share a private one; you must be invited to it (`read` to pull, `write` to push) or it 404s.
  **Anyone pushing must commit `data_version.json` in the same sitting** — a pushed snapshot whose
  pin is not committed is invisible: the team keeps pulling the old revision with no error. `git pull`
  before pushing, so a pin conflict surfaces in Git rather than silently overwriting someone's
  snapshot. `neo4j_data/` is never synced — rebuild it with step06.
- **Secrets:** copy `.env.example` → `.env` and set `GEMINI_API_KEY` (and optionally
  `OPENAI_API_KEY`, the fallback LLM provider for step 6's cross-check). All `src/` LLM
  scripts load `.env` from the repo root regardless of cwd. `.env` is git-ignored — never
  commit it.
- **Layout principle (enforced):** code lives only in the package folders
  (`crawl_data/`, `data_processing/`, `esg_news_crawler/`, `src/`, `kpi_build/`).
  Everything else is `config/` (schema + dictionaries) or `data/`
  (`raw/` → `interim/` → `labeled/` → `outputs/`). **No data files inside code packages.**
- **Two execution styles — do not mix them:**
  - `data_processing/` and `esg_news_crawler/` are **packages**, run as modules:
    `python -m data_processing.extract_esg`.
  - `src/` scripts are **standalone files** run directly (`python src/step02_extract_triplet_from_jsonl.py`);
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

**B. News ingestion (parallel evidence channel = the "conduct" side)**
```
esg_news_crawler.run → data/outputs/news/<TICKER>.jsonl + coverage.csv
   companies → queries → Google News RSS / Bing / DuckDuckGo → fetch (disk-cached, rate-limited)
            → extract (trafilatura) → normalize (sentence-split into the annual-report schema)
ViDeBERTa-v3-ESG classifier      → data/labeled/news_labeled/       (same classifier as reports)
data_processing.preprocess_news  → data/interim/news_preprocessed/  (P1: normalize publish dates,
   add publish_date_normalized / publish_year / date_uncertain, drop boilerplate; NO domain routing)
```
Reports are the **claim** side ("what they say"); news is the **conduct** side ("what they do").
Both feed the same `src/` graph-construction path and land in one temporal KG (see `docs/SYSTEM_DESIGN.md`).

`crawl_data/crawler_news.py` is a separate, FPT-specific standalone news crawler (not a
`-m` package, not wired into pipeline B above) — treat it as a legacy/experimental tool, not
the documented news-ingestion path. See `docs/NEWS_CRAWLER_OPTIMIZATION.md` for its design.

**C. Labeled JSONL → temporal knowledge graph (`src/`, the EmeraldKG port)**
```
src/step00_graph_quality_report.py      → graph_output/quality/quality_report_<label>.{json,md}
   (offline diagnostics, NO LLM/DB: measures the Q1–Q8 quality attributes of the resolved
    graph — consistency incl. P4 temporal invariants + P1 identity lint, conciseness,
    conduct completeness, Q7 traversability (median degree / leaves / masked-answerable /
    hub-free structural claim→conduct / T2 anchoring). Run BEFORE and AFTER any
    schema/pipeline change with --label; see docs/TEMPORAL_KG_DESIGN.md §4)
src/step01_extract_kpi_from_jsonl.py    → kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json
   (per page: Gemini 2.5 Flash w/ structured output → typed KPIObservation records,
    only pages with ≥1 esg=true sentence are sent; uses kpi_definitions_construction.json)
src/step02_extract_triplet_from_jsonl.py → graph_output/graphs/<pdf_stem>/page{N}.json  (+ _bugged.json, _malformed.txt)
   (per page: page text + page KPIs + config/schema.json → temporal triples → node/edge graph.
    --source report (default) = claim-side prompt; --source news = conduct-side prompt (Controversy/
    MediaReport/Penalty/observed KPIObservation); every node/edge stamped source_type=report|news)
src/step03_fix_invalid_triplets.py      → graph_output/validated/all_validated_triples.json (+ unfixable_triples.json)
   (Phase 1 offline: swap reversed edge directions + schema-validate;
    Phase 1.5 offline (P4): canonicalize dates to ISO YYYY[-MM[-DD]], warn valid_from>valid_to,
    default missing date_uncertain on news T2 nodes; --renormalize applies only this phase to
    the existing aggregated file (no LLM, keeps prior repairs);
    Phase 2 LLM: batch-repair invalid triples; Phase 3: aggregate)
src/step03b_anchor_kpi_facilities.py    → appends to all_validated_triples.json (+ anchor_patch_stats.json)
   (P3 offline patch, NO LLM: gazetteer of Facility names already in the graph matched against
    each KPI's source sentence (source_id → labeled JSONL) → emits KPIObservation
    --observedAtFacility--> Facility edges, tagged anchor_method=offline_gazetteer.
    Run after step03, before step05. New extractions get anchors from the step02 prompt instead)
src/step04_build_issuer_registry.py     → config/issuer_registry.json                       (run-once bootstrap)
   (drafts the reporting company's name variants → aliases / exclusions / needs_review;
    re-running preserves human edits, --force rebuilds; a human confirms needs_review)
src/step05_resolve_entities.py          → graph_output/resolved/resolved_graph.json (+ _stats.json)
   (step 4: collapse duplicate entity nodes into canonical entities, keeping temporal history.
    Stage A deterministic identity_keys merge + FROZEN issuer anchor (issuer_registry.json);
    Stage B VN-aware blocking (normalized signature + gemini-embedding-001 cosine);
    Stage C gemini-2.5-flash adjudication on ambiguous pairs (budgeted); Stage D consolidate)
src/step05b_stamp_provenance.py         → patches resolved_graph.json in place (+ provenance_patch_stats.json)
   (offline provenance patch, NO LLM: matches claim/evidence nodes (PROVENANCE_CLASSES, never
    T1 entities) back to the per-page graph_output/graphs/<doc>/page{N}.json files via a 4-tier
    precedence (parseable source_id → exact source_id index → recomputed stable_id → _pageNN_
    token) and stamps source_doc/source_page (+ article_title/url/domain for news docs from the
    news JSONL). NEVER reorders nodes (step06 _node_key + dossier node_index are positional).
    Run after step05, before step06; re-run after any step05 re-run. New step02 extractions
    self-stamp (provenance_method=extraction) and are skipped. See docs/PROVENANCE_PATCH.md)
src/step06_load_graph_to_neo4j.py       → Neo4j (bolt://localhost:8687, db `neo4j`)            (step 5)
   (load the resolved {nodes,edges} graph as a property graph — NO LLM. Nodes keyed by
    array index (entities already resolved; not re-deduped); edges keep temporal_metadata and
    MERGE on a temporal _edge_key so multi-year edges stay distinct; temporal_versions become
    supersedes version-node chains for supersedes-legal classes, else a JSON property)
src/step07_crosscheck_claims_vs_conduct.py → graph_output/crosscheck/<ticker>_claim_assessments.json   (step 6)
   (the analytical core: for each SustainabilityClaim, retrieve conduct-side candidates →
    LLM-adjudicate supports/contradicts/irrelevant → write verifiedBy / contradictedBy* edges.
    LLM adjudication is MANDATORY (no deterministic fallback) — multi-provider cascade
    (--provider-order gemini,openai): gemini-2.5-flash primary, OpenAI gpt-4o-mini fallback;
    aborts up front if neither provider is available. Self-verification guard drops
    company-own-domain "verify" edges. Emits advisory dossiers — NO greenwashing score/label.
    --dry-run / --to-neo4j)
src/step08_sync_crosscheck_to_neo4j.py  → Neo4j advisory layer                                        (step 6b)
   (NO LLM — reuses the paid step-6 dossier. MERGEs assessment/caveats/signals onto claim nodes +
    llm_supports / llm_contradicts / llm_flagged_support evidence edges (incl. KPI contradictions
    the base schema can't express). Idempotent; --clear-advisory, --dry-run)
src/step09_report_claim_ledger.py       → stdout + graph_output/crosscheck/<ticker>_claim_ledger.md   (step 7)
   (presentation only — NO LLM, reads ONLY Neo4j (run step 6b first). Per-company claim ledger,
    signal-first (contradicted → supported → unverified), with the coverage caveat.
    --review-queue (contradiction + no verification), --assessment, --claim-id, --markdown)
src/step10_evaluate.py                  → graph_output/evaluation/<ticker>_evaluation_report.md      (step 8 / P6)
   (evaluation WITHOUT ground truth — measures the evidence-linking machinery, never
    "greenwashing accuracy": coverage metrics + case studies + manual link-precision
    methodology + ablations. Offline-first (reads the step-6 dossiers/stats + coverage.csv);
    the ONLY paid part is a fixed 30-case OpenAI gold-set arm, and it is cached.
    Rendered report is in Vietnamese; code/comments stay English. --coverage,
    --case-studies, --ablation, --no-llm)
```

The `src/` scripts share helpers by importing across files: later stages import
`REPO_ROOT`, `build_page_text`, `load_pages_from_jsonl`, `RateLimiter`, `load_schema_sets`,
`normalize_name`, etc. from the earlier ones (`step01_extract_kpi_from_jsonl`,
`step02_extract_triplet_from_jsonl`, `step03_fix_invalid_triplets`, `step04_build_issuer_registry`). Changing a
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
labels. Key invariants the `src/` validation relies on (see docs/TEMPORAL_KG_DESIGN.md
for the T1/T2/T3 tier model behind them):
- **At extraction (step02/step03) every node carries** `valid_from`, `valid_to`,
  `is_current`; every edge carries `temporal_metadata` (`valid_from`, `valid_to`,
  `recorded_at`). In the **resolved** graph (step05+) time lives on **edges and T2/T3
  event nodes** (P2); T1 entity nodes are timeless, their history is `temporal_versions`.
- Dates are canonical ISO `YYYY[-MM[-DD]]` (step03 phase 1.5); a version chain with an
  open version has exactly one `is_current=true` (P4, enforced in step05).
- Each node has `identity_keys` used to compute a stable entity id (for dedup/versioning).
  **T1 identity is timeless (P1):** never put time fields (`valid_from`, `date`, `year`,
  `validity_period`, …) in a T1 class's `identity_keys` — step00 lints this. Observation
  classes (`KPIObservation`, `Emission`, `Waste`) legitimately carry time in their keys and
  are versioned per-observation; entities are versioned only when properties change
  (linked via `supersedes` edges).
- An edge label may appear with **multiple legal (source_class, target_class) pairs**;
  the validator treats any matching pair as valid and auto-swaps reversed directions.
- News-derived observation classes (`KPIObservation`, `Controversy`, `Penalty`,
  `MediaReport`) carry a required `date_uncertain` bool: `false` when the article states
  an explicit date/period for that fact, `true` when step02's news prompt had to fall
  back to the article's publish date as a proxy (never silently assume the publish year).
  step07 surfaces this as a caveat on any dossier whose evidence includes an uncertain date.
See `docs/SCHEMA_EXPLAINED.md` for the rationale.

## Common commands

```bash
pip install -r requirements.txt

# 0. Land the data snapshot this commit was built against (instead of re-running the pipeline)
python src/data_sync.py status                              # what is pinned vs what is local
python src/data_sync.py pull                                # teammate: fetch the revision in data_version.json
python src/data_sync.py push                                # after a rebuild: upload + re-pin (needs org `write`)
                                                            #   then: git add data_version.json && git commit

# A. Annual report → labeled ESG sentences
python -m data_processing.prepare_sentences \
    --input  "data/raw/annual_reports_sample/AAA_Baocaothuongnien_2025.pdf" \
    --output "data/interim/sentences/aaa_sentences.jsonl"
python -m data_processing.extract_esg            # labeled JSONL → esg_extracted records

# B. News evidence for one company (conduct side)
python -m esg_news_crawler.run --ticker AAA --limit 1
python -m data_processing.preprocess_news                             # P1: → data/interim/news_preprocessed/ (date-normalize + drop boilerplate)

# C. Labeled JSONL → temporal KG (run from repo root, in order)
python src/step00_graph_quality_report.py --label baseline                   # Q1–Q8 snapshot (before/after any change; offline)
python src/step01_extract_kpi_from_jsonl.py     -i <labeled.jsonl>            # → kpi_output/
python src/step02_extract_triplet_from_jsonl.py -i <report_labeled.jsonl>    # → graph_output/graphs/ (claim side; --source report default)
python src/step02_extract_triplet_from_jsonl.py -i <news_preprocessed.jsonl> --source news   # conduct side (stamps source_type=news)
python src/step03_fix_invalid_triplets.py                                    # → graph_output/validated/
python src/step03_fix_invalid_triplets.py --renormalize                      #   P4-only pass on the existing validated file (no LLM)
python src/step03b_anchor_kpi_facilities.py --dry-run                        # P3 offline anchor patch preview (then run without --dry-run)
python src/step04_build_issuer_registry.py                                   # → config/issuer_registry.json (run-once; then hand-confirm needs_review)
python src/step05_resolve_entities.py                                        # → graph_output/resolved/ (step 4: entity resolution)
python src/step05b_stamp_provenance.py --dry-run                             # provenance patch preview (then run without --dry-run; offline, no LLM)
python src/step06_load_graph_to_neo4j.py --dry-run                           # step 5: preview planned counts, no DB
docker compose up -d                                                 # start Neo4j on :8687 (then run neo4j/init.cypher once — see docs)
python src/step06_load_graph_to_neo4j.py --clear                            # → Neo4j (wipe + load; needs the instance running)
python src/step07_crosscheck_claims_vs_conduct.py --dry-run                 # step 6: preview claim↔conduct pairs (runs LLM, writes nothing)
python src/step07_crosscheck_claims_vs_conduct.py                           # → graph_output/crosscheck/ (advisory dossiers + linking edges)
python src/step08_sync_crosscheck_to_neo4j.py                              # step 6b: push dossiers into Neo4j advisory layer (no LLM)
python src/step09_report_claim_ledger.py                                   # step 7: render the AAA claim ledger FROM Neo4j (no LLM)
python src/step09_report_claim_ledger.py --review-queue --markdown         #   contradiction-no-verification queue + Markdown file
python src/step10_evaluate.py                                              # step 8 / P6: full Vietnamese evaluation report
python src/step10_evaluate.py --ablation --no-llm                          #   free arms only (coverage/case studies/ablation are offline)

# Demo UI (web front-end for step 7; reads the same Neo4j advisory layer, no LLM — see docs/DEMO_UI.md)
streamlit run app.py                                                       # company-code claim-ledger explorer at http://localhost:8501

# Useful src/ flags: --doc <substr>, --limit-docs N, --all (scope);
#   --all-pages (don't restrict to ESG pages); --dry-run (fix/resolve/load steps: offline only, no LLM/DB/writes);
#   quality (step00): --label <name>, --skip-slow (skip the BFS-heavy Q7(c)/(d)), --max-hops;
#   fix (step03): --renormalize (P4 pass only); anchor patch (step03b): --max-per-facility, --dry-run;
#   provenance patch (step05b): --graphs-dir, --news-globs, --stats-out, --dry-run;
#   resolve: --no-llm (Stages A+B.1 only), --similarity-threshold, --max-llm-pairs (budget the LLM adjudication);
#   load: --clear (wipe first), --no-versions (canonical only), --database, --strict (env: NEO4J_URI/USER/PASSWORD);
#   crosscheck: LLM adjudication is mandatory (no --no-llm); --max-llm-pairs, --provider-order gemini,openai, --to-neo4j;
#   sync (step08_sync_crosscheck_to_neo4j.py): --clear-advisory, --dry-run;
#   ledger (step09_report_claim_ledger.py, Neo4j-only): --review-queue, --assessment, --claim-id, --limit, --markdown;
#   evaluate (step10_evaluate.py): --coverage, --case-studies, --ablation, --no-llm (only the 30-case arm costs money)
```

No pytest harness or linter is configured. The one automated check is a plain assert
script covering the P3/P4 Phase-0 temporal logic and the step05b provenance matching —
run it from the repo root after touching step03/step03b/step05/step05b:

```bash
python test/test_temporal_invariants.py    # offline, no LLM/DB; asserts date canonicalization,
                                           # temporal invariants, source_id parsing, DSU consolidate,
                                           # provenance tier matching + node-order invariant
```

The rest of `test/` and `notebooks/` are Jupyter notebooks for manual validation
(e.g. `test/test_pdf_extraction.ipynb`).

## Documentation map

`docs/SYSTEM_DESIGN.md` is the **final end-to-end system design** — read it first for the big
picture: the symmetric greenwashing setup (reports = claims, independent news = conduct, both
in one temporal KG), the new news→graph branch and claim↔conduct cross-check stage, and the
deliberate "evidence + advisory LLM assessment, no greenwashing score/verdict" framing (no
ground-truth labels exist). The rest of `docs/` holds per-stage design notes worth reading
before modifying a stage:
`SCHEMA_EXPLAINED.md`, `TEMPORAL_KG_DESIGN.md` (the 8 temporal-KG design principles
P1–P8 + the Q1–Q8 quality attributes measured by step00 — read before touching the
schema, step02 prompts, step03, or step05), `SSRL_REASONING_LAYER.md` (the proposed
path-reasoning layer, steps 11–13 — not yet built; P5/P6/P8 constraints for it live in
its §4.6/§4.7/§5.3/§7.2), `KPI_EXTRACTION_FROM_JSONL.md`, `TRIPLET_EXTRACTION_FROM_JSONL.md`,
`TRIPLET_VALIDATION.md`, `PROVENANCE_PATCH.md` (step 5b — offline source_doc/source_page
stamping of the resolved graph so the UI/ledger can cite report page + article title),
`ENTITY_RESOLUTION.md` (step 4 — why it's a redesign, not a port),
`GRAPH_LOAD_NEO4J.md` (step 5 — Neo4j load; also a redesign),
`CLAIM_CONDUCT_CROSSCHECK.md` (step 6 — claim↔conduct cross-check, the analytical core),
`CLAIM_LEDGER.md` (step 6b sync + step 7 — dossier → Neo4j advisory layer, then the Neo4j-only claim ledger + analyst Cypher),
`DEMO_UI.md` (the Streamlit company-code claim-ledger explorer, `app.py` — how to run the demo),
`EVALUATION.md` (step 8 / P6 — why evaluation measures the linking machinery, not
greenwashing accuracy; the four methods and their costs),
`ENTITY_RESOLUTION_IMPROVEMENT.md` (Vietnamese — proposal to use graph structural
signatures to auto-resolve step-4's lexically ambiguous `needs_review` cases),
`KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`, `VIETNAM_IMPROVEMENT_PLAN.md`,
`NEWS_CRAWLER_OPTIMIZATION.md` (Vietnamese — architecture of the standalone, FPT-specific
`crawl_data/crawler_news.py`, not the documented `esg_news_crawler/` pipeline). The root
`ENTITY_RESOLUTION_PLAN.md` is the step-4 engineering checklist. `README.md` (root),
`esg_news_crawler/README.md`, and `kpi_build/README.md` cover their respective subsystems.
