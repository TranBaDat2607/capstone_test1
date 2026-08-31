"""Single source of truth for filesystem paths across the pipeline.

Replaces the per-file ``REPO_ROOT = Path(__file__).resolve().parents[1]`` idiom
that every ``src/step*.py`` repeats. The root is located by a MARKER (a directory
that has both ``config/`` and ``.git``) rather than by counting parents, so this
module keeps working no matter how deep inside the package it is imported from.

Owns only the SHARED roots and the file constants many stages reference
identically (``SCHEMA_PATH`` alone was copy-pasted in 8 stage files).
Stage-specific defaults stay in their stage module, built from these roots, e.g.:

    from esg_kg.core.paths import GRAPH_OUTPUT_DIR
    DEFAULT_OUT_DIR = GRAPH_OUTPUT_DIR / "validated"
"""

from __future__ import annotations

from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    """Walk up from *start* to the first ancestor that has both ``config/`` and
    ``.git`` — the repo root. Requiring BOTH avoids latching onto a nested repo
    such as the read-only ``EmeraldMind/`` reference (which has its own ``.git``
    but no top-level ``config/``).
    """
    for candidate in (start, *start.parents):
        if (candidate / "config").is_dir() and (candidate / ".git").exists():
            return candidate
    raise RuntimeError(
        f"repo root not found above {start}: no ancestor has both config/ and .git/. "
        "Set ESG_KG_REPO_ROOT to override."
    )


def _resolve_repo_root() -> Path:
    """Repo root, with an ``ESG_KG_REPO_ROOT`` env override as an escape hatch
    (useful for tests or unusual checkouts). Validated the same way either way.
    """
    import os

    override = os.environ.get("ESG_KG_REPO_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if not ((root / "config").is_dir() and (root / ".git").exists()):
            raise RuntimeError(
                f"ESG_KG_REPO_ROOT={root} is not a repo root (needs config/ and .git/)."
            )
        return root
    return _find_repo_root(Path(__file__).resolve())


REPO_ROOT: Path = _resolve_repo_root()

CONFIG_DIR: Path = REPO_ROOT / "config"
DATA_DIR: Path = REPO_ROOT / "data"
KPI_OUTPUT_DIR: Path = REPO_ROOT / "kpi_output"
GRAPH_OUTPUT_DIR: Path = REPO_ROOT / "graph_output"

GRAPHS_DIR: Path = GRAPH_OUTPUT_DIR / "graphs"
VALIDATED_DIR: Path = GRAPH_OUTPUT_DIR / "validated"
RESOLVED_DIR: Path = GRAPH_OUTPUT_DIR / "resolved"
CROSSCHECK_DIR: Path = GRAPH_OUTPUT_DIR / "crosscheck"
QUALITY_DIR: Path = GRAPH_OUTPUT_DIR / "quality"
EVALUATION_DIR: Path = GRAPH_OUTPUT_DIR / "evaluation"

SCHEMA_PATH: Path = CONFIG_DIR / "schema.json"
KPI_DEFS_PATH: Path = REPO_ROOT / "kpi_definitions_construction.json"
DATA_VERSION_FILE: Path = REPO_ROOT / "data_version.json"
ENV_FILE: Path = REPO_ROOT / ".env"
ENV_EXAMPLE_FILE: Path = REPO_ROOT / ".env.example"


def load_env(*, override: bool = False) -> None:
    """Load ``.env`` from the repo root — the single replacement for the
    ``load_dotenv(REPO_ROOT / ".env")`` line duplicated in ~7 stage files.

    Degrades gracefully: if ``python-dotenv`` is not installed, or ``.env`` is
    absent, it is a no-op (real secrets may come from the ambient environment).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=override)


__all__ = [
    "REPO_ROOT",
    "CONFIG_DIR",
    "DATA_DIR",
    "KPI_OUTPUT_DIR",
    "GRAPH_OUTPUT_DIR",
    "GRAPHS_DIR",
    "VALIDATED_DIR",
    "RESOLVED_DIR",
    "CROSSCHECK_DIR",
    "QUALITY_DIR",
    "EVALUATION_DIR",
    "SCHEMA_PATH",
    "KPI_DEFS_PATH",
    "DATA_VERSION_FILE",
    "ENV_FILE",
    "ENV_EXAMPLE_FILE",
    "load_env",
]
