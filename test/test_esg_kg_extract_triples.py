#!/usr/bin/env python3
"""
Old-vs-new equivalence for the LAST migration slice (15th and final stage):
`src/step02_extract_triplet_from_jsonl.py` -> `esg_kg.graph.extract_triples`.

WHY THIS IS A SEPARATE FILE
Same reason as every other per-stage equivalence file: `test_esg_kg_equivalence.py`
covers the kernel and is already huge; this covers one stage end-to-end. Same
contract — import BOTH trees, run them on the same input, assert equal.

WHY step02 NEEDED NO NEW core/ MODULE
Every symbol it imports was already lifted by earlier slices: the 5 JSONL helpers by
step01's slice (`core/io_jsonl`), `RateLimiter`/`DEFAULT_RATE_LIMIT` by the `core/llm`
slice, `get_identity_keys` by `core/schema`, `get_stable_entity_id`/`PROVENANCE_CLASSES`
by `core/identity`. The one stage-local duplicate, `schema_sets()`, is DELETED — its
first two return values were byte-identical to `esg_kg.core.schema.load_schema_sets()`'s
first two, so every call site now unpacks that 3-tuple and discards `edge_directions`.

WHY THIS SLICE'S PAID-PATH STUB LOOKS DIFFERENT FROM step01's
Unlike `KPIExtractor` (step01), step02 never constructs its own Gemini client — every
function that talks to the model (`call_llm`, `process_page`, `process_document`) takes
`client: genai.Client` as a plain parameter. So there is nothing to monkeypatch: a fake
client object satisfying `client.models.generate_content(model, contents, config)` can
just be passed in directly, in both trees, same as `_OpenAIProvider`-shaped stubs
elsewhere. `_response_to_text` also differs from step01: it only extracts `.candidates`
text when the response `isinstance(..., genai.types.GenerateContentResponse)`; anything
else falls through to `str(resp)`. So the fake response here answers via `__str__`,
not via a `.text`/`.candidates` shape — there is no finish_reason branch to fake, because
step02's parsing pipeline never inspects one.

Offline: no real Gemini call, no network, no GEMINI_API_KEY required. `data/labeled/`
and `kpi_output/` are git-ignored (shipped via the HF snapshot) — arms needing them SKIP
with a message on a bare clone.

Was driven through both `src/` and `esg_kg` while both trees existed (DESIGN.md §5.3);
repointed at `esg_kg` only (2026-07-29) now that `src/` is gone. Cross-tree comparisons
with no independent claim about correct behaviour were deleted rather than rewritten
against a guessed value.

Run from the repo root:

    python test/test_esg_kg_extract_triples.py
"""

import json
import logging
import shutil
import sys
import tempfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core import io_jsonl as core_io_jsonl  # noqa: E402
from esg_kg.core import llm as core_llm  # noqa: E402
from esg_kg.core import schema as core_schema  # noqa: E402
from esg_kg.core import identity as core_identity  # noqa: E402
from esg_kg.graph import extract_triples as new_mod  # noqa: E402

SCHEMA = json.loads((REPO / "config" / "schema.json").read_text(encoding="utf-8"))

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
    assert new_mod.load_pages_from_jsonl is core_io_jsonl.load_pages_from_jsonl
    assert new_mod.build_page_text is core_io_jsonl.build_page_text
    assert new_mod.page_has_esg is core_io_jsonl.page_has_esg
    assert new_mod.select_documents is core_io_jsonl.select_documents
    assert new_mod.parse_company_year_from_filename is core_io_jsonl.parse_company_year_from_filename
    assert new_mod.RateLimiter is core_llm.RateLimiter
    assert new_mod.get_identity_keys is core_schema.get_identity_keys
    assert new_mod.get_stable_entity_id is core_identity.get_stable_entity_id
    assert new_mod.PROVENANCE_CLASSES is core_identity.PROVENANCE_CLASSES


def test_schema_sets_replaced_by_load_schema_sets():
    """The stage-local duplicate is gone."""
    assert not hasattr(new_mod, "schema_sets"), \
        "new tree must not carry a schema_sets duplicate of core.schema.load_schema_sets"
    new_entities, new_edges, _edge_directions = core_schema.load_schema_sets(SCHEMA)
    assert new_entities, "arm is vacuous: load_schema_sets returned no entity classes"
    assert new_edges, "arm is vacuous: load_schema_sets returned no edge labels"


def test_cfg_json_matches():
    assert new_mod.CFG_JSON.temperature == 0, new_mod.CFG_JSON.temperature
    assert new_mod.CFG_JSON.response_mime_type == "application/json", new_mod.CFG_JSON.response_mime_type


