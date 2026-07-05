# EVALUATION.md — Step 8 / P6 design note

> Design note for the evaluation stage. The **rendered report is Vietnamese** (the POC
> audience); this note and the code are English, matching the rest of the repo. Read
> [`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §10 (evaluation without ground truth) and §11 (P6)
> first — this document explains *how* that plan is implemented.

## 1. Why this stage looks the way it does

The load-bearing constraint (SYSTEM_DESIGN §1.1): **there is no greenwashing ground truth** for
Vietnamese companies. So P6 does **not** measure "greenwashing accuracy" and produces **no score
or verdict**. It validates the *evidence-linking machinery* and demonstrates utility, via the four
methods in §10:

| # | Method | Cost | Where it runs |
|---|---|---|---|
| 1 | Coverage metrics | free | offline, from `coverage.csv` + cross-check stats |
| 2 | Case studies | free | offline, from the P4 dossiers |
| 3 | Manual link-precision | free | **methodology** (this doc + report §4) + a small illustrative indicator |
| 4 | Ablations | ~$0.02 | 30-case OpenAI arm (capped, cached) + a free corpus-level structural arm |

Two hard constraints shaped the implementation, both from the project memory notes
(*"verify cheaply, not via expensive re-runs"*):

- **Offline-first.** Everything except the 30-case LLM arm reads artifacts already on disk
  (`graph_output/crosscheck/aaa_claim_assessments.json`, `..._stats.json`,
  `data/interim/news_sentences/coverage.csv`). No Neo4j, no embeddings, no re-run of the
  3,113-pair cross-check.
- **Cost-capped LLM.** Gemini is billing-blocked; OpenAI works. The only paid work is adjudicating
  a fixed **30-case gold set** on `gpt-4o-mini` (~30 calls), and results are **cached** so re-runs
  cost nothing.

## 2. The single entry point — `src/step10_evaluate.py`

Standalone `src/` script (run from the repo root). Section-only flags print to stdout; with no
flag it assembles the full Vietnamese report.

```bash
python src/step10_evaluate.py                    # full report → graph_output/evaluation/aaa_evaluation_report.md
python src/step10_evaluate.py --coverage         # coverage section only            (free)
python src/step10_evaluate.py --case-studies     # case studies only                (free)
python src/step10_evaluate.py --ablation --no-llm # baseline + corpus structural    (free)
python src/step10_evaluate.py --ablation         # + the 30-case OpenAI arm         (~$0.02, cached)
```

Useful flags: `--no-llm` (skip the paid arm), `--refresh` (ignore the LLM cache), `--max-cases N`
(shrink the paid arm further), `--openai-model`, `--provider-order`, `--rate-limit`,
`--out-dir`, `--maxlen`.

**Reuse.** The LLM arm imports the production adjudicator from `step07_crosscheck_claims_vs_conduct`
(`Adjudicator.adjudicate(claim_text, evidence_text, evidence_meta)` → `{verdict, confidence,
rationale, provider}`) so the ablation exercises the *exact* code path the pipeline uses — the
only difference is the input is 30 fixed cases instead of the retrieved pairs. The import is lazy
(inside the LLM arm) so the free sections need none of the cross-check dependencies.

## 3. The 30-case gold set — `config/evaluation/ablation_cases.json`

A hand-labeled fixture of 30 `(claim, evidence)` adjudication cases for AAA, **10 supports / 10
contradicts / 10 irrelevant**. Tracked in `config/` because it is a controlled, human-authored
reference artifact (like `kpi_definitions_construction.json`); `data/` and `graph_output/` are
git-ignored and cannot hold it.

- **It grades *links*, not greenwashing.** Each `reference_verdict` answers "is this evidence link
  correct?" — never "is the company greenwashing?".
- **Provenance.** Claim + evidence texts are copied verbatim from the P4 dossiers.
  `case_type=real` (25) were actually adjudicated in production; `case_type=constructed` (5) pair a
  real claim with a real but topically-unrelated evidence node to test the `irrelevant` verdict
  (production writes no edge for `irrelevant`, so those are otherwise unobservable).
- **Label policy (strict independence).** An evidence item must speak to the *same thing* the claim
  asserts. Five `real` items are deliberately labeled `irrelevant` even though production returned
  `contradicts` (IR01–IR05) — temporal-window mismatches or metrics that don't actually bear on the
  claim. They are included **on purpose** to expose the failure modes in SYSTEM_DESIGN §12; they
  are why the LLM's `irrelevant` recall is low and its `contradicts` precision is < 1.

## 4. The three ablation comparisons

Only the middle one spends money.

1. **Deterministic lexical baseline (free, `baseline_verdict`).** Token overlap decides
   relevant-vs-irrelevant; polarity (a real minus sign or a decrease/`giảm` keyword against a
   growth/positive claim word) decides supports-vs-contradicts. It **cannot compare magnitudes**
   (EPS 2,550 vs 1,213), which is exactly where the LLM earns its keep. This is the "what you get
   without the LLM" arm.
2. **LLM adjudicator (OpenAI `gpt-4o-mini`, ~30 calls, cached).** The reused `Adjudicator` on the
   same 30 cases. Scored vs the reference with a confusion matrix + per-class precision/recall/F1.
   This doubles as the small illustrative **link-precision indicator** (method 3).
3. **Corpus-level structural-vs-LLM ablation (free).** Over all 1,093 dossiers: the pure structural
   signal (contradiction edge + no verification) flags the review queue but produces **zero**
   support assessments; the LLM adds the entire *support* axis + grounded rationale/confidence, and
   the self-verification guard demotes company-domain "supports". Pure graph query, no cost.

## 5. Full manual link-precision methodology (method 3, to scale beyond the indicator)

The 30-case agreement is only an *indicator*. The full study (report §4):

1. **Stratified sample** the written support/contradict edges by class and confidence; include a
   share of `irrelevant` pairs (requires enabling a verdict log in Step 6 — production currently
   persists only the 125 written edges, not the `irrelevant` verdicts).
2. **Blind** the LLM's labels; have **≥2 independent annotators** label each pair
   supports/contradicts/irrelevant from the claim + evidence text alone.
3. Compute **human↔human agreement** (e.g. Cohen's κ) to confirm the task is well-posed, then
   **LLM↔human agreement = link-precision**.
4. Report **per class** (contradiction precision matters most — it is reputationally sensitive),
   always with the §12 limitations.

## 6. Current results snapshot (AAA, `gpt-4o-mini`)

Regenerate with `python src/step10_evaluate.py`. As of the latest run:

- **Coverage:** AAA 40 articles / 1,054 sentences; 124 conduct nodes (108 KPIObservation +
  16 MediaReport); advisory split 66 supported / 22 contradicted / 1,005 unverified. Sector context:
  115 companies, ~4,537 articles / ~164,036 sentences.
- **Ablation (30 cases):** baseline **73.3%** vs LLM **76.7%** agreement. The LLM catches all 10
  contradicts (baseline misses the 3 numeric-magnitude ones) and keeps perfect support precision
  (1.00), but over-reaches on the 5 hard `irrelevant` cases (calls them `contradicts`) — the §12
  failure mode, made visible on purpose.
- **Corpus ablation:** structural-only = 22 contradicted / 0 supported; +LLM = 22 / 66; guard
  demoted 18 company-domain supports.

## 7. Outputs

| Path | What | Tracked? |
|---|---|---|
| `config/evaluation/ablation_cases.json` | 30-case gold fixture (input) | yes |
| `graph_output/evaluation/aaa_evaluation_report.md` | Vietnamese evaluation report | no (generated) |
| `graph_output/evaluation/ablation_llm_results.json` | LLM verdict cache (per model) | no (generated) |

## 8. Related docs

[`SYSTEM_DESIGN.md`](./SYSTEM_DESIGN.md) §10/§11/§12 ·
[`CLAIM_CONDUCT_CROSSCHECK.md`](./CLAIM_CONDUCT_CROSSCHECK.md) (Step 6, the adjudicator reused here) ·
[`CLAIM_LEDGER.md`](./CLAIM_LEDGER.md) (Step 7 presentation)
