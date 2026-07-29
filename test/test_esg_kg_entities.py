#!/usr/bin/env python3
"""
Old-vs-new equivalence for ONE migration slice:
`src/step05_resolve_entities.py` -> `esg_kg.resolve.entities` (14th stage migrated).

WHY THIS IS A SEPARATE FILE
Same reason as every prior single-stage file (`test_esg_kg_anchor_kpi.py`,
`_provenance.py`, `_align_claims.py`, `_crosscheck.py`, `_issuer.py`, `_extract.py`,
`_neo4j_sync.py`): `test_esg_kg_equivalence.py` covers the kernel and is already past
1,100 lines; this covers step05 end-to-end. The BLOCK this stage feeds into
(`05 -> 05b -> 05c`, DESIGN.md §5.7) has its own file, `test_esg_kg_resolve_block.py`.

WHY step05 NEEDED NO NEW core/ MODULE
Confirmed leaf per PIPELINE.md §2.1: every symbol it imports already lives in `core/` —
`REPO_ROOT`/`load_env` <- `core.paths`, `RateLimiter` <- `core.llm`, `date_start_key` <-
`core.dates`, `normalize_name` <- `core.naming`. One dead import is dropped:
`src/step05:48` also imported `load_schema_sets` from step03, never called anywhere in
the file — the same "garbage import" shape already found in `05d`/`07`.

WHY resolve() IS SPLIT HERE, UNLIKE MOST PRIOR LEAF MOVES
`esg_kg.resolve.entities.resolve_graph()` is a pure function (no file I/O, no client
construction) so `esg_kg/resolve/build_resolved.py` (the 05->05b->05c block) can chain
Stage A-D straight into 05b/05c in memory. `src/step05_resolve_entities.resolve(args)`
has no such split (and no return value at all) — it always writes to disk (or, with
`--dry-run`, only logs). So the comparison technique differs by stage: the OLD side is
driven through its real `resolve(args)` and the result is read back from the file it
wrote; the NEW side calls `resolve_graph()` directly and compares the returned dict.

HOW THE PAID BRANCH (Stage B embeddings + Stage C adjudication) IS COVERED WITHOUT PAYING
Same technique as `03` phase 2 / `05d` / `07` / `01`: inject a stub in front of the real
client. Here that is `google.genai.Client` itself (step05 has no `_Provider` abstraction,
same as step01) — for the OLD tree, `src/step05_resolve_entities.py`'s own `genai.Client`
attribute is monkeypatched (mirrors `test_esg_kg_extract.py`'s `_make_extractor`); for the
NEW tree, `resolve_graph()` takes an already-constructed `client` argument, so the fake is
simply passed in directly — no monkeypatching needed, a direct benefit of the split.
The fake `embed_content` returns an identical unit vector for every text (cosine == 1.0,
so every candidate pair clears the similarity threshold deterministically); the fake
`generate_content` answers `same_entity` from the parity of a CRC of the prompt, so both
trees see identical verdicts for identical inputs.

Offline: no real Gemini call, no network. `GEMINI_API_KEY` is set to a dummy value only
so the OLD tree's own "is a key configured" check does not abort first.

Run from the repo root:

    python test/test_esg_kg_entities.py
"""

import json
import logging
import sys
import tempfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ script --------------------------------------------------
import step05_resolve_entities as old_entities  # noqa: E402

# --- new: the esg_kg package -----------------------------------------------------
from esg_kg.resolve import entities as new_entities  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
DEFAULT_INPUT = REPO / "graph_output" / "validated" / "all_validated_triples.json"
DEFAULT_ISSUER_REGISTRY = REPO / "config" / "issuer_registry.json"
DEFAULT_STANDARDS_REGISTRY = REPO / "config" / "standards_registry.json"

VN_NAME = "CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT"
EN_NAME = "An Phat Green Environment and Plastic Joint Stock Company"

_skips: list = []
_cache: dict = {}


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def _quiet():
    root = logging.getLogger()
    prev = root.level
    root.setLevel(logging.ERROR)
    return prev


def _unquiet(prev) -> None:
    logging.getLogger().setLevel(prev)


def load_schema() -> dict:
    if "schema" not in _cache:
        _cache["schema"] = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return _cache["schema"]


