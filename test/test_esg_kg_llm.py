#!/usr/bin/env python3
"""
Coverage for the LLM kernel: `esg_kg/core/llm.py`.

    src/step02_extract_triplet_from_jsonl.py : DEFAULT_RATE_LIMIT, RateLimiter
                                              -> esg_kg.core.llm

WHY THIS SLICE
`core/llm.py` is the biggest single unlock of the refactor: it frees `step03`, `step05`,
`step07` and `step05d` at once, and then `step08`/`step10` behind them (PIPELINE.md §2.1).

WHAT STAYS BEHIND, DELIBERATELY
`Adjudicator` (step07) is NOT part of this slice. It is stage logic — prompt text,
verdict parsing, the provider cascade — not kernel.

2026-08-04: `_OpenAIProvider`/`_OpenAIEmbeddingProvider`/`openai_json_call` (added
2026-07-27 through 2026-07-29 while the Gemini project behind GEMINI_API_KEY was
billing-blocked) were removed outright, no fallback kept — this project now pays only
for Gemini. `_GeminiProvider` replaces them as the sole `_Provider` subclass, used by
step07's `Adjudicator` cascade and step05d's classifier. Every test below that used to
drive `_OpenAIProvider` (env key handling, disabled-without-key, the paid request shape,
a None-content reply) now drives `_GeminiProvider` instead — same discipline, different
SDK shape (`google.genai.Client.models.generate_content`, not
`openai.OpenAI.chat.completions.create`).

WHY THIS HAS A STRONG OFFLINE ARM
The throttle is pure arithmetic over a clock, and the provider's request SHAPE can be
pinned with a stub client. So the tests below never sleep, never resolve a hostname and
never spend a cent, yet they lock the exact JSON request step07 pays for.
`test_gemini_provider_request_shape` is the one that matters — if a future edit drops
`temperature=0` or `response_mime_type`, the paid adjudication silently changes
behaviour and only this arm notices.

2026-08-08: TRANSIENT-ERROR RETRY (user hitting frequent 503s on gemini-2.5-flash-lite).
`_GeminiProvider.call()` used to surface a `ServerError` (Gemini's "model overloaded,
try again" 5xx) to the caller on the very first occurrence — with a 503 a plain retry
almost always succeeds, so failing immediately was needlessly costly (Adjudicator counts
it as a failure and may disable the provider after 3). The three
`test_gemini_provider_retries_on_server_error*` / `_does_not_retry_client_error` arms
below pin: a `ServerError` (5xx) is retried with exponential backoff up to
`max_retries`, a `ClientError` (4xx — bad request, not-found, auth) is NEVER retried
(retrying a 4xx just burns quota for nothing), and the backoff sleeps go through the
same fake-clock seam as `RateLimiter` so nothing here really sleeps.

Offline: no LLM, no Neo4j, no network. Needs no artifacts from `graph_output/`, so unlike
its sibling files every arm here runs on a bare clone.

Run from the repo root:

    python test/test_esg_kg_llm.py
"""

import os
import sys
import types as _pytypes
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from google.genai import errors as genai_errors  # noqa: E402

from esg_kg.core import llm as new_llm  # noqa: E402


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list = []

    def time(self) -> float:
        return self.now

    def sleep(self, secs: float) -> None:
        self.sleeps.append(round(secs, 6))
        self.now += secs


def drive_limiter(module, limiter_cls, max_calls: int, script) -> tuple:
    """Run `script` (seconds to advance before each call) through one RateLimiter.

    Returns (trace, sleeps) where trace is the clock reading + window depth after each
    call — enough to catch an off-by-one in the 60s eviction as well as a changed
    wait_time formula.
    """
    clock = FakeClock()
    original = module.time
    module.time = clock
    try:
        rl = limiter_cls(max_calls_per_minute=max_calls)
        trace = []
        for advance, client in script:
            clock.now += advance
            rl.wait_if_needed(client)
            trace.append((client, round(clock.now, 6), len(rl.call_times[client])))
        return trace, list(clock.sleeps)
    finally:
        module.time = original


SCRIPT = [
    (0, 0), (0, 0), (0, 0),      # fill a 3-call window instantly
    (0, 0),                      # -> must sleep ~60.1
    (10, 0),                     # partial advance
    (0, 1), (0, 1), (0, 1), (0, 1),   # client 1 has its OWN window -> its own sleep
    (300, 0),                    # long idle -> window fully evicted, no sleep
    (0, 0),
]


