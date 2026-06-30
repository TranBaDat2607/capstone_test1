#!/usr/bin/env python3
"""
Bootstrap a *canonical issuer registry* for the entity-resolution step.

Step 4 (`resolve_entities.py`) needs to merge every name variant of the
*reporting company* (the issuer) into one node deterministically — never via
embeddings or an LLM, because the issuer is the backbone of the greenwashing
cross-check. The trouble: in `all_validated_triples.json` the issuer appears
under its current name, its pre-rename name, the bare ticker, and many English
forms, while look-alikes (a parent holding company, subsidiaries) share part of
the name but are *different* legal entities.

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

Output: `config/issuer_registry.json`, consumed by `resolve_entities.py`.

`normalize_name` is defined here and imported by the resolver so both sides
match identically. Run from the repo root: `python src/build_issuer_registry.py`.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pandas as pd

# Reuse step-1 helpers (src/ is on sys.path when run as `python src/...`).
from extract_kpi_from_jsonl import REPO_ROOT

# Report files are named "<TICKER>_Baocaothuongnien_<YEAR>"; the ticker is the
# corpus issuer. We read it from KPI source_ids, which carry that stem.
REPORT_STEM_RE = re.compile(r"^([A-Za-z0-9]{2,5})_Baocaothuongnien", re.IGNORECASE)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "validated" / "all_validated_triples.json"
DEFAULT_COMPANIES = REPO_ROOT / "config" / "company_annual_report.xlsx"
DEFAULT_OUTPUT = REPO_ROOT / "config" / "issuer_registry.json"
DEFAULT_MIN_SUBJECT_EDGES = 10

# Predicates whose *subject* is the company the report is about. A name that is
# frequently the subject of these is almost certainly the issuer.
ISSUER_PREDICATES = {
    "reportsKPI", "claims", "setsGoal", "ownsFacility", "holdsCertification",
    "subjectToRegulation", "adoptsStandard", "takesPartIn", "generatesEmission",
    "subjectToPenalty", "offsetsWith", "targetsScienceBased", "generatesWaste",
    "impactsCommunity", "publishesReport", "locatedIn",
}

# --------------------------------------------------------------------------- #
# Name normalization (shared with the resolver via import).
# --------------------------------------------------------------------------- #
# OCR / encoding artifacts seen in the PDF extraction (e.g. "MÔI TRƢỜNG"):
# map the broken codepoints to their nearest ASCII so they normalize cleanly.
OCR_FIXES = {"Ƣ": "U", "ƣ": "u", "ư": "u", "Ư": "U", "đ": "d", "Đ": "d"}

# Legal-form boilerplate stripped for blocking/matching (normalized, space-delimited;
# applied longest-first so "cong ty co phan" is removed before "cong ty").
LEGAL_FORMS = [
    "cong ty trach nhiem huu han", "tong cong ty", "cong ty co phan", "cong ty cp",
    "cong ty tnhh", "cong ty", "ctcp", "tnhh", "tap doan", "joint stock company",
    "joint stock", "corporation", "company", "co ltd", "ltd", "jsc", "j s c", "plc", "inc",
]

# Light bilingual / spelling canonicalization so an issuer's Vietnamese and English
# names share tokens (kept deliberately small to avoid over-merging).
SYNONYMS = {"green": "xanh", "plastics": "plastic"}

# Pure industry/filler tokens dropped when deriving an issuer's distinctive core.
GENERIC_TOKENS = {
    "nhua", "plastic", "vat", "lieu", "xay", "dung", "material", "materials",
    "industry", "industries", "viet", "nam", "vietnam", "san", "xuat", "the", "and",
}

# Tokens that mark a *different* entity in the same corporate family (parent /
# subsidiary). A name carrying one of these is routed to review, not auto-merged.
QUALIFIER_TOKENS = {
    "holdings", "yen", "bai", "khoang", "bao", "bi", "tien", "noi", "vinh",
    "thakhek", "hung", "anh", "duong",
}

# Known-separate entities seeded straight into exclusions (normalized substring -> note).
# Keys are specific normalized forms so they match the company, not any org that merely
# contains a common place name (e.g. "ha noi" would wrongly catch every Hanoi bank).
EXCLUDE_SEED = {
    "an phat holdings": "An Phát Holdings — parent group (ticker APH), a separate listed entity",
    "an tien": "An Tiến Industries (HII) — affiliate, separate listed entity",
    "nhua ha noi": "Nhựa Hà Nội (NHH) — affiliate, separate listed entity",
}


def normalize_name(s: Any) -> str:
    """Lowercase, de-OCR, strip diacritics + legal forms, canonicalize synonyms."""
    if not s:
        return ""
    s = str(s)
    for a, b in OCR_FIXES.items():
        s = s.replace(a, b)
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d")  # đ survives NFD
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = f" {s.strip()} "
    for phrase in sorted(LEGAL_FORMS, key=len, reverse=True):
        s = s.replace(f" {phrase} ", " ")
    for a, b in SYNONYMS.items():
        s = s.replace(f" {a} ", f" {b} ")
    return re.sub(r"\s+", " ", s).strip()


def name_tokens(s: Any) -> Set[str]:
    n = normalize_name(s)
    return set(n.split()) if n else set()


def issuer_core_tokens(official_name: str) -> Set[str]:
    """Distinctive tokens of the official name (drop pure industry/legal fillers)."""
    return {t for t in name_tokens(official_name) if t not in GENERIC_TOKENS}


# --------------------------------------------------------------------------- #
# Data loading.
# --------------------------------------------------------------------------- #
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
        # ticker from KPI provenance: source_id carries the "<TICKER>_Baocaothuongnien" stem
        for side in (subj, obj):
            if isinstance(side, dict) and side.get("class") == "KPIObservation":
                sid = side.get("properties", {}).get("source_id")
                m = REPORT_STEM_RE.match(str(sid)) if sid else None
                if m:
                    tickers.add(m.group(1).upper())
    return subj_counts, org_names, tickers


# --------------------------------------------------------------------------- #
# Classification.
# --------------------------------------------------------------------------- #
def classify_for_ticker(ticker: str, official_name: str, org_names: Set[str],
                        subj_counts: Counter, min_subject_edges: int) -> Dict[str, Any]:
    core = issuer_core_tokens(official_name)          # e.g. {an, phat, xanh}
    ticker_l = ticker.lower()
    aliases: List[str] = []
    exclusions: List[Dict[str, str]] = []
    needs_review: List[Dict[str, Any]] = []

    for name in sorted(org_names):
        norm = normalize_name(name)
        toks = set(norm.split())
        if not toks:
            continue
        edges = int(subj_counts.get(name, 0))
        shared = core & toks
        quals = toks & QUALIFIER_TOKENS

        # 0) seeded known-separate entities -> exclusions
        seed_note = next((note for sub, note in EXCLUDE_SEED.items() if sub in norm), None)
        if seed_note:
            exclusions.append({"name": name, "reason": seed_note})
            continue

        # 1) ticker shorthand ("AAA", "AAA Group", "AAA Corporation") -> alias
        if ticker_l in toks:
            aliases.append(name)
            continue

        # 2) confident variant: carries the full distinctive core, no competing qualifier
        if core and core.issubset(toks) and not quals:
            aliases.append(name)
            continue

        # 3) shares the surname core (>=2 core tokens) -> ambiguous, route to review
        if len(shared) >= 2:
            if quals:
                reason = f"shares issuer core {sorted(shared)} but qualifier {sorted(quals)} → likely related-but-separate entity"
                suggest = "exclude"
            elif edges >= min_subject_edges:
                reason = f"shares issuer core {sorted(shared)} and is subject of {edges} report edges → likely an issuer shorthand"
                suggest = "include"
            else:
                reason = f"shares issuer core {sorted(shared)} but weak structural support ({edges} report edges)"
                suggest = "exclude"
            needs_review.append({"name": name, "reason": reason,
                                 "subject_edges": edges, "suggest": suggest})

    # de-dup, keep most structurally-central aliases first
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


# --------------------------------------------------------------------------- #
# Merge with an existing (human-edited) registry.
# --------------------------------------------------------------------------- #
def merge_preserving_edits(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Keep human-confirmed aliases/exclusions; only (re)surface unseen names in needs_review."""
    confirmed_alias = set(old.get("aliases", []))
    confirmed_excl_names = {e["name"] for e in old.get("exclusions", [])}
    resolved = confirmed_alias | confirmed_excl_names

    merged_aliases = sorted(confirmed_alias | set(new["aliases"]))
    # union exclusions (old human notes win on name collision)
    excl_by_name = {e["name"]: e for e in new["exclusions"]}
    excl_by_name.update({e["name"]: e for e in old.get("exclusions", [])})

    review = [r for r in new["needs_review"]
              if r["name"] not in resolved and r["name"] not in merged_aliases]
    return {
        "ticker": new["ticker"],
        "canonical_name": old.get("canonical_name") or new["canonical_name"],
        "core_tokens": new["core_tokens"],
        "aliases": [a for a in merged_aliases if a not in excl_by_name],
        "exclusions": sorted(excl_by_name.values(), key=lambda e: e["name"]),
        "needs_review": review,
    }


def build(input_file: Path, companies_xlsx: Path, output_file: Path,
          min_subject_edges: int, force: bool) -> None:
    triples = json.loads(input_file.read_text(encoding="utf-8"))
    logger.info(f"Loaded {len(triples)} validated triples from {input_file.name}")
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
        fresh = classify_for_ticker(ticker, official, org_names, subj_counts, min_subject_edges)
        registry[ticker] = merge_preserving_edits(existing[ticker], fresh) if ticker in existing else fresh
        r = registry[ticker]
        logger.info(f"  {ticker} ({official}): {len(r['aliases'])} aliases, "
                    f"{len(r['exclusions'])} exclusions, {len(r['needs_review'])} need review")

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
    args = p.parse_args()

    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run fix_invalid_triplets.py first)")
        return
    if not args.companies.exists():
        logger.error(f"Company table not found: {args.companies}")
        return
    build(args.input, args.companies, args.output, args.min_subject_edges, args.force)


if __name__ == "__main__":
    main()
