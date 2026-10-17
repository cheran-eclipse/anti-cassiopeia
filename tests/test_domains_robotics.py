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
