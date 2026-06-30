# Triplet extraction from labeled JSONL — purpose, reason and logic

Script: [`src/extract_triplet_from_jsonl.py`](../src/extract_triplet_from_jsonl.py)

This step turns the per-page KPI JSONs produced by
[`extract_kpi_from_jsonl.py`](../src/extract_kpi_from_jsonl.py) (plus the original
sentence-level labeled JSONL, used to reconstruct page text) into a **temporal ESG
knowledge graph** — one `page{N}.json` file per page, holding the `nodes` / `edges`
of a small subgraph extracted from that page.

It mirrors the role of EmeraldMind's `2-extract-triplet.py`, but is adapted to our
pipeline: it reads **the labeled JSONL** instead of PDF-derived `.txt` side products,
loads KPIs from **our** `kpi_output/` tree, and uses a **single** `GEMINI_API_KEY`
with an internal RPM throttle instead of a pool of six rotating keys.

---

## 1. Why this step exists

Step 1 gave us **typed KPI observations** (numbers, units, years, kind/direction).
That is one node class in the schema (`KPIObservation`) — but the knowledge graph
defined in [`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) has sixteen+ node classes
(`Organization`, `Person`, `Facility`, `Product`, `Material`, `Emission`, `Waste`,
`Standard`, `Certification`, `Regulation`, `Initiative`, `Goal`,
`SustainabilityClaim`, `ThirdPartyVerification`, `CarbonOffsetProject`, …) and
dozens of edge types (`reportsKPI`, `operatesFacility`, `holdsCertification`,
`emits`, `disposes`, `supersedes`, …).

KPI numbers without the **subject** (which company), the **target** (which
facility/material), and the **relationship** (who reports what, who emits what to
whom, when) are not actually a graph — they are a list. This step closes the loop:
for each page, the LLM reads the reconstructed page text plus the KPI list and
emits **triples** `(subject, predicate, object, temporal_metadata)` that together
form a small per-page subgraph.

"Temporal" means every node carries `valid_from` / `valid_to` / `is_current`, and
every edge carries `temporal_metadata.recorded_at`. This is what lets downstream
analytics ask *"what did AAA report about Scope-1 emissions in 2017 vs 2023?"*
without conflating versions.

We use an LLM (Gemini 2.5 Flash) and not rules for the same reason as step 1:
Vietnamese ESG prose is irregular, the same fact can be stated three different
ways, and the schema is rich enough that hand-writing patterns per (subject-class,
predicate, object-class) tuple is prohibitive. The structured-prompt approach plus
**schema validation in post** gives us a working recall-precision tradeoff at low
cost.

---

## 2. What it consumes and what it produces

**Inputs**

| Input | Default path | Role |
|------|------|------|
| Labeled JSONL | `data/labeled/annual_labeled/labeled_annual_report_company_aaa.jsonl` | Sentence stream; used to **reconstruct per-page text** via `build_page_text`. |
| Per-doc KPI dir | `kpi_output/<pdf_stem>_kpis/page_NNN_kpis.json` | Step-1 output, attached to the prompt as JSON evidence. |
| Graph schema | `config/schema.json` | Allowed entity classes, edge labels, identity keys. Used to validate triples. |

**Outputs** (default root: `graph_output/`)

```
graph_output/
  graphs/
    AAA_Baocaothuongnien_2011/
      page2.json              ← valid temporal graph {nodes, edges}
      page3_bugged.json       ← triples that failed schema validation
      page7_malformed.txt     ← LLM response that wasn't parseable JSON
  debug_outputs_per_page/
    AAA_Baocaothuongnien_2011/
      AAA_Baocaothuongnien_2011_p2.txt   ← prompt + raw response (truncated)
```

A non-empty `page{N}.json` looks like:

```json
{
  "nodes": [
    {
      "class": "Organization",
      "properties": {
        "name": "AAA",
        "industry": "Plastics",
        "valid_from": "2011",
        "valid_to": null,
        "is_current": true
      },
      "stable_id": "Organization|aaa"
    },
    {
      "class": "KPIObservation",
      "properties": {
        "kpi_type": "TT96-6.6.1",
        "title": "Mức lương/thu nhập trung bình của người lao động",
        "value": 4000000,
        "unit": "đồng/tháng",
        "kind": "achieved",
        "direction": "absolute",
        "year": 2011,
        "valid_from": "2011-01-01",
        "valid_to": "2011-12-31",
        "is_current": false
      },
      "stable_id": "KPIObservation|tt96-6.6.1|2011|null|null"
    }
  ],
  "edges": [
    {
      "subject": 0,
      "predicate": "reportsKPI",
      "object": 1,
      "temporal_metadata": {
        "valid_from": "2011-01-01",
        "valid_to": null,
        "recorded_at": "2011-01-01"
      }
    }
  ]
}
```

Per-page granularity is identical to step 1: it makes the run **resumable**
(crash at page 700 of 1,000 → re-run skips the 700), keeps each LLM call bounded
in context, and preserves provenance (page → source PDF → company → year).

---

## 2b. Pipeline at a glance

```mermaid
flowchart TD
    A[Labeled JSONL<br/>one sentence per line] --> B[Group rows by<br/>source_pdf, page]
    B --> C[Rebuild full page text<br/>build_page_text from step 1]
    K[kpi_output/&lt;stem&gt;_kpis/<br/>page_NNN_kpis.json] --> L[Attach KPI list<br/>for this page]
    C --> D{Any sentence<br/>esg=true on page?}
    D -- No --> E[Write empty graph<br/>nodes:[], edges:[]]
    D -- Yes --> F[Build prompt<br/>schema + page text + KPI]
    L --> F
    F --> G[Gemini 2.5 Flash<br/>response_mime_type=application/json]
    G --> H[Clean JSON<br/>fences / quotes / commas]
    H --> I{Triples list<br/>parseable?}
    I -- No --> M[pageN_malformed.txt]
    I -- Yes --> J[Validate against schema<br/>entity classes + edge labels]
    J --> N[pageN_bugged.json<br/>invalid triples]
    J --> O[triple_list_to_graph<br/>stable IDs + versioning]
    O --> P[pageN.json]
    E --> P
    P -.cached on next run.-> B
    Q[10-RPM rate limiter] -.- G
```

Solid arrows are the runtime data flow for one page; the dashed arrow on `P` is
the resumability shortcut — on a re-run, any `pageN.json` that exists is loaded
from disk and the LLM is not called for it.

---

## 3. Logic walkthrough

### 3.1 Reuse step-1 helpers — page text reconstruction

The script imports four helpers directly from
[`extract_kpi_from_jsonl`](../src/extract_kpi_from_jsonl.py) (both files live in
`src/`, so Python adds that to `sys.path` automatically when you run the script):

- `load_pages_from_jsonl(path)` — groups the JSONL into
  `{ source_pdf: { page: [(sidx, text, esg), ...] } }`.
- `build_page_text(rows)` — sorts the row tuples by `sentence_index` and joins
  with single spaces. We keep the **full** page (not just ESG sentences) so the
  LLM has context for subjects/dates referenced obliquely on the page.
- `page_has_esg(rows)` — used by the ESG-only gate (§3.5).
- `parse_company_year_from_filename(source_pdf)` — same `(company, year)` parser,
  so `Organization.properties.name` and the `REPORTING YEAR` placeholder come out
  identical to step 1's records.
- `select_documents(docs, args)` — same `--doc / --limit-docs / --all` selection
  semantics as step 1.

No copy-paste: the helpers stay single-source-of-truth in step 1.

### 3.2 KPI loading (`load_kpis_for_doc`)

For each selected document we look up `kpi_dir / "<pdf_stem>_kpis"` (default
`kpi_output/`) and glob `page_*_kpis.json`. The page number is parsed from the
filename with regex `page_(\d+)_kpis\.json`. Page numbering is **1-based**
throughout this script — step 1 emits `page_001_kpis.json` for page 1, and we use
the same key here and as the output filename `page1.json`. This is one of the
deliberate divergences from EmeraldMind step 2, which subtracted 1 to go
0-based; see §4.

If the KPI directory does not exist (step 1 has not been run for this doc) we
log a warning and proceed with an empty KPI map — the LLM still gets the page
text, just without the structured KPI hint.

### 3.3 Prompt assembly (`TEMPORAL_GRAPH_PROMPT_TEMPLATE`, `build_page_prompt`)

This is the **single most load-bearing constant** in the file, ported verbatim
from EmeraldMind's `2-extract-triplet.py:191`. Three placeholders:

- `{schema_json}` — the full `config/schema.json` pretty-printed into the prompt.
  We pass the entire ontology (it's ~700 lines but well under Gemini Flash's
  context budget) so the model sees every legal class and edge in one pass.
- `{company}` — from `parse_company_year_from_filename`, e.g. `AAA_Baocaothuongnien`.
- `{year}` — same source, cast to `int`. Used both in the temporal-inference rules
  ("If reporting year is {year}, and no end date is mentioned, set valid_to to null
  and is_current to true") and in the positive-example block.

`build_page_prompt` then appends `--- DOC page {p_no} ---` with the reconstructed
page text and, if non-empty, a `--- KPI OBSERVATIONS (page {p_no}) ---` JSON block.
The KPI block is the bridge from step 1: it tells the model "you don't have to
re-extract the number; here it is — use it as the `object` of a `reportsKPI`
edge."

### 3.4 Gemini call + 10-RPM rate limiter (`RateLimiter`, `call_llm`)

The call uses `response_mime_type="application/json"` only — **no**
`response_schema`. The schema here is too dynamic (each triple can have a
different subject/object class with different properties) to express as a single
OpenAPI-3 schema. We rely on the prompt + post-validation instead.

The `RateLimiter` class is ported verbatim. It is a per-`client_idx` token-bucket
where `wait_if_needed` blocks until fewer than `max_calls_per_minute` calls have
landed in the last 60 seconds. With our single-key setup `client_idx` is always
`0`, so the limit applies globally across worker threads. Default 10 RPM matches
the Gemini free tier — bump `--rate-limit` if you have a paid tier.

On a 429 ("rate limit exceeded") or quota error the call retries with
exponential backoff (2, 4 s). If **all** retries inside `call_llm` were 429s, it
returns `rate_limited=True` and the caller skips the page **without writing
anything** so a future re-run can retry. This is intentional: writing an empty
graph for a rate-limited page would silently lose data.

### 3.5 ESG-only gate

By default we only spend tokens on pages that have **at least one `esg=true`
sentence** (the upstream ViDeBERTa classifier's call). For pages that fail the
gate we write `{"nodes": [], "edges": []}` straight to disk and skip the LLM.
`--all-pages` overrides this and runs every non-empty page.

Same rationale as step 1: most pages of an annual report are financial tables,
shareholder lists, and photo plates. Skipping them is the biggest single cost
saving in the whole pipeline.

### 3.6 JSON recovery (`_clean_json_response`, `_parse_json_response`)

Even with `response_mime_type=application/json`, Gemini occasionally wraps the
JSON in markdown fences, prepends `"Here is the JSON:"`, or emits trailing
commas — particularly on long or complex responses. The cleaner is robust to:

- ```` ```json … ``` ```` fences
- Preambles starting with `"Here"` or `"I'll"`
- Truncated outputs (finds the first `[` and last `]`)
- Trailing commas before `]` or `}`
- `// …` and `/* … */` comments
- Single quotes (last-resort fallback re-tries with `'` → `"` substitution)

