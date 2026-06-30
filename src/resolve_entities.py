#!/usr/bin/env python3
"""
Step 4 — entity resolution.

Collapses the many duplicate entity nodes in
`graph_output/validated/all_validated_triples.json` (step-3 output) into single
canonical entities, preserving each entity's temporal history, and writes a
deduplicated temporal knowledge graph to `graph_output/resolved/`.

A deliberate redesign of EmeraldMind/src/EmeraldKG/4-entity_resolution.py for the
Vietnamese / greenwashing setting (see docs/ENTITY_RESOLUTION.md). The pipeline:

  Stage A  deterministic merge (free)
           - exact identity_keys signature  (entities AND observations)
           - issuer anchor: merge the reporting company's name variants by exact
             membership in config/issuer_registry.json; the issuer cluster is
             FROZEN — its identity never depends on embeddings or an LLM.
  Stage B  Vietnamese-aware blocking (non-issuer entities only)
           - B1: normalized identity signature merge (diacritics/legal-form/case)
           - B2: gemini-embedding-001 cosine blocking (batched, L2-normalized)
  Stage C  gemini-2.5-flash adjudication on ambiguous candidate pairs (budgeted)
  Stage D  consolidate clusters -> temporal_versions; deterministic canonical;
           year-aware edge rewiring (keeps multi-year edges distinct)

Run from the repo root:  python src/resolve_entities.py
Reuses helpers from the earlier stages; loads .env (GEMINI_API_KEY) at the repo root.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types

from extract_kpi_from_jsonl import REPO_ROOT
from extract_triplet_from_jsonl import RateLimiter
from fix_invalid_triplets import load_schema_sets
from build_issuer_registry import normalize_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "validated" / "all_validated_triples.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "resolved"
DEFAULT_REGISTRY = REPO_ROOT / "config" / "issuer_registry.json"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_EMBED_MODEL = "gemini-embedding-001"
DEFAULT_EMBED_DIM = 768
DEFAULT_SIM = 0.92
DEFAULT_RATE_LIMIT = 10
DEFAULT_MAX_LLM_PAIRS = 400
DEFAULT_EMBED_BATCH = 100

# Observation (per-occurrence) classes: deduped only by exact identity_keys, never
# sent through the fuzzy embedding/LLM stage. Everything else in the schema is a
# resolvable entity. Declared here because schema.json carries no entity/observation
# flag; identity_keys themselves are read from the schema.
OBSERVATION_CLASSES = {
    "KPIObservation", "SustainabilityClaim", "ThirdPartyVerification", "Controversy",
    "Penalty", "MediaReport", "Investment", "CarbonOffsetProject", "ScienceBasedTarget",
    "Emission", "Waste",
}
TEMPORAL_FIELDS = {"valid_from", "valid_to", "is_current", "recorded_at"}


# --------------------------------------------------------------------------- #
# Union-Find.
# --------------------------------------------------------------------------- #
class DSU:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1

    def n_components(self, indices: Optional[List[int]] = None) -> int:
        idxs = indices if indices is not None else range(len(self.parent))
        return len({self.find(i) for i in idxs})


# --------------------------------------------------------------------------- #
# Schema + graph construction.
# --------------------------------------------------------------------------- #
def load_identity_keys(schema: Dict[str, Any]) -> Dict[str, List[str]]:
    return {n["class"]: list(n.get("identity_keys", [])) for n in schema.get("nodes", [])}


def build_graph(triples: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Triples -> ({nodes}, {edges}); identical (class, full-props) nodes are deduped."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    node_map: Dict[Tuple[str, Tuple], int] = {}

    def node_index(side: Dict[str, Any]) -> int:
        cls = side.get("class")
        props = side.get("properties", {}) or {}
        key = (cls, tuple(sorted((k, str(v)) for k, v in props.items())))
        if key not in node_map:
            node_map[key] = len(nodes)
            nodes.append({"class": cls, "properties": props})
        return node_map[key]

    for t in triples:
        subj, obj, pred = t.get("subject"), t.get("object"), t.get("predicate")
        if not isinstance(subj, dict) or not isinstance(obj, dict) or not pred:
            continue
        edge = {"subject": node_index(subj), "predicate": pred, "object": node_index(obj)}
        if "temporal_metadata" in t:
            edge["temporal_metadata"] = t["temporal_metadata"]
        edges.append(edge)
    return nodes, edges


def identity_signature(node: Dict[str, Any], idkeys: Dict[str, List[str]],
                       normalize: bool = False) -> Optional[Tuple]:
    cls = node["class"]
    keys = idkeys.get(cls)
    if not keys:
        return None
    props = node.get("properties", {})
    vals = []
    for k in keys:
        v = str(props.get(k, "")).strip()
        if v.lower() in ("none", "null"):  # JSON null / "None" are not identifiers
            v = ""
        vals.append(normalize_name(v) if normalize else v)
    if all(v == "" for v in vals):
        return None
    return (cls, tuple(vals))


def primary_name(node: Dict[str, Any]) -> str:
    p = node.get("properties", {})
    for k in ("name", "term", "title", "claim_id"):
        if p.get(k):
            return str(p[k])
    return ""


def non_temporal_props(node: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in node.get("properties", {}).items() if k not in TEMPORAL_FIELDS}


def embedding_text(node: Dict[str, Any]) -> str:
    parts = [f"Type: {node['class']}"]
    for k, v in sorted(non_temporal_props(node).items()):
        if v not in (None, ""):
            parts.append(f"{k}: {v}")
    return ". ".join(parts)


def prop_completeness(node: Dict[str, Any]) -> int:
    return sum(1 for v in non_temporal_props(node).values() if v not in (None, ""))


# --------------------------------------------------------------------------- #
# Issuer registry.
# --------------------------------------------------------------------------- #
def load_issuer_index(registry_path: Path) -> Tuple[Dict[str, Tuple[str, str]], int, int]:
    """normalized-name -> (ticker, canonical_name), plus (#aliases, #exclusions)."""
    if not registry_path.exists():
        logger.warning(f"No issuer registry at {registry_path}; skipping issuer anchor.")
        return {}, 0, 0
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    index: Dict[str, Tuple[str, str]] = {}
    n_alias = n_excl = 0
    for ticker, info in reg.items():
        canonical = info.get("canonical_name", ticker)
        excl = {normalize_name(e["name"]) for e in info.get("exclusions", [])}
        n_excl += len(excl)
        for alias in info.get("aliases", []):
            na = normalize_name(alias)
            if na and na not in excl:
                index[na] = (ticker, canonical)
                n_alias += 1
    return index, n_alias, n_excl


# --------------------------------------------------------------------------- #
# Stage C — LLM adjudication.
# --------------------------------------------------------------------------- #
ADJUDICATE_PROMPT = """You are doing entity resolution for a Vietnamese ESG knowledge graph.
Decide whether the two records refer to the SAME real-world entity.

Rules:
- Vietnamese legal forms are equivalent: "CTCP X", "Công ty Cổ phần X", "X JSC",
  "X Joint Stock Company" all denote the SAME company X.
- A Vietnamese name and its English translation can be the SAME entity
  (e.g. "Nhựa Tiền Phong" = "Tien Phong Plastic").
- Different temporal validity does NOT make them different (they may be versions over time).
- They are DIFFERENT when a distinguishing qualifier differs: parent vs subsidiary
  ("An Phát Holdings" vs "Nhựa An Phát Xanh"), a different province
  ("Sở TN&MT tỉnh A" vs "tỉnh B"), or otherwise clearly distinct organizations.

Record 1: Type {cls}; {a}
Record 2: Type {cls}; {b}

Return ONLY JSON: {{"same_entity": true}} or {{"same_entity": false}}."""


def llm_same_entity(a: Dict[str, Any], b: Dict[str, Any], client: genai.Client,
                    model: str, rate_limiter: RateLimiter) -> bool:
    prompt = ADJUDICATE_PROMPT.format(
        cls=a["class"],
        a=json.dumps(non_temporal_props(a), ensure_ascii=False),
        b=json.dumps(non_temporal_props(b), ensure_ascii=False),
    )
    try:
        rate_limiter.wait_if_needed(0)
        resp = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
        )
        text = (resp.text or "").strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return bool(json.loads(m.group(0)).get("same_entity", False))
    except Exception as e:
        logger.warning(f"LLM adjudication failed ({e}); treating as different.")
    return False


