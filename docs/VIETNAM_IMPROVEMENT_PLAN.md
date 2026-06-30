# Improvement Plan — Adapting the ESG Knowledge Graph to the Vietnam Study Case

**Project:** ESG GraphRAG over Vietnamese corporate disclosures
**Target artifact:** `config/schema.json` (+ supporting pipeline & vocab files)
**Status:** Planning document — no code changed yet.
**Companion docs:** `SCHEMA_EXPLAINED.md` (what the schema currently is).

---

## 0. TL;DR

The current schema is GRI/ESRS-shaped — it assumes the EU world where a *voluntary
standard* (ESRS, SBTi) is the binding authority. Vietnam has **no single ESG
standard**: it has a fragmented stack of **legal instruments** (Luật / Nghị định /
Thông tư / Quyết định) that mandate *disclosure* but not *methodology*, sitting on top
of **voluntary guidelines** (GRI, the SSC/IFC ESG Handbook) and **narrative, mostly
unverified** corporate reports.

This plan makes the graph able to express three things the current schema cannot:

1. **Binding force & instrument type** — mandatory law vs. voluntary guideline, and
   *which* legal instrument (e.g. Decree 06/2022/ND-CP).
2. **Multi-framework crosswalk** — map each disclosure to GRI *and* the local
   Circular 96/2020 index set, so the graph is both internationally comparable and
   locally auditable.
3. **Rigor / assurance / provenance** — because Vietnamese disclosures are narrative
   and rarely third-party assured, capture *how trustworthy* each fact is. This
   distribution is itself a research finding.

Work is split into **P0 (must-have, changes graph behaviour)**, **P1 (high value)**,
and **P2 (localization & polish)**.

---

## 1. Why the current schema doesn't fit Vietnam

### 1.1 The Vietnamese ESG reality

| Layer | Instrument(s) | Binding? | What it requires |
|---|---|---|---|
| Mandatory disclosure | **Circular 96/2020/TT-BTC** | Yes (disclosure only) | Listed/public firms put an ESG section in the annual report: energy, water, GHG, solid/hazardous waste, environmental-law compliance, labor policy, community. **No methodology mandated.** |
| Mandatory GHG inventory | **Decree 06/2022/ND-CP** + **Decision 13/2024/QĐ-TTg** (replaced 01/2022) | Yes (listed facilities) | 2,166 facilities emitting >3,000 tCO₂e must submit biennial GHG inventories from 2025. |
| Green finance | **Green Taxonomy — Decision 21/2025/QĐ-TTg** (45 sectors, 7 groups) | Emerging | Defines what counts as "green" for green credit/bonds. |
| Carbon market | **Decision 232/2025/QĐ-TTg** | Emerging | Centralized carbon exchange operated by HNX. |
| National targets | **Decision 896/QĐ-TTg**, NDC | State commitment | Net-zero by 2050; −43.5% vs BAU by 2030. |
| Voluntary guidance | **SSC/IFC ESG Handbook (Oct 2024)**, **GRI**, VNSI index | Not binding | The actual ESG *content* — exactly the "just a guideline" documents. |

