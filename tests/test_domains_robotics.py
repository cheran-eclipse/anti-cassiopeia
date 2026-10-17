"""
Tests the robotics adapter's wiring to the real retrieve->propose->verify
pipeline (chunking + BM25 + a real/fake LLM client + verify_proposal) over
its actual corpus files, plus the honest-failure paths (no key configured,
a live call failing, a cited quote that doesn't actually exist in the
corpus) — the single most important property of this adapter.

Most tests inject `_FakeClient`, a scripted test double for
NebiusTokenFactoryClient, so they exercise the REAL extract.propose() ->
verify_proposal() code path without a network call or a live key. The
`test_live_*` tests at the bottom are the exception: they call the actual
Nebius API and require a real, working NEBIUS_API_KEY — see their own
docstrings.
"""

import json
import os

import pytest

from anticassiopeia.core import Claim, VerdictState, VerificationEngine
from anticassiopeia.domains.robotics import RoboticsAdapter
from anticassiopeia.llm.nebius_client import NebiusClientError
from anticassiopeia.retrieval import BM25Index, chunk_document
from anticassiopeia.retrieval.extract import propose


class _FakeClient:
    """Test double for NebiusTokenFactoryClient. `responses` maps a substring of
    the "Question: ..." line extract.propose() embeds in its prompt to either a
    canned JSON response string, or an Exception instance to raise instead —
    simulating a live-call failure without a network call."""

    def __init__(self, responses: dict[str, str | Exception]):
        self._responses = responses

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        for marker, response in self._responses.items():
            if marker in prompt:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"no fake response scripted for prompt: {prompt!r}")


# Correct, honest answers a real model should give — verified against the actual
# corpus/chunking output (see each chunk_id's real text in anticassiopeia/corpus/).
# These are the SAME facts the adapter used to hand-author in _KNOWN_PROPOSALS
# before propose() went live; scripting them here (as a fake remote LLM) instead
# of baking them into the adapter is the whole point of this change.
_HONEST_RESPONSES: dict[str, str] = {
    "maximum rated depth aluminum acrylic housing": json.dumps(
        {
            "found": True,
            "chunk_id": "DOC1_BlueROV2#1",
            "quote": "Maximum Rated Depth (Aluminum): 300 m",
            "value": 300,
            "unit": "m",
            "kind": "rated",
        }
    ),
    "maximum rated depth housing": json.dumps(
        {
            "found": True,
            "chunk_id": "DOC2_BlueROV2#1",
            "quote": "Maximum Rated Depth: 100 m",
            "value": 100,
            "unit": "m",
            "kind": "rated",
        }
    ),
    "operating pressure range bar": json.dumps(
        {
            "found": True,
            "chunk_id": "DOC3_Bar30#3",
            "quote": "Operating range: 0 to 30 bar, -20 to +85 C",
            "value": 30,
            "unit": "bar",
            "kind": "rated",
        }
    ),
}


def _honest_adapter() -> RoboticsAdapter:
    return RoboticsAdapter(client=_FakeClient(dict(_HONEST_RESPONSES)))


def _engine() -> VerificationEngine:
    return VerificationEngine(domains={"robotics": _honest_adapter()})


