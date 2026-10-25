"""
The one interface every domain plugs into.

A domain adapter's only job is turning a Claim into Evidence, using
whatever source of truth is real for that domain (a datasheet, a register
map, a paper index, a dataset). It never decides the verdict itself —
that judgment stays centralized in the engine, so all four domains are
held to the same evidentiary standard instead of each inventing its own
notion of "confirmed."
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from anticassiopeia.core.verdict import Claim, Evidence


class DomainAdapter(ABC):
    """Base class every domain (substrate, silicon, searchlight, quant) implements."""

    #: Must match Claim.domain for claims this adapter accepts.
    domain_name: str

    #: False until gather_evidence() is wired to a real evidence source.
    #: Set True explicitly in the subclass once it is — never inferred.
    implemented: bool = False

    @abstractmethod
    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        """Return every piece of evidence this domain's sources can produce for `claim`.

        Return an empty list rather than fabricating evidence when the
        domain genuinely has nothing to check against — that's what
        drives the engine toward UNDETERMINED instead of a guess.
        """
        raise NotImplementedError

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        """Name what's missing when evidence is empty or inconclusive.

        Default: generic. Domains should override this with something
        concrete and specific to that domain's sources — "no datasheet
        found for part X" beats "insufficient evidence".
        """
        if not evidence:
            return [f"No evidence found for claim in domain '{self.domain_name}'."]
        return []

    def describe_partial_gaps(self, claim: Claim) -> list[str]:
        """Name sources this adapter EXPECTED to check but could not get a
        usable answer from, for the most recent `gather_evidence()` call.

        FOUND BUG this exists to fix (external review): `describe_gap()`
        above is only ever consulted by the engine when the FINAL evidence
        is empty or below the confidence threshold — so a source that
        returned something (an incomplete, ambiguous, or verification-
        rejected answer, not a clean `None`) silently vanished with no
        trace once at least one OTHER source produced enough evidence to
        render a confident verdict. A caller reading that confident verdict
        had no way to know one of the sources it should have checked never
        actually contributed. The engine now calls this UNCONDITIONALLY
        and appends every returned string to `Verdict.reasoning`,
        regardless of how confident the final verdict is.

        Default: no adapter knows its own expected-source count, so this
        says nothing by default — override only if the adapter actually
        tracks which sources it expected to consult (see `substrate.py`).
        """
        return []
