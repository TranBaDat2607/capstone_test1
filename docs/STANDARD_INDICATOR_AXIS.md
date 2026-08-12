# The TT96/GRI indicator axis

**Audience:** anyone working on `canonicalize` (03c), `indicators` (05c),
`align_claims` (05d), the cross-check, or the Evidence View UI.

The indicator axis turns a controlled vocabulary that used to be a *string property* into
first-class graph structure, so a company's **claim** about an indicator and the **conduct
KPIs** measured under it hang off one node.

Sections §2.4, §3, §3.1, §5.2, §5.3, §5.4 and §6 are referenced from source-code
docstrings — keep those numbers stable.

---

## 1. The problem

The 35 controlled KPI definitions in `kpi_definitions_construction.json` (repo root, built
once by `kpi_build/`) were reaching the graph only as free-text `kpi_type` values on
`KPIObservation`. Three consequences:

1. **Not traversable.** `kpi_type = "Tổng phát thải khí nhà kính"` is a string. Cypher
   cannot join a claim to a KPI through a string that the claim does not contain.
2. **Not joinable across sides.** The report side matched some KPIs against the controlled
   vocabulary; the news side produced free text. Two names for the same fact, no key.
3. **No pillar to show.** The Evidence View needs an E/S/G column per claim. Without an
   indicator node there is nothing to read it from, so it would have to be guessed.

---

## 2. Options considered and rejected

### 2.1 Connect every node type around the issuer to a `Standard` node — rejected

Turns `Standard` into a second super-hub with no added meaning: an edge saying "this node
is somehow related to TT96" answers no question the graph could not already answer.

### 2.2 One standard node per connecting node type — rejected

`Standard(TT96-for-KPI)`, `Standard(TT96-for-Emission)`, and so on. Identity would encode
the *neighbour's* class rather than the indicator, so the same indicator would fragment
into several nodes and the join it exists to enable would break.

### 2.3 Push the semantics into the relationship label — rejected

One fat `TT96` node with labels like `reportsKPIUnder_TT96_6_1_1`. This explodes the edge
vocabulary (35 indicators × several source classes), makes schema validation useless, and
puts identity in a label — the one place nothing can index it.

### 2.4 Delete the cross-check stage and wire KPI / Emission / Penalty / Goal straight to news — rejected

Superficially simpler, and wrong in a way worth recording because it recurs.

