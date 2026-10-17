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
    """Base class every domain (robotics, FPGA/embedded, web/research, ML/data) implements."""

    #: Must match Claim.domain for claims this adapter accepts.
    domain_name: str

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