# --------------------------------------------------------------------------- #
# Part A — module surface: constants + pure helpers
# --------------------------------------------------------------------------- #
def test_constants_match():
    for name in ("DEFAULT_MODEL", "DEFAULT_EMBED_MODEL", "DEFAULT_EMBED_DIM",
                "DEFAULT_SIM", "DEFAULT_RATE_LIMIT", "DEFAULT_MAX_LLM_PAIRS",
                "DEFAULT_EMBED_BATCH", "OBSERVATION_CLASSES", "TEMPORAL_FIELDS",
                "DOC_EDGE_EXPECTED_CLASS", "DOC_EDGE_SWAP", "ADJUDICATE_PROMPT"):
        a, b = getattr(new_entities, name), getattr(old_entities, name)
        assert a == b, f"{name} diverged: new={a!r} old={b!r}"


def test_dsu_matches():
    for n in (1, 5, 20):
        new_dsu, old_dsu = new_entities.DSU(n), old_entities.DSU(n)
        pairs = [(i, (i * 3 + 1) % n) for i in range(n)]
        for a, b in pairs:
            new_dsu.union(a, b)
            old_dsu.union(a, b)
        assert new_dsu.parent == old_dsu.parent or \
            [new_dsu.find(i) for i in range(n)] == [old_dsu.find(i) for i in range(n)]
        assert new_dsu.n_components() == old_dsu.n_components()


def test_identity_signature_and_primary_name_match():
    schema = load_schema()
    idkeys = new_entities.load_identity_keys(schema)
    assert idkeys == old_entities.load_identity_keys(schema)
    nodes = [
        {"class": "Organization", "properties": {"name": VN_NAME}},
        {"class": "Organization", "properties": {"name": "  "}},
        {"class": "KPIObservation", "properties": {"kpi_type": "x", "source_id": "s1", "value": 5}},
    ]
    for node in nodes:
        for normalize in (False, True):
            a = new_entities.identity_signature(node, idkeys, normalize=normalize)
            b = old_entities.identity_signature(node, idkeys, normalize=normalize)
            assert a == b, f"diverged for {node} normalize={normalize}: new={a} old={b}"
        assert new_entities.primary_name(node) == old_entities.primary_name(node)
        assert new_entities.non_temporal_props(node) == old_entities.non_temporal_props(node)
        assert new_entities.embedding_text(node) == old_entities.embedding_text(node)
        assert new_entities.prop_completeness(node) == old_entities.prop_completeness(node)


def test_build_graph_and_consolidate_match_on_a_synthetic_fixture():
    triples = [
        {"subject": {"class": "Organization", "properties": {"name": VN_NAME, "valid_from": "2023"}},
         "predicate": "ownsFacility",
         "object": {"class": "Facility", "properties": {"name": "Nhà máy 1", "valid_from": "2023"}},
         "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023"}},
        {"subject": {"class": "Organization", "properties": {"name": VN_NAME, "valid_from": "2024"}},
         "predicate": "ownsFacility",
         "object": {"class": "Facility", "properties": {"name": "Nhà máy 1", "valid_from": "2024"}},
         "temporal_metadata": {"valid_from": "2024", "valid_to": None, "recorded_at": "2024"}},
    ]
    import copy
    new_nodes, new_edges = new_entities.build_graph(copy.deepcopy(triples))
    old_nodes, old_edges = old_entities.build_graph(copy.deepcopy(triples))
    assert new_nodes == old_nodes and new_edges == old_edges

    schema = load_schema()
    idkeys = new_entities.load_identity_keys(schema)
    n = len(new_nodes)
    new_dsu, old_dsu = new_entities.DSU(n), old_entities.DSU(n)
    groups: dict = {}
    for i in range(n):
        sig = new_entities.identity_signature(new_nodes[i], idkeys)
        groups.setdefault(sig, []).append(i)
    for idxs in groups.values():
        for j in idxs[1:]:
            new_dsu.union(idxs[0], j)
            old_dsu.union(idxs[0], j)
    new_resolved, new_stats = new_entities.consolidate(new_nodes, new_edges, new_dsu, {})
    old_resolved, old_stats = old_entities.consolidate(old_nodes, old_edges, old_dsu, {})
    assert new_resolved == old_resolved, "consolidate() diverged on the synthetic fixture"
    assert new_stats == old_stats