If everything fails, the raw response is dumped to `pageN_malformed.txt` for
manual inspection. We **do not** write an empty graph in that case — the page
file remains absent so a re-run will retry.

### 3.7 Schema validation (`_validate_extraction_format`, in-line check in `process_page`)

Two layers:

1. Inside `call_llm`, `_validate_extraction_format` returns a boolean used only
   for logging — it counts how many triples in the response have legal classes
   and a known predicate. If 0/N pass it warns but still returns the parsed list
   so the next stage can split valid vs invalid.
2. Inside `process_page` we run the same per-triple check again to *partition*
   the list: valid triples go into the graph, invalid ones are written verbatim
   to `pageN_bugged.json`. Keeping the invalid triples around (instead of
   dropping them silently) makes debugging much cheaper — you can grep them to
   discover predicates the model invented that should be added to the schema.

### 3.8 Triple → graph (`triple_list_to_graph`, `get_stable_entity_id`)

Once we have valid triples, each entity is hashed to a `stable_id` of the form
`Class|key1|key2|...` where `key1, key2, ...` come from
`identity_keys` in `config/schema.json` (e.g. `Organization` → `["name"]`,
`Emission` → `["category", "scope", "valid_from"]`).

Then a **versioning key** is computed:

- For **observation classes** (`KPIObservation`, `Emission`, `Waste`) the version
  key is `stable_id | sha-of-all-properties`. Every distinct observation is a
  distinct node — emissions in 2022 ≠ emissions in 2023 even with the same
  category/scope.
