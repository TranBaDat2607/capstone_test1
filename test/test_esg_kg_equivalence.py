#!/usr/bin/env python3
"""
Old-vs-new equivalence checks for the `src/` -> `src_module/esg_kg/` refactor.

This is the safety net for Model A (see CLAUDE.md "Active refactor"): the old
`src/step*.py` pipeline is deliberately left untouched, so every helper pulled
into `esg_kg.core` exists in BOTH trees at once. Nothing stops the two copies
drifting except this file — it imports both, runs them on the same real input,
and asserts the results are equal.

Written test-first: an arm is added here BEFORE the corresponding `esg_kg.core`
module is extracted, so it fails (ImportError) until the extraction lands.

Offline: no LLM, no Neo4j, no network. `config/schema.json` is tracked in git so
the core arms always run; arms that need git-ignored artifacts (graph_output/,
shipped via the HF snapshot) SKIP with a message on a bare clone.

ONE core module is deliberately compared elsewhere: `esg_kg.core.console`. Its arm
lives in `test/test_console_utf8.py`, because proving the two copies equal needs
`sys.platform` / `sys.stdout` swapped out, and because the same file also asserts
the WIRING (that main() calls it). That is the hole this file structurally cannot
cover — it never executes a `__main__` block or a main(), which is exactly how the
win32 stdout fix came to exist in `src/` only. Do not add a duplicate arm here.

Run from the repo root:

    python test/test_esg_kg_equivalence.py
"""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ scripts ------------------------------------------------
import step00_graph_quality_report as old_step00  # noqa: E402
import step01_extract_kpi_from_jsonl as old_step01  # noqa: E402
import step03c_canonicalize_kpis as old_step03c  # noqa: E402
import step02_extract_triplet_from_jsonl as old_step02  # noqa: E402
import step03_fix_invalid_triplets as old_step03  # noqa: E402
import step04_build_issuer_registry as old_step04  # noqa: E402
import step05c_link_standard_indicators as old_step05c  # noqa: E402

# --- new: the esg_kg package ---------------------------------------------------
from esg_kg.core import dates as new_dates  # noqa: E402
from esg_kg.core import graph_patch as new_graph_patch  # noqa: E402
from esg_kg.kpi import canonicalize as new_canonicalize  # noqa: E402
from esg_kg.core import naming as new_naming  # noqa: E402
from esg_kg.core import paths as new_paths  # noqa: E402
from esg_kg.core import schema as new_schema  # noqa: E402
from esg_kg.report import quality as new_quality  # noqa: E402
from esg_kg.resolve import indicators as new_indicators  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
TRIPLES_FILE = REPO / "graph_output" / "validated" / "all_validated_triples.json"
RESOLVED_FILE = REPO / "graph_output" / "resolved" / "resolved_graph.json"

# How many real triples to run through validate_triple. A cap, not a sample:
# drift shows up in the first few hundred, and the test must stay fast.
CORPUS_CAP = 5000

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


def org_names(triples: list) -> list:
    """Real Organization names from the corpus — the actual input normalize_name sees."""
    names = []
    for t in triples:
        for side in ("subject", "object"):
            node = t.get(side)
            if isinstance(node, dict) and node.get("class") == "Organization":
                n = (node.get("properties") or {}).get("name")
                if isinstance(n, str) and n.strip():
                    names.append(n)
    return names


# --------------------------------------------------------------------------- #
# core/paths.py  — REPO_ROOT and the constants stages copy-pasted identically
# --------------------------------------------------------------------------- #
def test_paths_repo_root_matches_src():
    # step01's `parents[1]` and the new marker-based lookup must land on the
    # same directory — this is the single anchor every stage path is built from.
    assert new_paths.REPO_ROOT == old_step01.REPO_ROOT, (
        f"{new_paths.REPO_ROOT} != {old_step01.REPO_ROOT}"
    )
    assert new_paths.REPO_ROOT == REPO


def test_paths_constants_match_src():
    assert new_paths.KPI_DEFS_PATH == old_step01.DEFAULT_KPI_DEFS
    assert new_paths.KPI_OUTPUT_DIR == old_step01.DEFAULT_OUT_DIR
    assert new_paths.SCHEMA_PATH == SCHEMA_FILE
    assert new_paths.SCHEMA_PATH.exists()
    assert new_paths.VALIDATED_DIR == TRIPLES_FILE.parent


def test_paths_root_override_is_validated():
    # New behaviour (no src/ equivalent): the escape hatch must still verify the
    # marker, so a typo'd ESG_KG_REPO_ROOT fails loudly instead of silently
    # pointing every stage at the wrong tree.
    import os

    prev = os.environ.get("ESG_KG_REPO_ROOT")
    os.environ["ESG_KG_REPO_ROOT"] = str(REPO / "config")  # a dir, but not a root
    try:
        raised = False
        try:
            new_paths._resolve_repo_root()
        except RuntimeError:
            raised = True
        assert raised, "a non-root ESG_KG_REPO_ROOT must raise, not be accepted"
    finally:
        if prev is None:
            os.environ.pop("ESG_KG_REPO_ROOT", None)
        else:
            os.environ["ESG_KG_REPO_ROOT"] = prev


# --------------------------------------------------------------------------- #
# core/schema.py  — load_schema_sets, validate_triple, get_identity_keys
# --------------------------------------------------------------------------- #
def test_schema_load_schema_sets_matches_src():
    schema = load_schema()
    assert new_schema.load_schema_sets(schema) == old_step03.load_schema_sets(schema)


def test_schema_get_identity_keys_matches_src():
    schema = load_schema()
    assert new_schema.get_identity_keys(schema) == old_step02.get_identity_keys(schema)


def test_schema_validate_triple_matches_src_on_edge_cases():
    """Malformed shapes, hand-built so this arm runs on a bare clone too."""
    schema = load_schema()
    ec, el, ed = new_schema.load_schema_sets(schema)

    ok_props = {"name": "X", "valid_from": "2020", "valid_to": None, "is_current": True}
    tm = {"valid_from": "2020", "valid_to": None, "recorded_at": "2020"}
    cases = [
        "not a dict",
        {},
        {"subject": None, "predicate": "publishesReport", "object": None},
        {"subject": {"class": "Organization", "properties": ok_props},
         "predicate": "publishesReport",
         "object": {"class": "Report", "properties": dict(ok_props)},
         "temporal_metadata": tm},
        # reversed direction
        {"subject": {"class": "Report", "properties": dict(ok_props)},
         "predicate": "publishesReport",
         "object": {"class": "Organization", "properties": ok_props},
         "temporal_metadata": tm},
        # unknown class / predicate
        {"subject": {"class": "NotAClass", "properties": dict(ok_props)},
         "predicate": "publishesReport",
         "object": {"class": "Report", "properties": dict(ok_props)},
         "temporal_metadata": tm},
        {"subject": {"class": "Organization", "properties": ok_props},
         "predicate": "notAPredicate",
         "object": {"class": "Report", "properties": dict(ok_props)},
         "temporal_metadata": tm},
        # missing temporal fields
        {"subject": {"class": "Organization", "properties": {"name": "X"}},
         "predicate": "publishesReport",
         "object": {"class": "Report", "properties": dict(ok_props)}},
    ]
    for i, case in enumerate(cases):
        assert new_schema.validate_triple(case, ec, el, ed) == \
               old_step03.validate_triple(case, ec, el, ed), f"case {i}: {case!r}"


