"""
evaluation.kg_quality.rag_validator

Module 3 — Triple Grounding via RAG.

Builds a sentence-level BM25 index over source PDF blocks, then verifies
each KG Claim is grounded in the source documents using an independent
LLM judge (claude-haiku-4-5-20251001 by default — different from the
extraction model to avoid self-confirmation bias).

Metrics produced:
    M3.1  Triple Grounding Rate           (TGR)
    M3.2  Claim Grounding Rate            (CGR)
    M3.3  Source Block Agreement           (SBA)
    M3.4  Grounding-Confidence Correlation
"""
from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from kg.graph_store import KnowledgeGraph

logger = logging.getLogger(__name__)

# ── Lazy imports for optional dependencies ─────────────────────────────

_BM25_AVAILABLE = False
_UNDERTHESEA_AVAILABLE = False

try:
    from rank_bm25 import BM25Okapi  # type: ignore[import]
    _BM25_AVAILABLE = True
except ImportError:
    logger.info("rank_bm25 not installed — RAG validation unavailable.  pip install rank-bm25")

try:
    from underthesea import word_tokenize  # type: ignore[import]
    _UNDERTHESEA_AVAILABLE = True
except ImportError:
    logger.info("underthesea not installed — Vietnamese word segmentation unavailable.  pip install underthesea")


# ── Anthropic client helpers (adapted from evaluation/baselines.py) ────

def _get_anthropic_client(api_key: str | None, model: str) -> tuple[Any, str]:
    try:
        import anthropic  # type: ignore[import]
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        return client, model
    except ImportError:
        logger.warning("anthropic package not installed — LLM verification will return stubs.")
        return None, model


def _call_llm(
    client: Any,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 512,
) -> str:
    if client is None:
        return '{"grounded": false, "confidence": 0.0, "matching_passage": null}'
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return resp.content[0].text
    except Exception:  # noqa: BLE001
        logger.error("LLM call failed.", exc_info=True)
        return '{"grounded": false, "confidence": 0.0, "matching_passage": null}'


def _parse_grounding_response(raw: str) -> dict:
    """Parse the LLM JSON response into a grounding dict."""
    try:
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        return {
            "grounded": bool(data.get("grounded", False)),
            "confidence": float(data.get("confidence", 0.0)),
            "matching_passage": data.get("matching_passage"),
        }
    except Exception:  # noqa: BLE001
        logger.debug("Failed to parse grounding response: %s", raw[:200])
        return {"grounded": False, "confidence": 0.0, "matching_passage": None}


# ── Tokenization helper ───────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Vietnamese word-segmented tokenization with fallback to whitespace."""
    if _UNDERTHESEA_AVAILABLE:
        return word_tokenize(text, format="list")
    return text.lower().split()


# ── Sentence index ────────────────────────────────────────────────────

def _build_sentence_index(blocks: list[dict]) -> list[dict]:
    """Split blocks into sentences with metadata."""
    sentences: list[dict] = []
    for block in blocks:
        text = block.get("text", "")
        if not text.strip():
            continue
        block_id = block.get("id", "")
        page = block.get("page", 0)
        # Split on sentence boundaries
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        for part in parts:
            part = part.strip()
            if len(part) < 10:
                continue
            sentences.append({
                "sentence": part,
                "block_id": block_id,
                "page": page,
            })
    return sentences


# ── System prompt for grounding verification ──────────────────────────

_GROUNDING_SYSTEM_PROMPT = """\
You are a fact-checking assistant for ESG disclosures.
Given a claim extracted from a Vietnamese ESG report and retrieved
evidence passages, determine if the evidence supports the claim.
Return ONLY valid JSON — no markdown, no explanation."""


# ── Validator ─────────────────────────────────────────────────────────

