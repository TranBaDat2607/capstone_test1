# Stages 03 / 03b / 03c — validation, anchoring, canonicalization

```bash
python src/run.py build_validated --dry-run     # the normal way: 03 → 03b → 03c
python src/run.py build_validated

python src/run.py fix_triples --renormalize      # P4 date pass only, no LLM
python src/run.py anchor_kpi --dry-run           # preview gazetteer matches
python src/run.py canonicalize --dry-run         # preview kpi_id assignment
```

Modules: `graph/fix_triples.py` · `graph/anchor_kpi.py` · `kpi/canonicalize.py` ·
`graph/build_validated.py`
Output: `graph_output/validated/all_validated_triples.json` (+ `unfixable_triples.json`,
`anchor_patch_stats.json`, `kpi_canonical_stats.json`)

These three stages turn per-page extraction output into one validated, anchored,
canonically-labelled triple set. **Run them as the block.**

---

## 1. Why the block exists

All three read *and* write the same artifact. That intermediate file was never a
deliverable — it is internal state that leaked into being a contract, and it has a
measurable cost. On the AAA corpus the file was:

```
14,492  phase 1, offline        → free to rebuild
+   90  phase 2, LLM            → PAID FOR, and not deterministic
+   95  03b gazetteer anchors   → free to rebuild
= 14,677 triples  (plus 683 kpi_id stamps from 03c)
```

Re-running `fix_triples` alone rebuilds from the page graphs and writes over all of it —
destroying the anchors, the stamps and the 90 paid repairs, with no warning. The only thing
holding the chain together was a log line at the end of each stage: a contract by memory.

`build_validated` chains the three **in memory** and writes the artifact exactly **once**.

### 1.1 Artifact versus cache — the distinction that makes it safe

Dropping the intermediate *artifact* is the point. Dropping the *cache of a paid result*
would be a regression: every block run would re-pay for phase 2, and because the model is
not deterministic it would return something different each time.

| | Answers | Verdict |
|---|---|---|
| Intermediate artifact | "how far did the pipeline get?" | internal state — droppable |
| Cache | "what already cost money?" | not reproducible for free — keep |

So phase-2 repairs go to their own cache, keyed by the **content** of the input triple
(never its position in a batch — batch boundaries move between runs). The cache stores the
model's **raw reply**; `preserve_property_values` is applied on the way out, so the guard
stays our code and improving it also fixes cached repairs.

A second block run calls the LLM zero times and reproduces the identical artifact —
asserted by `test/test_esg_kg_validated_block.py`, together with a non-vacuity arm proving
the separate-stage chain writes the file three times and the block exactly once.

Every member stage stays individually runnable. A block *adds* an entry point; losing the
ability to run one stage alone would lose the ability to diagnose it.

---

## 2. Stage 03 — `fix_triples`

Four phases.

### Phase 1 — offline reconstruction and validation

Reconstruct triples from the per-page `{nodes, edges}` graphs, then validate against
`config/schema.json`. Two behaviours worth knowing:

- **Direction auto-swap.** If a triple's `(source_class, target_class)` pair is illegal but
  the *reversed* pair is legal, the subject and object are swapped rather than the triple
  discarded. The extractor confuses direction often enough that repairing is cheaper than
  losing the fact.
- **Any legal pair counts.** A label may have several legal pairs; the validator accepts a
  match against any of them.

Output: valid triples, plus an invalid set for phase 2.

### Phase 1.5 — temporal canonicalization (P4)

Offline, no LLM:

- every date normalized to ISO `YYYY[-MM[-DD]]`;
- `valid_from > valid_to` flagged;
- a missing `date_uncertain` defaulted on news-derived T2 nodes.

`--renormalize` runs **only this phase** against the existing aggregated file. It is the
safe way to re-apply date rules without touching the LLM or losing prior repairs.

The bug that motivated P4: one node had two `temporal_versions` both `is_current = true`
and both `valid_to = null`, differing only as `"2011"` versus `"2011-01-01"` — one fact
split into two fake versions.

### Phase 2 — LLM repair

The invalid triples are batched and sent for repair against the schema, then re-validated;
whatever is now valid is kept, the rest goes to `unfixable_triples.json`. Gemini only —
no provider flag on this stage.

**`preserve_property_values` is the guard that matters.** Phase 2 may repair a triple's
*shape* — its class, predicate or temporal fields — but must never translate, reformat,
invent or drop a property **value**. Since extraction now emits Vietnamese names and
titles, an English-instructed repair model "fixing" a Vietnamese name would silently split
one entity into two during resolution. The guard restores altered values, drops invented
ones, and permits the shape changes the repair is for.

`BATCH_FIX_PROMPT` is pinned byte-for-byte by tests, for the same reason as the extraction
prompts.

### Phase 3 — aggregate

Write `all_validated_triples.json` and `unfixable_triples.json`.

### Flags

