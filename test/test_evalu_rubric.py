#!/usr/bin/env python3
"""
Offline unit checks for evalu/rubric.py — the expert instrument
(Khung Đánh Giá Graph-RAG §3) and the consensus pipeline (§4 steps 2-4).

Run from the repo root:

    python test/test_evalu_rubric.py

These arms matter because the consensus code runs exactly once per annotation
round, on data that is expensive to collect. A bug found during a live session
with three executives costs a session; a bug found here costs nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evalu.rubric import (  # noqa: E402
    DIMENSION_KEYS,
    Ballot,
    blank_sheet,
    consensus,
    reliability_matrix,
    rubric_spec,
    weighted_median,
)


def test_weighted_median_unweighted_matches_plain_median():
    assert weighted_median([1, 2, 3], [1, 1, 1]) == 2
    assert weighted_median([5], [1]) == 5
    # even count with equal weights -> midpoint, never an out-of-range value
    got = weighted_median([2, 4], [1, 1])
    assert got == 3.0, got


def test_weighted_median_respects_weights():
    # the ESG/audit expert carries 2x on a grounding question: their 5 wins
    assert weighted_median([1, 5], [1.0, 2.0]) == 5
    assert weighted_median([1, 5], [2.0, 1.0]) == 1


def test_weighted_median_skips_gaps_and_zero_weights():
    assert weighted_median([None, 4, None], [1, 1, 1]) == 4
    assert weighted_median([1, 4], [0.0, 1.0]) == 4
    assert weighted_median([], []) is None
    assert weighted_median([None], [1]) is None


def test_weighted_median_stays_inside_observed_range():
    for vals, wts in (([1, 5], [1, 1]), ([1, 2, 5], [1, 1, 1]), ([2, 2, 5], [1, 1, 3])):
        got = weighted_median(vals, wts)
        assert min(vals) <= got <= max(vals), (vals, wts, got)


def test_reliability_matrix_preserves_gaps():
    ballots = [
        Ballot("c1", "r1", "ceo", {"grounding": 5}),
        Ballot("c1", "r2", "hrd", {"grounding": None}),   # abstained
        Ballot("c2", "r1", "ceo", {"grounding": 3}),
        Ballot("c2", "r2", "hrd", {"grounding": 4}),
    ]
    matrix, raters = reliability_matrix(ballots, "grounding")
    assert raters == ["r1", "r2"]
    assert matrix == [[5, None], [3, 4]], matrix


def _ballot(cid, rid, panel, **scores):
    full = {k: scores.get(k) for k in DIMENSION_KEYS}
    return Ballot(cid, rid, panel, full, assessment_agrees=scores.get("_agrees"))


def test_consensus_flags_wide_likert_spread():
    ballots = [
        _ballot("c1", "r1", "ceo", grounding=1),
        _ballot("c1", "r2", "esg_audit", grounding=5),      # spread 4 -> queued
        _ballot("c2", "r1", "ceo", grounding=4),
        _ballot("c2", "r2", "esg_audit", grounding=5),      # spread 1 -> not queued
    ]
    res = consensus(ballots)
    queued = {(q["claim_id"], q["dimension"]) for q in res["review_queue"]}
    assert ("c1", "grounding") in queued
    assert ("c2", "grounding") not in queued
    # the audit expert's 2x weight on grounding decides c1
    assert res["consensus_scores"]["c1"]["grounding"] == 5


def test_consensus_flags_verdict_conflict():
    ballots = [
        Ballot("c1", "r1", "ceo", {k: 3 for k in DIMENSION_KEYS}, assessment_agrees=True),
        Ballot("c1", "r2", "hrd", {k: 3 for k in DIMENSION_KEYS}, assessment_agrees=False),
    ]
    res = consensus(ballots)
    reasons = {q["reason"] for q in res["review_queue"]}
    assert "verdict_conflict" in reasons, reasons


def test_consensus_reports_agreement_per_dimension():
    ballots = []
    for i, (a, b) in enumerate([(5, 5), (4, 4), (3, 3), (5, 4), (2, 2)]):
        ballots.append(_ballot(f"c{i}", "r1", "ceo", grounding=a))
        ballots.append(_ballot(f"c{i}", "r2", "esg_audit", grounding=b))
    res = consensus(ballots)
    ag = res["per_dimension"]["grounding"]["agreement"]
    assert ag is not None and ag["headline_metric"] == "gwet_ac2"
    assert ag["headline"] > 0.6, ag
    # a dimension nobody scored must report None, not a fabricated 0
    assert res["per_dimension"]["provenance"]["agreement"] is None


def test_consensus_survives_single_rater():
    # one expert alone: consensus still produces a score, agreement is undefined
    res = consensus([_ballot("c1", "r1", "ceo", grounding=4)])
    assert res["consensus_scores"]["c1"]["grounding"] == 4
    assert res["per_dimension"]["grounding"]["agreement"] is None


def test_blank_sheet_shape_and_panel_guard():
    sheet = blank_sheet(["c1", "c2"], "ceo01", "ceo")
    assert len(sheet["ballots"]) == 2
    assert set(sheet["ballots"][0]["scores"]) == set(DIMENSION_KEYS)
    assert all(v is None for v in sheet["ballots"][0]["scores"].values())
    try:
        blank_sheet(["c1"], "x", "not_a_panel")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown panel must raise, not silently produce a sheet")


def test_rubric_spec_is_complete():
    spec = rubric_spec()
    assert len(spec["dimensions"]) == 4
    assert set(spec["panels"]) == {"ceo", "hrd", "esg_audit"}
    assert spec["iaa"]["headline"] == "gwet_ac2"
    assert spec["iaa"]["threshold"] == 0.61
    for d in spec["dimensions"]:
        assert d["anchor_1"] and d["anchor_3"] and d["anchor_5"], d["key"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
