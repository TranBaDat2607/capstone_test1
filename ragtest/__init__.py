"""
ragtest — a hybrid RAG retriever over the ESG sentences already extracted by this project.

It builds NOTHING new upstream: the corpus is read straight out of the existing
`data/outputs/esg_extracted/esg_all_records.jsonl` (282,195 ESG-classified sentences from
1,095 annual-report PDFs), filtered down to the 5 companies the project actually uses.
No pipeline stage is re-run.

Query direction is news -> claim: you paste a sentence from a news article, and the
retriever returns the annual-report ESG sentences ("claims") of that same company that
the news is talking about.

Layers:
    corpus      build/filter/clean the claim-side corpus         (offline)
    lexical     BM25 keyword search                              (offline)
    dense       cosine search over cached embeddings             (offline once embedded)
    fusion      reciprocal-rank fusion of the two                (offline)
    retriever   hybrid search + per-company filter               (offline)
    rerank      GLM listwise reranking                           (paid)
    answer      GLM claim-matching verdict                       (paid)
    store       append results as JSONL for the evaluation       (offline)
"""
