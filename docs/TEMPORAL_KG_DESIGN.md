# Temporal knowledge-graph design principles

**Audience:** anyone about to touch `config/schema.json`, an extraction prompt,
`fix_triples`, or `entities`. Read this before, not after.

This document holds two things: **eight design principles (P1–P8)** that the schema and
the pipeline are built to respect, and **eight quality attributes (Q1–Q8)** plus three
reasoning-readiness metrics (R1/R5/R7) that `quality` (stage 00) measures on every run.

Sections §2 and §4 are referenced from source-code docstrings — keep those numbers stable.

> **Working rule:** run `python src/run.py quality --label before-<change>` before a
> schema or pipeline change and `--label after-<change>` after it. The stage is offline
> and free; there is no excuse for an unmeasured change.

---

## 1. Why principles rather than a list of fixes

The graph had a recurring symptom: it behaved like *two graphs stacked on one plane*.
A dense, walkable structural core, and a large cloud of leaf nodes hanging off a single
hub. Fixing that node-by-node never held, because the cause was not any single node — it
was that three genuinely different kinds of node were being modelled with the same rules.

The principles below all follow from separating those kinds (§2) and then respecting the
boundary.

---

## 2. The three-tier node model

| Tier | Nature | Classes | Identity rule | Time rule |
|---|---|---|---|---|
| **T1 — Identity** | "what / who" — exists independently of any document | `Organization`, `Person`, `Facility`, `Product`, `Material`, `Location`, `Country`, `Standard`, `Regulation`, `Authority`, `Community`, `ClaimKeyword`, `Certification`, `StandardIndicator` | **Timeless** (P1): the key is the normalized name (+ jurisdiction where needed) | Property changes produce `temporal_versions` / `supersedes`. **Never** fork a node per observed year |
| **T2 — Event / Observation** | "what happened or was measured, and when" | `KPIObservation`, `Emission`, `Waste`, `Penalty`, `Controversy`, `MediaReport`, `ThirdPartyVerification`, `Investment`, `Project`, `Initiative`, `CarbonOffsetProject` | One node per occurrence — **time is part of the identity** | `valid_from` = when the event happened; `date_uncertain` when a publish date had to stand in |
| **T3 — Assertion** | "someone *said* something" | `SustainabilityClaim`, `Goal`, `ScienceBasedTarget` | One node per utterance, bound tightly to its source | Two axes: when it was said (`recorded_at`) and what period it speaks about (`valid_from`) |

`Certification` straddles T1 and T3: *the ISO 14001 certificate type* is T1, while *AAA
holding it 2021–2024* is an assertion. The resolution is to keep the node T1 (key
`["name"]`) and put the holding period on the `holdsCertification` **edge**.

The value of the table is that **each tier has different rules** for identity keys,
versioning, and its role in traversal. Every principle below is a consequence of holding
that boundary.

---

## 3. The eight principles

### P1 — Identity is timeless

> **A T1 node is identified by what it *is*, never by when we happened to see it.**

The violation this fixed: `Standard.identity_keys` once included `valid_from`, so "GRI"
became a separate node per reporting year and 94% of `Standard` nodes were isolated
leaves.

Two rules that came out of it, and are now enforced:

1. **Location keeps `country` in its key.** Companies here have export operations and
   foreign subsidiaries; dropping `country` would merge same-named places across borders.
   Domestic same-name collisions are handled by region normalization, not by weakening the
   key.
2. **Every future T1 class is forbidden from putting a time field in `identity_keys`.**
   This is a design invariant, not a one-time repair — `quality` lints it (Q2) and
   `test/test_schema_contract.py` asserts it.

### P2 — Time lives on statements, not on entities

> **A time-bounded fact is an edge carrying `temporal_metadata` — the quadruple
> `(s, r, o, t)` — or a T2/T3 node. T1 nodes carry no time.**

This principle legitimized what the data had already converged on: on the resolved graph
essentially every edge carries `temporal_metadata.valid_from`, while node-level time
survives only inside `temporal_versions`. Dropping `valid_from` from a T1 identity key
does not lose the period — it moves it to the edge (`adoptsStandard`,
`holdsCertification`), where the schema already had a slot for it.

### P3 — Every event node needs ≥ 2 structural anchors

> **When the source text allows it, a T2 node must be anchored to at least two distinct
> T1 nodes: the organization, plus one of facility / location / authority / product /
> partner.**

