#!/usr/bin/env python3
"""
Step 4 (step05) — entity resolution.

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

MIGRATED FROM ``src/step05_resolve_entities.py`` (14th stage migrated). Confirmed leaf
per PIPELINE.md §2.1: every symbol it imports already lives in ``core/`` —
``REPO_ROOT``/``load_env`` <- ``core.paths``, ``RateLimiter`` <- ``core.llm``,
``date_start_key`` <- ``core.dates``, ``normalize_name`` <- ``core.naming``. One dead
import is dropped: ``src/step05:48`` also imported ``load_schema_sets`` from step03, but
nothing in this file ever calls it (the same "garbage import" shape already found in the
``05d``/``07`` migrations). No logic line differs otherwise.

WHY resolve() IS SPLIT INTO resolve_graph() + main()
Unlike every earlier leaf move, this stage was split at migration time (not as a
follow-up, the way ``fix_triples`` gained ``run_phases()`` only once the ``03`` block was
built): ``resolve_graph()`` is a pure function (no file I/O, no client construction) so
the BLOCK (``esg_kg/resolve/build_resolved.py``, DESIGN.md §5.7) can chain
Stage A-D straight into 05b/05c in memory. ``main()`` keeps the exact CLI/file-write
behaviour of the original script for the standalone `run.py entities` entry point.

THE PAID-PATH CACHE
Stage C (`llm_same_entity`, non-deterministic, costs money) accepts an optional
duck-typed `adjudication_cache` with a `.get(a, b)` / `.put(a, b, value)` interface —
same shape as `fix_triples.run_phases`'s `repairs` parameter. `resolve_graph()` itself
does not know or care what implementation backs it; `main()` (this file, standalone
stage) passes `adjudication_cache=None`, so `python src/run.py entities` behaves
identically to `src/step05_resolve_entities.py` — no caching, exactly as before. Only
the block constructs and passes a real cache (`AdjudicationCache` in
`build_resolved.py`), matching the `03` block precedent that only the paid, non-
deterministic step (there: phase-2 repairs) gets cached — Stage B (embeddings) is
billed but deterministic and, per CLAUDE.md, effectively dormant today (the project runs
with `--no-llm`); an embedding cache is left as a follow-up if Stage B comes back into
regular use.

Run from the repo root:
    python src/run.py entities --dry-run
    python src/run.py entities
Equivalently, from inside src/:  python -m esg_kg.resolve.entities --dry-run

2026-08-04: the additive ``--provider openai`` path (added 2026-07-29 while the Gemini
project behind GEMINI_API_KEY was billing-blocked) was removed outright — this project
now pays only for Gemini, so Stage B/C is gemini-only again, no fallback.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from google.genai import types

from esg_kg.core.dates import date_start_key
from esg_kg.core.llm import DEFAULT_MODEL, RateLimiter, build_gemini_client
from esg_kg.core.naming import normalize_name
from esg_kg.core.paths import REPO_ROOT, load_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

DEFAULT_INPUT = REPO_ROOT / "graph_output" / "validated" / "all_validated_triples.json"
DEFAULT_SCHEMA = REPO_ROOT / "config" / "schema.json"
DEFAULT_OUT_DIR = REPO_ROOT / "graph_output" / "resolved"
DEFAULT_REGISTRY = REPO_ROOT / "config" / "issuer_registry.json"
DEFAULT_STANDARDS_REGISTRY = REPO_ROOT / "config" / "standards_registry.json"
# DEFAULT_MODEL (Stage C adjudication) comes from esg_kg.core.llm (GEMINI_MODEL env
# var, default gemini-2.5-flash-lite) — see that module's docstring.
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

# `subjectToRegulation` (Organization->Regulation) and `adoptsStandard` (Organization->Standard)
# both mean "the company follows this reference document" but the schema locks each to a
# different target class. step02's LLM extraction sometimes picks the wrong one when a single
# document could plausibly read as either (e.g. the voluntary SSC-IFC guide extracted once as a
# "regulation") — the document's TRUE class is only known once Stage A.3's frozen standards
# anchor resolves it (config/standards_registry.json `kind`), which happens here in Stage D, well
# after extraction. Relabeling deterministically at this point — keyed on the node's final
# resolved class, not on what any individual extraction guessed — means the fix holds no matter
# how many times step01-step06 is rerun on fresh data, not just for the mentions seen so far.
DOC_EDGE_EXPECTED_CLASS = {"subjectToRegulation": "Regulation", "adoptsStandard": "Standard"}
DOC_EDGE_SWAP = {"subjectToRegulation": "adoptsStandard", "adoptsStandard": "subjectToRegulation"}


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


def load_standards_index(registry_path: Path) -> Tuple[Dict[str, Tuple[str, str, str]], int, int]:
    """normalized-name -> (doc_key, canonical_name, kind) for Standard/Regulation mentions.

    Same shape and same purpose as load_issuer_index, applied to the five reference documents
    behind the indicator vocabulary (config/standards_registry.json, hand-maintained static
    config). The resulting clusters are FROZEN in Stage A.3, exactly like the issuer, so GRI's
    ≥4 spellings collapse onto one canonical node without ever consulting embeddings or an LLM
    (fixes C3).

    `kind` (registry's authoritative "Standard"/"Regulation" class) rides along so consolidate()
    can force the merged node's `class` — not just its `name` — to match the registry. Without
    this, the merged node's class is whichever member `max(prop_completeness, ...)` happens to
    pick, which can be a mis-extracted mention (e.g. the SSC-IFC guide extracted once as
    "Regulation") and silently produces schema-illegal edges downstream (adoptsStandard/
    issuedBy expect a "Standard" target/source)."""
    if not registry_path.exists():
        logger.warning(f"No standards registry at {registry_path}; skipping standards anchor.")
        return {}, 0, 0
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    index: Dict[str, Tuple[str, str, str]] = {}
    n_alias = n_excl = 0
    for key, info in reg.items():
        canonical = info.get("canonical_name", key)
        kind = info.get("kind", "Standard")
        excl = {normalize_name(e["name"]) for e in info.get("exclusions", [])}
        n_excl += len(excl)
        for alias in info.get("aliases", []):
            na = normalize_name(alias)
            if na and na not in excl:
                index[na] = (key, canonical, kind)
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


def llm_same_entity(a: Dict[str, Any], b: Dict[str, Any], client: Any,
                    model: str, rate_limiter: RateLimiter) -> bool:
    """`client` is a `genai.Client`."""
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
def embed_texts(texts: List[str], client: Any, model: str, dim: int,
                rate_limiter: RateLimiter, batch: int, max_retries: int = 4) -> np.ndarray:
    """Batch-embed with retry. A batch that keeps failing falls back to zero vectors
    (cosine 0 → no false matches) so the output stays aligned with `texts`.

    `client` is a `genai.Client`. Cosine blocking downstream doesn't care which
    produced the (L2-normalized) vectors."""
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
                issuer_tag: Dict[int, Tuple[str, str]],
                standards_tag: Optional[Dict[int, Tuple[str, str]]] = None
                ) -> Tuple[Dict[str, Any], Dict[str, int]]:
    standards_tag = standards_tag or {}
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
        if canonical["class"] in OBSERVATION_CLASSES:
            # P2 (TEMPORAL_KG_DESIGN): event time is an essential property of a
            # T2/T3 observation, not versioning metadata — keep it on the node.
            # T1 entities stay timeless; their history lives in temporal_versions
            # and on edge temporal_metadata.
            cp = canonical.get("properties", {})
            for k in ("valid_from", "valid_to", "is_current"):
                if k in cp:
                    props[k] = cp[k]
        node_class = canonical["class"]
        if tag:
            props["ticker"], props["name"] = tag[0], tag[1]
        elif root in standards_tag:
            # canonical reference document name AND class (no ticker — these are not
            # companies). The class must come from the registry's `kind`, not from whichever
            # member `canonical` happened to pick — a single mis-extracted mention (e.g. the
            # SSC-IFC guide tagged "Regulation" instead of "Standard") must not decide the
            # class of the whole frozen cluster, or adoptsStandard/issuedBy edges pointing at
            # it become schema-illegal (docs/STANDARD_INDICATOR_AXIS.md).
            props["name"], node_class = standards_tag[root]

        node: Dict[str, Any] = {"class": node_class, "properties": props}
        if len(members) > 1:
            # P4: versions are distinct facts, not distinct spellings — compare
            # dates by start instant so "2011" and "2011-01-01" collapse into one
            # version instead of two both claiming is_current=true.
            def _vsig(mp: Dict[str, Any], m: Dict[str, Any]) -> Tuple:
                return (
                    date_start_key(mp.get("valid_from")) or str(mp.get("valid_from")),
                    date_start_key(mp.get("valid_to")) or str(mp.get("valid_to")),
                    str(mp.get("name", primary_name(m))),
                )

            seen: Set[Tuple] = set()
            versions = []
            for m in members:
                mp = m.get("properties", {})
                sig = _vsig(mp, m)
                if sig in seen:
                    continue
                seen.add(sig)
                versions.append({
                    "valid_from": mp.get("valid_from"), "valid_to": mp.get("valid_to"),
                    "is_current": mp.get("is_current"), "properties": mp,
                })

            # P4 invariant: at most one open version may be current. If several
            # claim is_current=true, the latest-starting open version wins; a
            # chain that is all-closed (every valid_to set) legitimately has none.
            current_claims = [v for v in versions if v.get("is_current") is True]
            open_versions = [v for v in versions if v.get("valid_to") in (None, "")]
            if len(current_claims) != 1 and open_versions:
                winner = max(open_versions,
                             key=lambda v: date_start_key(v.get("valid_from")) or "")
                for v in versions:
                    flag = v is winner
                    v["is_current"] = flag
                    if isinstance(v.get("properties"), dict):
                        v["properties"]["is_current"] = flag
            node["temporal_versions"] = versions
        root_to_new[root] = len(new_nodes)
        new_nodes.append(node)

    seen_edges: Set[Tuple] = set()
    new_edges: List[Dict[str, Any]] = []
    doc_edges_relabeled = 0
    for e in edges:
        ns, no = root_to_new[dsu.find(e["subject"])], root_to_new[dsu.find(e["object"])]
        if ns == no:  # self-loop created by merging both endpoints
            continue
        predicate = e["predicate"]
        expected = DOC_EDGE_EXPECTED_CLASS.get(predicate)
        if expected is not None:
            obj_class = new_nodes[no]["class"]
            if obj_class != expected:
                swap = DOC_EDGE_SWAP[predicate]
                if obj_class == DOC_EDGE_EXPECTED_CLASS[swap]:
                    predicate = swap
                    doc_edges_relabeled += 1
        key = (ns, predicate, no, edge_year(e))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        ne = {"subject": ns, "predicate": predicate, "object": no}
        if "temporal_metadata" in e:
            ne["temporal_metadata"] = e["temporal_metadata"]
        new_edges.append(ne)

    stats = {"resolved_nodes": len(new_nodes), "resolved_edges": len(new_edges),
             "doc_edges_relabeled": doc_edges_relabeled}
    return {"nodes": new_nodes, "edges": new_edges}, stats


# --------------------------------------------------------------------------- #
# Driver — pure, no file I/O. Called by main() below and by the resolve BLOCK
# (esg_kg/resolve/build_resolved.py, DESIGN.md §5.7).
# --------------------------------------------------------------------------- #
def resolve_graph(triples: List[Dict[str, Any]], idkeys: Dict[str, List[str]], *,
                  registry_path: Path, standards_registry_path: Path,
                  similarity_threshold: float = DEFAULT_SIM,
                  model: str = DEFAULT_MODEL,
                  embed_model: str = DEFAULT_EMBED_MODEL,
                  embed_dim: int = DEFAULT_EMBED_DIM,
                  embed_batch: int = DEFAULT_EMBED_BATCH,
                  max_llm_pairs: int = DEFAULT_MAX_LLM_PAIRS,
                  no_llm: bool = True,
                  client: Optional[Any] = None,
                  rate_limiter: Optional[RateLimiter] = None,
                  adjudication_cache: Any = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Stage A -> B -> C -> D. Returns (resolved_graph, stats); writes nothing.

    Stage B/C run only when ``no_llm`` is False AND ``client`` is not None — the caller
    (``main()`` below, or the block) is responsible for constructing the client and
    deciding whether the run is offline. ``adjudication_cache``, if given, must expose
    ``.get(a, b) -> (value, found)`` / ``.put(a, b, value)`` (same duck-typed shape as
    ``fix_triples.run_phases``'s ``repairs`` parameter) so Stage C's paid, non-
    deterministic verdicts can be replayed for free on a rerun.

    ``client`` serves both Stage B (embeddings, ``.models.embed_content``) and Stage C
    (adjudication, ``.models.generate_content``) — one Gemini ``genai.Client``, two
    endpoints. There used to be a separate ``embed_client`` parameter for an
    OpenAI-shaped provider that split those into two objects; removed with the OpenAI
    path itself (2026-08-04) since nothing constructs two different clients any more.
    """
    embed_client = client
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
    issuer_index, n_alias, n_excl = load_issuer_index(registry_path)
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

    # ---- Stage A.3: standards anchor (frozen) ----
    # Same mechanism as A.2, applied to the five reference documents. Each doc_key's mentions
    # (GRI's many spellings, TT96 VN/EN, …) collapse onto one canonical node whose name comes
    # from the registry — never from embeddings or an LLM (fixes diagnosis C3).
    std_index, s_alias, s_excl = load_standards_index(standards_registry_path)
    std_members: Dict[str, List[int]] = defaultdict(list)
    for i in entity_idx:
        if nodes[i]["class"] not in ("Standard", "Regulation"):
            continue
        tag = std_index.get(normalize_name(primary_name(nodes[i])))
        if tag is not None:
            std_members[tag[0]].append(i)          # tag[0] = doc_key
    standards_roots: Set[int] = set()
    standards_tag: Dict[int, Tuple[str, str]] = {}
    for key, members in std_members.items():
        for j in members[1:]:
            dsu.union(members[0], j)
        root = dsu.find(members[0])
        standards_roots.add(root)
        _, canonical_name, kind = std_index[normalize_name(primary_name(nodes[members[0]]))]
        standards_tag[root] = (canonical_name, kind)
    logger.info(f"Stage A.3 standards anchor: merged {sum(len(m) for m in std_members.values())} "
                f"Standard/Regulation node(s) into {len(standards_roots)} frozen cluster(s) "
                f"(registry: {s_alias} aliases, {s_excl} exclusions)")

    # frozen node indices (issuer + standards) — excluded from Stages B/C
    anchor_roots = issuer_roots | standards_roots
    frozen = {i for i in entity_idx if dsu.find(i) in anchor_roots}

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

    # ---- Stage B.1b: subsumption merge (partial identity keys) ----
    # Stage B.1 above only merges nodes whose FULL normalized identity_keys tuple is
    # equal, so a mention missing an optional key (e.g. Location "Hải Dương" with no
    # `country`) never joins a mention of the same place that has it filled in
    # (GRAPH_IMPROVEMENT_PLAN.md B1). Two normalized-signature groups merge here when
    # they share the same anchor (first identity key, e.g. `name`) and no OTHER key
    # holds two different non-empty values — i.e. one node's non-empty keys are a
    # subset of the other's. A real conflict (two different non-empty values for the
    # same key, e.g. two different provinces) still blocks the merge.
    anchor_groups: Dict[Tuple[str, str], List[Tuple]] = defaultdict(list)
    for sig in norm_groups:
        cls, vals = sig
        if vals and vals[0]:
            anchor_groups[(cls, vals[0])].append(sig)
    for sigs in anchor_groups.values():
        for i in range(len(sigs)):
            for j in range(i + 1, len(sigs)):
                va, vb = sigs[i][1], sigs[j][1]
                if all(not x or not y or x == y for x, y in zip(va, vb)):
                    dsu.union(dsu.find(norm_groups[sigs[i]][0]), dsu.find(norm_groups[sigs[j]][0]))
    after_b1b = dsu.n_components(entity_idx)
    logger.info(f"Stage B.1b subsumption merge: entities -> {after_b1b} clusters")

    # ---- Stage B.2 + C: embedding blocking + LLM adjudication (entities, non-issuer) ----
    llm_comparisons = llm_matches = 0
    if not no_llm and client is not None:
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
            embs = embed_texts(texts, embed_client, embed_model, embed_dim, rate_limiter, embed_batch)
            sims = embs @ embs.T
            for a in range(len(roots)):
                for b in range(a + 1, len(roots)):
                    s = float(sims[a, b])
                    if s >= similarity_threshold:
                        candidates.append((s, roots[a], roots[b]))

        candidates.sort(key=lambda x: -x[0])
        logger.info(f"Stage C: {len(candidates)} candidate pairs >= {similarity_threshold} "
                    f"(budget {max_llm_pairs})")
        if len(candidates) > 5 * max_llm_pairs:
            logger.warning(f"Many more candidates ({len(candidates)}) than the LLM budget "
                           f"({max_llm_pairs}); only the highest-similarity pairs are adjudicated. "
                           f"Raise similarity_threshold and/or max_llm_pairs for a fuller run.")
        for s, ra, rb in candidates:
            if llm_comparisons >= max_llm_pairs:
                logger.info("Reached max_llm_pairs budget; stopping adjudication.")
                break
            ra, rb = dsu.find(ra), dsu.find(rb)
            if ra == rb or ra in issuer_roots or rb in issuer_roots:
                continue
            llm_comparisons += 1
            a_node, b_node = nodes[rep_of_root[ra]], nodes[rep_of_root[rb]]
            same = None
            if adjudication_cache is not None:
                cached, found = adjudication_cache.get(a_node, b_node)
                if found:
                    same = bool((cached or {}).get("same_entity", False))
            if same is None:
                same = llm_same_entity(a_node, b_node, client, model, rate_limiter)
                if adjudication_cache is not None:
                    adjudication_cache.put(a_node, b_node, {"same_entity": same})
            if same:
                dsu.union(ra, rb)
                llm_matches += 1
        logger.info(f"Stage C done: {llm_comparisons} comparisons, {llm_matches} merges")
    else:
        logger.info("Stages B.2/C skipped (no_llm/no client)")

    # ---- Stage D: consolidate ----
    resolved, dstats = consolidate(nodes, edges, dsu, issuer_tag, standards_tag)
    final_entity_clusters = dsu.n_components(entity_idx)
    logger.info(f"Stage D: {n} -> {dstats['resolved_nodes']} nodes, {len(edges)} -> {dstats['resolved_edges']} edges"
                f" ({dstats['doc_edges_relabeled']} subjectToRegulation/adoptsStandard relabeled"
                f" to match the resolved document's class)")

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
                   "reduction_pct": round((n - dstats["resolved_nodes"]) / n * 100, 1) if n else 0.0,
                   "doc_edges_relabeled": dstats["doc_edges_relabeled"]},
        "registry": {"aliases": n_alias, "exclusions": n_excl},
        "params": {"similarity_threshold": similarity_threshold, "embed_model": embed_model,
                   "embed_dim": embed_dim, "model": model, "no_llm": no_llm},
    }
    return resolved, stats