# --------------------------------------------------------------------------- #
# Part B — the real corpus, Stage A/B.1/D only (no_llm=True — today's real
# operating mode per CLAUDE.md: "Gemini is currently billing-blocked").
# --------------------------------------------------------------------------- #
def test_resolve_graph_matches_src_on_the_real_corpus_no_llm():
    if not DEFAULT_INPUT.exists():
        return _skip("real corpus no_llm", f"{DEFAULT_INPUT} not present (bare clone)")
    schema = load_schema()
    idkeys = new_entities.load_identity_keys(schema)
    triples = json.loads(DEFAULT_INPUT.read_text(encoding="utf-8"))

    prev = _quiet()
    try:
        new_resolved, new_stats = new_entities.resolve_graph(
            triples, idkeys,
            registry_path=DEFAULT_ISSUER_REGISTRY, standards_registry_path=DEFAULT_STANDARDS_REGISTRY,
            no_llm=True, client=None, rate_limiter=None, adjudication_cache=None,
        )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            args = old_entities.argparse.Namespace(
                input=DEFAULT_INPUT, schema=SCHEMA_FILE, out_dir=out_dir,
                registry=DEFAULT_ISSUER_REGISTRY, standards_registry=DEFAULT_STANDARDS_REGISTRY,
                similarity_threshold=old_entities.DEFAULT_SIM, rate_limit=old_entities.DEFAULT_RATE_LIMIT,
                model=old_entities.DEFAULT_MODEL, embed_model=old_entities.DEFAULT_EMBED_MODEL,
                embed_dim=old_entities.DEFAULT_EMBED_DIM, embed_batch=old_entities.DEFAULT_EMBED_BATCH,
                max_llm_pairs=old_entities.DEFAULT_MAX_LLM_PAIRS, no_llm=True, dry_run=False,
            )
            old_entities.resolve(args)
            old_resolved = json.loads((out_dir / "resolved_graph.json").read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert new_resolved == old_resolved, "resolved graph diverged on the real corpus (no_llm)"
    assert len(new_resolved["nodes"]) > 1000, "arm is vacuous: too few nodes"
    print(f"     ({len(new_resolved['nodes'])} nodes / {len(new_resolved['edges'])} edges, "
          f"no_llm=True — identical)")


# --------------------------------------------------------------------------- #
# Part C — the paid path (Stage B embeddings + Stage C adjudication), driven by
# a stub over google.genai.Client, on a synthetic near-duplicate-org fixture.
# --------------------------------------------------------------------------- #
class _FakeEmbedding:
    def __init__(self, values):
        self.values = values


class _FakeEmbedResponse:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class _FakeGenResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, calls_seen):
        self._calls_seen = calls_seen

    def embed_content(self, model, contents, config):
        self._calls_seen.append(("embed", model, tuple(contents)))
        dim = config.output_dimensionality
        vec = [1.0] + [0.0] * (dim - 1)
        return _FakeEmbedResponse([_FakeEmbedding(list(vec)) for _ in contents])

    def generate_content(self, model, contents, config):
        self._calls_seen.append(("generate", model, contents))
        same = zlib.crc32(contents.encode("utf-8")) % 2 == 0
        return _FakeGenResponse(json.dumps({"same_entity": same}))


class _FakeClient:
    def __init__(self, api_key=None):
        self.calls_seen: list = []
        self.models = _FakeModels(self.calls_seen)


def _near_duplicate_org_fixture():
    """Two spellings of the same org (VN vs EN translation) that Stage A/B.1 will NOT
    merge (different identity signature, no shared normalized tokens), so they must
    reach Stage B.2/C to be resolved — exactly the property this arm needs."""
    triples = [
        {"subject": {"class": "Organization",
                     "properties": {"name": VN_NAME, "valid_from": "2023", "valid_to": None, "is_current": True}},
         "predicate": "ownsFacility", "object": {"class": "Facility",
                     "properties": {"name": "Nhà máy An Phát", "valid_from": "2023", "valid_to": None, "is_current": True}},
         "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023"}},
        {"subject": {"class": "Organization",
                     "properties": {"name": EN_NAME, "valid_from": "2023", "valid_to": None, "is_current": True}},
         "predicate": "ownsFacility", "object": {"class": "Facility",
                     "properties": {"name": "An Phat Factory", "valid_from": "2023", "valid_to": None, "is_current": True}},
         "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023"}},
    ]
    return triples


