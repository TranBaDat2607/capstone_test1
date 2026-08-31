#!/usr/bin/env python3
"""
Regression checks for the `esg_kg.core` kernel modules (paths, schema, naming, dates,
graph_patch) plus the report/quality (step00) and resolve/indicators (step05c) stages.

Was the safety net for the `src/` -> `src/esg_kg/` refactor (Model A): it used to
import both trees, run them on the same real input, and assert the results equal. Now
that every stage has moved and `src/` is deleted, this file is repointed at `esg_kg`
alone (2026-07-29). Wherever a comparison had no independent claim of its own, it was
rewritten against a concrete golden value captured directly from the (already-proven-
equivalent) function — never fabricated — or, when hardcoding a real-corpus/real-schema
snapshot would be brittle against a legitimate future data change, converted to a
shape/non-vacuity check instead. See the per-section comments for which applies where.

Offline: no LLM, no Neo4j, no network. `config/schema.json` is tracked in git so
the core arms always run; arms that need git-ignored artifacts (graph_output/,
shipped via the HF snapshot) SKIP with a message on a bare clone.

TWO core modules are deliberately compared elsewhere. Do not add duplicate arms here:

  - `esg_kg.core.console` -> `test/test_console_utf8.py`, because proving the two
    copies equal needs `sys.platform` / `sys.stdout` swapped out, and because the same
    file also asserts the WIRING (that main() calls it). That is the hole this file
    structurally cannot cover — it never executes a `__main__` block or a main(),
    which is exactly how the win32 stdout fix came to exist in `src/` only.
  - `esg_kg.core.identity` -> `test/test_esg_kg_anchor_kpi.py`, which covers the
    step03b migration slice end-to-end (the stage plus the kernel module that slice
    had to extract). Splitting it off is organisational — this file was already past
    1,100 lines — not a difference in contract.

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

# --- the esg_kg package ---------------------------------------------------------
from esg_kg.core import dates as new_dates  # noqa: E402
from esg_kg.core import graph_patch as new_graph_patch  # noqa: E402
from esg_kg.kpi import canonicalize as new_canonicalize  # noqa: E402
from esg_kg.core import naming as new_naming  # noqa: E402
from esg_kg.core import paths as new_paths  # noqa: E402
from esg_kg.core import schema as new_schema  # noqa: E402
from esg_kg.report import quality as new_quality  # noqa: E402
from esg_kg.resolve import indicators as new_indicators  # noqa: E402

from _fixture_paths import resolve_artifact, skip_if_fixture, tag  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
TRIPLES_FILE = REPO / "graph_output" / "validated" / "all_validated_triples.json"
RESOLVED_FILE = REPO / "graph_output" / "resolved" / "resolved_graph.json"

# Where the corpus arms actually READ from: the real artifact when the HF
# snapshot is pulled, otherwise the committed synthetic fixture so the arms run
# on a bare clone instead of silently skipping. TRIPLES_FILE/RESOLVED_FILE above
# stay pinned to the canonical locations because several wiring assertions below
# compare the stages' own DEFAULT_* constants against them.
TRIPLES_DATA, TRIPLES_IS_FIXTURE = resolve_artifact("validated")
RESOLVED_DATA, RESOLVED_IS_FIXTURE = resolve_artifact("resolved")

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
    if not TRIPLES_DATA.exists():
        return []
    data = json.loads(TRIPLES_DATA.read_text(encoding="utf-8"))
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
def test_paths_repo_root_is_the_marker_directory():
    # the marker-based lookup must land on the actual repo root — the single
    # anchor every stage path is built from.
    assert new_paths.REPO_ROOT == REPO


def test_paths_constants_are_repo_relative():
    assert new_paths.KPI_DEFS_PATH == REPO / "kpi_definitions_construction.json"
    assert new_paths.KPI_OUTPUT_DIR == REPO / "kpi_output"
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
def test_schema_load_schema_sets_has_the_documented_shape():
    """Exact class/edge CONTENT is test_schema_contract.py's job (run after any hand-edit
    to schema.json); this checks load_schema_sets() wires the file into the right shape."""
    schema = load_schema()
    ec, el, ed = new_schema.load_schema_sets(schema)
    assert isinstance(ec, set) and isinstance(el, set) and isinstance(ed, dict)
    assert len(ec) > 0 and len(el) > 0
    assert set(ed) <= el, "edge_directions must only key legal edge labels"


def test_schema_get_identity_keys_covers_every_class():
    schema = load_schema()
    ec, _, _ = new_schema.load_schema_sets(schema)
    ik = new_schema.get_identity_keys(schema)
    assert set(ik) == ec, "every schema class must have an identity_keys entry"


def test_schema_validate_triple_on_edge_cases():
    """Malformed shapes, hand-built so this arm runs on a bare clone too. Expected
    (is_valid, reasons) pairs captured directly from validate_triple() against the real
    schema.json (2026-07-29) — a schema edit that changes these is exactly the kind of
    drift this arm exists to surface, same spirit as test_schema_contract.py."""
    schema = load_schema()
    ec, el, ed = new_schema.load_schema_sets(schema)

    ok_props = {"name": "X", "valid_from": "2020", "valid_to": None, "is_current": True}
    tm = {"valid_from": "2020", "valid_to": None, "recorded_at": "2020"}
    cases = [
        ("not a dict", (False, ["Not a dict"])),
        ({}, (False, ["Missing required keys (subject/predicate/object)"])),
        ({"subject": None, "predicate": "publishesReport", "object": None},
         (False, ["Subject is None", "Object is None", "Missing temporal_metadata"])),
        ({"subject": {"class": "Organization", "properties": ok_props},
          "predicate": "publishesReport",
          "object": {"class": "Report", "properties": dict(ok_props)},
          "temporal_metadata": tm},
         (False, ["Invalid object class: Report",
                  "Invalid direction: Organization -publishesReport-> Report"])),
        # reversed direction
        ({"subject": {"class": "Report", "properties": dict(ok_props)},
          "predicate": "publishesReport",
          "object": {"class": "Organization", "properties": ok_props},
          "temporal_metadata": tm},
         (False, ["Invalid subject class: Report",
                  "Invalid direction: Report -publishesReport-> Organization"])),
        # unknown class / predicate
        ({"subject": {"class": "NotAClass", "properties": dict(ok_props)},
          "predicate": "publishesReport",
          "object": {"class": "Report", "properties": dict(ok_props)},
          "temporal_metadata": tm},
         (False, ["Invalid subject class: NotAClass", "Invalid object class: Report",
                  "Invalid direction: NotAClass -publishesReport-> Report"])),
        ({"subject": {"class": "Organization", "properties": ok_props},
          "predicate": "notAPredicate",
          "object": {"class": "Report", "properties": dict(ok_props)},
          "temporal_metadata": tm},
         (False, ["Invalid object class: Report", "Invalid predicate: notAPredicate"])),
        # missing temporal fields
        ({"subject": {"class": "Organization", "properties": {"name": "X"}},
          "predicate": "publishesReport",
          "object": {"class": "Report", "properties": dict(ok_props)}},
         (False, ["Subject missing valid_from", "Subject missing valid_to",
                  "Subject missing is_current", "Invalid object class: Report",
                  "Invalid direction: Organization -publishesReport-> Report",
                  "Missing temporal_metadata"])),
    ]
    for i, (case, expected) in enumerate(cases):
        got = new_schema.validate_triple(case, ec, el, ed)
        assert got == expected, f"case {i}: {case!r}\n  got={got}\n  expected={expected}"


def test_schema_validate_triple_on_real_corpus_is_well_formed():
    """Every real triple must return a well-formed (bool, list[str]) verdict — the
    corpus's actual validity split is step03's concern (test_esg_kg_fix_triples.py
    already pins 'Valid: 2123, Invalid: 163' on the real page files)."""
    triples = load_triples()
    if not triples:
        _skip("validate_triple/corpus", f"{TRIPLES_FILE.name} absent (run data_sync pull)")
        return
    print(f"     {tag(TRIPLES_IS_FIXTURE)} validate_triple/corpus")
    schema = load_schema()
    ec, el, ed = new_schema.load_schema_sets(schema)
    checked = 0
    for t in triples[:CORPUS_CAP]:
        ok, reasons = new_schema.validate_triple(t, ec, el, ed)
        assert isinstance(ok, bool) and isinstance(reasons, list), f"triple #{checked}: {t}"
        checked += 1
    print(f"     ({checked} real triples compared)")


# --------------------------------------------------------------------------- #
# core/naming.py  — normalize_name, name_tokens, merge_preserving_edits
# --------------------------------------------------------------------------- #
def test_naming_normalize_name_on_hand_picked_cases():
    """Every transform normalize_name applies, against golden values captured directly
    from the function (2026-07-29) — a change to OCR_FIXES/LEGAL_FORMS/SYNONYMS that
    alters one of these is exactly the drift this arm exists to catch."""
    cases = [
        (None, ""), ("", ""), (0, ""), ("   ", ""),
        ("Công ty Cổ phần Nhựa An Phát Xanh", "nhua an phat xanh"),
        ("CTCP Nhua An Phat Xanh", "nhua an phat xanh"),
        ("AN PHAT XANH PLASTICS JOINT STOCK COMPANY", "an phat xanh plastic"),
        ("Tổng Công ty Đầu tư Phát triển Đô thị", "dau tu phat trien do thi"),  # đ + longest-first legal form
        ("Cty TNHH Ƣu Việt", "cty uu viet"),                                   # OCR chars
        ("An Phát  Xanh   ,  JSC.", "an phat xanh"),                           # punctuation + whitespace
        ("Green Plastics Co Ltd", "xanh plastic"),                            # SYNONYMS: green->xanh, plastics->plastic
        ("  CÔNG TY CỔ PHẦN  ", ""),                                          # legal form is the whole string
        ("Đđ Ưư", "dd uu"),
        (123, "123"),
    ]
    for c, expected in cases:
        got = new_naming.normalize_name(c)
        assert got == expected, f"case {c!r}: got {got!r}, expected {expected!r}"


def test_naming_normalize_name_on_real_names_is_well_formed():
    """Real corpus: every name normalizes to a string with no crash. Exact per-name
    correctness is covered by the hand-picked cases above (every transform is exercised
    there); this arm's job is non-vacuity at scale."""
    triples = load_triples()
    if not triples:
        _skip("normalize_name/corpus", f"{TRIPLES_FILE.name} absent (run data_sync pull)")
        return
    print(f"     {tag(TRIPLES_IS_FIXTURE)} normalize_name/corpus")
    names = org_names(triples[:CORPUS_CAP])
    if not names:
        _skip("normalize_name/corpus", "no Organization names in the corpus slice")
        return
    for n in names:
        got = new_naming.normalize_name(n)
        assert isinstance(got, str), f"name {n!r} -> {got!r}"
    print(f"     ({len(set(names))} distinct real Organization names compared)")


