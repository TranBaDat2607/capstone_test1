#!/usr/bin/env python3
"""
Step 5 — load the resolved temporal knowledge graph into Neo4j.

Consumes the step-4 output `graph_output/resolved/resolved_graph.json`
(`{"nodes": [...], "edges": [...]}`, already deduplicated by entity resolution) and
materializes it as a queryable property graph in Neo4j, so the greenwashing
cross-check ("do a company's *reported* ESG claims match its *real-world* conduct,
over time?") can actually be run with Cypher.

A deliberate redesign of EmeraldMind/src/EmeraldKG/5-load_edgelist_graph.py, NOT a port:
that reference loads a flat edge-list (nodes embedded by value, no temporal data) and
re-derives node identity at load time. Our input is a separate node/edge graph whose
edges reference nodes by integer index, whose entities are *already* resolved, and whose
edges/nodes carry temporal data. The two things this loader must not get wrong:

  1. Entities are NOT re-deduplicated — step 4 owns identity. A node's id is its
     array index (`_node_key = "n{i}"`); edges are rewired from indices to those keys.
  2. Edge time is preserved. `temporal_metadata` is flattened onto each relationship,
     and edges MERGE on a deterministic `_edge_key` (incl. the temporal fields) so the
     many multi-year edges between the same pair stay distinct (a naive MERGE would
     collapse them and destroy the time series).

Temporal node history (`temporal_versions`) is materialized faithfully where the schema
allows it: classes that have a legal `supersedes` self-edge get a version-node chain
(`canonical -[:supersedes]-> newest -> ... -> oldest`); every other class keeps its
history as a JSON-string property so no schema-illegal edge is emitted.

Run from the repo root:  python src/load_graph_to_neo4j.py
Connection defaults target a dedicated Neo4j Community instance; override via .env
(NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD) or CLI flags. Reuses REPO_ROOT and
load_schema_sets from the earlier stages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from extract_kpi_from_jsonl import REPO_ROOT
from fix_invalid_triplets import load_schema_sets

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_URI = "bolt://localhost:8687"
DEFAULT_USER = "greenwashing"
DEFAULT_PASSWORD = "nammovuivui"
DEFAULT_BATCH = 5000

# Every node also gets this shared label so a single index serves _node_key lookups
# during edge ingestion (Cypher cannot parameterize a label, and an unlabeled MATCH
# can use no index).
SHARED_LABEL = "_Entity"

_RE_NON_WORD = re.compile(r"[^\w]")


# --------------------------------------------------------------------------- #
# Helpers adapted from the reference loader (EmeraldMind is read-only).
# --------------------------------------------------------------------------- #
def _cypher_safe(s: str) -> str:
    return _RE_NON_WORD.sub("_", s)


def _normalize_props(props: dict) -> dict:
    """Coerce property values into Neo4j-storable scalars/lists (None->'', nested->JSON)."""
    out: Dict[str, Any] = {}
    for k, v in props.items():
        if v is None:
            out[k] = ""
        elif isinstance(v, dict):
            out[k] = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, list):
            if v and isinstance(v[0], dict):
                out[k] = json.dumps(v, ensure_ascii=False)
            else:
                out[k] = v
        else:
            out[k] = v
    return out


def _sanitize_props(d: dict) -> dict:
    return {_cypher_safe(k): v for k, v in d.items()}


def _row_props(props: dict) -> dict:
    return _sanitize_props(_normalize_props(props))


def _deterministic(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _year_sort_key(valid_from: Any) -> Tuple[int, str]:
    """Sort key for temporal ordering; leading 4-digit year, unknown/None sorts last."""
    s = "" if valid_from is None else str(valid_from)
    m = re.match(r"\s*(\d{4})", s)
    return (int(m.group(1)) if m else -1, s)


def batched(seq: List[Any], n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


# --------------------------------------------------------------------------- #
# Build the load payload from the resolved graph (no DB needed — used by --dry-run).
# --------------------------------------------------------------------------- #
def build_payload(
    graph: Dict[str, Any],
    schema_sets: Tuple[set, set, Dict[str, List[Tuple[str, str]]]],
    include_versions: bool,
) -> Dict[str, Any]:
    entity_classes, edge_labels, edge_directions = schema_sets
    supersedes_classes = {src for (src, _dst) in edge_directions.get("supersedes", [])}

    raw_nodes: List[dict] = graph["nodes"]
    raw_edges: List[dict] = graph["edges"]
    node_class = [n.get("class") for n in raw_nodes]

    nodes_by_label: Dict[str, List[dict]] = defaultdict(list)  # label -> [props incl _node_key]
    supersedes_edges: List[dict] = []                          # {sub, obj}
    warnings: List[str] = []

    for i, n in enumerate(raw_nodes):
        cls = n.get("class")
        if cls not in entity_classes:
            warnings.append(f"node n{i}: class {cls!r} not in schema")
        props = dict(n.get("properties") or {})
        versions = n.get("temporal_versions") or []

        # Current temporal fields come from the latest-valid_from version.
        current = max(versions, key=lambda v: _year_sort_key(v.get("valid_from")), default=None)
        node_props = dict(props)
        node_props["is_current"] = True
        if current:
            node_props["valid_from"] = current.get("valid_from")
            node_props["valid_to"] = current.get("valid_to")
        node_props["_node_key"] = f"n{i}"

        materialize = include_versions and cls in supersedes_classes and len(versions) > 1
        if materialize:
            # Dedup identical versions; chain newest -> oldest under the canonical node.
            seen: set = set()
            distinct: List[dict] = []
            for v in versions:
                vp = dict(v.get("properties") or {})
                sig = _deterministic(vp)
                if sig in seen:
                    continue
                seen.add(sig)
                distinct.append(vp)
            distinct.sort(key=lambda vp: _year_sort_key(vp.get("valid_from")), reverse=True)
            prev_key = node_props["_node_key"]
            for j, vp in enumerate(distinct):
                vkey = f"n{i}__v{j}"
                vp = dict(vp)
                vp["is_current"] = False
                vp["_node_key"] = vkey
                nodes_by_label[cls].append(vp)
                supersedes_edges.append({"sub": prev_key, "obj": vkey})
                prev_key = vkey
        elif len(versions) > 1:
            # Non-supersedes class (or --no-versions): keep history as a JSON blob.
            node_props["temporal_versions"] = versions

        nodes_by_label[cls].append(node_props)

    # Data edges: rewire indices -> _node_key, flatten temporal_metadata, key on the
    # full tuple so multi-year edges stay distinct and re-runs are idempotent.
    edges_by_pred: Dict[str, List[dict]] = defaultdict(list)
    for e in raw_edges:
        s, o, pred = e.get("subject"), e.get("object"), e.get("predicate")
        if pred not in edge_labels:
            warnings.append(f"edge n{s}-[{pred}]->n{o}: predicate not in schema")
        tm = e.get("temporal_metadata") or {}
        vf, vt, ra = tm.get("valid_from"), tm.get("valid_to"), tm.get("recorded_at")
        ekey = hashlib.sha1(f"{s}|{pred}|{o}|{vf}|{vt}|{ra}".encode("utf-8")).hexdigest()
        edges_by_pred[_cypher_safe(pred)].append(
            {
                "sub": f"n{s}",
                "obj": f"n{o}",
                "_edge_key": ekey,
                "valid_from": vf if vf is not None else "",
                "valid_to": vt if vt is not None else "",
                "recorded_at": ra if ra is not None else "",
            }
        )

    n_canon = len(raw_nodes)
    n_version = sum(len(v) for v in nodes_by_label.values()) - n_canon
    return {
        "nodes_by_label": nodes_by_label,
        "edges_by_pred": edges_by_pred,
        "supersedes_edges": supersedes_edges,
        "warnings": warnings,
        "counts": {
            "canonical_nodes": n_canon,
            "version_nodes": n_version,
            "data_edges": len(raw_edges),
            "supersedes_edges": len(supersedes_edges),
        },
        "labels": sorted(nodes_by_label.keys()),
    }


# --------------------------------------------------------------------------- #
# Neo4j ingestion.
# --------------------------------------------------------------------------- #
def setup_indexes(driver, labels: List[str]) -> None:
    logger.info("Creating indexes...")
    with driver.session() as session:
        session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:`{SHARED_LABEL}`) ON (n._node_key)")
    logger.info("Indexes ready")


def clear_database(driver) -> None:
    logger.info("Clearing database...")
    with driver.session() as session:
        session.run(
            "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
        )
    logger.info("Database cleared")


def ingest_nodes(driver, nodes_by_label: Dict[str, List[dict]], batch_size: int) -> int:
    total = sum(len(v) for v in nodes_by_label.values())
    done = 0
    logger.info(f"Ingesting {total} nodes across {len(nodes_by_label)} labels...")
    with driver.session() as session:
        for label, rows in nodes_by_label.items():
            safe = _cypher_safe(label)
            cypher = (
                "UNWIND $rows AS r\n"
                f"MERGE (n:`{safe}`:`{SHARED_LABEL}` {{_node_key: r._node_key}})\n"
                "SET n += r"
            )
            for batch in batched(rows, batch_size):
                payload = [_row_props(p) for p in batch]
                session.execute_write(lambda tx: tx.run(cypher, rows=payload).consume())
                done += len(batch)
                print(f"  nodes: {done}/{total}", end="\r")
    print()
    logger.info(f"Merged {total} nodes")
    return total


def ingest_data_edges(driver, edges_by_pred: Dict[str, List[dict]], batch_size: int) -> int:
    total = sum(len(v) for v in edges_by_pred.values())
    done = 0
    logger.info(f"Ingesting {total} data edges across {len(edges_by_pred)} predicates...")
    with driver.session() as session:
        for pred, rows in edges_by_pred.items():
            cypher = (
                "UNWIND $rows AS r\n"
                f"MATCH (a:`{SHARED_LABEL}` {{_node_key: r.sub}}), "
                f"(b:`{SHARED_LABEL}` {{_node_key: r.obj}})\n"
                f"MERGE (a)-[rel:`{pred}` {{_edge_key: r._edge_key}}]->(b)\n"
                "SET rel.valid_from = r.valid_from, rel.valid_to = r.valid_to, "
                "rel.recorded_at = r.recorded_at"
            )
            for batch in batched(rows, batch_size):
                session.execute_write(lambda tx: tx.run(cypher, rows=batch).consume())
                done += len(batch)
                print(f"  edges: {done}/{total}", end="\r")
    print()
    logger.info(f"Merged {total} data edges")
    return total


def ingest_supersedes(driver, edges: List[dict], batch_size: int) -> int:
    if not edges:
        return 0
    logger.info(f"Ingesting {len(edges)} supersedes edges...")
    cypher = (
        "UNWIND $rows AS r\n"
        f"MATCH (a:`{SHARED_LABEL}` {{_node_key: r.sub}}), "
        f"(b:`{SHARED_LABEL}` {{_node_key: r.obj}})\n"
        "MERGE (a)-[:`supersedes`]->(b)"
    )
    with driver.session() as session:
        for batch in batched(edges, batch_size):
            session.execute_write(lambda tx: tx.run(cypher, rows=batch).consume())
    logger.info(f"Merged {len(edges)} supersedes edges")
    return len(edges)


def print_graph_stats(driver) -> None:
    print("\n" + "=" * 60)
    print("GRAPH STATISTICS")
    print("=" * 60)
    with driver.session() as session:
        rows = session.run(
            "MATCH (n) WITH [l IN labels(n) WHERE l <> $shared][0] AS label "
            "RETURN label, count(*) AS c ORDER BY c DESC",
            shared=SHARED_LABEL,
        )
        print("\nNodes by class:")
        for r in rows:
            print(f"  {r['label']}: {r['c']}")
        rows = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC"
        )
        print("\nRelationships by type:")
        for r in rows:
            print(f"  {r['t']}: {r['c']}")
        nc = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        ec = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"\nTotal: {nc} nodes, {ec} relationships")
    print("=" * 60)


def main() -> None:
    p = argparse.ArgumentParser(description="Step 5 — load the resolved temporal graph into Neo4j.")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("-s", "--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--uri", default=os.getenv("NEO4J_URI", DEFAULT_URI))
    p.add_argument("--user", default=os.getenv("NEO4J_USER", DEFAULT_USER))
    p.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", DEFAULT_PASSWORD))
    p.add_argument("--database", default=None,
                   help="Named DB to load into (default: NEO4J_DATABASE env, else the "
                        "user's home/default database, e.g. greenwashingkg or neo4j)")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    p.add_argument("--clear", action="store_true", help="DETACH DELETE everything first")
    p.add_argument("--no-versions", action="store_true",
                   help="Load canonical nodes only; skip supersedes version-node chains")
    p.add_argument("--strict", action="store_true", help="Abort if any schema warning is raised")
    p.add_argument("--dry-run", action="store_true",
                   help="Build + validate the payload and print planned counts; no DB connection")
    args = p.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    # Re-read connection settings in case .env defines them (argparse defaults captured
    # os.getenv before load_dotenv ran).
    if args.uri == DEFAULT_URI:
        args.uri = os.getenv("NEO4J_URI", DEFAULT_URI)
    if args.user == DEFAULT_USER:
        args.user = os.getenv("NEO4J_USER", DEFAULT_USER)
    if args.password == DEFAULT_PASSWORD:
        args.password = os.getenv("NEO4J_PASSWORD", DEFAULT_PASSWORD)
    if args.database is None:
        args.database = os.getenv("NEO4J_DATABASE")

    logger.info(f"Loading graph: {args.input}")
    graph = json.loads(args.input.read_text(encoding="utf-8"))
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    schema_sets = load_schema_sets(schema)

    payload = build_payload(graph, schema_sets, include_versions=not args.no_versions)
    c = payload["counts"]
    logger.info(
        f"Planned: {c['canonical_nodes']} canonical + {c['version_nodes']} version nodes, "
        f"{c['data_edges']} data + {c['supersedes_edges']} supersedes edges"
    )
    warns = payload["warnings"]
    if warns:
        logger.warning(f"{len(warns)} schema warning(s); first 10:")
        for w in warns[:10]:
            logger.warning(f"  - {w}")
        if args.strict:
            logger.error("Aborting due to --strict.")
            return

    if args.dry_run:
        logger.info("Dry run — no DB connection, nothing written.")
        return

    from neo4j import GraphDatabase  # lazy: --dry-run works without the driver installed

    logger.info(f"Connecting to Neo4j at {args.uri} (db={args.database or 'default'})...")
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password),
                                  database=args.database)
    try:
        driver.verify_connectivity()
        logger.info("Connected.")
        if args.clear:
            clear_database(driver)
        setup_indexes(driver, payload["labels"])
        ingest_nodes(driver, payload["nodes_by_label"], args.batch_size)
        ingest_data_edges(driver, payload["edges_by_pred"], args.batch_size)
        ingest_supersedes(driver, payload["supersedes_edges"], args.batch_size)
        print_graph_stats(driver)
        logger.info("Graph loaded into Neo4j.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
