"""
main.py

ESG Greenwashing Detection Pipeline — orchestration entry point.

Usage:
    # Full audit of FPT 2023 (using pre-loaded sample instances):
    python main.py --company COMP_FPT --report RPT_FPT_ESG_2023

    # Load news data from crawl_data_news/ and run audit:
    python main.py --company COMP_FPT --report RPT_FPT_ESG_2023 --load-news

    # Extract entities from a PDF then audit:
    python main.py --company COMP_FPT --report RPT_FPT_ESG_2023 --pdf crawl_data/2023-fpt-esg-report.pdf

    # Run evaluation against baselines:
    python main.py --company COMP_FPT --report RPT_FPT_ESG_2023 --evaluate

    # Show KG stats only:
    python main.py --stats

Pipeline phases:
    A. Data & KG   — load sample instances + news + PDFs into KnowledgeGraph
    B. Graph RAG   — contrastive pro/anti subgraph retrieval per claim
    C. RL Reasoning — actor-critic prompting loop, per-claim verdicts
    D. Analysis    — temporal consistency + selective silence detection
    E. Output      — AuditResult JSON + human-readable report
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure code/ root is on sys.path when run directly
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from config import Config
from kg.graph_store import KnowledgeGraph
from kg.graph_builder import GraphBuilder
from kg.entity_linker import EntityLinker
from extraction.news_processor import NewsProcessor
from extraction.pdf_parser import PDFParser
from extraction.nlp_pipeline import NLPExtractionPipeline
from retrieval.contrastive_graph_rag import ContrastiveGraphRAG
from reasoning.rl_agent import RLReasoningAgent
from reasoning.verdict_generator import VerdictGenerator
from analysis.temporal_consistency import TemporalConsistencyModule
from analysis.silence_detector import SelectiveSilenceDetector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("esg_pipeline")


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class ESGAuditPipeline:
    """
    End-to-end ESG Greenwashing Detection pipeline.

    Parameters
    ----------
    api_key : str | None
        Anthropic API key. Reads ANTHROPIC_API_KEY env var if not provided.
    verbose : bool
        Enable debug logging.
    """

    def __init__(self, api_key: str | None = None, verbose: bool = False) -> None:
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        self.api_key = api_key or Config.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")

        # Phase A — KG
        self.kg = KnowledgeGraph()
        self.builder = GraphBuilder(self.kg)

        # Seed standard regulation nodes
        self.builder.add_mandatory_regulation_nodes()

        # Phase B — Retrieval
        self.graph_rag = ContrastiveGraphRAG(self.kg)

        # Phase C — Reasoning
        self.agent = RLReasoningAgent(
            api_key=self.api_key,
            model=Config.LLM_MODEL,
            max_iterations=Config.RL_MAX_ITERATIONS,
        )

        # Phase D — Analysis
        self.temporal_module = TemporalConsistencyModule(self.kg)
        self.silence_detector = SelectiveSilenceDetector(self.kg)

        # Phase E — Verdict
        self.verdict_gen = VerdictGenerator(
            agent=self.agent,
            graph_rag=self.graph_rag,
            temporal_module=self.temporal_module,
            silence_detector=self.silence_detector,
        )

    # ------------------------------------------------------------------
    # Phase A — Data ingestion
    # ------------------------------------------------------------------

    def load_sample_instances(self) -> None:
        """Load the pre-built FPT sample instances into the KG."""
        path = Config.SAMPLE_INSTANCES_PATH
        if path.exists():
            self.builder.load_from_instances_json(path)
            logger.info("Loaded sample instances. KG stats: %s", self.kg.stats())
        else:
            logger.warning("Sample instances not found at %s", path)

    def load_news(self, company_id: str, years: list[int] | None = None) -> int:
        """Ingest crawled news articles into the KG."""
        processor = NewsProcessor(Config.CRAWL_NEWS_DIR, company_id)
        count = processor.ingest_into_kg(self.builder, years=years)
        logger.info("News ingestion complete. KG now has %d nodes.", self.kg.node_count())
        return count

    def load_pdf(self, pdf_path: str | Path, company_id: str, report_id: str) -> None:
        """Parse a PDF report and extract entities/relations into the KG."""
        parser = PDFParser()
        pages = parser.parse(pdf_path)

        extractor = NLPExtractionPipeline(
            api_key=self.api_key,
            model=Config.LLM_MODEL,
            company_id=company_id,
            report_id=report_id,
        )
        result = extractor.extract_from_pages(pages)

        # Ingest extracted entities + relations
        # Wrap as instances-style JSON and load
        instances = {
            "entities": result["entities"],
            "relations": result["relations"],
        }
        # Write to temp file and reload, OR ingest directly
        self._ingest_extracted(instances, company_id, report_id)
        logger.info(
            "PDF extraction complete: %d entities, %d relations",
            len(result["entities"]), len(result["relations"]),
        )

    def _ingest_extracted(self, instances: dict, company_id: str, report_id: str) -> None:
        """Ingest extracted entity/relation dicts directly into the KG."""
        for entity in instances.get("entities", []):
            etype = entity.get("type", "Unknown")
            props = dict(entity.get("properties", {}))
            props["source_doc"] = report_id
            self.kg.add_node(entity["id"], etype, props)

        for rel in instances.get("relations", []):
            self.kg.add_relation(
                rel_id=rel.get("id", f"REL_{rel['source_id']}_{rel['target_id']}"),
                source_id=rel["source_id"],
                target_id=rel["target_id"],
                rel_type=rel["type"],
                properties={
                    "extracted_at": rel.get("extracted_at", "2026-03-14"),
                    "confidence_score": rel.get("confidence_score", 0.8),
                    "extraction_method": rel.get("extraction_method", "LLM_Constraint"),
                    **rel.get("properties", {}),
                },
            )

    # ------------------------------------------------------------------
    # Phase B–E — Audit
    # ------------------------------------------------------------------

    def audit_company(self, company_id: str, report_id: str | None = None) -> dict:
        """
        Run full greenwashing audit for a company.

        Parameters
        ----------
        company_id : str
            KG node ID of the company (e.g. "COMP_FPT").
        report_id : str | None
            Optional report to scope claim extraction to.

        Returns
        -------
        dict
            AuditResult matching ontology_schema.json v2.0.
        """
        logger.info("Starting audit for %s", company_id)

        # Check company node exists
        company_node = self.kg.get_node(company_id)
        if company_node is None:
            logger.warning("Company node %s not found in KG. Results may be empty.", company_id)

        result = self.verdict_gen.audit_company(company_id, self.kg, report_id=report_id)

        return result

    def audit_claim(self, claim_id: str) -> dict:
        """Run a single-claim audit."""
        return self.verdict_gen.audit_claim(claim_id, self.kg)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return KG statistics."""
        return self.kg.stats()

    def save_result(self, result: dict, output_path: str | Path | None = None) -> Path:
        """Save audit result to JSON file."""
        Config.ensure_output_dir()
        if output_path is None:
            company_id = result.get("company_id", "unknown").replace("COMP_", "")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = Config.OUTPUT_DIR / f"audit_{company_id}_{ts}.json"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info("Saved audit result to %s", output_path)
        return output_path

    def print_summary(self, result: dict) -> None:
        """Print a human-readable audit summary to stdout."""
        print("\n" + "=" * 60)
        print("ESG GREENWASHING AUDIT SUMMARY")
        print("=" * 60)
        print(f"Company     : {result.get('company_id', 'N/A')}")
        print(f"Report      : {result.get('report_id', 'N/A')}")
        print(f"Audited at  : {result.get('audited_at', 'N/A')}")
        print()
        print(f"Trust Score : {result.get('trust_score', 0):.2f}")
        print(f"Risk Level  : {result.get('greenwashing_risk', 'N/A')}")
        print()
        print(f"Total Claims    : {result.get('total_claims', 0)}")
        print(f"Supported Claims: {result.get('supported_claims', 0)}")
        print(f"Flagged Claims  : {result.get('flagged_claims', 0)}")
        print()

        for pillar in ("e", "s", "g"):
            score = result.get(f"{pillar}_score")
            if score is not None:
                label = {"e": "Environmental", "s": "Social", "g": "Governance"}[pillar]
                print(f"{label:>15} score: {score:.2f}")

        print()
        if result.get("summary"):
            print("Summary:", result["summary"])

        # Silence flags
        silence = result.get("silence_signals", {})
        if silence.get("silence_flags"):
            print()
            print("Selective Silence Flags:")
            for flag in silence["silence_flags"]:
                print(f"  [!]  {flag}")

        # Temporal divergence
        temporal = result.get("temporal_consistency", {})
        if temporal.get("divergence_years"):
            print()
            print("Temporal Divergence Years:", temporal["divergence_years"])

        print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="ESG Greenwashing Detection Pipeline",
    )
    p.add_argument(
        "--company",
        default="COMP_FPT",
        help="KG company node ID to audit (default: COMP_FPT)",
    )
    p.add_argument(
        "--report",
        default="RPT_FPT_ESG_2023",
        help="KG report node ID (default: RPT_FPT_ESG_2023)",
    )
    p.add_argument(
        "--load-news",
        action="store_true",
        help="Ingest crawled news from crawl_data_news/ before auditing",
    )
    p.add_argument(
        "--news-years",
        nargs="*",
        type=int,
        default=None,
        help="Year filter for news ingestion (e.g. --news-years 2021 2022 2023)",
    )
    p.add_argument(
        "--pdf",
        default=None,
        help="Path to a PDF report to extract entities from before auditing",
    )
    p.add_argument(
        "--no-sample",
        action="store_true",
        help="Skip loading sample_instances.json (use if building KG from scratch)",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Output JSON path for audit result (auto-generated if not set)",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Print KG statistics and exit",
    )
    p.add_argument(
        "--evaluate",
        action="store_true",
        help="Run baseline comparison evaluation after auditing",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Build pipeline
    pipeline = ESGAuditPipeline(verbose=args.verbose)

    # Phase A — Data loading
    if not args.no_sample:
        pipeline.load_sample_instances()

    if args.load_news:
        pipeline.load_news(args.company, years=args.news_years)

    if args.pdf:
        pipeline.load_pdf(args.pdf, args.company, args.report)

    # Stats-only mode
    if args.stats:
        stats = pipeline.stats()
        print("\nKnowledge Graph Statistics:")
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    # Phase B–E — Audit
    result = pipeline.audit_company(args.company, args.report)

    # Output
    pipeline.print_summary(result)
    saved_path = pipeline.save_result(result, args.output)
    print(f"Full audit result saved to: {saved_path}")

    # Optional evaluation
    if args.evaluate:
        _run_baseline_evaluation(pipeline, result, args.company)


def _run_baseline_evaluation(pipeline: ESGAuditPipeline, main_result: dict, company_id: str) -> None:
    """Run baseline comparisons and print comparison table."""
    try:
        from evaluation.baselines import VanillaRAGBaseline, LLMOnlyBaseline, GraphRAGNoRLBaseline
        from evaluation.metrics import evaluate_system
    except ImportError as e:
        logger.warning("Evaluation modules not available: %s", e)
        return

    logger.info("Running baseline evaluation...")

    # Get all claims for comparison
    claims = pipeline.kg.get_nodes_by_type("Claim")
    if not claims:
        print("No claims found for evaluation.")
        return

    # VanillaRAG baseline
    vanilla = VanillaRAGBaseline(api_key=pipeline.api_key)
    corpus = vanilla.build_text_corpus(claims)

    results_table = []
    for claim_node in claims[:5]:  # Evaluate first 5 claims for demo
        claim_id = claim_node["id"]
        claim_props = claim_node.get("properties", {})

        # Main system
        main_verdict = main_result.get("claim_verdicts", {}).get(claim_id, {})

        # Vanilla RAG
        context = vanilla.retrieve_similar(claim_props.get("text", ""), corpus)
        vanilla_verdict = vanilla.verdict(claim_props, context)

        # LLM Only
        llm_only = LLMOnlyBaseline(api_key=pipeline.api_key)
        llm_verdict = llm_only.verdict(claim_props)

        # GraphRAG no RL
        context_dict = pipeline.graph_rag.retrieve_contrastive_context(claim_id)
        graph_no_rl = GraphRAGNoRLBaseline(api_key=pipeline.api_key)
        graph_verdict = graph_no_rl.verdict(claim_props, context_dict)

        results_table.append({
            "claim_id": claim_id,
            "claim_text": claim_props.get("text", "")[:60] + "...",
            "main_system": main_verdict.get("verdict", "N/A"),
            "vanilla_rag": vanilla_verdict.get("verdict", "N/A"),
            "llm_only": llm_verdict.get("verdict", "N/A"),
            "graph_no_rl": graph_verdict.get("verdict", "N/A"),
        })

    print("\n" + "=" * 80)
    print("BASELINE COMPARISON (first 5 claims)")
    print("=" * 80)
    print(f"{'Claim':<40} {'Main':>12} {'VanillaRAG':>12} {'LLMOnly':>10} {'GraphNoRL':>12}")
    print("-" * 80)
    for row in results_table:
        print(
            f"{row['claim_text']:<40} {row['main_system']:>12} "
            f"{row['vanilla_rag']:>12} {row['llm_only']:>10} {row['graph_no_rl']:>12}"
        )
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
