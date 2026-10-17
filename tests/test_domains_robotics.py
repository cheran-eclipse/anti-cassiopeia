"""
Tests the robotics adapter's wiring to the real retrieve->verify pipeline
(chunking + BM25 + verify_proposal) over its actual corpus files, plus the
honest-failure path when a cited quote doesn't actually exist in the
corpus — the single most important property of this adapter.
"""

from anticassiopeia.core import Claim
from anticassiopeia.domains.robotics import RoboticsAdapter
from anticassiopeia.retrieval import Proposal


async def test_bluerov2_claim_produces_two_contradicting_sources():
    adapter = RoboticsAdapter()
    claim = Claim(text="BlueROV2 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 2
    assert all(e.stance == "contradicts" for e in ev)
    sources = {e.source for e in ev}
    assert sources == {"DOC1_BlueROV2", "DOC2_BlueROV2"}


async def test_bar30_claim_produces_real_evidence_with_a_real_locator():
    adapter = RoboticsAdapter()
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"
    assert "DOC3_Bar30" in ev[0].locator
    assert "chunk" in ev[0].locator  # proves it went through chunking, not a hardcoded string


async def test_bar100xt_has_no_corpus_and_gets_a_specific_named_gap():
    adapter = RoboticsAdapter()
    claim = Claim(text="Bar100XT survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "bar100xt" in gap[0].lower()
    assert "planning narrative" in gap[0].lower()


async def test_quspin_has_no_corpus_and_gets_a_specific_named_gap():
    adapter = RoboticsAdapter()
    claim = Claim(text="QuSpin QZFM Gen-3 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "quspin" in gap[0].lower()


async def test_unrecognized_part_gets_the_generic_gap():
    adapter = RoboticsAdapter()
    claim = Claim(text="Some totally unrelated part survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "no datasheet" in gap[0].lower()


async def test_fabricated_quote_is_rejected_even_through_the_full_adapter_path(monkeypatch):
    """The core property this whole pipeline exists for: even if this adapter's
    own authored Proposal cited a value that is NOT actually in the corpus text,
    verify_proposal() must reject it rather than trusting the adapter's say-so."""
    import anticassiopeia.domains.robotics as robotics_module

    adapter = RoboticsAdapter()
    fabricated = {
        "DOC3_Bar30": (
            "operating pressure range bar",
            Proposal(chunk_id="", quote="Operating range: 0 to 9999 bar", value=9999, unit="bar", kind="rated"),
        )
    }
    monkeypatch.setitem(robotics_module._KNOWN_PROPOSALS, "bar30", fabricated)

    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == [], "a quote that does not exist in the real corpus text must never become Evidence"


# --- stance polarity (docs/DESIGN: stance must follow the claim, not authoring-time intent) ---

from anticassiopeia.core import VerificationEngine, VerdictState  # noqa: E402


def _engine() -> VerificationEngine:
    return VerificationEngine(domains={"robotics": RoboticsAdapter()})


async def test_negated_bar30_claim_gets_opposite_stance_from_the_positive_framing():
    """The bug: 'Bar30 fails at 500 m' (TRUE per the ~30 bar rating) used to get the
    same 'contradicts' evidence as 'Bar30 survives 500 m' and so a BACKWARDS verdict."""
    adapter = RoboticsAdapter()
    pos = await adapter.gather_evidence(Claim(text="Bar30 survives 500 m depth", domain="robotics"))
    neg = await adapter.gather_evidence(Claim(text="Bar30 fails at 500 m depth", domain="robotics"))
    assert [e.stance for e in pos] == ["contradicts"]
    assert [e.stance for e in neg] == ["supports"]
    assert [e.locator for e in pos] == [e.locator for e in neg]  # same retrieved evidence, opposite stance


async def test_negated_claims_get_correct_verdicts_end_to_end():
    engine = _engine()
    for text in ("Bar30 fails at 500 m depth", "BlueROV2 fails at 500 m"):
        v = await engine.verify(Claim(text=text, domain="robotics"))
        assert v.state == VerdictState.CONFIRMED, text
    v = await engine.verify(Claim(text="Bar30 survives 500 m depth", domain="robotics"))
    assert v.state == VerdictState.CONTRADICTED


async def test_condition_is_read_from_the_claim_not_assumed_to_be_500m():
    engine = _engine()
    v = await engine.verify(Claim(text="Bar30 survives 100 m depth", domain="robotics"))
    assert v.state == VerdictState.CONFIRMED  # ~298 m depth-equivalent rating >= 100 m
    v = await engine.verify(Claim(text="Bar30 fails at 100 m depth", domain="robotics"))
    assert v.state == VerdictState.CONTRADICTED


async def test_context_condition_is_preferred_and_equivalent_to_text():
    engine = _engine()
    ctx = {"depth_m": 500, "polarity": "fails"}
    v = await engine.verify(Claim(text="Bar30 depth claim", domain="robotics", context=ctx))
    assert v.state == VerdictState.CONFIRMED


async def test_conflicting_sources_stay_undetermined():
    """BlueROV2 DOC1 says 300 m, DOC2 says 100 m: at 200 m they genuinely disagree."""
    v = await _engine().verify(Claim(text="BlueROV2 survives 200 m depth", domain="robotics"))
    assert {e.stance for e in v.evidence} == {"supports", "contradicts"}
    assert v.state == VerdictState.UNDETERMINED


async def test_bar_conversion_too_close_to_call_is_neutral_not_guessed():
    # 30 bar ~= 298 m; at 300 m the gauge/absolute ambiguity decides it, so say nothing.
    v = await _engine().verify(Claim(text="Bar30 survives 300 m depth", domain="robotics"))
    assert [e.stance for e in v.evidence] == ["neutral"]
    assert v.state == VerdictState.UNDETERMINED


async def test_ambiguous_or_missing_condition_is_a_named_gap_not_a_guess():
    adapter = RoboticsAdapter()
    for text in (
        "Bar30 does not fail at 500 m depth",   # negated verb: refuse to guess polarity
        "Bar30 survives 500 ft depth",          # unsupported unit
        "BlueROV2 weighs 10 kg",                # not a depth claim at all
    ):
        claim = Claim(text=text, domain="robotics")
        ev = await adapter.gather_evidence(claim)
        assert ev == [], text
        gap = adapter.describe_gap(claim, ev)
        assert "depth condition" in gap[0], text
        assert "depth_m" in gap[0], text


async def test_bad_context_values_are_a_named_gap():
    adapter = RoboticsAdapter()
    claim = Claim(text="Bar30 survives it", domain="robotics", context={"depth_m": "deep"})
    assert await adapter.gather_evidence(claim) == []
    assert "not a number" in adapter.describe_gap(claim, [])[0]


async def test_proposal_value_that_disagrees_with_its_own_quote_is_dropped(monkeypatch):
    """verify_proposal only checks the quote; stance must not follow an unchecked 'value'."""
    import anticassiopeia.domains.robotics as robotics_module

    lying = {
        "DOC3_Bar30": (
            "operating pressure range bar",
            Proposal(chunk_id="", quote="Operating range: 0 to 30 bar, -20 to +85 C", value=9999, unit="bar", kind="rated"),
        )
    }
    monkeypatch.setitem(robotics_module._KNOWN_PROPOSALS, "bar30", lying)
    ev = await RoboticsAdapter().gather_evidence(Claim(text="Bar30 survives 500 m depth", domain="robotics"))
    assert ev == []
