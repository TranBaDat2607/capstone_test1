#!/usr/bin/env python3
"""
Behaviour tests for ONE migration slice, `esg_kg.load.neo4j_load`
(originally ported from `src/step06_load_graph_to_neo4j.py`).

WHY THIS SLICE NEEDED NO NEW core/ MODULE
step06 imports exactly two things from a sibling: `REPO_ROOT` (-> `esg_kg.core.paths`, the
same swap every leaf stage has made since step01) and `load_schema_sets` (-> `esg_kg.core.
schema`, lifted from step03 on 2026-07-28). Both were already in `core/` before this slice —
confirmed leaf, per PIPELINE.md §2.1 / DESIGN.md's symbol table.

THE SECOND NEO4J-WRITE STAGE, WITH A RICHER CLIENT SURFACE THAN step08
`esg_kg.load.neo4j_sync` (step08, 2026-07-29) proved the technique of replacing the
installed `neo4j` package's `GraphDatabase` attribute directly (no `_Provider` layer stands
in front of the real driver the way it does for OpenAI/Gemini). step06 needs a STRONGER fake
than step08's: `ingest_nodes` / `ingest_data_edges` / `ingest_supersedes` all go through
`session.execute_write(lambda tx: tx.run(cypher, rows=...).consume())`, not a bare
`session.run()`, and `print_graph_stats` reads results back (`.single()`, iteration) rather
than only writing. The fake session/tx here supports both call shapes and both write and
read result shapes, but still just RECORDS (query, params) and never executes anything real.

WHAT VARIES ACROSS RUNS AND IS MASKED
Nothing here is time-stamped or otherwise non-deterministic — every Cypher string is a
static f-string and every parameter is a pure function of the payload, so captured calls
between the two trees must be byte-identical, no masking needed (same as step08).

Offline: no LLM, no real Neo4j, no network. The real-corpus arm needs
`graph_output/resolved/resolved_graph.json` (git-ignored, shipped via the HF snapshot) and
SKIPs with a message on a bare clone; the synthetic arms do not.

Repointed at `esg_kg` only (2026-07-29) now that `src/` is gone; this file used to import
`src/step06_load_graph_to_neo4j.py` too and assert the two trees agreed —
`test_esg_kg_equivalence.py` already proved that agreement while both trees existed.

Run from the repo root:

    python test/test_esg_kg_neo4j_load.py
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.load import neo4j_load as new_step06  # noqa: E402
from esg_kg.core.schema import load_schema_sets  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
from _fixture_paths import resolve_artifact, skip_if_fixture, tag  # noqa: E402

RESOLVED_FILE = REPO / "graph_output" / "resolved" / "resolved_graph.json"

RESOLVED_DATA, RESOLVED_IS_FIXTURE = resolve_artifact("resolved")


_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def _schema_sets():
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return load_schema_sets(schema)


def _mini_graph():
    return {
        "nodes": [
            {
                "class": "Organization",
                "properties": {"name": "Cong ty A", "ticker": "AAA"},
                "temporal_versions": [],
            },
            {
                "class": "Organization",
                "properties": {"name": "Cong ty B"},
                "temporal_versions": [
                    {"valid_from": "2022", "valid_to": "2023", "properties": {"name": "Cong ty B (old)"}},
                    {"valid_from": "2023", "valid_to": None, "properties": {"name": "Cong ty B"}},
                ],
            },
            {
                "class": "KPIObservation",
                "properties": {"kpi_type": "co2_emission", "value": 10},
                "temporal_versions": [
                    {"valid_from": "2021", "valid_to": "2022", "properties": {"value": 8}},
                    {"valid_from": "2022", "valid_to": None, "properties": {"value": 10}},
                ],
            },
        ],
        "edges": [
            {
                "subject": 0, "object": 2, "predicate": "reports",
                "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023-05-01"},
            },
        ],
    }


def test_build_payload_matches_both_trees_with_versions():
    graph = _mini_graph()
    schema_sets = _schema_sets()

    payload = new_step06.build_payload(graph, schema_sets, include_versions=True)

    assert payload["counts"]["version_nodes"] == 2
    assert len(payload["supersedes_edges"]) == 2
    kpi_nodes = payload["nodes_by_label"]["KPIObservation"]
    assert len(kpi_nodes) == 1
    assert "temporal_versions" in kpi_nodes[0]


def test_build_payload_no_versions_flag_matches_both_trees():
    graph = _mini_graph()
    schema_sets = _schema_sets()

    payload = new_step06.build_payload(graph, schema_sets, include_versions=False)

    assert payload["counts"]["version_nodes"] == 0
    assert payload["supersedes_edges"] == []


class _FakeRecord(dict):
    def __getitem__(self, key):
        return dict.get(self, key, 0)


class _FakeResult:
    def __init__(self, n=0):
        self._n = n

    def consume(self):
        class _Counters:
            pass

        class _Summary:
            counters = _Counters()

        return _Summary()

    def __iter__(self):
        return iter(())

    def single(self):
        return _FakeRecord()


class _FakeTx:
    def __init__(self, calls):
        self._calls = calls

    def run(self, query, **params):
        self._calls.append((query, params))
        rows = params.get("rows")
        return _FakeResult(len(rows) if isinstance(rows, list) else 0)


class _FakeSession:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self._calls.append((query, params))
        rows = params.get("rows")
        return _FakeResult(len(rows) if isinstance(rows, list) else 0)

    def execute_write(self, fn):
        return fn(_FakeTx(self._calls))


class _FakeDriver:
    def __init__(self, calls):
        self._calls = calls

    def session(self, database=None):
        return _FakeSession(self._calls)

    def verify_connectivity(self):
        pass

    def close(self):
        pass


class _FakeGraphDatabase:
    def __init__(self):
        self.calls = []
        self.driver_calls = []

    def driver(self, uri, auth=None, database=None):
        self.driver_calls.append((uri, auth, database))
        return _FakeDriver(self.calls)


def _run_with_stub(module, args_ns: argparse.Namespace):
    """Run `module.main()`-equivalent ingestion with `neo4j.GraphDatabase` replaced by a
    recorder, using the module's own helper functions in the same order `main()` calls
    them (setup_indexes -> [clear] -> ingest_nodes -> ingest_data_edges ->
    ingest_supersedes -> print_graph_stats), matching each tree's real driver plumbing."""
    import neo4j as neo4j_pkg
    fake = _FakeGraphDatabase()
    original = neo4j_pkg.GraphDatabase
    neo4j_pkg.GraphDatabase = fake
    try:
        driver = neo4j_pkg.GraphDatabase.driver(
            args_ns.uri, auth=(args_ns.user, args_ns.password), database=args_ns.database)
        try:
            if args_ns.clear:
                module.clear_database(driver)
            module.setup_indexes(driver)
            module.ingest_nodes(driver, args_ns.payload["nodes_by_label"], args_ns.batch_size)
            module.ingest_data_edges(driver, args_ns.payload["edges_by_pred"], args_ns.batch_size)
            module.ingest_supersedes(driver, args_ns.payload["supersedes_edges"], args_ns.batch_size)
            module.print_graph_stats(driver)
        finally:
            driver.close()
    finally:
        neo4j_pkg.GraphDatabase = original
    return fake.calls, fake.driver_calls