- For **entity classes** (`Organization`, `Facility`, …) the version key is
  `stable_id | valid_from | valid_to`. We only create a new node if the entity's
  temporal window changes, so AAA-the-organization is one node across all 13
  annual reports.

Nodes are deduplicated by version key; edges store integer indices into the
`nodes` array plus the `temporal_metadata` block.

### 3.9 Parallelism, resumability, failure isolation (`process_document`)

Pages of one document are processed concurrently via `ThreadPoolExecutor` with
`--max-workers` workers (default 4). The 10-RPM rate limiter is the real
bottleneck, so going past ~4 workers on a single free-tier key is wasted
parallelism — but the code handles it correctly (workers will block in
`wait_if_needed`).

Resumability is the same pattern as step 1: before each page is sent to the LLM,
`process_page` checks `out_file.exists()` and returns immediately if it does.
Combined with the "don't write on rate-limit" rule (§3.4), this means:

- Successful pages are cached and never re-billed.
- Rate-limited pages have no file → retried on the next run.
- Malformed-JSON pages have `pageN_malformed.txt` but **no** `pageN.json` →
  also retried.

### 3.10 Output layout

```
graph_output/
  graphs/
    <pdf_stem>/
      page{N}.json          ← always present once a page has been processed
      page{N}_bugged.json   ← only if N has invalid triples
      page{N}_malformed.txt ← only if a non-empty, unparseable response came back
  debug_outputs_per_page/
    <pdf_stem>/
      <pdf_stem>_p{N}.txt   ← prompt (first 2,000 chars) + full response
```

