"""export — derived, read-only views of the resolved graph for downstream consumers
that are not the product's own Neo4j/UI surface (e.g. an SSRL/RL training dataset).

Nothing here ever writes to `graph_output/resolved/resolved_graph.json` or touches
Neo4j — every module reads the resolved graph read-only and produces a wholly
separate artifact under `graph_output/export_kgc/` (GRAPH_IMPROVEMENT_PLAN.md B4).
This is the same "dataset tier, not DB tier" boundary docs/TEMPORAL_KG_DESIGN.md's
P6 already established for inverse (`_inv`) edges.

    export_kgc.py   hub-cluster decomposition into an SSRL export view (B4)
"""
