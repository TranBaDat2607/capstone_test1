#!/usr/bin/env python3
"""
Old-vs-new equivalence for ONE migration slice:
`src/step07_crosscheck_claims_vs_conduct.py` -> `esg_kg.crosscheck.claims_vs_conduct`.

WHY THIS IS A SEPARATE FILE
Same contract as `test_esg_kg_align_claims.py` / `_fix_triples.py` / `_provenance.py` /
`_anchor_kpi.py`: import BOTH trees, run them on the same real input, assert equal.
`test_esg_kg_equivalence.py` covers the kernel and is already past 1,100 lines; a whole
stage — especially this one, the highest-leverage remaining move (PIPELINE.md §2.1) —
gets its own file.

WHY THIS SLICE NEEDED NO NEW core/ MODULE
Every symbol step07 imports from a sibling stage was already lifted before this slice:
`REPO_ROOT` (-> core.paths, since step01's move), `load_schema_sets` (-> core.schema,
since step03), `normalize_name`/`name_tokens` (-> core.naming, since step04 was found to
be a dissolved hub), and `_Provider`/`_OpenAIProvider` (-> core.llm, 2026-07-27 — that
slice was EXTRACTED FROM step07 itself). `RateLimiter` was imported from step02 in the
old file but never referenced directly (only `_OpenAIProvider.__init__` used it) — same
dead-import shape the 05d slice found, so it is dropped here too.

`Adjudicator` stays in the stage, same as `core/llm.py`'s docstring always said it would:
it is prompt text + verdict parsing + provider cascade, i.e. stage logic, not kernel.

THE node_text TRAP (PIPELINE.md §2.1, DESIGN.md §2)
There are TWO functions named `node_text` and they are NOT interchangeable: THIS one
(step07:133) takes a NODE and dispatches on its `class`; `esg_kg.resolve.align_claims`'s
takes a PROPERTIES DICT. Merging them would silently rewrite whichever stage's paid
prompt lost its shape. `test_node_text_is_not_align_claims_node_text` pins the divergence
from the step07 side (align_claims' own test already pins it from the other side).

HOW THE PAID PATH IS COVERED WITHOUT PAYING
Same technique as the step03 phase-2 arm and the step05d headline arm: a STUB is injected
over `_OpenAIProvider` in both trees, answering deterministically from a CRC of the
adjudication prompt, so both trees see identical replies for identical (claim, evidence)
pairs. Unlike step05d, step07's `--dry-run` does NOT return before the provider is built
(it only skips the final file-writes) — so the dry-run arm also drives the full stub
adjudication path, and is a meaningful equivalence check in its own right, not just a
"nothing happens" check.

ONE NON-DETERMINISM TO MASK: `_mk_edge` stamps `recorded_at` with `datetime.now(...)`, so
the two trees (run one after the other) can disagree on that one field even though
everything else matches. `_edges_ignoring_recorded_at` strips it before comparison —
exactly as the align_claims arm masks the temp workspace path out of log lines.

THE IN-PLACE-PATCH QUESTION (PIPELINE.md §3) DOES NOT APPLY HERE
step07 reads `resolved_graph.json` (step05's/05b's/05c's/05d's output) and writes to a
DIFFERENT directory (`graph_output/crosscheck/`) — it never meets its own past output, so
the real-corpus arm is non-vacuous by construction. No `strip_*` fixture is needed, the
same shape step03's migration already established.

A DEFECT FOUND AND FIXED IN BOTH TREES (same file, follow-up commit to the migration)
`_parse_verdict` had the same latent defect step05d's `parse_reply` had before a308608:
`json.loads("[]")` succeeds (a list, not a dict), and the very next line called `.get()` on
it. Here the blast radius was smaller (the call site sits inside `Adjudicator.adjudicate`'s
own try/except, so it degraded to "no verdict for this pair" instead of losing an entire
run) but it was still a real defect: a merely-oddly-shaped reply got misfiled as a provider
*failure* rather than as an unusable-reply no-op. `test_parse_verdict_matches` exercises the
shapes the code already handled safely (pinned BEFORE the fix, so it stayed green
throughout); `test_parse_verdict_rejects_non_object_json_in_BOTH_trees` is the red-first
test for the fix itself — same order step05d's fix followed its migration.

Offline: no LLM, no Neo4j, no network — the stub replaces `_OpenAIProvider` before it can
look for `OPENAI_API_KEY` (which happens to be set in this environment; the stub still
wins because the code re-reads the module-global name at call time). `config/schema.json`
is tracked in git so the synthetic arms always run; arms needing `graph_output/resolved/
resolved_graph.json` (git-ignored, shipped via the HF snapshot) SKIP with a message on a
bare clone.

Run from the repo root:

    python test/test_esg_kg_crosscheck.py
"""

