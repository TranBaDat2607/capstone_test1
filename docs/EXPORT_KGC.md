# Stage 11 — hub decomposition into an export view

```bash
python src/run.py export_kgc --dry-run     # preview stats, write nothing
python src/run.py export_kgc               # write graph_output/export_kgc/
```

Module: `src/esg_kg/export/export_kgc.py` · Input:
`graph_output/resolved/resolved_graph.json` (**read-only**) · Output:
`graph_output/export_kgc/` (+ `export_kgc_stats.json`)

Offline, no LLM. Produces a **separate derived artifact** in which the issuer hub's degree
is reduced, for use by a future path-reasoning / RL layer. It never patches
`resolved_graph.json` and never touches Neo4j.

Run after `build_resolved`.

---

## 1. The problem

The issuer node is the graph's dominant hub — on the pinned 5-company snapshot one cluster
carries degree 5,300, and on a fuller AAA extraction it measured 9,511, about two-thirds of
all edges. This is what makes R5 (the max-degree gate of ≤ 500 in
[TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) P5) fail.

Scaling to more companies does **not** fix it: each company simply contributes its own star.

A bounded-degree walker sampling uniformly over thousands of neighbours has a few percent
chance of keeping the one neighbour that leads to evidence — it effectively dies at the
first hop, before learning anything.

---

## 2. Why an export view and not an in-place fix

`core/graph_patch.py`'s `assert_append_only` and `neo4j_load`'s array-index keying both
depend on `resolved_graph.json`'s node order never being restructured in place. Restructuring
the hub would invalidate every already-paid cross-check dossier, which references nodes by
position.

This is the same boundary P6 already established for inverse edges: **dataset-level
transforms live in the export tier only**. The stage reads its input read-only and writes a
wholly separate file; a real-corpus test arm asserts that `resolved_graph.json`'s bytes on
disk are unchanged after the stage runs.

---

## 3. What it does

```
for each Organization cluster matching config/issuer_registry.json:
    if summed cluster degree > --max-bucket-degree (default 500):
        group its edges by (year, predicate)
        mint one synthetic HubBucket node per group
        rewire: hub --▶ HubBucket --▶ original targets
```

The hub's own degree drops to **one edge per bucket**. Clusters below the threshold — smaller
companies — pass through unchanged.

Verified on the real AAA graph: **max degree 9,511 → 542** across 357 buckets.

### 3.1 Hub detection reuses the quality machinery

The stage imports `esg_kg/metric/hub.py`, the same multi-issuer cluster code that
`report/quality.py` uses for R5 and Q7(d), rather than reimplementing hub detection. So this
stage's notion of "hub" always agrees with the quality report's.

That machinery follows the **registry**, not `argmax(degree)`: a hub is every node matching
an issuer alias. With one issuer in the registry the two definitions coincide by accident;
with two, each forms its own high-degree star and neither is the global maximum, so a path
routed through issuer B's hub would wrongly count as hub-free.

### 3.2 Honest reporting instead of a forced fit

v1 buckets by `(year, predicate)` only — no third key. Some buckets still exceed the
threshold (the single largest AAA bucket, 2022 × `reportsKPI`-class, is over 500). The stats
file reports this as `buckets_over_threshold` and `threshold_met: false` rather than
escalating to a third key to make the number look right.

Stating what the transform did not achieve is the point. A silently-satisfied threshold
would be worse than a reported failure.

### 3.3 Everything synthetic is flagged

Every minted node and every rewired edge carries `is_synthetic: true`. This is P7: a bucket
hop carries no source sentence, so it must never be presented as a citable reasoning step.
A test asserts the flag on all of them.

### 3.4 `HubBucket` is not in the schema

Deliberately absent from `config/schema.json`. It is a dataset-construction artifact, not a
T1/T2/T3 entity, and the schema stays the source of truth for the real graph only. A test
asserts the string never appears in `schema.json`.

---

## 4. Flags

| Flag | Meaning |
|---|---|
| `-i` | Resolved graph (read-only) |
| `--issuer-registry` | Registry used for hub-cluster identification |
| `--max-bucket-degree` | Threshold above which a cluster is decomposed (default 500) |
| `-o` | Output path |
| `--stats-out` | Stats file path |
| `--dry-run` | Compute and report stats, write nothing |

---

## 5. Reading the stats

Per ticker: node and edge counts, bucket count, bucket size distribution,
`buckets_over_threshold`, degree before and after. Globally: `max_degree_after` and
`threshold_met`.

If `threshold_met` is `false`, the export is still usable — it just means a bounded-degree
consumer will need its own policy for the remaining oversized buckets, which is exactly what
P5's factored action space is for.

---

## 6. Scope

This is **only the hub-decomposition piece** of a future step 11, not its full design. The
reasoning layer it feeds does not exist; its design and the measurements behind it are in
[SSRL_REASONING_LAYER.md](SSRL_REASONING_LAYER.md) (§5.7 for where this stage sits in that
plan). See also [ROADMAP.md](ROADMAP.md) §2.7.

---

## 7. Tests

`python test/test_export_kgc.py` — a synthetic two-issuer fixture proves the property that
matters for scaling: a bucketed ticker's nodes and edges never leak into an untouched
ticker's. Plus input purity (the input lists are never mutated in place), determinism (two
runs, byte-identical output), `is_synthetic` on everything minted, and the schema-absence
check. The real-corpus arm asserts an order-of-magnitude degree reduction **and** that
`resolved_graph.json` is unchanged on disk; it skips gracefully when the data snapshot is
not present.

`python test/test_quality_hub_set.py` and `python test/test_reasoning_readiness_metrics.py`
cover the shared hub and readiness machinery.
