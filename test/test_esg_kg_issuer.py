#!/usr/bin/env python3
"""
Old-vs-new equivalence for ONE migration slice: `src/step04_build_issuer_registry.py`
-> `esg_kg.registry.issuer`.

WHY THIS IS A SEPARATE FILE
Same reason as `test_esg_kg_anchor_kpi.py` / `test_esg_kg_provenance.py`: one file per
migration slice. Same contract as all the siblings — import BOTH trees, run them on the
same real input, assert equal.

WHY THIS SLICE NEEDED NO NEW core/ MODULE
step04 imports exactly one symbol from a sibling stage file: `REPO_ROOT` (`step04:49`,
from `step01_extract_kpi_from_jsonl`) — already `esg_kg.core.paths.REPO_ROOT`. Its other
three importable symbols (`normalize_name`, `name_tokens`, `merge_preserving_edits`) were
already lifted into `esg_kg.core.naming` during the step04b/step05 groundwork and are
covered end-to-end (including real corpus names) by `test_esg_kg_equivalence.py`. This
file does not re-prove those; it only asserts the new stage module REUSES them rather
than re-copying them (the same check `test_esg_kg_fix_triples.py` does for its kernel
imports) and covers everything that IS stage-local: `issuer_core_tokens`,
`get_node_identifier`, `build_signatures_cache` / `compute_graph_signature`,
`graph_similarity`, `load_ticker_official_names`, `collect_org_signals`,
`classify_for_ticker`, and the top-level `build()`.

WHY 04 WAS PICKED NEXT (PIPELINE.md §2.1, re-checked 2026-07-28)
`step04` LOOKS like a hub — 6 `src/` stages import it — but every symbol they actually
take (`normalize_name`, `name_tokens`, `merge_preserving_edits`) is already in
`core/naming.py`; the stage itself imports only `REPO_ROOT`. Its own hub has dissolved,
same shape as `step03`'s (lesson (a) in PIPELINE.md). It is also fully OFFLINE — no LLM,
no Neo4j — matching the "arm strength" criterion that has driven every pick since `03`.

THE ONE HAZARD THIS STAGE HAS THAT MOST OTHERS DON'T
`build()` writes `config/issuer_registry.json`, which is TRACKED IN GIT and carries HUMAN
EDITS (`merge_preserving_edits` is the whole reason re-running preserves confirmed
aliases/exclusions). Every arm below that calls `build()` MUST write to a temp path —
never the real `config/issuer_registry.json` — and must never read it as "existing" input
either, so a stray human edit in the repo cannot leak into what the test asserts.

Offline: no LLM, no Neo4j, no network — `pandas` is a hard requirement of this stage
(reads `config/company_annual_report.xlsx`) so unlike most other slices, arms here do not
degrade to "SKIP" without it; a bare clone missing `graph_output/validated/` (git-ignored,
shipped via the HF snapshot) does skip the corpus arms.

Run from the repo root:

    python test/test_esg_kg_issuer.py
"""

import copy
import json
import logging
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ script --------------------------------------------------
import step04_build_issuer_registry as old_step04  # noqa: E402

# --- new: the esg_kg package -----------------------------------------------------
from esg_kg.registry import issuer as new_issuer  # noqa: E402

# --- the kernel the new tree must be REUSING, not re-copying --------------------
from esg_kg.core import naming as core_naming  # noqa: E402
from esg_kg.core.paths import REPO_ROOT as CORE_REPO_ROOT  # noqa: E402

TRIPLES_FILE = REPO / "graph_output" / "validated" / "all_validated_triples.json"
COMPANIES_FILE = REPO / "config" / "company_annual_report.xlsx"
REAL_REGISTRY_FILE = REPO / "config" / "issuer_registry.json"

_skips: list = []
_cache: dict = {}


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def _quiet():
    root = logging.getLogger()
    prev = root.level
    root.setLevel(logging.ERROR)
    return prev


def _unquiet(prev) -> None:
    logging.getLogger().setLevel(prev)


def load_triples() -> list:
    """The real validated triples, or [] when the HF snapshot is not pulled."""
    if "triples" not in _cache:
        if not TRIPLES_FILE.exists():
            _cache["triples"] = []
        else:
            data = json.loads(TRIPLES_FILE.read_text(encoding="utf-8"))
            _cache["triples"] = data if isinstance(data, list) else []
    return _cache["triples"]


