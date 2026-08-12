# LLM providers, rate limiting and caching

**Audience:** anyone adding an LLM call, swapping a provider, changing a model, or
wondering why a re-run cost nothing.

Everything here lives in `src/esg_kg/core/llm.py` and `src/esg_kg/core/llm_cache.py` —
the kernel modules every paid stage imports. Stage-specific prompt text and verdict parsing
stay in the stage.

---

## 1. Which stages spend money

| Stage | LLM | Provider choice |
|---|---|---|
| `extract` (01) | required | Gemini only |
| `extract_triples` (02) | required | `--provider gemini\|deepseek` |
| `fix_triples` (03, phase 2) | required | Gemini only |
| `entities` (05, Stage B.2 + C) | optional (`--no-llm` skips) | Gemini only |
| `align_claims` (05d) | required | `--provider gemini\|deepseek` |
| `claims_vs_conduct` (07) | **mandatory, no fallback** | `--provider-order gemini,deepseek,openai` |

Everything else — `quality`, `anchor_kpi`, `canonicalize`, `issuer`, `provenance`,
`indicators`, `export_kgc`, `neo4j_load`, `neo4j_sync`, `claim_ledger` — is free and
offline.

`extract`, `fix_triples` and `entities` are Gemini-only because they use Gemini-specific
explicit context caching that has no equivalent in the REST providers. Making them
swappable would be a separate, larger redesign, not a flag.

---

## 2. Configuration

All of it lives in `.env` at the repo root. Every stage loads that file regardless of the
working directory. `.env` is git-ignored — never commit it, and never share a key through
the dataset repo.

```dotenv
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash-lite     # optional; this is the default

DEEPSEEK_API_KEY=...                    # only if you use --provider deepseek
DEEPSEEK_MODEL=deepseek-v4-flash        # optional

OPENAI_API_KEY=...                      # only if you use --provider-order openai
OPENAI_MODEL=gpt-4o-mini                # optional

LLM_PROVIDER=gemini                     # default provider for stages that accept one
```

### 2.1 One model name, not six

`DEFAULT_MODEL` in `core/llm.py` reads `GEMINI_MODEL` and is imported by every LLM stage.
Each stage used to hardcode its own copy — six places to edit for a model swap, which is
exactly how one got missed. **Changing the model for the whole pipeline is an `.env` edit.**

`LLM_PROVIDER` is read *fresh* by the factory, not frozen at import, so a run can pick its
provider without re-importing the module.

### 2.2 One client constructor, not six

`build_gemini_client()` is the single place that turns `GEMINI_API_KEY` into a working
`genai.Client`, or `None`. It never raises: every call site bails out on `None` the same
way, instead of six slightly different getenv-and-construct blocks each deciding for itself
how to fail.

---

## 3. The provider contract

```python
class _Provider:
    name: str
    enabled: bool
    calls: int
    failures: int
    def call(self, system: str, user: str) -> str: ...
```

Three implementations:

| Class | Transport | Notes |
|---|---|---|
| `_GeminiProvider` | `google.genai.Client` | The default. Supports explicit context caching |
| `_DeepSeekProvider` | OpenAI-compatible REST via `requests` | No SDK dependency |
| `_OpenAIProvider` | Chat Completions REST via `requests` | No SDK dependency; opt-in for `claims_vs_conduct` |

Neither REST provider reintroduces a vendor SDK — both are plain JSON over `requests`.

### 3.1 `build_llm_provider()` — the factory

```python
provider = build_llm_provider(provider=args.provider, model=args.model,
                              rate_limit=args.rate_limit)
```