def test_schema_validate_triple_matches_src_on_real_corpus():
    triples = load_triples()
    if not triples:
        _skip("validate_triple/corpus", f"{TRIPLES_FILE.name} absent (run data_sync pull)")
        return
    schema = load_schema()
    ec, el, ed = new_schema.load_schema_sets(schema)
    checked = 0
    for t in triples[:CORPUS_CAP]:
        assert new_schema.validate_triple(t, ec, el, ed) == \
               old_step03.validate_triple(t, ec, el, ed), f"mismatch on triple #{checked}"
        checked += 1
    print(f"     ({checked} real triples compared)")


# --------------------------------------------------------------------------- #
# core/naming.py  — normalize_name, name_tokens, merge_preserving_edits
# --------------------------------------------------------------------------- #
def test_naming_normalize_name_matches_src():
    """Hand-picked cases covering every transform normalize_name applies."""
    cases = [
        None, "", 0, "   ",
        "Công ty Cổ phần Nhựa An Phát Xanh",
        "CTCP Nhua An Phat Xanh",
        "AN PHAT XANH PLASTICS JOINT STOCK COMPANY",
        "Tổng Công ty Đầu tư Phát triển Đô thị",       # đ + longest-first legal form
        "Cty TNHH Ƣu Việt",                             # OCR chars
        "An Phát  Xanh   ,  JSC.",                      # punctuation + whitespace
        "Green Plastics Co Ltd",                        # SYNONYMS: green->xanh, plastics->plastic
        "  CÔNG TY CỔ PHẦN  ",                          # legal form is the whole string
        "Đđ Ưư",
        123,
    ]
    for c in cases:
        assert new_naming.normalize_name(c) == old_step04.normalize_name(c), f"case {c!r}"


def test_naming_normalize_name_matches_src_on_real_names():
    triples = load_triples()
    if not triples:
        _skip("normalize_name/corpus", f"{TRIPLES_FILE.name} absent (run data_sync pull)")
        return
    names = org_names(triples[:CORPUS_CAP])
    if not names:
        _skip("normalize_name/corpus", "no Organization names in the corpus slice")
        return
    for n in names:
        assert new_naming.normalize_name(n) == old_step04.normalize_name(n), f"name {n!r}"
    print(f"     ({len(set(names))} distinct real Organization names compared)")


def test_naming_name_tokens_matches_src():
    for c in [None, "", "Công ty Cổ phần Nhựa An Phát Xanh", "CTCP", "Green Plastics Ltd"]:
        assert new_naming.name_tokens(c) == old_step04.name_tokens(c), f"case {c!r}"


def test_naming_merge_preserving_edits_matches_src():
    new_reg = {
        "ticker": "AAA",
        "canonical_name": "CTCP Nhựa An Phát Xanh",
        "core_tokens": ["an", "phat", "xanh"],
        "aliases": ["nhua an phat xanh", "an phat xanh"],
        "exclusions": [{"name": "an phat holdings", "reason": "parent"}],
        "needs_review": [{"name": "an phat bioplastics", "hits": 3},
                         {"name": "nhua an phat xanh", "hits": 9},
                         {"name": "an phat holdings", "hits": 2}],
    }
    old_reg = {
        # human edits that must survive
        "canonical_name": "Công ty Cổ phần Nhựa An Phát Xanh",
        "aliases": ["aaa", "an phat xanh jsc"],
        "exclusions": [{"name": "an phat holdings", "reason": "CONFIRMED separate legal entity"},
                       {"name": "an phat bioplastics", "reason": "subsidiary"}],
        "needs_review": [],
    }
    assert new_naming.merge_preserving_edits(old_reg, new_reg) == \
           old_step04.merge_preserving_edits(old_reg, new_reg)

    # empty prior registry (the first-run path)
    empty = {"aliases": [], "exclusions": [], "needs_review": []}
    assert new_naming.merge_preserving_edits(empty, new_reg) == \
           old_step04.merge_preserving_edits(empty, new_reg)


def test_naming_constants_match_src():
    # normalize_name is only as stable as the tables it reads; drift in these is
    # exactly the failure this file exists to catch.
    assert new_naming.OCR_FIXES == old_step04.OCR_FIXES
    assert new_naming.LEGAL_FORMS == old_step04.LEGAL_FORMS
    assert new_naming.SYNONYMS == old_step04.SYNONYMS


# --------------------------------------------------------------------------- #
# core/dates.py  — ISO_DATE_RE, normalize_date_string, date_start_key
# --------------------------------------------------------------------------- #
def test_dates_normalize_date_string_matches_src():
    """Every spelling the step02 LLM has been seen to emit, plus the reject paths."""
    cases = [
        None, "", "   ", "null", "NULL", "none", "None",
        "2011", "2011-3", "2011-03", "2011-1-3", "2011-01-03",     # ISO, zero-padding
        "2024-08-14T10:00:00", "2024-08-14T00:00:00Z",             # datetime -> date part
        "31/05/2023", "31-05-2023", "31.05.2023",                  # VN day-first
        "2023/05/31", "2023.05.31",                                # year-first
        "05/2023", "05-2023", "2023/05",                           # month + year
        "2023-13-01", "2023-00-01", "2023-01-32", "2023-01-00",    # out-of-range -> unparseable
        "Q2 2023", "quy 2 nam 2023", "garbage", "20230531",        # unrecognized -> unchanged
        2011, 0, True,                                             # non-str inputs
    ]
    for c in cases:
        assert new_dates.normalize_date_string(c) == old_step03.normalize_date_string(c), \
            f"case {c!r}"


def test_dates_date_start_key_matches_src():
    cases = [
        None, "", "null", "2011", "2011-01-01", "2011-03", "2011-03-15",
        "31/05/2023", "05/2023", "2024-08-14T10:00:00",
        "Q2 2023", "garbage", 2011,
    ]
    for c in cases:
        assert new_dates.date_start_key(c) == old_step03.date_start_key(c), f"case {c!r}"

    # the P4 collapse this function exists for, asserted on the NEW module:
    # "2011" and "2011-01-01" are one instant, not two versions
    assert new_dates.date_start_key("2011") == new_dates.date_start_key("2011-01-01")


def test_dates_constants_match_src():
    assert new_dates.ISO_DATE_RE.pattern == old_step03.ISO_DATE_RE.pattern
    # the private table normalize_date_string reads must move with it
    assert [p.pattern for p, _ in new_dates._DATE_PATTERNS] == \
           [p.pattern for p, _ in old_step03._DATE_PATTERNS]
    assert [g for _, g in new_dates._DATE_PATTERNS] == \
           [g for _, g in old_step03._DATE_PATTERNS]


def test_dates_matches_src_on_real_corpus():
    """Every date string the real graph actually carries — node validity and edge
    temporal_metadata alike."""
    triples = load_triples()
    if not triples:
        _skip("dates/corpus", f"{TRIPLES_FILE.name} absent (run data_sync pull)")
        return
    values = []
    for t in triples[:CORPUS_CAP]:
        for side in ("subject", "object"):
            node = t.get(side)
            if isinstance(node, dict):
                props = node.get("properties") or {}
                values += [props.get("valid_from"), props.get("valid_to")]
        tm = t.get("temporal_metadata")
        if isinstance(tm, dict):
            values += [tm.get("valid_from"), tm.get("valid_to"), tm.get("recorded_at")]
    for v in values:
        assert new_dates.normalize_date_string(v) == old_step03.normalize_date_string(v), \
            f"normalize_date_string({v!r})"
        assert new_dates.date_start_key(v) == old_step03.date_start_key(v), \
            f"date_start_key({v!r})"
    print(f"     ({len(set(map(repr, values)))} distinct real date values compared)")


