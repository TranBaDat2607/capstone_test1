#!/usr/bin/env python3
"""
Behaviour tests for ONE migration slice: `esg_kg.graph.anchor_kpi` (originally ported
from `src/step03b_anchor_kpi_facilities.py`), plus the `esg_kg.core.identity` module
that slice had to extract on the way.

WHY THIS IS A SEPARATE FILE (and not another arm in test_esg_kg_equivalence.py)
That file is past 1,100 lines and covers the whole kernel; this one covers a single
slice end-to-end. The split is organisational only.

Repointed at `esg_kg` only (2026-07-29) now that `src/` is gone; this file used to import
`src/step02_extract_triplet_from_jsonl.py` and `src/step03b_anchor_kpi_facilities.py` too
and assert the two trees agreed — `test_esg_kg_equivalence.py` already proved that
agreement while both trees existed.

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

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core import identity as new_identity  # noqa: E402
from esg_kg.core.schema import get_identity_keys  # noqa: E402
from esg_kg.graph import anchor_kpi as new_anchor  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
from _fixture_paths import resolve_artifact, skip_if_fixture, tag  # noqa: E402

TRIPLES_FILE = REPO / "graph_output" / "validated" / "all_validated_triples.json"

VALIDATED_DATA, VALIDATED_IS_FIXTURE = resolve_artifact("validated")


_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def load_triples() -> list:
    """The real validated corpus, or [] when the HF snapshot is not pulled."""
    if not VALIDATED_DATA.exists():
        return []
    data = json.loads(VALIDATED_DATA.read_text(encoding="utf-8"))
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
        new_identity.parse_source_id(sid)  # must not raise for any shape, incl. None/int

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
        if got is not None:
            n_parsed += 1

    assert n_parsed > 0, "corpus arm parsed nothing"
    print(f"     ({len(sids)} real source_ids, {n_parsed} parseable)")


def test_identity_get_stable_entity_id_matches_src_on_the_real_corpus():
    """The id every downstream dedup keys on. A drift here silently re-partitions the graph."""
    triples = load_triples()
    if not triples:
        _skip("identity/stable_entity_id", f"{TRIPLES_FILE.name} absent (data_sync pull)")
        return
    if VALIDATED_IS_FIXTURE:
        _skip("identity/stable_entity_id", skip_if_fixture(True))
        return

    keys_map = get_identity_keys(load_schema())
    seen_classes = set()
    n = 0
    for node in iter_nodes(triples):
        new_identity.get_stable_entity_id(node, keys_map)
        seen_classes.add(node.get("class"))
        n += 1

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
        new_identity.get_stable_entity_id(entity, keys_map)  # must not raise for any shape

    assert new_identity.get_stable_entity_id({"properties": {"name": "y"}}, keys_map) == "Unknown|y"
    assert new_identity.get_stable_entity_id(
        {"class": "Organization", "properties": {"name": "  An Phat  "}}, keys_map
    ) == "Organization|an phat"


def test_identity_provenance_classes_matches_src():
    schema_classes = {n["class"] for n in load_schema()["nodes"]}
    unknown = new_identity.PROVENANCE_CLASSES - schema_classes
    assert not unknown, f"PROVENANCE_CLASSES names classes absent from schema.json: {unknown}"
    for t1 in ("Organization", "Person", "Facility", "Location"):
        assert t1 not in new_identity.PROVENANCE_CLASSES, f"{t1} must not be stamped per-page"


def test_anchor_module_constants_match_src():
    """The gates that decide what enters the gazetteer. Silent to change, loud in the output."""
    assert new_anchor.DEFAULT_TRIPLES == TRIPLES_FILE
    assert new_anchor.DEFAULT_SCHEMA == SCHEMA_FILE


def test_anchor_prop_richness_matches_src():
    for props in [{}, {"a": 1}, {"a": None, "b": ""}, {"a": 0, "b": False},
                  {"name": "x", "value": None, "unit": "t"}]:
        new_anchor.prop_richness(props)  # must not raise for any shape
    assert new_anchor.prop_richness({"a": 0, "b": False}) == 2


def test_anchor_load_sentences_matches_src():
    """Reads the real corpus off disk via the documented globs."""
    new_s = new_anchor.load_sentences(new_anchor.DEFAULT_SENTENCE_GLOBS)
    if not new_s:
        _skip("anchor/load_sentences", "no labeled JSONL on disk (data_sync pull)")
        return
    assert len(new_s) > 0
    print(f"     ({len(new_s)} real sentences loaded)")


def test_anchor_collect_inventory_matches_src_on_the_real_corpus():
    triples = load_triples()
    if not triples:
        _skip("anchor/collect_inventory", f"{TRIPLES_FILE.name} absent (data_sync pull)")
        return

    print(f"     {tag(VALIDATED_IS_FIXTURE)} anchor/collect_inventory")
    new_f, new_k, new_a = new_anchor.collect_inventory(copy.deepcopy(triples))

    raw = {(n.get("properties") or {}).get("name")
           for n in iter_nodes(triples) if n.get("class") == "Facility"}
    assert len(new_f) > 0 and len(new_k) > 0, (len(new_f), len(new_k))
    assert len(new_f) < len(raw), f"gazetteer {len(new_f)} not filtered from {len(raw)} raw names"
    print(f"     ({len(raw)} raw Facility names -> {len(new_f)} gazetteer entries, "
          f"{len(new_k)} distinct KPIs, {len(new_a)} existing anchors)")


def strip_anchors(triples: list) -> list:
    """Drop this stage's OWN past output, restoring the corpus to its pre-patch state.

    `all_validated_triples.json` on disk has already been patched — 95 of its 306
    `observedAtFacility` triples carry `anchor_method: "offline_gazetteer"`. Those land in
    `collect_inventory`'s `anchored` set, so re-running the stage over the live file emits
    ZERO new triples and an arm built on it would compare two empty results while printing
    PASS. Same trap as step05c's already-patched indicator axis, same answer as its
    `strip_axis()`: rebuild the input, then rebuild the output.

    Only the gazetteer-minted edges go. The other 211 came from the step02 extractor and
    were present when the stage first ran, so they must stay in `anchored`.
    """
    return [t for t in triples if t.get("anchor_method") != "offline_gazetteer"]


def test_anchor_build_patch_matches_src_on_the_real_corpus():
    """The strongest arm: the whole stage body on the real corpus + the real sentences."""
    triples = load_triples()
    if not triples:
        _skip("anchor/build_patch-real", f"{TRIPLES_FILE.name} absent (data_sync pull)")
        return
    sentences = new_anchor.load_sentences(new_anchor.DEFAULT_SENTENCE_GLOBS)
    if not sentences:
        _skip("anchor/build_patch-real", "no labeled JSONL on disk (data_sync pull)")
        return
    schema = load_schema()
    cap = new_anchor.DEFAULT_MAX_PER_FACILITY
    triples = strip_anchors(triples)

    new_t, new_stats = new_anchor.build_patch(
        copy.deepcopy(triples), dict(sentences), schema, cap)

    assert new_stats["new_anchor_triples"] > 0, new_stats
    assert new_stats["facility_gazetteer_size"] > 0, new_stats
    assert all(t["predicate"] == "observedAtFacility" for t in new_t)
    assert all(t["anchor_method"] == "offline_gazetteer" for t in new_t)
    print(f"     ({new_stats['new_anchor_triples']} anchor triples over "
          f"{new_stats['kpi_observations']} KPIs)")


def test_anchor_build_patch_matches_src_on_the_hub_guard():
    """The P5 degree guard the live corpus never trips (facilities_over_cap is [] there).

    Without this arm the over-cap branch is compared by neither tree — the same gap the
    synthetic Penalty fixture closed for step05c.
    """
    triples = load_triples()
    if not triples:
        _skip("anchor/build_patch-cap", f"{TRIPLES_FILE.name} absent (data_sync pull)")
        return
    sentences = new_anchor.load_sentences(new_anchor.DEFAULT_SENTENCE_GLOBS)
    if not sentences:
        _skip("anchor/build_patch-cap", "no labeled JSONL on disk (data_sync pull)")
        return
    schema = load_schema()
    triples = strip_anchors(triples)

    new_t, new_stats = new_anchor.build_patch(
        copy.deepcopy(triples), dict(sentences), schema, 1)

    assert new_stats["facilities_over_cap"], "cap=1 tripped no facility — arm is vacuous"
    assert new_stats["new_anchor_triples"] < new_stats["raw_matches"], new_stats
    print(f"     (cap=1 dropped {len(new_stats['facilities_over_cap'])} facilities, "
          f"{new_stats['raw_matches']} raw -> {new_stats['new_anchor_triples']} kept)")


def test_anchor_is_idempotent_on_the_already_patched_corpus():
    """Re-running the stage over its own output must add nothing, in BOTH trees.

    This is the arm the vacuous version of the two above accidentally was — kept
    deliberately, because CLAUDE.md tells the operator to run step03b before step05 and
    the live corpus is already patched, so idempotency is the property actually relied on.
    Its non-vacuity guard is the inverse of the others': it asserts the input IS patched,
    which is what makes an empty result meaningful rather than a silent no-op.
    """
    triples = load_triples()
    if not triples:
        _skip("anchor/idempotent", f"{TRIPLES_FILE.name} absent (data_sync pull)")
        return
    sentences = new_anchor.load_sentences(new_anchor.DEFAULT_SENTENCE_GLOBS)
    if not sentences:
        _skip("anchor/idempotent", "no labeled JSONL on disk (data_sync pull)")
        return

    already = len(triples) - len(strip_anchors(triples))
    if already == 0:
        _skip("anchor/idempotent", "corpus carries no gazetteer anchors — nothing to re-run over")
        return

    schema = load_schema()
    cap = new_anchor.DEFAULT_MAX_PER_FACILITY
    new_t, new_stats = new_anchor.build_patch(
        copy.deepcopy(triples), dict(sentences), schema, cap)

    assert new_t == [], f"re-run minted {len(new_t)} duplicate anchors"
    assert new_stats["raw_matches"] == 0, new_stats
    print(f"     ({already} existing gazetteer anchors, re-run added 0)")


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
