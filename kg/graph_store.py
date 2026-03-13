"""
kg/graph_store.py
In-memory knowledge-graph store backed by ``networkx.MultiDiGraph``.

The graph is node-typed and edge-typed.  Every node stores its ``node_type``
and an arbitrary ``properties`` dict.  Every edge stores its ``rel_type`` and
an arbitrary ``properties`` dict, plus the auto-generated ``rel_id``.

Typical usage::

    from kg.graph_store import KnowledgeGraph

    kg = KnowledgeGraph()
    kg.add_node("COMP_FPT", "Company", {"name": "FPT Corporation"})
    kg.add_node("METRIC_CO2", "Metric", {"value": 1250, "unit": "tonne CO2e"})
    kg.add_relation("REL_001", "COMP_FPT", "METRIC_CO2", "has_emission", {})
    print(kg.stats())
"""

from __future__ import annotations

from collections import deque
from typing import Any

import networkx as nx


class KnowledgeGraph:
    """In-memory, multi-edge directed knowledge graph.

    Nodes are identified by a unique string ``node_id``.  Parallel edges
    between the same pair of nodes are allowed (``MultiDiGraph``), which is
    useful when a company both *complies_with* and *violates* different
    aspects of the same regulation.
    """

    def __init__(self) -> None:
        """Initialise an empty graph."""
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def add_node(self, node_id: str, node_type: str, properties: dict) -> None:
        """Add or update a node.

        If a node with *node_id* already exists its attributes are merged
        (existing keys are preserved; new keys are added).

        Args:
            node_id:    Unique identifier for the node (e.g. ``"COMP_FPT"``).
            node_type:  Ontology type label (e.g. ``"Company"``, ``"Metric"``).
            properties: Arbitrary key-value payload.
        """
        if self._graph.has_node(node_id):
            # Merge — do not overwrite existing data with empty values
            existing: dict = self._graph.nodes[node_id]
            merged_props = {**existing.get("properties", {}), **properties}
            self._graph.nodes[node_id]["properties"] = merged_props
            self._graph.nodes[node_id]["node_type"] = node_type
        else:
            self._graph.add_node(
                node_id,
                node_type=node_type,
                properties=dict(properties),
            )

    def add_relation(
        self,
        rel_id: str,
        source_id: str,
        target_id: str,
        rel_type: str,
        properties: dict,
    ) -> None:
        """Add a directed, typed edge between two nodes.

        Source and target nodes are created as stubs if they do not yet exist
        (``node_type="Unknown"``, empty properties).

        Args:
            rel_id:    Unique identifier for the relation (e.g. ``"REL_001"``).
            source_id: ID of the source node.
            target_id: ID of the target node.
            rel_type:  Ontology relation label (e.g. ``"has_emission"``).
            properties: Arbitrary key-value payload (confidence_score, etc.).
        """
        # Auto-create stub nodes so the graph stays consistent
        for nid in (source_id, target_id):
            if not self._graph.has_node(nid):
                self._graph.add_node(nid, node_type="Unknown", properties={})

        self._graph.add_edge(
            source_id,
            target_id,
            rel_id=rel_id,
            rel_type=rel_type,
            properties=dict(properties),
        )

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> dict | None:
        """Return node data dict or ``None`` if the node does not exist.

        Returns:
            A dict with keys ``node_id``, ``node_type``, ``properties``, or
            ``None`` when the node is absent.
        """
        if not self._graph.has_node(node_id):
            return None
        data = self._graph.nodes[node_id]
        return {
            "node_id": node_id,
            "node_type": data.get("node_type", "Unknown"),
            "properties": dict(data.get("properties", {})),
        }

    def get_neighbors(
        self,
        node_id: str,
        direction: str = "out",
        edge_types: list[str] | None = None,
    ) -> list[dict]:
        """Return adjacent nodes with edge metadata.

        Args:
            node_id:    The node whose neighbours are requested.
            direction:  ``"out"`` (successors), ``"in"`` (predecessors), or
                        ``"both"``.
            edge_types: Optional whitelist of ``rel_type`` values.  Pass
                        ``None`` to include all edge types.

        Returns:
            A list of dicts, each with keys:
            ``node_id``, ``node_type``, ``edge_type``, ``edge_props``,
            ``properties``.
        """
        if not self._graph.has_node(node_id):
            return []

        results: list[dict] = []

        def _collect(src: str, dst: str, edge_data: dict) -> None:
            rel_type: str = edge_data.get("rel_type", "")
            if edge_types is not None and rel_type not in edge_types:
                return
            neighbour_id = dst if src == node_id else src
            neighbour_data = self._graph.nodes.get(neighbour_id, {})
            results.append(
                {
                    "node_id": neighbour_id,
                    "node_type": neighbour_data.get("node_type", "Unknown"),
                    "edge_type": rel_type,
                    "edge_props": dict(edge_data.get("properties", {})),
                    "properties": dict(neighbour_data.get("properties", {})),
                }
            )

        if direction in ("out", "both"):
            for _, dst, edata in self._graph.out_edges(node_id, data=True):
                _collect(node_id, dst, edata)

        if direction in ("in", "both"):
            for src, _, edata in self._graph.in_edges(node_id, data=True):
                _collect(src, node_id, edata)

        return results

    def get_all_paths(
        self,
        source_id: str,
        edge_types: list[str],
        max_depth: int = 3,
    ) -> list[list[dict]]:
        """BFS traversal returning all simple paths up to *max_depth* hops.

        Only edges whose ``rel_type`` appears in *edge_types* are traversed.

        Args:
            source_id:  Starting node ID.
            edge_types: Allowed edge types for traversal.
            max_depth:  Maximum number of hops from the source.

        Returns:
            A list of paths; each path is a list of node-data dicts ordered
            from source to leaf (inclusive of the source).
        """
        if not self._graph.has_node(source_id):
            return []

        paths: list[list[dict]] = []

        # BFS queue: (current_node_id, path_so_far_as_list_of_dicts, visited_set)
        start_node_data = self.get_node(source_id) or {
            "node_id": source_id,
            "node_type": "Unknown",
            "properties": {},
        }
        queue: deque[tuple[str, list[dict], set[str]]] = deque(
            [(source_id, [start_node_data], {source_id})]
        )

        while queue:
            current_id, current_path, visited = queue.popleft()

            # Record this path (even partial ones ≥ 1 node are useful as
            # sub-paths; only record if it extends beyond the source)
            if len(current_path) > 1:
                paths.append(list(current_path))

            if len(current_path) - 1 >= max_depth:
                continue

            for _, dst, edata in self._graph.out_edges(current_id, data=True):
                rel_type: str = edata.get("rel_type", "")
                if rel_type not in edge_types:
                    continue
                if dst in visited:
                    continue
                dst_data = self.get_node(dst) or {
                    "node_id": dst,
                    "node_type": "Unknown",
                    "properties": {},
                }
                queue.append(
                    (dst, current_path + [dst_data], visited | {dst})
                )

        return paths

    def get_nodes_by_type(self, node_type: str) -> list[dict]:
        """Return all nodes whose ``node_type`` matches *node_type*.

        Args:
            node_type: The ontology type to filter by (e.g. ``"Company"``).

        Returns:
            List of node-data dicts (``node_id``, ``node_type``, ``properties``).
        """
        return [
            {
                "node_id": nid,
                "node_type": data.get("node_type", "Unknown"),
                "properties": dict(data.get("properties", {})),
            }
            for nid, data in self._graph.nodes(data=True)
            if data.get("node_type") == node_type
        ]

    def get_relations_by_type(self, rel_type: str) -> list[dict]:
        """Return all edges whose ``rel_type`` matches *rel_type*.

        Returns:
            List of dicts with keys ``rel_id``, ``rel_type``, ``source_id``,
            ``target_id``, ``properties``.
        """
        results: list[dict] = []
        for src, dst, edata in self._graph.edges(data=True):
            if edata.get("rel_type") == rel_type:
                results.append(
                    {
                        "rel_id": edata.get("rel_id", ""),
                        "rel_type": rel_type,
                        "source_id": src,
                        "target_id": dst,
                        "properties": dict(edata.get("properties", {})),
                    }
                )
        return results

    def get_company_subgraph(self, company_id: str) -> dict:
        """Return all nodes and edges within 3 hops of *company_id*.

        The subgraph is computed by BFS over all edge types in both directions,
        limited to ``MAX_HOPS = 3``.

        Returns:
            A dict with keys ``nodes`` (list of node dicts) and
            ``edges`` (list of edge dicts).
        """
        MAX_HOPS = 3
        if not self._graph.has_node(company_id):
            return {"nodes": [], "edges": []}

        visited_nodes: set[str] = set()
        visited_edges: set[tuple[str, str, str]] = set()  # (src, dst, rel_id)

        queue: deque[tuple[str, int]] = deque([(company_id, 0)])
        visited_nodes.add(company_id)

        while queue:
            current_id, depth = queue.popleft()
            if depth >= MAX_HOPS:
                continue

            # Outgoing edges
            for src, dst, edata in self._graph.out_edges(current_id, data=True):
                edge_key = (src, dst, edata.get("rel_id", ""))
                if edge_key not in visited_edges:
                    visited_edges.add(edge_key)
                if dst not in visited_nodes:
                    visited_nodes.add(dst)
                    queue.append((dst, depth + 1))

            # Incoming edges
            for src, dst, edata in self._graph.in_edges(current_id, data=True):
                edge_key = (src, dst, edata.get("rel_id", ""))
                if edge_key not in visited_edges:
                    visited_edges.add(edge_key)
                if src not in visited_nodes:
                    visited_nodes.add(src)
                    queue.append((src, depth + 1))

        nodes = [
            {
                "node_id": nid,
                "node_type": self._graph.nodes[nid].get("node_type", "Unknown"),
                "properties": dict(self._graph.nodes[nid].get("properties", {})),
            }
            for nid in visited_nodes
            if self._graph.has_node(nid)
        ]

        edges = [
            {
                "rel_id": edata.get("rel_id", ""),
                "rel_type": edata.get("rel_type", ""),
                "source_id": src,
                "target_id": dst,
                "properties": dict(edata.get("properties", {})),
            }
            for src, dst, edata in self._graph.edges(data=True)
            if (src, dst, edata.get("rel_id", "")) in visited_edges
        ]

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Aggregate / metadata
    # ------------------------------------------------------------------

    def node_count(self) -> int:
        """Return the total number of nodes in the graph."""
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        """Return the total number of edges (relations) in the graph."""
        return self._graph.number_of_edges()

    def to_dict(self) -> dict[str, Any]:
        """Serialise the entire graph to a JSON-compatible dict.

        Returns:
            A dict with keys ``nodes`` and ``edges``, each containing a list
            of serialisable dicts.
        """
        nodes = [
            {
                "node_id": nid,
                "node_type": data.get("node_type", "Unknown"),
                "properties": dict(data.get("properties", {})),
            }
            for nid, data in self._graph.nodes(data=True)
        ]
        edges = [
            {
                "rel_id": edata.get("rel_id", ""),
                "rel_type": edata.get("rel_type", ""),
                "source_id": src,
                "target_id": dst,
                "properties": dict(edata.get("properties", {})),
            }
            for src, dst, edata in self._graph.edges(data=True)
        ]
        return {"nodes": nodes, "edges": edges}

    def stats(self) -> dict[str, Any]:
        """Return node and edge counts broken down by type.

        Returns:
            A dict with keys ``total_nodes``, ``total_edges``,
            ``nodes_by_type`` (dict), ``edges_by_type`` (dict).
        """
        nodes_by_type: dict[str, int] = {}
        for _, data in self._graph.nodes(data=True):
            nt = data.get("node_type", "Unknown")
            nodes_by_type[nt] = nodes_by_type.get(nt, 0) + 1

        edges_by_type: dict[str, int] = {}
        for _, _, edata in self._graph.edges(data=True):
            et = edata.get("rel_type", "Unknown")
            edges_by_type[et] = edges_by_type.get(et, 0) + 1

        return {
            "total_nodes": self._graph.number_of_nodes(),
            "total_edges": self._graph.number_of_edges(),
            "nodes_by_type": nodes_by_type,
            "edges_by_type": edges_by_type,
        }

    # ------------------------------------------------------------------
    # Compatibility helpers for retrieval layer
    # ------------------------------------------------------------------

    def get_edges(self, node_id: str) -> list[dict[str, Any]]:
        """
        Return all outgoing edges from *node_id* as dicts with keys:
        ``type``, ``target``, ``source``, ``properties``, ``rel_id``.

        This is a convenience alias used by ContrastiveGraphRAG.
        """
        edges: list[dict[str, Any]] = []
        if node_id not in self._graph:
            return edges
        for _, dst, edata in self._graph.out_edges(node_id, data=True):
            edges.append({
                "type": edata.get("rel_type", ""),
                "edge_type": edata.get("rel_type", ""),
                "source": node_id,
                "target": dst,
                "rel_id": edata.get("rel_id", ""),
                "properties": dict(edata.get("properties", {})),
            })
        return edges

    def get_predecessors(self, node_id: str, edge_type: str | None = None) -> list[dict[str, Any]]:
        """
        Return all nodes that have an outgoing edge pointing to *node_id*,
        optionally filtered by *edge_type*.

        Returns a list of node dicts (same format as ``get_node``).
        """
        results: list[dict[str, Any]] = []
        if node_id not in self._graph:
            return results
        for src, _, edata in self._graph.in_edges(node_id, data=True):
            if edge_type is not None and edata.get("rel_type") != edge_type:
                continue
            node = self.get_node(src)
            if node is not None:
                results.append(node)
        return results

    def get_all_edges(self) -> list[dict[str, Any]]:
        """
        Return every edge in the graph as a flat list of dicts.

        Each dict has keys: ``type``, ``source``, ``target``, ``rel_id``, ``properties``.
        """
        return [
            {
                "type": edata.get("rel_type", ""),
                "source": src,
                "target": dst,
                "rel_id": edata.get("rel_id", ""),
                "properties": dict(edata.get("properties", {})),
            }
            for src, dst, edata in self._graph.edges(data=True)
        ]

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"KnowledgeGraph("
            f"nodes={self._graph.number_of_nodes()}, "
            f"edges={self._graph.number_of_edges()})"
        )