# --------------------------------------------------------------------------- #
# report/quality.py  — step00. The first whole STAGE moved, not just a helper.
#
# A stage has no single return value to compare, so equivalence is asserted on
# the three things that actually define it: the module constants (the T1/T2/T3
# tier map is a contract other files import), every Q1-Q8 metric function, and
# the rendered Markdown.
#
# Q7's BFS arms cost ~44s per call on the real 10k-node graph (measured), so the
# real-corpus arm runs with skip_slow=True and the (c)/(d) BFS is covered by the
# synthetic graph below instead, where it is instant. That synthetic graph is
# also what lets these arms run on a bare clone.
# --------------------------------------------------------------------------- #
def mini_graph() -> tuple:
    """A hand-built graph that trips EVERY counter step00 reports.

    Node indices are load-bearing: edges address nodes by position, and Q7
    walks that adjacency. `test_quality_mini_graph_is_not_vacuous` guards the
    intent — if a future edit flattens this into all-zero metrics, the
    comparison would still "pass" while testing nothing.
    """
    def rep(**kw):
        return dict(source_type="report", **kw)

    def news(**kw):
        return dict(source_type="news", **kw)

    nodes = [
        # 0: the hub (highest degree, excluded from Q7(d) paths)
        {"class": "Organization", "properties": rep(name="CTCP Nhựa An Phát Xanh", valid_from="2020")},
        # 1+? Q3: 1 and 14 normalize to the same key -> one surplus duplicate
        {"class": "Organization", "properties": rep(name="An Phát Xanh JSC", valid_from="2020")},
        {"class": "Facility", "properties": rep(name="Nhà máy Hải Dương", valid_from="2020")},
        # 3: Q1 broken-OCR char (Ƣ, seen in real PDF extraction)
        {"class": "Facility", "properties": rep(name="Nhà máy MÔI TRƢỜNG", valid_from="2020")},
        # 4: Q1 non-NFC name — written DECOMPOSED (combining diacritics) on purpose,
        #    which is what unnormalized PDF text extraction actually produces
        {"class": "Facility", "properties": rep(name="Nhà máy Bà Rịa", valid_from="2020")},
        # 5: report-side KPI, parseable source_id
        {"class": "KPIObservation", "properties": rep(name="Điện tiêu thụ", valid_from="2023",
                                                      source_id="AAA_2023_labeled_12_3")},
        # 6: news-side KPI = conduct; NO date_uncertain (Q2 counter) and no valid_from (Q5)
        {"class": "KPIObservation", "properties": news(name="Nước thải", source_id="news-article-xyz")},
        {"class": "Controversy", "properties": news(name="Xả thải vượt chuẩn", valid_from="2024-03",
                                                    date_uncertain=True)},
        # 8: Q2 non-canonical date spelling
        {"class": "Penalty", "properties": news(name="Phạt hành chính", valid_from="31/05/2023",
                                                date_uncertain=False)},
        {"class": "MediaReport", "properties": news(name="Bài báo VnExpress", valid_from="2024-01-15",
                                                    publisher="VnExpress", date_uncertain=False)},
        {"class": "SustainabilityClaim", "properties": rep(claim_id="AAA-C-001", valid_from="2023")},
        {"class": "SustainabilityClaim", "properties": rep(claim_id="AAA-C-002", valid_from="2023")},
        {"class": "ClaimKeyword", "properties": rep(term="phát thải", valid_from="2023")},
        # 13: REFERENCE_CLASSES — barred from Q7 hub/path metrics
        {"class": "StandardIndicator", "properties": rep(name="TT96-E1", valid_from="2020")},
        # 14: Q2 version chain with TWO is_current=true (P4 violation) + Q3 duplicate of node 1
        {"class": "Organization", "properties": rep(name="AN PHAT XANH , JSC.", valid_from="2019"),
         "temporal_versions": [
             {"valid_from": "2019", "valid_to": None, "is_current": True, "properties": {"name": "An Phat Xanh"}},
             {"valid_from": "2021", "valid_to": None, "is_current": True, "properties": {"name": "An Phat Xanh"}},
         ]},
        # 15: Q2 versions split ONLY by date spelling ("2011" vs "2011-01-01")
        {"class": "Organization", "properties": rep(name="An Phát Holdings", valid_from="2011"),
         "temporal_versions": [
             {"valid_from": "2011", "valid_to": None, "is_current": True, "properties": {"name": "An Phat Holdings"}},
             {"valid_from": "2011-01-01", "valid_to": None, "is_current": False, "properties": {"name": "An Phat Holdings"}},
         ]},
        # 16: isolated node (degree 0)
        {"class": "Product", "properties": rep(name="Bao bì phân hủy", valid_from="2022")},
        # 17: leaf (degree 1) — masking its only edge orphans it in Q7(c)
        {"class": "Person", "properties": {"name": "Nguyễn Văn A"}},
        {"class": "Location", "properties": {"name": "Hải Dương"}},
        # 19: Q2 valid_from > valid_to
        {"class": "Goal", "properties": {"name": "Giảm 20% phát thải", "valid_from": "2030", "valid_to": "2025"}},
    ]

    def ed(s, o, p, vf="2020", vt=None):
        return {"subject": s, "object": o, "predicate": p,
                "temporal_metadata": {"valid_from": vf, "valid_to": vt, "recorded_at": vf}}

    edges = [
        # Q7(c) branch 1: parallel SAME-label edges (multi-year) on pair (0,2)...
        ed(0, 2, "ownsFacility", "2020"),
        ed(0, 2, "ownsFacility", "2021"),
        # ...plus a DIFFERENT label on the same pair -> masking survives at 1 hop
        ed(2, 0, "partOf", "2020"),
        ed(0, 3, "ownsFacility"),
        ed(0, 4, "ownsFacility"),
        # the structural spine Q7(d) must find: 10 -> 5 -> 2 -> 6, hub-free
        ed(5, 2, "observedAtFacility", "2023"),
        ed(6, 2, "observedAtFacility", "2024"),
        ed(10, 5, "verifiedBy", "2023"),
        ed(10, 12, "hasKeyword", "2023"),
        ed(11, 12, "hasKeyword", "2023"),
        ed(11, 13, "alignsWithIndicator", "2023"),
        ed(10, 13, "alignsWithIndicator", "2023"),
        ed(5, 13, "measuredUnder", "2023"),
        ed(0, 9, "publishesReport", "2024"),
        # Q7(c) branch 2: masking this orphans node 17 (degree 1) -> unanswerable
        ed(9, 17, "reportedBy", "2024"),
        ed(0, 8, "subjectToPenalty", "2023"),
        ed(10, 7, "contradictedBy", "2024"),
        # Q7(c) branch 3: single-label pair with a 2-hop detour (2 -> 0 -> 18)
        ed(2, 18, "locatedIn"),
        ed(0, 18, "locatedIn"),
        ed(14, 2, "ownsFacility"),
        ed(15, 2, "ownsFacility"),
        # Q2 illegal edges: unknown predicate, and a legal label on an illegal pair
        ed(0, 1, "notARealEdgeLabel"),
        ed(19, 12, "alignsWithIndicator"),
    ]
    return nodes, edges


