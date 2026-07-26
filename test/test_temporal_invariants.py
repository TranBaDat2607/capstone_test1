#!/usr/bin/env python3
"""
Offline unit checks for the TEMPORAL_KG_DESIGN Phase-0 logic (P3/P4).

The repo has no pytest harness (test/ holds manual-validation notebooks), so this
is a plain assert script — run it from the repo root:

    python test/test_temporal_invariants.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from step03_fix_invalid_triplets import (  # noqa: E402
    date_start_key,
    enforce_temporal_invariants,
    normalize_date_string,
)
from step02_extract_triplet_from_jsonl import stamp_provenance  # noqa: E402
from step03b_anchor_kpi_facilities import parse_source_id  # noqa: E402
from step05_resolve_entities import DSU, consolidate  # noqa: E402
from step05b_stamp_provenance import (  # noqa: E402
    candidate_locations,
    choose_primary,
    parse_page_token,
    stamp_graph,
)


def test_normalize_date_string():
    assert normalize_date_string(None) == (None, True)
    assert normalize_date_string("") == (None, True)
    assert normalize_date_string("null") == (None, True)
    assert normalize_date_string("2011") == ("2011", True)
    assert normalize_date_string("2011-1-3") == ("2011-01-03", True)
    assert normalize_date_string("31/05/2023") == ("2023-05-31", True)
    assert normalize_date_string("05/2023") == ("2023-05", True)
    assert normalize_date_string("2023.05.31") == ("2023-05-31", True)
    assert normalize_date_string("2024-08-14T10:00:00") == ("2024-08-14", True)
    # unparseable spellings are returned unchanged and flagged, never invented
    assert normalize_date_string("Q2 2023") == ("Q2 2023", False)
    assert normalize_date_string("2023-13-01") == ("2023-13-01", False)


def test_date_start_key():
    # the P4 bug: "2011" and "2011-01-01" are the SAME start instant
    assert date_start_key("2011") == date_start_key("2011-01-01") == "2011-01-01"
    assert date_start_key("2011-03") == "2011-03-01"
    assert date_start_key("garbage") is None
    assert date_start_key(None) is None


def test_enforce_temporal_invariants():
    triples = [{
        "subject": {"class": "Organization",
                    "properties": {"name": "X", "valid_from": "01/2020",
                                   "valid_to": None, "is_current": True}},
        "predicate": "subjectToPenalty",
        "object": {"class": "Penalty",
                   "properties": {"penalty_id": "p1", "date": "14/08/2024",
                                  "source_type": "news",
                                  "valid_from": "2024-08-14", "valid_to": "2023",
                                  "is_current": False}},
        "temporal_metadata": {"valid_from": "2024/08/14", "valid_to": None,
                              "recorded_at": "2024"},
    }]
    stats = enforce_temporal_invariants(triples)
    subj = triples[0]["subject"]["properties"]
    obj = triples[0]["object"]["properties"]
    tm = triples[0]["temporal_metadata"]
    assert subj["valid_from"] == "2020-01"
    assert obj["date"] == "2024-08-14"
    assert tm["valid_from"] == "2024-08-14"
    # news T2 node without the required bool gets the conservative default
    assert obj["date_uncertain"] is True
    assert stats["date_uncertain_defaulted"] == 1
    # valid_from (2024-08-14) > valid_to (2023) is flagged, not rewritten
    assert stats["valid_from_after_valid_to"] == 1
    assert obj["valid_to"] == "2023"


def _org(name, valid_from, is_current=True, valid_to=None):
    return {"class": "Organization",
            "properties": {"name": name, "valid_from": valid_from,
                           "valid_to": valid_to, "is_current": is_current}}


def test_consolidate_version_dedup_and_is_current():
    # Two spellings of the same start instant -> ONE version (the observed AAA bug)
    nodes = [_org("X", "2011"), _org("X", "2011-01-01")]
    dsu = DSU(2)
    dsu.union(0, 1)
    resolved, _ = consolidate(nodes, [], dsu, {})
    (node,) = resolved["nodes"]
    assert len(node["temporal_versions"]) == 1

    # Distinct years both claiming is_current=true -> exactly one survives (latest open)
    nodes = [_org("Y", "2011"), _org("Y", "2020")]
    dsu = DSU(2)
    dsu.union(0, 1)
    resolved, _ = consolidate(nodes, [], dsu, {})
    (node,) = resolved["nodes"]
    versions = node["temporal_versions"]
    assert len(versions) == 2
    current = [v for v in versions if v["is_current"] is True]
    assert len(current) == 1
    assert current[0]["valid_from"] == "2020"

    # All-closed chain legitimately keeps zero current versions
    nodes = [_org("Z", "2011", is_current=False, valid_to="2015"),
             _org("Z", "2016", is_current=False, valid_to="2019")]
    dsu = DSU(2)
    dsu.union(0, 1)
    resolved, _ = consolidate(nodes, [], dsu, {})
    (node,) = resolved["nodes"]
    assert all(v["is_current"] is False for v in node["temporal_versions"])


def test_parse_source_id():
    assert parse_source_id("AAA_Baocaothuongnien_2011.pdf_10_1") == \
        ("AAA_Baocaothuongnien_2011.pdf", 10, 1)
    assert parse_source_id("no_page_or_sentence") is None
    assert parse_source_id(None) is None


# --------------------------------------------------------------------------- #
# Provenance patch (step05b, docs/PROVENANCE_PATCH.md).
# --------------------------------------------------------------------------- #
IDKEYS = {"SustainabilityClaim": ["claim_id"], "KPIObservation": ["kpi_type", "year"],
          "Organization": ["name"]}


def test_parse_page_token():
    assert parse_page_token("AAA_Baocaothuongnien_page12_LNST_DTT_2010") == \
        ("AAA_Baocaothuongnien", 12)
    assert parse_page_token("AAA_Baocaothuongnien_page7") == ("AAA_Baocaothuongnien", 7)
    # ids in the canonical <src>_<page>_<idx> form belong to parse_source_id, not here
    assert parse_page_token("AAA_Baocaothuongnien_2011.pdf_10_1") is None
    assert parse_page_token("no_token_here") is None
    assert parse_page_token(None) is None


def test_choose_primary():
    cands = {("AAA_Baocaothuongnien_2011", 5), ("AAA_Baocaothuongnien_2020", 3)}
    # year context wins over lexicographic order
    assert choose_primary(cands, 2020) == ("AAA_Baocaothuongnien_2020", 3)
    # no year context -> lexicographically smallest doc
    assert choose_primary(cands, None) == ("AAA_Baocaothuongnien_2011", 5)
    # same doc, several pages -> smallest page
    assert choose_primary({("D_2011", 9), ("D_2011", 2)}, None) == ("D_2011", 2)


def test_candidate_locations_tiers():
    stable_idx = {"SustainabilityClaim|c1": {("DOC_2011", 4)}}
    source_idx = {"weird_llm_id": {("DOC_2012", 7)}}

    # tier 1: a parseable source_id wins even when other indexes disagree
    node = {"class": "SustainabilityClaim",
            "properties": {"claim_id": "c1", "source_id": "DOC_2011.pdf_10_1"}}
    assert candidate_locations(node, stable_idx, source_idx, IDKEYS, []) == \
        ({("DOC_2011", 10)}, "source_id")

    # tier 2: exact raw source_id lookup
    node = {"class": "KPIObservation",
            "properties": {"kpi_type": "x", "year": 2012, "source_id": "weird_llm_id"}}
    assert candidate_locations(node, stable_idx, source_idx, IDKEYS, []) == \
        ({("DOC_2012", 7)}, "source_id_index")

    # tier 3: recomputed stable_id, reachable via a temporal_versions member too
    node = {"class": "SustainabilityClaim", "properties": {"claim_id": "other"},
            "temporal_versions": [{"properties": {"claim_id": "C1"}}]}  # case-insensitive
    assert candidate_locations(node, stable_idx, source_idx, IDKEYS, []) == \
        ({("DOC_2011", 4)}, "stable_id_index")

    # tier 4: _pageNN_ token + unique year-matching doc dir
    node = {"class": "KPIObservation",
            "properties": {"kpi_type": "y", "year": 2010,
                           "source_id": "DOC_page12_LNST_2010"}}
    assert candidate_locations(node, {}, {}, IDKEYS, ["DOC_2010", "DOC_2011"]) == \
        ({("DOC_2010", 12)}, "page_token")

    # nothing matches -> unstamped
    node = {"class": "SustainabilityClaim", "properties": {"claim_id": "nope"}}
    assert candidate_locations(node, stable_idx, source_idx, IDKEYS, []) == (set(), None)


def test_stamp_graph():
    graph = {"nodes": [
        {"class": "SustainabilityClaim", "properties": {"claim_id": "c1"}},
        {"class": "Organization", "properties": {"name": "org"}},          # T1: never stamped
        {"class": "KPIObservation",                                         # already ground truth
         "properties": {"kpi_type": "z", "year": 2011, "provenance_method": "extraction"}},
        {"class": "SustainabilityClaim", "properties": {"claim_id": "c2"}},  # ambiguous -> list
        {"class": "MediaReport", "properties": {"report_id": "m1", "title": "t",
                                                "source_id": "news_llm_id"}},
    ], "edges": []}
    idkeys = dict(IDKEYS, MediaReport=["report_id"])
    stable_idx = {"SustainabilityClaim|c1": {("DOC_2011", 4)},
                  "SustainabilityClaim|c2": {("DOC_2011", 4), ("DOC_2020", 9)}}
    source_idx = {"news_llm_id": {("AAA__vietstock.vn__abc123", 1)}}
    news_meta = {"AAA__vietstock.vn__abc123": {
        "article_title": "Bài báo X", "article_url": "https://x", "source_domain": "vietstock.vn"}}

    before = [n["class"] for n in graph["nodes"]]
    stats = stamp_graph(graph, stable_idx, source_idx, news_meta, idkeys, ["DOC_2011", "DOC_2020"])

    # node array untouched (order + count are load-bearing for step06/_node_key)
    assert [n["class"] for n in graph["nodes"]] == before

    n0, n1, n2, n3, n4 = (n["properties"] for n in graph["nodes"])
    assert n0["source_doc"] == "DOC_2011" and n0["source_page"] == 4
    assert "source_doc" not in n1                       # Organization skipped
    assert n2["provenance_method"] == "extraction"      # pre-stamped left alone
    assert "source_doc" not in n2
    assert n3["source_pages"] == ["DOC_2011:4", "DOC_2020:9"]   # ambiguity keeps full list
    assert n4["source_doc"] == "AAA__vietstock.vn__abc123"
    assert n4["article_title"] == "Bài báo X" and n4["article_url"] == "https://x"
    assert n4["title"] == "t"                           # original props untouched
    assert stats["multi_location_nodes"] == 1
    assert stats["news_enriched"] == 1
    assert stats["per_class"]["KPIObservation"] == {"already_stamped": 1}


def test_step02_stamp_provenance():
    graph = {"nodes": [
        {"class": "SustainabilityClaim", "properties": {"claim_id": "c"}},
        {"class": "Organization", "properties": {"name": "org"}},
    ], "edges": []}
    meta = {"title": "Bài X", "url": "https://y", "source_domain": "d.vn"}
    stamp_provenance(graph, "AAA__d.vn__ff00", 1, "news", meta)
    claim, org = (n["properties"] for n in graph["nodes"])
    assert claim["source_doc"] == "AAA__d.vn__ff00" and claim["source_page"] == 1
    assert claim["provenance_method"] == "extraction"
    assert claim["article_title"] == "Bài X" and claim["article_url"] == "https://y"
    assert "source_doc" not in org                      # T1 entity untouched

    graph = {"nodes": [{"class": "KPIObservation", "properties": {"kpi_type": "k"}}],
             "edges": []}
    stamp_provenance(graph, "AAA_Baocaothuongnien_2011", 10, "report", None)
    (kpi,) = (n["properties"] for n in graph["nodes"])
    assert kpi["source_doc"] == "AAA_Baocaothuongnien_2011" and kpi["source_page"] == 10
    assert "article_title" not in kpi


# --------------------------------------------------------------------------- #
# Indicator axis: step03c canonicalization + step05c linking + step08 stable-id.
# --------------------------------------------------------------------------- #
import json  # noqa: E402

from step03c_canonicalize_kpis import (  # noqa: E402
    Matcher, backfill_goal_target_date, canonicalize_kpis,
)
from step03_fix_invalid_triplets import load_schema_sets  # noqa: E402
from step05c_link_standard_indicators import (  # noqa: E402
    GraphPatch, doc_key_for, match_keyword, build_keyword_index,
)
from step08_sync_crosscheck_to_neo4j import (  # noqa: E402
    build_key_index, resolve_claim, resolve_evidence,
)

REPO = Path(__file__).resolve().parents[1]
_DEFS = json.loads((REPO / "kpi_definitions_construction.json").read_text(encoding="utf-8"))
_ALIASES = json.loads((REPO / "config" / "kpi_type_aliases.json").read_text(encoding="utf-8"))
_SCHEMA_SETS = load_schema_sets(json.loads((REPO / "config" / "schema.json").read_text(encoding="utf-8")))


def test_step03c_matcher_rejects_financial_and_keeps_kpi_type():
    m = Matcher(_DEFS, _ALIASES)
    # a genuine ESG alias maps
    ind, method = m.match("Male employees", "người")
    assert ind == "SSCIFC-S6", (ind, method)
    # a financial KPI in VND is rejected, never force-mapped onto an indicator
    ind, method = m.match("Lợi nhuận sau thuế", "tỷ đồng")
    assert ind is None and method == "rejected_unit", (ind, method)
    # an already-standard code is passed through unchanged (never re-derived)
    assert "TT96-6.6.1" in {d["id"] for d in _DEFS}


def _kpi_triple(props):
    return {"subject": {"class": "KPIObservation", "properties": props},
            "predicate": "reportsKPI",
            "object": {"class": "Organization", "properties": {"name": "X"}}}


def test_step03c_stamps_the_rule_that_decided_each_kpi_id():
    """Every KPIObservation must carry HOW its kpi_id was decided, on the node itself.

    Without it a wrong measuredUnder edge cannot be traced back to the rule that minted
    it, which is exactly what Matcher's docstring promises — and DESIGN.md §5.1 requires
    the method to be marked on the data (cf. anchor_method, provenance_method).
    """
    triples = [
        _kpi_triple({"title": "Male employees", "unit": "người", "value": 775}),
        _kpi_triple({"kpi_type": "TT96-6.6.1", "title": "Tổng số lao động",
                     "unit": "người", "value": 500}),
        _kpi_triple({"title": "Lợi nhuận sau thuế", "unit": "tỷ đồng", "value": 4.8e10}),
        _kpi_triple({"title": "Zzz khong co trong tu dien nao ca", "unit": "cái",
                     "value": 1}),
    ]
    canonicalize_kpis(triples, Matcher(_DEFS, _ALIASES))
    got = [t["subject"]["properties"] for t in triples]

    for p in got:
        assert "kpi_id_method" in p, f"no kpi_id_method stamped on {p.get('title')!r}"

    assert got[0]["kpi_id"] and got[0]["kpi_id_method"] == "alias_exact", got[0]
    # a code step01 already emitted is passed through, and says so
    assert got[1]["kpi_id"] == "TT96-6.6.1" and got[1]["kpi_id_method"] == "kpi_type", got[1]

    # THE POINT: both of these end up kpi_id=None, but they mean opposite things —
    # one is a deliberate refusal (financial KPI), the other a gap in the alias file.
    assert got[2]["kpi_id"] is None and got[2]["kpi_id_method"] == "rejected_unit", got[2]
    assert got[3]["kpi_id"] is None and got[3]["kpi_id_method"] == "no_match", got[3]
    assert got[2]["kpi_id_method"] != got[3]["kpi_id_method"], \
        "refused and failed are indistinguishable on the node"

    # identity is untouched: kpi_type is in identity_keys, so stamping must not disturb it
    assert "kpi_type" not in got[0], "stamping invented a kpi_type where step01 emitted none"
    assert got[1]["kpi_type"] == "TT96-6.6.1", "stamping rewrote kpi_type (breaks node order)"


def test_step03c_stamp_is_idempotent():
    """Re-running over an already-stamped file must not change any decision."""
    triples = [_kpi_triple({"title": "Male employees", "unit": "người", "value": 775}),
               _kpi_triple({"title": "Lợi nhuận sau thuế", "unit": "tỷ đồng", "value": 1})]
    canonicalize_kpis(triples, Matcher(_DEFS, _ALIASES))
    first = [dict(t["subject"]["properties"]) for t in triples]
    canonicalize_kpis(triples, Matcher(_DEFS, _ALIASES))
    second = [t["subject"]["properties"] for t in triples]
    assert first == second, f"second pass changed the nodes:\n{first}\n{second}"


def test_step03c_goal_backfill_future_only():
    triples = [
        {"subject": {"class": "Goal", "properties":
                     {"name": "Giảm phát thải đến năm 2030", "valid_from": "2020"}},
         "predicate": "setsGoal",
         "object": {"class": "Organization", "properties": {"name": "X"}}},
        # a matched year in the PAST relative to valid_from must NOT become a target_date
        {"subject": {"class": "Goal", "properties":
                     {"name": "Hoàn thành đến năm 2015", "valid_from": "2020"}},
         "predicate": "setsGoal",
         "object": {"class": "Organization", "properties": {"name": "X"}}},
    ]
    stats = backfill_goal_target_date(triples)
    assert triples[0]["subject"]["properties"]["target_date"] == "2030"
    assert "target_date" not in triples[1]["subject"]["properties"]
    assert stats["filled"] == 1 and stats["rejected_not_in_future"] == 1


def _mini_graph():
    # KPIObservation already carrying a canonical kpi_id + a self-reported-zero Penalty
    return {"nodes": [
        {"class": "KPIObservation", "properties": {"kpi_id": "TT96-6.1.1", "title": "GHG",
                                                    "valid_from": "2020"}},
        {"class": "Penalty", "properties": {"penalty_id": "AAA_2022_EnvPenalty_0times",
                                            "amount": 0, "valid_from": "2022"}},
    ], "edges": []}


def test_step05c_add_edge_direction_and_idempotency():
    ec, el, ed = _SCHEMA_SETS
    g = _mini_graph()
    gp = GraphPatch(g, ec, el, ed)
    si = {"class": "StandardIndicator", "properties": {"id": "TT96-6.1.1", "name": "GHG"}}
    idx, created = gp.ensure_node(si)
    assert created
    # ensure_node is idempotent — same identity does not duplicate
    idx2, created2 = gp.ensure_node(dict(si))
    assert idx2 == idx and not created2
    # legal measuredUnder direction is accepted
    assert gp.add_edge(0, "measuredUnder", idx, {"valid_from": "2020", "valid_to": None,
                                                 "recorded_at": "2026-01-01"})
    # re-adding the same edge is a no-op (dedup)
    assert not gp.add_edge(0, "measuredUnder", idx, {"valid_from": "2020", "valid_to": None,
                                                     "recorded_at": "2026-01-01"})
    # illegal direction (StandardIndicator -measuredUnder-> KPIObservation) is rejected
    assert not gp.add_edge(idx, "measuredUnder", 0, {"valid_from": None, "valid_to": None,
                                                     "recorded_at": "2026-01-01"})
    # append-only: the two original nodes are untouched in place
    assert [n["class"] for n in g["nodes"][:2]] == ["KPIObservation", "Penalty"]


def test_step05c_doc_key_and_keyword_tier():
    assert doc_key_for("TT96-6.1.1") == ("TT96", "Regulation")
    assert doc_key_for("SSCIFC-E2") == ("SSCIFC", "Standard")
    assert doc_key_for("GRI 305-1") is None
    # The catalog is passed in now rather than read from a module global, so this
    # helper-level check runs against the KEYWORDS table alone -- no 152 KB of GRI
    # titles leaking in and changing which phrase wins.
    kw = build_keyword_index(_DEFS, {})
    # unambiguous keyword resolves
    assert match_keyword("Chúng tôi giảm phát thải khí nhà kính", kw) == "TT96-6.1.1"
    # generic text resolves to nothing (no false alignment)
    assert match_keyword("Công ty phát triển bền vững", kw) is None


def test_step05_standards_anchor_fixes_class_and_relabels_edge():
    # The SSC-IFC bug, reproduced: a document mention gets extracted with the wrong class
    # (here "Regulation" for what the registry says is a "Standard"). consolidate() must let
    # the registry's `kind` — not whichever member "wins" by prop_completeness — decide the
    # merged node's class, and must relabel any subjectToRegulation edge pointing at it to
    # adoptsStandard so the pipeline never regenerates the illegal-edge bug on a fresh run.
    nodes = [
        {"class": "Organization", "properties": {"name": "AAA"}},
        {"class": "Regulation", "properties": {"name": "SSC-IFC Guide", "jurisdiction": "Vietnam"}},
    ]
    edges = [{"subject": 0, "predicate": "subjectToRegulation", "object": 1,
             "temporal_metadata": {"valid_from": "2020", "valid_to": None,
                                   "recorded_at": "2026-01-01"}}]
    dsu = DSU(2)
    standards_tag = {dsu.find(1): ("SSC-IFC Guide", "Standard")}
    resolved, dstats = consolidate(nodes, edges, dsu, {}, standards_tag)
    doc_node = next(n for n in resolved["nodes"] if n["class"] in ("Standard", "Regulation"))
    assert doc_node["class"] == "Standard"
    (edge,) = resolved["edges"]
    assert edge["predicate"] == "adoptsStandard"
    assert dstats["doc_edges_relabeled"] == 1


def test_step08_stable_id_survives_reorder():
    graph = {"nodes": [
        {"class": "SustainabilityClaim", "properties": {"claim_id": "c1", "description": "d1"}},
        {"class": "MediaReport", "properties": {"report_id": "r1", "title": "Bài báo độc lập X"}},
    ], "edges": []}
    by_claim, by_text = build_key_index(graph)
    # claim resolves by its stable claim_id, not by array position
    dossier = {"claim_id": "c1", "claim_node_index": 999}
    ck, how = resolve_claim(dossier, by_claim)
    assert ck == "n0" and how == "stable_id"
    # evidence resolves by (class, text) when node_index is stale
    ev = {"class": "MediaReport", "text": "Bài báo độc lập X", "node_index": 999}
    ek, how = resolve_evidence(ev, by_text)
    assert ek == "n1" and how == "text"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
