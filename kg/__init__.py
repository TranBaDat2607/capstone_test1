"""
kg — Knowledge Graph package for the ESG Greenwashing Detection pipeline.

Public surface:
    KnowledgeGraph   — in-memory NetworkX-backed graph store
    GraphBuilder     — populates a KnowledgeGraph from JSON instances and news
    EntityLinker     — fuzzy-match entity deduplication helper
"""

from __future__ import annotations

from kg.graph_store import KnowledgeGraph
from kg.graph_builder import GraphBuilder
from kg.entity_linker import EntityLinker

__all__ = ["KnowledgeGraph", "GraphBuilder", "EntityLinker"]
