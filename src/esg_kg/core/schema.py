"""Schema helpers shared across pipeline stages.

Extracted verbatim from the flat src/ scripts so every stage can import them
from one stable place instead of from a sibling step file:

    load_schema_sets, validate_triple   <- src/step03_fix_invalid_triplets.py
    get_identity_keys                    <- src/step02_extract_triplet_from_jsonl.py

All three are pure functions over a parsed ``config/schema.json`` dict (or a
single triple) — no filesystem, no network, no dependency on other stages.
Behaviour is asserted equivalent to the src/ originals in test.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


def load_schema_sets(
    schema: Dict[str, Any],
) -> Tuple[Set[str], Set[str], Dict[str, List[Tuple[str, str]]]]:
    """Return (entity classes, edge labels, edge_directions).

    edge_directions: { label -> [(source_class, target_class), ...] }.
    One label may have multiple legal directed pairs (e.g. `verifiedBy` is legal
    from SustainabilityClaim to either ThirdPartyVerification or KPIObservation).
    """
    entity_classes = {node["class"] for node in schema.get("nodes", [])}
    edge_labels = {edge["label"] for edge in schema.get("edges", [])}
    edge_directions: Dict[str, List[Tuple[str, str]]] = {}
    for edge in schema.get("edges", []):
        label = edge["label"]
        from_cls = edge.get("source_class")
        to_cls = edge.get("target_class")
        edge_directions.setdefault(label, [])
        if from_cls and to_cls:
            edge_directions[label].append((from_cls, to_cls))
    logger.info(f"Loaded {len(edge_directions)} edge direction rules")
    return entity_classes, edge_labels, edge_directions


def validate_triple(
    triple: Dict[str, Any],
    entity_classes: Set[str],
    edge_labels: Set[str],
    edge_directions: Dict[str, List[Tuple[str, str]]],
) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    if not isinstance(triple, dict):
        return False, ["Not a dict"]
    if not {"subject", "predicate", "object"}.issubset(triple.keys()):
        return False, ["Missing required keys (subject/predicate/object)"]

    subj = triple.get("subject")
    if subj is None:
        errors.append("Subject is None")
    elif not isinstance(subj, dict):
        errors.append("Subject not a dict")
    elif "class" not in subj or "properties" not in subj:
        errors.append("Subject missing class or properties")
    elif subj["class"] not in entity_classes:
        errors.append(f"Invalid subject class: {subj.get('class')}")
    elif not isinstance(subj["properties"], dict):
        errors.append("Subject properties not a dict")
    else:
        props = subj["properties"]
        for k in ("valid_from", "valid_to", "is_current"):
            if k not in props:
                errors.append(f"Subject missing {k}")

    obj = triple.get("object")
    if obj is None:
        errors.append("Object is None")
    elif not isinstance(obj, dict):
        errors.append("Object not a dict")
    elif "class" not in obj or "properties" not in obj:
        errors.append("Object missing class or properties")
    elif obj["class"] not in entity_classes:
        errors.append(f"Invalid object class: {obj.get('class')}")
    elif not isinstance(obj["properties"], dict):
        errors.append("Object properties not a dict")
    else:
        props = obj["properties"]
        for k in ("valid_from", "valid_to", "is_current"):
            if k not in props:
                errors.append(f"Object missing {k}")

    pred = triple.get("predicate")
    if not isinstance(pred, str):
        errors.append("Predicate not a string")
    elif pred not in edge_labels:
        errors.append(f"Invalid predicate: {pred}")
    elif isinstance(subj, dict) and isinstance(obj, dict) and subj.get("class") and obj.get("class"):
        pairs = edge_directions.get(pred, [])
        if pairs and not any(s == subj["class"] and t == obj["class"] for s, t in pairs):
            errors.append(f"Invalid direction: {subj['class']} -{pred}-> {obj['class']}")

    if "temporal_metadata" not in triple:
        errors.append("Missing temporal_metadata")
    else:
        tm = triple["temporal_metadata"]
        if not isinstance(tm, dict):
            errors.append("temporal_metadata not a dict")
        else:
            for k in ("valid_from", "valid_to", "recorded_at"):
                if k not in tm:
                    errors.append(f"temporal_metadata missing {k}")

    return len(errors) == 0, errors


def get_identity_keys(schema: Dict[str, Any]) -> Dict[str, List[str]]:
    return {n["class"]: n.get("identity_keys", ["name"]) for n in schema.get("nodes", [])}


__all__ = ["load_schema_sets", "validate_triple", "get_identity_keys"]
