"""
Tests for retrieval/hybrid.py -- RRF fusion (pure function, no I/O),
VectorIndex (pure numpy cosine search), and HybridIndex's honest
degradation to BM25-only on any embedding failure, at both index time
(embed()) and query time (search()). All OFFLINE: a fake embedding
client, no live Nebius call needed anywhere in this file.
"""

import pytest

from anticassiopeia.llm.nebius_client import NebiusClientError
from anticassiopeia.retrieval.chunking import chunk_document
from anticassiopeia.retrieval.hybrid import RRF_K, HybridIndex, VectorIndex, rrf_fuse


# --- rrf_fuse(): pure function ---


def test_rrf_fuse_single_method_matches_the_formula_exactly():
    fused = rrf_fuse({"a": 1, "b": 2})
    assert fused["a"] == pytest.approx(1.0 / (RRF_K + 1))
    assert fused["b"] == pytest.approx(1.0 / (RRF_K + 2))


def test_rrf_fuse_rewards_agreement_between_methods():
    """A chunk ranked #1 by BOTH methods must score higher than one ranked
    #1 by only one method -- the whole point of fusing two signals."""
    both_methods = rrf_fuse({"a": 1}, {"a": 1})
    one_method = rrf_fuse({"b": 1}, {})
    assert both_methods["a"] > one_method["b"]


def test_rrf_fuse_a_chunk_found_by_only_one_method_still_scores():
    fused = rrf_fuse({"a": 1, "b": 2}, {"c": 1})
    assert set(fused) == {"a", "b", "c"}
    assert all(v > 0 for v in fused.values())


def test_rrf_fuse_with_no_rank_maps_returns_empty():
    assert rrf_fuse() == {}


# --- VectorIndex: pure numpy cosine search ---


def test_vector_index_ranks_the_exact_match_first():
    index = VectorIndex(["a", "b", "c"], [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]])
    results = index.search([1.0, 0.0], top_k=3)
    assert results[0][0] == "a"
    assert results[0][1] == pytest.approx(1.0)


