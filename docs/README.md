# Documentation index

Every document in `docs/`, classified by **what it is**, because that is the thing most
easily got wrong here: some of these describe code that exists, some describe code that was
deleted, and some describe code that was never built. Reading a proposal as a description of
the system is the single most common mistake made in this repository.

Many documents are written in **Vietnamese** (marked 🇻🇳 below); some are bilingual. This
reflects how the project was written and has not been retrofitted into English.

## Read these before changing anything

| Document | Why |
| --- | --- |
| [`SYSTEM_DESIGN.md`](SYSTEM_DESIGN.md) | The end-to-end design. Start here: reports are the *claim* side, independent news the *conduct* side, both land in one temporal knowledge graph, and the system deliberately emits evidence rather than a greenwashing score. |
| [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md) | Closed decisions: the `src/` → `esg_kg` refactor, stages removed outright, the LLM-provider timeline. Read before reopening one. |
| [`EVALUATION_BASELINE.md`](EVALUATION_BASELINE.md) | The **frozen** measurement snapshot. It wins over whatever is currently on disk. Read before quoting any figure. |
| [`TEMPORAL_KG_DESIGN.md`](TEMPORAL_KG_DESIGN.md) 🇻🇳 | The 8 temporal-KG principles (P1–P8) and the Q1–Q8 quality attributes. Read before touching the schema, the step02 prompts, step03 or step05. |
| [`../test/README.md`](../test/README.md) | Per-file test catalogue and re-run triggers. |

## Current — these describe code that exists

| Document | Covers |
| --- | --- |
| [`SCHEMA_EXPLAINED.md`](SCHEMA_EXPLAINED.md) | `config/schema.json`: the node classes, edge labels and identity keys, and why. |
| [`KPI_EXTRACTION_FROM_JSONL.md`](KPI_EXTRACTION_FROM_JSONL.md) 🇻🇳 | `extract` (step01) — typed KPI observations from report pages. |
| [`TRIPLET_EXTRACTION_FROM_JSONL.md`](TRIPLET_EXTRACTION_FROM_JSONL.md) | `extract_triples` (step02) — page → temporal triples, report and news modes. |
| [`TRIPLET_VALIDATION.md`](TRIPLET_VALIDATION.md) | `fix_triples` (step03) — schema validation, direction repair, date canonicalization. |
| [`STANDARD_INDICATOR_AXIS.md`](STANDARD_INDICATOR_AXIS.md) 🇻🇳 | `canonicalize` (03c) and `indicators` (05c) — the TT96/GRI indicator axis. |
| [`ENTITY_RESOLUTION.md`](ENTITY_RESOLUTION.md) | `issuer` (step04) and `entities` (step05) — why this is a redesign, not a port. |
| [`PROVENANCE_PATCH.md`](PROVENANCE_PATCH.md) | `provenance` (05b) — offline `source_doc`/`source_page` stamping. |
| [`GRAPH_LOAD_NEO4J.md`](GRAPH_LOAD_NEO4J.md) | `neo4j_load` (step06) — the property-graph load. |
| [`CLAIM_CONDUCT_CROSSCHECK.md`](CLAIM_CONDUCT_CROSSCHECK.md) | `claims_vs_conduct` (step07) — the analytical core. |
| [`CLAIM_LEDGER.md`](CLAIM_LEDGER.md) | `neo4j_sync` (step08), `claim_ledger` (step09) and the analyst Cypher. |
| [`ESG_EVIDENCE_VIEW.md`](ESG_EVIDENCE_VIEW.md) 🇻🇳 | The 3-column TT96/GRI evidence-view UI (`api/` + `frontend/`). |
| [`REAL_DATA_INTEGRATION_GUIDE.md`](REAL_DATA_INTEGRATION_GUIDE.md) 🇻🇳 | The mock → live-Neo4j swap for that UI; only `api/evidence_service.py` changes. |
| [`KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`](KPI_DEFINITIONS_CONSTRUCTION_BUILD.md) 🇻🇳 | How `kpi_definitions_construction.json` was built from the Vietnamese regulations. |
| [`GRI_SCHEMA_DOCUMENTATION.md`](GRI_SCHEMA_DOCUMENTATION.md) 🇻🇳 | The shape of `gri/full_gri/json/*.json` and `config/gri_catalog.json`. |
| [`LABELING_STRATEGY.md`](LABELING_STRATEGY.md) 🇻🇳 | The labelling strategy and the `config/subsidiaries/` registries. |
| [`NEWS_CRAWLER_OPTIMIZATION.md`](NEWS_CRAWLER_OPTIMIZATION.md) 🇻🇳 | The **standalone, FPT-specific** `crawl_data/crawler_news.py` — *not* the documented `esg_news_crawler/` pipeline. |

