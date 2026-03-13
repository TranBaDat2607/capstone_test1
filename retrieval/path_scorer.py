"""
retrieval/path_scorer.py

Scoring utilities for KG paths retrieved during contrastive subgraph
retrieval.  All methods operate on raw interleaved path lists
(alternating node dicts and edge dicts) as produced by
``ContrastiveGraphRAG``.

No external dependencies beyond the Python standard library.
"""

from __future__ import annotations

import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Source-type reliability weights (aligned with ontology entity types)
_RELIABILITY: dict[str, float] = {
    "Report": 1.00,
    "DataPoint": 0.95,
    "Metric": 0.95,
    "Regulation": 1.00,
    "AuditResult": 1.00,
    "Target": 0.90,
    "Project": 0.90,
    "Company": 0.90,
    "NewsEvent": 0.85,
    "Claim": 0.80,
}

# Composite score weights
_W_CONFIDENCE: float = 0.50
_W_RECENCY: float = 0.25
_W_RELIABILITY: float = 0.25

# Recency decay threshold (years relative to claim year)
_RECENCY_WINDOW_YEARS: int = 2
_RECENCY_DECAY: float = 0.70
_RECENCY_FRESH: float = 1.00

# Fallback values used when data is missing
_DEFAULT_CONFIDENCE: float = 0.70
_DEFAULT_RELIABILITY: float = 0.85
_DEFAULT_RECENCY: float = 0.85


class PathScorer:
    """
    Stateless scorer for KG evidence paths.

    Each ``score_*`` method accepts an interleaved list in the form::

        [node_dict, edge_dict, node_dict, edge_dict, ..., node_dict]

    or just a list of edge dicts / node dicts, depending on the method.
    The methods are tolerant of either representation.

    Methods
    -------
    score_by_confidence(path)
        Mean confidence_score across all edges in *path*.
    score_by_recency(path, claim_year)
        Recency factor based on ``published_at`` / ``year`` fields of
        news/data nodes relative to *claim_year*.
    score_by_source_reliability(path)
        Reliability weight of the terminal node's entity type.
    composite_score(path, claim_year)
        Weighted combination of the three sub-scores.
    """

    # ------------------------------------------------------------------
    # Individual scoring dimensions
    # ------------------------------------------------------------------

    def score_by_confidence(self, path: list[Any]) -> float:
        """
        Compute the mean ``confidence_score`` across all edges in *path*.

        Parameters
        ----------
        path : list
            Interleaved list of node and edge dicts, or a flat list of
            edge dicts.

        Returns
        -------
        float
            Mean confidence in [0, 1].  Returns ``_DEFAULT_CONFIDENCE``
            when no edges with a ``confidence_score`` field are found.
        """
        confidences: list[float] = []
        for element in path:
            if not isinstance(element, dict):
                continue
            # Edge dicts: either no "id" key, or "edge_type" key present
            if "id" not in element or "edge_type" in element:
                score = element.get("confidence_score")
                if score is not None:
                    try:
                        confidences.append(float(score))
                    except (TypeError, ValueError):
                        pass

        if not confidences:
            return _DEFAULT_CONFIDENCE

        return round(sum(confidences) / len(confidences), 4)

    def score_by_recency(
        self,
        path: list[Any],
        claim_year: int | None = None,
    ) -> float:
        """
        Compute a recency factor for the path.

        For each node that has temporal metadata (``published_at``, ``year``),
        compare it against *claim_year* (or the current year if unknown):

        - Within ``_RECENCY_WINDOW_YEARS`` years -> fresh factor (1.0)
        - Older                                  -> decay factor (0.7)

        The final score is the mean across all temporal nodes found.

        Parameters
        ----------
        path : list
            Interleaved list of node and edge dicts.
        claim_year : int | None
            Reference year for recency calculation.

        Returns
        -------
        float
            Recency factor in [0.7, 1.0].
        """
        reference_year = claim_year or datetime.date.today().year
        factors: list[float] = []

        for element in path:
            if not isinstance(element, dict):
                continue
            # Only inspect node-like elements (those with an "id")
            if "id" not in element:
                continue

            node_year: int | None = _extract_year(element)
            if node_year is None:
                continue

            age = abs(reference_year - node_year)
            factors.append(
                _RECENCY_FRESH if age <= _RECENCY_WINDOW_YEARS else _RECENCY_DECAY
            )

        if not factors:
            return _DEFAULT_RECENCY

        return round(sum(factors) / len(factors), 4)

    def score_by_source_reliability(self, path: list[Any]) -> float:
        """
        Compute source reliability based on the entity type of the
        **terminal node** in *path*.

        Parameters
        ----------
        path : list
            Interleaved list of node and edge dicts.

        Returns
        -------
        float
            Reliability weight in [0, 1].
        """
        nodes = [e for e in path if isinstance(e, dict) and "id" in e]
        if not nodes:
            return _DEFAULT_RELIABILITY

        terminal_node = nodes[-1]
        node_type = terminal_node.get("node_type") or terminal_node.get("type", "")
        return _RELIABILITY.get(node_type, _DEFAULT_RELIABILITY)

    def composite_score(
        self,
        path: list[Any],
        claim_year: int | None = None,
    ) -> float:
        """
        Compute a weighted composite score for *path*.

        Formula::

            score = (W_CONF × avg_confidence)
                  + (W_RECENCY × recency_factor)
                  + (W_RELY × source_reliability)

        Weights: confidence=0.50, recency=0.25, reliability=0.25.

        Parameters
        ----------
        path : list
            Interleaved list of node and edge dicts.
        claim_year : int | None
            Reference year for recency calculation.

        Returns
        -------
        float
            Composite score in [0, 1].
        """
        if not path:
            return 0.0

        confidence = self.score_by_confidence(path)
        recency = self.score_by_recency(path, claim_year=claim_year)
        reliability = self.score_by_source_reliability(path)

        score = (
            _W_CONFIDENCE * confidence
            + _W_RECENCY * recency
            + _W_RELIABILITY * reliability
        )
        return round(min(max(score, 0.0), 1.0), 4)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _extract_year(node: dict[str, Any]) -> int | None:
    """
    Extract the most relevant year from a node dict.

    Checks (in order): ``published_at``, ``year``, ``start_year``,
    ``target_year``, ``baseline_year``.
    """
    # published_at: "YYYY-MM-DD" or "YYYY"
    published_at = node.get("published_at")
    if published_at:
        try:
            return int(str(published_at)[:4])
        except (ValueError, TypeError):
            pass

    for key in ("year", "start_year", "target_year", "baseline_year"):
        val = node.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass

    return None
