#!/usr/bin/env python3
"""
Behaviour tests for ONE migration slice:
`esg_kg.kpi.extract` + `esg_kg.core.io_jsonl` (ported from
`src/step01_extract_kpi_from_jsonl.py`).

WHY THIS IS A SEPARATE FILE
Same reason as `test_esg_kg_anchor_kpi.py` / `_provenance.py` / `_align_claims.py`:
`test_esg_kg_equivalence.py` covers the kernel and is already past 1,100 lines, while this
covers a single stage end-to-end.

WHY step01 WAS THE LAST HUB, AND WHAT core/io_jsonl.py IS
Per PIPELINE.md §2.1 point 3, step01 was the only remaining stage still imported for its OWN
stage-local symbols (not ones already lifted to `core/`): step02 took 5 helpers straight off
it. Those five — `load_pages_from_jsonl`, `build_page_text`, `page_has_esg`,
`select_documents`, `parse_company_year_from_filename` — are exactly what `core/io_jsonl.py`
lifts. They are pure (no network, no LLM), so the arm below for them is free and runs on the
real corpus.

WHY THIS SLICE NEEDED NO OTHER core/ MODULE
step01 does not use `_Provider`/`_GeminiProvider` at all — it talks to Gemini directly via
`google.genai.Client`, though since 2026-08-04 it gets that client from
`core.llm.build_gemini_client()` (the shared constructor `simplify` factored out of six
near-identical getenv/construct blocks) rather than calling `genai.Client(...)` inline.
`KPIExtractor`, its prompt, its JSON schema and `normalize_kpi_response` all stay
stage-local; only the 5 IO helpers and the client constructor come from `core/`.

HOW THE PAID BRANCH IS COVERED WITHOUT PAYING
Same technique as step03 phase 2 / step05d / step07: inject a STUB over the client the stage
constructs — here that means monkeypatching `build_gemini_client` itself to return a fake
client, answering deterministically from a CRC of the prompt text, walking multiple response
shapes the parser must survive: clean JSON, a non-STOP `finish_reason` (must return `[]`),
and empty text (must return `[]`).

Offline: no real Gemini call, no network, no GEMINI_API_KEY required (the stub replaces
`build_gemini_client` before any request is built; a dummy key is set only so
`KPIExtractor.__init__`'s presence check does not abort first). `data/labeled/annual_labeled/`
and `kpi_output/` are git-ignored (shipped via the HF snapshot) — arms needing them SKIP with
a message on a bare clone.

Was driven through both `src/` and `esg_kg` while both trees existed (DESIGN.md §5.3);
repointed at `esg_kg` only (2026-07-29) now that `src/` is gone. Several tests here used to
be nothing but a `new == old` comparison with no independently recorded expected value
(constant pins, `normalize_kpi_response` cases, `_build_prompt` text, `select_documents`
scope flags, `parse_company_year_from_filename` cases, `build_page_text`/`page_has_esg`
cases) — those were removed rather than guessed at (see the report for this migration).
Every surviving test still makes a concrete claim about `esg_kg`'s own behaviour that does
not depend on the deleted old tree.

Run from the repo root:

    python test/test_esg_kg_extract.py
"""

import json
import logging
import os
import shutil
import sys
import tempfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core import io_jsonl as core_io_jsonl  # noqa: E402
from esg_kg.core import llm as core_llm  # noqa: E402
from esg_kg.kpi import extract as new_extract  # noqa: E402

DEFAULT_INPUT = REPO / "data" / "labeled" / "annual_labeled" / "labeled_annual_report_company_aaa.jsonl"

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


