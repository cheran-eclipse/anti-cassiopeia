"""
Hybrid retrieval: BM25 (keyword) + vector (semantic) search, fused by
reciprocal rank fusion (RRF) -- ADDITIVE to the existing BM25-only path
(retrieval/bm25.py), never a replacement. Ported from a real, working,
already-evaluated implementation in the sibling project
`eclipse-constellation` (`src/constellation/retrieval/hybrid.py` /
`index.py`), not invented from scratch -- see
`claude/ANTI_CASSIOPEIA_HYBRID_RETRIEVAL_BUILD_PROMPT.md` for the full
build spec this follows.

WHY this closes a real, measured gap, not a hypothetical one: the
competitive-benchmark protocol's round 1
(`stress_test/results/BENCHMARK_ROUND1_REPORT.md`) found 3 conservative
misses and one dangerously-soft conspiracy-claim verdict, ALL traced to
the same root cause -- BM25 keyword search, given the raw claim sentence
as its query, finding zero or weak candidates for claims phrased in
words that don't literally appear in the best source. Vector search is
the one retrieval mechanism that can find a semantically-matching
passage using different words than the query -- BM25 structurally
cannot, no matter how its parameters are tuned.

HOW fusion works (reciprocal rank fusion, RRF_K=60 -- the standard
constant from the original RRF paper, same value Constellation's own
evaluated implementation uses, not re-tuned here):

    score(chunk) = sum over each retrieval method that ranked this chunk of:
        1.0 / (RRF_K + that method's rank for this chunk)

A chunk ranked #1 by BOTH methods scores highest; a chunk found by only
one method still scores (rewarding methods that agree, without requiring
agreement) -- rank-based, not raw-score-based, which is what makes it
safe to combine two different methods' incomparable score scales (BM25's
scores and cosine similarity have no common unit) without ad hoc
normalization.

HONEST DEGRADATION, same discipline Constellation's own HybridRetriever
already established and this module's own tests lock in: if embedding
fails for ANY reason -- no client given, a client that doesn't implement
embed() at all (e.g. existing test fakes, duck-typed), a live API
failure, a malformed response -- vector search is silently skipped for
that call and `HybridSearchResult.methods` records exactly which
method(s) actually ran (`["bm25"]` vs `["bm25", "vector"]`). This NEVER
raises up to the caller and NEVER pretends vector search happened when
it didn't; BM25 alone is always still a complete, correct answer, same
as before this module existed.

HONEST NEW LIMITATION this module itself introduces, stated plainly
(see retrieval/__init__.py's own docstring for where this is surfaced
project-wide): there is still no persistent embedding cache anywhere in
this codebase. substrate.py's BYOE/pooled paths and searchlight.py's
multi-candidate path all re-chunk AND re-embed their source text on
EVERY call, same as they already re-chunk and re-BM25-index on every
call today (see domains/substrate.py's own `_gather_byoe`/
`_gather_byoe_pool` -- there was no chunk/BM25 cache before this module
either). Querying the SAME uploaded document twice re-embeds it twice,
at real added cost and latency -- see this module's own cost/latency
measurements in the hybrid-retrieval build's own report for the actual
numbers. A persistent per-document embedding cache (keyed off
UploadStore's own document_id) would close this, but is a real,
separate architecture change -- not built here, named here so it's a
decision for a future round, not an invisible gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from anticassiopeia.llm.nebius_client import NebiusClientError
from anticassiopeia.retrieval.bm25 import BM25Index, ScoredChunk
from anticassiopeia.retrieval.chunking import Chunk

#: Standard constant from the original RRF paper (Cormack, Clarke & Buettcher,
#: 2009) -- NOT re-tuned for this project. Matches Constellation's own
#: evaluated implementation exactly, so the fusion formula itself is not a
#: new, unvalidated choice.
RRF_K = 60


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """L2-normalizes each row so a plain dot product becomes cosine
    similarity -- ported directly from Constellation's own
    retrieval/index.py (same zero-row guard: a zero vector's norm is
    clamped to 1.0 rather than dividing by zero, which would otherwise
    turn one malformed embedding into a crash for every query)."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class VectorIndex:
    """Local cosine-similarity search over a fixed set of embedded chunks.
    Pure numpy, no external vector-DB dependency -- same scope Constellation's
    own VectorIndex has (this project's corpora are small enough that an
    in-memory, no-approximation search is the right tool, not a limitation
    worth building around yet)."""

    def __init__(self, ids: list[str], vectors: list[list[float]]) -> None:
        if len(vectors) != len(ids):
            raise ValueError(f"{len(vectors)} vectors for {len(ids)} ids -- must match 1:1")
        self.ids = list(ids)
        self._matrix = _normalize_rows(np.asarray(vectors, dtype=np.float32))

    @property
    def dim(self) -> int:
        return int(self._matrix.shape[1])

    def search(self, query_vector: list[float], top_k: int) -> list[tuple[str, float]]:
        """Top-k (chunk_id, cosine_similarity) pairs, best first."""
        q = _normalize_rows(np.asarray([query_vector], dtype=np.float32))
        if q.shape[1] != self.dim:
            raise ValueError(f"query vector has dimension {q.shape[1]}, index has {self.dim}")
        sims = (self._matrix @ q.T).ravel()
        order = np.argsort(-sims, kind="stable")[:top_k]
        return [(self.ids[i], float(sims[i])) for i in order]


