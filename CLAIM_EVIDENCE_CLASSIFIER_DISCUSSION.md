# Claim–Evidence Classifier — Discussion Notes (2026-08-17)

**Status: DISCUSSION ONLY. Nothing here is implemented.** No code was written, no stage
was added, no file in the pipeline was modified. This is a handoff note so the next
planning session does not have to re-derive the numbers below.

**Question asked:** *if I can get labeled data for (claim, evidence) pairs, can I build a
model to predict supports / contradicts / unverified — and can I put my model vs the LLM
vs human labels in a comparison table in Experiments & Results?*

**Short answer:** yes to both, with one framing correction and four measurement caveats.
All are recorded below.

---

## 1. Framing correction: `unverified` is not a pair-level label

The pipeline already draws this line and any model must inherit it:

- **Pair level** `(claim, evidence)` → `supports` / `contradicts` / `irrelevant`.
  This is what `Adjudicator` (step07, `claims_vs_conduct`) emits per pair, and what
  `evalu/annotation.py`'s `LABELS = ("supports", "contradicts", "irrelevant")` uses.
- **Claim level** → `unverified` is an **aggregate**: retrieval returned nothing, or every
  returned pair came back `irrelevant`. Visible in the dossiers as
  `"assessment": "unverified_insufficient_evidence"` with `supporting_evidence: []`.

Putting `unverified` in the pair label space would make the model predict a property of
the **retriever**, not of the pair — its accuracy would silently track retrieval recall.

Train on the 3 pair labels; derive `unverified` by aggregation afterwards.

---

## 2. Labeled data that already exists on disk (verified 2026-08-17)

### 2a. Silver labels — 4,259 already-paid-for adjudications

Counted from `graph_output/crosscheck/adjudication_cache*.json` (6 files, gemini + the
historical openai runs):

| file | entries | supports | contradicts | irrelevant |
|---|---|---|---|---|
| `adjudication_cache.json` (gemini) | 887 | 59 | 14 | 814 |
| `adjudication_cache_openai.json` | 272 | 5 | 2 | 265 |
| `adjudication_cache_openai_ACC.json` | 112 | 6 | 0 | 106 |
| `adjudication_cache_openai_ACG.json` | 2,102 | 33 | 77 | 1,992 |
| `adjudication_cache_openai_ADP.json` | 534 | 21 | 13 | 500 |
| `adjudication_cache_openai_AGG.json` | 352 | 30 | 21 | 301 |
| **total** | **4,259** | **154** | **127** | **3,978** |

**Catch:** the cache is content-addressed. Each entry is
`sha256(prompt) -> {verdict, confidence, rationale, provider}` — **the claim and evidence
text are NOT stored.** Entry shape:

```json
{"verdict": "contradicts", "confidence": 0.8,
 "rationale": "Bằng chứng cho thấy ...", "provider": "gemini"}
```

**Recovery path (free, but conditional):** re-run `claims_vs_conduct` with the caches
warm — every pair is a cache hit, so no LLM call is made — instrumented to dump
`(claim_text, evidence_text, verdict, provider)` to JSONL. This is free **only** if
retrieval and the prompt are untouched; any change to either changes the hash key and the
run costs full price. The paid prompt templates are pinned byte-for-byte by their guard
tests, which helps here.

The dossiers (`*_claim_assessments.json`) are **not** a substitute source: they keep only
surviving supports/contradicts evidence, so the 3,978 `irrelevant` pairs (the majority
class) have no text there.

**Free label-quality signal:** pairs adjudicated by both gemini and the historical openai
caches give cross-provider agreement. Training on the agreeing subset yields a smaller but
cleaner silver set, and the disagreement rate is a real measured number about label noise.

### 2b. Gold labels — the 43-pair census

`sheetA_43pairs_filled.xlsx` / `sheetB_43pairs_filled.xlsx` at the repo root, two blind
external annotators, reproduced by `python evalu/score_census_43.py`.

Full output of that script, run 2026-08-17:

