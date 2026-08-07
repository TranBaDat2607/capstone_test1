"""
Reciprocal-rank fusion (RRF) of the lexical and semantic result lists.

Rank-based, not score-based, and that is the whole point: BM25 scores are unbounded
(they depend on idf and document length) while cosine lives in [-1, 1]. Summing the raw
numbers would let BM25 decide every ranking on its own, so the semantic channel would be
present in the code and absent from the results. RRF only ever looks at a document's
POSITION in each list, which is comparable across the two.

    score(d) = sum_i  w_i / (k + rank_i(d))       rank counted from 1, k = 60

k = 60 is the constant from the original RRF paper; it damps the top of each list enough
that one channel's first place cannot outweigh agreement between both channels.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_K = 60


def rrf_fuse(rankings: Sequence[Sequence[Tuple[int, float]]],
             k: int = DEFAULT_K,
             weights: Optional[Sequence[float]] = None) -> List[Tuple[int, float]]:
    """Fuse ranked (doc_index, score) lists into one ranking. Union, not intersection."""
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError(f"got {len(rankings)} rankings but {len(weights)} weights")

    fused: Dict[int, float] = {}
    for ranking, weight in zip(rankings, weights):
        for position, (doc_index, _score) in enumerate(ranking):
            fused[doc_index] = fused.get(doc_index, 0.0) + weight / (k + position + 1)

    return sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))


def rank_map(ranking: Sequence[Tuple[int, float]]) -> Dict[int, int]:
    """doc_index -> its 0-based position, for reporting which channel found what."""
    return {doc_index: position for position, (doc_index, _s) in enumerate(ranking)}