def test_rate_limiter_behaviour_is_identical():
    """The throttle is arithmetic over a clock — pin its exact trace/sleep schedule."""
    new_trace, new_sleeps = drive_limiter(new_llm, new_llm.RateLimiter, 3, SCRIPT)

    assert len(new_sleeps) == 2, f"expected the window to trip twice, got {new_sleeps}"
    for s in new_sleeps:
        assert abs(s - 60.1) < 1e-6, f"wait_time formula changed: {s}"
    print(f"     (trace of {len(new_trace)} calls; sleeps={new_sleeps})")


def test_rate_limiter_windows_are_per_client():
    """client_idx keys a SEPARATE deque+Lock; one busy client must not throttle another."""
    _, sleeps = drive_limiter(new_llm, new_llm.RateLimiter, 2, [(0, 0), (0, 0), (0, 7), (0, 7)])
    assert sleeps == [], f"distinct clients throttled each other: {sleeps}"

    _, sleeps = drive_limiter(new_llm, new_llm.RateLimiter, 2, [(0, 3), (0, 3), (0, 3)])
    assert len(sleeps) == 1, f"same client was not throttled: {sleeps}"
    print("     (per-client deque isolation holds)")


def test_provider_base_contract():
    """`_Provider` is the seam the cascade iterates over; its four attributes are API."""
    p = new_llm._Provider()
    assert p.name == "base", p.name
    assert p.enabled is False, "a bare provider must never look usable"
    assert p.calls == 0 and p.failures == 0
    try:
        p.call("sys", "user")
    except NotImplementedError:
        pass
    else:
        raise AssertionError(f"{new_llm._Provider}: base call() must raise NotImplementedError")
    assert issubclass(new_llm._GeminiProvider, new_llm._Provider)
    assert issubclass(new_llm._DeepSeekProvider, new_llm._Provider)
    assert issubclass(new_llm._OpenAIProvider, new_llm._Provider)
    print("     (base contract holds; _GeminiProvider/_DeepSeekProvider/_OpenAIProvider subclass it)")


def _without_gemini_key():
    """Context-manager-ish helper: remove the key, return a restore callable."""
    saved = os.environ.pop("GEMINI_API_KEY", None)

    def restore():
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved
    return restore


def test_gemini_provider_accepts_an_explicit_key():
    """A caller may pass api_key= explicitly (e.g. a one-off test run) WITHOUT needing
    GEMINI_API_KEY set in the environment at all. Default behaviour (env-only, no
    override) must be completely unaffected."""
    restore = _without_gemini_key()
    try:
        p = new_llm._GeminiProvider("gemini-2.5-flash", 10, api_key="explicit-key")
        assert p.enabled is True, "an explicit api_key must enable the provider even with no env var"
    finally:
        restore()
    print("     (explicit api_key override works with no GEMINI_API_KEY in env)")


def test_gemini_provider_disabled_without_key():
    """No key -> disabled, and NOT an exception: the cascade must be able to skip it."""
    restore = _without_gemini_key()
    try:
        p = new_llm._GeminiProvider("gemini-2.5-flash", 10)
        assert p.enabled is False, f"{new_llm._GeminiProvider} claimed to be enabled with no API key"
        assert p.name == "gemini", p.name
        assert not hasattr(p, "client"), "a disabled provider must not hold a client"
    finally:
        restore()
    print("     (disables cleanly, no raise, no client)")


class _StubGenerateContentResponse:
    def __init__(self, text):
        self.text = text


class _StubModels:
    """Captures the request instead of sending it. Records call order into `log`."""

    def __init__(self, log, text=' {"verdict": "supports"} '):
        self.log = log
        self.text = text
        self.captured = None

    def generate_content(self, **kwargs):
        self.log.append("create")
        self.captured = kwargs
        return _StubGenerateContentResponse(self.text)


class _SpyLimiter:
    def __init__(self, log):
        self.log = log

    def wait_if_needed(self, client_idx):
        self.log.append(("wait", client_idx))


def _call_with_stub(cls):
    """Build a real provider, then swap its client+throttle for stubs and call it."""
    os.environ["GEMINI_API_KEY"] = "not-a-real-key"
    p = cls("gemini-2.5-flash", 10)
    assert p.enabled is True, f"{cls} did not enable with a key present (genai SDK missing?)"

    log: list = []
    models = _StubModels(log)
    p.client = _pytypes.SimpleNamespace(models=models)
    p.rl = _SpyLimiter(log)

    out = p.call("SYSTEM PROMPT", "USER PROMPT")
    return out, models.captured, log


