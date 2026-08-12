# Thesis Review — Graph-RAG Greenwashing Detection for Vietnamese Listed Companies

**Date:** 2026-08-12 · **Object under review:** `capstone_report/main.tex` (2,496 lines) and the
codebase at `c4c9f42` (`main`), against the pinned data snapshot (`data_version.json` →
`902fcf84`, `code_commit 7c108f9`).

**How this review was produced.** Two independent reviewers worked in parallel without seeing
each other's output — one on research methodology and scientific validity, one on systems,
implementation and data integrity — plus a chair's own verification pass. Every finding below was
verified by opening the cited file or executing the cited command. No pipeline stage was re-run,
no LLM was called, no network access was used, and **no project file was modified**. Where the
two reviewers reached the same conclusion by different routes, that is noted as corroboration.

**Confidence tags.** `[CONFIRMED]` = personally verified, evidence quoted with `path:line` or
command output. `[RISK]` = suggestive but not fully verifiable offline. `[HYPOTHESIS]` = reasoned
concern with a stated cheapest test.

**A rule this review respects.** `docs/EVALUATION_BASELINE.md` freezes the reported measurement
snapshot (10,634 nodes / 14,744 edges / 464 dossiers / 5 issuers / 718 of 1,421 aligned). A
thesis-versus-disk mismatch on those frozen figures is *not* treated as a defect. What is treated
as a defect is internal inconsistency within the thesis, a figure matching neither the snapshot nor
disk, or a frozen figure presented without saying it is frozen. Corpus-size figures are **not** in
that freeze and are audited normally.

**One correction the chair owns.** An earlier pass reported 197 report-side issuers from an ad-hoc
parse of `source_pdf` stems. That is wrong. Using the project's own `REPORT_STEM_RE`, the correct
figure is **115** (roster: exactly 115 tickers; regex yields 116, of which 114 are in the roster).
The 197 was an artifact of splitting publisher filenames on `_` and counting tokens like `BCTN`
and `CBTT` as tickers. The thesis's "115 issuers" is **correct**; see §3.

---

## 1. Executive Assessment

**This is a good thesis with a serious reporting problem and one serious engineering problem, and
neither is fraud.**

Read sentence by sentence, the document is unusually honest — more so than most published work in
this area. It states that its internal metrics "cannot fail in an interesting way"
(`main.tex:2290`). It reports a 96.55% abstention rate in the abstract rather than burying it. It
uses Wilson intervals instead of the normal approximation, and it declines to report a
chance-corrected agreement coefficient at n=15 where the coefficient degenerates to 1 by
construction. It refuses to emit a greenwashing score and defends that refusal formally. It
correctly declines to conflate its annotation session with a more elaborate rubric study that was
never carried out (`main.tex:2380`), and it silently omits an annotation column that failed its
reliability threshold. These are marks of genuine scientific maturity and they should be credited
first.

The problem is that **the document does not add up at the level of the whole**. It has no
Discussion, no Conclusion, no Limitations chapter and no Threats-to-Validity section, while
forward-referencing a "Discussion chapter" three times and promising ablations four times — one of
them as a numbered contribution — that are never delivered. Every individual caveat is disclosed
somewhere; the sum is never written down. The result is a thesis whose parts are honest and whose
overall impression is more favourable than its evidence supports.

Two findings are more serious than framing. First, **the reported verdicts were not produced by the
system the thesis describes.** The adjudication cache key hashes only `(claim_text, evidence_text,
evidence_meta)` — not the prompt, model or provider — so the prompt-tightening half of the
2026-08-07 contamination fix never reached the reported numbers. All 24 cited evidence items carry
`provider: "openai"`, i.e. verdicts replayed from the pre-fix era, and a re-run today would serve
96.3% of its answers from that same stale cache. Second, **the headline precision result omits the
denominator that produced it.** Two external domain experts labelled 200 pairs; the thesis reports
on 15. On the full 200 those same experts confirmed 26.5%/35.0% overall and **6–9% of asserted
contradictions**, against the 86.7% and 100% (3/3) the thesis reports. The improvement is real and
the fix was legitimate — but the collapse from 226 cited pairs to 24, and the prior precision
level, appear nowhere in the thesis.

The corrective work is overwhelmingly **writing, not re-running**. The numbers that would fix the
largest problem are already computed and sitting in `docs/ANNOTATION_RESULTS.md`. Only one fix
(re-adjudicating 401 pairs after salting the cache key) costs money, and that cost is small and
bounded. Nothing in this review requires re-crawling, re-extracting, or rebuilding the graph before
submission.

**Verdict: substantial revision required before submission, concentrated in Chapters 4–5 and in one
cache-key bug. The underlying research is sound and several results are genuinely strong.**

---

## 2. Most Important Problems

Ranked by (risk to defensibility × ease of remedy). IDs cross-reference the two reviewers (A =
methodology, B = systems, S = chair).

### P1 — The prompt half of the contamination fix never reached the reported numbers
**Critical · [CONFIRMED] · (B1)**

Commit `7c108f9` has three layers: issuer-scope the conduct pool, add VN-aware tokenisation with
`min_topic_overlap=2`, and tighten `ADJUDICATE_SYSTEM` against halo reasoning. Layers 1–2 provably
ran; layer 3 did not affect a single reported verdict.

The cache key is content-only — `src/esg_kg/core/llm_cache.py:76-86` hashes whatever parts it is
given, and the caller passes only three (`src/esg_kg/crosscheck/claims_vs_conduct.py:493`):

```python
cached, hit = self.cache.get(claim_text, evidence_text, evidence_meta)
```

No prompt, no model id, no provider. Offline replay of the deterministic retrieval reproduces the
recorded stats *exactly* under post-fix rules and not at all under pre-fix rules (ACG recorded
190/134/359 = replayed; pre-fix would give 2,124 pairs), so layers 1–2 ran. But recomputing cache
keys for today's 401 candidate pairs against `adjudication_cache.json` gives **386/401 = 96.3%
hits, 376 answered by OpenAI**, and every cited evidence item in the baseline carries
`provider: "openai"`. OpenAI was removed 2026-08-04 and re-added for this stage 2026-08-06; the
prompt tightening landed 2026-08-07.