def test_naming_name_tokens_on_hand_picked_cases():
    cases = [
        (None, set()), ("", set()),
        ("Công ty Cổ phần Nhựa An Phát Xanh", {"an", "xanh", "nhua", "phat"}),
        ("CTCP", set()),
        ("Green Plastics Ltd", {"xanh", "plastic"}),
    ]
    for c, expected in cases:
        got = new_naming.name_tokens(c)
        assert got == expected, f"case {c!r}: got {got}, expected {expected}"


def test_naming_merge_preserving_edits_keeps_human_edits():
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
    merged = new_naming.merge_preserving_edits(old_reg, new_reg)
    assert merged["canonical_name"] == "Công ty Cổ phần Nhựa An Phát Xanh", \
        "the human-edited canonical_name must survive a merge"
    assert set(merged["aliases"]) == {"aaa", "an phat xanh", "an phat xanh jsc", "nhua an phat xanh"}
    assert {e["name"] for e in merged["exclusions"]} == {"an phat holdings", "an phat bioplastics"}
    assert next(e for e in merged["exclusions"] if e["name"] == "an phat holdings")["reason"] \
        == "CONFIRMED separate legal entity", "the human-edited exclusion reason must survive"
    assert merged["needs_review"] == [], \
        "an entry moved to exclusions by a human must not come back as needs_review"

    # empty prior registry (the first-run path) must just adopt the fresh draft
    empty = {"aliases": [], "exclusions": [], "needs_review": []}
    merged_empty = new_naming.merge_preserving_edits(empty, new_reg)
    assert merged_empty["canonical_name"] == new_reg["canonical_name"]
    assert set(merged_empty["aliases"]) == set(new_reg["aliases"])


def test_naming_constants_are_non_empty():
    # normalize_name is only as stable as the tables it reads; drift in these is
    # exactly the failure this file exists to catch. Exact content isn't pinned here
    # (these tables grow with new spellings/legal forms over time by design) — the
    # hand-picked normalize_name/name_tokens cases above are what catch a broken entry.
    assert new_naming.OCR_FIXES
    assert new_naming.LEGAL_FORMS
    assert new_naming.SYNONYMS


