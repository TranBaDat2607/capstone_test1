# Documentation index

A Graph-RAG pipeline for surfacing greenwashing **evidence** about Vietnamese listed
companies (Construction / Building Materials / Real Estate). Reports supply the *claims*,
independent news supplies the *conduct*, and both live in one temporal knowledge graph so a
claim can be cross-checked against what the company actually did.

Every document here describes code that exists. Unbuilt work lives in one place:
[ROADMAP.md](ROADMAP.md).

---

## Start here

| If you are… | Read |
|---|---|
| New to the project | [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md), then [PIPELINE_DIAGRAMS.md](PIPELINE_DIAGRAMS.md) |
| Setting up a machine | The root [`README.md`](../README.md), then [DATA_SYNC.md](DATA_SYNC.md) |
| About to change a stage | The stage's doc below, plus [TESTING.md](TESTING.md) |
| About to change the schema | [SCHEMA_EXPLAINED.md](SCHEMA_EXPLAINED.md) and [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) — in that order, before touching the file |
| Reviewing the method | [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §1.1 and §10, [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) §4 |
| Running the demo | [ESG_EVIDENCE_VIEW.md](ESG_EVIDENCE_VIEW.md) |

---

## Architecture

| Document | Contents |
|---|---|
| [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) | The end-to-end design: the two-channel claim/conduct model, the no-ground-truth constraint that shapes everything, the cross-check, and the output surfaces |
| [PIPELINE_DIAGRAMS.md](PIPELINE_DIAGRAMS.md) | Eleven diagrams: system context, both ingestion channels, the 16 stages, why blocks exist, entity resolution, the indicator axis, the cross-check, schema tiers, data layout, end-to-end sequence |

## Contracts — read before editing

| Document | Contents |
|---|---|
| [SCHEMA_EXPLAINED.md](SCHEMA_EXPLAINED.md) | `config/schema.json`: 28 node classes, 48 edge labels over 76 legal pairs, identity keys, temporal fields, and how to change it safely |
| [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) | The three-tier node model (§2), the eight design principles P1–P8 (§3), and the Q1–Q8 quality attributes plus R1/R5/R7 that stage 00 measures (§4) |
| [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) | The TT96/GRI indicator layer: the join point that lets a claim and its measurements find each other |

## Stages

Run everything as `python src/run.py <stage>` from the repo root; `--list` prints the live
table.

| Stage | Id | Document |
|---|---|---|
| `quality` | 00 | [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) §4 |
| `extract` | 01 | [KPI_EXTRACTION_FROM_JSONL.md](KPI_EXTRACTION_FROM_JSONL.md) |
| `extract_triples` | 02 | [TRIPLET_EXTRACTION_FROM_JSONL.md](TRIPLET_EXTRACTION_FROM_JSONL.md) |
| `fix_triples` · `anchor_kpi` · `canonicalize` · **`build_validated`** | 03 / 03b / 03c | [TRIPLET_VALIDATION.md](TRIPLET_VALIDATION.md) |
| `issuer` · `entities` · **`build_resolved`** | 04 / 05 | [ENTITY_RESOLUTION.md](ENTITY_RESOLUTION.md) |
| `provenance` | 05b | [PROVENANCE_PATCH.md](PROVENANCE_PATCH.md) |
| `indicators` · `align_claims` | 05c / 05d | [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) |
| `neo4j_load` | 06 | [GRAPH_LOAD_NEO4J.md](GRAPH_LOAD_NEO4J.md) |
| `claims_vs_conduct` | 07 | [CLAIM_CONDUCT_CROSSCHECK.md](CLAIM_CONDUCT_CROSSCHECK.md) |
| `neo4j_sync` · `claim_ledger` | 08 / 09 | [CLAIM_LEDGER.md](CLAIM_LEDGER.md) |
| `export_kgc` | 11 | [EXPORT_KGC.md](EXPORT_KGC.md) |

## Subsystems

| Document | Contents |
|---|---|
| [NEWS_INGESTION.md](NEWS_INGESTION.md) | The conduct channel: crawler design, retrieval strategy, why `coverage.csv` is a deliverable, date normalization, and the legacy standalone crawler |
| [ESG_EVIDENCE_VIEW.md](ESG_EVIDENCE_VIEW.md) | The three-column TT96/GRI demo UI, its endpoints, and where the E/S/G pillar comes from |
| [LLM_PROVIDERS_AND_CACHING.md](LLM_PROVIDERS_AND_CACHING.md) | Gemini / DeepSeek / OpenAI, the provider factory, rate limiting, and the two different caches |
| [DATA_SYNC.md](DATA_SYNC.md) | Distributing generated data via a Hugging Face dataset repo, and the pin that keeps data and code in step |
| [TESTING.md](TESTING.md) | The test-first working rule, the 38 checks, and how paid stages are covered for free |

## Reference vocabularies

| Document | Contents |
|---|---|
| [KPI_DEFINITIONS_CONSTRUCTION_BUILD.md](KPI_DEFINITIONS_CONSTRUCTION_BUILD.md) | The 35 Vietnamese indicators, their legal sources, and the run-once builder |
| [GRI_SCHEMA_DOCUMENTATION.md](GRI_SCHEMA_DOCUMENTATION.md) | The 136 GRI codes, the ownership rule that decides which standard owns a disclosure, and the crosswalk |

## Future work

| Document | Contents |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Open items with evidence, and the rejected ideas with their reasons — including why there is no trained greenwashing classifier |
| [SSRL_REASONING_LAYER.md](SSRL_REASONING_LAYER.md) | The path-reasoning layer: why the graph was a star, what was measured, which proposed benefits turned out to be fake, and the quantitative gate for deciding whether to build it |

---

## Documents outside `docs/`

| Path | Contents |
|---|---|
| [`README.md`](../README.md) | Repository overview, layout, onboarding, quick start |
| `CLAUDE.md` | Working rules and conventions for this codebase |
| `src/PIPELINE.md` | Canonical stage run order |
| `src/esg_kg/DESIGN.md` | The refactor record and its design decisions |
| `esg_news_crawler/README.md`, `kpi_build/README.md`, `gri/README.md` | Package-level usage |
| `neo4j/crosscheck_queries.cypher` | Analyst queries |

## Referenced but absent

Several source files cite documents that are not in this repository:
`GRAPH_IMPROVEMENT_PLAN.md`, `SOFTMAX_SCORING.md`, `EVALUATION.md`. The first describes
work that is partly built and partly unbuilt — see [ROADMAP.md](ROADMAP.md) §1. The other
two belong to stages that were **removed from the project**; they are dead references, not
pending features. Full list in [ROADMAP.md](ROADMAP.md) §4.