**Consequence.** The 13 supported + 3 contradicted verdicts — the thesis's entire positive signal —
were produced under the old halo-prone prompt. `docs/EVALUATION_BASELINE.md` correctly warns that
anything from `adjudication_cache_openai*.json` is "before the contamination fix", but it treats the
464/448/13/3 dossier numbers as post-fix. They are post-fix **in retrieval only**. The failure mode
layer 3 was written to close is same-company/different-topic halo reasoning — precisely the case
retrieval cannot rule out, and precisely where the reported ACG contradictions sit.

**Fix.** Salt the key: `ContentCache.key(sha256(ADJUDICATE_SYSTEM)[:12], model, claim_text,
evidence_text, evidence_meta)`, or add a `namespace` constructor argument. Then re-run
`claims_vs_conduct` for the five tickers (401 pairs — small, bounded spend) and re-report.
**Validate:** cache hits against the old file must drop to zero; add a test asserting that changing
one byte of `ADJUDICATE_SYSTEM` invalidates every entry — the natural companion to the byte-for-byte
prompt pins the repo already has.

**Note the likely direction.** A tightened prompt pushes more pairs to `irrelevant`, so a correct
re-run will probably push the unverified rate *above* 96.55% and reduce the 16 verdicts. This should
be expected and reported, not treated as a regression.

---

### P2 — The headline precision result omits 185 of 200 expert labels and the 89% output collapse
**Critical · [CONFIRMED] · (A1, S3) — corroborated by two independent scripts**

`main.tex:2385` frames the population as though it were ~24 pairs all along: "the stage cites 24
pairs in total, and 15 of those carry blind expert labels. Those 15 are the population measured
here." The annotation session those labels come from covered **200 real pairs** plus 20 decoys,
sampled from a population of **226 cited pairs** (`docs/ANNOTATION_RESULTS.md:20-23`), and
`ANNOTATION_RESULTS.md:105-107` states the collapse outright: after the patch, 24 cited pairs
versus 226 before.

Reproduced from the sheets and the answer key:

| Population | Annotator A | Annotator B |
|---|---|---|
| All 200 real pairs | **26.5%** (53/200) | **35.0%** (70/200) |
| Restricted to annotator-judged same-company | 55.8% (53/95) | 56.8% (21/37) |
| The 15 pairs the thesis reports | **86.7%** (13/15) | **86.7%** (13/15) |

The contradiction branch is sharpest. `ANNOTATION_RESULTS.md:84` records 7.0% (8/114) and 8.8%
(10/114); the chair independently ran `notebooks/eda/annotation_agreement.py` (offline, free) and
obtained:

```
system said 'contradicts': n=117, on gold subset n=112
   annotators concur : 7/112 = 6.2%  (Wilson 95% CI 3.1-12.3%)
   gold labels here  : {'irrelevant': 103, 'contradicts': 7, 'supports': 2}
system said 'supports': n=86, on gold subset n=63
   annotators concur : 41/63 = 65.1%
```

Against this, `main.tex:2418` reports contradiction precision as "100% (3/3)" and `main.tex:2422`
elevates it: "neither expert rejected an asserted contradiction, which is the output that matters
most." `grep` over `main.tex` returns **zero** occurrences of "contamination", "226", or "pre-fix".

**Is reporting the post-fix number legitimate?** Yes — 15 of 24 is a genuine 62.5% sample of the
post-fix cited output, and 86.7% is a defensible estimate *of post-fix precision*. What is not
defensible is presenting it unconditionally while suppressing that 185 labels from the same session
exist, that the same experts confirmed ~6% of the pre-fix contradictions, and that the 86.7% was
bought by an ~89% reduction in cited output. Those are exactly the precision/recall trade a reader
needs. `main.tex:2456` gestures at the shape of it — "a statement about what the system chooses to
show" — without a single number.

**This fix is not damage control.** Done properly it is the strongest result the project has: *two
independent domain experts confirmed 26.5–35% of the system's cited output before the fix and 86.7%
after, while cited volume fell from 226 pairs to 24.* That is a quantified, externally validated
before/after with a real mechanism. The thesis currently reports only the "after," which both
weakens its own case and exposes it to a selective-reporting charge from any examiner who opens
`ANNOTATION_RESULTS.md`.

**Interaction with P1 — state this carefully.** Because the prompt fix never applied, the 15 pairs
are survivors of the *retrieval* fix only. The honest description is "post-fix retrieval, pre-fix
adjudication prompt." Fixing P1 changes which pairs are cited, so P2's write-up should be done
**after** the re-run, not before.

---

### P3 — No Discussion, Conclusion, Limitations or Threats-to-Validity chapter
**Critical · [CONFIRMED] · (A3, S1)**

The thesis ends at §4.4 "Expert Annotation" and goes straight to `\appendix` (`main.tex:2459-2461`).
Chapter list, verified by grep: Project Introduction, Data, Methodology, Experiments and Results,
appendix. There is no Chapter 5.

