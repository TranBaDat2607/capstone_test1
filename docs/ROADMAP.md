# Roadmap — what is proposed, what landed, what was rejected

This file replaces four separate proposal documents (`CROSSCHECK_EXPANSION.md`,
`BERT_NER_GRAPH_QUALITY.md`, `ENTITY_RESOLUTION_IMPROVEMENT.md`,
`VIETNAM_IMPROVEMENT_PLAN.md`) that were being read as descriptions of shipped code.
Everything here is either **not built**, **partly built**, or **deliberately rejected**.
Anything that shipped was moved into the per-stage doc that owns it and is listed in
§1 only as a pointer.

Verified against the code on 2026-08-12.

---

## 1. Proposals that shipped (documented elsewhere now)

| Proposal | Where it landed | Doc that owns it |
|---|---|---|
| Canonical KPI vocabulary (`kpi_id`, `unit_normalized`, `value_normalized`, `period`) | `canonicalize` (03c) | [TRIPLET_VALIDATION.md](TRIPLET_VALIDATION.md) |
| `Goal.target_date` regex backfill | `canonicalize` (03c) | [TRIPLET_VALIDATION.md](TRIPLET_VALIDATION.md) |
| Indicator axis as first-class graph structure | `indicators` (05c) | [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) |
| Graph-signature entity resolution (weighted Jaccard, `--graph-sim-upper/-lower`) | `issuer` (04) | [ENTITY_RESOLUTION.md](ENTITY_RESOLUTION.md) |
| Deterministic `claim_id` (issue #2 / plan C1) | `extract_triples` (02) | [TRIPLET_EXTRACTION_FROM_JSONL.md](TRIPLET_EXTRACTION_FROM_JSONL.md) |
| Hub-cluster identification by issuer registry (plan A1) | `metric/hub.py`, used by `quality` | [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) §4 |
| Reasoning-readiness metrics R1 / R1′ / R7 (plan A2/A3) | `metric/reasoning_readiness.py` | [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) §4 |
| Hub decomposition into an export view (plan B4) | `export_kgc` (11) | [EXPORT_KGC.md](EXPORT_KGC.md) |
| `mentionsFacility` edge pair for news reports | `config/schema.json` | [SCHEMA_EXPLAINED.md](SCHEMA_EXPLAINED.md) |

`GRAPH_IMPROVEMENT_PLAN.md` is referenced by several source files (`quality.py`,
`export_kgc.py`, `hub.py`, `reasoning_readiness.py`, `test_claim_id_deterministic.py`)
but **does not exist in this repository**. Its items A1/A2/A3/B4/C1 all shipped and are
documented in the table above; the remaining unshipped items are folded into §2 below,
so the dangling reference is a naming artifact, not a missing design.

---

## 2. Open items

### 2.1 Ghost signals in the cross-check dossier — the highest-value gap

`neo4j_sync` (08) reads and `claim_ledger` (09) renders three dossier signals —
`kpi_gap`, `structural_contradiction`, `broken_promise` — but **`claims_vs_conduct` (07)
never writes a `signals` key**. Every claim therefore carries `kpi_gap=false`
permanently, and the ledger's signal column is decorative.

Two of the three checks are now unblocked, because the join key they needed exists:
`canonicalize` (03c) assigns `kpi_id` / `unit_normalized` / `value_normalized` / `period`
to both report-side and news-side `KPIObservation` nodes.

- **`kpi_gap`** — for each claim, match report-side and news-side KPI observations on
  (canonical `kpi_id`, overlapping period) and flag a relative divergence above a
  threshold (θ≈0.2 after unit normalization). Expect this to fire *rarely* — Vietnamese
  news seldom publishes comparable figures — but when it fires it is the strongest
  evidence the system can produce. A weaker `penalty-in-domain` variant (a news-side
  `Penalty` in the same KPI domain as a report-side KPI) is the practical fallback.
- **`broken_promise`** — for each `Goal` with a `target_date` past its grace period,
  look for completion evidence (a later "achieved" claim on the same topic, a
  `KPIObservation` meeting the metric, or a `ThirdPartyVerification`). Absence of
  evidence is not proof of a broken promise, so this must stay a *signal* feeding the
  advisory assessment, never a verdict. Goals with no `target_date` after backfill are
  slogans, not promises, and must be excluded from the check.
- **`structural_contradiction`** — intersect `subjectToRegulation` and `subjectToPenalty`
  edges on the same issuer where the penalty's domain matches the regulation's. Cheap
  (milliseconds) and purely structural.

All three are offline, no LLM. The natural home is a new signal-generator that patches
the dossier, since the earlier `step07b` that was supposed to host them was removed from
the project (see §3).

### 2.2 Retrieval is global token overlap

`claims_vs_conduct`'s candidate retrieval pools every news-side node of a conduct class
and ranks by Vietnamese token overlap. Two consequences: quantitative evidence is not
guaranteed to be considered, and misconduct by a subsidiary or a named facility never
reaches the parent's claims.

- **Always-include tier** — add every news-side `Penalty` for the issuer plus the top-3
  news `KPIObservation` to every claim's candidate set regardless of token overlap.
  Claims rarely restate numbers, yet numbers are the most checkable evidence.
- **Structural routing** — define the issuer's conduct pool as news nodes within k≤2
  hops of the `Organization` over `{ownsFacility, owns, investsIn, partnersWith,
  mentionsOrganization, observedAtFacility}`, and record the traversed path on each
  evidence item. The path doubles as the explanation shown in the UI.

Both widen the *pool* only — adjudication and the self-verification guard are unchanged,
so neither can manufacture a verdict. Cost control stays `--max-llm-pairs`.

### 2.3 News events cannot be anchored to a facility

`observedAtFacility` is legal only for `KPIObservation → Facility`. News reports
misconduct per *plant*, so `Controversy`, `Penalty` and `MediaReport` have no way to
attach to the facility they are about. Fixing this needs two changes:

1. add `(Controversy, Facility)`, `(Penalty, Facility)`, `(MediaReport, Facility)` as
   legal pairs of `observedAtFacility` — the validator already supports one label with
   many pairs, so this is additive;
2. extend `anchor_kpi` (03b)'s offline gazetteer to scan the source sentences of those
   three classes.

This also feeds §2.2's structural routing, which needs facility edges to route over.

### 2.4 Vietnamese NER to raise anchoring recall

`anchor_kpi`'s gazetteer does raw normalized string matching, so it misses name variants
("NM Nhựa An Phát 6", "nhà máy số 6 của An Phát"). `underthesea.ner()` is **already a
dependency** (via `sentence_splitter`), needs no torch, and runs on CPU: extract `ORG`
/ `LOC` spans from the source sentence and fuzzy-match the *spans* rather than the whole
sentence. A secondary use is crawler noise filtering — an article whose NER finds no ORG
matching an issuer alias can be flagged `off_target` and de-prioritized in retrieval.

Stated limitation to keep: underthesea's NER is a classical CRF/BiLSTM model
(F1 ≈ 0.85–0.90 on clean news). That is adequate for a *candidate filter in front of a
gazetteer*, not for primary extraction.

### 2.5 Local sentence embeddings for entity resolution

`entities` (05) is normally run `--no-llm`, i.e. Stage A + B.1 only: no embedding
blocking (B.2) and no adjudication (C). This originated as a workaround while the Gemini
project was billing-blocked; the block is gone, but the default has not been revisited.

A CPU sentence-encoder would make Stage B.2 free and reproducible rather than billed —
candidate models: `bkai-foundation-models/vietnamese-bi-encoder`,
`paraphrase-multilingual-MiniLM-L12-v2`, `keepitreal/vietnamese-sbert`. The corpus is a
few thousand short names, so a single cached CPU encode pass is minutes, not hours. Add
it as a second embedding provider (`gemini | local`) rather than silently switching the
default. Torch stays out of `requirements.txt`, matching the ViDeBERTa CPU convention.

Measure with `quality --label` before/after: added merges, Q3 conciseness, and the drop
in `needs_review` entries.

### 2.6 Regulatory layer cannot express binding force

The schema is GRI/ESRS-shaped: it assumes a voluntary standard is the binding authority.
Vietnam has no single ESG standard — it has mandatory *disclosure* instruments
(Circular 96/2020/TT-BTC; Decree 06/2022/NĐ-CP and Decision 13/2024/QĐ-TTg for GHG
inventories; Decision 21/2025/QĐ-TTg green taxonomy; Decision 232/2025/QĐ-TTg carbon
market) layered over voluntary guidance (GRI, the SSC/IFC ESG Handbook).

`Regulation` currently carries only `name` / `jurisdiction` / `description`, and
`Standard` only `name` / `description`. Neither can answer "is this binding?" or "which
instrument number?". The additive fix is properties, not new classes: `instrument_type`
(luật / nghị định / thông tư / quyết định / guideline), `mandatory`, `instrument_number`,
`effective_from`. Being additive, old nodes stay valid and the change is measurable with
`quality --label` before/after.

The multi-framework crosswalk half of this plan (map each disclosure to both GRI and the
Circular 96 index set) **already shipped** as the indicator axis — see §1.

### 2.7 The SSRL path-reasoning layer

Fully designed in [SSRL_REASONING_LAYER.md](SSRL_REASONING_LAYER.md); the layer itself is
unbuilt. `export_kgc` (11) is the only piece that exists — it produces the hub-decomposed
export view such a layer would train on.

R1 / R1′ / R7 in the quality report are its readiness metrics: the current graph
re-derives 47.2% of masked edges within 3 hops, and only 26.7% once issuer-hub routes are
barred. That gap is the number that would have to improve before path reasoning is worth
training.

Its own gate (§6.1 of that document) — the share of claims reaching conduct via a path with
at least one structural edge — moved from a simulated 16.0% on one company to a measured
44.6% on five, which supports its central "multi-company is necessary" claim. Two
prerequisites from the same document are still open: reifying `ClaimKeyword` for news-side
nodes with a `df ≤ 20` degree cap (§4.2 there), and filling the conduct-side gap (§4.4).

---

## 3. Rejected, with reasons

Keep these — they are the answers to the obvious "why didn't you just…" questions.

**Fine-tuning a BERT greenwashing classifier.** No ground-truth labels exist for
Vietnamese listed companies; that absence is the central premise of the system design.
Fine-tuning needs thousands of labels, and self-invented labels would train the model on
the labeller's bias — precisely the trap the evidence-plus-advisory architecture avoids.
It is also the wrong output shape: the deliverable is traceable evidence, not a binary
label from a black box, and a classifier cannot answer "why".

**Replacing LLM extraction with NER.** NER returns flat entity spans. `extract_triples`
needs schema-typed triples: a class from ~28, a relation from ~48 labels, a property map,
`valid_from` / `valid_to`, and `date_uncertain`. That gap is a full Vietnamese
relation-extraction plus temporal-tagging system; nothing off-the-shelf covers it. NER's
correct role is post-hoc anchoring (§2.4).

**Softmax evidence-balance scoring (`step07b`).** Built, then removed outright on
2026-07-29: nothing on the delivered UI surface ever read `assessment_scores` /
`score_components`. The categorical advisory `assessment` was always the primary output,
and no ground truth exists for a greenwashing probability. `neo4j_sync`'s docstring still
mentions the score fields and a `docs/SOFTMAX_SCORING.md` that no longer exists — dead
references, not a pending feature.

**No-ground-truth evaluation report (`step10`).** Removed 2026-07-28; coverage /
case-study / ablation measurement without labels was dropped as a deliverable, with no
replacement command.

**Standards-registry reseeding (`step04b`).** Removed 2026-07-29. It read `entities`'
output while `entities` read its own output — a cycle — and every alias it "discovered"
was a hardcoded seed. `config/standards_registry.json` is static config now; `quality`'s
standards-registry audit reports uncovered mentions instead.

---

## 4. Dangling documentation references in source code

Source docstrings cite four documents that are not in this repository. None blocks
anything; listing them so they are not repeatedly rediscovered as missing design.

| Reference | Cited by | Status |
|---|---|---|
| `GRAPH_IMPROVEMENT_PLAN.md` | `quality.py`, `export_kgc.py`, `hub.py`, `reasoning_readiness.py`, `test_claim_id_deterministic.py`, `test_entities_partial_key_merge.py`, `test_mentions_facility_edge.py`, `config/degenerate_relations.json` | Items A1/A2/A3/B1/B4/C1/C2 all shipped — see §1. Remaining items folded into §2 |
| ~~`SSRL_REASONING_LAYER.md`~~ | `reasoning_readiness.py`, `quality.py` §2.2/§6.1 | **Resolved** — the file was deleted by accident in commit `75b804c` (a feature commit) and has been restored |
| `SOFTMAX_SCORING.md` | `neo4j_sync.py` docstring, the claim-ledger header banner | Belongs to the removed `step07b`. Dead reference |
| `docs/CROSSCHECK_EXPANSION.md` §4.1/§5 | `canonicalize.py` docstring | Replaced by this file; §4.1 shipped (see §1), §5 was a schedule |
| `feedback-gri-catalog.md` | `gri/build_gri_catalog.py` docstring | A review note, now removed. Every rule it demanded is implemented and pinned by `test/test_gri_catalog_build.py` |
| `EVALUATION.md` | a stage docstring | Belongs to the removed `step10`. Dead reference |

Fixing these means editing docstrings, which is a code change and therefore out of scope
for a documentation pass.
