#!/usr/bin/env python3
"""
Coverage for `esg_kg.core.llm.GeminiContextCache` (GitHub issue #11).

WHY THIS EXISTS
`extract_triples`, `fix_triples` and `extract` (KPI) each embed a large static block
(`schema.json`, or `kpi_definitions_construction.json`) at the front of every LLM prompt,
byte-identical across many calls in one run. Gemini's explicit context caching
(`client.caches.create` + `cached_content=` on `GenerateContentConfig`) lets the SDK
charge a fraction of the input-token price for that repeated prefix instead of resending
it every time. `GeminiContextCache` is the one place that wraps `client.caches.create`
so the three call sites above don't each reimplement "create once, reuse the handle,
never let a failure break the pipeline."

WHAT THIS IS NOT
Not `esg_kg/core/llm_cache.py`'s `ContentCache` (issue #9) — that dedupes an IDENTICAL
full request to skip a repeat LLM call. This is provider-side: it discounts token cost
for a shared PREFIX across otherwise-different requests. The two are orthogonal.

Offline: no LLM, no network. The stub client's `.caches.create` is a plain Python
callable under test's control (returns an object with `.name`, or raises), so every
arm here runs on a bare clone.

Run from the repo root:

    python test/test_esg_kg_gemini_cache.py
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core import llm as new_llm  # noqa: E402


class _StubCachedContent:
    def __init__(self, name):
        self.name = name


class _StubCaches:
    """Records every create() call; can be told to raise instead of succeeding."""

    def __init__(self, raise_for=None):
        self.calls: list = []
        self._raise_for = raise_for or set()
        self._next_id = 0

    def create(self, *, model, config):
        self.calls.append({"model": model, "contents": config.contents, "ttl": config.ttl})
        if config.contents[0] in self._raise_for:
            raise RuntimeError("simulated caches.create failure")
        self._next_id += 1
        return _StubCachedContent(name=f"cachedContents/stub-{self._next_id}")


class _StubClient:
    def __init__(self, raise_for=None):
        self.caches = _StubCaches(raise_for=raise_for)


class _SpyLimiter:
    def __init__(self):
        self.waited: list = []

    def wait_if_needed(self, client_idx):
        self.waited.append(client_idx)


def test_identical_content_is_memoized():
    """Two get_or_create() calls with byte-identical content -> ONE create() call,
    same cache name returned both times."""
    client = _StubClient()
    cache = new_llm.GeminiContextCache(client, "gemini-2.5-flash")

    name1 = cache.get_or_create("STATIC SCHEMA BLOCK")
    name2 = cache.get_or_create("STATIC SCHEMA BLOCK")

    assert name1 is not None, "cache creation must succeed against a working stub"
    assert name1 == name2, f"identical content must return the same cache name: {name1!r} != {name2!r}"
    assert len(client.caches.calls) == 1, f"expected exactly 1 create() call, got {len(client.caches.calls)}"
    print("     (identical content memoized -> 1 create() call)")


def test_different_content_creates_separate_caches():
    """Two DIFFERENT static blocks (e.g. two documents' company+year headers) must
    each get their own cache — never silently share one."""
    client = _StubClient()
    cache = new_llm.GeminiContextCache(client, "gemini-2.5-flash")

    name_a = cache.get_or_create("HEADER FOR COMPANY A 2023")
    name_b = cache.get_or_create("HEADER FOR COMPANY B 2024")

    assert name_a != name_b, "different content must not collapse onto one cache name"
    assert len(client.caches.calls) == 2, f"expected 2 create() calls, got {len(client.caches.calls)}"
    print("     (distinct content -> distinct caches)")


def test_creation_failure_falls_back_to_none_and_is_memoized():
    """caches.create() raising must not raise OUT of get_or_create() — it returns None
    so the caller falls back to sending the static content inline, uncached. The
    failure itself is memoized: a SECOND call with the same content must not retry
    create() (no hammering a permanently-failing endpoint once per page)."""
    client = _StubClient(raise_for={"BAD BLOCK"})
    cache = new_llm.GeminiContextCache(client, "gemini-2.5-flash")

    name1 = cache.get_or_create("BAD BLOCK")
    name2 = cache.get_or_create("BAD BLOCK")

    assert name1 is None, f"a failed creation must surface as None, got {name1!r}"
    assert name2 is None, f"the memoized failure must still be None, got {name2!r}"
    assert len(client.caches.calls) == 1, (
        f"a failure must be memoized (no retry on the same content), got {len(client.caches.calls)} calls"
    )
    print("     (creation failure -> None, memoized, never retried)")


def test_rate_limiter_is_consulted_before_create():
    """The cache-creation call is itself a Gemini API call — it must go through the
    same shared RateLimiter as every other call in this codebase, not bypass it."""
    client = _StubClient()
    limiter = _SpyLimiter()
    cache = new_llm.GeminiContextCache(client, "gemini-2.5-flash")

    cache.get_or_create("SOME BLOCK", rate_limiter=limiter)

    assert limiter.waited == [0], f"expected wait_if_needed(0) once before create(), got {limiter.waited}"
    print("     (rate limiter consulted before caches.create)")


def test_rate_limiter_not_required():
    """rate_limiter is optional — callers that don't pass one must not crash."""
    client = _StubClient()
    cache = new_llm.GeminiContextCache(client, "gemini-2.5-flash")

    name = cache.get_or_create("NO LIMITER BLOCK")
    assert name is not None
    print("     (no rate_limiter passed -> no crash)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
