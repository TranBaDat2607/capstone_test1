"""
Dense (semantic) search: cosine similarity over cached embeddings.

Brute force with numpy on purpose. The corpus is ~12.5k sentences x 1,536 dims (~77 MB);
a full matrix-vector product is sub-millisecond, so an ANN index (faiss/chroma) would add
a dependency and an approximation for no measurable gain. numpy is already a project
dependency; faiss is not.

Unlike BM25, a zero score is still a result here — cosine 0 means "unrelated", not
"absent". Dropping zeros would make the per-company filter return nothing for a small
company (ADP has 530 sentences) whose rows happen to share no vocabulary with the query.
"""

from __future__ import annotations

from typing import List, Optional, Set, Tuple

import numpy as np


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype="float32")
    if matrix.ndim == 1:
        return matrix / (np.linalg.norm(matrix) + 1e-12)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / (norms + 1e-12)


class DenseIndex:
    """Cosine search over an (n_docs, dim) matrix. Rows are normalized on construction."""

    def __init__(self, embeddings: np.ndarray):
        self.matrix = l2_normalize(embeddings)

    def __len__(self) -> int:
        return int(self.matrix.shape[0])

    def search(self, query_vector: np.ndarray, top_k: int = 10,
               allowed_ids: Optional[Set[int]] = None) -> List[Tuple[int, float]]:
        if self.matrix.size == 0:
            return []
        if allowed_ids is not None and not allowed_ids:
            return []

        scores = self.matrix @ l2_normalize(np.asarray(query_vector, dtype="float32"))

        if allowed_ids is None:
            candidates = np.arange(scores.shape[0])
        else:
            candidates = np.fromiter(sorted(allowed_ids), dtype=np.int64)
            candidates = candidates[candidates < scores.shape[0]]
            if candidates.size == 0:
                return []

        subset = scores[candidates]
        take = min(top_k, subset.shape[0])
        # argpartition then sort only the slice we keep — O(n) instead of a full sort
        top = np.argpartition(-subset, take - 1)[:take] if take < subset.shape[0] \
            else np.arange(subset.shape[0])
        top = top[np.argsort(-subset[top], kind="stable")]
        return [(int(candidates[i]), float(subset[i])) for i in top]