def test_gemini_provider_request_shape():
    """Pin the exact paid request. This is the arm that protects step07's LLM contract.

    `temperature=0` and `response_mime_type='application/json'` are not style: the
    adjudicator parses the reply as JSON and the whole pipeline assumes determinism.
    Dropping either would still 'work' at runtime and quietly change every verdict.
    """
    saved = os.environ.get("GEMINI_API_KEY")
    try:
        new_out, new_req, new_log = _call_with_stub(new_llm._GeminiProvider)
    finally:
        if saved is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = saved

    assert new_req["model"] == "gemini-2.5-flash", new_req["model"]
    assert new_req["contents"] == "USER PROMPT", new_req["contents"]
    cfg = new_req["config"]
    assert cfg.system_instruction == "SYSTEM PROMPT", cfg.system_instruction
    assert cfg.response_mime_type == "application/json", cfg.response_mime_type
    assert cfg.temperature == 0, "temperature must stay 0 (determinism)"

    assert new_out == '{"verdict": "supports"}', repr(new_out)
    assert new_log == [("wait", 0), "create"], f"throttle must precede the request: {new_log}"
    print("     (request shape, strip, and wait->create ordering pinned)")


def test_gemini_provider_survives_a_none_reply():
    """Gemini can return `text=None`; the provider must yield '' rather than crash."""
    saved = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ["GEMINI_API_KEY"] = "not-a-real-key"
        p = new_llm._GeminiProvider("gemini-2.5-flash", 10)
        log: list = []
        models = _StubModels(log, text=None)
        p.client = _pytypes.SimpleNamespace(models=models)
        p.rl = _SpyLimiter(log)
        out = p.call("s", "u")
    finally:
        if saved is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = saved

    assert out == "", f"None-reply handling diverged: {out!r}"
    print("     (text=None -> '')")


class _StubModelsFlaky:
    """Raises a transient ServerError `fail_times` times, then succeeds."""

    def __init__(self, fail_times, text=' {"verdict": "supports"} '):
        self.fail_times = fail_times
        self.text = text
        self.attempts = 0

    def generate_content(self, **kwargs):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise genai_errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        return _StubGenerateContentResponse(self.text)


class _StubModelsAlwaysServerError:
    def __init__(self):
        self.attempts = 0

    def generate_content(self, **kwargs):
        self.attempts += 1
        raise genai_errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})


class _StubModelsClientError:
    def __init__(self):
        self.attempts = 0

    def generate_content(self, **kwargs):
        self.attempts += 1
        raise genai_errors.ClientError(404, {"error": {"message": "not found", "status": "NOT_FOUND"}})


def _gemini_provider_with_stub(models, *, max_retries=5, retry_backoff_base=1.0):
    saved = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "not-a-real-key"
    try:
        p = new_llm._GeminiProvider("gemini-2.5-flash-lite", 10,
                                     max_retries=max_retries, retry_backoff_base=retry_backoff_base)
    finally:
        if saved is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = saved
    assert p.enabled is True
    p.client = _pytypes.SimpleNamespace(models=models)
    p.rl = _SpyLimiter([])
    return p


def test_gemini_provider_default_retry_config():
    """Without an override, a provider picks up the module-level retry defaults —
    the same 'one place, not six' shape as DEFAULT_RATE_LIMIT/DEFAULT_MODEL."""
    p = _gemini_provider_with_stub(_StubModelsAlwaysServerError(),
                                    max_retries=new_llm.DEFAULT_MAX_RETRIES,
                                    retry_backoff_base=new_llm.DEFAULT_RETRY_BACKOFF_BASE)
    assert p.max_retries == new_llm.DEFAULT_MAX_RETRIES
    assert p.retry_backoff_base == new_llm.DEFAULT_RETRY_BACKOFF_BASE
    print(f"     (defaults: max_retries={new_llm.DEFAULT_MAX_RETRIES}, "
          f"backoff_base={new_llm.DEFAULT_RETRY_BACKOFF_BASE}s)")


