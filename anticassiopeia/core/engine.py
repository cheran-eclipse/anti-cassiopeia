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

from datetime import datetime

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence, Verdict, VerdictState

#: Minimum net (support - contradiction) trust-weight to call something CONFIRMED / CONTRADICTED.
#: Below this on both sides, the claim is UNDETERMINED rather than guessed at.
DECISION_THRESHOLD = 0.5

# REMOVED (external review): there used to be a second constant here,
# MIN_EVIDENCE_WEIGHT = 0.3, gating total_weight (support + contradict)
# before the net-weight check below ever ran. Proven dead code, not just
# unused: for any support/contradict >= 0, |support - contradict| <=
# support + contradict always (the net can never exceed the total) -- so
# whenever total_weight < 0.3, abs(net) was ALSO necessarily < 0.3 < 0.5
# = DECISION_THRESHOLD, meaning the net-weight check a few lines below
# already caught every case this constant could ever have caught, with
# the identical UNDETERMINED outcome. Verified by a 1,000,000-trial Monte
# Carlo check (zero violations) before removing, not just the algebra
# alone. Removed rather than redesigned to have an independent effect:
# docs/DESIGN.md §3 already states these thresholds are "arbitrary, not
# fit to anything" and shouldn't be tuned without real evidence data to
# tune them against -- inventing a new independent role for this
# constant without that data would be guessing, not fixing.

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

#: Item 19 (external review, time-decay — DESIGN.md's other long-listed
#: scoring gap, alongside redundancy above): how fast a piece of evidence's
#: trust erodes once it carries a REAL timestamp (see Evidence.timestamp's
#: own docstring — most evidence today has none, and decay is a no-op for
#: those). Chosen, not fit to data (same honest caveat DESIGN.md already
#: states about every other scoring constant here): two years is long
#: enough that routine evidence aging (e.g. an FPGA timing-closure report
#: from a few months ago) barely moves, but long enough evidence (years
#: old) visibly erodes.
EVIDENCE_HALF_LIFE_DAYS = 365.0 * 2

#: Decay never pushes a piece of evidence's trust below this FRACTION of
#: its original value — old real evidence is weaker, never worthless.
#: Set specifically so it can NEVER flip an existing single-source verdict
#: (the only shape fpga_embedded.py's Vivado path currently produces,
#: trust=0.9) from CONFIRMED/CONTRADICTED to UNDETERMINED purely from age:
#: 0.9 * MIN_DECAY_FACTOR must stay >= DECISION_THRESHOLD=0.5, i.e. this
#: floor must stay above 0.5/0.9 ≈ 0.556 — checked by
#: test_engine.py::test_min_decay_factor_can_never_flip_an_existing_single_source_verdict,
#: not just asserted here.
MIN_DECAY_FACTOR = 0.7


def _decayed_trust(evidence: Evidence, *, now: datetime | None = None) -> tuple[float, str | None]:
    """Returns (effective_trust, a human-readable decay note or None).

    A no-op (full trust, no note) whenever `evidence.timestamp` is None —
    decay only ever fires on evidence a domain adapter has attached a REAL
    date to from the underlying document itself, never guessed or back-filled
    (see Evidence.timestamp's own docstring for which domains do this today:
    only fpga_embedded.py's Vivado-report path, as of this round).
    """
    if evidence.timestamp is None:
        return evidence.trust, None
    now = now if now is not None else datetime.now()
    age_days = max((now - evidence.timestamp).total_seconds() / 86400.0, 0.0)
    decay_factor = max(MIN_DECAY_FACTOR, 0.5 ** (age_days / EVIDENCE_HALF_LIFE_DAYS))
    effective = evidence.trust * decay_factor
    if decay_factor >= 0.999:  # evidence is current enough that decay is invisible — no reasoning noise
        return effective, None
    return effective, (
        f"{evidence.source}: trust decayed from {evidence.trust:.2f} to {effective:.2f} "
        f"(evidence dated {evidence.timestamp.date()}, {age_days:.0f} days old)."
    )


