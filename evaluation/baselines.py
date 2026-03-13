"""
evaluation/baselines.py

Baseline implementations for systematic comparison against the full
ESG Greenwashing Detection pipeline.

Three baselines are provided:

1. ``VanillaRAGBaseline``     — flat keyword retrieval over text chunks + single LLM call.
2. ``LLMOnlyBaseline``        — single LLM call with no retrieval whatsoever.
3. ``GraphRAGNoRLBaseline``   — contrastive subgraph context + single LLM call
                                (no RL critic loop).

All three share a lightweight Anthropic API wrapper so the comparison is
fair: the same model and prompt format are used throughout.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy Anthropic client helper
# ---------------------------------------------------------------------------

def _get_anthropic_client(api_key: str | None, model: str) -> tuple[Any, str]:
    """Return an (anthropic.Anthropic, model) tuple, or (None, model) if the
    library is not installed.

    This function is intentionally lazy so that importing this module does
    not hard-fail in environments without the ``anthropic`` package.
    """
    try:
        import anthropic  # type: ignore[import]
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        return client, model
    except ImportError:
        logger.warning(
            "anthropic package not installed — LLM calls will return stub verdicts."
        )
        return None, model


def _call_llm(
    client: Any,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 512,
) -> str:
    """Send a single-turn message to the LLM and return the text response.

    Returns a JSON-serialisable stub string when the client is unavailable.
    """
    if client is None:
        logger.debug("LLM client unavailable — returning stub response.")
        return json.dumps(
            {
                "verdict": "Insufficient_Evidence",
                "confidence": 0.5,
                "rationale": "LLM client not available (stub response).",
            }
        )

    try:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return message.content[0].text
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM call failed: %s", exc)
        return json.dumps(
            {
                "verdict": "Insufficient_Evidence",
                "confidence": 0.0,
                "rationale": f"LLM call error: {exc}",
            }
        )


def _parse_verdict_response(raw: str) -> dict:
    """Best-effort JSON parse of an LLM verdict response.

    Falls back to a structured error dict on parse failure.
    """
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to extract a JSON object embedded in prose.
    import re
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    return {
        "verdict": "Insufficient_Evidence",
        "confidence": 0.0,
        "rationale": raw,
    }


# ---------------------------------------------------------------------------
# Baseline 1: VanillaRAG
# ---------------------------------------------------------------------------

class VanillaRAGBaseline:
    """
    Baseline: flat semantic search over chunked ESG report text -> LLM verdict.
    No graph traversal, no adversarial retrieval.

    This represents the simplest possible RAG pipeline: convert the KG (or
    raw report text) into plain text chunks, retrieve the top-K most similar
    chunks by keyword overlap, and ask the LLM for a verdict in one shot.

    Args:
        api_key: Anthropic API key.  If ``None`` the default environment
                 variable ``ANTHROPIC_API_KEY`` is used.
        model:   LLM model identifier.  Defaults to ``"claude-sonnet-4-6"``.
    """

    _SYSTEM_PROMPT = (
        "You are an ESG auditor specialising in greenwashing detection. "
        "You will be given an ESG claim and relevant context passages retrieved "
        "from company reports. Analyse the claim and context, then return a JSON "
        "object with the following keys:\n"
        '  "verdict": one of "Verified", "Greenwashing", "Insufficient_Evidence"\n'
        '  "confidence": float in [0, 1]\n'
        '  "rationale": one-sentence explanation\n'
        "Return ONLY the JSON object with no additional text."
    )

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.model = model
        self._client, self._model = _get_anthropic_client(api_key, model)

    # ------------------------------------------------------------------

    def build_text_corpus(self, entities: list[dict]) -> list[str]:
        """Convert KG node dicts to a flat list of text chunks.

        Each chunk is a human-readable string representation of a single
        entity (node), combining its ID, type, and key properties.

        Args:
            entities: List of KG node-property dicts.  Each dict should
                      contain at minimum ``"node_id"`` (or ``"id"``),
                      ``"node_type"`` (or ``"type"``), and any relevant
                      properties.

        Returns:
            A list of plain-text strings, one per entity.
        """
        chunks: list[str] = []
        for entity in entities:
            node_id = entity.get("node_id") or entity.get("id", "?")
            node_type = entity.get("node_type") or entity.get("type", "Unknown")

            # Collect human-readable fields, excluding internal metadata.
            skip_keys = {"node_id", "id", "node_type", "type"}
            fields = {
                k: v
                for k, v in entity.items()
                if k not in skip_keys and v is not None
            }

            field_str = " | ".join(f"{k}: {v}" for k, v in fields.items())
            chunk = f"[{node_type}:{node_id}] {field_str}"
            chunks.append(chunk)

        return chunks

    def retrieve_similar(
        self,
        query: str,
        corpus: list[str],
        top_k: int = 5,
    ) -> list[str]:
        """Retrieve the *top_k* most relevant corpus chunks for *query* using
        simple keyword overlap (Jaccard similarity on word tokens).

        This is deliberately lightweight — no embeddings, no vector store.
        It serves as the retrieval step for the baseline comparison.

        Args:
            query:  The claim text to search for.
            corpus: Text chunks produced by ``build_text_corpus``.
            top_k:  Maximum number of chunks to return.

        Returns:
            Up to *top_k* corpus strings ordered by descending similarity.
        """
        if not corpus:
            return []

        query_tokens = set(query.lower().split())

        def _jaccard(chunk: str) -> float:
            chunk_tokens = set(chunk.lower().split())
            intersection = query_tokens & chunk_tokens
            union = query_tokens | chunk_tokens
            return len(intersection) / max(len(union), 1)

        scored = sorted(corpus, key=_jaccard, reverse=True)
        return scored[:top_k]

    def verdict(self, claim: dict, context: list[str]) -> dict:
        """Produce a greenwashing verdict for *claim* given *context* chunks.

        This is a single LLM call — no iterative reasoning, no graph
        traversal.

        Args:
            claim:   A KG Claim node-property dict containing at least
                     ``"text"`` and optionally ``"year"`` and ``"pillar"``.
            context: Retrieved text chunks from ``retrieve_similar``.

        Returns:
            A dict with keys ``"verdict"``, ``"confidence"``, ``"rationale"``
            plus ``"baseline"`` identifying this as the VanillaRAG baseline.
        """
        claim_text = claim.get("text", str(claim))
        context_str = "\n\n".join(context) if context else "(no context retrieved)"

        user_message = (
            f"ESG Claim:\n{claim_text}\n\n"
            f"Retrieved Context:\n{context_str}"
        )

        raw = _call_llm(
            self._client,
            self._model,
            self._SYSTEM_PROMPT,
            user_message,
        )
        result = _parse_verdict_response(raw)
        result["baseline"] = "VanillaRAG"
        return result


# ---------------------------------------------------------------------------
# Baseline 2: LLM-Only
# ---------------------------------------------------------------------------

class LLMOnlyBaseline:
    """
    Baseline: direct LLM verdict with no retrieval.

    The model receives only the claim text and its metadata — no retrieved
    context, no graph traversal.  This is the zero-retrieval lower bound.

    Args:
        api_key: Anthropic API key.  Falls back to environment variable.
        model:   LLM model identifier.  Defaults to ``"claude-sonnet-4-6"``.
    """

    _SYSTEM_PROMPT = (
        "You are an ESG greenwashing detection expert. "
        "Based solely on the ESG claim provided, determine whether it is "
        "verifiable, potentially greenwashing, or has insufficient evidence. "
        "Return a JSON object with:\n"
        '  "verdict": one of "Verified", "Greenwashing", "Insufficient_Evidence"\n'
        '  "confidence": float in [0, 1]\n'
        '  "rationale": one-sentence explanation\n'
        "Return ONLY the JSON object with no additional text."
    )

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.model = model
        self._client, self._model = _get_anthropic_client(api_key, model)

    def verdict(self, claim: dict) -> dict:
        """Produce a greenwashing verdict for *claim* using the LLM alone.

        No retrieval, no graph context.

        Args:
            claim: A KG Claim node-property dict.  At minimum should contain
                   ``"text"``.  Additional metadata (``"year"``, ``"pillar"``,
                   ``"sentiment"``) is included when present.

        Returns:
            A dict with keys ``"verdict"``, ``"confidence"``, ``"rationale"``
            plus ``"baseline"`` = ``"LLMOnly"``.
        """
        claim_text = claim.get("text", str(claim))

        # Enrich the prompt with available metadata.
        meta_parts: list[str] = []
        for key in ("year", "pillar", "sentiment", "page_ref"):
            if key in claim and claim[key] is not None:
                meta_parts.append(f"{key}: {claim[key]}")
        meta_str = ("  Metadata: " + ", ".join(meta_parts)) if meta_parts else ""

        user_message = f"ESG Claim:\n{claim_text}{chr(10) + meta_str if meta_str else ''}"

        raw = _call_llm(
            self._client,
            self._model,
            self._SYSTEM_PROMPT,
            user_message,
        )
        result = _parse_verdict_response(raw)
        result["baseline"] = "LLMOnly"
        return result


# ---------------------------------------------------------------------------
# Baseline 3: GraphRAG without RL critic loop
# ---------------------------------------------------------------------------

class GraphRAGNoRLBaseline:
    """
    Baseline: contrastive subgraph retrieval WITHOUT the RL critic loop.
    Single LLM call with the retrieved graph context.

    This baseline isolates the contribution of the RL iterative critic loop
    by using the same contrastive subgraph context as the full system but
    making a single LLM call without multi-step reasoning or reward shaping.

    Args:
        api_key: Anthropic API key.  Falls back to environment variable.
        model:   LLM model identifier.  Defaults to ``"claude-sonnet-4-6"``.
    """

    _SYSTEM_PROMPT = (
        "You are an expert ESG greenwashing auditor. "
        "You have been provided with a Knowledge Graph subgraph containing "
        "supporting evidence (pro-ESG nodes) and contradicting evidence "
        "(anti-ESG nodes) related to an ESG claim. "
        "Analyse both sides of the evidence and return a JSON verdict:\n"
        '  "verdict": one of "Verified", "Greenwashing", "Insufficient_Evidence"\n'
        '  "confidence": float in [0, 1]\n'
        '  "rationale": one-sentence explanation citing specific evidence\n'
        '  "key_pro_evidence": list[str] — up to 3 supporting node IDs or descriptions\n'
        '  "key_anti_evidence": list[str] — up to 3 contradicting node IDs or descriptions\n'
        "Return ONLY the JSON object with no additional text."
    )

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.model = model
        self._client, self._model = _get_anthropic_client(api_key, model)

    def verdict(self, claim: dict, contrastive_context: dict) -> dict:
        """Produce a greenwashing verdict for *claim* using *contrastive_context*.

        The contrastive context is expected to be a dict with ``"pro_nodes"``
        and ``"anti_nodes"`` keys, each containing a list of KG node dicts as
        returned by the retrieval module.

        This is a single LLM call with no iterative RL reasoning loop.

        Args:
            claim:               A KG Claim node-property dict.
            contrastive_context: Dict with ``"pro_nodes"`` and ``"anti_nodes"``
                                 lists.  Typically produced by the
                                 ``ContrastiveSubgraphRetriever``.

        Returns:
            A dict with keys ``"verdict"``, ``"confidence"``, ``"rationale"``,
            ``"key_pro_evidence"``, ``"key_anti_evidence"``, and
            ``"baseline"`` = ``"GraphRAGNoRL"``.
        """
        claim_text = claim.get("text", str(claim))

        pro_nodes: list[dict] = contrastive_context.get("pro_nodes", [])
        anti_nodes: list[dict] = contrastive_context.get("anti_nodes", [])

        def _format_node(node: dict) -> str:
            node_id = node.get("node_id") or node.get("id", "?")
            node_type = node.get("node_type") or node.get("type", "?")
            text = node.get("text") or node.get("name") or node.get("description", "")
            category = node.get("category", "")
            year = node.get("year", "")
            parts = [p for p in [node_type, category, str(year) if year else "", text] if p]
            return f"  [{node_id}] {' | '.join(parts)}"

        pro_str = (
            "\n".join(_format_node(n) for n in pro_nodes)
            if pro_nodes
            else "  (none)"
        )
        anti_str = (
            "\n".join(_format_node(n) for n in anti_nodes)
            if anti_nodes
            else "  (none)"
        )

        user_message = (
            f"ESG Claim:\n{claim_text}\n\n"
            f"Supporting Evidence (Pro-ESG nodes):\n{pro_str}\n\n"
            f"Contradicting Evidence (Anti-ESG nodes):\n{anti_str}"
        )

        raw = _call_llm(
            self._client,
            self._model,
            self._SYSTEM_PROMPT,
            user_message,
        )
        result = _parse_verdict_response(raw)

        # Ensure expected keys exist even if the model omitted them.
        result.setdefault("key_pro_evidence", [])
        result.setdefault("key_anti_evidence", [])
        result["baseline"] = "GraphRAGNoRL"
        return result
