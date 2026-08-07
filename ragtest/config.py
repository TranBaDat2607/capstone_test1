"""
Paths, model names and defaults for ragtest.

The API is the OpenAI-compatible endpoint this project already uses (`OPENAI_BASE_URL`,
`OPENAI_API_KEY` in the repo-root .env — https://api.xah.io/v1, which serves GLM). That
host exposes chat + embeddings but NO rerank model, which is why reranking here is done
by the chat model itself (see rerank.py).

Index artifacts go under `data/outputs/` rather than inside this package: CLAUDE.md's
layout rule is "no data files inside code packages", and `data/` is git-ignored and
distributed via the Hugging Face snapshot instead.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---- inputs (already on disk — nothing here re-runs a pipeline stage) ----
ESG_RECORDS = REPO_ROOT / "data" / "outputs" / "esg_extracted" / "esg_all_records.jsonl"
NEWS_PREPROCESSED = (REPO_ROOT / "data" / "interim" / "news_preprocessed"
                     / "all_news_sentences_classified_preprocessed.jsonl")
ISSUER_REGISTRY = REPO_ROOT / "config" / "issuer_registry.json"

# ---- outputs ----
INDEX_DIR = REPO_ROOT / "data" / "outputs" / "ragtest"
RESULTS_PATH = INDEX_DIR / "query_results.jsonl"

# ---- models ----
EMBED_MODEL = os.getenv("RAGTEST_EMBED_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("RAGTEST_CHAT_MODEL", "glm-5.2")

# ---- retrieval defaults ----
DEFAULT_POOL = 50        # candidates pulled from each channel before fusion
DEFAULT_TOP_K = 10       # candidates handed to the reranker
DEFAULT_FINAL_K = 5      # candidates shown / sent to the verdict prompt
RRF_K = 60               # reciprocal-rank-fusion constant (standard value)
EMBED_BATCH = 64


def load_dotenv(path: Path | None = None) -> None:
    """Load the repo-root .env into os.environ (same convention as every esg_kg stage)."""
    path = path or (REPO_ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
