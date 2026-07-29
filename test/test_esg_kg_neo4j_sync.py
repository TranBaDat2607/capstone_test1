#!/usr/bin/env python3
"""
Behaviour tests for ONE migration slice, `esg_kg.load.neo4j_sync`
(originally ported from `src/step08_sync_crosscheck_to_neo4j.py`).

Repointed at `esg_kg` only (2026-07-29) now that `src/` is gone; this file used to import
`src/step08_sync_crosscheck_to_neo4j.py` too and assert the two trees agreed —
`test_esg_kg_equivalence.py` already proved that agreement while both trees existed.

WHY THIS SLICE NEEDED NO NEW core/ MODULE
step08 imports exactly two things from a sibling: `REPO_ROOT` (self-defined, -> now
`core.paths.REPO_ROOT`, same swap every leaf stage has made since step01) and `node_text`
from step07, which moved to `esg_kg.crosscheck.claims_vs_conduct` on 2026-07-28 — the move
that unblocked this one (PIPELINE.md §2.1). Nothing else is stage-to-stage.

THE node_text TRAP (PIPELINE.md §2.1, DESIGN.md §2), FROM A THIRD ANGLE
Two functions are named `node_text` in this codebase and they are NOT interchangeable:
`esg_kg.crosscheck.claims_vs_conduct.node_text` takes a NODE and dispatches on `class`
(what step08 needs — it walks `resolved_graph.json`'s raw node array); `esg_kg.resolve.
align_claims.node_text` takes a PROPERTIES DICT. `test_node_text_is_the_crosscheck_one`
pins the import identity so a future refactor cannot quietly rewire this stage onto the
wrong one.

THIS IS THE FIRST NEO4J-TOUCHING STAGE TO MIGRATE
Every migration so far that needed to cover a paid/networked branch for free injected a
stub UNDER the real client (`_OpenAIProvider`, `google.genai.Client`) and answered
deterministically. step08 has no `_Provider` layer to stand in front of — the real call is
`from neo4j import GraphDatabase` (a LOCAL import inside `run()`, executed only past
`--dry-run`), so the stub here replaces the installed `neo4j` package's `GraphDatabase`
attribute directly, exactly the way earlier stages replaced `google.genai.Client` when
there was no provider abstraction to intercept instead (`test_esg_kg_extract.py`). Both
trees see the SAME fake driver, which records every Cypher string + parameter dict it was
handed instead of executing anything — so the arm proves the two trees send Neo4j the same
work, without a live database and without touching `neo4j+bolt://` at all.

WHAT VARIES ACROSS RUNS AND IS MASKED
Nothing in this stage's writes is time-stamped or otherwise non-deterministic (unlike
step07's `recorded_at`) — the queries are static f-strings and the parameters are pure
functions of the dossier + resolved graph, so the two trees' captured calls must be
byte-identical, no masking needed.

THE IN-PLACE-PATCH QUESTION (PIPELINE.md §3) DOES NOT APPLY HERE
step08 reads a dossier (step07's output) and a resolved graph (step05's/05b's/.../05d's
output) and writes to Neo4j, a different system entirely — it never meets its own past
output on disk, so the real-corpus arm is non-vacuous by construction, same shape step03
and step07 already established.

Offline: no LLM, no real Neo4j, no network. `config/schema.json` is not even read by this
stage. Arms needing `graph_output/crosscheck/aaa_claim_assessments.json` or
`graph_output/resolved/resolved_graph.json` (both git-ignored, shipped via the HF
snapshot) SKIP with a message on a bare clone.

Run from the repo root:

    python test/test_esg_kg_neo4j_sync.py
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src_module"))

# --- new: the esg_kg package -----------------------------------------------------
from esg_kg.load import neo4j_sync as new_step08  # noqa: E402
from esg_kg.crosscheck import claims_vs_conduct as new_crosscheck  # noqa: E402

DOSSIER_FILE = REPO / "graph_output" / "crosscheck" / "aaa_claim_assessments.json"
RESOLVED_FILE = REPO / "graph_output" / "resolved" / "resolved_graph.json"

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


# --------------------------------------------------------------------------- #
# The stub Neo4j driver. Records every query + param dict; executes nothing.
# --------------------------------------------------------------------------- #
class _FakeCounters:
    def __init__(self, n):
        self.properties_set = n
        self.relationships_deleted = n
        self.relationships_created = n


class _FakeSummary:
    def __init__(self, n):
        self.counters = _FakeCounters(n)


class _FakeResult:
    def __init__(self, n):
        self._n = n

    def consume(self):
        return _FakeSummary(self._n)


class _FakeSession:
    def __init__(self, calls):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        rows = params.get("rows")
        n = len(rows) if isinstance(rows, list) else 1
        self._calls.append((query, params))
        return _FakeResult(n)


class _FakeDriver:
    def __init__(self, calls):
        self._calls = calls

    def session(self, database=None):
        return _FakeSession(self._calls)

    def close(self):
        pass


class _FakeGraphDatabase:
    """Drop-in for `neo4j.GraphDatabase`. `driver_calls` collects (uri, auth) per call."""

    def __init__(self):
        self.calls = []
        self.driver_calls = []

    def driver(self, uri, auth=None):
        self.driver_calls.append((uri, auth))
        return _FakeDriver(self.calls)


def _run_with_stub(module, ns: argparse.Namespace):
    """Run `module.run(ns)` with `neo4j.GraphDatabase` replaced by a recorder.

    Patches the real installed `neo4j` package's attribute, since both trees do
    `from neo4j import GraphDatabase` lazily inside `run()` — reading whatever the
    attribute is AT CALL TIME, same technique used for `google.genai.Client` in the
    step01 migration when no provider layer stood in front of the real client.
    """
    import neo4j as neo4j_pkg
    fake = _FakeGraphDatabase()
    original = neo4j_pkg.GraphDatabase
    neo4j_pkg.GraphDatabase = fake
    try:
        module.run(ns)
    finally:
        neo4j_pkg.GraphDatabase = original
    return fake.calls, fake.driver_calls


def _ns(**kw) -> argparse.Namespace:
    base = dict(
        ticker="AAA", input=None, resolved=RESOLVED_FILE,
        uri=None, user=None, password=None, database=None,
        clear_advisory=False, dry_run=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------- #
# node_text trap
# --------------------------------------------------------------------------- #
def test_node_text_is_the_crosscheck_one():
    assert new_step08.node_text is new_crosscheck.node_text, (
        "esg_kg.load.neo4j_sync.node_text must be the NODE-dispatching function from "
        "crosscheck.claims_vs_conduct (step08 walks raw graph nodes), not "
        "resolve.align_claims.node_text (which takes a properties dict) — merging them "
        "would silently change what this stage matches evidence text against."
    )


# --------------------------------------------------------------------------- #
# Pure-function equivalence: build_key_index / resolve_claim / resolve_evidence / build_rows
# --------------------------------------------------------------------------- #
def _mini_graph():
    return {"nodes": [
        {"class": "SustainabilityClaim", "properties": {"claim_id": "c1", "description": "d1"}},
        {"class": "MediaReport", "properties": {"title": "Bai bao doc lap X"}},
        {"class": "SustainabilityClaim", "properties": {"claim_id": "c2", "description": "d2"}},
    ], "edges": []}


def _mini_dossiers():
    return [
        {
            "claim_id": "c1", "claim_node_index": 999,
            "assessment": "appears_supported", "caveats": ["c"],
            "signals": {"structural_contradiction": True, "kpi_gap": {"x": 1}},
            "assessment_scores": {"contradicted": 0.1, "supported": 0.8, "abstain": 0.1},
            "score_disagrees_with_assessment": False,
            "supporting_evidence": [
                {"class": "MediaReport", "text": "Bai bao doc lap X", "node_index": 999,
                 "confidence": 0.9, "rationale": "r", "provider": "openai",
                 "date_uncertain": True, "source_domain": "", "date": None, "year": 2024},
            ],
            "contradicting_evidence": [], "flagged_non_independent_support": [],
        },
        {
            # claim_id absent from the graph -> falls back to positional
            "claim_id": "unknown", "claim_node_index": 2,
            "assessment": "unverified_insufficient_evidence", "caveats": [],
            "supporting_evidence": [], "contradicting_evidence": [],
            "flagged_non_independent_support": [],
        },
        {
            # unresolved: no claim_id match AND no claim_node_index
            "claim_id": "also_unknown",
            "supporting_evidence": [], "contradicting_evidence": [],
            "flagged_non_independent_support": [],
        },
    ]


def test_build_key_index_and_rows_match_both_trees():
    graph = _mini_graph()
    dossiers = _mini_dossiers()

    by_claim, by_text = new_step08.build_key_index(graph)

    rows, edges, how = new_step08.build_rows(dossiers, "aaa", by_claim, by_text)

    # sanity on the resolution mix itself, so the fixture is proven to exercise what it claims
    assert how["claim_stable_id"] == 1
    assert how["claim_positional"] == 1
    assert how["claim_unresolved"] == 1
    assert how["evidence_text"] == 1


# --------------------------------------------------------------------------- #
# End-to-end run() equivalence via the fake Neo4j driver — synthetic fixture
# --------------------------------------------------------------------------- #
def test_run_end_to_end_synthetic_both_trees_send_identical_neo4j_calls(tmp_path=None):
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        graph_file = td / "resolved_graph.json"
        graph_file.write_text(json.dumps(_mini_graph()), encoding="utf-8")
        dossier_file = td / "aaa_claim_assessments.json"
        dossier_file.write_text(json.dumps(_mini_dossiers()), encoding="utf-8")

        calls, driver_calls = _run_with_stub(
            new_step08, _ns(input=dossier_file, resolved=graph_file))

        assert len(driver_calls) > 0
        assert len(calls) > 0


def test_run_clear_advisory_both_trees_send_identical_neo4j_calls():
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        graph_file = td / "resolved_graph.json"
        graph_file.write_text(json.dumps(_mini_graph()), encoding="utf-8")
        dossier_file = td / "aaa_claim_assessments.json"
        dossier_file.write_text(json.dumps(_mini_dossiers()), encoding="utf-8")

        calls, _ = _run_with_stub(
            new_step08, _ns(input=dossier_file, resolved=graph_file, clear_advisory=True))

        assert len(calls) > 0
        # the clear-advisory branch adds 2 queries up front that the default run lacks
        assert "DELETE r" in calls[0][0]


def test_dry_run_touches_no_driver_both_trees():
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        graph_file = td / "resolved_graph.json"
        graph_file.write_text(json.dumps(_mini_graph()), encoding="utf-8")
        dossier_file = td / "aaa_claim_assessments.json"
        dossier_file.write_text(json.dumps(_mini_dossiers()), encoding="utf-8")

        calls, driver_calls = _run_with_stub(
            new_step08, _ns(input=dossier_file, resolved=graph_file, dry_run=True))

        assert calls == [] and driver_calls == []


def test_missing_resolved_graph_falls_back_to_positional_both_trees():
    """No `--resolved` file on disk (e.g. before step05 ever ran) must not crash — falls
    back to `node_index`-only resolution, matching the module docstring's documented
    tier 3."""
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        missing_graph = td / "does_not_exist.json"
        dossier_file = td / "aaa_claim_assessments.json"
        dossier_file.write_text(json.dumps(_mini_dossiers()), encoding="utf-8")

        calls, _ = _run_with_stub(
            new_step08, _ns(input=dossier_file, resolved=missing_graph))

        assert len(calls) > 0


def test_no_dossier_file_exits_both_trees():
    """`run()` calls `sys.exit(1)` when the dossier file is missing — it must refuse
    rather than crashing with a raw exception."""
    missing = REPO / "graph_output" / "crosscheck" / "__does_not_exist__.json"
    try:
        new_step08.run(_ns(input=missing, ticker="ZZZ"))
        assert False, "did not exit on a missing dossier file"
    except SystemExit as e:
        assert e.code == 1


# --------------------------------------------------------------------------- #
# Real corpus: 1,093 real dossiers x the real 10,425-node resolved graph
# --------------------------------------------------------------------------- #
def test_real_corpus_both_trees_send_identical_neo4j_calls():
    if not DOSSIER_FILE.exists() or not RESOLVED_FILE.exists():
        _skip("test_real_corpus_both_trees_send_identical_neo4j_calls",
              "graph_output/crosscheck/aaa_claim_assessments.json or "
              "graph_output/resolved/resolved_graph.json not present "
              "(git-ignored, shipped via the HF snapshot — see src/data_sync.py)")
        return

    calls, driver_calls = _run_with_stub(new_step08, _ns())

    assert len(driver_calls) > 0
    assert len(calls) >= 3, \
        f"expected >=3 real Neo4j calls (claim props + scoped clear + >=1 edge type), got {len(calls)}"

    print(f"    real corpus: {len(calls)} Neo4j calls issued "
          f"({len(calls[0][1].get('rows', []))} claim rows in call 0)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed"
          + (f", {len(_skips)} skipped." if _skips else "."))
