# Stages 08 / 09 — advisory layer and claim ledger

```bash
python src/run.py neo4j_sync                          # push dossiers into Neo4j (free)
python src/run.py claim_ledger                        # render from Neo4j
python src/run.py claim_ledger --review-queue --markdown
python src/run.py claim_ledger --claim-id claim_4b15ccc97f6d18d5
```

Modules: `load/neo4j_sync.py` · `report/claim_ledger.py` · Output: Neo4j advisory layer,
then `graph_output/crosscheck/<ticker>_claim_ledger.md` and stdout

Neither stage calls an LLM. They reuse the dossier the paid cross-check already produced.

---

## 1. Stage 08 — `neo4j_sync`

The cross-check stores the full picture only in its JSON dossier. Two things therefore
never reach Neo4j on their own:

- the per-claim `assessment` / `caveats` / `signals`, which are computed summaries rather
  than extracted edges;
- the `KPIObservation`-based contradictions, because the schema has no legal
  `Claim → KPIObservation` contradiction edge.

`neo4j_sync` closes that gap **without spending a token**: it re-reads the dossier and
merges it into the graph as an explicitly advisory layer, so the ledger and any Cypher can
read everything from Neo4j alone. Idempotent — a `MERGE` on a stable `_adv_key`.

### 1.1 What it writes

On each `SustainabilityClaim` node:

`assessment` · `assessment_is_advisory = true` · `caveats` (list) ·
`structural_contradiction` · `kpi_gap` · `crosscheck_ticker`

Advisory edges from the claim to its evidence node:

| Dossier list | Edge |
|---|---|
| `supporting_evidence` | `llm_supports` |
| `contradicting_evidence` (incl. KPI gaps) | `llm_contradicts` |
| `flagged_non_independent_support` | `llm_flagged_support` |

Each carrying `llm_suggested=true` plus `confidence` / `rationale` / `provider` /
`evidence_text` / `evidence_class` / `source_domain` / `date` / `year` / `independent` /
`date_uncertain` / `role`.

Every name is namespaced or flagged so an advisory opinion is never mistaken for an
extracted fact. The base graph written by `neo4j_load` stays exactly as extracted.

### 1.2 Node resolution — why this is not just `f"n{node_index}"`

The dossier records `claim_node_index` / `node_index`, which are **positions** in the
resolved graph's node array. Any `entities` re-run that changes clustering shifts those
positions, and a purely positional sync would then bind every advisory edge to the **wrong
node** — no error, just a corrupt layer.

So claims are resolved by a **stable id first**, falling back to position. This is also why
`claim_id` had to become deterministic ([TRIPLET_EXTRACTION_FROM_JSONL.md](TRIPLET_EXTRACTION_FROM_JSONL.md) §3):
claim resolution here is 100% stable-id with no fallback path that could rescue a
re-invented id.

### 1.3 Flags

`--ticker` · `-i` (dossier) · `--resolved` · `--uri` / `--user` / `--password` /
`--database` · `--clear-advisory` · `--dry-run`

`--clear-advisory` removes the advisory layer before writing. It is scoped to the ticker
being synced — a scoping bug that once cleared other tickers' advisory data was fixed in
commit `7c108f9`.

---

## 2. Stage 09 — `claim_ledger`

The final presentation stage. It reads **only Neo4j** — the JSON dossier is not touched
here — and renders a per-company claim ledger.

**Prerequisite:** run `neo4j_sync` first, or the ledger will be empty.

### 2.1 Ordering is signal-first

Claims are grouped and sorted so the ones that need attention come first:

```
appears_contradicted  →  appears_supported  →  unverified/insufficient
```

Within a group, claims with more and higher-confidence evidence rank higher. The point of a
ledger is triage, not completeness in reading order.

### 2.2 What a rendered entry contains