def mini_report(mod, schema: dict) -> dict:
    """Build step00's full report dict with the volatile fields pinned, so the
    two trees are compared on the metrics rather than on a timestamp."""
    nodes, edges = mini_graph()
    return {
        "label": "equivalence",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "graph_file": "graph_output/resolved/resolved_graph.json",
        "graph_mtime": "2026-01-01T00:00:00+00:00",
        "nodes": len(nodes),
        "edges": len(edges),
        "q1_accuracy": mod.q1_accuracy(nodes),
        "q2_consistency": mod.q2_consistency(nodes, edges, schema),
        "q3_conciseness": mod.q3_conciseness(nodes),
        "q4_completeness": mod.q4_completeness(nodes),
        "q5_timeliness": mod.q5_timeliness(nodes, edges),
        "q6_provenance": mod.q6_provenance(nodes),
        # skip_slow=False: the BFS arms are cheap here and nowhere else
        "q7_traversability": mod.q7_traversability(nodes, edges, 4, False),
        "q8_independence": mod.q8_independence(nodes),
    }


def test_quality_constants_match_src():
    """The tier map is a CONTRACT: test_schema_contract.py imports it rather than
    re-declaring it, so a silent drift here would quietly change what P1 lints."""
    for name in ("T1_CLASSES", "T2_CLASSES", "T3_CLASSES", "REFERENCE_CLASSES",
                 "CONDUCT_CLASSES", "TEMPORAL_IDENTITY_FIELDS", "STRUCTURAL_EDGES",
                 "BROKEN_CHARS", "DEFAULT_MAX_HOPS"):
        assert getattr(new_quality, name) == getattr(old_step00, name), f"constant {name}"


def test_quality_default_paths_match_src():
    # step00 built these from `REPO_ROOT / ...`; the module now takes them from
    # core.paths. Same files, or the stage writes its report somewhere new.
    assert new_quality.DEFAULT_GRAPH == old_step00.DEFAULT_GRAPH
    assert new_quality.DEFAULT_SCHEMA == old_step00.DEFAULT_SCHEMA
    assert new_quality.DEFAULT_OUT_DIR == old_step00.DEFAULT_OUT_DIR


def test_quality_helpers_match_src():
    nodes, _ = mini_graph()
    for nd in nodes:
        assert new_quality.node_name(nd) == old_step00.node_name(nd)
        assert new_quality.is_conduct(nd) == old_step00.is_conduct(nd)
        assert new_quality.is_news_t2(nd) == old_step00.is_news_t2(nd)
    for part, whole in [(0, 0), (0, 10), (1, 3), (7, 7), (13790, 10393)]:
        assert new_quality.pct(part, whole) == old_step00.pct(part, whole)


def test_quality_mini_graph_is_not_vacuous():
    """Guards the fixture, not the code: every counter the synthetic graph exists
    to exercise must actually be non-zero, or the equivalence arms below compare
    two piles of zeros and would miss real drift."""
    rep = mini_report(old_step00, load_schema())
    q2, q7 = rep["q2_consistency"], rep["q7_traversability"]
    for key in ("schema_illegal_edges", "non_canonical_date_values",
                "valid_from_after_valid_to", "version_chains_not_exactly_one_is_current",
                "versions_split_only_by_date_format", "news_t2_missing_date_uncertain"):
        assert q2[key] > 0, f"mini_graph no longer exercises q2.{key}"
    assert rep["q1_accuracy"]["nodes_with_non_nfc_name"] > 0
    assert rep["q1_accuracy"]["nodes_with_broken_ocr_chars"] > 0
    assert rep["q3_conciseness"]["total_surplus_duplicate_t1_nodes"] > 0
    assert rep["q4_completeness"]["controversy"] > 0 and rep["q4_completeness"]["penalty"] > 0
    assert rep["q7_traversability"]["isolated_nodes"] > 0
    assert q7["largest_hub"]["class"] == "Organization", "the hub must not be a StandardIndicator"
    # both BFS arms must land strictly between 0% and 100% — that is the only
    # proof the reachable AND unreachable branches are both walked
    for key in ("c_masked_queries_answerable_pct", "d_claims_structural_path_to_conduct_pct"):
        assert 0.0 < q7[key] < 100.0, f"q7.{key} = {q7[key]} exercises only one branch"


def test_quality_metrics_match_src_on_mini_graph():
    """Every Q1-Q8 function, including the Q7(c)/(d) BFS the real-graph arm skips."""
    schema = load_schema()
    assert mini_report(new_quality, schema) == mini_report(old_step00, schema)


def test_quality_render_markdown_matches_src():
    schema = load_schema()
    assert new_quality.render_markdown(mini_report(new_quality, schema)) == \
           old_step00.render_markdown(mini_report(old_step00, schema))


def test_quality_metrics_match_src_on_real_graph():
    """The resolved graph as it really is — 10k nodes of shapes no fixture invents.

    skip_slow=True: Q7(c)/(d) cost ~44s per call here (~88s for both trees), and
    the mini-graph arm above already compares them.
    """
    if not RESOLVED_FILE.exists():
        _skip("quality/real-graph", f"{RESOLVED_FILE.name} absent (run data_sync pull)")
        return
    graph = json.loads(RESOLVED_FILE.read_text(encoding="utf-8"))
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    schema = load_schema()
    assert new_quality.q1_accuracy(nodes) == old_step00.q1_accuracy(nodes)
    assert new_quality.q2_consistency(nodes, edges, schema) == old_step00.q2_consistency(nodes, edges, schema)
    assert new_quality.q3_conciseness(nodes) == old_step00.q3_conciseness(nodes)
    assert new_quality.q4_completeness(nodes) == old_step00.q4_completeness(nodes)
    assert new_quality.q5_timeliness(nodes, edges) == old_step00.q5_timeliness(nodes, edges)
    assert new_quality.q6_provenance(nodes) == old_step00.q6_provenance(nodes)
    assert new_quality.q7_traversability(nodes, edges, 4, True) == \
           old_step00.q7_traversability(nodes, edges, 4, True)
    assert new_quality.q8_independence(nodes) == old_step00.q8_independence(nodes)
    print(f"     ({len(nodes)} nodes / {len(edges)} edges compared, Q7 BFS skipped by design)")


# --------------------------------------------------------------------------- #
# step03c -> esg_kg.kpi.canonicalize  (STAGE arm)
# --------------------------------------------------------------------------- #
# A stage has no single return value, so — as with step00 — the arm compares the
# three things that define it: module constants, each pure function, and the full
# output produced on real input. The vocabulary inputs (kpi_definitions_construction
# .json, config/kpi_type_aliases.json) are BOTH tracked in git, so every arm except
# the corpus one runs on a bare clone.
KPI_DEFS_FILE = REPO / "kpi_definitions_construction.json"
KPI_ALIASES_FILE = REPO / "config" / "kpi_type_aliases.json"


def load_kpi_vocab():
    return (json.loads(KPI_DEFS_FILE.read_text(encoding="utf-8")),
            json.loads(KPI_ALIASES_FILE.read_text(encoding="utf-8")))