## Frozen records — measured output, not plans

| Document | Contains |
| --- | --- |
| [`EVALUATION_BASELINE.md`](EVALUATION_BASELINE.md) | The 2026-08-08 snapshot plus its dated addendum. Never silently replaced with a fresher run. |
| [`ANNOTATION_RESULTS.md`](ANNOTATION_RESULTS.md) 🇻🇳 | Measured inter-annotator agreement (kappa = 0.714) and adjudicator precision for that round. |
| [`ANNOTATION_GUIDELINE.md`](ANNOTATION_GUIDELINE.md) 🇻🇳 | The frozen labelling guideline. **Must not be edited** once labelling has begun — editing invalidates every comparison; bump to v1.1 and re-label instead. |
| [`PROJECT_HISTORY.md`](PROJECT_HISTORY.md) | The refactor, the removed stages, the provider timeline. |

## Diagrams and overviews

[`PIPELINE_DIAGRAMS.md`](PIPELINE_DIAGRAMS.md), [`PIPELINE_UNIFIED.md`](PIPELINE_UNIFIED.md),
[`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) 🇻🇳. These predate the refactor, so the pipeline
*shape* is accurate but stage names may be historical — `src/PIPELINE.md` and
`src/esg_kg/pipeline.py` are authoritative for current names.

## [`proposals/`](proposals/) — NOT implementations

**Nothing in this folder describes code that exists.** They are design proposals, evaluation
methodology, and internal review notes. Do not read them as descriptions of the system.

| Document | What it is |
| --- | --- |
| [`proposals/CROSSCHECK_EXPANSION.md`](proposals/CROSSCHECK_EXPANSION.md) 🇻🇳 | Proposed `signals` generator and graph-routed evidence retrieval. Its §D1 finding — that `kpi_gap`/`structural_contradiction` are *ghost* signals step07 never writes — is real and worth knowing. |
| [`proposals/BERT_NER_GRAPH_QUALITY.md`](proposals/BERT_NER_GRAPH_QUALITY.md) 🇻🇳 | Proposal to replace `gemini-embedding-001` with local CPU embeddings and to use NER for news anchoring. Explicitly rejects fine-tuning a greenwashing classifier, since no labels exist. |
| [`proposals/EVALUATION_WITHOUT_LABELS.md`](proposals/EVALUATION_WITHOUT_LABELS.md) 🇻🇳 | How to evaluate ONE system with no ground truth. Its §8 lists metrics already tried and found dead — read it before proposing a new one. |
| [`proposals/AGENT_AB_EVALUATION.md`](proposals/AGENT_AB_EVALUATION.md) 🇻🇳 | Paired McNemar design for comparing TWO systems, guarded by a negative control. Its "`claim_id` is not yet deterministic" caveat is **out of date** — that landed. |
| [`proposals/ENTITY_RESOLUTION_IMPROVEMENT.md`](proposals/ENTITY_RESOLUTION_IMPROVEMENT.md) 🇻🇳 | Proposal to auto-resolve step04's ambiguous `needs_review` cases via graph structural signatures. |
| [`proposals/VIETNAM_IMPROVEMENT_PLAN.md`](proposals/VIETNAM_IMPROVEMENT_PLAN.md) | Vietnam-specific improvement proposals. |
| [`proposals/thesis_review.md`](proposals/thesis_review.md) | Internal review log against numbered issues. Working notes, not reader-facing documentation. |

## Referenced but no longer present

Some documents were deleted and are still cited. They are recoverable, and the citations say
how — e.g. `git show a64aeb5^:docs/EVALUATION.md`. Affected:
`EVALUATION.md`, `SOFTMAX_SCORING.md`, `SSRL_REASONING_LAYER.md` (the path-reasoning layer,
steps 11–13, is **unbuilt**), the root `ENTITY_RESOLUTION_PLAN.md`, and
`GRAPH_IMPROVEMENT_PLAN.md` (whose section labels several tests still cite as their spec —
`PROJECT_HISTORY.md` §4 maps each label to what it became).
