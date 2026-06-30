# Graph load into Neo4j (step 5)

Script: [`src/load_graph_to_neo4j.py`](../src/load_graph_to_neo4j.py).
Input: `graph_output/resolved/resolved_graph.json` (step-4 output).
Output: a property graph in a Neo4j instance (default `bolt://localhost:8687`, db `neo4j`).

This step plays the role of EmeraldMind's `5-load_edgelist_graph.py` but is a **redesign,
not a port** — the reference loads a flat edge-list and re-derives node identity at load
time, which is wrong for our data. See the rationale below.

## Why a redesign

| | reference `5-load_edgelist_graph.py` | our `resolved_graph.json` |
|---|---|---|
| Top level | flat **list** of edges | `{"nodes":[…], "edges":[…]}` |
| Node location | embedded in each edge by value | separate `nodes[]` array |
| Edge → node | by value (`{class, properties}`) | by **integer index** into `nodes[]` |
| Node dedup | the loader does it (`generate_node_key`) | **already done by step 4** |
| Node history | none | `temporal_versions[]` |
| Edge time | none created (bare relationship) | `temporal_metadata` on every edge |

## The three things this loader gets right

1. **No re-deduplication.** Entity identity is owned by step 4. A node's id is its array
   index (`_node_key = "n{i}"`); edges are rewired from integer indices to those keys.
   Re-running the reference's `generate_node_key` would re-key by full property JSON and
   could split/merge differently than the resolver did.

2. **Edge time is preserved.** `temporal_metadata` is flattened onto each relationship
   (`valid_from`/`valid_to`/`recorded_at`), and edges MERGE on a deterministic `_edge_key`
   = `sha1(subject|predicate|object|valid_from|valid_to|recorded_at)`. This matters because
   many (subject, predicate, object) triples recur across different years (e.g. `isIn`
   between the same pair in 2009/2011/2012/2013); a naive `MERGE (a)-[:TYPE]->(b)` would
   collapse them into one and destroy the time series. There are no exact-duplicate edges,
   so keying on the full tuple is safe and keeps re-runs idempotent.

3. **Temporal history is faithful where the schema allows it (hybrid).** `supersedes` is
   only legal between identical entity classes (Organization, Person, Facility, Goal,
   Product, Regulation, Standard, Material, Certification). For nodes of those classes with
   >1 version, each distinct version becomes its own node, chained
   `canonical -[:supersedes]-> newest -> … -> oldest` (ordered by leading-year of
   `valid_from`); the canonical node is the head (`is_current = true`) and is what all data
   edges attach to. For every other class, the full `temporal_versions` list is stored as a
   JSON-string property instead, so no schema-illegal `supersedes` edge is emitted.

## Implementation notes

- Every node also carries a shared `:_Entity` label. Cypher cannot parameterize a label and
  an unlabeled `MATCH` can use no index, so a single `(:_Entity) ON (n._node_key)` index
  serves all endpoint lookups during edge ingestion.
- Vietnamese values need no special handling: `_cypher_safe` only sanitizes keys/labels/
  predicates (English here); UTF-8 values are stored verbatim. The clean canonical name
  lives on `properties.name`; OCR garble (e.g. `MÔI TRƢỜNG`) survives only inside the
  version chain as provenance.
- Validation is a **warning**, not a gate (the graph is already validated in step 3 and
  resolved in step 4); pass `--strict` to abort on any unknown class/predicate.

## Setup — start a Neo4j instance (one-time, recommended: Docker)

The loader is a **client**; it does not start a database. For a team, the reproducible
option is the committed [`docker-compose.yml`](../docker-compose.yml) (Enterprise image, so
everyone shares the same `greenwashing` user + `greenwashingkg` database — Community only
has the single `neo4j` user and default db).

```bash
# 1. start the DB (bolt :8687, browser http://localhost:8474)
docker compose up -d
docker compose ps                 # wait until STATUS shows "healthy"

# 2. one-time: create the greenwashing user + greenwashingkg database (idempotent)
docker cp neo4j/init.cypher greenwashing-kg:/tmp/init.cypher
docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui -d system -f /tmp/init.cypher

# 3. point the loader at it: copy .env.example -> .env (defaults already match)
```

`neo4j/init.cypher` is run as the admin `neo4j` user against the `system` db; it sets
`greenwashingkg` as the user's HOME DATABASE so the loader targets it automatically.

**Plain Community / no Docker:** start any Neo4j on bolt `:8687`, set the `neo4j`
password to `nammovuivui`, and in `.env` set `NEO4J_USER="neo4j"` and leave
`NEO4J_DATABASE` unset (loads into the default `neo4j` db). The `greenwashing` user and
named database require Enterprise/Desktop.

## Run

```bash
pip install -r requirements.txt          # adds neo4j>=5.0
python src/load_graph_to_neo4j.py --dry-run    # offline: print planned counts, no DB
python src/load_graph_to_neo4j.py --clear      # wipe + load (needs the instance running)
```

Connection comes from `.env` (`NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` /
`NEO4J_DATABASE`) or CLI flags (`--uri` / `--user` / `--password` / `--database`).
`--no-versions` loads canonical nodes only (skips the supersedes chains).

## Verify after loading

```cypher
// totals
MATCH (n) RETURN count(n);
MATCH ()-[r]->() RETURN count(r);

// multi-year edge preserved (distinct years between the same pair)
MATCH (:Organization)-[r:isIn]->() WHERE r.valid_from <> '' RETURN r.valid_from ORDER BY r.valid_from;

// version chain for the AAA issuer
MATCH p=(o:Organization {ticker:'AAA'})-[:supersedes*]->() RETURN p;

// edge time present
MATCH ()-[r:reportsKPI]->() RETURN r.valid_from LIMIT 5;
```

Re-running without `--clear` must not change node/edge counts (MERGE on `_node_key` /
`_edge_key`).
