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

2026-08-06: A SECOND PROVIDER, AS A SWAP NOT A CASCADE
``_DeepSeekProvider`` adds DeepSeek V4 Flash as a second ``_Provider`` — same
``call(system, user) -> str`` contract as ``_GeminiProvider``, so any caller written
against that contract (``claims_vs_conduct``'s ``Adjudicator``, ``align_claims``) can use
either one unchanged. This is deliberately NOT the 2026-07-27..2026-08-04 OpenAI episode
again: that was a forced fallback (Gemini was billing-blocked, OpenAI was the only thing
that worked, then it was removed outright once Gemini came back — see the note above).
This is the opposite shape — Gemini stays the default and fully working, DeepSeek is an
opt-in ALTERNATIVE the caller picks deliberately (one provider active per run, chosen via
``build_llm_provider()`` below), not an automatic fallback chain. Unlike the old OpenAI
provider, DeepSeek's API is OpenAI-compatible REST (``POST /chat/completions``), so this
uses the already-a-dependency ``requests`` rather than reintroducing the ``openai`` SDK
that was deliberately removed.

``_DeepSeekProvider.call()`` always sends ``"thinking": {"type": "disabled"}``.
``deepseek-v4-flash`` defaults to thinking mode ON, and DeepSeek's own docs say
``temperature``/``top_p`` are INERT while it's on — so without this flag, this class's own
``temperature=0`` would silently do nothing (breaking the determinism every caller here
assumes), and every call would also pay for a reasoning trace nothing in this pipeline
reads (only the plain ``content`` field is ever parsed as JSON).

``build_llm_provider()`` is the ONE place that turns an env var / explicit override into a
provider instance — the same "one constructor, not six" reasoning as
``build_gemini_client()`` above, generalized across providers. It reads ``LLM_PROVIDER``
FRESH on every call (not frozen at import like ``DEFAULT_MODEL``) so a caller — or a test —
can flip providers without reimporting this module; a stage's own ``--provider`` CLI flag
overrides it the same way ``--model`` overrides ``DEFAULT_MODEL``. ``align_claims`` (a
single-provider stage) goes through this factory directly. ``claims_vs_conduct`` keeps its
OWN registry inside ``Adjudicator`` instead — that class is stage logic (prompt text,
verdict parsing, the provider cascade), not kernel, exactly as this module's docstring has
always said — but its registry constructs the same ``_GeminiProvider``/``_DeepSeekProvider``
classes from here, so adding a provider still means editing this file once, not per-stage.
``extract``/``extract_triples``/``fix_triples``/``entities`` still call
``build_gemini_client()`` directly because they use Gemini-specific explicit context caching
(``GeminiContextCache`` below) that has no DeepSeek equivalent — making those swappable too
is a separate, larger redesign, not a drop-in.

2026-08-06: OPENAI RE-ADDED, OPT-IN, ``claims_vs_conduct`` ONLY
``_OpenAIProvider`` is back, at the user's explicit request, for ``claims_vs_conduct``
(step07) specifically — NOT a reversal of the 2026-08-04 removal note above, and NOT
another forced-fallback episode: Gemini stays the default, this is a third opt-in
alternative the caller picks deliberately (same shape as the DeepSeek addition one
section up), selected via ``claims_vs_conduct --provider-order openai``. Same
"OpenAI-compatible REST via ``requests``, no SDK" reasoning as ``_DeepSeekProvider`` —
the ``openai`` Python package is still not a dependency of this project.
``align_claims``/``extract_triples``/``fix_triples``/``entities`` do NOT expose this:
their own ``--provider`` flags still only accept ``choices=["gemini", "deepseek"]``,
so adding ``"openai"`` to ``_PROVIDER_CLASSES``/``_PROVIDER_DEFAULT_MODELS`` below does
not silently enable it anywhere but ``claims_vs_conduct``'s own registry (which
constructs providers straight from this module, not through those other stages'
argparse). ``OPENAI_API_KEY``/``OPENAI_MODEL`` in ``.env`` configure it; unset it and
every stage keeps using Gemini exactly as before.

