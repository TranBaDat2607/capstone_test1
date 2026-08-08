#!/usr/bin/env python3
"""
Offline test for test3/compare_metrics.py — the measuring instruments used to compare
the Graph-RAG arm against the plain-RAG arm.

No LLM, no network, no artifacts needed. Run from the repo root:

    python test3/test_compare_metrics.py

Why these particular assertions: a metric that is silently wrong produces a number that
looks fine and cannot be caught by eyeballing the output sheet. So every function is
pinned on cases where the right answer is known by hand — identical texts, disjoint
texts, empty input — plus the degenerate cases that make naive implementations divide
by zero or return a flattering value.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.core.console import ensure_utf8_stdout  # noqa: E402

from test3.compare_metrics import (  # noqa: E402
    bootstrap_ci,
    confusion,
    cosine,
    jaccard,
    label_agreement,
    mcnemar_exact,
    normalize_vn,
    rouge_l,
    text_similarity,
    token_prf,
    tokens,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def close(a, b, eps=1e-9):
    return a is not None and abs(a - b) < eps


# --------------------------------------------------------------------------
def test_normalize_and_tokens() -> None:
    print("\n[1] normalize_vn / tokens — Vietnamese text, punctuation, case")

    check("case folded", normalize_vn("Phạt Tiền") == normalize_vn("phạt tiền"))
    check("diacritics PRESERVED (they carry meaning in Vietnamese)",
          "ạ" in normalize_vn("Phạt"), normalize_vn("Phạt"))
    check("punctuation dropped",
          tokens("phạt 1,5 tỷ đồng.") == tokens("phạt 1 5 tỷ đồng"),
          f"{tokens('phạt 1,5 tỷ đồng.')} vs {tokens('phạt 1 5 tỷ đồng')}")
    check("whitespace collapsed", normalize_vn("a   b\n c") == normalize_vn("a b c"))
    check("empty text yields no tokens", tokens("") == [] and tokens(None) == [])

    # NFC: the same Vietnamese word typed decomposed vs precomposed must not read as
    # two different tokens — the corpus mixes both (ragtest/corpus.py normalizes to NFC).
    check("NFC-normalized: composed and decomposed forms match",
          tokens("Phạt") == tokens("Phạt"), f"{tokens('Phạt')} vs {tokens('Phạt')}")


# --------------------------------------------------------------------------
def test_word_matching() -> None:
    print("\n[2] word matching — token P/R/F1, Jaccard, ROUGE-L")

    a = "phạt 1,5 tỷ đồng do thao túng cổ phiếu"
    check("identical text → F1 = 1", close(token_prf(a, a)["f1"], 1.0))
    check("identical text → Jaccard = 1", close(jaccard(a, a), 1.0))
    check("identical text → ROUGE-L = 1", close(rouge_l(a, a), 1.0))

    check("disjoint text → F1 = 0", close(token_prf("alpha beta", "gamma delta")["f1"], 0.0))
    check("disjoint text → Jaccard = 0", close(jaccard("alpha beta", "gamma delta"), 0.0))
    check("disjoint text → ROUGE-L = 0", close(rouge_l("alpha beta", "gamma delta"), 0.0))

    # Half overlap, hand-computed: a={x,y}, b={y,z} → P=1/2, R=1/2, F1=1/2, J=1/3
    prf = token_prf("x y", "y z")
    check("half overlap → P=R=F1=0.5",
          close(prf["precision"], 0.5) and close(prf["recall"], 0.5) and close(prf["f1"], 0.5),
          str(prf))
    check("half overlap → Jaccard = 1/3", close(jaccard("x y", "y z"), 1 / 3))

    # Precision and recall must NOT be symmetric — a short prediction inside a long
    # reference has high precision, low recall. A metric that returns the same number
    # both ways has silently collapsed to Jaccard.
    short_long = token_prf("a b", "a b c d")
    check("P > R when the first text is the shorter one",
          short_long["precision"] > short_long["recall"], str(short_long))
    check("token_prf is direction-sensitive",
          token_prf("a b", "a b c d")["precision"] != token_prf("a b c d", "a b")["precision"])
    check("jaccard IS symmetric", close(jaccard("a b", "a b c d"), jaccard("a b c d", "a b")))

    # ROUGE-L sees ORDER, Jaccard does not — that is the whole reason to keep both.
    check("ROUGE-L penalises reordering, Jaccard does not",
          rouge_l("a b c d", "d c b a") < 1.0 and close(jaccard("a b c d", "d c b a"), 1.0),
          f"rouge={rouge_l('a b c d', 'd c b a')} jac={jaccard('a b c d', 'd c b a')}")

    # Empty input must be 0, never a crash and never 1.0 ("two empty strings are
    # identical" would score a failed retrieval as a perfect match).
    for name, fn in (("token F1", lambda x, y: token_prf(x, y)["f1"]),
                     ("jaccard", jaccard), ("rouge_l", rouge_l)):
        check(f"{name}: empty vs text = 0", close(fn("", "abc"), 0.0))
        check(f"{name}: empty vs empty = 0 (NOT 1)", close(fn("", ""), 0.0))


# --------------------------------------------------------------------------
def test_cosine() -> None:
    print("\n[3] cosine — semantic similarity over embedding vectors")

    check("identical vectors → 1", close(cosine([1.0, 0.0], [1.0, 0.0]), 1.0))
    check("orthogonal vectors → 0", close(cosine([1.0, 0.0], [0.0, 1.0]), 0.0))
    check("opposite vectors → -1", close(cosine([1.0, 0.0], [-1.0, 0.0]), -1.0))
    check("magnitude does not matter", close(cosine([3.0, 0.0], [9.0, 0.0]), 1.0))
    check("zero vector → None, not a divide-by-zero", cosine([0.0, 0.0], [1.0, 0.0]) is None)
    check("missing vector → None", cosine(None, [1.0, 0.0]) is None)


# --------------------------------------------------------------------------
def test_label_agreement() -> None:
    print("\n[4] relation labels — confusion matrix, agreement, kappa")

    labels = ("supports", "contradicts", "irrelevant")
    a = ["supports", "supports", "contradicts", "irrelevant"]
    b = ["supports", "irrelevant", "contradicts", "irrelevant"]

    matrix = confusion(a, b, labels)
    check("confusion matrix is labels x labels",
          set(matrix) == set(labels) and all(set(row) == set(labels) for row in matrix.values()))
    check("diagonal counts the agreements",
          matrix["supports"]["supports"] == 1 and matrix["contradicts"]["contradicts"] == 1
          and matrix["irrelevant"]["irrelevant"] == 1, str(matrix))
    check("off-diagonal counts the one disagreement",
          matrix["supports"]["irrelevant"] == 1, str(matrix["supports"]))
    check("matrix total equals the number of items",
          sum(sum(row.values()) for row in matrix.values()) == len(a))

    report = label_agreement(a, b, labels)
    check("raw agreement = 3/4", close(report["agreement"], 0.75), str(report["agreement"]))
    check("cohen kappa present and below raw agreement (chance-corrected)",
          report["cohen_kappa"] is not None and report["cohen_kappa"] < report["agreement"],
          str(report["cohen_kappa"]))
    check("n reported", report["n"] == 4)

    # Perfect agreement → kappa 1. Total disagreement must NOT come back positive.
    perfect = label_agreement(a, a, labels)
    check("identical label lists → agreement 1 and kappa 1",
          close(perfect["agreement"], 1.0) and close(perfect["cohen_kappa"], 1.0),
          str(perfect))

    # The degenerate case that breaks naive kappa: both raters constant. Agreement is
    # 1.0 but kappa is undefined (no variance) — must be None, never 0 or 1.
    const = label_agreement(["supports"] * 5, ["supports"] * 5, labels)
    check("both arms constant → agreement 1 but kappa is None (undefined)",
          close(const["agreement"], 1.0) and const["cohen_kappa"] is None, str(const))

    check("empty input → n=0, no crash", label_agreement([], [], labels)["n"] == 0)
    try:
        label_agreement(["supports"], ["supports", "irrelevant"], labels)
        check("mismatched lengths rejected", False, "no exception raised")
    except ValueError:
        check("mismatched lengths rejected", True)


# --------------------------------------------------------------------------
def test_stats() -> None:
    print("\n[5] statistics — McNemar, bootstrap CI")

    # Only the discordant cells carry information (AGENT_AB_EVALUATION.md §5.2).
    check("no discordant pairs → p = 1.0", close(mcnemar_exact(0, 0), 1.0))
    check("symmetric discordance → p = 1.0", close(mcnemar_exact(5, 5), 1.0))
    check("all discordance one way is significant", mcnemar_exact(10, 0) < 0.01,
          str(mcnemar_exact(10, 0)))
    check("p is a probability in [0,1]",
          all(0.0 <= mcnemar_exact(x, y) <= 1.0
              for x, y in ((0, 0), (1, 0), (3, 7), (10, 0), (25, 4))))
    check("McNemar is symmetric in b and c",
          close(mcnemar_exact(3, 7), mcnemar_exact(7, 3)))
    # b+c = 1 cannot reach significance, no matter the direction.
    check("a single discordant pair is never significant", mcnemar_exact(1, 0) > 0.05)

    lo, hi = bootstrap_ci([0.5] * 20, reps=200, seed=1)
    check("zero-variance sample → degenerate CI at the value",
          close(lo, 0.5) and close(hi, 0.5), f"({lo}, {hi})")
    lo, hi = bootstrap_ci([0.0, 0.25, 0.5, 0.75, 1.0] * 10, reps=500, seed=1)
    check("CI brackets the mean", lo < 0.5 < hi, f"({lo}, {hi})")
    check("CI is deterministic given a seed",
          bootstrap_ci([0.1, 0.9] * 10, reps=200, seed=7)
          == bootstrap_ci([0.1, 0.9] * 10, reps=200, seed=7))
    check("empty sample → (None, None), no crash", bootstrap_ci([], reps=10) == (None, None))


# --------------------------------------------------------------------------
def test_text_similarity_bundle() -> None:
    print("\n[6] text_similarity — the per-row bundle written to the sheet")

    got = text_similarity("phạt 1,5 tỷ đồng", "phạt 1,5 tỷ đồng")
    for key in ("token_f1", "token_precision", "token_recall", "jaccard", "rouge_l"):
        check(f"{key} present", key in got, str(sorted(got)))
    check("identical text scores 1 on every word-matching metric",
          all(close(got[k], 1.0) for k in ("token_f1", "jaccard", "rouge_l")), str(got))

    empty = text_similarity("", "abc")
    check("a missing claim scores 0 everywhere, never None",
          all(empty[k] == 0.0 for k in ("token_f1", "jaccard", "rouge_l")), str(empty))


def main() -> int:
    ensure_utf8_stdout()
    print("=" * 72)
    print(" test3/compare_metrics.py — offline test")
    print("=" * 72)

    test_normalize_and_tokens()
    test_word_matching()
    test_cosine()
    test_label_agreement()
    test_stats()
    test_text_similarity_bundle()

    print("\n" + "=" * 72)
    if FAILURES:
        print(f" FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print(" ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
