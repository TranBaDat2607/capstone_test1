# Stage 01 — KPI extraction from labeled JSONL

```bash
python src/run.py extract --doc AAA_2023
python src/run.py extract --all                 # every document
```

Module: `src/esg_kg/kpi/extract.py` · Output: `kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json`

Reads the sentence-level labeled JSONL and produces typed `KPIObservation` records per
page, against the 35 controlled indicators in `kpi_definitions_construction.json`
(repo root). These records are an input to `extract_triples` (02), which combines them with
the page text to build graph triples.

**Costs money.** Gemini only — there is no `--provider` flag on this stage.

---

## 1. What it does

```
data/labeled/.../*.jsonl
   │  group sentences by (source_pdf, page)
   ▼
page text (ALL sentences on the page, not just esg=true ones)
   │  keep the page only if it has ≥ 1 esg=true sentence
   ▼
Gemini + structured output + the 35-KPI vocabulary
   ▼
kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json
```

The stage mirrors `EmeraldMind/src/EmeraldKG/1-kpi-extraction.py` with four deliberate
differences: the input is already-extracted labeled JSONL rather than PDFs; the KPI schema
is the single-sector construction vocabulary; the model is Gemini via the official
`google-genai` SDK; and there is one API key with an internal rate limiter rather than a
multi-key pool.

### 1.1 Why the whole page is sent but only ESG pages are selected

Two different decisions that are easy to confuse:

- **Page selection** uses the ESG gate: a page with no `esg=true` sentence is skipped and
  gets an empty output file. This is the cost control.
- **Page content** is the *full* reconstructed page text, including non-ESG sentences.
  A KPI table row often carries its unit, year or scope in a neighbouring sentence the
  classifier did not mark ESG. Sending only the ESG sentences would silently truncate the
  numbers.

---

## 2. Output shape

One file per page, holding a list of KPI objects, each with its observations:

```jsonc
[
  {
    "kpi_type": "TT96-6.1.1",           // a controlled id when matched, else raw wording
    "title": "Tổng phát thải khí nhà kính",
    "observations": [
      { "value": 12500.0,
        "unit": "tCO2e",
        "kind": "achieved",             // baseline | target | achieved | projection
        "direction": "absolute",        // absolute | reduction | increase
        "year": 2023,
        "target_year": null,
        "baseline_year": null,
        "source_id": "AAA_2023_42_7",   // <source_pdf>_<page>_<sentence_index>
        "snippet": "..." }
    ]
  }
]
```

`kind` and `direction` are enums in the response schema, not free text — the distinction
between a *target* of −20% and an *achieved* −20% is the whole basis of any later
promise-versus-delivery check, so the model is not allowed to blur it.

`source_id` is what keeps sentence-level traceability alive: `anchor_kpi` (03b) and
`provenance` (05b) both resolve it back to the source sentence later.

### 2.1 Response normalization

`normalize_kpi_response` runs on every reply: a trailing `%` is moved out of the value into
the unit, numeric strings become floats, and year-like fields become integers. Models
return `"12.5%"` and `"2023"` often enough that parsing this downstream would be a
recurring bug.

---

## 3. Cost controls

| Mechanism | Effect |
|---|---|
| ESG page gate | Pages with no `esg=true` sentence are never sent |
| Idempotent skip | An existing output file means the page is skipped — a re-run costs nothing for work already done |
| `GeminiContextCache` | The static prefix (the 35-KPI vocabulary) is uploaded once via `client.caches.create()` and reused across every call in the run |
| `--max-workers` | Concurrency, throttled by the shared `RateLimiter` |
| `--limit-docs`, `--doc` | Scope the run |

### 3.1 The context-cache constraint worth knowing

Gemini rejects a `generate_content` call that sets **both** `cached_content` and
`system_instruction`. This stage's system instruction embeds the company, page and document
name, so it *varies per call* and cannot be baked into the cache. Once a cache handle is
in use, that text is folded into `contents` instead. Getting this wrong 400s every page —
it did, before the fix.

Cache creation failure (content below the ~2048-token minimum, permission, network) is
caught and memoized as `None`, so it is not retried on every subsequent call; the stage
falls back to sending the vocabulary inline. **Caching must never break the pipeline.**

`--no-context-cache` disables it entirely.

---

## 4. Flags

| Flag | Meaning |
|---|---|
| `-i` | Input labeled JSONL |
| `-k` | KPI definitions file (default: `kpi_definitions_construction.json` at the repo root) |
| `-o` | Output directory (default `kpi_output/`) |
| `--doc <substr>` | Only documents whose stem contains this |
| `--limit-docs N` | Cap the number of documents |
| `--all` | Every document in the input |
| `--all-pages` | Do not restrict to ESG pages (expensive; diagnostic use) |
| `--max-workers N` | Concurrent page requests |
| `--model` | Override the model; default comes from `GEMINI_MODEL` in `.env`, else `gemini-2.5-flash-lite` |
| `--no-context-cache` | Disable explicit context caching |

There is **no `--dry-run`** on this stage and no provider flag. The 2026-07-29 → 08-04
`--provider openai` path was removed when the project went back to paying only for Gemini.

---

## 5. Model configuration

The model id is **not hardcoded here**. `esg_kg.core.llm.DEFAULT_MODEL` reads
`GEMINI_MODEL` from `.env`, defaulting to `gemini-2.5-flash-lite`, and every LLM stage
imports that one constant. Changing the model for the whole pipeline is an `.env` edit, not
a code change. See [LLM_PROVIDERS_AND_CACHING.md](LLM_PROVIDERS_AND_CACHING.md).

---

## 6. Where it sits

```
labeled JSONL ──▶ [01 extract] ──▶ kpi_output/ ──┐
                                                  ├──▶ [02 extract_triples] ──▶ per-page graphs
labeled JSONL ────────────────────────────────────┘
```

`extract_triples` reads both the same labeled JSONL (for page text) and this stage's KPI
JSONs. Running 02 without 01 produces graphs with no quantitative backbone.

---

## 7. Tests

`python test/test_esg_kg_extract.py` — the pure JSONL helpers on the real corpus
(13 documents / 1,356 pages) plus the paid path driven by a stub over `google.genai.Client`
that answers deterministically from a CRC of the prompt, including the idempotency check
(an existing output file must skip without calling the client).

`python test/test_esg_kg_gemini_cache.py` — the context-cache behaviour, including the
`system_instruction` conflict.

`python test/test_step01_step07_language_guard.py` — the prompt must not drift into
producing English for Vietnamese source text.
