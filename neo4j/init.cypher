// One-time bootstrap for the greenwashing KG Neo4j instance (run against the
// `system` database as the admin `neo4j` user). Idempotent — safe to re-run.
// Apply with:
//   docker cp neo4j/init.cypher greenwashing-kg:/tmp/init.cypher
//   docker exec greenwashing-kg cypher-shell -u neo4j -p nammovuivui -d system -f /tmp/init.cypher

// 1. The named database the loader writes into (--database greenwashingkg / NEO4J_DATABASE).
CREATE DATABASE greenwashingkg IF NOT EXISTS;

// 2. The shared team login. HOME DATABASE makes greenwashingkg the default for this
//    user, so the loader writes there even without an explicit --database.
CREATE USER greenwashing IF NOT EXISTS
  SET PASSWORD 'nammovuivui' CHANGE NOT REQUIRED
  SET HOME DATABASE greenwashingkg;

// 3. Give the user full rights (create indexes + read/write). `admin` is fine for a
//    local dev/capstone instance; scope it down with a custom role for shared servers.
GRANT ROLE admin TO greenwashing;
