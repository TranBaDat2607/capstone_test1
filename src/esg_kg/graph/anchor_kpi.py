#!/usr/bin/env python3
"""
Step 3b — offline structural anchoring of leaf KPI observations (P3 in
docs/TEMPORAL_KG_DESIGN.md).

Principle P3 requires every T2 event node to be anchored to >= 2 T1 entities
whenever the source text allows. For NEW extractions that is handled by the
step02 prompt; this script patches the ALREADY-extracted (paid-for) data
offline, without any LLM:

  1. build a gazetteer of Facility names that already exist in the validated
     graph (graph_output/validated/all_validated_triples.json);
  2. for every KPIObservation, resolve its source sentence via `source_id`
     ("<source_pdf>_<page>_<sentence_index>") against the labeled JSONL corpora;
  3. if the sentence literally names a known facility (Vietnamese-normalized,
     word-bounded match), emit the schema edge the extractor should have made:
         KPIObservation --observedAtFacility--> Facility
     with the KPI's own event time as edge temporal_metadata and
     `anchor_method: "offline_gazetteer"` for auditability.

No new classes and no new edge labels are introduced — only edges the schema
already defines. Location names cannot be attached here because the schema has
no KPIObservation->Location edge (by design); Penalty->Authority (enforcedBy)
cannot be patched offline because Penalty nodes carry no sentence-level
source_id — both are covered going forward by the step02 prompt rules.

Run AFTER step03 and BEFORE step05 (the resolver merges the new edges into the
canonical graph), from the REPO ROOT:

    python src/run.py anchor_kpi --dry-run   # preview matches
    python src/run.py anchor_kpi             # append to validated triples

MIGRATED FROM ``src/step03b_anchor_kpi_facilities.py`` (2026-07-27), verbatim: this
file is that one with the docstring and the import block replaced, and with
``parse_source_id`` deleted rather than rewritten — it now lives in
``esg_kg.core.identity`` because ``step05b`` imports it too, and a stage must not
double as a utility library (DESIGN.md §1, same move as ``core/graph_patch.py``).
No logic line differs. Model A: the ``src/`` original keeps running untouched and
``test/test_esg_kg_anchor_kpi.py`` holds the two trees equal on the real corpus.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from esg_kg.core.identity import parse_source_id
from esg_kg.core.naming import normalize_name
from esg_kg.core.paths import REPO_ROOT
from esg_kg.core.schema import load_schema_sets, validate_triple

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_TRIPLES = REPO_ROOT / "graph_output" / "validated" / "all_validated_triples.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_STATS_OUT = REPO_ROOT / "graph_output" / "validated" / "anchor_patch_stats.json"
DEFAULT_SENTENCE_GLOBS = [
    "data/labeled/annual_labeled/*.jsonl",
    "data/labeled/news_labeled/*.jsonl",
    "data/interim/news_preprocessed/*.jsonl",
]
# Degree governance (P5): a gazetteer name that anchors half the corpus is a
# generic term, not a plant — refuse to mint a synthetic hub.
DEFAULT_MAX_PER_FACILITY = 150
MIN_NAME_CHARS = 10
MIN_NAME_TOKENS = 2
# Generic Vietnamese facility heads that survive the length gate but name nothing.
GENERIC_NAMES = {
    "nha may san xuat", "khu cong nghiep", "trung tam san xuat",
    "nha may che bien", "cum cong nghiep", "cac nha may san xuat",
    "cac nha may", "toa nha van phong",
}


# --------------------------------------------------------------------------- #
# Corpus sentences.
# --------------------------------------------------------------------------- #
def load_sentences(globs: List[str]) -> Dict[Tuple[str, int, int], str]:
    """(source_pdf, page, sentence_index) -> raw sentence text."""
    out: Dict[Tuple[str, int, int], str] = {}
    n_files = 0
    for pattern in globs:
        for path in sorted(REPO_ROOT.glob(pattern)):
            n_files += 1
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    src, page, idx = row.get("source_pdf"), row.get("page"), row.get("sentence_index")
                    if src is None or page is None or idx is None:
                        continue
                    out[(str(src), int(page), int(idx))] = row.get("text", "")
    logger.info(f"Loaded {len(out)} sentences from {n_files} JSONL file(s)")
    return out


# --------------------------------------------------------------------------- #
# Graph inventory.
# --------------------------------------------------------------------------- #
def prop_richness(props: Dict[str, Any]) -> int:
    return sum(1 for v in props.values() if v not in (None, ""))


def collect_inventory(triples: List[Dict[str, Any]]) -> Tuple[
        Dict[str, Dict[str, Any]],           # facility normalized name -> representative node
        Dict[str, Dict[str, Any]],           # kpi occurrence key -> {"node", "recorded_at"}
        Set[Tuple[str, str]]]:               # existing (kpi key, facility norm) anchors
    facilities: Dict[str, Dict[str, Any]] = {}
    kpis: Dict[str, Dict[str, Any]] = {}
    anchored: Set[Tuple[str, str]] = set()

    def kpi_key(props: Dict[str, Any]) -> str:
        return json.dumps(
            {k: props.get(k) for k in sorted(props)}, ensure_ascii=False, sort_keys=True)

    def visit_entity(ent: Dict[str, Any]) -> None:
        cls, props = ent.get("class"), ent.get("properties") or {}
        if cls == "Facility":
            norm = normalize_name(props.get("name", ""))
            if (len(norm) >= MIN_NAME_CHARS and len(norm.split()) >= MIN_NAME_TOKENS
                    and norm not in GENERIC_NAMES):
                cur = facilities.get(norm)
                if cur is None or prop_richness(props) > prop_richness(cur["properties"]):
                    facilities[norm] = {"class": "Facility", "properties": props}
        elif cls == "KPIObservation":
            k = kpi_key(props)
            if k not in kpis:
                kpis[k] = {"node": {"class": "KPIObservation", "properties": props},
                           "recorded_at": None}

    for t in triples:
        subj, obj = t.get("subject") or {}, t.get("object") or {}
        for ent in (subj, obj):
            if isinstance(ent, dict):
                visit_entity(ent)
        tm = t.get("temporal_metadata") or {}
        if t.get("predicate") == "reportsKPI" and isinstance(obj, dict) \
                and obj.get("class") == "KPIObservation":
            k = kpi_key(obj.get("properties") or {})
            if k in kpis and kpis[k]["recorded_at"] is None:
                kpis[k]["recorded_at"] = tm.get("recorded_at")
        if t.get("predicate") == "observedAtFacility" and isinstance(subj, dict) \
                and subj.get("class") == "KPIObservation" and isinstance(obj, dict):
            anchored.add((kpi_key(subj.get("properties") or {}),
                          normalize_name((obj.get("properties") or {}).get("name", ""))))

    logger.info(f"Inventory: {len(facilities)} usable facility names, "
                f"{len(kpis)} distinct KPI observations, {len(anchored)} existing anchors")
    return facilities, kpis, anchored


# --------------------------------------------------------------------------- #
# Matching + patch construction.
# --------------------------------------------------------------------------- #
def build_patch(triples: List[Dict[str, Any]], sentences: Dict[Tuple[str, int, int], str],
                schema: Dict[str, Any], max_per_facility: int
                ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    entity_classes, edge_labels, edge_directions = load_schema_sets(schema)
    facilities, kpis, anchored = collect_inventory(triples)

    def kpi_key(props: Dict[str, Any]) -> str:
        return json.dumps(
            {k: props.get(k) for k in sorted(props)}, ensure_ascii=False, sort_keys=True)

    candidates: List[Tuple[str, str]] = []  # (kpi key, facility norm)
    per_facility: Counter = Counter()
    no_sentence = 0
    for k, info in kpis.items():
        props = info["node"]["properties"]
        loc = parse_source_id(props.get("source_id"))
        if loc is None or loc not in sentences:
            no_sentence += 1
            continue
        norm_sentence = f" {normalize_name(sentences[loc])} "
        matched = [f for f in facilities if f" {f} " in norm_sentence]
        # Keep only maximal matches: "lo cn11 cn12" inside
        # "lo cn11 cn12 cum cong nghiep an dong" names the same place.
        matched = [f for f in matched
                   if not any(g != f and f" {f} " in f" {g} " for g in matched)]
        for fnorm in matched:
            if (k, fnorm) not in anchored:
                candidates.append((k, fnorm))
                per_facility[fnorm] += 1

    over_cap = {f for f, c in per_facility.items() if c > max_per_facility}
    for f in over_cap:
        logger.warning(f"Skipping facility {f!r}: {per_facility[f]} matches exceed "
                       f"--max-per-facility={max_per_facility} (likely a generic term)")

    new_triples: List[Dict[str, Any]] = []
    dropped_invalid = 0
    for k, fnorm in candidates:
        if fnorm in over_cap:
            continue
        info = kpis[k]
        kprops = info["node"]["properties"]
        triple = {
            "subject": {"class": "KPIObservation", "properties": kprops},
            "predicate": "observedAtFacility",
            "object": facilities[fnorm],
            "temporal_metadata": {
                "valid_from": kprops.get("valid_from"),
                "valid_to": kprops.get("valid_to"),
                "recorded_at": info["recorded_at"] or kprops.get("valid_from"),
            },
            "source_type": kprops.get("source_type", "report"),
            "anchor_method": "offline_gazetteer",
        }
        ok, errors = validate_triple(triple, entity_classes, edge_labels, edge_directions)
        if not ok:
            dropped_invalid += 1
            logger.warning(f"Dropping invalid anchor triple: {errors}")
            continue
        new_triples.append(triple)

    stats = {
        "kpi_observations": len(kpis),
        "kpi_without_resolvable_sentence": no_sentence,
        "facility_gazetteer_size": len(facilities),
        "raw_matches": len(candidates),
        "facilities_over_cap": sorted(over_cap),
        "dropped_invalid": dropped_invalid,
        "new_anchor_triples": len(new_triples),
        "matches_per_facility": {f: c for f, c in per_facility.most_common(25)},
    }
    return new_triples, stats


def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 3b — offline gazetteer anchoring of KPI observations to facilities (P3).")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_TRIPLES,
                   help="Aggregated validated triples (step03 output)")
    p.add_argument("-s", "--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--sentences", nargs="*", default=DEFAULT_SENTENCE_GLOBS,
                   help="Repo-relative globs of labeled JSONL files with source sentences")
    p.add_argument("--max-per-facility", type=int, default=DEFAULT_MAX_PER_FACILITY,
                   help="Skip facility names matching more KPI sentences than this (hub guard)")
    p.add_argument("--stats-out", type=Path, default=DEFAULT_STATS_OUT)
    p.add_argument("--dry-run", action="store_true",
                   help="Report matches without writing anything")
    args = p.parse_args()

    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run step03_fix_invalid_triplets.py first)")
        return
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    triples = json.loads(args.input.read_text(encoding="utf-8"))
    logger.info(f"Loaded {len(triples)} validated triples")

    sentences = load_sentences(args.sentences)
    new_triples, stats = build_patch(triples, sentences, schema, args.max_per_facility)

    logger.info("Anchor patch stats:\n" + json.dumps(stats, indent=2, ensure_ascii=False))
    if not new_triples:
        logger.info("No new anchor triples to add.")
        return
    for t in new_triples[:5]:
        kpi = t["subject"]["properties"]
        fac = t["object"]["properties"]
        logger.info(f"  sample: KPI {kpi.get('title')!r} --observedAtFacility--> {fac.get('name')!r}")

    if args.dry_run:
        logger.info(f"Dry run — would append {len(new_triples)} triples to {args.input}")
        return

    triples.extend(new_triples)
    args.input.write_text(json.dumps(triples, indent=2, ensure_ascii=False), encoding="utf-8")
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Appended {len(new_triples)} anchor triples to {args.input}; "
                f"stats -> {args.stats_out}")


if __name__ == "__main__":
    main()
