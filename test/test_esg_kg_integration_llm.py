#!/usr/bin/env python3
"""
Real-LLM integration test: steps 01 -> 02 -> build_validated -> issuer -> build_resolved
-> align_claims -> claims_vs_conduct, chained end-to-end through the actual `esg_kg`
functions (not `src/`), driven by REAL Gemini (gemini-2.5-flash + gemini-embedding-001)
calls against the synthetic BBB fixture:

    data/labeled/annual_labeled/labeled_annual_report_company_bbb.jsonl   (report/claim side)
    data/interim/news_preprocessed/bbb_news_classified_preprocessed.jsonl (news/conduct side)

WHY THIS IS NOT PART OF THE FREE/OFFLINE SUITE
Every other test/test_esg_kg_*.py is offline and free per CLAUDE.md's TDD rule — a stub
sits over `_GeminiProvider`/`google.genai.Client` so nothing here ever spends money by
accident. This file is the deliberate, explicitly authorized exception: it proves the
whole chain works against the REAL API, not just a stub that could itself be wrong about
the API's shape. It is OFF by default — running the whole suite (or this file bare)
never calls out:

    RUN_LLM_INTEGRATION_TESTS=1 python test/test_esg_kg_integration_llm.py

Scope is deliberately the tiny BBB fixture ONLY (4 report pages + 1 news page), never the
real AAA corpus — CLAUDE.md's "never verify by re-running a paid stage" rule means a
13,541-sentence corpus is not what a plumbing check should cost.

2026-08-04: the OpenAI/Novita provider selection this file used to drive (added
2026-07-29 while Gemini was billing-blocked) was removed outright along with
`_OpenAIProvider`/`_OpenAIEmbeddingProvider` themselves — no OpenAI fallback anywhere in
this project any more. This file now drives every stage's Gemini default directly
(`_GeminiProvider`, `genai.Client`), no `provider=`/`openai_*` kwargs anywhere.

Everything writes into a throwaway temp workspace (including a scratch copy of
config/company_annual_report.xlsx with one synthetic BBB row so step04 can draft a
registry entry — the real tracked xlsx is never touched, same precedent as
test_esg_kg_issuer.py). Assertions are structural (non-empty, well-formed, chain didn't
error), not exact-content, because a real LLM reply is not deterministic.

Run from the repo root:

    RUN_LLM_INTEGRATION_TESTS=1 python test/test_esg_kg_integration_llm.py
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

if not os.environ.get("RUN_LLM_INTEGRATION_TESTS"):
    print("SKIPPED test_esg_kg_integration_llm.py — set RUN_LLM_INTEGRATION_TESTS=1 to run "
          "(this makes real, billed LLM calls).")
    sys.exit(0)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO / ".env", override=True)

from esg_kg.core.llm import RateLimiter, _GeminiProvider  # noqa: E402

CHAT_MODEL = "gemini-2.5-flash"
EMBED_MODEL = "gemini-embedding-001"


def _gemini_available():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    probe = _GeminiProvider(CHAT_MODEL, 60, api_key=api_key)
    try:
        next(iter(probe.client.models.list()), None)
        return {"model": CHAT_MODEL, "api_key": api_key}
    except Exception as e:
        print(f"GEMINI_API_KEY present but did not authenticate ({e}).")
        return None


PROVIDER = _gemini_available()
if PROVIDER is None:
    print("SKIPPED test_esg_kg_integration_llm.py — GEMINI_API_KEY not set or did not authenticate.")
    sys.exit(0)
print(f"Real-LLM integration test using provider='gemini' model={PROVIDER['model']!r}")
from esg_kg.core.io_jsonl import load_pages_from_jsonl, select_documents  # noqa: E402
from esg_kg.graph import build_validated, extract_triples  # noqa: E402
from esg_kg.kpi import extract as kpi_extract  # noqa: E402
from esg_kg.registry import issuer  # noqa: E402
from esg_kg.resolve import align_claims, build_resolved  # noqa: E402
from esg_kg.crosscheck import claims_vs_conduct  # noqa: E402
from google import genai  # noqa: E402

REPORT_INPUT = REPO / "data" / "labeled" / "annual_labeled" / "labeled_annual_report_company_bbb.jsonl"
NEWS_INPUT = REPO / "data" / "interim" / "news_preprocessed" / "bbb_news_classified_preprocessed.jsonl"
KPI_DEFS = REPO / "kpi_definitions_construction.json"
SCHEMA_PATH = REPO / "config" / "schema.json"
INDICATOR_DEFS = KPI_DEFS  # same 35-KPI vocabulary file step05d aligns against


def _make_companies_xlsx(tmp: Path) -> Path:
    """A scratch ticker->name table with just the synthetic BBB row, so step04 can draft
    a registry entry without touching the real 1,359-row config/company_annual_report.xlsx."""
    import pandas as pd
    path = tmp / "company_annual_report.xlsx"
    pd.DataFrame([{
        "Mã CK": "BBB", "Tên công ty": "Công ty Cổ phần BBB Xanh",
        "Tên tài liệu": "Báo cáo thường niên", "Năm": 2024, "URL": "",
    }]).to_excel(path, index=False)
    return path


def test_full_llm_chain_on_bbb_fixture():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_llm_integration_"))
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        model, api_key = PROVIDER["model"], PROVIDER["api_key"]
        client = genai.Client(api_key=api_key)
        rl = RateLimiter(max_calls_per_minute=60)

        kpi_out = tmp / "kpi_output"
        extractor = kpi_extract.KPIExtractor(KPI_DEFS, model=model)
        docs = load_pages_from_jsonl(REPORT_INPUT)
        selected = select_documents(docs, argparse.Namespace(doc=None, limit_docs=None, all=True))
        assert selected == ["BBB_Baocaothuongnien_2024.pdf"], selected
        total_kpis = extractor.process_document(
            selected[0], docs[selected[0]], kpi_out, esg_only=True, max_workers=2)
        kpi_files = sorted((kpi_out / "BBB_Baocaothuongnien_2024_kpis").glob("page_*_kpis.json"))
        assert len(kpi_files) == 4, f"expected 4 page file(s) (1 skipped + 3 esg), got {len(kpi_files)}"
        for f in kpi_files:
            assert isinstance(json.loads(f.read_text(encoding="utf-8")), list), f"{f.name} not a JSON list"
        assert json.loads((kpi_out / "BBB_Baocaothuongnien_2024_kpis" / "page_001_kpis.json")
                          .read_text(encoding="utf-8")) == [], "non-ESG page 1 should be an empty list"
        print(f"PASS step01 (gemini): {total_kpis} KPI(s) extracted across {len(kpi_files)} page file(s) "
              f"(3 esg-flagged pages sent to the LLM)")

        graphs_out = tmp / "graph_output"
        r_success, r_failed = extract_triples.process_document(
            selected[0], docs[selected[0]], kpi_out, graphs_out, schema, model,
            client, rl, esg_only=True, max_workers=2, source="report")
        assert r_failed == 0, f"{r_failed} report page(s) failed"
        assert r_success == 4, r_success

        news_docs = load_pages_from_jsonl(NEWS_INPUT)
        news_meta = extract_triples.load_news_doc_meta(NEWS_INPUT)
        news_src = next(iter(news_docs))
        n_success, n_failed = extract_triples.process_document(
            news_src, news_docs[news_src], kpi_out, graphs_out, schema, model,
            client, rl, esg_only=True, max_workers=1, source="news",
            doc_meta=news_meta.get(news_src))
        assert n_failed == 0, f"{n_failed} news page(s) failed"
        assert n_success == 1, n_success

        graph_files = [f for f in (graphs_out / "graphs").rglob("page*.json")
                       if "_bugged" not in f.stem and "_malformed" not in f.name]
        total_nodes = total_edges = 0
        for f in graph_files:
            g = json.loads(f.read_text(encoding="utf-8"))
            total_nodes += len(g.get("nodes", []))
            total_edges += len(g.get("edges", []))
        assert total_nodes > 0, "step02 produced zero nodes across the whole BBB fixture"
        print(f"PASS step02 (gemini): {total_nodes} node(s) / {total_edges} edge(s) across "
              f"{len(graph_files)} page file(s) (report + news)")

        validated_out = tmp / "validated"
        fix_stats = build_validated.run_block(
            input_dir=graphs_out / "graphs", out_dir=validated_out, schema=schema,
            client=client, rate_limiter=rl, model=model, dry_run=False)
        validated_file = validated_out / "all_validated_triples.json"
        assert validated_file.exists()
        triples = json.loads(validated_file.read_text(encoding="utf-8"))
        assert len(triples) > 0, "build_validated produced zero triples"
        print(f"PASS build_validated (gemini): {len(triples)} triple(s), fix stats={fix_stats['fix']}")

        companies_xlsx = _make_companies_xlsx(tmp)
        issuer_out = tmp / "issuer_registry.json"
        issuer.build(validated_file, companies_xlsx, issuer_out,
                     min_subject_edges=issuer.DEFAULT_MIN_SUBJECT_EDGES, force=False,
                     graph_sim_upper=0.8, graph_sim_lower=0.2)
        registry = json.loads(issuer_out.read_text(encoding="utf-8"))
        assert "BBB" in registry, f"step04 did not draft a BBB entry — registry keys: {sorted(registry)}"
        print(f"PASS issuer (offline): drafted {sorted(registry)} "
              f"({len(registry['BBB']['aliases'])} aliases, {len(registry['BBB']['needs_review'])} needs_review)")

        resolved_out = tmp / "resolved"
        resolve_stats = build_resolved.run_block(
            input_path=validated_file, out_dir=resolved_out, schema=schema,
            graphs_dir=graphs_out / "graphs", registry_path=issuer_out,
            rate_limiter=rl, model=model, embed_model=EMBED_MODEL,
            dry_run=False, no_llm=True)
        resolved_file = resolved_out / "resolved_graph.json"
        assert resolved_file.exists()
        resolved = json.loads(resolved_file.read_text(encoding="utf-8"))
        assert len(resolved["nodes"]) > 0
        orgs = [n for n in resolved["nodes"] if n.get("class") == "Organization"]
        tickers = {n["properties"].get("ticker") for n in orgs if n["properties"].get("ticker")}
        print(f"PASS build_resolved (gemini, no_llm=True): "
              f"{len(resolved['nodes'])} node(s) / {len(resolved['edges'])} edge(s), "
              f"{len(orgs)} Organization node(s), ticker(s) stamped: {tickers or '(none)'}")

        align_args = argparse.Namespace(
            input=resolved_file, defs=INDICATOR_DEFS, schema=SCHEMA_PATH,
            max_llm_pairs=5, model=model, rate_limit=60,
            stats_out=tmp / "indicator_align_llm_stats.json", dry_run=False)
        align_claims.run(align_args)
        assert align_args.stats_out.exists()
        align_stats = json.loads(align_args.stats_out.read_text(encoding="utf-8"))
        print(f"PASS align_claims (gemini): {align_stats}")

        dossier_dir = tmp / "crosscheck"
        cc_args = argparse.Namespace(
            input=resolved_file, schema=SCHEMA_PATH, out_dir=dossier_dir, ticker="BBB",
            top_k=claims_vs_conduct.DEFAULT_TOP_K,
            window_before=claims_vs_conduct.DEFAULT_WINDOW_BEFORE,
            window_after=claims_vs_conduct.DEFAULT_WINDOW_AFTER,
            max_llm_pairs=5, model=model, provider_order=["gemini"],
            max_workers=2, rate_limit=60, embed=False, dry_run=False,
            to_neo4j=False, database=None)
        claims_vs_conduct.run(cc_args)
        dossier_files = list(dossier_dir.glob("*_claim_assessments.json"))
        print(f"PASS claims_vs_conduct (gemini): wrote {[f.name for f in dossier_files]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