# --------------------------------------------------------------------------- #
# core/dates.py  — ISO_DATE_RE, normalize_date_string, date_start_key
# --------------------------------------------------------------------------- #
def test_dates_normalize_date_string_on_every_spelling():
    """Every spelling the step02 LLM has been seen to emit, plus the reject paths.
    Golden values captured directly from normalize_date_string() (2026-07-29)."""
    cases = [
        (None, (None, True)), ("", (None, True)), ("   ", (None, True)),
        ("null", (None, True)), ("NULL", (None, True)), ("none", (None, True)), ("None", (None, True)),
        ("2011", ("2011", True)), ("2011-3", ("2011-03", True)), ("2011-03", ("2011-03", True)),
        ("2011-1-3", ("2011-01-03", True)), ("2011-01-03", ("2011-01-03", True)),          # ISO, zero-padding
        ("2024-08-14T10:00:00", ("2024-08-14", True)),
        ("2024-08-14T00:00:00Z", ("2024-08-14", True)),                                    # datetime -> date part
        ("31/05/2023", ("2023-05-31", True)), ("31-05-2023", ("2023-05-31", True)),
        ("31.05.2023", ("2023-05-31", True)),                                              # VN day-first
        ("2023/05/31", ("2023-05-31", True)), ("2023.05.31", ("2023-05-31", True)),        # year-first
        ("05/2023", ("2023-05", True)), ("05-2023", ("2023-05", True)), ("2023/05", ("2023-05", True)),  # month + year
        ("2023-13-01", ("2023-13-01", False)), ("2023-00-01", ("2023-00-01", False)),
        ("2023-01-32", ("2023-01-32", False)), ("2023-01-00", ("2023-01-00", False)),      # out-of-range -> unparseable
        ("Q2 2023", ("Q2 2023", False)), ("quy 2 nam 2023", ("quy 2 nam 2023", False)),
        ("garbage", ("garbage", False)), ("20230531", ("20230531", False)),                # unrecognized -> unchanged
        (2011, ("2011", True)), (0, ("0", False)), (True, ("True", False)),                # non-str inputs
    ]
    for c, expected in cases:
        got = new_dates.normalize_date_string(c)
        assert got == expected, f"case {c!r}: got {got}, expected {expected}"


def test_dates_date_start_key_on_every_spelling():
    cases = [
        (None, None), ("", None), ("null", None),
        ("2011", "2011-01-01"), ("2011-01-01", "2011-01-01"),
        ("2011-03", "2011-03-01"), ("2011-03-15", "2011-03-15"),
        ("31/05/2023", "2023-05-31"), ("05/2023", "2023-05-01"),
        ("2024-08-14T10:00:00", "2024-08-14"),
        ("Q2 2023", None), ("garbage", None), (2011, "2011-01-01"),
    ]
    for c, expected in cases:
        got = new_dates.date_start_key(c)
        assert got == expected, f"case {c!r}: got {got!r}, expected {expected!r}"

    # the P4 collapse this function exists for: "2011" and "2011-01-01" are one
    # instant, not two versions
    assert new_dates.date_start_key("2011") == new_dates.date_start_key("2011-01-01")


def test_dates_iso_date_re_matches_yyyy_mm_dd_shapes():
    assert new_dates.ISO_DATE_RE.pattern == r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$"
    for s in ("2011", "2011-03", "2011-03-15"):
        assert new_dates.ISO_DATE_RE.match(s), s
    for s in ("Q2 2023", "31/05/2023", "garbage", ""):
        assert not new_dates.ISO_DATE_RE.match(s), s


def test_dates_on_real_corpus_is_well_formed():
    """Every date string the real graph actually carries — node validity and edge
    temporal_metadata alike — must parse to the (value, ok) / value shape without
    crashing. Exact per-spelling correctness is covered by the hand-picked cases above."""
    triples = load_triples()
    if not triples:
        _skip("dates/corpus", f"{TRIPLES_FILE.name} absent (run data_sync pull)")
        return
    print(f"     {tag(TRIPLES_IS_FIXTURE)} dates/corpus")
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
        norm, ok = new_dates.normalize_date_string(v)
        assert isinstance(ok, bool), f"normalize_date_string({v!r})"
        key = new_dates.date_start_key(v)
        assert key is None or isinstance(key, str), f"date_start_key({v!r})"
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


def test_quality_constants_are_the_documented_tier_map():
    """The tier map is a CONTRACT: test_schema_contract.py imports it rather than
    re-declaring it, so a silent drift here would quietly change what P1 lints.
    Pinned against the real schema.json's class list (2026-07-29) — test_schema_
    contract.py's `test_every_class_is_assigned_to_exactly_one_tier` is what catches
    a NEW schema class landing in none of these; this arm catches an EXISTING one
    silently moving between tiers."""
    assert sorted(new_quality.T1_CLASSES) == [
        "Authority", "Certification", "ClaimKeyword", "Community", "Country", "Facility",
        "Location", "Material", "Organization", "Person", "Product", "Regulation",
        "Standard", "StandardIndicator"]
    assert sorted(new_quality.T2_CLASSES) == [
        "CarbonOffsetProject", "Controversy", "Emission", "Initiative", "Investment",
        "KPIObservation", "MediaReport", "Penalty", "Project", "ThirdPartyVerification", "Waste"]
    assert sorted(new_quality.T3_CLASSES) == ["Goal", "ScienceBasedTarget", "SustainabilityClaim"]
    assert new_quality.REFERENCE_CLASSES == {"StandardIndicator"}
    assert new_quality.CONDUCT_CLASSES == {"Controversy", "MediaReport", "Penalty"}
    assert new_quality.TEMPORAL_IDENTITY_FIELDS == {
        "baseline_year", "date", "is_current", "recorded_at", "target_year",
        "valid_from", "valid_to", "validity_period", "year"}
    assert sorted(new_quality.STRUCTURAL_EDGES) == [
        "enforcedBy", "holdsCertification", "investedIn", "investsIn", "involvedIn",
        "isIn", "locatedIn", "manufacturedAt", "observedAtFacility", "ownedBy", "owns",
        "ownsFacility", "partOf", "partnersWith", "producedBy", "sourcedFrom",
        "suppliedBy", "worksAt"]
    assert new_quality.BROKEN_CHARS == {"Ƣ", "ƣ", "�"}
    assert new_quality.DEFAULT_MAX_HOPS == 4


def test_quality_default_paths_are_repo_relative():
    assert new_quality.DEFAULT_GRAPH == REPO / "graph_output" / "resolved" / "resolved_graph.json"
    assert new_quality.DEFAULT_SCHEMA == SCHEMA_FILE
    assert new_quality.DEFAULT_OUT_DIR == REPO / "graph_output" / "quality"


