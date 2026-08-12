# Data sync — distributing generated data via Hugging Face

```bash
python src/esg_kg/core/datasync.py status     # what is pinned vs what is local
python src/esg_kg/core/datasync.py pull       # land the snapshot this commit was built against
python src/esg_kg/core/datasync.py push       # after a rebuild (needs org write access)
```

Module: `src/esg_kg/core/datasync.py` · Pin file: `data_version.json` (**tracked in Git**)

Not a pipeline stage — it has no `run.py` entry. This is the transport layer that lets a
teammate `git pull` the code and land the exact data snapshot that code was built against,
without re-running any expensive stage.

---

## 1. Why this exists

Three of the pipeline's inputs cannot simply be regenerated:

- LLM extraction (stages 01, 02, 03, 07) **costs money**;
- ViDeBERTa labeling needs a **GPU**;
- the news crawl is **not reproducible** — the web moves.

So the generated artifacts are distributed, not rebuilt.

### 1.1 Why not Git

`data/`, `graph_output/` and `kpi_output/` are hundreds of megabytes of generated
artifacts plus one 71 MB PDF. Git handles that badly: binary deltas bloat history
permanently, and GitHub hard-blocks files over 100 MB. Those folders are git-ignored; a
Hugging Face **dataset repo** carries them instead.

### 1.2 Why not a shared drive

The failure mode that actually bites is **data ↔ code version drift**: a teammate pulls
code at commit X while the shared folder sits at state Y, and the resulting errors are
baffling. So the pushed dataset revision is **pinned in `data_version.json`, which is
tracked in Git**.

Checking out an old commit and pulling therefore recovers the data that commit was built
against — which is also what makes a before/after comparison reproducible.

```jsonc
{ "repo_id": "nammovuivui-capstone/capstone",
  "repo_type": "dataset",
  "revision": "902fcf84cefce68bc70aff5e9e2ba805ff7062e6",
  "folders": ["data", "graph_output", "kpi_output"],
  "pushed_at": "2026-08-07T06:50:54+00:00",
  "code_commit": "7c108f97d699fb7e0698fe6b366effa81b541652",
  "size_mb": 18969.0 }
```

`code_commit` links the two directions, so a snapshot can be traced back to the code that
produced it.

---

## 2. Access

The dataset lives in the **`nammovuivui-capstone` organization**, not a personal namespace.
Hugging Face has no collaborator feature for user-owned repos, so an org is the only way to
share a private one.

You must be invited: `read` to pull, `write` to push. Without an invitation the repo
returns **404, not 403** — an authorization failure looks exactly like a typo.

Authenticate with `hf auth login`, or put `HF_TOKEN` in `.env`. A fine-grained token needs
org scope. The loader checks `.env` first, then falls back to the cached CLI login, so
`hf auth login` alone is enough and no token needs to be written to disk.

`huggingface_hub` is imported **lazily** and is deliberately **not** in
`requirements.txt` — the tool must work on a bare clone before any pipeline dependency is
installed. For the same reason this module resolves the repo root itself rather than
importing `core/paths.py`, and nothing else in `esg_kg` imports from it.

---

## 3. Scoping — the bug this prevents

Both `push` and `pull` are scoped by `ALLOW_PATTERNS` to exactly the three synced folders.

This is not an optimization. `local_dir` is the **code repository**, so an unscoped pull
writes the dataset repo's own root files over tracked ones. That is how the Hub's
`.gitattributes` came to be committed here — and why this repo now routes
`*.png/jpg/zip/parquet` through Git LFS.

`test/test_data_sync_scope.py` guards it offline, with `snapshot_download` replaced by a
recorder.

`data/outputs/news/_cache/**` is additionally excluded — it is a fetch cache, not data.

### 3.1 What is deliberately not distributed

None of this is about size:

| Path | Why not |
|---|---|
| `.env` | Secrets. Each member uses their own API keys, which keeps quota and billing attributable per person |
| `EmeraldMind/` | Read-only external reference with its own `.git` and its own secrets |
| `neo4j_data/` | A live database volume: corrupt if copied while running, and pinned to the image version. Rebuild it locally with `neo4j_load` — one command, no LLM |

---

## 4. Workflows

### 4.1 Joining the project

```bash
git clone <repo> && cd capstone_test1
pip install -r requirements.txt
cp .env.example .env                       # then fill in GEMINI_API_KEY
hf auth login                               # or set HF_TOKEN in .env
python src/esg_kg/core/datasync.py pull
docker compose up -d
python src/run.py neo4j_load --clear
```

Verify with `python src/run.py claim_ledger`.

### 4.2 Publishing a new snapshot

```bash
git pull                                                 # surface a pin conflict in Git, not on the Hub
python src/esg_kg/core/datasync.py push --dry-run        # inspect what would go up
python src/esg_kg/core/datasync.py push                  # needs an org write token
git add data_version.json && git commit -m "data: refresh snapshot" && git push
```

> **Anyone pushing must commit `data_version.json` in the same sitting.** A pushed snapshot
> whose pin is not committed is **invisible**: the Hub has the new data,
> `data_version.json` still points at the old revision, and the team keeps pulling stale
> data with no error at all.

`git pull` before pushing so a pin conflict surfaces as a Git conflict rather than silently
overwriting someone else's snapshot. Announce the push, so nobody is mid-rebuild on a
snapshot you replaced.

### 4.3 Checking state

```bash
python src/esg_kg/core/datasync.py status
```

Reports the pinned revision, the local folder sizes, and warns on drift.

---

## 5. Flags

| Command | Flags |
|---|---|
| `push` | `--repo-id`, `--dry-run` |
| `pull` | `--dry-run`, `--latest` (ignore the pin and fetch the newest revision — use knowingly) |
| `status` | — |

---

## 6. Tests

`test/test_data_sync_scope.py` — pull can never overwrite a tracked repo-root file.

`test/test_esg_kg_datasync.py` — constants, push/pull scoping, status reporting, with
every `huggingface_hub` call replaced by a recorder. Nothing touches the network.