# --------------------------------------------------------------------------- #
# Stage B — embeddings.
# --------------------------------------------------------------------------- #
def embed_texts(texts: List[str], client: genai.Client, model: str, dim: int,
                rate_limiter: RateLimiter, batch: int, max_retries: int = 4) -> np.ndarray:
    """Batch-embed with retry. A batch that keeps failing falls back to zero vectors
    (cosine 0 → no false matches) so the output stays aligned with `texts`."""
    out: List[np.ndarray] = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        vecs: Optional[List[np.ndarray]] = None
        for attempt in range(max_retries):
            try:
                rate_limiter.wait_if_needed(0)
                resp = client.models.embed_content(
                    model=model, contents=chunk,
                    config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=dim),
                )
                vecs = []
                for e in resp.embeddings:
                    v = np.asarray(e.values, dtype=np.float32)
                    nrm = np.linalg.norm(v)
                    vecs.append(v / nrm if nrm > 0 else v)
                break
            except Exception as ex:
                logger.warning(f"  embed batch failed (attempt {attempt + 1}/{max_retries}): {ex}")
                time.sleep(2 * (attempt + 1))
        if vecs is None:
            logger.warning(f"  embed batch permanently failed; zero-vectoring {len(chunk)} items")
            vecs = [np.zeros(dim, dtype=np.float32) for _ in chunk]
        out.extend(vecs)
        logger.info(f"  embedded {min(i + batch, len(texts))}/{len(texts)}")
    return np.vstack(out) if out else np.zeros((0, dim), dtype=np.float32)


