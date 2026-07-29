#!/usr/bin/env python3
"""
Team data sync — distribute the generated pipeline data via a Hugging Face dataset repo.

Not a pipeline step (hence no `STAGES`/`BLOCKS` row in `pipeline.py`, and no `run.py`
dispatch): this is the transport layer that lets a teammate `git pull` the code and then
land the exact `data/` + `graph_output/` + `kpi_output/` snapshot that code was built
against, without re-running any of the expensive stages (the LLM extraction in
step01/02/03/07 costs money; the ViDeBERTa labeling needs a GPU; and the news crawl is
*not* reproducible — the web moves).

MOVED FROM ``src/data_sync.py`` (2026-07-29), the last file blocking `src/` deletion:
verbatim except this docstring and the run line below. It resolves `REPO_ROOT` locally
rather than importing it from `esg_kg.core.paths` — by design, so this tool still runs
on a fresh clone before any LLM/pipeline dependency is installed (that constraint is
older than the refactor and travels with the file unchanged). Nothing else in `esg_kg`
imports from it, and it imports nothing else in `esg_kg`.
`test/test_esg_kg_datasync.py` compares this against `src/data_sync.py` on the real
repo (constants, `_git_commit`/`_read_version`/`_folder_size_mb`, `cmd_pull` incl.
`--dry-run`/`--latest`, `cmd_status`, and `cmd_push --dry-run` — the only push path safe
to compare for free, since the real path writes `data_version.json` and hits the network).

Why not Git: these folders are ~342 MB of generated artifacts and one 71 MB PDF, which
Git handles badly (binary deltas bloat history forever, and GitHub hard-blocks >100 MB
files). They are git-ignored; the dataset repo carries them instead.

Why not "just a shared Drive folder": the failure mode that actually bites is data↔code
version drift — teammate pulls code at commit X while the shared folder sits at state Y,
and the errors that follow are baffling. So the pushed dataset revision is PINNED into
`data_version.json`, which IS tracked in Git. Checking out an old commit therefore
recovers the data that went with it — which is also what makes the thesis baseline vs
after-phase0 comparison reproducible.

Deliberately NOT distributed (none of this is about size):
  - `.env`          — secrets. Each member copies .env.example and uses their own
                      GEMINI_API_KEY (keeps quota/billing attributable per person).
  - `EmeraldMind/`  — read-only external reference with its own .git and secrets (CLAUDE.md).
  - `neo4j_data/`   — a live DB volume: corrupt if copied while running, and pinned to the
                      Neo4j image version. Rebuild it locally with step06 instead (one
                      command, no LLM), from the resolved_graph.json this script ships.

Auth: `hf auth login`, or set HF_TOKEN in .env / the environment.
A write token is needed only for `push`; `pull` of a private repo needs a read token.

Run from the repo root:
    python src_module/esg_kg/core/datasync.py push --repo-id <user_or_org>/<name>   # maintainer, after a rebuild
    python src_module/esg_kg/core/datasync.py pull                                  # teammate, reads data_version.json
    python src_module/esg_kg/core/datasync.py status                                # what is pinned vs what is local
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Route large files through classic LFS (S3 multipart) instead of Xet, which huggingface_hub
# 1.x uses by default. Measured here: every one of the 15 LFS-bound files (all *.pdf, plus
# all_validated_triples.json at >10 MB) failed on Xet with "connection forcibly closed"
# (WinError 10054) and stalled at ~447 kB/s, while the 4028 non-LFS files committed fine.
# The same PDF over classic LFS uploaded in 4.5 s at 3.14 MB/s. setdefault, so anyone whose
# link does cope with Xet can still opt back in by exporting HF_HUB_DISABLE_XET=0.
# Must precede any huggingface_hub import — its constants are read at import time, which is
# why every import of it in this file is deliberately function-local.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# Resolved locally rather than imported from esg_kg.core.paths: this tool must run on a
# fresh clone before the LLM/pipeline dependencies are installed, so it stays import-light
# on purpose (three directories up from src_module/esg_kg/core/datasync.py).
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSION_FILE = REPO_ROOT / "data_version.json"

# The generated folders shipped to teammates. Everything here is git-ignored.
SYNCED_FOLDERS = ["data", "graph_output", "kpi_output"]
ALLOW_PATTERNS = [f"{f}/**" for f in SYNCED_FOLDERS]

# Belt-and-braces: ALLOW_PATTERNS already scopes the upload to the three folders, but an
# explicit deny keeps a stray secret from ever riding along if that scope is widened.
IGNORE_PATTERNS = [".env", ".env.*", "**/.env", "EmeraldMind/**", "neo4j_data/**", "**/__pycache__/**"]


def _load_token() -> Optional[str]:
    """Token from .env if present, else whatever `hf auth login` cached."""
    load_dotenv(REPO_ROOT / ".env")
    explicit = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if explicit:
        return explicit
    # get_token() also resolves the cached CLI login, so `hf auth login` alone is enough
    # and no token needs to be written into .env.
    from huggingface_hub import get_token

    return get_token()


def _git_commit() -> str:
    """Current code commit, recorded alongside the data revision to link the two."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _read_version() -> Optional[Dict[str, Any]]:
    if not VERSION_FILE.exists():
        return None
    return json.loads(VERSION_FILE.read_text(encoding="utf-8"))


