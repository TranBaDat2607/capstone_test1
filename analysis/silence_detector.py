"""
analysis/silence_detector.py

Graph-structural detection of strategic omission in ESG disclosures.

Greenwashing is not only about false claims — it is also about strategic
omission.  A company that says nothing about supply-chain labour practices
while loudly claiming environmental leadership engages in
*silence-as-deception*.

This module measures graph node density per mandatory disclosure category
against regulatory requirements (TT08/2026 checklist).  Unlike text-based
absence detection (e.g. SSRN 2025), the absence signal here is fully
auditable: the graph either contains qualifying nodes or it does not.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kg.graph_store import KnowledgeGraph
    from config import Config

logger = logging.getLogger(__name__)

# Node types that count as disclosure evidence for a category.
_DISCLOSURE_NODE_TYPES: frozenset[str] = frozenset(
    {"Metric", "DataPoint", "Claim"}
)

# Edge types that connect a company to a disclosure node.
_DISCLOSURE_EDGE_TYPES: frozenset[str] = frozenset(
    {"has_emission", "claims_reduction", "has_metric", "has_datapoint", "makes_claim"}
)

# Minimum number of qualifying nodes required for a category to be considered
# adequately covered.
_ADEQUATE_COVERAGE_MINIMUM: int = 2


class SelectiveSilenceDetector:
    """
    Detects strategic omission in ESG disclosures.

    Greenwashing is not only about false claims — it's also about
    strategic omission. Companies that say nothing about supply chain
    labor practices while loudly claiming environmental leadership
    engage in silence-as-deception.

    Method: measure graph density per mandatory disclosure category
    against regulatory requirements (TT08/2026 checklist).

    Novel: graph-structural absence detection (more auditable than
    text-based absence detection from SSRN 2025).

    Args:
        kg:     A populated ``KnowledgeGraph`` instance.
        config: Optional ``Config`` class (or instance); falls back to the
                module-level ``Config`` defaults when ``None``.
    """

    def __init__(self, kg: "KnowledgeGraph", config: "Config | None" = None) -> None:
        self.kg = kg

        if config is None:
            from config import Config
            config = Config

        self.config = config
        self.silence_threshold: float = getattr(
            config, "SILENCE_COVERAGE_THRESHOLD", 0.3
        )

    # ------------------------------------------------------------------
    # Mandatory category registry
    # ------------------------------------------------------------------

    def get_mandatory_categories(self, regulation_id: str) -> list[str]:
        """Return the list of mandatory disclosure categories for *regulation_id*.

        Categories are sourced from
        ``config.MANDATORY_DISCLOSURE_CATEGORIES[regulation_id]``.

        Args:
            regulation_id: A regulation node ID such as ``"REG_TT08_2026"``.

        Returns:
            List of category name strings (e.g. ``["Emissions", "Energy", ...]``).
            Returns an empty list if the regulation ID is not found.
        """
        categories_map: dict[str, list[str]] = getattr(
            self.config, "MANDATORY_DISCLOSURE_CATEGORIES", {}
        )
        result = categories_map.get(regulation_id, [])
        if not result:
            logger.warning(
                "No mandatory categories found for regulation '%s'. "
                "Check Config.MANDATORY_DISCLOSURE_CATEGORIES.",
                regulation_id,
            )
        return list(result)

    # ------------------------------------------------------------------
    # Node counting
    # ------------------------------------------------------------------

    def count_company_nodes_in_category(
        self,
        company_id: str,
        category: str,
    ) -> int:
        """Count qualifying KG nodes for *company_id* in *category*.

        A node qualifies when:
        * its ``node_type`` is one of ``Metric``, ``DataPoint``, or ``Claim``;
        * its ``category`` property matches *category* (case-insensitive); and
        * it is reachable from *company_id* via any outgoing edge whose
          ``relation_type`` is in ``_DISCLOSURE_EDGE_TYPES``, *or* is directly
          connected by any edge.

        Subsidiaries are also traversed (nodes reachable via
        ``subsidiary_of`` edges).

        Args:
            company_id: KG node ID of the focal company.
            category:   Disclosure category name (e.g. ``"Emissions"``).

        Returns:
            Integer count of qualifying nodes.
        """
        category_lower = category.lower()

        # Collect the focal company and any direct subsidiaries.
        company_ids: set[str] = {company_id}
        for edge in self.kg.get_all_edges():
            if edge.get("type") == "subsidiary_of" and edge.get("target") == company_id:
                company_ids.add(edge["source"])

        seen_nodes: set[str] = set()
        count = 0

        for cid in company_ids:
            for edge in self.kg.get_edges(cid):
                tgt = edge.get("target", "")
                if not tgt or tgt in seen_nodes:
                    continue

                node = self.kg.get_node(tgt)
                if node is None:
                    continue

                node_type = node.get("node_type", "")
                if node_type not in _DISCLOSURE_NODE_TYPES:
                    continue

                props = node.get("properties", {})
                node_category = str(props.get("category", "")).lower()
                node_pillar = str(props.get("pillar", "")).lower()

                # Match by category field, or (fallback) by GRI-pillar mapping.
                category_match = (
                    node_category == category_lower
                    or self._pillar_matches_category(node_pillar, category_lower)
                )
                if not category_match:
                    continue

                seen_nodes.add(tgt)
                count += 1

        return count

    # ------------------------------------------------------------------
    # Coverage scoring
    # ------------------------------------------------------------------

    def compute_coverage_score(self, company_id: str, category: str) -> float:
        """Compute the disclosure coverage score for *category*.

        Coverage is defined as::

            score = actual_nodes / ADEQUATE_COVERAGE_MINIMUM

        capped at ``1.0``.  A score of ``1.0`` means the company has at least
        ``_ADEQUATE_COVERAGE_MINIMUM`` qualifying nodes for this category.

        Args:
            company_id: KG node ID of the focal company.
            category:   Disclosure category name.

        Returns:
            Float in ``[0.0, 1.0]``.
        """
        actual = self.count_company_nodes_in_category(company_id, category)
        score = actual / _ADEQUATE_COVERAGE_MINIMUM
        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Silence-signal detection
    # ------------------------------------------------------------------

    def detect_silence_signals(
        self,
        company_id: str,
        regulation_id: str = "REG_TT08_2026",
    ) -> dict:
        """Scan all mandatory categories for *regulation_id* and flag those
        below the silence coverage threshold.

        Args:
            company_id:    KG node ID of the focal company.
            regulation_id: Regulation to check against.  Defaults to
                           ``"REG_TT08_2026"`` (TT08/2026/TT-BTC).

        Returns:
            A dict with the following structure::

                {
                    "company_id":      str,
                    "regulation_id":   str,
                    "coverage_scores": {category: float, ...},
                    "silence_flags":   [category, ...],   # categories below threshold
                    "overall_coverage": float,
                    "silence_risk":    "Low" | "Medium" | "High",
                }

            ``silence_risk`` is determined by the proportion of categories
            that are silent:
            * ``< 0.25`` silent -> ``"Low"``
            * ``0.25-0.50`` silent -> ``"Medium"``
            * ``> 0.50`` silent -> ``"High"``
        """
        categories = self.get_mandatory_categories(regulation_id)
        if not categories:
            return {
                "company_id": company_id,
                "regulation_id": regulation_id,
                "coverage_scores": {},
                "silence_flags": [],
                "overall_coverage": 1.0,
                "silence_risk": "Low",
            }

        coverage_scores: dict[str, float] = {}
        silence_flags: list[str] = []

        for category in categories:
            score = self.compute_coverage_score(company_id, category)
            coverage_scores[category] = round(score, 4)
            if score < self.silence_threshold:
                silence_flags.append(category)

        overall_coverage = sum(coverage_scores.values()) / max(len(coverage_scores), 1)

        silent_ratio = len(silence_flags) / max(len(categories), 1)
        if silent_ratio > 0.50:
            silence_risk: str = "High"
        elif silent_ratio >= 0.25:
            silence_risk = "Medium"
        else:
            silence_risk = "Low"

        return {
            "company_id": company_id,
            "regulation_id": regulation_id,
            "coverage_scores": coverage_scores,
            "silence_flags": silence_flags,
            "overall_coverage": round(overall_coverage, 4),
            "silence_risk": silence_risk,
        }

    # ------------------------------------------------------------------
    # Human-readable report
    # ------------------------------------------------------------------

    def generate_silence_report(self, signals: dict) -> str:
        """Produce a human-readable text report from silence-detection *signals*.

        Args:
            signals: A dict as returned by ``detect_silence_signals``.

        Returns:
            A formatted multi-line string suitable for logging or display.
        """
        company_id = signals.get("company_id", "Unknown")
        regulation_id = signals.get("regulation_id", "Unknown")
        overall_coverage = signals.get("overall_coverage", 0.0)
        silence_risk = signals.get("silence_risk", "Unknown")
        coverage_scores: dict[str, float] = signals.get("coverage_scores", {})
        silence_flags: list[str] = signals.get("silence_flags", [])

        lines: list[str] = [
            "=" * 60,
            f"Selective Silence Detection Report",
            f"Company       : {company_id}",
            f"Regulation    : {regulation_id}",
            f"Overall Coverage : {overall_coverage:.1%}",
            f"Silence Risk  : {silence_risk}",
            "-" * 60,
            "Per-Category Coverage:",
        ]

        for category, score in coverage_scores.items():
            flag_marker = " [SILENT]" if category in silence_flags else ""
            bar = self._coverage_bar(score)
            lines.append(f"  {category:<25} {bar} {score:.0%}{flag_marker}")

        if silence_flags:
            lines.append("-" * 60)
            lines.append(
                f"Flagged categories ({len(silence_flags)} of "
                f"{len(coverage_scores)}):"
            )
            for cat in silence_flags:
                lines.append(f"  - {cat}")
            lines.append(
                "\nINTERPRETATION: The above categories have insufficient "
                "KG node coverage relative to regulatory requirements.  "
                "This may indicate strategic omission rather than genuine "
                "compliance."
            )
        else:
            lines.append("No silence flags detected — all categories adequately covered.")

        lines.append("=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pillar_matches_category(pillar: str, category: str) -> bool:
        """Approximate mapping from GRI pillar letter to broad disclosure category.

        This is a fallback for nodes that store only a ``pillar`` (``"e"``,
        ``"s"``, ``"g"``) rather than an explicit ``category``.
        """
        environmental_categories = {
            "emissions", "energy", "water", "waste",
        }
        social_categories = {
            "employment", "health_safety", "diversity", "labour",
        }
        governance_categories = {
            "board_governance", "anti_corruption", "transparency",
        }

        if pillar == "e":
            return category in environmental_categories
        if pillar == "s":
            return category in social_categories
        if pillar == "g":
            return category in governance_categories
        return False

    @staticmethod
    def _coverage_bar(score: float, width: int = 10) -> str:
        """Generate a simple ASCII progress bar for *score* (in ``[0, 1]``)."""
        filled = round(score * width)
        return "[" + "#" * filled + "." * (width - filled) + "]"
