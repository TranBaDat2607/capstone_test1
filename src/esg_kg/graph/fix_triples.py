#!/usr/bin/env python3
"""
Step 3 — validate and repair the temporal-graph triples produced by step02.

  Phase 1 (offline):   reconstruct triples from the per-page {nodes, edges} graphs,
                       auto-swap subject/object where the schema declares the other
                       direction, then full schema validation -> valid + invalid.
  Phase 1.5 (offline): P4 in docs/TEMPORAL_KG_DESIGN.md — canonicalize every date to
                       ISO YYYY[-MM[-DD]], flag valid_from > valid_to, default a
                       missing date_uncertain on news T2 nodes.
                       `--renormalize` applies ONLY this phase to the existing
                       aggregated file (no LLM, keeps prior phase-2 repairs).
  Phase 2 (LLM):       batch the invalid triples and ask the model to repair them
                       against the schema; re-validate and keep what is now valid.
  Phase 3:             write all_validated_triples.json + unfixable_triples.json.

Run from the REPO ROOT:

    python src/run.py fix_triples --dry-run     # phase 1 only, no LLM, no writes
    python src/run.py fix_triples               # full run
    python src/run.py fix_triples --renormalize # P4 pass over the existing file

MIGRATED FROM ``src/step03_fix_invalid_triplets.py`` (2026-07-28), verbatim: this file
is that one with the docstring and the import block replaced, and with four helpers
DELETED rather than rewritten because they already live in the kernel —
``normalize_date_string`` / ``date_start_key`` (-> ``esg_kg.core.dates``) and
``load_schema_sets`` / ``validate_triple`` (-> ``esg_kg.core.schema``). No logic line
differs.

step03 LOOKED like a hub — seven src/ stages import from it — but every symbol they
take had already been lifted into ``core/`` by the earlier slices, and nobody imports
its stage-local functions. So this move needed no new kernel module, the second stage
after step05b to manage that.

``DEFAULT_RATE_LIMIT`` stays a module-local constant on purpose. ``core.llm`` exports
one too and both are 10 today, but importing it would tie this stage's throttle to
step02's; only ``RateLimiter`` itself is shared.

Model A: the ``src/`` original keeps running untouched, and
``test/test_esg_kg_fix_triples.py`` holds the two trees equal on the real corpus —
including phase 2, which is driven there by a stubbed LLM so the paid branch and its
``preserve_property_values`` guard are compared without spending anything.

2026-08-04: the additive ``--provider openai`` path (added 2026-07-29 while the Gemini
project behind GEMINI_API_KEY was billing-blocked) was removed outright — this project
now pays only for Gemini, so phase 2 is gemini-only again, no fallback.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import pathlib
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

from esg_kg.core.dates import date_start_key, normalize_date_string
from esg_kg.core.llm import DEFAULT_MODEL, GeminiContextCache, RateLimiter, build_gemini_client
from esg_kg.core.paths import REPO_ROOT
from esg_kg.core.schema import load_schema_sets, validate_triple

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

DEFAULT_INPUT_DIR = REPO_ROOT / "graph_output" / "graphs"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "validated"
# DEFAULT_MODEL comes from esg_kg.core.llm (GEMINI_MODEL env var, default
# gemini-2.5-flash-lite) — see that module's docstring.
DEFAULT_BATCH_SIZE = 25
DEFAULT_RATE_LIMIT = 10

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
# Phase 1.5 (offline): P4 temporal-invariant enforcement.
# Bitemporal integrity is a hard, machine-checked constraint (TEMPORAL_KG_DESIGN
# P4), not a convention:
#   * every date value is canonicalized to ISO YYYY[-MM[-DD]] (so "2011" vs
#     "2011-01-01" can never again split one fact into two temporal versions);
#   * valid_from > valid_to is flagged (never silently swapped);
#   * T2 news nodes (KPIObservation/Controversy/Penalty/MediaReport with
#     source_type=news) must carry a boolean date_uncertain — a missing flag is
#     set to true (the conservative "this date is a proxy" reading) and counted.
# --------------------------------------------------------------------------- #
NEWS_DATE_UNCERTAIN_CLASSES = {"KPIObservation", "Controversy", "Penalty", "MediaReport"}
_NODE_DATE_PROPS = ("valid_from", "valid_to", "date")
_EDGE_DATE_PROPS = ("valid_from", "valid_to", "recorded_at")


def enforce_temporal_invariants(triples: List[Dict[str, Any]]) -> Dict[str, int]:
    """Normalize dates and enforce the P4 invariants in place. Returns counters."""
    stats = {
        "dates_normalized": 0,
        "dates_unparseable": 0,
        "valid_from_after_valid_to": 0,
        "date_uncertain_defaulted": 0,
    }

    def norm_inplace(container: Dict[str, Any], keys: Tuple[str, ...]) -> None:
        for k in keys:
            if k not in container:
                continue
            v = container[k]
            if v is None:
                continue
            norm, ok = normalize_date_string(v)
            if not ok:
                stats["dates_unparseable"] += 1
            elif norm != v:
                container[k] = norm
                stats["dates_normalized"] += 1

    def check_range(container: Dict[str, Any], what: str) -> None:
        kf = date_start_key(container.get("valid_from"))
        kt = date_start_key(container.get("valid_to"))
        if kf and kt and kf > kt:
            stats["valid_from_after_valid_to"] += 1
            logger.warning(f"P4: valid_from > valid_to on {what}: "
                           f"{container.get('valid_from')} > {container.get('valid_to')}")

    for t in triples:
        for side in ("subject", "object"):
            ent = t.get(side)
            if not isinstance(ent, dict):
                continue
            props = ent.get("properties")
            if not isinstance(props, dict):
                continue
            norm_inplace(props, _NODE_DATE_PROPS)
            check_range(props, f"{ent.get('class')} node")
            if (ent.get("class") in NEWS_DATE_UNCERTAIN_CLASSES
                    and props.get("source_type") == "news"
                    and not isinstance(props.get("date_uncertain"), bool)):
                props["date_uncertain"] = True
                stats["date_uncertain_defaulted"] += 1
        tm = t.get("temporal_metadata")
        if isinstance(tm, dict):
            norm_inplace(tm, _EDGE_DATE_PROPS)
            check_range(tm, f"edge {t.get('predicate')}")
    return stats


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
    "5. **Discard unfixable**: If triple cannot be corrected, omit it from output\n"
    "6. **NEVER touch property values**: You may only change `class`, `predicate`,\n"
    "   `temporal_metadata`, and the node properties valid_from / valid_to / is_current.\n"
    "   Copy EVERY other property value byte-for-byte from the input.\n"
    "   - Do NOT translate. Vietnamese text stays Vietnamese, with its diacritics.\n"
    "   - Do NOT reformat, re-case, round numbers, or normalize units.\n"
    "   - Do NOT add properties that were not in the input, or remove any.\n"
    "   These values are source-traceable evidence, not prose to improve.\n\n"
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


# The only property values phase 2 is authorised to write. They are exactly the
# ones BATCH_FIX_PROMPT asks the model to add ("All nodes MUST have: valid_from,
# valid_to, is_current"); `temporal_metadata` is handled at triple level.
MUTABLE_NODE_PROPS = ("valid_from", "valid_to", "is_current")


def preserve_property_values(original: Any, repaired: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Let phase 2 repair a triple's SHAPE, never the VALUES inside it.

    `class`, `predicate`, `temporal_metadata` and the MUTABLE_NODE_PROPS are the
    model's to fix — that is what it was asked for. Every other property value is
    taken back from `original`, so a repair cannot translate a Vietnamese name,
    strip its diacritics, round a KPI value, tidy a unit, invent a property, or
    drop one. Nothing downstream would notice: `validate_triple` only checks
    class/predicate/temporal keys, and a translated name does not fail — it
    silently splits one entity into two in step05 Stage A, because normalize_name
    maps a Vietnamese spelling and its English translation to different keys.

    Returns (guarded_triple, n_blocked) and never mutates its inputs. `n_blocked`
    counts the value overrides that were refused; it is signal, not decoration —
    a batch with a high count means the prompt is drifting.
    """
    guarded = copy.deepcopy(repaired)
    if not isinstance(original, dict):
        return guarded, 0

    blocked = 0
    for side in ("subject", "object"):
        orig_side = original.get(side)
        new_side = guarded.get(side)
        if not isinstance(orig_side, dict) or not isinstance(new_side, dict):
            continue
        orig_props = orig_side.get("properties")
        if not isinstance(orig_props, dict):
            continue
        new_props = new_side.get("properties")
        if not isinstance(new_props, dict):
            new_props = {}

        merged = copy.deepcopy(orig_props)
        for k in MUTABLE_NODE_PROPS:
            if k in new_props:
                merged[k] = new_props[k]

        for k, v in new_props.items():        # changed or invented
            if k not in MUTABLE_NODE_PROPS and (k not in orig_props or orig_props[k] != v):
                blocked += 1
        for k in orig_props:                  # dropped
            if k not in MUTABLE_NODE_PROPS and k not in new_props:
                blocked += 1

        new_side["properties"] = merged
    return guarded, blocked


