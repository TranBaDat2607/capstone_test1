# The graph schema — `config/schema.json`

**Audience:** anyone changing the schema, an extraction prompt, or a validation rule.

`config/schema.json` is the single source of truth for the knowledge graph: **28 node
classes** and **48 distinct edge labels spread over 76 legal (source_class, target_class)
pairs**. Extraction, validation, entity resolution, the Neo4j loader and the quality
report all read it — nothing hardcodes a class list.

The temporal reasoning behind the design is in
[TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md); this file describes the artifact itself.

> **After any hand-edit, run `python test/test_schema_contract.py`.** It asserts P1 in
> both directions, that every class sits in exactly one tier, and that the indicator-axis
> edge pairs are present. It imports the tier map from `report/quality.py` rather than
> re-declaring it, so there is exactly one definition of the tiers in the repo.

---

## 1. File shape

```jsonc
{
  "nodes": [
    { "class": "Organization",
      "properties": ["name", "industry", "valid_from", "valid_to", "is_current"],
      "identity_keys": ["name"] },
    ...
  ],
  "edges": [
    { "label": "usesMaterial",
      "source_class": "Product",
      "target_class": "Material",
      "temporal_properties": ["valid_from", "valid_to", "recorded_at"] },
    ...
  ]
}
```

Two things to notice immediately:

1. **`identity_keys` is not the same as `properties`.** It is the subset used to compute a
   stable entity id, which drives deduplication and versioning. Changing it re-clusters the
   graph.
2. **One `label` may appear in several `edges` entries** with different class pairs. The
   validator treats *any* matching pair as legal, and auto-swaps a reversed direction
   rather than rejecting it — the extractor confuses subject and object often enough that
   silently repairing it is cheaper than discarding the triple.

---

## 2. Node classes by tier

Every class belongs to exactly one tier. The tier map lives in
`src/esg_kg/report/quality.py` and is a **contract**, not a local detail.

### T1 — entities (14)

Real-world things with a timeless identity.

`Organization` · `Person` · `Facility` · `Product` · `Material` · `Location` ·
`Country` · `Standard` · `Regulation` · `Authority` · `Community` · `ClaimKeyword` ·
`Certification` · `StandardIndicator`

`Certification` sits between T1 and T3 and is deliberately treated as T1: the node is the
*type* of certificate, and the holding period lives on the `holdsCertification` edge, not
on the node.

### T2 — events and observations (11)

Things that happened at a time. Time is part of their identity, and they are versioned per
observation.

`KPIObservation` · `Emission` · `Waste` · `Penalty` · `Controversy` · `MediaReport` ·
`ThirdPartyVerification` · `Investment` · `Project` · `Initiative` · `CarbonOffsetProject`

### T3 — statements (3)

Assertions someone made. One node per utterance.

`SustainabilityClaim` · `Goal` · `ScienceBasedTarget`

### Reference vocabulary

`StandardIndicator` is additionally marked a **reference class**. It is generated from a
controlled vocabulary, not extracted from text, and it is high-degree *by design* — every
KPI of a given indicator hangs off one node, which is the entire point of the join. The
quality report therefore excludes it from the hub and path metrics, and only there:
counting it would measure the vocabulary rather than the graph, and would make a
before/after comparison across the indicator-axis change meaningless.

---

## 3. Identity keys

| Class | `identity_keys` | Why |
|---|---|---|
| `Organization`, `Person`, `Facility`, `Product`, `Material`, `Standard`, `Certification`, `Regulation`, `Initiative`, `Goal`, `Community`, `Country`, `Project` | `["name"]` | A name is the identity; variants are collapsed by entity resolution, not by the schema |
| `StandardIndicator` | `["id"]` | The indicator code (`TT96-6.1.1`, `GRI 305-1`) is the identity |
| `Location` | `["name", "country"]` | Place names repeat across countries |
| `Authority` | `["name", "jurisdiction"]` | Same |
| `ClaimKeyword` | `["term"]` | |
| `SustainabilityClaim` | `["claim_id"]` | See §3.1 — this one has a history |
| `ThirdPartyVerification`, `CarbonOffsetProject`, `ScienceBasedTarget`, `Controversy`, `Penalty`, `MediaReport` | their own `*_id` | Event identity is the event, not its description |
| `KPIObservation` | `["kpi_type", "source_id", "year", "target_year", "baseline_year"]` | A T2 observation legitimately carries time in its key |
| `Emission` | `["category", "scope", "valid_from"]` | Same |
| `Waste` | `["category", "valid_from"]` | Same |
| `Investment` | `["investor", "investee", "date"]` | Same |