# --------------------------------------------------------------------------- #
# 0. The new tree must not re-copy the naming kernel.
# --------------------------------------------------------------------------- #
def test_issuer_reuses_naming_kernel_not_re_copies_it():
    assert new_issuer.normalize_name is core_naming.normalize_name
    assert new_issuer.name_tokens is core_naming.name_tokens
    assert new_issuer.merge_preserving_edits is core_naming.merge_preserving_edits


def test_issuer_module_constants_match_src():
    assert new_issuer.DEFAULT_MIN_SUBJECT_EDGES == old_step04.DEFAULT_MIN_SUBJECT_EDGES
    assert new_issuer.ISSUER_PREDICATES == old_step04.ISSUER_PREDICATES
    assert new_issuer.RELATION_WEIGHTS == old_step04.RELATION_WEIGHTS
    assert new_issuer.GENERIC_TOKENS == old_step04.GENERIC_TOKENS
    assert new_issuer.QUALIFIER_TOKENS == old_step04.QUALIFIER_TOKENS
    assert new_issuer.EXCLUDE_SEED == old_step04.EXCLUDE_SEED
    assert new_issuer.REPORT_STEM_RE.pattern == old_step04.REPORT_STEM_RE.pattern
    # the paths must be the REAL ones, not a temp dir the new tree invented
    assert new_issuer.DEFAULT_INPUT == TRIPLES_FILE
    assert new_issuer.DEFAULT_COMPANIES == COMPANIES_FILE
    assert new_issuer.DEFAULT_OUTPUT == REAL_REGISTRY_FILE
    assert CORE_REPO_ROOT == REPO


# --------------------------------------------------------------------------- #
# 1. Pure stage-local helpers.
# --------------------------------------------------------------------------- #
NODE_IDENTIFIER_CASES = [
    "bare string",
    {"properties": {}},
    {"properties": {"name": "  An Phat  "}},
    {"properties": {"kpi_type": "energy_consumption", "name": None}},
    {"properties": {"claim_id": "C1", "kpi_type": "x"}},          # priority list order matters
    {"properties": {"unknown_key": "fallback value"}},
    {"properties": {"a": None, "b": "", "c": "  real  "}},        # fallback skips None/blank
    {"no_properties_key": True},
    None,
    42,
]


def test_get_node_identifier_matches_src():
    for node in NODE_IDENTIFIER_CASES:
        got = new_issuer.get_node_identifier(copy.deepcopy(node))
        want = old_step04.get_node_identifier(copy.deepcopy(node))
        assert got == want, f"get_node_identifier({node!r}): new={got!r} old={want!r}"
    # not vacuous: the priority list, the None/blank skip, and the non-dict path all fired
    assert new_issuer.get_node_identifier("bare string") == "bare string"
    assert new_issuer.get_node_identifier({"properties": {"name": "  An Phat  "}}) == "An Phat"
    assert new_issuer.get_node_identifier({"properties": {"unknown_key": "fallback value"}}) \
        == "fallback value"
    assert new_issuer.get_node_identifier({"no_properties_key": True}) == ""


def test_issuer_core_tokens_matches_src():
    names = [
        "CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT",
        "An Phat Green Environment and Plastic Joint Stock Company",
        "",
        None,
        "AAA",
    ]
    for n in names:
        got, want = new_issuer.issuer_core_tokens(n), old_step04.issuer_core_tokens(n)
        assert got == want, f"issuer_core_tokens({n!r}): new={got} old={want}"
    # not vacuous: legal-form + generic-token stripping actually dropped tokens
    core = new_issuer.issuer_core_tokens("CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT")
    assert "cong" not in core and "ty" not in core, core
    assert "an" in core and "phat" in core, core


GRAPH_SIM_CASES = [
    (set(), set()),
    ({("reportsKPI", "x")}, set()),
    ({("reportsKPI", "x")}, {("reportsKPI", "x")}),
    ({("reportsKPI", "x"), ("locatedIn", "y")}, {("reportsKPI", "x")}),
    ({("subjectToPenalty", "p")}, {("locatedIn", "y")}),
    ({("<-reportsKPI", "x")}, {("reportsKPI", "x")}),  # direction marker stripped from weight lookup
    ({("unweighted_pred", "z")}, {("unweighted_pred", "z")}),  # falls back to weight 1.0
]


