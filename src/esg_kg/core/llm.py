"""llm — the shared LLM backend kernel: RPM throttling and the Gemini provider.

Extracted verbatim: ``DEFAULT_RATE_LIMIT`` + ``RateLimiter``
<- ``src/step02_extract_triplet_from_jsonl.py:62,70``.

WHY RateLimiter LIVES HERE
Four stages import it (``03``, ``05``, ``07``) — today that means several stage files
reach UP into ``src/step02`` for a utility, a stage file doubling as a library, the knot
DESIGN.md §1 says ``core/`` exists to untie, and the same shape ``core/graph_patch.py``
and ``core/identity.py`` already fixed.

WHAT IS DELIBERATELY NOT HERE
``Adjudicator`` (``step07``) stays with its stage. It is prompt text, verdict parsing
and the provider cascade — analysis, not kernel.

2026-08-04: THE OPENAI PROVIDER WAS REMOVED OUTRIGHT (no fallback kept). This project
now pays only for ``GEMINI_API_KEY``; ``_OpenAIProvider``/``_OpenAIEmbeddingProvider``/
``openai_json_call`` (added 2026-07-27 through 2026-07-29 while the Gemini project
behind ``GEMINI_API_KEY`` was permanently 403-blocked) are gone, along with every
``--provider openai`` / ``--openai-model`` / ``--openai-base-url`` CLI flag across the
stages that had one (``extract``, ``extract_triples``, ``fix_triples``, ``entities``).
``claims_vs_conduct`` (step07) and ``align_claims`` (step05d) — the two stages that
*require* an LLM and had no deterministic fallback — previously ran on OpenAI as their
only provider (the module docstring here used to say so); they now use ``_GeminiProvider``
below instead. Do not re-add an OpenAI path without checking whether the project is
billing-blocked again first.

ONE CLIENT CONSTRUCTOR, NOT SIX
``build_gemini_client()`` below is the single place that turns ``GEMINI_API_KEY`` into a
working ``genai.Client`` (or ``None``). Every stage that used to branch on
``--provider {gemini,openai}`` (``extract``, ``extract_triples``, ``fix_triples``,
``entities``, and the ``build_validated``/``build_resolved`` blocks) now calls this
instead of re-reading the env var and constructing the client inline — six copies of
that five-line "getenv, check, construct" block is exactly the duplication this refactor
was supposed to remove, not just rename. ``_GeminiProvider.__init__`` calls it too, so
there is truly one implementation.

CARE REQUIRED
``temperature=0`` and ``response_mime_type="application/json"`` in ``_GeminiProvider.call()``
are behaviour, not style: callers (``Adjudicator`` in step07, the classifier in step05d)
parse the reply as JSON and the pipeline assumes determinism. Dropping either still
"works" at runtime while quietly changing every paid verdict.
``test/test_esg_kg_llm.py`` pins the request shape with a stub client, so that
regression is caught without spending anything.

Equally load-bearing in ``RateLimiter``: the window is keyed per ``client_idx`` (its own
deque AND its own ``Lock``), the eviction boundary is ``>= 60``, and the queue is re-swept
*after* sleeping. The stage code calls it with ``client_idx=0`` because this project uses a
single API key, but the multi-key shape is kept as-is under the extract-verbatim rule.

The bodies are duplicated in ``src/`` while the refactor is in flight (Model A — the old
tree must keep running and cannot import from here). ``test/test_esg_kg_llm.py`` holds the
copies equal; that arm retires when the ``src/`` twins are deleted (DESIGN.md §5.3).

ONE MODEL NAME, NOT SIX (2026-08-05: gemini-2.5-flash -> gemini-2.5-flash-lite)
``DEFAULT_MODEL`` below is the single source of truth for which Gemini chat model every
LLM stage (``extract``, ``extract_triples``, ``fix_triples``, ``entities``, ``align_claims``,
``claims_vs_conduct``) defaults to. Each of those stage files used to hardcode its own
``DEFAULT_MODEL = "gemini-2.5-flash"`` — six copies to edit by hand for a model swap, which
is exactly how this got missed the first time. They now import this constant instead. It
reads ``GEMINI_MODEL`` from the environment so **the model can be changed by editing
``.env`` alone**, no code edit required: set ``GEMINI_MODEL=gemini-2.5-flash`` (or any other
Gemini model id) in ``.env`` to override the ``gemini-2.5-flash-lite`` default. ``load_env()``
is called right below, before this constant is computed, so a plain ``import
esg_kg.core.llm`` — even before a stage's own ``main()`` calls ``load_dotenv`` again — is
enough to pick up ``.env``. Every stage's ``--model`` CLI flag still overrides this at
runtime.
"""

