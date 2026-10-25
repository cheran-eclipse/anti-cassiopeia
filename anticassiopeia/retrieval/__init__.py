"""
Domain-agnostic retrieval pipeline: ingest → chunk → retrieve → propose → verify.

This is shared infrastructure usable by any domain adapter whose evidence
lives in real documents (robotics datasheets, FPGA timing reports, fetched
web pages) — the same pipeline shape Constellation's own working
demo_slice1.py used (see docs/extracted/constellation-robotics-seed.md §5),
reimplemented here as reusable infrastructure rather than copied code.

    chunk_document()  →  HybridIndex.search()  →  propose()  →  verify_proposal()
    (chunking.py)        (bm25.py + hybrid.py)     (extract.py)   (verify.py)

HYBRID SEARCH (BM25 + vector, fused by reciprocal rank fusion) IS NOW
IMPLEMENTED — see retrieval/hybrid.py's own module docstring for the full
build rationale (closing a real, measured gap found live by the
competitive-benchmark protocol's round 1) and its honest degradation
contract (vector search silently drops to BM25-only on ANY embedding
failure, recorded in `HybridSearchResult.methods`, never hidden). This is
ADDITIVE: retrieval/bm25.py's own `BM25Index` is unchanged and still used
directly wherever hybrid search isn't wired in (not every call site has
been migrated — see each domain adapter's own docstring for which paths
actually use `HybridIndex` vs. plain `BM25Index`).

HONEST NEW LIMITATION, stated plainly rather than assumed away by "we
added embeddings": there is still no persistent embedding (or chunk, or
BM25 index) cache anywhere in this codebase. Every call that uses hybrid
search re-chunks AND re-embeds its source text from scratch, at real
added Nebius cost and latency per call — see
`claude/ANTI_CASSIOPEIA_HYBRID_RETRIEVAL_BUILD_PROMPT.md`'s own build
report for the measured numbers. Adding embeddings closes a real
retrieval-recall gap; it does not make retrieval free, instant, or
cached — those are separate, still-open limitations.

Status: chunking.py, bm25.py, and hybrid.py are real, offline-testable
(hybrid.py's RRF fusion and degradation logic are pure-function/mockable;
the live embedding call itself needs a real NEBIUS_API_KEY, same as
extract.py's propose() always has). verify.py is real, offline, tested.
extract.py is real code but requires a live NEBIUS_API_KEY to actually
run. See each module's own docstring for specifics.
"""

from anticassiopeia.retrieval.bm25 import BM25Index, ScoredChunk, tokenize
from anticassiopeia.retrieval.chunking import Chunk, chunk_document
from anticassiopeia.retrieval.document_ingest import DocumentIngestError, extract_text
from anticassiopeia.retrieval.hybrid import HybridIndex, HybridSearchResult, VectorIndex, rrf_fuse
from anticassiopeia.retrieval.stance import judge_stance
from anticassiopeia.retrieval.verify import Proposal, VerificationResult, verify_proposal

__all__ = [
    "chunk_document",
    "Chunk",
    "BM25Index",
    "ScoredChunk",
    "tokenize",
    "HybridIndex",
    "HybridSearchResult",
    "VectorIndex",
    "rrf_fuse",
    "Proposal",
    "VerificationResult",
    "verify_proposal",
    "extract_text",
    "DocumentIngestError",
    "judge_stance",
]