This is the principle that attacks the leaf cloud at its root. The evidence for it is
internal to this graph: `Investment` is keyed `[investor, investee, date]` and wired at
both ends, and about half of those nodes have degree ≥ 2 — while `KPIObservation`, wired
only as `Organization —reportsKPI→ KPI`, sat at a few percent. Same pipeline, same model:
the nodes *designed* with two anchors are the ones that are reachable.

Two mechanisms implement it:

- **For new extractions** — the `extract_triples` prompt requires the model to attempt the
  anchor edges the schema already defines (`observedAtFacility`, `locatedIn`,
  `enforcedBy`, `mentionsProduct`, `manufacturedAt`) whenever the sentence names a
  facility, place or authority. No new classes, no new labels.
- **For already-paid data** — `anchor_kpi` (03b) patches offline: the source sentence is
  still recoverable via `source_id`, so a gazetteer of `Facility` names already in the
  graph is matched against it, emitting the edge the extractor should have made, tagged
  `anchor_method=offline_gazetteer`.

Measured by Q7(e). Still the biggest open gap — see the status table in §5.

### P4 — Temporal integrity is a hard constraint, not a convention

> **Bitemporal invariants are machine-checked in `fix_triples`, exactly like schema
> validation:** `valid_from ≤ valid_to`; every version chain has **exactly one**
> `is_current = true`; every date is normalized to one format; `date_uncertain` is
> mandatory on news-derived T2 nodes.

The violation that motivated it: an `Organization` node with two `temporal_versions` both
`is_current = true` and both `valid_to = null`, differing only in date format — `"2011"`
versus `"2011-01-01"`. One fact split into two fake versions, which corrupts Cypher
results and manufactures phantom paths for any traversal metric.

`fix_triples` phase 1.5 implements it: ISO `YYYY[-MM[-DD]]` canonicalization, an
`is_current` invariant, a `valid_from > valid_to` warning, and a refusal to treat two
format-variant versions as distinct. The principle for conflicting facts is *invalidate,
do not delete*: close the older version's `valid_to` and use `supersedes` consistently.

### P5 — Degree governance: every hub needs a policy

> **No node enters a reasoning action space without a degree policy: a degree cap,
> exclusion from the action space, or hierarchical (relation-first) action selection.**

The largest hub is the **issuer node itself** — on the pinned AAA snapshot, one cluster
with degree 5,300 (it has measured as high as 9,511 on a fuller extraction). Nearly every
useful claim → conduct path steps through it at the first hop. A path-reasoning agent
that samples uniformly over thousands of neighbours effectively dies at hop 1, and adding
more companies makes this *worse*, not better: each issuer contributes its own star.

Two responses, at two different layers:

- **Reasoning layer (unbuilt):** factored action selection — choose the *relation* first
  (~48 labels), then the target within that group. This turns degree 5,300 into
  48 × ~110. It is a trainer-side policy; the Neo4j graph is untouched.
- **Export layer (built):** `export_kgc` decomposes hub clusters into synthetic
  `HubBucket` nodes keyed by (year, predicate) for the export view only — never patching
  `resolved_graph.json` or Neo4j. See [EXPORT_KGC.md](EXPORT_KGC.md).

**Reference nodes get the same policy.** `StandardIndicator` nodes are deliberately
high-degree — every KPI of an indicator hanging off one node is the entire point of the
join. But they are *vocabulary*, not entities, so `quality` excludes them from the
hub-free Q7 metrics via `REFERENCE_CLASSES`. Without that exclusion the new `partOf`
edges — already in `STRUCTURAL_EDGES` — would inflate Q7(d) by construction and make the
before/after comparison across the indicator-axis change meaningless.

### P6 — Bidirectional traversal belongs to the dataset layer, not the database

> **Inverse edges are generated only in the KGC dataset exported for a reasoning layer.
> They are never written to Neo4j or to `resolved_graph.json`.**

Neo4j already traverses backwards in Cypher (`<-[:claims]-`); writing inverse edges into
the database would break existing queries and double the edge count in every document
already written. An RL walker, by contrast, genuinely needs them explicit in its action
space. So they live in the export tier, with an `_inv` naming convention and an
`is_inverse` flag.

This is the same boundary `export_kgc` respects for `HubBucket`, and the reason
`assert_append_only` exists in `core/graph_patch.py`.

### P7 — Provenance is a first-class property at every layer

