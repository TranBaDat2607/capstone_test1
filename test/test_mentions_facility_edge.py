#!/usr/bin/env python3
"""GRAPH_IMPROVEMENT_PLAN.md C2/B2 — MediaReport --mentionsFacility--> Facility|Location.

WHY THIS TEST EXISTS
`config/schema.json` lets a MediaReport anchor to an Organization (`mentionsOrganization`) or a
Product (`mentionsProduct`), but has no way to anchor a MediaReport directly to the Facility or
Location the article actually names. observedAtFacility (KPIObservation->Facility) and enforcedBy
(Penalty->Authority) already cover the KPI/penalty case (commit caf7121); mentionsFacility fills
the remaining gap: an article naming a facility or an incident location with no KPI/penalty
attached still had no direct anchor for its MediaReport node, which is exactly what keeps Q7(e)
(T2 conduct-node anchoring) low for the MediaReport class.

Offline: no LLM, no Neo4j, no network. Run from the repo root:

    python test/test_mentions_facility_edge.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core.schema import load_schema_sets  # noqa: E402
from esg_kg.graph.extract_triples import (  # noqa: E402
    NEWS_GRAPH_PROMPT_TEMPLATE,
    TEMPORAL_GRAPH_PROMPT_TEMPLATE,
)

SCHEMA_FILE = REPO / "config" / "schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def test_schema_declares_mentionsFacility_to_facility():
    schema = load_schema()
    matches = [
        e for e in schema["edges"]
        if e.get("label") == "mentionsFacility"
        and e.get("source_class") == "MediaReport"
        and e.get("target_class") == "Facility"
    ]
    assert matches, "expected a mentionsFacility edge from MediaReport to Facility in schema.json"


def test_schema_declares_mentionsFacility_to_location():
    schema = load_schema()
    matches = [
        e for e in schema["edges"]
        if e.get("label") == "mentionsFacility"
        and e.get("source_class") == "MediaReport"
        and e.get("target_class") == "Location"
    ]
    assert matches, "expected a mentionsFacility edge from MediaReport to Location in schema.json"


def test_load_schema_sets_exposes_both_mentionsFacility_pairs():
    schema = load_schema()
    _entity_classes, edge_labels, edge_directions = load_schema_sets(schema)
    assert "mentionsFacility" in edge_labels
    pairs = edge_directions["mentionsFacility"]
    assert ("MediaReport", "Facility") in pairs, pairs
    assert ("MediaReport", "Location") in pairs, pairs


def test_news_prompt_anchors_facility_via_mentionsFacility():
    assert "MediaReport --mentionsFacility--> Facility" in NEWS_GRAPH_PROMPT_TEMPLATE


def test_news_prompt_anchors_location_via_mentionsFacility():
    assert "MediaReport --mentionsFacility--> Location" in NEWS_GRAPH_PROMPT_TEMPLATE


def test_report_prompt_unaffected():
    for token in ("mentionsFacility", "mentionsOrganization", "mentionsProduct"):
        assert token not in TEMPORAL_GRAPH_PROMPT_TEMPLATE, (
            f"{token} is a news-only concept; it must not leak into the report/claim-side prompt"
        )


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
