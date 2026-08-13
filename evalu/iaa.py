"""
Inter-annotator agreement (Khung Đánh Giá Graph-RAG §4).

Four coefficients, because no single one survives this project's data:

  fleiss_kappa        classic multi-rater nominal agreement. Kept for the raw
                      ESG sentence-labelling arm, where the E/S/G/Neutral
                      classes are reasonably balanced.
  cohen_kappa         two raters, nominal. Kept mainly so the reports can SHOW
                      the prevalence paradox next to AC1 rather than assert it.
  krippendorff_alpha  handles missing ratings natively and supports ordinal
                      weighting — the right default for a 1..5 Likert grid that
                      not every expert fills in completely.
  gwet_ac1 / gwet_ac2 the cross-check layer's headline coefficient. Most claims
                      land in `unverified_insufficient_evidence`, and under that
                      kind of skew Kappa's chance-agreement term approaches 1 and
                      the coefficient collapses toward 0 even at 95%+ observed
                      agreement. Gwet's chance term is anchored on prevalence and
                      does not.

Input format
------------
Everything except `fleiss_kappa(..., counts=True)` takes a *reliability matrix*:
a list of units, each a list of one rating per rater, with None for "this rater
did not score this unit".

    matrix = [
        [5, 4, None],   # unit 1: rater A gave 5, B gave 4, C abstained
        [3, 3, 3],      # unit 2
    ]

Ordinal coefficients require the categories to be sortable (ints for Likert).

No numpy: the annotation batches here are hundreds of rows, and a bare clone
must be able to run this.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

Matrix = Sequence[Sequence[Any]]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _unit_counts(matrix: Matrix) -> Tuple[List[Counter], List[Any]]:
    """Per-unit category counts, plus the sorted category vocabulary."""
    per_unit = []
    vocab = set()
    for row in matrix:
        c = Counter(v for v in row if v is not None)
        per_unit.append(c)
        vocab.update(c)
    try:
        categories = sorted(vocab)
    except TypeError:                                    # mixed/unsortable labels
        categories = sorted(vocab, key=str)
    return per_unit, categories


def _pairable(per_unit: List[Counter]) -> List[Counter]:
    """Units rated fewer than twice carry no agreement information."""
    return [c for c in per_unit if sum(c.values()) >= 2]


def landis_koch_label(value: Optional[float]) -> Optional[str]:
    """Landis & Koch (1977) verbal anchors, used by §4 step 2 (threshold 0.61)."""
    if value is None:
        return None
    if value < 0.00:
        return "poor"
    if value < 0.21:
        return "slight"
    if value < 0.41:
        return "fair"
    if value < 0.61:
        return "moderate"
    if value < 0.81:
        return "substantial"
    return "almost perfect"


# --------------------------------------------------------------------------- #
# Fleiss' kappa
# --------------------------------------------------------------------------- #
def fleiss_kappa(data: Matrix, counts: bool = False) -> Optional[float]:
    """
    Fleiss' kappa for m raters over N subjects and q nominal categories.

    `counts=True` reads `data` as an N x q table of per-subject category counts
    (the shape published examples use); otherwise it is a reliability matrix.

    Returns None when chance agreement is 1 (every rating in one category), where
    kappa is mathematically undefined — reporting 0.0 there would read as
    "no agreement" when the truth is "the coefficient cannot speak".
    """
    if counts:
        table = [list(row) for row in data]
    else:
        per_unit, categories = _unit_counts(data)
        table = [[c.get(cat, 0) for cat in categories] for c in _pairable(per_unit)]

    table = [row for row in table if sum(row) >= 2]
    if not table:
        return None

    n_per_subject = {sum(row) for row in table}
    if len(n_per_subject) != 1:
        raise ValueError(
            "Fleiss' kappa requires the same number of raters on every subject; "
            f"got {sorted(n_per_subject)}. Use krippendorff_alpha for ragged data."
        )
    n = n_per_subject.pop()
    N = len(table)
    total = N * n

    p_bar = sum((sum(x * x for x in row) - n) / (n * (n - 1)) for row in table) / N
    col_totals = [sum(row[j] for row in table) for j in range(len(table[0]))]
    p_e = sum((c / total) ** 2 for c in col_totals)

    if abs(1 - p_e) < 1e-12:
        return None
    return (p_bar - p_e) / (1 - p_e)


# --------------------------------------------------------------------------- #
# Cohen's kappa
# --------------------------------------------------------------------------- #
def cohen_kappa(matrix: Matrix) -> Optional[float]:
    """Cohen's kappa for exactly two raters; units with a gap are dropped."""
    pairs = [(r[0], r[1]) for r in matrix if len(r) >= 2
             and r[0] is not None and r[1] is not None]
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    m1 = Counter(a for a, _ in pairs)
    m2 = Counter(b for _, b in pairs)
    pe = sum((m1.get(k, 0) / n) * (m2.get(k, 0) / n) for k in set(m1) | set(m2))
    if abs(1 - pe) < 1e-12:
        return None
    return (po - pe) / (1 - pe)


