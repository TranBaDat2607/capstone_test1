# System design — greenwashing evidence for Vietnamese listed companies

**Audience:** anyone who needs the whole picture — reviewers, new team members, and
anyone about to change a pipeline stage. Read this first; the per-stage docs assume it.

**Scope:** Construction / Building Materials / Real Estate companies listed in Vietnam.
Everything here describes code that exists. Proposed work lives in
[ROADMAP.md](ROADMAP.md); nothing in this file is aspirational.

Section numbers §1.1, §6, §6.4, §8.3 and §9 are referenced from source-code docstrings —
keep them stable when editing.

---

## 1. Purpose & problem statement

The system helps an analyst answer one question about a listed company:

> *Do the company's **reported** ESG claims hold up against **independent evidence** of
> what it actually did?*

It ingests the company's **own ESG reporting** (annual / sustainability reports) and
**third-party news** about the company, and represents both inside **one temporal
knowledge graph**. Because both live in the same graph, keyed to the same company and the
same time axis, a claim can be structurally compared against the conduct evidence
surrounding it.

### 1.1 The hard constraint that shapes everything: no ground truth

**No labeled greenwashing dataset exists for Vietnamese companies.** There is no gold
`greenwashing / not_greenwashing` annotation to train on or measure against. This is a
load-bearing constraint, not a caveat:

- The system is **not a classifier** and does **not** emit a greenwashing score. A number
  or a hard label would imply a ground truth that does not exist.
- For each claim it produces **(a) the evidence** — supporting and contradicting graph
  nodes with full provenance — and **(b) an explicitly advisory LLM assessment**:
  `appears_supported`, `appears_contradicted`, or `unverified_insufficient_evidence`,
  always with a rationale and caveats.
- The judgment is a **human's**. This is decision support: it surfaces and organizes
  evidence and offers an opinion; it does not adjudicate.

Throughout this repository, "detection" means *evidence surfacing plus an advisory
opinion*, never a verdict.

This constraint also explains three things that were built and then **removed**: a
no-ground-truth evaluation report, a softmax "evidence balance" score, and any notion of
a trained greenwashing classifier. See [ROADMAP.md](ROADMAP.md) §3.

### 1.2 What the evidence looks like

A real AAA example:

- **Claim side (report):** AAA presents itself as *"tiên phong sản phẩm nhựa thân thiện
  môi trường"* (pioneer in environmentally friendly plastics) — an Environmental
  `SustainabilityClaim`.
- **Conduct side (independent news):** *"Khai sai thuế, Nhựa An Phát Xanh bị xử lý hơn
  1,7 tỷ đồng"* (tax mis-declaration, penalized > 1.7 bn VND) — a Governance
  `Controversy` / `Penalty` from an independent outlet.

The system's job is to put both on the **one** AAA node, link the claim to the
contradicting evidence, and show an analyst the pair — **not** to declare AAA a
greenwasher.

---

## 2. Core idea, and how it differs from the reference implementation

The graph-construction stages port `EmeraldMind/src/EmeraldKG/` steps 1→3, then
deliberately redesign entity resolution (step 4) onward. The detection design is
**inverted** relative to the reference, and that inversion is the heart of the project.

| Aspect | Reference (`EmeraldKG`) | This project |
|---|---|---|
| What a "claim" is | An external CSV row | A `SustainabilityClaim` **node inside the KG**, extracted from the company's own reports |
| Where evidence lives | The KG (built from reports) is the corpus | The KG holds **both** claims (reports) and conduct (news), provenance-tagged |
| Detection mechanism | Embed external claim → retrieve from KG → LLM classify | **Intra-graph** claim ↔ conduct linking: retrieve candidate conduct nodes for a claim node, LLM-adjudicate, write `verifiedBy` / `contradictedBy*` edges |
| Supervision | Gold labels; reports accuracy / precision / recall | **No labels**; case studies, coverage reporting, manual link inspection |
| Output | A predicted label per claim | An **evidence dossier + advisory assessment** per claim; no label, no score |
| Independence of evidence | Weak — claims and KG are both company-authored | Explicit: reports = claims, news = conduct, plus a self-verification guard (§6.4) |

**Why symmetric.** Greenwashing is a gap between *saying* and *doing*. Keeping both sides
as nodes on the same company and the same timeline lets the gap be found by traversal and
tracked over time — which an external-query benchmark design cannot do. The schema was
built for exactly this (§4).

