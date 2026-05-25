"""Hybrid pruning of the YAKE candidate pool.

Reads `data_processing/yake_candidates.json` (merged_pool), optionally
pre-filters by YAKE score, applies the deterministic rejection rules
from `prune_rules.py`, and emits `data_processing/candidates_review.csv`
for human review.

YAKE score convention: *lower score = more relevant*. The `--max-score`
flag (or `MAX_SCORE` constant) keeps only candidates with score below
the threshold, which is useful for trimming the long noisy tail before
human review. Reference distribution from the current pool of 991
candidates: p25 ≈ 1.3e-3, p50 ≈ 2.8e-3, p75 ≈ 6.8e-3, max ≈ 1.8e-2.

The CSV is written with a UTF-8 BOM so Vietnamese characters render
correctly when opened in Excel. Every surviving row is included
(including auto-rejected ones) so the reviewer can spot-check; filter
on `auto_decision` in the spreadsheet to focus on rows that need a
human.

Run:
    python -m data_processing.prune_candidates                 # no score filter
    python -m data_processing.prune_candidates --max-score 3e-3
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from prune_rules import (
    RULE_LABEL,
    classify,
    guess_pillar,
    _seed_terms_by_pillar,
)


HERE = Path(__file__).resolve().parent
INPUT_PATH = HERE / "yake_candidates.json"
OUTPUT_PATH = HERE / "candidates_review.csv"

# Default score cutoff. `None` keeps every candidate; set to a positive
# float (e.g. 3e-3) to drop the tail before the rules are applied.
MAX_SCORE: float | None = 3e-3

CSV_COLUMNS = [
    "keyword",
    "score",
    "source",
    "auto_decision",
    "rule_id",
    "reason",
    "pillar_guess",
    "keep",
    "pillar",
    "note",
]


def _load_merged_pool(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    pool = payload.get("merged_pool")
    if not pool:
        raise ValueError(f"No `merged_pool` in {path}")
    return pool


def main(max_score: float | None = MAX_SCORE) -> None:
    pool = _load_merged_pool(INPUT_PATH)
    n_loaded = len(pool)
    print(f"Loaded {n_loaded:,} candidates from {INPUT_PATH.name}")

    if max_score is not None:
        pool = [e for e in pool if float(e["score"]) <= max_score]
        dropped = n_loaded - len(pool)
        print(
            f"Score filter (score ≤ {max_score:.3e}): "
            f"dropped {dropped:,}, kept {len(pool):,}"
        )

    if not pool:
        raise ValueError(
            "No candidates remain after score filtering. "
            "Raise --max-score or remove it."
        )

    seed = _seed_terms_by_pillar()

    rows: list[dict[str, object]] = []
    rule_counts: Counter[str] = Counter()
    review_count = 0

    for entry in pool:
        keyword = str(entry["keyword"]).strip()
        score = float(entry["score"])
        source = str(entry.get("source", ""))

        rule_id, reason = classify(keyword)
        if rule_id is None:
            decision = "review"
            review_count += 1
            pillar_guess = guess_pillar(keyword, seed=seed)
        else:
            decision = "reject"
            rule_counts[rule_id] += 1
            pillar_guess = ""

        rows.append({
            "keyword": keyword,
            "score": f"{score:.6e}",
            "source": source,
            "auto_decision": decision,
            "rule_id": rule_id or "",
            "reason": reason,
            "pillar_guess": pillar_guess,
            "keep": "",
            "pillar": "",
            "note": "",
        })

    # utf-8-sig writes a BOM so Excel detects UTF-8 on open.
    with OUTPUT_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    rejected = total - review_count
    print(f"\nWrote {total:,} rows to {OUTPUT_PATH}")
    print(f"  auto-rejected : {rejected:,} ({rejected/total:.1%})")
    print(f"  needs review  : {review_count:,} ({review_count/total:.1%})")
    print("\nRejections by rule:")
    for rule_id in sorted(rule_counts, key=lambda r: rule_counts[r], reverse=True):
        label = RULE_LABEL.get(rule_id, rule_id)
        print(f"  [{rule_id}] {rule_counts[rule_id]:>5,}  {label}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--max-score",
        type=float,
        default=MAX_SCORE,
        help=(
            "Drop candidates with YAKE score above this threshold "
            "(lower score = more relevant; reference quartiles: "
            "p25≈1.3e-3, p50≈2.8e-3, p75≈6.8e-3). Default: no filter."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(max_score=args.max_score)
