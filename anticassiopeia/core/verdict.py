"""
Core verdict types.

Anti-Cassiopeia never collapses "I don't know" into a confident-sounding
guess. Every check resolves to exactly one of three states — never a
smoothed-over probability dressed up as certainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class VerdictState(str, Enum):
    """The only three outcomes a check is allowed to return."""

    CONFIRMED = "confirmed"        # evidence clearly supports the claim
    CONTRADICTED = "contradicted"  # evidence clearly opposes the claim
    UNDETERMINED = "undetermined"  # evidence is missing, weak, or conflicting


@dataclass(frozen=True)
class Evidence:
    """One atomic piece of evidence gathered by a domain adapter.

    `stance` says what this piece of evidence does to the claim, not what
    it's "about" — a domain adapter should not emit evidence it hasn't
    actually weighed.
    """

    source: str                 # where this came from (URL, file path, datasheet id, paper DOI, ...)
    snippet: str                # the specific passage/value/reading that matters
    stance: str                 # "supports" | "contradicts" | "neutral"
    trust: float                # 0.0-1.0: how much this source is worth trusting, domain-adapter-assigned
    locator: str | None = None  # page/line/pin/register/section — precise enough to re-check by hand


@dataclass(frozen=True)
class Claim:
    """The atomic, checkable statement being verified.

    Keep claims narrow. "This BLDC motor survives 500m depth" is checkable.
    "This robot design is good" is not — that's a judgment, not a claim,
    and the engine will not pretend otherwise.
    """

    text: str
    domain: str                      # must match a registered DomainAdapter.domain_name
    context: dict = field(default_factory=dict)  # domain-specific extra parameters


@dataclass(frozen=True)
class Verdict:
    """The engine's complete, auditable answer for one claim."""

    claim: Claim
    state: VerdictState
    confidence: float | None         # None when state is UNDETERMINED for lack of evidence
    evidence: list[Evidence]
    reasoning: list[str]             # human-readable trace of how the verdict was reached, in order
    missing: list[str] = field(default_factory=list)  # named gaps — what would resolve an UNDETERMINED
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "claim": {"text": self.claim.text, "domain": self.claim.domain, "context": self.claim.context},
            "state": self.state.value,
            "confidence": self.confidence,
            "evidence": [e.__dict__ for e in self.evidence],
            "reasoning": self.reasoning,
            "missing": self.missing,
            "checked_at": self.checked_at.isoformat(),
        }
