"""
evaluation.kg_quality.runner

Orchestrates all KG quality evaluation modules and produces a unified
JSON report + console summary.

Usage::

    # Tier 1 only (free, no API key)
    python -m evaluation.kg_quality.runner \\
        --instances ontology/sample_instances.json \\
        --indicators ontology/framework_indicators.json \\
        --mode intrinsic

    # Tier 1 + 2 (requires ANTHROPIC_API_KEY)
    python -m evaluation.kg_quality.runner \\
        --instances ontology/sample_instances.json \\
        --extraction-result output/extracted/2023-fpt-esg-report/extraction_result.json \\
        --indicators ontology/framework_indicators.json \\
        --mode rag

    # Everything
    python -m evaluation.kg_quality.runner --mode all
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import Config
from kg.graph_builder import GraphBuilder
from generators.report_blocks import prepare_blocks

from evaluation.kg_quality.schema_validator import SchemaValidator
from evaluation.kg_quality.structural_analyzer import StructuralAnalyzer
from evaluation.kg_quality.rag_validator import RAGValidator
from evaluation.kg_quality.claim_quality import ClaimQualityAssessor

logger = logging.getLogger(__name__)

# ── OQS weights (from design doc §6) ──────────────────────────────────

OQS_WEIGHTS = {
    "ntvr": 0.10,
    "pcs": 0.10,
    "connectivity": 0.10,
    "tgr": 0.30,
    "cgr": 0.25,
    "icr": 0.15,
}


def _compute_oqs(schema: dict, structural: dict, rag: dict | None) -> float | None:
    """Compute the Overall Quality Score (weighted aggregate)."""
    ntvr = schema.get("node_type_validity_rate", 1.0)
    pcs = schema.get("property_completeness_avg", 1.0)
    onr = structural.get("orphan_node_rate", 0.0)
    icr = structural.get("indicator_coverage_rate", 0.0)

    connectivity = 1.0 - onr

    if rag is not None:
        tgr = rag.get("triple_grounding_rate")
        cgr = rag.get("claim_grounding_rate")
    else:
        tgr = None
        cgr = None

    # If RAG metrics are missing, compute partial OQS with Tier 1 only
    if tgr is None or cgr is None:
        # Tier 1 only: renormalize weights
        tier1_total = OQS_WEIGHTS["ntvr"] + OQS_WEIGHTS["pcs"] + OQS_WEIGHTS["connectivity"] + OQS_WEIGHTS["icr"]
        oqs = (
            OQS_WEIGHTS["ntvr"] * ntvr
            + OQS_WEIGHTS["pcs"] * pcs
            + OQS_WEIGHTS["connectivity"] * connectivity
            + OQS_WEIGHTS["icr"] * icr
        ) / tier1_total
        return round(oqs, 4)

    oqs = (
        OQS_WEIGHTS["ntvr"] * ntvr
        + OQS_WEIGHTS["pcs"] * pcs
        + OQS_WEIGHTS["connectivity"] * connectivity
        + OQS_WEIGHTS["tgr"] * tgr
        + OQS_WEIGHTS["cgr"] * cgr
        + OQS_WEIGHTS["icr"] * icr
    )
    return round(oqs, 4)


def _risk_label(oqs: float) -> str:
    if oqs >= 0.85:
        return "High quality"
    if oqs >= 0.70:
        return "Acceptable"
    return "Low quality"


# ── Runner ─────────────────────────────────────────────────────────────

class KGQualityRunner:
    """Orchestrate KG quality evaluation modules."""

    def __init__(
        self,
        instances_path: str | Path,
        extraction_result_path: str | Path | None = None,
        indicators_path: str | Path | None = None,
        api_key: str | None = None,
        eval_model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._instances_path = Path(instances_path)
        self._extraction_result_path = (
            Path(extraction_result_path) if extraction_result_path else None
        )
        self._indicators_path = (
            Path(indicators_path)
            if indicators_path
            else Config.ONTOLOGY_DIR / "framework_indicators.json"
        )
        self._api_key = api_key or Config.ANTHROPIC_API_KEY or None
        self._eval_model = eval_model

        # Load KG
        builder = GraphBuilder()
        builder.load_from_instances_json(str(self._instances_path))
        self._kg = builder.get_kg()

        # Load blocks (if available)
        self._blocks: list[dict] = []
        if self._extraction_result_path and self._extraction_result_path.exists():
            try:
                with open(self._extraction_result_path, encoding="utf-8") as f:
                    report = json.load(f)
                self._blocks = prepare_blocks(report)
                logger.info("Loaded %d blocks from %s", len(self._blocks), self._extraction_result_path)
            except Exception:
                logger.warning("Failed to load extraction result.", exc_info=True)

    def _build_meta(self, modules_run: list[str]) -> dict[str, Any]:
        return {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_version": "1.0",
            "kg_source": str(self._instances_path),
            "extraction_model": "claude-sonnet-4-20250514",
            "evaluation_model": self._eval_model,
            "kg_stats": self._kg.stats(),
            "modules_run": modules_run,
        }

    def run_intrinsic(self) -> dict[str, Any]:
        """Tier 1 only — schema + structural analysis."""
        schema = SchemaValidator(self._kg, self._indicators_path).validate()
        structural = StructuralAnalyzer(self._kg, self._indicators_path).analyze()
        oqs = _compute_oqs(schema, structural, None)

        return {
            "_meta": self._build_meta(["schema", "structural"]),
            "schema_conformance": schema,
            "structural_quality": structural,
            "overall_quality_score": oqs,
        }

    def run_rag_validation(self) -> dict[str, Any]:
        """Tier 1 + 2 — adds RAG grounding and claim quality."""
        schema = SchemaValidator(self._kg, self._indicators_path).validate()
        structural = StructuralAnalyzer(self._kg, self._indicators_path).analyze()

        rag: dict[str, Any] | None = None
        claim_qual: dict[str, Any] | None = None

        if self._blocks:
            rag_validator = RAGValidator(
                self._kg, self._blocks,
                api_key=self._api_key,
                model=self._eval_model,
            )
            rag = rag_validator.validate()

            claim_assessor = ClaimQualityAssessor(self._kg, self._blocks)
            claim_qual = claim_assessor.assess(grounding_results=rag)
        else:
            logger.warning(
                "No extraction result blocks available — "
                "skipping RAG validation and claim quality. "
                "Provide --extraction-result to enable Tier 2."
            )

        oqs = _compute_oqs(schema, structural, rag)

        result: dict[str, Any] = {
            "_meta": self._build_meta(["schema", "structural", "rag_validation", "claim_quality"]),
            "schema_conformance": schema,
            "structural_quality": structural,
            "overall_quality_score": oqs,
        }
        if rag is not None:
            result["rag_validation"] = rag
        if claim_qual is not None:
            result["claim_quality"] = claim_qual

        return result

    def run_all(self) -> dict[str, Any]:
        """Run everything available (Tier 1 + 2)."""
        return self.run_rag_validation()


# ── Console summary ───────────────────────────────────────────────────

def _print_summary(report: dict) -> None:
    """Print a human-readable summary to stdout."""
    print("\n" + "=" * 60)
    print("  KG QUALITY EVALUATION REPORT")
    print("=" * 60)

    meta = report.get("_meta", {})
    stats = meta.get("kg_stats", {})
    print(f"\n  KG Source:    {meta.get('kg_source', 'N/A')}")
    print(f"  Eval Model:   {meta.get('evaluation_model', 'N/A')}")
    print(f"  Nodes: {stats.get('total_nodes', '?')}  |  Edges: {stats.get('total_edges', '?')}")
    print(f"  Modules run:  {', '.join(meta.get('modules_run', []))}")

    # Schema
    sc = report.get("schema_conformance", {})
    print("\n  --- Tier 1: Schema Conformance ---")
    print(f"  Node Type Validity:     {sc.get('node_type_validity_rate', 'N/A')}")
    print(f"  Property Completeness:  {sc.get('property_completeness_avg', 'N/A')}")
    print(f"  Edge Type Validity:     {sc.get('edge_type_validity_rate', 'N/A')}")
    print(f"  Dangling References:    {sc.get('dangling_reference_rate', 'N/A')}")
    print(f"  Claim Type Validity:    {sc.get('claim_type_validity_rate', 'N/A')}")
    print(f"  Confidence Range:       {sc.get('confidence_range_validity', 'N/A')}")

    n_violations = len(sc.get("violations", []))
    if n_violations:
        print(f"  Violations: {n_violations}")

    # Structural
    sq = report.get("structural_quality", {})
    print("\n  --- Tier 1: Structural Quality ---")
    print(f"  Orphan Node Rate:       {sq.get('orphan_node_rate', 'N/A')}")
    print(f"  Connected Components:   {sq.get('connected_components', 'N/A')}")
    print(f"  Graph Density:          {sq.get('graph_density', 'N/A')}")
    print(f"  Indicator Coverage:     {sq.get('indicator_coverage_rate', 'N/A')}")

    mic = sq.get("mandatory_indicator_coverage", {})
    for reg, cov in mic.items():
        print(f"    {reg}: {cov}")

    conf = sq.get("confidence_distribution", {})
    if conf.get("mean") is not None:
        print(f"  Confidence: mean={conf['mean']}  median={conf['median']}  std={conf['std']}")

    flagged = sq.get("flagged_nodes", [])
    if flagged:
        print(f"  Flagged nodes: {len(flagged)}")
        for fn in flagged[:5]:
            print(f"    {fn['node_id']} ({fn['node_type']}): {fn['expected_min']} but got {fn['actual']}")

    # RAG
    rag = report.get("rag_validation")
    if rag:
        print("\n  --- Tier 2: RAG Grounding ---")
        print(f"  Triple Grounding Rate:  {rag.get('triple_grounding_rate', 'N/A')}")
        print(f"  Claim Grounding Rate:   {rag.get('claim_grounding_rate', 'N/A')}")
        print(f"  Source Block Agreement: {rag.get('source_block_agreement', 'N/A')}")
        print(f"  Confidence Correlation: {rag.get('grounding_confidence_correlation', 'N/A')}")

        ungrounded = rag.get("ungrounded_claims", [])
        if ungrounded:
            print(f"  Ungrounded claims: {len(ungrounded)}")
            for uc in ungrounded[:3]:
                print(f"    {uc['claim_id']}: {uc['claim_text'][:60]}...")

    # Claim quality
    cq = report.get("claim_quality")
    if cq:
        print("\n  --- Tier 2: Claim Quality ---")
        print(f"  Faithfulness Score:     {cq.get('extraction_faithfulness_score', 'N/A')}")
        print(f"  Calibration Error:      {cq.get('expected_calibration_error', 'N/A')}")

    # OQS
    oqs = report.get("overall_quality_score")
    print("\n" + "-" * 60)
    if oqs is not None:
        label = _risk_label(oqs)
        print(f"  OVERALL QUALITY SCORE:  {oqs}  ({label})")
    else:
        print("  OVERALL QUALITY SCORE:  N/A")
    print("=" * 60 + "\n")


# ── CLI ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="KG Quality Evaluation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--instances",
        default=str(Config.SAMPLE_INSTANCES_PATH),
        help="Path to sample_instances.json (default: %(default)s)",
    )
    parser.add_argument(
        "--extraction-result",
        default=None,
        help="Path to extraction_result.json (required for Tier 2)",
    )
    parser.add_argument(
        "--indicators",
        default=str(Config.ONTOLOGY_DIR / "framework_indicators.json"),
        help="Path to framework_indicators.json (default: %(default)s)",
    )
    parser.add_argument(
        "--mode",
        choices=["intrinsic", "rag", "all"],
        default="intrinsic",
        help="Evaluation mode (default: intrinsic)",
    )
    parser.add_argument(
        "--eval-model",
        default="claude-haiku-4-5-20251001",
        help="LLM model for evaluation (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        default=str(Config.OUTPUT_DIR / "kg_eval_report.json"),
        help="Output JSON report path (default: %(default)s)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    runner = KGQualityRunner(
        instances_path=args.instances,
        extraction_result_path=args.extraction_result,
        indicators_path=args.indicators,
        eval_model=args.eval_model,
    )

    if args.mode == "intrinsic":
        report = runner.run_intrinsic()
    elif args.mode == "rag":
        report = runner.run_rag_validation()
    else:
        report = runner.run_all()

    # Write JSON report
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    logger.info("Report written to %s", out_path)

    # Console summary
    _print_summary(report)


if __name__ == "__main__":
    main()
