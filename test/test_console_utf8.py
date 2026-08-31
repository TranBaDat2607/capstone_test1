#!/usr/bin/env python3
"""`esg_kg` must set up a utf-8 stdout on win32 (DESIGN.md §5.3).

Why this file exists. Commit 03a1592 added a win32 ``sys.stdout.reconfigure(
encoding="utf-8")`` block to ``src/step00_graph_quality_report.py``'s ``__main__``
only. The migrated twin ``esg_kg/report/quality.py`` never got it and
``src/run.py`` does not touch encoding either — so on a Windows console
``python src/step00_...`` printed its report fine while ``python
src/run.py quality`` could still die with ``UnicodeEncodeError`` at
``print(render_markdown(report))``. The refactored tree was strictly worse than
the one it replaces, at the one stage that exists to be run before AND after
every change. Repointed at `esg_kg` only (2026-07-29) now that `src/` is gone;
the fix landed in both trees while both existed (DESIGN.md §5.3), and
`test_both_trees_record_identical_calls` — the cross-tree proof of that — was
retired along with the old tree it compared against.

What actually fails is the terminal echo, not the files: the artifact is
written with an explicit ``encoding="utf-8"``. Measured on the real report, the
characters cp1252 rejects are ``→`` and ``≥`` from step00's own headings — so the
crash lands *after* the work is on disk, which is why the helper swallows its own
failures.

``test_esg_kg_equivalence.py`` structurally could not catch the original bug: it
imports the module and compares constants / Q1-Q8 metrics / rendered Markdown,
and never executes a ``__main__`` block. This file closes that hole, and it is
also the behavioural coverage for ``esg_kg.core.console``.

Two things are asserted, because either alone would be a false green:

  1. **behaviour** — the platform gate, the reconfigure call, and the two
     failure modes the ``except Exception`` swallows on purpose;
  2. **wiring** — a helper that exists but nothing calls is just as broken as
     the drift it was meant to fix.

The call site is the top of ``main()``, NOT ``__main__``, deliberately: that is
the only place both documented invocations pass through — ``python
src/run.py quality`` (which calls ``mod.main()``) and ``python -m
esg_kg.report.quality`` — and it keeps ``run.py`` a pure ``sys.path`` fixer that
"adds no behaviour", as its own docstring promises. It must NOT run at import
time: reconfiguring the stream out from under every importer (this test
included) is a side effect no library should have.

Offline, no LLM/Neo4j/network. Run from the repo root:

    python test/test_console_utf8.py
"""

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

NEW_FILE = REPO / "src" / "esg_kg" / "report" / "quality.py"
CORE_FILE = REPO / "src" / "esg_kg" / "core" / "console.py"

HELPER = "ensure_utf8_stdout"


class RecordingStdout:
    """Stands in for a console stream, recording how it was reconfigured."""

    def __init__(self, encoding="cp1252", raises: Exception = None):
        self.encoding = encoding
        self.calls: list = []
        self._raises = raises

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises

    def write(self, _s):  # never used; present so a stray print cannot explode
        return 0

    def flush(self):
        pass


class LegacyStdout:
    """A stream with no ``reconfigure`` at all (a wrapped/redirected stream)."""

    encoding = "cp1252"

    def write(self, _s):
        return 0

    def flush(self):
        pass


def _run(fn, *, platform: str, stdout):
    """Call ``fn`` with ``sys.platform`` and ``sys.stdout`` swapped out.

    Restores both no matter what, or the harness would print its own PASS lines
    into the fake stream.
    """
    real_platform, real_stdout = sys.platform, sys.stdout
    try:
        sys.platform = platform
        sys.stdout = stdout
        fn()
    finally:
        sys.platform = real_platform
        sys.stdout = real_stdout
    return stdout


def _load_helper():
    """The `esg_kg.core.console` copy of the helper."""
    from esg_kg.core.console import ensure_utf8_stdout as new
    return new


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _calls_helper(node) -> bool:
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == HELPER
               for n in ast.walk(node))


def _main_of(path: Path):
    tree = _parse(path)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert fn is not None, f"{path.name} has no module-level main()"
    return tree, fn


def test_on_win32_stdout_is_reconfigured_to_utf8():
    """The whole point: a cp1252 console must be switched to utf-8."""
    fn = _load_helper()
    out = _run(fn, platform="win32", stdout=RecordingStdout())
    assert out.calls == [{"encoding": "utf-8"}], (
        f"expected one reconfigure(encoding='utf-8'), got {out.calls}")


def test_off_win32_stdout_is_left_alone():
    """The platform gate is deliberate — POSIX stdout is already utf-8, and
    reconfiguring a stream nobody asked us to touch is a side effect."""
    fn = _load_helper()
    for platform in ("linux", "darwin"):
        out = _run(fn, platform=platform, stdout=RecordingStdout())
        assert out.calls == [], f"reconfigured stdout on {platform}: {out.calls}"


def test_a_stream_without_reconfigure_is_survived():
    """Python <3.7 streams and wrapped/redirected ones have no reconfigure().
    Printing a report is not worth crashing over — this pins the swallow."""
    fn = _load_helper()
    _run(fn, platform="win32", stdout=LegacyStdout())  # must not raise
    print("     (no reconfigure attribute -> no crash)")


def test_a_reconfigure_that_raises_is_swallowed():
    """Same contract for a stream that has the method but rejects the call."""
    fn = _load_helper()
    out = _run(fn, platform="win32",
               stdout=RecordingStdout(raises=ValueError("detached buffer")))
    assert out.calls == [{"encoding": "utf-8"}], "never attempted"


def test_main_calls_the_helper():
    """The stage entrypoint must actually call it.

    Checked statically rather than by running ``main()``: that would rebuild the
    whole Q1-Q8 report (~44s of BFS) and need the git-ignored graph artifacts,
    while the thing under test is one call at the top of a function.
    """
    _, fn = _main_of(NEW_FILE)
    assert _calls_helper(fn), (
        f"{NEW_FILE.name}: main() never calls {HELPER}() — the helper exists but "
        f"nothing invokes it, so the Vietnamese report can still crash")


def test_the_helper_never_runs_at_import_time():
    """Reconfiguring the stream as an import side effect would hit every
    importer — this test file included."""
    for path in (NEW_FILE, CORE_FILE):
        if not path.exists():
            continue
        tree = _parse(path)
        top_level = [n for n in tree.body if isinstance(n, ast.Expr)]
        for node in top_level:
            assert not _calls_helper(node), (
                f"{path.name} calls {HELPER}() at module level; it belongs in main()")


def test_the_core_module_is_where_the_new_tree_keeps_it():
    """`esg_kg/report/quality.py` must import the helper from the shared kernel,
    not keep a third private copy — every later stage prints Vietnamese too."""
    _load_helper()
    assert CORE_FILE.exists(), f"expected the new-tree home at {CORE_FILE}"
    src = NEW_FILE.read_text(encoding="utf-8")
    assert "from esg_kg.core.console import" in src, (
        "quality.py should import ensure_utf8_stdout from esg_kg.core.console")
    assert f"def {HELPER}" not in src, (
        f"quality.py defines its own {HELPER} — that is a third copy, not a fix")


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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
