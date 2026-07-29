#!/usr/bin/env python3
"""
The 03 BLOCK — `03 fix_triples` -> `03b anchor_kpi` -> `03c canonicalize` as ONE unit
that writes `all_validated_triples.json` exactly ONCE.

WHY THIS EXISTS (DESIGN.md §5.7, decided 2026-07-28)
In `src/` these are three stages that each read AND write the same file. That
intermediate artifact was never a deliverable — it is an implementation detail that
leaked into being a contract, and it has a measurable cost. The file on disk today is:

    14,492  phase 1, offline          -> free to rebuild
    +   90  phase 2, LLM              -> PAID FOR, and not deterministic
    +   95  03b gazetteer anchors     -> free to rebuild
    = 14,677  triples  (plus 683 kpi_id stamps from 03c)

Re-running step03 alone rebuilds from `graphs/` and `write_text()`s over all of it —
destroying 03b's anchors, 03c's stamps and the 90 paid repairs, with no warning. The
only thing holding the chain together is a log line at the end of each stage: a
contract by memory, the same defect §5.5 records for the 05 cluster.

THIS IS AN esg_kg-ONLY REDESIGN. `src/` is untouched (Model A) and keeps its three
separate stages. Deliberate, not drift — DESIGN.md §5.7 also records that §5.5's
"fix both trees" constraint does not apply to block changes.

THE DISTINCTION THAT MAKES IT SAFE: artifact vs cache
Dropping the *intermediate artifact* is the point. Dropping the *cache of a paid
result* would be a regression: every block run would re-pay for phase 2, and because
the model is not deterministic it would return something different each time. Today
03b/03c are free to re-run precisely BECAUSE they read a frozen file — that property
must survive. So phase-2 repairs go to their own cache (`phase2_repairs.json`), keyed
by the content of the input triple, and the block consults it before calling any LLM.
The cache stores the model's RAW reply; `preserve_property_values` is applied on the
way out, so the guard stays our code and improving it also fixes cached repairs.

    Intermediate artifact answers "how far did the pipeline get?"  -> internal state,
                                                                      droppable.
    Cache answers "what already cost money/time?"                  -> not reproducible
                                                                      for free, keep.

WHAT IS NOT TAKEN AWAY
`run.py fix_triples`, `run.py anchor_kpi` and `run.py canonicalize` all still work: the
block ADDS an entry point, it does not remove the per-stage ones, or the ability to
diagnose one stage alone goes with them. Per-stage stats files are still written — they
are diagnostics, not intermediate artifacts.

Run from the REPO ROOT:

    python src_module/run.py build_validated --dry-run
    python src_module/run.py build_validated

Covered by `test/test_esg_kg_validated_block.py`, whose main arm runs the `src/` chain
03 -> 03b -> 03c as an ORACLE and asserts the block's artifact is identical. That works
because this change alters WHEN the file is written, never WHAT ends up in it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import pathlib
from typing import Any, Dict, List, Optional, Tuple

from esg_kg.core.paths import REPO_ROOT, SCHEMA_PATH
from esg_kg.core.schema import load_schema_sets
from esg_kg.graph import anchor_kpi, fix_triples
from esg_kg.kpi import canonicalize

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = REPO_ROOT / "graph_output" / "graphs"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "validated"
DEFAULT_SCHEMA = SCHEMA_PATH
DEFAULT_CACHE = DEFAULT_OUT_DIR / "phase2_repairs.json"
ARTIFACT_NAME = "all_validated_triples.json"


# --------------------------------------------------------------------------- #
# The paid-result cache.
# --------------------------------------------------------------------------- #
class RepairCache:
    """Phase-2 repairs, keyed by the content of the triple that was sent.

    Deliberately NOT keyed by position: batch boundaries move when the corpus changes,
    and a position key would silently hand a repair to the wrong triple. The value is
    the model's raw reply (or ``None`` for "the model could not fix this"), so a
    replayed run reproduces the paid outcome exactly, including the failures — asking
    again for something the model already declined is just spending money to be told no
    a second time.
    """

    VERSION = 1

    def __init__(self, path: Optional[pathlib.Path] = None) -> None:
        self.path = path
        self.entries: Dict[str, Any] = {}
        self._dirty = False
        if path and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
                logger.info(f"Phase-2 cache: {len(self.entries)} repair(s) from {path}")
            except Exception as exc:  # a corrupt cache must never stop the pipeline
                logger.warning(f"Phase-2 cache at {path} unreadable ({exc}); starting empty")
                self.entries = {}

    @staticmethod
    def key(triple: Any) -> str:
        """Content hash of the triple as phase 2 sees it (internal `_` keys stripped,
        exactly like `fix_batch_with_llm` does before building the prompt)."""
        clean = ({k: v for k, v in triple.items() if not k.startswith("_")}
                 if isinstance(triple, dict) else triple)
        blob = json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, triple: Any) -> Tuple[Any, bool]:
        k = self.key(triple)
        if k in self.entries:
            return self.entries[k], True
        return None, False

    def put(self, triple: Any, value: Any) -> None:
        self.entries[self.key(triple)] = value
        self._dirty = True

    def save(self) -> bool:
        """Write only when something changed — a free replay must not touch the disk."""
        if not (self.path and self._dirty):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": self.VERSION, "entries": self.entries},
                       indent=2, ensure_ascii=False),
            encoding="utf-8")
        logger.info(f"Phase-2 cache: {len(self.entries)} repair(s) -> {self.path}")
        return True


# --------------------------------------------------------------------------- #
# The block.
# --------------------------------------------------------------------------- #
def run_block(*, input_dir: pathlib.Path, out_dir: pathlib.Path, schema: Dict[str, Any],
              sentences: Optional[List[str]] = None,
              max_per_facility: int = anchor_kpi.DEFAULT_MAX_PER_FACILITY,
              defs: Optional[Dict[str, Any]] = None,
              aliases: Optional[Dict[str, Any]] = None,
              fuzzy_threshold: int = canonicalize.DEFAULT_FUZZY_THRESHOLD,
              no_goals: bool = False,
              client: Any = None, rate_limiter: Any = None,
              model: str = fix_triples.DEFAULT_MODEL,
              batch_size: int = fix_triples.DEFAULT_BATCH_SIZE,
              llm=None, cache_path: Optional[pathlib.Path] = None,
              dry_run: bool = False) -> Dict[str, Any]:
    """Run 03 -> 03b -> 03c in memory and write the artifact once.

    Returns per-stage stats: ``{"fix": ..., "anchor": ..., "kpi": ..., "goal": ...}``.
    """
    entity_classes, edge_labels, edge_directions = load_schema_sets(schema)
    repairs = RepairCache(cache_path) if cache_path else None

    # --- 03: validate + repair (phases 1, 2, 1.5) — nothing written -------------
    logger.info("=== Block 03 — fix_triples ===")
    result = fix_triples.run_phases(
        input_dir, out_dir, schema, entity_classes, edge_labels, edge_directions,
        client, rate_limiter, model, batch_size, dry_run,
        llm=llm, repairs=repairs)
    if result is None:
        return {"fix": None, "anchor": None, "kpi": None, "goal": None}
    triples, unfixable, fix_stats = result

    # --- 03b: gazetteer anchors, appended in memory -----------------------------
    logger.info("=== Block 03b — anchor_kpi ===")
    globs = sentences if sentences is not None else anchor_kpi.DEFAULT_SENTENCE_GLOBS
    sentence_index = anchor_kpi.load_sentences(globs)
    new_triples, anchor_stats = anchor_kpi.build_patch(
        triples, sentence_index, schema, max_per_facility)
    triples.extend(new_triples)
    logger.info(f"  appended {len(new_triples)} anchor triple(s)")

    # --- 03c: canonical kpi_id + goal target_date, patched in memory ------------
    logger.info("=== Block 03c — canonicalize ===")
    defs = defs if defs is not None else json.loads(
        canonicalize.DEFAULT_DEFS.read_text(encoding="utf-8"))
    aliases = aliases if aliases is not None else json.loads(
        canonicalize.DEFAULT_ALIASES.read_text(encoding="utf-8"))
    matcher = canonicalize.Matcher(defs, aliases, fuzzy_threshold)
    n_before = len(triples)
    kpi_stats = canonicalize.canonicalize_kpis(triples, matcher)
    goal_stats = ({"skipped": True} if no_goals
                  else canonicalize.backfill_goal_target_date(triples))
    assert len(triples) == n_before, "03c must never add or remove triples"

    stats = {"fix": fix_stats, "anchor": anchor_stats, "kpi": kpi_stats, "goal": goal_stats}

    # --- the single write -------------------------------------------------------
    if dry_run:
        logger.info(f"Dry run — nothing written. Would have saved {len(triples)} triples "
                    f"to {out_dir / ARTIFACT_NAME}")
        fix_triples.log_summary(triples, unfixable, fix_stats)
        return stats

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ARTIFACT_NAME).write_text(
        json.dumps(triples, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Saved {len(triples)} triples to {out_dir / ARTIFACT_NAME} (written ONCE)")

    if unfixable:
        (out_dir / "unfixable_triples.json").write_text(
            json.dumps(unfixable, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "anchor_patch_stats.json").write_text(
        json.dumps(anchor_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "kpi_canonical_stats.json").write_text(
        json.dumps({"kpi": kpi_stats, "goal": goal_stats,
                    "params": {"fuzzy_threshold": fuzzy_threshold,
                               "aliases_version": aliases.get("version")}},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    if repairs is not None:
        repairs.save()

    fix_triples.log_summary(triples, unfixable, fix_stats)
    return stats


def main() -> None:
    p = argparse.ArgumentParser(
        description="Block 03 — validate + anchor + canonicalize in one pass, writing "
                    "all_validated_triples.json exactly once (DESIGN.md §5.7).")
    p.add_argument("-i", "--input-dir", type=pathlib.Path, default=DEFAULT_INPUT_DIR,
                   help="step02 page graphs")
    p.add_argument("-o", "--out-dir", type=pathlib.Path, default=DEFAULT_OUT_DIR)
    p.add_argument("-s", "--schema", type=pathlib.Path, default=DEFAULT_SCHEMA)
    p.add_argument("--sentences", nargs="*", default=None,
                   help="Repo-relative globs of labeled JSONL with source sentences (03b)")
    p.add_argument("--max-per-facility", type=int,
                   default=anchor_kpi.DEFAULT_MAX_PER_FACILITY)
    p.add_argument("--fuzzy-threshold", type=int,
                   default=canonicalize.DEFAULT_FUZZY_THRESHOLD)
    p.add_argument("--no-goals", action="store_true", help="Skip the Goal.target_date backfill")
    p.add_argument("--batch-size", type=int, default=fix_triples.DEFAULT_BATCH_SIZE)
    p.add_argument("--rate-limit", type=int, default=fix_triples.DEFAULT_RATE_LIMIT)
    p.add_argument("--model", type=str, default=fix_triples.DEFAULT_MODEL)
    p.add_argument("--provider", type=str, default="gemini", choices=["gemini", "openai"],
                   help="LLM backend for the phase-2 repair (default gemini; "
                        "openai needs OPENAI_API_KEY)")
    p.add_argument("--openai-model", type=str, default="gpt-4o-mini",
                   help="OpenAI model id, used only when --provider openai")
    p.add_argument("--openai-base-url", type=str, default=None,
                   help="Override the OpenAI endpoint (e.g. an OpenAI-compatible "
                        "third-party host); default is OpenAI's own API")
    p.add_argument("--cache", type=pathlib.Path, default=DEFAULT_CACHE,
                   help="Phase-2 repair cache; a re-run reuses it instead of paying again")
    p.add_argument("--no-cache", action="store_true",
                   help="Ignore the repair cache (forces phase 2 to ask the model again)")
    p.add_argument("--dry-run", action="store_true",
                   help="Phase 1 + 1.5 + 03b + 03c offline; call no LLM and write nothing")
    args = p.parse_args()

    if not args.input_dir.exists():
        logger.error(f"Input directory not found: {args.input_dir}")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return
    schema = json.loads(args.schema.read_text(encoding="utf-8"))

    # Phase 2 is the only paid part; everything else in the block is offline.
    client = None
    rate_limiter = None
    model = args.model
    if not args.dry_run:
        import os

        from esg_kg.core.paths import load_env
        load_env()
        if args.provider == "openai":
            if os.getenv("OPENAI_API_KEY"):
                client = fix_triples._OpenAIProvider(args.openai_model, args.rate_limit,
                                                     base_url=args.openai_base_url)
                rate_limiter = fix_triples.RateLimiter(max_calls_per_minute=args.rate_limit)
                model = args.openai_model
            else:
                logger.warning("OPENAI_API_KEY not set — phase 2 will run from the cache only")
        else:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                from google import genai
                client = genai.Client(api_key=api_key)
                rate_limiter = fix_triples.RateLimiter(max_calls_per_minute=args.rate_limit)
            else:
                logger.warning("GEMINI_API_KEY not set — phase 2 will run from the cache only")

    run_block(
        input_dir=args.input_dir, out_dir=args.out_dir, schema=schema,
        sentences=args.sentences, max_per_facility=args.max_per_facility,
        fuzzy_threshold=args.fuzzy_threshold, no_goals=args.no_goals,
        client=client, rate_limiter=rate_limiter, model=model,
        batch_size=args.batch_size,
        cache_path=None if args.no_cache else args.cache,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
