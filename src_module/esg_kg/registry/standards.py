"""Step 4b — bootstrap the canonical standards/regulations registry (run-once, NO LLM).

Design: docs/STANDARD_INDICATOR_AXIS.md §3.5. Sibling of step04_build_issuer_registry.py, same
contract: it drafts a registry, a human confirms the `needs_review` entries, and step05 uses the
result as a FROZEN anchor so the mentions never depend on embeddings or an LLM.

THE PROBLEM IT SOLVES (diagnosis C3)
The graph holds 436 `Standard`/`Regulation` nodes that the LLM lifted verbatim from the reports:
GRI appears as ≥4 spellings ("GRI Standards", "GRI Standard", "Global Reporting Initiative (GRI)",
…), TT96 as a Vietnamese and an English form, and one document (the SSC-IFC disclosure guide)
even lands under two different classes. Without a canonical anchor, entity resolution leaves them
scattered and the indicator axis (step05c) has several nodes to hang `partOf` off instead of one.

WHAT IT PRODUCES
config/standards_registry.json, keyed by a short document KEY (TT96, QD2171, QCVN09, SSCIFC, GRI):
  { "TT96": {
      "canonical_name": "Thông tư 96/2020/TT-BTC",
      "kind": "Regulation",
      "aliases": ["Thông tư 96/2020/TT-BTC", "Circular 96/2020/TT-BTC", ...],
      "exclusions": [{"name": "...", "reason": "..."}],
      "needs_review": [{"name": "...", "normalized": "...", "degree": 3, "suggest": "include|exclude"}]
  }, ... }

Only the five documents that make up the indicator vocabulary are canonicalized. Everything else
in the graph (accounting standards, tax circulars, ISO certificates) is intentionally left as-is:
those are real, distinct references that the indicator axis has no opinion about.

Re-running preserves human edits (merge_preserving_edits, shared via esg_kg.core.naming);
--force rebuilds.

Run from the repo root, after step04 (issuer) and before step05 (entities):
  python src_module/run.py standards                 # draft, then hand-confirm needs_review
  python src_module/run.py standards --force         # discard edits, rebuild
Equivalently, from inside src_module/:  python -m esg_kg.registry.standards

Moved verbatim from src/step04b_build_standards_registry.py (Model A: that file still
exists and still runs). Only the docstring and the import block differ — the logic below
is unchanged, and test/test_esg_kg_equivalence.py runs both trees over the real resolved
graph and compares the written registries to keep it that way.
"""

import argparse
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from esg_kg.core.naming import merge_preserving_edits, normalize_name
from esg_kg.core.paths import REPO_ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_OUTPUT = REPO_ROOT / "config" / "standards_registry.json"

# The five reference documents behind kpi_definitions_construction.json, each with the spellings
# actually observed in the AAA graph plus a regex that recognises further variants. `kind` is the
# schema class step05c will point `partOf` at. QD2171/QCVN09 have no mentions in AAA yet — they are
# seeded so a company that DOES cite them resolves onto the same canonical node.
SEEDS: List[Dict[str, Any]] = [
    {
        "key": "TT96", "kind": "Regulation",
        "canonical_name": "Thông tư 96/2020/TT-BTC",
        "seed_aliases": ["Thông tư 96/2020/TT-BTC", "Circular 96/2020/TT-BTC"],
        "match_re": r"96\s*/\s*2020",
    },
    {
        "key": "GRI", "kind": "Standard",
        "canonical_name": "GRI Standards",
        "seed_aliases": ["GRI Standards", "GRI Standard", "GRI Sustainability Reporting Standards",
                         "Global Reporting Initiative", "Global Reporting Initiative (GRI)"],
        "match_re": r"\bgri\b|global reporting",
    },
    {
        "key": "SSCIFC", "kind": "Standard",
        "canonical_name": "Sổ tay hướng dẫn công bố thông tin ESG (SSC-IFC)",
        "seed_aliases": ["Hướng dẫn công bố thông tin về Môi trường & Xã hội"],
        "match_re": r"cong bo thong tin.*moi truong|ssc|\bifc\b",
    },
    {
        "key": "QD2171", "kind": "Regulation",
        "canonical_name": "Quyết định 2171/QĐ-BXD",
        "seed_aliases": ["Quyết định 2171/QĐ-BXD"],
        "match_re": r"2171",
    },
    {
        "key": "QCVN09", "kind": "Standard",
        "canonical_name": "QCVN 09:2017/BXD",
        "seed_aliases": ["QCVN 09:2017/BXD"],
        "match_re": r"qcvn\s*09|09\s*:\s*2017",
    },
]

# Normalized substrings that betray a *different* document sharing a keyword — kept out so a
# blunt regex never sweeps in an accounting standard or a tax circular.
EXCLUDE_HINTS = {
    "TT96": ["200/2014", "202/2014", "155/2015", "244/2009", "ke toan", "kiem toan"],
    "GRI": [],
    "SSCIFC": ["kiem toan"],
    "QD2171": ["15/2006"],
    "QCVN09": [],
}


