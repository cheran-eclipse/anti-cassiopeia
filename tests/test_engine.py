from datetime import datetime, timedelta

import pytest

from anticassiopeia.core import Claim, DomainAdapter, Evidence, UnknownDomainError, VerificationEngine, VerdictState


class _FixedEvidenceAdapter(DomainAdapter):
    """Test double: returns whatever evidence list it's constructed with."""

    domain_name = "test_domain"

    def __init__(self, evidence: list[Evidence]):
        self._evidence = evidence

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        return self._evidence


def _claim(domain="test_domain"):
    return Claim(text="some claim", domain=domain)


async def test_unknown_domain_raises():
    engine = VerificationEngine(domains={})
    with pytest.raises(UnknownDomainError):
        await engine.verify(_claim())


async def test_no_evidence_is_undetermined_with_a_gap():
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter([])})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.UNDETERMINED
    assert v.confidence is None
    assert v.missing


async def test_strong_support_is_confirmed():
    # One source's trust=0.9 would naively give confidence=0.9/0.9=1.0 --
    # fixed (external review): a lone source is capped below full
    # certainty regardless of its own trust value, see test below.
    ev = [Evidence(source="s", snippet="x", stance="supports", trust=0.9)]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED
    assert v.confidence == pytest.approx(0.9)


async def test_single_source_confidence_is_capped_below_full_certainty():
    # FOUND BUG (external review): confidence = |net|/total_weight reached a
    # full 1.00 off exactly one piece of evidence, regardless of trust --
    # fixed by capping confidence when only one source contributes.
    from anticassiopeia.core.engine import SINGLE_SOURCE_CONFIDENCE_CAP

    ev = [Evidence(source="only-source", snippet="x", stance="supports", trust=0.99)]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED
    assert v.confidence == pytest.approx(SINGLE_SOURCE_CONFIDENCE_CAP)
    assert any("capped" in r.lower() for r in v.reasoning)


async def test_two_independent_sources_are_not_capped():
    # Genuine corroboration from two DIFFERENT sources is real signal a
    # lone source can't provide -- the cap must not apply here.
    ev = [
        Evidence(source="source-a", snippet="x", stance="supports", trust=0.9),
        Evidence(source="source-b", snippet="y", stance="supports", trust=0.9),
    ]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED
    assert v.confidence == pytest.approx(1.0)


async def test_same_source_repeated_does_not_double_count_weight():
    # FOUND BUG (external review, docs/DESIGN.md §3): two near-identical
    # pieces of evidence from the SAME source used to sum like two
    # independent confirmations. Fixed: same-source evidence is collapsed
    # to its single highest-trust piece before summing, so repeating a
    # source adds no extra weight (and does NOT lift the single-source cap
    # into a two-source result either).
    ev = [
        Evidence(source="same-doc", snippet="x", stance="supports", trust=0.6),
        Evidence(source="same-doc", snippet="x (duplicate chunk)", stance="supports", trust=0.6),
    ]
    one_piece = VerificationEngine(
        domains={"test_domain": _FixedEvidenceAdapter([ev[0]])}
    )
    two_pieces_same_source = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v1 = await one_piece.verify(_claim())
    v2 = await two_pieces_same_source.verify(_claim())
    assert v1.state == v2.state == VerdictState.CONFIRMED
    assert v1.confidence == pytest.approx(v2.confidence)  # the duplicate added nothing


async def test_strong_contradiction_is_contradicted():
    ev = [Evidence(source="s", snippet="x", stance="contradicts", trust=0.9)]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONTRADICTED


async def test_evenly_balanced_evidence_is_undetermined_not_a_coin_flip():
    ev = [
        Evidence(source="a", snippet="x", stance="supports", trust=0.6),
        Evidence(source="b", snippet="y", stance="contradicts", trust=0.6),
    ]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.UNDETERMINED


async def test_weak_evidence_below_decision_threshold_is_undetermined_even_if_one_sided():
    # single low-trust piece of evidence, all pointing one way, but too thin to decide.
    # (external review: engine.py used to have a SEPARATE MIN_EVIDENCE_WEIGHT=0.3
    # constant/check for this case -- proven mathematically dead code, since
    # |net| <= total_weight always, so anything below that 0.3 floor was
    # already below DECISION_THRESHOLD=0.5 too. Removed; this test's outcome
    # is unchanged, now via the single merged check.)
    ev = [Evidence(source="a", snippet="x", stance="supports", trust=0.1)]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.UNDETERMINED


