# Claim ↔ conduct cross-check — purpose, reason and logic

Script: [`src/crosscheck_claims_vs_conduct.py`](../src/crosscheck_claims_vs_conduct.py)
(Step 6 / P4). System context: [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §6.

This step runs **after** the temporal knowledge graph is built, resolved and loaded
(steps 1–5). It reads the resolved graph
(`graph_output/resolved/resolved_graph.json`) and, for every `SustainabilityClaim` the
issuer made in its **reports**, finds the **news conduct** that supports or contradicts
it, then emits an **advisory evidence dossier** at
`graph_output/crosscheck/aaa_claim_assessments.json`. It is the analytical core of the
greenwashing-evidence system — the stage that finally connects "what the company *says*"
to "what the company *does*."

It plays the role of EmeraldMind's detection steps (`6a-parse_claims_to_nodes.py` →
`6b-generate_embeddings.py` → `7-classify.py`), but is a **deliberate inversion**, not a
port (Section 5). The one non-negotiable framing, carried from `SYSTEM_DESIGN.md` §1.1:
**there is no ground truth**, so this step produces *evidence + an explicitly advisory
opinion*, **never a greenwashing score or a hard label**.

---

## 1. Why this step exists

Steps 1–5 put two kinds of node on the **one** resolved issuer node: the company's own
`SustainabilityClaim`s (from reports, `source_type=report`) and third-party `MediaReport`
/ `Controversy` / `Penalty` / observed `KPIObservation` (from news, `source_type=news`).
Co-locating them is necessary but not sufficient — nothing yet **links a specific claim to
the specific evidence that bears on it**. Greenwashing is a *gap between saying and doing*;
that gap only becomes visible once a claim is connected to the conduct that confirms or
undercuts it.

This step writes those links. Its output lets an analyst ask the schema's payoff question
directly: *which claims have contradicting evidence and no independent verification?* —
the review queue in `SYSTEM_DESIGN.md` §9.2.

**Why it must be advisory.** We have no labelled greenwashing dataset for Vietnamese
companies (§1.1). A score or a `greenwashing/not_greenwashing` label would imply a truth
we cannot back. So every output is `assessment_is_advisory: true`, every claim carries
`caveats` (always including the no-ground-truth note), and the LLM's suggested links are
namespaced `llm_suggested=true` so they can never be mistaken for extracted facts.

---

## 2. What it consumes and what it produces

**Inputs**
- `graph_output/resolved/resolved_graph.json` — the step-4 `{nodes, edges}` graph
  (index-referenced edges, provenance-tagged, one resolved issuer node).
- `config/schema.json` — read via `load_schema_sets` (from `fix_invalid_triplets.py`) to
  check that every edge this step writes is **schema-legal** before it is emitted.
- `.env` `GEMINI_API_KEY` — **only** if LLM adjudication is enabled (Section 4, 6b).

**Outputs** (`graph_output/crosscheck/`)
- `aaa_claim_assessments.json` — one advisory dossier per claim (Section 4, 6e).
- `aaa_crosscheck_stats.json` — run summary (assessment histogram, retrieval stats,
  coverage caveat, LLM status).
- `crosscheck_edges.json` — the LLM-suggested linking edges in the resolved graph's
  index format (re-loadable; empty in `--no-llm`). Optionally MERGEd into Neo4j with
  `--to-neo4j`.

**Current AAA run (offline, `--no-llm`):** 1093 claims on the issuer; conduct pool of 124
`source_type=news` nodes (16 `MediaReport` + 108 observed `KPIObservation`); topical
candidates found for 744 claims (avg 2.85/claim); assessments = **1091 unverified +
2 appears_contradicted**. The two contradictions are genuine, deterministic, and
explainable (Section 6).

---

## 3. Pipeline at a glance

```
resolved_graph.json ──▶ index issuer + claims + conduct pool
                         │
   6a  retrieve   ──────▶ per claim: same issuer → VN topic overlap → temporal window
                         │            → top-k candidates   (--embed rank optional, off)
   6b  adjudicate ──────▶ gemini-2.5-flash structured {verdict, confidence, rationale}
                         │            (optional, budgeted, degrades gracefully on 403)
   6c  write edges ─────▶ verifiedBy / contradictedBy / contradictedByMedia  (schema-checked)
   6c-guard ────────────▶ company-owned domain ⇒ never a verifiedBy edge
   6d  signals ─────────▶ structural contradiction + KPI numeric gap (deterministic)
   6e  dossier ─────────▶ assessment ∈ {appears_supported | appears_contradicted |
                                        unverified_insufficient_evidence} + caveats
```

