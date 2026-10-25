"""
Item 20 (compound-claim decomposition, 2-hour-budgeted round). Covers:
- _parse_decomposition()'s JSON-shape validation, offline, no LLM call.
- rollup()'s pure AND-semantics, offline, no LLM call.
- decompose_claim()/verify_compound() end-to-end against a FAKE client
  (same pattern as test_domains_substrate.py's _FakeClient) — no live
  Nebius call needed for any test in this file.
"""

import pytest

from anticassiopeia.core import Claim, Evidence, VerdictState, VerificationEngine
from anticassiopeia.core.compound import (
    DecompositionError, SubClaimResult, _parse_decomposition, decompose_claim, rollup, verify_compound,
)
from anticassiopeia.core.domain import DomainAdapter


class _FixedEvidenceAdapter(DomainAdapter):
    """Same test double as test_engine.py's — returns canned evidence per domain."""

    def __init__(self, domain_name: str, evidence: list[Evidence]):
        self.domain_name = domain_name
        self._evidence = evidence

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        return self._evidence


class _FakeDecomposeClient:
    """Test double for the LLM client decompose_claim() calls — duck-typed
    to NebiusTokenFactoryClient's complete() interface."""

    def __init__(self, response: str | Exception):
        self._response = response

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


# --- _parse_decomposition: pure JSON-shape validation ---

def test_parses_a_well_formed_two_part_response():
    parts = _parse_decomposition('{"parts": [{"text": "A", "domain": "substrate"}, {"text": "B", "domain": "searchlight"}]}')
    assert parts == [{"text": "A", "domain": "substrate"}, {"text": "B", "domain": "searchlight"}]


def test_strips_a_markdown_json_code_fence():
    parts = _parse_decomposition('```json\n{"parts": [{"text": "A", "domain": "substrate"}]}\n```')
    assert parts == [{"text": "A", "domain": "substrate"}]


def test_malformed_json_raises_decomposition_error_not_a_crash():
    with pytest.raises(DecompositionError, match="not valid JSON"):
        _parse_decomposition("not json at all")


def test_missing_parts_key_raises_decomposition_error():
    with pytest.raises(DecompositionError, match="parts"):
        _parse_decomposition('{"something_else": []}')


def test_empty_parts_list_raises_decomposition_error():
    with pytest.raises(DecompositionError, match="parts"):
        _parse_decomposition('{"parts": []}')


def test_part_missing_domain_field_raises_decomposition_error():
    with pytest.raises(DecompositionError, match="'text' and 'domain'"):
        _parse_decomposition('{"parts": [{"text": "A"}]}')


def test_part_with_empty_text_raises_decomposition_error():
    with pytest.raises(DecompositionError, match="empty"):
        _parse_decomposition('{"parts": [{"text": "  ", "domain": "substrate"}]}')


# --- decompose_claim(): wraps a real client call, including failures ---

async def test_decompose_claim_returns_parsed_parts_from_a_fake_client():
    client = _FakeDecomposeClient('{"parts": [{"text": "A", "domain": "substrate"}]}')
    parts = await decompose_claim(client, "A")
    assert parts == [{"text": "A", "domain": "substrate"}]


async def test_decompose_claim_wraps_a_client_exception_as_decomposition_error():
    client = _FakeDecomposeClient(RuntimeError("network exploded"))
    with pytest.raises(DecompositionError, match="network exploded"):
        await decompose_claim(client, "A")


# --- rollup(): pure AND-semantics, no I/O ---

def _verdict(state: VerdictState, confidence: float | None) -> "object":
    from anticassiopeia.core import Verdict
    return Verdict(claim=Claim(text="x", domain="substrate"), state=state, confidence=confidence, evidence=[], reasoning=[])


def test_rollup_all_confirmed_is_confirmed_with_the_minimum_confidence():
    results = [
        SubClaimResult(text="A", domain="substrate", verdict=_verdict(VerdictState.CONFIRMED, 0.9)),
        SubClaimResult(text="B", domain="searchlight", verdict=_verdict(VerdictState.CONFIRMED, 0.6)),
    ]
    state, confidence, reasoning = rollup(results)
    assert state == VerdictState.CONFIRMED
    assert confidence == pytest.approx(0.6)  # weakest link, not the strongest


def test_rollup_any_contradicted_is_contradicted_with_the_maximum_confidence_among_them():
    results = [
        SubClaimResult(text="A", domain="substrate", verdict=_verdict(VerdictState.CONFIRMED, 0.9)),
        SubClaimResult(text="B", domain="searchlight", verdict=_verdict(VerdictState.CONTRADICTED, 0.7)),
        SubClaimResult(text="C", domain="searchlight", verdict=_verdict(VerdictState.CONTRADICTED, 0.95)),
    ]
    state, confidence, reasoning = rollup(results)
    assert state == VerdictState.CONTRADICTED
    assert confidence == pytest.approx(0.95)  # the strongest evidence of falsity, not the weakest


