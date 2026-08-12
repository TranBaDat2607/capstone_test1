# Stage 02 — temporal triple extraction

```bash
python src/run.py extract_triples --dry-run --doc AAA_2023      # offline preview
python src/run.py extract_triples --doc AAA_2023 --source report
python src/run.py extract_triples -i <news_preprocessed.jsonl> --source news
```

Module: `src/esg_kg/graph/extract_triples.py` · Output:
`graph_output/graphs/<pdf_stem>/page{N}.json`

The stage that turns text into graph. For each page it combines the page text, the KPI
records from stage 01, and `config/schema.json`, and asks the model for temporal triples,
which are then converted into a `{nodes, edges}` page graph.

**Costs money.** Gemini by default; `--provider deepseek` is a swappable alternative.

---

## 1. Inputs and outputs

```
labeled JSONL (page text)  ─┐
kpi_output/<doc>_kpis/     ─┼──▶ prompt ──▶ LLM ──▶ triples ──▶ page graph
config/schema.json         ─┘
```

| Path | Contents |
|---|---|
| `graph_output/graphs/<pdf_stem>/page{N}.json` | valid temporal graph for that page |
| `graph_output/graphs/<pdf_stem>/page{N}_bugged.json` | triples that failed schema validation |
| `graph_output/graphs/<pdf_stem>/page{N}_malformed.txt` | replies that were not parseable JSON |
| `graph_output/debug_outputs_per_page/<pdf_stem>/…txt` | the prompt actually sent |

Keeping the three failure buckets separate is what makes the next stage possible: `bugged`
triples are what `fix_triples` phase 2 repairs, and `malformed` replies are a prompt
problem, not a schema problem.

---

## 2. Two prompts, one code path — `--source`

| Mode | Prompt | Primary classes | Stamp |
|---|---|---|---|
| `--source report` (default) | `TEMPORAL_GRAPH_PROMPT_TEMPLATE` | `SustainabilityClaim`, `Goal`, `Initiative`, reported `KPIObservation`, `Emission`, `Waste` | `source_type=report` |
| `--source news` | `NEWS_GRAPH_PROMPT_TEMPLATE` | `Controversy`, `MediaReport`, `Penalty`, observed `KPIObservation`, `ThirdPartyVerification` | `source_type=news` |

Both templates are pinned byte-for-byte by tests. A reworded prompt still "works" while
silently changing every extraction, so the pin is the regression net.

### 2.1 The news prompt's extra obligation: `date_uncertain`

News-derived observation classes carry a required boolean. The prompt must decide, per
fact, whether the article states an explicit date or period (`false`) or whether the
article's publish date is being used as a proxy (`true`). This is not optional and must
never be silently defaulted — `fix_triples` phase 1.5 fills in a missing value on news T2
nodes precisely because a missing decision is a bug, not a neutral state.

### 2.2 Structural anchoring (P3)

Both prompts require the model to attempt the anchor edges the schema already defines —
`observedAtFacility`, `locatedIn`, `enforcedBy`, `mentionsProduct`, `manufacturedAt` —
whenever the sentence names a facility, place or authority. No new classes, no new labels:
just using the schema fully. See [TEMPORAL_KG_DESIGN.md](TEMPORAL_KG_DESIGN.md) §3 (P3) for
why this is the highest-leverage prompt rule in the pipeline.

### 2.3 The language guard

Both templates require **Vietnamese** output for `name` / `title` / `description` and other
free text, and their worked examples no longer model English drift. The failure this
prevents is subtle: an English-translated company name splits one entity into two at the
resolution stage. `test/test_step02_language_guard.py` pins the requirement in the prompt
text; the consequence-guard lives downstream in `fix_triples`
(`preserve_property_values`), so a repair model cannot undo it either.

---

## 3. Deterministic `claim_id`

`SustainabilityClaim.identity_keys` is exactly `["claim_id"]`, and the stable entity id is
hashed straight off that property. Left to the model, `claim_id` is free text invented per
call — so re-running this stage over the identical sentence could mint a different id and
silently re-partition every already-paid cross-check dossier, because claim resolution in
`neo4j_sync` is 100% stable-id with no fallback.

`assign_deterministic_claim_ids` therefore **overwrites** whatever the model invented,
before the triples become a graph (node identity, and thus in-page dedup, is computed from
`claim_id`). The id is a pure function of content plus provenance:

```
claim_<sha1(source_doc | page | content_key | normalized_date)[:16]>
```

Two encodings of `content_key`, in preference order:

1. **Sentence-position anchor** — `pos:<sentence_index>:<start_token_offset>,…`.
   The claim's description is matched back to the page's real JSONL sentence rows by
   **longest common contiguous token run**, accepted at ≥ 0.7 overlap against the shorter
   side. Anchoring to a position rather than to the model's copied text survives
   re-transcription drift (different truncation point, punctuation, mild paraphrase).
2. **Text hash** — `text:<normalized description>`, the fallback when no confident anchor
   exists.

Three details that came out of measuring the real corpus (1,217 claims):

- **Contiguity, not set overlap.** Two different facts on the same page scored 0.5–0.6 on
  plain token-set overlap purely from shared Vietnamese function and business words.
  A contiguous run removes that ambiguity, which is why the threshold is 0.7 and not lower.
- **`(sentence_index, start_offset)`, not `sentence_index` alone.** Hashing on the sentence
  index produced 40 real collisions — one enumeration sentence listing several distinct
  facts for the same year. The start offset separates them; that gave zero collisions.
- **`date` is part of the basis.** An awards table repeating identical claim text for
  2009 / 2010 / 2011 would otherwise collapse into one node. The date here is extracted
  content, not an invented id.

360 of 1,217 claims get a confident anchor; the rest fall back to the text hash. The layer
is strictly additive — omitting the page rows reproduces the earlier behaviour exactly.

Pinned by `test/test_claim_id_deterministic.py`.

---

## 4. Providers and caching

| Provider | Flag | Context caching |
|---|---|---|
| Gemini (default) | `--provider gemini` or unset | `GeminiContextCache`, scoped per document |
| DeepSeek | `--provider deepseek` | none — always sends the full per-page prompt |

When a provider is explicitly set, the stage goes through `build_llm_provider()` and calls
`provider.call(...)` instead of the SDK's `generate_content(...)`, always with the full
per-page prompt (`build_page_prompt`, never the cache-shortened `build_page_body`). There
is no DeepSeek equivalent to Gemini's explicit context caching, so **`--no-context-cache`
is a no-op on a DeepSeek run**.

The Gemini cache is memoized by `sha256(static_content)`, which lets one instance serve a
per-document scope here (a new hash each time company/year change) and a whole-run scope in
other stages, without either caller tracking cache lifetime. This stage's system
instruction is constant (`"Return *only* valid JSON — no prose."`), so it is baked into the
cache itself rather than passed alongside it — the API rejects a call that sets both.

Details in [LLM_PROVIDERS_AND_CACHING.md](LLM_PROVIDERS_AND_CACHING.md).

---

## 5. Flags

| Flag | Meaning |
|---|---|
| `-i` | Input labeled / preprocessed JSONL |
| `-s` | Schema path (default `config/schema.json`) |
| `--kpi-dir` | Where stage 01's KPI JSONs are (default `kpi_output/`) |
| `-o` | Output directory |
| `--source report\|news` | Which prompt, and which `source_type` stamp |
| `--doc`, `--limit-docs`, `--all` | Scope |
| `--all-pages` | Do not restrict to ESG pages |
| `--max-workers`, `--rate-limit` | Concurrency and throttle |
| `--provider gemini\|deepseek` | Provider; defaults to `LLM_PROVIDER` env, else gemini |
| `--model` | Model id; defaults to the chosen provider's own default |
| `--no-context-cache` | Disable Gemini context caching (no-op on DeepSeek) |
| `--dry-run` | Build prompts and report counts, call nothing, write nothing |

---

## 6. Triples → graph

`triple_list_to_graph` converts the flat triple list into `{nodes, edges}`:

- node identity comes from the class's `identity_keys` via `get_stable_entity_id`, so
  repeated mentions on one page collapse;
- `OBSERVATION_CLASSES` (`KPIObservation`, `Emission`, `Waste`) are *not* collapsed the
  same way — an observation is one node per occurrence by design (T2, see
  [SCHEMA_EXPLAINED.md](SCHEMA_EXPLAINED.md));
- edges reference nodes by index;
- every node and edge is stamped with the temporal fields and `source_type`.

Edge **direction is not validated here** — that is `fix_triples`' job, which is why this
stage unpacks `load_schema_sets` and discards `edge_directions`.

---

## 7. Tests

`python test/test_esg_kg_extract_triples.py` — kernel-reuse identity checks, a real-corpus
arm over 13 documents, both prompt templates pinned byte-for-byte, `build_page_prompt`
compared for both `--source` modes, and the paid path driven by four deterministic stub
response shapes.

`python test/test_step02_language_guard.py` — the Vietnamese-output requirement.

`python test/test_claim_id_deterministic.py` — id derivation, drift robustness, and
uniqueness against the real resolved graph.
