"""
The domain-agnostic verification engine.

This is the one piece of logic every domain shares. It does not know
anything about datasheets, FPGAs, papers, or datasets — it only knows how
to turn a pile of Evidence into one of three verdict states, honestly.

Scoring is deliberately simple right now (trust-weighted sum of
supporting vs. contradicting evidence against fixed thresholds). It is a
bone, not a finished spine: swap this for something sharper once real
evidence is flowing from real domain adapters, not before.
"""

from __future__ import annotations

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence, Verdict, VerdictState

#: Minimum net (support - contradiction) trust-weight to call something CONFIRMED / CONTRADICTED.
#: Below this on both sides, the claim is UNDETERMINED rather than guessed at.
DECISION_THRESHOLD = 0.5

#: Minimum total trust-weighted evidence before the engine will render any
#: verdict other than UNDETERMINED. Thin evidence stays UNDETERMINED even
#: if it all points one way.
MIN_EVIDENCE_WEIGHT = 0.3

#: FOUND BUG (external review): `confidence = |net| / total_weight` reaches
#: a full 1.00 off a SINGLE piece of evidence, regardless of that source's
#: own `trust` value (e.g. one trust=0.85 supporting piece and nothing else
#: gives support=0.85, total=0.85, confidence=0.85/0.85=1.00 -- MORE
#: confident than the source's own stated trust). Uncalibrated in general
#: (no held-out fit backs this formula — see docs/DESIGN.md §3), but this
#: specific failure is fixable without a calibration study: corroboration
#: from more than one independent piece of evidence is real signal a lone
#: source can't provide, so confidence from exactly one contributing piece
#: is capped below full certainty. Not applied when 2+ pieces contribute
#: (that's genuine corroboration, left to the existing ratio).
SINGLE_SOURCE_CONFIDENCE_CAP = 0.9


def _redundancy_collapsed_weight(evidence: list[Evidence], stance: str) -> float:
    """Trust-weighted sum for one stance, with same-source redundancy collapsed first.

    FOUND BUG (external review, docs/DESIGN.md §3's "no handling of
    evidence redundancy" caveat): summing `trust` over every piece of
    evidence let two near-identical pieces from the SAME source count as
    two independent confirmations (e.g. two chunks of the same datasheet,
    or the same web page fetched twice, both landing as "supports"). Fixed
    by taking the single highest-trust piece PER SOURCE before summing
    across distinct sources — repeating the same source adds no extra
    weight, but two genuinely different sources still corroborate
    normally. Basic, not a full implementation: it only collapses exact
    `source` string matches, not near-duplicate content from differently-
    named sources (research_web.py's own Jaccard-similarity filter still
    handles that narrower case on top of this one).

    Time-decay (DESIGN.md's other listed gap) is NOT implemented here:
    `Evidence` carries no timestamp field today, and no current adapter
    attaches one to the evidence it returns, so a decay formula would
    have no real data to decay by — stated plainly as still open rather
    than faked with a formula that can't actually fire.
    """
    best_by_source: dict[str, float] = {}
    for e in evidence:
        if e.stance != stance:
            continue
        best_by_source[e.source] = max(best_by_source.get(e.source, 0.0), e.trust)
    return sum(best_by_source.values())


class UnknownDomainError(Exception):
    """Raised when a Claim names a domain with no registered adapter."""


class VerificationEngine:
    """Routes a Claim to its domain adapter, then renders a Verdict from the evidence."""

    def __init__(self, domains: dict[str, DomainAdapter]):
        self._domains = domains

    def register(self, adapter: DomainAdapter) -> None:
        self._domains[adapter.domain_name] = adapter

    async def verify(self, claim: Claim) -> Verdict:
        adapter = self._domains.get(claim.domain)
        if adapter is None:
            raise UnknownDomainError(
                f"No domain adapter registered for '{claim.domain}'. "
                f"Registered domains: {sorted(self._domains)}"
            )

        evidence = await adapter.gather_evidence(claim)
        return self._score(claim, adapter, evidence)

    def _score(self, claim: Claim, adapter: DomainAdapter, evidence: list[Evidence]) -> Verdict:
        reasoning: list[str] = [f"Gathered {len(evidence)} piece(s) of evidence from domain '{claim.domain}'."]

        # Surfaced UNCONDITIONALLY, before any confidence branching below —
        # see DomainAdapter.describe_partial_gaps' docstring for the bug
        # this closes (a source that returned an unusable, not-None,
        # answer silently vanishing once another source alone was enough
        # for a confident verdict).
        partial_gaps = adapter.describe_partial_gaps(claim)
        for gap in partial_gaps:
            reasoning.append(f"Partial gap: {gap}")

        contested = [e for e in evidence if e.stance == "contested"]
        if contested:
            reasoning.append(
                f"{len(contested)} piece(s) of evidence are contested (independent sources/extractions "
                "disagree) — excluded from scoring, carried here for the record."
            )

        support = _redundancy_collapsed_weight(evidence, "supports")
        contradict = _redundancy_collapsed_weight(evidence, "contradicts")
        reasoning.append(f"Support weight: {support:.2f}, contradiction weight: {contradict:.2f}.")

        total_weight = support + contradict
        if total_weight < MIN_EVIDENCE_WEIGHT:
            missing = adapter.describe_gap(claim, evidence)
            reasoning.append("Total evidence weight below minimum — refusing to render a confident verdict.")
            if contested and not missing:
                missing = [
                    f"{len(contested)} piece(s) of evidence exist but are contested (sources disagree) — "
                    "resolving the disagreement would unblock a verdict."
                ]
            return Verdict(
                claim=claim,
                state=VerdictState.UNDETERMINED,
                confidence=None,
                evidence=evidence,
                reasoning=reasoning,
                missing=missing or ["Insufficient evidence weight to decide."],
            )

        net = support - contradict
        if abs(net) < DECISION_THRESHOLD:
            reasoning.append("Support and contradiction are too close to call.")
            return Verdict(
                claim=claim,
                state=VerdictState.UNDETERMINED,
                confidence=None,
                evidence=evidence,
                reasoning=reasoning,
                missing=["Evidence conflicts or is too evenly weighted to resolve."],
            )

        if net > 0:
            state, winning_stance = VerdictState.CONFIRMED, "supports"
        else:
            state, winning_stance = VerdictState.CONTRADICTED, "contradicts"
        confidence = min(abs(net) / max(total_weight, 1e-9), 1.0)
        n_sources = len({e.source for e in evidence if e.stance == winning_stance})
        if n_sources <= 1 and confidence > SINGLE_SOURCE_CONFIDENCE_CAP:
            confidence = SINGLE_SOURCE_CONFIDENCE_CAP
            reasoning.append(
                f"Confidence capped at {SINGLE_SOURCE_CONFIDENCE_CAP:.2f}: only one source "
                "contributed to this verdict, and a lone source cannot alone justify full certainty."
            )
        reasoning.append(f"Verdict: {state.value} (confidence {confidence:.2f}).")

        return Verdict(
            claim=claim,
            state=state,
            confidence=confidence,
            evidence=evidence,
            reasoning=reasoning,
        )
