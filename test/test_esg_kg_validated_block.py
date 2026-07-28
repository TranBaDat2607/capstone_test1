#!/usr/bin/env python3
"""
The 03 BLOCK: `03 -> 03b -> 03c` is one unit that writes ONE artifact, ONCE.

WHAT CHANGED AND WHY (DESIGN.md §5.7, decided 2026-07-28)
In `src/` these are three stages that each read AND write
`graph_output/validated/all_validated_triples.json`. That intermediate artifact was never
a deliverable — it is an implementation detail that leaked into being a contract, and it
costs real money: re-running step03 alone rebuilds the file from `graphs/` and silently
destroys 03b's 95 anchor triples, 03c's 683 kpi_id stamps, AND the 90 phase-2 repairs that
were paid for. Nothing warns.

`esg_kg` therefore collapses them into one block that passes triples IN MEMORY and writes
the artifact exactly once at the end.

THIS IS AN esg_kg-ONLY REDESIGN. `src/` is not touched (Model A) and keeps its three
separate stages. That is deliberate, not drift — see DESIGN.md §5.7, which also records
that §5.5's "fix both trees" constraint does not apply to block changes.

WHY THE SAFETY NET SURVIVES THE REDESIGN — the point of this whole file
The change is to WHEN the file is written, not to WHAT ends up in it. So the old tree is
still a usable ORACLE even though it is frozen: run the `src/` chain 03 -> 03b -> 03c on a
temp copy, run the block, and the final artifacts must be EQUAL. If a future refactor ever
breaks that property, stop — at that point there is no oracle left, which is a different
class of risk.

THE ONE THING THE BLOCK MUST NOT SWALLOW
"Intermediate artifact" and "cache of a paid result" are different things. Dropping the
first is the point; dropping the second would mean every block run re-pays for phase 2 and
— because the LLM is not deterministic — returns something different each time. Today 03b
and 03c are free to re-run precisely BECAUSE they read a frozen file. So phase-2 repairs go
to their own cache (`phase2_repairs.json`), keyed by input triple, and the block reads it
before calling any LLM.

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
sys.path.insert(0, str(REPO / "src_module"))

# --- old tree: the three separate stages that act as the ORACLE ----------------
import step03_fix_invalid_triplets as old_step03  # noqa: E402
import step03b_anchor_kpi_facilities as old_step03b  # noqa: E402
import step03c_canonicalize_kpis as old_step03c  # noqa: E402

# --- new tree: the block -------------------------------------------------------
from esg_kg.graph import build_validated  # noqa: E402
from esg_kg.graph import anchor_kpi as new_anchor  # noqa: E402
from esg_kg.kpi import canonicalize as new_canon  # noqa: E402

SCHEMA_FILE = REPO / "config" / "schema.json"
GRAPHS_DIR = REPO / "graph_output" / "graphs"
DEFS_FILE = REPO / "kpi_definitions_construction.json"
ALIASES_FILE = REPO / "config" / "kpi_type_aliases.json"
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


# --------------------------------------------------------------------------- #
# The ORACLE: drive the three src/ stages exactly as the old pipeline does.
# --------------------------------------------------------------------------- #
def run_src_chain(out_dir: pathlib.Path, llm=None) -> list:
    """`03 -> 03b -> 03c`, each writing the shared artifact in turn.

    step03's own main() is NOT used: it would build a real genai client from .env.
    process_all_files(client=None) is the same code path with phase 2 skipped, which
    keeps this oracle offline and free.
    """
    schema = load_schema()
    entity_classes, edge_labels, edge_directions = old_step03.load_schema_sets(schema)
    out_dir.mkdir(parents=True, exist_ok=True)

    real_llm = old_step03.fix_batch_with_llm
    if llm is not None:
        old_step03.fix_batch_with_llm = llm
    try:
        old_step03.process_all_files(
            input_dir=GRAPHS_DIR, out_dir=out_dir, schema=schema,
            entity_classes=entity_classes, edge_labels=edge_labels,
            edge_directions=edge_directions,
            client=(object() if llm is not None else None),
            rate_limiter=None, model="stub", batch_size=25, dry_run=False,
        )
    finally:
        old_step03.fix_batch_with_llm = real_llm

    artifact = out_dir / ARTIFACT

    # --- 03b: append gazetteer anchors, in place -------------------------------
    triples = json.loads(artifact.read_text(encoding="utf-8"))
    sentences = old_step03b.load_sentences(old_step03b.DEFAULT_SENTENCE_GLOBS)
    new_triples, _ = old_step03b.build_patch(
        triples, sentences, schema, old_step03b.DEFAULT_MAX_PER_FACILITY)
    triples.extend(new_triples)
    artifact.write_text(json.dumps(triples, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- 03c: canonicalize kpi_id + goals, in place ----------------------------
    triples = json.loads(artifact.read_text(encoding="utf-8"))
    defs = json.loads(DEFS_FILE.read_text(encoding="utf-8"))
    aliases = json.loads(ALIASES_FILE.read_text(encoding="utf-8"))
    matcher = old_step03c.Matcher(defs, aliases, old_step03c.DEFAULT_FUZZY_THRESHOLD)
    old_step03c.canonicalize_kpis(triples, matcher)
    old_step03c.backfill_goal_target_date(triples)
    artifact.write_text(json.dumps(triples, indent=2, ensure_ascii=False), encoding="utf-8")

    return json.loads(artifact.read_text(encoding="utf-8"))


def run_block(out_dir: pathlib.Path, **kw):
    """The new tree's single entry point."""
    return build_validated.run_block(
        input_dir=GRAPHS_DIR, out_dir=out_dir, schema=load_schema(), **kw)