def test_quality_helpers_on_the_mini_graph():
    """node_name/is_conduct/is_news_t2 per mini_graph() node index, against golden
    values captured directly from the functions (2026-07-29). Only the T2 conduct
    classes (6-9: KPIObservation/Controversy/Penalty/MediaReport, all source_type=news)
    are True — everything else, including the same classes on the report side, is False."""
    nodes, _ = mini_graph()
    expected = {i: (False, False) for i in range(len(nodes))}
    for i in (6, 7, 8, 9):
        expected[i] = (True, True)
    for i, nd in enumerate(nodes):
        conduct, news_t2 = expected[i]
        assert new_quality.is_conduct(nd) == conduct, f"node {i} ({nd['class']}) is_conduct"
        assert new_quality.is_news_t2(nd) == news_t2, f"node {i} ({nd['class']}) is_news_t2"
        assert isinstance(new_quality.node_name(nd), str)

    for part, whole, expected_pct in [(0, 0, 0.0), (0, 10, 0.0), (1, 3, 33.3),
                                       (7, 7, 100.0), (13790, 10393, 132.7)]:
        got = new_quality.pct(part, whole)
        assert got == expected_pct, f"pct({part}, {whole}) = {got}, expected {expected_pct}"


MINI_REPORT_GOLDEN = {
    'label': 'equivalence', 'generated_at': '2026-01-01T00:00:00+00:00',
    'graph_file': 'graph_output/resolved/resolved_graph.json',
    'graph_mtime': '2026-01-01T00:00:00+00:00', 'nodes': 20, 'edges': 23,
    'q1_accuracy': {
        'nodes_with_non_nfc_name': 1, 'nodes_with_broken_ocr_chars': 1,
        'examples': ['Nhà máy MÔI TRƢỜNG', 'Nhà máy Bà Rịa'],
        'note': 'manual 30–50 node sample audit is out of scope for this script'},
    'q2_consistency': {
        'schema_illegal_edges': 2, 'non_canonical_date_values': 1,
        'valid_from_after_valid_to': 1, 'version_chains_not_exactly_one_is_current': 1,
        'versions_split_only_by_date_format': 1, 'news_t2_missing_date_uncertain': 1,
        't1_identity_keys_with_time_fields': [], 'total_violations': 7,
        'gate': '0 violations (proposal P4/Q2)'},
    'q3_conciseness': {
        'per_class': {
            'ClaimKeyword': {'nodes': 1, 'distinct_normalized_names': 1, 'surplus_duplicate_nodes': 0},
            'Facility': {'nodes': 3, 'distinct_normalized_names': 3, 'surplus_duplicate_nodes': 0},
            'Location': {'nodes': 1, 'distinct_normalized_names': 1, 'surplus_duplicate_nodes': 0},
            'Organization': {'nodes': 4, 'distinct_normalized_names': 3, 'surplus_duplicate_nodes': 1},
            'Person': {'nodes': 1, 'distinct_normalized_names': 1, 'surplus_duplicate_nodes': 0},
            'Product': {'nodes': 1, 'distinct_normalized_names': 1, 'surplus_duplicate_nodes': 0},
            'StandardIndicator': {'nodes': 1, 'distinct_normalized_names': 1, 'surplus_duplicate_nodes': 0}},
        'total_surplus_duplicate_t1_nodes': 1},
    'q4_completeness': {
        'controversy': 1, 'penalty': 1, 'media_report': 1, 'news_kpi_observations': 1,
        'gate': '>= 10 independent conduct nodes per pilot company'},
    'q5_timeliness': {
        'edges_with_valid_from_pct': 100.0, 't2_nodes_with_valid_from_pct': 80.0,
        'news_t2_nodes': 4, 'news_t2_with_date_uncertain_pct': 75.0,
        'news_t2_date_uncertain_true': 1, 'gate': 'edges with valid_from >= 99%'},
    'q6_provenance': {
        'nodes_with_source_type_pct': 85.0, 'kpi_nodes_with_parseable_source_id_pct': 50.0,
        'gate': 'keep 100%; extend to reasoning_path per-edge provenance (P7)'},
    'q7_traversability': {
        'a_median_degree': 1.0, 'b_leaf_nodes_pct': 50.0, 'isolated_nodes': 1,
        'hubs': [{'ticker': '_unregistered', 'degree': 9, 'node_count': 1,
                  'names': ['CTCP Nhựa An Phát Xanh']}],
        'r5_max_hub_degree': 9,
        'e_t2_nodes_degree_ge_2_pct': 40.0,
        'e_t2_anchoring_per_class': {
            'Controversy': {'nodes': 1, 'degree_ge_2_pct': 0.0},
            'KPIObservation': {'nodes': 2, 'degree_ge_2_pct': 50.0},
            'MediaReport': {'nodes': 1, 'degree_ge_2_pct': 100.0},
            'Penalty': {'nodes': 1, 'degree_ge_2_pct': 0.0}},
        'gate': 'Q7(e) >= 30% after P3 prompt fix; Q7(d) must rise clearly at 1->3 companies',
        'c_masked_queries_answerable_pct': 47.8,
        'c_per_relation_pct': {
            'ownsFacility': 33.3, 'alignsWithIndicator': 66.7, 'observedAtFacility': 0.0,
            'hasKeyword': 100.0, 'locatedIn': 100.0, 'partOf': 100.0, 'verifiedBy': 100.0,
            'measuredUnder': 100.0, 'publishesReport': 0.0, 'reportedBy': 0.0,
            'subjectToPenalty': 0.0, 'contradictedBy': 0.0, 'notARealEdgeLabel': 0.0},
        'd_claims_structural_path_to_conduct_pct': 50.0, 'd_claims_total': 2, 'd_max_hops': 4,
        'd_definition': ("hub-free path <= max_hops with >=1 structural edge; "
                         "excluded hub clusters = ['_unregistered']"),
        'r1_reachability_pct': 47.8, 'r1_edges_total': 23,
        'r1_prime_hub_free_pct': 0.0, 'r1_prime_edges_total': 11,
        'r1_trainable_pct': 47.8, 'r1_trainable_edges_total': 23,
        'r1_trainable_excluded_relations': [],
        'r7_metapaths_hub_free': [], 'r7_min_support': 50},
    'q8_independence': {
        'conduct_nodes_by_source_type': {'news': 4},
        'media_report_publishers': {'VnExpress': 1},
        'note': "per-dossier PR/independent ratio is computed by step07's self-verification guard"},
}


def test_quality_mini_graph_is_not_vacuous():
    """Guards the fixture, not the code: every counter the synthetic graph exists
    to exercise must actually be non-zero, or the equivalence arms below compare
    two piles of zeros and would miss real drift."""
    rep = mini_report(new_quality, load_schema())
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
    assert q7["hubs"][0]["ticker"] == "_unregistered", "no registry passed -> single-node fallback"
    assert q7["hubs"][0]["degree"] == q7["r5_max_hub_degree"] > 0
    # both BFS arms must land strictly between 0% and 100% — that is the only
    # proof the reachable AND unreachable branches are both walked
    for key in ("c_masked_queries_answerable_pct", "d_claims_structural_path_to_conduct_pct",
                "r1_reachability_pct", "r1_trainable_pct"):
        assert 0.0 < q7[key] < 100.0, f"q7.{key} = {q7[key]} exercises only one branch"
    # R1' must actually differ from R1 (barring the hub changes the answer) —
    # otherwise this fixture wouldn't prove the hub-exclusion code path fires.
    assert q7["r1_prime_hub_free_pct"] != q7["r1_reachability_pct"]
    assert q7["r1_prime_edges_total"] < q7["r1_edges_total"], (
        "barring the hub must drop at least one edge from R1's denominator")


