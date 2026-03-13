"""
kg/graph_builder.py
Populates a KnowledgeGraph from various data sources.

Sources supported:
  * ``sample_instances.json`` (ontology entity + relation arrays)
  * Live news-article dicts (e.g. from the FPT crawler)
  * Explicit regulation dicts
  * Hard-coded mandatory regulation nodes (TT96/2020, TT08/2026, Green Taxonomy)

Typical usage::

    from kg.graph_builder import GraphBuilder

    builder = GraphBuilder()
    builder.load_from_instances_json("ontology/sample_instances.json")
    builder.add_mandatory_regulation_nodes()
    kg = builder.get_kg()
    print(kg.stats())
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kg.graph_store import KnowledgeGraph

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Builds and enriches a :class:`~kg.graph_store.KnowledgeGraph`.

    Args:
        kg: An existing :class:`KnowledgeGraph` to build upon.  If *None* a
            fresh empty graph is created.
    """

    def __init__(self, kg: KnowledgeGraph | None = None) -> None:
        self._kg: KnowledgeGraph = kg if kg is not None else KnowledgeGraph()
        # Running counter used to generate unique relation IDs
        self._rel_counter: int = 0
        # Running counter used to generate unique news-event node IDs
        self._news_counter: int = 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _next_rel_id(self, prefix: str = "REL") -> str:
        """Return a unique relation ID with the given prefix."""
        self._rel_counter += 1
        return f"{prefix}_{self._rel_counter:05d}"

    def _next_news_id(self) -> str:
        """Return a unique NewsEvent node ID."""
        self._news_counter += 1
        return f"NEWS_AUTO_{self._news_counter:05d}"

    @staticmethod
    def _now_iso() -> str:
        """Return the current UTC datetime as an ISO-8601 date string."""
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Public loaders
    # ------------------------------------------------------------------

    def load_from_instances_json(self, path: str | Path) -> None:
        """Load entities and relations from a ``sample_instances.json`` file.

        The expected top-level structure is::

            {
                "entities": [
                    {"id": "...", "type": "...", "properties": {...}},
                    ...
                ],
                "relations": [
                    {
                        "id": "...",
                        "type": "...",
                        "source_id": "...",
                        "target_id": "...",
                        "properties": {...},
                        "extracted_at": "...",
                        "confidence_score": 0.9,
                        "extraction_method": "..."
                    },
                    ...
                ]
            }

        Relation-level global properties (``extracted_at``, ``confidence_score``,
        ``extraction_method``) are merged into the edge ``properties`` dict.

        Args:
            path: Filesystem path to the JSON file.

        Raises:
            FileNotFoundError: If the JSON file does not exist.
            ValueError: If the JSON structure is missing required keys.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Instances JSON not found: {path}")

        with path.open(encoding="utf-8") as fh:
            data: dict[str, Any] = json.load(fh)

        if "entities" not in data:
            raise ValueError(f"'entities' key missing in {path}")
        if "relations" not in data:
            raise ValueError(f"'relations' key missing in {path}")

        entity_count = 0
        for entity in data["entities"]:
            node_id: str = entity.get("id", "")
            node_type: str = entity.get("type", "Unknown")
            properties: dict = dict(entity.get("properties", {}))
            if not node_id:
                logger.warning("Skipping entity with empty id: %s", entity)
                continue
            self._kg.add_node(node_id, node_type, properties)
            entity_count += 1

        relation_count = 0
        for relation in data["relations"]:
            rel_id: str = relation.get("id", self._next_rel_id())
            rel_type: str = relation.get("type", "")
            source_id: str = relation.get("source_id", "")
            target_id: str = relation.get("target_id", "")

            if not (rel_type and source_id and target_id):
                logger.warning("Skipping incomplete relation: %s", relation)
                continue

            # Merge global relation metadata into properties
            props: dict = dict(relation.get("properties", {}))
            for meta_key in ("extracted_at", "confidence_score", "extraction_method"):
                if meta_key in relation:
                    props.setdefault(meta_key, relation[meta_key])

            self._kg.add_relation(rel_id, source_id, target_id, rel_type, props)
            relation_count += 1

        logger.info(
            "Loaded %d entities and %d relations from %s",
            entity_count,
            relation_count,
            path,
        )

    def add_news_event(self, article: dict, company_id: str) -> str:
        """Add a news article as a NewsEvent node and wire it into the graph.

        The article dict should contain at least one of the following key sets:

        * ``headline`` or ``title`` — article headline text
        * ``url`` — source URL
        * ``published_at`` — ISO date string (``"YYYY-MM-DD"``)
        * ``source`` — name of the news outlet
        * ``sentiment`` — ``"Positive"``, ``"Negative"``, or ``"Neutral"``
        * ``pillar`` — ESG pillar letter (``"E"``, ``"S"``, ``"G"``) or full name
        * ``content`` — article body text (optional)

        A ``mentions`` edge is created from the NewsEvent to *company_id*.

        If the article ``sentiment`` is ``"Negative"`` and the company has
        existing **Claim** nodes sharing the same ``pillar``, a
        ``contradicted_by`` edge is created from each matching Claim to this
        NewsEvent.

        Args:
            article: Dict containing the article metadata (see above).
            company_id: ID of the Company node the article is about.

        Returns:
            The ``node_id`` of the newly created NewsEvent node.
        """
        node_id: str = self._next_news_id()
        headline: str = article.get("headline") or article.get("title") or ""
        sentiment: str = article.get("sentiment", "Neutral")
        pillar: str = article.get("pillar", "")

        properties: dict = {
            "headline": headline,
            "url": article.get("url", ""),
            "published_at": article.get("published_at", self._now_iso()),
            "source": article.get("source", ""),
            "sentiment": sentiment,
            "pillar": pillar,
            "content": article.get("content", ""),
        }

        self._kg.add_node(node_id, "NewsEvent", properties)
        logger.debug("Added NewsEvent node %s: %s", node_id, headline[:60])

        # Link the news event to the company it mentions
        self._kg.add_relation(
            rel_id=self._next_rel_id("REL_NEWS"),
            source_id=node_id,
            target_id=company_id,
            rel_type="mentions",
            properties={
                "extracted_at": self._now_iso(),
                "confidence_score": 1.0,
                "extraction_method": "Rule-based",
            },
        )

        # If negative, add contradicted_by edges from matching Claims
        if sentiment == "Negative" and pillar:
            claim_nodes = self._kg.get_nodes_by_type("Claim")
            for claim in claim_nodes:
                claim_props = claim.get("properties", {})
                claim_pillar: str = claim_props.get("pillar", "")
                # Match on first character so "E" matches "Environmental", etc.
                if claim_pillar and claim_pillar[0].upper() == pillar[0].upper():
                    # Verify the claim belongs to this company via a path check
                    # (simple heuristic: check if company_id can reach this claim)
                    if self._claim_belongs_to_company(claim["node_id"], company_id):
                        self._kg.add_relation(
                            rel_id=self._next_rel_id("REL_CONTRA"),
                            source_id=claim["node_id"],
                            target_id=node_id,
                            rel_type="contradicted_by",
                            properties={
                                "extracted_at": self._now_iso(),
                                "confidence_score": 0.75,
                                "extraction_method": "Rule-based",
                                "auto_generated": True,
                            },
                        )
                        logger.debug(
                            "Created contradicted_by: %s -> %s",
                            claim["node_id"],
                            node_id,
                        )

        return node_id

    def _claim_belongs_to_company(self, claim_id: str, company_id: str) -> bool:
        """Return True if *claim_id* is reachable from *company_id* within 4 hops.

        Uses a simple BFS over outgoing edges; no edge-type filtering so that
        indirect linkage (company -> report -> claim) is captured.
        """
        from collections import deque

        visited: set[str] = {company_id}
        queue: deque[tuple[str, int]] = deque([(company_id, 0)])

        while queue:
            current, depth = queue.popleft()
            if depth > 4:
                continue
            for neighbour in self._kg.get_neighbors(current, direction="out"):
                nid = neighbour["node_id"]
                if nid == claim_id:
                    return True
                if nid not in visited:
                    visited.add(nid)
                    queue.append((nid, depth + 1))
        return False

    def add_regulation(self, reg: dict) -> str:
        """Add a single regulation node from a plain dict.

        The dict must contain at least ``id`` and ``name``; all other keys are
        stored as properties.

        Args:
            reg: Regulation data dict.  Required key: ``id``.

        Returns:
            The ``node_id`` of the regulation node.

        Raises:
            ValueError: If the dict has no ``id`` key.
        """
        reg_id: str = reg.get("id", "")
        if not reg_id:
            raise ValueError("Regulation dict must have a non-empty 'id' key.")

        properties: dict = {k: v for k, v in reg.items() if k != "id"}
        self._kg.add_node(reg_id, "Regulation", properties)
        logger.debug("Added Regulation node: %s", reg_id)
        return reg_id

    def add_mandatory_regulation_nodes(self) -> None:
        """Ensure the three canonical Vietnamese ESG regulation nodes exist.

        The nodes added are:

        * ``REG_TT96_2020`` — Thông tư 96/2020/TT-BTC (basic sustainability disclosure)
        * ``REG_TT08_2026`` — Thông tư 08/2026/TT-BTC (comprehensive ESG, effective 2026-02-03)
        * ``REG_GREEN_TAXONOMY_2025`` — QĐ 21/2025/QĐ-TTg (Vietnam Green Taxonomy)

        An ``amended_by`` edge from TT96 to TT08 is also created to reflect the
        regulatory succession.
        """
        regulations: list[dict] = [
            {
                "id": "REG_TT96_2020",
                "name": "Thông tư 96/2020/TT-BTC",
                "issuer": "Bộ Tài chính Việt Nam",
                "effective_date": "2021-01-01",
                "amended_by": "REG_TT08_2026",
                "scope": "Công ty đại chúng và công ty niêm yết HOSE, HNX",
                "is_mandatory": True,
                "required_categories": [
                    "Emissions",
                    "Energy",
                    "Employment",
                    "Board_Governance",
                ],
            },
            {
                "id": "REG_TT08_2026",
                "name": "Thông tư 08/2026/TT-BTC",
                "issuer": "Bộ Tài chính Việt Nam",
                "effective_date": "2026-02-03",
                "scope": (
                    "Sửa đổi bổ sung TT96/2020 — align ISSB và GRI, "
                    "ESG chuyển sang bắt buộc"
                ),
                "is_mandatory": True,
                "required_categories": [
                    "Emissions",
                    "Energy",
                    "Water",
                    "Waste",
                    "Employment",
                    "Health_Safety",
                    "Board_Governance",
                    "Anti_corruption",
                    "Transparency",
                ],
            },
            {
                "id": "REG_GREEN_TAXONOMY_2025",
                "name": "Quyết định 21/2025/QĐ-TTg (Vietnam Green Taxonomy)",
                "issuer": "Thủ tướng Chính phủ",
                "effective_date": "2025-01-01",
                "scope": "Phân loại dự án đầu tư xanh giai đoạn 2025-2030",
                "is_mandatory": False,
            },
        ]

        for reg in regulations:
            self.add_regulation(reg)

        # TT96 -> TT08 succession edge (only if both nodes exist)
        if (
            self._kg.get_node("REG_TT96_2020") is not None
            and self._kg.get_node("REG_TT08_2026") is not None
        ):
            self._kg.add_relation(
                rel_id=self._next_rel_id("REL_REG"),
                source_id="REG_TT96_2020",
                target_id="REG_TT08_2026",
                rel_type="amended_by",
                properties={
                    "extracted_at": self._now_iso(),
                    "confidence_score": 1.0,
                    "extraction_method": "Manual",
                },
            )
            logger.debug("Created amended_by edge: REG_TT96_2020 -> REG_TT08_2026")

        logger.info("Mandatory regulation nodes ensured in the knowledge graph.")

    # ------------------------------------------------------------------
    # Accessor
    # ------------------------------------------------------------------

    def get_kg(self) -> KnowledgeGraph:
        """Return the underlying :class:`KnowledgeGraph` instance."""
        return self._kg
