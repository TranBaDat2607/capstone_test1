# ragtest — hybrid RAG over the extracted ESG claims

Paste a sentence from a news article, get back the ESG claims **that same company** made
in its annual reports, plus a GLM verdict on whether the news supports or contradicts them.

This package **builds nothing upstream**. The corpus is read straight out of
`data/outputs/esg_extracted/esg_all_records.jsonl`, which `data_processing.extract_esg`
already produced. No pipeline stage is re-run and no artifact of the `esg_kg` pipeline is
modified.

## What it is for

The `esg_kg` pipeline runs **claim → conduct** (step07 takes a claim and looks for news
that bears on it). `ragtest` runs the same pairing from the other end, **news → claim**,
as a plain retrieval system rather than a graph traversal. That makes it the natural
comparison arm for the retrieval numbers in `evalu/out/retrieval_baselines.json`.

## Retrieval design

| stage | what | cost |
|---|---|---|
| company filter | alias match on the sentence → one ticker; the index is filtered **before** searching | free |
| keyword | BM25 (Okapi, k1=1.5, b=0.75), Unicode-aware Vietnamese tokenizer | free |
| semantic | cosine over `text-embedding-3-small` (1536d), numpy brute force | free after build |
| fusion | reciprocal-rank fusion, k=60 | free |
| rerank | GLM listwise — one call, returns a permutation | paid |
| verdict | GLM: which claim matches, supports/contradicts/irrelevant, evidence quote | paid |

Three choices worth knowing about, because each fixes a failure that is invisible in the
output when you get it wrong:

- **The company filter runs inside both searches, not after fusion.** AAA has 3,507
  indexed sentences and ADP has 345. A global top-50 for an ADP query is filled by the big
  companies, and post-filtering it leaves nothing — the small company would silently
  return no results.
- **Fusion is rank-based, not score-based.** BM25 scores are unbounded; cosine is in
  [-1, 1]. Adding the raw numbers lets BM25 decide every ranking on its own, so the
  semantic channel would be present in the code and absent from the results.
- **The reranker may only permute.** It cannot add, drop or rewrite a candidate, and a
  reply it cannot parse degrades to the fusion order instead of raising. A reranker that
  crashes on a refusal is worse than one that quietly does nothing.

There is **no rerank model on the endpoint** (`https://api.xah.io/v1` serves chat and two
embedding models; nothing with "rerank" in its `/v1/models` listing) and torch is
deliberately absent from `requirements.txt`, so a local cross-encoder is out too. The chat
model does the reranking.

## Corpus

8,956 claim sentences from **37 annual reports** across the 5 companies in use — down
from 12,516 raw ESG-labeled sentences after dropping bare page numbers and deduping
repeated cover-page banners (those are lexically dense and would win any query that
mentions the company name).

| ticker | sentences |
|---|---|
| AAA | 3,507 |
| ACC | 1,214 |
| ACG | 2,079 |
| ADP | 345 |
| AGG | 1,811 |

Every row keeps `(source_pdf, page, sentence_index)`, and its `doc_id` **is** that
location (`AAA_2013.pdf#p15#s1`) — so a claim the model cites can be opened at the right
report page.

## Commands

```bash
# 0. one-off: build the index (embeds once, then cached on disk — re-runs are free)
python ragtest/build_index.py --dry-run      # counts only, no API call
python ragtest/build_index.py

# 1. ask it things
python ragtest/query.py --interactive
python ragtest/query.py -q "Nhựa An Phát Xanh ra mắt bao bì phân huỷ sinh học"
python ragtest/query.py -q "..." --ticker AAA          # force the company
python ragtest/query.py -q "..." --no-llm              # retrieval only, zero API cost

# 2. batch from the news corpus already on disk
python ragtest/query.py --from-news --ticker AAA --limit 20
```

Flags: `--top-k` (candidates to the reranker, default 10), `--final-k` (shown + sent to
the verdict, default 5), `--pool` (per channel before fusion, default 50), `--no-rerank`,
`--no-verdict`, `--chat-model`, `--embed-model`, `--index-dir`, `--results`.

## Output

Artifacts land in `data/outputs/ragtest/` (git-ignored, per CLAUDE.md's layout rule):

```
corpus.jsonl          one row per claim sentence, with provenance
embeddings.npy        (n_docs, 1536) float32 — row i pairs with corpus line i BY POSITION
embed_cache.npy       the same vectors keyed by content, so nothing is ever embedded twice
embed_cache_keys.json sha1(model + text) per cache row, in row order
meta.json             model, dims, per-ticker counts, build time
query_results.jsonl   one row per query — the evaluation record
```

The cache holds vectors as float32 in a `.npy`, not as JSON floats: 8,956 x 1,536 floats
as JSON text is ~275 MB to duplicate a 55 MB matrix, and a build re-saves every 512
sentences, so the JSON form costs O(n²) disk writes — and `data/` is synced to the team's
Hugging Face snapshot, so the waste would be uploaded too. A legacy `embed_cache.json`
from an older build is migrated automatically on first use (nothing is re-embedded).

Each `query_results.jsonl` row keeps the query, the detected company, **every** candidate
with its `bm25_rank` / `dense_rank` / `fusion_rank` / `rerank_rank` and provenance, and the
verdict. That is enough to re-score a run offline — "would top-3 have been enough?", "did
reranking change the top-1?" — without paying for it twice.

## Tests

Plain assert scripts, offline, no API key needed (the paid path is driven by stubs):

```bash
python test/test_ragtest_corpus.py      # ticker/year parsing, boilerplate, dedup, traceability
python test/test_ragtest_retrieval.py   # VN tokenizer, BM25 idf, RRF, per-company filter
python test/test_ragtest_llm.py         # rerank permutation invariant, junk-reply handling, store
python test/test_ragtest_index_io.py    # index round-trip + the stale corpus/embedding guard
python test/test_ragtest_embed_cache.py # a cached text is never re-sent; float32 .npy storage
```

## Caveats

- **The index pairs corpus rows to embedding rows by position.** Rebuild the corpus
  without re-embedding and every result is quietly the wrong sentence. `load_index` and
  `HybridRetriever` both refuse a mismatched pair; do not work around them.
- **Company detection returns `None` rather than guessing.** A sentence naming no company
  is searched across all 5, and the output says so.
- **The verdict is advisory.** Same framing as step07: no ground-truth greenwashing label
  exists, so `supports`/`contradicts` is an opinion about two sentences, not a finding.