> **Every node and edge keeps `source_type`, `source_id`, `page`, `sentence_index`,
> `source_domain` — and every *derived inference*, including a reasoning path, must carry
> the provenance of each individual edge it traverses.**

The pipeline already does the node/edge half well, and that is a real strength to
preserve. The extension that matters for any future path evidence: serialize the list of
**edges with per-edge provenance**, not just a list of nodes. The sellable property of
path evidence is that a reader can check each step back to the sentence that produced it.

This is also the anti-hallucination fence: the adjudicating model only ever judges the
text of the nodes at each end. The path is found by traversal, the text is supplied by
provenance, and the model cannot invent a link.

`export_kgc` follows the same rule from the other side: a synthetic bucket hop carries no
source sentence, so every synthetic node and edge is flagged `is_synthetic` rather than
presented as a citable step.

### P8 — Temporal masking must be applied consistently

> **The same temporal mask applies in all three places: (a) label generation, (b) training
> action space, (c) inference action space. The mask uses both axes — `valid_from` (when
> it happened) and `recorded_at` (when it became known).**

The trap this closes: masking the action space at inference while generating supervision
labels on the *unmasked* graph teaches the model paths it will later be forbidden to take.
That distribution mismatch makes the supervised phase actively counterproductive.

The two-axis part is specific to this problem. "What had happened by 2021?" and "what was
*known* by 2021?" are different questions, and for greenwashing the second is the causally
correct one: a 2021 report cannot be accused of contradicting information that only
surfaced in 2024.

Temporal action-space constraints on temporal KGs are not novel in themselves (TITer /
TimeTraveler, EMNLP 2021). What is defensible as this project's contribution is the
combination: dense BFS-style labels in a *temporal* setting, a *bitemporal* two-axis mask,
and relation-balanced labels.

---

## 4. Quality attributes — what is measured, and where

`python src/run.py quality --label <name>` writes
`graph_output/quality/quality_report_<label>.{json,md}`. Offline, no LLM, no database, no
writes outside the output directory.

| # | Attribute | Definition here | Metric |
|---|---|---|---|
| **Q1** | Accuracy | Nodes reflect their source sentence | Non-NFC names; broken-OCR characters (`Ƣ`, `ƣ`, `�`) in names |
| **Q2** | Consistency | Schema-legal + P4 temporal invariants + P1 lint | Illegal edges; non-ISO dates; `valid_from > valid_to`; bad `is_current` chains; format-split versions; missing `date_uncertain`; T1 classes with time in `identity_keys` |
| **Q3** | Conciseness | One T1 entity = one node | Surplus duplicate T1 nodes per normalized name; `Standard` node count |
| **Q4** | Completeness | Evidence exists on *both* sides | Counts of `Controversy` / `Penalty` / `MediaReport` / news-side `KPIObservation` |
| **Q5** | Timeliness | Facts carry the right time | % edges with `valid_from`; % T2 nodes with `valid_from`; % news T2 with `date_uncertain` |
| **Q6** | Provenance | Traceable back to a sentence | % nodes with `source_type`; % KPIs with a parseable `source_id` |
| **Q7** | **Traversability** | Is the graph dense and multi-path enough for path reasoning? | (a) median degree; (b) % leaves; (c) % masked-edge queries answerable ≤ 3 hops; (d) % claims reaching conduct via a hub-free path with ≥ 1 structural edge; (e) % T2 nodes with degree ≥ 2, per class |
| **Q8** | Source independence | "Verification" must be independent of the company | Conduct evidence counted by channel (`report` vs `news`) |

Q7 is the attribute this project defines. It does not appear in the classical KG-quality
literature because it only becomes meaningful when a graph must serve path-based
reasoning. Defining and measuring it with five concrete indicators is a small but
defensible methodological contribution.

### 4.1 Reasoning-readiness metrics

Reported alongside Q7, from `esg_kg/metric/reasoning_readiness.py`:

| Metric | Meaning |
|---|---|
| **R1** | % of edges whose object is re-derivable from its subject within 3 undirected hops **after masking that edge**. Masking is what makes it non-vacuous — otherwise the edge trivially reaches its own endpoint |
| **R1′** | R1 with all issuer-hub nodes barred — the honest number, since a route through the hub is not a route a bounded-degree walker can take |
| **R1_trainable** | R1 with degenerate relations excluded (`reportsKPI` on the current graph) |
| **R5** | Maximum hub-**cluster** degree. A cluster, not a node: hub membership follows `config/issuer_registry.json`, so every issuer's star is caught, not only the single global maximum |
| **R7** | Count of hub-free length-3 metapaths with support ≥ 50 — the walkable backbone a path-reasoning layer would train on |