---

## 3. Data channels & provenance

Two ingestion channels feed the graph. Both normalize to the **same sentence-level
schema** (`source_pdf`, `page`, `sentence_index`, `text`, …) and both are ESG-classified
by the same ViDeBERTa-v3-ESG model, so from the KPI-extraction stage onward they share one
code path.

### 3.1 The two channels

| Channel | Source | Graph side | Node classes it produces |
|---|---|---|---|
| **R — Reports** | Annual / sustainability report PDFs | **Claim side** ("what they say") | `SustainabilityClaim`, reported `KPIObservation`, `Goal`, `Initiative`, `ScienceBasedTarget`, reported `Emission` / `Waste` |
| **N — News** | Third-party news via `esg_news_crawler` | **Conduct side** ("what they do") | `Controversy`, `MediaReport`, `Penalty`, **observed** `KPIObservation`, `ThirdPartyVerification` |

The canonical classifier outputs are the **full-sector** files —
`data/labeled/classified/all_sentences_classified.jsonl` (197 companies, 873,756
sentences, 303,723 `esg=true`) and
`data/labeled/news_labeled/all_news_sentences_classified.jsonl` (115 tickers, 174,256
sentences, 77,229 `esg=true`). An earlier AAA-only pilot batch under
`data/labeled/annual_labeled/` was superseded and removed from the dataset repo on
2026-08-02; if it appears on disk it is a stale leftover, not a second source.

**Locked decision: no ingestion-time routing.** All `esg=true` news goes to the conduct
side. There is no separate PR channel and no domain-policy config file. Company-owned PR
mostly *restates* the annual report, so routing it to the claim side would only duplicate
claims. The risk routing was meant to guard against — a company's own PR self-verifying
its claims — is handled where it actually matters, at cross-check time (§6.4).

### 3.2 Provenance tagging

Every node and edge carries a **`source_type` ∈ {`report`, `news`}** so "reported" and
"real-world" never blur once they share one graph. Alongside it:

| Field | Channel | Meaning |
|---|---|---|
| `source_id` / `source_pdf` | both | document / article id; `<source_pdf>_<page>_<sentence_index>` when parseable |
| `source_doc` / `source_page` | both | stamped by the provenance stage so the UI can cite a page |
| `article_title` / `article_url` / `source_domain` | news | stamped for news docs; `source_domain` drives the guard in §6.4 |
| `page`, `sentence_index` | both | sentence-level traceability back to the source |
| `date_uncertain` | news | `true` when the publish date had to stand in for the event date |

Sentence-level traceability is a hard requirement of the whole pipeline: every graph node
must trace back to the sentence it came from. See
[PROVENANCE_PATCH.md](PROVENANCE_PATCH.md).

---

## 4. Schema mapping

The graph schema (`config/schema.json`) is the single source of truth: **28 node classes**
and **48 distinct edge labels across 76 legal (source_class, target_class) pairs**. Full
rationale in [SCHEMA_EXPLAINED.md](SCHEMA_EXPLAINED.md); the temporal design principles
behind it are in [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md).

### 4.1 Claim side, conduct side, and the linking edges

```
                    ┌───────────── Organization (issuer) ─────────────┐
                    │                                                 │
     claims / setsGoal / reportsKPI                    subjectToPenalty / involvedIn
                    │                                                 │
                    ▼                                                 ▼
        SustainabilityClaim  ──verifiedBy──────────▶  ThirdPartyVerification
              │  Goal                                    KPIObservation (observed)
              │  Initiative      ──contradictedBy──▶  Controversy
              │                  ──contradictedByMedia▶ MediaReport / Penalty
              ▼
        StandardIndicator ◀──measuredUnder── KPIObservation
              (the join point, §4.3)
```

`verifiedBy` and `contradictedBy*` are the only edges the cross-check writes, and each is
stamped `llm_suggested=true` so an advisory link is never mistaken for an extracted fact.

### 4.2 Entity resolution treats both sides as one company

Report-side and news-side mentions of the same company must collapse to one node, or the
comparison never happens. That is what the issuer registry and the entity resolver do,
with the issuer cluster **frozen** — its identity never depends on an embedding or an LLM.
See [ENTITY_RESOLUTION.md](ENTITY_RESOLUTION.md).

### 4.3 The reference layer — the TT96/GRI indicator axis