Three forward references dangle: `main.tex:465` ("a limitation this thesis's Discussion chapter
returns to"), `main.tex:583` ("revisited in this thesis's Discussion chapter"), `main.tex:1067`
("recorded as such in the Discussion chapter"). The only limitations content is four bullets at
`main.tex:2452-2457`, explicitly scoped to the annotation measurement alone — and prefaced by
`main.tex:2450`: "Four limits belong here rather than in a closing limitations section," a sentence
that concedes such a section is expected and then never supplies it.

**What is missing entirely**, verified by grep: **LLM non-determinism** — zero occurrences of
"temperature", "seed" or "non-determin" in a thesis whose every extraction and adjudication stage is
a prompted LLM. **LLM judging LLM output** — never named as a threat, although the adjudicator
judges triples extracted by an LLM, a shared-failure-mode risk. **Vietnamese OCR/segmentation
error** — one occurrence of "OCR"; the 11,827-character "sentence" at `main.tex:847` is noted as an
artefact but never costed. **News coverage bias** — well covered in §2.3.5 but never carried into a
threats section. **The single-issuer evaluation base** — disclosed locally, never aggregated (P4).

---

### P4 — The aggregate evaluation base is never stated, and the graph-native retrieval path contributed nothing
**Critical for claim scope · [CONFIRMED] · (A15, S4, B §5)**

Every component of the bottom line is disclosed somewhere; the sum is never written down.

The parts, each disclosed honestly: three of five issuers return zero signal (`main.tex:2263`); all
labelled pairs belong to one issuer, ACG, spanning eleven claims (`main.tex:2455`); internal
controls are self-referential (`main.tex:2290`); the cited output is 24 pairs across 464 claims
(`main.tex:2456`). **No sentence in the thesis says: the entire external validation rests on 15
evidence pairs drawn from one of five issuers, and 16 of 464 claims (3.45%) received any verdict at
all.** The abstract, the contribution list, §4.4.4 and the absent conclusion were all searched.

The same pattern governs the most important systems finding on the claim side. The **indicator-axis
tier — the one genuinely graph-native retrieval path, the 2-hop join `claim --alignsWithIndicator-->
Indicator <--measuredUnder-- conduct`, and the mechanism that distinguishes this from keyword search
— fired zero times across the entire evaluation.** `indicator_tier_pairs: 0` in all five stats
files; all 24 cited items carry `retrieval_tier: "token_overlap"`. The thesis discloses this **for
AAA only**, at `main.tex:2012`: "Indicator-axis tier pairs & 0 of 23 — despite 20 of the 36 claims
already carrying an `alignsWithIndicator` link". It is never stated that the figure is 0 of 401
across all five issuers, and §4.1 (`main.tex:2229`) presents the 50.53% alignment coverage as "what
the retrieval-side indicator-axis tier draws on" — a path that in fact drew nothing.

**Cause** (diagnosed, not speculative): news-side KPI observations are overwhelmingly financial and
are deliberately rejected by `canonicalize` ("financial KPIs in VND are rejected"), so no conduct
node ever acquires a `measuredUnder` edge to an indicator a claim also points at. The design is
sound; the corpus cannot currently exercise it.

**Consequence.** Retrieval in the reported system is Vietnamese token overlap with a temporal
window. The knowledge graph contributes schema, identity resolution, temporality and provenance —
all real — but **not retrieval**. Any framing that implies graph-structured retrieval produced the
results overstates what ran.

---

### P5 — `anchor_kpi` (step03b) produces zero output, silently
**Critical (systems) · [CONFIRMED] · (B2)**

`graph_output/validated/anchor_patch_stats.json`, in full:

```json
{ "kpi_observations": 6661, "kpi_without_resolvable_sentence": 6661,
  "facility_gazetteer_size": 151, "raw_matches": 0, "facilities_over_cap": [],
  "dropped_invalid": 0, "new_anchor_triples": 0, "matches_per_facility": {} }
```

100% of KPI observations fail sentence resolution. Cause, at `src/esg_kg/graph/anchor_kpi.py:62-65`:
the default glob still lists `data/labeled/annual_labeled/*.jsonl` — the AAA pilot directory removed
on 2026-08-02. The canonical corpus `data/labeled/classified/all_sentences_classified.jsonl` is not
in the list. The stage exits 0.

This is the single root cause of two of the four test failures, both of which detect it correctly
("03b contributed nothing — the block is not running the anchor stage"). The offline gazetteer
anchoring contribution the pipeline documents is nil; a memory note recording "P3 KPI anchoring
still 5.3%" is now 0%, a silent regression.

**Fix.** Change the glob to `data/labeled/classified/*.jsonl` + `data/labeled/news_labeled/*.jsonl`,
and add a guard: if `kpi_without_resolvable_sentence == kpi_observations` and `kpi_observations > 0`,
log ERROR and exit non-zero. A 100% resolution failure is never a legitimate outcome.
**Validate:** `python src/run.py anchor_kpi --dry-run` (offline, free) → `raw_matches > 0`; the two
failing tests go green without editing either test.

---

### P6 — Contribution #5 claims three ablations that do not exist
**Critical · [CONFIRMED] · (A2, S2, B11)**

`main.tex:274` claims "a label-free evaluation instrument … demonstrated on three controlled
before/after ablations." `grep -c ablation main.tex` returns 4 — the claim plus three forward
references (`main.tex:550`, `:778`, `:792`). Chapter 4 has four sections and none is an ablation.
`config/evaluation/ablation_cases.json` has **zero Python consumers** and cites `docs/EVALUATION.md`,
which was deleted from the project — so the contribution has no executable artifact either.

The instrument itself does exist (`docs/EVALUATION_WITHOUT_LABELS.md`, the NC.1/NC.2 negative
controls) and one before/after **is already computed**: NC moved 28.76% FAIL → 100% PASS with
`cross_feed = 0` (`EVALUATION_BASELINE.md:81-87`). The work was done; it was not written up. A
contribution claim with no supporting section is the most attackable thing in a thesis.

---

### P7 — Corpus figures in the abstract do not reconcile with the pinned data
**Major · [CONFIRMED] · (B5, B14, A9, A11, S8)**

`main.tex:141-144` claims "1,416 annual-report filings from 115 listed issuers and 4,537 independent
news articles was crawled **and ESG-classified**". Measured against the pinned snapshot:

- **1,416** PDFs were *crawled*; **1,216** distinct `source_pdf` values are *classified*. The
  204-document gap (14.4%) is never mentioned, and **no stage records which 204 or why**.
  Inspection shows it is dominated by non-conforming publisher filenames and non-BCTN documents
  downloaded anyway (financial statements — `BCTC` not `BCTN` — and multi-part splits), so much of
  it is legitimately excluded material. But that cannot be demonstrated, because nothing logs it.
- **115 issuers is correct** (roster: exactly 115 tickers over 1,358 rows). See the chair's
  correction at the head of this document.
- **4,537 articles / 662 outlets is unsupported.** Measured: 4,582 doc ids, **3,797 distinct URLs**,
  **716** domains. Neither 4,537 nor 662 is obtainable from the pinned data by any counting
  convention tried, including `coverage.csv`'s `top_domains` (which yields 140). 785 doc ids (17.1%)
  are the same URL re-crawled under a second ticker, so the honest article-level denominator is
  **3,797**.

Separately, Chapter 2 and Chapter 4 disagree with each other about the same channel: Chapter 2
reports 164,036 news sentences and 662 domains; Chapter 4 reports 174,256 and matches disk exactly.
Chapter 2's figures are internally self-consistent (4,537 × 36.2 ≈ 164,036), so they are a real
measurement of an earlier crawl that was never refreshed. **This is not covered by the frozen-snapshot
rule** — that freeze covers graph, dossier and alignment figures, not corpus size.

**Good news on a related worry:** the cross-ticker article duplication does **not** contaminate the
graph. Inside `resolved_graph.json` there are 561 news nodes over 42 `source_doc` values and 41
distinct content hashes, with **zero hashes appearing under more than one ticker**. The AAA-pilot
duplication incident is also genuinely resolved in the pinned corpus. The inflation is confined to
corpus statistics. (One stale artifact to avoid quoting: `data/outputs/esg_extracted/esg_stats.json`
still counts the removed pilot file.)

---

### P8 — The self-verification guard is AAA-hardcoded and has never fired
**Major · [CONFIRMED] · (B3)**

The independence guarantee — a company-owned domain never creates a `verifiedBy` edge — is
implemented as a hardcoded allow-list at `claims_vs_conduct.py:175-179`, every entry of which is An
Phát / AAA. Measured against the real conduct pools, the guard is a **no-op for all five issuers**,
and `flagged_non_independent_support` is 0 across all 464 dossiers.

The risk today is latent rather than realised: all 24 cited items come from third-party news
domains (`cafef.vn`, `baodautu.vn`, `mekongasean.vn`). But the moment a company-owned or
syndicated-PR domain enters any conduct pool, it will be treated as independent evidence. The code
comment concedes the direction — "a miss only inflates support, never fabricates a contradiction" —
and for a greenwashing detector, inflated support is the harmful direction. The guard is also a
plain substring test that cannot see subdomains on a neutral host, syndicated press releases, or
aggregators.

Contribution #2 claims independence as *the* distinguishing property of this system. It is currently
enforced structurally (by `source_type` separation, which is real) but the domain-level guard that
the thesis describes at `main.tex:1990` is unexercised.

---

## 3. Data Pipeline Audit

Stage-by-stage, measured on the pinned snapshot. "Drop explained?" = does the pipeline record *why*
records were lost.

| Stage | Input | Output | Drop | Drop explained? | Verdict |
|---|---|---|---|---|---|
| roster → download | 1,358 rows / **115 tickers** | **1,416 PDFs** | — | n/a (`download_log.csv`) | OK — 1,416 is the crawl count |
| PDFs → classified | 1,416 PDFs | **1,216** docs; 873,756 sentences; 303,723 `esg=true` | **−204 (−14.4%)** | **NO** | **FAIL** — P7 |
| news crawl | 115 tickers, cap 40/ticker | 4,582 doc ids / **3,797 URLs** / **716** domains | 785 dupes (17.1%) | partial | **PARTIAL** — P7 |
| `preprocess_news` | 174,256 sentences | 58,849 kept | −66.2% | **YES** (stats file) | OK — large but recorded |
| `extract` (KPI) | ESG pages | **54** doc dirs, 3,665 page files | — | NO | **RISK** — 54 vs 114 docs |
| `extract_triples` | labelled JSONL | **114** doc dirs, 2,701 page files | — | YES | OK |
| `fix_triples` | 15,307 triples | 14,500 kept / **807 unfixable** | −5.27% | **YES** — per-triple errors + source | **EXEMPLARY** |
| `anchor_kpi` | 6,661 observations | **0 anchors** | **−100%** | recorded as a number, not diagnosed; exits 0 | **FAIL** — P5 |
| `canonicalize` | KPIObservations | `kpi_id` assigned | — | YES | OK |
| `entities` | 13,770 / 14,500 | 10,608 / 12,726 (−23.0%) | intentional dedup | YES | OK — Stage B/C dormant (`llm_comparisons: 0`) |
| `provenance` | 7,287 nodes | all `already_stamped` | 0 | YES | OK (idempotent); test arm vacuous |
| `indicators` | 10,608 / 12,726 | **10,634 / 14,744** | append-only, asserted | YES | **GOOD** |
| `claims_vs_conduct` | 481 claims | **464** dossiers | 1 orphan claim | partial | OK |

**Three structural observations.**

**(a) Only 20.5% of crawled conduct evidence reaches the graph.** The five issuers have 200 distinct
crawled articles (exactly 40 each — a hard crawler `--limit` cap, not organic coverage), of which
**41 entered the graph**. The whole conduct side is **561 news nodes from 41 documents** against
10,020 report nodes. This is the highest-leverage fix available anywhere in the project and it costs
nothing to diagnose.

**(b) The graph is a star, which bears on the multi-hop framing.** [CONFIRMED, B8]

```
nodes=10,634 edges=14,744 | degree: max=5,389 median=1.0 mean=2.77
isolated 9 | leaves 7,133 (67.1%) | components 71, largest 10,449 (98.3%)
edges incident to one of the 5 issuer hubs: 10,182/14,744 = 69.1%
reportsKPI edges: 6,569 = 44.6%   <- the sole relation degenerate_relations.json declares degenerate
```

With 67.1% leaves and 69.1% hub-incident edges, almost any 2-hop path between two non-hub nodes is
`X → issuer → Y` — "both facts belong to the same company", which the project itself classifies as
degenerate. The team diagnosed this correctly and built `export_kgc` to decompose the hub
(9,511 → 542), but that writes a *separate* artifact and never patches `resolved_graph.json` or
Neo4j — so the graph the thesis reports on, loads, and serves to the UI is the **undecomposed** star.

**(c) `resolved_graph.json` is append-only and not rebuildable identically.** [CONFIRMED, A5 + B]
`all_validated_triples.json` — written *upstream* of entity resolution — already contains 162
`alignsWithIndicator` and 38 `measuredUnder` edges, predicates only the downstream indicators stage
may create. On disk the resolved graph holds **807** `alignsWithIndicator` edges while
`indicator_axis_stats.json` records `created_edges: 649`; the 158-edge difference is residue from
prior runs. `align_claims` is ruled out as the explanation (zero `llm` alignment edges exist). This
surfaces visibly in Table 4.2, which reports 649 created edges and, three rows later, 718 nodes each
carrying at least one such edge — **718 nodes cannot each carry an edge if only 649 exist**. Both
numbers are individually faithful to their sources; they are drawn from different populations and
presented without reconciliation.

**Silent-failure audit — mostly reassuring.** Three named exceptions: `_vn_segments` falls back to
whitespace splitting on any tokenizer error, silently reverting to the exact unigram behaviour the
fix removed (add a warning + counter); `Adjudicator` disables a provider after 3 failures, which
consumed 9 pairs on the reported run (only 1 claim carries the caveat); `ContentCache` starts empty
on corruption, correctly logged. Against this, `unfixable_triples.json` records `_validation_errors`
**and** `_source_file` per dropped triple — a 5.27% drop fully attributable to named schema
violations. That is the model the rest of the pipeline should follow, and the contrast with P5
(100% drop, nothing actionable recorded) is instructive.

---

## 4. Evaluation Audit

### 4.1 Test suite — actual run, not the README's word

All 38 files run from the repo root: **34 exit 0, 4 exit 1**. Two of the 34 are the paid tests
correctly no-op'ing behind their env gates, so the real offline tally is **32 pass / 4 fail of 36**.

| Failing file | Cause | Category |
|---|---|---|
| `test_esg_kg_anchor_kpi.py` | "cap=1 tripped no facility — arm is vacuous" | **real defect** (P5) |
| `test_esg_kg_validated_block.py` | "03b contributed nothing — the block is not running the anchor stage" | **real defect** (P5) |
| `test_esg_kg_crosscheck.py` | `assert s["claims"] > 100` — AAA now has 36 | stale expectation |
| `test_esg_kg_provenance.py` | `assert stamped > 0` — everything already stamped | vacuous arm |

`test_temporal_invariants.py` passes 18/18 and `test_schema_contract.py` passes against the real
10,634-node graph: **P1 (timeless T1 identity), P2 (time on edges/T2–T3) and P4 (ISO dates, single
`is_current`) are genuinely enforced, not merely documented.** Contribution #3's linter claim is
real.

**Coverage quality.** The suite honours its own rule — stub *under* the abstraction, so real stage
logic executes against fake I/O. `test_esg_kg_crosscheck.py` runs the whole step07 driver against
the real graph with a deterministic fake provider; that is not a tautology. Three tests pin paid
prompt text byte-for-byte. Several carry explicit **vacuity guards**, which is why three of the four
failures are informative rather than noise — a test that refuses to pass by doing nothing is rare and
good. Weaknesses: `quality` (step00) has **no dedicated test** despite producing every Q1–Q8 figure;
the whole Neo4j leg is stub-only, so no test asserts the Cypher is semantically right; `extract` has
the thinnest coverage relative to its cost.

**On the repo's TDD claim.** The suite's *shape* supports it — tests are behavioural and several
encode the exact bug they were written for. But `git log` shows test and implementation landing in
the *same commit* in every case checked, so "red first" is asserted rather than evidenced. And P5 is
a stage that regressed to zero output, whose own test correctly detects it, and the failure was left
standing — the opposite of TDD discipline.

### 4.2 The 96.55% unverified rate — mechanical diagnosis

This is the most important number in the thesis and it has a clean answer. Exhaustive partition of
all 464 claims (the four buckets sum to 464 exactly):

| Bucket | Claims | % of 464 | % of the 448 unverified |
|---|---|---|---|
| **Zero retrieval candidates** | **303** | **65.3%** | **67.6%** |
| Had candidates, every verdict `irrelevant` | 144 | 31.0% | 32.1% |
| Had candidates, no verdict (provider failure) | 1 | 0.2% | 0.2% |
| Got a `supports` / `contradicts` verdict | 16 | 3.4% | — |

| Ticker | Claims | Conduct pool | Zero-cand. | All-irrelevant | Supported | Contradicted |
|---|---|---|---|---|---|---|
| AAA | 36 | 68 | 25 | 11 | 0 | 0 |
| ACC | 14 | 52 | 12 | 2 | 0 | 0 |
| ACG | 301 | 190 | 167 | 118 | 12 | 3 |
| ADP | 69 | 3 | 62 | 7 | 0 | 0 |
| AGG | 44 | 29 | 37 | 6 | 1 | 0 |

**Ranked causes.** (1) **Corpus coverage, dominant** — 41 conduct documents; ADP has a 3-node pool
against 69 claims, so 89.9% of its claims could not possibly find evidence. There is nothing to
retrieve. (2) **Retrieval recall, second and partly consequent** — `min_topic_overlap=2` over a
≤190-node pool leaves 303 claims matching nothing; the gate was tuned against contamination, never
calibrated against recall, and recall is structurally unmeasurable because `irrelevant` pairs are
never written. The indicator tier contributed nothing (P4). (3) **Adjudicator conservatism, real but
secondary** — 144 claims had evidence judged irrelevant, and since the worst-duplicated conduct
articles are generic ESG think-pieces, many of those verdicts are correct. (4) **Entity resolution,
ruled out** — only 1 of 481 claims is unreachable from an Organization; all five issuers resolve to
exactly one node with the right ticker.

**Bottom line.** The abstract's explanation — a conduct channel "roughly sixteen times smaller" — is
the *right* explanation and is honest. The measured node-level ratio is 10,020/561 = **17.9×**, so
"sixteen" is a mild understatement in the thesis's own favour. But the framing understates the
problem twice: the document-level ratio is far starker (41 documents), and 20.5% ingestion means
most crawled conduct evidence never reached the graph.

### 4.3 Statistical reporting

Chapter 4 states a policy at `main.tex:2151` — "every proportion computed on a finite sample is
accompanied by a 95% confidence interval" — and Table 4.5 then reports **twelve proportions with
zero intervals**, several on denominators that cannot carry a percentage:

| Metric | Reported | Denominator | Problem |
|---|---|---|---|
| M₄.₂ zero-report self-praise exclusion | **100.00%** | **1** | a percentage to two decimals on a single item |
| M₃.₁ timeless-identity violation | 0.00% | **14** | Wilson upper bound ≈ 21.5% |
| M₂.₃ value-preservation guard | 100.00% | 500 | needs the lower bound (≈99.2%) |
| M₅.₁ abstention rate | 96.55% | 464 | fine, but uninterval'd against the stated policy |

This is inconsistency, not ignorance: the negative-control paragraph (`main.tex:2350`) applies a
Wilson lower bound to its own result — "That 100% rests on 24 items, so its Wilson lower bound is
86.2%, not 100%" — which is exactly right. The technique simply was not applied to Table 4.5.
Separately, `main.tex:2422`'s prose reads three observations (3/3) as a finding.

### 4.4 Inter-annotator agreement — selectively scoped

The thesis reports 15/15 = 100% raw agreement and argues that chance-corrected coefficients are
uninformative *by construction* (`main.tex:2446`). That is true of the n=15 subset and false of the
instrument. Computed on the full session:

```
200 real pairs : raw agreement 0.860  Gwet AC1 0.818  Krippendorff α 0.696  Cohen κ 0.698
220 incl decoys: raw 0.873            AC1 0.837                            κ 0.713
```

`0.818` appears in `main.tex` exactly once — as a tabularx column width. `landis1977measurement`,
the standard citation for calling κ = 0.698 "substantial", sits **uncited** in `references.bib` — the
fingerprint of a paragraph drafted around the real figure and then narrowed. Citing Gwet and
Krippendorff in order to explain why neither is reported, when both were computed and are
favourable, reads worse than simply reporting them.

### 4.5 No baseline, no comparison, no control condition

Every number in Chapter 4 is a yield, coverage or agreement statistic on the system's own output
(`main.tex:2149` says so). Nothing establishes that the temporal-KG design outperforms anything.
"No ground truth exists" is load-bearing in two different ways here: it legitimately licenses
refusing to emit a greenwashing score, but it does **not** prevent comparing against a baseline,
ablating a component, or measuring run-to-run stability — none of which need labels, and none of
which the thesis does.

The bibliography betrays a dropped chapter: `han2025ragvsgraphrag` and `cormack2009reciprocal` (the
exact RRF algorithm `ragtest/fusion.py` uses) are both present and both **uncited**. The comparison
machinery exists on `wip/gri-parser-and-eval`. If it is added, the **~47× candidate-pool asymmetry**
must travel with it in the same table caption — the arms equalise reranker, adjudicator and
labelling model but not the candidate universe (481 claim nodes vs ~21,950 sentences), so the
coverage column is confounded before any retrieval mechanism is involved.

### 4.6 Verified clean — worth recording

- **No fabricated number leaked.** Every headline figure from `GRAPH_VS_RAG_COMPARISON.md` (whose §4
  is self-declared illustrative fabrication) was grepped against `main.tex`: **zero occurrences**.
- **The invalid join is not performed.** The thesis does not score `graphrag_vs_rag.xlsx` from
  `sheetA`/`sheetB` (which would be invalid — `claim_text` matches `graph_claim` in only 37/220 rows).
- **`about_claim_company` is correctly omitted.** That column fails its reliability threshold
  (AC1 = 0.480, reproduced exactly); it appears nowhere in the thesis.
- **Every frozen-snapshot figure matches disk exactly** — 10,634/14,744, 464/448/13/3, 718/1,421,
  299/481, 14,500/807, 7,324/1,464, and the 26-node/2,018-edge axis delta.
- **No citation misrepresents its source.** The Delmas–Burbano, Lyon–Maxwell, ClimateBERT and
  EmeraldMind characterisations all match what those works claim.
- **Determinism is properly handled**: `temperature=0` on every provider, JSON response mode, and
  DeepSeek explicitly disabling thinking mode because it makes temperature inert.

---

## 5. Thesis Claim Audit

| # | Contribution (`main.tex:265-277`) | Supported? | Basis |
|---|---|---|---|
| 1 | Vietnamese ESG corpus, 115 issuers, 1,416 documents | **Partly** | 115 verified correct; 1,416 is the *crawl* count while 1,216 were classified, and the abstract says the 1,416 "was crawled **and ESG-classified**" (P7) |
| 2 | Independent conduct channel, 4,537 articles / 662 outlets, `source_type`-separable | **Partly** | The channel and the stamp are real, and the graph is verifiably free of cross-ticker contamination. But 4,537/662 are unsupported (measured 3,797 URLs / 716 outlets), and the domain-level independence guard is a no-op for all five issuers (P8) |
| 3 | Temporal KG schema, 28/48/76, eight principles, machine-checkable invariants | **Yes** | Counts verified exactly against `config/schema.json`; `test_temporal_invariants.py` passes 18/18 on the real graph. **Caveat:** the schema is never actually presented anywhere in the thesis (see below) |
| 4 | Dual-standard TT96↔GRI axis, confirmed-only crosswalk, materialised as structure | **Partly** | 26 `equivalentTo` edges on disk match the stage stats; the crosswalk and `standard_of()` ownership fix are real and well described. Undercut by the append-only accumulation: ~20% of the alignment edges behind the headline 50.53% are unattributable to the described run |
| 5 | Label-free evaluation instrument, "demonstrated on three controlled before/after ablations" | **NO** | The ablations do not exist in the thesis, and the gold set has no code consumer (P6). The instrument exists and one before/after is already computed — nothing is reported |
| 6 | Never emits a greenwashing score, because no label exists to validate one | **Yes** | Formalised at `main.tex:1194-1213`, honoured throughout, and the deleted softmax-scoring pass is disclosed rather than hidden. The strongest contribution in the list |

**Three claim-level problems beyond the table.**

**The schema — contribution #3 — is never shown.** Five passages send the reader to "the schema
from Chapter 1" (`main.tex:1395`, `:1583`, `:1734`, `:1878`, `:1904`) for a specification Chapter 1
does not contain; its only schema content is one clause in the contribution list. There is no schema
table, class list or edge-label list anywhere in the document. The artifact is correct — it is just
never presented.

**The central empirical constraint is measured on one issuer and generalised to five.** The 15.8×
claim/conduct asymmetry is measured on AAA alone — Chapters 2 and 3 consistently say "the issuer
analysed end to end" (singular) — and the abstract then drops the qualifier and adds causation:
448/464 unverified is "the direct consequence of a conduct channel roughly sixteen times smaller".
The thesis's own Table 4.4 refutes the single-ratio story: conduct pools are 68/52/190/3/29, a 63×
spread, and `main.tex:2265` correctly identifies pool *depth and density*, not one global ratio, as
what tracks signal. The abstract and §4.2 are arguing different things.

**The abstract's closing sentence is unsupported.** `main.tex:154-155`: "Scaling the graph beyond
five issuers is engineering already specified by the pipeline, not an open research question."
Nothing in the thesis tests scaling behaviour, and the thesis's own results contradict it — ADP has
a conduct pool of 3 and returns zero signal. Scaling issuers without scaling the independent
evidence channel reproduces 100%-unverified, which is a data-acquisition research problem. Given
that the resolved graph is not currently reproducible from its own inputs, this is the weakest
sentence in the document.

**On EmeraldMind provenance — audited specifically, and clean.** The thesis discloses this honestly
and prominently: named in the framing, given its own related-work subsection, and stated plainly at
`main.tex:217` — "This thesis therefore **adapts EmeraldMind's RAG-plus-knowledge-graph paradigm**
to the Vietnamese context and extends it with a second, independent evidence channel." The two
claimed points of departure are precisely the two the thesis argues EmeraldMind lacks. No
concealment. One gap worth one sentence: the reader is told about *intellectual* provenance but not
that the codebase ports EmeraldMind's steps 1→3 closely.

---

## 6. Improvement Roadmap

**Tier 1 — Correctness of what is reported (do first; P2's write-up depends on the P1 re-run).**

1. **Salt the adjudication cache key** with `sha256(ADJUDICATE_SYSTEM)` + model id; re-run
   `claims_vs_conduct` for the five tickers (401 pairs). Re-report 464/448/13/3 from that run.
   *Validate:* hits against the old cache drop to 0; add a test that a one-byte prompt change
   invalidates every entry. **2–3 h + small bounded LLM spend.**
2. **Fix `anchor_kpi`'s glob** and add a 100%-failure guard that exits non-zero; re-run
   `build_validated` (offline, free). *Validate:* `raw_matches > 0`; two tests go green untouched.
   **1 h.**
3. **Record the full parameter set** in `*_crosscheck_stats.json`: `min_topic_overlap`,
   `provider_order`, resolved **model id**, prompt hash. Without the model id the run is not
   citable. **30 min.**

**Tier 2 — Reporting integrity (the bulk of the value).**

4. **Add the before/after precision subsection** to §4.4: 200 pairs labelled from a 226 population;
   26.5%/35.0% overall and ~6–9% on contradictions pre-fix; 86.7% on the survivors post-fix; cited
   volume 226 → 24. Frame as the project's strongest result. **3–4 h.**
5. **Write Chapter 5 (Discussion + Threats to Validity) and Chapter 6 (Conclusion).** Threats must
   name: LLM non-determinism, LLM-judging-LLM, the 15-pair/one-issuer base, the 226→24 collapse,
   news recency and outlet bias, classifier precision, and the indicator tier's zero contribution.
   Resolves three dangling forward references. **6–8 h.**
6. **Fix contribution #5** — report the ablations that exist (the NC before/after is computed and
   free) or reword the claim and delete the three forward references. **2–3 h.**
7. **State the aggregate evaluation base** in one paragraph, mirrored in the abstract: 15 pairs, one
   issuer, 16 of 464 claims verdicted, and the indicator tier at 0 of 401. **1 h.**
8. **Report AC1 = 0.818 / α = 0.696 / κ = 0.698 on n = 200** as the instrument's agreement; cite
   `landis1977measurement`; keep 15/15 as the subset observation. **1 h.**
9. **Reword the corpus claims**: 1,416 retrieved / **1,216 classified**; **115** issuers; **3,797
   unique articles (4,582 crawled documents) from 716 outlets**; "sixteen times" → "roughly
   eighteen". Reconcile Chapter 2's news table with Chapter 4. **2–3 h.**

**Tier 3 — Completeness and hygiene.**

10. **Add CIs or bare counts to Table 4.5**; soften the n=3 contradiction prose. **2 h.**
11. **Add a schema table** (Chapter 3 or the appendix) and repoint the five "Chapter 1" references.
    **3 h.**
12. **Report graph topology honestly in Chapter 4** — median degree 1, 67.1% leaves, 69.1%
    hub-incident, 44.6% degenerate `reportsKPI` — and state the multi-hop claim as conditional on
    `export_kgc` decomposition. **1–2 h.**
13. **Reconcile the single-issuer vs five-issuer framing**: compute the claim/conduct ratio per
    issuer (offline, cheap), report the range, requalify the abstract. **4 h.**
14. **Get the test suite green**: item 2 fixes two; update the stale `claims > 100` expectation and
    convert the vacuous provenance arm to an idempotence assertion. **2 h.**
15. **Re-run `quality --label final_baseline`** against the pinned graph (offline, free) — no
    quality report on disk matches 10,634/14,744; the closest is off by 11 nodes / 125 edges and all
    three predate the fix. **30 min.**
16. **Commit the uncommitted source changes** (`core/llm.py` retry logic, `registry/issuer.py`) and
    the three untracked authority docs (`EVALUATION_BASELINE.md`, `PROJECT_HISTORY.md`,
    `ANNOTATION_RESULTS.md`); decide deliberately on `capstone_report/` and the spreadsheets. **1 h.**
17. **Drive the self-verification guard and `STOPWORDS` from `config/issuer_registry.json`** rather
    than AAA-hardcoded sets; add a per-ticker assertion test. Note that AGG's retrieval is half
    carried by generic real-estate vocabulary (`dau tu`, `phat trien`, `bat dong san`) that survives
    the AAA-only stopword list. **2–3 h.**
18. **Bibliography and factual sweep**: five orphan entries, the Kim 2022/2023 year mismatch, the
    incomplete venue list (contribution #1 says "HNX and UPCoM" but the table also lists OTC and
    KHAC), provider naming in Table 4.4's caption, and **delete the "scaling is engineering not
    research" sentence**. **2–3 h.**
19. **Decide the RAG comparison**: include it with the ~47× pool asymmetry in the same caption, or
    state its absence explicitly and delete the two orphan citations. Do not leave the silent middle
    ground. **1 h (exclude) / 1–2 d (include).**

---

## 7. Minimum Viable Fix Set

The smallest set that makes the thesis defensible. Everything here is Tier 1 or Tier 2 above.

| # | Fix | Why it is non-negotiable | Effort |
|---|---|---|---|
| 1 | Salt the cache key and re-adjudicate the 401 pairs | Otherwise the reported verdicts are not the output of the submitted code. This is a correctness issue, not a presentation one | 2–3 h + small spend |
| 2 | Fix `anchor_kpi`'s glob + add the failure guard | A pipeline stage silently producing nothing, detected by its own tests, left standing | 1 h |
| 3 | Add the before/after precision subsection | Closes the one gap an examiner could read as selective reporting — and it is the project's best result | 3–4 h |
| 4 | Write Chapter 5 (Discussion + Threats) and Chapter 6 (Conclusion) | A thesis without a conclusion is structurally incomplete; also discharges three dangling references | 6–8 h |
| 5 | Fix contribution #5 (report the ablations or drop the claim) | An unsupported numbered contribution is the most attackable item in the document | 2–3 h |
| 6 | State the aggregate evaluation base, in the abstract and Chapter 5 | Pre-empts the obvious objection at zero cost | 1 h |
| 7 | Reword the corpus figures to match the pinned data | Three unsupported numbers in the abstract | 2–3 h |
| 8 | Report AC1 = 0.818 on n = 200 alongside the 15/15 | Removes an avoidable appearance of scope-shopping | 1 h |
| 9 | Record model id + `min_topic_overlap` in the stats file | Without it the reported run is not citable | 30 min |
| 10 | Get the test suite green and re-run `quality --label final_baseline` | A 4-red suite and no matching quality report undermine every reproducibility claim | 2.5 h |

**Total: roughly 22–28 hours plus one small, bounded LLM spend on 401 adjudication pairs.** Nothing
in this set requires re-crawling, re-extracting, or rebuilding the graph.

Deliberately **excluded** from the minimum set, as future work rather than submission blockers: the
RAG comparison (item 19), rebuilding `resolved_graph.json` to remove accumulated axis edges (a real
re-run cost — footnote Table 4.2 instead), wiring the indicator-axis retrieval tier so it can
actually fire, driving the independence guard from the registry, and expanding the conduct channel
beyond 41 documents. That last one is the highest-value research direction the project has.

---

## 8. Final Assessment

**The research is sound; the reporting is not yet finished.**

The design decisions that matter are right, and several are better than the literature this thesis
positions itself against. Treating "unverified" as a first-class outcome rather than forcing a
verdict is correct. Refusing to emit a greenwashing score in the absence of any label against which
one could be validated is correct, formally argued, and honoured throughout. Building an independent
conduct channel at all — the property that distinguishes this from disclosure-only detection — is
the right response to the Delmas–Burbano definition the thesis adopts. The round-trip KPI grounding
result (3,912/4,001 = 97.78%) is a genuine external check against a reference no pipeline stage can
edit, and it is the best-designed measurement in the document and currently under-sold. The temporal
invariants are enforced by a linter that passes on the real graph, not merely documented. The
annotation instrument — blindness enforced by a code whitelist, protocol frozen before results were
seen, label definitions biased against the system, attention checks with a pre-declared void
threshold — is better built than most, and the refusal to conflate it with the unperformed rubric
panel is exactly the kind of restraint that is easy to fudge and was not fudged.

The engineering shows real discipline in places that matter: `temperature=0` everywhere,
byte-for-byte prompt pinning, vacuity guards that make tests refuse to pass by doing nothing, an
append-only assertion protecting previously-paid dossiers, retry semantics that distinguish 5xx from
4xx with the reasoning written down, and a quarantine directory with a written justification instead
of a silent delete. The `unfixable_triples.json` contract — every dropped triple carrying its
validation errors and source file — is exemplary.

Against that, two things must be fixed because they are not presentational. The adjudication cache
omits the prompt from its key, so the verdicts the thesis reports were produced by a prompt that no
longer exists in the tree, and a re-run would replay 96.3% of them rather than recompute. And a
pipeline stage produces nothing at all, silently, because its default path still points at a
directory deleted ten days ago — a failure its own tests correctly detect and that was left standing.

The largest remaining problem is neither of those. It is that **the thesis is honest in every part
and over-flattering in the sum.** Three of five issuers return zero signal, all fifteen labelled
pairs belong to one issuer, the graph-native retrieval path fired zero times out of 401, and 16 of
464 claims received any verdict — each disclosed somewhere, none ever aggregated, and with no
conclusion chapter in which the aggregation would naturally live. Fixing that costs a paragraph and
a chapter, not an experiment.

The one thing this review would most want changed is also the cheapest: **report the before/after.**
Two independent domain experts confirmed roughly a third of the system's cited output before the
contamination fix and 86.7% after, while cited volume fell from 226 pairs to 24. That is a
quantified, externally validated engineering result with a mechanism, a cost and a direction — and
it is currently sitting unreported in `docs/ANNOTATION_RESULTS.md` while the thesis presents only
the favourable half. Reporting both halves would simultaneously remove the review's most serious
criticism and give the thesis its strongest result.