A direct edge from a KPI to a news node asserts a *relationship between two facts* that
nobody adjudicated. The whole point of the cross-check is that a claim and a piece of
conduct are related **only after a judgement**, and that judgement is what carries a
rationale, a confidence and a provenance trail. Wiring them structurally would fabricate
that relationship at extraction time, with no rationale attached, and there would be
nowhere to put the "this is advisory" flag that
[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §1.1 requires.

The indicator axis is the correct middle: it makes the two sides **findable** from each
other in two hops, and leaves the judgement to the cross-check.

### 2.5 Why the claim-centric architecture stays

The unit of analysis is the claim, because the question is "does what they said hold up?"
Indicators route evidence to claims; they never replace the claim as the subject.

---

## 3. The chosen design: two layers

Documents at the top, indicators below them, with the indicator node carrying identity and
the edge label carrying the role:

```
   (Regulation "TT96")  ◀──partOf──  (StandardIndicator "TT96-6.1.1")  ──equivalentTo──▶  (StandardIndicator "GRI 305-1")
                                              ▲          ▲
                                 measuredUnder│          │alignsWithIndicator
                                              │          │
                        (KPIObservation, Emission,   (SustainabilityClaim,
                         Penalty)                     Goal, Initiative)
```

`StandardIndicator` is the **join point**. Two hops replace token-overlap guessing:
`(:SustainabilityClaim)-[:alignsWithIndicator]->(:StandardIndicator)<-[:measuredUnder]-(:KPIObservation)`.

### 3.1 The node class

```jsonc
{ "class": "StandardIndicator",
  "properties": ["id", "name", "definition", "pillar", "section",
                 "source_document", "valid_from", "valid_to", "is_current"],
  "identity_keys": ["id"] }
```

`id` is the indicator code — `TT96-6.1.1`, `SSCIFC-S1`, `QCVN09-1`, `QD2171-1`,
`GRI 305-1`. Identity is the code, not the name, because the same indicator is spelled
several ways across documents and languages.

`StandardIndicator` is T1 (timeless identity) and is additionally a **reference class**:
generated from a controlled vocabulary rather than extracted from text, and deliberately
high-degree. `quality` excludes reference classes from the hub and path metrics — see
[TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) §3 (P5) for why that exclusion is required
rather than optional.

### 3.2 The edges

Three new labels plus a reuse of `partOf`:

| Label | Pairs | Meaning |
|---|---|---|
| `measuredUnder` | `KPIObservation` / `Emission` / `Penalty` → `StandardIndicator` | this measurement is reported under that indicator |
| `alignsWithIndicator` | `SustainabilityClaim` / `Goal` / `Initiative` / `Controversy` / `MediaReport` → `StandardIndicator` | this statement is *about* that indicator's topic |
| `equivalentTo` | `StandardIndicator` → `StandardIndicator` | crosswalk between frameworks (TT96 ↔ GRI) |
| `partOf` (reused) | `StandardIndicator` → `Regulation` / `Standard` | which document defines the indicator |

`alignsWithIndicator` is a **topic** relation, never a supports/contradicts judgement —
see §6.

### 3.3 Where the crosswalk lives

`config/standard_crosswalk.json`, **not** the KPI definitions file. The definitions file is
a provenance artifact: each of its 35 entries quotes its source document verbatim with a
`source` block, and it is regenerated by `kpi_build/`. A crosswalk is an editorial mapping
between two frameworks — a different kind of claim, with its own review state:

```jsonc
{ "tt96": "TT96-6.1.1",
  "gri": ["GRI 305-1", "GRI 305-2"],
  "gri_name": "Direct (Scope 1) and energy indirect (Scope 2) GHG emissions",
  "confidence": "high",
  "status": "confirmed",
  "note": "Scope 1+2 GHG is the canonical GRI 305-1/305-2 pair." }
```

Currently 23 `confirmed` rows and 4 in `needs_review`. **Only `confirmed` rows produce
`equivalentTo` edges**; `--trust-draft-crosswalk` overrides that for a demo and should not
be used for a measured run.

---

## 4. Where the vocabulary comes from

| File | Built by | Holds |
|---|---|---|
| `kpi_definitions_construction.json` (repo root) | `kpi_build/` (run-once) | 35 Vietnamese indicators: TT96, QĐ2171, QCVN09, SSC-IFC — each with `id`, `name`, `definition`, `pillar`, `sector`, and a verbatim `source` block |
| `config/gri_catalog.json` | `gri/build_gri_catalog.py` (run-once) | 136 GRI codes with `title_vi` / `title_en`, `pillar`, `units`, `tt96_equivalent`, `versions[]`, per-PDF `sha256` |
| `config/standard_crosswalk.json` | hand-edited | TT96 ↔ GRI equivalence rows with a review status |
| `config/kpi_type_aliases.json` | hand-edited | alias rules, `reject_units`, `unit_canonical`, `unit_scale_to_base` used by `canonicalize` |
| `config/standards_registry.json` | hand-edited (static config) | the 5 reference documents and their name variants, used to freeze `Standard` / `Regulation` mentions during entity resolution |

See [KPI_DEFINITIONS_CONSTRUCTION_BUILD.md](KPI_DEFINITIONS_CONSTRUCTION_BUILD.md) and
[GRI_SCHEMA_DOCUMENTATION.md](GRI_SCHEMA_DOCUMENTATION.md).

---

## 5. Implementation

Two insertion points, not one: coverage is fixed at the source *and* downstream.

### 5.1 Step 0 — schema plus a measured before/after

Add the class and the edge pairs to `config/schema.json`, then
`quality --label before-indicator-axis`. Free, and it is the only way the change can be
defended later.

### 5.2 Coverage: fix it at the source *and* downstream

`extract` (01) already matches many KPIs against the controlled vocabulary — on the AAA
corpus, 484 of 4,906 observations arrived carrying a `TT96-*` / `SSCIFC-*` code. The rest
arrive as free text ("Tiêu hao điện năng cho sản xuất", "Male employees"). Those are the
same facts under a different name, and without a canonical code they cannot be joined to
the axis.

`canonicalize` (03c) assigns that code offline, with no LLM:

- **It writes a NEW property `kpi_id` and never rewrites `kpi_type`.** The reason is
  provenance: `kpi_type` is the raw wording the extractor read off the page, `kpi_id` is
  the canonical code it maps to. Overwrite the raw value and a wrong mapping can never be
  traced back to what the report actually said. (A secondary, historical reason —
  `kpi_type` sits in `identity_keys`, so rewriting it would renumber the resolved node
  array — is no longer the headline argument, since a full re-extraction is a planned cost.)
- **Precision over recall.** Roughly 85% of the unmapped tail is purely financial
  ("Lợi nhuận sau thuế", unit VND). Those are not missing ESG mappings, they are correctly
  excluded noise: `reject_units` blocks them outright. Unmatched nodes keep
  `kpi_id = null` and are listed in the stats file so the alias dictionary can be grown
  deliberately.
- **Every node records which rule decided**, in `kpi_id_method`:
  `kpi_type` · `alias_exact` · `official_name` · `alias_contains` · `fuzzy_NN` ·
  `rejected_unit` · `unit_mismatch` · `no_title` · `no_match`. This matters more than it
  looks: a null `kpi_id` is ambiguous on its own — `rejected_unit` means a deliberate
  refusal, `no_match` means the alias file has a hole, and only the second is a backlog
  item. On the AAA corpus those were 2,913 versus 1,368, so without the stamp the real
  work is buried under noise three times its size. The same property makes a wrong
  `measuredUnder` edge traceable to the tier that minted it (`alias_exact` is curated,
  `fuzzy_NN` is a guess).

The same pass normalizes units (`unit_normalized`, `value_normalized`, `period`) and
backfills `Goal.target_date` by Vietnamese regex — future years only, so a year mentioned
in passing in a description cannot become a target.

The fuzzy tier needs `rapidfuzz`, which is deliberately not in `requirements.txt`; without
it the tier is disabled with a warning and the rest still runs.

### 5.3 `indicators` (05c) — materializing the axis, offline, no LLM

Runs after `provenance` (05b), before `neo4j_load`. It appends roughly 35 indicator nodes
plus their edges:

| Edge | Source |
|---|---|
| `partOf` | indicator → its defining document |
| `measuredUnder` | read from the `kpi_id` **already assigned by 03c** — never guessed here |
| `equivalentTo` | `confirmed` crosswalk rows only |
| `alignsWithIndicator` | keyword tier: longest matching phrase wins |

Three rules the stage will not break:

1. **It does not guess a KPI's indicator.** It reads `kpi_id`. Keeping that boundary means
   a wrong mapping is always traceable to 03c or the alias file, never to this stage.
2. **A `Penalty` with `amount == 0` gets no conduct edge.** "Fined 0 times" is a
   self-reported compliance *boast*, not conduct evidence; wiring it under a TT96
   compliance indicator would count a boast as a violation. Those nodes are flagged
   `self_reported_zero` instead.
3. **Append-only.** `neo4j_load` keys Neo4j by array index and the cross-check dossiers
   reference nodes by position, so the stage only appends and never reorders or replaces
   an existing item. `GraphPatch.assert_append_only()` verifies this by object identity
   before writing.

It also **restamps `StandardIndicator.pillar`** from the file entitled to say so —
`kpi_definitions_construction.json` for the Vietnamese vocabulary,
`config/gri_catalog.json` for GRI — and never invents one: an id neither file covers keeps
the pillar it had.

That restamping exists because of a real bug. The substring chain it replaced
(`"6.1"/"6.2"/… ⇒ Môi trường`, `"6.6"/"6.7" ⇒ Xã hội`, else `Quản trị`) mislabelled 7 of
65 live indicator nodes: `"TT96-6.6.1"` contains **both** `"6.6"` and `"6.1"`, and the
environmental branch ran first — so all five TT96-6.6.\* labour indicators were filed under
*Môi trường*. The Evidence View reads that property directly for a claim's E/S/G column, so
a guess there is visible to the reader. On the current snapshot the stage restamps 71
indicators.

### 5.4 `align_claims` (05d) — the optional LLM tier

The keyword tier in 05c resolves the unambiguous statements. `align_claims` raises coverage
on the ambiguous remainder using an LLM, writing `alignsWithIndicator` edges stamped
`alignment_method=llm`.

- **Optional.** The pipeline is complete without it; it is deliberately not part of the
  `build_resolved` block.
- **Topic classification only.** "Which indicator, if any, is this claim about?" — never a
  supports/contradicts judgement (§6).
- **Budgeted.** `--max-llm-pairs`, `--dry-run`, and a provider choice
  (`--provider gemini|deepseek`).
- Append-only over the resolved graph, same invariant as 05c.

### 5.5 What the axis looks like on real data

From `indicator_axis_stats.json` on the current snapshot: 26 nodes added (16
`StandardIndicator`, 8 GRI, plus the two document nodes) and 2,018 edges — 1,300
`measuredUnder`, 649 `alignsWithIndicator`, 43 `partOf`, 26 `equivalentTo`. The densest
indicators are `TT96-6.6.1` (204 measurements), `SSCIFC-S1` (150) and `TT96-6.2.1` (115);
one `Penalty` was flagged `self_reported_zero`; one `kpi_id` (`TT96-6.6.6`, 3 nodes) had no
matching indicator node.

---

## 6. Interaction with the cross-check: indicators route, they do not judge

This is the boundary that keeps the design honest.

`alignsWithIndicator` says *this claim is about this topic*. It says nothing about whether
the claim is true. `measuredUnder` says *this measurement is reported under this
indicator*. It says nothing about whether the measurement supports any claim.

The judgement — supports / contradicts / irrelevant — is made in one place only:
`claims_vs_conduct`, by an LLM, with a rationale, a confidence, a provider and an
`llm_suggested=true` stamp on the resulting edge. The axis makes the right evidence
*reachable*; it never decides.

What the axis unlocks in Cypher:

```cypher
// Claims about an indicator the company also reports KPIs for
MATCH (c:SustainabilityClaim)-[:alignsWithIndicator]->(i:StandardIndicator)
      <-[:measuredUnder]-(k:KPIObservation)
WHERE c.crosscheck_ticker = $t
RETURN i.id, i.pillar, c.description, collect(k.value)[..5]

// Vietnamese indicator → its GRI equivalent, for an international reader
MATCH (i:StandardIndicator)-[:equivalentTo]->(g:StandardIndicator)
RETURN i.id, i.name, g.id, g.name
```

The UI consumes exactly this: only claims carrying an `alignsWithIndicator` edge are shown
in the indicator-backed columns, and the E/S/G tab comes from the linked
`StandardIndicator.pillar`. See [ESG_EVIDENCE_VIEW.md](ESG_EVIDENCE_VIEW.md) for the one
deliberate exception, where verified/contradicted claims *without* an indicator link are
surfaced with a visibly flagged fallback pillar.

---

## 7. Limitations

- **Coverage is bounded by the alias dictionary.** `kpi_id_method = no_match` is the
  backlog; growing `config/kpi_type_aliases.json` is manual, deliberate work.
- **The keyword tier is longest-match, not semantic.** A claim phrased entirely in
  synonyms is left for 05d, and if 05d is not run it stays unaligned.
- **Crosswalk rows are editorial.** `needs_review` rows produce nothing until a human
  confirms them; that is intentional, since an unreviewed equivalence would silently make
  a Vietnamese indicator answer for a GRI one.
- **`equivalentTo` is directional in the data** (TT96 → GRI). Query both directions
  explicitly if you need symmetry.

---

## 8. Tests

`python test/test_indicator_axis.py` drives the real `indicators` run on a temporary
workspace and asserts: a self-reported-zero `Penalty` gets no conduct edge, the
`kpi_id`-not-`kpi_type` boundary holds, the confirmed-crosswalk gate holds, and the stage
is append-only and idempotent. `test/test_temporal_invariants.py` covers the `kpi_id`
canonicalization and the edge minting.
