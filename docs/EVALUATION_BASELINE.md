# The evaluation baseline — FROZEN

Extracted from `CLAUDE.md` on 2026-08-12. **Read this before quoting any evaluation number,
in the report or anywhere else.**

The capstone report (`capstone_report/main.tex`, Chapter 4 "Experiments and Results")
and `evaluation_final_focused.docx` describe **one and the same measurement snapshot**,
generated 2026-08-08T04:24:57Z. **That snapshot is the canonical baseline.** Every
figure below is what the report says, and they agree exactly across both documents:

```
resolved graph          10,634 nodes / 14,744 edges
validated triples       14,500 kept / 807 unfixable
cross-check dossiers    464 claims across exactly 5 issuers: AAA ACC ACG ADP AGG
                        448 unverified (96.55%) / 13 supported / 3 contradicted
indicator alignment     718 / 1,421 claim-like nodes (50.53%)
```

**Never "correct" these against a fresher run on disk.** If a stage's output has moved
past the snapshot, the snapshot wins for reporting purposes — re-pin or re-run
deliberately, do not silently quote newer numbers into a document built on the old ones.

Three points that have already caused a wrong conclusion once, recorded so they don't again:

- **HAR is NOT a sixth issuer. The baseline is five.** `har_claim_assessments.json` /
  `har_crosscheck_stats.json` were moved to `graph_output/crosscheck/_excluded/` on
  2026-08-08. They are not merely out of scope, they are *stale*: their
  `claim_node_index` values (10,804+) are out of range for the 10,634-node graph, the
  stats file's issuer `node_index` 10561 lands on an unrelated AGG `Penalty`, and the
  resolved graph contains zero nodes with a `HAR`-prefixed `source_doc`. See that
  folder's `README.md`. `config/issuer_registry.json` keeps its HAR entry deliberately —
  `claims_vs_conduct` takes `--ticker` and never iterates the registry, so it cannot
  silently come back.
- **Table 4.3's `openai` provider caption is CORRECT — do not "fix" it.** Those five
  runs genuinely were adjudicated by OpenAI during the 2026-07-27 → 2026-08-04 window
  described under "Gemini is the default paid LLM provider" above. The caption is a
  historical record of how the reported run was produced, not a stale reference to
  removed code. `adjudication_cache_openai*.json` is that run's evidence: every cache
  entry recoverable for it carries `provider: "openai"`. The fact that the `--provider
  openai` code path was later removed does not make the record wrong.
- **The 2026-08-07 fix (`7c108f9`) landed AFTER the annotated pairs were adjudicated.**
  Anything measured from `adjudication_cache_openai*.json` describes the **pre-fix**
  adjudicator — before conduct retrieval was issuer-scoped, before the VN-aware
  min-topic-overlap gate, and before `ADJUDICATE_SYSTEM` was tightened against halo
  reasoning. Label such numbers "before the contamination fix", never "the system".

### The blind annotation (`sheetA.xlsx` / `sheetB.xlsx`) — and how it must be described

The evaluation machinery lives on `wip/gri-parser-and-eval` in **`evalu/`**, and that branch
is the authority for everything in this subsection — `evalu/annotation.py` (sheet builder +
`score()`), `evalu/iaa.py` (agreement), `evalu/ANNOTATION_PROTOCOL.md` (the protocol, fixed
before results were seen). **Do not hand-reconstruct these numbers; run `evalu`'s own code.**

- **It was annotated by two EXTERNAL DOMAIN EXPERTS, not by the authors** (confirmed by the
  user 2026-08-08): sheet A by **Thái Anh Tuấn**, CEO of Phúc Lộc Group; sheet B by **Đỗ Kim
  Ngọc**, Director of the Corporate Banking Division at VPBank. Both are independent of the
  research team. This resolves two constraints the whole label-free framework was built
  around (`docs/EVALUATION_WITHOUT_LABELS.md` §1.1): "no expert annotator is available" and
  "author self-annotation is not objective". **`ANNOTATION_PROTOCOL.md` §7 still says to
  describe this as author annotation — that instruction is now factually outdated**, and the
  protocol needs an addendum recording the real provenance (the freeze rule bars changing
  *criteria*, not recording *who annotated*). Blindness is still enforced in code
  (`DISPLAY_FIELDS` whitelist, guarded by `test_sheet_is_blind`), not by discipline.
- **Still NOT the "CEO / HRD / Auditor panel".** Those three panels live in `evalu/rubric.py`
  and belong to a different, still-unperformed study — a 5-point Likert rubric over four
  dimensions with expertise-weighted consensus. One annotator here happens to be a CEO; that
  does not make this session that panel. `ANNOTATION_PROTOCOL.md` §7's warning against
  conflating the two remains fully in force.
