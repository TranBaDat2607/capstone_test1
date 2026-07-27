"""identity — how a node is named, located and keyed, shared by the graph stages.

Extracted verbatim: ``parse_source_id`` <- ``src/step03b_anchor_kpi_facilities.py:98``;
``get_stable_entity_id`` <- ``src/step02_extract_triplet_from_jsonl.py:104``;
``PROVENANCE_CLASSES`` <- ``src/step02_extract_triplet_from_jsonl.py:501``.

WHY THESE THREE TRAVEL TOGETHER
``src/step05b_stamp_provenance.py`` imports all three at once (:49-51) — two from
step02, one from step03b — because they are the three halves of the same question:
*which nodes carry page-level provenance* (``PROVENANCE_CLASSES``), *where does this
one come from* (``parse_source_id``), and *when the source_id is unusable, what is
this node's identity* (``get_stable_entity_id``, tier 3 of the patch's precedence
ladder — docs/PROVENANCE_PATCH.md).

Lifting them here is what lets step03b move at all. ``parse_source_id`` is defined
INSIDE step03b, so migrating that stage while leaving the symbol there would leave
the migrated step05b importing from a sibling STAGE — the "a step file doubles as a
utility library" knot DESIGN.md §1 says ``core/`` exists to untie, and the same shape
``core/graph_patch.py`` fixed for step05c/step05d.

CARE REQUIRED
``get_stable_entity_id`` is the key every dedup and every provenance tier-3 match
runs on. Its two defaults (missing class -> ``"Unknown"``, class absent from the map
-> ``["name"]``) and its ``strip().lower()`` on string values are behaviour, not
tidiness: change any of them and the graph silently re-partitions. It is deliberately
NOT ``normalize_name`` — that one strips legal forms and fixes OCR, which would merge
entities this id must keep apart.

The bodies are duplicated in ``src/`` while the refactor is in flight (Model A — the
old tree must keep running and cannot import from here).
``test/test_esg_kg_anchor_kpi.py`` holds the copies equal; that arm retires when the
``src/`` twins are deleted (DESIGN.md §5.3).
"""

from typing import Any, Dict, List, Optional, Tuple

# Claim + evidence classes that get page-level provenance stamped at extraction time
# (docs/PROVENANCE_PATCH.md). T1 entities (Organization, Person, ...) are deliberately
# excluded: they recur on dozens of pages and get merged in step05, so a single stamped
# page would be misleading.
PROVENANCE_CLASSES = {"SustainabilityClaim", "KPIObservation", "MediaReport", "Controversy",
                      "Penalty", "ThirdPartyVerification", "Emission", "Waste", "Certification"}


def parse_source_id(source_id: Any) -> Optional[Tuple[str, int, int]]:
    """"AAA_Baocaothuongnien_2011.pdf_10_1" -> ("AAA_Baocaothuongnien_2011.pdf", 10, 1)."""
    s = str(source_id or "")
    parts = s.rsplit("_", 2)
    if len(parts) != 3:
        return None
    src, page, idx = parts
    if not (page.isdigit() and idx.isdigit()):
        return None
    return src, int(page), int(idx)


def get_stable_entity_id(entity: Dict[str, Any], identity_keys_map: Dict[str, List[str]]) -> str:
    entity_class = entity.get("class", "Unknown")
    props = entity.get("properties", {})
    keys = identity_keys_map.get(entity_class, ["name"])
    parts = [entity_class]
    for k in keys:
        v = props.get(k, "")
        if isinstance(v, str):
            v = v.strip().lower()
        parts.append(str(v))
    return "|".join(parts)