import argparse
import copy
import json
import logging
import shutil
import sys
import tempfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "src_module"))

# --- old: the flat src/ script --------------------------------------------------
import step07_crosscheck_claims_vs_conduct as old_step07  # noqa: E402

# --- new: the esg_kg package -----------------------------------------------------
from esg_kg.core import llm as core_llm  # noqa: E402
from esg_kg.core import naming as core_naming  # noqa: E402
from esg_kg.core import paths as core_paths  # noqa: E402
from esg_kg.core import schema as core_schema  # noqa: E402
from esg_kg.crosscheck import claims_vs_conduct as new_step07  # noqa: E402
from esg_kg.resolve import align_claims as new_align_claims  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
RESOLVED_FILE = REPO / "graph_output" / "resolved" / "resolved_graph.json"

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


# --------------------------------------------------------------------------- #
# The stub provider. Deterministic from the adjudication prompt, so BOTH trees
# see the same replies for the same (claim, evidence) pair.
# --------------------------------------------------------------------------- #
def make_stub(mode: str = "mixed"):
    """Return a class with `_OpenAIProvider(model, rate_limit)`'s interface.

    `mode="mixed"` walks 5 reply shapes the parser must survive today (clean supports/
    contradicts/irrelevant, JSON wrapped in prose, and unparseable prose -> None).
    `mode="always_raise"` drives the 3-failures-0-successes disable branch.
    `mode="always_supports"` / `"always_contradicts"` pin one verdict for every pair —
    used by the targeted assessment-mapping and self-verification-guard arms.
    """
    calls_seen: list = []

    class _Stub:
        name = "openai"

        def __init__(self, model, rate_limit):
            self.model = model
            self.rate_limit = rate_limit
            self.enabled = True
            self.calls = 0
            self.failures = 0
            self.seen = calls_seen

        def call(self, system, user):
            calls_seen.append((system, user))
            if mode == "always_raise":
                raise RuntimeError("stub: provider is down")
            if mode == "always_supports":
                return json.dumps({"verdict": "supports", "confidence": 0.8, "rationale": "stub"})
            if mode == "always_contradicts":
                return json.dumps({"verdict": "contradicts", "confidence": 0.8, "rationale": "stub"})
            crc = zlib.crc32(user.encode("utf-8"))
            shape = crc % 5
            if shape == 0:
                return json.dumps({"verdict": "supports", "confidence": 0.83, "rationale": "stub-supports"})
            if shape == 1:
                return json.dumps({"verdict": "contradicts", "confidence": 0.77, "rationale": "stub-contradicts"})
            if shape == 2:
                return json.dumps({"verdict": "irrelevant", "confidence": 0.5, "rationale": "stub-irrelevant"})
            if shape == 3:  # JSON wrapped in prose -> the regex fallback in _parse_verdict
                return f'Sure!\n{{"verdict": "supports", "confidence": 0.6, "rationale": "wrapped"}}\nDone.'
            return "I could not determine a verdict for this pair."  # unparseable -> None

    _Stub.calls_seen = calls_seen
    return _Stub


