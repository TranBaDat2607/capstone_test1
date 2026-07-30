"""console — stdout setup shared by every stage that prints a report.

Extracted from ``src/step00_graph_quality_report.py``, where commit 03a1592 added
it inline inside the ``__main__`` block. It lives in ``core/`` rather than in that
one stage because it is not step00's concern: step09's claim ledger is Vietnamese
too (as step10's evaluation report was, before that stage was removed from the
project outright on 2026-07-28 — DESIGN.md §4.3), and every stage still to be
migrated will want the same two lines.

The problem is Windows-only, and it is the *terminal echo*, not the files. Both
artifacts are written with an explicit ``encoding="utf-8"``, so they were never at
risk; the last line of ``main()`` then ``print``s the rendered Markdown, and a
Windows console defaults to the ANSI code page (cp1252 on this repo's host).

Measured on the real report, the characters that cp1252 cannot encode are ``→``
and ``≥`` — typography from step00's own section headings, not Vietnamese. (Names
pulled from the graph add diacritics on top whenever a section lists them, e.g.
an uncovered standards-registry mention.) So the failure mode is a
``UnicodeEncodeError`` that kills the run *after* the JSON and Markdown already
landed on disk: the work is done, only the echo fails, which makes the crash pure
noise. That asymmetry is why the exception below is swallowed.

Three deliberate choices, each pinned by a test in ``test/test_console_utf8.py``:

* **Gated on win32.** POSIX streams are already utf-8, and reconfiguring a stream
  nobody asked us to touch is a side effect rather than a fix.
* **Failures are swallowed.** ``reconfigure`` does not exist before Python 3.7 or
  on wrapped/redirected streams, and can raise on a detached buffer. Losing the
  terminal echo is acceptable; crashing a report that already landed on disk is
  not.
* **Never called at import time.** Stages call it at the top of ``main()`` — the
  one path shared by all three documented invocations: ``python
  src/stepNN_*.py``, ``python src/run.py <stage>`` (which calls
  ``mod.main()``), and ``python -m esg_kg.<pkg>.<stage>``. Putting it in a
  ``__main__`` block instead is what let the two trees drift in the first place,
  since ``run.py`` never executes one.

The body is duplicated verbatim in ``src/step00_graph_quality_report.py`` while
the refactor is in flight (Model A — the old tree must keep running and cannot
import from here). ``test_console_utf8.py`` is the arm that keeps the two copies
equal; it retires when the ``src/`` twin is deleted (DESIGN.md §5.3, §6.1).
"""

import sys


def ensure_utf8_stdout() -> None:
    """Let ``sys.stdout`` carry non-ASCII on a Windows console. No-op elsewhere.

    Verified end-to-end: ``PYTHONIOENCODING=cp1252 python src/run.py
    quality`` raises ``UnicodeEncodeError`` on ``→`` without this, and completes
    with it.
    """
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001 - losing the echo beats crashing
            pass