def main() -> None:
    p = argparse.ArgumentParser(description="Step 4 — entity resolution for the VN ESG temporal graph.")
    p.add_argument("-i", "--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("-s", "--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("-o", "--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    p.add_argument("--standards-registry", type=Path, default=DEFAULT_STANDARDS_REGISTRY,
                   help="Canonical Standard/Regulation registry (frozen anchor; hand-maintained static config).")
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
        logger.error(f"Input not found: {args.input} (run build_validated / step03 first)")
        return
    if not args.schema.exists():
        logger.error(f"Schema not found: {args.schema}")
        return

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    idkeys = load_identity_keys(schema)
    triples = json.loads(args.input.read_text(encoding="utf-8"))
    logger.info(f"Loaded {len(triples)} validated triples")

    client = None
    rate_limiter = None
    model = args.model
    embed_model = args.embed_model
    if not args.no_llm:
        load_env()
        client = build_gemini_client()
        if client is None:
            logger.error(f"GEMINI_API_KEY not set in {REPO_ROOT / '.env'}; rerun with --no-llm or --dry-run")
            return
        rate_limiter = RateLimiter(max_calls_per_minute=args.rate_limit)

    resolved, stats = resolve_graph(
        triples, idkeys,
        registry_path=args.registry, standards_registry_path=args.standards_registry,
        similarity_threshold=args.similarity_threshold, model=model,
        embed_model=embed_model, embed_dim=args.embed_dim, embed_batch=args.embed_batch,
        max_llm_pairs=args.max_llm_pairs, no_llm=args.no_llm,
        client=client, rate_limiter=rate_limiter, adjudication_cache=None,
    )

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


if __name__ == "__main__":
    main()
