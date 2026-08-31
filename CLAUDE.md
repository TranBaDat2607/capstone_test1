# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A **Graph-RAG pipeline for detecting greenwashing in Vietnamese listed companies**
(Construction / Building Materials / Real Estate sector). It ingests ESG statements
from annual reports and news, classifies them, extracts numeric KPIs, and builds a
**temporal ESG knowledge graph** so a company's *reported* ESG claims can be
cross-checked against its *real-world* conduct.

## Read-only trees — `EmeraldMind/` and `overall_pipeline/`

`EmeraldMind/` is an external reference implementation. **Never edit it and never
treat its files as part of this codebase** (don't list, refactor, or count them as
project files). You may read it to understand intent: `src/esg_kg` (originally
`src/`, since migrated and deleted — see `docs/PROJECT_HISTORY.md` §1) ports
`EmeraldMind/src/EmeraldKG/` steps 1→2→3 closely, then 4 (entity resolution) as a
**deliberate redesign** — all adapted to take **labeled JSONL** input (not PDFs) and a
**single `GEMINI_API_KEY`** (not a multi-key pool). When porting more EmeraldKG stages,
keep prompts/validation/output conventions identical so stages stay drop-in compatible;
when a stage is redesigned instead of ported (like step 4), document why in `docs/`.
It is **excluded from git** (`.gitignore` → `EmeraldMind/`) — it has its own `.git`
repo and secrets, so it is never committed or pushed with this project.

`overall_pipeline/` is a **separate React 19 / Vite 8 / Tailwind v4 app** ("figma-make-app")
that renders the pipeline-architecture figures. It has its own `CLAUDE.md` (a one-line
`@AGENTS.md` include), its own `node_modules/`, and no connection whatsoever to the Python
pipeline. Same rule as above: **don't list, lint, refactor or count its files as part of this
codebase**, and don't start its dev server unless asked. If a task really is about those
figures, work inside it and follow its own `AGENTS.md` while you are there.

## Environment & conventions
- **Windows / PowerShell** host. `.rar`/`.7z` extraction in `crawl_data/extract_archives.py`
  shells out to external **UnRAR.exe / 7z.exe** (install WinRAR + 7-Zip separately).
- **Generated data is distributed via Hugging Face, not Git** (`src/esg_kg/core/datasync.py`,
  not a pipeline step): `data/`, `graph_output/`, `kpi_output/` are git-ignored (~342 MB) and ship
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
  snapshot. `neo4j_data/` is never synced — rebuild it with `neo4j_load`. Both `push` and `pull` are
  scoped with `ALLOW_PATTERNS` to exactly those three folders: `local_dir` is the CODE repo, so
  an unscoped pull writes the dataset's own root files over tracked ones — that is how the Hub's
  `.gitattributes` came to be committed here. That Hugging Face boilerplate was removed in
  the public-release cleanup, so new binaries are ordinary blobs; the 13 PNGs committed under
  `capstone_report/images/` and `notebooks/eda/output/` while it was in force are still LFS
  objects, and re-staging one without git-lfs installed would commit the pointer stub as the
  image. Guarded by `test/test_data_sync_scope.py`.
- **Secrets:** copy `.env.example` -> `.env` (git-ignored — never commit it). Every `esg_kg`
  LLM stage loads it from the repo root regardless of cwd. What lives there: `GEMINI_API_KEY`
  plus `GEMINI_MODEL` (one env var drives every Gemini stage through `core/llm.py`'s
  `DEFAULT_MODEL`; default `gemini-2.5-flash-lite`), `GEMINI_MAX_RETRIES` /
  `GEMINI_RETRY_BACKOFF_SECONDS` (see the retry bullet below), `DEEPSEEK_API_KEY` /
  `DEEPSEEK_MODEL`, `LLM_PROVIDER`, `HF_TOKEN`, and `NEO4J_URI` / `NEO4J_USER` /
  `NEO4J_PASSWORD`, plus `OPENAI_API_KEY` / `OPENAI_MODEL`. The OpenAI provider was removed
  outright on 2026-08-04 and then **re-added on 2026-08-06, opt-in and scoped to
  `claims_vs_conduct` only** (`core/llm.py:349` `_OpenAIProvider`, registered in
  `_PROVIDER_CLASSES`), selected per run with `--provider-order openai`. It is REST via
  `requests`; the `openai` SDK is still not a dependency. Leave `OPENAI_API_KEY` unset and
  nothing uses it (`docs/PROJECT_HISTORY.md` §2).
- **`.mcp.json` is project-scoped MCP config**, currently one Overleaf server
  (`@mjyoo2/overleaf-mcp`) taking `OVERLEAF_PROJECT_ID` / `OVERLEAF_GIT_TOKEN` from the
  environment — the capstone report is drafted on Overleaf and mirrored into
  `capstone_report/`, which also builds locally via its own `build.ps1` (MiKTeX;
  pdflatex -> bibtex -> pdflatex -> pdflatex).
- **Layout principle (enforced):** code lives only in the package folders
  (`crawl_data/`, `data_processing/`, `esg_news_crawler/`, `src/`,
  `kpi_build/`, `gri/`, plus the UI pair `api/` + `frontend/`). Everything else is `config/`
  (see the next bullet), `neo4j/` (`init.cypher` constraints + `crosscheck_queries.cypher`
  analyst queries), or `data/` (`raw/` -> `interim/` -> `labeled/` -> `outputs/`).
  **No data files inside code packages** — with two named exceptions, both run-once
  provenance builders that keep their sources beside them so a claim can be traced to a
  page: `kpi_build/` and `gri/` (the latter carries 42 GRI Standards PDFs, ~45 MB, in Git).
  Non-code trees that are none of the above and must not be treated as project code:
  `capstone_report/` (LaTeX + figures), `overall_pipeline/` (see above), `notebooks/eda/`
  (standalone offline analysis scripts writing to `notebooks/eda/output/`), `diagram/`, and
  the root-level annotation spreadsheets.
- **`config/` is wider than "schema + dictionaries" now.** Besides `schema.json`,
  `kpi_type_aliases.json`, `standards_registry.json`, `standard_crosswalk.json`,
  `gri_catalog.json` and `issuer_registry.json` it holds: `degenerate_relations.json` (read by
  `metric/reasoning_readiness.py` and `report/quality.py`), `evaluation/ablation_cases.json`,
  and `subsidiaries/<TICKER>.json` — 113 tracked per-ticker subsidiary registries extracted
  from annual-report pages by Gemini vision, most still `reviewed: false`. Those subsidiary
  files are referenced by `docs/SYSTEM_DESIGN.md`, `docs/LABELING_STRATEGY.md` and
  `docs/ANNOTATION_GUIDELINE.md` but have **no Python consumer on `main`** — don't assume a
  stage reads them.