def build(input_file: Path, output_file: Path, force: bool, min_degree: int) -> None:
    graph = json.loads(input_file.read_text(encoding="utf-8"))
    nodes = graph.get("nodes", [])

    # degree per node index → surfaced in needs_review so a human sees how load-bearing a mention is
    degree: Counter = Counter()
    for e in graph.get("edges", []):
        degree[e["subject"]] += 1
        degree[e["object"]] += 1

    mentions: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if n.get("class") in ("Standard", "Regulation"):
            name = str((n.get("properties") or {}).get("name") or "").strip()
            if name:
                mentions.append({"name": name, "norm": normalize_name(name),
                                 "class": n["class"], "degree": degree[i]})

    fresh: Dict[str, Any] = {}
    claimed: set = set()  # normalized names already claimed, so one mention serves one document
    for seed in SEEDS:
        key = seed["key"]
        seed_norm = {normalize_name(a) for a in seed["seed_aliases"]}
        rx = re.compile(seed["match_re"], re.IGNORECASE)
        excl_hints = EXCLUDE_HINTS.get(key, [])

        aliases: set = set(seed["seed_aliases"])
        exclusions: List[Dict[str, Any]] = []
        review: List[Dict[str, Any]] = []

        for m in mentions:
            if m["norm"] in claimed:
                continue
            hit_seed = m["norm"] in seed_norm
            hit_rx = bool(rx.search(m["name"]) or rx.search(m["norm"]))
            if not (hit_seed or hit_rx):
                continue

            bad = next((h for h in excl_hints if h in m["norm"]), None)
            if bad:
                exclusions.append({"name": m["name"], "reason": f"matched exclude hint '{bad}'"})
                claimed.add(m["norm"])
                continue

            if hit_seed:
                aliases.add(m["name"])          # exact seed spelling — trusted
                claimed.add(m["norm"])
            else:
                # regex-only hit → let a human confirm; suggest by how connected it is
                review.append({"name": m["name"], "normalized": m["norm"],
                               "class": m["class"], "degree": m["degree"],
                               "suggest": "include" if m["degree"] >= min_degree else "exclude"})

        fresh[key] = {
            "canonical_name": seed["canonical_name"],
            "kind": seed["kind"],
            "aliases": sorted(aliases),
            "exclusions": sorted(exclusions, key=lambda e: e["name"]),
            "needs_review": sorted(review, key=lambda r: -r["degree"]),
        }

    # merge with any existing hand-edited registry (reuse step04's logic; it ignores keys it
    # doesn't recognise like `kind`, so re-attach those from `fresh`)
    existing: Dict[str, Any] = {}
    if output_file.exists() and not force:
        try:
            existing = json.loads(output_file.read_text(encoding="utf-8"))
            logger.info(f"Found existing registry with {len(existing)} document(s); preserving edits.")
        except Exception as e:
            logger.warning(f"Could not read existing registry ({e}); rebuilding.")

    registry: Dict[str, Any] = {}
    for key, new in fresh.items():
        if key in existing:
            # merge_preserving_edits works on ticker-shaped dicts; give it the fields it expects.
            shaped_new = {"ticker": key, "canonical_name": new["canonical_name"],
                          "core_tokens": [], "aliases": new["aliases"],
                          "exclusions": new["exclusions"], "needs_review": new["needs_review"]}
            shaped_old = dict(existing[key])
            shaped_old.setdefault("ticker", key)
            merged = merge_preserving_edits(shaped_old, shaped_new)
            merged.pop("ticker", None)
            merged.pop("core_tokens", None)
            merged["kind"] = new["kind"]
            registry[key] = merged
        else:
            registry[key] = new

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {output_file}")
    for key, entry in registry.items():
        logger.info(f"  {key}: {len(entry['aliases'])} alias(es), "
                    f"{len(entry['exclusions'])} exclusion(s), "
                    f"{len(entry['needs_review'])} to review")
    if any(entry["needs_review"] for entry in registry.values()):
        logger.info("⚠ Some names need review — open the registry, move each needs_review entry "
                    "into 'aliases' or 'exclusions', then run step05.")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Bootstrap the canonical standards/regulations registry (run-once, no LLM).")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT,
                   help="Resolved graph JSON to scan for mentions.")
    p.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="Registry output path.")
    p.add_argument("--min-degree", type=int, default=2,
                   help="Degree at/above which a regex-only mention is suggested 'include'.")
    p.add_argument("--force", action="store_true", help="Rebuild from scratch, discarding edits.")
    args = p.parse_args()
    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run step05_resolve_entities.py first)")
        return
    build(args.input, args.output, args.force, args.min_degree)


if __name__ == "__main__":
    main()