**The rule (P1): never put a time field in a T1 class's `identity_keys`.** The linted set
is `valid_from`, `valid_to`, `is_current`, `recorded_at`, `date`, `year`, `target_year`,
`baseline_year`, `validity_period`. A T1 entity with time in its identity forks into a new
node every year and stops being one company. T2 observations are the *inverse* case and
must keep their time key — the schema contract test asserts both directions, so removing
`valid_from` from `Emission` fails just as loudly as adding it to `Organization`.

### 3.1 `claim_id` is derived, not invented

`SustainabilityClaim.identity_keys` is exactly `["claim_id"]`, and the stable entity id is
hashed straight off that property. `claim_id` used to be free text the model invented per
call, which meant re-running extraction over the same sentence could mint a different id
and silently re-partition every already-paid cross-check dossier.

`extract_triples` now derives it deterministically from `(source_doc, page, normalized
description, date)` — see `make_deterministic_claim_id` / `assign_deterministic_claim_ids`,
pinned by `test/test_claim_id_deterministic.py`. Cosmetic differences in the description
(whitespace, casing) must not change the id.

---

## 4. Edge labels

48 labels. Grouped by what they are for:

**Corporate structure**
`owns` · `ownsFacility` · `partOf` · `partnersWith` · `worksAt` · `ownedBy` ·
`locatedIn` · `isIn` · `impactsCommunity`

**Products and materials**
`producedBy` · `manufacturedAt` · `usesMaterial` · `suppliedBy` · `sourcedFrom` ·
`mentionsProduct`

**Environmental facts**
`generatesEmission` · `generatesWaste` · `reducesEmission` · `reducesWaste` ·
`offsetsWith` · `reportsKPI` · `observedAtFacility`

**Claims, goals, initiatives**
`claims` · `setsGoal` · `takesPartIn` · `targetsScienceBased` · `hasKeyword` ·
`aimsForCertification`

**Standards and compliance**
`adoptsStandard` · `holdsCertification` · `issuedBy` · `subjectToRegulation` ·
`subjectToPenalty` · `enforcedBy`

**Indicator axis** (see [STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md))
`measuredUnder` · `alignsWithIndicator` · `equivalentTo` · `partOf`

**Media and evidence**
`publishesReport` · `reportedBy` · `mentionsOrganization` · `mentionsFacility` ·
`involvedIn` · `investsIn` · `investedIn`

**Cross-check output** (written only by `claims_vs_conduct`)
`verifiedBy` · `contradictedBy` · `contradictedByMedia`

**Versioning**
`supersedes` — legal for the nine classes that can be re-stated over time
(`Organization`, `Facility`, `Person`, `Goal`, `Standard`, `Product`, `Material`,
`Certification`, `Regulation`).

### 4.1 Labels with more than one legal pair

Twelve labels are polymorphic. These are the ones to be careful with when editing:

| Label | Legal pairs |
|---|---|
| `alignsWithIndicator` | `SustainabilityClaim` / `Goal` / `Initiative` / `Controversy` / `MediaReport` → `StandardIndicator` |
| `measuredUnder` | `KPIObservation` / `Emission` / `Penalty` → `StandardIndicator` |
| `partOf` | `Facility` → `Organization`; `StandardIndicator` → `Regulation` / `Standard` |
| `locatedIn` | `Organization` / `Facility` / `CarbonOffsetProject` / `Community` / `Project` → `Location` |
| `verifiedBy` | `SustainabilityClaim` → `ThirdPartyVerification` / `KPIObservation` |
| `generatesEmission` | `Facility` / `Organization` → `Emission` |
| `holdsCertification` | `Organization` / `Facility` → `Certification` |
| `issuedBy` | `Certification` / `Standard` → `Authority` |
| `mentionsFacility` | `MediaReport` → `Facility` / `Location` |
| `involvedIn` | `Person` → `Product` / `CarbonOffsetProject` / `Project` |
| `sourcedFrom` | `Material` → `Organization` / `Location` |
| `supersedes` | nine same-class pairs |

---

## 5. Temporal fields

**At extraction** (`extract_triples`, `fix_triples`) every node carries `valid_from`,
`valid_to`, `is_current`, and every edge carries `temporal_metadata` (`valid_from`,
`valid_to`, `recorded_at`).

**In the resolved graph** (`entities` onward) time lives on **edges and on T2/T3 nodes**.
T1 entity nodes are timeless; their history is a `temporal_versions` list, and a version
chain with an open version has exactly one `is_current = true`.

Dates are canonical ISO `YYYY[-MM[-DD]]`, enforced by `fix_triples` phase 1.5. Partial
dates are legal and common — a report gives a year, not a day.

### 5.1 `date_uncertain` on news-derived observations

`KPIObservation`, `Controversy`, `Penalty` and `MediaReport` carry a required boolean
`date_uncertain`:

- `false` — the article states an explicit date or period for that fact;
- `true` — extraction had to fall back to the article's publish date as a proxy.

Never silently assume the publish year. The cross-check surfaces this as a caveat on any
dossier whose evidence includes an uncertain date, and the quality report tracks coverage
of the field.

### 5.2 `source_type`

Every node and edge carries `source_type ∈ {report, news}`. This is what keeps "what they
say" and "what they do" separable inside one graph, and it is the field the
self-verification guard and the whole cross-check depend on.

---

## 6. Changing the schema

1. **Write the test first** (repo working rule). For a schema change that usually means
   extending `test/test_schema_contract.py`.
2. **Measure before:** `python src/run.py quality --label before-<change>`.
3. Edit `config/schema.json`. Prefer **additive** changes — a new property, or a new legal
   pair for an existing label. Old nodes lacking a new property stay valid; a new class or
   a changed `identity_keys` does not have that property.
4. `python test/test_schema_contract.py` — the P1/tier/indicator-pair contract.
5. `python test/test_temporal_invariants.py` — required after touching anything the
   validation and resolution stages rely on.
6. Rebuild, then **measure after:** `quality --label after-<change>`, and read the two
   reports side by side.

**What not to do without a plan:** changing an `identity_keys` list re-clusters entity
resolution and renumbers the resolved node array. `neo4j_load` keys nodes by array index
and the cross-check dossiers reference nodes by position, so a renumbering invalidates
already-paid dossiers. This is a scheduled cost of a deliberate full re-extraction, not
something to do in passing.

**What is deliberately not in the schema:** `HubBucket`, the synthetic node minted by
`export_kgc`. It is a dataset-construction artifact, not a T1/T2/T3 entity, and
`config/schema.json` stays the source of truth for the real graph only. See
[EXPORT_KGC.md](EXPORT_KGC.md).

---

## 7. Known gaps

Recorded here so they are not rediscovered as bugs:

- **`observedAtFacility` is legal only for `KPIObservation → Facility`.** News reports
  misconduct per plant, but `Controversy`, `Penalty` and `MediaReport` have no way to
  attach to the facility they concern. Adding those three pairs is additive and is item
  §2.3 in [ROADMAP.md](ROADMAP.md).
- **`Penalty → Authority` (`enforcedBy`) cannot be patched offline**, because `Penalty`
  nodes carry no sentence-level `source_id`. New extractions get it from the prompt.
- **`Regulation` and `Standard` cannot express binding force** — no `mandatory`, no
  `instrument_type`, no instrument number. See [ROADMAP.md](ROADMAP.md) §2.6.
