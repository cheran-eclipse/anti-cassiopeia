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

        contested = [e for e in evidence if e.stance == "contested"]
        if contested:
            reasoning.append(
                f"{len(contested)} piece(s) of evidence are contested (independent sources/extractions "
                "disagree) — excluded from scoring, carried here for the record."
            )

        support = sum(e.trust for e in evidence if e.stance == "supports")
        contradict = sum(e.trust for e in evidence if e.stance == "contradicts")
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
            state = VerdictState.CONFIRMED
        else:
            state = VerdictState.CONTRADICTED
        confidence = min(abs(net) / max(total_weight, 1e-9), 1.0)
        reasoning.append(f"Verdict: {state.value} (confidence {confidence:.2f}).")

        return Verdict(
            claim=claim,
            state=state,
            confidence=confidence,
            evidence=evidence,
            reasoning=reasoning,
        )