import hashlib
import logging
import os
import time
from collections import deque
from threading import Lock
from typing import Dict, Optional

from google import genai
from google.genai import types

from esg_kg.core.paths import load_env

logger = logging.getLogger(__name__)

load_env()  # so GEMINI_MODEL below sees .env even if no stage has loaded it yet

DEFAULT_RATE_LIMIT = 10  # RPM
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


# --------------------------------------------------------------------------- #
# Rate limiter (verbatim port from 2-extract-triplet.py).
# Per-client RPM throttle. With a single API key we use client_idx=0.
# --------------------------------------------------------------------------- #
class RateLimiter:
    def __init__(self, max_calls_per_minute: int = DEFAULT_RATE_LIMIT):
        self.max_calls = max_calls_per_minute
        self.call_times: Dict[int, deque] = {}
        self.locks: Dict[int, Lock] = {}

    def wait_if_needed(self, client_idx: int) -> None:
        if client_idx not in self.call_times:
            self.call_times[client_idx] = deque()
            self.locks[client_idx] = Lock()

        with self.locks[client_idx]:
            now = time.time()
            calls = self.call_times[client_idx]
            while calls and now - calls[0] >= 60:
                calls.popleft()
            if len(calls) >= self.max_calls:
                wait_time = 60 - (now - calls[0]) + 0.1
                if wait_time > 0:
                    logger.info(f"Rate limit: waiting {wait_time:.1f}s for client {client_idx}")
                    time.sleep(wait_time)
                    now = time.time()
                    while calls and now - calls[0] >= 60:
                        calls.popleft()
            calls.append(time.time())


