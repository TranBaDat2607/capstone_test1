#!/usr/bin/env python3
"""
build_census_43.py — build the blind annotation sheets for the CURRENT
cited-evidence population, post the 2026-08-13 P1 cache-key fix.

Why a new driver instead of reusing the old sheetA/B/C.xlsx
-------------------------------------------------------------
sheetA.xlsx and sheetB.xlsx are already-filled, named external experts'
answer sheets scored against the OLD 226-pair population (see
docs/proposals/thesis_review.md issue #17). Editing them in place would corrupt that
historical record. sheetC.xlsx is the same old-population template, unfilled.

The pipeline's cited output has since moved twice (226 -> 24 -> 43); the
CURRENT population is whatever `collect_pairs` finds in the live dossiers
today. Because that population (expected ~43) is smaller than the sample
size the original protocol used (200), this is a CENSUS, not a sample:
`sample_pairs` with n >= population returns the whole population untouched
(evalu/ANNOTATION_PROTOCOL.md notes this explicitly for exactly this case).

No decoys / attention-check items are included in this round (dropped by
project decision on 2026-08-13 -- see the removal of the attention-check
paragraph from capstone_report/main.tex in the same sitting). Every row in
the resulting sheet is a real cited pair.

Uses the SAME frozen v1.0 criteria in docs/ANNOTATION_GUIDELINE.md (relation
labels, about_claim_company question, the "when torn, choose irrelevant"
rule) -- no edit to that file, because the criteria have not changed, only
the population being labelled has. Both annotators receive the identical
item set (same seed => same sample/decoy draw for both), which is what lets
score() compute inter-annotator agreement on matching pair_ids.

Offline: reads only what's already on disk (graph_output/, config/). No LLM,
no Neo4j, no network. Writes only under evalu/out/annotation/census_43/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evalu import loaders, negative_control  # noqa: E402
from evalu.annotation import (build_sheet, collect_pairs, sample_pairs,  # noqa: E402
                              write_sheet)

OUT_DIR = REPO_ROOT / "evalu" / "out" / "annotation" / "census_43"
DECOYS = 0
SEED = 42


def main() -> None:
    graph = loaders.load_resolved_graph()
    nodes = graph.get("nodes", [])
    dossiers, tickers = loaders.load_dossiers()

    issuer_registry = json.loads((REPO_ROOT / "config" / "issuer_registry.json")
                                 .read_text(encoding="utf-8"))
    variants = negative_control.load_issuer_variants(issuer_registry)

    pairs = collect_pairs(dossiers, nodes, variants)
    census = sample_pairs(pairs, n=len(pairs), seed=SEED)  # n>=population => whole population

    print(f"Tickers in corpus: {tickers}")
    print(f"Total cited (claim, evidence) pairs found: {len(pairs)}")
    print(f"Census size (== total, since n >= population): {len(census)}")
    by_kind: dict = {}
    for p in census:
        by_kind[p["system_kind"]] = by_kind.get(p["system_kind"], 0) + 1
    print(f"By system_kind: {by_kind}")
    by_company: dict = {}
    for p in census:
        by_company[p["claim_company"]] = by_company.get(p["claim_company"], 0) + 1
    print(f"By company: {by_company}")

    for annotator, name in (("A", "sheet_A"), ("B", "sheet_B")):
        sheet = build_sheet(census, decoys=DECOYS, seed=SEED, annotator=annotator)
        paths = write_sheet(sheet, OUT_DIR, name=name)
        n_items = len(sheet["items"])
        n_decoys = len(sheet["_decoy_ids"])
        print(f"  wrote {name}: {n_items} items ({n_items - n_decoys} real + "
             f"{n_decoys} decoys) -> {paths['json'].relative_to(REPO_ROOT)}")

    # sheetC: same template, deliberately unfilled (matches the existing
    # sheetC.xlsx convention noted in docs/ANNOTATION_RESULTS.md)
    sheet_c = build_sheet(census, decoys=DECOYS, seed=SEED, annotator="")
    write_sheet(sheet_c, OUT_DIR, name="sheet_C")
    print(f"  wrote sheet_C (blank template) -> {(OUT_DIR / 'sheet_C.json').relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
