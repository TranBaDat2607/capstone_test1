#!/usr/bin/env python3
"""
Offline unit checks for evalu/negative_control.py.

This is the falsification layer the §2 metrics lack: every metric in metrics.py
is a conformance check against the system's own design, so it can only confirm
that the code does what the code does. The tests here back a measurement that
can say "the analytical core is not doing what it claims" — and on the live
corpus, it does.

Run from the repo root:

    python test/test_evalu_negative_control.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evalu.negative_control import (  # noqa: E402
    attribute_ticker,
    evidence_attribution_audit,
    mentions_claimant,
    same_feed_specificity,
)


def approx(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


# ------------------------------------------------------------------ attribution
def test_attribute_ticker_from_news_source_doc():
    node = {"class": "MediaReport",
            "properties": {"source_doc": "AAA__baodautu.vn__6bef6bcbb6"}}
    assert attribute_ticker(node) == "AAA"


def test_attribute_ticker_is_none_for_report_side_nodes():
    # annual-report docs use a different naming convention and carry no ticker
    # prefix; guessing one would silently mis-attribute half the graph
    assert attribute_ticker({"properties": {"source_doc": "AAA_2013"}}) is None
    assert attribute_ticker({"properties": {"source_doc": ""}}) is None
    assert attribute_ticker({"properties": {}}) is None
    assert attribute_ticker({}) is None


def test_mentions_claimant_matches_name_variants_diacritic_insensitively():
    variants = {"ACG": {"an cuong", "acg", "go an cuong"}}
    node = {"properties": {"title": "An Cường – 30 năm phát triển bền vững"}}
    assert mentions_claimant(node, variants["ACG"]) is True
    other = {"properties": {"title": "Nhựa An Phát Xanh đấu giá cổ phiếu"}}
    assert mentions_claimant(other, variants["ACG"]) is False


def test_mentions_claimant_reads_only_fields_the_system_itself_sees():
    """
    The adjudicator is shown node_text(), which for a MediaReport is the title
    alone. Checking a field the pipeline never passes to the LLM would overstate
    what the system could have known.
    """
    node = {"properties": {"title": "Doanh nghiệp giảm phát thải",
                           "secret_body": "bài này nói về An Cường"}}
    assert mentions_claimant(node, {"an cuong"}) is False


# ------------------------------------------------------------------- audit
NODES = [
    {"class": "MediaReport", "properties": {"source_doc": "AAA__x.vn__1",
                                            "title": "AAA giảm phát thải"}},
    {"class": "MediaReport", "properties": {"source_doc": "ACG__y.vn__2",
                                            "title": "An Cường Net Zero 2050"}},
    {"class": "Penalty", "properties": {"source_doc": "AGG__z.vn__3",
                                        "description": "Phạt 3 tỷ đồng thao túng"}},
]
VARIANTS = {"AAA": {"aaa", "an phat"}, "ACG": {"acg", "an cuong"},
            "AGG": {"agg", "an gia"}}


def test_evidence_attribution_audit_counts_cross_feed():
    dossiers = [
        {"_ticker": "AAA", "assessment": "appears_supported",
         "supporting_evidence": [{"node_index": 0}],       # same feed
         "contradicting_evidence": []},
        {"_ticker": "AAA", "assessment": "appears_supported",
         "supporting_evidence": [{"node_index": 1}],       # ACG article
         "contradicting_evidence": []},
        {"_ticker": "AAA", "assessment": "appears_contradicted",
         "supporting_evidence": [],
         "contradicting_evidence": [{"node_index": 2}]},   # AGG penalty
    ]
    r = evidence_attribution_audit(dossiers, NODES, VARIANTS)
    d = r.details
    assert d["cited_total"] == 3
    assert d["same_feed"] == 1
    assert d["cross_feed"] == 2
    # neither cross-feed item names AAA, so neither is defensible
    assert d["cross_feed_unmentioned"] == 2
    assert approx(r.value, 1 / 3)          # metric = same-feed share
    # the contradiction arm is reported separately: it is the headline output
    assert d["by_kind"]["contradicting_evidence"]["cross_feed"] == 1


def test_audit_credits_a_cross_feed_article_that_names_the_claimant():
    """
    A story in ACG's feed that genuinely discusses AAA IS usable evidence. The
    audit must separate 'wrong feed' from 'wrong company', or the fix would
    throw away legitimate cross-feed coverage.
    """
    nodes = [{"class": "MediaReport",
              "properties": {"source_doc": "ACG__y.vn__9",
                             "title": "An Phát Xanh bị xử phạt môi trường"}}]
    dossiers = [{"_ticker": "AAA", "assessment": "appears_contradicted",
                 "supporting_evidence": [],
                 "contradicting_evidence": [{"node_index": 0}]}]
    r = evidence_attribution_audit(dossiers, nodes, VARIANTS)
    assert r.details["cross_feed"] == 1
    assert r.details["cross_feed_unmentioned"] == 0, "article names AAA -> defensible"


# ------------------------------------------------------- specificity / null
def test_same_feed_specificity_detects_chance_level_retrieval():
    """
    The null: if retrieval carries no company signal, the share of a company's
    evidence drawn from its own feed equals that feed's share of the pool.
    """
    pool_by_ticker = {"AAA": 7, "ACG": 18, "ACC": 9, "AGG": 8, "ADP": 2}   # 44
    # AAA cites 10 items, 1.6 expected from its own feed by chance; it got 2
    r = same_feed_specificity({"AAA": (2, 10)}, pool_by_ticker)
    assert approx(r.details["by_ticker"]["AAA"]["expected_rate"], 7 / 44)
    assert approx(r.details["by_ticker"]["AAA"]["observed_rate"], 0.2)
    assert r.details["by_ticker"]["AAA"]["lift"] > 1.0


def test_same_feed_specificity_lift_below_one_means_worse_than_chance():
    pool_by_ticker = {"AAA": 22, "ACG": 22}
    r = same_feed_specificity({"AAA": (2, 20)}, pool_by_ticker)   # 10% vs 50%
    assert r.details["by_ticker"]["AAA"]["lift"] < 1.0
    assert r.passed is False


def test_same_feed_specificity_perfect_retrieval_passes():
    pool_by_ticker = {"AAA": 10, "ACG": 10}
    r = same_feed_specificity({"AAA": (20, 20)}, pool_by_ticker)
    assert approx(r.details["by_ticker"]["AAA"]["observed_rate"], 1.0)
    assert r.passed is True


def test_same_feed_specificity_handles_empty_input():
    r = same_feed_specificity({}, {"AAA": 5})
    assert r.value is None, "no citations -> undefined, not 0.0"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
