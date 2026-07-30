#!/usr/bin/env python3
"""
The 05 BLOCK: `05 entities -> 05b provenance -> 05c indicators` is one unit that writes
ONE artifact, ONCE.

WHAT CHANGED AND WHY (DESIGN.md §5.7, decided 2026-07-28, built 2026-07-29)
In `src/` these were three scripts that each read AND write
`graph_output/resolved/resolved_graph.json`: `step05_resolve_entities.py` writes it from
scratch, then `step05b_stamp_provenance.py` and `step05c_link_standard_indicators.py`
patch it in place. `step05:655` overwrote the WHOLE file with no merge and no warning
(`PIPELINE.md` §3.1) — re-running it alone would silently destroy 05b's provenance stamps
and 05c's indicator axis.

`esg_kg` collapses the three into one block (`esg_kg/resolve/build_resolved.py`) that
passes the resolved graph IN MEMORY and writes the artifact exactly once — the same
redesign already proven for the `03` block
(`esg_kg/graph/build_validated.py` / `test_esg_kg_validated_block.py`), which this file
mirrors structurally. `05d` (`esg_kg.resolve.align_claims`) is NOT part of this block — it
stays a separate, optional, budgeted-LLM stage run AFTER the block, unchanged.

Repointed at `esg_kg` only (2026-07-29) now that `src/` is gone. This file used to run
`src/`'s three-stage chain as a live ORACLE and assert the block's artifact was byte-equal
to it — that comparison is what originally proved "collapsing three writes into one changes
WHEN the file is written, not WHAT ends up in it." With `src/` deleted there is no oracle
left to run, so the equality assertion is gone; what remains is the independent, new-tree-
only content the same function already carried (real corpus, >1000 nodes, indicator-axis
edges present, provenance stamps present) plus a same-named counter-arm
(`test_src_chain_really_writes_it_three_times`) that had NO independent claim of its own —
its entire content was characterizing the now-deleted old tree's behavior — so it was
deleted rather than kept as dead weight.

THE PAID-PATH CACHE — SCOPED TO STAGE C ONLY (see build_resolved.py's docstring for why
Stage B/embeddings is out of scope for now)
`AdjudicationCache` must make a rerun free: the fixture arm below drives Stage B/C
through a stub `google.genai.Client` twice and asserts the second run calls the LLM zero
times and produces an identical artifact — mirrors
`test_phase2_repairs_are_cached_and_the_rerun_is_free` in the `03` block's test file.

Offline: no LLM, no Neo4j, no network. The real-corpus arms SKIP on a bare clone.

Run from the repo root:

    python test/test_esg_kg_resolve_block.py
"""

import json
import logging
import pathlib
import sys
import tempfile
import zlib

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# --- the block --------------------------------------------------------------------
from esg_kg.resolve import build_resolved  # noqa: E402
from esg_kg.resolve import entities as new_entities  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
VALIDATED_FILE = REPO / "graph_output" / "validated" / "all_validated_triples.json"
GRAPHS_DIR = REPO / "graph_output" / "graphs"
ISSUER_REGISTRY = REPO / "config" / "issuer_registry.json"
STANDARDS_REGISTRY = REPO / "config" / "standards_registry.json"
DEFS_FILE = REPO / "kpi_definitions_construction.json"
CROSSWALK_FILE = REPO / "config" / "standard_crosswalk.json"
GRI_CATALOG_FILE = REPO / "config" / "gri_catalog.json"
ARTIFACT = "resolved_graph.json"

VN_NAME = "CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT"
EN_NAME = "An Phat Green Environment and Plastic Joint Stock Company"

_skips: list = []
_cache: dict = {}


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def have_corpus() -> bool:
    return VALIDATED_FILE.exists() and GRAPHS_DIR.is_dir()


def load_schema() -> dict:
    if "schema" not in _cache:
        _cache["schema"] = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return _cache["schema"]


def _quiet():
    root = logging.getLogger()
    prev = root.level
    root.setLevel(logging.ERROR)
    return prev


def _unquiet(prev) -> None:
    logging.getLogger().setLevel(prev)