2026-08-08: RETRY-WITH-BACKOFF ON TRANSIENT GEMINI ERRORS. ``gemini-2.5-flash-lite``
returns a plain 503 (``google.genai.errors.ServerError``, "model overloaded") often
enough under load that surfacing it to the caller on the FIRST occurrence was needlessly
costly: a caller like ``Adjudicator`` (step07) counts any exception as a failure and
disables the provider after 3 failures with 0 successes, so a handful of transient 503s
in a row could silently turn off Gemini for the rest of a run. ``_GeminiProvider.call()``
now retries a ``ServerError`` (any 5xx) up to ``max_retries`` times with exponential
backoff (``retry_backoff_base * 2**attempt`` seconds) before giving up and re-raising.
A ``ClientError`` (4xx — bad request, not found, auth) is deliberately NEVER retried:
those are not transient, and retrying one just burns quota waiting for an error that
retrying cannot fix. Defaults (``DEFAULT_MAX_RETRIES=5``, ``DEFAULT_RETRY_BACKOFF_BASE=2.0``
seconds) are read from ``GEMINI_MAX_RETRIES``/``GEMINI_RETRY_BACKOFF_SECONDS`` in
``.env`` — same "one place, env override" shape as ``DEFAULT_MODEL`` above — and every
``_GeminiProvider`` constructor call can still override them explicitly (used by
``test_esg_kg_llm.py`` to test the backoff schedule without a real clock). Scoped to
``_GeminiProvider`` only: DeepSeek/OpenAI use a different SDK-less REST shape and were
not reported as flaky, so retrying them is a separate change, not bundled in here.
"""

import hashlib
import logging
import os
import time
from collections import deque
from threading import Lock
from typing import Dict, Optional

import requests
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from esg_kg.core.paths import load_env

logger = logging.getLogger(__name__)

load_env()

DEFAULT_RATE_LIMIT = 10
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
DEFAULT_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "5"))
DEFAULT_RETRY_BACKOFF_BASE = float(os.getenv("GEMINI_RETRY_BACKOFF_SECONDS", "2.0"))
DEEPSEEK_DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
OPENAI_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


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


class _Provider:
    """One LLM backend. `call(system, user)` returns the raw text reply or raises."""
    name = "base"

    def __init__(self) -> None:
        self.enabled = False
        self.calls = 0
        self.failures = 0

    def call(self, system: str, user: str) -> str:  # pragma: no cover
        raise NotImplementedError


def _call_with_retry(fn, *, max_retries: int, backoff_base: float, provider_name: str):
    """Run `fn()`, retrying a transient `genai_errors.ServerError` (any 5xx — Gemini's
    "model overloaded, try again" response) with exponential backoff. A `ClientError`
    (4xx) is never retried: it isn't transient, and retrying one just burns quota on an
    error that won't clear on its own. Re-raises the last error once `max_retries` is
    exhausted, so this is a mitigation, not a way to silently hide an outage.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except genai_errors.ServerError as e:
            attempt += 1
            if attempt > max_retries:
                logger.error(f"[{provider_name}] giving up after {attempt - 1} retries: {e}")
                raise
            wait = backoff_base * (2 ** (attempt - 1))
            logger.warning(
                f"[{provider_name}] transient server error (attempt {attempt}/{max_retries}), "
                f"retrying in {wait:.1f}s: {e}"
            )
            time.sleep(wait)


class _GeminiProvider(_Provider):
    """Google Gemini backend (`google.genai.Client`), the single paid provider.

    Same `call(system, user) -> str` contract the old `_OpenAIProvider` had, so
    step07's `Adjudicator` cascade and step05d's classifier need no shape change to
    use this instead — only the registry/construction call site does.
    """
    name = "gemini"

    def __init__(self, model: str, rate_limit: int, api_key: Optional[str] = None,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE) -> None:
        super().__init__()
        self.model = model
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base
        client = build_gemini_client(api_key)
        if client is None:
            return
        self.client = client
        self.rl = RateLimiter(max_calls_per_minute=rate_limit)
        self.enabled = True

    def call(self, system: str, user: str) -> str:
        self.rl.wait_if_needed(0)
        resp = _call_with_retry(
            lambda: self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=0,
                ),
            ),
            max_retries=self.max_retries,
            backoff_base=self.retry_backoff_base,
            provider_name=self.name,
        )
        return (resp.text or "").strip()


