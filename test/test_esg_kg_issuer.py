#!/usr/bin/env python3
"""
Coverage for `esg_kg.registry.issuer` (formerly an old-vs-new equivalence test against
`src/step04_build_issuer_registry.py`).

Repointed at `esg_kg` only (2026-07-29) now that `src/` is gone. The cross-tree
comparisons this file used to run have been removed; what remains are the independent,
new-tree-only assertions each function already carried (specific expected values,
invariants, non-vacuity checks) — see the per-function history below for what changed.

WHY THIS IS A SEPARATE FILE
Same reason as `test_esg_kg_anchor_kpi.py` / `test_esg_kg_provenance.py`: one file per
migration slice.

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

# --- the esg_kg package -----------------------------------------------------------
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
        assert isinstance(got, str), f"get_node_identifier({node!r}) returned non-str: {got!r}"
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
        got = new_issuer.issuer_core_tokens(n)
        assert isinstance(got, set), f"issuer_core_tokens({n!r}) returned non-set: {got!r}"
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
        assert isinstance(got, float), f"graph_similarity({a}, {b}) returned non-float: {got!r}"
        assert 0.0 <= got <= 1.0, f"graph_similarity({a}, {b}) out of [0,1]: {got!r}"
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
    assert got, "empty mapping — arm is vacuous"
    print(f"     ({len(got)} tickers, identical mapping)")


def test_collect_org_signals_matches_src_on_the_real_corpus():
    triples = load_triples()
    if not triples:
        _skip("issuer/collect_org_signals", "all_validated_triples.json absent (data_sync pull)")
        return
    new_counts, new_orgs, new_tickers = new_issuer.collect_org_signals(triples)
    assert new_orgs, "no Organization names found — arm is vacuous"
    assert new_tickers, "no tickers detected — arm is vacuous"
    print(f"     ({len(new_orgs)} org names, {len(new_tickers)} tickers, identical)")


def test_collect_org_signals_detects_ticker_from_plain_year_filename():
    """2026-08-08: REPORT_STEM_RE only matched the legacy `<TICKER>_Baocaothuongnien...`
    filename (true for some of AAA's older PDFs). Every current annual report — AAA's
    newer ones included — is named `<TICKER>_<year>.pdf` (data/raw/annual_report/.../
    HAR_2016.pdf, ACC_2013.pdf, ...), which never matched, so `collect_org_signals`
    silently detected ONLY AAA out of a corpus containing several companies. That single-
    ticker detection then fed `build()`'s tickers loop directly (see the test below for
    the data-loss consequence: a non-empty-but-incomplete detection defeats the
    empty-set fallback). This is the source-of-truth fix: the plain `<TICKER>_YYYY`
    convention must be detected too.
    """
    triples = [
        {"subject": {"class": "KPIObservation",
                     "properties": {"source_id": "HAR_2016.pdf_14_0", "kpi_type": "test"}},
         "object": {"class": "Organization", "properties": {"name": "Test Co"}},
         "predicate": "observedAtFacility"},
    ]
    _, _, tickers = new_issuer.collect_org_signals(triples)
    assert "HAR" in tickers, f"plain '<TICKER>_YYYY.pdf' source_id not detected: {tickers}"
    print("     ('HAR_2016.pdf_14_0' -> ticker 'HAR' detected)")


def test_build_carries_forward_tickers_not_rebuilt_this_run():
    """2026-08-08: a real run against the live registry demonstrated this deleting
    ACC/ACG/ADP/AGG — `registry = {}` starts empty and is only populated for tickers in
    THIS run's detected `tickers` set; anything in `existing` but not rebuilt this run
    was silently dropped rather than carried forward, despite the "preserving human
    edits" log line implying otherwise. Reproduced here with a synthetic OLDCO entry
    that has no signal at all in this run's (tiny, single-ticker) corpus.
    """
    if not COMPANIES_FILE.exists():
        _skip("issuer/build-carry-forward", "config/company_annual_report.xlsx absent")
        return
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t1:
            out_file = Path(t1) / "issuer_registry.json"
            oldco_entry = {
                "ticker": "OLDCO", "canonical_name": "A Company Not In This Run's Corpus",
                "core_tokens": ["old", "company"], "aliases": ["Old Co"],
                "exclusions": [], "needs_review": [],
            }
            out_file.write_text(json.dumps({"OLDCO": oldco_entry}, ensure_ascii=False), encoding="utf-8")

            triples_file = Path(t1) / "triples.json"
            triples_file.write_text(json.dumps([
                {"subject": {"class": "KPIObservation",
                             "properties": {"source_id": "AAA_2013.pdf_1_0", "kpi_type": "test"}},
                 "object": {"class": "Organization", "properties": {"name": "AAA"}},
                 "predicate": "observedAtFacility"},
            ], ensure_ascii=False), encoding="utf-8")

            new_issuer.build(triples_file, COMPANIES_FILE, out_file,
                              new_issuer.DEFAULT_MIN_SUBJECT_EDGES, False, 0.8, 0.2)
            got = json.loads(out_file.read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert "OLDCO" in got, (
        f"OLDCO was dropped even though it wasn't rebuilt this run — "
        f"only {sorted(got)} survived")
    assert got["OLDCO"] == oldco_entry, "OLDCO must be carried forward UNCHANGED"
    print(f"     (OLDCO carried forward untouched; {sorted(got)} in final registry)")


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
        assert isinstance(got, dict), \
            f"classify_for_ticker({ticker!r}) unexpected shape: {got!r}"
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
        with tempfile.TemporaryDirectory() as t1:
            new_out = Path(t1) / "issuer_registry.json"
            new_issuer.build(TRIPLES_FILE, COMPANIES_FILE, new_out,
                              new_issuer.DEFAULT_MIN_SUBJECT_EDGES, True, 0.8, 0.2)
            got = json.loads(new_out.read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert got, "empty registry — arm is vacuous"
    for ticker, entry in got.items():
        assert "aliases" in entry and "exclusions" in entry and "needs_review" in entry, \
            f"{ticker}: registry entry missing expected keys: {sorted(entry)}"
    n_aliases = sum(len(v["aliases"]) for v in got.values())
    print(f"     ({len(got)} ticker(s), {n_aliases} alias(es) total)")


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
def test_build_preserves_human_edits_across_a_rerun():
    """merge_preserving_edits' whole reason for existing: a human-made edit (moving a
    needs_review entry into exclusions) must survive a re-run without --force."""
    if not load_triples() or not COMPANIES_FILE.exists():
        _skip("issuer/build-preserve-edits", "corpus or companies xlsx absent")
        return
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t1:
            new_out = Path(t1) / "issuer_registry.json"
            new_issuer.build(TRIPLES_FILE, COMPANIES_FILE, new_out,
                              new_issuer.DEFAULT_MIN_SUBJECT_EDGES, True, 0.8, 0.2)

            first = json.loads(new_out.read_text(encoding="utf-8"))
            some_ticker = next(iter(first), None)
            if some_ticker is None:
                _skip("issuer/build-preserve-edits", "registry came out empty")
                return

            # simulate a human moving one needs_review entry into exclusions, by hand
            reg = json.loads(new_out.read_text(encoding="utf-8"))
            entry = reg[some_ticker]
            if not entry["needs_review"]:
                _skip("issuer/build-preserve-edits", f"{some_ticker} has no needs_review entries")
                return
            moved = entry["needs_review"].pop(0)
            entry["exclusions"].append({"name": moved["name"], "reason": "human: false positive"})
            new_out.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")

            # re-run WITHOUT --force: the human edit must survive
            new_issuer.build(TRIPLES_FILE, COMPANIES_FILE, new_out,
                              new_issuer.DEFAULT_MIN_SUBJECT_EDGES, False, 0.8, 0.2)
            got = json.loads(new_out.read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    got_entry = got[some_ticker]
    assert any(e["name"] == moved["name"] for e in got_entry["exclusions"]), (
        f"the human-moved exclusion for {moved['name']!r} did not survive the re-run "
        f"(exclusions: {got_entry['exclusions']})")
    assert not any(nr["name"] == moved["name"] for nr in got_entry["needs_review"]), (
        f"{moved['name']!r} was re-added to needs_review — the human edit was not preserved")
    print(f"     (human edit on {some_ticker!r} survived a re-run)")


# --------------------------------------------------------------------------- #
# 4. DESIGN.md §5.2 "VI PHẠM": step04:428's dead `{nodes,edges}` sniff.
# --------------------------------------------------------------------------- #
# step03 / build_validated always write all_validated_triples.json as a flat
# List[dict] (step03:545,622); step05 reads that exact file with no sniffing at
# all. build()'s `{nodes,edges}` branch therefore never fires on any real input —
# it is dead code pretending the input format is uncertain when it is not, flagged
# for removal at exactly this migration ("xoá khi dời step04, đọc theo đúng một
# hợp đồng"). Fixed in BOTH trees per DESIGN.md §5.3: a dict-shaped input must now
# fail loudly (AttributeError, iterating dict keys as fake triples) instead of
# being silently reinterpreted as a graph.
NODES_EDGES_SHAPE = {
    "nodes": [{"class": "Organization", "properties": {"name": "Test Co"}}],
    "edges": [{"subject": 0, "object": 0, "predicate": "publishesReport"}],
}


def test_build_no_longer_silently_converts_a_nodes_edges_dict():
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t:
            input_file = Path(t) / "fake_validated.json"
            input_file.write_text(json.dumps(NODES_EDGES_SHAPE), encoding="utf-8")
            out = Path(t) / "registry_esg_kg.json"
            raised = False
            try:
                new_issuer.build(input_file, COMPANIES_FILE, out,
                                  new_issuer.DEFAULT_MIN_SUBJECT_EDGES, True, 0.8, 0.2)
            except AttributeError:
                raised = True
            assert raised, (
                "esg_kg.registry.issuer still silently converts a {nodes,edges} dict — "
                "the DESIGN.md §5.2 dead branch was not removed")
    finally:
        _unquiet(prev)
    print("     (esg_kg now rejects the {nodes,edges} shape instead of sniffing it)")


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