- **Two execution styles — do not mix them:**
  - `data_processing/` and `esg_news_crawler/` are **packages**, run as modules:
    `python -m data_processing.extract_esg`.
  - `src/esg_kg/` is a real package, run from the repo root via its dispatcher —
    `python src/run.py quality --label baseline` (equivalently
    `python -m esg_kg.report.quality` from inside `src/`). `python src/run.py --list` is the live
    stage table — **16/16 ready** today: the 15 stages migrated out of the old
    tree, plus `export_kgc`, written new afterwards. It reads that table from the
    import system rather than from a hand-kept list. **The old flat layout — one
    `src/stepNN_*.py` script per stage — is gone, deleted 2026-07-29, refactor
    complete** (`src/esg_kg/DESIGN.md` §7, `src/PIPELINE.md` §7). `esg_kg` is the
    only pipeline tree now.
- **`src/` means the `esg_kg` package tree, and only that** (renamed from
  `src_module/` on 2026-07-30, once the refactor was closed out and the name was free
  again). The history prose below — and most of `docs/` — was written while `src/` was
  the OLD flat `stepNN_*.py` tree, so a sentence there saying `src/` was "deleted", was
  "the oracle", or held `step07_crosscheck_claims_vs_conduct.py` is talking about that
  old layout, **not** about today's `src/`. Paths of the form `src/stepNN_*.py` are
  historical labels — no such file exists now; the live commands are all
  `python src/run.py <stage>`.
- **Sentence-level traceability** (`source_pdf`, `page`, `sentence_index`) is preserved
  through every stage so each graph node traces back to its source — keep it intact.
- **Torch is intentionally absent from `requirements.txt`.** The ViDeBERTa ESG classifier
  runs on GPU via `notebooks/kaggle_esg_classify.ipynb`; install torch locally only to
  test `data_processing/esg_classifier.py` on CPU.
- **Other deps are deliberately unlisted and imported lazily** — each degrades gracefully
  so a bare clone still runs: `huggingface_hub` (`datasync.py`), `rapidfuzz` (the
  KPI-canonicalization stage's fuzzy tier; disabled with a warning if absent).
- **Gemini is the default paid LLM provider; DeepSeek V4 Flash and OpenAI are swappable
  alternatives for the stages built against the provider-agnostic `_Provider` contract —
  there is no automatic fallback cascade between them.** `align_claims` and
  `extract_triples` pick a provider through `core/llm.py`'s `build_llm_provider()` factory
  (`--provider gemini|deepseek`, or the `LLM_PROVIDER` env var); `claims_vs_conduct`'s
  `Adjudicator` keeps its own registry (`--provider-order` — `deepseek` alone, or a comma list
  if a cascade is ever wanted) because that class is stage logic, not kernel.
  `extract`/`fix_triples`/`entities` are still **Gemini-only**: they call
  `build_gemini_client()` directly and use Gemini-specific explicit context caching
  (`GeminiContextCache`), which DeepSeek has no equivalent for — so on a DeepSeek run
  `extract_triples` skips caching and always sends the full per-page prompt, making
  `--no-context-cache` a no-op there. Unset `DEEPSEEK_API_KEY` and every stage keeps using
  Gemini. **OpenAI was removed outright on 2026-08-04 and re-added on 2026-08-06 as an
  opt-in for `claims_vs_conduct` ONLY** (`--provider-order openai`, `OPENAI_API_KEY` in
  `.env`): a swappable alternative like DeepSeek, deliberately NOT the forced fallback of the
  2026-07-27..08-04 episode, when Gemini was billing-blocked. No other stage has an OpenAI
  path. Read `docs/PROJECT_HISTORY.md` §2 before widening it. Entity resolution is
  still normally run with `--no-llm` (Stages A + B.1 only — no embedding blocking, no
  adjudication) because Stage B/C is dormant, not because of a billing block; don't assume
  it's safe to flip that default without checking. Real-LLM tests live in
  `test/test_esg_kg_integration_llm.py` / `test/test_esg_kg_system_llm.py`, gated behind
  `RUN_LLM_INTEGRATION_TESTS=1` / `RUN_LLM_SYSTEM_TEST=1` — they cost money and are
  deliberately NOT part of the free/offline suite.
- **Transient Gemini 5xx is retried; 4xx never is.** `_GeminiProvider.call()` retries a
  `google.genai.errors.ServerError` (the "model overloaded" 503 `gemini-2.5-flash-lite`
  returns under load) with exponential backoff — `GEMINI_MAX_RETRIES` (default 5) and
  `GEMINI_RETRY_BACKOFF_SECONDS` (default 2.0) in `.env`, overridable per constructor so a
  test can drive the schedule without a real clock — then re-raises, so it mitigates an outage
  rather than hiding one. A `ClientError` (4xx: bad request, auth, not found) is deliberately
  never retried: it isn't transient, and retrying burns quota on an error retrying can't fix.
  This exists because `Adjudicator` (step07) counts any exception as a failure and disables a
  provider after 3 failures with 0 successes — a short burst of 503s used to silently turn
  Gemini off for the rest of a run. Scoped to Gemini only; DeepSeek's SDK-less REST path was
  not reported flaky.
- **Two different LLM caches, deliberately orthogonal — don't merge them.**
  `core/llm_cache.py`'s `ContentCache` (issue #9) is content-addressed (sha256 key, JSON
  persisted, dirty-gated save, corrupt-file-safe load) and skips an **identical repeat
  request**; `RepairCache` (`build_validated`) and `AdjudicationCache` (`build_resolved`) sit
  on top of it. `core/llm.py`'s `GeminiContextCache` (issue #11) is provider-side and
  discounts the large **static prefix** (`schema.json`, `kpi_definitions_construction.json`)
  shared across otherwise-different calls. What gets cached: a paid, non-deterministic result
  (LLM repair/adjudication, keyed by content not position) yes; a merely
  billed-but-deterministic one (embeddings) no.

## Working rule: Test-Driven Development (applies to ALL code from now on)

**Write the test first. Run it. See it fail. Then write the code.** No production code
lands without a failing test that demanded it. This is not optional and not limited to the
refactor — it is how code gets written in this repo from now on.

The cycle, per unit of work:
1. **Red** — write the smallest test that expresses the next behaviour, run it, confirm it
   fails *for the expected reason* (a test that passes before the code exists is testing nothing).
2. **Green** — the minimum code to pass. No extra features "while I'm here".
3. **Refactor** — clean up with the test green, re-run.

Conventions (match `test/test_temporal_invariants.py`, the existing precedent):
- **Plain `assert` scripts, no pytest** — the repo has no pytest/linter harness. A test is
  a runnable file under `test/` printing pass/fail and exiting non-zero on failure.
- **Tests must be offline** — no LLM, no Neo4j, no network. They run on real artifacts
  already on disk (`config/schema.json`, `graph_output/…`). This keeps them free and
  repeatable; **never verify by re-running a paid stage** (see also `--dry-run`/`--no-llm`).
