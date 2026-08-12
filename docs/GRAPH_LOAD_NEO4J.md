# Stage 06 — loading the resolved graph into Neo4j

```bash
docker compose up -d                       # start the instance
python src/run.py neo4j_load --dry-run     # preview planned counts, no DB
python src/run.py neo4j_load --clear       # wipe and load
```

Module: `src/esg_kg/load/neo4j_load.py` · Input:
`graph_output/resolved/resolved_graph.json` · Output: a queryable property graph

No LLM. Materializes the resolved `{nodes, edges}` graph so the cross-check, the ledger,
the Evidence View and ad-hoc Cypher can all read one source.

---

## 1. Setting up the instance

`docker-compose.yml` runs **Neo4j 5 Enterprise** (the dev licence is free for
non-production and academic use) so the team can share one named database and one custom
user — Community only offers the single `neo4j` user and the default database.

```bash
docker compose up -d
# wait for healthy, then run the one-time bootstrap:
docker cp neo4j/init.cypher greenwashing-kg:/tmp/init.cypher
docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui -d system -f /tmp/init.cypher
```

| Setting | Value |
|---|---|
| Bolt | `bolt://localhost:8687` |
| Browser | `http://localhost:8474` |
| Database | `greenwashingkg` |
| Team user | `greenwashing` (home database `greenwashingkg`, so `--database` is optional) |

`neo4j/init.cypher` is idempotent: it creates the database, the user, and the role grant.
The password in the compose file is a **local development password** — change it, and do
not commit it, for anything beyond a local instance.

Override the connection with `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` in `.env`, or
with `--uri` / `--user` / `--password` / `--database`.

`neo4j_data/` is never synced with the dataset repo: a live database volume is corrupt if
copied while running and is pinned to the image version. Rebuild it locally with this
stage instead — one command, no LLM.

---

## 2. Why this is a redesign, not a port

The reference implementation loads a flat edge list with nodes embedded by value, no
temporal data, and re-derives node identity at load time. This loader's input is different
in three ways that each change the design:

1. edges reference nodes by **integer index**, not by value;
2. entities are **already resolved** upstream;
3. nodes and edges **carry temporal data**.

Two things follow, and they are the two things this stage must not get wrong.

### 2.1 Entities are not re-deduplicated

Stage 05 owns identity. A node's key is its **array index**: `_node_key = "n{i}"`, and
edges are rewired from indices to those keys. Re-deriving identity here would silently
disagree with the resolver.

This is why the append-only and node-order invariants matter so much upstream — see
[PROVENANCE_PATCH.md](PROVENANCE_PATCH.md) §3.

Every node also receives a shared label so one index serves all `_node_key` lookups:

```cypher
CREATE INDEX IF NOT EXISTS FOR (n:`<SharedLabel>`) ON (n._node_key)
```

### 2.2 Edge time is preserved

`temporal_metadata` is flattened onto each relationship, and edges `MERGE` on a
deterministic `_edge_key` that **includes the temporal fields**. This is load-bearing: the
same pair of nodes is frequently connected in several different years, and a naive `MERGE`
on (subject, predicate, object) would collapse them into one relationship and destroy the
time series the whole project is built on.

---

## 3. Temporal node history

`temporal_versions` is materialized in whichever way the schema permits:

- **Classes with a legal `supersedes` self-edge** — `Organization`, `Facility`, `Person`,
  `Goal`, `Standard`, `Product`, `Material`, `Certification`, `Regulation` — get a real
  version-node chain:

  ```
  canonical -[:supersedes]-> newest -> … -> oldest
  ```

- **Every other class** keeps its history as a JSON-string property, so no schema-illegal
  edge is ever emitted.

`--no-versions` loads canonical nodes only, which is useful for a fast smoke check.

---

## 4. What the loader writes

| Phase | Cypher shape |
|---|---|
| `setup_indexes` | one index per label on `_node_key` |
| `clear_database` | only with `--clear` |
| `ingest_nodes` | `MERGE (n:Label:Shared {_node_key: r._node_key}) SET n += r` in batches |
| `ingest_data_edges` | `MATCH` both endpoints by `_node_key`, then `MERGE` the relationship on `_edge_key` |
| `ingest_supersedes` | the version chains |
| `print_graph_stats` | read-back counts |

`build_payload()` is a pure function — it turns the resolved graph into the batched
payloads without touching a database, which is what makes the stage testable offline.

---

## 5. Flags

| Flag | Meaning |
|---|---|
| `-i` | Resolved graph (default `graph_output/resolved/resolved_graph.json`) |
| `-s` | Schema path |
| `--uri`, `--user`, `--password`, `--database` | Connection; env fallbacks `NEO4J_*` |
| `--batch-size` | Rows per write transaction |
| `--clear` | Wipe the database first |
| `--no-versions` | Canonical nodes only, no version chains |
| `--strict` | Fail on conditions that are otherwise warnings |
| `--dry-run` | Compute and report the payload, touch no database |

---

## 6. Verifying a load

```cypher
// counts by label
MATCH (n) RETURN labels(n)[0] AS label, count(*) ORDER BY count(*) DESC;

// multi-year edges survived
MATCH (a)-[r:reportsKPI]->(b)
RETURN a._node_key, count(DISTINCT r.valid_from) AS years
ORDER BY years DESC LIMIT 5;

// version chains
MATCH p = (c)-[:supersedes*]->(v) RETURN c.name, length(p) ORDER BY length(p) DESC LIMIT 5;
```

Analyst queries live in `neo4j/crosscheck_queries.cypher`.

---

## 7. What comes next

`neo4j_load` writes the **base** graph — extracted facts only. The advisory layer
(`assessment`, `caveats`, `llm_supports` / `llm_contradicts` edges) is written separately by
`neo4j_sync` (08) so that an advisory opinion is never confused with an extracted fact. See
[CLAIM_LEDGER.md](CLAIM_LEDGER.md).

---

## 8. Tests

`python test/test_esg_kg_neo4j_load.py` — `build_payload()` as a pure function on the real
corpus, plus an ingestion arm that compares every Cypher string and parameter dict against
a fake session/transaction that records calls and executes nothing. No live database is
needed, and none is touched.