def test_quality_metrics_on_mini_graph_match_the_golden_report():
    """Every Q1-Q8 function, including the Q7(c)/(d) BFS the real-graph arm skips,
    against the golden report captured directly from the module (2026-07-29).

    q1_accuracy.examples is compared separately, as a set of node NAMES rather than an
    exact list: those names carry Vietnamese diacritics in a deliberately DECOMPOSED
    (NFD) Unicode form (mini_graph()'s own comment), which a golden literal typed/
    copy-pasted through an editor risks silently re-composing to NFC — exactly the kind
    of drift Q1 exists to catch, so pinning it against a re-typed copy would be
    self-defeating. Comparing against mini_graph()'s OWN node names sidesteps that."""
    schema = load_schema()
    got = mini_report(new_quality, schema)
    got_examples = got["q1_accuracy"].pop("examples")
    golden = {k: v for k, v in MINI_REPORT_GOLDEN.items() if k != "q1_accuracy"}
    golden["q1_accuracy"] = {k: v for k, v in MINI_REPORT_GOLDEN["q1_accuracy"].items()
                             if k != "examples"}
    assert got == golden, (
        f"mini_report diverged from the golden snapshot:\n  got={got}\n  golden={golden}")

    nodes, _ = mini_graph()
    fixture_names = {new_quality.node_name(nd) for nd in nodes}
    assert set(got_examples) <= fixture_names, got_examples
    assert len(got_examples) == 2, got_examples


def test_quality_render_markdown_matches_the_golden_markdown():
    expected = (
        "# Graph quality report — equivalence\n\n"
        "- generated: 2026-01-01T00:00:00+00:00\n"
        "- graph: `graph_output/resolved/resolved_graph.json` (modified 2026-01-01T00:00:00+00:00)\n"
        "- size: 20 nodes / 23 edges\n\n"
        "| # | Attribute | Key figures |\n|---|---|---|\n"
        "| Q1 | Accuracy | non-NFC names: 1; broken-OCR names: 1 |\n"
        "| Q2 | Consistency | total violations: **7** (illegal edges 2, non-ISO dates 1, "
        "from>to 1, bad is_current chains 1, format-split versions 1, missing "
        "date_uncertain 1, T1 time-identity classes 0) |\n"
        "| Q3 | Conciseness | surplus duplicate T1 nodes: 1; Standard nodes: 0 |\n"
        "| Q4 | Completeness | Controversy 1 / Penalty 1 / MediaReport 1 / news KPI 1 |\n"
        "| Q5 | Timeliness | edges with valid_from: 100.0%; T2 nodes with valid_from: "
        "80.0%; news T2 with date_uncertain: 75.0% |\n"
        "| Q6 | Provenance | nodes with source_type: 85.0%; KPI with parseable "
        "source_id: 50.0% |\n"
        "| Q7 | Traversability | median degree 1.0; leaves 50.0%; masked-answerable "
        "47.8%; claim→conduct structural 50.0%; T2 deg≥2 40.0% |\n"
        "| Q8 | Independence | conduct by channel: {'news': 4} |\n\n"
        "## Q7(e) anchoring per T2 class\n\n"
        "| class | nodes | degree ≥ 2 |\n|---|---|---|\n"
        "| Controversy | 1 | 0.0% |\n"
        "| KPIObservation | 2 | 50.0% |\n"
        "| MediaReport | 1 | 100.0% |\n"
        "| Penalty | 1 | 0.0% |\n\n"
        "## Hub clusters (A1)\n\n"
        "| ticker | nodes | degree |\n|---|---|---|\n"
        "| _unregistered | 1 | 9 |\n\n"
        "R5 (max hub-cluster degree): 9\n\n"
        "## Reasoning readiness (R1 / R1' / R7)\n\n"
        "- R1 (masked-edge re-derivable ≤ 3 hops): 47.8% (23 edges)\n"
        "- R1' (R1, hub-free): 0.0% (11 edges)\n"
        "- R1_trainable (R1, degenerate relations excluded): 47.8% (23 edges; excluded: [])\n"
        "- R7 (hub-free length-3 metapaths, support ≥ 50): 0 metapath(s)\n"
    )
    schema = load_schema()
    got = new_quality.render_markdown(mini_report(new_quality, schema))
    assert got == expected, f"render_markdown diverged:\n--- got ---\n{got}\n--- expected ---\n{expected}"


def test_quality_metrics_on_real_graph_are_well_formed():
    """The resolved graph as it really is — 10k nodes of shapes no fixture invents.
    Exact-value correctness is covered by the mini-graph golden report above; this arm's
    job is that every Q-function returns its documented shape at real scale without
    crashing. skip_slow=True: Q7(c)/(d) cost ~44s per call (the mini-graph arm above
    already exercises that BFS logic on a graph small enough to run it every time).
    """
    if not RESOLVED_DATA.exists():
        _skip("quality/real-graph", f"{RESOLVED_FILE.name} absent (run data_sync pull)")
        return
    print(f"     {tag(RESOLVED_IS_FIXTURE)} quality/real-graph")
    graph = json.loads(RESOLVED_DATA.read_text(encoding="utf-8"))
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    schema = load_schema()
    assert isinstance(new_quality.q1_accuracy(nodes), dict)
    assert isinstance(new_quality.q2_consistency(nodes, edges, schema), dict)
    assert isinstance(new_quality.q3_conciseness(nodes), dict)
    assert isinstance(new_quality.q4_completeness(nodes), dict)
    assert isinstance(new_quality.q5_timeliness(nodes, edges), dict)
    assert isinstance(new_quality.q6_provenance(nodes), dict)
    q7 = new_quality.q7_traversability(nodes, edges, 4, True)
    assert isinstance(q7, dict) and "hubs" in q7 and isinstance(q7["hubs"], list)
    assert q7["r5_max_hub_degree"] > 0
    for key in ("c_masked_queries_answerable_pct", "d_claims_structural_path_to_conduct_pct",
                "r1_reachability_pct", "r1_prime_hub_free_pct", "r1_trainable_pct",
                "r7_metapaths_hub_free"):
        assert q7[key] is None, f"q7.{key} must be None under skip_slow=True, got {q7[key]!r}"
    assert isinstance(new_quality.q8_independence(nodes), dict)
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


