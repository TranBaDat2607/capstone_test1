#!/usr/bin/env python3
"""
Contract tests for config/schema.json — the single source of truth for the graph.

The schema is hand-edited (the indicator axis added a class and four edge pairs),
and a mistake in it is the worst class of bug in this pipeline: every later stage
reads it, and a wrong entry fails SILENTLY — an edge label with no legal pair just
makes step03 drop those triples, a class missing from the tier map just makes
step00's P1 lint skip it. Nothing else in the repo checks the schema itself.

These assertions are cheap and need no generated data, so they run on a bare clone.

    python test/test_schema_contract.py

IMPORTANT: the tier membership (T1/T2/T3) is IMPORTED from esg_kg.report.quality (step00),
never re-declared here. Re-declaring it is how you get a test that either raises false
alarms or, worse, passes while the real lint is looking at a different set of classes.
The tier map in step00 is the definition; this file checks the schema against it.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.report.quality import (  # noqa: E402
    REFERENCE_CLASSES,
    T1_CLASSES,
    T2_CLASSES,
    T3_CLASSES,
    TEMPORAL_IDENTITY_FIELDS,
)

SCHEMA = json.loads((REPO / "config" / "schema.json").read_text(encoding="utf-8"))
NODES = SCHEMA["nodes"]
EDGES = SCHEMA["edges"]
BY_CLASS = {n["class"]: n for n in NODES}


def identity_keys(node: dict) -> list:
    """The schema default when a class declares none — mirrors get_identity_keys."""
    return node.get("identity_keys", ["name"])


# --------------------------------------------------------------------------- #
# Tier map — the precondition for every other check in this file.
# --------------------------------------------------------------------------- #
def test_every_class_is_assigned_to_exactly_one_tier():
    """A class missing from the tier map escapes step00's P1 lint without a word.

    This is the silent-failure guard: the lint only walks T1_CLASSES, so a new
    T1 entity that nobody added to that set can carry time in its identity_keys
    forever and the quality report will keep saying "T1 time-identity classes 0".
    """
    tiers = {"T1": T1_CLASSES, "T2": T2_CLASSES, "T3": T3_CLASSES}
    for cls in sorted(BY_CLASS):
        member_of = [name for name, group in tiers.items() if cls in group]
        assert len(member_of) == 1, (
            f"{cls} is in {member_of or 'no tier'}; every schema class must be in "
            f"exactly one of T1/T2/T3 (see esg_kg/report/quality.py)"
        )

    # and the tier map must not name classes the schema does not define
    for name, group in tiers.items():
        unknown = sorted(group - set(BY_CLASS))
        assert not unknown, f"{name} names classes absent from schema.json: {unknown}"


# --------------------------------------------------------------------------- #
# P1 — identity is timeless (docs/TEMPORAL_KG_DESIGN.md)
# --------------------------------------------------------------------------- #
def test_t1_identity_keys_are_timeless():
    """P1 as a build gate, not just a metric step00 reports after the fact."""
    for cls in sorted(T1_CLASSES):
        bad = sorted(set(identity_keys(BY_CLASS[cls])) & TEMPORAL_IDENTITY_FIELDS)
        assert not bad, f"P1: T1 class {cls} has time fields in identity_keys: {bad}"


def test_observation_classes_keep_time_in_identity():
    """The other half of P1, and the reason this test exists.

    Observation classes are versioned PER OBSERVATION, so time in their identity is
    correct — "same KPI, different year" must be two nodes. Without this assertion a
    well-meaning cleanup that makes every class "consistent" with P1 would collapse
    them, and no other test would notice.
    """
    required = {"KPIObservation": "year", "Emission": "valid_from", "Waste": "valid_from"}
    for cls, key in required.items():
        assert cls in T2_CLASSES, f"{cls} must be a T2 observation class"
        assert key in identity_keys(BY_CLASS[cls]), (
            f"{cls}.identity_keys lost {key!r} — per-observation versioning is broken"
        )


# --------------------------------------------------------------------------- #
# Internal consistency
# --------------------------------------------------------------------------- #
def test_identity_keys_reference_declared_properties():
    """An identity key that is not a declared property can never be populated, so the
    stable id silently degrades to the same value for every node of that class."""
    for node in NODES:
        props = set(node.get("properties", []))
        missing = [k for k in identity_keys(node) if k not in props]
        assert not missing, f"{node['class']}: identity_keys {missing} are not declared properties"


def test_every_edge_label_has_at_least_one_legal_pair():
    """validate_triple treats a label with no (source_class, target_class) pair as
    unconstrained, so such a label passes validation and then matches nothing at query
    time — the failure is invisible until someone asks why an edge is missing."""
    pairs = {}
    for e in EDGES:
        pairs.setdefault(e["label"], []).append((e.get("source_class"), e.get("target_class")))
    for label, plist in sorted(pairs.items()):
        assert any(s and t for s, t in plist), f"edge label {label!r} has no legal class pair"


def test_edge_endpoints_are_declared_classes():
    for e in EDGES:
        for role in ("source_class", "target_class"):
            cls = e.get(role)
            if cls:
                assert cls in BY_CLASS, f"edge {e['label']}: {role}={cls!r} is not a schema class"


# --------------------------------------------------------------------------- #
# Indicator axis (docs/STANDARD_INDICATOR_AXIS.md §3.1–3.2)
# --------------------------------------------------------------------------- #
def test_standard_indicator_class_contract():
    assert "StandardIndicator" in BY_CLASS, "StandardIndicator class is missing"
    node = BY_CLASS["StandardIndicator"]
    # identity is the indicator code — timeless, single-key, so step05c's ensure_node
    # is idempotent across runs
    assert identity_keys(node) == ["id"], identity_keys(node)
    for prop in ("id", "name", "definition", "pillar", "section", "source_document"):
        assert prop in node["properties"], f"StandardIndicator missing property {prop!r}"
    # it is a reference vocabulary, deliberately excluded from the Q7 hub metrics
    assert "StandardIndicator" in REFERENCE_CLASSES


def test_indicator_axis_edge_pairs_exist():
    """The four pairs the axis is built from, in the direction step05c emits them.

    Direction matters: GraphPatch.add_edge validates against these, so a reversed
    entry here would make step05c silently emit zero edges of that kind.
    """
    declared = {(e["label"], e.get("source_class"), e.get("target_class")) for e in EDGES}
    required = [
        ("partOf", "StandardIndicator", "Regulation"),
        ("partOf", "StandardIndicator", "Standard"),
        ("measuredUnder", "KPIObservation", "StandardIndicator"),
        ("measuredUnder", "Emission", "StandardIndicator"),
        ("measuredUnder", "Penalty", "StandardIndicator"),
        ("alignsWithIndicator", "SustainabilityClaim", "StandardIndicator"),
        ("alignsWithIndicator", "Goal", "StandardIndicator"),
        ("alignsWithIndicator", "Initiative", "StandardIndicator"),
        ("equivalentTo", "StandardIndicator", "StandardIndicator"),
    ]
    for triple in required:
        assert triple in declared, f"schema.json is missing the edge pair {triple}"


def test_conduct_classes_can_reach_the_indicator_axis():
    """Q4/§4: the conduct side is what makes greenwashing detection possible. Each
    quantitative conduct class must have a route onto an indicator, or news evidence
    can never meet a claim at a join point."""
    declared = {(e["label"], e.get("source_class")) for e in EDGES}
    for cls in ("KPIObservation", "Emission", "Penalty"):
        assert ("measuredUnder", cls) in declared, f"{cls} cannot reach StandardIndicator"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