async def test_bluerov2_claim_produces_two_contradicting_sources():
    adapter = _honest_adapter()
    claim = Claim(text="BlueROV2 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 2
    assert all(e.stance == "contradicts" for e in ev)
    sources = {e.source for e in ev}
    assert sources == {"DOC1_BlueROV2", "DOC2_BlueROV2"}


async def test_bar30_claim_produces_real_evidence_with_a_real_locator():
    adapter = _honest_adapter()
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"
    assert "DOC3_Bar30" in ev[0].locator
    assert "chunk" in ev[0].locator  # proves it went through chunking, not a hardcoded string


async def test_bar100xt_has_no_corpus_and_gets_a_specific_named_gap():
    adapter = _honest_adapter()
    claim = Claim(text="Bar100XT survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "bar100xt" in gap[0].lower()
    assert "planning narrative" in gap[0].lower()


async def test_quspin_has_no_corpus_and_gets_a_specific_named_gap():
    adapter = _honest_adapter()
    claim = Claim(text="QuSpin QZFM Gen-3 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "quspin" in gap[0].lower()


async def test_unrecognized_part_gets_the_generic_gap():
    adapter = _honest_adapter()
    claim = Claim(text="Some totally unrelated part survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "no datasheet" in gap[0].lower()


async def test_fabricated_quote_is_rejected_even_through_the_full_adapter_path():
    """The core property this whole pipeline exists for: even if the (fake,
    scripted) LLM proposes a chunk_id that's real but a quote that is NOT
    actually in that chunk's text, verify_proposal() must reject it rather
    than trusting the proposer's say-so."""
    lying = json.dumps(
        {
            "found": True,
            "chunk_id": "DOC3_Bar30#3",  # a real chunk...
            "quote": "Operating range: 0 to 9999 bar",  # ...but this text isn't actually in it
            "value": 9999,
            "unit": "bar",
            "kind": "rated",
        }
    )
    adapter = RoboticsAdapter(client=_FakeClient({"operating pressure range bar": lying}))
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == [], "a quote that does not exist in the real corpus text must never become Evidence"


async def test_proposal_value_that_disagrees_with_its_own_quote_is_dropped():
    """verify_proposal only checks the quote; stance must not follow an unchecked
    'value' field the proposer attached to an otherwise-real quote."""
    lying = json.dumps(
        {
            "found": True,
            "chunk_id": "DOC3_Bar30#3",
            "quote": "Operating range: 0 to 30 bar, -20 to +85 C",  # real quote...
            "value": 9999,  # ...but this doesn't match the 30 the quote itself states
            "unit": "bar",
            "kind": "rated",
        }
    )
    adapter = RoboticsAdapter(client=_FakeClient({"operating pressure range bar": lying}))
    ev = await adapter.gather_evidence(Claim(text="Bar30 survives 500 m depth", domain="robotics"))
    assert ev == []


async def test_no_api_key_is_a_named_gap_not_a_crash(monkeypatch):
    """NEBIUS_API_KEY missing entirely must surface as a specific, honest gap —
    never a constructor crash and never silently treated the same as
    'nothing found'."""
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_BASE_URL", raising=False)
    adapter = RoboticsAdapter()  # no client injected, and no key in env
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "propose step can't run" in gap[0]
    assert "NEBIUS_API_KEY" in gap[0]


async def test_live_call_failure_is_a_named_gap_not_a_crash():
    """A NebiusClientError from the live client (bad key, non-200, wrong model,
    ...) must be caught per-document and surfaced by name, same pattern as
    domains/research_web.py's fetch-failure handling — never an unhandled
    exception out of gather_evidence(), never silently equated with
    'nothing found'."""
    failing = NebiusClientError("Nebius Token Factory returned 401: {\"detail\": \"...\"}")
    adapter = RoboticsAdapter(client=_FakeClient({"operating pressure range bar": failing}))
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "LLM propose call failed" in gap[0]
    assert "401" in gap[0]


# --- stance polarity (docs/DESIGN: stance must follow the claim, not authoring-time intent) ---


async def test_negated_bar30_claim_gets_opposite_stance_from_the_positive_framing():
    """The bug: 'Bar30 fails at 500 m' (TRUE per the ~30 bar rating) used to get the
    same 'contradicts' evidence as 'Bar30 survives 500 m' and so a BACKWARDS verdict."""
    pos = await _honest_adapter().gather_evidence(Claim(text="Bar30 survives 500 m depth", domain="robotics"))
    neg = await _honest_adapter().gather_evidence(Claim(text="Bar30 fails at 500 m depth", domain="robotics"))
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
    adapter = _honest_adapter()
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
    adapter = _honest_adapter()
    claim = Claim(text="Bar30 survives it", domain="robotics", context={"depth_m": "deep"})
    assert await adapter.gather_evidence(claim) == []
    assert "not a number" in adapter.describe_gap(claim, [])[0]


# --- live tests: require a real, working NEBIUS_API_KEY. Skipped (not run) when
# the var is entirely unset, so CI/local runs without a key don't silently fail.
# If the var IS set but the live API rejects it (bad/expired key, account not
# provisioned, wrong endpoint), these FAIL for real rather than skipping —
# a configured-but-broken key is itself a fact worth surfacing, not hiding. ---

_requires_live_key = pytest.mark.skipif(
    not os.environ.get("NEBIUS_API_KEY"), reason="requires a real, working NEBIUS_API_KEY"
)


@_requires_live_key
async def test_live_bar30_claim_is_accepted_through_the_real_propose_and_verify_pipeline():
    """4a: a part that IS in the corpus. The REAL live model must propose a quote
    that verify_proposal() actually accepts against the real chunk text — not a
    fake, not a mock, the genuine Nebius Token Factory round trip."""
    adapter = RoboticsAdapter()  # real NebiusTokenFactoryClient from the real env
    claim = Claim(text="Bar30 survives 100 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev, f"expected real accepted evidence; propose errors: {getattr(adapter, '_last_propose_errors', None)}"
    assert ev[0].stance == "supports"  # ~298 m depth-equivalent rating >= 100 m
    assert "DOC3_Bar30" in ev[0].locator


@_requires_live_key
async def test_live_model_honestly_reports_a_fact_not_in_the_shown_passages():
    """4b: the REAL model, shown real retrieved passages that genuinely don't state
    the requested fact, must report "not found" rather than hallucinating a value
    that could slip past verify_proposal(). Uses the real BlueROV2 corpus chunks
    (which state depth ratings) but asks about battery runtime, which isn't
    stated anywhere in them — a plausible-sounding fabrication is exactly the
    failure mode this project exists to catch."""
    from pathlib import Path

    from anticassiopeia.llm.nebius_client import NebiusTokenFactoryClient

    corpus_dir = Path(__file__).parent.parent / "anticassiopeia" / "corpus"
    text = (corpus_dir / "doc1_bluerov2_excerpt.txt").read_text()
    chunks = chunk_document("DOC1_BlueROV2", text, chunk_size=300, overlap=50)
    hits = BM25Index(chunks).search("maximum battery runtime hours", top_k=3)
    assert hits, "query must share at least one token with the corpus to reach a live call"

    proposal = await propose("maximum battery runtime hours", hits, NebiusTokenFactoryClient())
    assert proposal is None, f"expected an honest 'not found', got a hallucinated proposal: {proposal}"
