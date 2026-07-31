#!/usr/bin/env python3
"""
GRAPH_IMPROVEMENT_PLAN.md B1 — subsumption merge for partially-filled identity keys.

WHY THIS TEST EXISTS
`identity_signature()` (esg_kg/resolve/entities.py) builds a tuple from ALL of a
class's `identity_keys`. Stage B.1 only merges nodes whose FULL normalized tuple is
equal, so two mentions of the same real-world entity that differ only in which
optional key got extracted (e.g. one "Hải Dương" mention carries a `country`, another
doesn't) never merge — a dedup miss, not a false merge, but still wrong: 52 Location +
8 Authority duplicates measured live in `graph_output/resolved/resolved_graph.json`
(GRAPH_IMPROVEMENT_PLAN.md B1).

This is a genuine RED test against the code as it stands (no `--no-llm`/`--dry-run`
needed: Stage A/B.1/D all run without any LLM/network). It must pass once B1b
(subsumption merge) is added to Stage B.1, and stay passing across a full pipeline
re-run for any company because it drives `resolve_graph()` directly on synthetic
triples, not on a frozen fixture file.

Offline: no LLM, no Neo4j, no network. Run from the repo root:

    python test/test_entities_partial_key_merge.py
"""

import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.resolve import entities  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
MISSING_REGISTRY = REPO / "config" / "__no_such_registry__.json"


def _quiet():
    root = logging.getLogger()
    prev = root.level
    root.setLevel(logging.ERROR)
    return prev


def _unquiet(prev) -> None:
    logging.getLogger().setLevel(prev)


def load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def _facility_locatedin_location(facility_name: str, location_props: dict) -> dict:
    common = {"valid_from": "2023", "valid_to": None, "is_current": True}
    return {
        "subject": {"class": "Facility", "properties": {"name": facility_name, **common}},
        "predicate": "locatedIn",
        "object": {"class": "Location", "properties": {**location_props, **{k: v for k, v in common.items() if k not in location_props}}},
        "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023"},
    }


def _resolve(triples: list) -> dict:
    schema = load_schema()
    idkeys = entities.load_identity_keys(schema)
    prev = _quiet()
    try:
        resolved, _stats = entities.resolve_graph(
            triples, idkeys,
            registry_path=MISSING_REGISTRY, standards_registry_path=MISSING_REGISTRY,
            no_llm=True, client=None,
        )
    finally:
        _unquiet(prev)
    return resolved


def test_location_missing_country_merges_with_location_that_has_it():
    """`Location(name=hai duong, country="")` and `Location(name=hai duong,
    country="Việt Nam")` are the same real place; identity_keys = ['name', 'country']
    per config/schema.json, so today's exact-tuple Stage B.1 leaves them as two nodes."""
    triples = [
        _facility_locatedin_location("Nhà máy 1", {"name": "Hải Dương", "country": ""}),
        _facility_locatedin_location("Nhà máy 2", {"name": "hai duong", "country": "Việt Nam"}),
    ]
    resolved = _resolve(triples)
    locations = [n for n in resolved["nodes"] if n["class"] == "Location"]
    assert len(locations) == 1, f"expected the partial-key duplicates to merge, got {len(locations)}: {locations}"
    assert locations[0]["properties"].get("country") == "Việt Nam", \
        "merged node should keep the non-empty country from its sibling"


def test_location_with_conflicting_country_does_not_merge():
    """Two DIFFERENT non-empty values for the same key must block the merge — this is
    the guard against the false-merge case the plan calls out (§B1 rủi ro)."""
    triples = [
        _facility_locatedin_location("Nhà máy 1", {"name": "Hải Dương", "country": "Việt Nam"}),
        _facility_locatedin_location("Nhà máy 2", {"name": "hai duong", "country": "Trung Quốc"}),
    ]
    resolved = _resolve(triples)
    locations = [n for n in resolved["nodes"] if n["class"] == "Location"]
    assert len(locations) == 2, \
        f"conflicting non-empty keys must NOT merge, got {len(locations)}: {locations}"


def test_authority_missing_jurisdiction_merges_with_authority_that_has_it():
    """Same subsumption behaviour on a second class (identity_keys = ['name',
    'jurisdiction']), so the fix is general and not Location-specific."""
    common = {"valid_from": "2023", "valid_to": None, "is_current": True}
    triples = [
        {"subject": {"class": "Facility", "properties": {"name": "Nhà máy 1", **common}},
         "predicate": "regulatedBy",
         "object": {"class": "Authority", "properties": {"name": "Sở TN&MT Hải Dương", "jurisdiction": "", **common}},
         "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023"}},
        {"subject": {"class": "Facility", "properties": {"name": "Nhà máy 2", **common}},
         "predicate": "regulatedBy",
         "object": {"class": "Authority", "properties": {"name": "so tn&mt hai duong", "jurisdiction": "Hải Dương", **common}},
         "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023"}},
    ]
    resolved = _resolve(triples)
    authorities = [n for n in resolved["nodes"] if n["class"] == "Authority"]
    assert len(authorities) == 1, f"expected the partial-key Authority duplicates to merge, got {len(authorities)}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