- **220 rows = 200 real pairs + 20 decoys.** The decoys are attention checks and are
  excluded from precision. Threshold: more than 3/20 marked non-`irrelevant` voids the
  session. **Observed: 2/20 for both annotators — the session stands.**
- **Agreement, on the 200 real pairs** (decoys inflate every figure — quote the 200):
  `relation` Gwet AC1 = **0.818**, Krippendorff α = 0.696, Cohen κ = 0.698 → substantial.
  `about_claim_company` AC1 = **0.480**, α = 0.346 → *fails* the threshold, so that column
  must not carry a reported number. The protocol asks for AC1/α as headline, not Cohen κ.
- **Precision only, never recall** — pairs adjudicated `irrelevant` are never written to a
  dossier, so a missed piece of evidence is unobservable. Population 226 cited pairs
  (99 supporting + 127 contradicting) across the 5 issuers; sample 200 = 88.5%, stratified
  by (ticker × verdict kind), seed 42. `llm_current_pairs.xlsx` (226 rows) is that **full
  population as a census**, not a post-fix template.
- **The before/after of the contamination fix already exists — do not claim it is missing.**
  Two independent routes, both already computed: (1) `precision.same_company_only` restricts
  to pairs the annotator judged to be about the right company, which *is* an estimate of
  post-fix precision computable from the same session because the fix only removes pairs —
  overall 26.5% (A) / 35.0% (B) versus 55.8% / 56.8% same-company-only; (2) NC.1/NC.2 moved
  28.76% FAIL → 100% PASS with `cross_feed = 0` (`evalu/out/1.text`, and
  `evaluation_report_nc_postfix.md`).
- **`sheetA`/`sheetB` CANNOT score `graphrag_vs_rag.xlsx`.** All three share the 220
  `pair_id`s and `evidence_text`, but the two arms retrieve *different kinds of object*:
  `sheetA.claim_text` equals `graph_claim` in only 37/220 rows and `rag_claim` in 1/220.

### The Graph-RAG vs RAG comparison — `ragtest/` + `test3/` (same branch)

**The RAG baseline code exists** (pushed 2026-08-08; an earlier search of this branch
predated it and wrongly concluded it was absent). `ragtest/` is the plain-RAG arm — BM25 +
dense, RRF fusion (`RRF_K = 60`), per-company filtering applied *inside* both searches, then
listwise reranking by the chat model because the GLM endpoint serves no rerank model.
`test3/graph_rag_arm.py` is the graph arm, running step07's own two-tier retrieval in
reverse (evidence → claim) and importing step07's helpers rather than copying them.
`test3/README.md` is an unusually honest design doc — read it before touching the numbers.

**The balance the README claims is real but incomplete.** It equalises the reranker, the
adjudicator and the labelling model, which is the trap arXiv 2502.11371 warns about. It does
**not** equalise the candidate universe: the graph arm ranks over 481 `SustainabilityClaim`
nodes, the RAG arm over ~21,950 ESG sentences for the same five issuers — a ~47× pool
difference. Coverage (71.8% vs 100%) and the text-similarity columns are confounded by that
before any retrieval mechanism is involved. Report it as a limitation; do not read coverage
as a mechanism result.

## What is actually on disk: sheetA / sheetB / sheetC / llm_current_pairs

`sheetA.xlsx` and `sheetB.xlsx` are the two annotators' **completed** sheets — 220 rows each,
`relation` filled in all 220 (A: 163 Irrelevant / 49 Supports / 8 Contradicts; B: 145 / 65 /
10). **`sheetC.xlsx` is a blank third copy**: identical header, identical `pair_id`s and
`evidence_text`, but `relation` is empty in all 220 rows. It is not a third annotator and
there was no third session — do not compute a three-way agreement from it, and do not read it
as annotation data that went missing. `llm_current_pairs.xlsx` (226 rows) is the full
cited-pair population as a census, not a post-fix template.

## `GRAPH_VS_RAG_COMPARISON.md` is a proposal, not this measurement

The root-level `GRAPH_VS_RAG_COMPARISON.md` (Vietnamese) is explicitly marked
*"Trạng thái: ĐỀ XUẤT, chưa triển khai"* and says so of itself: the worked numbers in its §4
are **illustrative fabrications** written to explain the arithmetic, not measurements. It
designs a different, still-unimplemented experiment (SERR, plus a two-directional Method B
added after Method A was found to condition on the graph's own successes — survivorship
bias). Never conflate it with the real `ragtest/` + `test3/` arms above, with
`graphrag_vs_rag.xlsx`, or with `graphrag_vs_rag_report.docx`.