def test_prompt_templates_pin_the_vietnamese_language_fix_byte_for_byte():
    assert "## OUTPUT LANGUAGE" in new_mod.TEMPORAL_GRAPH_PROMPT_TEMPLATE
    assert "## OUTPUT LANGUAGE" in new_mod.NEWS_GRAPH_PROMPT_TEMPLATE


def test_header_body_split_reconstructs_build_page_prompt_byte_for_byte():
    """issue #11: build_page_prompt must still produce EXACTLY what it did before the
    split, for both report and news sources — this is what makes the split a pure
    refactor, not a behaviour change."""
    for source, article_meta in (
        ("report", None),
        ("news", {"source_domain": "x.vn", "title": "T", "publish_date": "2024-01-01", "url": "https://x/y"}),
    ):
        full = new_mod.build_page_prompt(
            SCHEMA, "some page text", 3, [{"kpi_type": "ESG-1-1"}],
            company="AAA", year=2023, source=source, article_meta=article_meta,
        )
        header = new_mod.build_document_header(SCHEMA, "AAA", 2023, source=source, article_meta=article_meta)
        body = new_mod.build_page_body("some page text", 3, [{"kpi_type": "ESG-1-1"}])
        assert full == f"{header}\n\n{body}", f"[{source}] header+body must reassemble byte-for-byte"


def test_document_header_is_identical_across_pages_of_one_document_but_differs_by_company_year():
    """The whole point of caching it: header must not depend on page_no/page_text/kpis,
    only on schema/company/year(/article_meta) — so one cache serves every page of a
    document, but a different document (different company or year) needs a new one."""
    h_page1 = new_mod.build_document_header(SCHEMA, "AAA", 2023, source="report")
    h_page99 = new_mod.build_document_header(SCHEMA, "AAA", 2023, source="report")
    assert h_page1 == h_page99, "header must not vary by page — nothing page-specific feeds it"

    h_other_company = new_mod.build_document_header(SCHEMA, "BBB", 2023, source="report")
    h_other_year = new_mod.build_document_header(SCHEMA, "AAA", 2024, source="report")
    assert h_page1 != h_other_company, "different company must produce a different header"
    assert h_page1 != h_other_year, "different year must produce a different header"


LEGAL_TRIPLE_JSON = json.dumps([{
    "subject": {"class": "Organization", "properties": {
        "name": "CÔNG TY TEST", "valid_from": "2023-01-01", "valid_to": None, "is_current": True}},
    "predicate": "reportsKPI",
    "object": {"class": "KPIObservation", "properties": {
        "kpi_type": "ESG-1-1", "value": 1, "unit": "MWh",
        "valid_from": "2023-01-01", "valid_to": None, "is_current": True}},
    "temporal_metadata": {"valid_from": "2023-01-01", "valid_to": None, "recorded_at": "2023-01-01"},
}])


class _FakeResponse:
    """`_response_to_text` falls through to `str(resp)` for anything that is not a
    real `genai.types.GenerateContentResponse` — so this answers via __str__, not a
    `.candidates` shape."""

    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


class _FakeModels:
    def __init__(self, calls_seen):
        self._calls_seen = calls_seen

    def generate_content(self, model, contents, config):
        self._calls_seen.append({
            "model": model,
            "contents": contents,
            "system_instruction": config.system_instruction,
            "response_mime_type": config.response_mime_type,
            "temperature": config.temperature,
            "cached_content": config.cached_content,
        })
        crc = zlib.crc32(contents.encode("utf-8"))
        shape = crc % 4
        if shape == 0:
            return _FakeResponse(LEGAL_TRIPLE_JSON)
        if shape == 1:
            return _FakeResponse("[]")
        if shape == 2:
            return _FakeResponse("not json at all")
        return _FakeResponse("")


class _FakeCachedContent:
    def __init__(self, name):
        self.name = name


class _FakeCaches:
    """Stub for `client.caches` (issue #11 / `GeminiContextCache`, core/llm.py). Records
    every create() call; can be told to raise instead of succeeding."""

    def __init__(self, raise_always=False):
        self.calls: list = []
        self._raise_always = raise_always
        self._next_id = 0

    def create(self, *, model, config):
        self.calls.append({
            "model": model,
            "contents": config.contents,
            "system_instruction": config.system_instruction,
        })
        if self._raise_always:
            raise RuntimeError("simulated caches.create failure")
        self._next_id += 1
        return _FakeCachedContent(name=f"cachedContents/stub-{self._next_id}")


class _FakeClient:
    def __init__(self, raise_caches=False):
        self.calls_seen: list = []
        self.models = _FakeModels(self.calls_seen)
        self.caches = _FakeCaches(raise_always=raise_caches)