def fix_batch_with_llm(batch: List[Dict[str, Any]], schema: Dict[str, Any],
                       client: Any, rate_limiter: RateLimiter, model: str,
                       cached_content: Optional[str] = None,
                       ) -> List[Optional[Dict[str, Any]]]:
    """`client` is a `genai.Client`. When `cached_content` is set (a Gemini cache name
    from `GeminiContextCache`, issue #11), `prompt` is just the batch JSON — the fixed
    SCHEMA block of `BATCH_FIX_PROMPT` lives in the cache instead of being resent every
    batch of one run (schema never changes mid-run, see `run_phases`)."""
    if not batch:
        return []
    clean_batch = [{k: v for k, v in t.items() if not k.startswith("_")} for t in batch]
    batch_json = json.dumps(clean_batch, indent=2, ensure_ascii=False)
    config: Dict[str, Any] = {"temperature": 0, "response_mime_type": "application/json"}
    if cached_content is not None:
        prompt = batch_json
        config["cached_content"] = cached_content
    else:
        prompt = BATCH_FIX_PROMPT.format(
            schema_json=json.dumps(schema, indent=2, ensure_ascii=False)
        ) + batch_json

    try:
        rate_limiter.wait_if_needed(0)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        fixed = extract_json_from_response(response.text or "")
        if isinstance(fixed, list):
            # Keep positions aligned with the input batch (null = unfixable). The
            # caller maps each repair back to its original by index, so we must NOT
            # filter out the Nones here.
            return fixed
        return []
    except Exception as e:
        logger.error(f"LLM fix failed: {e}")
        return []


