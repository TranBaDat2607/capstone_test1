# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **ESG Greenwashing Detection Pipeline** for Vietnamese corporate ESG disclosures. It uses a Knowledge Graph (KG) + Contrastive Graph RAG + Actor-Critic RL to audit ESG claims from annual reports and news against regulatory frameworks (TT96/2020, TT08/2026).

## Commands

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

### Run the news crawler only
```bash
cd crawl_data
pip install -r requirements.txt
python crawler_news.py
```

### Install dependencies
```bash
pip install -r requirements.txt
```

## Architecture

The pipeline runs in 5 sequential phases:

**Phase A — Data & KG Construction**
- `kg/graph_builder.py` loads `ontology/sample_instances.json` (entities + relations) into the in-memory NetworkX MultiDiGraph (`kg/graph_store.py`)
- `extraction/news_processor.py` walks `data/raw/crawl_data_news/YYYY/` and ingests news as `NewsEvent` nodes
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

## Key Files

| File | Role |
|------|------|
| `config.py` | All thresholds, paths, LLM settings, regulation definitions |
| `main.py` | CLI entry point, `ESGAuditPipeline` class |
| `kg/graph_store.py` | `KnowledgeGraph` — NetworkX MultiDiGraph wrapper |
| `reasoning/verdict_generator.py` | Top-level orchestration across all modules |
| `ontology/sample_instances.json` | Pre-built FPT entity/relation instances (**required, not in git**) |

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
- `ontology/` directory (with `sample_instances.json` and `ontology_schema.json`) is **not in git** but is required for the pipeline to run
- The KG is in-memory (NetworkX); Neo4j integration exists in config but is disabled
- LLM model is set to `claude-sonnet-4-6` in `config.py`; extraction prompts are Vietnamese ESG-specialized
- Greenwashing thresholds: trust score < 0.4 = High risk, < 0.7 = Medium risk (configurable in `config.py`)
- `evaluation/baselines.py` provides three comparison baselines: VanillaRAG, LLMOnly, GraphRAGNoRL