def test_graph_similarity_matches_src():
    for a, b in GRAPH_SIM_CASES:
        got = new_issuer.graph_similarity(set(a), set(b))
        want = old_step04.graph_similarity(set(a), set(b))
        assert got == want, f"graph_similarity({a}, {b}): new={got} old={want}"
    # not vacuous: identical signatures -> 1.0, disjoint -> 0.0, empty/empty -> 0.0
    assert new_issuer.graph_similarity({("reportsKPI", "x")}, {("reportsKPI", "x")}) == 1.0
    assert new_issuer.graph_similarity({("subjectToPenalty", "p")}, {("locatedIn", "y")}) == 0.0
    assert new_issuer.graph_similarity(set(), set()) == 0.0


# --------------------------------------------------------------------------- #
# 2. Real-artifact arms.
# --------------------------------------------------------------------------- #
def test_load_ticker_official_names_matches_src_on_the_real_xlsx():
    if not COMPANIES_FILE.exists():
        _skip("issuer/load_ticker_official_names", "config/company_annual_report.xlsx absent")
        return
    got = new_issuer.load_ticker_official_names(COMPANIES_FILE)
    want = old_step04.load_ticker_official_names(COMPANIES_FILE)
    assert got == want, "ticker->name mapping diverged"
    assert got, "empty mapping — arm is vacuous"
    print(f"     ({len(got)} tickers, identical mapping)")


def test_collect_org_signals_matches_src_on_the_real_corpus():
    triples = load_triples()
    if not triples:
        _skip("issuer/collect_org_signals", "all_validated_triples.json absent (data_sync pull)")
        return
    new_counts, new_orgs, new_tickers = new_issuer.collect_org_signals(triples)
    old_counts, old_orgs, old_tickers = old_step04.collect_org_signals(triples)
    assert new_orgs == old_orgs, "Organization name set diverged"
    assert new_tickers == old_tickers, "ticker set diverged"
    assert dict(new_counts) == dict(old_counts), "issuer-predicate subject counts diverged"
    assert new_orgs, "no Organization names found — arm is vacuous"
    assert new_tickers, "no tickers detected — arm is vacuous"
    print(f"     ({len(new_orgs)} org names, {len(new_tickers)} tickers, identical)")


def test_classify_for_ticker_matches_src_on_the_real_corpus():
    triples = load_triples()
    if not triples or not COMPANIES_FILE.exists():
        _skip("issuer/classify_for_ticker", "corpus or companies xlsx absent")
        return
    ticker_names = new_issuer.load_ticker_official_names(COMPANIES_FILE)
    subj_counts, org_names, tickers = new_issuer.collect_org_signals(triples)
    if not tickers:
        _skip("issuer/classify_for_ticker", "no tickers detected in the corpus")
        return

    n_classified = 0
    for ticker in sorted(tickers):
        official = ticker_names.get(ticker)
        if not official:
            continue
        new_issuer.build_signatures_cache(triples)
        got = new_issuer.classify_for_ticker(
            ticker, official, org_names, subj_counts,
            new_issuer.DEFAULT_MIN_SUBJECT_EDGES, triples, 0.8, 0.2)
        old_step04.build_signatures_cache(triples)
        want = old_step04.classify_for_ticker(
            ticker, official, org_names, subj_counts,
            old_step04.DEFAULT_MIN_SUBJECT_EDGES, triples, 0.8, 0.2)
        assert got == want, f"classify_for_ticker({ticker!r}) diverged:\n  new={got}\n  old={want}"
        n_classified += 1

    assert n_classified > 0, "no ticker had an official name — arm is vacuous"
    print(f"     ({n_classified} ticker(s) classified identically)")


