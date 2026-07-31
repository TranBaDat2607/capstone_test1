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
project files). You may read it to understand intent: `src/esg_kg` (originally
`src/`, since migrated and deleted — see "Refactor history" below) ports
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
  `.gitattributes` came to be committed here (and why this repo now routes `*.png/jpg/zip/parquet`
  through Git LFS). Guarded by `test/test_data_sync_scope.py`.
- **Secrets:** copy `.env.example` → `.env` and set `GEMINI_API_KEY` (and optionally
  `OPENAI_API_KEY`, the fallback LLM provider for the cross-check stage, and now also an
  additive provider for the stages listed below). Every `esg_kg` LLM stage loads `.env`
  from the repo root regardless of cwd. `.env` is git-ignored — never commit it.
- **Layout principle (enforced):** code lives only in the package folders
  (`crawl_data/`, `data_processing/`, `esg_news_crawler/`, `src/`,
  `kpi_build/`, `gri/`, plus the UI pair `api/` + `frontend/`). Everything else is `config/`
  (schema + dictionaries), `neo4j/` (`init.cypher` constraints + `crosscheck_queries.cypher`
  analyst queries), or `data/` (`raw/` → `interim/` → `labeled/` → `outputs/`).
  **No data files inside code packages** — with two named exceptions, both run-once
  provenance builders that keep their sources beside them so a claim can be traced to a
  page: `kpi_build/` and `gri/` (the latter carries 42 GRI Standards PDFs, ~45 MB, in Git).
- **Two execution styles — do not mix them:**
  - `data_processing/` and `esg_news_crawler/` are **packages**, run as modules:
    `python -m data_processing.extract_esg`.
  - `src/esg_kg/` is a real package, run from the repo root via its dispatcher —
    `python src/run.py quality --label baseline` (equivalently
    `python -m esg_kg.report.quality` from inside `src/`). All 15/15 stages are
    migrated (`python src/run.py --list` shows the table, reading it from the
    import system rather than a hand-kept list). **The old flat layout — one
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
  KPI-canonicalization stage's fuzzy tier; disabled with a warning if absent), `openai`
  (the crosscheck stage, and now also the extract/extract_triples/fix_triples/entities
  stages when `--provider openai` is passed). Install them on demand rather than adding
  them to `requirements.txt`.
- **Gemini is currently billing-blocked**, so the code has drifted to OpenAI where a
  choice exists: the crosscheck stage's `DEFAULT_PROVIDER_ORDER` is `"openai"` and entity
  resolution is normally run with `--no-llm` (Stages A + B.1 only — no embedding blocking,
  no adjudication). Don't "fix" these back to Gemini without checking whether the key
  works. **`extract` (KPI), `extract_triples`, `fix_triples`, and `entities` now also
  accept `--provider {gemini,openai}`** (default stays `gemini`, so existing invocations
  are unchanged) — added so integration/system testing could run end-to-end on
  `gpt-4o-mini` (or an OpenAI-compatible third-party endpoint via `--openai-base-url`)
  while Gemini stays billing-blocked. Real-LLM tests for this path live in
  `test/test_esg_kg_integration_llm.py` / `test/test_esg_kg_system_llm.py`, gated behind
  `RUN_LLM_INTEGRATION_TESTS=1` / `RUN_LLM_SYSTEM_TEST=1` — they cost money and are
  deliberately NOT part of the free/offline suite.

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

## Refactor history: flat `src/stepNN_*.py` → `src/esg_kg/` (COMPLETE — old tree deleted 2026-07-29)

**Status: done.** All 15/15 stages migrated to `src/esg_kg/`, the old flat `stepNN_*.py`
tree was deleted outright 2026-07-29, and it's the only pipeline tree now — no second copy
to stay equivalent with. `python src/run.py --list` is the live source of truth for stage
status. **Full blow-by-blow history (per-stage diff sizes, what moved when, every lesson
in detail) lives in `src/esg_kg/DESIGN.md` and `src/PIPELINE.md` (§7 in both records the
closeout) — read those, not this file, for the archival record.** What follows here is
just the cross-cutting lessons worth carrying into future work on this codebase:

- **"Hub" must be judged by import DIRECTION, not by how many files import you.** A stage
  imported by seven others can still be a safe leaf move if every symbol they take already
  lives in `core/` — check what the stage itself imports, not who imports it.
- **A same-named constant is not a shared constant.** Two modules both defining
  `DEFAULT_RATE_LIMIT = 10` look like a de-dup opportunity but aren't necessarily — importing
  one into the other can silently couple values that were only accidentally equal.
- **For a stage that patches an artifact in place, the question is "does it skip or
  recompute when it meets its own past output?", not "does it patch in place?"** A stage
  that always skips its own prior output makes its own equivalence-test fixture vacuous
  (compares two empty results and prints PASS) unless the fixture strips that prior output
  first — strip by provenance/method tag, never by edge/node label, since some of those
  edges came from elsewhere and must stay.
