# `config/schema.json` — Explained

This document explains the knowledge-graph schema in `config/schema.json`: what it
is, the design patterns it follows, every node and edge it defines, and how the
pieces fit together to support an ESG GraphRAG system.

> **Origin & context.** The schema was designed around **GRI / ESRS** (European
> ESG reporting). The pipeline ingests Vietnamese ESG/sustainability text, classifies
> it into E/S/G, maps it to GRI disclosures, and ultimately populates a graph shaped
> like this. For how to adapt it to the Vietnamese regulatory reality, see the
> companion discussion on the Vietnam study case — this file only documents what the
> schema *currently* is.

---

## 1. Top-level structure

The file is a single JSON object with two arrays:

```json
{
  "nodes": [ /* 27 node classes */ ],
  "edges": [ /* 60+ relationship definitions */ ]
}
```

- **`nodes`** — the *entity types* (vertices) the graph can contain. Each is a
  `class` with a list of `properties` and a list of `identity_keys`.
- **`edges`** — the *relationship types* allowed between node classes. Each has a
  `label`, a `source_class`, a `target_class`, and `temporal_properties`.

This is a **typed property graph schema**: it constrains *which* kinds of nodes may
exist and *which* directed relationships are legal between them.

### Node definition shape

```json
{
  "class": "Emission",
  "properties": ["category", "scope", "amount", "unit",
                 "valid_from", "valid_to", "is_current"],
  "identity_keys": ["category", "scope", "valid_from"]
}
```

- **`class`** — the node type name.
- **`properties`** — the attributes a node of this class carries.
- **`identity_keys`** — the subset of properties that uniquely identify a node.
  Two extracted records with the same `identity_keys` values are treated as the
  **same entity** and merged (deduplication / entity resolution). This is how the
  pipeline avoids creating a new `Emission` node every time the same Scope-1 figure
  is mentioned.

### Edge definition shape

```json
{
  "label": "generatesEmission",
  "source_class": "Facility",
  "target_class": "Emission",
  "temporal_properties": ["valid_from", "valid_to", "recorded_at"]
}
```

- **`label`** — the relationship name (the verb).
- **`source_class` / `target_class`** — the directed endpoints; the relationship
  goes *from* source *to* target.
- A label can be **reused** with different endpoint pairs (e.g. `generatesEmission`
  exists for both `Facility→Emission` and `Organization→Emission`). Each entry is a
  separate legal relationship.

---

## 2. The two cross-cutting design patterns

Almost every property list ends with the same fields. Understanding these two
patterns explains ~80% of the schema.

### 2.1 Bitemporal validity (every node and edge)

Every **node** carries:

| Property     | Meaning                                                              |
|--------------|---------------------------------------------------------------------|
| `valid_from` | When the fact became true *in the real world*.                      |
| `valid_to`   | When it stopped being true (open/null = still true).                |
| `is_current` | Convenience boolean flag: is this the currently-valid version?      |

Every **edge** carries:

| Property      | Meaning                                                            |
|---------------|-------------------------------------------------------------------|
| `valid_from`  | When the relationship became true in the real world.              |
| `valid_to`    | When it ended.                                                    |
| `recorded_at` | When the system *learned* / ingested the fact (transaction time). |