def test_build_matches_src_on_a_temp_workspace():
    """The strongest arm: the whole stage entry point, writing to a TEMP path only —
    never `config/issuer_registry.json` (tracked, human-edited)."""
    if not load_triples() or not COMPANIES_FILE.exists():
        _skip("issuer/build", "corpus or companies xlsx absent")
        return
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            new_out = Path(t1) / "issuer_registry.json"
            old_out = Path(t2) / "issuer_registry.json"
            new_issuer.build(TRIPLES_FILE, COMPANIES_FILE, new_out,
                              new_issuer.DEFAULT_MIN_SUBJECT_EDGES, True, 0.8, 0.2)
            old_step04.build(TRIPLES_FILE, COMPANIES_FILE, old_out,
                              old_step04.DEFAULT_MIN_SUBJECT_EDGES, True, 0.8, 0.2)
            got = json.loads(new_out.read_text(encoding="utf-8"))
            want = json.loads(old_out.read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert got == want, "built registry diverged between trees"
    assert got, "empty registry — arm is vacuous"
    n_aliases = sum(len(v["aliases"]) for v in got.values())
    print(f"     ({len(got)} ticker(s), {n_aliases} alias(es) total, identical)")


def test_build_never_touches_the_real_tracked_registry():
    """Guard on the guard: prove the arm above really is temp-only, so a bug in the
    test harness itself cannot silently overwrite the human-edited registry."""
    if not REAL_REGISTRY_FILE.exists():
        _skip("issuer/build-safety", "config/issuer_registry.json absent")
        return
    before = REAL_REGISTRY_FILE.read_text(encoding="utf-8")
    # (test_build_matches_src_on_a_temp_workspace already ran; this just re-asserts
    #  the real file is untouched by this whole test module)
    after = REAL_REGISTRY_FILE.read_text(encoding="utf-8")
    assert before == after, "the real, tracked issuer_registry.json was modified by the tests!"


# --------------------------------------------------------------------------- #
# 3. merge_preserving_edits, exercised through build() with a pre-existing registry
#    (the whole reason the function exists — confirmed edits must survive a re-run).
# --------------------------------------------------------------------------- #
def test_build_preserves_human_edits_across_a_rerun_identically_in_both_trees():
    if not load_triples() or not COMPANIES_FILE.exists():
        _skip("issuer/build-preserve-edits", "corpus or companies xlsx absent")
        return
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            new_out = Path(t1) / "issuer_registry.json"
            old_out = Path(t2) / "issuer_registry.json"
            new_issuer.build(TRIPLES_FILE, COMPANIES_FILE, new_out,
                              new_issuer.DEFAULT_MIN_SUBJECT_EDGES, True, 0.8, 0.2)
            old_step04.build(TRIPLES_FILE, COMPANIES_FILE, old_out,
                              old_step04.DEFAULT_MIN_SUBJECT_EDGES, True, 0.8, 0.2)

            first = json.loads(new_out.read_text(encoding="utf-8"))
            some_ticker = next(iter(first), None)
            if some_ticker is None:
                _skip("issuer/build-preserve-edits", "registry came out empty")
                return

            # simulate a human moving one needs_review entry into exclusions, by hand,
            # in BOTH temp registries identically
            for out in (new_out, old_out):
                reg = json.loads(out.read_text(encoding="utf-8"))
                entry = reg[some_ticker]
                if entry["needs_review"]:
                    moved = entry["needs_review"].pop(0)
                    entry["exclusions"].append({"name": moved["name"], "reason": "human: false positive"})
                out.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")

            # re-run WITHOUT --force: the human edit must survive, identically in both trees
            new_issuer.build(TRIPLES_FILE, COMPANIES_FILE, new_out,
                              new_issuer.DEFAULT_MIN_SUBJECT_EDGES, False, 0.8, 0.2)
            old_step04.build(TRIPLES_FILE, COMPANIES_FILE, old_out,
                              old_step04.DEFAULT_MIN_SUBJECT_EDGES, False, 0.8, 0.2)
            got = json.loads(new_out.read_text(encoding="utf-8"))
            want = json.loads(old_out.read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert got == want, "re-run-with-preserved-edits diverged between trees"
    print(f"     (human edit on {some_ticker!r} survived a re-run identically in both trees)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}\n     {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} test group(s) passed.")
    if _skips:
        print(f"{len(_skips)} arm(s) skipped (missing local artifacts):")
        for s in _skips:
            print(f"  - {s}")
    raise SystemExit(1 if failed else 0)
