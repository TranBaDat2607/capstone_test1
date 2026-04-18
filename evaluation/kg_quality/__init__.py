"""
evaluation.kg_quality — Knowledge Graph quality evaluation.

Modules
-------
schema_validator     Schema conformance checks (Tier 1).
structural_analyzer  Graph topology metrics (Tier 1).
rag_validator        BM25 + LLM triple grounding (Tier 2).
claim_quality        Extraction faithfulness & calibration (Tier 2).
runner               Orchestrator and CLI entry-point.
"""