---

## 4. Logic walkthrough

### 6a — candidate retrieval (which conduct might bear on this claim?)
For each claim, the conduct pool is filtered by cheap, explainable signals before any LLM:
1. **Same issuer** — the pool is the news-side conduct on the one resolved issuer node
   (guaranteed by step 4). No cross-company leakage.
2. **Topic overlap** — VN-normalized token overlap (`name_tokens` from
   `build_issuer_registry.py`) between the claim (its `description` **plus** its
   `ClaimKeyword` terms) and each candidate's text. Issuer-name and generic tokens are
   stop-listed so overlap reflects the ESG *topic*, not the company name.
3. **Temporal window** — a candidate's effective year must lie in
   `[claim_year − window_before, claim_year + window_after]`; a claim can only be
   contradicted by conduct around or after it. Candidates with an uncertain date are
   **surfaced but flagged**, never silently dropped (§7.2).
4. Remaining candidates are ranked by (overlap, recency) and the top-`k` kept. An optional
   embedding re-rank (`--embed`) is reserved but **off by default** — the pool is tiny and
   the Gemini embedding endpoint is currently billing-blocked.

### 6b — LLM adjudication (does this evidence support or contradict?)
Candidate pairs are ranked by topic overlap **globally** and the top `--max-llm-pairs`
(highest overlap first, §6.2) are adjudicated **concurrently** (`--max-workers`). Each pair
is judged only from the two provided texts, treating news as independent conduct and
preferring `irrelevant` over guessing, returning
`{verdict: supports|contradicts|irrelevant, confidence: 0-1, rationale}` as structured
output (the robust `response_schema` / `json_object` pattern from `extract_kpi_from_jsonl.py`).

**Multi-provider with graceful fallback.** Adjudication is *optional and non-fatal*, and
runs through a **provider cascade** (`--provider-order`, default `gemini,openai`):

- **Primary — `gemini-2.5-flash`** (structured output via `response_schema`).
- **Fallback — OpenAI `gpt-4o-mini`** (`response_format=json_object`). For this narrow,
  grounded 3-way task the two are comparable, so either produces usable links; spot-checked
  `gpt-4o-mini` verdicts were well-grounded (e.g. it flagged a claimed EPS target of 2,550
  VND against an observed 1,213 VND as a contradiction).

A provider that fails 3× with no success (e.g. a 403 billing block) is disabled and the
next takes over automatically; if all providers die — or `--no-llm`/`--dry-run` is set, or
no key is present — the run finishes on the deterministic signals alone. Each written edge
records which model produced it (`llm_provider`) so results stay auditable across
mixed-provider runs. **Key precedence:** the adjudicator loads `.env` with `override=True`,
so the repo `.env` is authoritative even if a stale `OPENAI_API_KEY` / `GEMINI_API_KEY` sits
in the shell environment (a real gotcha we hit — the shell var silently shadowed `.env`).

### 6c — write the linking edges
A verdict becomes a **schema-legal** edge, checked against `edge_directions` before it is
written:

| Verdict | Evidence class | Edge | Legal pair (schema) |
|---|---|---|---|
| supports | ThirdPartyVerification / KPIObservation | `verifiedBy` | SustainabilityClaim → {TPV, KPIObservation} |
| contradicts | Controversy | `contradictedBy` | SustainabilityClaim → Controversy |
| contradicts | MediaReport | `contradictedByMedia` | SustainabilityClaim → MediaReport |
| irrelevant | — | *(none)* | — |

Anything not schema-legal (e.g. a `Penalty`, which has no direct claim edge — its link to
the issuer is `Organization —subjectToPenalty→ Penalty`) still appears in the dossier's
evidence list but is **not** written as a claim edge, keeping the graph schema-valid. Every
edge carries `llm_verdict`, `confidence`, `rationale`, `evidence_source_type`,
`recorded_at`, and `llm_suggested=true`.

### 6c-guard — the self-verification guard (independence, no config file)
The one independence rule the pipeline keeps (§6.4). When about to write a `verifiedBy`
edge, if the evidence's domain is one of the **issuer's own** sites (a short inline set
plus an issuer-token heuristic on the domain), the support link is **not** counted as
independent verification — it is kept in the dossier flagged `independent=false` and never
contributes to `appears_supported`. The guard touches support only; contradiction is
unaffected. Safe-failure direction: a missed PR domain can only inflate *support*, never
fabricate a contradiction.