A claim about an indicator and the KPIs measured under that indicator hang off one
`StandardIndicator` node, so the cross-check can relate the two sides by traversal rather
than by token overlap. The axis also supplies each claim's E/S/G pillar to the UI, read
from `StandardIndicator.pillar` rather than guessed. See
[STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md).

---

## 5. End-to-end pipeline

Three subsystems feed one graph, which feeds two presentation surfaces.

```
A. Reports ──▶ sentences ──▶ ESG labels ──▶ ESG records ─┐
                                                          ├──▶ C. esg_kg (16 stages) ──▶ Neo4j ──▶ ledger + UI
B. News    ──▶ articles  ──▶ ESG labels ──▶ preprocessed ─┘
```

Stage-by-stage detail, flags and artifacts: [PIPELINE_DIAGRAMS.md](PIPELINE_DIAGRAMS.md)
for the visual version, `src/PIPELINE.md` for run order, and the per-stage docs linked
below.

### 5.1 Ingestion (A and B)

| Command | Output |
|---|---|
| `python crawl_data/download_reports.py` | `data/raw/annual_report/` |
| `python -m data_processing.prepare_sentences` | `data/interim/sentences/*.jsonl` — every sentence, no ESG filter |
| ViDeBERTa-v3-ESG (`notebooks/kaggle_esg_classify.ipynb` on GPU) | `data/labeled/classified/` |
| `python -m data_processing.extract_esg` | `data/outputs/esg_extracted/` |
| `python -m esg_news_crawler.run --ticker AAA` | `data/outputs/news/<TICKER>.jsonl` + `coverage.csv` |
| `python -m data_processing.preprocess_news` | `data/interim/news_preprocessed/` — normalized dates, boilerplate dropped |

See [NEWS_INGESTION.md](NEWS_INGESTION.md) for the conduct channel.

### 5.2 Graph construction (C) — `python src/run.py <stage>`

All 16 stages live in `src/esg_kg/`; `python src/run.py --list` prints the live table.

| Stage | Id | LLM? | Output | Doc |
|---|---|---|---|---|
| `quality` | 00 | no | `graph_output/quality/` — Q1–Q8 + R1/R5/R7 | [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) §4 |
| `extract` | 01 | Gemini | `kpi_output/<doc>_kpis/page_NNN_kpis.json` | [KPI_EXTRACTION_FROM_JSONL.md](KPI_EXTRACTION_FROM_JSONL.md) |
| `extract_triples` | 02 | Gemini / DeepSeek | `graph_output/graphs/<doc>/page{N}.json` | [TRIPLET_EXTRACTION_FROM_JSONL.md](TRIPLET_EXTRACTION_FROM_JSONL.md) |
| `fix_triples` | 03 | Gemini (phase 2) | `graph_output/validated/all_validated_triples.json` | [TRIPLET_VALIDATION.md](TRIPLET_VALIDATION.md) |
| `anchor_kpi` | 03b | no | appends anchor edges | [TRIPLET_VALIDATION.md](TRIPLET_VALIDATION.md) |
| `canonicalize` | 03c | no | adds `kpi_id`, backfills `Goal.target_date` | [TRIPLET_VALIDATION.md](TRIPLET_VALIDATION.md) |
| **`build_validated`** | block | Gemini | 03 → 03b → 03c, writes the artifact **once** | [TRIPLET_VALIDATION.md](TRIPLET_VALIDATION.md) |
| `issuer` | 04 | no | `config/issuer_registry.json` (run-once, hand-confirmed) | [ENTITY_RESOLUTION.md](ENTITY_RESOLUTION.md) |
| `entities` | 05 | optional | `graph_output/resolved/resolved_graph.json` | [ENTITY_RESOLUTION.md](ENTITY_RESOLUTION.md) |
| `provenance` | 05b | no | stamps `source_doc` / `source_page` in place | [PROVENANCE_PATCH.md](PROVENANCE_PATCH.md) |
| `indicators` | 05c | no | appends the `StandardIndicator` axis | [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) |
| **`build_resolved`** | block | optional | 05 → 05b → 05c, writes the artifact **once** | [ENTITY_RESOLUTION.md](ENTITY_RESOLUTION.md) |
| `align_claims` | 05d | Gemini / DeepSeek | optional extra `alignsWithIndicator` edges | [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) §5.4 |
| `export_kgc` | 11 | no | `graph_output/export_kgc/` — a separate export view | [EXPORT_KGC.md](EXPORT_KGC.md) |
| `neo4j_load` | 06 | no | Neo4j base graph | [GRAPH_LOAD_NEO4J.md](GRAPH_LOAD_NEO4J.md) |
| `claims_vs_conduct` | 07 | **mandatory** | `graph_output/crosscheck/<ticker>_claim_assessments.json` | [CLAIM_CONDUCT_CROSSCHECK.md](CLAIM_CONDUCT_CROSSCHECK.md) |
| `neo4j_sync` | 08 | no | Neo4j advisory layer | [CLAIM_LEDGER.md](CLAIM_LEDGER.md) |
| `claim_ledger` | 09 | no | per-company ledger, read from Neo4j | [CLAIM_LEDGER.md](CLAIM_LEDGER.md) |