def test_rollup_an_undetermined_part_with_no_contradiction_is_undetermined():
    results = [
        SubClaimResult(text="A", domain="substrate", verdict=_verdict(VerdictState.CONFIRMED, 0.9)),
        SubClaimResult(text="B", domain="searchlight", verdict=_verdict(VerdictState.UNDETERMINED, None)),
    ]
    state, confidence, reasoning = rollup(results)
    assert state == VerdictState.UNDETERMINED
    assert confidence is None


def test_rollup_with_no_verified_parts_at_all_is_undetermined_not_a_crash():
    results = [SubClaimResult(text="A", domain="unsupported", verdict=None)]
    state, confidence, reasoning = rollup(results)
    assert state == VerdictState.UNDETERMINED
    assert confidence is None
    assert any("unsupported" in r.lower() or "cannot supply" in r.lower() for r in reasoning) or any(
        "needs domain" in r for r in reasoning
    )


def test_rollup_of_an_empty_list_is_undetermined_not_a_crash():
    state, confidence, reasoning = rollup([])
    assert state == VerdictState.UNDETERMINED
    assert confidence is None


# --- verify_compound(): full orchestration against a fake client + real engine ---

async def test_verify_compound_confirms_when_every_decomposed_part_confirms():
    client = _FakeDecomposeClient(
        '{"parts": [{"text": "A", "domain": "substrate"}, {"text": "B", "domain": "searchlight"}]}'
    )
    engine = VerificationEngine(domains={
        "substrate": _FixedEvidenceAdapter("substrate", [Evidence(source="s1", snippet="x", stance="supports", trust=0.9)]),
        "searchlight": _FixedEvidenceAdapter("searchlight", [Evidence(source="s2", snippet="y", stance="supports", trust=0.9)]),
    })
    result = await verify_compound(engine, client, "A and B")
    assert result.state == VerdictState.CONFIRMED
    assert len(result.sub_claims) == 2
    assert all(sc.verdict is not None for sc in result.sub_claims)


async def test_verify_compound_contradicts_when_one_decomposed_part_contradicts():
    client = _FakeDecomposeClient(
        '{"parts": [{"text": "A", "domain": "substrate"}, {"text": "B", "domain": "searchlight"}]}'
    )
    engine = VerificationEngine(domains={
        "substrate": _FixedEvidenceAdapter("substrate", [Evidence(source="s1", snippet="x", stance="supports", trust=0.9)]),
        "searchlight": _FixedEvidenceAdapter("searchlight", [Evidence(source="s2", snippet="y", stance="contradicts", trust=0.9)]),
    })
    result = await verify_compound(engine, client, "A and B")
    assert result.state == VerdictState.CONTRADICTED


async def test_verify_compound_never_invents_an_ml_data_or_fpga_sub_claim():
    """The model classifying a part as needing quant/silicon must
    leave that part UNVERIFIED (domain="unsupported", verdict=None) --
    never routed through those adapters with a fabricated context dict."""
    client = _FakeDecomposeClient(
        '{"parts": [{"text": "A", "domain": "substrate"}, '
        '{"text": "the mean of some column is 5", "domain": "quant"}]}'
    )
    engine = VerificationEngine(domains={
        "substrate": _FixedEvidenceAdapter("substrate", [Evidence(source="s1", snippet="x", stance="supports", trust=0.9)]),
    })
    result = await verify_compound(engine, client, "A and the mean of some column is 5")
    unsupported = [sc for sc in result.sub_claims if sc.domain == "unsupported"]
    assert len(unsupported) == 1
    assert unsupported[0].verdict is None
    # one real CONFIRMED part, one unsupported part -> can't confirm the whole AND, nothing contradicts it either
    assert result.state == VerdictState.UNDETERMINED


async def test_verify_compound_handles_a_single_non_compound_claim():
    client = _FakeDecomposeClient('{"parts": [{"text": "A", "domain": "substrate"}]}')
    engine = VerificationEngine(domains={
        "substrate": _FixedEvidenceAdapter("substrate", [Evidence(source="s1", snippet="x", stance="supports", trust=0.9)]),
    })
    result = await verify_compound(engine, client, "A")
    assert result.state == VerdictState.CONFIRMED
    assert len(result.sub_claims) == 1


async def test_verify_compound_is_undetermined_not_a_crash_when_decomposition_itself_fails():
    client = _FakeDecomposeClient(RuntimeError("Nebius down"))
    engine = VerificationEngine(domains={})
    result = await verify_compound(engine, client, "A and B")
    assert result.state == VerdictState.UNDETERMINED
    assert result.sub_claims == []
    assert any("Nebius down" in r for r in result.reasoning)
