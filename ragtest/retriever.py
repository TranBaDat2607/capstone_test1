"""
The hybrid retriever: BM25 + dense cosine, fused by RRF, filtered per company.

The per-company filter is applied INSIDE both searches, not as a post-filter on the fused
top-k. That distinction is load-bearing: AAA has 5,692 sentences and ADP has 530, so a
global top-50 for an ADP query would be filled by the big companies and leave nothing
after filtering — the small company would silently return no results.

Everything here is offline once the embeddings are cached. The only paid call is the
single query embedding, and only when a `embedder` is supplied.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set

import numpy as np

from .config import DEFAULT_POOL, DEFAULT_TOP_K, RRF_K
from .dense import DenseIndex
from .fusion import rank_map, rrf_fuse
from .lexical import BM25Index


class HybridRetriever:
    def __init__(self, corpus: Sequence[Dict[str, Any]], embeddings: np.ndarray,
                 embedder: Any = None, bm25: Optional[BM25Index] = None):
        if len(corpus) != len(embeddings):
            raise ValueError(f"corpus has {len(corpus)} rows but embeddings has "
                             f"{len(embeddings)} — the index is stale, rebuild it")
        self.corpus = list(corpus)
        self.bm25 = bm25 or BM25Index(self.corpus)
        self.dense = DenseIndex(embeddings)
        self.embedder = embedder
        self._by_ticker: Dict[str, Set[int]] = {}
        for index, row in enumerate(self.corpus):
            self._by_ticker.setdefault(row.get("ticker"), set()).add(index)

    def tickers(self) -> List[str]:
        return sorted(t for t in self._by_ticker if t)

    def retrieve(self, query: str, ticker: Optional[str] = None,
                 top_k: int = DEFAULT_TOP_K, pool: int = DEFAULT_POOL,
                 weights: Sequence[float] = (1.0, 1.0)) -> List[Dict[str, Any]]:
        """Return up to `top_k` corpus rows, best first, each stamped with how it was found."""
        allowed: Optional[Set[int]] = None
        if ticker is not None:
            allowed = self._by_ticker.get(ticker, set())
            if not allowed:
                return []

        lexical_hits = self.bm25.search(query, top_k=pool, allowed_ids=allowed)

        dense_hits: List = []
        if self.embedder is not None:
            query_vector = np.asarray(self.embedder.embed([query]))[0]
            dense_hits = self.dense.search(query_vector, top_k=pool, allowed_ids=allowed)

        fused = rrf_fuse([lexical_hits, dense_hits], k=RRF_K, weights=weights)
        lexical_rank, dense_rank = rank_map(lexical_hits), rank_map(dense_hits)
        lexical_score = dict(lexical_hits)
        dense_score = dict(dense_hits)

        results: List[Dict[str, Any]] = []
        for doc_index, score in fused[:top_k]:
            row = dict(self.corpus[doc_index])
            row.update({
                "score": score,
                "bm25_rank": lexical_rank.get(doc_index),
                "bm25_score": lexical_score.get(doc_index),
                "dense_rank": dense_rank.get(doc_index),
                "dense_score": dense_score.get(doc_index),
            })
            results.append(row)
        return results
