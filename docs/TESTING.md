# Testing

```bash
python test/test_schema_contract.py        # run from the repo root
```

There is **no pytest harness and no linter** in this repo. A test is a plain runnable
script under `test/` that prints pass/fail and exits non-zero on failure. 38 of them exist.

---

## 1. The working rule: test first

**Write the test. Run it. See it fail. Then write the code.** No production code lands
without a failing test that demanded it.

1. **Red** — the smallest test expressing the next behaviour; run it; confirm it fails *for
   the expected reason*. A test that passes before the code exists is testing nothing.
2. **Green** — the minimum code to pass. No extra features while you are in there.
3. **Refactor** — clean up with the test green, re-run.

---

## 2. Three non-negotiable conventions

**Plain `assert` scripts, no framework.** Match `test/test_temporal_invariants.py`, the
existing precedent.

**Offline.** No LLM, no Neo4j, no network. Tests run against real artifacts already on
disk (`config/schema.json`, `graph_output/…`). This keeps them free and repeatable.

**Never verify by re-running a paid stage.** That is what `--dry-run`, `--no-llm` and the
stubbing technique below are for.

### 2.1 Stub *under* the abstraction layer

The technique used throughout, and the reason paid stages have real coverage: replace the
lowest existing boundary, not the whole function.

| Stage shape | What gets replaced |
|---|---|
| Goes through `_Provider` | the provider |
| Constructs `google.genai.Client` directly (`extract`, `entities`) | the client |
| Lazily imports a driver class (`neo4j_load`, `neo4j_sync`) | that attribute |

The stub answers deterministically — usually from a CRC of the prompt — so the real logic
still runs, just against fake I/O.

### 2.2 Beware the vacuous arm

A stage that *skips its own prior output* makes its own fixture vacuous: the file on disk is
already patched, so the test compares two empty results and prints PASS.

`anchor_kpi` is that case, which is why its test strips prior anchors first — **by
provenance/method tag, never by edge or node label**, since some of those edges came from
elsewhere and must survive. `provenance` is the contrast case: it re-stamps rather than
skipping, so its live arm is already non-vacuous, and its strip exists to prove the stage
never *reads* its own output.

The block tests carry the same idea explicitly: "writes exactly once" is paired with a
counter-arm showing the separate chain writes three times, so "exactly one" cannot be
trivially true.

---

## 3. What to run after touching what

| You changed | Run |
|---|---|
| `config/schema.json` | `test_schema_contract.py`, then `test_temporal_invariants.py` |
| Stage 03 / 03b / 03c / 05 / 05b / 05c / 08 | `test_temporal_invariants.py` |
| A `core/` helper | `test_esg_kg_equivalence.py` |
| `report/quality.py` | `test_esg_kg_equivalence.py`, `test_standards_audit.py`, `test_quality_hub_set.py` |
| An extraction or repair prompt | the matching language/value guard |
| `esg_kg/pipeline.py` or `run.py` | `test_pipeline_table.py` |
| `gri/` | `test_gri_catalog_build.py` |

---

## 4. The suite

### Contracts

| Test | Covers |
|---|---|
| `test_schema_contract.py` | `config/schema.json`: P1 both ways (T1 identity timeless / T2 observations **keep** their time key), every class in exactly one tier, indicator-axis edge pairs. The tier map is **imported** from `quality.py`, never re-declared |
| `test_pipeline_table.py` | Stage-table well-formedness: unique `old_step` labels, no short-name collisions, block members all migrated, a never-to-be-ported stage rendered as such rather than "not yet" |
| `test_temporal_invariants.py` | Date canonicalization, temporal invariants, `source_id` parsing, DSU consolidation, provenance tier matching + node order, `kpi_id` canonicalization, indicator-axis edge minting, stage-08 stable-id resolution |
| `test_console_utf8.py` | UTF-8 stdout setup on win32 — including the *wiring*, i.e. that `main()` actually calls it and nothing calls it at import |

### Per-stage behaviour