def run_block(out_dir: pathlib.Path, **kw) -> dict:
    """The new tree's single entry point."""
    schema = load_schema()
    stats = build_resolved.run_block(
        input_path=VALIDATED_FILE, out_dir=out_dir, schema=schema,
        graphs_dir=GRAPHS_DIR, registry_path=ISSUER_REGISTRY,
        standards_registry_path=STANDARDS_REGISTRY,
        defs=json.loads(DEFS_FILE.read_text(encoding="utf-8")),
        crosswalk=json.loads(CROSSWALK_FILE.read_text(encoding="utf-8")) if CROSSWALK_FILE.exists() else {},
        catalog=build_resolved.indicators.load_gri_catalog(GRI_CATALOG_FILE),
        no_llm=True, **kw,
    )
    return stats


# --------------------------------------------------------------------------- #
# 1. The block produces a complete, correctly-assembled graph on the real corpus.
# --------------------------------------------------------------------------- #
def test_block_produces_a_complete_resolved_graph_on_the_real_corpus():
    if not have_corpus():
        return _skip("block real corpus", "graph_output/{validated,graphs}/ not present")
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t2:
            block_out = pathlib.Path(t2)
            run_block(block_out)
            got = json.loads((block_out / ARTIFACT).read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert len(got["nodes"]) > 1000, f"only {len(got['nodes'])} nodes — the corpus was not really read"

    axis_edges = sum(1 for e in got["edges"]
                     if e.get("predicate") in ("partOf", "measuredUnder", "equivalentTo", "alignsWithIndicator"))
    stamped = sum(1 for n in got["nodes"] if (n.get("properties") or {}).get("source_doc"))
    assert axis_edges > 0, "05c contributed nothing — the block is not running the indicator stage"
    assert stamped > 0, "05b contributed nothing — the block is not running the provenance stage"
    print(f"     ({len(got['nodes'])} nodes, {len(got['edges'])} edges, "
          f"{stamped} provenance-stamped, {axis_edges} axis edges)")


# --------------------------------------------------------------------------- #
# 2. The design property being ADDED: one write, no intermediate state.
# --------------------------------------------------------------------------- #
def _record_writes():
    calls = []
    real = pathlib.Path.write_text

    def spy(self, data, *a, **kw):
        calls.append(pathlib.Path(self).name)
        return real(self, data, *a, **kw)

    pathlib.Path.write_text = spy
    return calls, real


def test_block_writes_the_artifact_exactly_once():
    if not have_corpus():
        return _skip("single write", "graph_output/{validated,graphs}/ not present")
    prev = _quiet()
    calls, real = _record_writes()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_block(pathlib.Path(tmp))
    finally:
        pathlib.Path.write_text = real
        _unquiet(prev)

    n = calls.count(ARTIFACT)
    assert n == 1, f"the block wrote {ARTIFACT} {n} time(s); the whole point is exactly 1"
    print(f"     (writes: {calls})")


# --------------------------------------------------------------------------- #
# 3. The paid-result cache (Stage C only) — the thing the block must NOT swallow.
# --------------------------------------------------------------------------- #
class _FakeEmbedding:
    def __init__(self, values):
        self.values = values


class _FakeEmbedResponse:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class _FakeGenResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, calls_seen):
        self._calls_seen = calls_seen

    def embed_content(self, model, contents, config):
        self._calls_seen.append(("embed", model, tuple(contents)))
        dim = config.output_dimensionality
        vec = [1.0] + [0.0] * (dim - 1)
        return _FakeEmbedResponse([_FakeEmbedding(list(vec)) for _ in contents])

    def generate_content(self, model, contents, config):
        self._calls_seen.append(("generate", model, contents))
        same = zlib.crc32(contents.encode("utf-8")) % 2 == 0
        return _FakeGenResponse(json.dumps({"same_entity": same}))


class _FakeClient:
    def __init__(self, api_key=None):
        self.calls_seen: list = []
        self.models = _FakeModels(self.calls_seen)


def _near_duplicate_triples():
    return [
        {"subject": {"class": "Organization",
                     "properties": {"name": VN_NAME, "valid_from": "2023", "valid_to": None, "is_current": True}},
         "predicate": "ownsFacility", "object": {"class": "Facility",
                     "properties": {"name": "Nhà máy An Phát", "valid_from": "2023", "valid_to": None, "is_current": True}},
         "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023"}},
        {"subject": {"class": "Organization",
                     "properties": {"name": EN_NAME, "valid_from": "2023", "valid_to": None, "is_current": True}},
         "predicate": "ownsFacility", "object": {"class": "Facility",
                     "properties": {"name": "An Phat Factory", "valid_from": "2023", "valid_to": None, "is_current": True}},
         "temporal_metadata": {"valid_from": "2023", "valid_to": None, "recorded_at": "2023"}},
    ]


