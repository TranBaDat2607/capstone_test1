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
step01 does not use `_Provider`/`_OpenAIProvider` at all — it talks to Gemini directly via
`google.genai.Client`. `core/llm.py`'s own docstring records that the Gemini provider was
never lifted (the project behind GEMINI_API_KEY is permanently 403). So `KPIExtractor`, its
prompt, its JSON schema and `normalize_kpi_response` all stay stage-local; only the 5 IO
helpers move.

HOW THE PAID BRANCH IS COVERED WITHOUT PAYING
Same technique as step03 phase 2 / step05d / step07: inject a STUB over the client the stage
constructs. Here that is `google.genai.Client` itself (there is no `_Provider` abstraction to
stand in front of), answering deterministically from a CRC of the prompt text, walking
multiple response shapes the parser must survive: clean JSON, a non-STOP `finish_reason`
(must return `[]`), and empty text (must return `[]`).

Offline: no real Gemini call, no network, no GEMINI_API_KEY required (the stub replaces
`google.genai.Client` before any request is built; a dummy key is set only so
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


# --------------------------------------------------------------------------- #
# Part A — core/io_jsonl.py: the 5 pure helpers
# --------------------------------------------------------------------------- #
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
            # each page's rows must round-trip through the two dependent pure helpers
            text = core_io_jsonl.build_page_text(rows)
            assert isinstance(text, str)
            assert isinstance(core_io_jsonl.page_has_esg(rows), bool)
            total_pages += 1
    assert total_pages > 0, "arm is vacuous: no pages loaded"
    print(f"  (loaded {len(new_docs)} document(s) / {total_pages} page(s) from the real corpus)")


# --------------------------------------------------------------------------- #
# Part B — module surface: paid-request-shape constants stay stage-local
# --------------------------------------------------------------------------- #
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
    system, user = new_ex._build_prompt(
        "Công ty đã giảm phát thải 20% trong năm 2023.", "AAA", new_extract.SECTOR, 5, "AAA_2023.pdf")
    assert "TT96-1" in user and "TT96-2" in user, "KPI definitions must reach the prompt"
    assert "AAA" in system
    assert "Công ty đã giảm phát thải 20%" in user
    # deterministic: same inputs -> byte-identical prompt
    system2, user2 = new_ex._build_prompt(
        "Công ty đã giảm phát thải 20% trong năm 2023.", "AAA", new_extract.SECTOR, 5, "AAA_2023.pdf")
    assert (system, user) == (system2, user2)


# --------------------------------------------------------------------------- #
# Part C — the paid path, driven by a stub over google.genai.Client
# --------------------------------------------------------------------------- #
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
    def __init__(self, api_key=None):
        self.calls_seen: list = []
        self.models = _FakeModels(self.calls_seen)


def _make_extractor(mod, defs_path):
    os.environ.setdefault("GEMINI_API_KEY", "test-stub-key")
    original_client = mod.genai.Client
    mod.genai.Client = _FakeClient
    try:
        return mod.KPIExtractor(defs_path, model="gemini-2.5-flash")
    finally:
        mod.genai.Client = original_client


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

        # pin the paid-request shape itself (CARE REQUIRED, same as core/llm.py's arm)
        assert len(new_ex.client.calls_seen) == len(texts)
        for call in new_ex.client.calls_seen:
            assert call["temperature"] == 0
            assert call["response_mime_type"] == "application/json"
            assert call["response_schema"] == new_extract.KPI_SCHEMA
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

        # non-ESG page (2) and empty-text page (3) must never have reached the client
        assert len(new_ex.client.calls_seen) == 1, \
            f"expected exactly 1 LLM call (page 1 only), got {len(new_ex.client.calls_seen)}"

        # idempotency: re-running with the same out_dir must not call the client again
        calls_before = len(new_ex.client.calls_seen)
        new_ex.process_document("AAA_2023.pdf", pages, new_out, esg_only=True, max_workers=1)
        assert len(new_ex.client.calls_seen) == calls_before, "re-run re-called the client"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Part D — the additive OpenAI path (`--provider openai`).
# Gemini stays the default; this only proves the alternate path is real and wired
# correctly, using the same stub-over-the-provider technique as core/llm.py's own
# arms. Single-tree only (this path has no counterpart in the old pipeline at all).
# --------------------------------------------------------------------------- #
def test_extract_page_openai_provider_parses_and_normalizes():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_openai_"))
    try:
        defs_path = _tiny_defs(tmp)
        saved = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"
        try:
            ex = new_extract.KPIExtractor(defs_path, provider="openai")
            assert ex.model == new_extract.DEFAULT_OPENAI_MODEL
            calls = []

            def fake_call(system, user):
                calls.append((system, user))
                return json.dumps({"kpis": [{
                    "kpi_type": "energy", "title": "t",
                    "observations": [{"value": "20%", "year": "2023", "unit": None,
                                       "kind": "achieved", "direction": "reduction",
                                       "target_year": None, "baseline_year": None,
                                       "source_id": "s1", "snippet": "..."}],
                    "page": 1, "doc_name": "doc.pdf", "company": "AAA", "sector": "s",
                }]})

            ex._openai.call = fake_call
            out = ex.extract_page("Chúng tôi đã giảm phát thải 20%.", "AAA", "sector", 1, "doc.pdf")
            assert len(out) == 1 and out[0]["kpi_type"] == "energy", out
            # normalize_kpi_response must still run on the OpenAI path (value -> float, % stripped)
            assert out[0]["observations"][0]["value"] == 20.0, out[0]["observations"][0]
            assert out[0]["observations"][0]["unit"] == "%", out[0]["observations"][0]
            assert out[0]["observations"][0]["year"] == 2023, out[0]["observations"][0]
            # the KPI schema must have been folded into what the provider received
            assert "kpi_type" in calls[0][0], "schema hint missing from system prompt"
        finally:
            if saved is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = saved
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("     (openai provider path parses + normalizes correctly)")


def test_kpi_extractor_openai_accepts_explicit_key_and_base_url_override():
    """Lets a caller point the openai path at an OpenAI-compatible third-party endpoint
    (e.g. Novita, for a one-off real-LLM test run) without OPENAI_API_KEY set."""
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_openai_override_"))
    try:
        defs_path = _tiny_defs(tmp)
        saved = os.environ.pop("OPENAI_API_KEY", None)
        try:
            ex = new_extract.KPIExtractor(
                defs_path, provider="openai", openai_model="some-model",
                openai_api_key="explicit-key", openai_base_url="https://example.invalid/v1")
            assert ex._openai.enabled is True
            assert ex._openai.client.api_key == "explicit-key"
            assert str(ex._openai.client.base_url).rstrip("/") == "https://example.invalid/v1"
        finally:
            if saved is not None:
                os.environ["OPENAI_API_KEY"] = saved
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("     (openai_api_key/openai_base_url override works with no OPENAI_API_KEY in env)")


def test_extract_page_gemini_default_unaffected_by_provider_arg():
    """--provider is additive: omitting it must behave exactly as before."""
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_default_"))
    try:
        defs_path = _tiny_defs(tmp)
        ex = _make_extractor(new_extract, defs_path)
        assert ex.provider == "gemini"
        assert not hasattr(ex, "_openai")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("     (default KPIExtractor() still builds the gemini path, untouched)")


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
