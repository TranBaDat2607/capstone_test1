#!/usr/bin/env python3
"""
Offline unit checks for evalu/retrieval_eval.py — the baseline comparison.

This is the piece that makes the work an EVALUATION rather than a test suite:
it asks whether Graph-RAG retrieval beats simpler alternatives, in the shape the
comparable capstone (AIP491) uses — Recall@k / Precision@k over a pooled
candidate set, with the graph ablated away in stages.

Run from the repo root:

    python test/test_evalu_retrieval.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evalu.retrieval_eval import (  # noqa: E402
    METHODS,
    bm25_scores,
    evaluate_run,
    pool_candidates,
    precision_at_k,
    recall_at_k,
)


def approx(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


# ------------------------------------------------------------------ metrics
def test_recall_and_precision_at_k():
    ranked = [10, 11, 12, 13, 14]
    gold = {11, 14, 99}                       # 99 was never retrieved
    assert approx(recall_at_k(ranked, gold, 3), 1 / 3)      # only 11 in top-3
    assert approx(recall_at_k(ranked, gold, 5), 2 / 3)
    assert approx(precision_at_k(ranked, gold, 3), 1 / 3)
    assert approx(precision_at_k(ranked, gold, 5), 2 / 5)


def test_precision_divides_by_k_not_by_hits():
    # a short ranked list must still be penalised against the full cut-off,
    # otherwise a retriever that returns one lucky item scores 100%
    assert approx(precision_at_k([7], {7}, 3), 1 / 3)


def test_metrics_undefined_without_gold():
    assert recall_at_k([1, 2], set(), 3) is None
    assert precision_at_k([], {1}, 3) == 0.0


# ------------------------------------------------------------------- bm25
def test_bm25_ranks_the_lexically_closest_document_first():
    docs = {
        1: "giảm phát thải khí nhà kính tại nhà máy",
        2: "chính sách nhân sự và đào tạo nhân viên",
        3: "phát thải khí nhà kính giảm mạnh trong năm",
    }
    scores = bm25_scores("phát thải khí nhà kính", docs)
    top = max(scores, key=scores.get)
    assert top in (1, 3), scores
    assert scores[2] < scores[top]


def test_bm25_ignores_terms_present_in_every_document():
    # a term in every doc has zero discriminative power; IDF must neutralise it
    docs = {1: "công ty a", 2: "công ty b", 3: "công ty c"}
    scores = bm25_scores("công ty", docs)
    assert max(scores.values()) - min(scores.values()) < 1e-6, scores


# ------------------------------------------------------------------ pooling
def test_pool_is_the_union_of_every_system_top_k():
    runs = {
        "sysA": {"c1": [1, 2, 3]},
        "sysB": {"c1": [3, 4, 5]},
        "random": {"c1": [9]},
    }
    pool = pool_candidates(runs, depth=3)
    assert pool["c1"] == {1, 2, 3, 4, 5, 9}, pool


def test_pool_respects_depth():
    runs = {"sysA": {"c1": [1, 2, 3, 4, 5]}}
    assert pool_candidates(runs, depth=2)["c1"] == {1, 2}


def test_pool_is_why_annotation_cannot_come_from_one_system():
    """
    Judging only what the incumbent retrieved makes every baseline look worse by
    construction: an item a baseline found and the incumbent missed would be
    unjudged, and counted as non-relevant. Pooling is what removes that bias.
    """
    runs = {"incumbent": {"c1": [1, 2]}, "baseline": {"c1": [7, 8]}}
    pool = pool_candidates(runs, depth=2)
    assert {7, 8} <= pool["c1"], "baseline-only findings must enter the pool"


# --------------------------------------------------------------- evaluation
def test_evaluate_run_macro_averages_across_claims():
    run = {"c1": [1, 2, 3], "c2": [4, 5, 6]}
    gold = {"c1": {1}, "c2": {5, 6}}
    res = evaluate_run(run, gold, ks=(3,))
    # c1: R@3 = 1/1 = 1.0 ; c2: R@3 = 2/2 = 1.0 -> macro 1.0
    assert approx(res["recall@3"], 1.0)
    # c1: P@3 = 1/3 ; c2: P@3 = 2/3 -> macro 0.5
    assert approx(res["precision@3"], 0.5)
    assert res["claims_scored"] == 2


def test_evaluate_run_skips_claims_with_no_gold():
    run = {"c1": [1], "c2": [2]}
    gold = {"c1": {1}}                        # c2 has no judged relevant item
    res = evaluate_run(run, gold, ks=(3,))
    assert res["claims_scored"] == 1, "an unjudged claim must not count as 0 recall"


def test_methods_include_the_required_ablation_arms():
    # the comparison is only meaningful if the graph can be removed in stages
    for name in ("random", "bm25", "token_overlap", "indicator_only",
                 "token_plus_indicator"):
        assert name in METHODS, name


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
