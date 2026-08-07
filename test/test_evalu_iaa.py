#!/usr/bin/env python3
"""
Offline unit checks for evalu/iaa.py — the inter-annotator agreement engine
(Khung Đánh Giá Graph-RAG §4).

The repo has no pytest harness, so this is a plain assert script — run it from
the repo root:

    python test/test_evalu_iaa.py

Every arm is pure math on hard-coded matrices: no artifacts, no network, no LLM.
The point of this file is that the IAA numbers reported in the thesis are
reproducible from published worked examples, not from whatever the code happens
to output.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evalu.iaa import (  # noqa: E402
    coincidence_matrix,
    cohen_kappa,
    fleiss_kappa,
    gwet_ac1,
    gwet_ac2,
    krippendorff_alpha,
    landis_koch_label,
)

NA = None


def approx(a, b, tol=5e-3):
    return abs(a - b) <= tol


# --------------------------------------------------------------------------
# Fleiss' kappa — Wikipedia worked example: 14 raters, 10 subjects, 5 categories
# Published: Pbar = 0.378, PbarE = 0.213, kappa = 0.209
# --------------------------------------------------------------------------
FLEISS_COUNTS = [
    [0, 0, 0, 0, 14],
    [0, 2, 6, 4, 2],
    [0, 0, 3, 5, 6],
    [0, 3, 9, 2, 0],
    [2, 2, 8, 1, 1],
    [7, 7, 0, 0, 0],
    [3, 2, 6, 3, 0],
    [2, 5, 3, 2, 2],
    [6, 5, 2, 1, 0],
    [0, 2, 2, 3, 7],
]


def test_fleiss_kappa_published_example():
    k = fleiss_kappa(FLEISS_COUNTS, counts=True)
    assert approx(k, 0.209), f"Fleiss kappa {k!r} != 0.209"


def test_fleiss_kappa_perfect_and_degenerate():
    # every rater picks the same category for every subject that differs per subject
    perfect = [[3, 0], [0, 3], [3, 0], [0, 3]]
    assert approx(fleiss_kappa(perfect, counts=True), 1.0)
    # all subjects in ONE category -> expected agreement is 1, kappa undefined
    degenerate = [[3, 0], [3, 0], [3, 0]]
    assert fleiss_kappa(degenerate, counts=True) is None


# --------------------------------------------------------------------------
# Krippendorff's alpha — 3 observers x 12 units, with missing ratings.
#
# The expected values below are DERIVED BY HAND from Krippendorff's
# coincidence-matrix definition, not copied from a paper, so they can be
# re-checked line by line:
#
#   pairable units u1..u10 (u11, u12 have a single rating -> excluded)
#   n = 2+3+3+3+3+3+3+3+3+2 = 28
#   coincidences: o11=3  o22=7  o33=6  o44=3  o55=2
#                 o12=o21=1.5   o13=o31=0.5   o23=o32=1.5
#   marginals:    n1=5  n2=10  n3=8  n4=3  n5=2
#
#   nominal:  Do = 7/28 = 0.25
#             De = (28^2 - (25+100+64+9+4)) / (28*27) = 582/756
#             alpha = 1 - 0.25/(582/756) = 0.675258
#
#   ordinal:  d2(1,2)=7.5^2=56.25  d2(1,3)=16.5^2=272.25  d2(2,3)=9^2=81
#             Do = (2*1.5*56.25 + 2*0.5*272.25 + 2*1.5*81)/28 = 684/28
#             De = 94640/756
#             alpha = 1 - (684/28)/(94640/756) = 0.804861
# --------------------------------------------------------------------------
KRIPP_MATRIX = [  # rows = units, cols = observers A, B, C
    [1, 1, NA],
    [2, 2, 3],
    [3, 3, 3],
    [3, 3, 3],
    [2, 2, 2],
    [1, 2, 3],
    [4, 4, 4],
    [1, 1, 2],
    [2, 2, 2],
    [NA, 5, 5],
    [NA, NA, 1],   # single rating -> contributes nothing
    [NA, 3, NA],   # single rating -> contributes nothing
]


def test_coincidence_matrix_internals():
    # Pin the intermediate object, not just the final scalar: a wrong alpha is
    # far easier to diagnose when the coincidence matrix is asserted separately.
    o, marginals, n = coincidence_matrix(KRIPP_MATRIX)
    assert n == 28, n
    assert marginals == {1: 5, 2: 10, 3: 8, 4: 3, 5: 2}, marginals
    assert approx(o[(1, 1)], 3) and approx(o[(2, 2)], 7) and approx(o[(3, 3)], 6)
    assert approx(o[(1, 2)], 1.5) and approx(o[(2, 1)], 1.5)
    assert approx(o[(1, 3)], 0.5) and approx(o[(2, 3)], 1.5)


def test_krippendorff_alpha_nominal():
    a = krippendorff_alpha(KRIPP_MATRIX, level="nominal")
    assert approx(a, 0.675258, tol=1e-5), f"alpha_nominal {a!r} != 0.675258"


def test_krippendorff_alpha_ordinal_rewards_near_misses():
    # Same data: ordinal must be MORE forgiving than nominal here, because every
    # disagreement in this matrix is between near ranks. This is the property the
    # framework relies on when scoring a 1..5 Likert scale.
    nom = krippendorff_alpha(KRIPP_MATRIX, level="nominal")
    ordi = krippendorff_alpha(KRIPP_MATRIX, level="ordinal")
    assert approx(ordi, 0.804861, tol=1e-5), f"alpha_ordinal {ordi!r} != 0.804861"
    assert ordi > nom, f"ordinal {ordi!r} should exceed nominal {nom!r}"


def test_krippendorff_alpha_bounds():
    perfect = [[5, 5, 5], [1, 1, 1], [3, 3, 3], [4, 4, 4]]
    assert approx(krippendorff_alpha(perfect, level="ordinal"), 1.0)
    # a unit rated by a single observer carries no disagreement information
    single = [[5, NA, NA], [1, 1, 1], [3, 3, 3], [4, 4, 4]]
    assert approx(krippendorff_alpha(single, level="ordinal"), 1.0)


def test_krippendorff_ordinal_penalises_distance():
    # two matrices with the SAME number of disagreements, different magnitude
    near = [[1, 2], [3, 3], [4, 4], [2, 2], [5, 5]]
    far = [[1, 5], [3, 3], [4, 4], [2, 2], [5, 5]]
    assert krippendorff_alpha(near, level="ordinal") > krippendorff_alpha(far, level="ordinal")


# --------------------------------------------------------------------------
# Gwet's AC1 — the prevalence-paradox case the framework (§4) is built around.
# 2 raters, 100 items: 90 both-yes, 4 both-no, 3+3 split.
#   pa   = 0.94
#   pi_yes = 0.93, pi_no = 0.07
#   pe_gwet = 2 * 0.93 * 0.07          = 0.1302  -> AC1   = 0.9310
#   pe_cohen = 0.93^2 + 0.07^2         = 0.8698  -> kappa = 0.5392
# Kappa collapses, AC1 does not. That contrast is the reason the framework
# picks AC1/AC2 for the cross-check layer, so it is pinned here.
# --------------------------------------------------------------------------
def paradox_matrix():
    rows = []
    rows += [["yes", "yes"]] * 90
    rows += [["no", "no"]] * 4
    rows += [["yes", "no"]] * 3
    rows += [["no", "yes"]] * 3
    return rows


def test_gwet_ac1_survives_prevalence_paradox():
    m = paradox_matrix()
    ac1 = gwet_ac1(m)
    kappa = cohen_kappa(m)
    assert approx(ac1, 0.9310), f"AC1 {ac1!r} != 0.9310"
    assert approx(kappa, 0.5392), f"Cohen kappa {kappa!r} != 0.5392"
    assert ac1 - kappa > 0.35, "the paradox gap is the whole point of choosing AC1"


def test_gwet_ac1_perfect_agreement():
    assert approx(gwet_ac1([["a", "a"], ["b", "b"], ["c", "c"]]), 1.0)


def test_gwet_ac2_identity_weights_reduce_to_ac1():
    # AC2 is the weighted generalisation of AC1; with identity weights the two
    # MUST coincide. If they don't, the weighting is wired in wrong.
    m = [[1, 1], [2, 3], [3, 3], [5, 4], [1, 2], [4, 4], [2, 2], [5, 5]]
    assert approx(gwet_ac2(m, weights="identity"), gwet_ac1(m), tol=1e-9)


def test_gwet_ac2_ordinal_is_more_lenient_than_ac1():
    # ordinal weights give partial credit for adjacent Likert scores
    m = [[1, 2], [3, 3], [4, 5], [2, 2], [5, 5], [3, 4]]
    assert gwet_ac2(m, weights="ordinal") > gwet_ac1(m)


def test_landis_koch_thresholds():
    assert landis_koch_label(0.05) == "slight"
    assert landis_koch_label(0.25) == "fair"
    assert landis_koch_label(0.45) == "moderate"
    assert landis_koch_label(0.65) == "substantial"
    assert landis_koch_label(0.85) == "almost perfect"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