def test_gemini_provider_retries_on_server_error():
    """A transient 503 (ServerError) is retried with exponential backoff instead of
    being surfaced as a failure on the very first occurrence."""
    models = _StubModelsFlaky(fail_times=2)
    p = _gemini_provider_with_stub(models, max_retries=5, retry_backoff_base=1.0)

    clock = FakeClock()
    original = new_llm.time
    new_llm.time = clock
    try:
        out = p.call("s", "u")
    finally:
        new_llm.time = original

    assert out == '{"verdict": "supports"}', repr(out)
    assert models.attempts == 3, f"expected 2 failures + 1 success, got {models.attempts} attempts"
    assert clock.sleeps == [1.0, 2.0], f"exponential backoff schedule changed: {clock.sleeps}"
    print("     (503 retried twice with 1.0s/2.0s backoff, then succeeded)")


def test_gemini_provider_gives_up_after_max_retries():
    """A ServerError that never clears must still propagate once max_retries is
    exhausted — retry is a mitigation, not an infinite loop that hides an outage."""
    models = _StubModelsAlwaysServerError()
    p = _gemini_provider_with_stub(models, max_retries=3, retry_backoff_base=1.0)

    clock = FakeClock()
    original = new_llm.time
    new_llm.time = clock
    try:
        try:
            p.call("s", "u")
        except genai_errors.ServerError:
            pass
        else:
            raise AssertionError("expected ServerError to propagate after exhausting retries")
    finally:
        new_llm.time = original

    assert models.attempts == 4, f"expected 1 initial + 3 retries = 4 attempts, got {models.attempts}"
    assert clock.sleeps == [1.0, 2.0, 4.0], f"backoff schedule changed: {clock.sleeps}"
    print("     (gives up and re-raises after max_retries; backoff schedule 1/2/4s)")


def test_gemini_provider_does_not_retry_client_error():
    """A 4xx ClientError (bad request, not-found, auth) must fail FAST, not retry —
    retrying a client error just burns quota for an error retrying can't fix."""
    models = _StubModelsClientError()
    p = _gemini_provider_with_stub(models, max_retries=5, retry_backoff_base=1.0)

    clock = FakeClock()
    original = new_llm.time
    new_llm.time = clock
    try:
        try:
            p.call("s", "u")
        except genai_errors.ClientError:
            pass
        else:
            raise AssertionError("expected ClientError to propagate immediately")
    finally:
        new_llm.time = original

    assert models.attempts == 1, f"a 4xx must not be retried, got {models.attempts} attempts"
    assert clock.sleeps == [], f"must not sleep/backoff on a non-retryable client error: {clock.sleeps}"
    print("     (4xx ClientError is NOT retried — fails fast)")


def _without_env_key(name: str):
    """Same restore-callable shape as `_without_gemini_key`, generalised to any var."""
    saved = os.environ.pop(name, None)

    def restore():
        if saved is not None:
            os.environ[name] = saved
    return restore


def test_deepseek_provider_accepts_an_explicit_key():
    restore = _without_env_key("DEEPSEEK_API_KEY")
    try:
        p = new_llm._DeepSeekProvider("deepseek-v4-flash", 10, api_key="explicit-key")
        assert p.enabled is True, "an explicit api_key must enable the provider even with no env var"
    finally:
        restore()
    print("     (explicit api_key override works with no DEEPSEEK_API_KEY in env)")


def test_deepseek_provider_disabled_without_key():
    restore = _without_env_key("DEEPSEEK_API_KEY")
    try:
        p = new_llm._DeepSeekProvider("deepseek-v4-flash", 10)
        assert p.enabled is False, f"{new_llm._DeepSeekProvider} claimed to be enabled with no API key"
        assert p.name == "deepseek", p.name
    finally:
        restore()
    print("     (disables cleanly, no raise)")


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _StubPost:
    """Captures the request instead of sending it, mirroring `_StubModels` above."""

    def __init__(self, log, payload=None):
        self.log = log
        self.payload = payload if payload is not None else {
            "choices": [{"message": {"content": ' {"verdict": "supports"} '}}]
        }
        self.captured_url = None
        self.captured_kwargs = None

    def __call__(self, url, **kwargs):
        self.log.append("post")
        self.captured_url = url
        self.captured_kwargs = kwargs
        return _StubResponse(self.payload)


