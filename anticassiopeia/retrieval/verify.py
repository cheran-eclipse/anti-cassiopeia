"""
Independent verification of a proposal — the step that decides whether an
LLM's (or a human's) claimed quote becomes a trusted Evidence object, or a
named rejection. This code never trusts the proposer; it re-checks from
the chunk text itself, every time.

This is deliberately separate from extract.py (the LLM "propose" step) —
the whole point of the pattern (see docs/DESIGN.md and
docs/extracted/constellation-robotics-seed.md §5) is that the code path
that decides whether to trust something is independent of whatever
proposed it. A proposal can come from an LLM, a human, or a test — this
module doesn't know or care which.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from anticassiopeia.core.verdict import Evidence
from anticassiopeia.retrieval.chunking import Chunk

_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class Proposal:
    """What a proposer (LLM or otherwise) claims about one chunk.

    `kind` records whether the proposer is claiming this is a rating/maximum
    ("rated") or a measured/tested result ("tested") — Constellation's own
    pattern treats conflating the two as a distinct failure mode worth
    catching, not just "right value, wrong category."
    """

    chunk_id: str
    quote: str              # the exact text the proposer claims appears in the chunk
    value: float | None = None
    unit: str | None = None
    kind: str | None = None  # "rated" | "tested" | None


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    reason: str              # always populated — why accepted, or why rejected
    evidence: Evidence | None = None  # set only when accepted


def verify_proposal(
    proposal: Proposal,
    chunks_by_id: dict[str, Chunk],
    *,
    source: str,
    stance: str,
    trust: float = 0.8,
) -> VerificationResult:
    """Independently re-checks a Proposal against the ACTUAL chunk text —
    never trusts the proposer's say-so about what the chunk contains.

    Rejections are specific and named (see docs/DESIGN.md's own standard:
    "no datasheet found" beats "insufficient evidence") — never a generic
    reject.
    """
    chunk = chunks_by_id.get(proposal.chunk_id)
    if chunk is None:
        return VerificationResult(accepted=False, reason=f"Proposal cites unknown chunk_id '{proposal.chunk_id}'.")

    if _normalize(proposal.quote) not in _normalize(chunk.text):
        return VerificationResult(
            accepted=False,
            reason=(
                f"Quote not found verbatim (whitespace-normalized) in chunk '{chunk.chunk_id}' "
                f"(lines starting at {chunk.line_start}). Proposer's quote: {proposal.quote!r}."
            ),
        )

    # Locate the quote's actual char offset within the chunk, for a precise locator —
    # re-derived here, not trusted from the proposal.
    norm_chunk = _normalize(chunk.text)
    norm_quote = _normalize(proposal.quote)
    offset_in_norm = norm_chunk.find(norm_quote)
    approx_char_offset = chunk.start + offset_in_norm if offset_in_norm >= 0 else chunk.start

    locator = f"{chunk.doc_id}, chunk {chunk.chunk_id}, ~char {approx_char_offset} (chunk starts line {chunk.line_start})"
    snippet = proposal.quote
    if proposal.value is not None:
        snippet = f"{snippet} (value={proposal.value!r}, unit={proposal.unit!r}, kind={proposal.kind!r})"

    evidence = Evidence(source=source, snippet=snippet, stance=stance, trust=trust, locator=locator)
    return VerificationResult(accepted=True, reason="Quote verified verbatim in the cited chunk.", evidence=evidence)