def rrf_fuse(*rank_maps: dict[str, int], k: int = RRF_K) -> dict[str, float]:
    """Pure function, no I/O -- each rank_map is {chunk_id: rank} (1-indexed,
    best=1) from one retrieval method. A chunk_id absent from a given
    rank_map simply didn't contribute a term from that method, exactly as
    the RRF formula intends (not an error, not a zero-fill)."""
    fused: dict[str, float] = {}
    for ranks in rank_maps:
        for chunk_id, rank in ranks.items():
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return fused


@dataclass(frozen=True)
class HybridSearchResult:
    scored: list[ScoredChunk]
    #: Which retrieval method(s) actually ran and contributed to this
    #: result -- "bm25" is always present; "vector" is present only when
    #: embedding genuinely succeeded for both the corpus AND this query.
    #: Read this, don't assume -- see module docstring's "HONEST
    #: DEGRADATION" section.
    methods: list[str] = field(default_factory=lambda: ["bm25"])
    #: Set only when vector search was attempted and failed (including
    #: "client has no embed() at all") -- named, never silently dropped.
    vector_error: str | None = None


class HybridIndex:
    """Build once over a fixed set of chunks (BM25 always, embeddings
    best-effort), then `search()` repeatedly -- same shape as
    retrieval/bm25.py's own BM25Index, extended with an optional vector
    leg. A caller that never calls `embed()` gets byte-for-byte BM25-only
    behavior, same ranking retrieval/bm25.py's BM25Index already
    produces -- this class is a strict superset, not a parallel path."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self._chunks_by_id = {c.chunk_id: c for c in chunks}
        self._bm25 = BM25Index(chunks)
        self._vectors: VectorIndex | None = None
        #: Named reason embedding is unavailable for this index, if any --
        #: distinct from "embed() was never called at all" (also None).
        self.embed_error: str | None = None

    async def embed(self, client) -> None:
        """Best-effort, call-and-forget: embeds every chunk's text via
        `client.embed()`. On ANY failure -- including `client` being
        `None`, or not implementing `embed()` at all (existing offline
        test fakes in this repo are plain duck-typed objects with only
        `complete()`) -- leaves `self._vectors` as `None` and records why
        in `self.embed_error`. `search()` below simply skips the vector
        leg whenever `self._vectors` is `None`, so callers never need
        their own try/except around this -- the degradation IS the
        contract, not an exceptional path."""
        if not self._chunks or client is None:
            if client is None:
                self.embed_error = "no client provided -- embedding was never attempted"
            return
        try:
            vectors = await client.embed([c.text for c in self._chunks])
            self._vectors = VectorIndex([c.chunk_id for c in self._chunks], vectors)
        except (NebiusClientError, AttributeError, TypeError) as exc:
            # AttributeError: client has no embed() method at all (a
            # duck-typed test fake, or any future client implementation
            # that only supports complete()). TypeError: a client whose
            # embed() exists but isn't awaitable/callable the way this
            # expects. Both are real-but-expected shapes to degrade from,
            # not programming errors to let propagate.
            self.embed_error = f"{type(exc).__name__}: {exc}"

    async def search(
        self, query_text: str, *, top_k: int, client, pool: int | None = None, mode: str = "hybrid",
    ) -> HybridSearchResult:
        """`client` is used ONLY to embed the query (chunk embedding
        already happened, or didn't, in `embed()` above) -- passed again
        here because the query is only known at search time. Same
        best-effort degradation as `embed()`: a query-embedding failure
        (including no vector index to search at all) falls back to
        BM25-only for this one call without raising.

        `mode` -- same three values and same purpose as Constellation's
        own HybridRetriever.search(): "hybrid" (default, production
        behavior) runs both legs and fuses; "bm25" and "vector" exist
        ONLY for evaluation (retrieval/evaluate.py's own harness needs to
        measure each method in isolation to report honest per-method
        numbers, not just the fused result) and are never used by any
        production call site in this repo."""
        if mode not in ("hybrid", "bm25", "vector"):
            raise ValueError(f"mode must be 'hybrid', 'bm25', or 'vector', got {mode!r}")
        pool_size = pool or max(top_k * 3, 10)

        bm25_rank: dict[str, int] = {}
        bm25_hits: list[ScoredChunk] = []
        methods: list[str] = []
        if mode in ("hybrid", "bm25"):
            bm25_hits = self._bm25.search(query_text, top_k=pool_size)
            bm25_rank = {hit.chunk.chunk_id: rank for rank, hit in enumerate(bm25_hits, start=1)}
            methods.append("bm25")

        vec_rank: dict[str, int] = {}
        vector_error: str | None = None
        if mode in ("hybrid", "vector"):
            if self._vectors is not None and client is not None:
                try:
                    query_vector = (await client.embed([query_text]))[0]
                    hits = self._vectors.search(query_vector, pool_size)
                    vec_rank = {chunk_id: rank for rank, (chunk_id, _sim) in enumerate(hits, start=1)}
                    methods.append("vector")
                except (NebiusClientError, AttributeError, TypeError, IndexError, ValueError) as exc:
                    vector_error = f"{type(exc).__name__}: {exc}"
            elif self._vectors is None:
                vector_error = self.embed_error or "no vector index built for this corpus"

        if not vec_rank:
            # Pure BM25 order, UNCHANGED from BM25Index.search()'s own
            # output -- no RRF math applied when there's only one method,
            # so a vector-less call is byte-for-byte what it always was.
            # (mode="vector" with no usable vectors correctly returns empty.)
            scored = bm25_hits[:top_k]
            return HybridSearchResult(scored=scored, methods=methods or ["bm25"], vector_error=vector_error)

        if not bm25_rank:
            # mode="vector": rank purely by cosine similarity, no RRF needed
            # (there is nothing to fuse against).
            order = sorted(vec_rank, key=lambda cid: vec_rank[cid])[:top_k]
            scored = [ScoredChunk(chunk=self._chunks_by_id[cid], score=1.0 / vec_rank[cid]) for cid in order]
            return HybridSearchResult(scored=scored, methods=methods, vector_error=vector_error)

        fused = rrf_fuse(bm25_rank, vec_rank)
        order = sorted(fused, key=lambda cid: (-fused[cid], bm25_rank.get(cid, pool_size + 1)))[:top_k]
        scored = [ScoredChunk(chunk=self._chunks_by_id[cid], score=fused[cid]) for cid in order]
        return HybridSearchResult(scored=scored, methods=methods, vector_error=vector_error)