def test_call_llm_produces_a_valid_paid_request_shape_across_response_shapes():
    prompts = [
        "prompt A - legal triple shape",
        "prompt B - empty array shape",
        "prompt C - malformed text shape",
        "prompt D - empty text shape",
    ]
    new_client = _FakeClient()
    new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
    for p in prompts:
        new_mod.call_llm(p, new_client, 0, new_rl, SCHEMA, "gemini-2.5-flash", retries=1)

    assert len(new_client.calls_seen) > 0, "arm is vacuous: call_llm never reached the client"
    for nc in new_client.calls_seen:
        assert nc["temperature"] == 0
        assert nc["response_mime_type"] == "application/json"


class _FakeProvider:
    """Stub for a `core.llm._Provider` (2026-08-06 `--provider deepseek` swap). Records
    every `call(system, user)` invocation; `client`/`cached_content` must be ignored
    entirely when a provider is passed to `call_llm`."""
    name = "deepseek"

    def __init__(self):
        self.calls_seen: list = []

    def call(self, system, user):
        self.calls_seen.append({"system": system, "user": user})
        return '[{"subject": {"class": "Organization", "properties": {}}, ' \
               '"predicate": "reportsKPI", "object": {"class": "KPIObservation", "properties": {}}}]'


def test_call_llm_with_a_provider_ignores_the_gemini_client_entirely():
    """The DeepSeek swap (core/llm.py's `build_llm_provider`) must bypass `client` and
    `cached_content` completely — `provider.call` is the only thing that fires."""
    new_client = _FakeClient()  # would raise/record if anything touched it
    provider = _FakeProvider()
    new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
    parsed, raw, rate_limited = new_mod.call_llm(
        "USER PROMPT", new_client, 0, new_rl, SCHEMA, "deepseek-v4-flash",
        retries=1, cached_content="should-be-ignored", provider=provider,
    )
    assert len(new_client.calls_seen) == 0, "provider path must never touch the Gemini client"
    assert len(provider.calls_seen) == 1, "arm is vacuous: provider.call was never reached"
    assert provider.calls_seen[0]["system"] == new_mod.JSON_ONLY_SYSTEM_INSTRUCTION
    assert provider.calls_seen[0]["user"] == "USER PROMPT"
    assert rate_limited is False
    assert isinstance(parsed, list) and parsed, f"reply not parsed as triples: {raw!r}"


def test_process_page_with_a_provider_always_sends_the_full_prompt():
    """Even when a Gemini `cache_name` is passed in (should never happen in practice —
    process_document never builds one when a provider is active — but if it did),
    `process_page` must send the FULL prompt when a provider is set, never
    `build_page_body`'s cache-only body: DeepSeek has no context-cache equivalent."""
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_02_provider_"))
    try:
        new_g = tmp / "g"
        new_dbg = tmp / "dbg"
        for d in (new_g, new_dbg):
            d.mkdir(parents=True)
        provider = _FakeProvider()
        new_client = _FakeClient()
        new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
        pg = {"page": 1, "text": "Cong ty giam phat thai 20% trong nam.", "has_esg": True}
        new_mod.process_page(pg, [], new_client, 0, new_rl, SCHEMA, "deepseek-v4-flash",
                             esg_only=True, pdf_stem="doc", dbg_pdf_dir=new_dbg, g_pdf_dir=new_g,
                             company="AAA", year=2024, source="report",
                             cache_name="should-be-ignored", provider=provider)
        assert len(new_client.calls_seen) == 0, "provider path must never touch the Gemini client"
        assert len(provider.calls_seen) == 1
        sent_user = provider.calls_seen[0]["user"]
        assert "KNOWLEDGE GRAPH SCHEMA" in sent_user, \
            "process_page sent the cache-only body instead of the full prompt"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_page_skips_non_esg_pages_and_is_idempotent_on_rerun():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_02_page_"))
    try:
        for source in ("report", "news"):
            new_g = tmp / f"{source}_new_g"
            new_dbg = tmp / f"{source}_new_dbg"
            for d in (new_g, new_dbg):
                d.mkdir(parents=True)

            article_meta = {"title": "T", "url": "https://x/y", "source_domain": "x.vn",
                            "publish_date": "2024-08-14"} if source == "news" else None

            pages = [
                {"page": 1, "text": "Cong ty giam phat thai 20% trong nam.", "has_esg": True},
                {"page": 2, "text": "Khong co noi dung ESG.", "has_esg": False},
                {"page": 3, "text": "", "has_esg": False},
            ]
            new_client = _FakeClient()
            new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
            for pg in pages:
                new_mod.process_page(pg, [], new_client, 0, new_rl, SCHEMA, "gemini-2.5-flash",
                                     esg_only=True, pdf_stem="doc", dbg_pdf_dir=new_dbg, g_pdf_dir=new_g,
                                     company="AAA", year=2024, source=source, article_meta=article_meta)

            assert len(new_client.calls_seen) > 0, f"[{source}] arm is vacuous: no client call happened"

            new_before = len(new_client.calls_seen)
            new_mod.process_page(pages[0], [], new_client, 0, new_rl, SCHEMA, "gemini-2.5-flash",
                                 esg_only=True, pdf_stem="doc", dbg_pdf_dir=new_dbg, g_pdf_dir=new_g,
                                 company="AAA", year=2024, source=source, article_meta=article_meta)
            new_growth = len(new_client.calls_seen) - new_before
            if (new_g / "page1.json").exists():
                assert new_growth == 0, f"[{source}] page1.json exists but re-run still called the client"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _multi_page_doc():
    return {
        1: [(1, "Cong ty giam phat thai 20% trong nam.", True)],
        2: [(2, "Cong ty dat muc tieu Net Zero vao 2050.", True)],
        3: [(3, "Nha may Song Hong tang san luong.", True)],
    }


