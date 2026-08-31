#!/usr/bin/env python3
"""
Behaviour tests for ONE migration slice: `esg_kg.resolve.provenance`
(ported from `src/step05b_stamp_provenance.py`).

WHY THIS IS A SEPARATE FILE
Same reason as `test_esg_kg_anchor_kpi.py`: `test_esg_kg_equivalence.py` is past 1,100
lines and covers the whole kernel, while this covers a single stage end-to-end.

WHY THIS SLICE NEEDED NO NEW core/ MODULE
step05b imports exactly four symbols, and the step03b migration had already lifted all of
them: `PROVENANCE_CLASSES`, `get_stable_entity_id`, `parse_source_id` (-> `core/identity.py`)
and `get_identity_keys` (-> `core/schema.py`). This was the first stage to move with the
kernel untouched, which is what "unblocked" meant in DESIGN.md.

HOW THE ALREADY-PATCHED-ARTIFACT LAW APPLIES HERE — AND HOW IT DIFFERS
`resolved_graph.json` on disk has already been stamped by this stage (6,258 of its 10,425
nodes carry `source_doc`/`source_page`). For step05c and step03b that fact made the naive
real-graph arm VACUOUS, because those stages skip what they already produced. **step05b does
not skip** — its only early `continue` is for `provenance_method == "extraction"`, which no
node in the live graph carries. Every other node is re-matched and re-stamped from scratch,
so the real-graph arm below genuinely exercises the stage.

The strip arm is therefore not here to rescue a vacuous comparison; it proves a stronger
property the other two stages cannot claim: the stage never READS its own output. None of
the keys it writes appears in any PROVENANCE_CLASS's `identity_keys` (checked against
`config/schema.json`), so `get_stable_entity_id` cannot see them — stripping must change
nothing. That property is checked entirely WITHIN this tree (stamping a stripped copy must
reproduce stamping the live, already-stamped graph) — it never needed an external oracle.

What the live data does NOT cover is the `extraction` skip branch (zero such nodes today —
it is there for post-re-extraction step02 output). That gets a synthetic arm, the same gap
the cap=1 fixture closed for step03b and the Penalty fixture for step05c.

Offline: no LLM, no Neo4j, no network. `config/schema.json` is tracked in git so the pure
arms always run; arms needing `graph_output/` (git-ignored, shipped via the HF snapshot)
SKIP with a message on a bare clone.

Was driven through both `src/` and `esg_kg` while both trees existed (DESIGN.md §5.3);
repointed at `esg_kg` only (2026-07-29) now that `src/` is gone. Several small pure-helper
tests here used to compare `new_prov.<fn>(x)` against `old_step05b.<fn>(x)` case-by-case with
no independently recorded expected value — those per-case loops were removed rather than
guessed at; each surviving test keeps the concrete, old-tree-independent assertions it
already had (specific pinned values, "not vacuous" counts, or a within-tree strip-vs-live
comparison).

Run from the repo root:

    python test/test_esg_kg_provenance.py
"""

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.resolve import provenance as new_prov  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
RESOLVED_FILE = REPO / "graph_output" / "resolved" / "resolved_graph.json"
GRAPHS_DIR = REPO / "graph_output" / "graphs"