def build_gemini_client(api_key: Optional[str] = None) -> Optional[genai.Client]:
    """Turn ``GEMINI_API_KEY`` (or an explicit override) into a ``genai.Client``, or
    ``None`` if no key is available or the SDK rejects it. Never raises — every call
    site bails out on ``None`` the same way, instead of six slightly different
    getenv/construct blocks each deciding for itself how to fail.
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[gemini] client init failed ({e}).")
        return None


# --------------------------------------------------------------------------- #
# LLM providers. The cascade that iterates over them (`Adjudicator`) stays in
# the stage — see the module docstring.
# --------------------------------------------------------------------------- #
class _Provider:
    """One LLM backend. `call(system, user)` returns the raw text reply or raises."""
    name = "base"

    def __init__(self) -> None:
        self.enabled = False
        self.calls = 0
        self.failures = 0

    def call(self, system: str, user: str) -> str:  # pragma: no cover
        raise NotImplementedError


class _GeminiProvider(_Provider):
    """Google Gemini backend (`google.genai.Client`), the single paid provider.

    Same `call(system, user) -> str` contract the old `_OpenAIProvider` had, so
    step07's `Adjudicator` cascade and step05d's classifier need no shape change to
    use this instead — only the registry/construction call site does.
    """
    name = "gemini"

    def __init__(self, model: str, rate_limit: int, api_key: Optional[str] = None) -> None:
        super().__init__()
        self.model = model
        client = build_gemini_client(api_key)
        if client is None:
            return
        self.client = client
        self.rl = RateLimiter(max_calls_per_minute=rate_limit)
        self.enabled = True

    def call(self, system: str, user: str) -> str:
        self.rl.wait_if_needed(0)
        resp = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return (resp.text or "").strip()


# --------------------------------------------------------------------------- #
# Explicit context caching (GitHub issue #11). `extract_triples`, `fix_triples`
# and `extract` (KPI) each embed a large static block (schema.json / kpi
# definitions) at the front of every prompt, byte-identical across many calls
# in one run — see each stage's own module docstring for its exact reuse scope.
# --------------------------------------------------------------------------- #
class GeminiContextCache:
    """One `client.caches.create()` per unique static prefix, reused via
    `cached_content=` across every `generate_content` call that shares it.

    Memoized by `sha256(static_content)`, which is what lets one instance serve
    both a whole-run scope (`fix_triples`/`extract`: the same hash for the
    entire invocation) and a per-document scope (`extract_triples`: a new hash
    each time company/year change) without either caller tracking cache
    lifetime itself — it just calls `get_or_create()` with whatever the
    current static content is and gets back the same handle when it repeats.

    A `caches.create` failure (below the ~2048-token minimum, permission,
    network) is caught and memoized as `None` so it is never retried on every
    subsequent call for the same content — `get_or_create()` just returns
    `None` and the caller falls back to sending the static content inline,
    uncached. Caching must never break the pipeline.

    IMPORTANT — the Gemini API rejects a `generate_content` call that sets both
    `cached_content` and `system_instruction` (or `tools`/`tool_config`) at once:
    "CachedContent can not be used with GenerateContent request setting
    system_instruction, tools or tool_config." (verified live 2026-08-05: every
    page of a --limit-docs 2 test run 400'd on this exact error before the fix).
    So once `get_or_create()` returns a cache name, the caller's own
    `generate_content` call must NOT also pass `system_instruction`. A caller whose
    system instruction is CONSTANT (e.g. `extract_triples`'s "Return *only* valid
    JSON - no prose.") should pass it here via `system_instruction=` so it is baked
    into the cache itself instead. A caller whose system instruction VARIES per call
    (e.g. `extract`'s KPI stage, where it embeds company/page/doc_name) cannot cache
    it at all — it must fold that text into `contents` instead once cached_content
    is set (see `extract.py`'s `extract_page`).
    """

    def __init__(self, client: "genai.Client", model: str, ttl: str = "3600s") -> None:
        self.client = client
        self.model = model
        self.ttl = ttl
        self._by_hash: Dict[str, Optional[str]] = {}

    def get_or_create(self, static_content: str,
                       rate_limiter: Optional[RateLimiter] = None,
                       system_instruction: Optional[str] = None) -> Optional[str]:
        key = hashlib.sha256(
            f"{system_instruction or ''}\x00{static_content}".encode("utf-8")
        ).hexdigest()
        if key in self._by_hash:
            return self._by_hash[key]
        if rate_limiter is not None:
            rate_limiter.wait_if_needed(0)
        try:
            cache = self.client.caches.create(
                model=self.model,
                config=types.CreateCachedContentConfig(
                    contents=[static_content], ttl=self.ttl,
                    system_instruction=system_instruction,
                ),
            )
            name = cache.name
        except Exception as exc:
            logger.warning(f"[gemini cache] create failed, falling back uncached ({exc})")
            name = None
        self._by_hash[key] = name
        return name

    def invalidate(self, static_content: str, system_instruction: Optional[str] = None) -> None:
        """Drop the memoized handle for this static content so the next `get_or_create()`
        call issues a fresh `caches.create()` instead of silently handing back a name
        that may have expired server-side (past `ttl` above) mid-run. `get_or_create()`
        never rechecks Gemini itself — once a hash is memoized it is returned forever —
        so a caller that suspects its cache has expired (a `generate_content` call
        rejecting `cached_content`) must call this before retrying, or it gets the same
        stale name back. See `kpi/extract.py`'s `_recreate_cache` for the call site."""
        key = hashlib.sha256(
            f"{system_instruction or ''}\x00{static_content}".encode("utf-8")
        ).hexdigest()
        self._by_hash.pop(key, None)
