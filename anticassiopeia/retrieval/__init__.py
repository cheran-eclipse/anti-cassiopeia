"""
Domain-agnostic retrieval pipeline: ingest → chunk → retrieve → propose → verify.

This is shared infrastructure usable by any domain adapter whose evidence
lives in real documents (robotics datasheets, FPGA timing reports, fetched
web pages) — the same pipeline shape Constellation's own working
demo_slice1.py used (see docs/extracted/constellation-robotics-seed.md §5),
reimplemented here as reusable infrastructure rather than copied code.

    chunk_document()  →  BM25Index.search()  →  propose()  →  verify_proposal()
    (chunking.py)        (bm25.py)              (extract.py)   (verify.py)

Honest scope note on "hybrid search": only BM25 (keyword) search is
implemented. Vector/embedding search is NOT — it needs an embedding model,
which nothing in this repo currently provides or calls. Constellation's own
documented pattern explicitly allows this: "if embeddings aren't available,
it falls back to BM25-only and records that fact in the result rather than
silently pretending it used both." This package does the same — it's
BM25-only, stated plainly, not described as "hybrid" anywhere in this repo.

Status: chunking.py and bm25.py are real, offline, tested. verify.py is
real, offline, tested. extract.py is real code but requires a live
NEBIUS_API_KEY to actually run — not exercised in this build session. See
each module's own docstring for specifics.
"""

from anticassiopeia.retrieval.bm25 import BM25Index, ScoredChunk, tokenize
from anticassiopeia.retrieval.chunking import Chunk, chunk_document
from anticassiopeia.retrieval.document_ingest import DocumentIngestError, extract_text
from anticassiopeia.retrieval.verify import Proposal, VerificationResult, verify_proposal

__all__ = [
    "chunk_document",
    "Chunk",
    "BM25Index",
    "ScoredChunk",
    "tokenize",
    "Proposal",
    "VerificationResult",
    "verify_proposal",
    "extract_text",
    "DocumentIngestError",
]
