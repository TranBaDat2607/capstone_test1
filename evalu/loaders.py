"""
Read-only access to the pipeline's artifacts.

Every function here opens files the pipeline WROTE and never writes back. The
labelled corpora are streamed rather than loaded, because
`all_sentences_classified.jsonl` alone is ~380 MB / 874k records.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

RESOLVED_GRAPH = REPO_ROOT / "graph_output" / "resolved" / "resolved_graph.json"
VALIDATED_TRIPLES = REPO_ROOT / "graph_output" / "validated" / "all_validated_triples.json"
PAGE_GRAPHS_DIR = REPO_ROOT / "graph_output" / "graphs"
CROSSCHECK_DIR = REPO_ROOT / "graph_output" / "crosscheck"
SCHEMA = REPO_ROOT / "config" / "schema.json"

REPORT_SENTENCES = REPO_ROOT / "data" / "labeled" / "classified" / "all_sentences_classified.jsonl"
NEWS_SENTENCES = REPO_ROOT / "data" / "labeled" / "news_labeled" / "all_news_sentences_classified.jsonl"


class MissingArtifact(RuntimeError):
    """Raised when a metric's input is absent — reported, never silently zeroed."""


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise MissingArtifact(f"{path.relative_to(REPO_ROOT)} not found")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_schema() -> Dict[str, Any]:
    return _read_json(SCHEMA)


def load_resolved_graph() -> Dict[str, Any]:
    return _read_json(RESOLVED_GRAPH)


def load_validated_triples() -> List[Dict[str, Any]]:
    return _read_json(VALIDATED_TRIPLES)


def identity_keys_map(schema: Dict[str, Any]) -> Dict[str, List[str]]:
    return {spec["class"]: spec.get("identity_keys") or ["name"]
            for spec in schema.get("nodes", []) if spec.get("class")}


def stream_jsonl(path: Path, limit: Optional[int] = None) -> Iterator[Dict[str, Any]]:
    """Yield records one at a time; malformed lines are skipped, not fatal."""
    if not path.exists():
        raise MissingArtifact(f"{path.relative_to(REPO_ROOT)} not found")
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                return
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_dossiers() -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every *_claim_assessments.json in graph_output/crosscheck, concatenated."""
    if not CROSSCHECK_DIR.exists():
        raise MissingArtifact("graph_output/crosscheck not found")
    dossiers: List[Dict[str, Any]] = []
    tickers: List[str] = []
    for p in sorted(CROSSCHECK_DIR.glob("*_claim_assessments.json")):
        ticker = p.name.replace("_claim_assessments.json", "").upper()
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        items = blob if isinstance(blob, list) else blob.get("assessments", [])
        for d in items:
            d.setdefault("_ticker", ticker)
        dossiers.extend(items)
        tickers.append(ticker)
    if not dossiers:
        raise MissingArtifact("no claim assessments found in graph_output/crosscheck")
    return dossiers, tickers


def iter_page_graph_nodes() -> Iterator[Dict[str, Any]]:
    """
    Pre-repair nodes: every node in graph_output/graphs/<doc>/page*.json, each
    already carrying the `stable_id` step02 stamped on it.
    """
    if not PAGE_GRAPHS_DIR.exists():
        raise MissingArtifact("graph_output/graphs not found")
    for page in PAGE_GRAPHS_DIR.glob("*/page*.json"):
        if page.name.endswith("_bugged.json"):
            continue
        try:
            blob = json.loads(page.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(blob, dict):
            for node in blob.get("nodes") or []:
                yield node


def repair_pairs(triples: Iterable[Dict[str, Any]],
                 id_keys: Dict[str, List[str]]
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Build the (before, after) node lists that M2.3 compares.

    Both sides are keyed by the SAME stable id: page graphs carry theirs from
    step02, and the validated side is recomputed with the pipeline's own
    `get_stable_entity_id`. Nodes that appear on only one side are counted and
    reported rather than dropped quietly — an identity-bearing property rewritten
    by the repair pass shows up exactly there, and pretending it matched would
    hide the very thing the guard exists to catch.
    """
    from esg_kg.core.identity import get_stable_entity_id

    before: Dict[str, Dict[str, Any]] = {}
    for node in iter_page_graph_nodes():
        sid = node.get("stable_id") or get_stable_entity_id(node, id_keys)
        before.setdefault(sid, {"id": sid, "properties": node.get("properties") or {}})

    after: Dict[str, Dict[str, Any]] = {}
    for t in triples:
        for side in ("subject", "object"):
            node = t.get(side)
            if not isinstance(node, dict):
                continue
            sid = get_stable_entity_id(node, id_keys)
            after.setdefault(sid, {"id": sid, "properties": node.get("properties") or {}})

    common = set(before) & set(after)
    stats = {
        "before_nodes": len(before),
        "after_nodes": len(after),
        "matched": len(common),
        "only_before": len(set(before) - common),
        "only_after": len(set(after) - common),
    }
    return ([before[k] for k in common], [after[k] for k in common], stats)