class _LogCatcher(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_new_tree_imports_the_kernel_rather_than_recopying():
    """A migrated stage must USE core/, not carry its own copy — otherwise the two drift."""
    assert new_extract.load_pages_from_jsonl is core_io_jsonl.load_pages_from_jsonl
    assert new_extract.build_page_text is core_io_jsonl.build_page_text
    assert new_extract.page_has_esg is core_io_jsonl.page_has_esg
    assert new_extract.select_documents is core_io_jsonl.select_documents
    assert new_extract.parse_company_year_from_filename is core_io_jsonl.parse_company_year_from_filename


def test_load_pages_from_jsonl_real_corpus():
    if not DEFAULT_INPUT.exists():
        _skip("test_load_pages_from_jsonl_real_corpus", f"{DEFAULT_INPUT} not present (bare clone)")
        return
    new_docs = core_io_jsonl.load_pages_from_jsonl(DEFAULT_INPUT)
    assert len(new_docs) > 0, "arm is vacuous: no documents loaded"

    total_pages = 0
    for src in new_docs:
        for page, rows in new_docs[src].items():
            text = core_io_jsonl.build_page_text(rows)
            assert isinstance(text, str)
            assert isinstance(core_io_jsonl.page_has_esg(rows), bool)
            total_pages += 1
    assert total_pages > 0, "arm is vacuous: no pages loaded"
    print(f"  (loaded {len(new_docs)} document(s) / {total_pages} page(s) from the real corpus)")


def test_kpi_schema_has_the_shape_the_paid_request_depends_on():
    """`KPI_SCHEMA` IS the paid request contract: a silently-dropped field still "works"
    while Gemini stops returning it. Pinned directly (no old-tree oracle needed — this is
    the schema the stub client below also asserts got wired into the request)."""
    assert new_extract.KPI_SCHEMA["type"] == "object"
    assert "kpis" in new_extract.KPI_SCHEMA["properties"]
    assert new_extract.DEFAULT_MODEL
    assert new_extract.SECTOR


def test_build_prompt_is_deterministic_and_carries_the_kpi_defs():
    new_ex = new_extract.KPIExtractor.__new__(new_extract.KPIExtractor)
    new_ex.kpi_defs = [{"id": "TT96-1", "definition": "d1"}, {"id": "TT96-2", "definition": "d2"}]
    new_ex.defs_text = "\n".join(f"{d['id']}: {d['definition']}" for d in new_ex.kpi_defs)
    new_ex.cache_name = None  # __new__ bypasses __init__, which normally sets this
    system, user = new_ex._build_prompt(
        "Công ty đã giảm phát thải 20% trong năm 2023.", "AAA", new_extract.SECTOR, 5, "AAA_2023.pdf")
    assert "TT96-1" in user and "TT96-2" in user, "KPI definitions must reach the prompt"
    assert "AAA" in system
    assert "Công ty đã giảm phát thải 20%" in user
    system2, user2 = new_ex._build_prompt(
        "Công ty đã giảm phát thải 20% trong năm 2023.", "AAA", new_extract.SECTOR, 5, "AAA_2023.pdf")
    assert (system, user) == (system2, user2)


class _FakeFinishReason:
    def __init__(self, name):
        self.name = name


class _FakeCandidate:
    def __init__(self, finish_name):
        self.finish_reason = _FakeFinishReason(finish_name) if finish_name else None


class _FakeResponse:
    def __init__(self, text, finish_name="STOP"):
        self.text = text
        self.candidates = [_FakeCandidate(finish_name)] if finish_name else []


class _FakeCachedContent:
    def __init__(self, name):
        self.name = name


class _FakeCaches:
    """Stub for `client.caches` (issue #11 / `GeminiContextCache`, core/llm.py)."""

    def __init__(self, raise_always=False):
        self.calls: list = []
        self._raise_always = raise_always
        self._next_id = 0

    def create(self, *, model, config):
        self.calls.append({"model": model, "contents": config.contents})
        if self._raise_always:
            raise RuntimeError("simulated caches.create failure")
        self._next_id += 1
        return _FakeCachedContent(name=f"cachedContents/stub-{self._next_id}")


class _FakeModels:
    def __init__(self, calls_seen):
        self._calls_seen = calls_seen

    def generate_content(self, model, contents, config):
        self._calls_seen.append({
            "model": model,
            "contents": contents,
            "system_instruction": config.system_instruction,
            "response_mime_type": config.response_mime_type,
            "response_schema": config.response_schema,
            "temperature": config.temperature,
            "max_output_tokens": config.max_output_tokens,
            "cached_content": config.cached_content,
        })
        crc = zlib.crc32(contents.encode("utf-8"))
        shape = crc % 4
        if shape == 0:
            kpis = [{
                "kpi_type": "other", "title": "t", "observations": [],
                "page": 1, "doc_name": "d", "company": "c", "sector": "s",
            }]
            return _FakeResponse(json.dumps({"kpis": kpis}))
        if shape == 1:
            return _FakeResponse(json.dumps({"kpis": []}))
        if shape == 2:
            return _FakeResponse("", finish_name="STOP")  # empty text -> []
        return _FakeResponse(json.dumps({"kpis": []}), finish_name="SAFETY")  # non-STOP -> []


class _FakeClient:
    def __init__(self, api_key=None, raise_caches=False):
        self.calls_seen: list = []
        self.models = _FakeModels(self.calls_seen)
        self.caches = _FakeCaches(raise_always=raise_caches)


def _make_extractor(mod, defs_path, raise_caches=False, use_context_cache=True):
    os.environ.setdefault("GEMINI_API_KEY", "test-stub-key")
    original_builder = mod.build_gemini_client
    mod.build_gemini_client = lambda api_key=None: _FakeClient(raise_caches=raise_caches)
    try:
        return mod.KPIExtractor(defs_path, model="gemini-2.5-flash",
                                use_context_cache=use_context_cache)
    finally:
        mod.build_gemini_client = original_builder


def _tiny_defs(tmp_dir: Path) -> Path:
    path = tmp_dir / "defs.json"
    path.write_text(json.dumps([{"id": "TT96-1", "definition": "energy"}]), encoding="utf-8")
    return path


def test_extract_page_survives_all_stub_response_shapes():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_"))
    try:
        defs_path = _tiny_defs(tmp)
        texts = [
            "Chúng tôi đã giảm phát thải 20% trong năm 2023.",
            "boilerplate page text with no ESG content",
            "",
            "x" * 500,
        ]
        new_ex = _make_extractor(new_extract, defs_path)
        for i, text in enumerate(texts):
            out = new_ex.extract_page(text, "AAA", new_extract.SECTOR, i, "doc.pdf")
            assert isinstance(out, list), f"extract_page must return a list, got {type(out)!r}"

        assert len(new_ex.client.calls_seen) == len(texts)
        for call in new_ex.client.calls_seen:
            assert call["temperature"] == 0
            assert call["response_mime_type"] == "application/json"
            assert call["response_schema"] == new_extract.KPI_SCHEMA
            if call["cached_content"] is not None:
                assert call["system_instruction"] is None, (
                    "cached_content and system_instruction must never both be set"
                )
                assert "ESG-KPI-EXTRACTOR-V2" in call["contents"], (
                    "instructions must be folded into contents when cached"
                )
            else:
                assert call["system_instruction"], "system_instruction must not be empty"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_document_skips_non_esg_pages_and_is_idempotent():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_doc_"))
    try:
        defs_path = _tiny_defs(tmp)
        pages = {
            1: [(0, "Chúng tôi cam kết giảm phát thải khí nhà kính.", True)],
            2: [(0, "Không có nội dung ESG ở trang này.", False)],
            3: [(0, "", False)],  # empty page text -> [] without calling the client
        }
        new_out = tmp / "new_out"
        new_ex = _make_extractor(new_extract, defs_path)

        new_total = new_ex.process_document("AAA_2023.pdf", pages, new_out, esg_only=True, max_workers=1)

        new_files = sorted(p.name for p in (new_out / "AAA_2023_kpis").glob("*.json"))
        assert new_files == [
            "page_001_kpis.json", "page_002_kpis.json", "page_003_kpis.json"], new_files

        page1 = json.loads((new_out / "AAA_2023_kpis" / "page_001_kpis.json").read_text(encoding="utf-8"))
        page2 = json.loads((new_out / "AAA_2023_kpis" / "page_002_kpis.json").read_text(encoding="utf-8"))
        page3 = json.loads((new_out / "AAA_2023_kpis" / "page_003_kpis.json").read_text(encoding="utf-8"))
        assert isinstance(page1, list)
        assert page2 == [], "non-ESG page (esg_only=True) must write an empty list without calling the client"
        assert page3 == [], "empty-text page must write an empty list without calling the client"
        assert new_total == len(page1), "process_document's return total must match page 1's KPI count"

        assert len(new_ex.client.calls_seen) == 1, \
            f"expected exactly 1 LLM call (page 1 only), got {len(new_ex.client.calls_seen)}"

        calls_before = len(new_ex.client.calls_seen)
        new_ex.process_document("AAA_2023.pdf", pages, new_out, esg_only=True, max_workers=1)
        assert len(new_ex.client.calls_seen) == calls_before, "re-run re-called the client"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cache_created_once_in_init_and_reused_across_documents_and_pages():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_cache_"))
    try:
        defs_path = _tiny_defs(tmp)
        new_ex = _make_extractor(new_extract, defs_path)

        assert new_ex.cache_name is not None, "cache creation must succeed against the stub"
        assert len(new_ex.client.caches.calls) == 1, (
            f"expected exactly 1 caches.create() in __init__, got {len(new_ex.client.caches.calls)}"
        )

        pages_doc_a = {1: [(0, "Chung toi cam ket giam phat thai.", True)]}
        pages_doc_b = {1: [(0, "Nha may dat muc tieu Net Zero.", True)]}
        new_ex.process_document("AAA_2023.pdf", pages_doc_a, tmp / "out", esg_only=True, max_workers=1)
        new_ex.process_document("BBB_2024.pdf", pages_doc_b, tmp / "out", esg_only=True, max_workers=1)

        assert len(new_ex.client.caches.calls) == 1, (
            "a second document must reuse the SAME cache, not create a new one "
            f"(got {len(new_ex.client.caches.calls)} caches.create() calls)"
        )
        assert len(new_ex.client.calls_seen) >= 2, "arm is vacuous: both pages must have reached the client"
        cache_names = {c["cached_content"] for c in new_ex.client.calls_seen}
        assert cache_names == {new_ex.cache_name}, f"every page must reuse the SAME cache: {cache_names}"
        for c in new_ex.client.calls_seen:
            assert "KPI_DEFINITIONS" not in c["contents"], (
                "the cached KPI_DEFINITIONS block must NOT be resent inline once cached_content is set"
            )
            assert c["system_instruction"] is None, (
                "cached_content and system_instruction must never both be set on one "
                "generate_content call -- Gemini's API rejects that combination outright"
            )
            assert "ESG-KPI-EXTRACTOR-V2" in c["contents"], (
                "when cached, the extraction instructions must be folded into contents "
                "instead of silently dropped"
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cache_creation_failure_falls_back_cleanly():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_cache_fail_"))
    try:
        defs_path = _tiny_defs(tmp)
        new_ex = _make_extractor(new_extract, defs_path, raise_caches=True)

        assert new_ex.cache_name is None, "a failed cache creation must leave cache_name None"
        pages = {1: [(0, "Chung toi cam ket giam phat thai.", True)]}
        new_ex.process_document("AAA_2023.pdf", pages, tmp / "out", esg_only=True, max_workers=1)

        assert len(new_ex.client.calls_seen) >= 1, "the page must still be attempted"
        for c in new_ex.client.calls_seen:
            assert c["cached_content"] is None, "a failed cache creation must leave every call uncached"
            assert "KPI_DEFINITIONS" in c["contents"], (
                "without a working cache, KPI_DEFINITIONS must still be sent inline"
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_use_context_cache_false_never_touches_caches_api():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_cache_off_"))
    try:
        defs_path = _tiny_defs(tmp)
        new_ex = _make_extractor(new_extract, defs_path, use_context_cache=False)

        assert new_ex.cache_name is None
        assert len(new_ex.client.caches.calls) == 0, "use_context_cache=False must never call caches.create"

        pages = {1: [(0, "Chung toi cam ket giam phat thai.", True)]}
        new_ex.process_document("AAA_2023.pdf", pages, tmp / "out", esg_only=True, max_workers=1)

        assert len(new_ex.client.caches.calls) == 0
        for c in new_ex.client.calls_seen:
            assert c["cached_content"] is None
            assert "KPI_DEFINITIONS" in c["contents"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _FlakyCacheModels(_FakeModels):
    """Fails the FIRST call that carries `cached_content` with a Gemini-style
    'CachedContent not found' error (simulating TTL expiry mid-run); every call
    after that -- including `extract_page`'s own retry -- succeeds normally."""

    def __init__(self, calls_seen):
        super().__init__(calls_seen)
        self._raised_once = False

    def generate_content(self, model, contents, config):
        if config.cached_content is not None and not self._raised_once:
            self._raised_once = True
            raise RuntimeError(
                "400 INVALID_ARGUMENT: CachedContent 'cachedContents/stub-1' not found."
            )
        return super().generate_content(model, contents, config)


class _FlakyCacheClient(_FakeClient):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.models = _FlakyCacheModels(self.calls_seen)


def _make_extractor_with_client(mod, defs_path, client_factory):
    os.environ.setdefault("GEMINI_API_KEY", "test-stub-key")
    original_builder = mod.build_gemini_client
    mod.build_gemini_client = lambda api_key=None: client_factory()
    try:
        return mod.KPIExtractor(defs_path, model="gemini-2.5-flash")
    finally:
        mod.build_gemini_client = original_builder


def test_extract_page_self_heals_once_when_cached_content_expires_midrun():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_cache_expire_"))
    try:
        defs_path = _tiny_defs(tmp)
        new_ex = _make_extractor_with_client(new_extract, defs_path, _FlakyCacheClient)

        assert new_ex.cache_name is not None
        first_cache_name = new_ex.cache_name

        out = new_ex.extract_page(
            "Chúng tôi đã giảm phát thải 20% trong năm 2023.", "AAA", new_extract.SECTOR, 1, "doc.pdf"
        )
        assert isinstance(out, list), "the page must still succeed, not raise or get lost"

        assert len(new_ex.client.caches.calls) == 2, (
            f"expected exactly 2 caches.create() calls (init + 1 self-heal), "
            f"got {len(new_ex.client.caches.calls)}"
        )
        assert new_ex.cache_name != first_cache_name, "cache_name must be replaced by the self-heal"

        cached_calls = [c for c in new_ex.client.calls_seen if c["cached_content"] is not None]
        assert len(cached_calls) == 1
        assert cached_calls[0]["cached_content"] == new_ex.cache_name
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_extract_page_reraises_non_cache_errors_without_recreating_cache():
    """A failure unrelated to the cache (network blip, model error, ...) must
    propagate unchanged -- self-healing is scoped to cache-expiry symptoms only.
    Retrying on every kind of failure would reintroduce the doubled-paid-call bug
    this fix is meant to close, just from a different angle."""
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_cache_othererr_"))
    try:
        defs_path = _tiny_defs(tmp)

        class _AlwaysFailsModels(_FakeModels):
            def generate_content(self, model, contents, config):
                raise RuntimeError("503 Service Unavailable")

        class _AlwaysFailsClient(_FakeClient):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.models = _AlwaysFailsModels(self.calls_seen)

        new_ex = _make_extractor_with_client(new_extract, defs_path, _AlwaysFailsClient)

        raised = False
        try:
            new_ex.extract_page("text", "AAA", new_extract.SECTOR, 1, "doc.pdf")
        except RuntimeError as e:
            raised = True
            assert "503" in str(e)
        assert raised, "a non-cache error must propagate, not be swallowed by the self-heal path"
        assert len(new_ex.client.caches.calls) == 1, "no self-heal recreation for a non-cache error"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_context_cache_invalidate_forces_a_fresh_create_on_next_get_or_create():
    """core/llm.py: GeminiContextCache.get_or_create() memoizes forever by content
    hash -- without invalidate(), a caller that suspects its cache expired would get
    the identical stale name back. This is the primitive extract.py's self-heal
    above is built on."""
    calls_seen: list = []
    fake_client = _FakeClient()
    ctx_cache = core_llm.GeminiContextCache(fake_client, "gemini-2.5-flash")

    name1 = ctx_cache.get_or_create("static content")
    assert len(fake_client.caches.calls) == 1
    name2 = ctx_cache.get_or_create("static content")
    assert name2 == name1, "same content, no invalidate -- must be memoized, not recreated"
    assert len(fake_client.caches.calls) == 1

    ctx_cache.invalidate("static content")
    name3 = ctx_cache.get_or_create("static content")
    assert len(fake_client.caches.calls) == 2, "after invalidate, get_or_create must create a NEW cache"
    assert name3 != name1, "the stub hands out a fresh cachedContents/stub-N each create() call"


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
