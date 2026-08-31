"""Contract test for the refactor's stage table (src/esg_kg/pipeline.py + run.py).

`pipeline.py` is load-bearing, not documentation: `run.py` reads it instead of keeping
its own copy, so `--list` reports migration progress by asking the import system. That
only stays true if the table itself stays true. This asserts the ways it can rot:

  1. a row's `old_step` label malformed or colliding with another row's (it is what
     `run.py <old_id>` still resolves by, even though `src/` itself is gone),
  2. two rows colliding on the short name `run.py` dispatches by,
  3. a stage that will NEVER be ported being rendered as merely "not yet" — the lie
     that matters, because it silently keeps dead work on the migration queue.

Offline, no LLM/Neo4j/network. Run from the repo root:  python test/test_pipeline_table.py
"""

import importlib.util
import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_py():
    """Import src/run.py by path — it is a script, not part of the package."""
    spec = importlib.util.spec_from_file_location("esg_kg_run", REPO_ROOT / "src" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run = _load_run_py()
STAGES = run.STAGES

EXPECTED_NOT_PORTED = set()


def test_every_old_step_label_is_well_formed_and_unique():
    """`old_step` is a historical label now (src/ is gone) — it still has to look like one
    (stepNN_name, matching the CLI id it's resolved by) and never collide."""
    labels = [old for _, old, _, _ in STAGES]
    assert len(labels) == len(set(labels)), f"duplicate old_step labels: {labels}"
    for order, old, _, _ in STAGES:
        assert re.match(r"^step\d{2}[a-z]?_[a-z0-9_]+$", old), f"{order}: malformed old_step {old!r}"


def test_short_names_are_unique():
    names = [run.short_name(m) for _, _, m, _ in STAGES if m]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"short names collide, so `run.py <name>` is ambiguous: {sorted(dupes)}"


def test_not_ported_stages_are_marked_and_explained():
    """A stage that will not be ported carries module=None (never a module path)."""
    marked = {order for order, _, module, _ in STAGES if module is None}
    assert marked == EXPECTED_NOT_PORTED, (
        f"stages marked not-ported = {sorted(marked)}, expected {sorted(EXPECTED_NOT_PORTED)}")
    for order, _, module, note in STAGES:
        if module is None:
            assert note and "not ported" in note.lower(), (
                f"stage {order} is not ported but its note does not say so: {note!r}")


def test_list_does_not_call_a_not_ported_stage_pending():
    out = io.StringIO()
    with redirect_stdout(out):
        run.print_list()
    text = out.getvalue()
    for order, old, module, _ in STAGES:
        if module is None:
            row = next(ln for ln in text.splitlines()
                       if ln.strip().startswith(order) or f" {order} " in ln[:12])
            assert f"still src/{old}" not in row, (
                f"stage {order} is never being ported, but --list shows it as pending:\n  {row}")


def test_list_denominator_excludes_not_ported_stages():
    portable = sum(1 for _, _, m, _ in STAGES if m is not None)
    out = io.StringIO()
    with redirect_stdout(out):
        run.print_list()
    header = out.getvalue().splitlines()[0]
    assert f"/{portable} ready" in header, (
        f"--list header should count only portable stages ({portable}), got: {header!r}")


def test_resolve_finds_a_not_ported_stage_by_its_old_id():
    """`run.py 07b` must still resolve, so the user gets the src/ command, not 'unknown stage'."""
    for order in EXPECTED_NOT_PORTED:
        hit = run.resolve(order)
        assert hit is not None, f"run.py can no longer resolve {order!r}"
        assert hit[2] is None, f"{order} resolved to a module path {hit[2]!r}, expected None"


def test_blocks_table_exists():
    assert hasattr(run, "BLOCKS"), "pipeline.py must expose BLOCKS for the §5.7 block design"


def test_every_block_names_real_stages():
    stage_ids = {order for order, _, _, _ in STAGES}
    for name, module, members, _note in run.BLOCKS:
        assert members, f"block {name!r} lists no member stages"
        for m in members:
            assert m in stage_ids, f"block {name!r} names {m!r}, which is not a stage id"


def test_every_block_module_is_importable():
    for name, module, _members, _note in run.BLOCKS:
        assert importlib.util.find_spec(module) is not None, (
            f"block {name!r} points at {module!r}, which does not import")


def test_block_names_do_not_collide_with_stage_names():
    """`run.py` dispatches blocks and stages through one namespace."""
    stage_names = {run.short_name(m) for _, _, m, _ in STAGES if m}
    stage_ids = {order.lower() for order, _, _, _ in STAGES}
    seen = set()
    for name, _module, _members, _note in run.BLOCKS:
        assert name not in stage_names, f"block {name!r} collides with a stage short name"
        assert name.lower() not in stage_ids, f"block {name!r} collides with a step id"
        assert name not in seen, f"duplicate block name {name!r}"
        seen.add(name)


def test_run_py_can_resolve_a_block():
    for name, module, _members, _note in run.BLOCKS:
        hit = run.resolve_block(name)
        assert hit is not None, f"run.py cannot resolve block {name!r}"
        assert hit[1] == module


def test_block_members_are_all_migrated_stages():
    """A block can only be built out of stages that already live in esg_kg — otherwise
    it would silently run a subset and still look complete."""
    by_id = {order: module for order, _, module, _ in STAGES}
    for name, _module, members, _note in run.BLOCKS:
        for m in members:
            module = by_id[m]
            assert module is not None, f"block {name!r} includes not-ported stage {m}"
            assert run.is_migrated(module), (
                f"block {name!r} includes {m}, which has not been migrated yet")


def test_list_shows_the_blocks():
    buf = io.StringIO()
    with redirect_stdout(buf):
        run.print_list()
    out = buf.getvalue()
    for name, _module, _members, _note in run.BLOCKS:
        assert name in out, f"--list never mentions block {name!r}"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}\n     {exc}")
        except Exception as exc:  # noqa: BLE001 - a broken test is a failure too
            failed += 1
            print(f"ERROR {t.__name__}\n     {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} test(s) passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