# --------------------------------------------------------------------------- #
# Phases 1-3 driver.
# --------------------------------------------------------------------------- #
def run_phases(input_dir: pathlib.Path, out_dir: pathlib.Path, schema: Dict[str, Any],
               entity_classes: Set[str], edge_labels: Set[str],
               edge_directions: Dict[str, List[Tuple[str, str]]],
               client: Optional[Any], rate_limiter: RateLimiter,
               model: str, batch_size: int, dry_run: bool,
               *, llm=None, repairs=None,
               ctx_cache: Optional[GeminiContextCache] = None):
    """Phases 1 -> 2 -> 1.5. Returns ``(all_valid, unfixable, summary)`` and WRITES NOTHING.

    Split out of ``process_all_files`` so the 03 block
    (``esg_kg/graph/build_validated.py``) can run these phases and hand the triples
    straight to 03b/03c in memory, with no intermediate artifact on disk
    (DESIGN.md §5.7). ``process_all_files`` is now exactly this plus the two writes, so
    its behaviour is unchanged and the old-vs-new equivalence arm still holds.

    ``out_dir`` is still taken because phase 1 must not read page files that live inside
    our own output directory.

    Two optional hooks, both no-ops when omitted:
      * ``llm`` replaces the phase-2 call (tests inject a stub instead of paying);
      * ``repairs`` is a cache object with ``get(triple) -> (value, found)`` and
        ``put(triple, value)``. Phase-2 output is looked up there BEFORE any model call,
        so a re-run is free and deterministic. Duck-typed on purpose: the cache lives in
        the block module, and a stage must not import a block.

    ``ctx_cache`` (issue #11): an optional ``GeminiContextCache``. When given, the fixed
    SCHEMA block of ``BATCH_FIX_PROMPT`` is uploaded once (schema never changes within a
    run) and every phase-2 batch call reuses it via ``cached_content=``, instead of
    resending the schema in every batch's prompt.

    Returns ``None`` when there is nothing to process.
    """
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
        return None

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
    cache_hits = 0
    if all_invalid and not dry_run:
        call_llm = llm or fix_batch_with_llm

        # A repair that has already been paid for is looked up first. Positions are kept
        # by index throughout, because the prompt returns repairs positionally aligned
        # with the batch it was given.
        repaired_by_idx: Dict[int, Any] = {}
        if repairs is not None:
            for idx, original in enumerate(all_invalid):
                value, found = repairs.get(original)
                if found:
                    repaired_by_idx[idx] = value
                    cache_hits += 1
        todo = [(idx, t) for idx, t in enumerate(all_invalid) if idx not in repaired_by_idx]
        if cache_hits:
            logger.info(f"\n=== Phase 2: {cache_hits} repair(s) reused from cache, "
                        f"{len(todo)} still to ask ===")

        if todo and client is None:
            logger.error("LLM phase requested but GEMINI_API_KEY is not set; skipping phase 2")
        elif todo:
            logger.info(f"\n=== Phase 2: LLM batch fixing ({len(todo)} triples) ===")
            cache_name: Optional[str] = None
            if ctx_cache is not None:
                header = BATCH_FIX_PROMPT.format(
                    schema_json=json.dumps(schema, indent=2, ensure_ascii=False))
                cache_name = ctx_cache.get_or_create(header, rate_limiter)
            n_batches = (len(todo) - 1) // batch_size + 1
            for i in range(0, len(todo), batch_size):
                chunk = todo[i:i + batch_size]
                batch = [t for _, t in chunk]
                logger.info(f"Batch {i // batch_size + 1}/{n_batches} ({len(batch)} triples)")
                repaired = call_llm(batch, schema, client, rate_limiter, model, cached_content=cache_name)
                returned = sum(1 for r in repaired if r is not None)
                for k, (idx, _original) in enumerate(chunk):
                    value = repaired[k] if k < len(repaired) else None
                    repaired_by_idx[idx] = value
                    if repairs is not None:
                        repairs.put(all_invalid[idx], value)
                logger.info(f"  Batch result: {returned} returned")

        # Guard + validate every repair (cached or fresh) in input order. Marking the
        # original `_fixed` lets the unfixable set be the exact complement — no value
        # comparison, no double-counting the ones we successfully repaired.
        blocked_values = 0
        for idx, original in enumerate(all_invalid):
            repaired_triple = repaired_by_idx.get(idx)
            if repaired_triple is None or not isinstance(repaired_triple, dict):
                continue
            # Take back every value the model was not authorised to write, BEFORE
            # validating: what we validate must be what we keep. Applied on the way OUT
            # of the cache too, so the cache stores the paid artifact and the guard stays
            # our own code — improving the guard re-applies to cached repairs.
            repaired_triple, n_blocked = preserve_property_values(original, repaired_triple)
            blocked_values += n_blocked
            is_valid, _ = validate_triple(repaired_triple, entity_classes, edge_labels, edge_directions)
            if is_valid:
                clean = {k: v for k, v in repaired_triple.items() if not k.startswith("_")}
                fixed_triples.append(clean)
                original["_fixed"] = True
        if repaired_by_idx:
            logger.info(f"\nPhase 2 fixed: {len(fixed_triples)}/{len(all_invalid)} triples "
                        f"({cache_hits} from cache)")
        if blocked_values:
            logger.warning(
                f"Phase 2 tried to rewrite {blocked_values} property value(s) it is not "
                "authorised to touch — restored from the originals. A high count means "
                "BATCH_FIX_PROMPT is drifting (translated names, 'tidied' units, invented keys)."
            )
        all_valid.extend(fixed_triples)
    elif all_invalid and dry_run:
        logger.info(f"\n=== Phase 2: SKIPPED (--dry-run) — would have sent {len(all_invalid)} invalid triples ===")

    # Invalid triples whose positionally-aligned repair re-validated were tagged
    # `_fixed` above, so the unfixable set is exactly the untagged remainder. (The
    # repaired forms already live in all_valid; the originals must not be re-listed.)
    unfixable = [t for t in all_invalid if not t.get("_fixed")]

    logger.info("\n=== Phase 1.5: P4 temporal-invariant enforcement ===")
    t_stats = enforce_temporal_invariants(all_valid)
    logger.info(
        f"  dates normalized to ISO: {t_stats['dates_normalized']}\n"
        f"  unparseable date values: {t_stats['dates_unparseable']}\n"
        f"  valid_from > valid_to:   {t_stats['valid_from_after_valid_to']}\n"
        f"  date_uncertain defaulted (news T2): {t_stats['date_uncertain_defaulted']}"
    )

    summary = {
        "files": len(all_files), "normal_files": len(normal_files),
        "bugged_files": len(bugged_files), "total": total_stats["total"],
        "direction_fixed": total_stats["direction_fixed"],
        "initially_valid": total_stats["valid"], "llm_fixed": len(fixed_triples),
        "cache_hits": cache_hits, "temporal": t_stats,
    }
    return all_valid, unfixable, summary