This matches the layout EmeraldMind's `3-fix-invalid-triplet.py` expects, so the
downstream cleanup step can consume our output without modification.

---

## 4. Differences from EmeraldMind's `2-extract-triplet.py`

| Aspect | EmeraldMind step 2 | This script | Why |
|---|---|---|---|
| Page-text source | per-page `.txt` files written by step 1 (`{company}_{year}_text/`) | reconstructed from labeled JSONL via `build_page_text` | Our step 1 doesn't write the `.txt` side product; we already have the sentences in JSONL. |
| Doc enumeration | `glob("*.pdf")` in `--input_dir` | unique `source_pdf` values in JSONL | Avoids needing a PDF on disk just to use it as a filename. |
| Page numbering | 0-based (line 100 / 132 subtract 1) | 1-based throughout | Matches step 1's `page_NNN_kpis.json` naming. Output is therefore `pageN.json` where N is the 1-based page. |
| API keys | `GEMINI_API_KEY_1..6`, 6-way pool with per-key 10 RPM | single `GEMINI_API_KEY` + global 10 RPM | We have one key. The script is ready to add round-robin later without changing the rate-limiter contract. |
| ESG-only filter | none (every page is sent) | `--all-pages` toggle, default skips non-ESG pages | Biggest cost saving in the pipeline. Has no precision cost when the upstream classifier is well-calibrated. |
| Schema default | required `--schema <path>` | `config/schema.json` (already in repo) | Sensible default; flag still overrides. |

