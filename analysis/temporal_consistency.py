"""
analysis/temporal_consistency.py

Diachronic (cross-time) consistency checking for ESG claims against a
news-event Knowledge Graph timeline.

Novel contribution: existing LLM-based greenwashing detectors evaluate
claims in isolation or against contemporaneous data.  This module performs
*diachronic* consistency checking — it compares forward-looking ESG rhetoric
to historical news records across a configurable sliding window, exposing
divergences that only become visible over time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kg.graph_store import KnowledgeGraph
    from config import Config

logger = logging.getLogger(__name__)


class TemporalConsistencyModule:
    """
    Detects behavioral divergence between forward-looking ESG claims
    and historical news records.

    Key insight: Companies can make truthful claims at one point in time
    that become false later — or make forward-looking promises that
    contradict their recorded past behavior.

    Novel contribution: diachronic consistency checking over a news KG
    timeline (no existing LLM greenwashing detector does this).

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
        self.window: int = getattr(config, "TEMPORAL_WINDOW_YEARS", 2)

    # ------------------------------------------------------------------
    # Graph helpers
    # ------------------------------------------------------------------

    def get_news_events_in_window(
        self,
        company_id: str,
        start_year: int,
        end_year: int,
    ) -> list[dict]:
        """Retrieve all ``NewsEvent`` nodes connected to *company_id* within
        the inclusive year window ``[start_year, end_year]``.

        Subsidiary companies (connected via ``subsidiary_of`` relations where
        the *target* is ``company_id``) are also traversed, reflecting the
        principle that a parent company's ESG posture is influenced by the
        conduct of its subsidiaries.

        Args:
            company_id: The KG node ID of the company (e.g. ``"COMP_FPT"``).
            start_year: Inclusive lower bound of the time window.
            end_year:   Inclusive upper bound of the time window.

        Returns:
            A list of node-property dicts, each augmented with ``"node_id"``
            and (where parseable) ``"year"`` keys.
        """
        # Collect the focal company and any direct subsidiaries.
        company_ids: set[str] = {company_id}
        for edge in self.kg.get_all_edges():
            if edge.get("type") == "subsidiary_of" and edge.get("target") == company_id:
                company_ids.add(edge["source"])

        news_events: list[dict] = []

        for node in self.kg.get_nodes_by_type("NewsEvent"):
            node_id = node.get("node_id", "")
            props = node.get("properties", {})
            # Merge props into a flat dict for _extract_year
            flat = {**props, "node_type": node.get("node_type", ""), "node_id": node_id}
            year = self._extract_year(flat)
            if year is None or not (start_year <= year <= end_year):
                continue

            # Check if this event is connected to any company in our set
            predecessors = {n.get("node_id") for n in self.kg.get_predecessors(node_id)}
            successors = {nb.get("node_id") for nb in self.kg.get_neighbors(node_id, direction="out")}
            neighbours = predecessors | successors
            if neighbours & company_ids:
                event = {**flat}
                event["year"] = year
                news_events.append(event)

        return news_events

    # ------------------------------------------------------------------
    # Sentiment trajectory
    # ------------------------------------------------------------------

    def compute_sentiment_trajectory(self, events: list[dict]) -> dict:
        """Group *events* by year and compute per-year sentiment counts and
        net-sentiment score.

        Args:
            events: A list of NewsEvent dicts as returned by
                    ``get_news_events_in_window``.  Each dict must contain
                    ``"year"`` and ``"sentiment"`` keys
                    (``"Positive"`` | ``"Negative"`` | ``"Neutral"``).

        Returns:
            A dict keyed by year (``int``) whose values are::

                {
                    "positive": int,
                    "negative": int,
                    "neutral":  int,
                    "net_sentiment": float,   # in [-1, 1]
                }

            ``net_sentiment`` is computed as
            ``(positive - negative) / max(total, 1)``.
        """
        trajectory: dict[int, dict] = {}

        for event in events:
            year = event.get("year")
            if year is None:
                continue

            if year not in trajectory:
                trajectory[year] = {"positive": 0, "negative": 0, "neutral": 0}

            sentiment = str(event.get("sentiment", "Neutral")).capitalize()
            if sentiment == "Positive":
                trajectory[year]["positive"] += 1
            elif sentiment == "Negative":
                trajectory[year]["negative"] += 1
            else:
                trajectory[year]["neutral"] += 1

        for year, counts in trajectory.items():
            total = counts["positive"] + counts["negative"] + counts["neutral"]
            counts["net_sentiment"] = (
                (counts["positive"] - counts["negative"]) / max(total, 1)
            )

        return trajectory

    # ------------------------------------------------------------------
    # Per-claim consistency score
    # ------------------------------------------------------------------

    def compute_temporal_consistency_score(
        self,
        claim: dict,
        company_id: str,
    ) -> float:
        """Compute how consistent a single ESG *claim* is with the surrounding
        news context within a ``±window`` year band.

        A claim with ``Positive`` sentiment should be corroborated by
        predominantly positive or neutral news coverage.  A positive claim
        surrounded by negative news is a consistency red flag.

        Args:
            claim:      A KG node-property dict.  Must contain ``"year"`` and
                        ``"sentiment"`` keys.
            company_id: The KG node ID of the company making the claim.

        Returns:
            A float in ``[0.0, 1.0]`` where ``1.0`` means all surrounding
            news events are consistent with the claim's sentiment and
            ``0.0`` means all are contradictory.  Returns ``0.5`` when no
            relevant news exists (neutral / insufficient-evidence default).
        """
        claim_year: int | None = claim.get("year")
        if claim_year is None:
            logger.warning("Claim missing 'year' property; returning neutral score 0.5")
            return 0.5

        claim_sentiment = str(claim.get("sentiment", "Positive")).capitalize()

        start = claim_year - self.window
        end = claim_year + self.window
        events = self.get_news_events_in_window(company_id, start, end)

        if not events:
            return 0.5  # no evidence — neutral default

        consistent_count = 0
        total = len(events)

        for event in events:
            news_sentiment = str(event.get("sentiment", "Neutral")).capitalize()
            if claim_sentiment == "Positive":
                # Positive claim is consistent with Positive or Neutral news.
                if news_sentiment in ("Positive", "Neutral"):
                    consistent_count += 1
            elif claim_sentiment == "Negative":
                # Negative claim is consistent with Negative or Neutral news.
                if news_sentiment in ("Negative", "Neutral"):
                    consistent_count += 1
            else:
                # Neutral claim — any non-extreme news is consistent.
                consistent_count += 1

        return consistent_count / max(total, 1)

    # ------------------------------------------------------------------
    # Rhetoric–behaviour gap
    # ------------------------------------------------------------------

    def detect_rhetoric_behavior_gap(
        self,
        company_id: str,
        claim_year: int,
    ) -> dict:
        """Detect whether ESG rhetoric improves while news coverage worsens
        in the same year — the canonical greenwashing signal.

        The method computes:
        * **rhetoric_trend**: change in average claim sentiment score from
          ``(claim_year - 1)`` to ``claim_year``.
        * **behavior_trend**: change in average news net-sentiment from
          ``(claim_year - 1)`` to ``claim_year``.
        * **gap_magnitude**: ``rhetoric_trend - behavior_trend``.

        A gap is flagged when rhetoric improves (``rhetoric_trend > 0``)
        while behavior worsens (``behavior_trend < 0``).

        Args:
            company_id: KG node ID of the company.
            claim_year: The focal year for gap detection.

        Returns:
            A dict::

                {
                    "gap_detected":      bool,
                    "rhetoric_trend":    float,
                    "behavior_trend":    float,
                    "gap_magnitude":     float,
                }
        """
        # ------------------------------------------------------------------
        # Gather claims for the focal year and the prior year.
        # ------------------------------------------------------------------
        def _avg_claim_sentiment(year: int) -> float:
            scores: list[float] = []
            for nb in self.kg.get_neighbors(company_id, direction="out", edge_types=["claims_reduction"]):
                node = self.kg.get_node(nb.get("node_id", ""))
                if node is None:
                    continue
                props = node.get("properties", {})
                if node.get("node_type") != "Claim":
                    continue
                if props.get("year") != year:
                    continue
                sentiment = str(props.get("sentiment", "Neutral")).capitalize()
                scores.append(self._sentiment_to_score(sentiment))
            return sum(scores) / max(len(scores), 1) if scores else 0.0

        # ------------------------------------------------------------------
        # News net-sentiment for the focal year and the prior year.
        # ------------------------------------------------------------------
        def _avg_news_sentiment(year: int) -> float:
            events = self.get_news_events_in_window(company_id, year, year)
            if not events:
                return 0.0
            trajectory = self.compute_sentiment_trajectory(events)
            return trajectory.get(year, {}).get("net_sentiment", 0.0)

        rhetoric_prev = _avg_claim_sentiment(claim_year - 1)
        rhetoric_curr = _avg_claim_sentiment(claim_year)
        rhetoric_trend = rhetoric_curr - rhetoric_prev

        behavior_prev = _avg_news_sentiment(claim_year - 1)
        behavior_curr = _avg_news_sentiment(claim_year)
        behavior_trend = behavior_curr - behavior_prev

        gap_magnitude = rhetoric_trend - behavior_trend
        gap_detected = (rhetoric_trend > 0) and (behavior_trend < 0)

        return {
            "gap_detected": gap_detected,
            "rhetoric_trend": round(rhetoric_trend, 4),
            "behavior_trend": round(behavior_trend, 4),
            "gap_magnitude": round(gap_magnitude, 4),
        }

    # ------------------------------------------------------------------
    # Full timeline analysis
    # ------------------------------------------------------------------

    def analyze_company_timeline(self, company_id: str) -> dict:
        """Run a full diachronic analysis for *company_id* across all years
        represented in the Knowledge Graph.

        For each year the method collects:
        * number of claims and positive claims
        * number of news events and negative news events
        * per-year consistency score

        It then identifies *divergence years* — years where the consistency
        score falls below ``0.5`` (i.e. contradicting news outweighs
        supporting news) and computes an overall consistency score.

        Args:
            company_id: KG node ID of the company.

        Returns:
            A dict::

                {
                    "timeline": {
                        year: {
                            "claims_count":    int,
                            "positive_claims": int,
                            "news_count":      int,
                            "negative_news":   int,
                            "consistency_score": float,
                        },
                        ...
                    },
                    "overall_consistency": float,
                    "divergence_years":    list[int],
                }
        """
        # Collect all years present in claims and news events for this company.
        years: set[int] = set()

        for nb in self.kg.get_neighbors(company_id, direction="out"):
            node = self.kg.get_node(nb.get("node_id", ""))
            if node is None:
                continue
            props = node.get("properties", {})
            flat = {**props, "node_type": node.get("node_type", "")}
            year = props.get("year") or self._extract_year(flat)
            if year is not None:
                years.add(int(year))

        # Also include years from news events connected to the company.
        for news_node in self.kg.get_nodes_by_type("NewsEvent"):
            nid = news_node.get("node_id", "")
            predecessors = {n.get("node_id") for n in self.kg.get_predecessors(nid)}
            successors = {n.get("node_id") for n in self.kg.get_neighbors(nid, direction="out")}
            if company_id in (predecessors | successors):
                props = news_node.get("properties", {})
                flat = {**props, "node_type": news_node.get("node_type", "")}
                year = self._extract_year(flat)
                if year is not None:
                    years.add(year)

        if not years:
            return {
                "timeline": {},
                "overall_consistency": 1.0,
                "divergence_years": [],
            }

        timeline: dict[int, dict] = {}
        consistency_scores: list[float] = []

        for year in sorted(years):
            # Claims — gather via public KG API
            claims_count = 0
            positive_claims = 0
            year_claims = []
            for nb in self.kg.get_neighbors(company_id, direction="out", edge_types=["claims_reduction"]):
                node = self.kg.get_node(nb.get("node_id", ""))
                if node is None or node.get("node_type") != "Claim":
                    continue
                props = node.get("properties", {})
                flat = {**props, "node_type": "Claim", "node_id": node.get("node_id")}
                node_year = props.get("year") or self._extract_year(flat)
                if node_year != year:
                    continue
                claims_count += 1
                if str(props.get("sentiment", "")).capitalize() == "Positive":
                    positive_claims += 1
                claim_for_scoring = {**flat, "year": year}
                year_claims.append(claim_for_scoring)

            # News events
            events = self.get_news_events_in_window(company_id, year, year)
            news_count = len(events)
            negative_news = sum(
                1 for e in events
                if str(e.get("sentiment", "")).capitalize() == "Negative"
            )

            if year_claims:
                year_scores = [
                    self.compute_temporal_consistency_score(c, company_id)
                    for c in year_claims
                ]
                consistency_score = sum(year_scores) / len(year_scores)
            elif news_count > 0:
                # No claims but there is news — derive score from news alone.
                negative_ratio = negative_news / max(news_count, 1)
                consistency_score = 1.0 - negative_ratio
            else:
                consistency_score = 1.0  # no data — assume consistent

            timeline[year] = {
                "claims_count": claims_count,
                "positive_claims": positive_claims,
                "news_count": news_count,
                "negative_news": negative_news,
                "consistency_score": round(consistency_score, 4),
            }
            consistency_scores.append(consistency_score)

        overall_consistency = (
            sum(consistency_scores) / len(consistency_scores)
            if consistency_scores
            else 1.0
        )
        divergence_years = [
            year for year, data in timeline.items()
            if data["consistency_score"] < 0.5
        ]

        return {
            "timeline": timeline,
            "overall_consistency": round(overall_consistency, 4),
            "divergence_years": sorted(divergence_years),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_year(node_data: dict) -> int | None:
        """Best-effort extraction of a publication year from a node-property dict.

        Tries ``"year"`` first, then parses the leading four digits of
        ``"published_at"`` (ISO-8601 date string).
        """
        if "year" in node_data and node_data["year"] is not None:
            try:
                return int(node_data["year"])
            except (ValueError, TypeError):
                pass

        published_at = node_data.get("published_at", "")
        if published_at and len(str(published_at)) >= 4:
            try:
                return int(str(published_at)[:4])
            except (ValueError, TypeError):
                pass

        return None

    @staticmethod
    def _sentiment_to_score(sentiment: str) -> float:
        """Map a sentiment label to a numeric score in ``[-1, 1]``."""
        mapping = {"Positive": 1.0, "Neutral": 0.0, "Negative": -1.0}
        return mapping.get(sentiment.capitalize(), 0.0)
