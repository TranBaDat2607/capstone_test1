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
"""

import logging
import os
import time
from collections import deque
from threading import Lock
from typing import Dict, Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT = 10  # RPM


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
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            return
        try:
            self.client = genai.Client(api_key=api_key)
            self.rl = RateLimiter(max_calls_per_minute=rate_limit)
            self.enabled = True
        except Exception as e:  # pragma: no cover
            logger.warning(f"[gemini] client init failed ({e}); provider disabled.")

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
