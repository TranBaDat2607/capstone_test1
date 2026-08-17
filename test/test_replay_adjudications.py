#!/usr/bin/env python3
"""Behavioural tests for `esg_kg.export.replay_adjudications` — the offline extractor
that turns the already-paid-for adjudication caches into a `(claim, evidence, verdict)`
JSONL training set.

WHAT THIS TOOL MUST NEVER DO, AND WHY THE FIRST TEST IS ABOUT THAT
The whole point of the replay is that it is FREE. `claims_vs_conduct` recovers the same
information only by constructing a real `Adjudicator`, which calls a real provider on
every cache MISS — so an "instrumented step07 run" pays full price the moment retrieval
or the prompt shifts. This tool must be incapable of that by construction: it never
imports, constructs, or holds a provider. `test_never_constructs_a_provider` pins it.

THE KEY-FIDELITY CONTRACT (the reason this is not a 20-line script)
A recovered row is only correct if the tool recomputes the EXACT string
`Adjudicator.adjudicate` hashed. Three things have to line up:

  1. the texts        — `node_text(claim_node)` / `node_text(conduct_node)`
  2. the meta string  — f"{class} from {domain or 'news'}, year {year}"
  3. the key parts    — `cache.get(salt, claim_text, evidence_text, evidence_meta)`

`test_recovers_a_verdict_written_by_the_real_adjudicator` is the guard: it drives the
REAL `Adjudicator` (stubbed under `_GeminiProvider`, the repo's standard technique) to
populate a real `ContentCache` on disk, then asserts the replay recovers that entry. If
anyone changes how step07 builds its key, that test fails here rather than silently
producing an empty training set.

TWO PROMPT GENERATIONS LIVE IN THE SAME CACHE FILES
The P1 fix (2026-08-13, `067b93f`) salted the cache key with
`sha256(ADJUDICATE_SYSTEM)[:12] + "|" + "<provider>:<model>"`. Entries written BEFORE it
are unsalted 3-part keys produced by the OLD, pre-halo-guard prompt; entries written
after are salted 4-part keys. Both shapes sit in `adjudication_cache.json` today, for
overlapping pairs, and they disagree often enough that mixing them would poison a
training set with contradictory labels for identical text. The tool must therefore
recover both and LABEL which generation each row came from — never silently merge them.

Offline: no LLM, no Neo4j, no network. Synthetic arms always run; the real-artifact arm
SKIPs when the git-ignored, HF-shipped graph/caches are absent on a bare clone.

Run from the repo root:

    python test/test_replay_adjudications.py
"""

import argparse
import ast
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core.llm_cache import ContentCache  # noqa: E402
from esg_kg.crosscheck import claims_vs_conduct as step07  # noqa: E402
from esg_kg.export import replay_adjudications as replay  # noqa: E402

PRE_P5_BACKUP = REPO / "graph_output" / "resolved" / "_pre_p5_backup" / "resolved_graph.json.bak"
CURRENT_GRAPH = REPO / "graph_output" / "resolved" / "resolved_graph.json"
CROSSCHECK_DIR = REPO / "graph_output" / "crosscheck"

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def synthetic_graph() -> dict:
    """One claim + two news conduct nodes. Shapes chosen so `node_text`, `node_domain`
    and `node_year` all take a different branch than each other."""
    return {
        "nodes": [
            {"class": "Organization", "properties": {"name": "Cong ty CP Nhua An Phat", "ticker": "AAA"}},
            {"class": "SustainabilityClaim",
             "properties": {"claim_id": "c-001", "source_type": "report",
                            "description": "Cong ty cam ket giam phat thai khi nha kinh 20% vao nam 2030."}},
            {"class": "MediaReport",
             "properties": {"source_type": "news", "publisher": "vnexpress.net",
                            "date": "2024-05-02",
                            "description": "Nha may cua cong ty bi xu phat vi xa thai vuot quy chuan."}},
            {"class": "Controversy",
             "properties": {"source_type": "news", "source_domain": "tuoitre.vn",
                            "date": "2023-11-20",
                            "description": "Cu dan phan anh tinh trang o nhiem quanh khu san xuat."}},
        ],
        "edges": [{"subject": 0, "predicate": "claims", "object": 1,
                   "temporal_metadata": {"valid_from": "2024-01-01"}}],
    }