def test_canonicalize_constants_are_the_documented_shape():
    assert new_canonicalize.STANDARD_CODE_RE.pattern == r"^(TT96-|QD2171|QCVN09|SSCIFC-)"
    assert new_canonicalize.DEFAULT_FUZZY_THRESHOLD == 92
    assert [p.pattern for p in new_canonicalize.GOAL_YEAR_PATTERNS] == [
        r"(?:đến|vào|trước|tới)\s*năm\s*(20\d{2})",
        r"giai\s*đoạn\s*20\d{2}\s*[-–—]\s*(20\d{2})",
        r"\bby\s*(20\d{2})"]


def test_canonicalize_default_paths_are_repo_relative():
    assert new_canonicalize.DEFAULT_TRIPLES == TRIPLES_FILE
    assert new_canonicalize.DEFAULT_DEFS == KPI_DEFS_FILE
    assert new_canonicalize.DEFAULT_ALIASES == KPI_ALIASES_FILE
    assert new_canonicalize.DEFAULT_STATS_OUT == REPO / "graph_output" / "validated" / "kpi_canonical_stats.json"


def test_canonicalize_pure_helpers_on_hand_picked_cases():
    """Golden values captured directly from the functions (2026-07-29)."""
    titles = [
        ("  Tiêu hao ĐIỆN năng  ", "tiêu hao điện năng"),
        ("Male employees", "male employees"), ("", ""), (None, ""),
        ("Lợi nhuận sau thuế.", "lợi nhuận sau thuế"),
        ("(Tổng số lao động)", "tổng số lao động"),
        ("nước thải — sản xuất", "nước thải — sản xuất"),
    ]
    for t, expected in titles:
        got = new_canonicalize.normalize_title(t)
        assert got == expected, f"{t!r}: got {got!r}, expected {expected!r}"

    periods = [
        ({"year": 2012}, "2012"), ({"year": "2013"}, "2013"), ({"target_year": 2030}, "2030"),
        ({"valid_from": "2011-01-01"}, "2011"), ({"year": 99}, None), ({}, None),
    ]
    for props, expected in periods:
        got = new_canonicalize.derive_period(props)
        assert got == expected, f"{props}: got {got}, expected {expected}"

    scales = {"nghìn m3": {"factor": 1000, "base": "m³"}, "mwh": {"factor": 1000, "base": "kWh"}}
    rescales = [
        ((5, "nghìn m3"), (5000.0, "m³")), ((2.5, "MWh"), (2500.0, "kWh")),
        (("x", "MWh"), (None, None)), ((5, "chưa biết"), (None, None)),
    ]
    for (value, unit), expected in rescales:
        got = new_canonicalize.rescale_value(value, unit, scales)
        assert got == expected, f"({value}, {unit}): got {got}, expected {expected}"


def test_canonicalize_matcher_is_well_formed_on_the_whole_vocabulary():
    """Drive the matcher over every official name and every alias — not a sample. Exact
    match-result correctness for the real corpus is covered by the non-vacuity arm below
    (`by_method` tiers firing); this arm's job is that the matcher never crashes on any
    vocabulary entry and every probe returns its documented shape."""
    defs, aliases = load_kpi_vocab()
    m = new_canonicalize.Matcher(defs, aliases)
    assert m.valid_ids == {d["id"] for d in defs}
    assert isinstance(m.exact, dict) and isinstance(m.contains, list)
    assert isinstance(m.reject_units, set) and isinstance(m.units_of, dict)

    probes = [(d["name"], "") for d in defs]
    for rule in aliases.get("rules") or []:
        units = rule.get("units") or [""]
        for t in (rule.get("exact") or []) + (rule.get("contains") or []):
            probes.append((t, units[0]))
    probes += [("Lợi nhuận sau thuế", "tỷ đồng"), ("", "người"), ("khong ton tai", "cái")]
    for title, unit in probes:
        result = m.match(title, unit)
        assert result is None or (isinstance(result, tuple) and len(result) == 2 and
                                  (result[0] is None or result[0] in m.valid_ids)), \
            (title, unit, result)
    print(f"     ({len(probes)} vocabulary probes compared)")


def test_canonicalize_on_the_real_corpus_is_well_formed():
    """The real corpus, patched in place — every KPIObservation must come out with a
    well-formed stamp (or none). Exact-result correctness is covered by the hand-picked
    cases above; the non-vacuity arm below covers that every tier actually fires."""
    triples = load_triples()
    if not triples:
        _skip("canonicalize/corpus", f"{TRIPLES_FILE.name} absent (run data_sync pull)")
        return
    print(f"     {tag(TRIPLES_IS_FIXTURE)} canonicalize/corpus")
    defs, aliases = load_kpi_vocab()
    work = json.loads(json.dumps(triples))

    stats = new_canonicalize.canonicalize_kpis(work, new_canonicalize.Matcher(defs, aliases))
    assert isinstance(stats, dict) and "distinct_kpi_nodes" in stats

    props = kpi_props(work)
    for i, p in enumerate(props):
        if "kpi_id" in p:
            assert p["kpi_id"] is None or isinstance(p["kpi_id"], str), f"KPIObservation #{i}: {p}"

    goal_stats = new_canonicalize.backfill_goal_target_date(work)
    assert isinstance(goal_stats, dict)
    print(f"     ({len(props)} real KPIObservation occurrences compared, "
          f"{stats['distinct_kpi_nodes']} distinct)")


def test_canonicalize_corpus_arm_is_not_vacuous():
    """Guard the arm above: if the corpus produced no mapped AND no rejected node, it
    would be comparing two empty piles and still 'PASS'."""
    triples = load_triples()
    if not triples:
        _skip("canonicalize/not-vacuous", f"{TRIPLES_FILE.name} absent")
        return
    # Tier B: this arm asserts real corpus SCALE (>100 distinct KPI nodes) and
    # that all four matcher tiers fire. The synthetic fixture is deliberately
    # tiny, so it cannot satisfy either -- and lowering the thresholds to fit
    # would turn a real check into a decorative one. Skip instead.
    if TRIPLES_IS_FIXTURE:
        _skip("canonicalize/not-vacuous", skip_if_fixture(True))
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


def test_graph_patch_temporal_md_matches_the_formula():
    """TODAY is computed at import time (`date.today().isoformat()`), so it can't be a
    hardcoded golden value — the formula it plugs into can: recorded_at is always
    TODAY, valid_from/valid_to always pass through unchanged."""
    assert new_graph_patch.TODAY == __import__("datetime").date.today().isoformat()
    for props in [{"valid_from": "2023", "valid_to": "2024"},
                  {"valid_from": "2023-01-01", "valid_to": None},
                  {"valid_from": None}, {}, {"unrelated": 1}]:
        md = new_graph_patch.temporal_md(props)
        assert md == {
            "valid_from": props.get("valid_from"), "valid_to": props.get("valid_to"),
            "recorded_at": new_graph_patch.TODAY,
        }, props