```markdown
### `claim_aa74212799d3dc3c` — [2015-01-01, report] — _AAA_2021 p.38_

> Sản phẩm bao bì tự hủy thân thiện với môi trường

**Assessment:** appears_contradicted (advisory)

- ✗ **KPIObservation** (conf 0.90, 2030, baodautu.vn; «article title»): "..."
    - _rationale:_ ...
- _signals:_ structural_contradiction=false, kpi_gap=none
- _caveat:_ No ground-truth greenwashing label exists; this is an advisory opinion.
```

The source reference (`AAA_2021 p.38`, or an article title and domain for news) comes from
the provenance stamps — see [PROVENANCE_PATCH.md](PROVENANCE_PATCH.md). That line is the
whole payoff of keeping sentence-level traceability through nine stages.

### 2.3 The header

Every ledger opens with the advisory banner, the assessment histogram, and the **coverage
line**:

```
**Independent conduct on the issuer:** 298 KPIObservation, 41 MediaReport, 3 Penalty.
⚠ Thin independent conduct — absence of contradiction is NOT exoneration.
```

That warning is not decoration. It is the mechanism that stops a reader from interpreting
28 `unverified` claims as 28 clean ones ([SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §8.3).

### 2.4 The review queue

`--review-queue` narrows to the cases a human should look at first: a claim with
contradicting evidence and **no** independent verification. It is the smallest useful
output of the whole pipeline.

### 2.5 Flags

| Flag | Meaning |
|---|---|
| `--ticker` | Which company |
| `--assessment` | Filter by assessment value, or `all` |
| `--review-queue` | Contradiction with no independent verification |
| `--claim-id` | A single claim, in full |
| `--limit` | Cap entries |
| `--maxlen` | Truncation length for quoted text |
| `--markdown` | Also write `graph_output/crosscheck/<ticker>_claim_ledger.md` |
| `--uri` / `--user` / `--password` / `--database` | Connection |

---

## 3. Cypher for the same questions

`neo4j/crosscheck_queries.cypher` holds the analyst set. The two most used:

```cypher
// Review queue: contradicted, never independently verified
MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})-[:llm_contradicts]->(e)
WHERE NOT (c)-[:llm_supports]->()
RETURN c.claim_id, c.description, collect(e.evidence_text)[..3] AS evidence;

// Evidence independence mix for one company
MATCH (c:SustainabilityClaim {crosscheck_ticker:$t})-[x]->(e)
WHERE type(x) STARTS WITH 'llm_'
RETURN type(x) AS role, x.independent AS independent, count(*) AS n
ORDER BY role;
```

---

## 4. Known issues

- **`signals` are inert.** Both stages read and render `structural_contradiction` and
  `kpi_gap`, but stage 07 never writes them, so every claim shows `false` / `none`
  permanently. See [ROADMAP.md](ROADMAP.md) §2.1.
- **The header banner references `docs/SOFTMAX_SCORING.md`**, and `neo4j_sync`'s docstring
  references evidence-balance score fields. Both belong to the removed `step07b` stage and
  are dead references in the code, not pending features.
- **Ledger output in the pinned snapshot predates a bug fix.** Commit `7c108f9` fixed
  cross-company contamination in the cross-check; ledger files generated before it can show
  another ticker's penalty attached to this ticker's claim. Regenerate rather than trusting
  an old `.md`.

---

## 5. Tests

`python test/test_esg_kg_neo4j_sync.py` — compares real Neo4j calls byte-for-byte against a
fake driver that records Cypher and parameters and executes nothing; covers
`--clear-advisory`, a missing resolved graph, and the missing-dossier exit guard.

`python test/test_esg_kg_claim_ledger.py` — the first Neo4j-**reading** stage, so the fake
driver must return real fake data: a queue of result sets in the exact order of the
session calls, so both the Cypher sent and the dossiers assembled from the rows can be
compared. The strongest arm covers the pure presentation and sorting helpers, which carry
most of the stage's logic.

`python test/test_temporal_invariants.py` — includes stage-08 stable-id (`claim_id`)
resolution.