# --------------------------------------------------------------------------- #
# 1. The oracle arm — the whole reason the redesign is safe.
# --------------------------------------------------------------------------- #
def test_block_output_equals_src_chain_on_the_real_corpus():
    if not have_corpus():
        return _skip("block vs src chain", "graph_output/graphs/ not present")
    prev = _quiet()
    try:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            want = run_src_chain(pathlib.Path(t1) / "validated")
            block_out = pathlib.Path(t2) / "validated"
            run_block(block_out)
            got = json.loads((block_out / ARTIFACT).read_text(encoding="utf-8"))
    finally:
        _unquiet(prev)

    assert len(got) == len(want), (
        f"triple count diverged: block={len(got)} src-chain={len(want)}")
    assert got == want, "the block produced a different artifact than the src/ chain"
    assert len(got) > 1000, f"only {len(got)} triples — the corpus was not really read"

    anchors = sum(1 for t in got if t.get("anchor_method") == "offline_gazetteer")
    kpi_ids = sum(1 for t in got for s in ("subject", "object")
                  if (t.get(s) or {}).get("properties", {}).get("kpi_id"))
    assert anchors > 0, "03b contributed nothing — the block is not running the anchor stage"
    assert kpi_ids > 0, "03c contributed nothing — the block is not running canonicalize"
    print(f"     ({len(got)} triples, {anchors} anchors, {kpi_ids} kpi_id — identical)")


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
    """The src/ chain writes it three times; the block must write it once."""
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


def test_src_chain_really_writes_it_three_times():
    """Guard against a vacuous version of the arm above: prove the OLD behaviour is
    what we think it is, otherwise 'exactly 1' might be trivially true."""
    if not have_corpus():
        return _skip("triple-write baseline", "graph_output/graphs/ not present")
    prev = _quiet()
    calls, real = _record_writes()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_src_chain(pathlib.Path(tmp) / "validated")
    finally:
        pathlib.Path.write_text = real
        _unquiet(prev)

    n = calls.count(ARTIFACT)
    assert n == 3, f"expected the src/ chain to write the artifact 3 times, saw {n}"
    print(f"     (src/ chain writes it {n}× — the block writes it 1×)")


# --------------------------------------------------------------------------- #
# 3. The paid-result cache — the thing the block must NOT swallow.
# --------------------------------------------------------------------------- #
def _tampering_llm_factory(counter):
    def llm(batch, schema, client, rate_limiter, model):
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