---

## 5. Schema reference

The graph ontology consumed and validated by this script is
[`config/schema.json`](../config/schema.json) — 16+ entity classes and ~30 edge
labels, each with `identity_keys` declaring the natural key used for stable IDs.
See [`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) for the human-readable tour.

The script only **reads** the schema in two places: at startup (to log the class
and edge counts) and inside `_validate_extraction_format` / `triple_list_to_graph`.
Adding a new class or edge to `config/schema.json` is a no-code change here.

---

## 6. Setup

```bash
pip install -r requirements.txt   # google-genai, python-dotenv already pinned
```

Make sure `.env` at the repo root has your key:

```bash
# .env
GEMINI_API_KEY="..."
```

And make sure **step 1 has been run for the documents you want to process** —
this script needs the per-page KPI JSONs in `kpi_output/<pdf_stem>_kpis/`.
If you run it on a doc with no KPI dir, it will still work (the prompt just
won't have the structured KPI block) but you'll get worse results.

---

## 7. Run

```bash
# Default: just the first document (cheap smoke test)
python src/extract_triplet_from_jsonl.py

# A specific document (substring match against source_pdf)
python src/extract_triplet_from_jsonl.py --doc AAA_Baocaothuongnien_2011

# First N documents
python src/extract_triplet_from_jsonl.py --limit-docs 3

# Everything
python src/extract_triplet_from_jsonl.py --all

# Recall sweep — run every non-empty page, not just ESG-tagged ones
python src/extract_triplet_from_jsonl.py --all --all-pages

# Resume after a rate-limit interruption — same command, missing pages refill
python src/extract_triplet_from_jsonl.py --all
```

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `-i, --input` | `data/labeled/annual_labeled/labeled_annual_report_company_aaa.jsonl` | Labeled JSONL |
| `-s, --schema` | `config/schema.json` | Graph schema JSON |
| `--kpi-dir` | `kpi_output/` | Per-doc KPI root |
| `-o, --out-dir` | `graph_output/` | Output directory |
| `--doc <substr>` | — | Only docs whose `source_pdf` contains this substring |
| `--limit-docs N` | — | First N documents |
| `--all` | — | All documents |
| `--all-pages` | off | Run every non-empty page (default: only pages with ≥1 `esg=true` sentence) |
| `--max-workers N` | 4 | Parallel page workers |
| `--rate-limit N` | 10 | Max RPM. Match your Gemini tier (free: 10, paid Tier 1: 1000). |
| `--model` | `gemini-2.5-flash` | Gemini model id |

---

## 8. Related docs

- [`KPI_EXTRACTION_FROM_JSONL.md`](./KPI_EXTRACTION_FROM_JSONL.md) — step 1, produces the per-page KPI JSONs consumed here.
- [`SCHEMA_EXPLAINED.md`](./SCHEMA_EXPLAINED.md) — the knowledge-graph ontology this script validates triples against.
- [`KPI_DEFINITIONS_CONSTRUCTION_BUILD.md`](./KPI_DEFINITIONS_CONSTRUCTION_BUILD.md) — how the KPI vocabulary feeding step 1's prompt is built.
- [`VIETNAM_IMPROVEMENT_PLAN.md`](./VIETNAM_IMPROVEMENT_PLAN.md) — broader plan for adapting the GRI/ESRS-shaped graph to the Vietnamese regulatory reality.