# --------------------------------------------------------------------------- #
# Krippendorff's alpha
# --------------------------------------------------------------------------- #
def coincidence_matrix(matrix: Matrix) -> Tuple[Dict[Tuple[Any, Any], float],
                                                Dict[Any, float], float]:
    """
    Krippendorff's coincidence matrix.

    Each unit contributes its ordered pairs of distinct ratings, weighted by
    1/(m_u - 1) so that units rated by many observers do not dominate units
    rated by few. Returns (o, marginals, n).
    """
    o: Dict[Tuple[Any, Any], float] = {}
    for row in matrix:
        vals = [v for v in row if v is not None]
        m = len(vals)
        if m < 2:
            continue
        w = 1.0 / (m - 1)
        for i, a in enumerate(vals):
            for j, b in enumerate(vals):
                if i == j:
                    continue
                o[(a, b)] = o.get((a, b), 0.0) + w

    marginals: Dict[Any, float] = {}
    for (a, _b), v in o.items():
        marginals[a] = marginals.get(a, 0.0) + v
    n = sum(marginals.values())
    # keep integral counts integral so tests can compare them exactly
    marginals = {k: (round(v) if abs(v - round(v)) < 1e-9 else v)
                 for k, v in marginals.items()}
    n = round(n) if abs(n - round(n)) < 1e-9 else n
    return o, marginals, n


def _delta2(level: str, categories: List[Any], marginals: Dict[Any, float]):
    """Squared difference function for the requested measurement level."""
    if level == "nominal":
        return lambda a, b: 0.0 if a == b else 1.0

    if level == "interval":
        return lambda a, b: float(a - b) ** 2

    if level == "ordinal":
        rank = {c: i for i, c in enumerate(categories)}
        cum = []
        running = 0.0
        for c in categories:
            running += marginals.get(c, 0.0)
            cum.append(running)

        def d2(a, b):
            ia, ib = rank[a], rank[b]
            lo, hi = (ia, ib) if ia <= ib else (ib, ia)
            # sum of marginals from lo..hi, minus half the two endpoints
            span = cum[hi] - (cum[lo - 1] if lo > 0 else 0.0)
            g = span - (marginals.get(categories[lo], 0.0)
                        + marginals.get(categories[hi], 0.0)) / 2.0
            return g * g

        return d2

    raise ValueError(f"unknown level {level!r}; use nominal|ordinal|interval")


def krippendorff_alpha(matrix: Matrix, level: str = "nominal") -> Optional[float]:
    """
    Krippendorff's alpha. `level` selects the difference function:
    nominal (any mismatch costs the same), ordinal (rank distance, weighted by
    the marginals — the right choice for Likert), or interval.

    Returns 1.0 when there is no observed disagreement, and None when expected
    disagreement is 0 (a single category overall), where alpha is undefined.
    """
    o, marginals, n = coincidence_matrix(matrix)
    if n < 2:
        return None
    try:
        categories = sorted(marginals)
    except TypeError:
        categories = sorted(marginals, key=str)

    d2 = _delta2(level, categories, marginals)

    do = sum(v * d2(a, b) for (a, b), v in o.items()) / n
    de = sum(marginals[a] * marginals[b] * d2(a, b)
             for a in categories for b in categories if a != b) / (n * (n - 1))

    if abs(de) < 1e-12:
        return None if do > 0 else 1.0
    return 1.0 - do / de