- **Two same-named helpers can be deliberately different, not duplicates** — e.g. this
  codebase has two `node_text` functions (one takes a properties dict, one takes a full
  node and class-dispatches); merging them would silently change a paid LLM prompt.
- **Testing a paid/networked stage for free: stub UNDER the abstraction layer**, not around
  the whole function. If the stage goes through `_OpenAIProvider`/`google.genai.Client`/a
  DB driver class, replace that attribute with a deterministic stub (e.g. keyed by a CRC of
  the prompt) so real logic still runs, just against fake I/O.
- **The block pattern (DESIGN.md §5.7):** when several stages only exist because they each
  read-then-write the same shared artifact, collapse them into one in-memory chain that
  writes the artifact ONCE (`build_validated` = fix_triples→anchor_kpi→canonicalize;
  `build_resolved` = entities→provenance→indicators). Two rules make this safe: (1) keep
  every per-stage entry point too — losing the ability to run one stage alone loses the
  ability to diagnose it; (2) cache only the non-deterministic **paid** result (e.g. LLM
  repair/adjudication, keyed by content not position), never a merely-billed-but-
  deterministic one (e.g. embeddings), since the latter isn't worth the complexity while
  Gemini stays billing-blocked and that path is dormant anyway.
- **Three stages were removed from the project outright, not ported**, and have no
  replacement command: `step10` (P6 evaluation — no-ground-truth measurement is no longer a
  deliverable), `step04b` (standards-registry reseed — superseded by static config, see
  below), `step07b` (softmax evidence-balance scores — never read by the delivered UI).
- A **deliberate full re-extraction of the graph** (rebuilding AAA from scratch, DESIGN.md
  §5.4) is the longer-term goal this refactor enabled — "would change `identity_keys`/node
  order/invalidate paid dossiers" is a scheduled cost now, not a veto. It is gated on
  **deterministic `claim_id` (GitHub issue #2)**, which has not landed yet — don't assume a
  re-extraction is safe to run until that lands.
- `config/standards_registry.json` is **static config**, not regenerated by any stage —
  hand-edit it; `quality`'s `standards_registry_audit` reports uncovered mentions instead.

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
    --provider {gemini,openai} (default gemini) — openai path added for testing/scaling
    when Gemini billing is blocked, see Environment & conventions above)
extract_triples  (step02) → graph_output/graphs/<pdf_stem>/page{N}.json  (+ _bugged.json, _malformed.txt)
   (per page: page text + page KPIs + config/schema.json → temporal triples → node/edge graph.
    --source report (default) = claim-side prompt; --source news = conduct-side prompt (Controversy/
    MediaReport/Penalty/observed KPIObservation); every node/edge stamped source_type=report|news.
    --provider {gemini,openai}, default gemini)
