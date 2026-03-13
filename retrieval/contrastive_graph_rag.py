"""
retrieval/contrastive_graph_rag.py

Core novel contribution: adversarial contrastive subgraph retrieval for
ESG greenwashing detection.

For each ESG claim this module retrieves two opposing subgraphs:
  - Pro-claim subgraph : paths that support the claim
  - Anti-claim subgraph: paths that contradict the claim

This dual retrieval enables structured evidence adjudication, which is
impossible with flat similarity-based RAG.
"""

from __future__ import annotations

import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Local imports – paths relative to the `code/` root on PYTHONPATH
# ---------------------------------------------------------------------------
from kg.graph_store import KnowledgeGraph
from config import Config
from retrieval.path_scorer import PathScorer


# ---------------------------------------------------------------------------
# Edge-type routing tables (aligned with ontology_schema.json v2.0)
# ---------------------------------------------------------------------------

# Edges that indicate evidence IN FAVOUR of an ESG claim
_PRO_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "supported_by",       # Claim -> DataPoint
        "has_emission",       # Company -> Metric
        "complies_with",      # Company -> Regulation
        "targets_reduction",  # Company -> Target
        "invests_in",         # Company -> Project
    }
)

# Edges that indicate evidence AGAINST an ESG claim
_ANTI_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "contradicted_by",  # Claim -> NewsEvent
        "violates",         # Company -> Regulation
    }
)

# Source-reliability weights (used by PathScorer and format helpers)
_SOURCE_RELIABILITY: dict[str, float] = {
    "Report": 1.00,
    "DataPoint": 0.95,
    "Metric": 0.95,
    "NewsEvent": 0.85,
    "Target": 0.90,
    "Project": 0.90,
    "Regulation": 1.00,
    "Company": 0.90,
    "Claim": 0.80,
    "AuditResult": 1.00,
}