def kpi_props(triples: list) -> list:
    """Every KPIObservation property dict in the corpus — the real matcher input."""
    out = []
    for t in triples:
        for side in ("subject", "object"):
            node = t.get(side)
            if isinstance(node, dict) and node.get("class") == "KPIObservation":
                p = node.get("properties")
                if isinstance(p, dict):
                    out.append(p)
    return out


def test_canonicalize_constants_match_src():
    assert new_canonicalize.STANDARD_CODE_RE.pattern == old_step03c.STANDARD_CODE_RE.pattern
    assert new_canonicalize.DEFAULT_FUZZY_THRESHOLD == old_step03c.DEFAULT_FUZZY_THRESHOLD
    assert [p.pattern for p in new_canonicalize.GOAL_YEAR_PATTERNS] == \
           [p.pattern for p in old_step03c.GOAL_YEAR_PATTERNS]


def test_canonicalize_default_paths_match_src():
    for name in ("DEFAULT_TRIPLES", "DEFAULT_DEFS", "DEFAULT_ALIASES", "DEFAULT_STATS_OUT"):
        assert getattr(new_canonicalize, name) == getattr(old_step03c, name), name


def test_canonicalize_pure_helpers_match_src():
    titles = ["  Tiêu hao ĐIỆN năng  ", "Male employees", "", None,
              "Lợi nhuận sau thuế.", "(Tổng số lao động)", "nước thải — sản xuất"]
    for t in titles:
        assert new_canonicalize.normalize_title(t) == old_step03c.normalize_title(t), t
    for props in [{"year": 2012}, {"year": "2013"}, {"target_year": 2030},
                  {"valid_from": "2011-01-01"}, {"year": 99}, {}]:
        assert new_canonicalize.derive_period(props) == old_step03c.derive_period(props), props
    scales = {"nghìn m3": {"factor": 1000, "base": "m³"}, "mwh": {"factor": 1000, "base": "kWh"}}
    for value, unit in [(5, "nghìn m3"), (2.5, "MWh"), ("x", "MWh"), (5, "chưa biết")]:
        assert new_canonicalize.rescale_value(value, unit, scales) == \
               old_step03c.rescale_value(value, unit, scales), (value, unit)


def test_canonicalize_matcher_matches_src_on_the_whole_vocabulary():
    """Drive both matchers over every official name and every alias — not a sample."""
    defs, aliases = load_kpi_vocab()
    new_m, old_m = new_canonicalize.Matcher(defs, aliases), old_step03c.Matcher(defs, aliases)
    assert new_m.valid_ids == old_m.valid_ids
    assert new_m.exact == old_m.exact
    assert new_m.contains == old_m.contains
    assert new_m.reject_units == old_m.reject_units
    assert new_m.units_of == old_m.units_of

    probes = [(d["name"], "") for d in defs]
    for rule in aliases.get("rules") or []:
        units = rule.get("units") or [""]
        for t in (rule.get("exact") or []) + (rule.get("contains") or []):
            probes.append((t, units[0]))
    probes += [("Lợi nhuận sau thuế", "tỷ đồng"), ("", "người"), ("khong ton tai", "cái")]
    for title, unit in probes:
        assert new_m.match(title, unit) == old_m.match(title, unit), (title, unit)
    print(f"     ({len(probes)} vocabulary probes compared)")


def test_canonicalize_matches_src_on_the_real_corpus():
    """The strongest arm: patch the REAL corpus in both trees, compare every node.

    Each tree gets its own deep copy, so the two runs cannot contaminate each other —
    canonicalize_kpis mutates the property dicts in place.
    """
    triples = load_triples()
    if not triples:
        _skip("canonicalize/corpus", f"{TRIPLES_FILE.name} absent (run data_sync pull)")
        return
    defs, aliases = load_kpi_vocab()
    new_triples = json.loads(json.dumps(triples))
    old_triples = json.loads(json.dumps(triples))

    new_stats = new_canonicalize.canonicalize_kpis(new_triples, new_canonicalize.Matcher(defs, aliases))
    old_stats = old_step03c.canonicalize_kpis(old_triples, old_step03c.Matcher(defs, aliases))
    assert new_stats == old_stats, "stats dict diverged"

    new_props, old_props = kpi_props(new_triples), kpi_props(old_triples)
    assert len(new_props) == len(old_props)
    for i, (a, b) in enumerate(zip(new_props, old_props)):
        assert a == b, f"KPIObservation #{i} diverged:\n  new={a}\n  old={b}"

    new_goal = new_canonicalize.backfill_goal_target_date(new_triples)
    old_goal = old_step03c.backfill_goal_target_date(old_triples)
    assert new_goal == old_goal, "goal backfill stats diverged"
    print(f"     ({len(new_props)} real KPIObservation occurrences compared, "
          f"{new_stats['distinct_kpi_nodes']} distinct)")


def test_canonicalize_corpus_arm_is_not_vacuous():
    """Guard the arm above: if the corpus produced no mapped AND no rejected node, it
    would be comparing two empty piles and still 'PASS'."""
    triples = load_triples()
    if not triples:
        _skip("canonicalize/not-vacuous", f"{TRIPLES_FILE.name} absent")
        return
    defs, aliases = load_kpi_vocab()
    work = json.loads(json.dumps(triples))
    stats = new_canonicalize.canonicalize_kpis(work, new_canonicalize.Matcher(defs, aliases))
    assert stats["distinct_kpi_nodes"] > 100, stats["distinct_kpi_nodes"]
    assert stats["mapped"] > 0 and stats["unmapped"] > 0, stats
    methods = stats["by_method"]
    for tier in ("kpi_type", "alias_exact", "rejected_unit", "no_match"):
        assert methods.get(tier, 0) > 0, f"tier {tier!r} never fired: {methods}"


# --------------------------------------------------------------------------- #
# core/graph_patch.py  — GraphPatch / temporal_md, extracted out of step05c
# --------------------------------------------------------------------------- #
# These get their own arm group rather than riding along with the step05c stage arm
# below, because their lifetime is different: step05d imports GraphPatch/temporal_md
# STRAIGHT FROM CORE once it moves, so the shared contract has to be pinned
# independently of how step05c happens to use it. Per DESIGN.md §5.3 this group only
# retires when `src/step05c_link_standard_indicators.py` is deleted — later than the
# stage arm.
#
# The fixture uses real schema labels so add_edge's direction check is exercised against
# the real rules: partOf (StandardIndicator -> Regulation) is legal, measuredUnder
# (Regulation -> StandardIndicator) is a real label pointed the wrong way, and
# "notARealLabel" is not in the schema at all.
def patch_fixture() -> dict:
    """A tiny graph in a fixed order, so the append-only prefix check has something to hold."""
    return {
        "nodes": [
            {"class": "Regulation",
             "properties": {"name": "Thông tư 96/2020/TT-BTC", "is_current": True}},
            {"class": "StandardIndicator",
             "properties": {"id": "TT96-6.1.1", "name": "Phát thải khí nhà kính",
                            "pillar": "Môi trường", "valid_from": "2020", "valid_to": None}},
            {"class": "KPIObservation",
             "properties": {"kpi_id": "TT96-6.1.1", "title": "Tổng phát thải",
                            "valid_from": "2023", "valid_to": None}},
        ],
        "edges": [
            {"subject": 2, "predicate": "measuredUnder", "object": 1,
             "temporal_metadata": {"valid_from": "2023", "valid_to": None}},
        ],
    }