```
Population by company (from the answer key): {'ACG': 42, 'AGG': 1}

=== Annotator A (Thai Anh Tuan) ===
  overall       27/43 = 62.8%  Wilson95%[47.9%, 75.6%]
  supporting_evidence      22/37 = 59.5%  Wilson95%[43.5%, 73.7%]
  contradicting_evidence   5/6   = 83.3%  Wilson95%[43.6%, 97.0%]
  same_company_only  18/19 = 94.7%
  confusion (system asserts -> human label):
    supports     (n=37)  supports=22  contradicts=0  irrelevant=15
    contradicts  (n=6)   supports=1   contradicts=5  irrelevant=0

=== Annotator B (Do Kim Ngoc) ===
  overall       28/43 = 65.1%  Wilson95%[50.2%, 77.6%]
  supporting_evidence      23/37 = 62.2%  Wilson95%[46.1%, 75.9%]
  contradicting_evidence   5/6   = 83.3%  Wilson95%[43.6%, 97.0%]
  same_company_only  15/15 = 100.0%
  confusion (system asserts -> human label):
    supports     (n=37)  supports=23  contradicts=0  irrelevant=14
    contradicts  (n=6)   supports=1   contradicts=5  irrelevant=0

Inter-annotator agreement, n=43:
  raw agreement  42/43 = 97.7%
  Cohen's kappa  0.960 (almost perfect)
  Gwet's AC1     0.967 (almost perfect)
  disagreement: pair_id=2f274900b2d1  A=irrelevant  B=supports
```

Derived gold distribution (annotator A): supports 23, contradicts 5, irrelevant 15.
So the gold set **does** contain an `irrelevant` class — both stages of a two-stage model
are evaluable on it. Contradicts is the thin class at 5–6.

### 2c. The earlier 200-pair round

Recoverable from git only — `git show bb7093b:sheetA.xlsx` (also `sheetB.xlsx`,
`sheetC.xlsx`), deleted from the working tree in `bb7093b`. Different population,
different agreement level (κ=0.714 / AC1=0.818). **Do not quote its agreement figures
alongside the 43-pair census's 0.960/0.967** — they are separate rounds.

---

## 3. The binding constraint

**127 contradicts, not 4,259.** Contradiction is the class the thesis is about, it is ~3%
of the silver data, and only 6 pairs of it are in gold.

Consequences:

- **Do not train a flat 3-way classifier** on a 93%-irrelevant distribution — it will
  learn "predict irrelevant". Two-stage is the better fit:
  1. *relevant vs irrelevant* over all 4,259 (the majority-class stage, plenty of data);
  2. *supports vs contradicts* over the 281 survivors (154/127 — the one place the data
     shape is actually favourable).
- **n=6 contradicts in gold** gives a Wilson CI of `[43.6%, 97.0%]`. No claim of the form
  "our model is more precise on contradictions than the LLM" is supportable from it.
- **Exclude the 43 gold pairs from training.** Silver comes from the same adjudicator that
  produced them; leakage is easy to introduce by accident.

---

## 4. The finding that makes the section worth writing

From the confusion tables above: **every LLM error is a relevance error.**

- 0 of 37 asserted `supports` were flipped to `contradicts` by either annotator — the
  polarity judgment is essentially never wrong.
- 15 (A) / 14 (B) of 37 asserted `supports` were judged `irrelevant` — the
  retrieval-plus-relevance gate is wrong ~40% of the time.
- `same_company_only` confirms it: 18/19 and 15/15 correct once the annotator marked the
  evidence as actually about the claim's company.

This reframes the contribution. Stage 1 (*relevant vs irrelevant*) attacks the **measured**
bottleneck and is backed by 3,978 silver labels, not 127.

Claim to make: *"the adjudicator's errors are concentrated in relevance rather than
polarity, and a deterministic classifier distilled from 4k adjudicated pairs closes that
gap at zero marginal cost."*
Claim **not** to make: *"our model judges contradiction better than an LLM"* (unprovable at
n=6).

---

## 5. Build order discussed (cheapest first)

1. **Zero-shot XNLI baseline** (XLM-R fine-tuned on XNLI, off the shelf). Zero labels
   needed. Gives the floor row in the comparison table.
2. **Distilled cross-encoder — the recommended contribution.** PhoBERT-base or XLM-R
   fine-tuned on the silver pairs, two-stage per §3, evaluated on the 43 gold. Fits the
   repo shape as a **separate derived artifact** (like `export_kgc`) that never patches
   `resolved_graph.json`, Neo4j, or the frozen evaluation baseline.
3. **Human-supervised from scratch** — needs ~1–2k human-labeled pairs to beat option 2.
   Not reachable on the current timeline.

**Honest ceiling on option 2:** a distilled student cannot beat its teacher on the
teacher's own systematic errors. It buys **reproducibility, cost, and coverage** (all pairs
scorable instead of a `--max-llm-pairs` budget) — not accuracy. Framing it as "an improved
greenwashing detector" invites the obvious reviewer question.

**First dependency for everything above:** the cache-replay extraction script that turns
the warm caches into a `(claim, evidence, verdict, provider)` JSONL training set. Offline
and free. Not written.

---

## 6. Table design for Experiments & Results

Humans are the **reference axis and the ceiling row**, never a competing system. A row
reading "Human — 100%" is meaningless.

