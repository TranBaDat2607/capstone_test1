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

Run from the repo root:

    python test/test_esg_kg_equivalence.py
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ scripts ------------------------------------------------
import step01_extract_kpi_from_jsonl as old_step01  # noqa: E402
import step02_extract_triplet_from_jsonl as old_step02  # noqa: E402
import step03_fix_invalid_triplets as old_step03  # noqa: E402
import step04_build_issuer_registry as old_step04  # noqa: E402

# --- new: the esg_kg package ---------------------------------------------------
from esg_kg.core import naming as new_naming  # noqa: E402
from esg_kg.core import paths as new_paths  # noqa: E402
from esg_kg.core import schema as new_schema  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
TRIPLES_FILE = REPO / "graph_output" / "validated" / "all_validated_triples.json"

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
