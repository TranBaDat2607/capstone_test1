"""llm — the shared LLM backend kernel: RPM throttling and the OpenAI provider.

Extracted verbatim: ``DEFAULT_RATE_LIMIT`` + ``RateLimiter``
<- ``src/step02_extract_triplet_from_jsonl.py:62,70``; ``_Provider`` + ``_OpenAIProvider``
<- ``src/step07_crosscheck_claims_vs_conduct.py:271,284``.

WHY THESE FOUR TRAVEL TOGETHER
They cannot be split across two commits: ``_OpenAIProvider.__init__`` CONSTRUCTS a
``RateLimiter``. Today that means ``src/step07`` reaches UP into ``src/step02`` for a
utility — a stage file doubling as a library, the knot DESIGN.md §1 says ``core/`` exists
to untie, and the same shape ``core/graph_patch.py`` and ``core/identity.py`` already
fixed. Four stages import ``RateLimiter`` from step02 (``03``, ``05``, ``07``) and
``_OpenAIProvider`` from step07 (``05d``), so this one module is the refactor's biggest
single unlock (PIPELINE.md §2.1).

WHAT IS DELIBERATELY NOT HERE
``Adjudicator`` (``step07:311``) stays with its stage. It is prompt text, verdict parsing
and the provider cascade — analysis, not kernel. Consequence worth remembering: ``step10``
is NOT unblocked by this module, because its lazy ``from step07... import Adjudicator``
(``step10:368``) sits inside a ``try`` and fails *silently*; it moves only after step07.

There is no Gemini provider to lift. ``step07:34`` records that it was removed outright —
the project behind ``GEMINI_API_KEY`` is permanently 403, and every run wasted seconds
retrying it before falling back to OpenAI.

CARE REQUIRED
``temperature=0`` and ``response_format={"type": "json_object"}`` in ``call()`` are
behaviour, not style: the adjudicator parses the reply as JSON and the pipeline assumes
determinism. Dropping either still "works" at runtime while quietly changing every paid
verdict. ``test/test_esg_kg_llm.py`` pins the whole request shape with a stub client, so
that regression is caught without spending anything.

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
from typing import Dict

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
# LLM providers (verbatim from step07). The cascade that iterates over them
# (`Adjudicator`) stays in the stage — see the module docstring.
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


class _OpenAIProvider(_Provider):
    name = "openai"

    def __init__(self, model: str, rate_limit: int) -> None:
        super().__init__()
        self.model = model
        if not os.getenv("OPENAI_API_KEY"):
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.rl = RateLimiter(max_calls_per_minute=rate_limit)
            self.enabled = True
        except Exception as e:  # pragma: no cover
            logger.warning(f"[openai] client init failed ({e}); provider disabled.")

    def call(self, system: str, user: str) -> str:
        self.rl.wait_if_needed(0)
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return (resp.choices[0].message.content or "").strip()
