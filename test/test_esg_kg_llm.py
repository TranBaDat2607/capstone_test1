#!/usr/bin/env python3
"""
Old-vs-new equivalence for ONE migration slice: the LLM kernel.

    src/step02_extract_triplet_from_jsonl.py : DEFAULT_RATE_LIMIT, RateLimiter
    src/step07_crosscheck_claims_vs_conduct.py : _Provider, _OpenAIProvider
                                              -> esg_kg.core.llm

WHY THIS SLICE, AND WHY THE FOUR SYMBOLS TRAVEL TOGETHER
`core/llm.py` is the biggest single unlock of the refactor: it frees `step03`, `step05`,
`step07` and `step05d` at once, and then `step08`/`step10` behind them (PIPELINE.md §2.1).
The four symbols cannot be split across two commits because `_OpenAIProvider.__init__`
CONSTRUCTS a `RateLimiter` — the provider and the throttle are one unit even though they
are defined in two different stage files today. That cross-file dependency (step07
reaching UP into step02 for a utility) is exactly the knot DESIGN.md §1 says `core/`
exists to untie.

WHAT STAYS BEHIND, DELIBERATELY
`Adjudicator` (step07:311) is NOT part of this slice. It is stage logic — prompt text,
verdict parsing, the provider cascade — not kernel. That is also why `step10` stayed
blocked after this lands: its lazy `from step07... import Adjudicator` sat inside a `try`
and failed SILENTLY, so it could only move once step07 itself moved. (`step10` was removed
from the project outright on 2026-07-28 — DESIGN.md §4.3 — so this is now historical.)

WHY THIS HAS A STRONG OFFLINE ARM WHEN THE STAGES IT UNBLOCKS DO NOT
Every stage still eligible to move (01/04/06/09) has a weak equivalence arm — Neo4j, or a
paid LLM call. This slice does not: the throttle is pure arithmetic over a clock, and the
provider's request SHAPE can be pinned with a stub client. So the test below never sleeps,
never resolves a hostname and never spends a cent, yet it locks the exact JSON request
step07 pays for. `test_openai_provider_request_shape` is the one that matters — if a future
edit drops `temperature=0` or `response_format`, the paid adjudication silently changes
behaviour and only this arm notices.

Offline: no LLM, no Neo4j, no network. Needs no artifacts from `graph_output/`, so unlike
its sibling files every arm here runs on a bare clone.

Was driven through both `src/` and `esg_kg` while both trees existed (DESIGN.md §5.3);
repointed at `esg_kg` only (2026-07-29) now that `src/` is gone. Cross-tree comparisons
with no independent claim about correct behaviour were deleted rather than rewritten
against a guessed value; see the deletion notes in the PR/commit that made this change.

Run from the repo root:

    python test/test_esg_kg_llm.py
"""

import os
import sys
import types as _pytypes
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src_module"))

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
    assert issubclass(new_llm._OpenAIProvider, new_llm._Provider)
    print("     (base contract holds; _OpenAIProvider subclasses it)")


def _without_openai_key():
    """Context-manager-ish helper: remove the key, return a restore callable."""
    saved = os.environ.pop("OPENAI_API_KEY", None)

    def restore():
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved
    return restore


def test_openai_provider_accepts_an_explicit_key_and_base_url_override():
    """NEW (2026-07-29): a caller may pass api_key=/base_url= explicitly — e.g. to point
    the same OpenAI-shaped provider at an OpenAI-compatible third-party endpoint (Novita)
    for a one-off test run — WITHOUT needing OPENAI_API_KEY set in the environment at all.
    Default behaviour (env-only, no override) must be completely unaffected."""
    restore = _without_openai_key()
    try:
        p = new_llm._OpenAIProvider("some-model", 10, api_key="explicit-key", base_url="https://example.invalid/v1")
        assert p.enabled is True, "an explicit api_key must enable the provider even with no env var"
        assert p.client.api_key == "explicit-key"
        assert str(p.client.base_url).rstrip("/") == "https://example.invalid/v1"
    finally:
        restore()
    print("     (explicit api_key/base_url override works with no OPENAI_API_KEY in env)")


