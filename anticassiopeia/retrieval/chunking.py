"""
Ingest a document into chunks that each carry an exact, re-checkable
character span back to the source text.

This is the base of the whole retrieval pipeline: every later citation
(BM25 hit, LLM proposal, verified Evidence) traces back to one of these
chunks by id, and every chunk traces back to one exact (start, end) span
in the original document text. Nothing downstream is allowed to point at
"the document" in general — only at a specific chunk, and a specific span
inside it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    chunk_id: str      # stable id, e.g. "{doc_id}#{index}"
    doc_id: str
    text: str
    start: int          # char offset into the ORIGINAL document text
    end: int             # exclusive
    line_start: int      # 1-indexed line number the chunk starts on
    page: int | None = None  # only set when the source document is paginated


def chunk_document(
    doc_id: str,
    text: str,
    *,
    chunk_size: int = 800,
    overlap: int = 150,
) -> list[Chunk]:
    """Splits `text` into overlapping chunks, each carrying its exact
    (start, end) offset and starting line number in the ORIGINAL text.

    Splits on paragraph/line boundaries where possible rather than mid-word,
    by snapping each chunk's end to the nearest preceding newline within the
    target window (falling back to a hard cut only if no newline exists in
    range) — so a quote inside a chunk reads as a human would expect it to,
    not as an arbitrarily truncated character run.
    """
    if chunk_size <= overlap:
        raise ValueError(f"chunk_size ({chunk_size}) must be greater than overlap ({overlap}).")
    if not text:
        return []

    chunks: list[Chunk] = []
    pos = 0
    index = 0
    n = len(text)

    while pos < n:
        target_end = min(pos + chunk_size, n)
        end = target_end
        if target_end < n:
            # snap to the last newline at or before target_end, but not before
            # we'd produce a near-empty chunk
            newline = text.rfind("\n", pos, target_end)
            if newline != -1 and newline > pos + (chunk_size // 4):
                end = newline + 1  # include the newline so offsets stay contiguous

        chunk_text = text[pos:end]
        line_start = text.count("\n", 0, pos) + 1
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}#{index}",
                doc_id=doc_id,
                text=chunk_text,
                start=pos,
                end=end,
                line_start=line_start,
            )
        )
        index += 1

        if end >= n:
            break
        pos = max(end - overlap, pos + 1)  # always make forward progress

    return chunks