_skips: list = []
_cache: dict = {}


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def load_resolved() -> dict:
    """The real resolved graph, or {} when the HF snapshot is not pulled."""
    if not RESOLVED_FILE.exists():
        return {}
    data = json.loads(RESOLVED_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def page_indexes():
    """(stable_idx, source_idx, docs) built ONCE — it is a full pass over 43 doc dirs."""
    if "idx" not in _cache:
        _cache["idx"] = new_prov.build_page_indexes(GRAPHS_DIR)
    return _cache["idx"]


def test_provenance_module_constants_match_src():
    assert new_prov.DEFAULT_RESOLVED == RESOLVED_FILE
    assert new_prov.DEFAULT_GRAPHS_DIR == GRAPHS_DIR
    assert new_prov.DEFAULT_SCHEMA == SCHEMA_FILE


PAGE_TOKEN_CASES = [
    "AAA_Baocaothuongnien_page12_LNST_DTT_2010",   # match -> ('AAA_Baocaothuongnien', 12)
    "AAA_page3_x",                                  # match -> ('AAA', 3)
    "doc_page7",                                    # match at end-of-string ($ branch)
    "AAA_Baocaothuongnien_2011.pdf_10_1",          # parses as source_id -> None (the guard)
    "no_page_token_here",                           # no '_pageNN' -> None
    "page12_only",                                  # no prefix before '_page' -> None
    "",                                             # -> None
    None,                                           # -> None
    12345,                                          # non-str -> None
]


def test_provenance_parse_page_token_matches_src():
    matched = [s for s in PAGE_TOKEN_CASES if new_prov.parse_page_token(s) is not None]
    assert len(matched) == 3, f"expected 3 token matches, got {matched}"
    assert new_prov.parse_page_token("AAA_Baocaothuongnien_page12_x") == \
        ("AAA_Baocaothuongnien", 12)
    assert new_prov.parse_page_token("AAA_Baocaothuongnien_2011.pdf_10_1") is None


def test_provenance_node_year_context_matches_src():
    assert new_prov.node_year_context({"year": 2019, "target_year": 2030}) == 2019
    assert new_prov.node_year_context({"target_year": 2030, "date": "2021"}) == 2030
    assert new_prov.node_year_context({"year": "1899"}) is None


PROP_DICT_CASES = [
    {},                                                              # no properties at all
    {"properties": {"a": 1}},                                        # canonical only
    {"properties": {"a": 1}, "temporal_versions": []},               # empty version list
    {"properties": {"a": 1},
     "temporal_versions": [{"properties": {"b": 2}}, {"properties": {"c": 3}}]},
    {"properties": {"a": 1}, "temporal_versions": [{"no_props": True}]},  # version w/o props
    {"temporal_versions": [{"properties": {"b": 2}}]},               # versions but no canonical
]


def test_provenance_prop_dicts_matches_src():
    assert new_prov._prop_dicts(PROP_DICT_CASES[3]) == [{"a": 1}, {"b": 2}, {"c": 3}]
    assert new_prov._prop_dicts(PROP_DICT_CASES[4]) == [{"a": 1}]


def test_provenance_choose_primary_matches_src():
    assert new_prov.choose_primary({("AAA_2018", 1), ("AAA_2019", 9)}, 2019) == ("AAA_2019", 9)
    assert new_prov.choose_primary({("AAA_2018", 1), ("AAA_2019", 9)}, 2020) == ("AAA_2018", 1)


def test_provenance_build_page_indexes_matches_src_on_the_real_pages():
    if not GRAPHS_DIR.is_dir():
        _skip("provenance/build_page_indexes", "graph_output/graphs absent (data_sync pull)")
        return
    new_s, new_src, new_docs = new_prov.build_page_indexes(GRAPHS_DIR)
    assert new_s and new_src and new_docs, (len(new_s), len(new_src), len(new_docs))
    print(f"     ({len(new_docs)} docs -> {len(new_s)} stable_ids, "
          f"{len(new_src)} source_ids)")


def test_provenance_load_news_article_meta_matches_src():
    new_m = new_prov.load_news_article_meta(new_prov.DEFAULT_NEWS_GLOBS)
    if not new_m:
        _skip("provenance/load_news_article_meta", "no news JSONL on disk (data_sync pull)")
        return
    assert any(v["article_title"] for v in new_m.values()), "no article_title in any row"
    print(f"     ({len(new_m)} news docs with article metadata)")


def test_provenance_candidate_locations_matches_src_on_the_real_graph():
    """Every provenance node in the real graph, through the whole 4-tier precedence."""
    graph = load_resolved()
    if not graph or not GRAPHS_DIR.is_dir():
        _skip("provenance/candidate_locations", "resolved graph or graphs/ absent (data_sync pull)")
        return
    stable_idx, source_idx, docs = page_indexes()
    ikm = new_prov.get_identity_keys(load_schema())
    report_docs = [d for d in docs if "__" not in d]

    tiers = {}
    n = 0
    for node in graph.get("nodes", []):
        if node.get("class") not in new_prov.PROVENANCE_CLASSES:
            continue
        n += 1
        got = new_prov.candidate_locations(node, stable_idx, source_idx, ikm, report_docs)
        tiers[got[1]] = tiers.get(got[1], 0) + 1

    assert n > 0, "no provenance-class nodes in the graph"
    matched = {k: v for k, v in tiers.items() if k is not None}
    assert len(matched) >= 2, f"only one tier exercised: {tiers}"
    print(f"     ({n} provenance nodes, tiers {dict(sorted(tiers.items(), key=lambda x: str(x[0])))})")


TIER_METHODS = {"source_id", "source_id_index", "stable_id_index", "page_token"}
STAMPED_KEYS = ("source_doc", "source_page", "source_pages",
                "article_title", "article_url", "source_domain")


def strip_provenance(graph: dict) -> tuple:
    """Drop this stage's OWN past output, restoring the graph to its pre-patch state.

    Strips only what THIS stage minted — nodes whose `provenance_method` is one of its four
    tier names. A node stamped `extraction` came from step02 and must survive untouched,
    exactly as `strip_anchors` keeps the 211 extractor-made `observedAtFacility` edges: strip
    by provenance, never by key name.

    Unlike step03b/step05c this is NOT needed to avoid a vacuous arm (step05b re-stamps
    rather than skipping). It is here to prove the stage never reads its own output.
    """
    g = copy.deepcopy(graph)
    n = 0
    for node in g.get("nodes", []):
        props = node.get("properties") or {}
        if props.get("provenance_method") not in TIER_METHODS:
            continue
        for k in STAMPED_KEYS:
            props.pop(k, None)
        props.pop("provenance_method", None)
        n += 1
    return g, n


def _stamp(graph: dict):
    """Run the full stage body over a COPY of graph; return (stamped_graph, stats)."""
    stable_idx, source_idx, docs = page_indexes()
    news_meta = new_prov.load_news_article_meta(new_prov.DEFAULT_NEWS_GLOBS)
    ikm = new_prov.get_identity_keys(load_schema())
    report_docs = [d for d in docs if "__" not in d]

    g = copy.deepcopy(graph)
    stats = new_prov.stamp_graph(g, stable_idx, source_idx, news_meta, ikm, report_docs)
    return g, stats


def test_provenance_stamp_graph_matches_src_on_the_real_graph():
    """The strongest arm: the whole stage body on the real 10k-node graph."""
    graph = load_resolved()
    if not graph or not GRAPHS_DIR.is_dir():
        _skip("provenance/stamp_graph-real", "resolved graph or graphs/ absent (data_sync pull)")
        return
    g_new, s_new = _stamp(graph)

    stamped = sum(c.get("stamped", 0) for c in s_new["per_class"].values())
    assert stamped > 0, s_new
    assert len(s_new["per_method"]) >= 2, s_new["per_method"]
    print(f"     ({stamped} nodes stamped via {dict(s_new['per_method'])})")


def test_provenance_stamp_graph_matches_src_on_the_stripped_graph():
    """The stage must not read its own output: stripping the stamps changes nothing.

    None of the keys step05b writes appears in any PROVENANCE_CLASS's `identity_keys`, so
    `get_stable_entity_id` cannot see them and tier 3 must resolve identically. This arm is
    what keeps that true — if a future edit made a stamped key feed back into matching, the
    graph would drift on every re-run with no other signal. The comparison is entirely
    WITHIN this tree: stamping the stripped graph from scratch must reproduce stamping the
    already-live (already-stamped) graph.
    """
    graph = load_resolved()
    if not graph or not GRAPHS_DIR.is_dir():
        _skip("provenance/stamp_graph-stripped", "resolved graph or graphs/ absent (data_sync pull)")
        return
    stripped, n_stripped = strip_provenance(graph)
    if n_stripped == 0:
        _skip("provenance/stamp_graph-stripped", "graph carries no stamps — nothing to strip")
        return

    g_new, s_new = _stamp(stripped)
    g_live, s_live = _stamp(graph)

    assert s_new == s_live, (f"stripping changed the outcome — the stage reads its own "
                             f"output:\n  stripped={s_new}\n  live={s_live}")
    assert g_new == g_live, "stripped rebuild differs from the live re-stamp"
    print(f"     ({n_stripped} stamps stripped and rebuilt identically — "
          f"stage does not read its own output)")


def test_provenance_stamp_graph_never_reorders_nodes():
    """The HARD INVARIANT in the stage docstring, asserted rather than trusted.

    step06 keys Neo4j nodes by array index (`_node_key = f"n{i}"`) and the step07 dossiers
    reference nodes by `node_index`, so a grow/shrink/reorder here silently corrupts the
    paid advisory layer. `main()` asserts the counts; this also pins the ORDER and the
    per-position class/identity, which counts alone would not catch.
    """
    graph = load_resolved()
    if not graph or not GRAPHS_DIR.is_dir():
        _skip("provenance/node-order", "resolved graph or graphs/ absent (data_sync pull)")
        return
    before = [(n.get("class"), n.get("id"), n.get("stable_id"))
              for n in graph.get("nodes", [])]
    n_edges = len(graph.get("edges", []))

    g_new, _ = _stamp(graph)
    after = [(n.get("class"), n.get("id"), n.get("stable_id")) for n in g_new.get("nodes", [])]

    assert len(after) == len(before), f"node count changed: {len(before)} -> {len(after)}"
    assert after == before, "node array was reordered or its identities were rewritten"
    assert len(g_new.get("edges", [])) == n_edges, "edge array changed"
    assert before, "graph has no nodes — arm is vacuous"
    print(f"     ({len(before)} nodes, {n_edges} edges — order and identity preserved)")


def test_provenance_extraction_stamped_nodes_are_skipped():
    """The `provenance_method == "extraction"` branch, which the live graph never reaches.

    Zero nodes carry it today — it exists for step02 output after the planned re-extraction
    (DESIGN.md §5.4). Synthetic, like step03b's cap=1 arm and step05c's Penalty fixture, and
    it needs no artifacts on disk: the skip happens before any index lookup.
    """
    cls = sorted(new_prov.PROVENANCE_CLASSES)[0]
    graph = {
        "nodes": [
            # already self-stamped by the extractor -> must be left EXACTLY as-is
            {"class": cls, "properties": {"provenance_method": "extraction",
                                          "source_doc": "KEEP_ME", "source_page": 99,
                                          "source_id": "OTHER_2_2"}},
            # not stamped -> must be matched through tier 1 ('<src>_<page>_<idx>')
            {"class": cls, "properties": {"source_id": "SOMEDOC_5_1"}},
            # not a provenance class -> never touched at all
            {"class": "Organization", "properties": {"source_id": "SOMEDOC_5_1"}},
        ],
        "edges": [],
    }
    ikm = new_prov.get_identity_keys(load_schema())

    g_new = copy.deepcopy(graph)
    s_new = new_prov.stamp_graph(g_new, {}, {}, {}, ikm, [])

    assert s_new["per_class"][cls]["already_stamped"] == 1, s_new
    assert g_new["nodes"][0]["properties"]["source_doc"] == "KEEP_ME", "extraction stamp overwritten"
    assert g_new["nodes"][1]["properties"]["source_doc"] == "SOMEDOC", g_new["nodes"][1]
    assert g_new["nodes"][1]["properties"]["provenance_method"] == "source_id", g_new["nodes"][1]
    assert "source_doc" not in g_new["nodes"][2]["properties"], "non-provenance class was stamped"
    print("     (extraction stamp preserved, sibling node still matched via tier 1)")


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