**Sources:**
[IFLR — Vietnam ESG trends](https://www.iflr.com/article/2a647zxame68p5ftezpxd/vietnam-catches-up-with-global-esg-trends) ·
[Keslio — Sustainability Reporting Requirements in Vietnam](https://www.keslio.com/insights/sustainability-reporting-requirements-in-vietnam) ·
[Klinova — Mandatory GHG Inventory: Who Must Comply](https://klinova.vn/latest-news/mandatory-ghg-inventory-in-vietnam-who-must-comply.html) ·
[Monsoon Carbon — Vietnam's Mandatory GHG Inventories](https://monsooncarbon.com/prepare-now-for-vietnams-mandatory-ghg-inventories-since-october-2024/) ·
[Vietnam Briefing — Carbon Market under Decision 232](https://www.vietnam-briefing.com/news/vietnams-carbon-market-development-objectives-and-implementation-plan-under-decision-232.html/) ·
[Watson Farley & Williams — Vietnam's Green Taxonomy (Decision 21/2025)](https://www.wfw.com/articles/vietnams-green-taxonomy-new-legal-framework-green-credit-green-bonds/)

### 1.2 The four concrete gaps

| # | Gap | Where it hurts in the current schema |
|---|-----|--------------------------------------|
| G1 | **No notion of binding force or instrument type.** | `Standard` and `Regulation` have no `mandatory` flag, no `instrument_type`, no instrument number. You cannot distinguish a binding decree from a voluntary handbook. |
| G2 | **Single-framework mapping.** | `gri_mapper.py` maps Vietnamese sentences *only* to GRI codes. There is no link to the Circular 96 index set that VN firms are legally required to disclose. You cannot ask "did company X cover all Circular-96 indices?" |
| G3 | **No rigor / assurance / provenance.** | Nodes have no `confidence`, `evidence_text`, or `assurance_level`. In VN almost nothing is third-party assured — but the schema can't record that, so it treats a self-declared claim and an audited fact identically. |
| G4 | **EU defaults & missing local vocab.** | `Authority`/`Regulation.jurisdiction` default to EU bodies; no VND currency default, no province modeling, no VSIC industry codes, no Vietnamese-body seed list, no GHG-inventory-obligation concept. |

What is **fine and reusable**: the physical/measurement core (`Emission`, `Waste`,
`KPIObservation`, `Community`, `Facility`, `Product`), the bitemporal model, and
especially the `SustainabilityClaim ↔ verify/contradict` greenwashing sub-graph —
that cluster is a *strength* for Vietnam and we lean into it.

---

## 2. Target design changes

> Notation: 🟢 new class/edge/field · 🟡 modified · 🔴 keep but expect sparse.
> JSON snippets are illustrative — match the existing formatting in `schema.json`.

### P0 — Reframe the regulatory layer around legal instruments + guidelines

This is the change that actually makes the graph "Vietnamese."

#### P0.1 🟡 Enrich `Regulation` to model legal instruments

```json
{
  "class": "Regulation",
  "properties": [
    "name", "name_vi", "jurisdiction", "description",
    "instrument_type",        // enum: law | decree | circular | decision | resolution
    "number",                 // e.g. "06/2022/ND-CP", "96/2020/TT-BTC"
    "issuing_body",           // e.g. "Government", "Ministry of Finance"
    "effective_date",
    "mandatory",              // boolean
    "status",                 // in_force | superseded | draft
    "valid_from", "valid_to", "is_current"
  ],
  "identity_keys": ["number"]
}
```

> Changing `identity_keys` from `["name","jurisdiction"]` to `["number"]` is deliberate:
> the instrument *number* is the stable, unambiguous identity in Vietnamese law.
> The existing `Regulation —supersedes→ Regulation` edge then cleanly models
> "Decision 13/2024 supersedes Decision 01/2022."

#### P0.2 🟡 Add binding/framework typing to `Standard`

```json
{
  "class": "Standard",
  "properties": [
    "name", "name_vi", "description",
    "framework_type",   // enum: statutory | voluntary_guideline | market_standard | international
    "binding",          // boolean
    "issuer",           // e.g. "GRI", "SSC", "ISO"
    "valid_from", "valid_to", "is_current"
  ],
  "identity_keys": ["name", "valid_from"]
}
```

A "guideline" (GRI, SSC/IFC Handbook) is simply a `Standard` with
`framework_type = voluntary_guideline`, `binding = false`. No separate class needed.

#### P0.3 🟡 + seed `Authority` with Vietnamese bodies

```json
{
  "class": "Authority",
  "properties": [
    "name", "name_vi", "type", "jurisdiction",
    "level",            // national | provincial
    "parent",           // parent authority name (nullable)
    "valid_from", "valid_to", "is_current"
  ],
  "identity_keys": ["name", "jurisdiction"]
}
```

Seed list (a `config/vn_authorities.json` reference file): MAE/MONRE (Bộ Nông nghiệp và
Môi trường), SSC/UBCKNN (State Securities Commission), MOIT (Bộ Công Thương), HOSE,
HNX, and provincial DONRE (Sở TN&MT). Without this, extracted Vietnamese authority
mentions have nothing to resolve against.

---

### P1 — Multi-framework disclosure crosswalk

Keep GRI as the international semantic backbone (it's the de-facto voluntary standard
in VN and your LaBSE mapper already targets it), but add **Circular 96** as a parallel
local controlled vocabulary so disclosures are both comparable *and* auditable.

#### P1.1 🟢 New node `DisclosureRequirement`

```json
{
  "class": "DisclosureRequirement",
  "properties": [
    "framework",        // enum: GRI | Circular96 | ESRS | GreenTaxonomy
    "code",             // e.g. "305-1" (GRI) or "C96-ENV-GHG" (local)
    "title_en", "title_vi",
    "mandatory",        // boolean (true for Circular96 indices)
    "valid_from", "valid_to", "is_current"
  ],
  "identity_keys": ["framework", "code"]
}
```

#### P1.2 🟢 New edges

```json
{ "label": "satisfiesDisclosure", "source_class": "KPIObservation",
  "target_class": "DisclosureRequirement",
  "temporal_properties": ["valid_from", "valid_to", "recorded_at"] },

{ "label": "mapsToFramework", "source_class": "DisclosureRequirement",
  "target_class": "DisclosureRequirement",
  "temporal_properties": ["valid_from", "valid_to", "recorded_at"] }
```

`mapsToFramework` is the **crosswalk** edge — it links a GRI code to its Circular 96
counterpart, so one extraction can answer both "GRI 305-1 covered?" and "Circular 96
GHG index covered?".

#### P1.3 🟢 Seed the Circular 96 index vocabulary — `config/circular96_indices.json`

Minimum set to encode (each becomes a `DisclosureRequirement` with
`framework=Circular96`, `mandatory=true`):

| Local code | Title (EN) | Maps to GRI (approx.) |
|---|---|---|
| `C96-ENV-ENERGY` | Energy consumption | 302-1 |
| `C96-ENV-WATER`  | Water consumption / management | 303-3/5 |
| `C96-ENV-GHG`    | GHG emissions | 305-1/2/3 |
| `C96-ENV-WASTE`  | Solid & hazardous waste | 306-3 |
| `C96-ENV-COMPLY` | Compliance with environmental law | 2-27 |
| `C96-SOC-LABOR`  | Employee/labor policy | 401/403/404/405 |
| `C96-SOC-COMM`   | Community responsibility & investment | 413 |

> This table doubles as documentation of the local→international mapping for your thesis.

#### P1.4 🟢 Provenance & rigor fields (lean into the greenwashing angle)

Add to the extracted "fact" classes (`KPIObservation`, `SustainabilityClaim`,
`Emission`, `Waste`, and ideally as edge attributes):

```json
"confidence",       // 0..1 extraction confidence from classifier/LLM
"evidence_text",    // the source sentence/span (grounding back to the PDF)
"source_id",        // already present on KPIObservation — propagate everywhere
"assurance_level"   // enum: none | self_declared | limited | reasonable | third_party
```

In practice most Vietnamese disclosures land at `none` / `self_declared`. Plotting the
distribution of `assurance_level` across the corpus is a **direct, defensible research
result** — it quantifies how much of "Vietnamese ESG reporting" is unverified narrative.

---

### P2 — Localization & Vietnam-specific facts

#### P2.1 🟢 GHG-inventory obligation (a uniquely Vietnamese, high-value fact)

```json
{
  "class": "ComplianceObligation",
  "properties": [
    "obligation_type",   // e.g. "ghg_inventory"
    "threshold",         // e.g. "3000 tCO2e"
    "applies_from",      // e.g. "2025"
    "source_instrument", // FK to Regulation.number, e.g. "13/2024/QD-TTg"
    "valid_from", "valid_to", "is_current"
  ],
  "identity_keys": ["obligation_type", "source_instrument"]
}
```

```json
{ "label": "subjectToObligation", "source_class": "Facility",
  "target_class": "ComplianceObligation",
  "temporal_properties": ["valid_from", "valid_to", "recorded_at"] },
{ "label": "subjectToObligation", "source_class": "Organization",
  "target_class": "ComplianceObligation",
  "temporal_properties": ["valid_from", "valid_to", "recorded_at"] }
```

Also 🟡 add to `Emission`: `methodology` (did it follow the Decree 06 inventory
method?) and `verified` (boolean).

#### P2.2 🟡 Localize values & vocab

- `Investment.currency`, `Penalty.amount`: default **VND**; keep currency explicit.
- `Location`: treat **province** as `region` (63 provinces). Seed `Country = "Vietnam"`.
- `Organization` / `Facility`: add `vsic_code` (Vietnam Standard Industrial
  Classification) and `green_taxonomy_sector` (the 45-sector Decision 21 list) — lets
  you link a facility to its GHG-inventory obligation and green-finance eligibility.
- Add `name_vi` / `name_en` to reference entities (`Authority`, `Regulation`,
  `Standard`, `DisclosureRequirement`) since extraction is Vietnamese-first.

#### P2.3 🔴 EU-only classes — keep but expect sparse

- `ScienceBasedTarget` — SBTi adoption in VN is rare; keep, expect near-empty.
- `CarbonOffsetProject` — **keep and watch**: becoming relevant with the Decision 232
  carbon market / HNX exchange. No change needed.

---

## 3. Pipeline changes that follow from the schema changes

The schema is consumed by the extraction pipeline, so these edits have downstream work:

| Schema change | Pipeline impact |
|---|---|
| P1 crosswalk (`DisclosureRequirement`) | Extend `gri_mapper.py`: after GRI match, also resolve to the Circular 96 index via the `mapsToFramework` table. Add `config/circular96_indices.json` loader. |
| P1.4 provenance fields | Extraction/record builder (`extract_esg.py`, `make_record`) must carry `confidence`, `evidence_text` (already have `text`/`scores` — wire them through), and emit `assurance_level` (rule: default `self_declared`, upgrade to `third_party` only when a `ThirdPartyVerification` is linked). |
| P0 instrument typing | NER/extraction step needs a Vietnamese **legal-instrument recognizer** (regex for `\d+/\d{4}/(NĐ-CP|TT-BTC|QĐ-TTg|...)` is high-precision and cheap). |
| P2 localization | Seed reference files (`vn_authorities.json`, `vn_provinces.json`, `circular96_indices.json`) used during entity resolution. |

---

## 4. Phased roadmap

| Phase | Scope | Deliverables | Effort |
|---|---|---|---|
| **Phase 1 — Regulatory backbone (P0)** | Enrich `Regulation`, `Standard`, `Authority`; seed `vn_authorities.json`; add legal-instrument regex to extraction. | Updated `schema.json`; authority seed file; instrument recognizer. | S–M |
| **Phase 2 — Crosswalk (P1.1–1.3)** | Add `DisclosureRequirement` + crosswalk edges; build `circular96_indices.json` with GRI mappings; extend `gri_mapper.py`. | Local index vocab; dual-framework mapping; "Circular-96 coverage" query. | M |
| **Phase 3 — Rigor & provenance (P1.4)** | Add `confidence`/`evidence_text`/`assurance_level`; wire through extraction; compute assurance distribution. | Provenance-enriched records; assurance-level analysis chart. | M |
| **Phase 4 — Localization & obligations (P2)** | VND defaults, province modeling, VSIC/Green-Taxonomy codes, `ComplianceObligation` + GHG-inventory seed. | Localized vocab; obligation sub-graph; facility→obligation links. | M |
| **Phase 5 — Validation** | Run against a handful of real VN annual reports (e.g. Vinamilk, FPT, Vingroup); check coverage, dedup, and the greenwashing query end-to-end. | Validation notes; iterate schema. | M |

`S` ≈ <1 day, `M` ≈ a few days. Phases 1→2→3 are the critical path for the academic
contribution; Phase 4 adds Vietnamese richness; Phase 5 proves it.

---

## 5. Academic framing (for the capstone write-up)

Position the knowledge graph as a **normalization layer over heterogeneous, mostly
voluntary Vietnamese disclosures**:

- **GRI** = international semantic interlingua (comparability).
- **Circular 96** = local mandatory backbone (auditability).
- **Legal instruments** modeled as first-class binding context (the thing the EU
  schema collapses).
- **Assurance/confidence fields** that *expose* how much Vietnamese ESG reporting is
  unverified narrative.

That last gap — the distance between what firms *claim* and what is *verified* — is the
research contribution, and the schema is built to measure it.

---

## 6. Open questions to resolve before/while building

1. **Graph backend** — Neo4j, a JSON store, or an in-memory graph for GraphRAG? Affects
   how `identity_keys` and bitemporal fields are enforced.
2. **Circular 96 ↔ GRI mapping** — auto-derive via LaBSE similarity, or hand-curate the
   ~7 indices (recommended: hand-curate, it's small and high-stakes)?
3. **`assurance_level` inference rule** — purely structural (has a verification edge?) or
   also text-cue based ("được kiểm toán bởi…")?
4. **Scope of corpus** — VNSI/HOSE-listed firms only, or broader? Determines how much
   the mandatory-vs-voluntary distinction actually varies in the data.

---

*Plan authored against `config/schema.json` and the Vietnam regulatory landscape as of
June 2026. Update as the schema and corpus evolve.*