### 6d — deterministic complementary signals (not verdicts)
Two cheap, fully explainable signals run **always**, independent of the LLM:
- **Structural contradiction** — a claim that has a `contradictedBy` / `contradictedByMedia`
  edge (pre-existing in the graph or newly adjudicated) but no independent verification.
  Pure graph query.
- **KPI numeric gap** — a report *target* `KPIObservation` and a news *observed*
  `KPIObservation` that share a topic with the claim but move in opposite directions
  (respecting `kind`/`direction`). Deliberately **strict** (same non-generic `kpi_type`,
  ≥2 shared title tokens) and precomputed once.

Per `SYSTEM_DESIGN.md` §6.5 these **enrich** the dossier and enable ablations; the KPI gap
is recorded as a signal and **never** flips the headline assessment on its own (an earlier
loose version wrongly did, marking 416/1093 claims contradicted — now fixed).

### 6e — the output: dossier + advisory assessment (NOT a score)
Per claim:
```jsonc
{
  "claim_id": "AAA_HasSeparateRiskDept_Implicit_2021",
  "claim_text": "AAA has a separate risk management department",
  "claim_source_type": "report", "year": 2021,
  "assessment": "appears_contradicted",     // | appears_supported | unverified_insufficient_evidence
  "assessment_is_advisory": true,           // ALWAYS true
  "supporting_evidence": [ /* guard-passed, independent */ ],
  "flagged_non_independent_support": [ /* company-domain support, shown but not counted */ ],
  "contradicting_evidence": [ /* node id, text, source_domain, date, confidence, rationale */ ],
  "signals": { "structural_contradiction": true, "kpi_gap": null },
  "caveats": [ "No ground-truth greenwashing label exists; this is an advisory opinion.", ... ]
}
```
Aggregation is deterministic: contradiction evidence **or** a structural contradiction ⇒
`appears_contradicted`; else independent support ⇒ `appears_supported`; else
`unverified_insufficient_evidence`.

---

## 5. Design vs EmeraldMind's detection steps (6a/6b/7)

EmeraldMind detects greenwashing by treating a claim as an **external query** scored
against the KG, with **gold labels**. This project inverts that into **intra-graph
advisory linking** with **no labels**:

| Aspect | EmeraldKG `6a/6b/7` | This step |
|---|---|---|
| What a claim is | an external CSV row parsed into a node (`6a`) | a `SustainabilityClaim` node **already in the KG** |
| Query vs corpus | claim = query, KG = corpus | claim **and** conduct are both nodes in the graph |
| Mechanism | embed claim → retrieve from KG → `classify` | retrieve conduct candidates for a claim → adjudicate → **write linking edges** |
| Output | a predicted **label** + accuracy / precision / recall | **evidence dossier + advisory assessment**; no label, no score |
| Supervision | gold labels | **no ground truth**; case studies + manual link-precision |
| Independence | weak (claims + KG both company-authored) | explicit: report = claim, news = conduct; self-verification guard |

The retrieval loop mirrors `7-classify.py`'s `retrieve_evidence`, but the corpus is
*conduct nodes in the KG* and the query is *a claim node in the KG*. (Notably, that
reference does its retrieval with a **local** `SentenceTransformer`, not a paid embedding
API — precedent for the deterministic-retrieval default here.)

---

## 6. The data-availability caveat (surfaced, not hidden)

The design is schema-complete, but the **current graph is thin on independent conduct**,
and this step reports that honestly rather than papering over it:

- The news channel produced **0** `Controversy`, **0** `Penalty`, and 16 `MediaReport`s —
  all neutral/positive analyst & PR coverage. The two `appears_contradicted` results come
  from **self-disclosed** report-side Controversies ("AAA has no separate risk-management
  department", "…has not applied an internal-audit model"), correctly matched to the
  opposing claims via existing `contradictedBy` edges.
- The headline **vietnamnet.vn tax-penalty** example (§1.2, §9.3) exists in the labeled
  news input but was never extracted into a `Controversy`/`Penalty` node (that domain was
  not among the news docs processed in P2).

Consequently, on today's data most claims resolve to `unverified_insufficient_evidence`,
and the tool prints a standing coverage caveat: **thin conduct means "little external
evidence found," not "the company is clean"** (§8.3). To make the worked example fire,
re-extract the penalty-bearing news and re-run steps 3→5, then re-run this step
(Section 8, follow-up).

---

## 7. Schema reference

Edges this step may write (all already in `config/schema.json`; validated at runtime):

| Edge | Direction | Written when |
|---|---|---|
| `verifiedBy` | SustainabilityClaim → ThirdPartyVerification / KPIObservation | `supports`, and the evidence is **independent** (guard-passed) |
| `contradictedBy` | SustainabilityClaim → Controversy | `contradicts` |
| `contradictedByMedia` | SustainabilityClaim → MediaReport | `contradicts` |

No new node classes and no new edge labels are introduced. `llm_suggested=true` on every
written edge keeps advisory links separable from extracted facts.

---

## 8. Setup & run

```bash
# 0. Prereqs: steps 1–5 done, so graph_output/resolved/resolved_graph.json exists.
#    .env needs a working key for the chosen provider(s) (GEMINI_API_KEY and/or OPENAI_API_KEY).

# 1. Offline preview — no API, no writes (recommended first)
python src/crosscheck_claims_vs_conduct.py --dry-run

# 2. Deterministic run — writes dossiers from structural + KPI signals only (no API)
python src/crosscheck_claims_vs_conduct.py --no-llm

# 3. Full run — gemini-2.5-flash primary, gpt-4o-mini fallback, concurrent, whole budget
python src/crosscheck_claims_vs_conduct.py --max-llm-pairs 3200 --rate-limit 400 --max-workers 8

# 3b. OpenAI only (skip the currently-blocked Gemini and its wasted 403s)
python src/crosscheck_claims_vs_conduct.py --provider-order openai --max-llm-pairs 3200 --rate-limit 400

# 4. Optionally MERGE the advisory edges into Neo4j (llm_suggested=true)
python src/crosscheck_claims_vs_conduct.py --to-neo4j
```

### Flags
| Flag | Meaning |
|---|---|
| `--ticker` | issuer to cross-check (default `AAA`) |
| `--top-k` | candidates kept per claim after retrieval (default 8) |
| `--window-before` / `--window-after` | temporal window in years (default 1 / 50) |
| `--max-llm-pairs` | adjudication budget, highest-overlap first (default 300) |
| `--provider-order` | LLM cascade preference (default `gemini,openai`; e.g. `openai`) |
| `--model` / `--openai-model` | Gemini primary id / OpenAI fallback id (`gpt-4o-mini`) |
| `--max-workers` | concurrent adjudication workers (default 8) |
| `--no-llm` | deterministic signals only (no adjudication) |
| `--dry-run` | `--no-llm` + write nothing (offline preview) |
| `--embed` | (reserved) embedding re-rank of candidates; off by default |
| `--to-neo4j` / `--database` | MERGE advisory edges into Neo4j on the loader's `_node_key` convention |
| `--rate-limit` | max requests/min per provider (raise for OpenAI, e.g. 400) |

**Cost discipline** (carried from the pipeline, per the memory note *"verify cheaply, not
via expensive re-runs"*): deterministic signals need no API; `--dry-run`/`--no-llm` preview
for free; `--max-llm-pairs` bounds spend; a full AAA run (~3.1k pairs) of `gpt-4o-mini`
costs roughly US$0.5 and ~13 min at `--max-workers 8`. The Gemini project is currently
billing-suspended (`gemini-2.5-flash` **and** `gemini-embedding-001` return a "Lightning
dunning" 403), so the pipeline falls back to `gpt-4o-mini`; the deterministic path remains
the zero-API default.

### Follow-up (to light up the worked example — needs billing restored)
```bash
python src/extract_triplet_from_jsonl.py -i data/interim/news_preprocessed/aaa_news_classified_preprocessed.jsonl \
    --source news --doc vietnamnet            # re-extract the tax-penalty article
python src/fix_invalid_triplets.py && python src/resolve_entities.py --no-llm && python src/load_graph_to_neo4j.py --clear
python src/crosscheck_claims_vs_conduct.py    # now a real Controversy/Penalty exists to contradict a claim
```

---

## 9. Related docs

[`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) (§6 — the cross-check spec) ·
[`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) ·
[`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) ·
[`GRAPH_LOAD_NEO4J.md`](./GRAPH_LOAD_NEO4J.md)
