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
  snapshot. `neo4j_data/` is never synced — rebuild it with step06. Both `push` and `pull` are
  scoped with `ALLOW_PATTERNS` to exactly those three folders: `local_dir` is the CODE repo, so
  an unscoped pull writes the dataset's own root files over tracked ones — that is how the Hub's
  `.gitattributes` came to be committed here (and why this repo now routes `*.png/jpg/zip/parquet`
  through Git LFS). Guarded by `test/test_data_sync_scope.py`.
- **Secrets:** copy `.env.example` → `.env` and set `GEMINI_API_KEY` (and optionally
  `OPENAI_API_KEY`, the fallback LLM provider for step 6's cross-check). All `src/` LLM
  scripts load `.env` from the repo root regardless of cwd. `.env` is git-ignored — never
  commit it.
- **Layout principle (enforced):** code lives only in the package folders
  (`crawl_data/`, `data_processing/`, `esg_news_crawler/`, `src/`, `src_module/`,
  `kpi_build/`, `gri/`, plus the UI pair `api/` + `frontend/`). Everything else is `config/`
  (schema + dictionaries), `neo4j/` (`init.cypher` constraints + `crosscheck_queries.cypher`
  analyst queries), or `data/` (`raw/` → `interim/` → `labeled/` → `outputs/`).
  **No data files inside code packages** — with two named exceptions, both run-once
  provenance builders that keep their sources beside them so a claim can be traced to a
  page: `kpi_build/` and `gri/` (the latter carries 42 GRI Standards PDFs, ~45 MB, in Git).
- **Two execution styles — do not mix them:**
  - `data_processing/` and `esg_news_crawler/` are **packages**, run as modules:
    `python -m data_processing.extract_esg`.
  - `src/` scripts are **standalone files** run directly (`python src/step02_extract_triplet_from_jsonl.py`);
    they import each other by module name relying on Python putting `src/` on `sys.path`.
    Run them from the repo root.
  - `src_module/esg_kg/` is the in-progress third style (see the refactor section below):
    a real package, run from the repo root via its dispatcher —
    `python src_module/run.py quality --label baseline` (equivalently
    `python -m esg_kg.report.quality` from inside `src_module/`). Five stages have been
    migrated so far; `python src_module/run.py --list` shows which, and it asks the
    import system rather than trusting a hand-kept list. `src/` is still the pipeline
    you execute.
- **Sentence-level traceability** (`source_pdf`, `page`, `sentence_index`) is preserved
  through every stage so each graph node traces back to its source — keep it intact.
- **Torch is intentionally absent from `requirements.txt`.** The ViDeBERTa ESG classifier
  runs on GPU via `notebooks/kaggle_esg_classify.ipynb`; install torch locally only to
  test `data_processing/esg_classifier.py` on CPU.
- **Other deps are deliberately unlisted and imported lazily** — each degrades gracefully
  so a bare clone still runs: `huggingface_hub` (`data_sync.py`), `rapidfuzz` (step03c's
  fuzzy tier; disabled with a warning if absent), `openai` (step07/step10). Install them
  on demand rather than adding them to `requirements.txt`.
- **Gemini is currently billing-blocked**, so the code has drifted to OpenAI where a
  choice exists: step07's `DEFAULT_PROVIDER_ORDER` is `"openai"` and step05 is run with
  `--no-llm` (Stages A + B.1 only — no embedding blocking, no adjudication). Don't
  "fix" these back to Gemini without checking whether the key works.

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

## Active refactor: `src/` → `src_module/esg_kg/`

Migrating the 19 flat `src/step*.py` scripts to a module architecture, **one stage at a
time**. Design + old→new file mapping: `src_module/esg_kg/DESIGN.md`; canonical run order
(replacing the `stepNN_` prefixes): `src_module/esg_kg/pipeline.py`.

Non-negotiable rules while this is in flight:
- **Model A — never rewire `src/`.** The old pipeline must keep running untouched.
  `esg_kg` is not on `src/`'s `sys.path`, so editing `src/` to import from it would just
  `ImportError`. Helpers therefore **exist in both trees temporarily** — accepted cost.
- **The TDD test for this refactor is an old-vs-new equivalence test**: import the `src/`
  original *and* the `esg_kg` version, run both on real input, assert equal results. Write
  it before extracting the module. This is the only thing preventing the two copies drifting.
- **A stage may move only when every symbol IT imports already lives in `esg_kg.core`** —
  *not* merely when nobody imports it. Order: finish `core/` → leaf stages → hubs
  (step04 → step03 → step02 → step01).
- Extract helpers **verbatim**. Behaviour changes and refactoring are separate commits.

**Goal of the refactor: `esg_kg` must be able to rebuild the graph from scratch — including
for AAA** (DESIGN.md §5.4, decided 2026-07-26). So **"it would change `identity_keys` /
node order / invalidate the paid dossiers" is NOT a veto any more** — it is a scheduled
cost. When a refactor touches a mechanism whose correct fix belongs at an earlier stage,
**canonicalize it there** instead of preserving the later patch; keep a late patch only
under E2/E3 (those are about *information*, which a re-extraction cannot recover). E1
patches (`anchor_method`, `provenance_method`, step03c's `kpi_id`) now have an expiry date.
Two things do not relax: §5.3 still applies (a canonicalization is a behaviour change → its
own commit, **both trees**, red-first test), and the re-extraction is a deliberate one-time
decision — **deterministic `claim_id` (GitHub issue #2) must land first**, or step08's tier-1
resolution misses silently. Until that run happens, `src/` is still the live pipeline.

State: `core/` has `paths` (marker-based `REPO_ROOT`), `schema`, `naming`, `dates`, all
covered by `test/test_esg_kg_equivalence.py`. **`step00` is the first migrated STAGE**
(`esg_kg/report/quality.py`) — with it the run convention is settled: `src_module/run.py`
is the only file that touches `sys.path`, and it reads the stage table from `pipeline.py`
so `--list` reports migration status honestly. No `pip install` step.

`step03c` is the second migrated stage (`esg_kg/kpi/canonicalize.py`), its equivalence arm
comparing all 5,214 real KPIObservation occurrences across both trees.
**`step04b` is deliberately NOT ported either** (DESIGN.md §4.2, decided 2026-07-26): it read
`resolved_graph.json` — step05's *output* — while step05 reads the registry it writes, a
dependency cycle that made it unrunnable on a bare clone; and its scan earned nothing (all 10
aliases in the committed registry are its own hardcoded `SEEDS`, and a re-run only surfaced
step04b's own `canonical_name` as a to-review item). So **`config/standards_registry.json` is
static config now** — nothing regenerates it, it carries `match_patterns`/`exclude_hints`
inline, and **step00 audits its coverage** instead (`standards_registry_audit`, same family as
the P1 identity lint). `src/step04b_build_standards_registry.py` is NOT deleted — it remains
the from-scratch reseed tool.
`step05c` is the third migrated stage (`esg_kg/resolve/indicators.py`, 2026-07-27). Moving it
gave `GraphPatch`/`temporal_md` a home in **`core/graph_patch.py`** — they had been imported
UP into `src/step05d:34` from a stage, the "a step file doubles as a utility library" knot
`core/` exists to untie. The diff against `src/` is 15 added / 115 deleted lines with **no new
logic line**, generated by slicing the file rather than retyping it. Its two run-level
equivalence arms are complementary, not redundant: the real-graph arm runs on a copy with the
indicator axis **stripped** (remove `StandardIndicator` nodes + the 4 axis edge labels, remap
the array indices) because the live graph is already patched and every stats counter sits
behind `if gp.add_edge(...)` — without stripping it compares two empty reports; and the
synthetic arm is the only one that reaches the `Penalty` fine branch, since all four live
`Penalty` nodes carry `amount == 0` and take the self-reported-zero `continue`.
`step03b` is the fourth migrated stage (`esg_kg/graph/anchor_kpi.py`, 2026-07-27), diff
17 added / 20 deleted with **no logic line changed**. It came with **`core/identity.py`**
(`parse_source_id` <- step03b, `get_stable_entity_id`/`PROVENANCE_CLASSES` <- step02):
`parse_source_id` was DEFINED in step03b and imported by `step05b:51`, so moving the stage
without lifting it would have left the migrated 05b importing from a sibling stage — the
same knot `core/graph_patch.py` untied a day earlier. Its arms live in a separate
`test/test_esg_kg_anchor_kpi.py` (the equivalence file is past 1,100 lines) and the
**first draft of them was vacuous**: the live `all_validated_triples.json` is already
patched (95 of its 306 `observedAtFacility` edges carry `anchor_method=offline_gazetteer`),
so a re-run emits nothing and the arm compared two empty results while printing PASS. This
is now a known law for every in-place-patch stage, with two confirmed cases — strip the
stage's OWN past output to rebuild the pre-patch input (`strip_axis` for 05c,
`strip_anchors` for 03b), stripping by provenance and never by edge label (the other 211
`observedAtFacility` edges came from extraction and must stay). See `src_module/PIPELINE.md` §3.
`step05b` is the fifth migrated stage (`esg_kg/resolve/provenance.py`, 2026-07-27), diff
18 added / 8 deleted — docstring and imports only, **no logic line changed**. It is the
first stage to move **without extracting any new `core/` module**: the step03b slice had
already lifted all four symbols it needs. Its arms are in `test/test_esg_kg_provenance.py`.
**It also corrected the in-place-patch law above, so read that law with this caveat**: the
right question is not "does the stage patch in place" but **"when it meets its own past
output, does it `continue` or recompute?"** 05c/03b skip, so their naive arms went vacuous;
step05b's only skip is `provenance_method == "extraction"` (zero nodes today — it is for
post-re-extraction step02 output), so it re-matches and re-stamps everything and the live-graph
arm really does compare 6,258 stamps. `strip_provenance` is still written, but to prove a
stronger property: none of the keys 05b writes appears in any `PROVENANCE_CLASSES`
`identity_keys`, so `get_stable_entity_id` cannot see them and **the stage never reads its own
output** — if that broke, the graph would drift on every re-run with no other signal.
`step05d` is still blocked on `core/llm.py` (`step05d:35`
imports `_OpenAIProvider`/`RateLimiter` from step07), NOT on `GraphPatch` any more —
and `core/llm.py` is the biggest single unlock, freeing `step03`, `step05`, `step07`
and `step05d` at once. `step04`/`step06`/`step09` are also symbol-eligible, but 06/09
read Neo4j so their arms cannot run offline (DESIGN.md §4 step 3 defers them).
**`step07b` is deliberately NOT being ported** (DESIGN.md §4.1): the delivered surface is
the `frontend/`+`api/` UI, which never reads its softmax scores, so `pipeline.py` carries
it as `new_module=None` and `run.py --list` shows `(not ported)` and drops it from the
denominator. It is NOT deleted — `src/step07b_enrich_dossiers.py` still runs, and both
consumers tolerate the scores being absent (step08 sets null, step09 skips the block). After
the planned re-extraction the new dossiers start without scores; run that script by hand if
you want them back — that is not a reason to port it.
Known debt: `src/step00_graph_quality_report.py` still exists, so the T1/T2/T3 tier map that
`test/test_schema_contract.py` imports lives in two trees — cleanup commit spelled out in
`src_module/esg_kg/DESIGN.md` §6.1.

Corrections to DESIGN.md found by review, not yet folded into it:
- The two `node_text` are **NOT duplicates** — `step05d:63` takes a *properties dict*,
  `step07:133` takes a *node* and class-dispatches. Both move; keep separate names.
  Merging them silently rewrites step07's paid LLM prompt.
- `GraphPatch` / `temporal_md` (step05c) are shared but have **no home in the `core/` layout** —
  this blocks step05d.
- `step05d`, `step08`, `step10` are listed as safe "leaf" moves but are not: they import
  from step05c/step07. `step10_evaluate.py:367` hides a lazy `from step07… import Adjudicator`
  inside a `try` — it fails *silently* if broken.

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
src/step03c_canonicalize_kpis.py        → appends/patches all_validated_triples.json (+ kpi_canonical_stats.json)
   (offline, NO LLM: assigns each KPIObservation a canonical `kpi_id` from the 35-indicator
    vocabulary via config/kpi_type_aliases.json + rapidfuzz on official names, writing a NEW
    property (NEVER rewrites `kpi_type`, which is in identity_keys — so node order is preserved
    and paid step07 dossiers survive). Also unit_normalized/value_normalized/period and a
    Goal.target_date regex backfill (future years only). Feeds the indicator axis, docs/
    STANDARD_INDICATOR_AXIS.md §5.2. Run after step03b, before step04. Precision over recall:
    financial KPIs in VND are rejected, not force-mapped)
src/step04_build_issuer_registry.py     → config/issuer_registry.json                       (run-once bootstrap)
   (drafts the reporting company's name variants → aliases / exclusions / needs_review;
    re-running preserves human edits, --force rebuilds; a human confirms needs_review)
config/standards_registry.json          — STATIC CONFIG, no longer a pipeline stage (2026-07-26)
   (the 5 reference documents behind the indicator vocabulary (TT96, QĐ2171, QCVN09, SSC-IFC,
    GRI) with their aliases/exclusions + `match_patterns`/`exclude_hints`. step05's standards
    anchor freezes GRI's ≥4 spellings and TT96 VN/EN onto one canonical node each (diagnosis C3).
    Hand-edited: add an alias, then re-run step05. NOTHING generates it — step00's
    `standards_registry_audit` reports uncovered mentions instead, which is all the old
    generator ever produced. `src/step04b_build_standards_registry.py` still exists as the
    from-scratch reseed tool, but it is OFF the run order: it read step05's output while
    step05 read its output. See DESIGN.md §4.2)
src/step05_resolve_entities.py          → graph_output/resolved/resolved_graph.json (+ _stats.json)
   (step 4: collapse duplicate entity nodes into canonical entities, keeping temporal history.
    Stage A deterministic identity_keys merge + FROZEN issuer anchor (issuer_registry.json) +
    FROZEN standards anchor (Stage A.3, standards_registry.json — Standard/Regulation mentions);
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
src/step05c_link_standard_indicators.py → patches resolved_graph.json in place (+ indicator_axis_stats.json)
   (offline, NO LLM: materializes the TT96/GRI indicator axis. APPENDS ~35 StandardIndicator
    nodes + edges: partOf (indicator→document), measuredUnder (KPIObservation/Emission→indicator,
    read from step03c's kpi_id — never guessed here), equivalentTo (TT96→GRI, from
    config/standard_crosswalk.json, confirmed rows only), and a keyword tier of alignsWithIndicator
    (Claim/Goal/Initiative→indicator; longest matching phrase wins). Penalty amount==0 = self-reported
    "fined 0 times" → flagged self_reported_zero, NO conduct edge. APPEND-ONLY (asserts the
    existing node/edge prefix is untouched — dossiers stay valid). Also RESTAMPS
    StandardIndicator.pillar from the file entitled to say — kpi_definitions_construction.json
    for the VN vocabulary, config/gri_catalog.json (--gri-catalog) for GRI — and never invents
    one: an id neither covers keeps the pillar it had. The Evidence View reads that property
    directly for a claim's E/S/G column, so a guess there is visible to the reader. Run after
    step05b, before step06. See docs/STANDARD_INDICATOR_AXIS.md)
src/step05d_align_claims_to_indicators.py → patches resolved_graph.json in place (+ indicator_align_llm_stats.json)
   (OPTIONAL, LLM, budgeted: alignsWithIndicator for the Claim/Goal/Initiative the keyword tier
    left unresolved. Topic classification only (alignment_method=llm), NOT a supports/contradicts
    judgement. Pipeline is complete without it. Run after step05c; --max-llm-pairs, --dry-run)
src/step06_load_graph_to_neo4j.py       → Neo4j (bolt://localhost:8687, db `neo4j`)            (step 5)
   (load the resolved {nodes,edges} graph as a property graph — NO LLM. Nodes keyed by
    array index (entities already resolved; not re-deduped); edges keep temporal_metadata and
    MERGE on a temporal _edge_key so multi-year edges stay distinct; temporal_versions become
    supersedes version-node chains for supersedes-legal classes, else a JSON property)
src/step07_crosscheck_claims_vs_conduct.py → graph_output/crosscheck/<ticker>_claim_assessments.json   (step 6)
   (the analytical core: for each SustainabilityClaim, retrieve conduct-side candidates →
    LLM-adjudicate supports/contradicts/irrelevant → write verifiedBy / contradictedBy* edges.
    LLM adjudication is MANDATORY (no deterministic fallback) — multi-provider cascade
    (--provider-order, default `openai` = gpt-4o-mini while Gemini is billing-blocked;
    `gemini,openai` puts gemini-2.5-flash first); aborts up front if no provider is
    available. Self-verification guard drops company-own-domain "verify" edges.
    Emits advisory dossiers — NO greenwashing score/label. --dry-run / --to-neo4j)
src/step07b_enrich_dossiers.py          → patches the step07 dossiers in place (idempotent)     (step 6c)
   (offline, NO LLM/DB: softmax over three evidence-balance components → assessment_scores
    {contradicted, supported, abstain} + score_components + score_disagrees_with_assessment,
    written back into <ticker>_claim_assessments.json. This is NOT a greenwashing
    probability (SYSTEM_DESIGN §1.1 — no ground truth); the categorical `assessment` stays
    the primary output. Deterministic over the frozen dossier, so it never needs the paid
    step07 re-run. The `signals` terms (lam_struct/lam_kpi/lam_bp) contribute 0 until the
    generator in docs/CROSSCHECK_EXPANSION.md lands — safe to run today. Consumed by
    step08 + step09. Read docs/SOFTMAX_SCORING.md before touching the formula; beta0 is a
    design decision, not a fitted parameter. --dry-run, --calibrate, --bin-confidence, --params)
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
python src/step03c_canonicalize_kpis.py --dry-run                            # assign canonical kpi_id (then run without --dry-run; offline, no LLM)
python src/step04_build_issuer_registry.py                                   # → config/issuer_registry.json (run-once; then hand-confirm needs_review)
#   (no step04b: config/standards_registry.json is static config, hand-edited; step00 audits its coverage)
python src/step05_resolve_entities.py                                        # → graph_output/resolved/ (step 4: entity resolution + standards anchor)
python src/step05b_stamp_provenance.py --dry-run                             # provenance patch preview (then run without --dry-run; offline, no LLM)
python gri/build_gri_catalog.py                                              # → config/gri_catalog.json (run-once builder, not a stage; commit the result)
python src/step05c_link_standard_indicators.py --dry-run                     # TT96/GRI indicator axis preview (reports the pillar restamp too; then run without --dry-run)
python src/step05d_align_claims_to_indicators.py --dry-run                   # OPTIONAL LLM: align remaining claims (then --max-llm-pairs N to run)
python src/step06_load_graph_to_neo4j.py --dry-run                           # step 5: preview planned counts, no DB
docker compose up -d                                                 # start Neo4j on :8687 (then run neo4j/init.cypher once — see docs)
python src/step06_load_graph_to_neo4j.py --clear                            # → Neo4j (wipe + load; needs the instance running)
python src/step07_crosscheck_claims_vs_conduct.py --dry-run                 # step 6: preview claim↔conduct pairs (runs LLM, writes nothing)
python src/step07_crosscheck_claims_vs_conduct.py                           # → graph_output/crosscheck/ (advisory dossiers + linking edges)
python src/step07b_enrich_dossiers.py --dry-run                            # step 6c: softmax evidence-balance scores (then run without --dry-run; offline, no LLM)
python src/step08_sync_crosscheck_to_neo4j.py                              # step 6b: push dossiers into Neo4j advisory layer (no LLM)
python src/step09_report_claim_ledger.py                                   # step 7: render the AAA claim ledger FROM Neo4j (no LLM)
python src/step09_report_claim_ledger.py --review-queue --markdown         #   contradiction-no-verification queue + Markdown file
python src/step10_evaluate.py                                              # step 8 / P6: full Vietnamese evaluation report
python src/step10_evaluate.py --ablation --no-llm                          #   free arms only (coverage/case studies/ablation are offline)

# Refactor target (src_module/esg_kg) — step00 + step03b + step03c + step05b + step05c have moved so far
python src_module/run.py --list                                            # stages + which are migrated
python src_module/run.py quality --label baseline                          # == src/step00_graph_quality_report.py
python src_module/run.py canonicalize --dry-run                            # == src/step03c_canonicalize_kpis.py
python src_module/run.py anchor_kpi --dry-run                              # == src/step03b_anchor_kpi_facilities.py
python src_module/run.py provenance --dry-run                              # == src/step05b_stamp_provenance.py
python src_module/run.py indicators --dry-run                              # == src/step05c_link_standard_indicators.py

# ESG Evidence View UI (web front-end; reads the Neo4j advisory layer, no LLM — see docs/ESG_EVIDENCE_VIEW.md)
python api/main.py                                                         # 3-column TT96/GRI evidence view at http://localhost:8000

# Useful src/ flags: --doc <substr>, --limit-docs N, --all (scope);
#   --all-pages (don't restrict to ESG pages); --dry-run (fix/resolve/load steps: offline only, no LLM/DB/writes);
#   quality (step00): --label <name>, --skip-slow (skip the BFS-heavy Q7(c)/(d)), --max-hops, --standards-registry;
#   fix (step03): --renormalize (P4 pass only); anchor patch (step03b): --max-per-facility, --dry-run;
#   kpi canonical (step03c): --aliases, --fuzzy-threshold, --no-goals, --dry-run;
#   provenance patch (step05b): --graphs-dir, --news-globs, --stats-out, --dry-run;
#   indicator axis (step05c): --crosswalk, --no-gri, --no-align, --trust-draft-crosswalk, --dry-run;
#   claim→indicator LLM (step05d): --max-llm-pairs, --openai-model, --dry-run;
#   resolve: --no-llm (Stages A+B.1 only), --standards-registry, --similarity-threshold, --max-llm-pairs;
#   load: --clear (wipe first), --no-versions (canonical only), --database, --strict (env: NEO4J_URI/USER/PASSWORD);
#   crosscheck: LLM adjudication is mandatory (no --no-llm); --max-llm-pairs, --provider-order (default openai), --to-neo4j;
#   softmax scores (step07b): --dry-run, --calibrate (grid over tau/beta1/w_max), --bin-confidence, --params '{"tau":0.75}';
#   sync (step08_sync_crosscheck_to_neo4j.py): --clear-advisory, --dry-run;
#   ledger (step09_report_claim_ledger.py, Neo4j-only): --review-queue, --assessment, --claim-id, --limit, --markdown;
#   evaluate (step10_evaluate.py): --coverage, --case-studies, --ablation, --no-llm (only the 30-case arm costs money)
```

No pytest harness or linter is configured — tests are plain assert scripts under `test/`
(see the TDD working rule above; new code adds new files here, test-first). The existing
check covers the P3/P4 Phase-0 temporal logic, the step05b provenance matching, and the
indicator-axis stages (step03c/step05c/step08) — run it from the repo root after touching
step03/step03b/step03c/step05/step05b/step05c/step08:

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
python test/test_standards_audit.py        # step00's standards-registry audit, in BOTH trees:
                                           # an uncurated GRI spelling surfaces, an out-of-scope
                                           # accounting standard does NOT (the noise filter that
                                           # makes the section readable), a curated exclusion
                                           # stays closed, and canonical_name is never reported
                                           # as unknown (step04b's old feedback artifact).
                                           # Run after touching step00 or the registry config.
python test/test_pipeline_table.py         # refactor stage table (src_module/esg_kg/pipeline.py
                                           # + run.py): every row points at a real src/ file,
                                           # short names don't collide, and a stage that is
                                           # NEVER being ported is rendered as such instead of
                                           # as "not yet" (which would keep dead work queued).
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
python test/test_data_sync_scope.py        # data_sync pull is scoped to the three synced folders,
                                           # so it can never overwrite a tracked repo-root file
                                           # (that is how the Hub's .gitattributes got committed).
                                           # Offline: snapshot_download is replaced by a recorder.
python test/test_esg_kg_equivalence.py     # refactor safety net: imports BOTH src/ and
                                           # src_module/esg_kg, runs them on the real
                                           # schema/corpus, asserts equal. Run after ANY
                                           # edit to a src/ helper that has a core/ twin,
                                           # or to step00 (whose whole Q1-Q8 surface is
                                           # compared against esg_kg/report/quality.py —
                                           # real graph with --skip-slow, plus a synthetic
                                           # 20-node graph for the 44s Q7 BFS arms).
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
`SOFTMAX_SCORING.md` (step 6c — the evidence-balance formula, its parameters, and why it
is explicitly not a greenwashing probability; read before changing step07b),
`ESG_EVIDENCE_VIEW.md` (the 3-column TT96/GRI evidence-view UI, `api/` + `frontend/` — how to run the demo),
`REAL_DATA_INTEGRATION_GUIDE.md` (Vietnamese — the mock→live-Neo4j swap for that UI; the
rule that only `api/evidence_service.py` changes, never the frontend),
`EVALUATION.md` (step 8 / P6 — why evaluation measures the linking machinery, not
greenwashing accuracy; the four methods and their costs),
`ENTITY_RESOLUTION_IMPROVEMENT.md` (Vietnamese — proposal to use graph structural
signatures to auto-resolve step-4's lexically ambiguous `needs_review` cases),
`KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`, `VIETNAM_IMPROVEMENT_PLAN.md`,
`NEWS_CRAWLER_OPTIMIZATION.md` (Vietnamese — architecture of the standalone, FPT-specific
`crawl_data/crawler_news.py`, not the documented `esg_news_crawler/` pipeline). The root
`ENTITY_RESOLUTION_PLAN.md` is the step-4 engineering checklist. `README.md` (root),
`esg_news_crawler/README.md`, `kpi_build/README.md`, and `gri/README.md` cover their
respective subsystems.

Added with the GRI catalog (2026-07-26), describing the `src/` pipeline as it runs today —
none of them mention `src_module/`/`esg_kg`, so for the refactor's view of stage C read
`src_module/PIPELINE.md` instead: `docs/PIPELINE_DIAGRAMS.md` (10 figures: architecture,
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