fix_triples      (step03) → graph_output/validated/all_validated_triples.json (+ unfixable_triples.json)
   (Phase 1 offline: swap reversed edge directions + schema-validate;
    Phase 1.5 offline (P4): canonicalize dates to ISO YYYY[-MM[-DD]], warn valid_from>valid_to,
    default missing date_uncertain on news T2 nodes; --renormalize applies only this phase to
    the existing aggregated file (no LLM, keeps prior repairs);
    Phase 2 LLM: batch-repair invalid triples (--provider {gemini,openai}, default gemini);
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
    re-running preserves human edits, --force rebuilds; a human confirms needs_review)
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
    Stage B VN-aware blocking (normalized signature + gemini-embedding-001 cosine, or an
    OpenAI embedding model via --provider openai); Stage C adjudication on ambiguous pairs
    (budgeted; gemini-2.5-flash or gpt-4o-mini); Stage D consolidate. --no-llm skips B+C)
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
   (GRAPH_IMPROVEMENT_PLAN.md B4, offline, NO LLM: reads resolved_graph.json READ-ONLY and
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
    LLM adjudication is MANDATORY (no deterministic fallback) — provider cascade
    (--provider-order, default `openai` = gpt-4o-mini); aborts up front if no provider is
    available. **OpenAI is the ONLY provider left**: Gemini support was removed outright
    because the project behind GEMINI_API_KEY is permanently 403, so passing `gemini` logs
    "Unknown adjudication provider — ignored". Do not plan a Gemini fallback here.
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

The step07b offline softmax evidence-balance scoring stage (P6-adjacent, not shown above) was
never wired into the delivered UI surface and was removed outright with `src/` on 2026-07-29,
same decision as step04b above — see "Refactor history" for the record.

`step10_evaluate.py` (step 8 / P6 evaluation report, no-ground-truth coverage/case-study/
ablation) was **removed from the project on 2026-07-28** — see "Refactor history" above.
The claim ledger (`step09`) is the last stage in the pipeline now.

Stages share helpers through `esg_kg/core/`: `paths` (`REPO_ROOT`), `io_jsonl`
(`build_page_text`, `load_pages_from_jsonl`, ...), `llm` (`RateLimiter`, `_OpenAIProvider`,
...), `schema` (`load_schema_sets`, ...), `naming` (`normalize_name`, ...), `dates`,
`identity`, `graph_patch`. No stage imports another stage's internals any more — that
sibling-importing shape belonged to the old `src/` scripts and was untied module by module
during the refactor (see "Refactor history" above). Changing a `core/` helper's signature
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
See `docs/SCHEMA_EXPLAINED.md` for the rationale.

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
    --input  "data/raw/annual_reports_sample/AAA_Baocaothuongnien_2025.pdf" \
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
#  2026-07-29 — see "Refactor history" above; there is no replacement command for either)

# ESG Evidence View UI (web front-end; reads the Neo4j advisory layer, no LLM — see docs/ESG_EVIDENCE_VIEW.md)
python api/main.py                                                         # 3-column TT96/GRI evidence view at http://localhost:8000

# Useful flags: --doc <substr>, --limit-docs N, --all (scope);
#   --all-pages (don't restrict to ESG pages); --dry-run (fix/resolve/load stages: offline only, no LLM/DB/writes);
#   --provider {gemini,openai} on extract/extract_triples/fix_triples/entities (default gemini;
#     --openai-model, --openai-base-url for a third-party OpenAI-compatible endpoint);
#   quality: --label <name>, --skip-slow (skip the BFS-heavy Q7(c)/(d)), --max-hops, --standards-registry;
#   fix_triples: --renormalize (P4 pass only); anchor_kpi: --max-per-facility, --dry-run;
#   canonicalize: --aliases, --fuzzy-threshold, --no-goals, --dry-run;
#   provenance: --graphs-dir, --news-globs, --stats-out, --dry-run;
#   indicators: --crosswalk, --no-gri, --no-align, --trust-draft-crosswalk, --dry-run;
#   align_claims: --max-llm-pairs, --openai-model, --openai-base-url, --dry-run;
#   export_kgc: --max-bucket-degree (default 500), --issuer-registry, --dry-run;
#   entities: --no-llm (Stages A+B.1 only), --standards-registry, --similarity-threshold, --max-llm-pairs,
#     --openai-embed-model;
#   neo4j_load: --clear (wipe first), --no-versions (canonical only), --database, --strict (env: NEO4J_URI/USER/PASSWORD);
#   claims_vs_conduct: LLM adjudication is mandatory (no --no-llm); --max-llm-pairs, --provider-order (default openai),
#     --openai-base-url, --to-neo4j;
#   neo4j_sync: --clear-advisory, --dry-run;
#   claim_ledger (Neo4j-only): --review-queue, --assessment, --claim-id, --limit, --markdown;
```

No pytest harness or linter is configured — tests are plain assert scripts under `test/`
(see the TDD working rule above; new code adds new files here, test-first). The existing
check covers the P3/P4 Phase-0 temporal logic, the step05b provenance matching, and the
indicator-axis stages (step03c/step05c/step08) — run it from the repo root after touching
step03/step03b/step03c/step05/step05b/step05c/step08.

**Reading note on the per-file comments below**: many were written while `src/` and
`esg_kg` existed side by side, so phrases like "both trees" / "BOTH trees" describe how
that test *proved the migration correct at the time* — importing `src/` as the oracle and
comparing. After `src/` was deleted (2026-07-29), every one of those files (`test_esg_kg_*`,
`test_console_utf8.py`, `test_standards_audit.py`) was converted to a single-tree test
against `esg_kg` alone — same assertions, same non-vacuity guarantees, no `src/` import
left anywhere. Read "both trees" in what follows as history, not as what the test imports
today:

```bash
python test/test_temporal_invariants.py    # offline, no LLM/DB; asserts date canonicalization,
                                           # temporal invariants, source_id parsing, DSU consolidate,
                                           # provenance tier matching + node-order invariant,
                                           # kpi_id canonicalization, indicator-axis edge minting,
                                           # and step08 stable-id (claim_id) resolution
python test/test_schema_contract.py        # config/schema.json itself: P1 both ways (T1 identity
                                           # timeless / T2 observations KEEP their time key), every
                                           # class in exactly one tier, indicator-axis edge pairs.
                                           # Tier map is IMPORTED from step00, never re-declared.
                                           # Run after ANY hand-edit to schema.json.
python test/test_indicator_axis.py         # drives step05c's real run() on a temp workspace:
                                           # self-reported-zero Penalty gets NO conduct edge,
                                           # kpi_id-not-kpi_type boundary, confirmed-crosswalk
                                           # gate, stage-level append-only + idempotency.
python test/test_standards_audit.py        # esg_kg's standards-registry audit (quality.py):
                                           # an uncurated GRI spelling surfaces, an out-of-scope
                                           # accounting standard does NOT (the noise filter that
                                           # makes the section readable), a curated exclusion
                                           # stays closed, and canonical_name is never reported
                                           # as unknown (step04b's old feedback artifact).
                                           # Run after touching step00 or the registry config.
python test/test_pipeline_table.py         # esg_kg stage table (esg_kg/pipeline.py + run.py):
                                           # every old_step label is well-formed and unique
                                           # (src/ is gone, so this no longer checks a real
                                           # file exists — see pipeline.py's own docstring),
                                           # short names don't collide, block members are all
                                           # migrated stages, and a stage that will NEVER be
                                           # ported is rendered as such instead of "not yet"
                                           # (which would keep dead work permanently queued).
python test/test_gri_catalog_build.py      # gri/build_gri_catalog.py: a disclosure is attributed
                                           # to the standard whose id is its prefix (not to whichever
                                           # file sorts first), pillar comes from the source via
                                           # PILLAR_MAP (never a substring guess), provenance fields
                                           # agree with the attributed standard, and GRI 306's real
                                           # 2016+2020 versions still merge. Run after touching gri/.
python test/test_console_utf8.py           # ensure_utf8_stdout in BOTH trees + the WIRING (main()
                                           # actually calls it, nothing calls it at import). Closes
                                           # the hole the equivalence test cannot see: it never
                                           # executes main() or a __main__ block.
python test/test_data_sync_scope.py        # esg_kg.core.datasync pull is scoped to the three
                                           # synced folders, so it can never overwrite a tracked
                                           # repo-root file (that is how the Hub's .gitattributes
                                           # got committed). Offline: snapshot_download is a recorder.
python test/test_esg_kg_datasync.py        # esg_kg.core.datasync (the src/data_sync.py port,
                                           # 2026-07-29 — the last file that blocked deleting
                                           # src/): constants match the documented shape, push/pull
                                           # scoping, status reporting. Offline: huggingface_hub
                                           # calls replaced by recorders, nothing touches the network.
python test/test_esg_kg_equivalence.py     # regression net for esg_kg's core/ helpers and
                                           # quality.py (step00's whole Q1-Q8 surface), run on
                                           # the real schema/corpus against golden values
                                           # captured from esg_kg itself (converted from a
                                           # src/-vs-esg_kg comparison once src/ was proven
                                           # equivalent and then deleted, 2026-07-29). Run
                                           # after ANY edit to a core/ helper, or to
                                           # esg_kg/report/quality.py — real graph with
                                           # --skip-slow, plus a synthetic 20-node graph for
                                           # the 44s Q7 BFS arms.
python test/test_esg_kg_anchor_kpi.py      # same contract as the file above, for the step03b
                                           # migration slice: core/identity (parse_source_id,
                                           # get_stable_entity_id, PROVENANCE_CLASSES) and
                                           # graph/anchor_kpi. Split off because that file is
                                           # past 1,100 lines. Runs the stage in BOTH trees on
                                           # the real corpus with strip_anchors() applied (the
                                           # file on disk is already patched — without the
                                           # strip the arm compares two empty results), plus a
                                           # cap=1 arm for the P5 hub guard the live data never
                                           # trips, plus an idempotency arm. Run after touching
                                           # step03b, step02's identity helpers, or step05b.
python test/test_esg_kg_provenance.py      # same contract, for the step05b migration slice
                                           # (resolve/provenance). Note the CONTRAST with the
                                           # file above: step05b does NOT skip its own past
                                           # output, it re-stamps, so the live-graph arm is
                                           # already non-vacuous (6,258 stamps compared in both
                                           # trees). strip_provenance() is there to prove the
                                           # stage never READS its own output — no key it writes
                                           # is in any identity_keys, so a stripped rebuild must
                                           # be identical. Plus a node-order arm (step06 keys
                                           # Neo4j by array index) and a synthetic arm for the
                                           # provenance_method="extraction" skip that no live
                                           # node exercises. Run after touching step05b, step02's
                                           # identity helpers, or the per-page graph writer.
python test/test_esg_kg_llm.py             # same contract, for the core/llm slice (RateLimiter
                                           # <- step02, _Provider/_OpenAIProvider <- step07).
                                           # Needs NO artifacts, so every arm runs on a bare
                                           # clone. Drives the throttle through a FAKE CLOCK
                                           # (never really sleeps) and pins the PAID request
                                           # shape with a stub client: temperature=0,
                                           # response_format=json_object, the system/user
                                           # split, and wait_if_needed BEFORE create. Those
                                           # are behaviour, not style — dropping one still
                                           # "works" while silently changing every verdict.
                                           # Run after touching step02's RateLimiter, step07's
                                           # providers, or any stage's DEFAULT_RATE_LIMIT.
python test/test_esg_kg_fix_triples.py     # same contract, for the step03 migration slice
                                           # (graph/fix_triples). The headline arm runs the
                                           # REAL corpus (43 doc dirs / 1,370 page files)
                                           # through both trees with client=None — phase 2
                                           # logs-and-skips, so it is offline and free — and
                                           # compares the written artifacts (14,492 validated
                                           # + 1,036 unfixable). No strip_* fixture needed:
                                           # unlike 05c/03b/05b this stage never reads its own
                                           # output. Phase 2 IS covered, by a stubbed tampering
                                           # LLM in both trees, which is what proves
                                           # preserve_property_values is wired into the
                                           # migrated copy and not just src/. Also pins
                                           # BATCH_FIX_PROMPT byte-for-byte (a reworded paid
                                           # prompt still "works" while changing every repair)
                                           # and asserts the new tree IMPORTS the four kernel
                                           # helpers rather than re-copying them. Run after
                                           # touching step03, core/dates, or core/schema.
python test/test_step03_llm_value_guard.py # step03 phase 2 may repair a triple's SHAPE
                                           # (class/predicate/temporal fields) but never
                                           # translate/reformat/invent/drop a property VALUE
                                           # (preserve_property_values) — belt-and-braces on
                                           # top of BATCH_FIX_PROMPT now that step02 emits
                                           # Vietnamese name/title (issue #6): an
                                           # English-instructed repair model "fixing" a VN
                                           # name would silently split one entity into two at
                                           # step05. Asserts both behaviour (guard restores/
                                           # drops/permits the right fields) and wiring (a
                                           # stubbed tampering LLM run through the real
                                           # process_all_files, artifact read back). Offline.
                                           # Run after touching step03's BATCH_FIX_PROMPT or
                                           # preserve_property_values.
python test/test_esg_kg_validated_block.py # the 03 BLOCK (DESIGN.md §5.7): 03 -> 03b -> 03c
                                           # as one unit writing the artifact ONCE. The main
                                           # arm runs the src/ chain as an ORACLE and asserts
                                           # the block's artifact is identical — that works
                                           # because the redesign changes WHEN the file is
                                           # written, not WHAT is in it. Paired with a
                                           # non-vacuity arm (src/ chain must write it 3×,
                                           # block exactly 1×) so "exactly 1" cannot be
                                           # trivially true. Also pins the paid-repair cache:
                                           # a second run calls the LLM ZERO times, and a
                                           # rebuild with client=None still reproduces the
                                           # cached repair. Run after touching the block,
                                           # fix_triples.run_phases, anchor_kpi or canonicalize.
python test/test_esg_kg_align_claims.py    # same contract, for the step05d migration slice
                                           # (resolve/align_claims). This stage REQUIRES an
                                           # LLM and --dry-run returns before the provider is
                                           # built, so both trees are driven by a STUB provider
                                           # injected over _OpenAIProvider, answering
                                           # deterministically from a CRC of the prompt — the
                                           # whole paid path compared for free, on the real
                                           # resolved graph (1,810 candidates, 60 adjudications).
                                           # Pins the node_text trap (05d takes a properties
                                           # dict, step07 takes a node — merging them rewrites
                                           # step07's paid prompt), SYSTEM byte-for-byte, and
                                           # append-only/node order, which nothing else guards
                                           # because 05d never calls assert_append_only itself.
                                           # Synthetic fixtures cover the 3-failure abort, an
                                           # indicator id with no node, and the re-run skip.
                                           # Run after touching step05d or core/graph_patch.
python test/test_esg_kg_crosscheck.py      # same contract, for the step07 migration slice
                                           # (crosscheck/claims_vs_conduct) — the highest-
                                           # leverage move so far: the only stage that was
                                           # still blocking others (08 on node_text, 10 on
                                           # Adjudicator). _Provider/_OpenAIProvider now
                                           # import FROM core.llm instead of being redefined
                                           # (that kernel module was extracted FROM this file
                                           # on 2026-07-27); Adjudicator stays in the stage.
                                           # Unlike step05d, --dry-run here does NOT return
                                           # before the provider is built, so the dry-run arm
                                           # is a real equivalence check, not a vacuous one.
                                           # Headline arm runs the full retrieval + stub
                                           # adjudication + dossier path on the real resolved
                                           # graph (1,093 claims, 3,461 candidate pairs) in
                                           # both trees and compares dossiers/stats/edges
                                           # (masking the one non-deterministic field,
                                           # `recorded_at`). Pins the node_text trap from this
                                           # side (this stage's takes a NODE and dispatches on
                                           # class; step05d's takes a properties dict),
                                           # ADJUDICATE_SYSTEM byte-for-byte, the self-
                                           # verification guard (a company-owned domain must
                                           # never get a verifiedBy edge), and the assessment-
                                           # mapping priority (contradiction beats support in
                                           # the same dossier) via synthetic fixtures. Also
                                           # covers a follow-up fix, same shape as step05d's
                                           # a308608: _parse_verdict called .get() on whatever
                                           # json.loads returned, so a reply like "[]" crashed
                                           # instead of being refused — smaller blast radius
                                           # here (caught by Adjudicator.adjudicate's own
                                           # try/except) but still wrong. Fixed in BOTH trees.
                                           # Run after touching step07 or core/llm.
python test/test_esg_kg_issuer.py          # same contract, for the step04 migration slice
                                           # (registry/issuer) — confirmed leaf, not hub:
                                           # AST-diff shows 11 shared functions, 0 bytes
                                           # different; the 3 deleted functions are exactly
                                           # the 3 now imported from core/naming. The stage
                                           # writes config/issuer_registry.json, a file
                                           # TRACKED in git with human edits, so every arm
                                           # runs build() against a temp workspace — one arm
                                           # asserts the real tracked file is never touched,
                                           # another simulates a person moving a needs_review
                                           # entry into exclusions and re-running, proving the
                                           # edit survives identically in both trees. Also
                                           # covers a follow-up fix: build() used to silently
                                           # accept an alternate {nodes,edges} input shape
                                           # that no writer has produced since step03 started
                                           # emitting List[Dict] — removed in BOTH trees,
                                           # red-first. Run after touching step04 or
                                           # core/naming.
python test/test_esg_kg_extract.py         # same contract, for the step01 migration slice
                                           # (kpi/extract) — the last genuine hub (nothing
                                           # else was still importing another stage's
                                           # stage-local symbols). This stage does NOT use
                                           # _Provider/_OpenAIProvider: core/llm.py's own
                                           # docstring records that no Gemini provider was
                                           # ever lifted, so KPIExtractor talks to
                                           # google.genai.Client directly and stays entirely
                                           # stage-local — only the 5 pure JSONL helpers
                                           # (load_pages_from_jsonl, build_page_text,
                                           # page_has_esg, select_documents,
                                           # parse_company_year_from_filename) move, into a
                                           # NEW kernel module core/io_jsonl.py — exactly the
                                           # 5 symbols step02 imports from step01, so this
                                           # module is what step02 needs, not a precondition
                                           # for step01 itself. The paid path has no
                                           # _Provider to stand in front of, so the stub is
                                           # injected directly over google.genai.Client,
                                           # answering deterministically from a CRC of the
                                           # prompt — the fourth use of that technique,
                                           # confirming it is a general pattern and not an
                                           # OpenAI-specific trick. Headline arm compares
                                           # load_pages_from_jsonl/build_page_text/
                                           # page_has_esg on the real corpus (13 documents /
                                           # 1,356 pages) plus a synthetic process_document
                                           # run through both trees, including an idempotency
                                           # check (out_file.exists() must skip without
                                           # re-calling the client). Run after touching
                                           # step01 or core/llm.
python test/test_esg_kg_neo4j_sync.py      # same contract, for the step08 migration slice
                                           # (load/neo4j_sync) — the first NEO4J-touching
                                           # stage to migrate. A confirmed leaf: it imports
                                           # only its own REPO_ROOT and node_text from step07
                                           # (moved the day before — that move is what
                                           # unblocked this one). Every earlier paid/networked
                                           # stage covered its expensive branch by stubbing
                                           # UNDER an existing abstraction (_OpenAIProvider,
                                           # google.genai.Client); step08 has no such layer in
                                           # front of the real call (a lazy `from neo4j import
                                           # GraphDatabase` inside run(), executed only past
                                           # --dry-run), so the stub replaces the installed
                                           # neo4j package's GraphDatabase attribute directly —
                                           # the same shape step01 used when there was no
                                           # provider abstraction in front of the Gemini
                                           # client either. The fake driver records every
                                           # Cypher string + parameter dict and executes
                                           # nothing, so the headline arm compares 5 real
                                           # Neo4j calls byte-for-byte between both trees on
                                           # the real corpus (1,093 dossiers against the
                                           # 10,425-node resolved graph) without touching a
                                           # live database. Also covers --clear-advisory, a
                                           # missing-resolved-graph positional-only fallback,
                                           # the sys.exit(1) guard for a missing dossier file,
                                           # and pins the node_text trap from a third angle
                                           # (esg_kg.load.neo4j_sync.node_text IS
                                           # esg_kg.crosscheck.claims_vs_conduct.node_text).
                                           # Run after touching step08 or crosscheck's
                                           # node_text.
python test/test_esg_kg_neo4j_load.py      # same contract, for the step06 migration slice
                                           # (load/neo4j_load) — the second Neo4j-WRITING
                                           # stage. Wider client surface than step08:
                                           # ingest_nodes/ingest_data_edges/ingest_supersedes
                                           # go through session.execute_write(lambda tx:
                                           # tx.run(...).consume()) rather than a bare
                                           # session.run(), and print_graph_stats reads
                                           # back (.single(), iteration) — so the fake
                                           # session/tx must answer both call shapes and
                                           # read shapes, still recording (cypher, params)
                                           # and executing nothing. Headline arm:
                                           # build_payload() as a pure function on the real
                                           # corpus (10,425 nodes) plus an ingestion arm
                                           # comparing 76 Neo4j calls byte-for-byte between
                                           # both trees. Run after touching step06.
python test/test_esg_kg_claim_ledger.py    # same contract, for the step09 migration slice
                                           # (report/claim_ledger) — the first Neo4j-READING
                                           # stage migrated, unlike step06/step08 which only
                                           # write. load_from_neo4j() actually processes what
                                           # the driver returns, so a "just record the call"
                                           # fake driver (step06/step08's shape) would give a
                                           # vacuous arm — the fake here must return REAL FAKE
                                           # DATA, a queue of 4 result sets in the exact order
                                           # of the 4 session.run() calls, so both the Cypher
                                           # and the assembled dossier can be compared. Also
                                           # the first migrated stage with NO real-corpus arm
                                           # at all (it reads only Neo4j, no JSON file on
                                           # disk) — the strongest arm instead covers the pure
                                           # presentation/sorting helpers (build_header,
                                           # render_markdown, _sort_key, ...), which is most of
                                           # the stage's real logic. Run after touching step09.
python test/test_esg_kg_entities.py        # same contract, for the step05 migration slice
                                           # (resolve/entities) — confirmed leaf (every import
                                           # already in core/; one dead import,
                                           # load_schema_sets, dropped — same "garbage import"
                                           # shape as 05d/07). Unlike most leaf moves,
                                           # resolve() was split into resolve_graph() (pure,
                                           # no file I/O, no client construction) + main() AT
                                           # MIGRATION TIME, not as a later block follow-up
                                           # (contrast fix_triples/run_phases), because the
                                           # resolve BLOCK (build_resolved.py) needs to call it
                                           # directly. Headline arm: resolve_graph() vs the old
                                           # resolve() on the real corpus with no_llm=True —
                                           # today's actual operating mode per "Gemini is
                                           # currently billing-blocked" above, not a weakened
                                           # proxy — comparing the full resolved graph
                                           # (10,356 nodes / 13,041 edges, identical). The paid
                                           # path (Stage B embeddings + Stage C adjudication)
                                           # is covered by a stub over google.genai.Client —
                                           # same technique as step01 (no _Provider
                                           # abstraction stands in front of Gemini) — on a
                                           # synthetic near-duplicate-org fixture (a VN name
                                           # and its English translation, engineered to reach
                                           # Stage B/C since Stage A/B.1 cannot merge them).
                                           # Also proves the new-tree-only AdjudicationCache
                                           # property: a second resolve_graph() call with the
                                           # same cache object calls the LLM zero times and
                                           # reproduces the identical result. Run after
                                           # touching step05 or core/llm.
python test/test_esg_kg_resolve_block.py   # the 05 BLOCK (DESIGN.md §5.7, §3.2b): 05 -> 05b
                                           # -> 05c as one unit writing resolved_graph.json
                                           # ONCE. Same shape as test_esg_kg_validated_block.py
                                           # for the 03 block. Headline arm runs the REAL
                                           # src/ chain step05(--no-llm) -> step05b -> step05c
                                           # as an ORACLE on the real corpus (14,677 validated
                                           # triples) and asserts the block's artifact is
                                           # identical (10,425 nodes / 14,387 edges). Paired
                                           # with the "writes exactly once" arm and its
                                           # counter-arm (the src/ chain must write it 3x, the
                                           # block exactly 1x) — same technique as the 03
                                           # block. The paid-path cache arm runs the block
                                           # twice through a stubbed google.genai.Client on the
                                           # same near-duplicate-org fixture as
                                           # test_esg_kg_entities.py: the second run calls
                                           # generate_content ZERO times and reproduces the
                                           # identical artifact — proving AdjudicationCache
                                           # (Stage C only; Stage B/embeddings is deliberately
                                           # NOT cached, see build_resolved.py's docstring).
                                           # Also a smoke-check that the ALREADY-migrated,
                                           # UNCHANGED 05d (align_claims) still runs cleanly
                                           # --dry-run against the block's output, since 05d
                                           # is deliberately NOT part of the block. Run after
                                           # touching step05, step05b, step05c, or the block.
python test/test_step02_language_guard.py  # issue #6: pins that TEMPORAL_GRAPH_PROMPT_TEMPLATE
                                           # and NEWS_GRAPH_PROMPT_TEMPLATE require Vietnamese
                                           # output (name/title/description/free text) and no
                                           # longer model the drift in their own worked examples.
                                           # Prompt-text-only (no runtime guard at step02 itself —
                                           # the consequence-guard already lives at step03,
                                           # preserve_property_values, 046e572); red against the
                                           # unfixed prompt. Run after touching either template.
python test/test_esg_kg_extract_triples.py # same contract as the files above, for the step02
                                           # migration slice (graph/extract_triples) — the 15th
                                           # and FINAL stage. Confirmed leaf: every symbol it
                                           # imports was already lifted (core/io_jsonl, core/llm,
                                           # core/schema, core/identity); the one stage-local
                                           # duplicate, schema_sets(), is deleted in favour of
                                           # core.schema.load_schema_sets(). Unlike step01,
                                           # step02 never constructs its own client — call_llm/
                                           # process_page/process_document all take `client` as a
                                           # plain parameter, so the paid-path stub is a fake
                                           # client object passed in directly, not a genai.Client
                                           # monkeypatch. 12 groups: kernel-reuse identity checks,
                                           # a real-corpus arm (13 documents), both prompt
                                           # templates pinned byte-for-byte (carrying the issue-#6
                                           # language fix), build_page_prompt compared for both
                                           # --source report and --source news, and the paid path
                                           # driven by 4 deterministic response shapes. Run after
                                           # touching step02 or core/io_jsonl.
python test/test_export_kgc.py             # esg_kg.export.export_kgc (GRAPH_IMPROVEMENT_PLAN.md
                                           # B4): reuses metric/hub.py's multi-issuer cluster
                                           # machinery rather than reimplementing hub detection.
                                           # Synthetic 2-issuer fixture proves the property that
                                           # matters for scaling — a bucketed ticker's nodes/edges
                                           # never leak into an untouched ticker's — plus input-
                                           # purity (never mutates nodes/edges in place),
                                           # determinism (two runs, byte-identical output),
                                           # is_synthetic flagging on every new node/edge (P7 —
                                           # a bucket hop carries no source sentence, so it must
                                           # be flagged, not presented as a citable reasoning
                                           # step), and that "HubBucket" never appears in
                                           # config/schema.json (it is a dataset-construction
                                           # artifact, not a T1/T2/T3 entity). Real-corpus arm
                                           # (skips gracefully without the HF snapshot) asserts
                                           # an order-of-magnitude degree reduction AND that
                                           # resolved_graph.json's bytes on disk are unchanged
                                           # after the stage runs — the whole point of the
                                           # export-only design. Run after touching export_kgc
                                           # or metric/hub.py.
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
schema, step02 prompts, step03, or step05), `KPI_EXTRACTION_FROM_JSONL.md`, `TRIPLET_EXTRACTION_FROM_JSONL.md`,
`TRIPLET_VALIDATION.md`, `PROVENANCE_PATCH.md` (step 5b — offline source_doc/source_page
stamping of the resolved graph so the UI/ledger can cite report page + article title),
`ENTITY_RESOLUTION.md` (step 4 — why it's a redesign, not a port),
`GRAPH_LOAD_NEO4J.md` (step 5 — Neo4j load; also a redesign),
`CLAIM_CONDUCT_CROSSCHECK.md` (step 6 — claim↔conduct cross-check, the analytical core),
`CLAIM_LEDGER.md` (step 6b sync + step 7 — dossier → Neo4j advisory layer, then the Neo4j-only claim ledger + analyst Cypher),
`ESG_EVIDENCE_VIEW.md` (the 3-column TT96/GRI evidence-view UI, `api/` + `frontend/` — how to run the demo),
`REAL_DATA_INTEGRATION_GUIDE.md` (Vietnamese — the mock→live-Neo4j swap for that UI; the
rule that only `api/evidence_service.py` changes, never the frontend),
`ENTITY_RESOLUTION_IMPROVEMENT.md` (Vietnamese — proposal to use graph structural
signatures to auto-resolve step-4's lexically ambiguous `needs_review` cases),
`KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`, `VIETNAM_IMPROVEMENT_PLAN.md`,
`NEWS_CRAWLER_OPTIMIZATION.md` (Vietnamese — architecture of the standalone, FPT-specific
`crawl_data/crawler_news.py`, not the documented `esg_news_crawler/` pipeline). The root
`ENTITY_RESOLUTION_PLAN.md` is the step-4 engineering checklist. `README.md` (root),
`esg_news_crawler/README.md`, `kpi_build/README.md`, and `gri/README.md` cover their
respective subsystems.

Added with the GRI catalog (2026-07-26), describing stage C by its now-deleted `src/`
filenames — the pipeline shape/diagrams are still accurate, but none of them mention
`src/`/`esg_kg`'s stage names, so for the current view of stage C read
`src/PIPELINE.md` and `esg_kg/pipeline.py` instead: `docs/PIPELINE_DIAGRAMS.md` (10 figures: architecture,
collection, extraction, KPI, KG construction, entity resolution, cross-check, schema, data
layout, end-to-end sequence), `docs/PIPELINE_UNIFIED.md`, `docs/PROJECT_OVERVIEW.md`,
`docs/GRI_SCHEMA_DOCUMENTATION.md` (the shape of `gri/full_gri/json/*.json` and of
`config/gri_catalog.json`), plus the rendered diagrams in `diagram/`.

**Proposals, not implementations** (pre-defence-1 improvement plan — don't read them as
descriptions of existing code): `CROSSCHECK_EXPANSION.md` (Vietnamese — the `signals`
generator, graph-routed evidence retrieval, and the D1 finding that `kpi_gap` /
`structural_contradiction` are currently *ghost* signals step07 never writes) and
`BERT_NER_GRAPH_QUALITY.md` (Vietnamese — decision analysis: local CPU sentence-embeddings
to replace the billing-blocked `gemini-embedding-001` in step05, underthesea NER for news
anchoring; explicitly rejects fine-tuning a greenwashing classifier, since no labels exist).
`docs/SSRL_REASONING_LAYER.md` is referenced by `TEMPORAL_KG_DESIGN.md` but **is not in the
repo** — the path-reasoning layer (steps 11–13) is unbuilt and its design doc is missing.
