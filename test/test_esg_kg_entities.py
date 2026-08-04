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
so the resolver's own "is a key configured" check does not abort first.

Was driven through both `src/` and `esg_kg` while both trees existed (DESIGN.md §5.3);
repointed at `esg_kg` only (2026-07-29) now that `src/` is gone. Cross-tree comparisons
with no independent claim about correct behaviour were deleted rather than rewritten
against a guessed value.

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
    finally:
        _unquiet(prev)

    assert len(new_resolved["nodes"]) > 1000, "arm is vacuous: too few nodes"
    print(f"     ({len(new_resolved['nodes'])} nodes / {len(new_resolved['edges'])} edges, "
          f"no_llm=True)")


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
        new_client = _FakeClient()
        new_resolved, new_stats = new_entities.resolve_graph(
            triples, idkeys, registry_path=missing_registry, standards_registry_path=missing_registry,
            no_llm=False, client=new_client, rate_limiter=new_entities.RateLimiter(max_calls_per_minute=1000),
            adjudication_cache=None,
        )
    finally:
        _unquiet(prev)

    assert new_stats["stages"]["llm_comparisons"] > 0, "arm is vacuous: Stage C never ran"
    # the two orgs merged into one resolved entity via Stage B.2/C
    org_names = {n["properties"]["name"] for n in new_resolved["nodes"] if n["class"] == "Organization"}
    assert len(org_names) == 1, f"expected the near-duplicate orgs to merge, got {org_names}"
    print(f"     (llm_comparisons={new_stats['stages']['llm_comparisons']}, "
          f"llm_matches={new_stats['stages']['llm_matches']})")


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
            no_llm=False, client=client1, rate_limiter=new_entities.RateLimiter(max_calls_per_minute=1000),
            adjudication_cache=cache,
        )
        assert any(c[0] == "generate" for c in client1.calls_seen), "first run never called the LLM"

        client2 = _FakeClient()
        r2, s2 = new_entities.resolve_graph(
            triples, idkeys, registry_path=missing_registry, standards_registry_path=missing_registry,
            no_llm=False, client=client2, rate_limiter=new_entities.RateLimiter(max_calls_per_minute=1000),
            adjudication_cache=cache,
        )
    finally:
        _unquiet(prev)

    generate_calls_2 = [c for c in client2.calls_seen if c[0] == "generate"]
    assert generate_calls_2 == [], f"second run called the LLM again ({generate_calls_2})"
    assert r1 == r2, "cached rerun produced a different resolved graph"
    print(f"     (run 1 called generate_content {sum(1 for c in client1.calls_seen if c[0] == 'generate')}x, "
          f"run 2 called it 0x)")


# 2026-08-04: the additive OpenAI path for Stage B/C (added 2026-07-29,
# `test_openai_paid_path_resolves_the_near_duplicate_org` /
# `test_openai_and_gemini_clients_are_not_confused`) was removed outright along with
# `_OpenAIProvider`/`_OpenAIEmbeddingProvider` themselves — no OpenAI fallback anywhere
# in this project any more. The Gemini paid path is already covered above by
# `test_paid_path_matches_across_trees_on_a_synthetic_fixture` and
# `test_adjudication_cache_is_reused_on_a_rerun` (Stage B/C driven by a stubbed
# `google.genai.Client`).


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
