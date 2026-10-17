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
    ev = [Evidence(source="s", snippet="x", stance="supports", trust=0.9)]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.CONFIRMED
    assert v.confidence == pytest.approx(1.0)


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


async def test_weak_evidence_below_minimum_weight_is_undetermined_even_if_one_sided():
    # single low-trust piece of evidence, all pointing one way, but too thin overall
    ev = [Evidence(source="a", snippet="x", stance="supports", trust=0.1)]
    engine = VerificationEngine(domains={"test_domain": _FixedEvidenceAdapter(ev)})
    v = await engine.verify(_claim())
    assert v.state == VerdictState.UNDETERMINED


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
    assert v.confidence == pytest.approx(1.0)  # contested evidence must not dilute this


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
    assert v.confidence == pytest.approx(1.0)


async def test_register_adds_a_domain_after_construction():
    engine = VerificationEngine(domains={})
    engine.register(_FixedEvidenceAdapter([]))
    v = await engine.verify(_claim())  # would raise UnknownDomainError if register() didn't work
    assert v.state == VerdictState.UNDETERMINED
