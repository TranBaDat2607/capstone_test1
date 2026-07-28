#!/usr/bin/env python3
"""
Old-vs-new equivalence for ONE migration slice:
`src/step01_extract_kpi_from_jsonl.py` -> `esg_kg.kpi.extract` + `esg_kg.core.io_jsonl`.

WHY THIS IS A SEPARATE FILE
Same reason as `test_esg_kg_anchor_kpi.py` / `_provenance.py` / `_align_claims.py`:
`test_esg_kg_equivalence.py` covers the kernel and is already past 1,100 lines, while this
covers a single stage end-to-end. Same contract as all of them — import BOTH trees, run
them on the same input, assert equal.

WHY step01 IS THE LAST HUB, AND WHAT core/io_jsonl.py IS
Per PIPELINE.md §2.1 point 3, step01 is the only remaining stage still imported for its OWN
stage-local symbols (not ones already lifted to `core/`): step02 takes 5 helpers straight off
it (`step02_extract_triplet_from_jsonl.py:43-50`). Those five — `load_pages_from_jsonl`,
`build_page_text`, `page_has_esg`, `select_documents`, `parse_company_year_from_filename` —
are exactly what `core/io_jsonl.py` lifts. They are pure (no network, no LLM), so the arm
below for them is free and runs on the real corpus.

WHY THIS SLICE NEEDED NO OTHER core/ MODULE
step01 does not use `_Provider`/`_OpenAIProvider` at all — it talks to Gemini directly via
`google.genai.Client`. `core/llm.py`'s own docstring records that the Gemini provider was
never lifted ("There is no Gemini provider to lift" — the project behind GEMINI_API_KEY is
permanently 403). So `KPIExtractor`, its prompt, its JSON schema and `normalize_kpi_response`
all stay stage-local; only the 5 IO helpers move.

HOW THE PAID BRANCH IS COVERED WITHOUT PAYING
Same technique as step03 phase 2 / step05d / step07: inject a STUB over the client the stage
constructs. Here that is `google.genai.Client` itself (there is no `_Provider` abstraction to
stand in front of), answering deterministically from a CRC of the prompt text so both trees
see identical replies, walking multiple response shapes the parser must survive: clean JSON,
a non-STOP `finish_reason` (must return `[]`), and empty text (must return `[]`).

Offline: no real Gemini call, no network, no GEMINI_API_KEY required (the stub replaces
`google.genai.Client` before any request is built; a dummy key is set only so
`KPIExtractor.__init__`'s presence check does not abort first). `data/labeled/annual_labeled/`
and `kpi_output/` are git-ignored (shipped via the HF snapshot) — arms needing them SKIP with
a message on a bare clone.

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
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ script --------------------------------------------------
import step01_extract_kpi_from_jsonl as old_extract  # noqa: E402

# --- new: the esg_kg package -----------------------------------------------------
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


def test_parse_company_year_from_filename_matches():
    cases = [
        "AAA_Baocaothuongnien_2011.pdf",
        "AAA_Baocaothuongnien_2011",
        "no_year_here.pdf",
        "trailing___2020.pdf",
        "2020.pdf",
        "a_b_c_2019_extra.pdf",
        "",
    ]
    for name in cases:
        a = new_extract.parse_company_year_from_filename(name)
        b = old_extract.parse_company_year_from_filename(name)
        assert a == b, f"diverged for {name!r}: new={a} old={b}"


def test_build_page_text_and_page_has_esg_match():
    fixtures = [
        [(2, "second.", True), (0, "first.", False), (1, "middle", False)],
        [],
        [(0, "  only  ", False)],
        [(0, "", True), (1, "   ", False)],
    ]
    for rows in fixtures:
        assert new_extract.build_page_text(rows) == old_extract.build_page_text(rows)
        assert new_extract.page_has_esg(rows) == old_extract.page_has_esg(rows)


def test_select_documents_matches_all_scope_flags():
    import argparse

    docs = {"a.pdf": {}, "b.pdf": {}, "c.pdf": {}}

    scenarios = [
        argparse.Namespace(doc=None, all=False, limit_docs=None),          # default: first only
        argparse.Namespace(doc=None, all=True, limit_docs=None),           # --all
        argparse.Namespace(doc=None, all=False, limit_docs=2),             # --limit-docs
        argparse.Namespace(doc="b", all=False, limit_docs=None),           # --doc match
        argparse.Namespace(doc="zzz", all=False, limit_docs=None),         # --doc no match
    ]
    for args in scenarios:
        nh, oh = _LogCatcher(), _LogCatcher()
        # select_documents logs via its OWN module's logger, not the caller's: in the new
        # tree that is core_io_jsonl (the function is imported, not redefined, in kpi/extract).
        core_io_jsonl.logger.addHandler(nh)
        old_extract.logger.addHandler(oh)
        try:
            a = new_extract.select_documents(docs, args)
            b = old_extract.select_documents(docs, args)
        finally:
            core_io_jsonl.logger.removeHandler(nh)
            old_extract.logger.removeHandler(oh)
        assert a == b, f"diverged for {args}: new={a} old={b}"
        assert nh.messages == oh.messages, f"log output diverged for {args}"


def test_load_pages_from_jsonl_real_corpus():
    if not DEFAULT_INPUT.exists():
        _skip("test_load_pages_from_jsonl_real_corpus", f"{DEFAULT_INPUT} not present (bare clone)")
        return
    new_docs = core_io_jsonl.load_pages_from_jsonl(DEFAULT_INPUT)
    old_docs = old_extract.load_pages_from_jsonl(DEFAULT_INPUT)
    assert list(new_docs.keys()) == list(old_docs.keys()), "document order diverged"
    assert new_docs == old_docs, "page reconstruction diverged on the real corpus"
    assert len(new_docs) > 0, "arm is vacuous: no documents loaded"

    total_pages = 0
    for src in new_docs:
        for page, rows in new_docs[src].items():
            assert core_io_jsonl.build_page_text(rows) == old_extract.build_page_text(rows)
            assert core_io_jsonl.page_has_esg(rows) == old_extract.page_has_esg(rows)
            total_pages += 1
    assert total_pages > 0, "arm is vacuous: no pages compared"
    print(f"  (compared {len(new_docs)} document(s) / {total_pages} page(s) from the real corpus)")


# --------------------------------------------------------------------------- #
# Part B — module surface: paid-request-shape constants stay stage-local
# --------------------------------------------------------------------------- #
def test_constants_and_schema_match():
    assert new_extract.DEFAULT_INPUT == old_extract.DEFAULT_INPUT
    assert new_extract.DEFAULT_KPI_DEFS == old_extract.DEFAULT_KPI_DEFS
    assert new_extract.DEFAULT_OUT_DIR == old_extract.DEFAULT_OUT_DIR
    assert new_extract.DEFAULT_MODEL == old_extract.DEFAULT_MODEL
    assert new_extract.SECTOR == old_extract.SECTOR
    # The JSON schema IS the paid request contract: dropping a field still "works" while
    # Gemini silently stops returning it.
    assert new_extract.KPI_SCHEMA == old_extract.KPI_SCHEMA, "KPI_SCHEMA diverged"
    assert new_extract._OBSERVATION_SCHEMA == old_extract._OBSERVATION_SCHEMA
    assert new_extract._KPI_ITEM_SCHEMA == old_extract._KPI_ITEM_SCHEMA


def test_normalize_kpi_response_matches():
    cases = [
        [{"observations": [{"value": "12.5%", "year": "2023"}]}],
        [{"observations": [{"value": "not-a-number", "unit": "kg"}]}],
        [{"observations": [{"value": 5, "target_year": "2030", "baseline_year": "abc"}]}],
        [{"observations": []}],
        [],
    ]
    for data in cases:
        import copy
        a = new_extract.normalize_kpi_response(copy.deepcopy(data))
        b = old_extract.normalize_kpi_response(copy.deepcopy(data))
        assert a == b, f"diverged for {data!r}: new={a} old={b}"


def test_build_prompt_matches():
    args_list = [
        ("Công ty đã giảm phát thải 20% trong năm 2023.", "AAA", old_extract.SECTOR, 5, "AAA_2023.pdf"),
        ("", "BBB", old_extract.SECTOR, 1, "b.pdf"),
    ]
    new_ex = new_extract.KPIExtractor.__new__(new_extract.KPIExtractor)
    new_ex.kpi_defs = [{"id": "TT96-1", "definition": "d1"}, {"id": "TT96-2", "definition": "d2"}]
    old_ex = old_extract.KPIExtractor.__new__(old_extract.KPIExtractor)
    old_ex.kpi_defs = new_ex.kpi_defs
    for page_text, company, sector, page_num, doc_name in args_list:
        a = new_ex._build_prompt(page_text, company, sector, page_num, doc_name)
        b = old_ex._build_prompt(page_text, company, sector, page_num, doc_name)
        assert a == b, f"prompt diverged for {doc_name}"


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


def test_extract_page_matches_across_response_shapes():
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
        old_ex = _make_extractor(old_extract, defs_path)
        for i, text in enumerate(texts):
            a = new_ex.extract_page(text, "AAA", old_extract.SECTOR, i, "doc.pdf")
            b = old_ex.extract_page(text, "AAA", old_extract.SECTOR, i, "doc.pdf")
            assert a == b, f"extract_page diverged for text[{i}]: new={a} old={b}"
        # pin the paid-request shape itself (CARE REQUIRED, same as core/llm.py's arm)
        assert len(new_ex.client.calls_seen) == len(old_ex.client.calls_seen)
        for nc, oc in zip(new_ex.client.calls_seen, old_ex.client.calls_seen):
            assert nc["temperature"] == 0 == oc["temperature"]
            assert nc["response_mime_type"] == "application/json" == oc["response_mime_type"]
            assert nc["response_schema"] == old_extract.KPI_SCHEMA
            assert nc["system_instruction"] == oc["system_instruction"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_document_matches_and_skips_existing_output():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_01_doc_"))
    try:
        defs_path = _tiny_defs(tmp)
        pages = {
            1: [(0, "Chúng tôi cam kết giảm phát thải khí nhà kính.", True)],
            2: [(0, "Không có nội dung ESG ở trang này.", False)],
            3: [(0, "", False)],  # empty page text -> [] without calling the client
        }
        new_out = tmp / "new_out"
        old_out = tmp / "old_out"
        new_ex = _make_extractor(new_extract, defs_path)
        old_ex = _make_extractor(old_extract, defs_path)

        new_total = new_ex.process_document("AAA_2023.pdf", pages, new_out, esg_only=True, max_workers=1)
        old_total = old_ex.process_document("AAA_2023.pdf", pages, old_out, esg_only=True, max_workers=1)
        assert new_total == old_total, f"total KPI count diverged: new={new_total} old={old_total}"

        new_files = sorted(p.name for p in (new_out / "AAA_2023_kpis").glob("*.json"))
        old_files = sorted(p.name for p in (old_out / "AAA_2023_kpis").glob("*.json"))
        assert new_files == old_files, f"file set diverged: new={new_files} old={old_files}"
        for name in new_files:
            nj = json.loads((new_out / "AAA_2023_kpis" / name).read_text(encoding="utf-8"))
            oj = json.loads((old_out / "AAA_2023_kpis" / name).read_text(encoding="utf-8"))
            assert nj == oj, f"{name} content diverged"

        # non-ESG page (2) and empty-text page (3) must never have reached the client
        assert new_ex.client.calls_seen == old_ex.client.calls_seen
        assert len(new_ex.client.calls_seen) == 1, \
            f"expected exactly 1 LLM call (page 1 only), got {len(new_ex.client.calls_seen)}"

        # idempotency: re-running with the same out_dir must not call the client again
        new_calls_before = len(new_ex.client.calls_seen)
        old_calls_before = len(old_ex.client.calls_seen)
        new_ex.process_document("AAA_2023.pdf", pages, new_out, esg_only=True, max_workers=1)
        old_ex.process_document("AAA_2023.pdf", pages, old_out, esg_only=True, max_workers=1)
        assert len(new_ex.client.calls_seen) == new_calls_before, "re-run re-called the client (new tree)"
        assert len(old_ex.client.calls_seen) == old_calls_before, "re-run re-called the client (old tree)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