def make_stub(verdict: str = "irrelevant"):
    """A `_GeminiProvider`-shaped stub: same constructor signature and `call` contract,
    so the REAL `Adjudicator` runs unmodified against it."""
    calls_seen: list = []

    class _Stub:
        name = "gemini"

        def __init__(self, model, rate_limit, api_key=None):
            self.model = model
            self.rate_limit = rate_limit
            self.enabled = True
            self.calls = 0
            self.failures = 0

        def call(self, system, user):
            calls_seen.append((system, user))
            return json.dumps({"verdict": verdict, "confidence": 0.83,
                               "rationale": "stub rationale"})

    _Stub.calls_seen = calls_seen
    return _Stub


class Workspace:
    """Temp dirs so no arm ever touches the real caches or writes into graph_output/."""

    def __init__(self, graph: dict):
        self.dir = Path(tempfile.mkdtemp(prefix="esgkg_replay_"))
        self.graph_path = self.dir / "resolved_graph.json"
        self.graph_path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        self.cache_path = self.dir / "adjudication_cache.json"
        self.out = self.dir / "out" / "adjudicated_pairs.jsonl"
        self.stats_out = self.dir / "out" / "replay_stats.json"

    def args(self, **overrides) -> argparse.Namespace:
        args = argparse.Namespace(
            input=self.graph_path, cache=[self.cache_path], out=self.out,
            stats_out=self.stats_out, salt_model=[], generation="both", dry_run=False,
        )
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    def rows(self):
        if not self.out.exists():
            return None
        return [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines() if line.strip()]

    def stats(self):
        return json.loads(self.stats_out.read_text(encoding="utf-8")) if self.stats_out.exists() else None

    def write_cache(self, entries: dict) -> None:
        self.cache_path.write_text(json.dumps({"version": 1, "entries": entries}, ensure_ascii=False),
                                   encoding="utf-8")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _pair_texts(graph: dict, ci: int, xi: int):
    """The three strings step07 hashes, computed with step07's OWN helpers."""
    cnode, xnode = graph["nodes"][ci], graph["nodes"][xi]
    claim_text = step07.node_text(cnode)
    evidence_text = step07.node_text(xnode)
    meta = (f"{xnode.get('class')} from {step07.node_domain(xnode) or 'news'}, "
            f"year {step07.node_year(xnode)}")
    return claim_text, evidence_text, meta


