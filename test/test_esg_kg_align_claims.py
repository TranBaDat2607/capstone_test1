#!/usr/bin/env python3
"""
Behavioural coverage for ONE migration slice: `esg_kg.resolve.align_claims`
(originally ported from `src/step05d_align_claims_to_indicators.py`).

REPOINTED AT esg_kg ONLY (2026-07-29)
`src/` is scheduled for deletion now that all 15 stages have moved, so this file no
longer imports it or asserts `new == old`. Where a test function ALSO made an
independent claim about `esg_kg`'s own behaviour, only the cross-tree comparison
lines were stripped; where a function was a pure `new == old` comparison, it was
rewritten to assert concrete expected values (never fabricated — read straight off
`esg_kg/resolve/align_claims.py`) or, when no safe concrete value existed, deleted
(none were, here).

WHY THIS IS A SEPARATE FILE
Same reason as `test_esg_kg_anchor_kpi.py` / `_provenance.py` / `_fix_triples.py`:
`test_esg_kg_equivalence.py` covers the kernel and is past 1,100 lines, while this covers a
single stage end-to-end. Same contract as all of them — import BOTH trees, run them on the
same input, assert equal.

WHY THIS SLICE NEEDED NO NEW core/ MODULE
It is the third stage (after 05b and 03) to move with the kernel untouched. step05d imports
five symbols from the old tree and every one was already lifted: `REPO_ROOT`
(-> `core/paths`), `load_schema_sets` (-> `core/schema`), `GraphPatch` + `temporal_md`
(-> `core/graph_patch`, lifted by the 05c slice), `_OpenAIProvider` (-> `core/llm`).

HOW THE PAID BRANCH IS COVERED WITHOUT PAYING
This is a mandatory-LLM stage: `--dry-run` returns before the provider is even built, so a
dry-run-only arm would prove almost nothing. The stage is therefore driven by a STUB
provider injected over `_OpenAIProvider`, exactly as the step03 slice drives phase 2. The
stub answers deterministically from a CRC of the prompt, and it deliberately returns all
five reply shapes the parser must survive: clean JSON, "none", JSON embedded in prose,
junk, and a well-formed id that is not in the vocabulary.

WHAT THE ALREADY-PATCHED-ARTIFACT LAW (PIPELINE.md §3) SAYS HERE
Ask the one question: meeting its own past output, does the stage skip or recompute? It
SKIPS — a node with any `alignsWithIndicator` edge is excluded from `candidates`, so a
re-run cannot re-adjudicate it. That is 05c/03b's shape, which is what made those arms
vacuous... except the live `resolved_graph.json` today holds 639 alignsWithIndicator edges
and ALL of them are `alignment_method=keyword` (05c's), ZERO are `llm`. The stage has never
been run against this snapshot, so its own residue is absent and the real-graph arm is
non-vacuous with no fixture. `strip_llm_alignments()` exists anyway and is applied
defensively: it removes 0 edges today, and the day someone runs 05d for real it is what
keeps this arm honest instead of silently shrinking. Keyword edges are NEVER stripped —
they are 05c's output, and 05d skipping them is the design (it handles the remainder), not
self-output.

WHAT `test_node_text_is_not_step07s` COMPARES AGAINST NOW
It used to import `step07_crosscheck_claims_vs_conduct` from `src/`; it now imports
`esg_kg.crosscheck.claims_vs_conduct`, the migrated stage's own copy of the trap — the
divergence (properties dict vs. node) is a property of the current code, not of the old
tree, so the check is exactly as strong post-conversion.

THE TRAP THIS SLICE HAD TO AVOID (PIPELINE.md §2.1)
There are TWO functions named `node_text` and they are NOT duplicates: this one takes a
PROPERTIES DICT, `step07:133` takes a NODE and dispatches on its class. Merging them would
silently rewrite step07's paid prompt. `test_node_text_is_not_step07s` pins the difference.

Offline: no LLM, no Neo4j, no network, no OPENAI_API_KEY (the stub replaces the provider
before it can look for one). `config/schema.json` and `kpi_definitions_construction.json`
are tracked in git so the synthetic arms always run; arms needing `graph_output/`
(git-ignored, shipped via the HF snapshot) SKIP with a message on a bare clone.

Run from the repo root:

    python test/test_esg_kg_align_claims.py
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

# --- esg_kg package --------------------------------------------------------
from esg_kg.core import graph_patch as core_graph_patch  # noqa: E402
from esg_kg.core import llm as core_llm  # noqa: E402
from esg_kg.core import schema as core_schema  # noqa: E402
from esg_kg.resolve import align_claims as new_05d  # noqa: E402
from esg_kg.crosscheck import claims_vs_conduct as new_step07  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
DEFS_FILE = REPO / "kpi_definitions_construction.json"
RESOLVED_FILE = REPO / "graph_output" / "resolved" / "resolved_graph.json"

_skips: list = []


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def load_defs() -> list:
    return json.loads(DEFS_FILE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# The stub provider. Deterministic from the prompt, so BOTH trees see the same
# replies for the same nodes — that is what makes the comparison meaningful.
# --------------------------------------------------------------------------- #
def make_stub(valid_ids: list, mode: str = "mixed"):
    """Return a class with `_OpenAIProvider(model, rate_limit)`'s interface.

    `mode="mixed"` walks all five reply shapes the parser must survive.
    `mode="always_raise"` drives the 3-failures-0-successes abort branch.
    """
    ids = sorted(valid_ids)
    calls_seen: list = []

    class _Stub:
        name = "openai"

        def __init__(self, model, rate_limit, api_key=None, base_url=None):
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
            crc = zlib.crc32(user.encode("utf-8"))
            shape = crc % 5
            if shape == 0:  # clean JSON, a real id
                return json.dumps({"indicator_id": ids[crc % len(ids)], "confidence": 0.91})
            if shape == 1:  # honest "none" — the answer for boilerplate
                return '{"indicator_id": "none", "confidence": 0.12}'
            if shape == 2:  # JSON wrapped in prose -> the regex fallback in parse_reply
                return f'Sure!\n{{"indicator_id": "{ids[crc % len(ids)]}", "confidence": 0.7}}\nHope that helps.'
            if shape == 3:  # not JSON at all -> None
                return "I could not determine an indicator for this statement."
            return '{"indicator_id": "TT96-9.9.9", "confidence": 0.99}'  # well-formed, unknown id

    _Stub.calls_seen = calls_seen
    return _Stub


class Workspace:
    """A temp copy of a graph + the stats path, so no arm ever touches the real artifacts."""

    def __init__(self, graph: dict, defs: list = None):
        self.dir = Path(tempfile.mkdtemp(prefix="esgkg_05d_"))
        self.graph_path = self.dir / "resolved_graph.json"
        self.stats_path = self.dir / "indicator_align_llm_stats.json"
        self.graph_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        self.defs_path = self.dir / "defs.json"
        if defs is not None:
            self.defs_path.write_text(json.dumps(defs, ensure_ascii=False), encoding="utf-8")
        else:
            self.defs_path = DEFS_FILE

    def args(self, **overrides) -> argparse.Namespace:
        args = argparse.Namespace(
            input=self.graph_path, defs=self.defs_path, schema=SCHEMA_FILE,
            max_llm_pairs=200, openai_model="gpt-4o-mini", rate_limit=60,
            stats_out=self.stats_path, dry_run=False,
        )
        for k, v in overrides.items():
            setattr(args, k, v)
        return args

    @property
    def graph(self) -> dict:
        return json.loads(self.graph_path.read_text(encoding="utf-8"))

    @property
    def stats(self) -> dict:
        if not self.stats_path.exists():
            return {}
        return json.loads(self.stats_path.read_text(encoding="utf-8"))

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def run_new(graph: dict, defs: list = None, stub_mode: str = "mixed", **overrides):
    """Run the stage against esg_kg on the given input; return (ws, stub, logs)."""
    valid_ids = [d["id"] for d in (defs if defs is not None else load_defs())]
    ws = Workspace(copy.deepcopy(graph), defs)
    stub = make_stub(valid_ids, stub_mode)
    original = new_05d._OpenAIProvider
    handler = _LogCatcher()
    new_05d.logger.addHandler(handler)
    try:
        new_05d._OpenAIProvider = stub
        new_05d.run(ws.args(**overrides))
    finally:
        new_05d._OpenAIProvider = original
        new_05d.logger.removeHandler(handler)
    # The final log line echoes the workspace's mkdtemp path — mask it so a rerun's
    # comparison against fixed strings (e.g. "unaligned") is not sensitive to it.
    logs = [m.replace(str(ws.dir), "<WS>") for m in handler.messages]
    return ws, stub, logs


class _LogCatcher(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def strip_llm_alignments(graph: dict) -> int:
    """Remove this stage's OWN past output — `alignsWithIndicator` edges written by the LLM
    tier — and NOTHING else. 05c's keyword edges stay: they are another stage's output, and
    05d skipping their subjects is the design. Returns how many edges were removed (0 on
    today's snapshot: the stage has never been run against it)."""
    before = len(graph["edges"])
    graph["edges"] = [e for e in graph["edges"]
                      if not (e.get("predicate") == "alignsWithIndicator"
                              and e.get("alignment_method") == "llm")]
    return before - len(graph["edges"])


def real_graph():
    """The live resolved graph with any prior LLM alignment stripped, or None on a bare clone."""
    if not RESOLVED_FILE.exists():
        return None, 0
    graph = json.loads(RESOLVED_FILE.read_text(encoding="utf-8"))
    removed = strip_llm_alignments(graph)
    return graph, removed


# --------------------------------------------------------------------------- #
# 1. Module surface: constants, and that the new tree IMPORTS the kernel
# --------------------------------------------------------------------------- #
def test_constants_match():
    """Concrete expected values (esg_kg/resolve/align_claims.py), not a cross-tree diff."""
    assert new_05d.ALIGN_CLASSES == ("SustainabilityClaim", "Goal", "Initiative")
    assert new_05d.DEFAULT_RESOLVED == REPO / "graph_output" / "resolved" / "resolved_graph.json"
    assert new_05d.DEFAULT_DEFS == REPO / "kpi_definitions_construction.json"
    assert new_05d.DEFAULT_SCHEMA == REPO / "config" / "schema.json"
    assert new_05d.DEFAULT_STATS_OUT == REPO / "graph_output" / "resolved" / "indicator_align_llm_stats.json"

    # The SYSTEM prompt is PAID BEHAVIOUR, not style: reword it and the stage still "works"
    # while every classification changes. Pinned byte-for-byte, like BATCH_FIX_PROMPT in the
    # 03 slice.
    assert new_05d.SYSTEM == (
        "You classify a Vietnamese company ESG statement against a fixed list of disclosure "
        "indicators (Circular 96/2020/TT-BTC and the SSC-IFC ESG guide). Choose the ONE indicator "
        "the statement is primarily about, or \"none\" if it is generic / not about any of them. "
        "Do not guess — 'none' is the right answer for boilerplate. Return only JSON: "
        "{\"indicator_id\": \"TT96-6.1.1\"|...|\"none\", \"confidence\": 0-1}."
    ), "the paid SYSTEM prompt was reworded"


def test_new_tree_imports_the_kernel_rather_than_recopying():
    """A migrated stage must USE core/, not carry its own copy — otherwise the two drift."""
    assert new_05d.GraphPatch is core_graph_patch.GraphPatch, "GraphPatch was re-copied"
    assert new_05d.temporal_md is core_graph_patch.temporal_md, "temporal_md was re-copied"
    assert new_05d._OpenAIProvider is core_llm._OpenAIProvider, "_OpenAIProvider was re-copied"
    assert new_05d.load_schema_sets is core_schema.load_schema_sets, "load_schema_sets re-copied"


# --------------------------------------------------------------------------- #
# 2. Pure helpers
# --------------------------------------------------------------------------- #
def test_build_prompt_matches():
    """Independent claim: every prompt is well-formed, and the 600-char cap is exact."""
    defs = load_defs()
    cases = ["Chúng tôi cam kết giảm phát thải khí nhà kính 20% vào năm 2030.",
             "", "x" * 599, "y" * 600, "z" * 601, "Đào tạo an toàn lao động cho 1.200 nhân viên"]
    for text in cases:
        prompt = new_05d.build_prompt(text, defs)
        assert "INDICATORS:" in prompt and "STATEMENT:" in prompt, f"prompt malformed for {text[:30]!r}"
        assert text[:600] in prompt, f"prompt dropped the statement for {text[:30]!r}"

    # the 600-char truncation is behaviour: it caps what each classification costs
    long_prompt = new_05d.build_prompt("z" * 5000, defs)
    assert "z" * 600 in long_prompt and "z" * 601 not in long_prompt, "truncation moved off 600"


def test_node_text_matches():
    """Concrete expected values for `node_text`'s join-and-strip over description/name/title."""
    cases = [
        ({"description": "d", "name": "n", "title": "t"}, "d n t"),
        ({"name": "chỉ có tên"}, "chỉ có tên"),
        ({"description": None, "name": "", "title": "T"}, "T"),
        ({}, ""),
        ({"unrelated": "ignored"}, ""),
    ]
    for props, expected in cases:
        assert new_05d.node_text(props) == expected, f"node_text({props}) != {expected!r}"


def test_node_text_is_not_step07s():
    """PIPELINE.md §2.1's documented trap: two same-named functions, DIFFERENT signatures.

    This one takes a PROPERTIES DICT; step07's (`esg_kg.crosscheck.claims_vs_conduct`) takes
    a NODE and dispatches on its class. Unifying them silently rewrites step07's paid prompt,
    so the migration must keep 05d's own. Feed a *node* to prove they are not interchangeable.
    """
    node = {"class": "SustainabilityClaim", "properties": {"description": "giảm phát thải"}}
    assert new_05d.node_text(node) == "", "05d's node_text accepted a node — it takes properties"
    assert new_05d.node_text(node["properties"]) == "giảm phát thải"
    assert new_05d.node_text is not new_step07.node_text, "05d's node_text was merged with step07's"
    assert new_step07.node_text(node) != "", "step07's node_text takes a NODE (guard is inverted)"


def _outcome(fn, raw, valid):
    """(value) or (exception type) — so an arm can compare trees that both raise."""
    try:
        return ("value", fn(raw, valid))
    except Exception as e:
        return ("raised", type(e).__name__)


def test_parse_reply_matches():
    """Concrete expected outcome per reply shape, replacing the old cross-tree diff."""
    valid = {"TT96-6.1.1", "SSCIFC-S6"}
    cases = [
        ('{"indicator_id": "TT96-6.1.1", "confidence": 0.9}', "TT96-6.1.1"),  # clean
        ('{"indicator_id": "none"}', None),                                   # honest refusal
        ('blah {"indicator_id": "SSCIFC-S6"} trailing', "SSCIFC-S6"),         # regex fallback
        ('no json here', None),                                              # unparseable
        ('{"indicator_id": "TT96-9.9.9"}', None),                            # well-formed, unknown id
        ('{"confidence": 0.5}', None),                                       # key missing
        ('{broken json', None),                                              # malformed
        ('[]', None),                                                        # valid JSON, WRONG SHAPE
        ('"just a string"', None),                                           # ditto
        ('', None),                                                          # empty
    ]
    for raw, expected in cases:
        got = _outcome(new_05d.parse_reply, raw, valid)
        assert got == ("value", expected), f"parse_reply({raw!r}) = {got}, expected {expected!r}"


def test_parse_reply_rejects_non_object_json():
    """Valid JSON of the wrong SHAPE must be refused like any other unusable reply.

    Before the fix, `json.loads('[]')` succeeded, returned a list, and `out.get(...)` raised
    AttributeError. Every other malformed shape already returned None, so this was a genuine
    inconsistency — and an expensive one: `run()` writes the graph only AFTER the loop and
    nothing catches an exception from `parse_reply`, so ONE odd reply discarded every
    adjudication already paid for in that run.

    Not reachable through the real provider today (`response_format={"type":"json_object"}`
    guarantees an object), which is why it survived unnoticed. It becomes reachable the
    moment a provider without that guarantee is added — exactly the kind of latent trap a
    migration is the right time to notice and the wrong time to fix silently, so this landed
    as its own commit in both `src/` and `esg_kg` at the time (DESIGN.md §5.3); this file now
    only proves esg_kg's own copy.
    """
    for raw in ("[]", '"just a string"', "42", "null", "true"):
        assert new_05d.parse_reply(raw, {"TT96-6.1.1"}) is None, f"mishandled {raw!r}"

    # the fix must not have made the parser lenient about anything else
    assert new_05d.parse_reply('{"indicator_id": "TT96-6.1.1"}', {"TT96-6.1.1"}) == "TT96-6.1.1"
    assert new_05d.parse_reply('[{"indicator_id": "TT96-6.1.1"}]', {"TT96-6.1.1"}) is None, \
        "a LIST wrapping a good object must still be refused, not unwrapped"


# --------------------------------------------------------------------------- #
# 3. Stage runs — real corpus
# --------------------------------------------------------------------------- #
def test_dry_run_writes_nothing():
    graph, _ = real_graph()
    if graph is None:
        return _skip("test_dry_run_writes_nothing",
                     "graph_output/resolved/resolved_graph.json not present (HF snapshot)")
    nw, _, nlogs = run_new(graph, dry_run=True)
    try:
        assert any("unaligned" in m for m in nlogs), f"candidate line missing: {nlogs}"
        assert not nw.stats_path.exists(), "--dry-run wrote stats"
        assert nw.graph == graph, "--dry-run mutated the graph"
    finally:
        nw.close()


def test_full_run_on_real_graph():
    """The headline arm: the whole paid path, esg_kg, real graph, stub LLM."""
    graph, removed = real_graph()
    if graph is None:
        return _skip("test_full_run_on_real_graph", "resolved_graph.json not present")
    budget = 60
    nw, nstub, _ = run_new(graph, max_llm_pairs=budget)
    try:
        s = nw.stats
        # NON-VACUITY: this arm must actually adjudicate and actually write edges.
        assert s["candidates"] > 100, f"suspiciously few candidates: {s}"
        assert s["adjudicated"] == budget, f"budget not honoured: {s}"
        assert s["edges_added"] > 0, f"no edges written — arm is vacuous: {s}"
        assert s["none_or_absent"] > 0, f"the 'none' branch never fired: {s}"
        assert s["dropped_invalid"] == 0, f"schema rejected an edge: {s}"
        assert s["llm_calls"] == budget and s["llm_failures"] == 0, s
        assert len(nstub.calls_seen) == budget, "stub call count doesn't match the budget"
        print(f"     (stripped {removed} prior llm edge(s); {s['candidates']} candidates, "
              f"{s['edges_added']} edge(s) added from {budget} adjudications)")
    finally:
        nw.close()


def test_run_is_append_only_and_preserves_node_order():
    """step06 keys Neo4j by ARRAY INDEX and step07 dossiers cite nodes by position.

    step05d — unlike step05c — never calls assert_append_only() itself, so this is the only
    thing standing between a future edit and silently repositioned nodes.
    """
    graph, _ = real_graph()
    if graph is None:
        return _skip("test_run_is_append_only_and_preserves_node_order",
                     "resolved_graph.json not present")
    n_nodes0, n_edges0 = len(graph["nodes"]), len(graph["edges"])
    nw, _, _ = run_new(graph, max_llm_pairs=40)
    try:
        out = nw.graph
        assert out["nodes"] == graph["nodes"], "05d added or reordered NODES (it must not)"
        assert len(out["edges"]) >= n_edges0, "05d removed edges"
        assert out["edges"][:n_edges0] == graph["edges"], "existing edge prefix was disturbed"
        assert len(out["nodes"]) == n_nodes0
        for e in out["edges"][n_edges0:]:
            assert e["predicate"] == "alignsWithIndicator", f"unexpected new edge: {e}"
            assert e["alignment_method"] == "llm", f"new edge not tagged llm: {e}"
            assert e["temporal_metadata"]["recorded_at"] == core_graph_patch.TODAY, e
    finally:
        nw.close()


# --------------------------------------------------------------------------- #
# 4. Live branches the real data never reaches — synthetic fixtures
# --------------------------------------------------------------------------- #
def _tiny_graph():
    """3 alignable nodes + 2 indicator nodes, small enough that a budget covers every candidate."""
    return {
        "nodes": [
            {"class": "StandardIndicator", "properties": {"id": "TT96-6.1.1", "name": "Phát thải"}},
            {"class": "StandardIndicator", "properties": {"id": "SSCIFC-S6", "name": "Cộng đồng"}},
            {"class": "SustainabilityClaim",
             "properties": {"description": "Giảm phát thải 20%", "valid_from": "2024-01-01"}},
            {"class": "Goal", "properties": {"name": "Trung hoà carbon 2050"}},
            {"class": "Initiative", "properties": {"title": "Quỹ từ thiện cộng đồng"}},
            {"class": "Organization", "properties": {"name": "Không phải lớp align"}},
            {"class": "Goal", "properties": {}},  # no text -> never a candidate
        ],
        "edges": [],
    }


def _tiny_defs():
    return [{"id": "TT96-6.1.1", "name": "Tổng phát thải khí nhà kính", "pillar": "Môi trường"},
            {"id": "SSCIFC-S6", "name": "Đóng góp cộng đồng", "pillar": "Xã hội"}]


def test_rerun_skips_what_it_already_aligned():
    """PIPELINE.md §3's one question — meeting its own output, does it skip or recompute?

    05d SKIPS: `candidates` excludes any node that already carries an alignsWithIndicator
    edge. Proven here rather than on the real graph because only a synthetic graph is small
    enough for the budget to cover EVERY candidate — on the live file a second run simply
    walks further down a 1,810-long queue, which would prove nothing about skipping.
    """
    defs = _tiny_defs()
    nw, _, _ = run_new(_tiny_graph(), defs=defs, max_llm_pairs=50)
    try:
        first = nw.stats
        assert first["edges_added"] > 0, f"fixture never wrote an edge — arm is vacuous: {first}"

        # feed run 1's OUTPUT back in
        nw2, _, _ = run_new(nw.graph, defs=defs, max_llm_pairs=50)
        try:
            assert nw2.stats["edges_added"] == 0, f"re-run duplicated edges: {nw2.stats}"
            assert nw2.stats["candidates"] < first["candidates"], \
                f"aligned nodes were NOT excluded on re-run: {nw2.stats}"
            assert nw2.graph["edges"] == nw.graph["edges"], "re-run changed the edge list"
        finally:
            nw2.close()
    finally:
        nw.close()


def test_provider_failures_abort_branch():
    """3 failures with 0 successes must abort the loop. No live run has ever tripped it."""
    defs = _tiny_defs()
    nw, nstub, nlogs = run_new(
        _tiny_graph(), defs=defs, stub_mode="always_raise", max_llm_pairs=50)
    try:
        s = nw.stats
        assert s["llm_failures"] == 3 and s["llm_calls"] == 0, f"abort branch not taken: {s}"
        assert s["adjudicated"] == 0 and s["edges_added"] == 0, s
        assert len(nstub.calls_seen) == 3, f"loop did not stop after 3 failures: {nstub.calls_seen}"
        assert any("aborting" in m.lower() for m in nlogs), f"no abort log: {nlogs}"
    finally:
        nw.close()


def test_indicator_absent_from_graph_is_counted_not_written():
    """A def id with no StandardIndicator node: valid per the vocabulary, unusable as an edge
    target. Live data has all 35 present, so only a fixture reaches this branch."""
    graph = _tiny_graph()
    graph["nodes"] = [n for n in graph["nodes"] if n.get("class") != "StandardIndicator"]
    defs = _tiny_defs()
    nw, _, nlogs = run_new(graph, defs=defs, max_llm_pairs=50)
    try:
        s = nw.stats
        assert s["edges_added"] == 0, f"wrote an edge to a missing indicator: {s}"
        assert s["none_or_absent"] == s["adjudicated"] > 0, s
        assert any("run step05c first" in m for m in nlogs), f"no missing-node warning: {nlogs}"
    finally:
        nw.close()


def test_missing_input_is_reported_not_crashed():
    ws = Workspace(_tiny_graph(), _tiny_defs())
    try:
        handler = _LogCatcher()
        new_05d.logger.addHandler(handler)
        try:
            new_05d.run(ws.args(input=ws.dir / "does_not_exist.json"))
        finally:
            new_05d.logger.removeHandler(handler)
        assert any("not found" in m.lower() for m in handler.messages), handler.messages
    finally:
        ws.close()


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
