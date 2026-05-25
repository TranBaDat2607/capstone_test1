"""Compile the reviewed CSV into the final ESG keyword dictionary.

Reads `data_processing/candidates_review.csv` after the human has filled
in `keep` and `pillar` columns, validates the entries, and writes
`data_processing/esg_keywords_v2.json` — the file that `esg_keywords.py`
loads at import time.

Validation:
  - `keep=Y` rows must have `pillar` set to one of {E, S, G} or a
    comma-separated combination (e.g. "E,S").
  - Rows with `keep=Y` and missing/invalid pillar abort the build with a
    line-numbered error so the reviewer can fix the CSV.

Multi-pillar handling: a term tagged `E,S` is duplicated into both
`by_pillar["E"]` and `by_pillar["S"]`. The `terms` list keeps the
original multi-pillar tag for traceability.

Run:
    python -m data_processing.compile_dictionary
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
INPUT_PATH = HERE / "candidates_review.csv"
OUTPUT_PATH = HERE / "esg_keywords_v2.json"
YAKE_CONFIG_PATH = HERE / "yake_candidates.json"

VALID_PILLARS = {"E", "S", "G"}


def _parse_pillar(raw: str, row_num: int, keyword: str) -> list[str]:
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError(
            f"row {row_num} ('{keyword}'): keep=Y but no pillar set"
        )
    bad = [p for p in parts if p not in VALID_PILLARS]
    if bad:
        raise ValueError(
            f"row {row_num} ('{keyword}'): invalid pillar(s) {bad}; "
            f"must be subset of {sorted(VALID_PILLARS)}"
        )
    # Preserve order, drop dups.
    out: list[str] = []
    for p in parts:
        if p not in out:
            out.append(p)
    return out


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"{INPUT_PATH} not found. Run `python -m data_processing.prune_candidates` "
            "first, then fill in `keep` and `pillar` columns."
        )

    yake_config: dict[str, object] = {}
    if YAKE_CONFIG_PATH.exists():
        try:
            yake_config = json.loads(YAKE_CONFIG_PATH.read_text(encoding="utf-8")).get("config", {})
        except (json.JSONDecodeError, OSError):
            yake_config = {}

    terms: list[dict[str, object]] = []
    by_pillar: dict[str, list[str]] = {"E": [], "S": [], "G": []}
    seen_per_pillar: dict[str, set[str]] = {"E": set(), "S": set(), "G": set()}

    n_total = 0
    n_kept = 0

    with INPUT_PATH.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):  # start=2 → row 1 is header
            n_total += 1
            keep = row.get("keep", "").strip().upper()
            if keep != "Y":
                continue

            keyword = row.get("keyword", "").strip()
            if not keyword:
                raise ValueError(f"row {i}: keep=Y but keyword is empty")

            pillars = _parse_pillar(row.get("pillar", ""), i, keyword)
            score_str = row.get("score", "").strip()
            try:
                score = float(score_str) if score_str else None
            except ValueError:
                score = None

            term_entry = {
                "keyword": keyword,
                "pillar": pillars if len(pillars) > 1 else pillars[0],
                "source": row.get("source", "").strip(),
                "score": score,
                "note": row.get("note", "").strip(),
            }
            terms.append(term_entry)
            n_kept += 1

            for p in pillars:
                key = keyword.lower()
                if key not in seen_per_pillar[p]:
                    by_pillar[p].append(keyword)
                    seen_per_pillar[p].add(key)

    payload = {
        "config": {
            "yake": yake_config,
            "pruned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n_candidates": n_total,
            "n_kept": n_kept,
        },
        "terms": terms,
        "by_pillar": by_pillar,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Read {n_total:,} rows from {INPUT_PATH.name}")
    print(f"Kept {n_kept:,} term(s) → wrote {OUTPUT_PATH.name}")
    for p in ("E", "S", "G"):
        print(f"  pillar {p}: {len(by_pillar[p])}")


if __name__ == "__main__":
    main()
