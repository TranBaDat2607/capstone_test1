#!/usr/bin/env python3
"""Single entry point for the `esg_kg` stages — run from the REPO ROOT.

    python src_module/run.py --list                       # every stage + migration status
    python src_module/run.py quality --label baseline     # run one stage
    python src_module/run.py 00 --label baseline          # ...by its old step id
    python src_module/run.py quality -- --help            # stage's own --help

Why this file exists at all. The `src/` scripts are standalone files that work
because Python puts the script's own directory on `sys.path`; `esg_kg` is a real
package one level down in `src_module/`, so `python -m esg_kg.report.quality`
only resolves with `src_module/` on the path. The three ways to get it there are
an editable install (a build step teammates on a bare clone would have to run),
an exported PYTHONPATH (per-shell, easy to forget), or this: ONE file that adds
the directory and dispatches. It keeps the repo-root convention that every other
command in CLAUDE.md follows, and needs no install.

`python -m esg_kg.report.quality` from inside `src_module/` remains equally
valid — this dispatcher adds no behaviour, it only fixes the path. Stage output
locations do not depend on the working directory either way: they are anchored
on the marker-based REPO_ROOT in `esg_kg.core.paths`.

The stage table is not duplicated here. It is read from `esg_kg/pipeline.py`,
which is what makes that file load-bearing rather than documentation: the run
order the `stepNN_` prefixes used to encode now has exactly one home, and
`--list` reports the migration honestly by asking the import system which
modules actually exist.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from esg_kg.pipeline import BLOCKS, STAGES  # noqa: E402


def short_name(module) -> str:
    """`esg_kg.report.quality` -> `quality` (unique across STAGES).

    A not-ported stage (module=None) has no new name; it is only ever addressed by its
    old step id or filename, so `-` is a label, not an identifier.
    """
    return module.rsplit(".", 1)[-1] if module else "-"


def is_migrated(module) -> bool:
    if module is None:  # deliberately not ported — never "pending"
        return False
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        # a parent package (esg_kg.load, ...) not created yet
        return False


def resolve(token: str):
    """Accept the short name, the old step id ('03b'), or the old filename."""
    t = token.lower()
    for order, old, module, note in STAGES:
        keys = {order.lower(), old.lower(), f"step{order}".lower()}
        if module:  # a not-ported stage has no module path or short name to match on
            keys |= {short_name(module).lower(), module.lower()}
        if t in keys:
            return order, old, module, note
    return None


def all_members_ready(members) -> bool:
    """A block is only runnable once every stage it is built from has been migrated —
    otherwise it would quietly run a subset of the work and still look complete."""
    by_id = {order: module for order, _, module, _ in STAGES}
    return all(by_id.get(m) and is_migrated(by_id[m]) for m in members)


def resolve_block(token: str):
    """A block is addressed only by its name — it has no step id and no `src/` file."""
    t = token.lower()
    for name, module, members, note in BLOCKS:
        if t in {name.lower(), module.lower()}:
            return name, module, members, note
    return None


def print_list() -> None:
    # Not-ported stages are excluded from the denominator: counting them would make the
    # migration permanently unfinishable, since they are never coming.
    portable = [s for s in STAGES if s[2] is not None]
    done = sum(1 for _, _, m, _ in portable if is_migrated(m))
    skipped = len(STAGES) - len(portable)
    tail = f"  ({skipped} stage(s) deliberately not ported)" if skipped else ""
    print(f"esg_kg stages — {done}/{len(portable)} migrated from src/{tail}\n")
    print(f"  {'':2} {'step':4} {'name':20} {'module':38} status")
    print("  " + "-" * 84)
    for order, old, module, note in STAGES:
        if module is None:
            print(f"  {'--':2} {order:4} {short_name(module):20} {'(not ported)':38} "
                  f"src/{old}.py only")
            continue
        ok = is_migrated(module)
        mark = "OK " if ok else "   "
        status = "ready" if ok else f"still src/{old}.py"
        print(f"  {mark} {order:4} {short_name(module):20} {module:38} {status}")
    print("\n  ready   -> python src_module/run.py <name> [args]")
    print("  src/    -> python src/<file>.py [args]   (not migrated yet)")
    if skipped:
        print("  --      -> python src/<file>.py [args]   (not ported BY DECISION — see note)")
    if BLOCKS:
        # Blocks are listed apart from the stages on purpose: they have no `src/` file
        # and no migration status, so putting them in the table above would invite the
        # reading that some stage is now "done twice".
        print("\nBlocks — several stages as ONE unit, artifact written once (DESIGN.md §5.7):")
        for name, module, members, _note in BLOCKS:
            mark = "OK " if all_members_ready(members) else "   "
            print(f"  {mark} {name:20} {module:38} = {' -> '.join(members)}")
        print("\n  block   -> python src_module/run.py <block name> [args]")

    print("\nNotes:")
    for order, _, module, note in STAGES:
        print(f"  {order:4} {note}")
    for name, _, _, note in BLOCKS:
        print(f"  {name:4} {note}")


def main(argv: list) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__.strip())
        print("\nRun `--list` to see the stages.")
        return 0
    if argv[0] in {"-l", "--list", "list"}:
        print_list()
        return 0

    # Blocks are checked first: a block name can never collide with a stage name
    # (test_pipeline_table asserts it), so the order is about clarity, not precedence.
    block = resolve_block(argv[0])
    if block is not None:
        name, module, members, note = block
        if not all_members_ready(members):
            print(f"block {name} needs stages {', '.join(members)}, and not all are "
                  f"migrated yet", file=sys.stderr)
            return 2
        return _call(module, name, argv[1:])

    hit = resolve(argv[0])
    if hit is None:
        print(f"unknown stage: {argv[0]!r}", file=sys.stderr)
        print("run `python src_module/run.py --list` for the stage names", file=sys.stderr)
        return 2

    order, old, module, note = hit
    if module is None:
        print(f"stage {order} is not part of esg_kg by decision — {note}", file=sys.stderr)
        print(f"    python src/{old}.py {' '.join(argv[1:])}".rstrip(), file=sys.stderr)
        return 2
    if not is_migrated(module):
        print(f"stage {order} has not been migrated yet — it still runs from the old tree:",
              file=sys.stderr)
        print(f"    python src/{old}.py {' '.join(argv[1:])}".rstrip(), file=sys.stderr)
        return 2

    return _call(module, short_name(module), argv[1:])


def _call(module: str, label: str, rest: list) -> int:
    """Import a stage/block module and hand it the remaining argv."""
    if rest and rest[0] == "--":  # explicit separator, so `-- --help` reaches the stage
        rest = rest[1:]
    mod = importlib.import_module(module)
    if not hasattr(mod, "main"):
        print(f"{module} has no main() to call", file=sys.stderr)
        return 2
    # the stage parses sys.argv itself, exactly as it did as a src/ script
    sys.argv = [f"run.py {label}"] + rest
    mod.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