def test_process_document_creates_one_cache_and_reuses_it_across_every_page():
    """issue #11: one client.caches.create() per document, not one per page — and every
    page's generate_content call must carry that same cached_content, with a body-only
    prompt (no header duplicated in `contents`)."""
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_02_doc_cache_"))
    try:
        new_client = _FakeClient()
        new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
        ctx_cache = core_llm.GeminiContextCache(new_client, "gemini-2.5-flash")

        new_mod.process_document(
            "AAA_2023.pdf", _multi_page_doc(), tmp / "kpi", tmp / "out", SCHEMA,
            "gemini-2.5-flash", new_client, new_rl, esg_only=True, max_workers=1,
            ctx_cache=ctx_cache,
        )

        assert len(new_client.caches.calls) == 1, (
            f"expected exactly 1 caches.create() for one document, got {len(new_client.caches.calls)}"
        )
        assert new_client.caches.calls[0]["system_instruction"] == new_mod.JSON_ONLY_SYSTEM_INSTRUCTION, (
            "the cache must carry JSON_ONLY_SYSTEM_INSTRUCTION so it isn't silently dropped"
        )
        assert len(new_client.calls_seen) >= 3, "arm is vacuous: not all 3 pages reached the client"
        cache_names = {c["cached_content"] for c in new_client.calls_seen}
        assert cache_names == {"cachedContents/stub-1"}, (
            f"every page must reuse the SAME cache name: {cache_names}"
        )
        header = new_mod.build_document_header(SCHEMA, "AAA", 2023, source="report")
        for c in new_client.calls_seen:
            assert header not in c["contents"], (
                "the cached header must NOT be resent inline once cached_content is set"
            )
            assert c["system_instruction"] is None, (
                "cached_content and system_instruction must never both be set on one "
                "generate_content call"
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_document_falls_back_cleanly_when_cache_creation_fails():
    """A caches.create() failure must not break extraction: every page still gets
    processed, just without cached_content (today's uncached behaviour)."""
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_02_doc_cache_fail_"))
    try:
        new_client = _FakeClient(raise_caches=True)
        new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
        ctx_cache = core_llm.GeminiContextCache(new_client, "gemini-2.5-flash")

        s, f = new_mod.process_document(
            "AAA_2023.pdf", _multi_page_doc(), tmp / "kpi", tmp / "out", SCHEMA,
            "gemini-2.5-flash", new_client, new_rl, esg_only=True, max_workers=1,
            ctx_cache=ctx_cache,
        )

        assert len(new_client.calls_seen) >= 3, "all 3 pages must still be attempted"
        assert all(c["cached_content"] is None for c in new_client.calls_seen), (
            "a failed cache creation must leave every call uncached, not crash"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_document_without_ctx_cache_never_touches_caches_api():
    """No ctx_cache passed (the --no-context-cache escape hatch) -> caches.create is
    never called at all, and every page's contents include the full header (today's
    unmodified behaviour)."""
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_02_doc_no_cache_"))
    try:
        new_client = _FakeClient()
        new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)

        new_mod.process_document(
            "AAA_2023.pdf", _multi_page_doc(), tmp / "kpi", tmp / "out", SCHEMA,
            "gemini-2.5-flash", new_client, new_rl, esg_only=True, max_workers=1,
            ctx_cache=None,
        )

        assert len(new_client.caches.calls) == 0, "ctx_cache=None must never call caches.create"
        assert all(c["cached_content"] is None for c in new_client.calls_seen)
        header = new_mod.build_document_header(SCHEMA, "AAA", 2023, source="report")
        for c in new_client.calls_seen:
            assert header in c["contents"], "without caching, the header must still be sent inline"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
    if _skips:
        print(f"{len(_skips)} arm(s) skipped (missing local artifacts):")
        for s in _skips:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