def drive_graph_patch(mod, schema_sets) -> dict:
    """Run the same scripted sequence through one tree's GraphPatch and report everything.

    Each call builds its own fixture: GraphPatch mutates the graph dict in place, so the
    two trees must never be handed the same object.
    """
    graph = patch_fixture()
    gp = mod.GraphPatch(graph, *schema_sets)
    out = {"n_nodes0": gp.n_nodes0, "n_edges0": gp.n_edges0}

    # find(): index 0 is a legitimate answer, which is why the stage tests `is None`
    out["find_doc"] = gp.find("Regulation", "Thông tư 96/2020/TT-BTC")
    out["find_indicator"] = gp.find("StandardIndicator", "TT96-6.1.1")
    out["find_missing"] = gp.find("StandardIndicator", "TT96-9.9.9")

    # dedup by identity: the indicator already there is found, a new one is appended
    out["ensure_dup"] = gp.ensure_node(
        {"class": "StandardIndicator", "properties": {"id": "TT96-6.1.1", "name": "khác hẳn"}})
    out["ensure_new"] = gp.ensure_node(
        {"class": "StandardIndicator", "properties": {"id": "GRI 305-1", "name": "Direct GHG"}})

    md = mod.temporal_md(graph["nodes"][1]["properties"])
    out["edge_legal"] = gp.add_edge(1, "partOf", 0, md)
    out["edge_duplicate"] = gp.add_edge(1, "partOf", 0, md)          # same triple -> False
    out["edge_extra"] = gp.add_edge(out["ensure_new"][0], "partOf", 0, md,
                                    extra={"confidence": 0.9})
    out["edge_unknown_label"] = gp.add_edge(1, "notARealLabel", 0, md)
    out["edge_wrong_direction"] = gp.add_edge(0, "measuredUnder", 1, md)

    out["dropped_invalid"] = gp.dropped_invalid
    out["by_id"] = dict(gp._by_id)
    out["edgeset"] = set(gp._edgeset)
    out["graph"] = graph
    return out


def append_only_verdict(mod, schema_sets, mutate) -> str:
    """What assert_append_only() does after `mutate` — the message too, not just pass/fail."""
    gp = mod.GraphPatch(patch_fixture(), *schema_sets)
    mutate(gp)
    try:
        gp.assert_append_only()
        return "ok"
    except AssertionError as exc:
        return f"AssertionError: {exc}"


def test_graph_patch_temporal_md_matches_src():
    # TODAY is computed at import time in both trees. Equal unless the run straddles
    # midnight, which is worth failing over: it would mean the two trees stamped
    # different recorded_at values in one pipeline run.
    assert new_graph_patch.TODAY == old_step05c.TODAY
    for props in [{"valid_from": "2023", "valid_to": "2024"},
                  {"valid_from": "2023-01-01", "valid_to": None},
                  {"valid_from": None}, {}, {"unrelated": 1}]:
        assert new_graph_patch.temporal_md(props) == old_step05c.temporal_md(props), props


def test_graph_patch_norm_matches_src():
    for s in ["Thông tư 96/2020/TT-BTC", "  CÔNG TY CP Nhựa An Phát  ", "", None, 12]:
        assert new_graph_patch.norm(s) == old_step05c.norm(s), s


def test_graph_patch_dedup_and_append_matches_src():
    sets = old_step03.load_schema_sets(load_schema())
    new_out = drive_graph_patch(new_graph_patch, sets)
    old_out = drive_graph_patch(old_step05c, sets)
    for key in sorted(old_out):
        assert new_out[key] == old_out[key], f"GraphPatch diverged on {key!r}"


def test_graph_patch_assert_append_only_matches_src():
    """Both trees must draw the line in the same place — this is the invariant behind
    step06's `_node_key = "n{i}"` and the positional node refs in the step07 dossiers."""
    sets = old_step03.load_schema_sets(load_schema())
    cases = {
        "untouched": lambda gp: None,
        "appended": lambda gp: gp.nodes.append({"class": "Standard", "properties": {"name": "GRI"}}),
        # allowed: the stage stamps self_reported_zero / a corrected pillar in place
        "property_mutated": lambda gp: gp.nodes[0]["properties"].update({"pillar": "Xã hội"}),
        "node_reordered": lambda gp: gp.nodes.reverse(),
        "node_replaced": lambda gp: gp.nodes.__setitem__(0, dict(gp.nodes[0])),
        "node_dropped": lambda gp: gp.nodes.pop(),
        "edge_replaced": lambda gp: gp.edges.__setitem__(0, dict(gp.edges[0])),
        "edge_dropped": lambda gp: gp.edges.clear(),
    }
    for name, mutate in cases.items():
        new_v = append_only_verdict(new_graph_patch, sets, mutate)
        old_v = append_only_verdict(old_step05c, sets, mutate)
        assert new_v == old_v, f"{name}: new={new_v!r} old={old_v!r}"
    # guard the guard: if every case returned "ok" this would be asserting nothing
    verdicts = {n: append_only_verdict(new_graph_patch, sets, m) for n, m in cases.items()}
    assert verdicts["untouched"] == "ok" and verdicts["property_mutated"] == "ok", verdicts
    assert all(v.startswith("AssertionError") for n, v in verdicts.items()
               if n in ("node_reordered", "node_replaced", "node_dropped",
                        "edge_replaced", "edge_dropped")), verdicts


# --------------------------------------------------------------------------- #
# step05c -> esg_kg.resolve.indicators  (STAGE arm)
# --------------------------------------------------------------------------- #
# Same three layers as step00/step03c: module constants, each pure function, and the
# full output of a real run(). run() reads and writes files, so "output" here means a
# temp workspace: graph + defs + crosswalk + catalog in, patched graph + stats out.
# The Workspace shape is lifted from test/test_indicator_axis.py:150 — same ten
# Namespace fields the stage's main() builds.
CROSSWALK_FILE = REPO / "config" / "standard_crosswalk.json"
GRI_CATALOG_FILE = REPO / "config" / "gri_catalog.json"

# The four indicators the fixture needs: 6.1.1 (GHG, keyword tier + Emission), 6.5.1/6.5.2
# (the Penalty split), 6.6.3 (social, but its code contains "6.3" — the pillar trap).
FIXTURE_IDS = ("TT96-6.1.1", "TT96-6.5.1", "TT96-6.5.2", "TT96-6.6.3")

# What step05c mints. Stripping these is what turns the real-graph arm from a no-op
# re-run into a full one — see strip_axis().
AXIS_EDGE_LABELS = {"partOf", "measuredUnder", "equivalentTo", "alignsWithIndicator"}


def fixture_defs() -> list:
    defs = [d for d in json.loads(KPI_DEFS_FILE.read_text(encoding="utf-8"))
            if d["id"] in FIXTURE_IDS]
    assert len(defs) == len(FIXTURE_IDS), f"vocabulary lost one of {FIXTURE_IDS}"
    return defs


