# Stage 07 — claim ↔ conduct cross-check

```bash
python src/run.py claims_vs_conduct --dry-run              # preview pairs (still calls the LLM)
python src/run.py claims_vs_conduct --ticker AAA
python src/run.py claims_vs_conduct --provider-order deepseek --max-llm-pairs 200
```

Module: `src/esg_kg/crosscheck/claims_vs_conduct.py` · Output:
`graph_output/crosscheck/<ticker>_claim_assessments.json` (+ `<ticker>_crosscheck_stats.json`,
`crosscheck_edges.json`, `adjudication_cache.json`)

The analytical core. For every `SustainabilityClaim` on the issuer it retrieves conduct
candidates, has them adjudicated, writes schema-legal linking edges, and emits an
**advisory evidence dossier** — never a greenwashing score or label.

**This is the only stage where an LLM verdict is mandatory.**

---

## 1. Framing (non-negotiable)

No ground-truth greenwashing labels exist for Vietnamese companies
([SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §1.1). Therefore:

- the output field is `assessment` with three values — `appears_supported`,
  `appears_contradicted`, `unverified_insufficient_evidence`;
- `assessment_is_advisory` is always `true`;
- `caveats` always includes the no-ground-truth note;
- there is no score, no probability, and no binary label anywhere in the output.

This is the in-graph **inversion** of the reference implementation's detection steps: their
claim is an external CSV row scored against a KG with gold labels; here the claim is a node
already *in* the graph, cross-checked against conduct nodes already in the graph, producing
advisory evidence links.

---

## 2. Pipeline

### 6a — candidate retrieval (deterministic, cheap)

The conduct pool is the issuer's nodes in `CONDUCT_CLASSES` = `Controversy`, `Penalty`,
`MediaReport`, `KPIObservation`, `ThirdPartyVerification`.

**Two retrieval tiers.**

**Token tier.** Vietnamese-segmented topic overlap between the claim's text (plus its
keywords) and the candidate's text, requiring at least `--min-topic-overlap` shared tokens
(default **2** — a single shared token is too weak a signal on Vietnamese text). Then a
temporal filter: candidates outside `[claim_year − window_before, claim_year + window_after]`
are dropped, **unless the candidate's date is uncertain**, in which case it is kept rather
than silently discarded. Defaults are `--window-before 1` and `--window-after 50`: conduct
may precede a claim by at most a year, and follow it indefinitely.

**Indicator tier.** Conduct joined to the claim through the indicator axis
(`claim -[:alignsWithIndicator]-> StandardIndicator <-[:measuredUnder]- conduct`) is
injected with a boosted score and **bypasses the token gate entirely**. This matters
because a claim and its own measurement frequently share zero tokens — *"giảm phát thải"*
versus *"12.450 tCO2e"*. The temporal window still applies. Every such pair is stamped
`retrieval_tier: "indicator"` in the dossier; token-tier pairs are `"token_overlap"`.

Candidates are ranked by (score, recency) and capped at `--top-k` (default 8).

`--embed` adds optional embedding-based ranking; it is off by default because deterministic
retrieval is free and reproducible.

### 6b — adjudication (mandatory)

Each `(claim, candidate)` pair is sent with a fixed system prompt and must return
`supports` / `contradicts` / `irrelevant`, with a confidence and a rationale.

- **No deterministic fallback.** If no provider is available, the run aborts up front with
  an explicit error rather than silently degrading into a weaker mode.
- Pairs are adjudicated **highest-overlap first**, up to `--max-llm-pairs` (default 300),
  concurrently across `--max-workers`, throttled by the shared rate limiter.
- `budget_hit` is recorded when there were more pairs than budget, and the affected claims
  get a caveat saying their evidence was not evaluated. Truncation is reported, never
  silent.
- Verdicts are cached content-addressed on `(claim_text, evidence_text, evidence_meta)` —
  never on position in a batch, because candidate ranking moves between runs. A re-run is
  free and reproducible.

`ADJUDICATE_SYSTEM` is pinned byte-for-byte by tests.

### 6c — linking edges

| Verdict | Evidence class | Edge |
|---|---|---|
| `supports` | `ThirdPartyVerification`, `KPIObservation` | `verifiedBy` |
| `contradicts` | `Controversy` | `contradictedBy` |
| `contradicts` | `MediaReport`, `Penalty` | `contradictedByMedia` |
| `irrelevant` | — | none (but the pair counts as adjudicated) |

Each edge carries `llm_suggested=true`, the confidence, the rationale, the provider and the
`source_type`, so every advisory link is attributable and re-runnable. An edge is only
written if the schema declares that pair legal.

Contradictions the schema cannot express — notably `Claim → KPIObservation` — stay in the
dossier and reach Neo4j through the advisory layer instead ([CLAIM_LEDGER.md](CLAIM_LEDGER.md)).

### 6c-guard — self-verification

See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) §6.4 for the rationale. Implementation: when a
`supports` verdict's evidence comes from a company-owned domain (a small per-ticker set
plus an issuer-core-token check — `anphat`, `aneco`, `aaplastic` for AAA), the item is
**still recorded** in `supporting_evidence` with `independent: false` and a `guard`
explanation, but **no `verifiedBy` edge is written** and it does not count toward
`appears_supported`.

Visible but not counted. Hiding it would lose information; counting it would let a company
verify itself.

### 6d — assessment and dossier