class RAGValidator:
    """BM25 + LLM-based triple grounding validation."""

    def __init__(
        self,
        kg: KnowledgeGraph,
        blocks: list[dict],
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._kg = kg
        self._blocks = blocks
        self._client, self._model = _get_anthropic_client(api_key, model)

        # Build sentence index and BM25
        self._sentence_index = _build_sentence_index(blocks)
        self._bm25: Any | None = None
        self._tokenized_corpus: list[list[str]] = []

        if self._sentence_index and _BM25_AVAILABLE:
            self._tokenized_corpus = [
                _tokenize(s["sentence"]) for s in self._sentence_index
            ]
            self._bm25 = BM25Okapi(self._tokenized_corpus)
            logger.info("BM25 index built with %d sentences.", len(self._sentence_index))
        elif not _BM25_AVAILABLE:
            logger.warning("BM25 not available — retrieval will be skipped.")

    def _retrieve_top_k(self, query: str, k: int = 5) -> list[dict]:
        """Retrieve top-k sentences for a query using BM25."""
        if self._bm25 is None:
            return []
        query_tokens = _tokenize(query)
        scores = self._bm25.get_scores(query_tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
        return [
            {**self._sentence_index[i], "bm25_score": round(float(scores[i]), 4)}
            for i in top_indices
            if scores[i] > 0
        ]

    def _verify_claim(self, claim_props: dict, retrieved: list[dict]) -> dict:
        """Ask LLM whether retrieved evidence supports the claim."""
        claim_text = claim_props.get("claim_text", "")
        value = claim_props.get("value", "N/A")
        unit = claim_props.get("unit", "N/A")
        indicator_id = claim_props.get("indicator_id", "")

        evidence_lines = []
        for i, r in enumerate(retrieved, 1):
            evidence_lines.append(
                f"{i}. [Block {r['block_id']}, Page {r['page']}] {r['sentence']}"
            )
        evidence_str = "\n".join(evidence_lines) if evidence_lines else "(no evidence retrieved)"

        user_message = (
            f"CLAIM: {claim_text}\n"
            f"VALUE: {value} {unit}\n"
            f"INDICATOR: {indicator_id}\n\n"
            f"RETRIEVED EVIDENCE (top {len(retrieved)} passages):\n{evidence_str}\n\n"
            f"Does the evidence support this claim?\n"
            f"Return JSON only:\n"
            f'{{"grounded": true/false, "confidence": 0.0-1.0, "matching_passage": "..." or null}}'
        )

        raw = _call_llm(self._client, self._model, _GROUNDING_SYSTEM_PROMPT, user_message)
        return _parse_grounding_response(raw)

    def _pearson_correlation(self, x: list[float], y: list[float]) -> float | None:
        """Manual Pearson r (avoids scipy dependency)."""
        n = len(x)
        if n < 3:
            return None
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
        if std_x == 0 or std_y == 0:
            return None
        return round(cov / (std_x * std_y), 4)

    # ── public API ─────────────────────────────────────────────────────

    def validate(self) -> dict[str, Any]:
        """Run RAG-based grounding validation for all Claims."""
        claims = self._kg.get_nodes_by_type("Claim")
        if not claims:
            logger.warning("No Claim nodes found — skipping RAG validation.")
            return {
                "triple_grounding_rate": None,
                "claim_grounding_rate": None,
                "source_block_agreement": None,
                "grounding_confidence_correlation": None,
                "ungrounded_claims": [],
                "claim_results": [],
            }

        logger.info("Validating %d claims against %d sentences ...", len(claims), len(self._sentence_index))

        grounded_count = 0
        sba_match = 0
        sba_total = 0
        confidence_scores: list[float] = []
        grounding_scores: list[float] = []
        ungrounded: list[dict] = []
        claim_results: list[dict] = []

        for claim in claims:
            props = claim.get("properties", {})
            claim_id = claim["node_id"]
            claim_text = props.get("claim_text", "")

            # Retrieve
            retrieved = self._retrieve_top_k(claim_text, k=5)

            # Verify
            result = self._verify_claim(props, retrieved)
            is_grounded = result["grounded"]

            if is_grounded:
                grounded_count += 1
            else:
                ungrounded.append({
                    "claim_id": claim_id,
                    "claim_text": claim_text[:100],
                    "reason": "LLM judged not grounded" if retrieved else "no evidence retrieved",
                })

            # Source Block Agreement
            source_block = props.get("source_block_id", "")
            if source_block and retrieved:
                sba_total += 1
                if retrieved[0]["block_id"] == source_block:
                    sba_match += 1

            # For correlation
            cs = props.get("confidence_score")
            if cs is not None:
                confidence_scores.append(float(cs))
                grounding_scores.append(result["confidence"])

            claim_results.append({
                "claim_id": claim_id,
                "grounded": is_grounded,
                "grounding_confidence": result["confidence"],
                "extraction_confidence": float(cs) if cs is not None else None,
            })

            logger.debug("Claim %s: grounded=%s (conf=%.2f)", claim_id, is_grounded, result["confidence"])

        total = len(claims)
        tgr = round(grounded_count / total, 4)
        cgr = tgr  # Same for now (all triples evaluated are claim-based)
        sba = round(sba_match / sba_total, 4) if sba_total > 0 else None
        correlation = self._pearson_correlation(confidence_scores, grounding_scores)

        result = {
            "triple_grounding_rate": tgr,
            "claim_grounding_rate": cgr,
            "source_block_agreement": sba,
            "grounding_confidence_correlation": correlation,
            "ungrounded_claims": ungrounded,
            "claim_results": claim_results,
        }

        logger.info(
            "RAG validation done — TGR=%.4f  CGR=%.4f  SBA=%s  r=%s",
            tgr, cgr, sba, correlation,
        )
        return result
