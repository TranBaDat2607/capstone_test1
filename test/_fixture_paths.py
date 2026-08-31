#!/usr/bin/env python3
"""Resolve a pipeline artifact to the real corpus if present, else a fixture.

Why this exists. ``graph_output/`` is git-ignored and distributed through a
**private** Hugging Face dataset repo. Someone with only a clone of this public
repository cannot obtain it, so every real-corpus assertion in the suite used to
skip — the suite printed "all pass" while roughly twenty checks had never run.
``test/fixtures/`` holds a small synthetic stand-in (see
``test/fixtures/build_fixtures.py``) so those checks execute anyway.

Three rules make this safe rather than a way to fake a green suite:

1. **The real artifact always wins.** A maintainer who has run ``datasync pull``
   sees exactly the behaviour they saw before; the fixture is a fallback, never
   an override. There is no env var to set, deliberately — an opt-in nobody
   outside the team would think to set would defeat the point.

2. **Every arm says which source it used.** Call ``tag()`` and print it, so
   ``grep '\\[fixture\\]'`` over a run tells you precisely how much of the suite
   was exercised against real data. A silent substitution would make CI-green
   mean less than it appears to, which is the failure this design is guarding
   against.

3. **Scale assertions refuse the fixture.** Three checks elsewhere assert real
   corpus *size* (``len(nodes) > 1000``, ``claims > 100``, ``candidates > 100``).
   A 22-node fixture cannot satisfy those truthfully, and weakening the
   thresholds to fit would convert a real check into a decorative one. Such arms
   call ``skip_if_fixture()`` and keep skipping with a distinct reason.

Offline: this module only touches the filesystem.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

FIXTURE_DIR = REPO / "test" / "fixtures"

_ARTIFACTS = {
    "validated": (
        REPO / "graph_output" / "validated" / "all_validated_triples.json",
        FIXTURE_DIR / "validated_triples.json",
    ),
    "resolved": (
        REPO / "graph_output" / "resolved" / "resolved_graph.json",
        FIXTURE_DIR / "resolved_graph.json",
    ),
}


def resolve_artifact(name: str):
    """Return ``(path, is_fixture)`` for ``name`` in {"validated", "resolved"}.

    Prefers the real artifact. Falls back to the committed fixture. If neither
    exists, returns the real path with ``is_fixture=False`` so the caller's
    existing ``.exists()`` gate skips exactly as it did before.
    """
    try:
        real, fixture = _ARTIFACTS[name]
    except KeyError:
        raise ValueError(
            f"unknown artifact {name!r}; expected one of {sorted(_ARTIFACTS)}") from None
    if real.exists():
        return real, False
    if fixture.exists():
        return fixture, True
    return real, False


def tag(is_fixture: bool) -> str:
    """Marker to print on a result line so the coverage source stays greppable."""
    return "[fixture]" if is_fixture else "[real]"


def skip_if_fixture(is_fixture: bool) -> str:
    """Reason string for an arm that genuinely needs real corpus scale, else ""."""
    if is_fixture:
        return ("real-scale arm — needs `datasync pull`, not a fixture "
                "(the synthetic graph is deliberately tiny)")
    return ""