`test_esg_kg_extract.py` (01) · `test_esg_kg_extract_triples.py` (02) ·
`test_esg_kg_fix_triples.py` (03) · `test_esg_kg_anchor_kpi.py` (03b) ·
`test_esg_kg_issuer.py` (04) · `test_esg_kg_entities.py` (05) ·
`test_esg_kg_provenance.py` (05b) · `test_indicator_axis.py` (05c) ·
`test_esg_kg_align_claims.py` (05d) · `test_esg_kg_neo4j_load.py` (06) ·
`test_esg_kg_crosscheck.py` (07) · `test_esg_kg_neo4j_sync.py` (08) ·
`test_esg_kg_claim_ledger.py` (09) · `test_export_kgc.py` (11)

### Blocks

`test_esg_kg_validated_block.py` · `test_esg_kg_resolve_block.py` — each asserts the
artifact is written exactly once, the paid-result cache is hit on a second run, and the
result is identical to running the members separately.

### Kernel

| Test | Covers |
|---|---|
| `test_esg_kg_equivalence.py` | `core/` helpers and the whole Q1–Q8 surface, against golden values on the real corpus, plus a synthetic 20-node graph for the slow Q7 BFS arms |
| `test_esg_kg_llm.py` | `RateLimiter` through a **fake clock** (never really sleeps), and the paid request shape: `temperature=0`, JSON response mode, the system/user split, and `wait_if_needed` *before* the call |
| `test_esg_kg_llm_cache.py` | Content-addressed key derivation, same-run hits, corrupt-file safety |
| `test_esg_kg_gemini_cache.py` | Context-cache memoization and the `cached_content` + `system_instruction` conflict |
| `test_esg_kg_datasync.py`, `test_data_sync_scope.py` | Push/pull scoping; a pull can never overwrite a tracked repo-root file |

### Guards for specific defects

Each of these exists because something real broke:

| Test | The defect |
|---|---|
| `test_step02_language_guard.py` | Extraction prompts drifting into English on Vietnamese source text — which splits one entity into two downstream |
| `test_step01_step07_language_guard.py` | The same defect shape in the KPI and adjudication prompts |
| `test_step03_llm_value_guard.py` | A repair model translating or reformatting a property **value** while fixing a triple's shape |
| `test_claim_id_deterministic.py` | A re-invented `claim_id` silently re-partitioning every already-paid dossier |
| `test_gri_catalog_build.py` | 80 of 136 GRI entries attributed to whichever file sorted first |
| `test_quality_hub_set.py` | "The hub" defined as a single `argmax(degree)`, which breaks with two issuers |
| `test_mentions_facility_edge.py` | `MediaReport → Facility \| Location` anchoring |
| `test_entities_partial_key_merge.py` | Subsumption merge for partially-filled identity keys |
| `test_standards_audit.py` | The audit must surface an uncurated GRI spelling, must **not** surface an out-of-scope accounting standard, must respect a curated exclusion, and must never report `canonical_name` as unknown |
| `test_reasoning_readiness_metrics.py` | R1 / R1′ / R7 and the degenerate-relations loader |

---

## 5. Paid tests, gated off by default

`test_esg_kg_integration_llm.py` chains 01 → 02 → `build_validated` → `issuer` →
`build_resolved` → `align_claims` → `claims_vs_conduct` through the real functions with a
real provider.

`test_esg_kg_system_llm.py` drives the actual `python src/run.py <stage>` CLI commands,
subprocess by subprocess, in the documented order — proving the *command line* entry points
chain, not just the functions.

Both cost money and are **deliberately not part of the free suite**. They run only with:

```bash
RUN_LLM_INTEGRATION_TESTS=1 python test/test_esg_kg_integration_llm.py
RUN_LLM_SYSTEM_TEST=1        python test/test_esg_kg_system_llm.py
```

---

## 6. A note on the docstrings

Many test docstrings describe an old-versus-new *equivalence* check against a `src/`
tree that no longer exists (the flat `stepNN_*.py` layout, deleted 2026-07-29). Those files
were all converted to single-tree tests against `esg_kg` alone — same assertions, same
non-vacuity guarantees. Read "both trees" in a docstring as history, not as what the test
imports today.

The remaining files under `test/` and everything in `notebooks/` are Jupyter notebooks for
manual validation, not part of the assert suite.