- Run from the repo root: `python test/<name>.py`.
- Touching step03/03b/03c/05/05b/05c/08 still means re-running `test_temporal_invariants.py`.

## History that must not be re-litigated

Two files hold the record — `docs/PROJECT_HISTORY.md` (the `src/` -> `esg_kg` refactor and its
cross-cutting lessons, the LLM-provider timeline, the stages removed outright) and
`docs/EVALUATION_BASELINE.md` (the frozen measurement snapshot, the blind annotation, the
Graph-RAG vs RAG arms). Read the relevant one before "fixing" something that looks stale.
The five points that have actually been re-derived wrongly:

- **The refactor is done.** 16/16 stages live in `src/esg_kg/`; the old flat tree was deleted
  2026-07-29. `stepNN_` labels survive only as `pipeline.py`'s `old_step` field and as what
  `run.py 05b` resolves by — **no `src/stepNN_*.py` file exists**, and `python src/run.py
  --list` is the live source of truth.
- **`step10` (P6 evaluation), `step04b` (standards-registry reseed) and `step07b` (softmax
  evidence-balance scores) were removed from the project, not ported.** There is no
  replacement command for any of them.
- **Deterministic `claim_id` HAS landed** (`a3f4497`; `assign_deterministic_claim_ids` in
  `graph/extract_triples.py`, wired into the per-page loop; guarded by
  `test/test_claim_id_deterministic.py`, 13 groups including real-corpus uniqueness). The
  planned full re-extraction is therefore **no longer gated on GitHub issue #2** — what
  remains is the scheduled cost of changed node order and invalidated paid dossiers, which
  DESIGN.md §5.4 already accepts. Any prose still calling issue #2 pending (including
  `docs/proposals/AGENT_AB_EVALUATION.md`) is out of date.
