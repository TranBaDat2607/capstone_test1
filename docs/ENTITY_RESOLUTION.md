# Stages 04 / 05 — issuer registry and entity resolution

```bash
python src/run.py issuer                          # run-once bootstrap, then hand-confirm
python src/run.py build_resolved --dry-run        # the normal way: 05 → 05b → 05c
python src/run.py build_resolved
python src/run.py entities --no-llm               # stage 05 alone, for diagnosis
```

Modules: `registry/issuer.py` · `resolve/entities.py` · `resolve/build_resolved.py`
Output: `config/issuer_registry.json` (tracked in Git) ·
`graph_output/resolved/resolved_graph.json`

Entity resolution is a **deliberate redesign** of the reference implementation's step 4,
not a port. The reason is the problem: Vietnamese company names appear as the current name,
the pre-rename name, the bare ticker, and many English forms, while look-alikes (a parent
holding company, a subsidiary) share part of the name but are *different legal entities*.
Getting this wrong does not degrade the output gracefully — it silently splits or merges
the company the entire cross-check hangs on.

---

## 1. Stage 04 — the issuer registry

The reporting company's name variants must merge into one node **deterministically**, never
via embeddings or an LLM. The issuer is the backbone of the greenwashing comparison; its
identity cannot depend on a model verdict.

`issuer` drafts that registry from data already in the repo:

- `config/company_annual_report.xlsx` → ticker to official name;
- `all_validated_triples.json` → the `Organization` name variants actually present, plus a
  structural signal (how often each name is the *subject* of report-type edges — the issuer
  dominates these).

Each distinct name lands in one of three buckets:

| Bucket | Meaning |
|---|---|
| `aliases` | Confident issuer variants — merge into the issuer |
| `exclusions` | Known-separate entities — never merge |
| `needs_review` | Ambiguous — a human decides |

Output is `config/issuer_registry.json`, keyed by ticker, with `canonical_name`,
`core_tokens`, and the three lists. Currently populated for AAA, ACC, ACG, ADP, AGG.

**Re-running preserves human edits.** Confirmed aliases and exclusions are kept; only
newly-seen names are appended to `needs_review`. `--force` rebuilds from scratch and
discards those edits.

### 1.1 The graph-signature classifier

Pure lexical matching sent too much to `needs_review`. A name that shares the issuer's core
tokens but is missing one ("Nhựa An Phát" versus "Nhựa An Phát Xanh") is lexically
ambiguous, and so is a genuinely separate sibling ("An Phát Complex"). Both landed in the
human queue.

The insight: **the same entity behaves the same way in the graph.** So for an ambiguous
name, compare its graph neighbourhood against the issuer's.

**Signature.** For an `Organization` node *O*, the signature is the set of
`(relation_direction, neighbour_identifier)` pairs: `(P, id(X))` when *O* is the subject of
`P` toward *X*, and `("<-" + P, id(Y))` when *O* is the object of `P` from *Y*. The
neighbour's identifier is its most distinctive property, scanned in order
`name → kpi_type → title → other identity keys`.

**Weighted Jaccard.** Not every relation identifies a legal entity equally well. Being
penalized is far more distinctive than publishing a report:

| Weight | Relations |
|---|---|
| 3.0 | `subjectToPenalty` |
| 2.5 | `holdsCertification` |
| 2.0 | `reportsKPI`, `claims`, `setsGoal`, `adoptsStandard`, `targetsScienceBased` |
| 1.5 | `subjectToRegulation`, `ownsFacility`, `takesPartIn`, `generatesEmission`, `generatesWaste`, `offsetsWith`, `impactsCommunity` |
| 1.0 | `locatedIn`, `publishesReport`, and anything unlisted |

$$\mathrm{Sim}(A,B) = \frac{\sum_{x \in A \cap B} w(x)}{\sum_{y \in A \cup B} w(y)}$$

**Anti-contamination.** The issuer's own reference signature is built from the official name
plus **only** absolutely-confident variants (an exact normalized match on the ticker or the
official name). A merely-probable alias never contributes to the signature it will later be
compared against, or a single lexical misclassification would propagate into every
subsequent decision.

**Decision.**

| Lexical verdict | Action |
|---|---|
| Confident | `aliases`, as before — no graph check needed |
| Ambiguous (≥ 2 shared core tokens) | Compute `Sim`: `> --graph-sim-upper` (default 0.8) → `aliases`; `< --graph-sim-lower` (default 0.2) → `exclusions`; between → `needs_review` |

If no issuer signature can be built, the classifier falls back to the original lexical
logic and says so in the recorded reason.

Signatures are cached globally once per run, so the cost is linear in the number of
neighbouring relations.

### 1.2 Flags

`-i` · `--companies` · `-o` · `--min-subject-edges` · `--force` · `--graph-sim-upper` ·
`--graph-sim-lower`

> `config/issuer_registry.json` is **tracked in Git and hand-edited**. Every test arm runs
> against a temporary workspace, and one arm asserts the real tracked file is never
> touched.

---

## 2. Stage 05 — entity resolution

Collapses duplicate entity nodes in `all_validated_triples.json` into canonical entities,
preserving each entity's temporal history, and writes the deduplicated temporal graph.

### Stage A — deterministic merge (free)

