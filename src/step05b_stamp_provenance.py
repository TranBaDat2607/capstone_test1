#!/usr/bin/env python3
"""
Step 5b — offline provenance stamping of the resolved graph (docs/PROVENANCE_PATCH.md).

Sentence-level traceability (`source_pdf`, `page`, `sentence_index`) is a core
principle of this pipeline, but the step03 aggregation drops the "which page file
did this node come from" context: resolved nodes only keep the LLM's free-text
`source` (claims) or a partially-parseable `source_id` (KPIs). The per-page
extraction files `graph_output/graphs/<doc>/page{N}.json` still exist on disk and
their path encodes exactly the doc + page every node was extracted from — so this
script patches the ALREADY-extracted (paid-for) resolved graph offline, without
any LLM or DB:

  1. index every page-file node by its `stable_id` and by its raw
     `properties.source_id` -> {(doc, page)};
  2. for every claim/evidence node in resolved_graph.json (PROVENANCE_CLASSES —
     never T1 entities, which recur on dozens of pages), match it back through a
     4-tier precedence (parseable source_id -> exact source_id index ->
     recomputed stable_id -> "_pageNN_" token) and stamp
     `source_doc` / `source_page` / `provenance_method`;
  3. for news docs (`TICKER__domain__hash`), also stamp `article_title` /
     `article_url` / `source_domain` from the news JSONL corpora so the UI can
     cite the article by name.

HARD INVARIANT: the node array is NEVER grown, shrunk, or reordered — only
`properties` dicts are mutated. step06 keys Neo4j nodes by array index
(`_node_key = f"n{i}"`) and the step07 dossiers reference nodes by
`node_index` / `claim_node_index`, so any reordering would silently corrupt the
advisory layer. Nodes already stamped `provenance_method="extraction"` (future
step02 output) are left untouched.

Run AFTER step05 and BEFORE step06 (re-run it after any step05 re-run):

    python src/step05b_stamp_provenance.py --dry-run   # preview coverage
    python src/step05b_stamp_provenance.py             # stamp resolved_graph.json in place
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from step01_extract_kpi_from_jsonl import REPO_ROOT
from step02_extract_triplet_from_jsonl import (PROVENANCE_CLASSES, get_identity_keys,
                                               get_stable_entity_id)
from step03b_anchor_kpi_facilities import parse_source_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_RESOLVED = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
DEFAULT_GRAPHS_DIR = REPO_ROOT / "graph_output" / "graphs"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_STATS_OUT = REPO_ROOT / "graph_output" / "resolved" / "provenance_patch_stats.json"
DEFAULT_NEWS_GLOBS = [
    "data/labeled/news_labeled/*.jsonl",
    "data/interim/news_preprocessed/*.jsonl",
]
PAGE_FILE_RE = re.compile(r"^page(\d+)\.json$")   # excludes *_bugged.json / *_malformed.txt
PAGE_TOKEN_RE = re.compile(r"^(.+?)_page(\d+)(?:_|$)")


# --------------------------------------------------------------------------- #
# Indexes over the per-page extraction files + news article metadata.
# --------------------------------------------------------------------------- #
def build_page_indexes(graphs_dir: Path) -> Tuple[Dict[str, Set[Tuple[str, int]]],
                                                  Dict[str, Set[Tuple[str, int]]],
                                                  List[str]]:
    """One pass over graphs/*/page{N}.json.

    Returns (stable_id_index, source_id_index, doc_names):
      stable_id_index:  node["stable_id"]              -> {(doc_dir_name, page)}
      source_id_index:  node["properties"]["source_id"] -> {(doc_dir_name, page)}
    """
    stable_idx: Dict[str, Set[Tuple[str, int]]] = {}
    source_idx: Dict[str, Set[Tuple[str, int]]] = {}
    docs: List[str] = []
    n_files = 0
    for doc_dir in sorted(p for p in graphs_dir.iterdir() if p.is_dir()):
        docs.append(doc_dir.name)
        for f in sorted(doc_dir.iterdir()):
            m = PAGE_FILE_RE.match(f.name)
            if not m:
                continue
            page = int(m.group(1))
            try:
                graph = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning(f"Skipping unparseable page file: {f}")
                continue
            n_files += 1
            loc = (doc_dir.name, page)
            for node in graph.get("nodes", []):
                sid = node.get("stable_id")
                if sid:
                    stable_idx.setdefault(sid, set()).add(loc)
                src_id = (node.get("properties") or {}).get("source_id")
                if src_id:
                    source_idx.setdefault(str(src_id), set()).add(loc)
    logger.info(f"Indexed {n_files} page files across {len(docs)} docs: "
                f"{len(stable_idx)} stable_ids, {len(source_idx)} source_ids")
    return stable_idx, source_idx, docs


def load_news_article_meta(globs: List[str]) -> Dict[str, Dict[str, str]]:
    """News doc_id ('AAA__<domain>__<sha1_10>', the JSONL `source_pdf`) -> article meta.

    First-seen row wins — all rows of one article share title/url/domain. Same
    reading style as step03b.load_sentences, but keeps title/url instead of text.
    """
    meta: Dict[str, Dict[str, str]] = {}
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
                    src = row.get("source_pdf")
                    if not src or src in meta:
                        continue
                    meta[str(src)] = {
                        "article_title": str(row.get("title") or ""),
                        "article_url": str(row.get("url") or ""),
                        "source_domain": str(row.get("source_domain") or ""),
                    }
    logger.info(f"Loaded article metadata for {len(meta)} news docs from {n_files} JSONL file(s)")
    return meta


# --------------------------------------------------------------------------- #
# Matching.
# --------------------------------------------------------------------------- #
def parse_page_token(source_id: Any) -> Optional[Tuple[str, int]]:
    """'AAA_Baocaothuongnien_page12_LNST_DTT_2010' -> ('AAA_Baocaothuongnien', 12).

    Last-resort parse of KPI-style ids that embed a '_pageNN_' token. Ids in the
    canonical '<src>_<page>_<idx>' form belong to parse_source_id, not here.
    """
    if parse_source_id(source_id) is not None:
        return None
    m = PAGE_TOKEN_RE.match(str(source_id or ""))
    if not m:
        return None
    return m.group(1), int(m.group(2))


def node_year_context(props: Dict[str, Any]) -> Optional[int]:
    """First 4-digit year among year / target_year / date / valid_from (that order)."""
    for k in ("year", "target_year", "date", "valid_from"):
        m = re.search(r"(19|20)\d{2}", str(props.get(k, "") or ""))
        if m:
            return int(m.group(0))
    return None


def _prop_dicts(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Canonical properties first, then each temporal_versions member's properties."""
    out = [node.get("properties") or {}]
    for tv in node.get("temporal_versions") or []:
        p = tv.get("properties")
        if p:
            out.append(p)
    return out


def candidate_locations(node: Dict[str, Any],
                        stable_idx: Dict[str, Set[Tuple[str, int]]],
                        source_idx: Dict[str, Set[Tuple[str, int]]],
                        identity_keys_map: Dict[str, List[str]],
                        report_docs: List[str]) -> Tuple[Set[Tuple[str, int]], Optional[str]]:
    """4-tier matching precedence; the first tier with candidates wins.

    1. "source_id"        — the node's own source_id parses as <src>_<page>_<idx>.
    2. "source_id_index"  — exact raw source_id lookup in the page-file index
                            (covers LLM-invented ids the page files retain verbatim).
    3. "stable_id_index"  — recomputed stable_id (canonical + temporal versions).
    4. "page_token"       — embedded '_pageNN_' + unique year-matching doc dir.
    """
    prop_dicts = _prop_dicts(node)
    source_ids = [p.get("source_id") for p in prop_dicts if p.get("source_id")]

    cands: Set[Tuple[str, int]] = set()
    for sid in source_ids:
        parsed = parse_source_id(sid)
        if parsed:
            src, page, _idx = parsed
            doc = src[:-4] if src.endswith(".pdf") else src   # page dirs carry the bare stem
            cands.add((doc, page))
    if cands:
        return cands, "source_id"

    for sid in source_ids:
        cands |= source_idx.get(str(sid), set())
    if cands:
        return cands, "source_id_index"

    cls = node.get("class", "Unknown")
    for p in prop_dicts:
        sid = get_stable_entity_id({"class": cls, "properties": p}, identity_keys_map)
        cands |= stable_idx.get(sid, set())
    if cands:
        return cands, "stable_id_index"

    year = node_year_context(prop_dicts[0])
    for sid in source_ids:
        tok = parse_page_token(sid)
        if not tok:
            continue
        prefix, page = tok
        matching = [d for d in report_docs
                    if d.startswith(prefix) and year and d.endswith(f"_{year}")]
        if len(matching) == 1:
            cands.add((matching[0], page))
    if cands:
        return cands, "page_token"

    return set(), None


def choose_primary(cands: Set[Tuple[str, int]], year: Optional[int]) -> Tuple[str, int]:
    """Ambiguity policy: (1) prefer docs whose stem ends '_<year>' of the node's year
    context; (2) lexicographically smallest doc; (3) smallest page."""
    pool = cands
    if year:
        year_matched = {c for c in cands if c[0].endswith(f"_{year}")}
        if year_matched:
            pool = year_matched
    return min(pool)


# --------------------------------------------------------------------------- #
# Stamping.
# --------------------------------------------------------------------------- #
def stamp_graph(graph: Dict[str, Any],
                stable_idx: Dict[str, Set[Tuple[str, int]]],
                source_idx: Dict[str, Set[Tuple[str, int]]],
                news_meta: Dict[str, Dict[str, str]],
                identity_keys_map: Dict[str, List[str]],
                report_docs: List[str]) -> Dict[str, Any]:
    """Mutates graph['nodes'] properties in place; returns the stats dict.

    Never inserts, removes, or reorders nodes (step06/_node_key + dossier
    node_index both key on array position).
    """
    per_class: Dict[str, Counter] = {}
    per_method: Counter = Counter()
    multi_location = 0
    news_enriched = 0
    news_meta_missing: Set[str] = set()
    sample_unmatched: List[str] = []
    samples: List[str] = []

    for node in graph.get("nodes", []):
        cls = node.get("class", "Unknown")
        if cls not in PROVENANCE_CLASSES:
            continue
        props = node.setdefault("properties", {})
        cstats = per_class.setdefault(cls, Counter())
        if props.get("provenance_method") == "extraction":
            cstats["already_stamped"] += 1
            continue

        cands, method = candidate_locations(node, stable_idx, source_idx,
                                            identity_keys_map, report_docs)
        if not cands:
            cstats["unmatched"] += 1
            if props.get("source_id") and len(sample_unmatched) < 5:
                sample_unmatched.append(str(props["source_id"]))
            continue

        doc, page = choose_primary(cands, node_year_context(props))
        props["source_doc"] = doc
        props["source_page"] = int(page)
        props["provenance_method"] = method
        if len(cands) > 1:
            props["source_pages"] = sorted(f"{d}:{p}" for d, p in cands)
            multi_location += 1

        if "__" in doc:   # news doc_id shape TICKER__domain__hash
            meta = news_meta.get(doc)
            if meta:
                for k, v in meta.items():
                    if v:
                        props[k] = v
                news_enriched += 1
            else:
                news_meta_missing.add(doc)

        cstats["stamped"] += 1
        per_method[method] += 1
        if len(samples) < 5:
            samples.append(f"{cls} -> {doc} p.{page} ({method})")

    return {
        "per_class": {cls: dict(c) for cls, c in sorted(per_class.items())},
        "per_method": dict(per_method),
        "multi_location_nodes": multi_location,
        "news_enriched": news_enriched,
        "news_meta_missing": sorted(news_meta_missing),
        "sample_unmatched_source_ids": sample_unmatched,
        "samples": samples,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Step 5b — offline provenance stamping of the resolved graph "
                    "(source_doc/source_page + news article meta; no LLM, no DB).")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_RESOLVED,
                   help="Resolved graph (step05 output), patched in place")
    p.add_argument("--graphs-dir", type=Path, default=DEFAULT_GRAPHS_DIR,
                   help="Per-page extraction files (step02 output)")
    p.add_argument("-s", "--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--news-globs", nargs="*", default=DEFAULT_NEWS_GLOBS,
                   help="Repo-relative globs of news JSONL files with article title/url")
    p.add_argument("--stats-out", type=Path, default=DEFAULT_STATS_OUT)
    p.add_argument("--dry-run", action="store_true",
                   help="Report coverage without writing anything")
    args = p.parse_args()

    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run step05_resolve_entities.py first)")
        return
    if not args.graphs_dir.is_dir():
        logger.error(f"Graphs dir not found: {args.graphs_dir} (run step02 first)")
        return

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    identity_keys_map = get_identity_keys(schema)
    graph = json.loads(args.input.read_text(encoding="utf-8"))
    n_nodes, n_edges = len(graph.get("nodes", [])), len(graph.get("edges", []))
    logger.info(f"Loaded resolved graph: {n_nodes} nodes, {n_edges} edges")

    stable_idx, source_idx, docs = build_page_indexes(args.graphs_dir)
    news_meta = load_news_article_meta(args.news_globs)
    report_docs = [d for d in docs if "__" not in d]

    stats = stamp_graph(graph, stable_idx, source_idx, news_meta,
                        identity_keys_map, report_docs)

    # Hard invariant: node/edge arrays untouched except for properties mutation.
    assert len(graph.get("nodes", [])) == n_nodes and len(graph.get("edges", [])) == n_edges, \
        "provenance patch must never change node/edge counts"

    logger.info("Provenance patch stats:\n" + json.dumps(stats, indent=2, ensure_ascii=False))
    for s in stats["samples"]:
        logger.info(f"  sample: {s}")

    if args.dry_run:
        logger.info(f"Dry run — would rewrite {args.input} with stamped properties")
        return

    args.input.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Stamped provenance into {args.input}; stats -> {args.stats_out}")
    logger.info("Next: reload Neo4j (step06 --clear) then re-sync the advisory layer (step08).")


if __name__ == "__main__":
    main()
