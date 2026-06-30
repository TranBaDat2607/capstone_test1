# Entity Resolution (Step 4) — Implementation Plan

Build checklist for `src/resolve_entities.py`, the next stage after
[`src/fix_invalid_triplets.py`](src/fix_invalid_triplets.py). This file is the
*engineering* plan; the *explanatory* writeup lives in
[`docs/ENTITY_RESOLUTION.md`](docs/ENTITY_RESOLUTION.md).

> Status: **implemented.** Two scripts — `src/build_issuer_registry.py` (issuer-registry
> bootstrap) and `src/resolve_entities.py` (the resolver). Full design writeup in
> [`docs/ENTITY_RESOLUTION.md`](docs/ENTITY_RESOLUTION.md).
>
> **As-built deltas from the original sketch below:**
> - The issuer anchor is a **bootstrapped registry** (`config/issuer_registry.json`), not a
>   raw xlsx-name match: `build_issuer_registry.py` auto-classifies each Organization name into
>   `aliases` / `exclusions` / `needs_review` from structural (subject-of-report-edge counts) +
>   lexical signals; a human confirms `needs_review`. This was required because AAA's official
>   name isn't even among its top variants (it was renamed) and `An Phát Holdings` is a separate
>   listed entity. The resolver merges aliases into one **frozen** issuer cluster.
> - The entity/observation split is declared in `resolve_entities.py` (`OBSERVATION_CLASSES`);
>   only `identity_keys` come from `schema.json` (the schema has no observation flag).
> - Default `--similarity-threshold` is **0.92** (short ESG names → ~136k candidate pairs at
>   0.86); deterministic stages A + B.1 carry the load, `--max-llm-pairs` caps Stage-C cost.
> - Stage B is split into **B.1** (free normalized-signature merge) and **B.2** (embedding).
> - AAA POC result: 13,696 graph nodes → 10,330 resolved; issuer 536 raw → 1 node (305 versions,
>   1999→2025); `An Phát Holdings` stays separate; 562 multi-year edges preserved.

---

## 1. Context / problem

Per-page triple extraction emits the **same real-world entity once per page it is
mentioned on**. After `fix_invalid_triplets.py` flattens 13 AAA annual reports into
one `all_validated_triples.json`, the issuer "An Phát" appears as dozens of duplicate
`Organization` nodes — identical Vietnamese strings differing only by `valid_from`, an
English-language variant, and OCR-garbled variants (`MÔI TRƢỜNG`). Entity resolution
collapses these into one canonical node **without losing temporal history**, so a
company's *reported* claims and its *real-world* conduct attach to the same node — the
backbone of the greenwashing cross-check.

The EmeraldKG reference (`EmeraldMind/src/EmeraldKG/4-entity_resolution.py`) does this
with local Ollama embeddings + an LLM, but a verbatim port does **not** fit:

- it ignores `config/schema.json`'s `identity_keys` (the schema's whole dedup mechanism);
- it is English-biased (`nomic-embed-text`) — wrong for Vietnamese / cross-lingual / OCR text;
- it is O(n²) blocking + O(k²) LLM calls — costly on a metered Gemini key;
- its edge-merge keys on `(subject, predicate, object)` and **drops multi-year
  `temporal_metadata`** — data loss for the trend analysis greenwashing depends on;
- it needs a local Ollama server, not the project's single `GEMINI_API_KEY`.

So this is a **hybrid redesign**, not a port: deterministic `identity_keys` merge +
ticker anchor first, Vietnamese-aware fuzzy matching only on the survivors, Gemini for
both embeddings and adjudication.

---

## 2. Inputs & outputs

**Input:** `graph_output/validated/all_validated_triples.json` — flat array of
schema-valid triples (`subject`/`predicate`/`object`/`temporal_metadata`).

**Outputs (new sibling dir `graph_output/resolved/`):**

```
graph_output/resolved/
  resolved_graph.json         ← {nodes, edges}; merged nodes carry temporal_versions[]
  resolved_graph_stats.json   ← reduction %, merges, LLM comparisons/matches, versions preserved
```

---

## 3. Algorithm (implementation checklist)

1. **Load + build graph.** Read the validated triples; dereference into `{nodes, edges}`.
   Input is already schema-valid, so run `validate_triple` only as a cheap optional guard
   (default off, behind a flag), not a full re-validation pass.
2. **Stage A — deterministic `identity_keys` merge (free, precise).**
   - [ ] Derive `entity_classes`, `observation_classes`, and the per-class `identity_keys`
     map **from `schema.json`** (no hardcoded sets).
   - [ ] Compute a stable signature per node from its `identity_keys`; exact-signature
     collisions merge immediately (entities *and* observations — e.g. same KPI by `source_id`).
   - [ ] **Ticker anchor for the issuer Org:** derive the ticker from the source-file stem
     (`AAA_Baocaothuongnien_2011` → `AAA`); look up the official name in
     `config/company_annual_report.xlsx` (`Mã CK`→`Tên công ty`); merge issuer-Org variants
     under a ticker-stamped canonical identity. Non-issuer orgs are left to Stages B–C.
