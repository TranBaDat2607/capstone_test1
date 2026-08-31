#!/usr/bin/env python3
"""
Offline unit checks for evalu/annotation.py — the blind human-annotation layer.

This produces the only ground truth the project will ever have, so the sheet
generator has one invariant that matters more than everything else: the sheet
must not leak what the system concluded. An annotator who can see the verdict
will drift toward agreeing with it, and the resulting precision number is worth
nothing. `test_sheet_is_blind` is the arm that guards that.

Run from the repo root:

    python test/test_evalu_annotation.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evalu.annotation import (  # noqa: E402
    LABELS,
    build_sheet,
    collect_pairs,
    sample_pairs,
    score,
)


def _nodes():
    return [
        {"class": "MediaReport", "properties": {"source_doc": "AAA__x.vn__1",
                                                "title": "AAA giảm phát thải 12%"}},
        {"class": "MediaReport", "properties": {"source_doc": "ACG__y.vn__2",
                                                "title": "An Cường Net Zero 2050"}},
        {"class": "Penalty", "properties": {"source_doc": "AGG__z.vn__3",
                                            "description": "Phạt 3 tỷ đồng thao túng"}},
        {"class": "MediaReport", "properties": {"source_doc": "ACC__w.vn__4",
                                                "title": "Bê tông Becamex mở rộng"}},
    ]


def _dossiers():
    return [
        {"_ticker": "AAA", "claim_id": "c1", "claim_text": "Cam kết Net Zero 2050",
         "assessment": "appears_supported",
         "supporting_evidence": [{"node_index": 0, "text": "AAA giảm phát thải 12%"},
                                 {"node_index": 1, "text": "An Cường Net Zero 2050"}],
         "contradicting_evidence": []},
        {"_ticker": "ACG", "claim_id": "c2", "claim_text": "Đảm bảo quyền cổ đông",
         "assessment": "appears_contradicted",
         "supporting_evidence": [],
         "contradicting_evidence": [{"node_index": 2, "text": "Phạt 3 tỷ đồng thao túng"}]},
        {"_ticker": "ACC", "claim_id": "c3", "claim_text": "Phát triển bền vững",
         "assessment": "unverified_insufficient_evidence",
         "supporting_evidence": [], "contradicting_evidence": []},
    ]


def test_collect_pairs_only_takes_cited_evidence():
    pairs = collect_pairs(_dossiers(), _nodes())
    assert len(pairs) == 3, len(pairs)          # the unverified dossier contributes none
    kinds = sorted(p["system_kind"] for p in pairs)
    assert kinds == ["contradicting_evidence", "supporting_evidence",
                     "supporting_evidence"]


def test_sample_is_deterministic_for_a_seed():
    pairs = collect_pairs(_dossiers(), _nodes())
    a = sample_pairs(pairs, n=2, seed=42)
    b = sample_pairs(pairs, n=2, seed=42)
    c = sample_pairs(pairs, n=2, seed=7)
    assert [x["pair_id"] for x in a] == [x["pair_id"] for x in b]
    assert len(a) == 2
    assert isinstance(c, list)


def test_sample_larger_than_population_returns_census():
    pairs = collect_pairs(_dossiers(), _nodes())
    got = sample_pairs(pairs, n=999, seed=1)
    assert len(got) == len(pairs), "must not invent pairs to reach n"


def test_sample_is_stratified_across_verdict_kinds():
    pairs = collect_pairs(_dossiers(), _nodes())
    got = sample_pairs(pairs, n=2, seed=3)
    kinds = {p["system_kind"] for p in got}
    assert len(kinds) == 2, f"both verdict kinds must appear, got {kinds}"


LEAKY_KEYS = {"assessment", "system_kind", "system_verdict", "evidence_ticker",
              "source_doc", "confidence", "rationale", "retrieval_tier",
              "same_company_auto"}


def test_sheet_is_blind():
    """The sheet must carry NOTHING that reveals the system's conclusion."""
    pairs = collect_pairs(_dossiers(), _nodes())
    sheet = build_sheet(sample_pairs(pairs, n=3, seed=1), decoys=0, seed=1)
    for item in sheet["items"]:
        leaked = LEAKY_KEYS & set(item)
        assert not leaked, f"sheet leaks {leaked}"
        assert item["claim_company"]
        assert item["claim_text"] and item["evidence_text"]
        assert item["relation"] is None and item["about_claim_company"] is None