def test_graph_patch_norm_on_hand_picked_cases():
    cases = [
        ("Thông tư 96/2020/TT-BTC", "thong tu 96 2020 tt btc"),
        ("  CÔNG TY CP Nhựa An Phát  ", "nhua an phat"),
        ("", ""), (None, ""), (12, "12"),
    ]
    for s, expected in cases:
        got = new_graph_patch.norm(s)
        assert got == expected, f"{s!r}: got {got!r}, expected {expected!r}"


def _mask_recorded_at(out: dict) -> dict:
    """`drive_graph_patch`'s output embeds `recorded_at` (today's date) inside the
    fixture graph's edges — mask it the same way the other non-determinism arms do."""
    out = dict(out)
    graph = json.loads(json.dumps(out["graph"]))
    for e in graph.get("edges", []):
        tm = e.get("temporal_metadata")
        if isinstance(tm, dict) and "recorded_at" in tm:
            tm["recorded_at"] = "<TODAY>"
    out["graph"] = graph
    return out


def test_graph_patch_dedup_and_append_golden():
    """GraphPatch's find/ensure_node/add_edge contract, against golden values captured
    directly from the module (2026-07-29, `recorded_at` masked to a fixed placeholder)."""
    sets = new_schema.load_schema_sets(load_schema())
    out = _mask_recorded_at(drive_graph_patch(new_graph_patch, sets))
    expected = {
        "n_nodes0": 3, "n_edges0": 1,
        "find_doc": 0, "find_indicator": 1, "find_missing": None,
        "ensure_dup": (1, False), "ensure_new": (3, True),
        "edge_legal": True, "edge_duplicate": False, "edge_extra": True,
        "edge_unknown_label": False, "edge_wrong_direction": False,
        "dropped_invalid": 2,
        "by_id": {("Regulation", "thong tu 96 2020 tt btc"): 0,
                  ("StandardIndicator", "tt96 6 1 1"): 1,
                  ("KPIObservation", ""): 2,
                  ("StandardIndicator", "gri 305 1"): 3},
        "edgeset": {(1, "partOf", 0), (2, "measuredUnder", 1), (3, "partOf", 0)},
        "graph": {
            "nodes": [
                {"class": "Regulation", "properties": {"name": "Thông tư 96/2020/TT-BTC", "is_current": True}},
                {"class": "StandardIndicator", "properties": {"id": "TT96-6.1.1", "name": "Phát thải khí nhà kính",
                                                              "pillar": "Môi trường", "valid_from": "2020", "valid_to": None}},
                {"class": "KPIObservation", "properties": {"kpi_id": "TT96-6.1.1", "title": "Tổng phát thải",
                                                           "valid_from": "2023", "valid_to": None}},
                {"class": "StandardIndicator", "properties": {"id": "GRI 305-1", "name": "Direct GHG"}},
            ],
            "edges": [
                {"subject": 2, "predicate": "measuredUnder", "object": 1,
                 "temporal_metadata": {"valid_from": "2023", "valid_to": None}},
                {"subject": 1, "predicate": "partOf", "object": 0,
                 "temporal_metadata": {"valid_from": "2020", "valid_to": None, "recorded_at": "<TODAY>"},
                 "anchor_method": "offline_indicator_map"},
                {"subject": 3, "predicate": "partOf", "object": 0,
                 "temporal_metadata": {"valid_from": "2020", "valid_to": None, "recorded_at": "<TODAY>"},
                 "anchor_method": "offline_indicator_map", "confidence": 0.9},
            ],
        },
    }
    for key in sorted(expected):
        assert out[key] == expected[key], f"GraphPatch diverged on {key!r}:\n  got={out[key]}\n  expected={expected[key]}"


def test_graph_patch_assert_append_only_draws_the_documented_line():
    """This is the invariant behind step06's `_node_key = "n{i}"` and the positional
    node refs in the step07 dossiers: appends and in-place property edits are fine,
    everything that could shift or remove a positional reference is not."""
    sets = new_schema.load_schema_sets(load_schema())
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


def test_indicators_constants_are_the_documented_shape():
    # TODAY / norm belong to core/graph_patch.py now — their arms are test_graph_patch_*
    # above. KEYWORDS is a large, growing lookup table (same treatment as naming's
    # OCR_FIXES/LEGAL_FORMS/SYNONYMS) — checked for shape/coverage, not pinned verbatim;
    # the match_keyword probes below are what catch an entry breaking.
    assert new_indicators.DOC_OF_PREFIX == [
        ("TT96-", ("TT96", "Regulation")), ("QD2171", ("QD2171", "Regulation")),
        ("QCVN09", ("QCVN09", "Standard")), ("SSCIFC-", ("SSCIFC", "Standard"))]
    assert new_indicators.DOC_CANONICAL == {
        "TT96": "Thông tư 96/2020/TT-BTC", "QD2171": "Quyết định 2171/QĐ-BXD",
        "QCVN09": "QCVN 09:2017/BXD",
        "SSCIFC": "Sổ tay hướng dẫn công bố thông tin ESG (SSC-IFC)", "GRI": "GRI Standards"}
    assert isinstance(new_indicators.KEYWORDS, dict) and len(new_indicators.KEYWORDS) > 0
    for ind_id, phrases in new_indicators.KEYWORDS.items():
        assert isinstance(phrases, list) and phrases, ind_id


def test_indicators_default_paths_are_repo_relative():
    assert new_indicators.DEFAULT_RESOLVED == RESOLVED_FILE
    assert new_indicators.DEFAULT_DEFS == KPI_DEFS_FILE
    assert new_indicators.DEFAULT_CROSSWALK == CROSSWALK_FILE
    assert new_indicators.DEFAULT_SCHEMA == SCHEMA_FILE
    assert new_indicators.DEFAULT_STATS_OUT == RESOLVED_FILE.parent / "indicator_axis_stats.json"
    assert new_indicators.GRI_CATALOG_PATH == GRI_CATALOG_FILE