def test_paid_path_matches_across_trees_on_a_synthetic_fixture():
    import os
    os.environ.setdefault("GEMINI_API_KEY", "test-stub-key")
    schema = load_schema()
    idkeys = new_entities.load_identity_keys(schema)
    triples = _near_duplicate_org_fixture()
    missing_registry = REPO / "config" / "__no_such_registry__.json"

    prev = _quiet()
    try:
        # --- new tree: pass the fake client straight to the pure function ---------
        new_client = _FakeClient()
        new_resolved, new_stats = new_entities.resolve_graph(
            triples, idkeys, registry_path=missing_registry, standards_registry_path=missing_registry,
            no_llm=False, client=new_client, rate_limiter=old_entities.RateLimiter(max_calls_per_minute=1000),
            adjudication_cache=None,
        )

        # --- old tree: monkeypatch genai.Client, drive through the real resolve() -
        original_client_cls = old_entities.genai.Client
        old_entities.genai.Client = _FakeClient
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_dir = Path(tmp)
                input_file = out_dir / "triples.json"
                input_file.write_text(json.dumps(triples, ensure_ascii=False), encoding="utf-8")
                args = old_entities.argparse.Namespace(
                    input=input_file, schema=SCHEMA_FILE, out_dir=out_dir,
                    registry=missing_registry, standards_registry=missing_registry,
                    similarity_threshold=old_entities.DEFAULT_SIM, rate_limit=1000,
                    model=old_entities.DEFAULT_MODEL, embed_model=old_entities.DEFAULT_EMBED_MODEL,
                    embed_dim=old_entities.DEFAULT_EMBED_DIM, embed_batch=old_entities.DEFAULT_EMBED_BATCH,
                    max_llm_pairs=old_entities.DEFAULT_MAX_LLM_PAIRS, no_llm=False, dry_run=False,
                )
                old_entities.resolve(args)
                old_resolved = json.loads((out_dir / "resolved_graph.json").read_text(encoding="utf-8"))
        finally:
            old_entities.genai.Client = original_client_cls
    finally:
        _unquiet(prev)

    assert new_stats["stages"]["llm_comparisons"] > 0, "arm is vacuous: Stage C never ran"
    assert new_resolved == old_resolved, "paid-path result diverged between trees"
    print(f"     (llm_comparisons={new_stats['stages']['llm_comparisons']}, "
          f"llm_matches={new_stats['stages']['llm_matches']} — identical both trees)")


def test_adjudication_cache_is_reused_on_a_rerun():
    """New-tree-only property (the OLD stage has no cache parameter at all): a second
    call with the same cache object must not call the client again, and must produce
    the identical merge decision."""
    schema = load_schema()
    idkeys = new_entities.load_identity_keys(schema)
    triples = _near_duplicate_org_fixture()
    missing_registry = REPO / "config" / "__no_such_registry__.json"

    class _DictCache:
        def __init__(self):
            self.entries = {}

        @staticmethod
        def _key(a, b):
            blob = json.dumps({"class": a["class"], "a": new_entities.non_temporal_props(a),
                               "b": new_entities.non_temporal_props(b)}, sort_keys=True, ensure_ascii=False)
            return zlib.crc32(blob.encode("utf-8"))

        def get(self, a, b):
            k = self._key(a, b)
            if k in self.entries:
                return self.entries[k], True
            return None, False

        def put(self, a, b, value):
            self.entries[self._key(a, b)] = value

    prev = _quiet()
    try:
        cache = _DictCache()
        client1 = _FakeClient()
        r1, s1 = new_entities.resolve_graph(
            triples, idkeys, registry_path=missing_registry, standards_registry_path=missing_registry,
            no_llm=False, client=client1, rate_limiter=old_entities.RateLimiter(max_calls_per_minute=1000),
            adjudication_cache=cache,
        )
        assert any(c[0] == "generate" for c in client1.calls_seen), "first run never called the LLM"

        client2 = _FakeClient()
        r2, s2 = new_entities.resolve_graph(
            triples, idkeys, registry_path=missing_registry, standards_registry_path=missing_registry,
            no_llm=False, client=client2, rate_limiter=old_entities.RateLimiter(max_calls_per_minute=1000),
            adjudication_cache=cache,
        )
    finally:
        _unquiet(prev)

    generate_calls_2 = [c for c in client2.calls_seen if c[0] == "generate"]
    assert generate_calls_2 == [], f"second run called the LLM again ({generate_calls_2})"
    assert r1 == r2, "cached rerun produced a different resolved graph"
    print(f"     (run 1 called generate_content {sum(1 for c in client1.calls_seen if c[0] == 'generate')}x, "
          f"run 2 called it 0x)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
    if _skips:
        print(f"{len(_skips)} arm(s) skipped (missing local artifacts):")
        for s in _skips:
            print(f"  - {s}")
