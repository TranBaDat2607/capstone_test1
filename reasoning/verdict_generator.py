"""
reasoning/verdict_generator.py

High-level orchestration layer that coordinates:
  - ``RLReasoningAgent``      : per-claim RL actor-critic reasoning
  - ``ContrastiveGraphRAG``   : contrastive evidence retrieval
  - Temporal consistency module  (duck-typed interface)
  - Silence detector module      (duck-typed interface)

Exposes two public methods:

  audit_claim(claim_id, kg)    -> dict   (single claim audit result)
  audit_company(company_id, kg)-> dict   (full company AuditResult)

The ``AuditResult`` dict schema matches ``ontology_schema.json`` v2.0.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from kg.graph_store import KnowledgeGraph
from reasoning.rl_agent import RLReasoningAgent
from retrieval.contrastive_graph_rag import ContrastiveGraphRAG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Risk threshold constants (from ontology_doc.md §2.10)
# ---------------------------------------------------------------------------

_TRUST_LOW_RISK: float = 0.80    # trust_score >= this -> Low risk
_TRUST_MEDIUM_RISK: float = 0.50 # trust_score >= this -> Medium risk
                                  # trust_score <  this -> High risk


class VerdictGenerator:
    """
    Orchestrates claim-level and company-level greenwashing audits.

    Parameters
    ----------
    agent : RLReasoningAgent
        Configured RL reasoning agent used for per-claim inference.
    graph_rag : ContrastiveGraphRAG
        Contrastive retrieval module bound to the current KG.
    temporal_module : object | None
        Module with a ``check(company_id, kg)`` method that returns a
        dict with at least ``{"consistent": bool, "issues": list[str]}``.
        Pass ``None`` to skip temporal consistency checks.
    silence_detector : object | None
        Module with a ``detect(company_id, kg)`` method that returns a
        dict with at least ``{"silent_pillars": list[str]}``.
        Pass ``None`` to skip silence detection.
    """

    def __init__(
        self,
        agent: RLReasoningAgent,
        graph_rag: ContrastiveGraphRAG,
        temporal_module: Any | None = None,
        silence_detector: Any | None = None,
    ) -> None:
        self.agent = agent
        self.graph_rag = graph_rag
        self.temporal_module = temporal_module
        self.silence_detector = silence_detector

    # ------------------------------------------------------------------
    # Claim-level audit
    # ------------------------------------------------------------------

    def audit_claim(
        self,
        claim_id: str,
        kg: KnowledgeGraph,
    ) -> dict[str, Any]:
        """
        Perform a full greenwashing audit for a single claim.

        Steps
        -----
        1. Retrieve contrastive context via ``ContrastiveGraphRAG``.
        2. Run the RL actor-critic reasoning loop via ``RLReasoningAgent``.
        3. Return a structured result dict.

        Parameters
        ----------
        claim_id : str
            KG node ID of the Claim to audit (e.g. ``CLM_E_001``).
        kg : KnowledgeGraph
            In-memory knowledge graph.  The ``graph_rag`` instance must
            have been initialised with the same graph; passing ``kg`` here
            allows future hot-swapping of graph instances.

        Returns
        -------
        dict with keys:
            claim_id            : str
            claim_text          : str
            pillar              : str
            verdict             : "Verified" | "Greenwashing" | "Insufficient_Evidence"
            confidence          : float
            balance_score       : float   (pro_paths / total_paths)
            pro_count           : int
            anti_count          : int
            reasoning_chain     : list[dict]
            evidence_chain      : list[str]
            iterations_used     : int
            low_confidence_flag : bool
        """
        # 1. Contrastive context
        contrastive_context = self.graph_rag.retrieve_contrastive_context(claim_id)

        # Attach the RAG instance so rl_agent.reason() can call format_paths_for_llm
        contrastive_context["_rag_instance"] = self.graph_rag

        claim_node: dict[str, Any] = contrastive_context.get("claim", {})
        if not claim_node:
            logger.warning("audit_claim: claim node %r not found in KG", claim_id)
            return _empty_claim_result(claim_id)

        # 2. RL reasoning
        reasoning_result = self.agent.reason(
            claim_id=claim_id,
            claim=claim_node,
            contrastive_context=contrastive_context,
        )

        return {
            "claim_id": claim_id,
            "claim_text": claim_node.get("text", ""),
            "pillar": claim_node.get("pillar", "?"),
            "verdict": reasoning_result.get("verdict", "Insufficient_Evidence"),
            "confidence": reasoning_result.get("confidence", 0.0),
            "balance_score": contrastive_context.get("balance_score", 0.0),
            "pro_count": contrastive_context.get("pro_count", 0),
            "anti_count": contrastive_context.get("anti_count", 0),
            "reasoning_chain": reasoning_result.get("reasoning_chain", []),
            "evidence_chain": reasoning_result.get("evidence_chain", []),
            "iterations_used": reasoning_result.get("iterations_used", 0),
            "low_confidence_flag": reasoning_result.get("low_confidence_flag", True),
        }

    # ------------------------------------------------------------------
    # Company-level audit
    # ------------------------------------------------------------------

    def audit_company(
        self,
        company_id: str,
        kg: KnowledgeGraph,
    ) -> dict[str, Any]:
        """
        Perform a full greenwashing audit for all claims of a company.

        Steps
        -----
        1. Retrieve all Claim nodes associated with *company_id* via
           ``claims_reduction`` edges.
        2. Audit each claim with ``audit_claim``.
        3. Run temporal consistency check (if module available).
        4. Run silence detection (if module available).
        5. Compute aggregate ``trust_score``, ``greenwashing_risk``,
           and pillar-level scores (e_score, s_score, g_score).
        6. Return an ``AuditResult`` dict matching the ontology schema.

        Parameters
        ----------
        company_id : str
            KG node ID of the Company (e.g. ``COMP_FPT``).
        kg : KnowledgeGraph
            In-memory knowledge graph.

        Returns
        -------
        dict
            Full AuditResult matching ontology_schema.json §AuditResult.
        """
        # 1. Gather claim IDs for this company
        claim_ids = _get_company_claim_ids(company_id, kg)
        if not claim_ids:
            logger.warning(
                "audit_company: no claims found for company %r", company_id
            )

        # 2. Audit each claim
        claim_results: list[dict[str, Any]] = []
        for claim_id in claim_ids:
            try:
                result = self.audit_claim(claim_id=claim_id, kg=kg)
                claim_results.append(result)
            except Exception as exc:
                logger.error(
                    "audit_company: error auditing claim %r: %s", claim_id, exc
                )
                claim_results.append(_empty_claim_result(claim_id))

        # 3. Temporal consistency check
        temporal_issues: list[str] = []
        temporal_consistent: bool = True
        if self.temporal_module is not None:
            try:
                temporal_result = self.temporal_module.check(company_id, kg)
                temporal_consistent = temporal_result.get("consistent", True)
                temporal_issues = temporal_result.get("issues", [])
            except Exception as exc:
                logger.warning("Temporal module failed: %s", exc)

        # 4. Silence detection
        silent_pillars: list[str] = []
        if self.silence_detector is not None:
            try:
                silence_result = self.silence_detector.detect(company_id, kg)
                silent_pillars = silence_result.get("silent_pillars", [])
            except Exception as exc:
                logger.warning("Silence detector failed: %s", exc)

        # 5. Aggregate scoring
        total_claims = len(claim_results)
        supported_claims = sum(
            1 for r in claim_results if r.get("verdict") == "Verified"
        )
        flagged_claims = sum(
            1 for r in claim_results if r.get("verdict") == "Greenwashing"
        )

        trust_score = supported_claims / max(total_claims, 1)
        greenwashing_risk = _compute_risk_level(trust_score)

        # Pillar-level scores
        e_score = _pillar_score(claim_results, "E")
        s_score = _pillar_score(claim_results, "S")
        g_score = _pillar_score(claim_results, "G")

        # Determine report_id: try to get it from the KG company node
        company_node = _safe_get_node(kg, company_id) or {}
        report_id = company_node.get("report_id", f"RPT_{company_id}_UNKNOWN")

        # Summary text
        flagged_count_text = (
            f"{flagged_claims}/{total_claims}"
            if total_claims
            else "0/0"
        )
        summary_parts: list[str] = [
            f"Company {company_id}: {supported_claims}/{total_claims} claims verified.",
            f"{flagged_count_text} claims flagged as potential greenwashing.",
        ]
        if not temporal_consistent:
            summary_parts.append(
                f"Temporal inconsistencies detected: {'; '.join(temporal_issues[:3])}"
            )
        if silent_pillars:
            summary_parts.append(
                f"Reporting silence detected in pillars: {', '.join(silent_pillars)}"
            )
        summary = " ".join(summary_parts)

        audit_id = f"AUDIT_{company_id}_{datetime.date.today().year}"
        audited_at = datetime.date.today().isoformat()

        return {
            # Ontology AuditResult fields
            "id": audit_id,
            "company_id": company_id,
            "report_id": report_id,
            "audited_at": audited_at,
            "trust_score": round(trust_score, 4),
            "greenwashing_risk": greenwashing_risk,
            "total_claims": total_claims,
            "supported_claims": supported_claims,
            "flagged_claims": flagged_claims,
            "e_score": e_score,
            "s_score": s_score,
            "g_score": g_score,
            "summary": summary,
            # Extended fields for pipeline consumers
            "claim_results": claim_results,
            "temporal_consistent": temporal_consistent,
            "temporal_issues": temporal_issues,
            "silent_pillars": silent_pillars,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_company_claim_ids(company_id: str, kg: KnowledgeGraph) -> list[str]:
    """
    Return the IDs of all Claim nodes linked to *company_id* via
    ``claims_reduction`` edges.
    """
    try:
        edges = kg.get_edges(company_id)
    except Exception:
        return []

    claim_ids: list[str] = []
    for edge in edges:
        edge_type = edge.get("type") or edge.get("edge_type", "")
        if edge_type == "claims_reduction":
            target_id = edge.get("target") or edge.get("to", "")
            if target_id:
                claim_ids.append(target_id)

    return claim_ids


def _safe_get_node(kg: KnowledgeGraph, node_id: str) -> dict[str, Any] | None:
    """Retrieve a node without raising exceptions."""
    try:
        return kg.get_node(node_id)
    except Exception:
        return None


def _compute_risk_level(trust_score: float) -> str:
    """
    Convert a trust_score into a greenwashing_risk label.

    Thresholds (from ontology_doc.md §2.10):
      >= 0.80 -> "Low"
      >= 0.50 -> "Medium"
      <  0.50 -> "High"
    """
    if trust_score >= _TRUST_LOW_RISK:
        return "Low"
    if trust_score >= _TRUST_MEDIUM_RISK:
        return "Medium"
    return "High"


def _pillar_score(claim_results: list[dict[str, Any]], pillar: str) -> float:
    """
    Compute the verified-claim ratio for a specific ESG pillar.

    Returns 0.0 if no claims belong to the pillar.
    """
    pillar_results = [r for r in claim_results if r.get("pillar") == pillar]
    if not pillar_results:
        return 0.0
    verified = sum(1 for r in pillar_results if r.get("verdict") == "Verified")
    return round(verified / len(pillar_results), 4)


def _empty_claim_result(claim_id: str) -> dict[str, Any]:
    """Return a safe empty claim result for error/missing cases."""
    return {
        "claim_id": claim_id,
        "claim_text": "",
        "pillar": "?",
        "verdict": "Insufficient_Evidence",
        "confidence": 0.0,
        "balance_score": 0.0,
        "pro_count": 0,
        "anti_count": 0,
        "reasoning_chain": [],
        "evidence_chain": [],
        "iterations_used": 0,
        "low_confidence_flag": True,
    }
