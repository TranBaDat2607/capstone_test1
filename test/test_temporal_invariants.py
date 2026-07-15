#!/usr/bin/env python3
"""
Offline unit checks for the TEMPORAL_KG_DESIGN Phase-0 logic (P3/P4).

The repo has no pytest harness (test/ holds manual-validation notebooks), so this
is a plain assert script — run it from the repo root:

    python test/test_temporal_invariants.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from step03_fix_invalid_triplets import (  # noqa: E402
    date_start_key,
    enforce_temporal_invariants,
    normalize_date_string,
)
from step03b_anchor_kpi_facilities import parse_source_id  # noqa: E402
from step05_resolve_entities import DSU, consolidate  # noqa: E402


def test_normalize_date_string():
    assert normalize_date_string(None) == (None, True)
    assert normalize_date_string("") == (None, True)
    assert normalize_date_string("null") == (None, True)
    assert normalize_date_string("2011") == ("2011", True)
    assert normalize_date_string("2011-1-3") == ("2011-01-03", True)
    assert normalize_date_string("31/05/2023") == ("2023-05-31", True)
    assert normalize_date_string("05/2023") == ("2023-05", True)
    assert normalize_date_string("2023.05.31") == ("2023-05-31", True)
    assert normalize_date_string("2024-08-14T10:00:00") == ("2024-08-14", True)
    # unparseable spellings are returned unchanged and flagged, never invented
    assert normalize_date_string("Q2 2023") == ("Q2 2023", False)
    assert normalize_date_string("2023-13-01") == ("2023-13-01", False)


def test_date_start_key():
    # the P4 bug: "2011" and "2011-01-01" are the SAME start instant
    assert date_start_key("2011") == date_start_key("2011-01-01") == "2011-01-01"
    assert date_start_key("2011-03") == "2011-03-01"
    assert date_start_key("garbage") is None
    assert date_start_key(None) is None


def test_enforce_temporal_invariants():
    triples = [{
        "subject": {"class": "Organization",
                    "properties": {"name": "X", "valid_from": "01/2020",
                                   "valid_to": None, "is_current": True}},
        "predicate": "subjectToPenalty",
        "object": {"class": "Penalty",
                   "properties": {"penalty_id": "p1", "date": "14/08/2024",
                                  "source_type": "news",
                                  "valid_from": "2024-08-14", "valid_to": "2023",
                                  "is_current": False}},
        "temporal_metadata": {"valid_from": "2024/08/14", "valid_to": None,
                              "recorded_at": "2024"},
    }]
    stats = enforce_temporal_invariants(triples)
    subj = triples[0]["subject"]["properties"]
    obj = triples[0]["object"]["properties"]
    tm = triples[0]["temporal_metadata"]
    assert subj["valid_from"] == "2020-01"
    assert obj["date"] == "2024-08-14"
    assert tm["valid_from"] == "2024-08-14"
    # news T2 node without the required bool gets the conservative default
    assert obj["date_uncertain"] is True
    assert stats["date_uncertain_defaulted"] == 1
    # valid_from (2024-08-14) > valid_to (2023) is flagged, not rewritten
    assert stats["valid_from_after_valid_to"] == 1
    assert obj["valid_to"] == "2023"


def _org(name, valid_from, is_current=True, valid_to=None):
    return {"class": "Organization",
            "properties": {"name": name, "valid_from": valid_from,
                           "valid_to": valid_to, "is_current": is_current}}


def test_consolidate_version_dedup_and_is_current():
    # Two spellings of the same start instant -> ONE version (the observed AAA bug)
    nodes = [_org("X", "2011"), _org("X", "2011-01-01")]
    dsu = DSU(2)
    dsu.union(0, 1)
    resolved, _ = consolidate(nodes, [], dsu, {})
    (node,) = resolved["nodes"]
    assert len(node["temporal_versions"]) == 1

    # Distinct years both claiming is_current=true -> exactly one survives (latest open)
    nodes = [_org("Y", "2011"), _org("Y", "2020")]
    dsu = DSU(2)
    dsu.union(0, 1)
    resolved, _ = consolidate(nodes, [], dsu, {})
    (node,) = resolved["nodes"]
    versions = node["temporal_versions"]
    assert len(versions) == 2
    current = [v for v in versions if v["is_current"] is True]
    assert len(current) == 1
    assert current[0]["valid_from"] == "2020"

    # All-closed chain legitimately keeps zero current versions
    nodes = [_org("Z", "2011", is_current=False, valid_to="2015"),
             _org("Z", "2016", is_current=False, valid_to="2019")]
    dsu = DSU(2)
    dsu.union(0, 1)
    resolved, _ = consolidate(nodes, [], dsu, {})
    (node,) = resolved["nodes"]
    assert all(v["is_current"] is False for v in node["temporal_versions"])


def test_parse_source_id():
    assert parse_source_id("AAA_Baocaothuongnien_2011.pdf_10_1") == \
        ("AAA_Baocaothuongnien_2011.pdf", 10, 1)
    assert parse_source_id("no_page_or_sentence") is None
    assert parse_source_id(None) is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