def fixture_graph() -> dict:
    """One node per branch of run(), so the arm compares a busy stats dict, not an empty one."""
    def n(cls, **p):
        p.setdefault("valid_from", "2023")
        p.setdefault("valid_to", None)
        p.setdefault("is_current", True)
        return {"class": cls, "properties": p}

    return {
        "nodes": [
            # the document node already in the graph -> partOf must reuse it, not mint one
            n("Regulation", name="Thông tư 96/2020/TT-BTC"),
            n("KPIObservation", kpi_id="TT96-6.1.1", title="Tổng phát thải KNK",
              value=12450, unit="tCO2e", source_type="report"),
            n("KPIObservation", kpi_id="TT96-9.9.9", title="Chỉ số ngoài từ vựng"),  # unmapped
            n("KPIObservation", kpi_type="TT96-6.1.1", title="Chưa canonical"),      # no kpi_id
            n("Emission", category="Scope 1", value=8000, unit="tCO2e"),
            n("Penalty", penalty_id="AAA_2022_EnvPenalty_0times", amount=0,
              description="Số lần bị phạt vi phạm môi trường"),                      # self-reported
            n("Penalty", penalty_id="AAA_2023_EnvPenalty", amount=150_000_000,
              description="Xử phạt xả thải vượt chuẩn", source_type="news"),
            n("SustainabilityClaim", description="Cam kết giảm phát thải khí nhà kính đến 2030"),
            n("Goal", name="Tiết kiệm năng lượng toàn hệ thống", description=""),
            # a stale pillar on a pre-existing node -> the restamp branch
            n("StandardIndicator", id="TT96-6.6.3", name="Chỉ số TT96-6.6.3",
              pillar="Môi trường", definition=None, section=None,
              source_document="Thông tư 96"),
        ],
        "edges": [],
    }


def fixture_crosswalk() -> dict:
    """Both review states, so the confirmed-only gate is exercised in both directions."""
    return {"version": "test",
            "confirmed": [
                {"tt96": "TT96-6.1.1", "gri": ["GRI 305-1"], "gri_name": "Direct GHG",
                 "status": "needs_review", "confidence": 0.5},
                {"tt96": "TT96-6.5.1", "gri": ["GRI 2-27"], "gri_name": "Compliance",
                 "status": "confirmed", "confidence": 0.9},
            ],
            "needs_review": []}


def fixture_catalog() -> dict:
    return {"GRI 2-27": {"title_vi": "Tuân thủ pháp luật và quy định",
                         "title_en": "Compliance with laws and regulations",
                         "pillar": "Quản trị", "definition_vi": "Chỉ số công bố GRI 2-27"},
            "GRI 305-1": {"title_vi": "Phát thải khí nhà kính trực tiếp (Scope 1)",
                          "title_en": "Direct (Scope 1) GHG emissions",
                          "pillar": "Môi trường", "definition_vi": "Chỉ số công bố GRI 305-1"}}


def run_indicators(mod, graph, defs, crosswalk, catalog, **overrides) -> tuple:
    """Drive one tree's run() over a private temp workspace; return (graph_after, stats)."""
    tmp = Path(tempfile.mkdtemp(prefix="esgkg_eq_axis_"))
    try:
        paths = {}
        for name, obj in (("resolved_graph", graph), ("defs", defs),
                          ("crosswalk", crosswalk), ("gri_catalog", catalog)):
            paths[name] = tmp / f"{name}.json"
            paths[name].write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        stats_path = tmp / "stats.json"
        args = argparse.Namespace(
            input=paths["resolved_graph"], defs=paths["defs"],
            crosswalk=paths["crosswalk"], schema=SCHEMA_FILE,
            gri_catalog=paths["gri_catalog"], no_gri=False, no_align=False,
            trust_draft_crosswalk=False, stats_out=stats_path, dry_run=False)
        for k, v in overrides.items():
            setattr(args, k, v)
        mod.run(args)
        # --dry-run returns before writing either file; "no stats" is itself part of the
        # behaviour being compared, so report None rather than papering over it.
        stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else None
        return (json.loads(paths["resolved_graph"].read_text(encoding="utf-8")), stats)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def strip_axis(graph: dict) -> dict:
    """Remove everything step05c mints, so a re-run does the real work.

    Without this the real-graph arm is close to vacuous: the live graph is ALREADY
    patched (67 StandardIndicator, 641 measuredUnder, 639 alignsWithIndicator, 26
    equivalentTo, 102 partOf), and every counter in the stage's report sits behind
    `if gp.add_edge(...)` (step05c:364,384,410,434) — so a second run reports ~nothing
    and the arm would be comparing two empty piles.

    Document nodes (Regulation TT96, Standard QCVN09, ...) are NOT stripped: they come
    from extraction, not from this stage, so partOf gets reconnected to the real target.
    Edges address nodes by ARRAY INDEX, hence the remap.
    """
    keep, old2new = [], {}
    for i, node in enumerate(graph.get("nodes") or []):
        if node.get("class") == "StandardIndicator":
            continue
        old2new[i] = len(keep)
        keep.append(node)
    edges = []
    for edge in graph.get("edges") or []:
        if edge.get("predicate") in AXIS_EDGE_LABELS:
            continue
        s, o = old2new.get(edge.get("subject")), old2new.get(edge.get("object"))
        if s is None or o is None:
            continue
        edges.append({**edge, "subject": s, "object": o})
    return {**graph, "nodes": keep, "edges": edges}


def test_indicators_constants_match_src():
    # TODAY / norm are NOT compared here: after the extraction they belong to
    # core/graph_patch.py and nothing in the stage references them any more, so
    # re-importing them into this module just to be asserted would be a dead import
    # written to please a test. Their arms are test_graph_patch_* above.
    assert new_indicators.DOC_OF_PREFIX == old_step05c.DOC_OF_PREFIX
    assert new_indicators.DOC_CANONICAL == old_step05c.DOC_CANONICAL
    assert new_indicators.KEYWORDS == old_step05c.KEYWORDS


def test_indicators_default_paths_match_src():
    for name in ("DEFAULT_RESOLVED", "DEFAULT_DEFS", "DEFAULT_CROSSWALK",
                 "DEFAULT_SCHEMA", "DEFAULT_STATS_OUT", "GRI_CATALOG_PATH"):
        assert getattr(new_indicators, name) == getattr(old_step05c, name), name