### Table A — agreement with human gold (n=43)

| System | Overall prec. (n=43) | supports (n=37) | contradicts (n=6) | Determ. | Cost/pair |
|---|---|---|---|---|---|
| Zero-shot XNLI baseline | — | — | — | ✓ | 0 |
| Distilled cross-encoder (ours) | — | — | — | ✓ | 0 |
| LLM adjudicator (gemini) | 62.8% / 65.1% | 59.5% / 62.2% | 83.3% | ✗ | paid |
| *Human A vs B (agreement ceiling)* | *97.7%, AC1 0.967* | — | — | — | — |

### Table B — fidelity to the LLM on all 4,259 cached pairs

No human labels needed, large n, tight CIs. Measures how well the distillation worked,
plus cost / latency / determinism. **Different question — do not merge into Table A.**

Plus a confusion matrix for the model mirroring the existing `tab:expert-confusion`.

### Four rules for those tables

1. **Pick one gold.** A and B disagree on exactly one pair (`2f274900b2d1`). Adjudicate it
   and report against a single adjudicated gold instead of carrying two numbers per cell.
2. **Use McNemar, not two point estimates.** The CIs overlap heavily, but both systems are
   scored on *the same 43 pairs*, so a paired McNemar test on the discordant cells is valid
   and far more powerful. `docs/AGENT_AB_EVALUATION.md` already prescribes this.
3. **Caption the external-validity limit.** 42 of 43 pairs are ACG — effectively a
   single-company census. Belongs in the caption, not a footnote.
4. **Keep the 43 out of training** (repeat of §3).

---

## 6b. ADDENDUM 2026-08-17 — the replay is BUILT, and it moves three numbers above

`src/esg_kg/export/replay_adjudications.py` (stage `12`, `python src/run.py
replay_adjudications`) is implemented and green (`test/test_replay_adjudications.py`, 12
groups). **Recovery is 4,259/4,259 cache entries — 100%, zero unrecovered, all six files.**
Output: `graph_output/replay/adjudicated_pairs.jsonl` + `replay_stats.json`.

Four things §2a and §3 above got wrong, all of them now measured:

**(a) "Re-run `claims_vs_conduct` with the caches warm" does not work — but not for the
reason you'd guess.** step07 constructs a real `Adjudicator`, which pays on every miss; and
the historical runs used different retrieval settings anyway (2,102 OpenAI entries for ACG vs
the 2026-08-13 run's 359 candidate pairs), so no single retrieval config recovers them all.
The tool therefore **does not reproduce retrieval**: it probes the full claims × conduct cross
product (481 × 342 ≈ 165k pairs, ~1s), a strict superset of any historical retrieval, and lets
the cache lookup be the filter. It cannot construct a provider by design; an AST test pins that.

That choice also bought immunity to the 2026-08-14 P5 reorder for free. P5 (issue #20) rebuilt
the graph 10,634/14,744 → 10,624/15,130, which breaks any recovery route keyed on **node
index** — reconstructing pairs from the dossiers' own `node_index` fields recovers **0%**,
they now land on different classes. The cross-product probe never trusts an index, only the
text at it, so **both the current graph and `_pre_p5_backup/resolved_graph.json.bak` recover
4,259/4,259 with byte-identical rows** (pinned by
`test_real_caches_replay_and_are_index_independent`). No need to hunt for the old snapshot.
The caveat is forward-looking: a future rebuild that re-extracts or re-words claim text would
break recovery silently, since a changed text is just a key that misses — `MIN_RECOVERY_RATE`
aborts the run rather than write an empty training set.

**(b) The 4,259 are TWO prompt generations, and the older one is wrong where it matters.**
The P1 fix (`067b93f`, 2026-08-13) salted the cache key. Unsalted 3-part keys are the OLD
pre-halo-guard prompt; salted 4-part keys are today's. Both are live in
`adjudication_cache.json` for overlapping pairs:

| generation | rows | supports | contradicts | irrelevant |
|---|---|---|---|---|
| current (salted, `gemini-2.5-flash`) | 401 | 36 | 6 | 359 |
| legacy (unsalted, pre-fix prompt) | 4,319 | 124 | 135 | 4,060 |

391 pairs carry both. They disagree on **6.1% overall — but 43.8% (21/48) once either verdict
is non-`irrelevant`**, i.e. precisely on the classes the thesis is about. (Consistent with the
census: legacy verdicts match the current dossiers 23/43, salted ones 42/43.) Training on the
merged 4,259 would feed the model contradictory labels for byte-identical text.

**(c) The real class counts, deduped on TEXT.** 4,720 rows over 4,259 entries over **3,520
distinct text pairs** — two different node pairs can carry identical text and share one paid
call, so a set deduped on node index double-counts. Preferring `current` and falling back to
`legacy`:

```
stage 1  relevant 217  vs  irrelevant 3,298
stage 2  supports 107  vs  contradicts 110
```

So §3's "127 contradicts" is really **110 — of which only 6 come from the current prompt.**
The binding constraint is tighter than the doc assumed, and the two-stage split in §3 is even
more clearly the right shape: stage 1 keeps ~3.5k labels, stage 2 is the balanced 107/110.

**(d) The cross-provider signal is real and cheap.** 235 pairs were adjudicated by both
gemini and openai; they agree on **229 (97.5%)**. That is a usable label-noise floor, and it
is far higher than the two-generation agreement — the prompt change moved verdicts much more
than the provider swap did.

Open question this raises for §5: the honest silver set for stage 2 is ~217 current+legacy
pairs, and only 42 of them carry a current-prompt label. Re-adjudicating the legacy pairs
under the current prompt is the obvious fix and is NOT free — it is ~3.5k paid calls, or a
targeted ~200 for the non-`irrelevant` ones, which is cheap and would remove the (b) problem
outright. **Done — see §6c.**

---

## 6c. RESOLVED 2026-08-17 — the legacy labels were re-adjudicated, and most were wrong

`src/esg_kg/crosscheck/readjudicate.py` (stage `13`) asked the CURRENT prompt about all
**182** legacy pairs that were non-`irrelevant` and had no current verdict. 182/182 answered.
Cost: 182 Gemini `gemini-2.5-flash` calls, appended to `adjudication_cache.json` under the
current salt — so a later `claims_vs_conduct` run gets them free.

**104 of 182 labels changed (57%).** The transition table:

| legacy → current | n |
|---|---|
| contradicts → **irrelevant** | **81** |
| supports → supports | 58 |
| contradicts → contradicts | 20 |
| supports → irrelevant | 14 |
| contradicts → supports | 3 |
| supports → contradicts | 1 |
| (mixed-provider legacy pairs) | 5 |

That single 81 is the halo-reasoning bug the 2026-08-07 prompt tightening was written to
kill, measured: the old prompt read an unrelated adverse event as contradicting a claim on a
different topic. **Only 20 of 104 legacy `contradicts` survive as `contradicts`.**

### What the training set actually looks like now

Deduped on text, current-prompt preferred, legacy as fallback:

```
stage 1   relevant    124   vs   irrelevant  3,396
stage 2   supports     96   vs   contradicts    28      <- 124/124 current-prompt labelled
```

**Stage 2 is now single-generation — no mixed labels at all.** That was the point. But the
price is that §3's "the one place the data shape is actually favourable" (154/127) **is no
longer true**: contradicts collapsed from 110 to **28**, and stage 2 is now both small and
3.4:1 imbalanced.

Consequences to carry into §5, replacing §3's optimism:

- Training on the pre-fix silver set would have taught the model the halo-reasoning bug on
  **81 of its 110** contradiction examples. Doing this first was not optional.
- 28 silver contradicts + 6 gold contradicts is a thin basis for anything. The two-stage
  split still stands, but stage 2 is now the *scarce* stage, not the comfortable one —
  consider merging it into a single relevance-first model with a weak polarity head, or
  budgeting real human labels specifically for contradictions.
- Stage 1 is unaffected and still has ~3.5k labels; the §4 finding (errors are relevance
  errors) is if anything strengthened — the current prompt moved 95 pairs INTO `irrelevant`
  and only 4 out of it.
- Caveat that must be stated in any writeup: only the non-`irrelevant` legacy pairs were
  re-adjudicated. The 2,992 legacy `irrelevant` labels were NOT re-checked, so stage 1's
  negative class is still pre-fix-prompt. The bias direction is known (the new prompt is
  stricter, so it would mostly confirm them) but it is not measured.

---

## 7. Repo facts relied on

- `evalu/` is in this repo (ported in `bb7093b`, issue #17); `evalu/score_census_43.py` is
  the reproducible source of the §2b numbers; `evalu/annotation.py` `score()` and
  `evalu/iaa.py` back the precision and agreement figures.
- Pair-level verdicts come from `Adjudicator` in `claims_vs_conduct` (step07); its
  `AdjudicationCache` sits on `core/llm_cache.py`'s content-addressed `ContentCache`.
- Nothing here touches the frozen evaluation baseline in `docs/EVALUATION_BASELINE.md`
  (10,634/14,744 → 10,624/15,130 after the issue #20 addendum; 464 dossiers, 5 issuers).
  A classifier would be a new derived artifact, not a re-run of that snapshot.