This is a **bitemporal model**: `valid_*` tracks *real-world time* ("the company
emitted X in 2023"), while `recorded_at` on edges tracks *knowledge time* ("we read
this from the 2024 report"). It lets the graph answer questions like *"what did we
believe the 2023 emissions were, as of the 2024 report vs. the 2025 restatement?"* —
crucial when ESG figures get revised across report years.

### 2.2 `supersedes` — versioning over time

Because facts change, the schema includes a `supersedes` edge for the classes most
likely to be *restated or replaced*:

`Organization`, `Facility`, `Person`, `Goal`, `Standard`, `Product`, `Material`,
`Certification`, `Regulation` (each `supersedes` its own class).

When a newer version of an entity replaces an older one (a renamed company, a revised
target, a regulation that replaces an earlier one), the new node points to the old
one with `supersedes`, and the old one's `valid_to` / `is_current` are closed off.
Combined with the bitemporal fields, this gives a full audit trail of how the graph's
picture of reality evolved.

> **Note:** `identity_keys` for the "versionable" classes often *include* a temporal
> field — e.g. `Standard` is keyed by `["name", "valid_from"]`, `Emission` by
> `["category", "scope", "valid_from"]`. This deliberately lets multiple time-stamped
> versions of the "same" logical entity coexist as distinct nodes.

---

## 3. The node classes (27)

The classes group naturally by ESG function. They are organised below by role.

### 3.1 Core actors & physical assets

| Class          | Key properties                     | Identity            | Role |
|----------------|------------------------------------|---------------------|------|
| `Organization` | name, industry                     | name                | The central actor — a company/entity that reports, emits, owns, claims, etc. |
| `Person`       | name, role                         | name                | Executives, authors, project leads. |
| `Facility`     | name, type                         | name                | A physical site (plant, mine, office) owned by an Organization. |
| `Product`      | name, description                  | name                | A good produced/sold. |
| `Material`     | name, category, source             | name                | Inputs/raw materials used in products. |

These are the "who" and "what" of the graph. `Organization` is the hub that most
relationships originate from.

### 3.2 Environmental measurements

| Class            | Key properties                                | Identity                          | Role |
|------------------|-----------------------------------------------|-----------------------------------|------|
| `Emission`       | category, scope, amount, unit                 | category, scope, valid_from       | A GHG emission figure (Scope 1/2/3). |
| `Waste`          | category, amount, destination                 | category, valid_from              | Waste generated and where it goes. |
| `CarbonOffsetProject` | project_id, name, type                   | project_id                        | A project used to offset emissions. |
| `ScienceBasedTarget`  | target_id, description, target_year, baseline_year | target_id              | A formal SBTi-style reduction target. |

### 3.3 Performance & goals

| Class            | Key properties                                                                 | Identity | Role |
|------------------|--------------------------------------------------------------------------------|----------|------|
| `KPIObservation` | kpi_type, title, value, unit, kind, direction, year, target_year, baseline_year, source_id, company | kpi_type, source_id, year, target_year, baseline_year | A single reported metric data point — the workhorse fact type. `kind`/`direction` distinguish actuals vs targets and improvement direction; `source_id` ties it to the source document. |
| `Goal`           | name, description, target_date, metric                                          | name     | A qualitative/strategic objective. |
| `Initiative`     | name, description, sponsor                                                      | name     | A program/action taken to improve ESG (can reduce emissions/waste, aim for certification). |
| `Project`        | name, description, status, start_date, end_date                                | name     | A concrete project (often the object of an Investment). |

`KPIObservation` is the most richly-attributed class because it is the quantitative
backbone — it captures *the number, its unit, the year, whether it's an actual or a
target, the baseline, and the source*. The distinction between `Goal` (narrative),
`KPIObservation` (quantitative), and `ScienceBasedTarget` (formal target) is worth
noting.

### 3.4 Standards, compliance & governance

| Class           | Key properties                              | Identity                  | Role |
|-----------------|---------------------------------------------|---------------------------|------|
| `Standard`      | name, description                           | name, valid_from          | A reporting/management standard the org adopts (GRI, ISO, ESRS…). |
| `Certification` | name, description, validity_period          | name, valid_from, validity_period | A certificate held by an org/facility (ISO 14001, etc.). |
| `Regulation`    | name, jurisdiction, description             | name, jurisdiction        | A law/rule the org is subject to. |
| `Authority`     | name, type, jurisdiction                    | name, jurisdiction        | The body that issues standards/certs or enforces penalties. |
| `Penalty`       | penalty_id, description, amount, date       | penalty_id                | A fine/sanction imposed on an org. |

### 3.5 Claims, verification & greenwashing detection

This cluster is the schema's most distinctive design and is built specifically to
**detect greenwashing** — to cross-check what a company *says* against independent
evidence.

| Class                   | Key properties                          | Identity        | Role |
|-------------------------|-----------------------------------------|-----------------|------|
| `SustainabilityClaim`   | claim_id, description, date, source     | claim_id        | Something the org *asserts* about its ESG performance. |
| `ThirdPartyVerification`| verification_id, verifier, date, result | verification_id | An independent audit/assurance of a claim. |
| `Controversy`           | controversy_id, description, date, source | controversy_id | A documented incident that may contradict a claim. |
| `MediaReport`           | report_id, title, publisher, date       | report_id       | A news article (can support or contradict claims). |
| `ClaimKeyword`          | term                                    | term            | A normalised keyword tag attached to a claim. |

The narrative logic: an `Organization` **`claims`** a `SustainabilityClaim`, which can
be **`verifiedBy`** a `ThirdPartyVerification` or a `KPIObservation` (corroboration),
or **`contradictedBy`** a `Controversy` / **`contradictedByMedia`** a `MediaReport`
(refutation). See §4.4.

### 3.6 Stakeholders, geography & finance

| Class        | Key properties                       | Identity          | Role |
|--------------|--------------------------------------|-------------------|------|
| `Community`  | name, description                    | name              | A community impacted by the org. |
| `Location`   | name, region, country                | name, country     | A place (sub-country granularity via `region`). |
| `Country`    | name                                 | name              | A country node. |
| `Investment` | amount, currency, date, investor, investee | investor, investee, date | A financial flow (reified as a node so it can connect to projects). |

`Investment` is a **reified relationship** — instead of a single edge "Org invests in
Project," it's modelled as a node so it can carry amount/currency/date *and* link to
both the investor and the funded `Project`.

---

## 4. The edges (relationships)

There are 60+ edge definitions. Below they are grouped by theme. (Each arrow is
`source → target` with the edge `label`.)

### 4.1 Structure & ownership
- `Facility —partOf→ Organization`
- `Organization —ownsFacility→ Facility`
- `Organization —owns→ Organization` (corporate ownership)
- `Organization —partnersWith→ Organization`
- `Product —producedBy→ Organization`, `Product —suppliedBy→ Organization`
- `Product —manufacturedAt→ Facility`
- `Product —usesMaterial→ Material`
- `Material —sourcedFrom→ Organization`, `Material —sourcedFrom→ Location`
- `Person —worksAt→ Organization`, `Person —involvedIn→ Product / Project / CarbonOffsetProject`

### 4.2 Environmental impact & action
- `Facility —generatesEmission→ Emission`, `Organization —generatesEmission→ Emission`
- `Facility —generatesWaste→ Waste`
- `Initiative —reducesEmission→ Emission`, `Initiative —reducesWaste→ Waste`
- `Initiative —aimsForCertification→ Certification`
- `Organization —offsetsWith→ CarbonOffsetProject`
- `Organization —targetsScienceBased→ ScienceBasedTarget`
- `Organization —impactsCommunity→ Community`

### 4.3 Performance, goals & standards
- `Organization —reportsKPI→ KPIObservation`
- `KPIObservation —observedAtFacility→ Facility`
- `Organization —setsGoal→ Goal`
- `Organization —takesPartIn→ Initiative`
- `Organization —adoptsStandard→ Standard`
- `Organization / Facility —holdsCertification→ Certification`
- `Organization —subjectToRegulation→ Regulation`

### 4.4 Claims & verification (the greenwashing sub-graph)
- `Organization —claims→ SustainabilityClaim`
- `SustainabilityClaim —verifiedBy→ ThirdPartyVerification`
- `SustainabilityClaim —verifiedBy→ KPIObservation`  *(claim corroborated by a real metric)*
- `SustainabilityClaim —contradictedBy→ Controversy`
- `SustainabilityClaim —contradictedByMedia→ MediaReport`
- `SustainabilityClaim —hasKeyword→ ClaimKeyword`

This is the schema's analytical payoff: a query can find claims with **no**
`verifiedBy` edge but **with** a `contradictedBy*` edge → candidate greenwashing.

### 4.5 Compliance, penalties & authorities
- `Organization —subjectToPenalty→ Penalty`
- `Penalty —enforcedBy→ Authority`
- `Certification —issuedBy→ Authority`, `Standard —issuedBy→ Authority`

### 4.6 Media & reputation
- `Organization —publishesReport→ MediaReport`
- `MediaReport —reportedBy→ Person`
- `MediaReport —mentionsOrganization→ Organization`, `MediaReport —mentionsProduct→ Product`

### 4.7 Finance
- `Organization —investsIn→ Investment`
- `Investment —investedIn→ Project`
- `Project —ownedBy→ Organization`

### 4.8 Geography
- `locatedIn` from `Organization`, `Facility`, `CarbonOffsetProject`, `Community`,
  `Project` → `Location`
- `Location —isIn→ Country`

### 4.9 Versioning
- `supersedes` (same-class → same-class) for the 9 versionable classes listed in §2.2.

---

## 5. How a query traverses the graph (worked example)

> *"Did Company X's net-zero claim hold up, and who funded the projects behind it?"*

1. Start at `Organization {name: "X"}`.
2. `claims → SustainabilityClaim` (the net-zero claim).
3. Follow `verifiedBy → ThirdPartyVerification`/`KPIObservation` (evidence for) and
   `contradictedBy → Controversy` / `contradictedByMedia → MediaReport` (evidence against).
4. From the org, `setsGoal → Goal` and `targetsScienceBased → ScienceBasedTarget`
   give the stated targets; `reportsKPI → KPIObservation` gives the actuals to compare.
5. `takesPartIn → Initiative → reducesEmission → Emission` shows the *actions*.
6. `investsIn → Investment → investedIn → Project` shows the *money* behind those
   actions, and `Project —locatedIn→ Location —isIn→ Country` grounds them
   geographically.

The bitemporal fields let every step be filtered to a point in time
("…as reported in FY2023").

---

## 6. Quick reference: design takeaways

- **Property-graph, GRI/ESRS-oriented.** Designed for EU-style ESG reporting concepts.
- **Bitemporal by default** — every node/edge tracks real-world validity, and edges
  also track ingestion time (`recorded_at`).
- **Entity resolution via `identity_keys`** — the dedup contract for merging extracted
  mentions into single entities.
- **`supersedes` + temporal keys** give a versioned, auditable history.
- **`KPIObservation`** is the quantitative workhorse; **`SustainabilityClaim` + verify/
  contradict** edges are the qualitative, greenwashing-detection core.
- **Reified relationships** (`Investment`) carry their own attributes and multi-link.

---

*Generated as a reading aid for `config/schema.json`. If the schema file changes,
update this document to match.*