def _call_deepseek_with_stub(payload=None):
    os.environ["DEEPSEEK_API_KEY"] = "not-a-real-key"
    p = new_llm._DeepSeekProvider("deepseek-v4-flash", 10)
    assert p.enabled is True, "_DeepSeekProvider did not enable with a key present"

    log: list = []
    stub = _StubPost(log, payload=payload)
    original_post = new_llm.requests.post
    new_llm.requests.post = stub
    p.rl = _SpyLimiter(log)
    try:
        out = p.call("SYSTEM PROMPT", "USER PROMPT")
    finally:
        new_llm.requests.post = original_post
    return out, stub, log


def test_deepseek_provider_request_shape():
    """Pin the exact paid request: OpenAI-compatible chat/completions body, bearer
    auth, temperature=0 and JSON response_format for the same determinism reason
    `_GeminiProvider`'s shape is pinned above. `thinking: disabled` is pinned for the
    same reason: DeepSeek V4 Flash's docs say `temperature`/`top_p` are INERT while
    thinking mode is on (the default), so without this flag `temperature=0` above is
    silently a no-op and every reply also wastes tokens on a reasoning trace this
    pipeline throws away (it only parses `content` as JSON)."""
    saved = os.environ.get("DEEPSEEK_API_KEY")
    try:
        out, stub, log = _call_deepseek_with_stub()
    finally:
        if saved is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = saved

    assert stub.captured_url == "https://api.deepseek.com/chat/completions", stub.captured_url
    headers = stub.captured_kwargs["headers"]
    assert headers["Authorization"] == "Bearer not-a-real-key", headers
    body = stub.captured_kwargs["json"]
    assert body["model"] == "deepseek-v4-flash", body["model"]
    assert body["messages"] == [
        {"role": "system", "content": "SYSTEM PROMPT"},
        {"role": "user", "content": "USER PROMPT"},
    ], body["messages"]
    assert body["temperature"] == 0, "temperature must stay 0 (determinism)"
    assert body["response_format"] == {"type": "json_object"}, body["response_format"]
    assert body["thinking"] == {"type": "disabled"}, \
        "thinking mode must be disabled, or temperature=0 above is silently inert"

    assert out == '{"verdict": "supports"}', repr(out)
    assert log == [("wait", 0), "post"], f"throttle must precede the request: {log}"
    print("     (request shape, strip, and wait->post ordering pinned)")


def test_deepseek_provider_survives_an_empty_choices_reply():
    """A malformed/empty reply must yield '' rather than crash, same discipline as
    `_GeminiProvider`'s None-reply arm."""
    out, _, _ = _call_deepseek_with_stub(payload={"choices": []})
    assert out == "", f"empty-choices handling diverged: {out!r}"
    print("     (choices=[] -> '')")


def test_openai_provider_accepts_an_explicit_key():
    restore = _without_env_key("OPENAI_API_KEY")
    try:
        p = new_llm._OpenAIProvider("gpt-4o-mini", 10, api_key="explicit-key")
        assert p.enabled is True, "an explicit api_key must enable the provider even with no env var"
    finally:
        restore()
    print("     (explicit api_key override works with no OPENAI_API_KEY in env)")


def test_openai_provider_disabled_without_key():
    restore = _without_env_key("OPENAI_API_KEY")
    try:
        p = new_llm._OpenAIProvider("gpt-4o-mini", 10)
        assert p.enabled is False, f"{new_llm._OpenAIProvider} claimed to be enabled with no API key"
        assert p.name == "openai", p.name
    finally:
        restore()
    print("     (disables cleanly, no raise)")


def _call_openai_with_stub(payload=None):
    os.environ["OPENAI_API_KEY"] = "not-a-real-key"
    p = new_llm._OpenAIProvider("gpt-4o-mini", 10)
    assert p.enabled is True, "_OpenAIProvider did not enable with a key present"

    log: list = []
    stub = _StubPost(log, payload=payload)
    original_post = new_llm.requests.post
    new_llm.requests.post = stub
    p.rl = _SpyLimiter(log)
    try:
        out = p.call("SYSTEM PROMPT", "USER PROMPT")
    finally:
        new_llm.requests.post = original_post
    return out, stub, log