def log_summary(all_valid: List[Dict[str, Any]], unfixable: List[Dict[str, Any]],
                summary: Dict[str, Any]) -> None:
    """The end-of-stage report. Shared so the block prints the same numbers."""
    total = summary["total"]
    success_rate = f"{len(all_valid) / total * 100:.1f}%" if total > 0 else "N/A"
    logger.info(
        "\n=== Final summary ===\n"
        f"Total input files: {summary['files']} (normal: {summary['normal_files']}, "
        f"bugged: {summary['bugged_files']})\n"
        f"Total input triples: {total}\n"
        f"Direction fixed offline: {summary['direction_fixed']}\n"
        f"Initially valid: {summary['initially_valid']}\n"
        f"Fixed by LLM: {summary['llm_fixed']}\n"
        f"Final valid triples: {len(all_valid)}\n"
        f"Unfixable: {len(unfixable)}\n"
        f"Success rate: {success_rate}"
    )


def process_all_files(input_dir: pathlib.Path, out_dir: pathlib.Path, schema: Dict[str, Any],
                      entity_classes: Set[str], edge_labels: Set[str],
                      edge_directions: Dict[str, List[Tuple[str, str]]],
                      client: Optional[Any], rate_limiter: RateLimiter,
                      model: str, batch_size: int, dry_run: bool,
                      ctx_cache: Optional[GeminiContextCache] = None) -> None:
    """Stage entry point: phases 1-1.5 (``run_phases``) then phase 3 (write).

    Kept as the standalone stage so `run.py fix_triples` still works and so a single
    stage can still be diagnosed on its own (DESIGN.md §5.7). The 03 BLOCK does not
    call this — it calls ``run_phases`` and passes the triples on in memory.
    """
    result = run_phases(input_dir, out_dir, schema, entity_classes, edge_labels,
                        edge_directions, client, rate_limiter, model, batch_size, dry_run,
                        ctx_cache=ctx_cache)
    if result is None:
        return
    all_valid, unfixable, summary = result

    logger.info("\n=== Phase 3: Saving results ===")
    if dry_run:
        logger.info("Dry run — not writing any files.")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "all_validated_triples.json"
        out_file.write_text(json.dumps(all_valid, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Saved {len(all_valid)} valid triples to {out_file}")

        if unfixable:
            uf_file = out_dir / "unfixable_triples.json"
            uf_file.write_text(json.dumps(unfixable, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Saved {len(unfixable)} unfixable triples to {uf_file}")

    log_summary(all_valid, unfixable, summary)


# --------------------------------------------------------------------------- #
# Renormalize-only mode: apply the P4 phase to an already-aggregated
# all_validated_triples.json. The step-2 LLM extraction results are a frozen,
# paid-for asset — this lets P4 land on them without re-running phase 2.
# --------------------------------------------------------------------------- #
def renormalize_existing(out_dir: pathlib.Path, entity_classes: Set[str], edge_labels: Set[str],
                         edge_directions: Dict[str, List[Tuple[str, str]]]) -> None:
    in_file = out_dir / "all_validated_triples.json"
    if not in_file.exists():
        logger.error(f"--renormalize: {in_file} not found (run the full step first)")
        return
    triples = json.loads(in_file.read_text(encoding="utf-8"))
    logger.info(f"Renormalizing {len(triples)} validated triples in {in_file}")
    t_stats = enforce_temporal_invariants(triples)

    still_valid = 0
    for t in triples:
        ok, _ = validate_triple(t, entity_classes, edge_labels, edge_directions)
        still_valid += ok
    if still_valid != len(triples):
        logger.warning(f"{len(triples) - still_valid} triple(s) no longer schema-valid "
                       f"after normalization — inspect before proceeding")

    in_file.write_text(json.dumps(triples, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        f"Rewrote {in_file}\n"
        f"  dates normalized to ISO: {t_stats['dates_normalized']}\n"
        f"  unparseable date values: {t_stats['dates_unparseable']}\n"
        f"  valid_from > valid_to:   {t_stats['valid_from_after_valid_to']}\n"
        f"  date_uncertain defaulted (news T2): {t_stats['date_uncertain_defaulted']}"
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
    parser.add_argument("--renormalize", action="store_true",
                        help="Only re-apply the P4 temporal-invariant phase to the existing "
                             "all_validated_triples.json (offline, no LLM, keeps prior repairs)")
    parser.add_argument("--no-context-cache", action="store_true",
                        help="Disable Gemini explicit context caching (issue #11) for phase-2 "
                             "repair batches. On by default: one cache per run (the fixed "
                             "SCHEMA block of BATCH_FIX_PROMPT), reused across every batch — "
                             "schema never changes mid-run.")
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

    if args.renormalize:
        renormalize_existing(args.out_dir, entity_classes, edge_labels, edge_directions)
        return

    client: Optional[Any] = None
    if not args.dry_run:
        load_dotenv(REPO_ROOT / ".env")
        client = build_gemini_client()
        if client is None:
            logger.error(f"GEMINI_API_KEY not set in {REPO_ROOT / '.env'}; use --dry-run to skip phase 2")
            return

    rate_limiter = RateLimiter(max_calls_per_minute=args.rate_limit)
    ctx_cache = (None if (client is None or args.no_context_cache)
                 else GeminiContextCache(client, args.model))

    process_all_files(
        args.input_dir, args.out_dir, schema,
        entity_classes, edge_labels, edge_directions,
        client, rate_limiter, args.model,
        args.batch_size, args.dry_run, ctx_cache=ctx_cache,
    )


if __name__ == "__main__":
    main()