Resolution order: an explicit argument (a stage's own `--provider`), then the
`LLM_PROVIDER` env var, then `"gemini"`. When `model` is omitted it falls back to **that
provider's own default**, never the other's — which would silently send a Gemini model id
to DeepSeek.

Use this instead of hardcoding `_GeminiProvider(...)`, so "which provider" stays one switch.

`claims_vs_conduct`'s `Adjudicator` deliberately keeps its own small registry rather than
using the factory: provider preference there is stage logic (ordering, verdict parsing,
prompt text), not kernel.

### 3.2 Behaviour that is load-bearing, not style

`temperature=0` and JSON response mode (`response_mime_type="application/json"` for Gemini,
`response_format={"type": "json_object"}` for the REST providers) are **behaviour**. Callers
parse the reply as JSON and the pipeline assumes determinism. Dropping either still "works"
at runtime while quietly changing every paid verdict. `test/test_esg_kg_llm.py` pins the
request shape with a stub client, so that regression is caught without spending anything.

---

## 4. Rate limiting

`RateLimiter` is a per-client sliding-window RPM throttle, default 10 RPM.

Three details that matter and are pinned by tests:

- the window is keyed **per `client_idx`**, with its own deque *and* its own lock;
- the eviction boundary is `>= 60` seconds;
- the queue is re-swept **after** sleeping, not before.

Stage code calls it with `client_idx=0` because this project uses a single API key; the
multi-key shape is kept intact.

`DEFAULT_RATE_LIMIT` is also defined locally in `fix_triples`. Both are 10 today, and that
duplication is **deliberate** — importing one into the other would tie that stage's throttle
to another stage's. Only `RateLimiter` itself is shared. A same-named constant is not
automatically a shared constant.

---

## 5. Two different caches

They solve different problems and must not be confused.

### 5.1 Result cache — `core/llm_cache.py`

`ContentCache` is an **application-level cache of the result**, so the same content is never
paid for twice.

- **Key** = `sha256` of whatever the caller passes as parts — the stage's own business key
  (a triple dict, a `{class, a, b}` pair, a `(claim_text, evidence_text, evidence_meta)`
  tuple) — **never a position in a batch**. Batch boundaries and candidate ranking move
  between runs; a positional key would silently hand one call's result to a different call.
- **Value** = whatever the caller wants to remember, including the model's raw reply, or
  `None` for "the model declined".
- Persisted as JSON, written only when something changed, corrupt-file-safe on load.
- A same-run repeat is already free: `entries` is a plain in-memory dict populated
  synchronously by `put()`, so a second identical call hits before any disk I/O.
- `get`/`put` take a lock, because `claims_vs_conduct` adjudicates concurrently. The lock
  guards only the dict access, never the network call, so it adds no serialization.

Two named wrappers use it: `RepairCache` (phase-2 triple repairs) and `AdjudicationCache`
(Stage C same-entity verdicts). Both keep the exact hash their hand-written predecessors
produced, so pre-existing cache files still hit.

**What gets cached: paid *and* non-deterministic results only.** Embeddings are billed but
deterministic, so they are deliberately not cached — see
[ENTITY_RESOLUTION.md](ENTITY_RESOLUTION.md) §3.

### 5.2 Prompt cache — `GeminiContextCache`

Provider-side. One `client.caches.create()` per unique static prefix, reused via
`cached_content=` across every `generate_content` call that shares it, memoized by
`sha256(static_content)`. That memoization is what lets one instance serve a whole-run
scope (`extract`, `fix_triples`: one hash for the entire invocation) and a per-document
scope (`extract_triples`: a new hash whenever company/year change) without either caller
tracking cache lifetime.

**Two traps:**

1. **Gemini rejects a call that sets both `cached_content` and `system_instruction`** (or
   `tools`/`tool_config`). A caller whose system instruction is *constant* should pass it in
   at cache creation so it is baked in. A caller whose system instruction *varies* per call
   — `extract`, which embeds company/page/document name — cannot cache it at all and must
   fold that text into `contents`. Getting this wrong 400s every page.
2. **Creation failure is memoized as `None`**, so it is not retried on every subsequent
   call; the caller falls back to sending the static content inline. Caching must never
   break the pipeline.

`--no-context-cache` disables it. It is a **no-op on DeepSeek**, which has no equivalent
and always sends the full prompt.

---

## 6. Provider history

Worth knowing, because the code carries traces of it.

| Date | Change |
|---|---|
| 2026-07-27 | OpenAI added while the Gemini project was 403 billing-blocked |
| 2026-08-04 | OpenAI removed **outright**, SDK dependency and every `--provider openai` flag deleted, once Gemini billing was restored |
| 2026-08-05 | Default model changed to `gemini-2.5-flash-lite`, and hardcoded copies replaced by one constant |
| 2026-08-06 | DeepSeek added as an opt-in REST provider; OpenAI **re-added** the same way |

The distinction the code insists on: 2026-07-27 was a *forced* fallback during an outage;
2026-08-06 is a *swappable alternative you opt into*. Gemini remains the working default,
and there is no automatic cascade between providers.

Cached artifacts named `adjudication_cache_openai*.json` under `graph_output/crosscheck/`
date from the 2026-07/08 OpenAI period.

---

## 7. Testing paid code for free

The technique used throughout: **stub under the abstraction layer, not around the whole
function.**

If a stage goes through `_Provider`, replace that. If it constructs `google.genai.Client`
directly (`extract`, `entities`), replace the client. If it lazily imports a driver class
(`neo4j_load`, `neo4j_sync`), replace that attribute. The stub answers deterministically —
usually from a CRC of the prompt — so the real logic still runs, just against fake I/O.

Tests that cover this area:

- `test/test_esg_kg_llm.py` — `RateLimiter` through a fake clock (never really sleeps) and
  the paid request shape;
- `test/test_esg_kg_llm_cache.py` — key derivation, same-run hits, corrupt-file safety;
- `test/test_esg_kg_gemini_cache.py` — context-cache behaviour and the
  `system_instruction` conflict.

Real-LLM tests exist but are gated behind `RUN_LLM_INTEGRATION_TESTS=1` /
`RUN_LLM_SYSTEM_TEST=1` (`test/test_esg_kg_integration_llm.py`,
`test/test_esg_kg_system_llm.py`). They cost money and are deliberately **not** part of the
free offline suite. Never verify a change by re-running a paid stage.
