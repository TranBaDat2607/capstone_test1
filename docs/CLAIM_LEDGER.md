# Claim ledger — the presentation stage (Step 7 / P5)

Scripts: [`src/sync_crosscheck_to_neo4j.py`](../src/sync_crosscheck_to_neo4j.py) (Step 6b) +
[`src/report_claim_ledger.py`](../src/report_claim_ledger.py) (Step 7) · queries:
[`neo4j/crosscheck_queries.cypher`](../neo4j/crosscheck_queries.cypher).
System context: [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §9.

This is the final stage of the greenwashing-**evidence** pipeline. It presents, for a company,
every `SustainabilityClaim` beside the conduct evidence that supports or contradicts it, plus
an advisory assessment — **read entirely from Neo4j**. The one non-negotiable framing carried
from `SYSTEM_DESIGN.md` §1.1: **there is no ground truth**, so the ledger shows *evidence + an
explicitly advisory opinion*, **never** a greenwashing score or hard label.

---

## 1. Why there are two scripts (and why Neo4j-only)

Step 6 (`crosscheck_claims_vs_conduct.py`, P4) does the paid LLM work and writes the full
result to a JSON dossier (`graph_output/crosscheck/<ticker>_claim_assessments.json`). But two
parts of that result never reach Neo4j on their own:

- the per-claim **`assessment` / `caveats` / `signals`** — they are computed summaries, not edges;
- the **KPIObservation-based contradictions** (e.g. *"ensures revenue growth"* vs an observed
  **−42.3 %**) — the schema has no legal `Claim→KPIObservation` contradiction edge, so Step 6
  keeps them dossier-only.

So to make the graph the single source the ledger reads from, we first **push the dossier into
Neo4j** — for **free, no LLM** (the tokens were already spent once, in Step 6; re-reading the
cached dossier costs nothing). That is Step 6b. Then Step 7 renders purely from Neo4j.

```
graph_output/crosscheck/<ticker>_claim_assessments.json   (Step 6 output, already paid for)
        │
        ▼  Step 6b — sync_crosscheck_to_neo4j.py   (NO LLM, idempotent)
Neo4j advisory layer  (assessment/caveats/signals on claims + llm_* evidence edges)
        │
        ▼  Step 7 — report_claim_ledger.py   (reads ONLY Neo4j)
console ledger  +  <ticker>_claim_ledger.md  +  neo4j/crosscheck_queries.cypher
```

## 2. Step 6b — `sync_crosscheck_to_neo4j.py` (dossier → Neo4j, no LLM)

Reads `<ticker>_claim_assessments.json` and MERGEs an **advisory layer** onto the step-5 graph,
matching nodes on the loader's `_node_key = "n{index}"` convention:

On each `SustainabilityClaim` node it sets `assessment`, `assessment_is_advisory=true`,
`caveats` (list), `structural_contradiction`, `kpi_gap`, `crosscheck_ticker`. It also writes
advisory edges Claim→evidence node, **namespaced so advisory ≠ extracted fact**, each carrying
`llm_suggested=true` + `confidence / rationale / provider / evidence_text / evidence_class /
source_domain / date / year / independent / date_uncertain`:

| Dossier bucket | Edge type | Note |
|---|---|---|
| `supporting_evidence` | `llm_supports` | independent (guard-passed) support |
| `contradicting_evidence` | `llm_contradicts` | **incl. KPIObservation gaps** the schema can't express |
| `flagged_non_independent_support` | `llm_flagged_support` | company-domain, shown but not counted |

Idempotent (MERGE on a stable `_adv_key`); `--clear-advisory` wipes the prior layer first;
`--dry-run` prints counts only. **AAA sync:** 1093 claim rows → 6558 props;
182 advisory edges (140 `llm_supports` + 24 `llm_contradicts` + 18 `llm_flagged_support`).

```bash
python src/sync_crosscheck_to_neo4j.py --dry-run          # counts only
python src/sync_crosscheck_to_neo4j.py --clear-advisory   # wipe + re-write
```

## 3. Step 7 — `report_claim_ledger.py` (renders from Neo4j only)

No LLM, no JSON. Queries the advisory layer and renders:

**Header** (issuer name + histogram from `c.assessment`; conduct pool from `source_type='news'`
nodes; standing coverage caveat):

```
========================================================================================
AAA — CTCP Nhựa An Phát Xanh
  claims: 1093  |  appears_supported: 66  |  appears_contradicted: 22  |  unverified/insufficient: 1005
  ⚠ Independent conduct on the issuer: 108 KPIObservation, 16 MediaReport.
    Thin independent conduct — absence of contradiction is NOT exoneration (docs/SYSTEM_DESIGN.md §8.3).
  Advisory only — no greenwashing score or verdict; each assessment is an LLM-assisted opinion for human review.
========================================================================================
```

**Per-claim entry** — `✗` contradicting, `✓` supporting, `⚑` company-domain support (shown but
not counted). Real, deterministic AAA example now served from Neo4j:

```
CLAIM  AAA_SC_001   [2021, source=report]
  "Ensures growth in revenue and profit"
  ASSESSMENT: appears_contradicted (advisory)
  ✗ KPIObservation  (conf 1.00, 2026)
     "Revenue decrease Revenue -42.3 % achieved"
     rationale: … a revenue decrease of 42.3%, which directly contradicts the claim …
  ✓ KPIObservation  (conf 0.90, 2025)  "Net revenue growth H1 2025 … 7.3 % achieved"  …
  signals: structural_contradiction=true; kpi_gap=none
  caveats:
     - No ground-truth greenwashing label exists; this is an advisory opinion.
```

Entries sort signal-first (`appears_contradicted` → `appears_supported` → `unverified`), then by
descending evidence confidence. Default view shows only the signal-bearing buckets and a one-line
count for the 1005 unverified claims.

### Flags
| Flag | Meaning |
|---|---|
| `--ticker` | issuer to render (default `AAA`); reads `c.crosscheck_ticker` |
| `--assessment {appears_contradicted,appears_supported,unverified_insufficient_evidence,all}` | show one bucket; `all` includes unverified |
| `--review-queue` | only claims with contradiction **and** no independent verification (AAA: 14) |
| `--claim-id ID` | render a single claim, un-truncated |
| `--limit N` / `--maxlen N` | cap entries / truncate text (default 300 chars) |
| `--markdown [PATH]` | also write a Markdown ledger (default `graph_output/crosscheck/<ticker>_claim_ledger.md`) |
| `--uri` / `--user` / `--password` / `--database` | Neo4j connection (default from `.env` `NEO4J_*`) |

If the ledger reports *"No claims with an assessment"*, the sync (Step 6b) has not been run yet.

## 4. Analyst Cypher (`neo4j/crosscheck_queries.cypher`)

Six queries against the advisory layer: (1) review queue per claim, (2) review queue with
contradicting evidence, (3) assessment roll-up, (4) one claim's full dossier, (5) coverage
sanity (conduct pool), (6) housekeeping to drop/re-sync the advisory layer. All keyed on the
`llm_*` edges + `c.assessment` written by Step 6b.

## 5. Honest deviations & current-data caveats

1. **No stored E/S/G category on claims.** Claim nodes carry only
   `claim_id / description / date / source / source_type`, so the ledger prints `[year, source]`
   rather than the `[Environmental]` of the §9.1 mock-up.
2. **The tax-penalty headline example doesn't fire on today's data** (per
   `CLAIM_CONDUCT_CROSSCHECK.md` §6 — that article was never extracted into a
   `Controversy`/`Penalty`). The real worked examples that DO fire: *appears_contradicted*
   `AAA_SC_001` (revenue **−42.3 %**) and recycled-materials (**80–85 % imported**);
   *appears_supported* the bonus-system claim.
3. On today's thin conduct, most claims are `unverified_insufficient_evidence` — which means
   *little external evidence found*, **not** *the company is clean* (§8.3).

## 6. Run order

```bash
# Prereqs: steps 1–5 done + Step 6 dossier exists; Neo4j (step 5) running.
python src/sync_crosscheck_to_neo4j.py            # Step 6b: dossier → Neo4j advisory layer (free)
python src/report_claim_ledger.py                 # Step 7: AAA ledger (contradicted + supported)
python src/report_claim_ledger.py --review-queue  #   contradiction, no verification (14)
python src/report_claim_ledger.py --assessment all --markdown
```

No API key, no token cost — both scripts are LLM-free.

## 7. Related docs

[`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) (§9) ·
[`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md) (Step 6 — the dossiers this consumes) ·
[`GRAPH_LOAD_NEO4J.md`](./GRAPH_LOAD_NEO4J.md) (Step 5 — the graph the advisory layer sits on) ·
[`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md)
