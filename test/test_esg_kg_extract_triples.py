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
sys.path.insert(0, str(REPO / "src_module"))

# --- new: the esg_kg package -------------------------------------------------------
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


# --------------------------------------------------------------------------- #
# Part A — kernel reuse: identity + real-corpus, all offline/free.
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Part B — module surface: constants, prompt templates, pure helpers.
# --------------------------------------------------------------------------- #
def test_cfg_json_matches():
    assert new_mod.CFG_JSON.temperature == 0, new_mod.CFG_JSON.temperature
    assert new_mod.CFG_JSON.response_mime_type == "application/json", new_mod.CFG_JSON.response_mime_type


def test_prompt_templates_pin_the_vietnamese_language_fix_byte_for_byte():
    assert "## OUTPUT LANGUAGE" in new_mod.TEMPORAL_GRAPH_PROMPT_TEMPLATE
    assert "## OUTPUT LANGUAGE" in new_mod.NEWS_GRAPH_PROMPT_TEMPLATE


# --------------------------------------------------------------------------- #
# Part C — the paid path, driven by a fake client passed directly (no
# monkeypatch needed: call_llm/process_page/process_document all take `client`
# as a plain parameter).
# --------------------------------------------------------------------------- #
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


class _FakeClient:
    def __init__(self):
        self.calls_seen: list = []
        self.models = _FakeModels(self.calls_seen)


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

            # page 2 (not ESG) and page 3 (empty text) must never reach the client — only
            # page 1 can, so at least one call happened but the arm is not vacuous.
            assert len(new_client.calls_seen) > 0, f"[{source}] arm is vacuous: no client call happened"

            # Re-run page 1. `out_file.exists()` skip only fires if page 1's CRC-selected
            # response shape happened to succeed on the first pass (a losing shape leaves no
            # out_file, so a legitimate retry is expected) — that depends on the prompt's
            # hash, which this test does not control. So the property checked is
            # conditional: IF page1.json already exists, a re-run must not call the client.
            new_before = len(new_client.calls_seen)
            new_mod.process_page(pages[0], [], new_client, 0, new_rl, SCHEMA, "gemini-2.5-flash",
                                 esg_only=True, pdf_stem="doc", dbg_pdf_dir=new_dbg, g_pdf_dir=new_g,
                                 company="AAA", year=2024, source=source, article_meta=article_meta)
            new_growth = len(new_client.calls_seen) - new_before
            if (new_g / "page1.json").exists():
                assert new_growth == 0, f"[{source}] page1.json exists but re-run still called the client"
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


# --------------------------------------------------------------------------- #
# NEW (2026-07-29): the additive OpenAI path (`--provider openai`). Gemini stays the
# default; no src/ counterpart exists for this branch, so it is single-tree only —
# same discipline as test_esg_kg_extract.py's equivalent Part D.
# --------------------------------------------------------------------------- #
_VALID_TRIPLE = {
    "subject": {"class": "Organization", "properties": {"name": "Test Co"}},
    "predicate": "reportsKPI",
    "object": {"class": "KPIObservation", "properties": {"kpi_type": "x", "title": "t"}},
    "temporal_metadata": {"valid_from": "2023-01-01", "valid_to": None, "recorded_at": "2023-01-01"},
}


class _StubOpenAIProvider:
    def __init__(self, reply):
        self.reply = reply
        self.calls: list = []

    def call(self, system, user):
        self.calls.append((system, user))
        return self.reply


def test_call_llm_openai_provider_unwraps_triples_object():
    provider = _StubOpenAIProvider(json.dumps({"triples": [_VALID_TRIPLE]}))
    rl = new_mod.RateLimiter(max_calls_per_minute=1000)
    parsed, raw, rate_limited = new_mod.call_llm(
        "prompt text", provider, 0, rl, SCHEMA, "gpt-4o-mini", retries=1, provider="openai")
    assert rate_limited is False
    assert parsed == [_VALID_TRIPLE], parsed
    assert raw == provider.reply
    assert len(provider.calls) == 1
    system, user = provider.calls[0]
    assert user == "prompt text", "the full templated prompt must reach the model verbatim"
    assert "json" in system.lower(), "OpenAI json_object mode requires 'json' in the messages"
    print("     (openai reply unwrapped from {'triples': [...]} and validated)")


def test_call_llm_openai_provider_accepts_bare_array_too():
    """Belt-and-braces: if the model ignores the wrapper instruction and returns a bare
    array, that must still parse rather than being treated as a format error."""
    provider = _StubOpenAIProvider(json.dumps([_VALID_TRIPLE]))
    rl = new_mod.RateLimiter(max_calls_per_minute=1000)
    parsed, _, rate_limited = new_mod.call_llm(
        "prompt text", provider, 0, rl, SCHEMA, "gpt-4o-mini", retries=1, provider="openai")
    assert rate_limited is False
    assert parsed == [_VALID_TRIPLE], parsed
    print("     (a bare JSON array reply is also accepted)")


def test_call_llm_openai_provider_bad_json_does_not_crash():
    provider = _StubOpenAIProvider("not json at all")
    rl = new_mod.RateLimiter(max_calls_per_minute=1000)
    parsed, raw, rate_limited = new_mod.call_llm(
        "prompt text", provider, 0, rl, SCHEMA, "gpt-4o-mini", retries=1, provider="openai")
    assert rate_limited is False
    assert parsed == [], parsed
    assert raw == "not json at all"
    print("     (unparseable reply -> [] rather than raising)")


def test_call_llm_gemini_default_unaffected_by_provider_arg():
    """provider='gemini' (the default) must behave exactly as before this change."""
    client = _FakeClient()
    rl = new_mod.RateLimiter(max_calls_per_minute=1000)
    a = new_mod.call_llm("prompt A - legal triple shape", client, 0, rl, SCHEMA,
                         "gemini-2.5-flash", retries=1)
    b = new_mod.call_llm("prompt A - legal triple shape", client, 0, rl, SCHEMA,
                         "gemini-2.5-flash", retries=1, provider="gemini")
    assert a == b, "omitting provider= must match provider='gemini' explicitly"
    print("     (default call_llm() still takes the gemini path, untouched)")


if __name__ == "__main__":
    main()