- **A.1** exact `identity_keys` signature — entities *and* observations.
- **A.2** **issuer anchor, frozen.** Merge the reporting company's variants by exact
  membership in `config/issuer_registry.json`. This cluster's identity never depends on an
  embedding or an LLM.
- **A.3** **standards anchor, frozen.** Merge `Standard` / `Regulation` mentions using
  `config/standards_registry.json`, which freezes GRI's four-plus spellings and TT96's
  Vietnamese and English forms onto one canonical node each.

### Stage B — Vietnamese-aware blocking (non-issuer entities only)

- **B.1** normalized identity-signature merge — diacritics, legal form, case.
- **B.2** `gemini-embedding-001` cosine blocking, batched and L2-normalized.

### Stage C — adjudication

`gemini-2.5-flash` on the ambiguous candidate pairs, budgeted by `--max-llm-pairs`.
Verdicts are cached content-addressed on `{class, a, b}`, so a second run costs nothing and
reproduces the same result.

### Stage D — consolidate

DSU clusters become `temporal_versions`; a deterministic canonical is chosen; edges are
rewired **year-aware**, so multi-year edges between the same pair stay distinct rather than
collapsing into one.

### 2.1 `--no-llm` is the usual mode

`--no-llm` runs Stage A + B.1 only: no embedding blocking, no adjudication. This is how the
pipeline is normally run today. It originated as a workaround while the Gemini project was
billing-blocked; the block is gone, but the default has not been revisited — **do not assume
it is safe to flip without checking**. See [ROADMAP.md](ROADMAP.md) §2.5 for the local-
embedding alternative.

### 2.2 Flags

`-i` · `-s` · `-o` · `--registry` · `--standards-registry` · `--similarity-threshold` ·
`--rate-limit` · `--model` · `--embed-model` · `--embed-dim` · `--embed-batch` ·
`--max-llm-pairs` · `--no-llm` · `--dry-run`

### 2.3 `resolve_graph()` versus `main()`

`resolve_graph()` is a pure function — no file I/O, no client construction — so the block
can chain Stage A–D straight into 05b and 05c in memory. `main()` keeps the CLI and the
file writes. This split happened at migration time precisely because the block needed it.

---

## 3. The `build_resolved` block

Same rationale as the 03 block ([TRIPLET_VALIDATION.md](TRIPLET_VALIDATION.md) §1): `05`,
`05b` and `05c` all read and write `resolved_graph.json`. `entities` writes the **whole
file from scratch with no merge and no warning**, so re-running it alone silently destroys
`provenance`'s stamps and `indicators`' axis.

`build_resolved` chains the three in memory and writes the artifact once.

**Scoped caching.** Stage C adjudication is cached — a non-deterministic verdict that costs
money. Stage B embeddings are deliberately **not** cached: merely billed but deterministic,
and not worth the complexity while that path is dormant.

**`align_claims` (05d) is deliberately not part of the block.** It is optional and budgeted,
and it patches the resolved graph *after* the block runs. The block must produce a correct,
complete `resolved_graph.json` with 05d entirely absent.

Flags mirror the member stages, plus `--cache` / `--no-cache`.

---

## 4. Invariants everything downstream depends on

| Invariant | Why |
|---|---|
| **Node array order is never changed** by 05b, 05c or 05d | `neo4j_load` keys Neo4j by array index (`_node_key = "n{i}"`) and the cross-check dossiers reference nodes by `node_index`. A reordering silently binds the advisory layer to the wrong nodes |
| **05c and 05d are append-only** | `GraphPatch.assert_append_only()` verifies by object identity before writing |
| **The issuer cluster is frozen** | It is the subject of every claim the system evaluates |
| **T1 identity is timeless** | See [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) P1 |

Re-run `provenance` after any `entities` re-run.

---

## 5. Known limitation

`needs_review` still requires a human, and the registry currently covers five tickers. The
graph-signature tier reduces the queue but does not eliminate it — an entity with too thin
a neighbourhood produces a weak signature and correctly falls back to human review rather
than guessing.

`config/subsidiaries/` holds extracted subsidiary/associate tables for 108 tickers
(`ticker`, `source_doc`, `source_pages`, `companies[]` with ownership percentages,
`reviewed: false`). **Nothing in the pipeline reads it yet.** It is staged input for the
structural-routing work in [ROADMAP.md](ROADMAP.md) §2.2, and would also be a stronger
exclusion source than lexical qualifiers for this stage.

---

## 6. Tests

| Test | Covers |
|---|---|
| `test/test_esg_kg_issuer.py` | Stage 04 against a temp workspace; a simulated human edit surviving a re-run; the real tracked file never touched |
| `test/test_esg_kg_entities.py` | `resolve_graph()` on the real corpus with `no_llm=True`; the paid path via a stub over `google.genai.Client` on a synthetic near-duplicate-org fixture; the adjudication cache calling the LLM zero times on a second run |
| `test/test_entities_partial_key_merge.py` | Partial identity-key merge behaviour |
| `test/test_esg_kg_resolve_block.py` | The block writes exactly once; the separate chain writes three times; cache behaviour; a smoke check that 05d still runs against the block's output |
| `test/test_quality_hub_set.py` | Hub-cluster identification follows the registry, not a single `argmax(degree)` |
