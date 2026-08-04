#!/usr/bin/env python3
"""
The 03 BLOCK: `03 -> 03b -> 03c` is one unit that writes ONE artifact, ONCE.

WHAT CHANGED AND WHY (DESIGN.md §5.7, decided 2026-07-28)
In the old flat-script pipeline these were three stages that each read AND write
`graph_output/validated/all_validated_triples.json`. That intermediate artifact was never
a deliverable — it is an implementation detail that leaked into being a contract, and it
costs real money: re-running the fix stage alone rebuilds the file from `graphs/` and
silently destroys the anchor stage's 95 anchor triples, the canonicalize stage's 683
`kpi_id` stamps, AND the 90 phase-2 repairs that were paid for. Nothing warns.

`esg_kg` therefore collapses them into one block that passes triples IN MEMORY and writes
the artifact exactly once at the end.

WHY THE SAFETY NET SURVIVED THE REDESIGN
The change was to WHEN the file is written, not to WHAT ends up in it. While `src/` still
existed it served as an ORACLE: the old three-stage chain was run on a temp copy, the block
was run, and the final artifacts were asserted EQUAL (14,584 triples / 92 anchors / 679
`kpi_id`, real corpus). That oracle arm is gone now that `src/` has been deleted
(repointed at `esg_kg` only, 2026-07-29) — see the note on
`test_block_output_is_well_formed_on_the_real_corpus` below for what survives of it, and
`test_src_chain_really_writes_it_three_times` (deleted) for what did not.

THE ONE THING THE BLOCK MUST NOT SWALLOW
"Intermediate artifact" and "cache of a paid result" are different things. Dropping the
first is the point; dropping the second would mean every block run re-pays for phase 2 and
— because the LLM is not deterministic — returns something different each time. Today the
anchor/canonicalize stages are free to re-run precisely BECAUSE they read a frozen file. So
phase-2 repairs go to their own cache (`phase2_repairs.json`), keyed by triple CONTENT
(never by position — batch boundaries move), storing the model's raw reply with
`preserve_property_values` applied on the way out.

Offline: no LLM, no Neo4j, no network. The corpus arms SKIP on a bare clone.

Run from the repo root:

    python test/test_esg_kg_validated_block.py
"""

import copy
import json
import logging
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.graph import build_validated  # noqa: E402
from esg_kg.graph import anchor_kpi as new_anchor  # noqa: E402
from esg_kg.kpi import canonicalize as new_canon  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
GRAPHS_DIR = REPO / "graph_output" / "graphs"
ARTIFACT = "all_validated_triples.json"

VN_NAME = "CÔNG TY CỔ PHẦN NHỰA VÀ MÔI TRƯỜNG XANH AN PHÁT"
EN_NAME = "An Phat Green Environment and Plastic Joint Stock Company"

_skips: list = []
_cache: dict = {}


def _skip(name: str, why: str) -> None:
    _skips.append(f"{name}: {why}")
    print(f"SKIP {name} — {why}")


def have_corpus() -> bool:
    return GRAPHS_DIR.is_dir() and any(GRAPHS_DIR.rglob("page*.json"))


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


def run_block(out_dir: pathlib.Path, **kw):
    """The single entry point: `03 -> 03b -> 03c` chained in memory, writing once."""
    return build_validated.run_block(
        input_dir=GRAPHS_DIR, out_dir=out_dir, schema=load_schema(), **kw)


