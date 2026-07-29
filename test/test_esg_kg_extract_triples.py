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
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ script (already carries the issue-#6 language fix) -------
import step02_extract_triplet_from_jsonl as old_mod  # noqa: E402

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
    """The stage-local duplicate is gone; load_schema_sets's first two values match it."""
    assert not hasattr(new_mod, "schema_sets"), \
        "new tree must not carry a schema_sets duplicate of core.schema.load_schema_sets"
    old_entities, old_edges = old_mod.schema_sets(SCHEMA)
    new_entities, new_edges, _edge_directions = core_schema.load_schema_sets(SCHEMA)
    assert new_entities == old_entities
    assert new_edges == old_edges


def test_pages_for_doc_and_load_kpis_for_doc_real_corpus():
    if not old_mod.DEFAULT_INPUT.exists():
        _skip("test_pages_for_doc_and_load_kpis_for_doc_real_corpus",
              f"{old_mod.DEFAULT_INPUT} not present (bare clone)")
        return
    docs = core_io_jsonl.load_pages_from_jsonl(old_mod.DEFAULT_INPUT)
    compared = 0
    for src, jsonl_pages in docs.items():
        a = new_mod.pages_for_doc(jsonl_pages)
        b = old_mod.pages_for_doc(jsonl_pages)
        assert a == b, f"pages_for_doc diverged for {src}"
        compared += 1
        pdf_stem = src.rsplit(".", 1)[0]
        ka = new_mod.load_kpis_for_doc(pdf_stem, old_mod.DEFAULT_KPI_DIR)
        kb = old_mod.load_kpis_for_doc(pdf_stem, old_mod.DEFAULT_KPI_DIR)
        assert ka == kb, f"load_kpis_for_doc diverged for {pdf_stem}"
    assert compared > 0, "arm is vacuous: no documents compared"
    print(f"  (compared {compared} document(s) from the real corpus)")


# --------------------------------------------------------------------------- #
# Part B — module surface: constants, prompt templates, pure helpers.
# --------------------------------------------------------------------------- #
def test_constants_match():
    assert new_mod.DEFAULT_INPUT == old_mod.DEFAULT_INPUT
    assert new_mod.DEFAULT_SCHEMA == old_mod.DEFAULT_SCHEMA
    assert new_mod.DEFAULT_KPI_DIR == old_mod.DEFAULT_KPI_DIR
    assert new_mod.DEFAULT_OUT_DIR == old_mod.DEFAULT_OUT_DIR
    assert new_mod.DEFAULT_MODEL == old_mod.DEFAULT_MODEL
    assert new_mod.DEFAULT_RATE_LIMIT == old_mod.DEFAULT_RATE_LIMIT
    assert new_mod.DEFAULT_MAX_WORKERS == old_mod.DEFAULT_MAX_WORKERS


def test_cfg_json_matches():
    assert new_mod.CFG_JSON.temperature == old_mod.CFG_JSON.temperature == 0
    assert new_mod.CFG_JSON.response_mime_type == old_mod.CFG_JSON.response_mime_type
    assert new_mod.CFG_JSON.system_instruction == old_mod.CFG_JSON.system_instruction


def test_prompt_templates_pin_the_vietnamese_language_fix_byte_for_byte():
    # old_mod already carries the issue-#6 fix (Part A landed in src/ first) — this is
    # a straightforward equality pin, same technique as test_esg_kg_crosscheck.py
    # pinning ADJUDICATE_SYSTEM.
    assert new_mod.TEMPORAL_GRAPH_PROMPT_TEMPLATE == old_mod.TEMPORAL_GRAPH_PROMPT_TEMPLATE
    assert new_mod.NEWS_GRAPH_PROMPT_TEMPLATE == old_mod.NEWS_GRAPH_PROMPT_TEMPLATE
    assert "## OUTPUT LANGUAGE" in new_mod.TEMPORAL_GRAPH_PROMPT_TEMPLATE
    assert "## OUTPUT LANGUAGE" in new_mod.NEWS_GRAPH_PROMPT_TEMPLATE


def test_build_page_prompt_matches_for_report_and_news():
    report_kwargs = dict(schema=SCHEMA, page_text="Doanh thu nam 2023 dat 1.200 ty dong.",
                         page_no=3, page_kpis=[{"kpi_type": "ESG-1-1", "value": 1}],
                         company="AAA", year=2023, source="report")
    a = new_mod.build_page_prompt(**report_kwargs)
    b = old_mod.build_page_prompt(**report_kwargs)
    assert a == b, "report-source build_page_prompt diverged"

    news_kwargs = dict(schema=SCHEMA, page_text="Cong ty bi xu phat vi vi pham moi truong.",
                       page_no=1, page_kpis=[], company="AAA", year=2024, source="news",
                       article_meta={"source_domain": "vietnamnet.vn", "title": "AAA bi xu phat",
                                     "publish_date": "2024-08-14", "url": "https://vietnamnet.vn/x"})
    a2 = new_mod.build_page_prompt(**news_kwargs)
    b2 = old_mod.build_page_prompt(**news_kwargs)
    assert a2 == b2, "news-source build_page_prompt diverged"


def test_json_cleaning_and_validation_helpers_match():
    responses = [
        '```json\n[{"a": 1}]\n```',
        'Here is the JSON:\n[{"a": 1}]',
        '[{"a": 1},]',
        "not json at all",
        "",
        '{"a": 1, "b": 2,}',
    ]
    for r in responses:
        ca = new_mod._clean_json_response(r)
        cb = old_mod._clean_json_response(r)
        assert ca == cb, f"_clean_json_response diverged for {r!r}"
        pa = new_mod._parse_json_response(r)
        pb = old_mod._parse_json_response(r)
        assert pa == pb, f"_parse_json_response diverged for {r!r}"

    legal_triple = [{
        "subject": {"class": "Organization", "properties": {"name": "X"}},
        "predicate": "reportsKPI",
        "object": {"class": "KPIObservation", "properties": {"kpi_type": "ESG-1-1"}},
    }]
    illegal_triple = [{"subject": {"class": "NotAClass", "properties": {}},
                       "predicate": "reportsKPI", "object": {"class": "KPIObservation", "properties": {}}}]
    for data in (legal_triple, illegal_triple, [], "not a list", None):
        va = new_mod._validate_extraction_format(data, SCHEMA)
        vb = old_mod._validate_extraction_format(data, SCHEMA)
        assert va == vb, f"_validate_extraction_format diverged for {data!r}"


def test_triple_list_to_graph_and_stamping_match():
    triples = [{
        "subject": {"class": "Organization", "properties": {
            "name": "CÔNG TY TEST", "valid_from": "2023-01-01", "valid_to": None, "is_current": True}},
        "predicate": "reportsKPI",
        "object": {"class": "KPIObservation", "properties": {
            "kpi_type": "ESG-1-1", "value": 1, "unit": "MWh",
            "valid_from": "2023-01-01", "valid_to": None, "is_current": True}},
        "temporal_metadata": {"valid_from": "2023-01-01", "valid_to": None, "recorded_at": "2023-01-01"},
    }]
    ga = new_mod.triple_list_to_graph(triples, SCHEMA)
    gb = old_mod.triple_list_to_graph(triples, SCHEMA)
    assert ga == gb, "triple_list_to_graph diverged"

    import copy
    for source in ("report", "news"):
        sa = new_mod.stamp_source_type(copy.deepcopy(ga), source)
        sb = old_mod.stamp_source_type(copy.deepcopy(gb), source)
        assert sa == sb, f"stamp_source_type diverged for source={source}"

        meta = {"title": "T", "url": "https://x/y", "source_domain": "x.vn"} if source == "news" else None
        pa = new_mod.stamp_provenance(copy.deepcopy(ga), "doc_2023", 1, source, meta)
        pb = old_mod.stamp_provenance(copy.deepcopy(gb), "doc_2023", 1, source, meta)
        assert pa == pb, f"stamp_provenance diverged for source={source}"


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


def test_call_llm_matches_across_response_shapes():
    prompts = [
        "prompt A - legal triple shape",
        "prompt B - empty array shape",
        "prompt C - malformed text shape",
        "prompt D - empty text shape",
    ]
    new_client, old_client = _FakeClient(), _FakeClient()
    new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
    old_rl = old_mod.RateLimiter(max_calls_per_minute=1000)
    for p in prompts:
        a = new_mod.call_llm(p, new_client, 0, new_rl, SCHEMA, "gemini-2.5-flash", retries=1)
        b = old_mod.call_llm(p, old_client, 0, old_rl, SCHEMA, "gemini-2.5-flash", retries=1)
        assert a == b, f"call_llm diverged for {p!r}: new={a} old={b}"

    assert len(new_client.calls_seen) == len(old_client.calls_seen)
    for nc, oc in zip(new_client.calls_seen, old_client.calls_seen):
        assert nc["temperature"] == 0 == oc["temperature"]
        assert nc["response_mime_type"] == "application/json" == oc["response_mime_type"]
        assert nc["system_instruction"] == oc["system_instruction"]
        assert nc["model"] == oc["model"]


def test_process_page_matches():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_02_page_"))
    try:
        for source in ("report", "news"):
            new_g, old_g = tmp / f"{source}_new_g", tmp / f"{source}_old_g"
            new_dbg, old_dbg = tmp / f"{source}_new_dbg", tmp / f"{source}_old_dbg"
            for d in (new_g, old_g, new_dbg, old_dbg):
                d.mkdir(parents=True)

            article_meta = {"title": "T", "url": "https://x/y", "source_domain": "x.vn",
                            "publish_date": "2024-08-14"} if source == "news" else None

            pages = [
                {"page": 1, "text": "Cong ty giam phat thai 20% trong nam.", "has_esg": True},
                {"page": 2, "text": "Khong co noi dung ESG.", "has_esg": False},
                {"page": 3, "text": "", "has_esg": False},
            ]
            new_client, old_client = _FakeClient(), _FakeClient()
            new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
            old_rl = old_mod.RateLimiter(max_calls_per_minute=1000)
            for pg in pages:
                new_mod.process_page(pg, [], new_client, 0, new_rl, SCHEMA, "gemini-2.5-flash",
                                     esg_only=True, pdf_stem="doc", dbg_pdf_dir=new_dbg, g_pdf_dir=new_g,
                                     company="AAA", year=2024, source=source, article_meta=article_meta)
                old_mod.process_page(pg, [], old_client, 0, old_rl, SCHEMA, "gemini-2.5-flash",
                                     esg_only=True, pdf_stem="doc", dbg_pdf_dir=old_dbg, g_pdf_dir=old_g,
                                     company="AAA", year=2024, source=source, article_meta=article_meta)

            new_files = sorted(p.name for p in new_g.glob("*"))
            old_files = sorted(p.name for p in old_g.glob("*"))
            assert new_files == old_files, f"[{source}] file set diverged: {new_files} vs {old_files}"
            for name in new_files:
                if name.endswith(".json"):
                    nj = json.loads((new_g / name).read_text(encoding="utf-8"))
                    oj = json.loads((old_g / name).read_text(encoding="utf-8"))
                    assert nj == oj, f"[{source}] {name} content diverged"

            # page 2 (not ESG) and page 3 (empty text) must never reach the client — only
            # page 1 can. How many calls page 1 itself takes depends on which of the 4 CRC
            # shapes its (large, schema-embedded) prompt happens to hash to — a legal-triple
            # shape resolves in 1 call, a losing shape retries up to process_page's own
            # max_retries x call_llm's retries — so the real equivalence property is that
            # BOTH trees make the same number of calls, not a specific constant.
            assert len(new_client.calls_seen) == len(old_client.calls_seen) > 0, (
                f"[{source}] call count diverged or vacuous: "
                f"new={len(new_client.calls_seen)} old={len(old_client.calls_seen)}")

            # Re-run page 1. `out_file.exists()` skip only fires if page 1's CRC-selected
            # response shape happened to succeed on the first pass (a losing shape leaves no
            # out_file, so a legitimate retry is expected) — that depends on the prompt's
            # hash, which this test does not control, but which is identical in both trees.
            # So the equivalence property is "both trees grow by the same amount", not "zero
            # growth" unconditionally.
            new_before, old_before = len(new_client.calls_seen), len(old_client.calls_seen)
            new_mod.process_page(pages[0], [], new_client, 0, new_rl, SCHEMA, "gemini-2.5-flash",
                                 esg_only=True, pdf_stem="doc", dbg_pdf_dir=new_dbg, g_pdf_dir=new_g,
                                 company="AAA", year=2024, source=source, article_meta=article_meta)
            old_mod.process_page(pages[0], [], old_client, 0, old_rl, SCHEMA, "gemini-2.5-flash",
                                 esg_only=True, pdf_stem="doc", dbg_pdf_dir=old_dbg, g_pdf_dir=old_g,
                                 company="AAA", year=2024, source=source, article_meta=article_meta)
            new_growth = len(new_client.calls_seen) - new_before
            old_growth = len(old_client.calls_seen) - old_before
            assert new_growth == old_growth, (
                f"[{source}] re-run call growth diverged: new={new_growth} old={old_growth}")
            if (new_g / "page1.json").exists():
                assert new_growth == 0, f"[{source}] page1.json exists but re-run still called the client"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_document_matches():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_02_doc_"))
    try:
        new_out, old_out = tmp / "new_out", tmp / "old_out"
        jsonl_pages = {
            1: [(0, "Cong ty giam phat thai 20% trong nam 2023.", True)],
            2: [(0, "Khong co noi dung ESG o trang nay.", False)],
        }
        new_client, old_client = _FakeClient(), _FakeClient()
        new_rl = new_mod.RateLimiter(max_calls_per_minute=1000)
        old_rl = old_mod.RateLimiter(max_calls_per_minute=1000)
        a = new_mod.process_document("AAA_Baocaothuongnien_2023.pdf", jsonl_pages, REPO / "kpi_output",
                                     new_out, SCHEMA, "gemini-2.5-flash", new_client, new_rl,
                                     esg_only=True, max_workers=1, source="report")
        b = old_mod.process_document("AAA_Baocaothuongnien_2023.pdf", jsonl_pages, REPO / "kpi_output",
                                     old_out, SCHEMA, "gemini-2.5-flash", old_client, old_rl,
                                     esg_only=True, max_workers=1, source="report")
        assert a == b, f"process_document (success, failed) diverged: new={a} old={b}"

        new_files = sorted(p.relative_to(new_out).as_posix() for p in new_out.rglob("*") if p.is_file())
        old_files = sorted(p.relative_to(old_out).as_posix() for p in old_out.rglob("*") if p.is_file())
        new_files = [f.replace("new_out", "").replace("AAA_Baocaothuongnien_2023", "DOC") for f in new_files]
        old_files = [f.replace("old_out", "").replace("AAA_Baocaothuongnien_2023", "DOC") for f in old_files]
        assert new_files == old_files, f"directory contents diverged: {new_files} vs {old_files}"
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