def test_openai_provider_request_shape():
    """Pin the exact paid request: OpenAI chat/completions body, bearer auth,
    temperature=0 and JSON response_format for the same determinism reason
    `_GeminiProvider`'s/`_DeepSeekProvider`'s shapes are pinned above."""
    saved = os.environ.get("OPENAI_API_KEY")
    try:
        out, stub, log = _call_openai_with_stub()
    finally:
        if saved is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = saved

    assert stub.captured_url == "https://api.openai.com/v1/chat/completions", stub.captured_url
    headers = stub.captured_kwargs["headers"]
    assert headers["Authorization"] == "Bearer not-a-real-key", headers
    body = stub.captured_kwargs["json"]
    assert body["model"] == "gpt-4o-mini", body["model"]
    assert body["messages"] == [
        {"role": "system", "content": "SYSTEM PROMPT"},
        {"role": "user", "content": "USER PROMPT"},
    ], body["messages"]
    assert body["temperature"] == 0, "temperature must stay 0 (determinism)"
    assert body["response_format"] == {"type": "json_object"}, body["response_format"]

    assert out == '{"verdict": "supports"}', repr(out)
    assert log == [("wait", 0), "post"], f"throttle must precede the request: {log}"
    print("     (request shape, strip, and wait->post ordering pinned)")


def test_openai_provider_survives_an_empty_choices_reply():
    """A malformed/empty reply must yield '' rather than crash, same discipline as
    `_GeminiProvider`'s/`_DeepSeekProvider`'s empty-reply arms."""
    out, _, _ = _call_openai_with_stub(payload={"choices": []})
    assert out == "", f"empty-choices handling diverged: {out!r}"
    print("     (choices=[] -> '')")


def test_build_llm_provider_selects_gemini_by_default():
    restore = _without_env_key("LLM_PROVIDER")
    try:
        p = new_llm.build_llm_provider(model="gemini-2.5-flash", rate_limit=10, api_key="k")
        assert isinstance(p, new_llm._GeminiProvider), type(p)
    finally:
        restore()
    print("     (no LLM_PROVIDER set -> gemini)")


def test_build_llm_provider_selects_deepseek_explicitly():
    p = new_llm.build_llm_provider(provider="deepseek", model="deepseek-v4-flash",
                                    rate_limit=10, api_key="k")
    assert isinstance(p, new_llm._DeepSeekProvider), type(p)
    assert p.enabled is True
    print("     (explicit provider='deepseek' -> _DeepSeekProvider)")


def test_build_llm_provider_reads_env_switch():
    """The switch is read fresh per call (not frozen at import), so a test can flip
    it without reimporting the module — this is what makes it a per-run swap."""
    os.environ["LLM_PROVIDER"] = "deepseek"
    try:
        p = new_llm.build_llm_provider(model="deepseek-v4-flash", rate_limit=10, api_key="k")
        assert isinstance(p, new_llm._DeepSeekProvider), type(p)
    finally:
        os.environ.pop("LLM_PROVIDER", None)
    print("     (LLM_PROVIDER=deepseek env switch honoured)")


def test_build_llm_provider_rejects_unknown_name():
    try:
        new_llm.build_llm_provider(provider="bogus", api_key="k")
    except ValueError as e:
        assert "bogus" in str(e), str(e)
    else:
        raise AssertionError("build_llm_provider must reject an unknown provider name")
    print("     (unknown provider name raises ValueError)")


def test_build_llm_provider_defaults_model_per_provider():
    """When `model` is omitted, each provider must fall back to ITS OWN default
    model, not another provider's — a plain `model or DEFAULT_MODEL` bug would
    silently send a Gemini model id to DeepSeek's/OpenAI's API."""
    restore = _without_env_key("DEEPSEEK_API_KEY")
    try:
        p = new_llm.build_llm_provider(provider="deepseek", rate_limit=10, api_key="k")
        assert p.model == new_llm.DEEPSEEK_DEFAULT_MODEL, p.model
    finally:
        restore()
    print(f"     (deepseek default model = {new_llm.DEEPSEEK_DEFAULT_MODEL})")


def test_build_llm_provider_selects_openai_explicitly():
    p = new_llm.build_llm_provider(provider="openai", model="gpt-4o-mini",
                                    rate_limit=10, api_key="k")
    assert isinstance(p, new_llm._OpenAIProvider), type(p)
    assert p.enabled is True
    print("     (explicit provider='openai' -> _OpenAIProvider)")


def test_build_llm_provider_defaults_model_for_openai():
    restore = _without_env_key("OPENAI_API_KEY")
    try:
        p = new_llm.build_llm_provider(provider="openai", rate_limit=10, api_key="k")
        assert p.model == new_llm.OPENAI_DEFAULT_MODEL, p.model
    finally:
        restore()
    print(f"     (openai default model = {new_llm.OPENAI_DEFAULT_MODEL})")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