def test_indicators_pure_helpers_match_src():
    for ind in ["TT96-6.1.1", "QD2171-1", "QCVN09-1", "SSCIFC-S6", "GRI 305-1", "", "TT96"]:
        assert new_indicators.doc_key_for(ind) == old_step05c.doc_key_for(ind), ind

    defs, catalog = fixture_defs(), fixture_catalog()
    for d in defs:
        assert new_indicators.make_indicator_node(d) == old_step05c.make_indicator_node(d)
    for key, kind in (("TT96", "Regulation"), ("GRI", "Standard")):
        canonical = old_step05c.DOC_CANONICAL[key]
        assert new_indicators.make_doc_node(key, kind, canonical) == \
               old_step05c.make_doc_node(key, kind, canonical)
    for code, name in [("GRI 305-1", "Direct GHG"), ("GRI 2-27", None),
                       ("GRI 999-9", "Không có trong catalog"), ("GRI 999-9", None)]:
        assert new_indicators.make_gri_node(code, name, catalog) == \
               old_step05c.make_gri_node(code, name, catalog), code

    assert new_indicators.pillar_authority(defs, catalog) == \
           old_step05c.pillar_authority(defs, catalog)

    # load_gri_catalog degrades to {} on a missing/broken file — pin that too
    assert new_indicators.load_gri_catalog(REPO / "config" / "does_not_exist.json") == \
           old_step05c.load_gri_catalog(REPO / "config" / "does_not_exist.json")
    if GRI_CATALOG_FILE.exists():
        assert new_indicators.load_gri_catalog(GRI_CATALOG_FILE) == \
               old_step05c.load_gri_catalog(GRI_CATALOG_FILE)

    # restamp mutates in place -> one fresh copy per tree
    authority = old_step05c.pillar_authority(defs, catalog)
    new_nodes, old_nodes = fixture_graph()["nodes"], fixture_graph()["nodes"]
    assert new_indicators.restamp_pillars(new_nodes, authority) == \
           old_step05c.restamp_pillars(old_nodes, authority)
    assert new_nodes == old_nodes

    # keyword tier: longest matching phrase wins (pinned as-is; changing it is a
    # behaviour commit under DESIGN.md §5.3, not something to "fix" toward older docs)
    new_kw = new_indicators.build_keyword_index(defs, catalog)
    old_kw = old_step05c.build_keyword_index(defs, catalog)
    assert new_kw == old_kw
    probes = ["Cam kết giảm phát thải khí nhà kính đến 2030",
              "Tiết kiệm năng lượng và tiêu thụ năng lượng",  # two candidates, longest wins
              "An toàn lao động tại nhà máy", "Không liên quan gì cả", "",
              "Tuân thủ pháp luật và quy định về môi trường"]
    for text in probes:
        assert new_indicators.match_keyword(text, new_kw) == \
               old_step05c.match_keyword(text, old_kw), text


def test_indicators_run_matches_src_on_temp_workspace():
    """The stage-level arm: same inputs, two trees, compare the patched graph AND stats.

    Runs on a synthetic fixture, so unlike the real-graph arm it also works on a bare
    clone (no HF snapshot). The two are complementary, not redundant — measured by
    mutation check: swapping step05c's `pen_ind = "TT96-6.5.2" if amount else ...` is
    invisible to the real-graph arm, because all four Penalty nodes in the live graph
    carry amount == 0 and take the self-reported-zero `continue` before ever reaching
    that line. Only this fixture has a Penalty with a real fine.
    """
    defs, crosswalk, catalog = fixture_defs(), fixture_crosswalk(), fixture_catalog()
    new_graph, new_stats = run_indicators(new_indicators, fixture_graph(), defs, crosswalk, catalog)
    old_graph, old_stats = run_indicators(old_step05c, fixture_graph(), defs, crosswalk, catalog)
    assert new_stats == old_stats, f"stats diverged:\n  new={new_stats}\n  old={old_stats}"
    assert len(new_graph["nodes"]) == len(old_graph["nodes"])
    for i, (a, b) in enumerate(zip(new_graph["nodes"], old_graph["nodes"])):
        assert a == b, f"node #{i} diverged:\n  new={a}\n  old={b}"
    assert new_graph["edges"] == old_graph["edges"]

    # the same three flags run() branches on, so the arm covers the switches too
    for overrides in ({"no_gri": True}, {"no_align": True}, {"trust_draft_crosswalk": True},
                      {"dry_run": True}):
        n_g, n_s = run_indicators(new_indicators, fixture_graph(), defs, crosswalk, catalog,
                                  **overrides)
        o_g, o_s = run_indicators(old_step05c, fixture_graph(), defs, crosswalk, catalog,
                                  **overrides)
        assert (n_g, n_s) == (o_g, o_s), f"diverged with {overrides}"


def test_indicators_temp_workspace_arm_is_not_vacuous():
    """Guard the arm above: every branch of run() must actually fire on the fixture."""
    defs, crosswalk, catalog = fixture_defs(), fixture_crosswalk(), fixture_catalog()
    graph, stats = run_indicators(new_indicators, fixture_graph(), defs, crosswalk, catalog)
    for label in ("partOf", "measuredUnder", "equivalentTo", "alignsWithIndicator"):
        assert stats["created_edges"].get(label, 0) > 0, f"{label} never minted: {stats}"
    assert stats["created_nodes"].get("StandardIndicator", 0) > 0, stats
    assert stats["created_nodes"].get("StandardIndicator(GRI)", 0) > 0, stats
    assert stats["penalty_self_reported_zero"] > 0, stats
    assert stats["unmapped_kpi_ids"], stats
    assert stats["pillar_restamped"] > 0, stats
    # the confirmed-only gate really gated: TT96-6.1.1's row is needs_review
    assert stats["created_edges"]["equivalentTo"] == 1, stats
    # and the document node already in the graph was reused, not duplicated
    docs = [n for n in graph["nodes"]
            if n.get("class") == "Regulation"
            and (n.get("properties") or {}).get("name") == "Thông tư 96/2020/TT-BTC"]
    assert len(docs) == 1, f"document node duplicated: {len(docs)}"


def test_indicators_matches_src_on_the_real_graph():
    """The strongest arm: the real resolved graph, stripped back to its pre-axis state so
    the run does the full job (67 indicators / ~1,400 axis edges) rather than a no-op."""
    if not RESOLVED_FILE.exists():
        _skip("indicators/real-graph", f"{RESOLVED_FILE.name} absent (run data_sync pull)")
        return
    if not (KPI_DEFS_FILE.exists() and CROSSWALK_FILE.exists() and GRI_CATALOG_FILE.exists()):
        _skip("indicators/real-graph", "defs/crosswalk/gri_catalog missing")
        return

    base = strip_axis(json.loads(RESOLVED_FILE.read_text(encoding="utf-8")))
    defs = json.loads(KPI_DEFS_FILE.read_text(encoding="utf-8"))
    crosswalk = json.loads(CROSSWALK_FILE.read_text(encoding="utf-8"))
    catalog = json.loads(GRI_CATALOG_FILE.read_text(encoding="utf-8"))

    new_graph, new_stats = run_indicators(new_indicators, base, defs, crosswalk, catalog)
    old_graph, old_stats = run_indicators(old_step05c, base, defs, crosswalk, catalog)
    assert new_stats == old_stats, "stats diverged on the real graph"
    assert len(new_graph["nodes"]) == len(old_graph["nodes"])
    for i, (a, b) in enumerate(zip(new_graph["nodes"], old_graph["nodes"])):
        assert a == b, f"real node #{i} diverged:\n  new={a}\n  old={b}"
    assert len(new_graph["edges"]) == len(old_graph["edges"])
    for i, (a, b) in enumerate(zip(new_graph["edges"], old_graph["edges"])):
        assert a == b, f"real edge #{i} diverged:\n  new={a}\n  old={b}"

    # not vacuous: the stripped graph really was rebuilt, not re-read
    for label in ("partOf", "measuredUnder", "equivalentTo", "alignsWithIndicator"):
        assert new_stats["created_edges"].get(label, 0) > 0, \
            f"{label} not rebuilt on the real graph: {new_stats['created_edges']}"
    assert new_stats["created_nodes"].get("StandardIndicator", 0) > 0, new_stats
    assert new_stats["penalty_self_reported_zero"] > 0, new_stats
    print(f"     ({new_stats['nodes_before']} real nodes, "
          f"+{new_stats['nodes_added']} indicators, +{new_stats['edges_added']} axis edges "
          f"compared across both trees)")


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
