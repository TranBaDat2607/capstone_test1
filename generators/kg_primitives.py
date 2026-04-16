"""
generators/kg_primitives.py

Shared KG building blocks: entity/relation constructors and helpers.
"""
from __future__ import annotations

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Relation ID counter
# ---------------------------------------------------------------------------
_rel_counter = 0


def _next_rel_id(prefix: str = "REL") -> str:
    global _rel_counter
    _rel_counter += 1
    return f"{prefix}_{_rel_counter:05d}"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Entity / relation builders
# ---------------------------------------------------------------------------

def make_entity(node_id: str, node_type: str, properties: dict) -> dict:
    return {"id": node_id, "type": node_type, "properties": properties}


def make_relation(
    rel_type: str,
    source_id: str,
    target_id: str,
    confidence: float = 1.0,
    method: str = "Manual",
    extra: dict | None = None,
) -> dict:
    props = {"extracted_at": _now_iso(), **(extra or {})}
    return {
        "id": _next_rel_id("REL"),
        "type": rel_type,
        "source_id": source_id,
        "target_id": target_id,
        "confidence_score": confidence,
        "extraction_method": method,
        "properties": props,
    }