class Workspace:
    """A temp copy of a graph + an out-dir, so no arm ever touches the real artifacts."""

    def __init__(self, graph: dict):
        self.dir = Path(tempfile.mkdtemp(prefix="esgkg_step07_"))
        self.graph_path = self.dir / "resolved_graph.json"
        self.out_dir = self.dir / "crosscheck"
        self.graph_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")

    def args(self, **overrides) -> argparse.Namespace:
        args = argparse.Namespace(
            input=self.graph_path, schema=SCHEMA_FILE, out_dir=self.out_dir,
            ticker="AAA", top_k=8, window_before=1, window_after=50,
            max_llm_pairs=40, openai_model="gpt-4o-mini",
            provider_order=["openai"], max_workers=4, rate_limit=60,
            embed=False, dry_run=False, to_neo4j=False, database=None,
        )
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    def dossiers_path(self, ticker="AAA"):
        return self.out_dir / f"{ticker.lower()}_claim_assessments.json"

    def stats_path(self, ticker="AAA"):
        return self.out_dir / f"{ticker.lower()}_crosscheck_stats.json"

    @property
    def edges_path(self):
        return self.out_dir / "crosscheck_edges.json"

    def dossiers(self, ticker="AAA"):
        p = self.dossiers_path(ticker)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def stats(self, ticker="AAA"):
        p = self.stats_path(ticker)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def edges(self):
        return json.loads(self.edges_path.read_text(encoding="utf-8")) if self.edges_path.exists() else None

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class _LogCatcher(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def run_both(graph: dict, stub_mode: str = "mixed", **overrides):
    """Run the stage in BOTH trees on identical input; return (new_result, old_result).

    Each result is (Workspace, stub_class, masked_log_lines).
    """
    out = []
    for mod in (new_step07, old_step07):
        ws = Workspace(copy.deepcopy(graph))
        stub = make_stub(stub_mode)
        original = mod._OpenAIProvider
        handler = _LogCatcher()
        mod.logger.addHandler(handler)
        try:
            mod._OpenAIProvider = stub
            mod.run(ws.args(**overrides))
        finally:
            mod._OpenAIProvider = original
            mod.logger.removeHandler(handler)
        out.append((ws, stub, [m.replace(str(ws.dir), "<WS>") for m in handler.messages]))
    return out[0], out[1]


def _edges_ignoring_recorded_at(edges):
    """Strip the one genuinely non-deterministic field (`recorded_at`, wall-clock at the
    moment `_mk_edge` ran) so two runs of the SAME logic can be compared for equality."""
    out = []
    for e in edges:
        e = copy.deepcopy(e)
        e["properties"].pop("recorded_at", None)
        out.append(e)
    return out


def real_graph():
    """The live resolved graph, or None on a bare clone (git-ignored, HF-shipped)."""
    if not RESOLVED_FILE.exists():
        return None
    return json.loads(RESOLVED_FILE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 1. Module surface: constants, and that the new tree IMPORTS the kernel
# --------------------------------------------------------------------------- #
def test_constants_match():
    for name in ("DEFAULT_INPUT", "DEFAULT_SCHEMA", "DEFAULT_OUT_DIR", "DEFAULT_OPENAI_MODEL",
                 "DEFAULT_PROVIDER_ORDER", "DEFAULT_RATE_LIMIT", "DEFAULT_MAX_LLM_PAIRS",
                 "DEFAULT_TOP_K", "DEFAULT_WINDOW_BEFORE", "DEFAULT_WINDOW_AFTER"):
        assert getattr(new_step07, name) == getattr(old_step07, name), f"{name} diverged"

    assert new_step07.CONDUCT_CLASSES == old_step07.CONDUCT_CLASSES
    assert new_step07.SUPPORT_EDGE == old_step07.SUPPORT_EDGE
    assert new_step07.CONTRADICT_EDGE == old_step07.CONTRADICT_EDGE
    assert new_step07.COMPANY_DOMAINS == old_step07.COMPANY_DOMAINS
    assert new_step07.ISSUER_DOMAIN_TOKENS == old_step07.ISSUER_DOMAIN_TOKENS
    assert new_step07.STOPWORDS == old_step07.STOPWORDS

    # ADJUDICATE_SYSTEM is PAID BEHAVIOUR, not prose: reword it and the stage still "works"
    # while every verdict changes. Byte-for-byte, like SYSTEM in the align_claims slice.
    assert new_step07.ADJUDICATE_SYSTEM == old_step07.ADJUDICATE_SYSTEM, \
        "the paid ADJUDICATE_SYSTEM prompt was reworded"


def test_new_tree_imports_the_kernel_rather_than_recopying():
    """A migrated stage must USE core/, not carry its own copy — otherwise the two drift."""
    assert new_step07._OpenAIProvider is core_llm._OpenAIProvider, "_OpenAIProvider was re-copied"
    assert new_step07._Provider is core_llm._Provider, "_Provider was re-copied"
    assert new_step07.load_schema_sets is core_schema.load_schema_sets, "load_schema_sets re-copied"
    assert new_step07.normalize_name is core_naming.normalize_name, "normalize_name re-copied"
    assert new_step07.name_tokens is core_naming.name_tokens, "name_tokens re-copied"
    assert new_step07.REPO_ROOT == core_paths.REPO_ROOT


def test_new_tree_has_no_dead_ratelimiter_import():
    """The old file imports RateLimiter from step02 but never references it directly (only
    _OpenAIProvider.__init__ does, and that class now comes pre-built from core.llm) — the
    same dead-import shape the 05d slice found. The new module should not re-introduce it."""
    assert not hasattr(new_step07, "RateLimiter"), \
        "RateLimiter should not be imported directly into the migrated stage"


# --------------------------------------------------------------------------- #
# 2. Pure helpers
# --------------------------------------------------------------------------- #
def test_props_matches():
    cases = [{"properties": {"a": 1}}, {"properties": None}, {}]
    for n in cases:
        assert new_step07.props(n) == old_step07.props(n)


def test_node_text_matches():
    cases = [
        {"class": "KPIObservation", "properties": {"title": "t", "kpi_type": "energy",
                                                     "value": 10, "unit": "kWh", "kind": "actual"}},
        {"class": "KPIObservation", "properties": {}},
        {"class": "ThirdPartyVerification", "properties": {"verifier": "SGS", "result": "pass"}},
        {"class": "SustainabilityClaim", "properties": {"description": "giảm phát thải"}},
        {"class": "Controversy", "properties": {"title": "Vụ việc"}},
        {"class": "MediaReport", "properties": {"text": "bài báo"}},
        {"class": "Goal", "properties": {"name": "n", "term": "long"}},
        {"class": "Organization", "properties": {}},
    ]
    for n in cases:
        assert new_step07.node_text(n) == old_step07.node_text(n), f"node_text diverged: {n}"


def test_node_text_is_not_align_claims_node_text():
    """PIPELINE.md §2.1's documented trap, pinned from the step07 side (align_claims' own
    test already pins it from the other side). step07's node_text takes a NODE and
    dispatches on class; align_claims' takes a bare PROPERTIES dict."""
    node = {"class": "SustainabilityClaim", "properties": {"description": "giảm phát thải"}}
    assert new_step07.node_text(node) == "giảm phát thải"
    assert new_step07.node_text is not new_align_claims.node_text, \
        "step07's node_text was merged with align_claims'"
    # feeding step07's node shape to align_claims' node_text must NOT behave the same way
    assert new_align_claims.node_text(node) == "", \
        "align_claims' node_text accepted a full node — it takes a properties dict"


def test_node_year_matches():
    cases = [
        {"properties": {"publish_year": 2023}},
        {"properties": {"target_year": "2030"}},
        {"properties": {"year": "abcd"}},
        {"properties": {"date": "2021-05-01"}},
        {"properties": {"valid_from": "not a date"}},
        {"properties": {"claim_id": "social_activities_2011"}},
        {"properties": {}},
    ]
    for n in cases:
        assert new_step07.node_year(n) == old_step07.node_year(n), f"node_year diverged: {n}"


def test_node_domain_matches():
    cases = [
        {"properties": {"source_domain": "VnExpress.vn"}},
        {"properties": {"publisher": "tuoitre.vn"}},
        {"properties": {"source": "no-dot-here"}},
        {"properties": {}},
    ]
    for n in cases:
        assert new_step07.node_domain(n) == old_step07.node_domain(n), f"node_domain diverged: {n}"


def test_date_uncertain_matches():
    cases = [
        {"properties": {"date_uncertain": True}},
        {"properties": {"date_uncertain": "false"}},
        {"properties": {"date": "2021-01-01"}},
        {"properties": {"date": "2021-03-05"}},
        {"properties": {}},
    ]
    for n in cases:
        assert new_step07.date_uncertain(n) == old_step07.date_uncertain(n), f"date_uncertain diverged: {n}"


def test_topic_tokens_matches():
    cases = [("Công ty Nhựa An Phát giảm phát thải khí nhà kính", None),
             ("", {"extra", "tokens"}),
             ("Green Plastics environment report 2023", {"aaa"})]
    for text, extra in cases:
        assert new_step07.topic_tokens(text, extra) == old_step07.topic_tokens(text, extra)


def test_is_company_domain_matches():
    cases = ["aaa.com.vn", "AnPhatHoldings.vn", "vnexpress.net", "", "anphat-fake.co"]
    for d in cases:
        assert new_step07.is_company_domain(d) == old_step07.is_company_domain(d), f"diverged: {d}"


def test_mk_edge_matches():
    a = new_step07._mk_edge(0, "verifiedBy", 1, "supports", 0.9, "why", "news", "openai", True)
    b = old_step07._mk_edge(0, "verifiedBy", 1, "supports", 0.9, "why", "news", "openai", True)
    a["properties"].pop("recorded_at")
    b["properties"].pop("recorded_at")
    assert a == b


def test_parse_verdict_matches():
    """Shapes the CURRENT code already handles safely. The non-dict-JSON crash shape
    ('[]', '"txt"') is deliberately NOT exercised here — see the module docstring."""
    cases = [
        '{"verdict": "supports", "confidence": 0.9, "rationale": "r"}',
        '{"verdict": "contradicts"}',
        '{"verdict": "irrelevant", "confidence": "0.4"}',
        'blah {"verdict": "supports"} trailing',
        'no json here',
        '{"verdict": "unknown_value"}',
        '{broken json',
        '',
        None,
    ]
    for raw in cases:
        a = new_step07._parse_verdict(raw)
        b = old_step07._parse_verdict(raw)
        assert a == b, f"_parse_verdict diverged on {raw!r}: {a} vs {b}"
    assert new_step07._parse_verdict(cases[0])["verdict"] == "supports"
    assert new_step07._parse_verdict(cases[3])["verdict"] == "supports", "regex fallback regressed"
    assert new_step07._parse_verdict(cases[5]) is None, "an unknown verdict value must be rejected"


def test_parse_verdict_rejects_non_object_json_in_BOTH_trees():
    """Valid JSON of the wrong SHAPE must be refused like any other unusable reply.

    Same class of defect step05d's `parse_reply` had before a308608:
    `json.loads('[]')` succeeds (a list, not a dict), and the very next line calls
    `.get()` on it, raising AttributeError. Here the blast radius is smaller — the call
    site is inside `Adjudicator.adjudicate`'s own try/except, so a crash here degrades to
    "no verdict for this pair" rather than losing an entire run — but it is still wrong:
    it misfiles an oddly-shaped-but-parseable reply as a *provider failure* instead of an
    unusable-reply no-op, which pollutes `p.failures` and the "active" provider-health flag
    in the stats file for no good reason.

    Not reachable through the real provider today (`response_format={"type":"json_object"}`
    guarantees an object) — the same reason step05d's twin went unnoticed until a
    migration was the moment someone read the parser closely enough to see it.
    """
    for raw in ("[]", '"just a string"', "42", "null", "true"):
        for fn in (new_step07._parse_verdict, old_step07._parse_verdict):
            assert fn(raw) is None, f"{fn.__module__} mishandled {raw!r}"

    # the fix must not have made the parser lenient about anything else
    ok = '{"verdict": "supports", "confidence": 0.5}'
    assert new_step07._parse_verdict(ok)["verdict"] == "supports"
    assert new_step07._parse_verdict('[{"verdict": "supports"}]') is None, \
        "a LIST wrapping a good object must still be refused, not unwrapped"


# --------------------------------------------------------------------------- #
# 3. Graph indexing (pure, real corpus if available, else a tiny synthetic graph)
# --------------------------------------------------------------------------- #
def _tiny_indexing_graph():
    return {
        "nodes": [
            {"class": "Organization", "properties": {"ticker": "AAA", "name": "Issuer"}},
            {"class": "SustainabilityClaim", "properties": {"description": "giảm phát thải"}},
            {"class": "ClaimKeyword", "properties": {"term": "phát thải"}},
            {"class": "SustainabilityClaim", "properties": {"description": "khác"}},
        ],
        "edges": [
            {"subject": 0, "predicate": "claims", "object": 1},
            {"subject": 1, "predicate": "hasKeyword", "object": 2},
            {"subject": 0, "predicate": "claims", "object": 3},
        ],
    }


def test_graph_class_matches():
    data = real_graph() or _tiny_indexing_graph()
    ng, og = new_step07.Graph(data), old_step07.Graph(data)
    assert dict(ng.out) == dict(og.out)
    assert dict(ng.inc) == dict(og.inc)
    for i in range(min(50, len(data["nodes"]))):
        assert ng.cls(i) == og.cls(i)


def test_find_issuer_and_claim_keywords_match():
    data = real_graph() or _tiny_indexing_graph()
    ng, og = new_step07.Graph(data), old_step07.Graph(data)
    assert new_step07.find_issuer(ng, "AAA") == old_step07.find_issuer(og, "AAA")
    assert new_step07.find_issuer(ng, "NOSUCHTICKER") == old_step07.find_issuer(og, "NOSUCHTICKER") is None
    assert dict(new_step07.claim_keywords(ng)) == dict(old_step07.claim_keywords(og))


# --------------------------------------------------------------------------- #
# 4. Stage runs — real corpus (the headline arm)
# --------------------------------------------------------------------------- #
def test_full_run_on_real_graph_matches():
    """The headline arm: the whole paid retrieval + adjudication + dossier path, both
    trees, real graph, stub LLM."""
    graph = real_graph()
    if graph is None:
        return _skip("test_full_run_on_real_graph_matches", "resolved_graph.json not present")
    budget = 60
    (nw, nstub, nlogs), (ow, ostub, ologs) = run_both(graph, max_llm_pairs=budget)
    try:
        assert nw.stats() == ow.stats(), f"stats diverged:\n  new={nw.stats()}\n  old={ow.stats()}"
        assert nw.dossiers() == ow.dossiers(), "dossiers diverged"
        n_edges, o_edges = nw.edges(), ow.edges()
        assert _edges_ignoring_recorded_at(n_edges) == _edges_ignoring_recorded_at(o_edges), \
            "linking edges diverged (ignoring recorded_at)"
        # Adjudication runs on a ThreadPoolExecutor, so the ORDER calls_seen is appended in
        # (inside worker threads) is not deterministic run-to-run even though exe.map()
        # itself yields results in submission order — compare as a multiset, not a sequence.
        assert sorted(u for _, u in nstub.calls_seen) == sorted(u for _, u in ostub.calls_seen), \
            "the two trees sent different prompts to the LLM"

        s = nw.stats()
        # NON-VACUITY: this arm must actually retrieve, adjudicate, and write edges/dossiers.
        assert s["claims"] > 100, f"suspiciously few claims: {s}"
        assert s["retrieval"]["candidate_pairs"] > 0, f"no candidate pairs retrieved: {s}"
        assert s["llm"]["pairs_adjudicated"] == budget, f"budget not honoured: {s}"
        assert s["linking_edges_written"] > 0, f"no edges written — arm is vacuous: {s}"
        assert sum(s["assessments"].values()) == s["claims"], "assessment histogram doesn't cover every claim"
        print(f"     ({s['claims']} claims, {s['retrieval']['candidate_pairs']} candidate pairs, "
              f"{s['linking_edges_written']} edge(s) from {budget} adjudications)")
    finally:
        nw.close(), ow.close()


def test_dry_run_still_adjudicates_but_writes_nothing():
    """Unlike step05d, step07's --dry-run does NOT return before the provider is built —
    it only skips the final writes. So this arm is a real equivalence check, not a vacuous
    one: both trees must retrieve + adjudicate identically and then write nothing."""
    graph = real_graph()
    if graph is None:
        return _skip("test_dry_run_still_adjudicates_but_writes_nothing", "resolved_graph.json not present")
    budget = 30
    (nw, nstub, nlogs), (ow, ostub, ologs) = run_both(graph, max_llm_pairs=budget, dry_run=True)
    try:
        assert nlogs == ologs, f"dry-run log diverged:\n  new={nlogs}\n  old={ologs}"
        assert any("Dry run" in m for m in nlogs), f"dry-run notice missing: {nlogs}"
        # see test_full_run_on_real_graph_matches: thread scheduling makes calls_seen ORDER
        # non-deterministic run-to-run, so compare as a multiset.
        assert sorted(u for _, u in nstub.calls_seen) == sorted(u for _, u in ostub.calls_seen)
        assert len(nstub.calls_seen) == budget, "dry-run should still spend the adjudication budget"
        assert nw.dossiers() is None and ow.dossiers() is None, "--dry-run wrote a dossier file"
        assert nw.edges() is None and ow.edges() is None, "--dry-run wrote an edges file"
    finally:
        nw.close(), ow.close()


def test_missing_issuer_is_reported_not_crashed():
    graph = real_graph() or _tiny_indexing_graph()
    (nw, _, nlogs), (ow, _, ologs) = run_both(graph, ticker="NOSUCHTICKER", max_llm_pairs=10)
    try:
        assert nlogs == ologs, f"log diverged:\n  new={nlogs}\n  old={ologs}"
        assert any("No issuer Organization" in m for m in nlogs), nlogs
        assert nw.dossiers() is None and ow.dossiers() is None
    finally:
        nw.close(), ow.close()


# --------------------------------------------------------------------------- #
# 5. Live branches the real data may not reach cleanly — synthetic fixtures
# --------------------------------------------------------------------------- #
def _guard_graph():
    """One claim, one company-owned-domain MediaReport that topically overlaps it — the
    self-verification guard (§6.4) must drop the 'independent' support, never fabricate a
    verifiedBy edge from the issuer's own outlet."""
    return {
        "nodes": [
            {"class": "Organization", "properties": {"ticker": "AAA", "name": "CTCP AAA"}},
            {"class": "SustainabilityClaim",
             "properties": {"description": "Chúng tôi cam kết giảm phát thải khí nhà kính"}},
            {"class": "MediaReport",
             "properties": {"text": "Công ty công bố giảm phát thải khí nhà kính",
                            "publisher": "aaa.com.vn", "source_type": "news",
                            "date": "2023-05-01"}},
        ],
        "edges": [{"subject": 0, "predicate": "claims", "object": 1}],
    }


def test_self_verification_guard_matches():
    graph = _guard_graph()
    (nw, _, _), (ow, _, _) = run_both(graph, stub_mode="always_supports", max_llm_pairs=10)
    try:
        assert nw.dossiers() == ow.dossiers(), "dossiers diverged"
        assert _edges_ignoring_recorded_at(nw.edges() or []) == \
               _edges_ignoring_recorded_at(ow.edges() or []), "edges diverged"

        d = nw.dossiers()[0]
        assert d["supporting_evidence"] == [], "guarded support must not count as independent"
        assert len(d["flagged_non_independent_support"]) == 1, d
        assert d["flagged_non_independent_support"][0]["guard"].startswith("dropped:")
        assert d["assessment"] == "unverified_insufficient_evidence", \
            "company-owned support must not flip the assessment"
        assert not nw.edges(), "a company-owned domain must never get a verifiedBy edge"
    finally:
        nw.close(), ow.close()


def _assessment_graph():
    """One claim with 2 independent conduct candidates: one Controversy (-> contradicts)
    and one KPIObservation (-> supports). contradicts must win (contradiction has priority
    over support in the assessment mapping)."""
    return {
        "nodes": [
            {"class": "Organization", "properties": {"ticker": "AAA", "name": "CTCP AAA"}},
            {"class": "SustainabilityClaim",
             "properties": {"description": "Chúng tôi cam kết giảm phát thải khí nhà kính"}},
            {"class": "Controversy",
             "properties": {"title": "Vi phạm xả thải khí nhà kính", "publisher": "baodautu.vn",
                            "source_type": "news", "date": "2023-06-01"}},
            {"class": "KPIObservation",
             "properties": {"title": "Phát thải khí nhà kính giảm", "kpi_type": "emission",
                            "source_type": "news", "publisher": "tuoitre.vn", "date": "2023-07-01"}},
        ],
        "edges": [{"subject": 0, "predicate": "claims", "object": 1}],
    }


def test_assessment_mapping_matches_when_evidence_is_mixed():
    graph = _assessment_graph()
    (nw, nstub, _), (ow, ostub, _) = run_both(graph, stub_mode="always_supports", max_llm_pairs=10)
    try:
        # both conduct candidates get "supports" from the always_supports stub, so this
        # arm alone can't reach "contradicted" — flip one pair's verdict deterministically
        # by re-running with a stub that always answers "contradicts" instead, and confirm
        # BOTH trees still agree with each other on the resulting assessment.
        assert nw.dossiers() == ow.dossiers()
        d = nw.dossiers()[0]
        assert d["assessment"] == "appears_supported"
        assert len(d["supporting_evidence"]) == 2
    finally:
        nw.close(), ow.close()

    (nw2, _, _), (ow2, _, _) = run_both(graph, stub_mode="always_contradicts", max_llm_pairs=10)
    try:
        assert nw2.dossiers() == ow2.dossiers()
        d2 = nw2.dossiers()[0]
        assert d2["assessment"] == "appears_contradicted", \
            "a contradiction must win over supporting evidence in the same dossier"
        assert len(d2["contradicting_evidence"]) == 2
        assert "mixed" not in " ".join(d2["caveats"]), d2["caveats"]
    finally:
        nw2.close(), ow2.close()


def _three_candidate_graph():
    """Like `_assessment_graph` but with a THIRD conduct candidate — the abort-branch test
    needs >=3 total pairs across the run since the 3-failures-0-successes counter is
    per-provider and cumulative, not per-claim."""
    g = _assessment_graph()
    g["nodes"].append({"class": "MediaReport",
                        "properties": {"text": "Phát thải khí nhà kính tăng cao",
                                       "source_type": "news", "publisher": "vnexpress.net",
                                       "date": "2023-08-01"}})
    return g


def test_provider_failures_abort_branch():
    """3 failures with 0 successes must abort the adjudication loop for that run.
    max_workers=1 so the shared failure counter isn't racing across threads."""
    graph = _three_candidate_graph()
    (nw, nstub, nlogs), (ow, ostub, ologs) = run_both(
        graph, stub_mode="always_raise", max_llm_pairs=10, max_workers=1)
    try:
        assert nw.stats() == ow.stats(), f"stats diverged:\n  new={nw.stats()}\n  old={ow.stats()}"
        s = nw.stats()
        providers = s["llm"]["providers"]
        assert providers and providers[0]["failures"] == 3 and providers[0]["calls_ok"] == 0, providers
        assert not s["llm"]["active"], "provider should be disabled after 3/0"
        assert s["linking_edges_written"] == 0
    finally:
        nw.close(), ow.close()


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
