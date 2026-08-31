#!/usr/bin/env python3
"""
Behaviour tests for `esg_kg.core.datasync` — a utility, not a pipeline stage
(`pipeline.py`'s own comment names this destination), so it carries no `STAGES`/
`BLOCKS` row and is not runnable via `run.py`; it stays a standalone script, exactly
like `src/data_sync.py` was (`python src/esg_kg/core/datasync.py push|pull|status`).

Was driven through both `src/data_sync.py` and `esg_kg.core.datasync` while both trees
existed, proving the verbatim port was byte-for-byte equivalent (DESIGN.md §5.3).
Repointed at `esg_kg` only (2026-07-29) now that `src/` is gone.

Offline: `huggingface_hub.snapshot_download`/`HfApi` are replaced with recorders —
nothing touches the network, the Hub, or the local filesystem outside
`REPO_ROOT / "data_version.json"` (real file, read but never written by these arms).

Run from the repo root:

    python test/test_esg_kg_datasync.py
"""

import argparse
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from esg_kg.core import datasync as ds  # noqa: E402

import huggingface_hub  # noqa: E402


def test_constants_are_the_documented_shape():
    assert ds.SYNCED_FOLDERS == ["data", "graph_output", "kpi_output"]
    assert ds.ALLOW_PATTERNS == ["data/**", "graph_output/**", "kpi_output/**"]
    assert ds.REPO_ROOT == REPO
    assert ds.VERSION_FILE == REPO / "data_version.json"
    for pat in (".env", "**/.env", "EmeraldMind/**", "neo4j_data/**"):
        assert pat in ds.IGNORE_PATTERNS, f"{pat!r} missing from IGNORE_PATTERNS"
    print(f"     (SYNCED_FOLDERS={ds.SYNCED_FOLDERS}, {len(ds.ALLOW_PATTERNS)} "
          f"allow pattern(s), {len(ds.IGNORE_PATTERNS)} ignore pattern(s))")


def test_helpers_run_clean_on_the_real_repo():
    commit = ds._git_commit()
    assert commit == "unknown" or len(commit) == 40, f"not a git sha: {commit!r}"
    version = ds._read_version()
    if version is not None:
        assert {"repo_id", "revision", "folders"} <= set(version), version
    for f in ds.SYNCED_FOLDERS:
        size = ds._folder_size_mb(REPO / f)
        assert size >= 0.0, f"{f}: negative size {size}"
    print(f"     (_git_commit={commit[:12]!r}, pinned revision: "
          f"{(version or {}).get('revision', '(none)')[:12]})")


class _DownloadRecorder:
    """Stands in for snapshot_download — records the call instead of making it."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return str(REPO)


def _run_pull(**arg_overrides):
    args = argparse.Namespace(latest=False, dry_run=False)
    for k, v in arg_overrides.items():
        setattr(args, k, v)
    rec = _DownloadRecorder()
    real = huggingface_hub.snapshot_download
    huggingface_hub.snapshot_download = rec  # cmd_pull imports it inside the function
    try:
        rc = ds.cmd_pull(args)
    finally:
        huggingface_hub.snapshot_download = real
    return rc, rec.calls


def test_cmd_pull_scopes_the_download_to_the_synced_folders():
    rc, calls = _run_pull()
    assert rc == 0, f"cmd_pull returned {rc}"
    assert len(calls) == 1, f"expected exactly one download call, got {len(calls)}"
    assert calls[0].get("allow_patterns") == ds.ALLOW_PATTERNS
    print(f"     (1 download call, allow_patterns={calls[0].get('allow_patterns')})")


def test_cmd_pull_dry_run_downloads_nothing():
    rc, calls = _run_pull(dry_run=True)
    assert rc == 0 and calls == [], f"--dry-run still called snapshot_download: {calls}"
    print("     (--dry-run: snapshot_download called zero times)")


def test_cmd_pull_latest_flag_omits_the_revision():
    rc, calls = _run_pull(latest=True)
    assert rc == 0
    assert calls[0].get("revision") is None, f"--latest should omit revision, got {calls[0].get('revision')!r}"
    print("     (--latest: `revision` omitted from the download call)")


def test_cmd_pull_honours_the_pin_unless_latest_is_asked_for():
    _, calls = _run_pull(latest=False)
    pinned = ds._read_version() or {}
    assert calls[0].get("revision") == pinned.get("revision"), (
        "the default pull must ask for the revision pinned in data_version.json")
    print("     (default pull requests the pinned revision)")


def test_cmd_status_returns_clean():
    rc = ds.cmd_status(argparse.Namespace())
    assert rc == 0
    print("     (cmd_status returns 0, no exception)")


def _run_push_dry_run(root=None, **arg_overrides):
    """Only the --dry-run path is safe to run for free: the real path writes
    data_version.json and hits the network. --dry-run exercises everything up to
    that point (repo-id resolution, folder presence/size logging) with no side effects.

    `root` temporarily replaces the module-level REPO_ROOT that cmd_push scans for
    SYNCED_FOLDERS, so the folder-presence branch is decided by the test rather than
    by whatever happens to be on the machine's disk.
    """
    args = argparse.Namespace(repo_id=None, private=True, dry_run=True)
    for k, v in arg_overrides.items():
        setattr(args, k, v)
    if root is None:
        return ds.cmd_push(args)
    previous = ds.REPO_ROOT
    ds.REPO_ROOT = root
    try:
        return ds.cmd_push(args)
    finally:
        ds.REPO_ROOT = previous


def test_cmd_push_dry_run_writes_nothing():
    """Both folder-presence branches, pinned explicitly.

    This arm used to call cmd_push with no control over REPO_ROOT and assert
    `rc == 0` unconditionally. That passes on a maintainer's machine (which has
    run `datasync pull`) and FAILS on a bare clone -- the exact state of every new
    contributor and every CI runner -- because cmd_push correctly returns 1 with
    "nothing to push" when none of the synced folders exist. The old assertion
    made an environment-dependent outcome look like a defect, so both branches are
    now asserted for what they are.
    """
    before = ds.VERSION_FILE.read_bytes() if ds.VERSION_FILE.exists() else None

    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "bare_clone"
        empty.mkdir()
        rc_empty = _run_push_dry_run(root=empty)
        assert rc_empty == 1, (
            "with none of the synced folders present, --dry-run push must report "
            f"'nothing to push' and return 1, got {rc_empty}")

        populated = Path(tmp) / "after_a_rebuild"
        (populated / "graph_output" / "resolved").mkdir(parents=True)
        (populated / "graph_output" / "resolved" / "resolved_graph.json").write_text(
            '{"nodes": [], "edges": []}', encoding="utf-8")
        rc_present = _run_push_dry_run(root=populated)
        assert rc_present == 0, (
            f"with a synced folder present, --dry-run push must return 0, got {rc_present}")

    after = ds.VERSION_FILE.read_bytes() if ds.VERSION_FILE.exists() else None
    assert after == before, "--dry-run push modified data_version.json"
    assert ds.REPO_ROOT == REPO, "REPO_ROOT was not restored after the patch"
    print("     (--dry-run push: 1 with no folders, 0 with one, data_version.json untouched)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
