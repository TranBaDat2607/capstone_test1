"""
Chat + embedding clients for the OpenAI-compatible endpoint this project already uses
(`OPENAI_BASE_URL` / `OPENAI_API_KEY` in the repo-root .env — https://api.xah.io/v1,
serving GLM).

Written against urllib rather than the `openai` package on purpose: CLAUDE.md keeps
`openai` deliberately unlisted in requirements.txt and lazily imported, so a bare clone
still runs. urllib is stdlib, and the two endpoints used here (/chat/completions,
/embeddings) are plain JSON POSTs.

`temperature=0` on the chat calls: reranking and verdicts are measurements, and a
measurement that changes between two identical runs cannot be compared across an
evaluation.

Embeddings are cached on disk keyed by sha1(model + text), so re-building the index or
re-asking a question you already asked costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from .config import EMBED_BATCH


class APIError(RuntimeError):
    pass


def _post(url: str, payload: Dict[str, Any], api_key: str, timeout: int = 120,
          retries: int = 4) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last: Optional[Exception] = None
    for attempt in range(retries):
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            last = APIError(f"HTTP {exc.code}: {detail}")
            # 4xx other than rate limiting will not fix themselves
            if exc.code not in (408, 409, 429) and exc.code < 500:
                raise last
        except Exception as exc:  # noqa: BLE001 — network flakiness
            last = exc
        time.sleep(2 ** attempt)
    raise APIError(f"request to {url} failed after {retries} attempts: {last}")


class ChatClient:
    """Minimal chat wrapper. `complete()` is the only surface the rerank/answer code uses."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 120):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.calls = 0

    def complete(self, system: str, user: str, temperature: float = 0.0,
                 json_mode: bool = True, max_tokens: int = 1500) -> str:
        payload: Dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            data = _post(f"{self.base_url}/chat/completions", payload,
                         self.api_key, self.timeout)
        except APIError:
            if not json_mode:
                raise
            # not every OpenAI-compatible host implements response_format; the prompts
            # ask for JSON in words too, so dropping it is a safe degradation.
            payload.pop("response_format", None)
            data = _post(f"{self.base_url}/chat/completions", payload,
                         self.api_key, self.timeout)

        self.calls += 1
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""


class EmbeddingClient:
    """Batched embeddings with a content-addressed disk cache."""

    def __init__(self, api_key: str, base_url: str, model: str,
                 cache_path: Optional[Path] = None, batch_size: int = EMBED_BATCH,
                 timeout: int = 120):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.batch_size = batch_size
        self.timeout = timeout
        self.cache_path = Path(cache_path) if cache_path else None
        # key -> row in self._vectors. Vectors live in a float32 matrix, not in this dict:
        # 8,956 x 1,536 floats serialized as JSON text is ~275 MB to duplicate a 55 MB
        # .npy, and a build re-saves every 512 sentences, so the JSON form costs O(n^2)
        # disk writes. data/ is synced to the team's HF snapshot, so that waste ships too.
        self.cache: Dict[str, int] = {}
        self._vectors: List[np.ndarray] = []
        self.api_calls = 0
        self.cache_hits = 0
        self._load_cache()

    # ---- cache storage: <stem>.npy (vectors) + <stem>_keys.json (row order) ----

    @property
    def _vectors_path(self) -> Optional[Path]:
        return self.cache_path.with_suffix(".npy") if self.cache_path else None

    @property
    def _keys_path(self) -> Optional[Path]:
        if not self.cache_path:
            return None
        return self.cache_path.with_name(f"{self.cache_path.stem}_keys.json")

    def _load_cache(self) -> None:
        if not self.cache_path:
            return
        vectors_path, keys_path = self._vectors_path, self._keys_path
        if vectors_path.exists() and keys_path.exists():
            try:
                keys = json.loads(keys_path.read_text(encoding="utf-8"))
                matrix = np.load(vectors_path)
                if len(keys) == len(matrix):
                    self._vectors = [row for row in matrix]
                    self.cache = {key: index for index, key in enumerate(keys)}
                    return
                print(f"  [cache] {vectors_path.name} has {len(matrix)} rows but "
                      f"{len(keys)} keys — ignoring it and re-embedding")
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                print(f"  [cache] could not read {vectors_path.name} ({exc}) — re-embedding")
            self.cache, self._vectors = {}, []
            return

        # Legacy format: one JSON object of {key: [float, ...]}. Migrate it rather than
        # re-paying for vectors already bought.
        if self.cache_path.exists():
            try:
                legacy = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            if not isinstance(legacy, dict) or not legacy:
                return
            for key, vector in legacy.items():
                self.cache[key] = len(self._vectors)
                self._vectors.append(np.asarray(vector, dtype="float32"))
            self.save_cache()
            try:
                self.cache_path.unlink()
                print(f"  [cache] migrated {len(self.cache):,} vectors from "
                      f"{self.cache_path.name} to {self._vectors_path.name} (float32)")
            except OSError:
                pass

    def _key(self, text: str) -> str:
        return hashlib.sha1(f"{self.model}\x00{text}".encode("utf-8")).hexdigest()

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        texts = list(texts)
        vectors: List[Optional[np.ndarray]] = [None] * len(texts)
        pending: List[int] = []
        for position, text in enumerate(texts):
            row = self.cache.get(self._key(text))
            if row is not None:
                vectors[position] = self._vectors[row]
                self.cache_hits += 1
            else:
                pending.append(position)

        for start in range(0, len(pending), self.batch_size):
            chunk = pending[start:start + self.batch_size]
            payload = {"model": self.model, "input": [texts[i] for i in chunk]}
            data = _post(f"{self.base_url}/embeddings", payload, self.api_key, self.timeout)
            self.api_calls += 1
            rows = sorted(data.get("data", []), key=lambda r: r.get("index", 0))
            if len(rows) != len(chunk):
                raise APIError(f"expected {len(chunk)} embeddings, got {len(rows)}")
            for position, row in zip(chunk, rows):
                vector = np.asarray(row["embedding"], dtype="float32")
                vectors[position] = vector
                self.cache[self._key(texts[position])] = len(self._vectors)
                self._vectors.append(vector)

        return np.asarray(vectors, dtype="float32")

    def save_cache(self) -> None:
        if not self.cache_path or not self._vectors:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        keys = [None] * len(self._vectors)
        for key, row in self.cache.items():
            keys[row] = key
        np.save(self._vectors_path, np.vstack(self._vectors).astype("float32"))
        self._keys_path.write_text(json.dumps(keys), encoding="utf-8")


def build_clients(chat_model: str, embed_model: str,
                  cache_path: Optional[Path] = None) -> Dict[str, Any]:
    """Construct both clients from the repo-root .env. Raises if the key is missing."""
    import os

    from .config import load_dotenv

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    if not api_key:
        raise APIError("OPENAI_API_KEY is not set — copy .env.example to .env and fill it in")
    return {
        "chat": ChatClient(api_key, base_url, chat_model),
        "embed": EmbeddingClient(api_key, base_url, embed_model, cache_path=cache_path),
        "base_url": base_url,
    }