class ContrastiveGraphRAG:
    """
    Adversarial contrastive subgraph retrieval for greenwashing detection.

    For each ESG claim, retrieves:
    - Pro-claim subgraph: paths supporting the claim
    - Anti-claim subgraph: paths contradicting the claim

    This dual retrieval enables structured evidence adjudication, which is
    impossible with flat similarity-based RAG.

    Parameters
    ----------
    kg : KnowledgeGraph
        In-memory knowledge graph instance.
    config : Config, optional
        System configuration. Defaults are used when None.
    """

    def __init__(self, kg: KnowledgeGraph, config: Config | None = None) -> None:
        self.kg = kg
        self.config = config or Config()
        self.scorer = PathScorer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve_pro_paths(
        self,
        claim_id: str,
        max_depth: int = 3,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Retrieve paths from the KG that support *claim_id*.

        Traversal strategy
        ------------------
        1. Start at the Claim node.
        2. Follow outgoing edges whose type is in ``_PRO_EDGE_TYPES``
           (supported_by, has_emission, complies_with, targets_reduction,
           invests_in).
        3. Also pivot via ``claims_reduction``: find the Company that owns
           this Claim, then expand its pro-edges.
        4. BFS / DFS up to *max_depth* hops.

        Returns
        -------
        list[dict]
            Up to *top_k* path dicts, each with keys:
            ``path`` (alternating node/edge list), ``score`` (float),
            ``path_type`` ("pro").
        """
        raw_paths: list[list[dict[str, Any]]] = []

        claim_node = self._get_node(claim_id)
        if claim_node is None:
            return []

        # 1. Direct pro-paths from Claim node
        self._dfs_paths(
            start_node=claim_node,
            allowed_edge_types=_PRO_EDGE_TYPES,
            max_depth=max_depth,
            current_path=[claim_node],
            visited={claim_id},
            results=raw_paths,
        )

        # 2. Company-pivot: find Company -[claims_reduction]-> Claim
        company_nodes = self._find_nodes_by_reverse_edge(
            target_node_id=claim_id,
            edge_type="claims_reduction",
        )
        for company_node in company_nodes:
            pivot_path = [company_node, {"type": "claims_reduction"}, claim_node]
            self._dfs_paths(
                start_node=company_node,
                allowed_edge_types=_PRO_EDGE_TYPES,
                max_depth=max_depth,
                current_path=[company_node],
                visited={company_node.get("node_id") or company_node.get("id", ""), claim_id},
                results=raw_paths,
                base_prefix=pivot_path,
            )

        claim_year = (claim_node.get("properties") or {}).get("year") or claim_node.get("year")
        scored = self._score_and_label(raw_paths, direction="pro", claim_year=claim_year)
        return sorted(scored, key=lambda p: p["score"], reverse=True)[:top_k]

    def retrieve_anti_paths(
        self,
        claim_id: str,
        max_depth: int = 3,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Retrieve paths from the KG that contradict *claim_id*.

        Traversal strategy
        ------------------
        1. Start at the Claim node.
        2. Follow outgoing edges whose type is in ``_ANTI_EDGE_TYPES``
           (contradicted_by, violates).
        3. Pivot via ``claims_reduction``: find the parent Company, then
           expand its ``violates`` edges and ``subsidiary_of`` chains.

        Returns
        -------
        list[dict]
            Up to *top_k* path dicts, each with keys:
            ``path`` (alternating node/edge list), ``score`` (float),
            ``path_type`` ("anti").
        """
        raw_paths: list[list[dict[str, Any]]] = []

        claim_node = self._get_node(claim_id)
        if claim_node is None:
            return []

        # 1. Direct anti-paths from Claim node
        self._dfs_paths(
            start_node=claim_node,
            allowed_edge_types=_ANTI_EDGE_TYPES,
            max_depth=max_depth,
            current_path=[claim_node],
            visited={claim_id},
            results=raw_paths,
        )

        # 2. Company-pivot: violations and subsidiary chains
        company_nodes = self._find_nodes_by_reverse_edge(
            target_node_id=claim_id,
            edge_type="claims_reduction",
        )
        anti_company_edges = frozenset({"violates", "subsidiary_of"})
        for company_node in company_nodes:
            pivot_path = [company_node, {"type": "claims_reduction"}, claim_node]
            self._dfs_paths(
                start_node=company_node,
                allowed_edge_types=anti_company_edges,
                max_depth=max_depth,
                current_path=[company_node],
                visited={company_node.get("node_id") or company_node.get("id", ""), claim_id},
                results=raw_paths,
                base_prefix=pivot_path,
            )

        claim_year = claim_node.get("year")
        scored = self._score_and_label(raw_paths, direction="anti", claim_year=claim_year)
        return sorted(scored, key=lambda p: p["score"], reverse=True)[:top_k]

    def retrieve_contrastive_context(self, claim_id: str) -> dict[str, Any]:
        """
        Retrieve the full contrastive context for a single claim.

        Returns
        -------
        dict with keys:
            - ``claim``        : the Claim node dict
            - ``pro_paths``    : list of pro path dicts
            - ``anti_paths``   : list of anti path dicts
            - ``pro_count``    : int
            - ``anti_count``   : int
            - ``balance_score``: float in [0, 1], proportion of pro evidence
        """
        claim_node = self._get_node(claim_id)
        if claim_node is None:
            return {
                "claim": {},
                "pro_paths": [],
                "anti_paths": [],
                "pro_count": 0,
                "anti_count": 0,
                "balance_score": 0.0,
            }

        pro_paths = self.retrieve_pro_paths(claim_id)
        anti_paths = self.retrieve_anti_paths(claim_id)

        total = len(pro_paths) + len(anti_paths)
        balance_score = len(pro_paths) / max(total, 1)

        return {
            "claim": claim_node,
            "pro_paths": pro_paths,
            "anti_paths": anti_paths,
            "pro_count": len(pro_paths),
            "anti_count": len(anti_paths),
            "balance_score": balance_score,
        }

    def score_path(self, path: list[dict[str, Any]], direction: str) -> float:
        """
        Score a single path.

        Scoring formula
        ---------------
        score = avg_confidence × recency_factor × source_reliability

        - ``avg_confidence``    : mean confidence_score across all edges in path
        - ``recency_factor``    : 1.0 for news within 2 years of the claim;
                                  0.7 otherwise
        - ``source_reliability``: reliability weight of terminal node's type

        Parameters
        ----------
        path : list[dict]
            Alternating list of node dicts and edge dicts.
        direction : str
            "pro" or "anti" (reserved for future asymmetric weighting).

        Returns
        -------
        float
            Composite score in [0, 1].
        """
        if not path:
            return 0.0

        edges = self._extract_edges(path)
        nodes = self._extract_nodes(path)

        # Determine claim year from the first node in the path if it's a Claim
        claim_year: int | None = None
        first_node = path[0] if path else {}
        if first_node.get("node_type") == "Claim" or first_node.get("type") == "Claim":
            claim_year = first_node.get("year")

        avg_confidence = self.scorer.score_by_confidence(edges)
        recency = self.scorer.score_by_recency(nodes, claim_year)
        reliability = self.scorer.score_by_source_reliability(nodes)

        return round(avg_confidence * recency * reliability, 4)

    def format_paths_for_llm(self, paths: list[dict[str, Any]]) -> str:
        """
        Format a list of path dicts into human-readable text for LLM context.

        Each path is rendered as a chain of nodes and edge labels, e.g.::

            [Claim: CLM_E_001 | "50% plastic reduction by 2025"]
            --[supported_by]-->
            [DataPoint: DP_E_001 | value=870 tấn (2023)]
            (score=0.87)

        Parameters
        ----------
        paths : list[dict]
            Scored path dicts as returned by ``retrieve_pro_paths`` /
            ``retrieve_anti_paths``.

        Returns
        -------
        str
            Multi-line formatted string ready for LLM prompting.
        """
        if not paths:
            return "(no paths found)"

        lines: list[str] = []
        for idx, path_dict in enumerate(paths, start=1):
            raw_path: list[dict[str, Any]] = path_dict.get("path", [])
            score: float = path_dict.get("score", 0.0)
            path_type: str = path_dict.get("path_type", "unknown")

            lines.append(f"Path {idx} [{path_type.upper()} | score={score:.3f}]:")
            chain_parts: list[str] = []

            for element in raw_path:
                if _is_node(element):
                    chain_parts.append(_format_node(element))
                else:
                    edge_label = element.get("type") or element.get("edge_type", "?")
                    chain_parts.append(f"--[{edge_label}]-->")

            lines.append("  " + " ".join(chain_parts))
            lines.append("")  # blank separator

        return "\n".join(lines).rstrip()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_node(self, node_id: str) -> dict[str, Any] | None:
        """Retrieve a node by ID from the KG; return None if absent."""
        try:
            return self.kg.get_node(node_id)
        except Exception:
            return None

    def _find_nodes_by_reverse_edge(
        self, target_node_id: str, edge_type: str
    ) -> list[dict[str, Any]]:
        """
        Find all nodes that have an outgoing edge of *edge_type* pointing to
        *target_node_id*.  Returns [] if the KG does not support reverse lookup.
        """
        try:
            return self.kg.get_predecessors(target_node_id, edge_type=edge_type)
        except AttributeError:
            # Fallback: scan all edges (slower but safe)
            results: list[dict[str, Any]] = []
            try:
                for edge in self.kg.get_all_edges():
                    if (
                        edge.get("type") == edge_type
                        and edge.get("target") == target_node_id
                    ):
                        src_node = self._get_node(edge.get("source", ""))
                        if src_node is not None:
                            results.append(src_node)
            except Exception:
                pass
            return results
        except Exception:
            return []

    def _get_neighbors(
        self,
        node: dict[str, Any],
        allowed_edge_types: frozenset[str],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """
        Return (neighbor_node, edge) pairs reachable from *node* via edges
        whose type is in *allowed_edge_types*.
        """
        node_id = node.get("node_id") or node.get("id", "")
        results: list[tuple[dict[str, Any], dict[str, Any]]] = []
        try:
            edges = self.kg.get_edges(node_id)
        except Exception:
            return results

        for edge in edges:
            edge_type = edge.get("type") or edge.get("edge_type", "")
            if edge_type not in allowed_edge_types:
                continue
            neighbor_id = edge.get("target") or edge.get("to", "")
            if not neighbor_id:
                continue
            neighbor_node = self._get_node(neighbor_id)
            if neighbor_node is not None:
                results.append((neighbor_node, edge))

        return results

    def _dfs_paths(
        self,
        start_node: dict[str, Any],
        allowed_edge_types: frozenset[str],
        max_depth: int,
        current_path: list[Any],
        visited: set[str],
        results: list[list[Any]],
        base_prefix: list[Any] | None = None,
    ) -> None:
        """
        Depth-first search that collects all paths up to *max_depth* hops.

        Each completed path (length >= 3, i.e. at least one edge traversal)
        is appended to *results*.  Paths include interleaved node and edge
        dicts: [node, edge, node, edge, node, ...].

        Parameters
        ----------
        base_prefix : list | None
            If provided, prepend this list to every collected path.  Used
            when pivoting through a Company node before following edges.
        """
        # A path is "complete" once it has at least one edge traversed
        if len(current_path) >= 3:
            full_path = (base_prefix or []) + current_path
            results.append(full_path)

        if len(current_path) >= (max_depth * 2 + 1):
            return

        neighbors = self._get_neighbors(start_node, allowed_edge_types)
        for neighbor_node, edge in neighbors:
            neighbor_id = neighbor_node.get("node_id") or neighbor_node.get("id", "")
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)
            current_path.append(edge)
            current_path.append(neighbor_node)
            self._dfs_paths(
                start_node=neighbor_node,
                allowed_edge_types=allowed_edge_types,
                max_depth=max_depth,
                current_path=current_path,
                visited=visited,
                results=results,
                base_prefix=base_prefix,
            )
            current_path.pop()
            current_path.pop()
            visited.discard(neighbor_id)

    def _score_and_label(
        self,
        raw_paths: list[list[Any]],
        direction: str,
        claim_year: int | None,
    ) -> list[dict[str, Any]]:
        """Convert raw path lists into scored, labelled path dicts."""
        scored: list[dict[str, Any]] = []
        for raw_path in raw_paths:
            score = self.scorer.composite_score(raw_path, claim_year=claim_year)
            scored.append(
                {
                    "path": raw_path,
                    "score": score,
                    "path_type": direction,
                }
            )
        return scored

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_edges(path: list[Any]) -> list[dict[str, Any]]:
        """Extract edge dicts from an interleaved path list."""
        return [element for element in path if not _is_node(element)]

    @staticmethod
    def _extract_nodes(path: list[Any]) -> list[dict[str, Any]]:
        """Extract node dicts from an interleaved path list."""
        return [element for element in path if _is_node(element)]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _is_node(element: dict[str, Any]) -> bool:
    """
    Heuristic: an element is a node (not an edge) when it has an ``id``
    field and its ``type`` / ``node_type`` value is a known entity type.
    """
    if not isinstance(element, dict):
        return False
    # An edge typically only has type + source + target + properties
    # A node always has an "id" field
    return "id" in element


def _format_node(node: dict[str, Any]) -> str:
    """
    Produce a compact string representation of a KG node for LLM context.

    Includes the node type, ID, and the most informative available property.
    """
    node_type = node.get("node_type") or node.get("type", "Node")
    node_id = node.get("node_id") or node.get("id", "?")
    parts = [f"[{node_type}: {node_id}"]

    # Properties may be nested under "properties" key (KnowledgeGraph format)
    props = node.get("properties") or node
    # Pick the most informative text property for context
    for key in ("text", "headline", "name", "description", "title"):
        val = props.get(key)
        if val:
            truncated = str(val)[:80]
            parts.append(f' | "{truncated}"')
            break

    # Numeric value properties
    for key in ("value", "unit", "year", "sentiment", "pillar"):
        val = node.get(key)
        if val is not None:
            parts.append(f" | {key}={val}")

    parts.append("]")
    return "".join(parts)
