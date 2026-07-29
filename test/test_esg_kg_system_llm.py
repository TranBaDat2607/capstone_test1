#!/usr/bin/env python3
"""
Real-LLM SYSTEM test: drives the actual `python src_module/run.py <stage> ...` CLI
commands, subprocess by subprocess, in the documented run order — proving the command
LINE entry points chain correctly, not just the underlying Python functions
(test_esg_kg_integration_llm.py covers those directly and is complementary, not
redundant: a stage's argparse wiring, env/dotenv loading, and file-path defaults are
only exercised by actually invoking `run.py` as a user would).

    extract -> extract_triples (report) -> extract_triples (news) -> build_validated
    -> issuer -> build_resolved -> align_claims -> claims_vs_conduct

against the synthetic BBB fixture, using the same provider selection (OpenAI gpt-4o-mini
if OPENAI_API_KEY authenticates, else Novita's OpenAI-compatible endpoint) as the
integration test. Steps 06/08/09 (Neo4j-dependent) are SKIP-GATED on a live connection
probe, not faked — this is a system test, so it should exercise the real thing when
available rather than paper over it with a stub.

OFF by default — makes real, billed LLM calls:

    RUN_LLM_SYSTEM_TEST=1 python test/test_esg_kg_system_llm.py

Everything is redirected into a throwaway temp workspace via each stage's own CLI path
flags; nothing here touches graph_output/, kpi_output/, or config/issuer_registry.json.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN_PY = REPO / "src_module" / "run.py"

if not os.environ.get("RUN_LLM_SYSTEM_TEST"):
    print("SKIPPED test_esg_kg_system_llm.py — set RUN_LLM_SYSTEM_TEST=1 to run "
          "(this makes real, billed LLM calls via subprocess).")
    sys.exit(0)

sys.path.insert(0, str(REPO / "src_module"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO / ".env", override=True)
from esg_kg.core.llm import _OpenAIProvider  # noqa: E402

NOVITA_BASE_URL = "https://api.novita.ai/v3/openai"
NOVITA_MODEL = "meta-llama/llama-3.1-8b-instruct"


def _select_provider():
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        probe = _OpenAIProvider("gpt-4o-mini", 60, api_key=openai_key)
        try:
            probe.client.models.list()
            return {"label": "openai", "model": "gpt-4o-mini", "api_key": openai_key, "base_url": None}
        except Exception as e:
            print(f"OPENAI_API_KEY present but did not authenticate ({e}); trying Novita.")
    novita_key = os.getenv("NOVITA_API_KEY")
    if novita_key:
        return {"label": "novita", "model": NOVITA_MODEL, "api_key": novita_key, "base_url": NOVITA_BASE_URL}
    return None


PROVIDER = _select_provider()
if PROVIDER is None:
    print("SKIPPED test_esg_kg_system_llm.py — neither OPENAI_API_KEY nor NOVITA_API_KEY authenticated.")
    sys.exit(0)
print(f"System test using provider={PROVIDER['label']!r} model={PROVIDER['model']!r}")

REPORT_INPUT = REPO / "data" / "labeled" / "annual_labeled" / "labeled_annual_report_company_bbb.jsonl"
NEWS_INPUT = REPO / "data" / "interim" / "news_preprocessed" / "bbb_news_classified_preprocessed.jsonl"
KPI_DEFS = REPO / "kpi_definitions_construction.json"
SCHEMA_PATH = REPO / "config" / "schema.json"


def _neo4j_reachable() -> bool:
    uri = os.getenv("NEO4J_URI", "bolt://localhost:8687")
    host_port = uri.split("://", 1)[-1]
    host, _, port = host_port.partition(":")
    try:
        with socket.create_connection((host, int(port or 7687)), timeout=2):
            return True
    except OSError:
        return False


def _make_companies_xlsx(tmp: Path) -> Path:
    import pandas as pd
    path = tmp / "company_annual_report.xlsx"
    pd.DataFrame([{
        "Mã CK": "BBB", "Tên công ty": "Công ty Cổ phần BBB Xanh",
        "Tên tài liệu": "Báo cáo thường niên", "Năm": 2024, "URL": "",
    }]).to_excel(path, index=False)
    return path


def _run(args: list, env: dict, timeout: int = 900) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(RUN_PY)] + args
    print(f"$ {' '.join(str(a) for a in cmd)}")
    return subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout)


def _assert_ok(proc: subprocess.CompletedProcess, label: str) -> None:
    if proc.returncode != 0:
        raise AssertionError(
            f"{label} exited {proc.returncode}\n--- stdout ---\n{proc.stdout[-3000:]}\n"
            f"--- stderr ---\n{proc.stderr[-3000:]}")


def test_full_llm_chain_via_run_py_cli():
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_system_"))
    try:
        model, api_key, base_url = PROVIDER["model"], PROVIDER["api_key"], PROVIDER["base_url"]
        label = PROVIDER["label"]

        env = os.environ.copy()
        env["OPENAI_API_KEY"] = api_key
        openai_flags = ["--provider", "openai", "--openai-model", model]
        # align_claims/claims_vs_conduct are OpenAI-only stages (no gemini path to
        # choose between), so they have no --provider flag at all.
        openai_only_flags = ["--openai-model", model]
        if base_url:
            openai_flags += ["--openai-base-url", base_url]
            openai_only_flags += ["--openai-base-url", base_url]

        kpi_out = tmp / "kpi_output"
        graphs_out = tmp / "graph_output"
        validated_out = tmp / "validated"
        issuer_out = tmp / "issuer_registry.json"
        resolved_out = tmp / "resolved"

        # --- step01: extract (real LLM via CLI) -----------------------------------
        proc = _run(["extract", "--doc", "BBB_Baocaothuongnien_2024",
                    "-i", str(REPORT_INPUT), "-o", str(kpi_out)] + openai_flags, env)
        _assert_ok(proc, "extract")
        kpi_files = list((kpi_out / "BBB_Baocaothuongnien_2024_kpis").glob("page_*_kpis.json"))
        assert len(kpi_files) == 4, f"expected 4 page file(s), got {len(kpi_files)}"
        print(f"PASS extract ({label}) via CLI: {len(kpi_files)} page file(s) written")

        # --- step02: extract_triples (report + news, real LLM via CLI) -----------
        proc = _run(["extract_triples", "--doc", "BBB_Baocaothuongnien_2024",
                    "-i", str(REPORT_INPUT), "--kpi-dir", str(kpi_out),
                    "-o", str(graphs_out), "--source", "report"] + openai_flags, env)
        _assert_ok(proc, "extract_triples (report)")

        # A single news page occasionally 401s on Novita's gateway right after a burst
        # of report-page calls (reproduced directly outside this test too — the SAME
        # key/base_url succeeds in isolation seconds later, so this is a third-party
        # rate-limit/cooldown artifact of the free testing host, not a pipeline bug).
        # process_document is idempotent per page (skips a page whose output file
        # already exists), so a bare re-invocation after a pause is a safe, honest
        # retry — it either fills in the missing page or is a no-op.
        news_dir_name = "BBB__baodautu.vn__b1a2c3d4e5"
        for attempt in range(2):
            proc = _run(["extract_triples", "-i", str(NEWS_INPUT), "--kpi-dir", str(kpi_out),
                        "-o", str(graphs_out), "--source", "news"] + openai_flags, env)
            _assert_ok(proc, "extract_triples (news)")
            news_files = list((graphs_out / "graphs" / news_dir_name).glob("page*.json")) \
                if (graphs_out / "graphs" / news_dir_name).exists() else []
            if news_files:
                break
            if attempt == 0:
                print("News page produced no output (likely a Novita rate-limit blip); "
                      "waiting 15s and retrying once.")
                time.sleep(15)

        graph_files = [f for f in (graphs_out / "graphs").rglob("page*.json")
                       if "_bugged" not in f.stem and "_malformed" not in f.name]
        assert len(graph_files) == 5, f"expected 5 page graph file(s) (4 report + 1 news), got {len(graph_files)}"
        print(f"PASS extract_triples ({label}) via CLI: {len(graph_files)} page graph file(s) (report + news)")

        # --- build_validated block (03 -> 03b -> 03c), real LLM phase-2 via CLI ---
        proc = _run(["build_validated", "-i", str(graphs_out / "graphs"), "-o", str(validated_out),
                    "--cache", str(validated_out / "phase2_repairs.json")] + openai_flags, env)
        _assert_ok(proc, "build_validated")
        validated_file = validated_out / "all_validated_triples.json"
        assert validated_file.exists()
        triples = json.loads(validated_file.read_text(encoding="utf-8"))
        assert len(triples) > 0, "build_validated produced zero triples"
        print(f"PASS build_validated ({label}) via CLI: {len(triples)} triple(s)")

        # --- step04: issuer registry draft (offline; scratch xlsx) ---------------
        companies_xlsx = _make_companies_xlsx(tmp)
        proc = _run(["issuer", "-i", str(validated_file), "--companies", str(companies_xlsx),
                    "-o", str(issuer_out)], env)
        _assert_ok(proc, "issuer")
        registry = json.loads(issuer_out.read_text(encoding="utf-8"))
        assert "BBB" in registry, f"step04 did not draft a BBB entry via CLI — keys: {sorted(registry)}"
        print(f"PASS issuer via CLI: drafted {sorted(registry)}")

        # --- build_resolved block (05 -> 05b -> 05c) ------------------------------
        # no_llm under Novita (no embedding models there) — same reasoning as the
        # integration test; matches step05's actual production default today.
        resolve_flags = list(openai_flags)
        if base_url:
            resolve_flags = ["--no-llm"]
        proc = _run(["build_resolved", "-i", str(validated_file), "-o", str(resolved_out),
                    "--graphs-dir", str(graphs_out / "graphs"), "--registry", str(issuer_out)]
                    + resolve_flags, env)
        _assert_ok(proc, "build_resolved")
        resolved_file = resolved_out / "resolved_graph.json"
        assert resolved_file.exists()
        resolved = json.loads(resolved_file.read_text(encoding="utf-8"))
        assert len(resolved["nodes"]) > 0
        print(f"PASS build_resolved ({label}) via CLI: {len(resolved['nodes'])} node(s) / "
              f"{len(resolved['edges'])} edge(s)")

        # --- step05d: align_claims (real LLM via CLI) -----------------------------
        align_stats_out = tmp / "indicator_align_llm_stats.json"
        proc = _run(["align_claims", "-i", str(resolved_file), "--max-llm-pairs", "5",
                    "--stats-out", str(align_stats_out)] + openai_only_flags, env)
        _assert_ok(proc, "align_claims")
        print(f"PASS align_claims ({label}) via CLI: {align_stats_out.exists()}")

        # --- step07: claims_vs_conduct (real LLM, mandatory, via CLI) ------------
        dossier_dir = tmp / "crosscheck"
        proc = _run(["claims_vs_conduct", "-i", str(resolved_file), "-o", str(dossier_dir),
                    "--ticker", "BBB", "--max-llm-pairs", "5"] + openai_only_flags, env)
        _assert_ok(proc, "claims_vs_conduct")
        dossier_files = list(dossier_dir.glob("*_claim_assessments.json"))
        print(f"PASS claims_vs_conduct ({label}) via CLI: wrote {[f.name for f in dossier_files]}")

        # --- steps 06/08/09: Neo4j-dependent, skip-gated on a live connection ----
        if not _neo4j_reachable():
            print("SKIP steps 06/08/09 (neo4j_load/neo4j_sync/claim_ledger) — Neo4j "
                  "unreachable (Docker Desktop not running). Known gap for this run, "
                  "not silently faked.")
        else:
            proc = _run(["neo4j_load", "-i", str(resolved_file), "--clear"], env)
            _assert_ok(proc, "neo4j_load")
            proc = _run(["neo4j_sync", "-i", str(dossier_dir), "--ticker", "BBB"], env)
            _assert_ok(proc, "neo4j_sync")
            proc = _run(["claim_ledger", "--ticker", "BBB"], env)
            _assert_ok(proc, "claim_ledger")
            print("PASS neo4j_load / neo4j_sync / claim_ledger via CLI (live Neo4j)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
