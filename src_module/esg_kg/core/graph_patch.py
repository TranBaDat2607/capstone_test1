"""graph_patch — append-only patching of the RESOLVED graph, shared by the 05x stages.

Extracted verbatim from ``src/step05c_link_standard_indicators.py`` (TODAY :76,
``temporal_md`` :102, ``norm`` :109, ``GraphPatch`` :114). It lives in ``core/``
rather than in that one stage because it is not step05c's private concern:
``src/step05d_align_claims_to_indicators.py:34`` already imports ``GraphPatch`` and
``temporal_md`` FROM the stage, which is exactly the "a step file doubles as a utility
library" knot DESIGN.md §1 says ``core/`` exists to untie. With this module in place
the migrated 05d imports from the kernel instead of from a sibling stage.

WHAT THE INVARIANT IS FOR
``step06`` keys Neo4j on the node's ARRAY INDEX (``_node_key = "n{i}"``) and the
step07 dossiers reference nodes by position, so any stage that patches an
already-resolved graph may only append past the original length and mutate an
existing node's ``properties`` in place. ``assert_append_only()`` proves that by
snapshotting ``id()`` of every node/edge in the prefix — which permits the in-place
property writes the stages legitimately make (``self_reported_zero`` on a Penalty, a
corrected ``pillar``) while catching a reorder or a replacement.

The body is duplicated in ``src/step05c_link_standard_indicators.py`` while the
refactor is in flight (Model A — the old tree must keep running and cannot import
from here). ``test/test_esg_kg_equivalence.py`` holds the two copies equal; that arm
retires when the ``src/`` twin is deleted (DESIGN.md §5.3).
"""

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from esg_kg.core.naming import normalize_name

logger = logging.getLogger(__name__)

TODAY = date.today().isoformat()


def temporal_md(props: Dict[str, Any]) -> Dict[str, Any]:
    """Edge temporal_metadata: valid_from inherited from the observation, recorded_at = run day."""
    return {"valid_from": props.get("valid_from"),
            "valid_to": props.get("valid_to"),
            "recorded_at": TODAY}


def norm(s: Any) -> str:
    return normalize_name(s)


# --------------------------------------------------------------------------- #
class GraphPatch:
    """Append-only view over the resolved graph. Tracks how many nodes/edges existed before so
    the invariant can be asserted, and dedups appended nodes by identity so re-running is a no-op."""

    def __init__(self, graph: Dict[str, Any], entity_classes, edge_labels, edge_dirs):
        self.graph = graph
        self.nodes: List[Dict[str, Any]] = graph["nodes"]
        self.edges: List[Dict[str, Any]] = graph["edges"]
        self.n_nodes0 = len(self.nodes)
        self.n_edges0 = len(self.edges)
        # Identity snapshot of the existing prefix: the object id() of each node/edge dict at
        # positions 0..n0. We only ever .append() new items and mutate existing `properties` in
        # place, so these objects must stay the SAME objects in the SAME order — that is the
        # invariant step06 (_node_key = "n{i}") and the step07 dossiers depend on. Snapshotting
        # id() lets assert_append_only() catch any accidental reorder/replace while still allowing
        # a property mutation (e.g. stamping self_reported_zero on a Penalty).
        self._prefix_node_ids = [id(n) for n in self.nodes]
        self._prefix_edge_ids = [id(e) for e in self.edges]
        self.entity_classes = entity_classes
        self.edge_labels = edge_labels
        self.edge_dirs = edge_dirs

        # index existing nodes by (class, identity-name) so we neither duplicate an indicator
        # nor a document node across runs
        self._by_id: Dict[Tuple[str, str], int] = {}
        for i, n in enumerate(self.nodes):
            self._register(i)

        # existing edges as a set of (subject, predicate, object) so we don't re-add
        self._edgeset = {(e.get("subject"), e.get("predicate"), e.get("object"))
                         for e in self.edges}
        self.dropped_invalid = 0

    def assert_append_only(self) -> None:
        """The prefix (first n0 nodes/edges) must be the same objects in the same order —
        only appends past n0 and in-place property mutation are allowed."""
        assert len(self.nodes) >= self.n_nodes0 and len(self.edges) >= self.n_edges0, \
            "step05c must not shrink the node/edge arrays"
        assert [id(n) for n in self.nodes[:self.n_nodes0]] == self._prefix_node_ids, \
            "step05c reordered or replaced an existing node — breaks _node_key/dossier positions"
        assert [id(e) for e in self.edges[:self.n_edges0]] == self._prefix_edge_ids, \
            "step05c reordered or replaced an existing edge"

    def _key(self, node: Dict[str, Any]) -> Tuple[str, str]:
        cls = node.get("class", "")
        p = node.get("properties") or {}
        ident = p.get("id") if cls == "StandardIndicator" else p.get("name")
        return (cls, norm(ident))

    def _register(self, idx: int) -> None:
        self._by_id.setdefault(self._key(self.nodes[idx]), idx)

    def find(self, cls: str, ident: str) -> Optional[int]:
        return self._by_id.get((cls, norm(ident)))

    def ensure_node(self, node: Dict[str, Any]) -> Tuple[int, bool]:
        """Return (index, created)."""
        key = self._key(node)
        if key in self._by_id:
            return self._by_id[key], False
        idx = len(self.nodes)
        self.nodes.append(node)
        self._by_id[key] = idx
        return idx, True

    def add_edge(self, s_idx: int, predicate: str, o_idx: int,
                 temporal_metadata: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> bool:
        """Append an index-based edge after checking the schema DIRECTION only.

        We do NOT reuse step03's validate_triple here: it also requires valid_from/valid_to/
        is_current on both endpoints, which is correct at the extraction stage but wrong on the
        RESOLVED graph, where step05 deliberately strips those fields off T1/T3 entity nodes
        (time lives on edges + temporal_versions, P2). The real constraint this stage must honour
        is the legal (source_class, target_class) pair — exactly the gap diagnosis C5 identified."""
        s_cls = self.nodes[s_idx].get("class")
        o_cls = self.nodes[o_idx].get("class")
        if predicate not in self.edge_labels:
            self.dropped_invalid += 1
            logger.warning(f"Dropping {predicate}: label not in schema")
            return False
        pairs = self.edge_dirs.get(predicate, [])
        if pairs and not any(s == s_cls and t == o_cls for s, t in pairs):
            self.dropped_invalid += 1
            logger.warning(f"Dropping invalid direction {s_cls} -{predicate}-> {o_cls}")
            return False
        sig = (s_idx, predicate, o_idx)
        if sig in self._edgeset:
            return False
        edge = {"subject": s_idx, "predicate": predicate, "object": o_idx,
                "temporal_metadata": temporal_metadata, "anchor_method": "offline_indicator_map"}
        if extra:
            edge.update(extra)
        self.edges.append(edge)
        self._edgeset.add(sig)
        return True
