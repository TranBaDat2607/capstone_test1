# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **ESG Greenwashing Detection Pipeline** for Vietnamese corporate ESG disclosures. It uses a Knowledge Graph (KG) + Contrastive Graph RAG + Actor-Critic RL to audit ESG claims from annual reports and news against regulatory frameworks (TT96/2020, TT08/2026).

## Commands

### Install dependencies
```bash
pip install -r requirements.txt
```

### Run the pipeline
```bash
# Full audit (requires ontology/sample_instances.json to exist)
python main.py --company COMP_FPT --report RPT_FPT_ESG_2023

# With news loading
python main.py --company COMP_FPT --report RPT_FPT_ESG_2023 --load-news

# With PDF extraction
python main.py --company COMP_FPT --report RPT_FPT_ESG_2023 --pdf data/raw/crawled_annual_report/<file>.pdf

# With evaluation against baselines
python main.py --company COMP_FPT --report RPT_FPT_ESG_2023 --evaluate

# Print KG stats only
python main.py --stats
```

### Build ontology data
```bash
python generators/build_ontology_from_pdfs.py   # regenerate framework_indicators.json (no LLM, uses pdfplumber + regex)
python generators/build_instances.py             # regenerate sample_instances.json (requires ANTHROPIC_API_KEY)
```

### KG quality evaluation
```bash
# Tier 1 only — schema + structural metrics (free, no API key needed)
python -m evaluation.kg_quality.runner --mode intrinsic

# Tier 1 + 2 — adds BM25 + LLM grounding verification (requires ANTHROPIC_API_KEY)
python -m evaluation.kg_quality.runner \
  --extraction-result output/extracted/2023-fpt-esg-report/extraction_result.json \
  --mode rag

# Custom paths
python -m evaluation.kg_quality.runner \
  --instances ontology/sample_instances.json \
  --indicators ontology/framework_indicators.json \
  --extraction-result output/extracted/2023-fpt-esg-report/extraction_result.json \
  --eval-model claude-haiku-4-5-20251001 \
  --mode all \
  --out output/kg_eval_report.json
```

### Run the news crawler only
```bash
cd crawl_data
pip install -r requirements.txt
python crawler_news.py
```

## Architecture

The pipeline runs in 5 sequential phases:

**Phase A — Data & KG Construction**
- `generators/build_ontology_from_pdfs.py` extracts indicator definitions from GRI PDFs + manual Vietnamese regulations → `ontology/framework_indicators.json`
- `generators/build_instances.py` uses Claude (`claude-sonnet-4-20250514`) to extract claims from report blocks → `ontology/sample_instances.json`
- `kg/graph_builder.py` loads `sample_instances.json` into the in-memory NetworkX MultiDiGraph (`kg/graph_store.py`)
- `extraction/news_processor.py` ingests news as `NewsEvent` nodes; negative-sentiment news auto-creates `contradicted_by` edges
- `extraction/pdf_parser.py` (pdfplumber primary, PyMuPDF fallback) + `extraction/nlp_pipeline.py` (LLM-based) extract entities from PDFs

**Phase B — Contrastive Graph RAG**
- `retrieval/contrastive_graph_rag.py` retrieves two subgraphs per claim: PRO (supporting) and ANTI (contradicting)
- `retrieval/path_scorer.py` ranks paths by composite score: 50% confidence, 25% recency, 25% source reliability

**Phase C — RL Reasoning**
- `reasoning/rl_agent.py` runs an in-context Actor-Critic loop (no gradient updates): Actor generates reasoning steps, Critic rewards steps citing valid KG nodes (+1) and penalizes unsupported claims (-1)
- `reasoning/verdict_generator.py` orchestrates single-claim and company-level audits

**Phase D — Analysis**
- `analysis/temporal_consistency.py` checks diachronic consistency: forward-looking ESG claims vs. historical news timelines
- `analysis/silence_detector.py` detects strategic omissions by checking graph node density against mandatory TT08/2026 disclosure categories

**Phase E — Output**
- JSON `AuditResult` + human-readable console summary

### KG Quality Evaluation (evaluation/kg_quality/)

Uses a **two-model strategy** to avoid self-confirmation bias: Sonnet extracts claims, Haiku evaluates them.

- **Tier 1 (free):** `schema_validator.py` (type/property/edge conformance) + `structural_analyzer.py` (orphan nodes, connectivity, indicator coverage, confidence distribution)
- **Tier 2 (LLM cost):** `rag_validator.py` (BM25 retrieval with Vietnamese word segmentation via `underthesea` + Haiku grounding verification) + `claim_quality.py` (extraction faithfulness, calibration error)
- **Runner:** `runner.py` orchestrates modules, computes Overall Quality Score (OQS), writes JSON report to `output/kg_eval_report.json`
- **Design doc:** `docs/kg_evaluation_design.md` has full metric formulas and architecture

## Key Files

| File | Role |
|------|------|
| `config.py` | All thresholds, paths, LLM settings, regulation definitions |
| `main.py` | CLI entry point, `ESGAuditPipeline` class |
| `kg/graph_store.py` | `KnowledgeGraph` — NetworkX MultiDiGraph wrapper |
| `kg/entity_linker.py` | Fuzzy company-name deduplication with Vietnamese normalization |
| `reasoning/verdict_generator.py` | Top-level orchestration across all modules |
| `generators/build_instances.py` | LLM-based claim extraction → `sample_instances.json` |
| `generators/claude_extractor.py` | Claude API call + prompt for ESG claim extraction |
| `ontology/sample_instances.json` | Pre-built FPT entity/relation instances (**required, not in git**) |
| `ontology/framework_indicators.json` | 85 ESG indicators across GRI/TT96/TT08/TCFD (**required, not in git**) |

## Environment Variables

Required in `.env` (not committed):
```
ANTHROPIC_API_KEY=sk-...
# Optional Neo4j (disabled by default, uses in-memory NetworkX):
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
```

## Important Notes

- `data/` is gitignored — all crawled news and PDFs are local only
- `ontology/` directory is **not in git** but is required for the pipeline to run
- The KG is in-memory (NetworkX); Neo4j integration exists in config but is disabled
- All LLM calls use the Anthropic Claude API via the `anthropic` SDK. The main pipeline and extraction use `claude-sonnet-4-20250514` (`Config.LLM_MODEL`); KG evaluation uses `claude-haiku-4-5-20251001` (separate model to avoid self-confirmation bias)
- Greenwashing thresholds: trust score < 0.4 = High risk, < 0.7 = Medium risk (configurable in `config.py`)
- `evaluation/baselines.py` provides three comparison baselines: VanillaRAG, LLMOnly, GraphRAGNoRL
- No test suite exists — verification is done by running the pipeline and KG evaluation
- `get_all_edges()` returns dicts with key `type` (not `rel_type`); `get_relations_by_type()` returns dicts with key `rel_type` — be aware of this inconsistency when writing code that queries the graph
