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

from esg_kg.pipeline import STAGES  # noqa: E402


def short_name(module: str) -> str:
    """`esg_kg.report.quality` -> `quality` (unique across STAGES)."""
    return module.rsplit(".", 1)[-1]


def is_migrated(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        # a parent package (esg_kg.load, ...) not created yet
        return False


def resolve(token: str):
    """Accept the short name, the old step id ('03b'), or the old filename."""
    t = token.lower()
    for order, old, module, note in STAGES:
        if t in {short_name(module).lower(), order.lower(), old.lower(),
                 f"step{order}".lower(), module.lower()}:
            return order, old, module, note
    return None


def print_list() -> None:
    done = sum(1 for _, _, m, _ in STAGES if is_migrated(m))
    print(f"esg_kg stages — {done}/{len(STAGES)} migrated from src/\n")
    print(f"  {'':2} {'step':4} {'name':20} {'module':38} status")
    print("  " + "-" * 84)
    for order, old, module, note in STAGES:
        ok = is_migrated(module)
        mark = "OK " if ok else "   "
        status = "ready" if ok else f"still src/{old}.py"
        print(f"  {mark} {order:4} {short_name(module):20} {module:38} {status}")
    print("\n  ready   -> python src_module/run.py <name> [args]")
    print("  src/    -> python src/<file>.py [args]   (not migrated yet)")
    print("\nNotes:")
    for order, _, module, note in STAGES:
        print(f"  {order:4} {note}")


def main(argv: list) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__.strip())
        print("\nRun `--list` to see the stages.")
        return 0
    if argv[0] in {"-l", "--list", "list"}:
        print_list()
        return 0

    hit = resolve(argv[0])
    if hit is None:
        print(f"unknown stage: {argv[0]!r}", file=sys.stderr)
        print("run `python src_module/run.py --list` for the stage names", file=sys.stderr)
        return 2

    order, old, module, _ = hit
    if not is_migrated(module):
        print(f"stage {order} has not been migrated yet — it still runs from the old tree:",
              file=sys.stderr)
        print(f"    python src/{old}.py {' '.join(argv[1:])}".rstrip(), file=sys.stderr)
        return 2

    rest = argv[1:]
    if rest and rest[0] == "--":  # explicit separator, so `-- --help` reaches the stage
        rest = rest[1:]
    mod = importlib.import_module(module)
    if not hasattr(mod, "main"):
        print(f"{module} has no main() to call", file=sys.stderr)
        return 2
    # the stage parses sys.argv itself, exactly as it did as a src/ script
    sys.argv = [f"run.py {short_name(module)}"] + rest
    mod.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
