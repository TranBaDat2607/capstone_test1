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
and the provider cascade — analysis, not kernel. Consequence worth remembering (now
historical): ``step10`` was NOT unblocked by this module, because its lazy ``from step07...
import Adjudicator`` sat inside a ``try`` and failed *silently*; it would only have moved
after step07. ``step10`` itself was removed from the project outright on 2026-07-28
(DESIGN.md §4.3), so this no longer matters in practice.

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

import json
import logging
import os
import time
from collections import deque
from threading import Lock
from typing import Dict, List, Optional

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

    def __init__(self, model: str, rate_limit: int,
                 api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        """`api_key`/`base_url` default to OPENAI_API_KEY / OpenAI's own endpoint (every
        existing call site) — passing them explicitly is how a one-off run points this
        same OpenAI-shaped provider at an OpenAI-compatible third-party endpoint (e.g.
        Novita) instead, without touching any stage's default."""
        super().__init__()
        self.model = model
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url)
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


# --------------------------------------------------------------------------- #
# NEW (2026-07-29): an OpenAI path for the stages that were Gemini-only until now
# (01 kpi.extract, 02 graph.extract_triples, 03 graph.fix_triples phase 2, 05
# resolve.entities Stage B/C). Additive — Gemini stays each stage's default, this
# only gives `--provider openai` somewhere real to call. Unlike everything above,
# there is no `src/` twin to keep equal: these two pieces never existed there.
# --------------------------------------------------------------------------- #
class _OpenAIEmbeddingProvider(_Provider):
    """OpenAI's analogue of step05 Stage B's `gemini-embedding-001` call.

    Same shape as `_OpenAIProvider` (lazy client, RateLimiter, `enabled` flag) but the
    request is `embeddings.create`, not `chat.completions.create` — a different OpenAI
    endpoint, not a `call()` override, so it stays a sibling of `_OpenAIProvider` rather
    than a subclass override.
    """
    name = "openai-embedding"

    def __init__(self, model: str, rate_limit: int,
                 api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        """Same override shape as `_OpenAIProvider` — see its docstring."""
        super().__init__()
        self.model = model
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key, base_url=base_url)
            self.rl = RateLimiter(max_calls_per_minute=rate_limit)
            self.enabled = True
        except Exception as e:  # pragma: no cover
            logger.warning(f"[openai-embedding] client init failed ({e}); provider disabled.")

    def embed(self, texts: List[str], dimensions: Optional[int] = None) -> List[List[float]]:
        """`dimensions` mirrors Gemini Stage B's `output_dimensionality=dim` (both
        `text-embedding-3-small/large` support truncating via this OpenAI kwarg) —
        omitted by default so the request shape test above stays unchanged."""
        self.rl.wait_if_needed(0)
        kwargs = {"model": self.model, "input": texts}
        if dimensions is not None:
            kwargs["dimensions"] = dimensions
        resp = self.client.embeddings.create(**kwargs)
        return [d.embedding for d in resp.data]


def openai_json_call(provider: "_OpenAIProvider", system: str, user: str, schema_hint: dict) -> dict:
    """Call an OpenAI-shaped provider and parse a JSON-mode reply.

    Gemini's `response_schema` (steps 01/02) constrains the model's output structurally;
    OpenAI's `response_format={"type": "json_object"}` (all `_OpenAIProvider.call` uses)
    only guarantees *valid* JSON, not conformance to any particular shape — so the schema
    has to travel as a prompt instruction instead. One retry with a sharper nudge covers
    the "model added prose around the JSON" failure mode; a second failure raises rather
    than silently returning an empty/wrong result, matching this project's rule against
    a stage papering over an unusable LLM reply (see step05d/step07's `.get()` fixes).
    """
    schema_text = json.dumps(schema_hint, ensure_ascii=False)
    system_with_schema = (
        f"{system}\n\nRespond with a single JSON object that conforms exactly to this JSON "
        f"Schema (no extra keys, no markdown fences, no prose):\n{schema_text}"
    )
    last_err: Exception = ValueError("openai_json_call: no attempt was made")
    for attempt in range(2):
        raw = provider.call(system_with_schema, user)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            last_err = e
            user = user + "\n\n(Your previous reply was not valid JSON. Reply with ONLY the JSON object.)"
    raise ValueError(f"openai_json_call: reply was not valid JSON after retry: {last_err}")