```
if any contradicting evidence          → appears_contradicted
elif any INDEPENDENT supporting        → appears_supported
else                                    → unverified_insufficient_evidence
```

Contradiction outranks support in a mixed dossier, and the mixed case adds its own caveat.
Note the middle branch: it tests `independent` support, not all support — the guard is what
makes that distinction real.

Caveats are generated for: no ground truth (always), no independent conduct for the issuer
at all, no topically-related evidence for this claim, evidence skipped due to budget, an
uncertain publish date among the evidence, and mixed evidence.

---

## 3. Dossier shape

```jsonc
{
  "claim_id": "claim_a1b2c3d4e5f6a7b8",
  "claim_text": "...",
  "claim_node_index": 1234,
  "assessment": "appears_contradicted",
  "assessment_is_advisory": true,
  "caveats": ["No ground-truth greenwashing label exists; this is an advisory opinion.", "..."],
  "supporting_evidence": [
    { "node_index": 5678, "class": "KPIObservation", "text": "...",
      "source_domain": "vietstock.vn", "date": "2023-05-01", "year": 2023,
      "confidence": 0.8, "rationale": "...", "provider": "gemini",
      "date_uncertain": false, "retrieval_tier": "indicator", "independent": true }
  ],
  "contradicting_evidence": [ /* ... */ ]
}
```

`node_index` and `claim_node_index` are **positions** in the resolved graph's node array.
This is why upstream stages must never reorder that array, and why `neo4j_sync` resolves
claims by stable id first rather than trusting position blindly.

### 3.1 The stats file

`<ticker>_crosscheck_stats.json` records the issuer, claim count, conduct pool by class,
retrieval counts (including `indicator_tier_pairs` and `claims_with_indicator_link`), the
assessment histogram, edges written, LLM calls and failures per provider, the parameters
used, and an explicit `coverage_caveat` string.

Read the histogram together with the pool size. On the pinned AAA run: 36 claims, a conduct
pool of 68, only 11 claims drew any candidate, 23 pairs adjudicated, and all 36 assessments
came back `unverified_insufficient_evidence`. That is a coverage result, not a clean bill of
health — which is precisely what the caveat says.

---

## 4. Providers

`--provider-order` is a comma-separated preference list; `gemini` is the default.
`deepseek` and `openai` are **swappable alternatives you opt into**, not a required
fallback cascade — set `--provider-order deepseek` to use DeepSeek alone. An unknown name
logs `Unknown adjudication provider — ignored`.

`Adjudicator` keeps its own small provider registry rather than using the shared
`build_llm_provider()` factory, because provider preference here is stage logic (prompt
text, verdict parsing, ordering), not kernel. See
[LLM_PROVIDERS_AND_CACHING.md](LLM_PROVIDERS_AND_CACHING.md).

Historical note: OpenAI was the sole provider here from 2026-07-27 to 2026-08-04 while the
Gemini project was billing-blocked, then removed outright, then re-added on 2026-08-06 as an
opt-in REST provider. Some cached artifacts under `graph_output/crosscheck/` are named
`adjudication_cache_openai*.json` from that period.

---

## 5. Flags

| Flag | Meaning |
|---|---|
| `-i`, `-s`, `-o` | Input graph, schema, output directory |
| `--ticker` | Which issuer to process |
| `--top-k` | Candidates kept per claim (default 8) |
| `--window-before`, `--window-after` | Temporal window in years (1, 50) |
| `--min-topic-overlap` | Token-tier gate (default 2) |
| `--max-llm-pairs` | Adjudication budget (default 300) |
| `--provider-order` | Comma list: `gemini`, `deepseek`, `openai` |
| `--model` | Model id |
| `--max-workers`, `--rate-limit` | Concurrency and throttle |
| `--embed` | Optional embedding re-ranking |
| `--cache` / `--no-cache` | Adjudication cache path / disable |
| `--to-neo4j`, `--database` | Write the linking edges straight to Neo4j |
| `--dry-run` | Write no files — **still calls the LLM** |

> `--dry-run` here is not free. Unlike most stages it does not return before the provider
> is built; it exercises the whole retrieval and adjudication path and simply skips the
> writes.

---

## 6. Known limitations

- **Retrieval does not route through graph structure.** The token tier is global overlap,
  and the indicator tier only reaches conduct joined by an indicator. A subsidiary's or a
  named facility's misconduct never reaches the parent's claims. See
  [ROADMAP.md](ROADMAP.md) §2.2 — `config/subsidiaries/` already holds the ownership data
  this would need.
- **No always-include tier.** A `Penalty` with no token overlap and no indicator link is
  never considered, even though penalties are the most checkable evidence the graph holds.
- **`signals` are not written.** `kpi_gap`, `structural_contradiction` and
  `broken_promise` are read by stages 08 and 09 but never produced here. See
  [ROADMAP.md](ROADMAP.md) §2.1.
- **Assessment is per claim, not per company.** There is deliberately no company-level
  roll-up, because aggregating advisory opinions into one figure would reconstruct the
  score this design refuses to emit.

---

## 7. Tests

`python test/test_esg_kg_crosscheck.py` — the full retrieval, stub adjudication and
dossier path on the real resolved graph in one arm (masking the non-deterministic
`recorded_at`), plus synthetic fixtures for the self-verification guard, the
contradiction-beats-support priority, and a malformed verdict reply being refused rather
than crashing. `ADJUDICATE_SYSTEM` is pinned byte-for-byte.

`python test/test_step01_step07_language_guard.py` — output-language requirements.
