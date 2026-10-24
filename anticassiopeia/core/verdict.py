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
    stance: str                 # "supports" | "contradicts" | "neutral" | "contested"
    trust: float                # 0.0-1.0: how much this source is worth trusting, domain-adapter-assigned
    locator: str | None = None  # page/line/pin/register/section — precise enough to re-check by hand
    # Item 19 (external review, time-decay): when THIS evidence was itself
    # dated as of (e.g. a Vivado report's own "| Date : ..." line) — NOT
    # when it was fetched/computed just now. None (the default) means no
    # real date is known for this specific piece, which is the honest
    # state for most evidence today (a freshly re-computed statistic, a
    # live-fetched web page with no reliably extractable publish date) —
    # engine.py's decay only ever fires when this is actually set by the
    # domain adapter from real document content, never guessed or backfilled.
    timestamp: datetime | None = None

    # "contested": two independent sources/extractions disagree on this specific fact
    # (not just differ in magnitude — disagree on the fact itself). The engine counts
    # this toward neither support nor contradiction, but surfaces it in reasoning —
    # see docs/DESIGN.md §1 and the retrieval-pattern note in
    # docs/extracted/constellation-robotics-seed.md §5 ("disagreement is a signal,
    # not noise"). Two sources that both contradict a claim, just by different
    # margins (e.g. two depth ratings that both fail a 500m test), are NOT contested
    # — they agree on stance, so they stay "contradicts" with their disagreement on
    # magnitude carried in each one's own `snippet`.


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
