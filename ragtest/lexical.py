"""
BM25 keyword search — the lexical half of the hybrid retriever.

Why BM25 and not plain term overlap: the corpus is one company's annual reports, so the
company name and stock words ("phát triển bền vững", "công ty") appear in nearly every
sentence. Term overlap ranks by how many query words a document repeats, which those
ubiquitous words win outright; BM25's idf term pushes them to almost zero weight and lets
the rare, discriminative word ("bao bì tự phân huỷ", "nước thải") decide the ranking.

Tokenization is Unicode-aware and NFC-normalizing: Vietnamese diacritics must survive, and
some of these PDFs carry decomposed or mangled forms ("TRƢỜNG"). An ASCII-only tokenizer
would shred every accented word and quietly turn this channel into noise.

Offline and free — no model, no network.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

K1 = 1.5
B = 0.75

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return _TOKEN_RE.findall(unicodedata.normalize("NFC", text).lower())


class BM25Index:
    """Okapi BM25 over the corpus rows' `text` field."""

    def __init__(self, documents: Sequence[Dict[str, Any]], text_key: str = "text"):
        self.documents = list(documents)
        self.doc_tokens = [tokenize(d.get(text_key)) for d in self.documents]
        self.doc_len = [len(t) for t in self.doc_tokens]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0

        self.term_freq: List[Counter] = [Counter(t) for t in self.doc_tokens]
        self.postings: Dict[str, List[int]] = {}
        for index, counts in enumerate(self.term_freq):
            for term in counts:
                self.postings.setdefault(term, []).append(index)

        total = len(self.documents)
        self.idf: Dict[str, float] = {}
        for term, posting in self.postings.items():
            df = len(posting)
            self.idf[term] = math.log(1.0 + (total - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 10,
               allowed_ids: Optional[Set[int]] = None) -> List[Tuple[int, float]]:
        """Score only documents that share a term with the query; never return a zero hit."""
        if allowed_ids is not None and not allowed_ids:
            return []

        scores: Dict[int, float] = {}
        for term in tokenize(query):
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = self.idf[term]
            for index in posting:
                if allowed_ids is not None and index not in allowed_ids:
                    continue
                freq = self.term_freq[index][term]
                norm = K1 * (1 - B + B * (self.doc_len[index] / self.avg_len
                                          if self.avg_len else 1.0))
                scores[index] = scores.get(index, 0.0) + idf * (freq * (K1 + 1)) / (freq + norm)

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:top_k]
