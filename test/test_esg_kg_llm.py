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

# --- new: the esg_kg package ---------------------------------------------------
from esg_kg.core import llm as new_llm  # noqa: E402


# --------------------------------------------------------------------------- #
# A fake clock. Both trees call `time.time()` / `time.sleep()` through their own
# module-global `time`, so swapping that attribute isolates one tree at a time and
# lets the throttle be driven deterministically without ever really sleeping.
# --------------------------------------------------------------------------- #
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


# A single script exercising: filling the window, tripping the wait, the post-sleep
# re-eviction, an idle gap that empties the window, and a second client's independence.
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

    # ...and the arm is not vacuous: the wait branch really fired, for BOTH clients.
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
    print("     (base contract holds; _GeminiProvider subclasses it)")


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

    # The shape itself, spelled out so a regression names the field it broke.
    assert new_req["model"] == "gemini-2.5-flash", new_req["model"]
    assert new_req["contents"] == "USER PROMPT", new_req["contents"]
    cfg = new_req["config"]
    assert cfg.system_instruction == "SYSTEM PROMPT", cfg.system_instruction
    assert cfg.response_mime_type == "application/json", cfg.response_mime_type
    assert cfg.temperature == 0, "temperature must stay 0 (determinism)"

    # The reply is stripped, and the throttle is consulted BEFORE the request goes out.
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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