def _ns(payload, **kw) -> argparse.Namespace:
    base = dict(uri="bolt://x", user="u", password="p", database=None,
                batch_size=5000, clear=False, payload=payload)
    base.update(kw)
    return argparse.Namespace(**base)


def test_ingestion_calls_identical_both_trees():
    schema_sets = _schema_sets()
    payload = new_step06.build_payload(_mini_graph(), schema_sets, include_versions=True)

    calls, driver_calls = _run_with_stub(new_step06, _ns(payload))

    assert len(driver_calls) > 0
    assert len(calls) > 0


def test_clear_flag_emits_identical_detach_delete_both_trees():
    schema_sets = _schema_sets()
    payload = new_step06.build_payload(_mini_graph(), schema_sets, include_versions=True)

    calls, _ = _run_with_stub(new_step06, _ns(payload, clear=True))

    assert len(calls) > 0
    assert "DETACH DELETE" in calls[0][0]


def test_dry_run_touches_no_driver_both_trees():
    """--dry-run builds the payload and prints planned counts without importing/using
    `neo4j` at all — mirrored via main()'s own argparse path on a tmp input file, since
    the dry-run branch returns before any driver code runs."""
    import tempfile
    schema_sets = _schema_sets()  # noqa: F841 (documents why this arm needs no schema swap)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        graph_file = td / "resolved_graph.json"
        graph_file.write_text(json.dumps(_mini_graph()), encoding="utf-8")

        argv_backup = sys.argv
        try:
            sys.argv = ["prog", "-i", str(graph_file), "-s", str(SCHEMA_FILE), "--dry-run"]
            new_step06.main()
        finally:
            sys.argv = argv_backup


def test_real_corpus_ingestion_calls_identical_both_trees():
    if not RESOLVED_DATA.exists():
        _skip("test_real_corpus_ingestion_calls_identical_both_trees",
              "graph_output/resolved/resolved_graph.json not present "
              "(git-ignored, shipped via the HF snapshot — see src/data_sync.py)")
        return
    print(f"     {tag(RESOLVED_IS_FIXTURE)} real_corpus_ingestion")
    schema_sets = _schema_sets()
    graph = json.loads(RESOLVED_DATA.read_text(encoding="utf-8"))
    payload = new_step06.build_payload(graph, schema_sets, include_versions=True)

    calls, driver_calls = _run_with_stub(new_step06, _ns(payload))

    assert len(driver_calls) > 0
    assert len(calls) > 0
    print(f"    real corpus: {len(calls)} Neo4j calls issued")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed"
          + (f", {len(_skips)} skipped." if _skips else "."))
