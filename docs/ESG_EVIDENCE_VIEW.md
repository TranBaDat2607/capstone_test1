# ESG Evidence View — the demo UI

```bash
docker compose up -d          # Neo4j must be running
python src/run.py neo4j_load --clear
python src/run.py claims_vs_conduct
python src/run.py neo4j_sync
python api/main.py            # → http://localhost:8000
```

Packages: `api/` (backend) + `frontend/` (static) · Data source: **live Neo4j, required**

A three-column TT96/GRI evidence view: for a chosen company and year, which ESG claims
appear supported, which appear contradicted, and what the evidence is — with the E/S/G tab
taken from the graph rather than guessed.

---

## 1. Architecture

```
frontend/index.html + css/style.css + js/app.js     ← frozen; never edit for a data change
        │  fetch /api/...
        ▼
api/main.py                 pure-stdlib http.server, no framework
        │
        ▼
api/evidence_service.py     ALL data access — Cypher against live Neo4j
        │
        ▼
Neo4j: base graph (neo4j_load) + advisory layer (neo4j_sync)
```

### 1.1 Why no framework

`api/main.py` is built on Python's standard-library `http.server` on purpose: it dodges
FastAPI/Flask/pydantic version mismatches across five developer machines for a demo surface
that needs three endpoints. It serves JSON with `Access-Control-Allow-Origin: *` and
no-cache headers, plus the static frontend.

### 1.2 The rule: only `evidence_service.py` changes

> **The entire frontend stays as it is. A data-source change happens in
> `api/evidence_service.py` and nowhere else.**

This was the rule during the mock→live migration and it still holds. The frontend contract
(the JSON shape below) is the interface; the service is free to change how it fills it.

---

## 2. Endpoints

| Route | Returns |
|---|---|
| `GET /api/companies?q=<query>` | Issuers that have at least one indicator-aligned claim, each with `ticker`, `name`, `available_years` |
| `GET /api/evidence/<ticker>?year=<year>` | The three-column breakdown, grouped by pillar |
| `GET /static/<path>` · `GET /` | The static frontend |

Response shape:

```jsonc
{
  "company": { "ticker": "AAA", "name": "CTCP Nhựa An Phát Xanh",
               "year_range": "2015 - 2024", "available_years": ["2015 - 2024", "2024", ...] },
  "selected_year": "2023",
  "tabs": {
    "environment": { "verified": [...], "contradicted": [...], "missing": [] },
    "social":      { ... },
    "governance":  { ... }
  }
}
```

Each card carries the claim quote, its source reference (`source_doc` + `source_page`, or
an article title and domain), the standard id, and a verifier plus finding drawn from the
evidence edge's `source_domain` / `provider` and its `rationale`.

---

## 3. Where the pillar comes from

The default path shows only claims that carry an `alignsWithIndicator` edge, so the
E/S/G tab comes **precisely** from the linked `StandardIndicator.pillar` — never guessed.

That property is why `indicators` (05c) restamps pillars from the file entitled to say so;
a substring guess once mislabelled all five TT96-6.6.\* labour indicators as environmental,
and this view is where a reader would have seen it. See
[STANDARD_INDICATOR_AXIS.md](STANDARD_INDICATOR_AXIS.md) §5.3.

### 3.1 The deliberate exception, and how it is flagged

On 2026-08-07 the query was relaxed at the user's explicit request, to surface
`appears_supported` / `appears_contradicted` claims that have **no** `alignsWithIndicator`
edge and were therefore invisible in this view entirely — including real dividend and
revenue contradictions.

Those claims have no indicator to read a pillar from, so the pillar is a **keyword guess
over the claim's own text**. Every such card is stamped `standard_id = "NGOÀI-KHUNG"` so
the UI can visibly flag it as unclassified, rather than silently presenting a guess as if
it were as reliable as an indicator-backed pillar.

Claims that are neither indicator-aligned **nor** verified/contradicted stay excluded.
Admitting them would blow the "missing" column up from a handful to hundreds of untriaged
rows.

---

## 4. The "missing" column

Currently kept empty. It was intended for mandatory TT96/GRI indicators the company never
disclosed — which needs the `kpi_gap` signal that stage 07 does not yet write
([ROADMAP.md](ROADMAP.md) §2.1). It is deferred rather than filled with a proxy.

---

## 5. Connection

Defaults match the loader: `bolt://localhost:8687`, user `greenwashing`, database
`greenwashingkg`. Override with `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` in `.env`.

**Neo4j is required.** There is no mock fallback: the query helpers raise `RuntimeError`
with an explicit message if the database is unreachable. A demo that silently falls back to
fabricated data is worse than one that fails loudly.

---

## 6. Running order

The UI reads the advisory layer, so all of these must have run:

1. `build_resolved` — the graph, with the indicator axis
2. `neo4j_load --clear` — the base graph
3. `claims_vs_conduct` — the dossiers (costs money)
4. `neo4j_sync` — the advisory layer (free)

Skipping step 4 gives an empty view with no error from the database — the claims exist but
carry no `assessment`.

---

## 7. Troubleshooting

| Symptom | Cause |
|---|---|
| `RuntimeError` on any request | Neo4j not running, or wrong credentials |
| Company list empty | No claim has an `alignsWithIndicator` edge — run `indicators` (05c), and optionally `align_claims` (05d) |
| Company appears, all columns empty | `neo4j_sync` has not run for that ticker |
| A card shows `NGOÀI-KHUNG` | Expected — see §3.1 |
| Year selector missing years | Years come from claim dates in the graph; thin data means few years |