def _folder_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1048576


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_push(args: argparse.Namespace) -> int:
    from huggingface_hub import HfApi

    pinned = _read_version()
    repo_id = args.repo_id or (pinned or {}).get("repo_id")
    if not repo_id:
        logger.error("No --repo-id given and none pinned in data_version.json.")
        return 1

    token = _load_token()
    if not token and not args.dry_run:
        logger.error("No HF token. Run `hf auth login` or set HF_TOKEN in .env.")
        return 1

    present = [f for f in SYNCED_FOLDERS if (REPO_ROOT / f).exists()]
    missing = [f for f in SYNCED_FOLDERS if f not in present]
    for f in present:
        logger.info("  %-14s %7.1f MB", f, _folder_size_mb(REPO_ROOT / f))
    if missing:
        logger.warning("Missing locally, will not be uploaded: %s", ", ".join(missing))
    if not present:
        logger.error("None of %s exist — nothing to push.", SYNCED_FOLDERS)
        return 1

    total = sum(_folder_size_mb(REPO_ROOT / f) for f in present)
    logger.info("Target: %s (private=%s), total %.1f MB", repo_id, args.private, total)

    if args.dry_run:
        logger.info("[dry-run] Would create/ensure the repo and upload the folders above.")
        logger.info("[dry-run] Would pin the resulting revision into %s", VERSION_FILE.name)
        return 0

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=args.private, exist_ok=True)

    code_commit = _git_commit()
    # upload_large_folder, not upload_folder: the latter has no retry, so on a slow link a
    # dropped connection leaves it hanging on a dead socket forever (seen here — it stalled
    # at 85% and never recovered). This one is resumable, multi-threaded and retries, and it
    # keeps its progress metadata in <folder_path>/.cache/huggingface (git-ignored) so an
    # interrupted run picks up where it left off instead of re-uploading.
    api.upload_large_folder(
        folder_path=str(REPO_ROOT),
        repo_id=repo_id,
        repo_type="dataset",
        allow_patterns=ALLOW_PATTERNS,
        ignore_patterns=IGNORE_PATTERNS,
        print_report=True,
        print_report_every=30,
    )

    # It commits in batches and returns None, so the pin is the repo head once it settles —
    # the intermediate commits are irrelevant, only the final tree needs to be reproducible.
    revision = api.dataset_info(repo_id).sha
    payload = {
        "repo_id": repo_id,
        "repo_type": "dataset",
        "revision": revision,
        "folders": present,
        "pushed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": code_commit,
        "size_mb": round(total, 1),
    }
    VERSION_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    logger.info("Pushed. Pinned revision %s -> %s", revision[:12], VERSION_FILE.name)
    logger.info("Now COMMIT %s so teammates resolve this exact snapshot.", VERSION_FILE.name)
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    from huggingface_hub import snapshot_download

    pinned = _read_version()
    if not pinned:
        logger.error("%s not found — is the repo up to date? Try `git pull`.", VERSION_FILE.name)
        return 1

    repo_id = pinned["repo_id"]
    # --latest is an escape hatch; the default deliberately honours the pin so the data
    # always matches the checked-out code.
    revision = None if args.latest else pinned.get("revision")
    logger.info("Pulling %s @ %s", repo_id, (revision or "latest")[:12])
    if pinned.get("code_commit", "unknown") not in ("unknown", _git_commit()):
        logger.warning(
            "This snapshot was pushed for code commit %s but you are on %s. "
            "If something breaks, reconcile these first.",
            pinned["code_commit"][:8], _git_commit()[:8],
        )

    if args.dry_run:
        logger.info("[dry-run] Would download %s into %s", pinned.get("folders"), REPO_ROOT)
        return 0

    snapshot_download(
        repo_id=repo_id,
        repo_type=pinned.get("repo_type", "dataset"),
        revision=revision,
        local_dir=str(REPO_ROOT),
        token=_load_token(),
        # Scoped exactly like the upload. local_dir is the CODE repo, so an unscoped
        # download writes the dataset's own root files over tracked ones — that is how
        # the Hub's .gitattributes ended up committed here, turning on Git LFS for
        # png/jpg/zip/parquet in a repo that never wanted it. Guarded by
        # test/test_data_sync_scope.py.
        allow_patterns=ALLOW_PATTERNS,
    )
    logger.info("Done. Rebuild Neo4j with: python src_module/run.py neo4j_load --clear")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    pinned = _read_version()
    if not pinned:
        logger.info("No %s — nothing pinned yet.", VERSION_FILE.name)
    else:
        logger.info("Pinned : %s @ %s", pinned["repo_id"], pinned.get("revision", "?")[:12])
        logger.info("Pushed : %s (for code commit %s)",
                    pinned.get("pushed_at", "?"), pinned.get("code_commit", "?")[:8])
        drift = pinned.get("code_commit", "unknown") not in ("unknown", _git_commit())
        logger.info("Code   : %s%s", _git_commit()[:8], "  <-- differs from pin" if drift else "  (matches pin)")
    logger.info("Local folders:")
    for f in SYNCED_FOLDERS:
        p = REPO_ROOT / f
        logger.info("  %-14s %s", f, f"{_folder_size_mb(p):7.1f} MB" if p.exists() else "  (absent)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_push = sub.add_parser("push", help="upload the local data snapshot and pin its revision")
    p_push.add_argument("--repo-id", help="HF dataset repo, e.g. user/capstone-esg-kg-data")
    p_push.add_argument("--private", action="store_true", default=True)
    p_push.add_argument("--public", dest="private", action="store_false")
    p_push.add_argument("--dry-run", action="store_true")
    p_push.set_defaults(func=cmd_push)

    p_pull = sub.add_parser("pull", help="download the pinned snapshot from data_version.json")
    p_pull.add_argument("--latest", action="store_true", help="ignore the pin, take the newest revision")
    p_pull.add_argument("--dry-run", action="store_true")
    p_pull.set_defaults(func=cmd_pull)

    sub.add_parser("status", help="show the pinned vs local state").set_defaults(func=cmd_status)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
