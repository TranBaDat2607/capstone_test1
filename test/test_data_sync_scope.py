#!/usr/bin/env python3
"""`data_sync.py pull` must write ONLY the three synced folders.

`cmd_push` scopes its upload with `allow_patterns=ALLOW_PATTERNS`; `cmd_pull` called
`snapshot_download` without it, so it downloaded the ENTIRE dataset repo into
REPO_ROOT — including the file at the dataset's own root. The HF dataset repo carries
a `.gitattributes` (the Hub's LFS template), and the code repo tracks a file at that
same path, so every teammate's pull silently modified a tracked Git file.

That is not hypothetical and not harmless. It is where the 75-line `.gitattributes`
committed in 03a1592 came from: nobody wrote it, a previous pull dragged it in from
the Hub and it got committed, which is why this code repo now routes `*.png/jpg/zip/
bin/parquet` through Git LFS. A pull during this session added another line to it.

Blast radius today is one file — the dataset repo has 5,607 files of which exactly one
sits at the root — but the mechanism is unbounded: anything added to the dataset root
lands in the code repo.

Offline: `snapshot_download` is replaced with a recorder, so nothing touches the
network and nothing is written. Run from the repo root:

    python test/test_data_sync_scope.py
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import huggingface_hub  # noqa: E402

import data_sync  # noqa: E402


class Recorder:
    """Stands in for snapshot_download; records the call instead of making it."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return str(REPO)


def run_pull(**arg_overrides):
    """Call cmd_pull with the network replaced. Returns the recorded kwargs."""
    args = argparse.Namespace(latest=False, dry_run=False)
    for k, v in arg_overrides.items():
        setattr(args, k, v)
    rec = Recorder()
    real = huggingface_hub.snapshot_download
    huggingface_hub.snapshot_download = rec  # cmd_pull imports it inside the function
    try:
        rc = data_sync.cmd_pull(args)
    finally:
        huggingface_hub.snapshot_download = real
    return rc, rec.calls


def test_pull_scopes_the_download_to_the_synced_folders():
    rc, calls = run_pull()
    assert rc == 0, f"cmd_pull returned {rc}"
    assert len(calls) == 1, f"expected exactly one download, got {len(calls)}"
    got = calls[0].get("allow_patterns")
    assert got == data_sync.ALLOW_PATTERNS, (
        f"pull must scope itself the way push does.\n"
        f"  expected {data_sync.ALLOW_PATTERNS}\n  got      {got!r}")


def test_pull_cannot_reach_a_file_at_the_repo_root():
    """The property that actually protects .gitattributes: every pattern is confined
    to a folder, and a root-level path has no folder to be confined to."""
    _, calls = run_pull()
    patterns = calls[0].get("allow_patterns") or []
    assert patterns, "no allow_patterns at all — every repo-root file is in scope"
    for p in patterns:
        assert "/" in p, f"pattern {p!r} is not confined to a folder"
        folder = p.split("/", 1)[0]
        assert folder in data_sync.SYNCED_FOLDERS, (
            f"pattern {p!r} escapes the synced folders {data_sync.SYNCED_FOLDERS}")
    for root_file in (".gitattributes", "README.md", ".gitignore"):
        assert not any(root_file.startswith(p.split("/", 1)[0] + "/") for p in patterns), (
            f"{root_file} is still in scope")


def test_pull_honours_the_pin_unless_latest_is_asked_for():
    """The pin is what keeps data and checked-out code reproducible together."""
    _, calls = run_pull(latest=False)
    pinned = data_sync._read_version() or {}
    assert calls[0].get("revision") == pinned.get("revision"), (
        "the default pull must ask for the revision pinned in data_version.json")
    _, calls_latest = run_pull(latest=True)
    assert calls_latest[0].get("revision") is None, "--latest must not send a revision"


def test_dry_run_downloads_nothing():
    rc, calls = run_pull(dry_run=True)
    assert rc == 0 and calls == [], f"--dry-run still called snapshot_download: {calls}"


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