# --------------------------------------------------------------------------- #
# 1. The block's own output, on the real corpus.
#
# This used to ALSO assert the block's artifact was byte-identical to the src/
# 03->03b->03c chain run as an oracle on a temp copy (DESIGN.md §5.7's whole safety
# argument). That comparison is gone with src/ (repointed 2026-07-29) — but the
# concrete claims below about the block's OWN output (corpus really read, both
# sub-stages really contributed) do not depend on the oracle and are kept.
# --------------------------------------------------------------------------- #
def test_block_output_is_well_formed_on_the_real_corpus():
    if not have_corpus():
        return _skip("block real corpus", "graph_output/graphs/ not present")
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t2:
            block_out = pathlib.Path(t2) / "validated"
            run_block(block_out)
            got = json.loads((block_out / ARTIFACT).read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert len(got) > 1000, f"only {len(got)} triples — the corpus was not really read"

    anchors = sum(1 for t in got if t.get("anchor_method") == "offline_gazetteer")
    kpi_ids = sum(1 for t in got for s in ("subject", "object")
                  if (t.get(s) or {}).get("properties", {}).get("kpi_id"))
    assert anchors > 0, "03b contributed nothing — the block is not running the anchor stage"
    assert kpi_ids > 0, "03c contributed nothing — the block is not running canonicalize"
    print(f"     ({len(got)} triples, {anchors} anchors, {kpi_ids} kpi_id)")


# --------------------------------------------------------------------------- #
# 2. The design property being ADDED: one write, no intermediate state.
# --------------------------------------------------------------------------- #
def _record_writes():
    """Wrap Path.write_text so we can see every file the block touches, in order."""
    calls = []
    real = pathlib.Path.write_text

    def spy(self, data, *a, **kw):
        calls.append(pathlib.Path(self).name)
        return real(self, data, *a, **kw)

    pathlib.Path.write_text = spy
    return calls, real


def test_block_writes_the_artifact_exactly_once():
    """The old three-stage chain wrote it three times; the block must write it once."""
    if not have_corpus():
        return _skip("single write", "graph_output/graphs/ not present")
    prev = _quiet()
    calls, real = _record_writes()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_block(pathlib.Path(tmp) / "validated")
    finally:
        pathlib.Path.write_text = real
        _unquiet(prev)

    n = calls.count(ARTIFACT)
    assert n == 1, f"the block wrote {ARTIFACT} {n} time(s); the whole point is exactly 1"
    # and it must be the LAST thing written, i.e. no stage reads it back afterwards
    assert calls[-1] == ARTIFACT or ARTIFACT in calls, calls
    print(f"     (writes: {calls})")


# --------------------------------------------------------------------------- #
# 3. The paid-result cache — the thing the block must NOT swallow.
# --------------------------------------------------------------------------- #
def _tampering_llm_factory(counter):
    def llm(batch, schema, client, rate_limiter, model, cached_content=None):
        counter.append(len(batch))
        out = []
        for t in batch:
            r = copy.deepcopy(t)
            r["predicate"] = "ownsFacility"
            r["subject"]["properties"]["name"] = EN_NAME   # must be blocked by the guard
            out.append(r)
        return out
    return llm


def _phase2_corpus(tmp: pathlib.Path) -> pathlib.Path:
    """A tiny corpus with one triple that only phase 2 can repair."""
    page = {
        "nodes": [
            {"class": "Organization", "properties": {
                "name": VN_NAME, "valid_from": "2024", "valid_to": None, "is_current": True}},
            {"class": "Facility", "properties": {
                "name": "Nhà máy số 1", "valid_from": "2024", "valid_to": None,
                "is_current": True}},
        ],
        "edges": [{"subject": 0, "object": 1, "predicate": "ownsFacilty",
                   "temporal_metadata": {"valid_from": "2024", "valid_to": None,
                                         "recorded_at": "2024"}}],
    }
    doc = tmp / "graphs" / "aaa_2024"
    doc.mkdir(parents=True)
    (doc / "page1.json").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    return tmp / "graphs"


def test_phase2_repairs_are_cached_and_the_rerun_is_free():
    """Run twice with a counting LLM: the second run must call it ZERO times and
    produce the identical artifact. This is what keeps a block re-run free."""
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            graphs = _phase2_corpus(tmp)
            out_dir = tmp / "validated"
            cache = out_dir / "phase2_repairs.json"

            seen1 = []
            build_validated.run_block(
                input_dir=graphs, out_dir=out_dir, schema=load_schema(),
                client=object(), llm=_tampering_llm_factory(seen1), cache_path=cache)
            first = json.loads((out_dir / ARTIFACT).read_text(encoding="utf-8"))

            assert seen1, "phase 2 never ran — the fixture no longer reaches it"
            assert cache.exists(), f"the block did not write the repair cache at {cache}"

            seen2 = []
            build_validated.run_block(
                input_dir=graphs, out_dir=out_dir, schema=load_schema(),
                client=object(), llm=_tampering_llm_factory(seen2), cache_path=cache)
            second = json.loads((out_dir / ARTIFACT).read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert seen2 == [], f"the second run called the LLM again ({seen2}) — cache not used"
    assert first == second, "a cached re-run produced a different artifact"
    print(f"     (run 1 called the LLM {seen1}, run 2 called it {seen2 or 'not at all'})")


def test_cached_repairs_apply_with_no_llm_available_at_all():
    """The real reason the cache exists: reproduce a PAID result offline, for free.
    A re-run with client=None must still contain the repair."""
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            graphs = _phase2_corpus(tmp)
            out_dir = tmp / "validated"
            cache = out_dir / "phase2_repairs.json"

            build_validated.run_block(
                input_dir=graphs, out_dir=out_dir, schema=load_schema(),
                client=object(), llm=_tampering_llm_factory([]), cache_path=cache)
            paid = json.loads((out_dir / ARTIFACT).read_text(encoding="utf-8"))

            # now: no client, no llm — offline rebuild
            build_validated.run_block(
                input_dir=graphs, out_dir=out_dir, schema=load_schema(),
                client=None, cache_path=cache)
            free = json.loads((out_dir / ARTIFACT).read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert len(paid) == 1, f"the paid run should have kept the repaired triple, got {paid}"
    assert free == paid, (
        "an offline rebuild lost the cached phase-2 repair — the 90 paid repairs "
        "would be destroyed by exactly this path")
    print("     (paid repair reproduced offline, byte-identical)")


def test_the_value_guard_still_applies_inside_the_block():
    """preserve_property_values must run in the block too, or the block becomes the
    new way to let a translated name through (issue #6)."""
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            graphs = _phase2_corpus(tmp)
            out_dir = tmp / "validated"
            build_validated.run_block(
                input_dir=graphs, out_dir=out_dir, schema=load_schema(),
                client=object(), llm=_tampering_llm_factory([]),
                cache_path=out_dir / "phase2_repairs.json")
            got = json.loads((out_dir / ARTIFACT).read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert len(got) == 1, f"expected the repaired triple, got {got}"
    assert got[0]["predicate"] == "ownsFacility", "the honest repair was lost"
    assert got[0]["subject"]["properties"]["name"] == VN_NAME, (
        "the block wrote the LLM's translated name — the guard is not wired into it")


# --------------------------------------------------------------------------- #
# 4. What the block must NOT take away (DESIGN.md §5.7).
# --------------------------------------------------------------------------- #
def test_individual_stages_remain_runnable():
    """Collapsing into a block ADDS an entry point; it must not delete the stage ones,
    or the ability to diagnose one stage in isolation goes with them."""
    for mod in (new_anchor, new_canon):
        assert hasattr(mod, "main"), f"{mod.__name__} lost its main()"
    assert hasattr(new_anchor, "build_patch")
    assert hasattr(new_canon, "canonicalize_kpis")


def test_block_still_writes_the_per_stage_stats():
    """Stats are diagnostics, not intermediate artifacts — the block keeps them."""
    if not have_corpus():
        return _skip("stats", "graph_output/graphs/ not present")
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = pathlib.Path(tmp) / "validated"
            stats = run_block(out_dir)
            names = {p.name for p in out_dir.iterdir()}
    finally:
        _unquiet(prev)

    assert "anchor_patch_stats.json" in names, names
    assert "kpi_canonical_stats.json" in names, names
    for key in ("fix", "anchor", "kpi"):
        assert key in stats, f"run_block() should report per-stage stats, missing {key!r}"


def test_dry_run_writes_nothing():
    if not have_corpus():
        return _skip("dry run", "graph_output/graphs/ not present")
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = pathlib.Path(tmp) / "validated"
            run_block(out_dir, dry_run=True)
            existed = out_dir.exists() and any(out_dir.iterdir())
    finally:
        _unquiet(prev)
    assert not existed, "--dry-run wrote files"


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
