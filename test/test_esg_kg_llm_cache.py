#!/usr/bin/env python3
"""
Coverage for the shared content-addressed LLM cache: `esg_kg/core/llm_cache.py`
(GitHub issue #9).

WHY THIS EXISTS
Two hand-written caches already exist with the identical shape — sha256 content key,
JSON persisted, dirty-gated save, corrupt-file-safe load:

    RepairCache        <- esg_kg/graph/build_validated.py  (step03 phase-2 repairs)
    AdjudicationCache   <- esg_kg/resolve/build_resolved.py  (step05 Stage C verdicts)

and the three most expensive LLM stages (`extract`, `extract_triples`,
`claims_vs_conduct`) have NO cache at all. `ContentCache` below is the one shared
module both existing caches are refactored to sit on top of (see
`test_esg_kg_validated_block.py` / `test_esg_kg_resolve_block.py`, which must keep
passing unchanged — that is the "no behaviour change" acceptance criterion, not
re-tested here).

WHAT THIS FILE COVERS
- content-addressed key (dict key order doesn't matter; different content does)
- get/put roundtrip, including the multi-part key shape (`AdjudicationCache`-style
  `(class, a, b)`, not just single-value keys)
- dirty-gated save (a read-only replay must never touch disk)
- disk load (a second instance pointed at the same path sees the first instance's puts)
- corrupt-file recovery (must never crash the pipeline)
- the issue's headline acceptance criterion: two calls with IDENTICAL content in the
  SAME run must reach the underlying (expensive) call exactly once

Offline: no LLM, no Neo4j, no network, no artifacts from `graph_output/` required —
runs on a bare clone.

Run from the repo root:

    python test/test_esg_kg_llm_cache.py
"""

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core import llm_cache  # noqa: E402


def test_key_ignores_dict_key_order_but_not_content():
    a = {"subject": "AAA", "predicate": "reportsKPI", "value": 12.5}
    a_reordered = {"value": 12.5, "predicate": "reportsKPI", "subject": "AAA"}
    b = {"subject": "AAA", "predicate": "reportsKPI", "value": 12.6}

    k_a = llm_cache.ContentCache.key(a)
    k_a_reordered = llm_cache.ContentCache.key(a_reordered)
    k_b = llm_cache.ContentCache.key(b)

    assert k_a == k_a_reordered, "dict key order must not change the content key"
    assert k_a != k_b, "different content must produce a different key"
    print("     (dict key order ignored, content changes still detected)")


def test_key_supports_multi_part_business_keys():
    """AdjudicationCache-shape: key = (class, props_a, props_b), not a single value."""
    k1 = llm_cache.ContentCache.key("Organization", {"name": "AAA Corp"}, {"name": "AAA JSC"})
    k2 = llm_cache.ContentCache.key("Organization", {"name": "AAA Corp"}, {"name": "AAA JSC"})
    k3 = llm_cache.ContentCache.key("Organization", {"name": "AAA Corp"}, {"name": "BBB JSC"})
    assert k1 == k2, "identical multi-part keys must hash identically"
    assert k1 != k3, "changing one part of a multi-part key must change the hash"


def test_get_put_roundtrip_in_memory():
    cache = llm_cache.ContentCache()
    value, hit = cache.get("claim text", "evidence text", "meta")
    assert hit is False and value is None, "an empty cache must never fake a hit"

    cache.put("claim text", "evidence text", "meta", value={"verdict": "supports"})
    value, hit = cache.get("claim text", "evidence text", "meta")
    assert hit is True, "a put() must be visible to a get() with the same parts"
    assert value == {"verdict": "supports"}

    value, hit = cache.get("claim text", "OTHER evidence", "meta")
    assert hit is False, "different content must miss"


def test_save_is_dirty_gated():
    with tempfile.TemporaryDirectory(prefix="esgkg_llmcache_") as td:
        path = Path(td) / "cache.json"
        cache = llm_cache.ContentCache(path)
        assert cache.save() is False, "a read-only cache with nothing new must not write"
        assert not path.exists(), "save() returned False but still wrote a file"

        cache.put("k", value="v")
        assert cache.save() is True, "a dirty cache must write on save()"
        assert path.exists()

        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["version"] == llm_cache.ContentCache.VERSION
        assert len(raw["entries"]) == 1


def test_load_from_disk_sees_a_prior_instance_puts():
    with tempfile.TemporaryDirectory(prefix="esgkg_llmcache_") as td:
        path = Path(td) / "cache.json"
        first = llm_cache.ContentCache(path)
        first.put("a", "b", value=42)
        first.save()

        second = llm_cache.ContentCache(path)
        value, hit = second.get("a", "b")
        assert hit is True, "a fresh instance must load entries a prior instance saved"
        assert value == 42


def test_corrupt_cache_file_recovers_to_empty():
    with tempfile.TemporaryDirectory(prefix="esgkg_llmcache_") as td:
        path = Path(td) / "cache.json"
        path.write_text("{not valid json", encoding="utf-8")

        cache = llm_cache.ContentCache(path)  # must not raise
        value, hit = cache.get("anything")
        assert hit is False
        assert value is None
        cache.put("anything", value="ok")
        value, hit = cache.get("anything")
        assert hit is True and value == "ok"


def test_identical_content_calls_the_underlying_llm_once_per_run():
    cache = llm_cache.ContentCache()
    calls = []

    def fake_llm_call(system, user):
        calls.append((system, user))
        return f"reply for {user!r}"

    def cached_call(system, user):
        value, hit = cache.get(system, user)
        if hit:
            return value
        result = fake_llm_call(system, user)
        cache.put(system, user, value=result)
        return result

    r1 = cached_call("SYS", "same prompt")
    r2 = cached_call("SYS", "same prompt")   # must hit the cache, not the LLM
    r3 = cached_call("SYS", "a different prompt")

    assert r1 == r2, "identical content must return the identical cached reply"
    assert len(calls) == 2, f"expected exactly 2 real call(s) (1 unique + 1 distinct), got {len(calls)}: {calls}"
    print("     (2 identical + 1 distinct call -> exactly 2 real LLM calls)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