**Blocks.** Where several stages each read *and* write the same artifact, they are not
several stages — they are one. `build_validated` and `build_resolved` chain their members
in memory and write the artifact exactly once, because re-running the first member alone
silently destroys what the later ones added, including results that were paid for. Every
member stays individually runnable for diagnosis.

### 5.3 The `--source` mode on extraction

`extract_triples` runs one of two prompts against the same code path:

- `--source report` (default) — the claim-side prompt: `SustainabilityClaim`, `Goal`,
  `Initiative`, reported `KPIObservation`.
- `--source news` — the conduct-side prompt: `Controversy`, `MediaReport`, `Penalty`,
  observed `KPIObservation`, and a mandatory `date_uncertain` decision.

Every node and edge is stamped `source_type` accordingly. One extractor, two prompts, one
graph.

---

## 6. The cross-check stage — the analytical core

`claims_vs_conduct` (07) reads the resolved graph and, for every `SustainabilityClaim` on
the issuer, links the conduct evidence that bears on it, then emits an advisory dossier.
This is the stage where the whole design pays off, and the only stage where an LLM
verdict is mandatory.

### 6.1 Candidate retrieval

For each claim, build a candidate set from the issuer's conduct pool
(`Controversy`, `Penalty`, `MediaReport`, `KPIObservation`, `ThirdPartyVerification`) via
two deterministic tiers:

- **Token tier** — Vietnamese topic overlap of at least `--min-topic-overlap` shared
  segmented tokens (default 2; one shared token is too weak on Vietnamese text), then a
  temporal window: `--window-before` (default 1) and `--window-after` (default 50) years
  around the claim year. A claim can be contradicted by conduct contemporaneous with or
  after it, not by something years prior. Candidates whose date is *uncertain* are kept
  rather than dropped.
- **Indicator tier** — conduct joined to the claim through the indicator axis
  (`claim → StandardIndicator ← conduct`) is injected with a boosted score and **bypasses
  the token gate**, because a claim and its own measurement often share zero tokens
  (*"giảm phát thải"* versus *"12.450 tCO2e"*). This is what §4.3 exists for.

Ranked, capped at `--top-k` (default 8), and each pair records which tier found it.
Embedding-based ranking is available behind `--embed` but off by default. Known
limitation: neither tier routes through corporate structure, so a subsidiary's misconduct
never reaches the parent's claims — see [ROADMAP.md](ROADMAP.md) §2.2.

### 6.2 LLM adjudication — mandatory

Each (claim, candidate) pair goes to the model with a fixed system prompt and must come
back as one of `supports` / `contradicts` / `irrelevant`, with a confidence and a
rationale. There is **no deterministic fallback**: the run aborts up front if no provider
is available. Budget is controlled by `--max-llm-pairs` (default 300), not by silently
degrading to a keyword heuristic.

Provider choice is `--provider-order` (default `gemini`; `deepseek` is a swappable
alternative, not a required cascade). Verdicts are cached content-addressed on
(claim text, evidence text, evidence metadata), so a re-run is free and reproducible. See
[LLM_PROVIDERS_AND_CACHING.md](LLM_PROVIDERS_AND_CACHING.md).

### 6.3 Writing the linking edges

Schema-legal edges only:

| Verdict | Evidence class | Edge |
|---|---|---|
| supports | `ThirdPartyVerification`, `KPIObservation` | `verifiedBy` |
| contradicts | `Controversy` | `contradictedBy` |
| contradicts | `MediaReport`, `Penalty` | `contradictedByMedia` |