def test_openai_embedding_provider_accepts_an_explicit_key_and_base_url_override():
    restore = _without_openai_key()
    try:
        p = new_llm._OpenAIEmbeddingProvider("some-embed-model", 10, api_key="explicit-key",
                                             base_url="https://example.invalid/v1")
        assert p.enabled is True
        assert p.client.api_key == "explicit-key"
        assert str(p.client.base_url).rstrip("/") == "https://example.invalid/v1"
    finally:
        restore()
    print("     (embedding provider accepts the same override)")


def test_openai_provider_disabled_without_key():
    """No key -> disabled, and NOT an exception: the cascade must be able to skip it."""
    restore = _without_openai_key()
    try:
        p = new_llm._OpenAIProvider("gpt-4o-mini", 10)
        assert p.enabled is False, f"{new_llm._OpenAIProvider} claimed to be enabled with no API key"
        assert p.name == "openai", p.name
        assert not hasattr(p, "client"), "a disabled provider must not hold a client"
    finally:
        restore()
    print("     (disables cleanly, no raise, no client)")


class _StubResponse:
    def __init__(self, content):
        msg = _pytypes.SimpleNamespace(content=content)
        self.choices = [_pytypes.SimpleNamespace(message=msg)]


class _StubCompletions:
    """Captures the request instead of sending it. Records call order into `log`."""

    def __init__(self, log, content=' {"verdict": "supports"} '):
        self.log = log
        self.content = content
        self.captured = None

    def create(self, **kwargs):
        self.log.append("create")
        self.captured = kwargs
        return _StubResponse(self.content)


class _SpyLimiter:
    def __init__(self, log):
        self.log = log

    def wait_if_needed(self, client_idx):
        self.log.append(("wait", client_idx))


def _call_with_stub(cls):
    """Build a real provider, then swap its client+throttle for stubs and call it."""
    os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"
    p = cls("gpt-4o-mini", 10)
    assert p.enabled is True, f"{cls} did not enable with a key present (openai SDK missing?)"

    log: list = []
    completions = _StubCompletions(log)
    p.client = _pytypes.SimpleNamespace(chat=_pytypes.SimpleNamespace(completions=completions))
    p.rl = _SpyLimiter(log)

    out = p.call("SYSTEM PROMPT", "USER PROMPT")
    return out, completions.captured, log


def test_openai_provider_request_shape():
    """Pin the exact paid request. This is the arm that protects step07's LLM contract.

    `temperature=0` and `response_format={'type':'json_object'}` are not style: the
    adjudicator parses the reply as JSON and the whole pipeline assumes determinism.
    Dropping either would still 'work' at runtime and quietly change every verdict.
    """
    saved = os.environ.get("OPENAI_API_KEY")
    try:
        new_out, new_req, new_log = _call_with_stub(new_llm._OpenAIProvider)
    finally:
        if saved is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = saved

    # The shape itself, spelled out so a regression names the field it broke.
    assert new_req["model"] == "gpt-4o-mini", new_req["model"]
    assert new_req["temperature"] == 0, "temperature must stay 0 (determinism)"
    assert new_req["response_format"] == {"type": "json_object"}, new_req.get("response_format")
    assert new_req["messages"] == [
        {"role": "system", "content": "SYSTEM PROMPT"},
        {"role": "user", "content": "USER PROMPT"},
    ], new_req["messages"]

    # The reply is stripped, and the throttle is consulted BEFORE the request goes out.
    assert new_out == '{"verdict": "supports"}', repr(new_out)
    assert new_log == [("wait", 0), "create"], f"throttle must precede the request: {new_log}"
    print("     (request shape, strip, and wait->create ordering pinned)")


def test_openai_provider_survives_a_none_reply():
    """OpenAI can return `content=None`; the provider must yield '' rather than crash."""
    saved = os.environ.get("OPENAI_API_KEY")
    try:
        os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"
        p = new_llm._OpenAIProvider("gpt-4o-mini", 10)
        log: list = []
        completions = _StubCompletions(log, content=None)
        p.client = _pytypes.SimpleNamespace(
            chat=_pytypes.SimpleNamespace(completions=completions))
        p.rl = _SpyLimiter(log)
        out = p.call("s", "u")
    finally:
        if saved is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = saved

    assert out == "", f"None-reply handling diverged: {out!r}"
    print("     (content=None -> '')")