def test_indicators_pure_helpers_on_hand_picked_cases():
    """Golden values captured directly from the functions (2026-07-29)."""
    doc_keys = [("TT96-6.1.1", ("TT96", "Regulation")), ("QD2171-1", ("QD2171", "Regulation")),
                ("QCVN09-1", ("QCVN09", "Standard")), ("SSCIFC-S6", ("SSCIFC", "Standard")),
                ("GRI 305-1", None), ("", None), ("TT96", None)]
    for ind, expected in doc_keys:
        got = new_indicators.doc_key_for(ind)
        assert got == expected, f"{ind!r}: got {got}, expected {expected}"

    defs, catalog = fixture_defs(), fixture_catalog()
    for d in defs:
        node = new_indicators.make_indicator_node(d)
        assert node["class"] == "StandardIndicator"
        assert node["properties"]["id"] == d["id"]
        assert node["properties"]["is_current"] is True

    for key, kind in (("TT96", "Regulation"), ("GRI", "Standard")):
        canonical = new_indicators.DOC_CANONICAL[key]
        node = new_indicators.make_doc_node(key, kind, canonical)
        assert node == {"class": kind, "properties": {
            "name": canonical, "valid_from": None, "valid_to": None, "is_current": True}}

    gri_cases = [
        ("GRI 305-1", "Direct GHG", "Phát thải khí nhà kính trực tiếp (Scope 1)", "Chỉ số công bố GRI 305-1", "Môi trường"),
        ("GRI 2-27", None, "Tuân thủ pháp luật và quy định", "Chỉ số công bố GRI 2-27", "Quản trị"),
        ("GRI 999-9", "Không có trong catalog", "Không có trong catalog",
         "Chỉ số GRI 999-9: Không có trong catalog", None),
        ("GRI 999-9", None, "GRI 999-9", "Chỉ số GRI 999-9: GRI 999-9", None),
    ]
    for code, name, exp_name, exp_def, exp_pillar in gri_cases:
        node = new_indicators.make_gri_node(code, name, catalog)
        assert node["properties"]["id"] == code
        assert node["properties"]["name"] == exp_name, code
        assert node["properties"]["definition"] == exp_def, code
        assert node["properties"]["pillar"] == exp_pillar, code

    assert new_indicators.pillar_authority(defs, catalog) == {
        "TT96-6.1.1": "Môi trường", "TT96-6.5.1": "Môi trường", "TT96-6.5.2": "Môi trường",
        "TT96-6.6.3": "Xã hội", "GRI 2-27": "Quản trị", "GRI 305-1": "Môi trường"}

    # load_gri_catalog degrades to {} on a missing/broken file
    assert new_indicators.load_gri_catalog(REPO / "config" / "does_not_exist.json") == {}
    if GRI_CATALOG_FILE.exists():
        assert isinstance(new_indicators.load_gri_catalog(GRI_CATALOG_FILE), dict)

    # restamp mutates in place; TT96-6.6.3's stale "Môi trường" -> authority's "Xã hội"
    authority = new_indicators.pillar_authority(defs, catalog)
    nodes = fixture_graph()["nodes"]
    changes = new_indicators.restamp_pillars(nodes, authority)
    assert dict(changes) == {"TT96-6.6.3: Môi trường -> Xã hội": 1}
    restamped = next(n for n in nodes if n["class"] == "StandardIndicator")
    assert restamped["properties"]["pillar"] == "Xã hội"

    # keyword tier: longest matching phrase wins (pinned as-is; changing it is a
    # behaviour commit under DESIGN.md §5.3, not something to "fix" toward older docs)
    kw = new_indicators.build_keyword_index(defs, catalog)
    probes = [
        ("Cam kết giảm phát thải khí nhà kính đến 2030", "TT96-6.1.1"),
        ("Tiết kiệm năng lượng và tiêu thụ năng lượng", "TT96-6.3.2"),  # two candidates, longest wins
        ("An toàn lao động tại nhà máy", "SSCIFC-S5"),
        ("Không liên quan gì cả", None), ("", None),
        ("Tuân thủ pháp luật và quy định về môi trường", "GRI 2-27"),
    ]
    for text, expected in probes:
        got = new_indicators.match_keyword(text, kw)
        assert got == expected, f"{text!r}: got {got!r}, expected {expected!r}"


def test_indicators_run_branches_on_temp_workspace_are_well_formed():
    """The stage-level flag switches (no_gri/no_align/trust_draft_crosswalk/dry_run) must
    each run cleanly and return the documented (graph, stats) shape. The main path's
    exact behaviour on this same fixture is pinned in depth by
    test_indicators_temp_workspace_arm_is_not_vacuous below (edges minted, self-reported-
    zero Penalty, document reuse, confirmed-crosswalk gate) — this arm's job is the
    switches, not re-proving the main path."""
    defs, crosswalk, catalog = fixture_defs(), fixture_crosswalk(), fixture_catalog()
    for overrides in ({}, {"no_gri": True}, {"no_align": True},
                      {"trust_draft_crosswalk": True}, {"dry_run": True}):
        graph, stats = run_indicators(new_indicators, fixture_graph(), defs, crosswalk, catalog,
                                      **overrides)
        assert isinstance(graph, dict) and "nodes" in graph and "edges" in graph, overrides
        if overrides.get("dry_run"):
            assert stats is None, "dry_run must write no stats file"
        else:
            assert isinstance(stats, dict), overrides


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


def test_indicators_on_the_real_graph_rebuilds_the_axis():
    """The strongest arm: the real resolved graph, stripped back to its pre-axis state so
    the run does the full job (67 indicators / ~1,400 axis edges) rather than a no-op."""
    if not RESOLVED_DATA.exists():
        _skip("indicators/real-graph", f"{RESOLVED_FILE.name} absent (run data_sync pull)")
        return
    if not (KPI_DEFS_FILE.exists() and CROSSWALK_FILE.exists() and GRI_CATALOG_FILE.exists()):
        _skip("indicators/real-graph", "defs/crosswalk/gri_catalog missing")
        return

    print(f"     {tag(RESOLVED_IS_FIXTURE)} indicators/real-graph")
    base = strip_axis(json.loads(RESOLVED_DATA.read_text(encoding="utf-8")))
    defs = json.loads(KPI_DEFS_FILE.read_text(encoding="utf-8"))
    crosswalk = json.loads(CROSSWALK_FILE.read_text(encoding="utf-8"))
    catalog = json.loads(GRI_CATALOG_FILE.read_text(encoding="utf-8"))

    graph, stats = run_indicators(new_indicators, base, defs, crosswalk, catalog)

    # not vacuous: the stripped graph really was rebuilt, not re-read
    for label in ("partOf", "measuredUnder", "equivalentTo", "alignsWithIndicator"):
        assert stats["created_edges"].get(label, 0) > 0, \
            f"{label} not rebuilt on the real graph: {stats['created_edges']}"
    assert stats["created_nodes"].get("StandardIndicator", 0) > 0, stats
    assert stats["penalty_self_reported_zero"] > 0, stats
    assert len(graph["nodes"]) == stats["nodes_before"] + stats["nodes_added"]
    print(f"     ({stats['nodes_before']} real nodes, "
          f"+{stats['nodes_added']} indicators, +{stats['edges_added']} axis edges)")


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