# --------------------------------------------------------------------------- #
# 1. The tool must be incapable of spending money
# --------------------------------------------------------------------------- #
def test_never_constructs_a_provider():
    """Checked against the module's CODE, not its prose — the docstring is entitled to
    explain how the tool relates to `Adjudicator`; what it must never do is import or
    call one."""
    for banned in ("Adjudicator", "_GeminiProvider", "_DeepSeekProvider", "_OpenAIProvider",
                   "build_llm_provider", "build_gemini_client"):
        assert not hasattr(replay, banned), (
            f"replay_adjudications must not hold {banned} — the tool's whole value is that "
            "it cannot call a provider on a cache miss")

    src = (REPO / "src" / "esg_kg" / "export" / "replay_adjudications.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    BANNED_MODULES = {"esg_kg.core.llm", "google.genai", "genai", "requests", "openai", "httpx"}
    BANNED_NAMES = {"Adjudicator", "_GeminiProvider", "_DeepSeekProvider", "_OpenAIProvider",
                    "build_llm_provider", "build_gemini_client", "_Provider"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name not in BANNED_MODULES, f"imports {a.name}"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") not in BANNED_MODULES, f"imports from {node.module}"
            for a in node.names:
                assert a.name not in BANNED_NAMES, f"imports {a.name} from {node.module}"
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            assert name not in BANNED_NAMES, f"calls {name}()"


# --------------------------------------------------------------------------- #
# 2. Key fidelity: a verdict the REAL Adjudicator cached must come back out
# --------------------------------------------------------------------------- #
def test_recovers_a_verdict_written_by_the_real_adjudicator():
    graph = synthetic_graph()
    ws = Workspace(graph)
    stub = make_stub("contradicts")
    original = step07._GeminiProvider
    try:
        step07._GeminiProvider = stub
        cache = ContentCache(ws.cache_path)
        adj = step07.Adjudicator("gemini-2.5-flash", 60, ["gemini"], api_key="fake", cache=cache)
        assert adj.enabled, "stubbed Adjudicator should be enabled"
        claim_text, ev_text, meta = _pair_texts(graph, 1, 2)
        out = adj.adjudicate(claim_text, ev_text, meta)
        assert out and out["verdict"] == "contradicts"
        cache.save()
    finally:
        step07._GeminiProvider = original

    try:
        replay.run(ws.args(salt_model=["gemini:gemini-2.5-flash"]))
        rows = ws.rows()
        assert rows, "the replay recovered nothing the real Adjudicator had just cached"
        hit = [r for r in rows if r["claim_node_index"] == 1 and r["evidence_node_index"] == 2]
        assert len(hit) == 1, f"expected exactly one row for the cached pair, got {len(hit)}"
        r = hit[0]
        assert r["verdict"] == "contradicts", r
        assert r["claim_text"] == claim_text, "claim_text must be step07's node_text output"
        assert r["evidence_text"] == ev_text, "evidence_text must be step07's node_text output"
        assert r["evidence_meta"] == meta, f"meta string drifted from step07's: {r['evidence_meta']!r}"
        assert r["key_shape"] == "salted", r
        assert r["prompt_generation"] == "current", r
        assert r["provider"] == "gemini", r
    finally:
        ws.close()


def test_evidence_meta_matches_the_stage_formula():
    """The meta string is part of the hashed content, so a reworded f-string silently
    zeroes the recovery rate. Pin it against step07's own helpers."""
    graph = synthetic_graph()
    for xi in (2, 3):
        _, _, expected = _pair_texts(graph, 1, xi)
        assert replay.evidence_meta(graph["nodes"][xi]) == expected, (
            f"node {xi}: {replay.evidence_meta(graph['nodes'][xi])!r} != {expected!r}")


# --------------------------------------------------------------------------- #
# 3. Two prompt generations must be recovered AND kept apart
# --------------------------------------------------------------------------- #
def test_recovers_legacy_unsalted_entries_and_labels_them():
    graph = synthetic_graph()
    ws = Workspace(graph)
    claim_text, ev_text, meta = _pair_texts(graph, 1, 2)
    legacy_key = ContentCache.key(claim_text, ev_text, meta)
    ws.write_cache({legacy_key: {"verdict": "supports", "confidence": 0.9,
                                 "rationale": "pre-P1-fix verdict", "provider": "openai"}})
    try:
        replay.run(ws.args())
        rows = ws.rows()
        assert len(rows) == 1, f"expected 1 legacy row, got {rows}"
        r = rows[0]
        assert r["key_shape"] == "unsalted", r
        assert r["prompt_generation"] == "legacy", r
        assert r["verdict"] == "supports" and r["provider"] == "openai", r
    finally:
        ws.close()


def test_generation_filter_separates_the_two_prompt_generations():
    """The same pair carrying BOTH a legacy and a current verdict is the poisoning case:
    identical text, contradictory labels. Both must be recoverable, and selectable."""
    graph = synthetic_graph()
    ws = Workspace(graph)
    claim_text, ev_text, meta = _pair_texts(graph, 1, 2)
    salt = replay.salt_for("gemini:gemini-2.5-flash")
    ws.write_cache({
        ContentCache.key(claim_text, ev_text, meta):
            {"verdict": "supports", "confidence": 0.9, "rationale": "old", "provider": "openai"},
        ContentCache.key(salt, claim_text, ev_text, meta):
            {"verdict": "irrelevant", "confidence": 0.7, "rationale": "new", "provider": "gemini"},
    })
    try:
        replay.run(ws.args(salt_model=["gemini:gemini-2.5-flash"], generation="both"))
        rows = ws.rows()
        assert len(rows) == 2, f"both generations must survive, got {rows}"
        assert {r["prompt_generation"] for r in rows} == {"legacy", "current"}
        st = ws.stats()
        assert st["pairs_with_both_generations"] == 1, st
        assert st["generations_disagree"] == 1, (
            "a pair whose legacy and current verdicts differ must be counted — that number "
            f"is the measured impact of the P1 prompt fix: {st}")

        replay.run(ws.args(salt_model=["gemini:gemini-2.5-flash"], generation="current"))
        rows = ws.rows()
        assert len(rows) == 1 and rows[0]["prompt_generation"] == "current", rows

        replay.run(ws.args(salt_model=["gemini:gemini-2.5-flash"], generation="legacy"))
        rows = ws.rows()
        assert len(rows) == 1 and rows[0]["prompt_generation"] == "legacy", rows
    finally:
        ws.close()


def test_cross_provider_agreement_is_measured():
    """One pair adjudicated by two providers is a free label-quality signal: the
    disagreement rate is a measured number about how noisy the silver labels are. It
    only exists because the SAME key lives in several cache files, so it has to be
    counted across files, not within one."""
    graph = synthetic_graph()
    ws = Workspace(graph)
    claim_text, ev_text, meta = _pair_texts(graph, 1, 2)
    key_a = ContentCache.key(claim_text, ev_text, meta)
    claim2, ev2, meta2 = _pair_texts(graph, 1, 3)
    key_b = ContentCache.key(claim2, ev2, meta2)

    second = ws.dir / "adjudication_cache_openai.json"
    ws.write_cache({key_a: {"verdict": "supports", "confidence": 0.9, "rationale": "g",
                            "provider": "gemini"},
                    key_b: {"verdict": "irrelevant", "confidence": 0.4, "rationale": "g",
                            "provider": "gemini"}})
    second.write_text(json.dumps({"version": 1, "entries": {
        key_a: {"verdict": "contradicts", "confidence": 0.7, "rationale": "o", "provider": "openai"},
        key_b: {"verdict": "irrelevant", "confidence": 0.6, "rationale": "o", "provider": "openai"},
    }}, ensure_ascii=False), encoding="utf-8")
    try:
        replay.run(ws.args(cache=[ws.cache_path, second]))
        st = ws.stats()
        assert st["cross_provider_pairs"] == 2, st
        assert st["cross_provider_agree"] == 1, (
            f"one pair agrees (irrelevant/irrelevant), one disagrees: {st}")
        assert st["cross_provider_agreement_rate"] == 0.5, st
        # 4 rows over 2 distinct text pairs — the consumer must dedupe on TEXT.
        assert st["distinct_text_pairs"] == 2, st
        assert st["rows"] == 4, st
    finally:
        ws.close()


def test_duplicate_text_pairs_share_one_cache_entry():
    """Two DIFFERENT node pairs carrying byte-identical text hash to ONE key — step07
    paid once and both replay. The row count therefore exceeds the entry count, and a
    training set deduped on node index would double-count them."""
    graph = synthetic_graph()
    twin = json.loads(json.dumps(graph["nodes"][1]))  # a second claim node, identical text
    graph["nodes"].append(twin)
    ws = Workspace(graph)
    claim_text, ev_text, meta = _pair_texts(graph, 1, 2)
    ws.write_cache({ContentCache.key(claim_text, ev_text, meta):
                    {"verdict": "supports", "confidence": 0.9, "rationale": "r", "provider": "gemini"}})
    try:
        replay.run(ws.args())
        rows = ws.rows()
        assert len(rows) == 2, f"both node pairs must replay off the one entry: {rows}"
        assert {r["claim_node_index"] for r in rows} == {1, 4}, rows
        st = ws.stats()
        assert st["recovered_cache_entries"] == 1, st
        assert st["distinct_text_pairs"] == 1, st
    finally:
        ws.close()


def test_salt_formula_matches_the_adjudicator():
    """`salt_for` must reproduce `Adjudicator._cache_salt` exactly, including the
    prompt hash taken from the LIVE ADJUDICATE_SYSTEM (never a copied literal)."""
    stub = make_stub()
    original = step07._GeminiProvider
    try:
        step07._GeminiProvider = stub
        adj = step07.Adjudicator("gemini-2.5-flash", 60, ["gemini"], api_key="fake")
        assert replay.salt_for("gemini:gemini-2.5-flash") == adj._cache_salt, (
            f"{replay.salt_for('gemini:gemini-2.5-flash')!r} != {adj._cache_salt!r}")
    finally:
        step07._GeminiProvider = original

    expected_hash = hashlib.sha256(step07.ADJUDICATE_SYSTEM.encode("utf-8")).hexdigest()[:12]
    assert replay.salt_for("x:y").startswith(expected_hash + "|")


# --------------------------------------------------------------------------- #
# 4. It must not invent rows, and must respect --dry-run
# --------------------------------------------------------------------------- #
def test_pairs_absent_from_the_cache_produce_no_rows():
    graph = synthetic_graph()
    ws = Workspace(graph)
    ws.write_cache({})
    try:
        replay.run(ws.args())
        assert ws.rows() == [], "an empty cache must yield an empty training set, not guesses"
        st = ws.stats()
        assert st["rows"] == 0 and st["pairs_probed"] > 0, st
    finally:
        ws.close()


def test_dry_run_writes_nothing():
    graph = synthetic_graph()
    ws = Workspace(graph)
    claim_text, ev_text, meta = _pair_texts(graph, 1, 2)
    ws.write_cache({ContentCache.key(claim_text, ev_text, meta):
                    {"verdict": "supports", "confidence": 0.5, "rationale": "r", "provider": "gemini"}})
    try:
        replay.run(ws.args(dry_run=True))
        assert not ws.out.exists(), "--dry-run must not write the JSONL"
        assert not ws.stats_out.exists(), "--dry-run must not write the stats file"
    finally:
        ws.close()


def test_conduct_pool_is_news_scoped_like_the_stage():
    """The probe pool must be the stage's conduct universe (CONDUCT_CLASSES +
    source_type=news) — a claim node or a report-side node must never enter it."""
    graph = synthetic_graph()
    graph["nodes"].append({"class": "KPIObservation",
                           "properties": {"source_type": "report", "kpi_type": "emission", "value": 12}})
    idxs = replay.conduct_indices(graph["nodes"])
    assert idxs == [2, 3], f"report-side and non-conduct nodes leaked into the pool: {idxs}"
    assert replay.claim_indices(graph["nodes"]) == [1]


# --------------------------------------------------------------------------- #
# 5. Real artifacts (SKIP on a bare clone)
# --------------------------------------------------------------------------- #
def _replay_real(graph_path: Path, caches: list):
    out_dir = Path(tempfile.mkdtemp(prefix="esgkg_replay_real_"))
    try:
        args = argparse.Namespace(
            input=graph_path, cache=caches, out=out_dir / "pairs.jsonl",
            stats_out=out_dir / "stats.json", salt_model=[], generation="both", dry_run=False)
        replay.run(args)
        rows = [json.loads(l) for l in (out_dir / "pairs.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()]
        st = json.loads((out_dir / "stats.json").read_text(encoding="utf-8"))
        return rows, st
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def test_real_caches_replay_and_are_index_independent():
    """The 2026-08-14 P5 fix reordered the resolved graph (10,634/14,744 ->
    10,624/15,130), which breaks any recovery route keyed on NODE INDEX — the dossiers'
    own node_index values now resolve to different classes, recovering 0%. Probing the
    cross product never trusts an index, only the text at it, so BOTH the current graph
    and the pre-P5 backup must recover identically. That equality is the property worth
    pinning: it is what makes the replay survive a graph rebuild that preserves text."""
    caches = sorted(CROSSCHECK_DIR.glob("adjudication_cache*.json"))
    if not PRE_P5_BACKUP.exists() or not CURRENT_GRAPH.exists() or not caches:
        _skip("test_real_caches_replay_and_are_index_independent",
              "needs graph_output/ (git-ignored, shipped via the HF snapshot)")
        return

    rows_old, st_old = _replay_real(PRE_P5_BACKUP, caches)
    assert len(rows_old) > 100, f"real replay recovered only {len(rows_old)} rows"
    for r in rows_old:
        assert r["verdict"] in ("supports", "contradicts", "irrelevant"), r
        assert r["claim_text"] and r["evidence_text"], r
        assert r["prompt_generation"] in ("current", "legacy"), r
    assert st_old["recovered_cache_entries"] > 0 and st_old["recovery_rate"] > 0.5, (
        f"recovery rate too low to trust the replay: {st_old}")

    rows_new, st_new = _replay_real(CURRENT_GRAPH, caches)
    assert st_new["recovery_rate"] == st_old["recovery_rate"], (
        "the P5 node reorder must not change what the cross-product probe recovers "
        f"(current={st_new['recovery_rate']}, pre-P5={st_old['recovery_rate']})")
    key = lambda rs: sorted((r["claim_text"], r["evidence_text"], r["verdict"],
                             r["cache_file"], r["prompt_generation"]) for r in rs)
    assert key(rows_new) == key(rows_old), (
        "same caches + same texts must yield the same labelled rows regardless of node order")


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