Each carries `llm_suggested=true`, the confidence, the rationale and the provider, so
every advisory link is attributable and re-runnable. Contradictions the schema cannot
express — notably `Claim → KPIObservation` — stay in the dossier and reach Neo4j through
the advisory layer instead (§9).

### 6.4 The self-verification guard

The one piece of independence logic in the pipeline, replacing the discarded
ingestion-time domain routing (§8.1). It exists because a company's own PR must not be
allowed to verify the company's own claims.

> **Rule.** When about to write a `verifiedBy` edge, if the evidence's `source_domain`
> belongs to the company's own sites, do not write it as independent verification. Keep it
> flagged instead, so it is visible but never counted toward `appears_supported`.

Why this is sufficient and cheap:

- **Contradiction is unaffected.** The guard touches support only. Company PR effectively
  never contradicts the company.
- **No maintained policy file.** A company's own domains are a small per-ticker set the
  crawler already knows, plus an issuer-core-token check on the domain.
- **Safe failure direction.** A missed PR domain inflates *support* (too lenient); it can
  never manufacture an accusation.

### 6.5 Output — evidence dossier, advisory assessment, no score

Per claim, written to `graph_output/crosscheck/<ticker>_claim_assessments.json`:

```jsonc
{
  "claim_id": "...",
  "claim_text": "AAA tiên phong sản phẩm nhựa thân thiện môi trường",
  "claim_node_index": 1234,
  "assessment": "appears_contradicted",   // | appears_supported | unverified_insufficient_evidence
  "assessment_is_advisory": true,          // ALWAYS true — §1.1
  "supporting_evidence": [ /* node_index, text, class, source_domain, date, confidence, rationale */ ],
  "contradicting_evidence": [ /* ... */ ],
  "flagged_non_independent_support": [ /* dropped by the §6.4 guard */ ],
  "caveats": [
    "No ground-truth greenwashing label exists; this is an advisory opinion.",
    "At least one evidence item has an uncertain publish date.",
    "Evidence is mixed (both supporting and contradicting items found)."
  ]
}
```

Framing rules baked into the writer:

- The field is `assessment` with three advisory values — never `greenwashing`, never a
  number.
- `assessment_is_advisory` is always `true`, and `caveats` always carries the
  no-ground-truth note plus any coverage or date-uncertainty warnings.
- Contradiction outranks support when a dossier contains both, and the mixed-evidence
  caveat is added.

A `signals` block (`kpi_gap`, `structural_contradiction`, `broken_promise`) is read by the
sync and ledger stages but **is not currently written by this stage** — see
[ROADMAP.md](ROADMAP.md) §2.1. Treat those fields as inert today.

---

## 7. Temporal alignment

The graph is temporal, so the comparison must be too — but news dates are unreliable.

1. **Normalization** (`preprocess_news`): use `publish_date` when it is present and
   plausible (not a placeholder, not equal to the crawl date, within `[1990, now]`); else
   parse a year from the URL or the article text; else set `date_uncertain = true` and
   keep the crawl date only as a loose upper bound.
2. **Canonicalization** (`fix_triples` phase 1.5): every date becomes ISO
   `YYYY[-MM[-DD]]`, `valid_from > valid_to` is flagged, and news-side event nodes get a
   default `date_uncertain` if extraction omitted it.
3. **Matching** (§6.1): the claim year plus the configured window.

Conduct with `date_uncertain = true` is still surfaced as candidate evidence but flagged
in the dossier caveats — nothing is silently dropped.

---

## 8. Data-quality handling

### 8.1 No domain routing

An earlier design classified `source_domain` into independent / company-owned / aggregator
buckets via a config file and routed PR to the claim side. It was removed: PR mostly
restates the annual report (no new signal), and the one thing routing protected against is
handled more cheaply by the guard in §6.4, using a field already present on every node.

### 8.2 Noise filtering reuses upstream signals

No new noise machinery. Records failing the company-mention check or with near-empty text
are dropped; only `esg=true` sentences drive extraction; whatever slips through is
low-volume noise the adjudicator marks `irrelevant`.

### 8.3 Coverage is a first-class caveat, not silence

From `data/outputs/news/coverage.csv`: **thin coverage means "little external evidence was
found", not "the company is clean."** Every company-level summary and every
`unverified_insufficient_evidence` assessment carries coverage counts, and the stats file
carries an explicit `coverage_caveat` string, so absence of evidence is never presented as
evidence of absence.