`-i` · `-s` · `-o` · `--batch-size` · `--rate-limit` · `--model` · `--dry-run`
(phase 1 only, no LLM, no writes) · `--renormalize` · `--no-context-cache`

---

## 3. Stage 03b — `anchor_kpi`

Offline structural anchoring, no LLM. Implements P3 for data that was already extracted and
paid for.

```
1. build a gazetteer of Facility names already present in the validated graph
2. for each KPIObservation, resolve its source sentence via source_id
   ("<source_pdf>_<page>_<sentence_index>") against the labeled JSONL
3. if the sentence literally names a known facility (Vietnamese-normalized,
   word-bounded match) emit the edge the extractor should have made:
       KPIObservation --observedAtFacility--> Facility
   with the KPI's own event time as the edge's temporal_metadata and
   anchor_method="offline_gazetteer" for auditability
```

No new classes and no new edge labels — only edges the schema already defines.

**What it deliberately cannot do:**

- Location names cannot be attached: the schema has no `KPIObservation → Location` edge,
  by design.
- `Penalty → Authority` (`enforcedBy`) cannot be patched offline, because `Penalty` nodes
  carry no sentence-level `source_id`.

Both are covered going forward by the extraction prompt instead. Extending the gazetteer to
news event classes is blocked on adding schema pairs — [ROADMAP.md](ROADMAP.md) §2.3.

`--max-per-facility` caps how many anchors one facility may absorb, a hub guard the live
data does not currently trip.

Flags: `-i` · `-s` · `--sentences` · `--max-per-facility` · `--stats-out` · `--dry-run`

---

## 4. Stage 03c — `canonicalize`

Offline, no LLM. Assigns each `KPIObservation` a canonical `kpi_id` from the 35-indicator
vocabulary, plus unit normalization and a `Goal.target_date` backfill.

Design detail and the alias/precision rules are in
[STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) §5.2. The three properties to
remember:

1. **It writes a NEW property `kpi_id` and never rewrites `kpi_type`.** `kpi_type` is the
   raw wording from the page; `kpi_id` is the code it maps to. Overwrite the raw value and
   a wrong mapping can never be traced back to what the report said.
2. **Precision over recall.** Financial KPIs in VND are rejected outright via
   `reject_units`, not force-mapped. Unmatched nodes keep `kpi_id = null`.
3. **Every node records which rule decided**, in `kpi_id_method` — `alias_exact` is
   curated, `fuzzy_NN` is a guess, `rejected_unit` is a deliberate refusal, `no_match` is a
   dictionary hole. Only the last is a backlog item, and on the AAA corpus the two were
   2,913 versus 1,368.

The `Goal.target_date` backfill is a Vietnamese regex over `name + description`
(`đến/vào/trước/tới năm 20XX`, `giai đoạn 20XX–20YY`, `by 20XX`), applied only when the
field is empty and only for **future** years, so a year mentioned in passing cannot become
a target. Goals with no `target_date` after the backfill are slogans, not promises.

The fuzzy tier needs `rapidfuzz`, deliberately absent from `requirements.txt`; without it
the tier is disabled with a warning and everything else still runs.

Flags: `-i` · `--defs` · `--aliases` · `--fuzzy-threshold` · `--no-goals` · `--stats-out`
· `--dry-run`

---

## 5. Running order and re-runs

```
graphs/ ──▶ 03 fix_triples ──▶ 03b anchor_kpi ──▶ 03c canonicalize ──▶ all_validated_triples.json
            └──────────────── build_validated writes ONCE ─────────────┘
```

| Situation | Do this |
|---|---|
| Normal rebuild | `build_validated` |
| Date rules changed only | `fix_triples --renormalize` |
| New facility names appeared | `anchor_kpi` (it is idempotent) |
| Alias dictionary grew | `canonicalize` |
| Diagnosing one stage | run that stage alone, on a copy |

Never run `fix_triples` alone against a file that 03b/03c have already patched unless you
intend to lose their output.

---

## 6. Tests

| Test | Covers |
|---|---|
| `test/test_esg_kg_fix_triples.py` | The real corpus (43 doc dirs / 1,370 page files) through phase 1 offline; phase 2 via a stubbed tampering LLM; `BATCH_FIX_PROMPT` pinned |
| `test/test_step03_llm_value_guard.py` | `preserve_property_values` — behaviour *and* wiring, red-first against the unguarded version |
| `test/test_esg_kg_anchor_kpi.py` | 03b on the real corpus with prior anchors stripped (without the strip the arm compares two empty results), plus a hub-guard arm and an idempotency arm |
| `test/test_esg_kg_validated_block.py` | The block writes exactly once; the separate chain writes three times; a second run calls the LLM zero times |
| `test/test_temporal_invariants.py` | Date canonicalization, temporal invariants, `source_id` parsing, `kpi_id` canonicalization |

Run `test/test_temporal_invariants.py` after touching any of 03 / 03b / 03c.
