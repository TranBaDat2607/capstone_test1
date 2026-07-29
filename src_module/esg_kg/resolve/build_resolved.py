#!/usr/bin/env python3
"""
The 05 BLOCK — `05 entities` -> `05b provenance` -> `05c indicators` as ONE unit that
writes `resolved_graph.json` exactly ONCE.

WHY THIS EXISTS (DESIGN.md §5.7, decided 2026-07-28, built 2026-07-29)
In `src/` these are three stages that each read AND write
`graph_output/resolved/resolved_graph.json`: `step05_resolve_entities.py:655` writes the
WHOLE file from scratch, then `step05b_stamp_provenance.py` and
`step05c_link_standard_indicators.py` patch it in place. `step05` overwrites the entire
file with no merge and no warning (`PIPELINE.md` §3.1) — re-running it alone silently
destroys 05b's provenance stamps and 05c's indicator axis, with nothing to say so.

`esg_kg` therefore collapses the three into one block that passes the resolved graph
IN MEMORY and writes the artifact exactly once at the end — the same redesign already
proven for the `03` block (`fix_triples -> anchor_kpi -> canonicalize`,
`esg_kg/graph/build_validated.py`).

`05d` (`esg_kg.resolve.align_claims`) is DELIBERATELY NOT part of this block. It is
optional (`--max-llm-pairs`, budgeted LLM) and already patches `resolved_graph.json` in
place AFTER this block runs — exactly as it does today after `src/step05c`. The block
must produce a correct, complete `resolved_graph.json` with 05d entirely absent; nothing
here changes.

THIS IS AN esg_kg-ONLY REDESIGN. `src/` is not touched (Model A) and keeps its three
separate scripts. That is deliberate, not drift — DESIGN.md §5.7 records that §5.5's
"fix both trees" constraint does not apply to block changes.

WHY THE SAFETY NET SURVIVES THE REDESIGN
The change is to WHEN the file is written, not to WHAT ends up in it. So `src/`'s chain
`step05(--no-llm) -> step05b -> step05c` is still a usable ORACLE: run it on a temp copy,
run the block, and the final `resolved_graph.json` must be EQUAL
(`test/test_esg_kg_resolve_block.py`).

THE PAID-PATH CACHE — SCOPED TO STAGE C ONLY
Stage C (`entities.llm_same_entity`, gemini-2.5-flash adjudication) is the exact analogue
of the `03` block's phase-2 repairs: a non-deterministic LLM verdict that costs money.
`AdjudicationCache` below gives it the same treatment as `RepairCache` — keyed by the
content of the (class, non-temporal-props) pair, so a rerun replays the paid verdict for
free. Stage B (`gemini-embedding-001`) is NOT cached: it is billed but deterministic per
model version, and per CLAUDE.md the pipeline runs today (and for the documented future)
with `--no-llm`, so Stages B/C do not execute in the live pipeline at all right now.
Building a full embedding cache would be speculative work for a currently-dormant path;
an embedding cache is a follow-up if/when Stage B comes back into regular use.

WHAT IS NOT TAKEN AWAY
`run.py entities`, `run.py provenance` and `run.py indicators` all still work: the block
ADDS an entry point, it does not remove the per-stage ones. In particular, patching an
ALREADY-RESOLVED graph on disk (the thing `--renormalize` is for in the `03` block) needs
no new flag here — `run.py provenance --dry-run` / `run.py indicators --dry-run` already
do exactly that, unchanged, directly against `resolved_graph.json`. Per-stage diagnostic
files (`resolved_graph_stats.json`, `provenance_patch_stats.json`,
`indicator_axis_stats.json`) are still written — they are diagnostics, not intermediate
artifacts.

Run from the REPO ROOT:

    python src_module/run.py build_resolved --dry-run
    python src_module/run.py build_resolved

Covered by `test/test_esg_kg_resolve_block.py`, whose main arm runs the `src/` chain
`step05(--no-llm) -> step05b -> step05c` as an ORACLE and asserts the block's artifact is
identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import pathlib
from typing import Any, Dict, List, Optional, Tuple

from esg_kg.core.paths import REPO_ROOT
from esg_kg.core.schema import get_identity_keys, load_schema_sets
from esg_kg.resolve import entities, indicators, provenance

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "validated" / "all_validated_triples.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "resolved"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_REGISTRY = REPO_ROOT / "config" / "issuer_registry.json"
DEFAULT_STANDARDS_REGISTRY = REPO_ROOT / "config" / "standards_registry.json"
DEFAULT_GRAPHS_DIR = REPO_ROOT / "graph_output" / "graphs"
DEFAULT_NEWS_GLOBS = provenance.DEFAULT_NEWS_GLOBS
DEFAULT_DEFS = indicators.DEFAULT_DEFS
DEFAULT_CROSSWALK = indicators.DEFAULT_CROSSWALK
DEFAULT_GRI_CATALOG = indicators.GRI_CATALOG_PATH
DEFAULT_CACHE = DEFAULT_OUT_DIR / "entity_adjudication_cache.json"
ARTIFACT_NAME = "resolved_graph.json"


# --------------------------------------------------------------------------- #
# The paid-result cache — Stage C only (see module docstring for the scoping).
# --------------------------------------------------------------------------- #
class AdjudicationCache:
    """Stage C same-entity verdicts, keyed by the content of the pair sent to the model.

    Same shape as `esg_kg.graph.build_validated.RepairCache`: keyed by content (not
    position — candidate order depends on embedding similarity ranking, which is not
    stable across code changes), storing the raw `{"same_entity": bool}` verdict so a
    replayed run reproduces the paid outcome exactly.
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
                logger.info(f"Adjudication cache: {len(self.entries)} verdict(s) from {path}")
            except Exception as exc:  # a corrupt cache must never stop the pipeline
                logger.warning(f"Adjudication cache at {path} unreadable ({exc}); starting empty")
                self.entries = {}

    @staticmethod
    def _key(a: Dict[str, Any], b: Dict[str, Any]) -> str:
        blob = json.dumps(
            {"class": a.get("class"),
             "a": entities.non_temporal_props(a), "b": entities.non_temporal_props(b)},
            sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[Any, bool]:
        k = self._key(a, b)
        if k in self.entries:
            return self.entries[k], True
        return None, False

    def put(self, a: Dict[str, Any], b: Dict[str, Any], value: Any) -> None:
        self.entries[self._key(a, b)] = value
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
        logger.info(f"Adjudication cache: {len(self.entries)} verdict(s) -> {self.path}")
        return True


# --------------------------------------------------------------------------- #
# The block.
# --------------------------------------------------------------------------- #
def run_block(*, input_path: pathlib.Path, out_dir: pathlib.Path, schema: Dict[str, Any],
              graphs_dir: pathlib.Path = DEFAULT_GRAPHS_DIR,
              news_globs: Optional[List[str]] = None,
              registry_path: pathlib.Path = DEFAULT_REGISTRY,
              standards_registry_path: pathlib.Path = DEFAULT_STANDARDS_REGISTRY,
              defs: Optional[List[Dict[str, Any]]] = None,
              crosswalk: Optional[Dict[str, Any]] = None,
              catalog: Optional[Dict[str, Any]] = None,
              no_gri: bool = False, no_align: bool = False,
              trust_draft_crosswalk: bool = False,
              similarity_threshold: float = entities.DEFAULT_SIM,
              model: str = entities.DEFAULT_MODEL,
              embed_model: str = entities.DEFAULT_EMBED_MODEL,
              embed_dim: int = entities.DEFAULT_EMBED_DIM,
              embed_batch: int = entities.DEFAULT_EMBED_BATCH,
              max_llm_pairs: int = entities.DEFAULT_MAX_LLM_PAIRS,
              no_llm: bool = True, client: Any = None, embed_client: Any = None,
              rate_limiter: Any = None,
              cache_path: Optional[pathlib.Path] = None,
              dry_run: bool = False) -> Dict[str, Any]:
    """Run 05 -> 05b -> 05c in memory and write the artifact once.

    Returns per-stage stats: ``{"resolve": ..., "provenance": ..., "indicators": ...}``.
    """
    news_globs = news_globs if news_globs is not None else DEFAULT_NEWS_GLOBS
    defs = defs if defs is not None else json.loads(DEFAULT_DEFS.read_text(encoding="utf-8"))
    crosswalk = crosswalk if crosswalk is not None else (
        json.loads(DEFAULT_CROSSWALK.read_text(encoding="utf-8")) if DEFAULT_CROSSWALK.exists() else {})
    catalog = catalog if catalog is not None else indicators.load_gri_catalog(DEFAULT_GRI_CATALOG)
    cache = AdjudicationCache(cache_path) if cache_path else None

    # --- 05: entity resolution -> resolved graph, in memory ---------------------
    logger.info("=== Block 05 — entities ===")
    triples = json.loads(input_path.read_text(encoding="utf-8"))
    idkeys = entities.load_identity_keys(schema)
    resolved, resolve_stats = entities.resolve_graph(
        triples, idkeys, registry_path=registry_path, standards_registry_path=standards_registry_path,
        similarity_threshold=similarity_threshold, model=model, embed_model=embed_model,
        embed_dim=embed_dim, embed_batch=embed_batch, max_llm_pairs=max_llm_pairs,
        no_llm=no_llm, client=client, embed_client=embed_client, rate_limiter=rate_limiter,
        adjudication_cache=cache,
    )
    logger.info(f"  {len(resolved['nodes'])} nodes, {len(resolved['edges'])} edges")

    # --- 05b: provenance stamping, in memory ------------------------------------
    logger.info("=== Block 05b — provenance ===")
    identity_keys_map = get_identity_keys(schema)
    stable_idx, source_idx, docs = provenance.build_page_indexes(graphs_dir) \
        if graphs_dir.is_dir() else ({}, {}, [])
    news_meta = provenance.load_news_article_meta(news_globs)
    report_docs = [d for d in docs if "__" not in d]
    prov_stats = provenance.stamp_graph(
        resolved, stable_idx, source_idx, news_meta, identity_keys_map, report_docs)

    # --- 05c: indicator axis, in memory -----------------------------------------
    logger.info("=== Block 05c — indicators ===")
    entity_classes, edge_labels, edge_dirs = load_schema_sets(schema)
    axis_report = indicators.link_indicator_axis(
        resolved, defs, crosswalk, catalog, entity_classes, edge_labels, edge_dirs,
        no_gri=no_gri, no_align=no_align, trust_draft_crosswalk=trust_draft_crosswalk,
    )

    stats = {"resolve": resolve_stats, "provenance": prov_stats, "indicators": axis_report}

    # --- the single write --------------------------------------------------------
    if dry_run:
        logger.info(f"Dry run — nothing written. Would have saved "
                    f"{len(resolved['nodes'])} nodes / {len(resolved['edges'])} edges "
                    f"to {out_dir / ARTIFACT_NAME}")
        return stats

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ARTIFACT_NAME).write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Saved {len(resolved['nodes'])} nodes / {len(resolved['edges'])} edges "
                f"to {out_dir / ARTIFACT_NAME} (written ONCE)")

    (out_dir / "resolved_graph_stats.json").write_text(
        json.dumps(resolve_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "provenance_patch_stats.json").write_text(
        json.dumps(prov_stats, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "indicator_axis_stats.json").write_text(
        json.dumps(axis_report, indent=2, ensure_ascii=False), encoding="utf-8")
    if cache is not None:
        cache.save()

    return stats


def main() -> None:
    p = argparse.ArgumentParser(
        description="Block 05 — resolve entities + stamp provenance + link the indicator "
                    "axis in one pass, writing resolved_graph.json exactly once (DESIGN.md §5.7).")
    p.add_argument("-i", "--input", type=pathlib.Path, default=DEFAULT_INPUT,
                   help="all_validated_triples.json (step03/build_validated output)")
    p.add_argument("-o", "--out-dir", type=pathlib.Path, default=DEFAULT_OUT_DIR)
    p.add_argument("-s", "--schema", type=pathlib.Path, default=DEFAULT_SCHEMA)
    p.add_argument("--graphs-dir", type=pathlib.Path, default=DEFAULT_GRAPHS_DIR,
                   help="Per-page extraction files (step02 output), for provenance stamping")
    p.add_argument("--news-globs", nargs="*", default=None,
                   help="Repo-relative globs of news JSONL with article title/url")
    p.add_argument("--registry", type=pathlib.Path, default=DEFAULT_REGISTRY)
    p.add_argument("--standards-registry", type=pathlib.Path, default=DEFAULT_STANDARDS_REGISTRY)
    p.add_argument("--defs", type=pathlib.Path, default=DEFAULT_DEFS)
    p.add_argument("--crosswalk", type=pathlib.Path, default=DEFAULT_CROSSWALK)
    p.add_argument("--gri-catalog", type=pathlib.Path, default=DEFAULT_GRI_CATALOG)
    p.add_argument("--no-gri", action="store_true", help="Skip equivalentTo -> GRI edges (05c)")
    p.add_argument("--no-align", action="store_true", help="Skip the keyword alignsWithIndicator tier (05c)")
    p.add_argument("--trust-draft-crosswalk", action="store_true",
                   help="Emit GRI edges for draft crosswalk rows too (demo only)")
    p.add_argument("--similarity-threshold", type=float, default=entities.DEFAULT_SIM)
    p.add_argument("--rate-limit", type=int, default=entities.DEFAULT_RATE_LIMIT)
    p.add_argument("--model", type=str, default=entities.DEFAULT_MODEL)
    p.add_argument("--embed-model", type=str, default=entities.DEFAULT_EMBED_MODEL)
    p.add_argument("--embed-dim", type=int, default=entities.DEFAULT_EMBED_DIM)
    p.add_argument("--embed-batch", type=int, default=entities.DEFAULT_EMBED_BATCH)
    p.add_argument("--max-llm-pairs", type=int, default=entities.DEFAULT_MAX_LLM_PAIRS)
    p.add_argument("--provider", type=str, default="gemini", choices=["gemini", "openai"],
                   help="LLM backend for Stage B/C (default gemini; openai needs OPENAI_API_KEY)")
    p.add_argument("--openai-model", type=str, default="gpt-4o-mini",
                   help="OpenAI chat model for Stage C, used only when --provider openai")
    p.add_argument("--openai-embed-model", type=str, default="text-embedding-3-small",
                   help="OpenAI embedding model for Stage B, used only when --provider openai")
    p.add_argument("--openai-base-url", type=str, default=None,
                   help="Override the OpenAI endpoint (e.g. an OpenAI-compatible "
                        "third-party host); default is OpenAI's own API")
    p.add_argument("--no-llm", action="store_true", help="Stage A + B.1 only (no embeddings/LLM)")
    p.add_argument("--cache", type=pathlib.Path, default=DEFAULT_CACHE,
                   help="Stage C adjudication cache; a re-run reuses it instead of paying again")
    p.add_argument("--no-cache", action="store_true",
                   help="Ignore the adjudication cache (forces Stage C to ask the model again)")
    p.add_argument("--dry-run", action="store_true",
                   help="--no-llm and write nothing (offline preview)")
    args = p.parse_args()

    if args.dry_run:
        args.no_llm = True
    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run build_validated / step03 first)")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    catalog = indicators.load_gri_catalog(args.gri_catalog)

    # Stage B/C is the only paid part; everything else in the block is offline.
    client = None
    embed_client = None
    rate_limiter = None
    model = args.model
    embed_model = args.embed_model
    if not args.no_llm:
        import os

        from esg_kg.core.paths import load_env
        load_env()
        if args.provider == "openai":
            if os.getenv("OPENAI_API_KEY"):
                client = entities._OpenAIProvider(args.openai_model, args.rate_limit,
                                                  base_url=args.openai_base_url)
                embed_client = entities._OpenAIEmbeddingProvider(args.openai_embed_model, args.rate_limit,
                                                                 base_url=args.openai_base_url)
                rate_limiter = entities.RateLimiter(max_calls_per_minute=args.rate_limit)
                model = args.openai_model
                embed_model = args.openai_embed_model
            else:
                logger.warning("OPENAI_API_KEY not set — Stage B/C will be skipped")
                args.no_llm = True
        else:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                from google import genai
                client = genai.Client(api_key=api_key)
                rate_limiter = entities.RateLimiter(max_calls_per_minute=args.rate_limit)
            else:
                logger.warning("GEMINI_API_KEY not set — Stage B/C will be skipped")
                args.no_llm = True

    run_block(
        input_path=args.input, out_dir=args.out_dir, schema=schema,
        graphs_dir=args.graphs_dir, news_globs=args.news_globs,
        registry_path=args.registry, standards_registry_path=args.standards_registry,
        crosswalk=(json.loads(args.crosswalk.read_text(encoding="utf-8")) if args.crosswalk.exists() else {}),
        catalog=catalog, no_gri=args.no_gri, no_align=args.no_align,
        trust_draft_crosswalk=args.trust_draft_crosswalk,
        similarity_threshold=args.similarity_threshold, model=model,
        embed_model=embed_model, embed_dim=args.embed_dim, embed_batch=args.embed_batch,
        max_llm_pairs=args.max_llm_pairs, no_llm=args.no_llm,
        client=client, embed_client=embed_client, rate_limiter=rate_limiter,
        cache_path=None if args.no_cache else args.cache,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