async def test_describe_gap_is_consulted_even_for_genuinely_conflicting_nonempty_evidence():
    # FOUND improvement while removing MIN_EVIDENCE_WEIGHT (external review):
    # the old "too close to call" branch never called adapter.describe_gap()
    # at all, always using a generic message -- merging the two branches
    # means an adapter with something specific to say about conflicting
    # evidence now gets the chance to say it, not just on the zero-evidence path.
    class _AdapterWithSpecificConflictGap(_FixedEvidenceAdapter):
        def describe_gap(self, claim, evidence):
            return ["Specific reason: sources genuinely disagree about X."]

    ev = [
        Evidence(source="a", snippet="x", stance="supports", trust=0.6),
        Evidence(source="b", snippet="y", stance="contradicts", trust=0.6),
    ]
    engine = VerificationEngine(domains={"test_domain": _AdapterWithSpecificConflictGap(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.UNDETERMINED
    assert v.missing == ["Specific reason: sources genuinely disagree about X."]


async def test_contested_evidence_is_excluded_from_scoring_not_counted_either_way():
    # one real supporting piece, plus a contested piece that should NOT swing the
    # verdict toward contradicted or add false confidence either direction
    ev = [
        Evidence(source="a", snippet="x", stance="supports", trust=0.9),
        Evidence(source="b", snippet="y", stance="contested", trust=0.9),
    ]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED
    # contested evidence must not dilute this -- still just one scored
    # (non-contested) source, so still subject to the single-source cap.
    assert v.confidence == pytest.approx(0.9)


async def test_only_contested_evidence_is_undetermined_with_a_specific_reason():
    ev = [Evidence(source="a", snippet="x", stance="contested", trust=0.9)]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.UNDETERMINED
    assert any("contested" in m.lower() for m in v.missing)


async def test_neutral_evidence_does_not_affect_the_verdict():
    ev = [
        Evidence(source="a", snippet="x", stance="supports", trust=0.9),
        Evidence(source="b", snippet="y", stance="neutral", trust=0.9),
    ]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED
    assert v.confidence == pytest.approx(0.9)  # still just one scored source


async def test_adapter_partial_gaps_are_always_surfaced_in_reasoning():
    # FOUND BUG (external review): a source returning an unusable, not-None
    # answer used to vanish without a trace once another source alone was
    # enough for a confident verdict. describe_partial_gaps() must now be
    # surfaced in reasoning regardless of final confidence.
    class _AdapterWithPartialGap(_FixedEvidenceAdapter):
        def describe_partial_gaps(self, claim):
            return ["doc-b: got an answer, but it wasn't usable: test reason."]

    ev = [Evidence(source="doc-a", snippet="x", stance="supports", trust=0.9)]
    engine = VerificationEngine(domains={"test_domain": _AdapterWithPartialGap(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED  # confident verdict...
    assert any("doc-b" in r and "test reason" in r for r in v.reasoning)  # ...but gap still recorded


async def test_undated_evidence_never_decays():
    # Item 19: Evidence.timestamp defaults to None -- the vast majority of
    # evidence today (freshly re-computed ml_data stats, live research_web
    # fetches, SVD register reads) must behave EXACTLY as before this
    # feature existed.
    ev = [Evidence(source="s", snippet="x", stance="supports", trust=0.9)]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED
    assert v.confidence == pytest.approx(0.9)
    assert not any("decay" in r.lower() for r in v.reasoning)


async def test_recently_dated_evidence_barely_decays():
    from anticassiopeia.core.engine import _decayed_trust

    ev = Evidence(source="s", snippet="x", stance="supports", trust=0.9, timestamp=datetime.now() - timedelta(days=1))
    trust, note = _decayed_trust(ev)
    assert trust == pytest.approx(0.9, abs=1e-2)  # 1 day against a 2-year half-life -- negligible
    assert note is None  # decay this small isn't worth noising up reasoning with


async def test_old_dated_evidence_decays_but_floors_at_min_decay_factor():
    from anticassiopeia.core.engine import MIN_DECAY_FACTOR, _decayed_trust

    ev = Evidence(
        source="s", snippet="x", stance="supports", trust=0.9,
        timestamp=datetime.now() - timedelta(days=365 * 20),  # 20 years -- many half-lives
    )
    trust, note = _decayed_trust(ev)
    assert trust == pytest.approx(0.9 * MIN_DECAY_FACTOR)
    assert note is not None
    assert "decayed from 0.90" in note


async def test_decaying_the_losing_side_raises_confidence_in_the_real_engine():
    # A single-stance verdict's confidence ratio is always 1.0 (or capped),
    # regardless of decay -- scaling the only stance present changes
    # nothing about net/total. Decay's effect is only visible with a real
    # MIX of supporting and contradicting evidence, so that's what this
    # test uses: an old, decayed CONTRADICTING piece should count for less,
    # raising confidence in the (undated, undecayed) supporting side.
    fresh_support = Evidence(source="a", snippet="x", stance="supports", trust=0.9)
    old_contradict = Evidence(
        source="b", snippet="y", stance="contradicts", trust=0.3,
        timestamp=datetime.now() - timedelta(days=365 * 20),
    )
    baseline_contradict = Evidence(source="b", snippet="y", stance="contradicts", trust=0.3)  # undated twin

    decayed_engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter([fresh_support, old_contradict])})
    baseline_engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter([fresh_support, baseline_contradict])})
    v_decayed = await decayed_engine.verify(_claim())
    v_baseline = await baseline_engine.verify(_claim())

    assert v_decayed.state == v_baseline.state == VerdictState.CONFIRMED
    assert v_decayed.confidence > v_baseline.confidence  # weakening the opposing evidence raised confidence
    assert any("time-decay" in r.lower() for r in v_decayed.reasoning)
    assert not any("time-decay" in r.lower() for r in v_baseline.reasoning)


async def test_min_decay_factor_can_never_flip_an_existing_single_source_verdict():
    # engine.py's own MIN_DECAY_FACTOR comment states this property --
    # verified here directly, not just asserted in a comment. Every current
    # adapter's single-source trust is 0.9 (fpga_embedded.py's Vivado/SVD
    # paths; robotics.py/research_web.py's LLM-verified single quotes) --
    # decay must never be able to push a lone 0.9 piece below
    # DECISION_THRESHOLD=0.5 purely from age, however old the evidence is.
    from anticassiopeia.core.engine import DECISION_THRESHOLD, MIN_DECAY_FACTOR

    assert 0.9 * MIN_DECAY_FACTOR >= DECISION_THRESHOLD

    ev = [Evidence(
        source="s", snippet="x", stance="supports", trust=0.9,
        timestamp=datetime.now() - timedelta(days=365 * 100),  # absurdly old, well past any floor
    )]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED


async def test_register_adds_a_domain_after_construction():
    engine = VerificationEngine(domains={})
    engine.register(_FixedEvidenceAdapter([]))
    v = await engine.verify(_claim())  # would raise UnknownDomainError if register() didn't work
    assert v.state == VerdictState.UNDETERMINED
