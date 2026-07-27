#!/usr/bin/env python3
"""
Old-vs-new equivalence for ONE migration slice: `src/step03b_anchor_kpi_facilities.py`
-> `esg_kg.graph.anchor_kpi`, plus the `esg_kg.core.identity` module that slice had to
extract on the way.

WHY THIS IS A SEPARATE FILE (and not another arm in test_esg_kg_equivalence.py)
That file is past 1,100 lines and covers the whole kernel; this one covers a single
slice end-to-end. Same contract as its sibling: import BOTH trees, run them on the
same real input, assert equal. The split is organisational only — the safety net it
provides is identical, and both must be run after touching anything they compare.

WHY core/identity.py EXISTS AT ALL
`parse_source_id` is DEFINED in `src/step03b_anchor_kpi_facilities.py:98` and IMPORTED
by `src/step05b_stamp_provenance.py:51`. Moving step03b without first lifting that
symbol into the kernel would leave the migrated 05b importing from a sibling STAGE —
the exact "a step file doubles as a utility library" knot that `core/graph_patch.py`
untied for step05c/step05d a day earlier (DESIGN.md §1). So the slice is two commits:
core/identity.py first, then the stage. `PROVENANCE_CLASSES` and `get_stable_entity_id`
join it from step02 because 05b imports all three together.

Offline: no LLM, no Neo4j, no network. `config/schema.json` is tracked in git so the
identity arms always run; arms needing `graph_output/` (git-ignored, shipped via the
HF snapshot) SKIP with a message on a bare clone.

Run from the repo root:

    python test/test_esg_kg_anchor_kpi.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ scripts ------------------------------------------------
import step02_extract_triplet_from_jsonl as old_step02  # noqa: E402
import step03b_anchor_kpi_facilities as old_step03b  # noqa: E402

# --- new: the esg_kg package ---------------------------------------------------
from esg_kg.core import identity as new_identity  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
TRIPLES_FILE = REPO / "graph_output" / "validated" / "all_validated_triples.json"

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def load_triples() -> list:
    """The real validated corpus, or [] when the HF snapshot is not pulled."""
    if not TRIPLES_FILE.exists():
        return []
    data = json.loads(TRIPLES_FILE.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("triples", [])
    return data if isinstance(data, list) else []


def iter_nodes(triples: list):
    """Every subject/object node in the corpus — the actual input these helpers see."""
    for t in triples:
        for side in ("subject", "object"):
            node = t.get(side)
            if isinstance(node, dict) and "class" in node:
                yield node


# --------------------------------------------------------------------------- #
# core/identity.py — parse_source_id  <- step03b:98
# --------------------------------------------------------------------------- #

# Hand-picked inputs covering every RETURN PATH, so the arm holds even on a bare clone
# where the corpus is absent. The real-corpus arm below adds volume, not new branches.
SOURCE_ID_EDGE_CASES = [
    "AAA_Baocaothuongnien_2011.pdf_10_1",   # canonical <src>_<page>_<idx>
    "AAA_Baocaothuongnien_2011.pdf_0_0",    # zeros are valid, not falsy-skipped
    "a_b_c_12_345",                          # underscores inside the doc name: rsplit, not split
    "no_page_or_sentence",                   # 3 parts but page/idx not digits -> None
    "only_two",                              # too few parts -> None
    "nounderscoreatall",                     # -> None
    "doc.pdf_10_x",                          # idx not a digit -> None
    "doc.pdf_x_10",                          # page not a digit -> None
    "doc.pdf_-1_2",                          # '-' defeats isdigit() -> None
    "doc.pdf_10_1 ",                         # trailing space -> None (no strip anywhere)
    "",                                      # -> None
    None,                                    # -> None (the str(x or "") guard)
    12345,                                   # non-str input -> None
]


def test_identity_parse_source_id_matches_src_on_edge_cases():
    for sid in SOURCE_ID_EDGE_CASES:
        got = new_identity.parse_source_id(sid)
        want = old_step03b.parse_source_id(sid)
        assert got == want, f"parse_source_id({sid!r}): new={got!r} old={want!r}"

    # not vacuous: both the parsed and the None path really fired
    parsed = [s for s in SOURCE_ID_EDGE_CASES if new_identity.parse_source_id(s) is not None]
    assert len(parsed) == 3, f"expected 3 parseable edge cases, got {parsed}"
    assert new_identity.parse_source_id("a_b_c_12_345") == ("a_b_c", 12, 345)


def test_identity_parse_source_id_matches_src_on_the_real_corpus():
    triples = load_triples()
    if not triples:
        _skip("identity/parse_source_id-corpus", f"{TRIPLES_FILE.name} absent (data_sync pull)")
        return

    sids = []
    for node in iter_nodes(triples):
        sid = (node.get("properties") or {}).get("source_id")
        if sid is not None:
            sids.append(sid)

    n_parsed = 0
    for sid in sids:
        got = new_identity.parse_source_id(sid)
        want = old_step03b.parse_source_id(sid)
        assert got == want, f"parse_source_id({sid!r}): new={got!r} old={want!r}"
        if got is not None:
            n_parsed += 1

    assert n_parsed > 0, "corpus arm parsed nothing — it is comparing two empty results"
    print(f"     ({len(sids)} real source_ids, {n_parsed} parseable, compared across both trees)")


# --------------------------------------------------------------------------- #
# core/identity.py — get_stable_entity_id  <- step02:104
# --------------------------------------------------------------------------- #
def test_identity_get_stable_entity_id_matches_src_on_the_real_corpus():
    """The id every downstream dedup keys on. A drift here silently re-partitions the graph."""
    triples = load_triples()
    if not triples:
        _skip("identity/stable_entity_id", f"{TRIPLES_FILE.name} absent (data_sync pull)")
        return

    keys_map = old_step02.get_identity_keys(load_schema())
    seen_classes = set()
    n = 0
    for node in iter_nodes(triples):
        got = new_identity.get_stable_entity_id(node, keys_map)
        want = old_step02.get_stable_entity_id(node, keys_map)
        assert got == want, f"stable id diverged for {node.get('class')}: {got!r} != {want!r}"
        seen_classes.add(node.get("class"))
        n += 1

    # not vacuous: many classes, hence many different identity_keys shapes, were exercised
    assert n > 1000, f"only {n} nodes compared"
    assert len(seen_classes) > 5, f"only {len(seen_classes)} classes exercised: {seen_classes}"
    print(f"     ({n} real nodes across {len(seen_classes)} classes)")


def test_identity_get_stable_entity_id_matches_src_on_shapes_the_corpus_lacks():
    """Defaults and coercions the real data may never hit, but 05b depends on."""
    keys_map = {"Organization": ["name"], "KPIObservation": ["kpi_type", "value", "year"]}
    cases = [
        {"class": "Organization", "properties": {"name": "  An Phat  "}},   # strip+lower
        {"class": "Organization", "properties": {}},                        # missing key -> ""
        {"class": "KPIObservation", "properties": {"kpi_type": "CO2", "value": 12, "year": None}},
        {"class": "NotInSchema", "properties": {"name": "x"}},              # falls back to ["name"]
        {"properties": {"name": "y"}},                                      # missing class -> Unknown
        {"class": "Organization"},                                          # missing properties
    ]
    for entity in cases:
        got = new_identity.get_stable_entity_id(entity, keys_map)
        want = old_step02.get_stable_entity_id(entity, keys_map)
        assert got == want, f"{entity}: new={got!r} old={want!r}"

    # pin the two defaults explicitly, so a change to them fails loudly in BOTH trees
    assert new_identity.get_stable_entity_id({"properties": {"name": "y"}}, keys_map) == "Unknown|y"
    assert new_identity.get_stable_entity_id(
        {"class": "Organization", "properties": {"name": "  An Phat  "}}, keys_map
    ) == "Organization|an phat"


# --------------------------------------------------------------------------- #
# core/identity.py — PROVENANCE_CLASSES  <- step02:501
# --------------------------------------------------------------------------- #
def test_identity_provenance_classes_matches_src():
    assert new_identity.PROVENANCE_CLASSES == old_step02.PROVENANCE_CLASSES, (
        f"new={sorted(new_identity.PROVENANCE_CLASSES)} "
        f"old={sorted(old_step02.PROVENANCE_CLASSES)}"
    )
    # it is a set of real schema classes, and it deliberately excludes T1 entities
    # (PROVENANCE_PATCH.md: a merged Organization has no single source page)
    schema_classes = {n["class"] for n in load_schema()["nodes"]}
    unknown = new_identity.PROVENANCE_CLASSES - schema_classes
    assert not unknown, f"PROVENANCE_CLASSES names classes absent from schema.json: {unknown}"
    for t1 in ("Organization", "Person", "Facility", "Location"):
        assert t1 not in new_identity.PROVENANCE_CLASSES, f"{t1} must not be stamped per-page"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
    if _skips:
        print(f"{len(_skips)} arm(s) skipped (missing local artifacts):")
        for s in _skips:
            print(f"  - {s}")
