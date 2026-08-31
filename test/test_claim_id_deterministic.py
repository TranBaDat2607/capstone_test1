#!/usr/bin/env python3
"""
GRAPH_IMPROVEMENT_PLAN.md C1 / GitHub issue #2 — deterministic `claim_id`.

WHY THIS TEST EXISTS
`SustainabilityClaim`'s `identity_keys` is exactly `["claim_id"]` (config/schema.json),
and `get_stable_entity_id` (esg_kg/core/identity.py) hashes a node's identity straight
off that property. Today `claim_id` is whatever free-text string the LLM invents in
`extract_triples`'s prompt (TEMPORAL_GRAPH_PROMPT_TEMPLATE only tells it to leave the
*value* as-is, never how to construct it) — so re-running step02 over the exact same
source sentence can mint a different `claim_id` and silently re-partition every one of
the 1,093 already-paid crosscheck dossiers (DESIGN.md §1.1 / GRAPH_IMPROVEMENT_PLAN.md
§1.1: claim resolution in `load/neo4j_sync.py` is 100% `stable_id` tier — there is no
fallback).

This test drives `assign_deterministic_claim_ids` / `make_deterministic_claim_id`
(esg_kg.graph.extract_triples) directly on synthetic triples — no LLM, no network — and
against the real resolved graph already on disk for a non-vacuous uniqueness check.

Offline: no LLM, no Neo4j, no network. Run from the repo root:

    python test/test_claim_id_deterministic.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.graph.extract_triples import (  # noqa: E402
    assign_deterministic_claim_ids,
    make_deterministic_claim_id,
    match_claim_sentence_anchors,
    triple_list_to_graph,
)
from esg_kg.core.io_jsonl import load_pages_from_jsonl  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
RESOLVED_GRAPH = REPO / "graph_output" / "resolved" / "resolved_graph.json"
LABELED_JSONL = REPO / "data" / "labeled" / "annual_labeled" / "labeled_annual_report_company_aaa.jsonl"


def load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def _claim_triple(claim_id: str, description: str) -> dict:
    return {
        "subject": {"class": "Organization", "properties": {
            "name": "CTCP Nhựa An Phát Xanh", "valid_from": "2023", "valid_to": None, "is_current": True,
        }},
        "predicate": "claims",
        "object": {"class": "SustainabilityClaim", "properties": {
            "claim_id": claim_id, "description": description, "date": "2023",
            "valid_from": "2023-01-01", "valid_to": None, "is_current": True,
        }},
        "temporal_metadata": {"valid_from": "2023-01-01", "valid_to": None, "recorded_at": "2023-01-01"},
    }


def test_same_source_sentence_same_id_despite_llm_drift():
    """Two 'runs' over the identical source sentence, where the LLM invents a
    DIFFERENT free-text claim_id each time (and slightly different whitespace/case in
    the description) — the deterministic id must come out identical both times."""
    run1 = [_claim_triple("aaa_claim_01", "Chúng tôi cam kết giảm phát thải carbon vào năm 2025.")]
    run2 = [_claim_triple("commitment-carbon-2025", "chúng tôi cam kết giảm phát thải carbon vào năm 2025.  ")]

    assign_deterministic_claim_ids(run1, "AAA_Baocaothuongnien_2023", 12)
    assign_deterministic_claim_ids(run2, "AAA_Baocaothuongnien_2023", 12)

    id1 = run1[0]["object"]["properties"]["claim_id"]
    id2 = run2[0]["object"]["properties"]["claim_id"]
    assert id1 == id2, f"same (doc, page, sentence) must yield the same claim_id, got {id1!r} vs {id2!r}"
    assert id1 != "aaa_claim_01" and id1 != "commitment-carbon-2025", \
        "the LLM-invented claim_id must be discarded, not echoed back"


def test_different_description_different_id():
    """Two genuinely different claims on the same page must not collide."""
    triples = [
        _claim_triple("x", "Chúng tôi cam kết giảm phát thải carbon vào năm 2025."),
        _claim_triple("y", "Chúng tôi cam kết sử dụng 100% năng lượng tái tạo vào năm 2030."),
    ]
    assign_deterministic_claim_ids(triples, "AAA_Baocaothuongnien_2023", 12)
    id_a = triples[0]["object"]["properties"]["claim_id"]
    id_b = triples[1]["object"]["properties"]["claim_id"]
    assert id_a != id_b, "different claim text on the same page must get different ids"


def test_different_page_different_id_for_same_text():
    """The same boilerplate sentence repeated on two different pages is two distinct
    claim occurrences, not one node — page is part of the identity basis."""
    same_text = "Chúng tôi cam kết phát triển bền vững."
    t1 = _claim_triple("a", same_text)
    t2 = _claim_triple("b", same_text)
    assign_deterministic_claim_ids([t1], "AAA_Baocaothuongnien_2023", 5)
    assign_deterministic_claim_ids([t2], "AAA_Baocaothuongnien_2023", 9)
    assert t1["object"]["properties"]["claim_id"] != t2["object"]["properties"]["claim_id"]


def test_only_sustainabilityclaim_entities_are_touched():
    """The rewrite must not clobber unrelated properties on other classes that happen
    to sit in the same triple (e.g. Organization has no claim_id at all)."""
    triples = [_claim_triple("x", "Cam kết bảo vệ môi trường.")]
    assign_deterministic_claim_ids(triples, "AAA_Baocaothuongnien_2023", 3)
    assert "claim_id" not in triples[0]["subject"]["properties"]


def test_multiple_triples_same_claim_merge_into_one_node():
    """Within one page, the same claim mentioned across two different edges (subject
    in one triple, object in another) must resolve to ONE graph node once claim_id is
    made deterministic — proving the fix actually prevents the fan-out, not just
    changes the string."""
    desc = "Chúng tôi cam kết giảm phát thải carbon vào năm 2025."
    triples = [
        _claim_triple("llm-made-up-id-1", desc),
        {
            "subject": {"class": "SustainabilityClaim", "properties": {
                "claim_id": "llm-made-up-id-2", "description": desc, "date": "2023",
                "valid_from": "2023-01-01", "valid_to": None, "is_current": True,
            }},
            "predicate": "hasKeyword",
            "object": {"class": "ClaimKeyword", "properties": {
                "name": "carbon", "valid_from": "2023-01-01", "valid_to": None, "is_current": True,
            }},
            "temporal_metadata": {"valid_from": "2023-01-01", "valid_to": None, "recorded_at": "2023-01-01"},
        },
    ]
    assign_deterministic_claim_ids(triples, "AAA_Baocaothuongnien_2023", 12)
    schema = load_schema()
    graph = triple_list_to_graph(triples, schema)
    claim_nodes = [n for n in graph["nodes"] if n["class"] == "SustainabilityClaim"]
    assert len(claim_nodes) == 1, f"expected the two mentions to merge into one node, got {len(claim_nodes)}"


def test_make_deterministic_claim_id_is_a_pure_function():
    a = make_deterministic_claim_id("doc.pdf", 4, "some claim text")
    b = make_deterministic_claim_id("doc.pdf", 4, "some claim text")
    c = make_deterministic_claim_id("doc.pdf", 4, "some OTHER claim text")
    assert a == b
    assert a != c


def test_real_corpus_claim_ids_stay_unique():
    """Recompute the deterministic id for every SustainabilityClaim node already in
    resolved_graph.json (which carries source_doc/source_page/description from the
    provenance patch) and assert the new scheme does not collide any of the 1,217
    currently-unique real claims (GRAPH_IMPROVEMENT_PLAN.md §4/C1: 'phải duy nhất trên
    corpus thật ... không được làm tệ đi')."""
    if not RESOLVED_GRAPH.exists():
        print("  (skip: graph_output/resolved/resolved_graph.json not present locally)")
        return
    data = json.loads(RESOLVED_GRAPH.read_text(encoding="utf-8"))
    claims = [n for n in data["nodes"] if n.get("class") == "SustainabilityClaim"]
    assert claims, "expected real SustainabilityClaim nodes in resolved_graph.json"

    old_ids = {c["properties"].get("claim_id") for c in claims}
    new_ids = {
        make_deterministic_claim_id(
            c["properties"].get("source_doc", ""),
            c["properties"].get("source_page", 0),
            c["properties"].get("description", ""),
            c["properties"].get("date", ""),
        )
        for c in claims
    }
    assert len(old_ids) == len(claims), "sanity: today's claim_id is already unique per node"
    assert len(new_ids) == len(claims), (
        f"deterministic scheme must not collide real claims: {len(claims)} nodes -> "
        f"{len(new_ids)} unique ids"
    )


LONG_ROW = (
    "Trong năm 2023, Hội đồng quản trị cùng Ban điều hành Công ty đã chỉ đạo các "
    "phòng chức năng thực hiện nhiều hoạt động xã hội có ý nghĩa, trong đó tiêu biểu "
    "là chương trình cam kết giảm phát thải carbon và sử dụng năng lượng tái tạo "
    "trong toàn bộ dây chuyền sản xuất của nhà máy."
)
UNRELATED_ROW_SHARING_WORDS = (
    "Công ty là một trong những doanh nghiệp sản xuất bao bì hàng đầu tại Việt Nam "
    "với nhiều năm kinh nghiệm trong lĩnh vực sản xuất, đã thiết lập được mối quan hệ "
    "kinh doanh tốt đẹp với nhiều đối tác và tập đoàn nổi tiếng."
)


def _page_rows(*texts: str) -> list:
    return [(i + 1, t, True) for i, t in enumerate(texts)]


def test_two_wordings_of_the_same_sentence_get_the_same_claim_id():
    """Core deliverable: two 'runs' where the LLM excerpts the SAME underlying
    sentence differently (different truncation point / trailing punctuation) must
    still resolve to the same claim_id, because both excerpts anchor to the same
    (sentence_index, start_offset) inside the real page text."""
    rows = _page_rows(LONG_ROW)
    desc_run1 = "chương trình cam kết giảm phát thải carbon và sử dụng năng lượng tái tạo"
    desc_run2 = "chương trình cam kết giảm phát thải carbon và sử dụng năng lượng tái tạo trong toàn bộ dây chuyền sản xuất"

    t1 = [_claim_triple("llm-id-1", desc_run1)]
    t2 = [_claim_triple("llm-id-2", desc_run2)]
    assign_deterministic_claim_ids(t1, "AAA_Baocaothuongnien_2023", 12, page_rows=rows)
    assign_deterministic_claim_ids(t2, "AAA_Baocaothuongnien_2023", 12, page_rows=rows)

    id1 = t1[0]["object"]["properties"]["claim_id"]
    id2 = t2[0]["object"]["properties"]["claim_id"]
    assert id1 == id2, f"two excerpts of the same sentence must match, got {id1!r} vs {id2!r}"

    text_only_id = make_deterministic_claim_id("AAA_Baocaothuongnien_2023", 12, desc_run1, "2023")
    assert id1 != text_only_id, "the position-anchored id must differ from the plain text-hash fallback"


def test_multiple_distinct_claims_in_one_enumeration_sentence_same_date_do_not_collide():
    """Real-corpus danger case this design exists to fix: one sentence enumerates
    several different facts/awards, all reported for the SAME year — hashing on
    sentence_index alone (even with date) collided 40/1217 real claims; the
    (sentence_index, start_offset) anchor must keep them distinct."""
    row = "Top 30 doanh nghiệp minh bạch nhất HNX - Sao vàng đất Việt - Thương hiệu mạnh - Bằng khen của Uỷ ban nhân dân tỉnh."
    rows = _page_rows(row)
    triples = [
        _claim_triple("a", "Sao vàng đất Việt"),
        _claim_triple("b", "Thương hiệu mạnh"),
        _claim_triple("c", "Bằng khen của Uỷ ban nhân dân tỉnh"),
    ]
    assign_deterministic_claim_ids(triples, "AAA_Baocaothuongnien_2015", 4, page_rows=rows)
    ids = [t["object"]["properties"]["claim_id"] for t in triples]
    assert len(set(ids)) == 3, f"three distinct awards in one enumeration sentence must not collide: {ids}"


def test_match_rejects_unrelated_row_sharing_common_words():
    """A same-page row that shares generic vocabulary but not the actual claimed
    content must not be picked as a match (the contiguity requirement guard)."""
    desc = "chương trình cam kết giảm phát thải carbon và sử dụng năng lượng tái tạo"
    rows = _page_rows(UNRELATED_ROW_SHARING_WORDS)
    anchors = match_claim_sentence_anchors(desc, rows)
    assert anchors == [], f"unrelated row sharing only common words must not match, got {anchors}"


def test_short_description_skips_matching_and_uses_fallback():
    """A description below the minimum token gate must route straight to the
    already-tested text-hash fallback, matching page_rows=None exactly."""
    rows = _page_rows(LONG_ROW)
    desc = "cam kết"  # 2 tokens, below MIN_CLAIM_DESC_TOKENS_FOR_MATCH
    anchors = match_claim_sentence_anchors(desc, rows)
    assert anchors == [], "a too-short description must not attempt matching at all"

    with_rows = [_claim_triple("x", desc)]
    without_rows = [_claim_triple("x", desc)]
    assign_deterministic_claim_ids(with_rows, "AAA_Baocaothuongnien_2023", 12, page_rows=rows)
    assign_deterministic_claim_ids(without_rows, "AAA_Baocaothuongnien_2023", 12, page_rows=None)
    assert (with_rows[0]["object"]["properties"]["claim_id"]
            == without_rows[0]["object"]["properties"]["claim_id"])


def test_cross_language_description_falls_back_deterministically():
    """The real historical pre-'issue #6' case: an English description drawn from a
    Vietnamese source sentence cannot token-match (~0 overlap) — must fall back, and
    stay deterministic across repeated calls through that fallback path."""
    rows = _page_rows(LONG_ROW)
    desc = "implemented many meaningful social activities for employees after work"
    anchors = match_claim_sentence_anchors(desc, rows)
    assert anchors == [], "cross-language description must not falsely match a Vietnamese row"

    run1 = [_claim_triple("x", desc)]
    run2 = [_claim_triple("y", desc)]
    assign_deterministic_claim_ids(run1, "AAA_Baocaothuongnien_2011", 10, page_rows=rows)
    assign_deterministic_claim_ids(run2, "AAA_Baocaothuongnien_2011", 10, page_rows=rows)
    assert (run1[0]["object"]["properties"]["claim_id"]
            == run2[0]["object"]["properties"]["claim_id"])


def test_real_corpus_sentence_anchoring_stays_unique():
    """Extends test_real_corpus_claim_ids_stay_unique with the sentence-anchoring
    layer engaged: recompute every real claim's id using its page's real JSONL rows
    and assert the 1,217 real claims are still all unique (must not regress)."""
    if not RESOLVED_GRAPH.exists() or not LABELED_JSONL.exists():
        print("  (skip: resolved_graph.json or labeled JSONL not present locally)")
        return
    docs = load_pages_from_jsonl(LABELED_JSONL)
    rows_by_doc_page = {}
    for src, pages in docs.items():
        doc_key = src[:-4] if src.endswith(".pdf") else src
        for page, rows in pages.items():
            rows_by_doc_page[(doc_key, page)] = rows

    data = json.loads(RESOLVED_GRAPH.read_text(encoding="utf-8"))
    claims = [n for n in data["nodes"] if n.get("class") == "SustainabilityClaim"]
    assert claims, "expected real SustainabilityClaim nodes in resolved_graph.json"

    new_ids = set()
    for c in claims:
        props = c["properties"]
        doc, page = props.get("source_doc", ""), props.get("source_page", 0)
        description, date = props.get("description", ""), props.get("date", "")
        page_rows = rows_by_doc_page.get((doc, page), [])
        anchors = match_claim_sentence_anchors(description, page_rows) if page_rows else None
        new_ids.add(make_deterministic_claim_id(doc, page, description, date, sentence_anchors=anchors))

    assert len(new_ids) == len(claims), (
        f"sentence-anchored scheme must not collide real claims: {len(claims)} nodes -> "
        f"{len(new_ids)} unique ids"
    )


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
