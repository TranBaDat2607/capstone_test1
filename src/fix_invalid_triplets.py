#!/usr/bin/env python3
"""
Validate and repair the temporal-graph triples produced by
`extract_triplet_from_jsonl.py`, mirroring EmeraldMind/src/EmeraldKG/3-fix-invalid-triplet.py
with three adaptations:

  * single GEMINI_API_KEY client (instead of the GEMINI_API_KEY_1..7 pool).
  * phase-2 LLM batches go through the same RateLimiter we use in step 2
    (default 10 RPM, configurable via --rate-limit), instead of a fixed
    time.sleep(1) between batches.
  * aggregated outputs land in graph_output/validated/ (a sibling of the
    per-page graph dir), not inside the input dir.

Pipeline:
  Phase 1 (offline):
    - recursively load every page*.json under --input-dir
    - reconstruct triples from {nodes, edges} graphs, or read raw triple arrays
    - auto-fix triples whose subject/object are swapped vs the schema's
      declared (source_class, target_class) for that edge label
    - full schema validation -> split into valid + invalid
  Phase 2 (LLM, optional):
    - batch invalid triples (default 25 per batch)
    - ask gemini-2.5-flash to repair them against the schema
    - re-validate the repaired triples; keep what's now valid
    - drop the rest into unfixable_triples.json
  Phase 3:
    - write graph_output/validated/all_validated_triples.json
    - write graph_output/validated/unfixable_triples.json (if any)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv
from google import genai

# Reuse helpers from earlier pipeline steps. When run as `python src/fix_invalid_triplets.py`
# Python adds src/ to sys.path automatically.
from extract_kpi_from_jsonl import REPO_ROOT
from extract_triplet_from_jsonl import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)


DEFAULT_INPUT_DIR = REPO_ROOT / "graph_output" / "graphs"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "validated"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_BATCH_SIZE = 25
DEFAULT_RATE_LIMIT = 10


# --------------------------------------------------------------------------- #
# Schema introspection.
# --------------------------------------------------------------------------- #
def load_schema_sets(schema: Dict[str, Any]) -> Tuple[Set[str], Set[str], Dict[str, List[Tuple[str, str]]]]:
    """Return (entity classes, edge labels, edge_directions).

    edge_directions: { label -> [(source_class, target_class), ...] }.
    One label may have multiple legal directed pairs (e.g. `verifiedBy` is legal
    from SustainabilityClaim to either ThirdPartyVerification or KPIObservation).
    """
    entity_classes = {node["class"] for node in schema.get("nodes", [])}
    edge_labels = {edge["label"] for edge in schema.get("edges", [])}
    edge_directions: Dict[str, List[Tuple[str, str]]] = {}
    for edge in schema.get("edges", []):
        label = edge["label"]
        from_cls = edge.get("source_class")
        to_cls = edge.get("target_class")
        edge_directions.setdefault(label, [])
        if from_cls and to_cls:
            edge_directions[label].append((from_cls, to_cls))
    logger.info(f"Loaded {len(edge_directions)} edge direction rules")
    return entity_classes, edge_labels, edge_directions


# --------------------------------------------------------------------------- #
# File loading: handle both graph format (step-2 page{N}.json) and raw
# triple-array format (step-2 page{N}_bugged.json).
# --------------------------------------------------------------------------- #
def load_triples_from_file(file_path: pathlib.Path) -> Tuple[List[Dict[str, Any]], str]:
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))

        if isinstance(data, dict) and "nodes" in data and "edges" in data:
            nodes = data["nodes"]
            triples: List[Dict[str, Any]] = []
            for edge in data["edges"]:
                if not isinstance(edge, dict):
                    continue
                subj_idx = edge.get("subject")
                obj_idx = edge.get("object")
                pred = edge.get("predicate")
                if subj_idx is None or obj_idx is None or not pred:
                    continue
                if not (0 <= subj_idx < len(nodes)) or not (0 <= obj_idx < len(nodes)):
                    logger.warning(f"Invalid node index in {file_path.name}")
                    continue
                triple = {
                    "subject": {
                        "class": nodes[subj_idx].get("class"),
                        "properties": nodes[subj_idx].get("properties", {}),
                    },
                    "predicate": pred,
                    "object": {
                        "class": nodes[obj_idx].get("class"),
                        "properties": nodes[obj_idx].get("properties", {}),
                    },
                }
                if "temporal_metadata" in edge:
                    triple["temporal_metadata"] = edge["temporal_metadata"]
                triples.append(triple)
            return triples, "graph"

        if isinstance(data, list):
            valid_triples: List[Dict[str, Any]] = []
            for i, triple in enumerate(data):
                if not isinstance(triple, dict):
                    logger.warning(f"{file_path.name}: skipping non-dict triple at index {i}")
                    continue
                if not triple.get("subject") or not triple.get("object") or not triple.get("predicate"):
                    logger.warning(f"{file_path.name}: skipping triple with missing fields at index {i}")
                    continue
                valid_triples.append(triple)
            if len(valid_triples) < len(data):
                logger.info(f"{file_path.name}: filtered {len(data) - len(valid_triples)} malformed triples")
            return valid_triples, "triple_array"

        logger.warning(f"{file_path.name}: unexpected format")
        return [], "unknown"
    except Exception as e:
        logger.error(f"Error loading {file_path.name}: {e}")
        return [], "error"


# --------------------------------------------------------------------------- #
# Offline direction fix: if (subj.class, obj.class) is not a legal pair for
# this predicate but (obj.class, subj.class) is, swap them.
# --------------------------------------------------------------------------- #
def fix_direction(triple: Dict[str, Any],
                  edge_directions: Dict[str, List[Tuple[str, str]]]) -> Tuple[Dict[str, Any], bool]:
    pred = triple.get("predicate")
    subj = triple.get("subject") or {}
    obj = triple.get("object") or {}
    subj_class = subj.get("class") if isinstance(subj, dict) else None
    obj_class = obj.get("class") if isinstance(obj, dict) else None
    if not pred or not subj_class or not obj_class:
        return triple, False
    if pred not in edge_directions:
        return triple, False

    pairs = edge_directions[pred]
    if any(s == subj_class and t == obj_class for s, t in pairs):
        return triple, False
    if any(s == obj_class and t == subj_class for s, t in pairs):
        fixed: Dict[str, Any] = {"subject": obj, "predicate": pred, "object": subj}
        if "temporal_metadata" in triple:
            fixed["temporal_metadata"] = triple["temporal_metadata"]
        return fixed, True
    return triple, False


# --------------------------------------------------------------------------- #
# Full per-triple schema validation.
# --------------------------------------------------------------------------- #
def validate_triple(triple: Dict[str, Any], entity_classes: Set[str], edge_labels: Set[str],
                    edge_directions: Dict[str, List[Tuple[str, str]]]) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    if not isinstance(triple, dict):
        return False, ["Not a dict"]
    if not {"subject", "predicate", "object"}.issubset(triple.keys()):
        return False, ["Missing required keys (subject/predicate/object)"]

    subj = triple.get("subject")
    if subj is None:
        errors.append("Subject is None")
    elif not isinstance(subj, dict):
        errors.append("Subject not a dict")
    elif "class" not in subj or "properties" not in subj:
        errors.append("Subject missing class or properties")
    elif subj["class"] not in entity_classes:
        errors.append(f"Invalid subject class: {subj.get('class')}")
    elif not isinstance(subj["properties"], dict):
        errors.append("Subject properties not a dict")
    else:
        props = subj["properties"]
        for k in ("valid_from", "valid_to", "is_current"):
            if k not in props:
                errors.append(f"Subject missing {k}")

    obj = triple.get("object")
    if obj is None:
        errors.append("Object is None")
    elif not isinstance(obj, dict):
        errors.append("Object not a dict")
    elif "class" not in obj or "properties" not in obj:
        errors.append("Object missing class or properties")
    elif obj["class"] not in entity_classes:
        errors.append(f"Invalid object class: {obj.get('class')}")
    elif not isinstance(obj["properties"], dict):
        errors.append("Object properties not a dict")
    else:
        props = obj["properties"]
        for k in ("valid_from", "valid_to", "is_current"):
            if k not in props:
                errors.append(f"Object missing {k}")

    pred = triple.get("predicate")
    if not isinstance(pred, str):
        errors.append("Predicate not a string")
    elif pred not in edge_labels:
        errors.append(f"Invalid predicate: {pred}")
    elif isinstance(subj, dict) and isinstance(obj, dict) and subj.get("class") and obj.get("class"):
        pairs = edge_directions.get(pred, [])
        if pairs and not any(s == subj["class"] and t == obj["class"] for s, t in pairs):
            errors.append(f"Invalid direction: {subj['class']} -{pred}-> {obj['class']}")

    if "temporal_metadata" not in triple:
        errors.append("Missing temporal_metadata")
    else:
        tm = triple["temporal_metadata"]
        if not isinstance(tm, dict):
            errors.append("temporal_metadata not a dict")
        else:
            for k in ("valid_from", "valid_to", "recorded_at"):
                if k not in tm:
                    errors.append(f"temporal_metadata missing {k}")

    return len(errors) == 0, errors


# --------------------------------------------------------------------------- #
# Phase 1: per-file offline processing.
# --------------------------------------------------------------------------- #
def process_file_offline(file_path: pathlib.Path, entity_classes: Set[str],
                         edge_labels: Set[str], edge_directions: Dict[str, List[Tuple[str, str]]]
                         ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int], str]:
    stats = {"total": 0, "direction_fixed": 0, "valid": 0, "invalid": 0}
    triples, format_type = load_triples_from_file(file_path)
    stats["total"] = len(triples)
    if not triples:
        return [], [], stats, format_type

    fixed_triples: List[Dict[str, Any]] = []
    for triple in triples:
        fixed, was_fixed = fix_direction(triple, edge_directions)
        if was_fixed:
            stats["direction_fixed"] += 1
        fixed_triples.append(fixed)

    valid: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []
    for triple in fixed_triples:
        is_valid, errors = validate_triple(triple, entity_classes, edge_labels, edge_directions)
        if is_valid:
            valid.append(triple)
            stats["valid"] += 1
        else:
            triple["_validation_errors"] = errors
            triple["_source_file"] = str(file_path)
            invalid.append(triple)
            stats["invalid"] += 1

    return valid, invalid, stats, format_type


# --------------------------------------------------------------------------- #
# Phase 2: LLM repair (verbatim prompt from EmeraldMind step 3).
# --------------------------------------------------------------------------- #
BATCH_FIX_PROMPT = (
    "You are fixing invalid ESG knowledge graph triples to match a schema.\n\n"
    "## VALIDATION RULES\n"
    "1. **Fix typos/synonyms**: Correct class names and predicates to match schema exactly\n"
    "2. **Add missing temporal properties**: Ensure all nodes have valid_from, valid_to, is_current\n"
    "3. **Add missing edge metadata**: Ensure all edges have temporal_metadata\n"
    "4. **Schema compliance**:\n"
    "   - predicate must be in edge labels\n"
    "   - subject.class & object.class must be in entity classes\n"
    "5. **Discard unfixable**: If triple cannot be corrected, omit it from output\n\n"
    "## TEMPORAL PROPERTIES (REQUIRED)\n"
    "All nodes MUST have:\n"
    "- valid_from: When information became valid (YYYY or YYYY-MM-DD)\n"
    "- valid_to: When superseded (null if current)\n"
    "- is_current: Boolean\n\n"
    "All edges MUST have temporal_metadata:\n"
    "- valid_from, valid_to, recorded_at\n\n"
    "## COMMON FIXES\n"
    "- Missing temporal properties: Use context year as valid_from\n"
    "- Typo in class/predicate: Match to closest schema term\n"
    "- Missing temporal_metadata: Create with reasonable defaults\n\n"
    "SCHEMA:\n"
    "{schema_json}\n\n"
    "OUTPUT FORMAT:\n"
    "Return JSON array of valid triples in the SAME ORDER as input.\n"
    "For unfixable triples, return null in that position.\n\n"
    "Output ONLY valid JSON - no markdown, no prose.\n\n"
    "INVALID TRIPLES TO FIX:\n"
)


def extract_json_from_response(response_text: str) -> List[Any]:
    text = response_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```\s*$", "", text, flags=re.MULTILINE).strip()
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    start = text.find("[")
    end = text.rfind("]") + 1
    if start != -1 and end > start:
        text = text[start:end]
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode failed: {e}")
    return []


def fix_batch_with_llm(batch: List[Dict[str, Any]], schema: Dict[str, Any],
                       client: genai.Client, rate_limiter: RateLimiter, model: str) -> List[Dict[str, Any]]:
    if not batch:
        return []
    clean_batch = [{k: v for k, v in t.items() if not k.startswith("_")} for t in batch]
    prompt = BATCH_FIX_PROMPT.format(
        schema_json=json.dumps(schema, indent=2, ensure_ascii=False)
    ) + json.dumps(clean_batch, indent=2, ensure_ascii=False)

    try:
        rate_limiter.wait_if_needed(0)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"temperature": 0, "response_mime_type": "application/json"},
        )
        fixed = extract_json_from_response(response.text or "")
        if isinstance(fixed, list):
            return [t for t in fixed if t is not None]
        return []
    except Exception as e:
        logger.error(f"LLM fix failed: {e}")
        return []


# --------------------------------------------------------------------------- #
# Phases 1-3 driver.
# --------------------------------------------------------------------------- #
def process_all_files(input_dir: pathlib.Path, out_dir: pathlib.Path, schema: Dict[str, Any],
                      entity_classes: Set[str], edge_labels: Set[str],
                      edge_directions: Dict[str, List[Tuple[str, str]]],
                      client: Optional[genai.Client], rate_limiter: RateLimiter,
                      model: str, batch_size: int, dry_run: bool) -> None:
    graph_files = list(input_dir.rglob("page*.json"))

    # Defensive: skip anything that lives inside our own out_dir.
    try:
        out_resolved = out_dir.resolve()
    except Exception:
        out_resolved = out_dir
    graph_files = [f for f in graph_files if out_resolved not in f.resolve().parents]

    normal_files = [
        f for f in graph_files
        if not any(s in f.stem for s in ("_validated", "_bugged", "_fixed", "_unfixable", "_malformed"))
    ]
    bugged_files = [
        f for f in graph_files
        if "_bugged" in f.stem
        and not any(s in f.stem for s in ("_validated", "_fixed", "_unfixable", "_malformed"))
    ]
    all_files = normal_files + bugged_files
    if not all_files:
        logger.warning(f"No page*.json files found under {input_dir}")
        return

    logger.info(f"Found {len(normal_files)} normal + {len(bugged_files)} bugged files = {len(all_files)} total")

    logger.info("=== Phase 1: Offline processing ===")
    all_valid: List[Dict[str, Any]] = []
    all_invalid: List[Dict[str, Any]] = []
    total_stats: Dict[str, int] = defaultdict(int)
    format_counts: Dict[str, int] = defaultdict(int)
    for fp in all_files:
        valid, invalid, stats, format_type = process_file_offline(fp, entity_classes, edge_labels, edge_directions)
        all_valid.extend(valid)
        all_invalid.extend(invalid)
        format_counts[format_type] += 1
        for k, v in stats.items():
            total_stats[k] += v
        if stats["direction_fixed"] > 0:
            logger.info(f"  {fp.name}: fixed {stats['direction_fixed']} direction(s) offline")

    logger.info(
        "\nOffline results:\n"
        f"  Total files: {len(all_files)} (graph: {format_counts['graph']}, triple_array: {format_counts['triple_array']})\n"
        f"  Total triples: {total_stats['total']}\n"
        f"  Direction fixed: {total_stats['direction_fixed']}\n"
        f"  Valid: {total_stats['valid']}\n"
        f"  Invalid (need LLM): {total_stats['invalid']}"
    )

    fixed_triples: List[Dict[str, Any]] = []
    if all_invalid and not dry_run:
        if client is None:
            logger.error("LLM phase requested but GEMINI_API_KEY is not set; skipping phase 2")
        else:
            logger.info(f"\n=== Phase 2: LLM batch fixing ({len(all_invalid)} triples) ===")
            n_batches = (len(all_invalid) - 1) // batch_size + 1
            for i in range(0, len(all_invalid), batch_size):
                batch = all_invalid[i:i + batch_size]
                logger.info(f"Batch {i // batch_size + 1}/{n_batches} ({len(batch)} triples)")
                fixed_batch = fix_batch_with_llm(batch, schema, client, rate_limiter, model)
                for triple in fixed_batch:
                    is_valid, _ = validate_triple(triple, entity_classes, edge_labels, edge_directions)
                    if is_valid:
                        fixed_triples.append(triple)
                logger.info(f"  Batch result: {len(fixed_batch)} returned, "
                            f"{sum(1 for t in fixed_batch if validate_triple(t, entity_classes, edge_labels, edge_directions)[0])} validated")
            logger.info(f"\nLLM fixed: {len(fixed_triples)}/{len(all_invalid)} triples")
            all_valid.extend(fixed_triples)
    elif all_invalid and dry_run:
        logger.info(f"\n=== Phase 2: SKIPPED (--dry-run) — would have sent {len(all_invalid)} invalid triples ===")

    logger.info("\n=== Phase 3: Saving results ===")
    if dry_run:
        logger.info("Dry run — not writing any files.")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "all_validated_triples.json"
        out_file.write_text(json.dumps(all_valid, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Saved {len(all_valid)} valid triples to {out_file}")

        unfixable = [t for t in all_invalid if t not in fixed_triples]
        if unfixable:
            uf_file = out_dir / "unfixable_triples.json"
            uf_file.write_text(json.dumps(unfixable, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Saved {len(unfixable)} unfixable triples to {uf_file}")

    total = total_stats["total"]
    success_rate = f"{len(all_valid) / total * 100:.1f}%" if total > 0 else "N/A"
    unfixable_count = total_stats["invalid"] - len(fixed_triples)
    logger.info(
        "\n=== Final summary ===\n"
        f"Total input files: {len(all_files)} (normal: {len(normal_files)}, bugged: {len(bugged_files)})\n"
        f"Total input triples: {total}\n"
        f"Direction fixed offline: {total_stats['direction_fixed']}\n"
        f"Initially valid: {total_stats['valid']}\n"
        f"Fixed by LLM: {len(fixed_triples)}\n"
        f"Final valid triples: {len(all_valid)}\n"
        f"Unfixable: {unfixable_count}\n"
        f"Success rate: {success_rate}"
    )


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate + fix ESG temporal-graph triples (step 2 output) against the schema."
    )
    parser.add_argument("-i", "--input-dir", type=pathlib.Path, default=DEFAULT_INPUT_DIR,
                        help="Directory containing graph JSON files (recursively)")
    parser.add_argument("-s", "--schema", type=pathlib.Path, default=DEFAULT_SCHEMA, help="Graph schema JSON")
    parser.add_argument("-o", "--out-dir", type=pathlib.Path, default=DEFAULT_OUT_DIR,
                        help="Output directory for aggregated results")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="Triples per LLM repair batch")
    parser.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT,
                        help="Max RPM for the LLM phase")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Gemini model id")
    parser.add_argument("--dry-run", action="store_true",
                        help="Stop after phase 1: report counts but don't call the LLM or write files")
    args = parser.parse_args()

    if not args.input_dir.exists():
        logger.error(f"Input directory not found: {args.input_dir}")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return

    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        entity_classes, edge_labels, edge_directions = load_schema_sets(schema)
        logger.info(f"Loaded schema: {len(entity_classes)} entities, {len(edge_labels)} edges")
    except Exception as e:
        logger.error(f"Failed to load schema: {e}")
        return

    client: Optional[genai.Client] = None
    if not args.dry_run:
        load_dotenv(REPO_ROOT / ".env")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error(f"GEMINI_API_KEY not set in {REPO_ROOT / '.env'}; use --dry-run to skip phase 2")
            return
        client = genai.Client(api_key=api_key)

    rate_limiter = RateLimiter(max_calls_per_minute=args.rate_limit)

    process_all_files(
        args.input_dir, args.out_dir, schema,
        entity_classes, edge_labels, edge_directions,
        client, rate_limiter, args.model, args.batch_size, args.dry_run,
    )


if __name__ == "__main__":
    main()
