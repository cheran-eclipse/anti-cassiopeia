"""
A real, from-scratch Okapi BM25 index. No external dependency — this is
the keyword-search half of "hybrid search" (see module docstring in
retrieval/__init__.py for why vector search is NOT included yet).

Standard Okapi BM25 scoring:

    score(D, Q) = sum over query terms t of:
        IDF(t) * ( f(t, D) * (k1 + 1) ) / ( f(t, D) + k1 * (1 - b + b * |D| / avgdl) )

with IDF(t) = ln( (N - n(t) + 0.5) / (n(t) + 0.5) + 1 )  (the +1 keeps IDF
non-negative for terms that appear in every document, the standard
BM25+-style fix for the classic formula's negative-IDF edge case).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from anticassiopeia.retrieval.chunking import Chunk

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")  # keeps "ms5837-30ba", "500m", "0.245" intact


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


class BM25Index:
    """Build once over a fixed set of chunks, then `search()` repeatedly."""

    def __init__(self, chunks: list[Chunk], *, k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b

        self._doc_tokens: list[list[str]] = [tokenize(c.text) for c in chunks]
        self._doc_len = [len(toks) for toks in self._doc_tokens]
        self._avgdl = (sum(self._doc_len) / len(self._doc_len)) if self._doc_len else 0.0

        self._term_freqs: list[Counter[str]] = [Counter(toks) for toks in self._doc_tokens]

        df: Counter[str] = Counter()
        for toks in self._doc_tokens:
            df.update(set(toks))
        self._n_docs = len(chunks)
        self._idf: dict[str, float] = {
            term: math.log((self._n_docs - freq + 0.5) / (freq + 0.5) + 1) for term, freq in df.items()
        }

    def search(self, query: str, top_k: int = 5) -> list[ScoredChunk]:
        if not self.chunks:
            return []
        q_terms = tokenize(query)
        if not q_terms:
            return []

        scores = [0.0] * self._n_docs
        for term in q_terms:
            idf = self._idf.get(term)
            if idf is None:
                continue  # term never appears in the corpus — contributes nothing, not an error
            for i in range(self._n_docs):
                f = self._term_freqs[i].get(term, 0)
                if f == 0:
                    continue
                dl = self._doc_len[i]
                denom = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl) if self._avgdl else f
                scores[i] += idf * (f * (self.k1 + 1)) / denom

        ranked = sorted(
            (ScoredChunk(chunk=self.chunks[i], score=scores[i]) for i in range(self._n_docs) if scores[i] > 0),
            key=lambda sc: sc.score,
            reverse=True,
        )
        return ranked[:top_k]
