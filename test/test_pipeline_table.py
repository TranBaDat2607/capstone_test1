"""Contract test for the refactor's stage table (src_module/esg_kg/pipeline.py + run.py).

`pipeline.py` is load-bearing, not documentation: `run.py` reads it instead of keeping
its own copy, so `--list` reports migration progress by asking the import system. That
only stays true if the table itself stays true. This asserts the three ways it can rot:

  1. a row pointing at a `src/` file that does not exist (renamed/deleted stage),
  2. two rows colliding on the short name `run.py` dispatches by,
  3. a stage that will NEVER be ported being rendered as merely "not yet" — the lie
     that matters, because it silently keeps dead work on the migration queue.

Offline, no LLM/Neo4j/network. Run from the repo root:  python test/test_pipeline_table.py
"""

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"


def _load_run_py():
    """Import src_module/run.py by path — it is a script, not part of the package."""
    spec = importlib.util.spec_from_file_location("esg_kg_run", REPO_ROOT / "src_module" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run = _load_run_py()
STAGES = run.STAGES

# Stages deliberately NOT ported to esg_kg. A row here is a decision, not a backlog item;
# the reason belongs in the pipeline.py note and in DESIGN.md.
EXPECTED_NOT_PORTED = {"07b"}


def test_every_stage_points_at_a_real_src_file():
    missing = [(order, old) for order, old, _, _ in STAGES if not (SRC / f"{old}.py").exists()]
    assert not missing, f"STAGES rows whose src/ file does not exist: {missing}"


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
    assert f"/{portable} migrated" in header, (
        f"--list header should count only portable stages ({portable}), got: {header!r}")


def test_resolve_finds_a_not_ported_stage_by_its_old_id():
    """`run.py 07b` must still resolve, so the user gets the src/ command, not 'unknown stage'."""
    for order in EXPECTED_NOT_PORTED:
        hit = run.resolve(order)
        assert hit is not None, f"run.py can no longer resolve {order!r}"
        assert hit[2] is None, f"{order} resolved to a module path {hit[2]!r}, expected None"


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
