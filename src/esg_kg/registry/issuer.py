#!/usr/bin/env python3
"""
Bootstrap a *canonical issuer registry* for the entity-resolution step.

Step 4 (`esg_kg.resolve.entities`, still `src/step05_resolve_entities.py` today) needs to
merge every name variant of the *reporting company* (the issuer) into one node
deterministically — never via embeddings or an LLM, because the issuer is the backbone of
the greenwashing cross-check. The trouble: in `all_validated_triples.json` the issuer
appears under its current name, its pre-rename name, the bare ticker, and many English
forms, while look-alikes (a parent holding company, subsidiaries) share part of the name
but are *different* legal entities.

This script auto-builds a draft registry from data already in the repo:

  * `config/company_annual_report.xlsx`  -> ticker -> official name
  * `graph_output/validated/all_validated_triples.json` -> the Organization name
    variants actually present, plus a structural signal (how often each name is
    the *subject* of report-type edges -> the issuer dominates these).

Each distinct Organization name is classified into:

  * aliases       — confident issuer variants (merge into the issuer)
  * exclusions    — known-separate entities (never merge into the issuer)
  * needs_review  — ambiguous; a human confirms include/exclude

Re-running preserves human edits: confirmed aliases/exclusions are kept; only
newly-seen names are (re)appended to needs_review. `--force` rebuilds fresh.

Output: `config/issuer_registry.json`, consumed by the entity resolver.

Extracted verbatim from `src/step04_build_issuer_registry.py` (DESIGN.md Model A — the
`src/` original keeps running untouched). `normalize_name` / `name_tokens` /
`merge_preserving_edits` are imported from `esg_kg.core.naming` rather than redefined:
that module already carries them (lifted during the step04b/step05 groundwork) because
`normalize_name` is the most load-bearing helper in the repo — step04 writes
`config/issuer_registry.json` with it and step05 re-derives the same keys when resolving
entities, so both sides must normalize identically or the frozen issuer anchor silently
stops matching. `issuer_core_tokens` / `GENERIC_TOKENS` stay here: nothing else imports
them, so they belong with the issuer registry builder, not in the shared kernel.

Run from the repo root: `python src/run.py issuer`.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pandas as pd

from esg_kg.core.naming import merge_preserving_edits, name_tokens, normalize_name
from esg_kg.core.paths import REPO_ROOT

REPORT_STEM_RE = re.compile(r"^([A-Za-z0-9]{2,5})_(?:Baocaothuongnien|\d{4})", re.IGNORECASE)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "validated" / "all_validated_triples.json"
DEFAULT_COMPANIES = REPO_ROOT / "config" / "company_annual_report.xlsx"
DEFAULT_OUTPUT = REPO_ROOT / "config" / "issuer_registry.json"
DEFAULT_MIN_SUBJECT_EDGES = 10

ISSUER_PREDICATES = {
    "reportsKPI", "claims", "setsGoal", "ownsFacility", "holdsCertification",
    "subjectToRegulation", "adoptsStandard", "takesPartIn", "generatesEmission",
    "subjectToPenalty", "offsetsWith", "targetsScienceBased", "generatesWaste",
    "impactsCommunity", "publishesReport", "locatedIn",
}

GENERIC_TOKENS = {
    "nhua", "plastic", "vat", "lieu", "xay", "dung", "material", "materials",
    "industry", "industries", "viet", "nam", "vietnam", "san", "xuat", "the", "and",
}

QUALIFIER_TOKENS = {
    "holdings", "yen", "bai", "khoang", "bao", "bi", "tien", "noi", "vinh",
    "thakhek", "hung", "anh", "duong",
}

EXCLUDE_SEED = {
    "an phat holdings": "An Phát Holdings — parent group (ticker APH), a separate listed entity",
    "an tien": "An Tiến Industries (HII) — affiliate, separate listed entity",
    "nhua ha noi": "Nhựa Hà Nội (NHH) — affiliate, separate listed entity",
}

RELATION_WEIGHTS: Dict[str, float] = {
    "subjectToPenalty": 3.0,
    "holdsCertification": 2.5,
    "reportsKPI": 2.0,
    "claims": 2.0,
    "setsGoal": 2.0,
    "adoptsStandard": 2.0,
    "targetsScienceBased": 2.0,
    "subjectToRegulation": 1.5,
    "ownsFacility": 1.5,
    "takesPartIn": 1.5,
    "generatesEmission": 1.5,
    "generatesWaste": 1.5,
    "offsetsWith": 1.5,
    "impactsCommunity": 1.5,
    "locatedIn": 1.0,
    "publishesReport": 1.0,
}

_SIGNATURES_CACHE: Dict[str, Set[Tuple[str, str]]] = {}


def issuer_core_tokens(official_name: str) -> Set[str]:
    """Distinctive tokens of the official name (drop pure industry/legal fillers)."""
    return {t for t in name_tokens(official_name) if t not in GENERIC_TOKENS}


def get_node_identifier(node: Any) -> str:
    """Helper to extract a stable, meaningful identifier string for any node."""
    if not isinstance(node, dict):
        return str(node).strip()
    props = node.get("properties", {})
    if not props:
        return ""
    for key in ["name", "kpi_type", "title", "category", "claim_id", "verification_id", "project_id", "target_id", "controversy_id", "penalty_id", "report_id", "term"]:
        if key in props and props[key] is not None:
            val = str(props[key]).strip()
            if val:
                return val
    for val in props.values():
        if val is not None:
            val_str = str(val).strip()
            if val_str:
                return val_str
    return ""


def build_signatures_cache(triples: List[Dict[str, Any]]) -> None:
    """Populate the global signatures cache for all Organization names from the triples list."""
    global _SIGNATURES_CACHE
    _SIGNATURES_CACHE.clear()
    for t in triples:
        subj = t.get("subject")
        obj = t.get("object")
        pred = t.get("predicate")
        if not pred:
            continue

        pred_str = str(pred).strip()

        if isinstance(subj, dict) and subj.get("class") == "Organization":
            subj_name = str(subj.get("properties", {}).get("name", "")).strip()
            if subj_name:
                obj_val = get_node_identifier(obj)
                if obj_val:
                    _SIGNATURES_CACHE.setdefault(subj_name, set()).add((pred_str, obj_val))

        if isinstance(obj, dict) and obj.get("class") == "Organization":
            obj_name = str(obj.get("properties", {}).get("name", "")).strip()
            if obj_name:
                subj_val = get_node_identifier(subj)
                if subj_val:
                    _SIGNATURES_CACHE.setdefault(obj_name, set()).add((f"<-pred_str", subj_val))


def compute_graph_signature(name: str, triples: List[Dict[str, Any]]) -> Set[Tuple[str, str]]:
    """Build a graph signature for an Organization node based on its neighboring relations."""
    global _SIGNATURES_CACHE
    if not _SIGNATURES_CACHE:
        build_signatures_cache(triples)
    return _SIGNATURES_CACHE.get(name, set())


def graph_similarity(sig_a: Set[Tuple[str, str]], sig_b: Set[Tuple[str, str]]) -> float:
    """Compute the Weighted Jaccard Similarity between two graph signatures."""
    if not sig_a and not sig_b:
        return 0.0

    intersection = sig_a & sig_b
    union = sig_a | sig_b

    def get_weight(item: Tuple[str, str]) -> float:
        pred = item[0]
        clean_pred = pred.replace("<-", "")
        return RELATION_WEIGHTS.get(clean_pred, 1.0)

    intersection_weight = sum(get_weight(item) for item in intersection)
    union_weight = sum(get_weight(item) for item in union)

    if union_weight == 0.0:
        return 0.0
    return intersection_weight / union_weight


def load_ticker_official_names(xlsx: Path) -> Dict[str, str]:
    df = pd.read_excel(xlsx)
    df = df[["Mã CK", "Tên công ty"]].dropna(subset=["Mã CK"])
    mapping: Dict[str, str] = {}
    for _, row in df.iterrows():
        ticker = str(row["Mã CK"]).strip().upper()
        name = str(row["Tên công ty"]).strip()
        if ticker and name and name.lower() != "nan" and ticker not in mapping:
            mapping[ticker] = name
    return mapping


def collect_org_signals(triples: List[Dict[str, Any]]
                        ) -> Tuple[Counter, Set[str], Set[str]]:
    """Return (subject-of-issuer-edge counts per raw org name, all org names, corpus tickers)."""
    subj_counts: Counter = Counter()
    org_names: Set[str] = set()
    tickers: Set[str] = set()
    for t in triples:
        subj, obj, pred = t.get("subject"), t.get("object"), t.get("predicate")
        for side in (subj, obj):
            if isinstance(side, dict) and side.get("class") == "Organization":
                nm = str(side.get("properties", {}).get("name", "")).strip()
                if nm:
                    org_names.add(nm)
        if isinstance(subj, dict) and subj.get("class") == "Organization" and pred in ISSUER_PREDICATES:
            nm = str(subj.get("properties", {}).get("name", "")).strip()
            if nm:
                subj_counts[nm] += 1
        for side in (subj, obj):
            if isinstance(side, dict) and side.get("class") == "KPIObservation":
                sid = side.get("properties", {}).get("source_id")
                m = REPORT_STEM_RE.match(str(sid)) if sid else None
                if m:
                    tickers.add(m.group(1).upper())
    return subj_counts, org_names, tickers


def classify_for_ticker(ticker: str, official_name: str, org_names: Set[str],
                        subj_counts: Counter, min_subject_edges: int,
                        triples: List[Dict[str, Any]],
                        graph_sim_upper: float, graph_sim_lower: float) -> Dict[str, Any]:
    core = issuer_core_tokens(official_name)
    ticker_l = ticker.lower()
    aliases: List[str] = []
    exclusions: List[Dict[str, str]] = []
    needs_review: List[Dict[str, Any]] = []

    issuer_signature: Set[Tuple[str, str]] = set()
    issuer_signature.update(compute_graph_signature(official_name, triples))

    norm_official = normalize_name(official_name)
    for name in org_names:
        norm_name = normalize_name(name)
        if not norm_name:
            continue

        seed_note = next((note for sub, note in EXCLUDE_SEED.items() if sub in norm_name), None)
        if seed_note:
            continue

        if norm_name == ticker_l or norm_name == norm_official:
            issuer_signature.update(compute_graph_signature(name, triples))

    for name in sorted(org_names):
        norm = normalize_name(name)
        toks = set(norm.split())
        if not toks:
            continue
        edges = int(subj_counts.get(name, 0))
        shared = core & toks
        quals = toks & QUALIFIER_TOKENS

        seed_note = next((note for sub, note in EXCLUDE_SEED.items() if sub in norm), None)
        if seed_note:
            exclusions.append({"name": name, "reason": seed_note})
            continue

        if ticker_l in toks:
            aliases.append(name)
            continue

        if core and core.issubset(toks) and not quals:
            aliases.append(name)
            continue

        if len(shared) >= 2:
            if not issuer_signature:
                if quals:
                    reason = f"shares issuer core {sorted(shared)} but qualifier {sorted(quals)} → likely related-but-separate entity (no issuer signature)"
                    suggest = "exclude"
                elif edges >= min_subject_edges:
                    reason = f"shares issuer core {sorted(shared)} and is subject of {edges} report edges → likely an issuer shorthand (no issuer signature)"
                    suggest = "include"
                else:
                    reason = f"shares issuer core {sorted(shared)} but weak structural support ({edges} report edges) (no issuer signature)"
                    suggest = "exclude"
                needs_review.append({"name": name, "reason": reason,
                                     "subject_edges": edges, "suggest": suggest})
            else:
                name_signature = compute_graph_signature(name, triples)
                sim = graph_similarity(name_signature, issuer_signature)

                if sim > graph_sim_upper:
                    aliases.append(name)
                elif sim < graph_sim_lower:
                    reason = f"shares issuer core {sorted(shared)} but low graph similarity ({sim:.3f})"
                    if quals:
                        reason += f" and qualifier {sorted(quals)}"
                    exclusions.append({"name": name, "reason": reason})
                else:
                    reason = f"shares issuer core {sorted(shared)} and intermediate graph similarity ({sim:.3f})"
                    if quals:
                        reason += f" with qualifier {sorted(quals)}"
                    suggest = "include" if sim >= 0.5 else "exclude"
                    needs_review.append({"name": name, "reason": reason,
                                         "subject_edges": edges, "suggest": suggest})

    aliases = sorted(set(aliases), key=lambda n: (-int(subj_counts.get(n, 0)), n))
    needs_review.sort(key=lambda r: (-r["subject_edges"], r["name"]))
    return {
        "ticker": ticker,
        "canonical_name": official_name,
        "core_tokens": sorted(core),
        "aliases": aliases,
        "exclusions": exclusions,
        "needs_review": needs_review,
    }


def build(input_file: Path, companies_xlsx: Path, output_file: Path,
          min_subject_edges: int, force: bool,
          graph_sim_upper: float, graph_sim_lower: float) -> None:
    data = json.loads(input_file.read_text(encoding="utf-8"))
    triples = data

    logger.info(f"Loaded {len(triples)} validated triples from {input_file.name}")

    build_signatures_cache(triples)

    ticker_names = load_ticker_official_names(companies_xlsx)
    subj_counts, org_names, tickers = collect_org_signals(triples)
    logger.info(f"Distinct Organization names: {len(org_names)} | corpus tickers: {sorted(tickers) or '∅'}")

    if not tickers:
        logger.warning("No ticker detected from KPI source_ids; falling back to all xlsx tickers present in names.")
        tickers = set(ticker_names.keys())

    existing: Dict[str, Any] = {}
    if output_file.exists() and not force:
        try:
            existing = json.loads(output_file.read_text(encoding="utf-8"))
            logger.info(f"Found existing registry with {len(existing)} ticker(s); preserving human edits.")
        except Exception as e:
            logger.warning(f"Could not read existing registry ({e}); rebuilding.")

    registry: Dict[str, Any] = {}
    for ticker in sorted(tickers):
        official = ticker_names.get(ticker)
        if not official:
            logger.warning(f"  {ticker}: no official name in {companies_xlsx.name}; skipping")
            continue
        fresh = classify_for_ticker(ticker, official, org_names, subj_counts, min_subject_edges, triples, graph_sim_upper, graph_sim_lower)
        registry[ticker] = merge_preserving_edits(existing[ticker], fresh) if ticker in existing else fresh
        r = registry[ticker]
        logger.info(f"  {ticker} ({official}): {len(r['aliases'])} aliases, "
                    f"{len(r['exclusions'])} exclusions, {len(r['needs_review'])} need review")

    carried = sorted(t for t in existing if t not in registry)
    for ticker in carried:
        registry[ticker] = existing[ticker]
    if carried:
        logger.info(f"  carried forward {len(carried)} ticker(s) not rebuilt this run "
                    f"(untouched): {carried}")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {output_file}")
    if any(registry[t]["needs_review"] for t in registry):
        logger.info("⚠ Some names need review — open the registry and move each needs_review "
                    "entry into 'aliases' or 'exclusions', then re-run the resolver.")


def main() -> None:
    p = argparse.ArgumentParser(description="Bootstrap the canonical issuer registry for entity resolution.")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT, help="Validated triples JSON")
    p.add_argument("--companies", type=Path, default=DEFAULT_COMPANIES, help="ticker→name xlsx")
    p.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="Registry output path")
    p.add_argument("--min-subject-edges", type=int, default=DEFAULT_MIN_SUBJECT_EDGES,
                   help="Min subject-of-report-edge count to suggest 'include' for a partial-name match")
    p.add_argument("--force", action="store_true", help="Rebuild from scratch, discarding human edits")
    p.add_argument("--graph-sim-upper", type=float, default=0.8,
                   help="Graph similarity threshold above which ambiguous entities are auto-resolved as aliases")
    p.add_argument("--graph-sim-lower", type=float, default=0.2,
                   help="Graph similarity threshold below which ambiguous entities are auto-resolved as exclusions")
    args = p.parse_args()

    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run build_validated first)")
        return
    if not args.companies.exists():
        logger.error(f"Company table not found: {args.companies}")
        return
    build(args.input, args.companies, args.output, args.min_subject_edges, args.force, args.graph_sim_upper, args.graph_sim_lower)


if __name__ == "__main__":
    main()
