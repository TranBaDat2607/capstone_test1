"""
evaluation.kg_quality.claim_quality

Module 4 — Claim Extraction Quality Assessor.

Evaluates how faithfully the LLM-extracted claims represent the source
text and how well-calibrated the confidence scores are.
No ground truth required for the metrics implemented here.

Metrics produced:
    M4.1  Extraction Faithfulness Score  (EFS)
    M4.5  Expected Calibration Error     (ECE)
"""
from __future__ import annotations

import logging
from typing import Any

from kg.graph_store import KnowledgeGraph

logger = logging.getLogger(__name__)

# Lazy BM25 / underthesea imports
_BM25_AVAILABLE = False
_UNDERTHESEA_AVAILABLE = False

try:
    from rank_bm25 import BM25Okapi  # type: ignore[import]
    _BM25_AVAILABLE = True
except ImportError:
    pass

try:
    from underthesea import word_tokenize  # type: ignore[import]
    _UNDERTHESEA_AVAILABLE = True
except ImportError:
    pass


def _tokenize(text: str) -> list[str]:
    if _UNDERTHESEA_AVAILABLE:
        return word_tokenize(text, format="list")
    return text.lower().split()


class ClaimQualityAssessor:
    """Assess claim extraction quality without ground truth."""

    def __init__(
        self,
        kg: KnowledgeGraph,
        blocks: list[dict],
    ) -> None:
        self._kg = kg
        # Build block_id → text lookup
        self._block_map: dict[str, str] = {}
        for b in blocks:
            bid = b.get("id", "")
            text = b.get("text", "")
            if bid and text:
                self._block_map[bid] = text

    def _extraction_faithfulness(self) -> tuple[float | None, list[dict]]:
        """M4.1 — BM25-based faithfulness between claim_text and source block."""
        claims = self._kg.get_nodes_by_type("Claim")
        if not claims or not self._block_map:
            return None, []
        if not _BM25_AVAILABLE:
            logger.warning("rank_bm25 not installed — EFS cannot be computed.")
            return None, []

        # Build a BM25 index over all blocks
        block_ids = list(self._block_map.keys())
        block_texts = [self._block_map[bid] for bid in block_ids]
        tokenized_blocks = [_tokenize(t) for t in block_texts]
        bm25 = BM25Okapi(tokenized_blocks)

        scores: list[float] = []
        details: list[dict] = []

        for claim in claims:
            props = claim.get("properties", {})
            claim_text = props.get("claim_text", "")
            source_bid = props.get("source_block_id", "")

            if not claim_text:
                continue

            query_tokens = _tokenize(claim_text)
            bm25_scores = bm25.get_scores(query_tokens)

            # Find the score for the claimed source block
            if source_bid in block_ids:
                idx = block_ids.index(source_bid)
                claim_score = float(bm25_scores[idx])
            else:
                # Source block not found — use max score as fallback
                claim_score = float(max(bm25_scores)) if len(bm25_scores) > 0 else 0.0

            # Also get the max score for normalization
            max_score = float(max(bm25_scores)) if len(bm25_scores) > 0 else 1.0

            normalized = claim_score / max_score if max_score > 0 else 0.0
            scores.append(normalized)

            details.append({
                "claim_id": claim["node_id"],
                "source_block_id": source_bid,
                "faithfulness_score": round(normalized, 4),
            })

        if not scores:
            return None, []

        avg = round(sum(scores) / len(scores), 4)
        return avg, details

    def _expected_calibration_error(
        self,
        grounding_results: dict | None,
    ) -> float | None:
        """M4.5 — ECE comparing confidence bins to actual grounding rates."""
        if not grounding_results:
            return None

        claim_results = grounding_results.get("claim_results", [])
        if not claim_results:
            return None

        # Define bins matching the confidence scale in claude_extractor.py
        bins = [
            (0.3, 0.59, "low"),
            (0.6, 0.89, "medium"),
            (0.9, 1.0, "high"),
        ]

        ece = 0.0
        total = 0

        for lo, hi, _label in bins:
            bin_items = [
                cr for cr in claim_results
                if cr.get("extraction_confidence") is not None
                and lo <= cr["extraction_confidence"] <= hi
            ]
            if not bin_items:
                continue

            avg_conf = sum(cr["extraction_confidence"] for cr in bin_items) / len(bin_items)
            grounding_rate = sum(
                1 for cr in bin_items if cr.get("grounded", False)
            ) / len(bin_items)

            ece += len(bin_items) * abs(avg_conf - grounding_rate)
            total += len(bin_items)

        if total == 0:
            return None
        return round(ece / total, 4)

    # ── public API ─────────────────────────────────────────────────────

    def assess(self, grounding_results: dict | None = None) -> dict[str, Any]:
        """Run claim quality assessment."""
        efs, efs_details = self._extraction_faithfulness()
        ece = self._expected_calibration_error(grounding_results)

        result: dict[str, Any] = {
            "extraction_faithfulness_score": efs,
            "expected_calibration_error": ece,
        }

        logger.info("Claim quality done — EFS=%s  ECE=%s", efs, ece)
        return result