3. **Stage B — Vietnamese-aware fuzzy candidate generation (survivors only).**
   - [ ] `normalize_vn_name`: strip legal forms (`Công ty Cổ phần`/`CTCP`/`JSC`/
     `Joint Stock Company`/`Tập đoàn`/…), repair OCR artifacts (`Ƣ→Ư`, `Ơ` family),
     casefold + strip diacritics for blocking keys.
   - [ ] Block by normalized key; within a class, `gemini-embedding-001` cosine similarity
     (batched, `task_type=SEMANTIC_SIMILARITY`) groups near-duplicates above a threshold.
4. **Stage C — Gemini adjudication on ambiguous pairs only.**
   - [ ] `gemini-2.5-flash` with **structured-output boolean** (`response_schema`), not
     string parsing. VN-flavored prompt examples (`CTCP X` vs `X JSC` = same;
     `Sở TN&MT tỉnh A` vs `tỉnh B` = different).
   - [ ] Throttle via the shared `RateLimiter`.
5. **Stage D — build resolved graph.**
   - [ ] Consolidate each cluster; keep a `temporal_versions` array of all versions.
   - [ ] **Deterministic canonical** pick: has-ticker > most-complete props > longest name
     (never "first in list").
   - [ ] Rewire edges with **year-aware keys** `(subj, pred, obj, year)` so multi-year
     entity→entity edges are preserved, not collapsed.
   - [ ] Write `resolved_graph.json` + `resolved_graph_stats.json`.

---

## 4. Module layout (`src/resolve_entities.py`)

**Reuse (import, don't re-implement):**
- `REPO_ROOT` from `extract_kpi_from_jsonl`
- `RateLimiter` from `extract_triplet_from_jsonl`
- `load_schema_sets`, `validate_triple` from `fix_invalid_triplets`

**New functions:**
- `load_identity_keys(schema)` → `{class: [keys]}`, plus entity/observation class sets
- `identity_signature(node, identity_keys)` → stable string
- `normalize_vn_name(s)` → blocking-normalized name
- `derive_ticker(source_id_or_stem)` and `load_company_aliases(xlsx)` → `{ticker: [names]}`
- `embed_batch(texts, client, rate_limiter)` → vectors (`gemini-embedding-001`)
- `gemini_is_same_entity(a, b, client, rate_limiter)` → bool (structured output)
- `build_resolved_graph(graph, clusters, observation_indices)` → `{nodes, edges}`

---

## 5. Schema-derived sets

`config/schema.json` gives every node `identity_keys`. Resolution behaviour comes
straight from the schema, so adding a class (e.g. the planned `DisclosureRequirement`,
`ComplianceObligation` from `docs/VIETNAM_IMPROVEMENT_PLAN.md`) needs **no code change**.
Observation classes (versioned per-observation) vs resolvable entities are inferred from
the schema rather than the two hardcoded sets EmeraldKG ships.

---

## 6. CLI & defaults

```bash
python src/resolve_entities.py \
  -i graph_output/validated/all_validated_triples.json \
  -s config/schema.json \
  -o graph_output/resolved/
```

| Flag | Default | Meaning |
|------|---------|---------|
| `-i, --input` | `graph_output/validated/all_validated_triples.json` | Validated triples |
| `-s, --schema` | `config/schema.json` | Schema (classes + `identity_keys`) |
| `-o, --out-dir` | `graph_output/resolved/` | Output dir |
| `--companies` | `config/company_annual_report.xlsx` | Ticker→name for issuer anchor |
| `--similarity-threshold` | `0.85` | Embedding cosine cutoff for Stage B |
| `--rate-limit` | `10` | Max RPM for embeddings + adjudication |
| `--model` | `gemini-2.5-flash` | Adjudicator |
| `--embed-model` | `gemini-embedding-001` | Embedder (3072-dim, multilingual) |
| `--dry-run` | off | Stages A–B only (no LLM, no writes): see how much the free identity-key merge alone achieves |

---

## 7. Cost / scale notes

- Stage A (identity-key merge + ticker anchor) is free and collapses the bulk of duplicates
  for a single-company POC, so `n` entering Stages B–C is small.
- Observations (≈345 KPIs/report × 13) are deduped by key, never embedded or sent to the LLM.
- Embeddings are **batched** and rate-limited; the adjudicator runs **only on ambiguous
  survivor pairs**, not all pairs — keeping the run inside the Gemini free tier for the POC.

---

## 8. Open items / future

- `supersedes` edges as an alternative/addition to inline `temporal_versions` (depends on the
  graph-backend decision — `VIETNAM_IMPROVEMENT_PLAN.md` open question #1).
- Cross-source resolution: fold the news channel (`data/outputs/news/<TICKER>.jsonl`) into the
  same ticker anchor so controversies attach to the issuer node.
- Multi-company batch run once the POC validates on AAA.

---

## 9. Verification

```bash
# Free pass only — how much does identity-key + ticker anchor merge on its own?
python src/resolve_entities.py --dry-run

# Full run on AAA
python src/resolve_entities.py
```

Eyeball checks on `graph_output/resolved/`:
- the AAA issuer collapses to **one** `Organization` node carrying the ticker, with a
  `temporal_versions` array spanning 2011→2025;
- a non-issuer org (e.g. `Trung ương hội Doanh nhân trẻ Việt Nam`) is **not** merged into AAA;
- multi-year entity→entity edges survive (count of distinct years preserved);
- `resolved_graph_stats.json` shows the node reduction and how many merges were free
  (identity-key) vs LLM-adjudicated.