def test_adjudication_cache_is_reused_and_the_rerun_is_free():
    """Run the block twice with a stub client: the second run must call generate_content
    ZERO times and produce the identical artifact — mirrors the 03 block's phase-2 arm."""
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            input_file = tmp / "triples.json"
            input_file.write_text(json.dumps(_near_duplicate_triples(), ensure_ascii=False), encoding="utf-8")
            out_dir = tmp / "resolved"
            cache = out_dir / "entity_adjudication_cache.json"
            missing_registry = tmp / "__no_such_registry__.json"
            schema = load_schema()

            client1 = _FakeClient()
            stats1 = build_resolved.run_block(
                input_path=input_file, out_dir=out_dir, schema=schema,
                graphs_dir=tmp / "no_graphs", registry_path=missing_registry,
                standards_registry_path=missing_registry,
                defs=[], crosswalk={}, catalog={},
                no_llm=False, client=client1,
                rate_limiter=new_entities.RateLimiter(max_calls_per_minute=1000),
                cache_path=cache,
            )
            first = json.loads((out_dir / ARTIFACT).read_text(encoding="utf-8"))
            generate_calls_1 = [c for c in client1.calls_seen if c[0] == "generate"]
            assert generate_calls_1, "first run never called Stage C — fixture no longer reaches it"
            assert cache.exists(), f"the block did not write the adjudication cache at {cache}"

            client2 = _FakeClient()
            stats2 = build_resolved.run_block(
                input_path=input_file, out_dir=out_dir, schema=schema,
                graphs_dir=tmp / "no_graphs", registry_path=missing_registry,
                standards_registry_path=missing_registry,
                defs=[], crosswalk={}, catalog={},
                no_llm=False, client=client2,
                rate_limiter=new_entities.RateLimiter(max_calls_per_minute=1000),
                cache_path=cache,
            )
            second = json.loads((out_dir / ARTIFACT).read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    generate_calls_2 = [c for c in client2.calls_seen if c[0] == "generate"]
    assert generate_calls_2 == [], f"the second run called Stage C again ({generate_calls_2}) — cache not used"
    assert first == second, "a cached re-run produced a different resolved_graph.json"
    print(f"     (run 1 called generate_content {len(generate_calls_1)}x, run 2 called it 0x)")


# --------------------------------------------------------------------------- #
# 4. 05d compatibility smoke-check: the block's output must still satisfy the
#    next (unchanged, optional) stage in the chain.
# --------------------------------------------------------------------------- #
def test_align_claims_runs_against_the_blocks_output_without_error():
    if not have_corpus():
        return _skip("05d smoke-check", "graph_output/{validated,graphs}/ not present")
    from esg_kg.resolve import align_claims

    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = pathlib.Path(tmp)
            run_block(out_dir)
            log = _LogCatcher()
            align_claims.logger.addHandler(log)
            # _quiet() raised the ROOT level to ERROR, which also raises the effective
            # level align_claims.logger inherits — override it locally so its INFO
            # messages still reach our handler.
            align_claims.logger.setLevel(logging.INFO)
            try:
                args = align_claims.argparse.Namespace(
                    input=out_dir / ARTIFACT, defs=DEFS_FILE, schema=SCHEMA_FILE,
                    dry_run=True, max_llm_pairs=0, openai_model="gpt-4o-mini", rate_limit=10,
                    stats_out=out_dir / "indicator_align_llm_stats.json",
                )
                align_claims.run(args)  # must not raise on the block's output shape
            finally:
                align_claims.logger.removeHandler(log)
                align_claims.logger.setLevel(logging.NOTSET)
    finally:
        _unquiet(prev)

    candidate_lines = [m for m in log.messages if "unaligned" in m]
    assert candidate_lines, "align_claims never got far enough to report candidates"
    print(f"     (05d --dry-run against the block's output: {candidate_lines[0]})")


class _LogCatcher(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list = []

    def emit(self, record):
        self.messages.append(record.getMessage())


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