### 4.2 Reading a report

From the pinned 5-company snapshot (`with_news_5co_20260806`, 6,918 nodes / 9,797 edges):

```
Q2 Consistency    total violations: 6 (illegal edges 0, non-ISO dates 2, from>to 1,
                  bad is_current chains 2, format-split versions 1)
Q4 Completeness   Controversy 0 / Penalty 9 / MediaReport 83 / news KPI 298
Q5 Timeliness     edges with valid_from 95.8%; news T2 with date_uncertain 100.0%
Q6 Provenance     nodes with source_type 98.7%; KPI with parseable source_id 76.9%
Q7 Traversability median degree 1.0; leaves 67.2%; masked-answerable 47.4%;
                  claim→conduct structural 44.6%; T2 deg≥2 28.3%
R5                max hub-cluster degree: 5300
R1 / R1' / R7     47.2% / 26.7% / 945 metapaths
```

What to read from it: consistency is nearly clean; the conduct side is thin (that is the
coverage caveat, not a bug); and traversability is the live problem — a median degree of
1.0 with 67% leaves is the leaf cloud P3 targets, and R1 dropping from 47.2% to 26.7% once
the hub is barred is exactly the P5 hub dependency.

### 4.3 Useful flags

| Flag | Effect |
|---|---|
| `--label <name>` | Names the output pair; use it every time |
| `--skip-slow` | Skips the BFS-heavy Q7(c)/(d) and R1/R7 arms (~44 s on the real graph) |
| `--max-hops` | Path length bound for Q7(d) |
| `--issuer-registry` | Registry used for hub-cluster identification |
| `--degenerate-relations` | Relations excluded from R1_trainable |
| `--standards-registry` | Registry used by the standards-coverage audit |

### 4.4 The standards-registry audit

The report ends with a coverage audit of `config/standards_registry.json`: which
`Standard` / `Regulation` spellings in the graph look like a reference document but are
not curated yet. It is the feedback loop that replaced the removed reseed stage — you read
the audit, hand-edit the registry, and re-run `entities`. The noise filter matters:
out-of-scope accounting standards must *not* be reported, or the section becomes
unreadable. `test/test_standards_audit.py` pins that behaviour.

---

## 5. Status against the principles

| Principle | Status | Where it lives |
|---|---|---|
| P1 identity is timeless | **Done** — enforced and linted | `config/schema.json`, Q2, `test_schema_contract.py` |
| P2 time on statements | **Done** — schema and data agree | `entities`, edge `temporal_metadata` |
| P3 ≥ 2 anchors per event | **Partial** — biggest open gap; Q7(e) 28.3% overall, `KPIObservation` 26.5% | `extract_triples` prompt, `anchor_kpi`; news-event anchoring still blocked on schema pairs ([ROADMAP.md](ROADMAP.md) §2.3) |
| P4 temporal integrity | **Done** — machine-checked | `fix_triples` phase 1.5, `test_temporal_invariants.py` |
| P5 degree governance | **Partial** — export view built, reasoning-layer policy unbuilt | `export_kgc`, `metric/hub.py` |
| P6 inverse edges in the export tier | **Done as a boundary** — respected by `export_kgc` | `core/graph_patch.py`, `export_kgc` |
| P7 first-class provenance | **Done for nodes/edges**; path provenance pending a reasoning layer | `provenance` (05b), `is_synthetic` flags |
| P8 consistent temporal masking | **Design only** — no reasoning layer exists yet | [ROADMAP.md](ROADMAP.md) §2.7 |

---

## 6. Related

- [SCHEMA_EXPLAINED.md](SCHEMA_EXPLAINED.md) — the artifact these principles constrain
- [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) — the reference layer and why
  it is excluded from hub metrics
- [EXPORT_KGC.md](EXPORT_KGC.md) — P5/P6 in practice
- [SSRL_REASONING_LAYER.md](SSRL_REASONING_LAYER.md) — the path-reasoning layer these
  principles were derived for; P3, P5, P6 and P8 all trace back to its measurements
- [ROADMAP.md](ROADMAP.md) — remaining open work