# --------------------------------------------------------------------------- #
# Gwet's AC1 / AC2
# --------------------------------------------------------------------------- #
def _gwet_weights(categories: List[Any], kind: str) -> Dict[Tuple[Any, Any], float]:
    q = len(categories)
    idx = {c: i for i, c in enumerate(categories)}
    w: Dict[Tuple[Any, Any], float] = {}
    for a in categories:
        for b in categories:
            d = abs(idx[a] - idx[b])
            if kind == "identity":
                w[(a, b)] = 1.0 if d == 0 else 0.0
            elif kind == "linear":
                w[(a, b)] = 1.0 - (d / (q - 1)) if q > 1 else 1.0
            elif kind == "ordinal":
                # Gwet's ordinal weights: 1 - C(d+1,2)/C(q,2)
                w[(a, b)] = 1.0 - (d * (d + 1)) / (q * (q - 1)) if q > 1 else 1.0
            else:
                raise ValueError(f"unknown weights {kind!r}")
    return w


def _gwet(matrix: Matrix, weights: str) -> Optional[float]:
    per_unit, categories = _unit_counts(matrix)
    units = _pairable(per_unit)
    q = len(categories)
    if not units or q == 0:
        return None
    if q == 1:
        # everyone agreed on the only category in play; chance-corrected
        # agreement is undefined rather than perfect
        return None

    w = _gwet_weights(categories, weights)

    pa = 0.0
    for c in units:
        n_i = sum(c.values())
        acc = 0.0
        for a in categories:
            n_ia = c.get(a, 0)
            if not n_ia:
                continue
            for b in categories:
                n_ib = c.get(b, 0)
                if not n_ib:
                    continue
                acc += w[(a, b)] * n_ia * (n_ib - (1 if a == b else 0))
        pa += acc / (n_i * (n_i - 1))
    pa /= len(units)

    # prevalence of each category, averaged over units
    pi = {}
    for a in categories:
        pi[a] = sum(c.get(a, 0) / sum(c.values()) for c in units) / len(units)

    spread = sum(p * (1 - p) for p in pi.values())
    t_w = sum(w.values())
    pe = (t_w / (q * (q - 1))) * spread

    if abs(1 - pe) < 1e-12:
        return None
    return (pa - pe) / (1 - pe)


def gwet_ac1(matrix: Matrix) -> Optional[float]:
    """Gwet's AC1 — unweighted (nominal categories)."""
    return _gwet(matrix, "identity")


def gwet_ac2(matrix: Matrix, weights: str = "ordinal") -> Optional[float]:
    """
    Gwet's AC2 — the weighted generalisation of AC1, for ordinal scales.

    `weights="identity"` reduces exactly to AC1 (asserted in the test suite);
    "ordinal" is Gwet's own rank weighting and is the default for Likert data.
    """
    return _gwet(matrix, weights)


# --------------------------------------------------------------------------- #
# convenience
# --------------------------------------------------------------------------- #
def agreement_report(matrix: Matrix, ordinal: bool = True) -> Dict[str, Any]:
    """Every coefficient at once, plus the Landis & Koch reading of the headline."""
    level = "ordinal" if ordinal else "nominal"
    headline = gwet_ac2(matrix) if ordinal else gwet_ac1(matrix)
    return {
        "units": len(matrix),
        "raters": max((len(r) for r in matrix), default=0),
        "gwet_ac1": gwet_ac1(matrix),
        "gwet_ac2": gwet_ac2(matrix) if ordinal else None,
        "krippendorff_alpha": krippendorff_alpha(matrix, level=level),
        "fleiss_kappa": _safe_fleiss(matrix),
        "cohen_kappa": cohen_kappa(matrix) if all(len(r) == 2 for r in matrix) else None,
        "headline": headline,
        "headline_metric": "gwet_ac2" if ordinal else "gwet_ac1",
        "headline_label": landis_koch_label(headline),
        "meets_substantial_threshold": (headline is not None and headline >= 0.61),
    }


def _safe_fleiss(matrix: Matrix) -> Optional[float]:
    try:
        return fleiss_kappa(matrix)
    except ValueError:
        return None       # ragged rater counts: Fleiss simply does not apply