def _decay_all(evidence: list[Evidence]) -> tuple[dict[Evidence, float], list[str]]:
    """Decays every piece of evidence once (not per-stance, so the SAME decayed
    value is used consistently everywhere a piece of evidence is weighed)."""
    effective: dict[Evidence, float] = {}
    notes: list[str] = []
    for e in evidence:
        trust, note = _decayed_trust(e)
        effective[e] = trust
        if note:
            notes.append(note)
    return effective, notes


def _redundancy_collapsed_weight(evidence: list[Evidence], stance: str, effective_trust: dict[Evidence, float]) -> float:
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

    Uses each piece's time-decayed trust (`effective_trust`, computed once
    per `_score()` call by `_decay_all()`), not raw `e.trust` — the "highest
    trust per source" comparison below is therefore also decay-aware.
    """
    best_by_source: dict[str, float] = {}
    for e in evidence:
        if e.stance != stance:
            continue
        best_by_source[e.source] = max(best_by_source.get(e.source, 0.0), effective_trust[e])
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

        # FOUND BUG (external review, verified against the real code):
        # `Claim.context` is an unrestricted dict (verbatim from a POST
        # /verify body), and adapter code assumes field TYPES without
        # checking all of them -- `report_path: 123` (an int, not a str)
        # crashes `Path(123)` with a TypeError; `metric: []` crashes
        # `ctx["metric"].lower()` with an AttributeError; `url: 123`
        # crashes research_web.py's urlparse() the same way. Each of
        # these escaped as an unhandled 500, not a clean 4xx/UNDETERMINED
        # -- centralized here, the ONE place every claim already flows
        # through regardless of domain, rather than hand-auditing every
        # field of every current (and future) adapter's context contract
        # individually. This is deliberately broad (any Exception an
        # adapter's own _check()-style validation didn't anticipate), on
        # the same "never trust an adapter not to misbehave" principle
        # the SSRF guard and path-safety checks already apply elsewhere --
        # a bug in a FUTURE adapter's type-handling is caught here too,
        # not just the four cases found this round.
        try:
            evidence = await adapter.gather_evidence(claim)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment above
            return Verdict(
                claim=claim,
                state=VerdictState.UNDETERMINED,
                confidence=None,
                evidence=[],
                reasoning=[
                    f"Domain '{claim.domain}' could not process this claim's context: "
                    f"{type(exc).__name__}: {exc}"
                ],
                missing=[
                    "Claim.context has a field in a shape this domain's adapter could not handle "
                    "(wrong type, missing nested key, or similar) — refusing to guess rather than "
                    "letting the error propagate."
                ],
            )
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

        effective_trust, decay_notes = _decay_all(evidence)
        for note in decay_notes:
            reasoning.append(f"Time-decay: {note}")

        support = _redundancy_collapsed_weight(evidence, "supports", effective_trust)
        contradict = _redundancy_collapsed_weight(evidence, "contradicts", effective_trust)
        reasoning.append(f"Support weight: {support:.2f}, contradiction weight: {contradict:.2f}.")

        total_weight = support + contradict

        # MERGED (external review — see MIN_EVIDENCE_WEIGHT's removal note
        # above): this used to be two separate checks, a total_weight
        # minimum and this net-weight one, but the first was PROVEN dead
        # code — it never independently fired, since |net| <= total_weight
        # always, so total_weight below its old 0.3 floor meant |net| was
        # also already below this 0.5 threshold. Merging them loses no
        # case the old code handled (every one still lands here with the
        # SAME describe_gap()-sourced `missing` value, now called
        # unconditionally rather than only on the old first branch), and
        # gains one: an adapter that has something specific to say about
        # GENUINELY CONFLICTING (not just absent) evidence now gets the
        # chance to say it too, instead of always getting the generic
        # fallback below.
        net = support - contradict
        if abs(net) < DECISION_THRESHOLD:
            missing = adapter.describe_gap(claim, evidence)
            reasoning.append(
                "Total evidence weight below the decision threshold — refusing to render a confident verdict."
                if not evidence else
                "Support and contradiction are too close to call."
            )
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
                missing=missing or ["Evidence conflicts or is too evenly weighted to resolve."],
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