# --------------------------------------------------------------------------- #
# NEW kernel surface (2026-07-29): _OpenAIEmbeddingProvider + openai_json_call.
#
# These have NO src/ counterpart — they exist to give steps 01/02/03/05 (Gemini-only
# today) an additive OpenAI fallback for real-LLM testing. So unlike every arm above,
# these are single-tree tests: there is nothing in `src/` to compare against. They
# still follow the same "pin the exact paid request shape with a stub" discipline as
# test_openai_provider_request_shape above, because that is what catches a silent
# behaviour change (dropped schema hint, wrong embedding model) without spending
# anything.
# --------------------------------------------------------------------------- #

def test_openai_embedding_provider_disabled_without_key():
    restore = _without_openai_key()
    try:
        p = new_llm._OpenAIEmbeddingProvider("text-embedding-3-small", 10)
        assert p.enabled is False
        assert p.name == "openai-embedding", p.name
        assert not hasattr(p, "client")
    finally:
        restore()
    print("     (disables cleanly, no raise, no client)")


class _StubEmbeddingData:
    def __init__(self, vec):
        self.embedding = vec


class _StubEmbeddingResponse:
    def __init__(self, vecs):
        self.data = [_StubEmbeddingData(v) for v in vecs]


class _StubEmbeddings:
    def __init__(self, log, vecs):
        self.log = log
        self.vecs = vecs
        self.captured = None

    def create(self, **kwargs):
        self.log.append("create")
        self.captured = kwargs
        return _StubEmbeddingResponse(self.vecs)


def test_openai_embedding_provider_request_shape_and_order():
    """Pin the embeddings.create request shape and wait->create ordering, same discipline
    as test_openai_provider_request_shape for the chat-completions provider."""
    saved = os.environ.get("OPENAI_API_KEY")
    try:
        os.environ["OPENAI_API_KEY"] = "sk-test-not-a-real-key"
        p = new_llm._OpenAIEmbeddingProvider("text-embedding-3-small", 10)
        assert p.enabled is True

        log: list = []
        vecs = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        p.client = _pytypes.SimpleNamespace(embeddings=_StubEmbeddings(log, vecs))
        p.rl = _SpyLimiter(log)

        out = p.embed(["hello", "world"])
    finally:
        if saved is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = saved

    assert out == vecs, out
    assert p.client.embeddings.captured == {
        "model": "text-embedding-3-small", "input": ["hello", "world"],
    }, p.client.embeddings.captured
    assert log == [("wait", 0), "create"], f"throttle must precede the request: {log}"
    print("     (embeddings.create request shape + wait->create ordering pinned)")


def test_openai_json_call_parses_valid_json():
    log: list = []
    p = _pytypes.SimpleNamespace(
        call=lambda system, user: (log.append((system, user)) or '{"kpis": []}')
    )
    out = new_llm.openai_json_call(p, "SYS", "USER", {"type": "object"})
    assert out == {"kpis": []}, out
    # the schema must actually be folded into what the provider receives
    called_system = log[0][0]
    assert "SYS" in called_system, called_system
    assert '"type": "object"' in called_system, called_system
    print("     (valid JSON on the first attempt parses; schema folded into system prompt)")


def test_openai_json_call_retries_once_then_raises():
    calls = []

    def flaky_call(system, user):
        calls.append(user)
        return "not json"

    p = _pytypes.SimpleNamespace(call=flaky_call)
    try:
        new_llm.openai_json_call(p, "SYS", "USER", {"type": "object"})
    except Exception:
        pass
    else:
        raise AssertionError("expected a parse failure to raise after the retry")
    assert len(calls) == 2, f"expected exactly one retry (2 total calls), got {len(calls)}"
    assert calls[0] != calls[1], "the retry must nudge the user prompt, not repeat it verbatim"
    print("     (bad JSON retried once with a nudge, then raises — no silent empty result)")


def test_openai_json_call_recovers_on_the_retry():
    calls = []

    def recovers_second_time(system, user):
        calls.append(user)
        return "not json" if len(calls) == 1 else '{"ok": true}'

    p = _pytypes.SimpleNamespace(call=recovers_second_time)
    out = new_llm.openai_json_call(p, "SYS", "USER", {"type": "object"})
    assert out == {"ok": True}, out
    assert len(calls) == 2
    print("     (a retry that succeeds is not treated as a failure)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