- **The evaluation snapshot wins over a fresher run on disk** — 10,634 nodes / 14,744 edges,
  464 dossiers across exactly five issuers (AAA ACC ACG ADP AGG), 2026-08-08T04:24:57Z. HAR is
  not a sixth issuer, and Table 4.3's `openai` provider caption is a correct historical record,
  not a stale reference. Never silently quote newer numbers into a document built on the old
  ones. Reasons and the full figure set: `docs/EVALUATION_BASELINE.md`. **Superseded on the
  graph-size figures only** by the 2026-08-14 issue #20 (P5) fix — `anchor_kpi`'s stale glob
  meant it had been silently producing zero output since the 2026-08-02 corpus swap; fixed,
  and `build_validated`/`build_resolved` re-run offline. Resolved graph is now **10,624 nodes
  / 15,130 edges**. The 464-dossier / 718-alignment figures are unchanged and verified
  unaffected (see `docs/EVALUATION_BASELINE.md`'s 2026-08-14 addendum for why) — do not
  re-derive them from a fresher run either.
- **`GRAPH_IMPROVEMENT_PLAN.md` no longer exists** (deleted from `main` in `66d1704`), yet
  `export_kgc` and five test files still cite its section labels (A1, A2/A3, B1, B4, C1,
  C2/B2) as their spec. Recover it with `git show 66d1704^:GRAPH_IMPROVEMENT_PLAN.md` instead
  of treating those references as typos — `docs/PROJECT_HISTORY.md` §4 maps each label to what
  it became.

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
Both feed the same `esg_kg` graph-construction path and land in one temporal KG (see `docs/SYSTEM_DESIGN.md`).

**Full-sector labeling landed 2026-08-02 — check the full-corpus file, not a per-company one.**
The canonical, current classifier output is the whole sector, not just AAA:
`data/labeled/classified/all_sentences_classified.jsonl` (197 companies, 873,756 sentences,
303,723 `esg=true`) for reports, and `data/labeled/news_labeled/all_news_sentences_classified.jsonl`
(115 tickers, 174,256 sentences, 77,229 `esg=true`) for news — same for their `extract_esg`
outputs under `data/outputs/esg_extracted/classified/` and `.../news_labeled/`. An earlier
AAA-only pilot batch (`data/labeled/annual_labeled/`, `data/outputs/esg_extracted/annual_labeled/`,
plus `aaa_news_classified*`/`aaa_all_sentences*`/`aaa_sentences*`) predated the full run and
silently duplicated AAA under a different filename convention (`AAA_2013.pdf` vs
`AAA_Baocaothuongnien_2012.pdf` for identical content) — inflating AAA's share of
`esg_all_records.jsonl` to ~2×. Removed from the HF dataset repo 2026-08-02 (commit `a7e73bd1`,
pinned in `data_version.json`); if those paths still show up on disk from an older pull, they're
stale leftovers to ignore/delete, not a second data source. **Before concluding "only AAA is
labeled/extracted" or "the sector corpus is missing," check `data/labeled/classified/` and
`data/outputs/esg_extracted/classified/` first** — that mistake has already happened once.

`crawl_data/crawler_news.py` is a separate, FPT-specific standalone news crawler (not a
`-m` package, not wired into pipeline B above) — treat it as a legacy/experimental tool, not
the documented news-ingestion path. See `docs/NEWS_CRAWLER_OPTIMIZATION.md` for its design.

**C. Labeled JSONL → temporal knowledge graph (`src/esg_kg`)**

Run via `python src/run.py <stage> [args]` from the repo root (`--list` shows every
stage). The `stepNN_` labels below are the historical run-order names each stage carries as
its `old_step` field in `pipeline.py` — `src/`, the tree that filename prefix used to name a
real file in, was deleted 2026-07-29 (refactor complete, DESIGN.md §7); they are kept only
because they encode run order and are still what `run.py <old_id>` resolves by (e.g.
`run.py 05b`).
```
quality        (step00) → graph_output/quality/quality_report_<label>.{json,md}
   (offline diagnostics, NO LLM/DB: measures the Q1–Q8 quality attributes of the resolved
    graph — consistency incl. P4 temporal invariants + P1 identity lint, conciseness,
    conduct completeness, Q7 traversability (median degree / leaves / masked-answerable /
    hub-free structural claim→conduct / T2 anchoring). Run BEFORE and AFTER any
    schema/pipeline change with --label; see docs/TEMPORAL_KG_DESIGN.md §4)
extract         (step01) → kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json
   (per page: Gemini 2.5 Flash w/ structured output → typed KPIObservation records,
    only pages with ≥1 esg=true sentence are sent; uses kpi_definitions_construction.json.
    Gemini-only, no provider flag — the 2026-07-29..2026-08-04 --provider openai path
    was removed outright once Gemini billing was unblocked)
extract_triples  (step02) → graph_output/graphs/<pdf_stem>/page{N}.json  (+ _bugged.json, _malformed.txt)
   (per page: page text + page KPIs + config/schema.json → temporal triples → node/edge graph.
    --source report (default) = claim-side prompt; --source news = conduct-side prompt (Controversy/
    MediaReport/Penalty/observed KPIObservation); every node/edge stamped source_type=report|news.
    Gemini by default (build_gemini_client + GeminiContextCache, same as extract above);
    --provider deepseek added 2026-08-06 as a swappable alternative — skips context
    caching, always sends the full per-page prompt, via core/llm.py's build_llm_provider())
fix_triples      (step03) → graph_output/validated/all_validated_triples.json (+ unfixable_triples.json)
   (Phase 1 offline: swap reversed edge directions + schema-validate;
    Phase 1.5 offline (P4): canonicalize dates to ISO YYYY[-MM[-DD]], warn valid_from>valid_to,
    default missing date_uncertain on news T2 nodes; --renormalize applies only this phase to
    the existing aggregated file (no LLM, keeps prior repairs);
    Phase 2 LLM: batch-repair invalid triples, Gemini-only, no provider flag;
    Phase 3: aggregate)
anchor_kpi       (step03b) → appends to all_validated_triples.json (+ anchor_patch_stats.json)
   (P3 offline patch, NO LLM: gazetteer of Facility names already in the graph matched against
    each KPI's source sentence (source_id → labeled JSONL) → emits KPIObservation
    --observedAtFacility--> Facility edges, tagged anchor_method=offline_gazetteer.
    Run after fix_triples, before entities. New extractions get anchors from the extract_triples
    prompt instead)
canonicalize     (step03c) → appends/patches all_validated_triples.json (+ kpi_canonical_stats.json)
   (offline, NO LLM: assigns each KPIObservation a canonical `kpi_id` from the 35-indicator
    vocabulary via config/kpi_type_aliases.json + rapidfuzz on official names, writing a NEW
    property (NEVER rewrites `kpi_type`, which is in identity_keys — so node order is preserved
    and paid dossiers survive). Also unit_normalized/value_normalized/period and a
    Goal.target_date regex backfill (future years only). Feeds the indicator axis, docs/
    STANDARD_INDICATOR_AXIS.md §5.2. Run after anchor_kpi, before issuer. Precision over recall:
    financial KPIs in VND are rejected, not force-mapped)
build_validated  BLOCK: fix_triples -> anchor_kpi -> canonicalize in one pass, writing
    all_validated_triples.json ONCE (DESIGN.md §5.7) — the normal way to run all three
issuer           (step04) → config/issuer_registry.json                       (run-once bootstrap)
   (drafts the reporting company's name variants → aliases / exclusions / needs_review;
    re-running preserves human edits, --force rebuilds; a human confirms needs_review.
    Reads the ticker off KPI source_ids via REPORT_STEM_RE, which matches BOTH the legacy
    <TICKER>_Baocaothuongnien_<YEAR> stem and the current plain <TICKER>_<YEAR> one — it
    used to match only the former, so it detected just AAA out of a multi-company corpus.
    A ticker already curated in the file but NOT rebuilt this run is carried forward
    unchanged, never dropped — the file is tracked and hand-edited, so dropping one is a
    silent deletion of curated work)
config/standards_registry.json          — STATIC CONFIG, not a pipeline stage
   (the 5 reference documents behind the indicator vocabulary (TT96, QĐ2171, QCVN09, SSC-IFC,
    GRI) with their aliases/exclusions + `match_patterns`/`exclude_hints`. entities' standards
    anchor freezes GRI's ≥4 spellings and TT96 VN/EN onto one canonical node each (diagnosis C3).
    Hand-edited: add an alias, then re-run entities. NOTHING generates it — quality's
    `standards_registry_audit` reports uncovered mentions instead. The old from-scratch reseed
    tool, `step04b_build_standards_registry.py`, was removed outright with `src/` on 2026-07-29
    (DESIGN.md §4.2) — rebuilding from scratch now means hand-editing the JSON.)
entities         (step05) → graph_output/resolved/resolved_graph.json (+ _stats.json)
   (step 4: collapse duplicate entity nodes into canonical entities, keeping temporal history.
    Stage A deterministic identity_keys merge + FROZEN issuer anchor (issuer_registry.json) +
    FROZEN standards anchor (Stage A.3, standards_registry.json — Standard/Regulation mentions);
    Stage B VN-aware blocking (normalized signature + gemini-embedding-001 cosine);
    Stage C adjudication on ambiguous pairs (budgeted; gemini-2.5-flash). Gemini-only,
    no provider flag. Stage D consolidate. --no-llm skips B+C)
provenance       (step05b) → patches resolved_graph.json in place (+ provenance_patch_stats.json)
   (offline provenance patch, NO LLM: matches claim/evidence nodes (PROVENANCE_CLASSES, never
    T1 entities) back to the per-page graph_output/graphs/<doc>/page{N}.json files via a 4-tier
    precedence (parseable source_id → exact source_id index → recomputed stable_id → _pageNN_
    token) and stamps source_doc/source_page (+ article_title/url/domain for news docs from the
    news JSONL). NEVER reorders nodes (neo4j_load _node_key + dossier node_index are positional).
    Run after entities, before neo4j_load; re-run after any entities re-run. New extract_triples
    output self-stamps (provenance_method=extraction) and is skipped. See docs/PROVENANCE_PATCH.md)
indicators       (step05c) → patches resolved_graph.json in place (+ indicator_axis_stats.json)
   (offline, NO LLM: materializes the TT96/GRI indicator axis. APPENDS ~35 StandardIndicator
    nodes + edges: partOf (indicator→document), measuredUnder (KPIObservation/Emission→indicator,
    read from canonicalize's kpi_id — never guessed here), equivalentTo (TT96→GRI, from
    config/standard_crosswalk.json, confirmed rows only), and a keyword tier of alignsWithIndicator
    (Claim/Goal/Initiative→indicator; longest matching phrase wins). Penalty amount==0 = self-reported
    "fined 0 times" → flagged self_reported_zero, NO conduct edge. APPEND-ONLY (asserts the
    existing node/edge prefix is untouched — dossiers stay valid). Also RESTAMPS
    StandardIndicator.pillar from the file entitled to say — kpi_definitions_construction.json
    for the VN vocabulary, config/gri_catalog.json (--gri-catalog) for GRI — and never invents
    one: an id neither covers keeps the pillar it had. The Evidence View reads that property
    directly for a claim's E/S/G column, so a guess there is visible to the reader. Run after
    provenance, before neo4j_load. See docs/STANDARD_INDICATOR_AXIS.md)
build_resolved   BLOCK: entities -> provenance -> indicators in one pass, writing
    resolved_graph.json ONCE (DESIGN.md §5.7) — the normal way to run all three
align_claims     (step05d) → patches resolved_graph.json in place (+ indicator_align_llm_stats.json)
   (OPTIONAL, LLM, budgeted: alignsWithIndicator for the Claim/Goal/Initiative the keyword tier
    left unresolved. Topic classification only (alignment_method=llm), NOT a supports/contradicts
    judgement. Pipeline is complete without it. Run after build_resolved; --max-llm-pairs, --dry-run)
export_kgc       (step11, partial) → graph_output/export_kgc/ (+ export_kgc_stats.json)
   (plan item B4 — the plan file itself is deleted, see docs/PROJECT_HISTORY.md §4.
    Offline, NO LLM: reads resolved_graph.json READ-ONLY and
    writes a wholly SEPARATE derived artifact for an SSRL/RL export view — never patches
    resolved_graph.json or Neo4j (P6 boundary in docs/TEMPORAL_KG_DESIGN.md). Every
    Organization cluster matching config/issuer_registry.json (reuses esg_kg/metric/hub.py,
    the same multi-issuer machinery quality.py's R5/Q7(d) use) whose summed degree exceeds
    --max-bucket-degree (default 500) is decomposed: its edges are grouped into synthetic
    HubBucket nodes keyed by (year, predicate), cutting the hub's own degree to one edge per
    bucket. Verified on the real AAA graph: max degree 9,511 → 542 (357 buckets; the single
    largest bucket, 2022×reportsKPI-class, still exceeds 500 — v1 only buckets by
    (year, predicate), reported honestly via threshold_met rather than escalated to a third
    key). HubBucket is NOT added to config/schema.json — it is a dataset-construction
    artifact, not a T1/T2/T3 entity. Run after build_resolved; --max-bucket-degree, --dry-run)
neo4j_load       (step06) → Neo4j (bolt://localhost:8687, db `neo4j`)            (step 5)
   (load the resolved {nodes,edges} graph as a property graph — NO LLM. Nodes keyed by
    array index (entities already resolved; not re-deduped); edges keep temporal_metadata and
    MERGE on a temporal _edge_key so multi-year edges stay distinct; temporal_versions become
    supersedes version-node chains for supersedes-legal classes, else a JSON property)
claims_vs_conduct (step07) → graph_output/crosscheck/<ticker>_claim_assessments.json   (step 6)
   (the analytical core: for each SustainabilityClaim, retrieve conduct-side candidates →
    LLM-adjudicate supports/contradicts/irrelevant → write verifiedBy / contradictedBy* edges.
    LLM adjudication is MANDATORY (no deterministic fallback) — `Adjudicator`'s own
    registry (--provider-order, default `gemini`) picks `_GeminiProvider`,
    `_DeepSeekProvider` or `_OpenAIProvider` (all core/llm.py); aborts up front if no
    provider is available.
    OpenAI was used here from 2026-07-27 (when the Gemini project was 403-blocked) until
    2026-08-04, when it was removed outright — then re-added 2026-08-06 as an OPT-IN for
    this stage only (`--provider-order openai`), not a forced fallback. DeepSeek V4 Flash (2026-08-06) is
    a different situation: a swappable alternative you opt into via
    `--provider-order deepseek`, not a forced fallback, needing `DEEPSEEK_API_KEY` in
    `.env`. Passing any other name still logs "Unknown adjudication provider — ignored".
    Self-verification guard drops company-own-domain "verify" edges.
    Emits advisory dossiers — NO greenwashing score/label. --dry-run / --to-neo4j)
neo4j_sync       (step08) → Neo4j advisory layer                                        (step 6b)
   (NO LLM — reuses the paid step-6 dossier. MERGEs assessment/caveats/signals onto claim nodes +
    llm_supports / llm_contradicts / llm_flagged_support evidence edges (incl. KPI contradictions
    the base schema can't express). Idempotent; --clear-advisory, --dry-run)
claim_ledger     (step09) → stdout + graph_output/crosscheck/<ticker>_claim_ledger.md   (step 7)
   (presentation only — NO LLM, reads ONLY Neo4j (run neo4j_sync first). Per-company claim
    ledger, signal-first (contradicted → supported → unverified), with the coverage caveat.
    --review-queue (contradiction + no verification), --assessment, --claim-id, --markdown)
```


`step07b` (offline softmax evidence-balance scoring) and `step10_evaluate.py` (the P6
evaluation report) are absent from the table above because both were removed from the project
outright, with no replacement command — see `docs/PROJECT_HISTORY.md` §3. The claim ledger
(`step09`) is the last stage in the pipeline now.

Stages share helpers through `esg_kg/core/`: `paths` (`REPO_ROOT`, `load_env`), `io_jsonl`
(`build_page_text`, `load_pages_from_jsonl`, ...), `llm` (`RateLimiter`, `_GeminiProvider`,
`_DeepSeekProvider`, `build_llm_provider`, `GeminiContextCache`, ...), `llm_cache`
(`ContentCache`), `schema` (`load_schema_sets`, ...), `naming` (`normalize_name`, ...),
`dates`, `identity`, `graph_patch`, `console` (`ensure_utf8_stdout`). A second shared
subpackage, `esg_kg/metric/`, holds graph *measurements* rather than helpers: `hub.py` (the
registry-driven multi-issuer hub SET — not the single max-degree node, which was correct only
while there was one issuer) and `reasoning_readiness.py` (R1 / R1' / R7 / R1_trainable, reading
`config/degenerate_relations.json`). `report/quality.py`'s Q7(d)/R5 and `export/export_kgc.py`
both consume `metric/`. No stage imports another stage's internals any more — that
sibling-importing shape belonged to the old `src/` scripts and was untied module by module
during the refactor (`docs/PROJECT_HISTORY.md` §1). Changing a `core/` helper's signature
affects every stage that imports it.

**D. KPI definition builder (`kpi_build/`, run-once provenance pipeline)**
Stages `01_…`→`06_…` download official Vietnamese ESG regulations (Circular 96/2020,
QĐ 2171, QCVN 09, SSC-IFC guide) and extract them **verbatim** into
`kpi_definitions_construction.json` (35 KPIs, each carrying a `source` block). This file
is the controlled KPI vocabulary consumed by stage C's KPI extractor. It rarely needs
rebuilding; treat it as generated data.

**D2. GRI catalog builder (`gri/`, run-once, same shape as `kpi_build/`)**
`gri/crawl_full_gri.py` downloads the 42 GRI Standards PDFs into
`gri/full_gri/Full set of GRI Standards - English/` and extracts them to
`gri/full_gri/json/`; `gri/build_gri_catalog.py` folds those into
**`config/gri_catalog.json`** — 136 GRI indicator codes with `title_vi`/`title_en`,
`pillar`, `units`, `tt96_equivalent`, `versions[]` and per-PDF `sha256`. step05c reads it
for GRI node names and pillars. **NOT a pipeline stage** (it reads no pipeline output, so
unlike the old step04b there is no cycle) — rebuild by hand after editing the crawl or the
crosswalk, then commit the regenerated JSON.
*Ownership rule worth knowing before touching it:* a GRI standard's JSON also re-lists
disclosures belonging to OTHER standards (the sector standards GRI 11–14 and the 2024/25
rewrites GRI 101–103 do this), so a disclosure is attributed to the standard whose
`standard_id` is its prefix — `standard_of()` — never to whichever file is read first.
Getting that wrong mis-attributed 80/136 entries and mangled 31 titles. Covered by
`test/test_gri_catalog_build.py`.

**E. ESG Evidence View UI (`api/` + `frontend/`) — the demo surface**
`api/main.py` is a **pure–standard-library `http.server`** (deliberately no FastAPI/Flask,
to dodge framework version mismatches) that serves the REST endpoints and the static
`frontend/` on `http://localhost:8000`. All data access lives in `api/evidence_service.py`,
which reads **live Neo4j** (the step06 base graph + the step08 advisory layer) — the mock
data is gone and **Neo4j is REQUIRED**; the query helpers raise `RuntimeError` if it is
unreachable. Only claims carrying an `alignsWithIndicator` edge are shown, so each card's
E/S/G pillar comes from the linked `StandardIndicator.pillar` rather than being guessed.
The frontend (`index.html` + `css/style.css` + `js/app.js`) is intentionally frozen:
per `docs/REAL_DATA_INTEGRATION_GUIDE.md`, data-source changes belong in
`evidence_service.py` only. See `docs/ESG_EVIDENCE_VIEW.md`.

## The graph schema (`config/schema.json`)

The single source of truth for the knowledge graph: ~28 node classes (Organization,
KPIObservation, Emission, SustainabilityClaim, Controversy, …) and ~50 directed edge
labels. Key invariants the `esg_kg` validation relies on (see docs/TEMPORAL_KG_DESIGN.md
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
- `mentionsFacility` (MediaReport -> Facility|Location) exists so a news article naming a
  facility or an incident location has a direct anchor even when no KPI or penalty is attached
  — the gap that kept Q7(e) (T2 conduct-node anchoring) low for the MediaReport class
  (`test/test_mentions_facility_edge.py`).
- `SustainabilityClaim.identity_keys` is exactly `["claim_id"]`, and `claim_id` is now
  **derived deterministically from the source sentence** at extraction time
  (`assign_deterministic_claim_ids`) rather than being free text the LLM invents. That is what
  makes a re-run reproduce the same claim nodes — and what stops `neo4j_sync`'s 100%
  `stable_id` claim resolution (there is no fallback tier) from silently re-partitioning
  already-paid dossiers.
See `docs/SCHEMA_EXPLAINED.md` for the rationale.

## The evaluation baseline — FROZEN

`docs/EVALUATION_BASELINE.md` is the authority. It is a **frozen snapshot**
(2026-08-08T04:24:57Z) shared by `capstone_report/main.tex` Chapter 4 and
`evaluation_final_focused.docx`, which agree exactly:

```
resolved graph          10,634 nodes / 14,744 edges
validated triples       14,500 kept / 807 unfixable
cross-check dossiers    464 claims across exactly 5 issuers: AAA ACC ACG ADP AGG
                        448 unverified (96.55%) / 13 supported / 3 contradicted
indicator alignment     718 / 1,421 claim-like nodes (50.53%)
```

**2026-08-14: the resolved-graph line above is superseded** by the issue #20 (P5) fix to
`anchor_kpi`'s stale glob — see `docs/EVALUATION_BASELINE.md`'s dated addendum for the
new figures (10,624 / 15,130) and why every other line in this block was verified
unaffected and left as-is.

**Never "correct" these against a fresher run on disk** — if a stage's output has moved past
the snapshot, the snapshot still wins for reporting purposes; re-pin or re-run deliberately.
Read that file in full before quoting any evaluation figure: it covers why HAR is not a sixth
issuer, why Table 4.3's `openai` caption is correct, what "before the contamination fix"
means, how the blind annotation by two external domain experts must be described (and why it
is *not* the CEO/HRD/Auditor rubric panel), which spreadsheet joins are valid, and the ~47x
candidate-pool asymmetry that confounds the Graph-RAG vs RAG coverage column.

## Common commands

```bash
pip install -r requirements.txt

# 0. Land the data snapshot this commit was built against (instead of re-running the pipeline)
python src/esg_kg/core/datasync.py status            # what is pinned vs what is local
python src/esg_kg/core/datasync.py pull               # teammate: fetch the revision in data_version.json
python src/esg_kg/core/datasync.py push                # after a rebuild: upload + re-pin (needs org `write`)
                                                            #   then: git add data_version.json && git commit

# A. Annual report → labeled ESG sentences
python -m data_processing.prepare_sentences \
    --input  "data/raw/annual_report/Xây dựng - VLXD - BĐS/AAA - Nhựa An Phát Xanh/AAA_2024.pdf" \
    --output "data/interim/sentences/aaa_sentences.jsonl"
python -m data_processing.extract_esg            # labeled JSONL → esg_extracted records

# B. News evidence for one company (conduct side)
python -m esg_news_crawler.run --ticker AAA --limit 1
python -m data_processing.preprocess_news                             # P1: → data/interim/news_preprocessed/ (date-normalize + drop boilerplate)

# C. Labeled JSONL → temporal KG (src/esg_kg — run from the repo root, in order)
python src/run.py --list                                            # every stage + status
python src/run.py quality --label baseline                         # Q1–Q8 snapshot (before/after any change; offline)
python src/run.py extract -i <labeled.jsonl>                       # → kpi_output/
python src/run.py extract_triples -i <report_labeled.jsonl>        # → graph_output/graphs/ (claim side; --source report default)
python src/run.py extract_triples -i <news_preprocessed.jsonl> --source news   # conduct side (stamps source_type=news)
python src/run.py build_validated --dry-run                        # BLOCK fix_triples -> anchor_kpi -> canonicalize, writes
                                                                           #   all_validated_triples.json ONCE (DESIGN.md §5.7); then without --dry-run
python src/run.py fix_triples --renormalize                        #   P4-only pass on the existing validated file (no LLM; not part of the block)
python src/run.py issuer                                           # → config/issuer_registry.json (run-once; then hand-confirm needs_review)
#   (no step04b: config/standards_registry.json is static config, hand-edited; quality audits its coverage)
python gri/build_gri_catalog.py                                              # → config/gri_catalog.json (run-once builder, not a stage; commit the result)
python src/run.py build_resolved --dry-run                         # BLOCK entities -> provenance -> indicators, writes
                                                                           #   resolved_graph.json ONCE (DESIGN.md §5.7); then without --dry-run
python src/run.py align_claims --dry-run                           # OPTIONAL LLM: align remaining claims (then --max-llm-pairs N to run)
python src/run.py export_kgc --dry-run                             # B4: preview hub-decomposition stats for the SSRL export view (no writes)
python src/run.py export_kgc                                       # → graph_output/export_kgc/ (never touches resolved_graph.json/Neo4j)
python src/run.py neo4j_load --dry-run                             # preview planned counts, no DB
docker compose up -d                                                 # start Neo4j on :8687 (then run neo4j/init.cypher once — see docs)
python src/run.py neo4j_load --clear                               # → Neo4j (wipe + load; needs the instance running)
python src/run.py claims_vs_conduct --dry-run                      # preview claim↔conduct pairs (runs LLM, writes nothing)
python src/run.py claims_vs_conduct                                # → graph_output/crosscheck/ (advisory dossiers + linking edges)
python src/run.py neo4j_sync                                       # push dossiers into Neo4j advisory layer (no LLM)
python src/run.py claim_ledger                                     # render the AAA claim ledger FROM Neo4j (no LLM)
python src/run.py claim_ledger --review-queue --markdown           #   contradiction-no-verification queue + Markdown file
# (step07b softmax scores and step10 P6 evaluation were both removed outright with src/ on
#  2026-07-29 — docs/PROJECT_HISTORY.md §3; there is no replacement command for either)

# ESG Evidence View UI (web front-end; reads the Neo4j advisory layer, no LLM — see docs/ESG_EVIDENCE_VIEW.md)
python api/main.py                                                         # 3-column TT96/GRI evidence view at http://localhost:8000

# Report + offline analysis (no LLM, no network, no Neo4j)
python evalu/score_census_43.py                                             # regenerates the 43-pair census numbers in capstone_report/main.tex S4.4
python notebooks/eda/news_volume_by_company.py                              # -> notebooks/eda/output/*.csv + *.png
powershell -ExecutionPolicy Bypass -File capstone_report/build.ps1          # -> capstone_report/main.pdf (MiKTeX)

# Tests — plain assert scripts, offline; full catalogue + re-run triggers in test/README.md
python test/test_temporal_invariants.py                                     # after step03/03b/03c/05/05b/05c/08
python test/test_esg_kg_equivalence.py                                      # after any core/ helper or report/quality.py
python test/test_schema_contract.py                                         # after any hand edit to config/schema.json

# Useful flags: --doc <substr>, --limit-docs N, --all (scope);
#   --all-pages (don't restrict to ESG pages); --dry-run (fix/resolve/load stages: offline only, no LLM/DB/writes);
#   extract/fix_triples/entities are Gemini-only — no --provider flag
#     (the 2026-07-29..2026-08-04 --provider openai path was removed outright);
#   extract_triples: --provider gemini|deepseek (added 2026-08-06, default from LLM_PROVIDER
#     env/gemini; deepseek skips GeminiContextCache — --no-context-cache is a no-op there);
#   quality: --label <name>, --skip-slow (skip the BFS-heavy Q7(c)/(d)), --max-hops, --standards-registry;
#   fix_triples: --renormalize (P4 pass only); anchor_kpi: --max-per-facility, --dry-run;
#   canonicalize: --aliases, --fuzzy-threshold, --no-goals, --dry-run;
#   provenance: --graphs-dir, --news-globs, --stats-out, --dry-run;
#   indicators: --crosswalk, --no-gri, --no-align, --trust-draft-crosswalk, --dry-run;
#   align_claims: --max-llm-pairs, --provider (gemini|deepseek, default from LLM_PROVIDER env/gemini),
#     --model (per-provider default when omitted), mandatory LLM, --dry-run;
#   export_kgc: --max-bucket-degree (default 500), --issuer-registry, --dry-run;
#   entities: --no-llm (Stages A+B.1 only), --standards-registry, --similarity-threshold, --max-llm-pairs;
#   neo4j_load: --clear (wipe first), --no-versions (canonical only), --database, --strict (env: NEO4J_URI/USER/PASSWORD);
#   claims_vs_conduct: LLM adjudication is mandatory (no --no-llm); --max-llm-pairs, --provider-order (default gemini;
#     'deepseek' is a swappable alternative, not a required cascade), --model, --to-neo4j;
#   neo4j_sync: --clear-advisory, --dry-run;
#   claim_ledger (Neo4j-only): --review-queue, --assessment, --claim-id, --limit, --markdown;
```

## Tests

No pytest harness and no linter — tests are plain `assert` scripts under `test/`, run from the
repo root as `python test/<name>.py`, printing pass/fail and exiting non-zero on failure.
**The per-file catalogue — what each of the 38 files guards, and when to re-run it — lives in
`test/README.md`.** The rules that belong in context:

- Every test is **offline** (no LLM, no Neo4j, no network) except
  `test_esg_kg_integration_llm.py` and `test_esg_kg_system_llm.py`, which cost money and no-op
  unless `RUN_LLM_INTEGRATION_TESTS=1` / `RUN_LLM_SYSTEM_TEST=1` is set.
- **Cover a paid or networked stage by stubbing UNDER its abstraction layer** —
  `_GeminiProvider`, `google.genai.Client`, `neo4j.GraphDatabase`, or a provider passed in as a
  parameter — with a deterministic fake (usually keyed by a CRC of the prompt), so real stage
  logic still runs against fake I/O. Never verify by re-running a paid stage.
- Re-run triggers: step03/03b/03c/05/05b/05c/08 -> `test_temporal_invariants.py`; any `core/`
  helper or `report/quality.py` -> `test_esg_kg_equivalence.py`; a hand edit to
  `config/schema.json` -> `test_schema_contract.py`; `metric/hub.py` or Q7 ->
  `test_quality_hub_set.py`.
- **Paid prompt templates are pinned byte-for-byte** by their guards
  (`test_step02_language_guard.py`, `test_step01_step07_language_guard.py`,
  `test_step03_llm_value_guard.py`, plus byte-for-byte arms inside the stage tests). A reworded
  prompt still "works" while silently changing every verdict — that is why the pin exists.

## Documentation map

`docs/SYSTEM_DESIGN.md` is the **final end-to-end system design** — read it first for the big
picture: the symmetric greenwashing setup (reports = claims, independent news = conduct, both
in one temporal KG), the news->graph branch and claim<->conduct cross-check stage, and the
deliberate "evidence + advisory LLM assessment, no greenwashing score/verdict" framing (no
ground-truth labels exist).

**Written to be read before you act:**
- `docs/PROJECT_HISTORY.md` — the refactor, the LLM-provider timeline, the removed stages, the
  deleted `GRAPH_IMPROVEMENT_PLAN.md` label map. Read before re-opening a closed decision.
- `docs/EVALUATION_BASELINE.md` — the frozen snapshot, the blind annotation, Graph-RAG vs RAG.
  Read before quoting any number.
- `test/README.md` — the test catalogue and re-run triggers.
- `docs/TEMPORAL_KG_DESIGN.md` — the 8 temporal-KG principles P1-P8 plus the Q1-Q8 quality
  attributes measured by `quality`. Read before touching the schema, step02 prompts, step03 or
  step05.

**Per-stage design notes:** `SCHEMA_EXPLAINED.md`, `KPI_EXTRACTION_FROM_JSONL.md`,
`TRIPLET_EXTRACTION_FROM_JSONL.md`, `TRIPLET_VALIDATION.md`, `PROVENANCE_PATCH.md` (step05b —
offline `source_doc`/`source_page` stamping so the UI/ledger can cite report page + article
title), `STANDARD_INDICATOR_AXIS.md` (step03c/step05c — the TT96/GRI indicator axis),
`ENTITY_RESOLUTION.md` (step05 — why it's a redesign, not a port), `GRAPH_LOAD_NEO4J.md`
(step06 — also a redesign), `CLAIM_CONDUCT_CROSSCHECK.md` (step07 — the analytical core),
`CLAIM_LEDGER.md` (step08 sync + step09 ledger + analyst Cypher), `ESG_EVIDENCE_VIEW.md` (the
3-column TT96/GRI evidence-view UI — how to run the demo), `REAL_DATA_INTEGRATION_GUIDE.md`
(Vietnamese — the mock->live-Neo4j swap for that UI, and the rule that only
`api/evidence_service.py` changes, never the frontend), `KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`,
`LABELING_STRATEGY.md` (the labelling strategy, and the subsidiary registries behind
`config/subsidiaries/`), `NEWS_CRAWLER_OPTIMIZATION.md` (Vietnamese — architecture of the
standalone, FPT-specific `crawl_data/crawler_news.py`, not the documented `esg_news_crawler/`
pipeline), `VIETNAM_IMPROVEMENT_PLAN.md`, `ENTITY_RESOLUTION_IMPROVEMENT.md` (Vietnamese —
proposal to auto-resolve step04's lexically ambiguous `needs_review` cases via graph structural
signatures). The root `ENTITY_RESOLUTION_PLAN.md` was the step04 engineering checklist and
is **no longer in the repo** — recover it with `git show e903c1f^:ENTITY_RESOLUTION_PLAN.md`.
`README.md` (root), `esg_news_crawler/README.md`, `kpi_build/README.md` and `gri/README.md`
cover their respective subsystems.

**Diagrams and pipeline redraws.** The GRI-era docs (2026-07-26) describe stage C by its
now-deleted `src/stepNN_*.py` filenames — the pipeline *shape* is still accurate, but for
current stage names read `src/PIPELINE.md` and `esg_kg/pipeline.py` instead:
`docs/PIPELINE_DIAGRAMS.md` (10 figures), `docs/PIPELINE_UNIFIED.md`, `docs/PROJECT_OVERVIEW.md`,
`docs/GRI_SCHEMA_DOCUMENTATION.md` (the shape of `gri/full_gri/json/*.json` and of
`config/gri_catalog.json`), plus the rendered diagrams in `diagram/`. Newer, root-level, and
written against the live code: `DATA_CONSTRUCTION_PIPELINE.md` (Mermaid, end-to-end A->E),
`PIPELINE_MODULE_ARCHITECTURE.md` (the same stage C redrawn as `src/esg_kg/` swimlanes) and
`FIGMA_DIAGRAM_PROMPTS.md` (prompts for regenerating the academic-style figures — the source
for `overall_pipeline/`'s React figures and `capstone_report/`'s `fig_ch3_*.png`).

**Proposals, not implementations** — don't read these as descriptions of existing code:
`CROSSCHECK_EXPANSION.md` (Vietnamese — the `signals` generator, graph-routed evidence
retrieval, and the D1 finding that `kpi_gap` / `structural_contradiction` are *ghost* signals
step07 never writes), `BERT_NER_GRAPH_QUALITY.md` (Vietnamese — local CPU sentence-embeddings
to replace `gemini-embedding-001` in step05, underthesea NER for news anchoring; explicitly
rejects fine-tuning a greenwashing classifier, since no labels exist),
`EVALUATION_WITHOUT_LABELS.md` (Vietnamese — how to evaluate ONE system with no ground truth:
metamorphic relations, negative control + permutation p-value, Krippendorff alpha; its §8 lists
metrics already tried and dead, read it before proposing a new one), `AGENT_AB_EVALUATION.md`
(Vietnamese — paired McNemar on metamorphic violations for comparing TWO systems, always
guarded by a negative-control specificity so a merely-more-lenient agent can't read as an
improvement; note its "`claim_id` is not yet deterministic" caveat is now **out of date**, see
"History that must not be re-litigated" above), and the root `GRAPH_VS_RAG_COMPARISON.md`
(Vietnamese — an unimplemented experiment design whose §4 numbers are illustrative
fabrications; NOT the real `ragtest/` + `test3/` comparison).

**`docs/ANNOTATION_RESULTS.md` is NOT a proposal — it is measured, historical output**
(Vietnamese): kappa = 0.714 between the two annotators of `sheetA`/`sheetB`, the adjudicator's
pre-fix precision on that 226/200-pair round, and the two joins that are valid versus the one
that is not. Its frozen input is `docs/ANNOTATION_GUIDELINE.md`: once labelling has begun that
guideline **must not be edited** — editing it invalidates every comparison; bump to v1.1 and
re-label instead — which is why results live in a separate file. **`evalu/` is now IN this repo**
(ported from `wip/gri-parser-and-eval` in `bb7093b`, 2026-08-13, closing issue #17), not a
branch you need to fetch separately, and is the canonical annotation tooling —
`evalu/annotation.py` (`score()`), `evalu/iaa.py` (agreement). `notebooks/eda/annotation_agreement.py`,
the temporary self-built stand-in kept only until `evalu/` merged, was deleted the same sitting;
its regeneration command is gone with it. **`sheetA.xlsx`/`sheetB.xlsx`/`sheetC.xlsx` were
deleted from the working tree in the same commit** — `docs/ANNOTATION_RESULTS.md`'s numbers do
not change (still the correct historical record of that round) but are no longer regenerable
without first recovering those three files from git history (`git show bb7093b:sheetA.xlsx`).
The *current* cited population is a separate, later 43-pair census (37 supports + 6
contradicts, superseding the 226→24 history `docs/proposals/thesis_review.md` issue #17 tracked),
labelled in `sheetA_43pairs_filled.xlsx`/`sheetB_43pairs_filled.xlsx` and reproduced by
`python evalu/score_census_43.py` — that script, not `annotation_agreement.py`, is what backs
`capstone_report/main.tex` §4.4 now.

`docs/SSRL_REASONING_LAYER.md` is referenced by `TEMPORAL_KG_DESIGN.md` but **is not in the
repo** — the path-reasoning layer (steps 11-13) is unbuilt and its design doc is missing.