# --------------------------------------------------------------------------- #
# Stage D — consolidate.
# --------------------------------------------------------------------------- #
def edge_year(edge: Dict[str, Any]) -> str:
    tm = edge.get("temporal_metadata", {}) or {}
    for field in ("valid_from", "recorded_at"):
        m = re.search(r"\d{4}", str(tm.get(field, "")))
        if m:
            return m.group(0)
    return ""


def consolidate(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], dsu: DSU,
                issuer_tag: Dict[int, Tuple[str, str]]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    clusters: Dict[int, List[int]] = defaultdict(list)
    for i in range(len(nodes)):
        clusters[dsu.find(i)].append(i)

    root_to_new: Dict[int, int] = {}
    new_nodes: List[Dict[str, Any]] = []
    for root, idxs in clusters.items():
        members = [nodes[i] for i in idxs]
        tag = issuer_tag.get(root)
        # canonical = issuer's official record if tagged, else most complete then longest name
        canonical = max(members, key=lambda n: (prop_completeness(n), len(primary_name(n))))
        props: Dict[str, Any] = {k: v for k, v in non_temporal_props(canonical).items() if v not in (None, "")}
        for m in members:
            for k, v in non_temporal_props(m).items():
                if k not in props and v not in (None, ""):
                    props[k] = v
        if tag:
            props["ticker"], props["name"] = tag[0], tag[1]

        node: Dict[str, Any] = {"class": canonical["class"], "properties": props}
        if len(members) > 1:
            seen: Set[Tuple] = set()
            versions = []
            for m in members:
                mp = m.get("properties", {})
                sig = (str(mp.get("valid_from")), str(mp.get("valid_to")), str(mp.get("name", primary_name(m))))
                if sig in seen:
                    continue
                seen.add(sig)
                versions.append({
                    "valid_from": mp.get("valid_from"), "valid_to": mp.get("valid_to"),
                    "is_current": mp.get("is_current"), "properties": mp,
                })
            node["temporal_versions"] = versions
        root_to_new[root] = len(new_nodes)
        new_nodes.append(node)

    seen_edges: Set[Tuple] = set()
    new_edges: List[Dict[str, Any]] = []
    for e in edges:
        ns, no = root_to_new[dsu.find(e["subject"])], root_to_new[dsu.find(e["object"])]
        if ns == no:  # self-loop created by merging both endpoints
            continue
        key = (ns, e["predicate"], no, edge_year(e))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        ne = {"subject": ns, "predicate": e["predicate"], "object": no}
        if "temporal_metadata" in e:
            ne["temporal_metadata"] = e["temporal_metadata"]
        new_edges.append(ne)

    stats = {"resolved_nodes": len(new_nodes), "resolved_edges": len(new_edges)}
    return {"nodes": new_nodes, "edges": new_edges}, stats


