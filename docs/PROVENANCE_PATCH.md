# Stage 05b — provenance patch

```bash
python src/run.py provenance --dry-run     # preview coverage
python src/run.py provenance               # stamp resolved_graph.json in place
```

Module: `src/esg_kg/resolve/provenance.py` · Output: patches
`graph_output/resolved/resolved_graph.json` in place (+ `provenance_patch_stats.json`)

Offline, no LLM, no database. Restores the "which document and page did this node come
from" context that aggregation drops, so the ledger and the UI can cite a report page or an
article by name.

Runs **after** `entities` (05), **before** `neo4j_load` (06). Re-run it after any `entities`
re-run. Normally executed as part of the `build_resolved` block.

---

## 1. The problem it solves

Sentence-level traceability (`source_pdf`, `page`, `sentence_index`) is a core principle of
the pipeline, but the stage-03 aggregation drops the per-page file context. Resolved nodes
keep only the model's free-text `source` (for claims) or a partially-parseable `source_id`
(for KPIs).

The per-page extraction files `graph_output/graphs/<doc>/page{N}.json` still exist, and
their **path encodes exactly the document and page** every node was extracted from. This
stage matches nodes back to those files.

---

## 2. How it works

```
1. index every page-file node by its stable_id and by its raw
   properties.source_id  →  {(doc, page)}

2. for every claim/evidence node in resolved_graph.json (PROVENANCE_CLASSES only —
   never T1 entities, which recur on dozens of pages), match it back through a
   4-tier precedence and stamp source_doc / source_page / provenance_method

3. for news docs (TICKER__domain__hash), also stamp article_title / article_url /
   source_domain from the news JSONL corpora
```

### 2.1 The four matching tiers

Tried in order; the first hit wins and is recorded in `provenance_method`:

| Tier | Method | Notes |
|---|---|---|
| 1 | Parseable `source_id` | `<source_pdf>_<page>_<sentence_index>` — the cheapest and most reliable |
| 2 | Exact `source_id` index lookup | For ids that do not parse but appear verbatim in a page file |
| 3 | Recomputed `stable_id` | Re-derive the node's identity hash and look it up |
| 4 | `_pageNN_` token | Last resort: a page token embedded in the id string |

Recording *which* tier matched is not cosmetic. It is the same rule as `anchor_method` in
03b and `kpi_id_method` in 03c: a wrong stamp must be traceable to the rule that made it.

### 2.2 Which nodes get stamped

`PROVENANCE_CLASSES` — claim and evidence nodes only. **Never T1 entities.** An
`Organization` legitimately appears on dozens of pages, so stamping it with one
`source_page` would be a lie, not a citation.

On the current snapshot the stamped classes are `KPIObservation` (6,560),
`SustainabilityClaim` (481), `MediaReport` (127), `Certification` (78), `Emission` (17),
`Penalty` (11), `Waste` (11) and `ThirdPartyVerification` (2).

### 2.3 News enrichment

For documents whose stem matches the news naming convention `TICKER__domain__hash`, the
stage additionally reads the news JSONL corpora and stamps `article_title`, `article_url`
and `source_domain`. This is what lets a UI card say *"vietnamnet.vn — «Khai sai thuế…»"*
rather than showing an opaque id, and it is what the self-verification guard in the
cross-check reads.

---

## 3. Hard invariant — the node array is never restructured

**Only `properties` dicts are mutated.** The node array is never grown, shrunk, or
reordered.

`neo4j_load` keys Neo4j nodes by array index (`_node_key = f"n{i}"`), and the cross-check
dossiers reference nodes by `node_index` / `claim_node_index`. Any reordering would
silently corrupt the advisory layer — every edge bound to the wrong node, with no error.

A dedicated test arm asserts node order is preserved.

---

## 4. It never reads its own output

None of the keys this stage writes appears in any `identity_keys`, and the stage
re-stamps rather than skipping. So stripping every stamp and rebuilding must produce an
identical result — which is exactly what `strip_provenance()` in the test proves. This is
the *contrast* case to `anchor_kpi`, which does skip its own prior output and therefore
needs its fixture stripped just to be non-vacuous.

One thing it does skip: nodes already stamped `provenance_method = "extraction"`. New
extraction output self-stamps, and re-deriving it would be pointless work.

---

## 5. Flags

| Flag | Meaning |
|---|---|
| `-i` | Resolved graph to patch |
| `--graphs-dir` | Where the per-page extraction files are |
| `-s` | Schema path |
| `--news-globs` | Glob patterns for the news JSONL corpora used for article enrichment |
| `--stats-out` | Where to write the stats file |
| `--dry-run` | Report coverage, write nothing |

---

## 6. Reading the stats file

`provenance_patch_stats.json` reports per class and per method, plus:

- `multi_location_nodes` — nodes matching more than one (doc, page). Non-zero means the
  matcher is ambiguous for those nodes and the first tier that hit may be arbitrary.
- `news_meta_missing` — news docs whose JSONL could not be found for enrichment.
- `sample_unmatched_source_ids` — the head of the unmatched tail, for diagnosing whether
  the gap is a naming convention change or genuinely missing page files.

A run where every class shows only `already_stamped` and `per_method` is empty means
nothing needed re-stamping — the expected result on an unchanged graph.

---

## 7. Tests

`python test/test_esg_kg_provenance.py` — the live-graph arm compares thousands of stamps;
`strip_provenance()` proves the stage never reads its own output; a node-order arm guards
the array-index invariant; and a synthetic arm covers the
`provenance_method="extraction"` skip that no live node exercises.

`python test/test_temporal_invariants.py` also covers the tier matching and the node-order
invariant.
