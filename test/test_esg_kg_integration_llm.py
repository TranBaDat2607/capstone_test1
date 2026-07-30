#!/usr/bin/env python3
"""
Real-LLM integration test: steps 01 -> 02 -> build_validated -> issuer -> build_resolved
-> align_claims -> claims_vs_conduct, chained end-to-end through the actual `esg_kg`
functions (not `src/`), driven by REAL OpenAI (gpt-4o-mini + text-embedding-3-small)
calls against the synthetic BBB fixture:

    data/labeled/annual_labeled/labeled_annual_report_company_bbb.jsonl   (report/claim side)
    data/interim/news_preprocessed/bbb_news_classified_preprocessed.jsonl (news/conduct side)

WHY THIS IS NOT PART OF THE FREE/OFFLINE SUITE
Every other test/test_esg_kg_*.py is offline and free per CLAUDE.md's TDD rule — a stub
sits over `_OpenAIProvider`/`google.genai.Client` so nothing here ever spends money by
accident. This file is the deliberate, explicitly authorized exception: it proves the
OpenAI provider paths added to steps 01/02/03/05 (2026-07-29, alongside this file) work
against the REAL API, not just a stub that could itself be wrong about the API's shape.
It is OFF by default — running the whole suite (or this file bare) never calls out:

    RUN_LLM_INTEGRATION_TESTS=1 python test/test_esg_kg_integration_llm.py

Scope is deliberately the tiny BBB fixture ONLY (4 report pages + 1 news page), never the
real AAA corpus — CLAUDE.md's "never verify by re-running a paid stage" rule means a
13,541-sentence corpus is not what a plumbing check should cost.

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

from esg_kg.core.llm import RateLimiter, _OpenAIEmbeddingProvider, _OpenAIProvider  # noqa: E402

# --------------------------------------------------------------------------- #
# Provider selection: prefer real OpenAI (gpt-4o-mini, the production default
# baked into step05d/step07's own --openai-model flags) if OPENAI_API_KEY is
# present AND actually authenticates; otherwise fall back to NOVITA_API_KEY via
# Novita's OpenAI-compatible endpoint with an explicit model id (Novita hosts open-
# weight models only — it has no "gpt-4o-mini"). Either way this is a ONE-OFF test
# override via _OpenAIProvider's api_key=/base_url= params (esg_kg/core/llm.py,
# 2026-07-29) — no stage's own default provider/model changes.
#
# Novita has NO embedding models (confirmed live via client.models.list() — zero
# ids matching embed/bge/gte/e5), so under the Novita fallback, step05 Stage B/C
# (entity resolution's embedding-blocking + adjudication) is run with no_llm=True
# instead of a fabricated embedding path. That is not a downgrade of THIS test —
# CLAUDE.md records --no-llm as step05's actual real-world default today (Gemini
# billing-blocked), so this fallback exercises the pipeline exactly as it already
# runs in production, just with the newly-added OpenAI-shaped chat path swapped in
# for steps 01/02/03/05d/07.
# --------------------------------------------------------------------------- #
NOVITA_BASE_URL = "https://api.novita.ai/v3/openai"
NOVITA_MODEL = "meta-llama/llama-3.1-8b-instruct"


def _select_provider():
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        probe = _OpenAIProvider("gpt-4o-mini", 60, api_key=openai_key)
        try:
            probe.client.models.list()
            return {"label": "openai", "model": "gpt-4o-mini", "api_key": openai_key,
                    "base_url": None, "embeddings": True}
        except Exception as e:
            print(f"OPENAI_API_KEY present but did not authenticate ({e}); trying Novita.")

    novita_key = os.getenv("NOVITA_API_KEY")
    if novita_key:
        return {"label": "novita", "model": NOVITA_MODEL, "api_key": novita_key,
                "base_url": NOVITA_BASE_URL, "embeddings": False}
    return None


PROVIDER = _select_provider()
if PROVIDER is None:
    print("SKIPPED test_esg_kg_integration_llm.py — neither OPENAI_API_KEY nor "
          "NOVITA_API_KEY authenticated.")
    sys.exit(0)
print(f"Real-LLM integration test using provider={PROVIDER['label']!r} model={PROVIDER['model']!r} "
      f"(embeddings {'enabled' if PROVIDER['embeddings'] else 'unavailable -> step05 runs --no-llm'})")
from esg_kg.core.io_jsonl import load_pages_from_jsonl, select_documents  # noqa: E402
from esg_kg.graph import build_validated, extract_triples  # noqa: E402
from esg_kg.kpi import extract as kpi_extract  # noqa: E402
from esg_kg.registry import issuer  # noqa: E402
from esg_kg.resolve import align_claims, build_resolved  # noqa: E402
from esg_kg.crosscheck import claims_vs_conduct  # noqa: E402

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
        model, api_key, base_url = PROVIDER["model"], PROVIDER["api_key"], PROVIDER["base_url"]
        label = PROVIDER["label"]
        chat = _OpenAIProvider(model, 60, api_key=api_key, base_url=base_url)
        rl = RateLimiter(max_calls_per_minute=60)
        assert chat.enabled, f"{label} chat provider failed to enable"

        # --- step01: KPI extraction (real LLM) ------------------------------------
        kpi_out = tmp / "kpi_output"
        extractor = kpi_extract.KPIExtractor(
            KPI_DEFS, provider="openai", openai_model=model,
            openai_api_key=api_key, openai_base_url=base_url)
        docs = load_pages_from_jsonl(REPORT_INPUT)
        selected = select_documents(docs, argparse.Namespace(doc=None, limit_docs=None, all=True))
        assert selected == ["BBB_Baocaothuongnien_2024.pdf"], selected
        total_kpis = extractor.process_document(
            selected[0], docs[selected[0]], kpi_out, esg_only=True, max_workers=2)
        # process_document writes a file for EVERY page (all 4) — non-ESG pages (page 1)
        # get [] without a real LLM call; only the 3 esg-flagged pages are real calls.
        kpi_files = sorted((kpi_out / "BBB_Baocaothuongnien_2024_kpis").glob("page_*_kpis.json"))
        assert len(kpi_files) == 4, f"expected 4 page file(s) (1 skipped + 3 esg), got {len(kpi_files)}"
        for f in kpi_files:
            assert isinstance(json.loads(f.read_text(encoding="utf-8")), list), f"{f.name} not a JSON list"
        assert json.loads((kpi_out / "BBB_Baocaothuongnien_2024_kpis" / "page_001_kpis.json")
                          .read_text(encoding="utf-8")) == [], "non-ESG page 1 should be an empty list"
        print(f"PASS step01 ({label}): {total_kpis} KPI(s) extracted across {len(kpi_files)} page file(s) "
              f"(3 esg-flagged pages sent to the LLM)")

        # --- step02: triple extraction (real LLM), report + news -----------------
        graphs_out = tmp / "graph_output"
        # like step01, process_document counts EVERY page as "succeeded" (all 4 —
        # 1 auto-empty non-ESG page + 3 real LLM calls), not just the ESG-flagged ones.
        r_success, r_failed = extract_triples.process_document(
            selected[0], docs[selected[0]], kpi_out, graphs_out, schema, model,
            chat, rl, esg_only=True, max_workers=2, source="report", provider="openai")
        assert r_failed == 0, f"{r_failed} report page(s) failed"
        assert r_success == 4, r_success

        news_docs = load_pages_from_jsonl(NEWS_INPUT)
        news_meta = extract_triples.load_news_doc_meta(NEWS_INPUT)
        news_src = next(iter(news_docs))
        n_success, n_failed = extract_triples.process_document(
            news_src, news_docs[news_src], kpi_out, graphs_out, schema, model,
            chat, rl, esg_only=True, max_workers=1, source="news",
            doc_meta=news_meta.get(news_src), provider="openai")
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
        print(f"PASS step02 ({label}): {total_nodes} node(s) / {total_edges} edge(s) across "
              f"{len(graph_files)} page file(s) (report + news)")

        # --- build_validated block (03 -> 03b -> 03c), real LLM phase-2 repair ---
        validated_out = tmp / "validated"
        fix_stats = build_validated.run_block(
            input_dir=graphs_out / "graphs", out_dir=validated_out, schema=schema,
            client=chat, rate_limiter=rl, model=model, dry_run=False)
        validated_file = validated_out / "all_validated_triples.json"
        assert validated_file.exists()
        triples = json.loads(validated_file.read_text(encoding="utf-8"))
        assert len(triples) > 0, "build_validated produced zero triples"
        print(f"PASS build_validated ({label}): {len(triples)} triple(s), fix stats={fix_stats['fix']}")

        # --- step04: issuer registry draft (offline; scratch xlsx + output) ------
        companies_xlsx = _make_companies_xlsx(tmp)
        issuer_out = tmp / "issuer_registry.json"
        issuer.build(validated_file, companies_xlsx, issuer_out,
                     min_subject_edges=issuer.DEFAULT_MIN_SUBJECT_EDGES, force=False,
                     graph_sim_upper=0.8, graph_sim_lower=0.2)
        registry = json.loads(issuer_out.read_text(encoding="utf-8"))
        assert "BBB" in registry, f"step04 did not draft a BBB entry — registry keys: {sorted(registry)}"
        print(f"PASS issuer (offline): drafted {sorted(registry)} "
              f"({len(registry['BBB']['aliases'])} aliases, {len(registry['BBB']['needs_review'])} needs_review)")

        # --- build_resolved block (05 -> 05b -> 05c) ------------------------------
        # Stage B/C only runs with real embeddings available (OpenAI). Under the
        # Novita fallback (no embedding models) this is no_llm=True — today's actual
        # production default per CLAUDE.md, not a weakened version of this test.
        resolved_out = tmp / "resolved"
        embed_kwargs = {}
        if PROVIDER["embeddings"]:
            embed = _OpenAIEmbeddingProvider("text-embedding-3-small", 60, api_key=api_key, base_url=base_url)
            assert embed.enabled
            embed_kwargs = {"client": chat, "embed_client": embed, "no_llm": False}
        else:
            embed_kwargs = {"no_llm": True}
        resolve_stats = build_resolved.run_block(
            input_path=validated_file, out_dir=resolved_out, schema=schema,
            graphs_dir=graphs_out / "graphs", registry_path=issuer_out,
            rate_limiter=rl, model=model, embed_model="text-embedding-3-small",
            dry_run=False, **embed_kwargs)
        resolved_file = resolved_out / "resolved_graph.json"
        assert resolved_file.exists()
        resolved = json.loads(resolved_file.read_text(encoding="utf-8"))
        assert len(resolved["nodes"]) > 0
        orgs = [n for n in resolved["nodes"] if n.get("class") == "Organization"]
        tickers = {n["properties"].get("ticker") for n in orgs if n["properties"].get("ticker")}
        print(f"PASS build_resolved ({label}, no_llm={embed_kwargs.get('no_llm', False)}): "
              f"{len(resolved['nodes'])} node(s) / {len(resolved['edges'])} edge(s), "
              f"{len(orgs)} Organization node(s), ticker(s) stamped: {tickers or '(none)'}")

        # --- step05d: align remaining claims to indicators (real LLM) ------------
        align_args = argparse.Namespace(
            input=resolved_file, defs=INDICATOR_DEFS, schema=SCHEMA_PATH,
            max_llm_pairs=5, openai_model=model, rate_limit=60,
            openai_api_key=api_key, openai_base_url=base_url,
            stats_out=tmp / "indicator_align_llm_stats.json", dry_run=False)
        align_claims.run(align_args)
        assert align_args.stats_out.exists()
        align_stats = json.loads(align_args.stats_out.read_text(encoding="utf-8"))
        print(f"PASS align_claims ({label}): {align_stats}")

        # --- step07: claim <-> conduct crosscheck (real LLM, mandatory) ----------
        dossier_dir = tmp / "crosscheck"
        cc_args = argparse.Namespace(
            input=resolved_file, schema=SCHEMA_PATH, out_dir=dossier_dir, ticker="BBB",
            top_k=claims_vs_conduct.DEFAULT_TOP_K,
            window_before=claims_vs_conduct.DEFAULT_WINDOW_BEFORE,
            window_after=claims_vs_conduct.DEFAULT_WINDOW_AFTER,
            max_llm_pairs=5, openai_model=model, provider_order=["openai"],
            openai_api_key=api_key, openai_base_url=base_url,
            max_workers=2, rate_limit=60, embed=False, dry_run=False,
            to_neo4j=False, database=None)
        claims_vs_conduct.run(cc_args)
        dossier_files = list(dossier_dir.glob("*_claim_assessments.json"))
        print(f"PASS claims_vs_conduct ({label}): wrote {[f.name for f in dossier_files]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