class _DeepSeekProvider(_Provider):
    """DeepSeek backend (OpenAI-compatible REST, no SDK dependency) — a swappable
    ALTERNATIVE to `_GeminiProvider`, not a fallback: same `call(system, user) -> str`
    contract, so `Adjudicator` (step07) and `align_claims` (step05d) use it unchanged.
    See the module docstring for why this isn't the 2026-08-04 OpenAI episode again.
    """
    name = "deepseek"
    API_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, model: str, rate_limit: int, api_key: Optional[str] = None) -> None:
        super().__init__()
        self.model = model
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return
        self.api_key = api_key
        self.rl = RateLimiter(max_calls_per_minute=rate_limit)
        self.enabled = True

    def call(self, system: str, user: str) -> str:
        self.rl.wait_if_needed(0)
        resp = requests.post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
            },
            timeout=120,
        )
        resp.raise_for_status()
        choices = resp.json().get("choices") or []
        if not choices:
            return ""
        content = (choices[0].get("message") or {}).get("content")
        return (content or "").strip()


class _OpenAIProvider(_Provider):
    """OpenAI backend (Chat Completions REST, no `openai` SDK dependency) — a
    swappable ALTERNATIVE, opt-in for `claims_vs_conduct` (step07) only, re-added
    2026-08-06 at the user's explicit request. Same `call(system, user) -> str`
    contract as `_GeminiProvider`/`_DeepSeekProvider`, and the same "no SDK"
    reasoning as `_DeepSeekProvider`: OpenAI's REST API is plain JSON over
    `requests`, so this does not reintroduce the `openai` package removed
    2026-08-04 (see the module docstring's history above — this is a deliberate
    opt-in swap the user asked for, not a repeat of that forced-fallback episode).
    """
    name = "openai"
    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, model: str, rate_limit: int, api_key: Optional[str] = None) -> None:
        super().__init__()
        self.model = model
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            return
        self.api_key = api_key
        self.rl = RateLimiter(max_calls_per_minute=rate_limit)
        self.enabled = True

    def call(self, system: str, user: str) -> str:
        self.rl.wait_if_needed(0)
        resp = requests.post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        resp.raise_for_status()
        choices = resp.json().get("choices") or []
        if not choices:
            return ""
        content = (choices[0].get("message") or {}).get("content")
        return (content or "").strip()


_PROVIDER_CLASSES = {"gemini": _GeminiProvider, "deepseek": _DeepSeekProvider, "openai": _OpenAIProvider}
_PROVIDER_DEFAULT_MODELS = {
    "gemini": DEFAULT_MODEL, "deepseek": DEEPSEEK_DEFAULT_MODEL, "openai": OPENAI_DEFAULT_MODEL,
}


def build_llm_provider(provider: Optional[str] = None, model: Optional[str] = None,
                        rate_limit: int = DEFAULT_RATE_LIMIT,
                        api_key: Optional[str] = None) -> _Provider:
    """The one factory a caller should use instead of hardcoding `_GeminiProvider(...)`,
    so "which provider" is a single switch: `provider` (an explicit override, e.g. a
    stage's own `--provider` flag) or, if omitted, the `LLM_PROVIDER` env var (read fresh
    here, not frozen at import — a run can pick its provider without reimporting this
    module), defaulting to `"gemini"` when neither is set. `model`, if omitted, falls back
    to THAT provider's own default (`DEFAULT_MODEL` for gemini, `DEEPSEEK_DEFAULT_MODEL`
    for deepseek) — never the other provider's, which would silently send a Gemini model
    id to DeepSeek's API or vice versa.
    """
    name = (provider or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
    cls = _PROVIDER_CLASSES.get(name)
    if cls is None:
        raise ValueError(f"Unknown LLM provider '{name}' (known: {sorted(_PROVIDER_CLASSES)})")
    return cls(model or _PROVIDER_DEFAULT_MODELS[name], rate_limit, api_key=api_key)


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