# --------------------------------------------------------------------------- #
# Driver.
# --------------------------------------------------------------------------- #
def resolve(args: argparse.Namespace) -> None:
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    idkeys = load_identity_keys(schema)
    triples = json.loads(args.input.read_text(encoding="utf-8"))
    logger.info(f"Loaded {len(triples)} validated triples")

    nodes, edges = build_graph(triples)
    n = len(nodes)
    entity_idx = [i for i, x in enumerate(nodes) if x["class"] not in OBSERVATION_CLASSES]
    obs_idx = [i for i in range(n) if nodes[i]["class"] in OBSERVATION_CLASSES]
    logger.info(f"Graph: {n} nodes ({len(entity_idx)} entity, {len(obs_idx)} observation), {len(edges)} edges")

    dsu = DSU(n)

    # ---- Stage A.1: exact identity-key merge (entities + observations) ----
    # Observations whose identity signature collides only because a discriminating
    # key (e.g. source_id) is missing must NOT merge across different titles, or
    # distinct line items ("Cost of goods sold" vs "Financial expenses") fuse.
    groups: Dict[Tuple, List[int]] = defaultdict(list)
    for i in range(n):
        sig = identity_signature(nodes[i], idkeys, normalize=False)
        if sig is not None:
            groups[sig].append(i)
    for idxs in groups.values():
        if nodes[idxs[0]]["class"] in OBSERVATION_CLASSES:
            by_title: Dict[str, List[int]] = defaultdict(list)
            for i in idxs:
                p = nodes[i].get("properties", {})
                by_title[str(p.get("title") or primary_name(nodes[i]) or "").strip().lower()].append(i)
            for grp in by_title.values():
                for j in grp[1:]:
                    dsu.union(grp[0], j)
        else:
            for j in idxs[1:]:
                dsu.union(idxs[0], j)
    after_a1 = dsu.n_components()
    logger.info(f"Stage A.1 identity-key merge: {n} -> {after_a1} nodes")

    # ---- Stage A.2: issuer anchor (frozen) ----
    issuer_index, n_alias, n_excl = load_issuer_index(args.registry)
    issuer_members: List[int] = []
    for i in entity_idx:
        if nodes[i]["class"] != "Organization":
            continue
        if normalize_name(primary_name(nodes[i])) in issuer_index:
            issuer_members.append(i)
    issuer_roots: Set[int] = set()
    issuer_tag: Dict[int, Tuple[str, str]] = {}
    if issuer_members:
        for j in issuer_members[1:]:
            dsu.union(issuer_members[0], j)
        root = dsu.find(issuer_members[0])
        issuer_roots.add(root)
        issuer_tag[root] = issuer_index[normalize_name(primary_name(nodes[issuer_members[0]]))]
    logger.info(f"Stage A.2 issuer anchor: merged {len(issuer_members)} Organization node(s) "
                f"into {len(issuer_roots)} frozen issuer cluster(s) "
                f"(registry: {n_alias} aliases, {n_excl} exclusions)")

    # frozen issuer node indices — excluded from Stages B/C
    frozen = {i for i in entity_idx if dsu.find(i) in issuer_roots}

    # ---- Stage B.1: normalized identity-signature merge (entities, non-issuer) ----
    norm_groups: Dict[Tuple, List[int]] = defaultdict(list)
    for i in entity_idx:
        if i in frozen:
            continue
        sig = identity_signature(nodes[i], idkeys, normalize=True)
        if sig is not None:
            norm_groups[sig].append(i)
    for idxs in norm_groups.values():
        reps = sorted({dsu.find(j) for j in idxs})
        for r in reps[1:]:
            dsu.union(reps[0], r)
    after_b1 = dsu.n_components(entity_idx)
    logger.info(f"Stage B.1 normalized-name merge: entities -> {after_b1} clusters")

    # ---- Stage B.2 + C: embedding blocking + LLM adjudication (entities, non-issuer) ----
    llm_comparisons = llm_matches = 0
    if not args.no_llm:
        load_dotenv(REPO_ROOT / ".env")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error(f"GEMINI_API_KEY not set in {REPO_ROOT / '.env'}; rerun with --no-llm or --dry-run")
            return
        client = genai.Client(api_key=api_key)
        rl = RateLimiter(max_calls_per_minute=args.rate_limit)

        # collect one representative node index per cluster-root, per class
        rep_of_root: Dict[int, int] = {}
        for i in entity_idx:
            if i in frozen:
                continue
            r = dsu.find(i)
            cur = rep_of_root.get(r)
            if cur is None or prop_completeness(nodes[i]) > prop_completeness(nodes[cur]):
                rep_of_root[r] = i
        class_roots: Dict[str, List[int]] = defaultdict(list)
        for r, i in rep_of_root.items():
            class_roots[nodes[i]["class"]].append(r)

        candidates: List[Tuple[float, int, int]] = []  # (sim, rootA, rootB)
        for cls, roots in class_roots.items():
            if len(roots) < 2:
                continue
            texts = [embedding_text(nodes[rep_of_root[r]]) for r in roots]
            logger.info(f"Stage B.2 embedding {len(roots)} '{cls}' clusters")
            embs = embed_texts(texts, client, args.embed_model, args.embed_dim, rl, args.embed_batch)
            sims = embs @ embs.T
            for a in range(len(roots)):
                for b in range(a + 1, len(roots)):
                    s = float(sims[a, b])
                    if s >= args.similarity_threshold:
                        candidates.append((s, roots[a], roots[b]))

        candidates.sort(key=lambda x: -x[0])
        logger.info(f"Stage C: {len(candidates)} candidate pairs >= {args.similarity_threshold} "
                    f"(budget {args.max_llm_pairs})")
        if len(candidates) > 5 * args.max_llm_pairs:
            logger.warning(f"Many more candidates ({len(candidates)}) than the LLM budget "
                           f"({args.max_llm_pairs}); only the highest-similarity pairs are adjudicated. "
                           f"Raise --similarity-threshold and/or --max-llm-pairs for a fuller run.")
        for s, ra, rb in candidates:
            if llm_comparisons >= args.max_llm_pairs:
                logger.info("Reached --max-llm-pairs budget; stopping adjudication.")
                break
            ra, rb = dsu.find(ra), dsu.find(rb)
            if ra == rb or ra in issuer_roots or rb in issuer_roots:
                continue
            llm_comparisons += 1
            if llm_same_entity(nodes[rep_of_root[ra]], nodes[rep_of_root[rb]], client, args.model, rl):
                dsu.union(ra, rb)
                llm_matches += 1
        logger.info(f"Stage C done: {llm_comparisons} comparisons, {llm_matches} merges")
    else:
        logger.info("Stages B.2/C skipped (--no-llm/--dry-run)")

    # ---- Stage D: consolidate ----
    resolved, dstats = consolidate(nodes, edges, dsu, issuer_tag)
    final_entity_clusters = dsu.n_components(entity_idx)
    logger.info(f"Stage D: {n} -> {dstats['resolved_nodes']} nodes, {len(edges)} -> {dstats['resolved_edges']} edges")

    stats = {
        "input": {"triples": len(triples), "graph_nodes": n, "graph_edges": len(edges),
                  "entity_nodes": len(entity_idx), "observation_nodes": len(obs_idx)},
        "stages": {
            "after_identity_key_merge": after_a1,
            "issuer_members_merged": len(issuer_members),
            "issuer_clusters": len(issuer_roots),
            "after_normalized_merge_entities": after_b1,
            "llm_comparisons": llm_comparisons,
            "llm_matches": llm_matches,
            "final_entity_clusters": final_entity_clusters,
        },
        "output": {"resolved_nodes": dstats["resolved_nodes"], "resolved_edges": dstats["resolved_edges"],
                   "node_reduction": n - dstats["resolved_nodes"],
                   "reduction_pct": round((n - dstats["resolved_nodes"]) / n * 100, 1) if n else 0.0},
        "registry": {"aliases": n_alias, "exclusions": n_excl},
        "params": {"similarity_threshold": args.similarity_threshold, "embed_model": args.embed_model,
                   "embed_dim": args.embed_dim, "model": args.model, "no_llm": args.no_llm},
    }

    if args.dry_run:
        logger.info("Dry run — not writing files.\n" + json.dumps(stats, indent=2, ensure_ascii=False))
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "resolved_graph.json").write_text(
        json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out_dir / "resolved_graph_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote {args.out_dir / 'resolved_graph.json'} and resolved_graph_stats.json")
    logger.info("\n=== Summary ===\n" + json.dumps(stats["output"] | stats["stages"], indent=2, ensure_ascii=False))


def main() -> None:
    p = argparse.ArgumentParser(description="Step 4 — entity resolution for the VN ESG temporal graph.")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("-s", "--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("-o", "--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    p.add_argument("--similarity-threshold", type=float, default=DEFAULT_SIM)
    p.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT)
    p.add_argument("--model", type=str, default=DEFAULT_MODEL)
    p.add_argument("--embed-model", type=str, default=DEFAULT_EMBED_MODEL)
    p.add_argument("--embed-dim", type=int, default=DEFAULT_EMBED_DIM)
    p.add_argument("--embed-batch", type=int, default=DEFAULT_EMBED_BATCH)
    p.add_argument("--max-llm-pairs", type=int, default=DEFAULT_MAX_LLM_PAIRS)
    p.add_argument("--no-llm", action="store_true", help="Stages A + B.1 only (no embeddings/LLM)")
    p.add_argument("--dry-run", action="store_true", help="--no-llm and write nothing (offline preview)")
    args = p.parse_args()

    if args.dry_run:
        args.no_llm = True
    if not args.input.exists():
        logger.error(f"Input not found: {args.input} (run fix_invalid_triplets.py first)")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return
    resolve(args)


if __name__ == "__main__":
    main()