This matters more than it sounds. On the pinned AAA run, 36 of 36 claims came back
`unverified_insufficient_evidence` — not because AAA is clean, but because the independent
conduct pool for those claims was 68 nodes and only 11 claims drew any candidate at all.
Reporting that honestly is the design, not a failure of it.

---

## 9. Output & querying

Three surfaces read the graph; none of them calls an LLM.

### 9.1 The advisory layer in Neo4j

`neo4j_sync` (08) re-reads the dossier the paid run already produced and merges it into
Neo4j as an explicitly namespaced advisory layer: `assessment`, `assessment_is_advisory`,
`caveats` and `crosscheck_ticker` on each claim node, plus `llm_supports` /
`llm_contradicts` / `llm_flagged_support` evidence edges — including the KPI-based
contradictions the base schema cannot express. Idempotent; costs nothing.

Claims are resolved by a **stable id first**, falling back to array position, because the
dossier records node *positions* and any re-clustering upstream would otherwise bind every
advisory edge to the wrong node with no error.

### 9.2 The per-company claim ledger

`claim_ledger` (09) renders every claim with its evidence and assessment, signal-first
(contradicted → supported → unverified), with the coverage caveat in the header. It reads
**only Neo4j** — run `neo4j_sync` first. `--review-queue` narrows to the cases that need a
human: a contradiction with no independent verification. See
[CLAIM_LEDGER.md](CLAIM_LEDGER.md).

### 9.3 The ESG Evidence View UI

`python api/main.py` serves a three-column TT96/GRI evidence view on `:8000` from live
Neo4j. Each card's E/S/G pillar comes from the linked `StandardIndicator.pillar` rather
than a guess. See [ESG_EVIDENCE_VIEW.md](ESG_EVIDENCE_VIEW.md).

### 9.4 Cypher

Analyst queries live in `neo4j/crosscheck_queries.cypher`. The shape most used:

```cypher
// Claims with contradicting evidence and no independent verification
MATCH (c:SustainabilityClaim {crosscheck_ticker: $t})-[x:llm_contradicts]->(e)
WHERE NOT (c)-[:llm_supports]->()
RETURN c.description, c.assessment, collect(e.description)[..3] AS evidence
ORDER BY size(collect(e)) DESC
```

---

## 10. Limitations, risks, and the ethical frame

| Risk | How the design contains it |
|---|---|
| Presenting an advisory opinion as a verdict | No score, no label; `assessment_is_advisory` on every record; caveats mandatory; the UI and ledger repeat the framing |
| Thin news coverage read as exoneration | Coverage counts on every summary; explicit `coverage_caveat` (§8.3) |
| A company's PR verifying its own claims | Self-verification guard (§6.4) |
| Unreliable news dates | Three-step normalization plus `date_uncertain` surfaced as a caveat (§7) |
| An LLM repair silently rewriting extracted values | `preserve_property_values` in `fix_triples` restores any property value the repair model altered |
| The model answering in English on Vietnamese source text | Language guards pinned by tests on both extraction prompts |
| A wrong indicator mapping being untraceable | `kpi_id` is a *new* property; the raw `kpi_type` is never overwritten, and every mapping records which tier decided it |

The system can be wrong in one direction cheaply (missing a real contradiction) and in the
other direction expensively (implying misconduct). Every default is set toward the first.

---

## 11. Related documents

- **Contracts:** [SCHEMA_EXPLAINED.md](SCHEMA_EXPLAINED.md),
  [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md),
  [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md)
- **Stages:** see the table in §5.2
- **Infrastructure:** [LLM_PROVIDERS_AND_CACHING.md](LLM_PROVIDERS_AND_CACHING.md),
  [DATA_SYNC.md](DATA_SYNC.md), [TESTING.md](TESTING.md)
- **Reference vocabularies:**
  [KPI_DEFINITIONS_CONSTRUCTION_BUILD.md](KPI_DEFINITIONS_CONSTRUCTION_BUILD.md),
  [GRI_SCHEMA_DOCUMENTATION.md](GRI_SCHEMA_DOCUMENTATION.md)
- **Future work:** [ROADMAP.md](ROADMAP.md)
- **Repo-internal:** `src/PIPELINE.md` (run order), `src/esg_kg/DESIGN.md` (refactor
  record), `CLAUDE.md` (working rules)