def test_vector_index_rejects_a_dimension_mismatch():
    index = VectorIndex(["a"], [[1.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="dimension"):
        index.search([1.0, 0.0], top_k=1)


def test_vector_index_rejects_mismatched_ids_and_vectors_count():
    with pytest.raises(ValueError, match="must match"):
        VectorIndex(["a", "b"], [[1.0, 0.0]])


def test_vector_index_handles_a_zero_vector_without_crashing():
    """The zero-row norm guard, ported from Constellation's own
    index.py -- a malformed all-zero embedding must not raise a
    division-by-zero, just rank last/neutrally."""
    index = VectorIndex(["a", "b"], [[0.0, 0.0], [1.0, 0.0]])
    results = index.search([1.0, 0.0], top_k=2)
    assert len(results) == 2


# --- HybridIndex: honest degradation ---

_DOC_TEXT = (
    "The Widget Mk4 enclosure carries an IP68 rating.\n\n"
    "The Gadget Pro draws a maximum of 9 watts under full load.\n"
)


class _NoEmbedClient:
    """A duck-typed client with ONLY complete() -- same shape as every
    existing offline test fake elsewhere in this repo (e.g.
    test_substrate_byoe.py's _FakeClient). embed() must degrade to
    BM25-only against this, not crash -- this is the single most
    important regression this module's tests guard against, since every
    existing test file's fakes look exactly like this."""

    async def complete(self, prompt, *, system=None, temperature=0.0):
        return "unused"


class _WorkingEmbedClient:
    def __init__(self, dim: int = 4):
        self._dim = dim
        self.embed_calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        # Deterministic, distinct-ish vectors per text (hash-based), not
        # real semantics -- these tests only check the PLUMBING (that
        # embeddings are requested, fused, and ranked), not retrieval
        # quality, which needs a real embedder (see the live eval report).
        return [[float((hash(t) >> (i * 4)) % 7) for i in range(self._dim)] for t in texts]


class _FailingEmbedClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NebiusClientError("Nebius Token Factory returned 500: simulated failure")


def _real_chunks():
    return chunk_document("doc", _DOC_TEXT, chunk_size=80, overlap=10)


async def test_no_embed_call_at_all_is_pure_bm25_and_methods_says_so():
    index = HybridIndex(_real_chunks())
    result = await index.search("Widget Mk4 IP68", top_k=3, client=None)
    assert result.methods == ["bm25"]
    assert result.vector_error is not None
    assert len(result.scored) > 0  # BM25 still works completely on its own


async def test_a_client_with_no_embed_method_degrades_to_bm25_only_at_index_time():
    index = HybridIndex(_real_chunks())
    await index.embed(_NoEmbedClient())
    assert index.embed_error is not None
    assert "AttributeError" in index.embed_error

    result = await index.search("Widget Mk4 IP68", top_k=3, client=_NoEmbedClient())
    assert result.methods == ["bm25"]


async def test_embedding_failure_at_index_time_is_named_and_degrades_cleanly():
    index = HybridIndex(_real_chunks())
    await index.embed(_FailingEmbedClient())
    assert "NebiusClientError" in index.embed_error
    assert "simulated failure" in index.embed_error

    result = await index.search("Widget Mk4 IP68", top_k=3, client=_FailingEmbedClient())
    assert result.methods == ["bm25"]
    assert result.vector_error == index.embed_error


async def test_successful_embedding_actually_runs_the_vector_leg():
    client = _WorkingEmbedClient()
    index = HybridIndex(_real_chunks())
    await index.embed(client)
    assert index.embed_error is None
    assert len(client.embed_calls) == 1  # one batch call for all chunks

    result = await index.search("Widget Mk4 IP68 rating", top_k=3, client=client)
    assert result.methods == ["bm25", "vector"]
    assert result.vector_error is None
    assert len(result.scored) > 0


async def test_query_time_embedding_failure_degrades_even_when_index_time_succeeded():
    """A corpus that embedded fine at index time can still fail at QUERY
    time (a transient live-call failure) -- search() must degrade
    independently of embed()'s own earlier success, per the module's own
    'both index time and query time' degradation contract."""
    index = HybridIndex(_real_chunks())
    await index.embed(_WorkingEmbedClient())
    assert index.embed_error is None  # index-time embedding DID succeed

    result = await index.search("Widget Mk4 IP68", top_k=3, client=_FailingEmbedClient())
    assert result.methods == ["bm25"]
    assert result.vector_error is not None


async def test_hybrid_result_with_no_bm25_hits_and_no_vector_is_empty_not_a_crash():
    index = HybridIndex(_real_chunks())
    result = await index.search("xyzzy quux frobnicate completely unrelated gibberish", top_k=3, client=None)
    assert result.scored == []
    assert result.methods == ["bm25"]


# --- mode= : evaluation-only isolation of each method ---


async def test_mode_bm25_never_calls_embed_even_with_a_working_client():
    client = _WorkingEmbedClient()
    index = HybridIndex(_real_chunks())
    await index.embed(client)
    client.embed_calls.clear()  # reset after the index-time embed above

    result = await index.search("Widget Mk4 IP68", top_k=3, client=client, mode="bm25")
    assert result.methods == ["bm25"]
    assert client.embed_calls == []  # proves the vector leg genuinely did not run


async def test_mode_vector_never_consults_bm25_ranking():
    client = _WorkingEmbedClient()
    index = HybridIndex(_real_chunks())
    await index.embed(client)

    result = await index.search("xyzzy quux frobnicate -- zero BM25 overlap by design", top_k=3, client=client, mode="vector")
    # BM25 would find nothing for this query; mode="vector" must still
    # return ranked results purely from embeddings.
    assert result.methods == ["vector"]
    assert len(result.scored) > 0


async def test_mode_vector_with_no_embeddings_available_returns_empty_not_bm25_fallback():
    """mode="vector" is an evaluation isolation mode -- it must NOT
    silently fall back to BM25 when embeddings aren't available, or the
    eval harness using it to measure vector-only performance would
    actually be measuring BM25 and mislabeling it."""
    index = HybridIndex(_real_chunks())  # embed() never called
    result = await index.search("Widget Mk4 IP68", top_k=3, client=None, mode="vector")
    assert result.scored == []


def test_search_rejects_an_invalid_mode():
    import asyncio

    index = HybridIndex(_real_chunks())

    async def _run():
        await index.search("x", top_k=1, client=None, mode="not-a-real-mode")

    with pytest.raises(ValueError, match="mode must be"):
        asyncio.run(_run())