def test_decoys_are_indistinguishable_from_real_items():
    pairs = collect_pairs(_dossiers(), _nodes())
    sheet = build_sheet(sample_pairs(pairs, n=3, seed=1), decoys=2, seed=1)
    assert len(sheet["items"]) == 5
    keysets = {frozenset(i.keys()) for i in sheet["items"]}
    assert len(keysets) == 1, "a decoy must not be identifiable by its shape"
    assert len(sheet["_decoy_ids"]) == 2


def _pid_by_evidence(sheet, needle):
    """build_sheet shuffles, so items must be located by content, not position."""
    for item in sheet["items"]:
        if needle in (item["evidence_text"] or ""):
            return item["pair_id"]
    raise AssertionError(f"no sheet item containing {needle!r}")


def _standard_annotation(sheet):
    """
    A fixed annotator response used by several arms:
      AAA claim + AAA article        -> supports,     right company  (system OK)
      AAA claim + An Cường article   -> irrelevant,   wrong company  (system WRONG)
      ACG claim + AGG penalty        -> contradicts,  wrong company  (system OK)
    """
    return [
        {"pair_id": _pid_by_evidence(sheet, "AAA giảm phát thải"),
         "relation": "supports", "about_claim_company": True},
        {"pair_id": _pid_by_evidence(sheet, "An Cường Net Zero"),
         "relation": "irrelevant", "about_claim_company": False},
        {"pair_id": _pid_by_evidence(sheet, "Phạt 3 tỷ đồng"),
         "relation": "contradicts", "about_claim_company": False},
    ]


def test_score_computes_precision_and_ignores_decoys():
    pairs = collect_pairs(_dossiers(), _nodes())
    sheet = build_sheet(pairs, decoys=0, seed=1)
    res = score(sheet, _standard_annotation(sheet))
    assert res["annotated"] == 3
    assert res["precision"]["overall"]["correct"] == 2
    assert abs(res["precision"]["overall"]["value"] - 2 / 3) < 1e-9


def test_score_flags_decoys_marked_as_evidence():
    pairs = collect_pairs(_dossiers(), _nodes())
    sheet = build_sheet(pairs, decoys=2, seed=5)
    ann = [{"pair_id": pid, "relation": "supports", "about_claim_company": True}
           for pid in sheet["_decoy_ids"]]
    res = score(sheet, ann)
    assert res["attention_check"]["decoys_annotated"] == 2
    assert res["attention_check"]["decoys_failed"] == 2
    assert res["attention_check"]["pass_rate"] == 0.0


def test_score_validates_the_automated_attribution():
    """
    The annotator's own 'is this about the right company?' answer is compared to
    negative_control's source_doc heuristic. This is what turns NC.1 from an
    unverified heuristic into a human-validated measurement.
    """
    pairs = collect_pairs(_dossiers(), _nodes())
    sheet = build_sheet(pairs, decoys=0, seed=1)
    res = score(sheet, _standard_annotation(sheet))
    agree = res["attribution_validation"]
    assert agree["compared"] == 3
    assert agree["agreed"] == 3, agree
    assert abs(agree["value"] - 1.0) < 1e-9


def test_score_reports_precision_on_the_post_fix_subset():
    pairs = collect_pairs(_dossiers(), _nodes())
    sheet = build_sheet(pairs, decoys=0, seed=1)
    res = score(sheet, _standard_annotation(sheet))
    post = res["precision"]["same_company_only"]
    assert post["n"] == 1 and post["correct"] == 1


def test_score_handles_unannotated_items():
    pairs = collect_pairs(_dossiers(), _nodes())
    sheet = build_sheet(pairs, decoys=0, seed=1)
    res = score(sheet, [])
    assert res["annotated"] == 0
    assert res["precision"]["overall"]["value"] is None, "0/0 is undefined, not 0.0"


def test_labels_are_the_three_documented_ones():
    assert set(LABELS) == {"supports", "contradicts", "irrelevant"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
