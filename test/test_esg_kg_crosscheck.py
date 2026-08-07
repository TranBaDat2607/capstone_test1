#!/usr/bin/env python3
"""
Behavioural tests for `esg_kg.crosscheck.claims_vs_conduct` (migrated from
`src/step07_crosscheck_claims_vs_conduct.py`).

Repointed at esg_kg only (2026-07-29) now that src/ is scheduled for deletion — the
old-vs-new comparison logic has been removed. Where a test had no independent claim of
its own, its cross-tree comparison was rewritten into an assertion against a concrete,
hand-verified expected value (module constants, pure-helper outputs, `Graph`/
`claim_keywords` recomputed independently from the raw edge list) rather than deleted;
the coverage of esg_kg's own behaviour — pinned prompts/constants, the node_text trap,
the self-verification guard, the assessment-mapping priority, the `_parse_verdict`
non-object-JSON fix — is unchanged.

WHY THIS SLICE NEEDED NO NEW core/ MODULE
Every symbol step07 imports from a sibling stage was already lifted before this slice:
`REPO_ROOT` (-> core.paths, since step01's move), `load_schema_sets` (-> core.schema,
since step03), `normalize_name`/`name_tokens` (-> core.naming, since step04 was found to
be a dissolved hub), and `_Provider`/`_GeminiProvider` (-> core.llm; `_GeminiProvider`
replaced `_OpenAIProvider` outright on 2026-08-04, no fallback kept, once the project
went back to paying only for Gemini — see core/llm.py's docstring for the timeline).
`RateLimiter` was imported from step02 in the old file but never referenced directly
(only the provider's own `__init__` uses it) — same dead-import shape the 05d slice
found, so it is dropped here too.

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
over `_GeminiProvider`, answering deterministically from a CRC of the adjudication prompt,
so the paid branch is exercised for free. `--dry-run` does NOT return before the provider
is built (it only skips the final file-writes) — so the dry-run arm also drives the full
stub adjudication path, not just a "nothing happens" check.

ONE NON-DETERMINISM TO MASK: `_mk_edge` stamps `recorded_at` with `datetime.now(...)`, so
two runs of the same logic can disagree on that one field even though everything else
matches. `_edges_ignoring_recorded_at` strips it before comparison — exactly as the
align_claims arm masks the temp workspace path out of log lines.

THE IN-PLACE-PATCH QUESTION (PIPELINE.md §3) DOES NOT APPLY HERE
step07 reads `resolved_graph.json` (step05's/05b's/05c's/05d's output) and writes to a
DIFFERENT directory (`graph_output/crosscheck/`) — it never meets its own past output, so
the real-corpus arm is non-vacuous by construction. No `strip_*` fixture is needed, the
same shape step03's migration already established.

A DEFECT FOUND AND FIXED (same file, follow-up commit to the migration)
`_parse_verdict` had the same latent defect step05d's `parse_reply` had before a308608:
`json.loads("[]")` succeeds (a list, not a dict), and the very next line called `.get()` on
it. Here the blast radius was smaller (the call site sits inside `Adjudicator.adjudicate`'s
own try/except, so it degraded to "no verdict for this pair" instead of losing an entire
run) but it was still a real defect: a merely-oddly-shaped reply got misfiled as a provider
*failure* rather than as an unusable-reply no-op. `test_parse_verdict_matches` pins the
shapes the code already handled safely; `test_parse_verdict_rejects_non_object_json_in_BOTH_trees`
is the red-first test for the fix itself (name kept from when it drove both trees — it now
pins the fixed behaviour directly against `esg_kg`).

Offline: no LLM, no Neo4j, no network — the stub replaces `_GeminiProvider` before it can
look for `GEMINI_API_KEY` (the stub wins regardless because the code re-reads the
module-global name at call time). `config/schema.json`
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
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# --- the esg_kg package -----------------------------------------------------------
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
    """Return a class with `_GeminiProvider(model, rate_limit)`'s interface.

    `mode="mixed"` walks 5 reply shapes the parser must survive today (clean supports/
    contradicts/irrelevant, JSON wrapped in prose, and unparseable prose -> None).
    `mode="always_raise"` drives the 3-failures-0-successes disable branch.
    `mode="always_supports"` / `"always_contradicts"` pin one verdict for every pair —
    used by the targeted assessment-mapping and self-verification-guard arms.
    """
    calls_seen: list = []

    class _Stub:
        name = "gemini"

        def __init__(self, model, rate_limit, api_key=None):
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
            ticker="AAA", top_k=8, window_before=1, window_after=50, min_topic_overlap=2,
            max_llm_pairs=40, model="gemini-2.5-flash",
            provider_order=["gemini"], max_workers=4, rate_limit=60,
            embed=False, dry_run=False, to_neo4j=False, database=None,
            cache=None,  # issue #9: no cache unless a test overrides it
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


def run_new(graph: dict, stub_mode: str = "mixed", **overrides):
    """Run the stage against a stubbed `_GeminiProvider`; return (Workspace, stub_class,
    masked_log_lines)."""
    mod = new_step07
    ws = Workspace(copy.deepcopy(graph))
    stub = make_stub(stub_mode)
    original = mod._GeminiProvider
    handler = _LogCatcher()
    mod.logger.addHandler(handler)
    try:
        mod._GeminiProvider = stub
        mod.run(ws.args(**overrides))
    finally:
        mod._GeminiProvider = original
        mod.logger.removeHandler(handler)
    return ws, stub, [m.replace(str(ws.dir), "<WS>") for m in handler.messages]


def real_graph():
    """The live resolved graph, or None on a bare clone (git-ignored, HF-shipped)."""
    if not RESOLVED_FILE.exists():
        return None
    return json.loads(RESOLVED_FILE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 1. Module surface: constants, and that the new tree IMPORTS the kernel
# --------------------------------------------------------------------------- #
EXPECTED_ADJUDICATE_SYSTEM = (
    "You assess greenwashing evidence for a Vietnamese ESG knowledge graph. You are given "
    "ONE ESG claim a company made in its own report, and ONE piece of independent evidence "
    "about the company (usually a news item). Decide, using ONLY the two texts, whether the "
    "evidence SUPPORTS the claim, CONTRADICTS it, or is IRRELEVANT.\n"
    "Rules:\n"
    "- Treat the evidence as independent conduct ('what the company did'), not as a restatement "
    "of the claim.\n"
    "- 'contradicts' means the evidence is in tension with the SAME SPECIFIC topic, process, or "
    "activity the claim describes (e.g. a claim about emissions vs an emissions violation; a claim "
    "about a specific governance procedure vs evidence that THAT SAME procedure failed or was "
    "skipped). A general negative fact about the company (an unrelated penalty, violation, or "
    "controversy on a different topic) does NOT by itself contradict a claim about a different, "
    "specific topic — do not infer 'the company is untrustworthy in general, therefore this claim "
    "is false' from one adverse event unless the evidence is actually about the same matter as "
    "the claim.\n"
    "- 'supports' means the evidence independently corroborates that SAME specific claim (e.g. a "
    "third-party verification, certification, or an observed metric consistent with the claim).\n"
    "- Prefer 'irrelevant' when the evidence is about a different topic than the claim — even if "
    "both are negative, both are positive, or both broadly concern ESG/governance — or when the "
    "evidence is neutral financial/market coverage. Do not guess.\n"
    "- The texts are Vietnamese. confidence is 0.0-1.0. Ground the rationale in the evidence text.\n"
    "## OUTPUT LANGUAGE\n"
    "Write `rationale` in VIETNAMESE, with full diacritics, matching the language of the claim/evidence "
    "texts. Do NOT translate into English. Do NOT strip diacritics (khong duoc bo dau). This rule does "
    "NOT apply to `verdict` (a fixed English label: supports/contradicts/irrelevant) or `confidence` "
    "(a number)."
)


def test_constants_match():
    """Pinned against concrete expected values (not a cross-tree comparison)."""
    assert new_step07.DEFAULT_INPUT == REPO / "graph_output" / "resolved" / "resolved_graph.json"
    assert new_step07.DEFAULT_SCHEMA == SCHEMA_FILE
    assert new_step07.DEFAULT_OUT_DIR == REPO / "graph_output" / "crosscheck"
    # DEFAULT_MODEL is re-exported from core.llm (env-driven, GEMINI_MODEL); pin its
    # value there instead of duplicating the fallback string here.
    assert new_step07.DEFAULT_MODEL == core_llm.DEFAULT_MODEL
    assert new_step07.DEFAULT_PROVIDER_ORDER == "gemini"
    assert new_step07.DEFAULT_RATE_LIMIT == 10
    assert new_step07.DEFAULT_MAX_LLM_PAIRS == 300
    assert new_step07.DEFAULT_TOP_K == 8
    assert new_step07.DEFAULT_WINDOW_BEFORE == 1
    assert new_step07.DEFAULT_WINDOW_AFTER == 50
    assert new_step07.DEFAULT_MIN_TOPIC_OVERLAP == 2

    assert new_step07.CONDUCT_CLASSES == {
        "Controversy", "Penalty", "MediaReport", "KPIObservation", "ThirdPartyVerification"}
    assert new_step07.SUPPORT_EDGE == "verifiedBy"
    assert new_step07.CONTRADICT_EDGE == {
        "Controversy": "contradictedBy", "MediaReport": "contradictedByMedia"}
    assert new_step07.COMPANY_DOMAINS == {
        "anphatholdings.vn", "aneco.com.vn", "anphatbioplastics.com", "anphat.vn",
        "aaa.com.vn", "aaa.com", "aaplastic.vn",
    }
    assert new_step07.ISSUER_DOMAIN_TOKENS == {"anphat", "aneco", "aaplastic"}
    assert new_step07.STOPWORDS == {
        "cong", "ty", "co", "phan", "tnhh", "tap", "doan", "aaa", "an", "phat", "xanh",
        "nhua", "green", "plastic", "plastics", "environment", "moi", "truong", "va",
        "cua", "cac", "trong", "nam", "the", "and", "for", "with", "cong ty",
        "bao", "cao", "report", "nien", "thuong", "ve", "la", "den", "cho", "khi",
    }

    # ADJUDICATE_SYSTEM is PAID BEHAVIOUR, not prose: reword it and the stage still "works"
    # while every verdict changes. Byte-for-byte pin against a hardcoded literal, like SYSTEM
    # in the align_claims slice.
    assert new_step07.ADJUDICATE_SYSTEM == EXPECTED_ADJUDICATE_SYSTEM, \
        "the paid ADJUDICATE_SYSTEM prompt was reworded"


def test_new_tree_imports_the_kernel_rather_than_recopying():
    """A migrated stage must USE core/, not carry its own copy — otherwise the two drift."""
    assert new_step07._GeminiProvider is core_llm._GeminiProvider, "_GeminiProvider was re-copied"
    assert new_step07._Provider is core_llm._Provider, "_Provider was re-copied"
    assert new_step07.load_schema_sets is core_schema.load_schema_sets, "load_schema_sets re-copied"
    assert new_step07.normalize_name is core_naming.normalize_name, "normalize_name re-copied"
    assert new_step07.name_tokens is core_naming.name_tokens, "name_tokens re-copied"
    assert new_step07.REPO_ROOT == core_paths.REPO_ROOT


def test_new_tree_has_no_dead_ratelimiter_import():
    """The old file imports RateLimiter from step02 but never references it directly (only
    the provider's own __init__ does, and that class now comes pre-built from core.llm) —
    the same dead-import shape the 05d slice found. The new module should not re-introduce it."""
    assert not hasattr(new_step07, "RateLimiter"), \
        "RateLimiter should not be imported directly into the migrated stage"


# --------------------------------------------------------------------------- #
# 2. Pure helpers
# --------------------------------------------------------------------------- #
def test_props_matches():
    cases = [
        ({"properties": {"a": 1}}, {"a": 1}),
        ({"properties": None}, {}),
        ({}, {}),
    ]
    for n, expected in cases:
        assert new_step07.props(n) == expected


def test_node_text_matches():
    cases = [
        ({"class": "KPIObservation", "properties": {"title": "t", "kpi_type": "energy",
                                                      "value": 10, "unit": "kWh", "kind": "actual"}},
         "t energy 10 kWh actual"),
        ({"class": "KPIObservation", "properties": {}}, ""),
        ({"class": "ThirdPartyVerification", "properties": {"verifier": "SGS", "result": "pass"}},
         "SGS pass"),
        ({"class": "SustainabilityClaim", "properties": {"description": "giảm phát thải"}},
         "giảm phát thải"),
        ({"class": "Controversy", "properties": {"title": "Vụ việc"}}, "Vụ việc"),
        ({"class": "MediaReport", "properties": {"text": "bài báo"}}, "bài báo"),
        ({"class": "Goal", "properties": {"name": "n", "term": "long"}}, "n"),
        ({"class": "Organization", "properties": {}}, ""),
    ]
    for n, expected in cases:
        assert new_step07.node_text(n) == expected, f"node_text wrong for {n}"


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
        ({"properties": {"publish_year": 2023}}, 2023),
        ({"properties": {"target_year": "2030"}}, 2030),
        ({"properties": {"year": "abcd"}}, None),
        ({"properties": {"date": "2021-05-01"}}, 2021),
        ({"properties": {"valid_from": "not a date"}}, None),
        ({"properties": {"claim_id": "social_activities_2011"}}, 2011),
        ({"properties": {}}, None),
    ]
    for n, expected in cases:
        assert new_step07.node_year(n) == expected, f"node_year wrong for {n}"


def test_node_domain_matches():
    cases = [
        ({"properties": {"source_domain": "VnExpress.vn"}}, "vnexpress.vn"),
        ({"properties": {"publisher": "tuoitre.vn"}}, "tuoitre.vn"),
        ({"properties": {"source": "no-dot-here"}}, ""),
        ({"properties": {}}, ""),
    ]
    for n, expected in cases:
        assert new_step07.node_domain(n) == expected, f"node_domain wrong for {n}"


def test_date_uncertain_matches():
    cases = [
        ({"properties": {"date_uncertain": True}}, True),
        ({"properties": {"date_uncertain": "false"}}, False),
        ({"properties": {"date": "2021-01-01"}}, True),   # bare YYYY-01-01 = a proxy date
        ({"properties": {"date": "2021-03-05"}}, False),
        ({"properties": {}}, False),
    ]
    for n, expected in cases:
        assert new_step07.date_uncertain(n) == expected, f"date_uncertain wrong for {n}"


def test_topic_tokens_matches():
    """topic_tokens = VN-aware segments (underthesea.word_tokenize via _vn_segments), each
    normalize_name()'d and kept WHOLE (not exploded into unigrams) UNLESS every word in
    the segment is itself a STOPWORD, union filtered `extra`. Uses the module's own
    (already-migrated) _vn_segments/normalize_name/STOPWORDS as the oracle for
    tokenization itself — what this test verifies is that topic_tokens WIRES them
    correctly (the drop-if-all-stopwords rule, length filter, extra-set union), not that
    VN segmentation itself is linguistically correct (2026-08-07: replaced plain unigram
    name_tokens() — see test_topic_tokens_avoids_vn_homograph_collision for why)."""
    def expected(text, extra):
        toks = set()
        for seg in new_step07._vn_segments(text):
            norm = new_step07.normalize_name(seg)
            words = norm.split()
            if not words or all(w in new_step07.STOPWORDS for w in words):
                continue
            if len(norm) >= 3:
                toks.add(norm)
        if extra:
            toks |= {t for t in extra if len(t) >= 3 and t not in new_step07.STOPWORDS}
        return toks

    cases = [("Công ty Nhựa An Phát giảm phát thải khí nhà kính", None),
             ("", {"extra", "tokens"}),
             ("Green Plastics environment report 2023", {"aaa"})]
    for text, extra in cases:
        assert new_step07.topic_tokens(text, extra) == expected(text, extra)
    # non-vacuity: the Vietnamese case must actually surface real topic words, not stopwords
    assert new_step07.topic_tokens(cases[0][0], None), \
        "fixture stopped producing any topic token"
    # "Công ty" (both words boilerplate) must still be dropped, same as the old unigram rule
    assert "cong ty" not in new_step07.topic_tokens(cases[0][0], None)


def test_topic_tokens_avoids_vn_homograph_collision():
    """The concrete bug this stage hit in production (2026-08-07): 'phiếu bầu' (ballot)
    and 'cổ phiếu' (stock) share only the bare syllable 'phiếu' once naive unigram split
    strips 'cổ' as a stopword — an unrelated AGG stock-manipulation Penalty then became
    'contradicting evidence' for an ACG ballot-appointment claim (77/91 of ACG's
    contradicting-evidence citations traced back to this). underthesea keeps 'cổ phiếu'
    together as ONE segment, distinct from the bare 'phiếu' the ballot claim contributes,
    so the two texts below must share NO topic token — closing the collision at the
    tokenizer level (independent of, and in addition to, the source_doc issuer-scope fix
    and the min-topic-overlap gate)."""
    ballot = new_step07.topic_tokens(
        "Công ty đã bổ nhiệm một bên độc lập kiểm đếm phiếu bầu tại ĐHĐCĐ")
    stock = new_step07.topic_tokens("Phạt tiền vì thao túng cổ phiếu AGG")
    assert not (ballot & stock), f"unexpected shared token(s): {ballot & stock}"
    # sanity: a genuinely similar sentence about the SAME topic still overlaps plenty
    same_topic = new_step07.topic_tokens(
        "AAA công bố đã bổ nhiệm bên độc lập kiểm phiếu bầu ĐHĐCĐ")
    assert len(ballot & same_topic) >= new_step07.DEFAULT_MIN_TOPIC_OVERLAP


def _weak_overlap_graph():
    """One claim and one same-issuer MediaReport sharing EXACTLY ONE topic token
    ('nha may' / factory) — a real but weak signal on its own (many unrelated claims and
    conduct items can both mention "nhà máy"). Used to prove the min-topic-overlap gate
    (default 2) filters single-token matches at retrieval, before the LLM ever sees them."""
    return {
        "nodes": [
            {"class": "Organization", "properties": {"ticker": "AAA", "name": "CTCP AAA"}},
            {"class": "SustainabilityClaim",
             "properties": {"description": "Chúng tôi đã lắp đặt hệ thống xử lý nước thải "
                                            "hiện đại tại nhà máy"}},
            {"class": "MediaReport",
             "properties": {"text": "Nhà máy bị đình chỉ hoạt động do vi phạm an toàn lao động",
                            "source_domain": "vnexpress.net", "source_type": "news",
                            "date": "2023-01-01"}},
        ],
        "edges": [{"subject": 0, "predicate": "claims", "object": 1}],
    }


def test_min_topic_overlap_gate_filters_single_token_matches():
    """Default min_topic_overlap=2: a same-issuer conduct node sharing only 1 topic token
    with the claim must never reach the LLM. Overriding the gate down to 1 must let it
    through — proving the filter is the reason, not something else (e.g. the temporal
    window) accidentally excluding the pair."""
    graph = _weak_overlap_graph()

    nw, _, log = run_new(graph, stub_mode="always_contradicts", max_llm_pairs=10)
    try:
        d = nw.dossiers()[0]
        assert d["contradicting_evidence"] == [], \
            f"a 1-token match must be filtered by the default gate: {d}"
        assert d["assessment"] == "unverified_insufficient_evidence"
    finally:
        nw.close()

    nw2, _, _ = run_new(graph, stub_mode="always_contradicts", max_llm_pairs=10,
                         min_topic_overlap=1)
    try:
        d2 = nw2.dossiers()[0]
        assert len(d2["contradicting_evidence"]) == 1, \
            f"lowering the gate to 1 must let the same pair through: {d2}"
    finally:
        nw2.close()


def test_is_company_domain_matches():
    cases = [
        ("aaa.com.vn", True),           # in COMPANY_DOMAINS
        ("AnPhatHoldings.vn", True),     # lowercases to a COMPANY_DOMAINS member
        ("vnexpress.net", False),        # neither a member nor an issuer token substring
        ("", False),
        ("anphat-fake.co", True),        # "anphat" ISSUER_DOMAIN_TOKENS substring match
    ]
    for d, expected in cases:
        assert new_step07.is_company_domain(d) == expected, f"diverged: {d}"


def test_mk_edge_matches():
    a = new_step07._mk_edge(0, "verifiedBy", 1, "supports", 0.9, "why", "news", "gemini", True)
    recorded_at = a["properties"].pop("recorded_at")
    assert a == {
        "subject": 0, "predicate": "verifiedBy", "object": 1,
        "properties": {
            "llm_verdict": "supports", "confidence": 0.9, "rationale": "why",
            "evidence_source_type": "news", "llm_provider": "gemini",
            "llm_suggested": True, "independent": True,
        },
    }
    assert recorded_at, "recorded_at must be stamped"


def test_parse_verdict_matches():
    """Shapes the CURRENT code already handles safely, against concrete expected values
    read off `_parse_verdict`'s own source. The non-dict-JSON crash shape ('[]', '"txt"')
    is deliberately NOT exercised here — see the module docstring."""
    cases = [
        ('{"verdict": "supports", "confidence": 0.9, "rationale": "r"}',
         {"verdict": "supports", "confidence": 0.9, "rationale": "r"}),
        ('{"verdict": "contradicts"}',
         {"verdict": "contradicts", "confidence": 0.0, "rationale": ""}),
        ('{"verdict": "irrelevant", "confidence": "0.4"}',
         {"verdict": "irrelevant", "confidence": 0.4, "rationale": ""}),
        ('blah {"verdict": "supports"} trailing',  # regex fallback recovers the embedded object
         {"verdict": "supports", "confidence": 0.0, "rationale": ""}),
        ('no json here', None),
        ('{"verdict": "unknown_value"}', None),  # not one of supports/contradicts/irrelevant
        ('{broken json', None),                  # no closing brace for the regex fallback either
        ('', None),
        (None, None),
    ]
    for raw, expected in cases:
        got = new_step07._parse_verdict(raw)
        assert got == expected, f"_parse_verdict({raw!r}) = {got}, expected {expected}"


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
        assert new_step07._parse_verdict(raw) is None, f"mishandled {raw!r}"

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
    """`Graph.out`/`.inc` are just an index over `data["edges"]` — reconstruct the expected
    index directly from the input rather than needing a second implementation as an oracle."""
    data = real_graph() or _tiny_indexing_graph()
    g = new_step07.Graph(data)

    expected_out, expected_inc = defaultdict(list), defaultdict(list)
    for e in data["edges"]:
        s, o, pr = e.get("subject"), e.get("object"), e.get("predicate")
        if isinstance(s, int) and isinstance(o, int) and pr:
            expected_out[s].append((pr, o))
            expected_inc[o].append((pr, s))

    assert dict(g.out) == dict(expected_out)
    assert dict(g.inc) == dict(expected_inc)
    for i in range(min(50, len(data["nodes"]))):
        assert g.cls(i) == data["nodes"][i].get("class", "")


def test_find_issuer_and_claim_keywords_match():
    data = real_graph() or _tiny_indexing_graph()
    g = new_step07.Graph(data)
    issuer = new_step07.find_issuer(g, "AAA")
    assert issuer is None or (0 <= issuer < len(g.nodes) and g.cls(issuer) == "Organization")
    assert new_step07.find_issuer(g, "NOSUCHTICKER") is None

    kw = new_step07.claim_keywords(g)
    # kw is exactly the ClaimKeyword terms reachable via hasKeyword, recomputed independently
    expected_kw = defaultdict(set)
    for e in data["edges"]:
        if e.get("predicate") == "hasKeyword":
            s, o = e.get("subject"), e.get("object")
            if isinstance(s, int) and isinstance(o, int) and g.cls(o) == "ClaimKeyword":
                term = (data["nodes"][o].get("properties") or {}).get("term")
                if term:
                    expected_kw[s] |= new_step07.name_tokens(term)
    assert dict(kw) == dict(expected_kw)


# --------------------------------------------------------------------------- #
# 4. Stage runs — real corpus (the headline arm)
# --------------------------------------------------------------------------- #
def test_full_run_on_real_graph_matches():
    """The headline arm: the whole paid retrieval + adjudication + dossier path on the
    real graph, stub LLM."""
    graph = real_graph()
    if graph is None:
        return _skip("test_full_run_on_real_graph_matches", "resolved_graph.json not present")
    budget = 60
    nw, nstub, nlogs = run_new(graph, max_llm_pairs=budget)
    try:
        s = nw.stats()
        # NON-VACUITY: this arm must actually retrieve, adjudicate, and write edges/dossiers.
        assert s["claims"] > 100, f"suspiciously few claims: {s}"
        assert s["retrieval"]["candidate_pairs"] > 0, f"no candidate pairs retrieved: {s}"
        assert s["llm"]["pairs_adjudicated"] == budget, f"budget not honoured: {s}"
        assert s["linking_edges_written"] > 0, f"no edges written — arm is vacuous: {s}"
        assert sum(s["assessments"].values()) == s["claims"], "assessment histogram doesn't cover every claim"
        assert nw.dossiers() is not None, "dossiers file not written"
        print(f"     ({s['claims']} claims, {s['retrieval']['candidate_pairs']} candidate pairs, "
              f"{s['linking_edges_written']} edge(s) from {budget} adjudications)")
    finally:
        nw.close()


def test_dry_run_still_adjudicates_but_writes_nothing():
    """Unlike step05d, step07's --dry-run does NOT return before the provider is built —
    it only skips the final writes, so this arm is a real check of that behaviour.

    budget is kept well below AAA's real retrieval count on purpose: it was 30 when
    retrieval was pure token-overlap (287 real candidate pairs), but the 2026-08-07
    issuer-scope + VN-aware-tokenizer + min-topic-overlap fix cut AAA's real pairs to 23 —
    a legitimate precision improvement, not a regression. Pinning budget below whatever
    that number happens to be today would make this test fragile to future retrieval
    tuning; 10 has headroom either way."""
    graph = real_graph()
    if graph is None:
        return _skip("test_dry_run_still_adjudicates_but_writes_nothing", "resolved_graph.json not present")
    budget = 10
    nw, nstub, nlogs = run_new(graph, max_llm_pairs=budget, dry_run=True)
    try:
        assert any("Dry run" in m for m in nlogs), f"dry-run notice missing: {nlogs}"
        assert len(nstub.calls_seen) == budget, "dry-run should still spend the adjudication budget"
        assert nw.dossiers() is None, "--dry-run wrote a dossier file"
        assert nw.edges() is None, "--dry-run wrote an edges file"
    finally:
        nw.close()


def test_missing_issuer_is_reported_not_crashed():
    graph = real_graph() or _tiny_indexing_graph()
    nw, _, nlogs = run_new(graph, ticker="NOSUCHTICKER", max_llm_pairs=10)
    try:
        assert any("No issuer Organization" in m for m in nlogs), nlogs
        assert nw.dossiers() is None
    finally:
        nw.close()


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
    nw, _, _ = run_new(graph, stub_mode="always_supports", max_llm_pairs=10)
    try:
        d = nw.dossiers()[0]
        assert d["supporting_evidence"] == [], "guarded support must not count as independent"
        assert len(d["flagged_non_independent_support"]) == 1, d
        assert d["flagged_non_independent_support"][0]["guard"].startswith("dropped:")
        assert d["assessment"] == "unverified_insufficient_evidence", \
            "company-owned support must not flip the assessment"
        assert not nw.edges(), "a company-owned domain must never get a verifiedBy edge"
    finally:
        nw.close()


def _cross_company_graph():
    """Two issuers (AAA, AGG) in the same graph. AAA's claim and AGG's crawled Penalty
    share exactly one topic token ('phieu' — from AAA's 'phiếu bầu' / ballot vs AGG's
    'cổ phiếu' / stock, a homograph collision once 'cổ' is stripped as a stopword), so
    pre-fix retrieval (topic overlap only, no issuer scope) would pull AGG's conduct into
    AAA's candidate pool. AAA's own MediaReport shares much stronger overlap and must
    still be retrieved — the fix scopes by source_doc's <TICKER>__ prefix, not by
    dropping topic-overlap retrieval altogether. Reproduces the real ACG/AGG contamination
    found in the live graph (77/91 of ACG's 'contradicting evidence' citations were
    actually about AGG)."""
    return {
        "nodes": [
            {"class": "Organization", "properties": {"ticker": "AAA", "name": "CTCP AAA"}},
            {"class": "Organization", "properties": {"ticker": "AGG", "name": "CTCP AGG"}},
            {"class": "SustainabilityClaim",
             "properties": {"description": "Công ty đã bổ nhiệm một bên độc lập kiểm đếm "
                                            "phiếu bầu tại ĐHĐCĐ"}},
            {"class": "Penalty",
             "properties": {"description": "Phạt tiền vì thao túng cổ phiếu AGG",
                            "source_domain": "vnexpress.net", "source_type": "news",
                            "source_doc": "AGG__vnexpress.net__deadbeef01", "date": "2024-03-01"}},
            {"class": "MediaReport",
             "properties": {"text": "AAA công bố đã bổ nhiệm bên độc lập kiểm phiếu bầu ĐHĐCĐ",
                            "source_domain": "baodautu.vn", "source_type": "news",
                            "source_doc": "AAA__baodautu.vn__cafef0001", "date": "2024-04-01"}},
        ],
        "edges": [{"subject": 0, "predicate": "claims", "object": 2}],
    }


def test_conduct_pool_scoped_to_same_issuer_by_source_doc():
    """A different issuer's crawled conduct (source_doc='AGG__...') must never enter AAA's
    candidate pool even when it shares a topic token with AAA's claim — closes the
    cross-company contamination retrieval used to allow (the module docstring's §6a has
    always promised 'same issuer + VN topic overlap', the code never enforced the first
    half). AAA's own conduct, which overlaps far more strongly, must still come through."""
    graph = _cross_company_graph()
    nw, _, _ = run_new(graph, stub_mode="always_contradicts", max_llm_pairs=10)
    try:
        d = nw.dossiers()[0]
        cited_domains = [e.get("source_domain") for e in d["contradicting_evidence"]]
        assert "vnexpress.net" not in cited_domains, (
            f"AGG's conduct node must never reach AAA's dossier: {cited_domains}")
        assert "baodautu.vn" in cited_domains, (
            f"AAA's own conduct must still be retrieved: {cited_domains}")
    finally:
        nw.close()


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
    nw, _, _ = run_new(graph, stub_mode="always_supports", max_llm_pairs=10)
    try:
        d = nw.dossiers()[0]
        assert d["assessment"] == "appears_supported"
        assert len(d["supporting_evidence"]) == 2
    finally:
        nw.close()

    # flip the verdict deterministically to confirm contradiction wins over support
    nw2, _, _ = run_new(graph, stub_mode="always_contradicts", max_llm_pairs=10)
    try:
        d2 = nw2.dossiers()[0]
        assert d2["assessment"] == "appears_contradicted", \
            "a contradiction must win over supporting evidence in the same dossier"
        assert len(d2["contradicting_evidence"]) == 2
        assert "mixed" not in " ".join(d2["caveats"]), d2["caveats"]
    finally:
        nw2.close()


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
    nw, nstub, nlogs = run_new(
        graph, stub_mode="always_raise", max_llm_pairs=10, max_workers=1)
    try:
        s = nw.stats()
        providers = s["llm"]["providers"]
        assert providers and providers[0]["failures"] == 3 and providers[0]["calls_ok"] == 0, providers
        assert not s["llm"]["active"], "provider should be disabled after 3/0"
        assert s["linking_edges_written"] == 0
    finally:
        nw.close()


def _duplicate_claim_graph():
    """Two SustainabilityClaims with the IDENTICAL text, one MediaReport topically
    overlapping both — the two (claim, evidence) adjudication calls this produces have
    byte-identical (claim_text, evidence_text, evidence_meta), the exact shape issue #9's
    cache must dedupe within a single run (e.g. a repeated disclaimer across two report
    years, or a boilerplate sentence shared by two claims)."""
    claim_text = "Chung toi cam ket giam phat thai khi nha kinh"
    return {
        "nodes": [
            {"class": "Organization", "properties": {"ticker": "AAA", "name": "CTCP AAA"}},
            {"class": "SustainabilityClaim", "properties": {"description": claim_text}},
            {"class": "SustainabilityClaim", "properties": {"description": claim_text}},
            {"class": "MediaReport",
             "properties": {"text": "Cong ty cong bo giam phat thai khi nha kinh",
                            "publisher": "vnexpress.net", "source_type": "news",
                            "date": "2023-05-01"}},
        ],
        "edges": [
            {"subject": 0, "predicate": "claims", "object": 1},
            {"subject": 0, "predicate": "claims", "object": 2},
        ],
    }


def test_identical_claim_evidence_pairs_hit_the_cache_once():
    """Issue #9's headline acceptance criterion: two adjudication calls with identical
    (claim_text, evidence_text, evidence_meta) in the SAME run must reach the provider
    (the stub, standing in for the real LLM) exactly once — the second is a cache hit."""
    graph = _duplicate_claim_graph()
    with tempfile.TemporaryDirectory(prefix="esgkg_step07_cache_") as td:
        cache_path = Path(td) / "adjudication_cache.json"
        nw, stub, _ = run_new(graph, stub_mode="always_supports", max_llm_pairs=10,
                               max_workers=1, cache=cache_path)
        try:
            assert len(stub.calls_seen) == 1, (
                f"expected exactly 1 real call for 2 identical (claim, evidence) pairs, "
                f"got {len(stub.calls_seen)}: {stub.calls_seen}")
            d = nw.dossiers()
            assert len(d) == 2
            assert d[0]["assessment"] == "appears_supported"
            assert d[1]["assessment"] == "appears_supported", \
                "the cache-hit dossier must reproduce the same verdict as the cache-miss one"
            assert cache_path.exists(), "a non-dry-run must persist the cache to disk"
        finally:
            nw.close()


def test_adjudication_cache_survives_across_runs():
    """Cross-run reuse (same shape as RepairCache/AdjudicationCache's block tests): a
    second run against the SAME cache path must reproduce the verdict WITHOUT calling
    the provider at all, even when that provider would otherwise fail every call."""
    graph = _duplicate_claim_graph()
    with tempfile.TemporaryDirectory(prefix="esgkg_step07_cache_") as td:
        cache_path = Path(td) / "adjudication_cache.json"

        nw1, _, _ = run_new(graph, stub_mode="always_supports", max_llm_pairs=10,
                             max_workers=1, cache=cache_path)
        nw1.close()
        assert cache_path.exists()

        nw2, stub2, _ = run_new(graph, stub_mode="always_raise", max_llm_pairs=10,
                                 max_workers=1, cache=cache_path)
        try:
            assert stub2.calls_seen == [], \
                f"a re-run against a populated cache must not call the provider: {stub2.calls_seen}"
            d2 = nw2.dossiers()
            assert d2[0]["assessment"] == "appears_supported", \
                "a re-run must reproduce the cached verdict from a now-failing provider"
        finally:
            nw2.close()


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
