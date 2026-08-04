"""llm_cache — the shared content-addressed cache for paid LLM results (GitHub issue #9).

WHY THIS EXISTS
Two hand-written caches already existed with the identical shape before this module did:

    RepairCache        (esg_kg/graph/build_validated.py)  — step03 phase-2 repairs
    AdjudicationCache   (esg_kg/resolve/build_resolved.py) — step05 Stage C same-entity verdicts

Both: sha256 content key, JSON persisted, save only when dirty, corrupt-file-safe load.
`ContentCache` below is that shape lifted into one shared module; both caches are now
thin wrappers over it (same external `get`/`put`/`save` contracts and on-disk JSON
shape, so neither call site nor the cache file format changed — see
`test/test_esg_kg_validated_block.py` / `test/test_esg_kg_resolve_block.py`).

WHAT "CONTENT-ADDRESSED" MEANS HERE
The key is a hash of whatever the caller passes as `*parts` — the exact business key
each stage already used (a triple dict, a {class, a, b} dict, a (claim_text,
evidence_text, evidence_meta) tuple), never a position/order in a batch. A single part
is hashed directly rather than wrapped in a list, so `RepairCache`/`AdjudicationCache`
produce the exact same hash their hand-written code did — a cache file from before this
module existed still hits. Batch boundaries and candidate ranking move between runs; a
position key would silently hand one call's result to a different call.

WHY A SAME-RUN REPEAT IS ALREADY FREE
`entries` is a plain in-memory dict populated synchronously by `put()`, so two calls
with identical `*parts` within the same process already hit on the second call before
any disk I/O happens — no separate "in-flight" tracking is needed for that property.
`test/test_esg_kg_llm_cache.py` pins this directly.

THREAD SAFETY
`claims_vs_conduct` (step07) adjudicates candidate pairs concurrently
(`ThreadPoolExecutor`), so `get`/`put` take a lock around the dict access. This never
blocks on the network call itself — only the in-memory read/write is guarded — so it
adds no serialization to the actual LLM calls, just prevents two threads from
corrupting `entries` on the (rare) same-key race.

WHAT THIS IS NOT
Not provider-side prompt caching (Anthropic/OpenAI/Gemini's own cache) — this is an
application-level cache of the RESULT, to avoid asking again for content already sent.
"""

import hashlib
import json
import logging
import pathlib
import threading
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ContentCache:
    """Generic content-addressed cache: key = sha256(JSON of the parts passed to
    `get`/`put`), value = whatever the caller wants to remember (a raw LLM reply, a
    parsed verdict, `None` for "the model declined") — persisted to `path` as JSON,
    written only when something changed.
    """

    VERSION = 1

    def __init__(self, path: Optional[pathlib.Path] = None) -> None:
        self.path = path
        self.entries: Dict[str, Any] = {}
        self._dirty = False
        self._lock = threading.Lock()
        if path and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.entries = raw.get("entries", {}) if isinstance(raw, dict) else {}
                logger.info(f"Cache: {len(self.entries)} entrie(s) from {path}")
            except Exception as exc:  # a corrupt cache must never stop the pipeline
                logger.warning(f"Cache at {path} unreadable ({exc}); starting empty")
                self.entries = {}

    @staticmethod
    def key(*parts: Any) -> str:
        """Content hash of `parts` — dict key order inside a part never affects the
        hash (`sort_keys=True`), but the parts themselves are positional (order matters
        the same way function arguments do). A single part is hashed directly, not
        wrapped in a list — so a caller keyed on one business object (e.g. `RepairCache`'s
        cleaned triple) gets the exact same hash `RepairCache`/`AdjudicationCache` computed
        by hand before this module existed, and a cache file written by that old code
        still hits."""
        value = parts[0] if len(parts) == 1 else parts
        blob = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, *parts: Any) -> Tuple[Any, bool]:
        k = self.key(*parts)
        with self._lock:
            if k in self.entries:
                return self.entries[k], True
        return None, False

    def put(self, *parts: Any, value: Any) -> None:
        k = self.key(*parts)
        with self._lock:
            self.entries[k] = value
            self._dirty = True

    def save(self) -> bool:
        """Write only when something changed — a free replay must not touch disk."""
        if not (self.path and self._dirty):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": self.VERSION, "entries": self.entries},
                       indent=2, ensure_ascii=False),
            encoding="utf-8")
        logger.info(f"Cache: {len(self.entries)} entrie(s) -> {self.path}")
        return True
