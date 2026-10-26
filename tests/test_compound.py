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
    _DECOMPOSE_SYSTEM_PROMPT,
    _FIDELITY_CHECK_SYSTEM_PROMPT,
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
    to NebiusTokenFactoryClient's complete() interface. decompose_claim()
    makes a SECOND call (the fidelity check) whenever more than one part
    comes back — dispatched on the `system` prompt, since this one fake
    object has to answer both calls differently. `fidelity_response`
    defaults to "faithful" so every existing single-response call site
    (written before the fidelity check existed) keeps passing unchanged;
    pass "unfaithful" explicitly to test the rejection path."""

    def __init__(self, response: str | Exception, fidelity_response: str = "faithful"):
        self._response = response
        self._fidelity_response = fidelity_response

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        if system == _FIDELITY_CHECK_SYSTEM_PROMPT:
            return self._fidelity_response
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


# --- decomposition FIDELITY (round 2 category-8 finding, 2026-10-26) ---
#
# FOUND live (stress_test/test_compound_on_cat8.py): for a "X; therefore
# Y1, Y2, Y3" fallacy-chain claim, decompose_claim() sometimes silently
# rewrote each false Y into its own negation instead of extracting it as
# actually asserted -- an obviously-false compound claim ("a significant
# association was found; therefore it caused the outcome, it must
# replicate everywhere, and no confounder explains it") decomposed into
# three TRUE statements and scored a false CONFIRMED. Confirmed
# non-deterministic on live re-test. These tests use the EXACT bad JSON
# captured from that live run, via a scripted fake client -- proving the
# fidelity check catches this specific real failure, not a hypothetical
# one, regardless of whether a live model would reproduce it again today.

_REAL_NEGATED_DECOMPOSE_JSON = (
    '{"parts": ['
    '{"text": "A statistically significant association between two variables does not '
    'necessarily imply that the first variable caused the second.", "domain": "searchlight"}, '
    '{"text": "An association observed in a study is not guaranteed to replicate in every '
    'population.", "domain": "searchlight"}, '
    '{"text": "A statistically significant association can still be explained by confounding '
    'variables.", "domain": "searchlight"}'
    ']}'
)

_ORIGINAL_FALLACY_CHAIN_CLAIM = (
    "A paper published in a peer-reviewed journal reports a statistically significant "
    "association between two variables; therefore, the first variable caused the second, "
    "the association must replicate in every population, and no confounding variable can "
    "explain the result."
)


async def test_decompose_claim_raises_when_fidelity_check_says_unfaithful():
    """The core regression: given the EXACT real bad decomposition this
    project's own live testing produced, and a fidelity check that
    (correctly) flags it, decompose_claim() must raise -- never silently
    return the corrected-but-unfaithful parts."""
    client = _FakeDecomposeClient(_REAL_NEGATED_DECOMPOSE_JSON, fidelity_response="unfaithful")
    with pytest.raises(DecompositionError, match="fidelity check"):
        await decompose_claim(client, _ORIGINAL_FALLACY_CHAIN_CLAIM)


async def test_verify_compound_is_undetermined_not_falsely_confirmed_on_unfaithful_decomposition():
    """End-to-end: the exact real bug this responds to was a false
    CONFIRMED on an obviously-false compound claim. With the fidelity
    check catching it, the claim must land on the honest UNDETERMINED
    gap instead -- never silently verify a different (corrected) claim
    than the one actually submitted."""
    client = _FakeDecomposeClient(_REAL_NEGATED_DECOMPOSE_JSON, fidelity_response="unfaithful")
    engine = VerificationEngine(domains={
        "searchlight": _FixedEvidenceAdapter("searchlight", [Evidence(source="s", snippet="x", stance="supports", trust=0.9)]),
    })
    result = await verify_compound(engine, client, _ORIGINAL_FALLACY_CHAIN_CLAIM)
    assert result.state == VerdictState.UNDETERMINED
    assert result.sub_claims == []
    assert any("fidelity check" in r for r in result.reasoning)


async def test_decompose_claim_still_succeeds_when_fidelity_check_says_faithful():
    """No regression on the happy path: a genuinely faithful multi-part
    decomposition (the normal case) must still succeed exactly as before
    -- the fidelity check is an additive safety net, not a new way for
    ordinary, correct decompositions to fail."""
    client = _FakeDecomposeClient(
        '{"parts": [{"text": "A", "domain": "substrate"}, {"text": "B", "domain": "searchlight"}]}',
        fidelity_response="faithful",
    )
    parts = await decompose_claim(client, "A and B")
    assert parts == [{"text": "A", "domain": "substrate"}, {"text": "B", "domain": "searchlight"}]


async def test_decompose_claim_defaults_to_faithful_when_caller_does_not_specify():
    """Every call site written before the fidelity check existed passes a
    single response with no fidelity_response argument -- must keep
    working exactly as before, not start failing because of an
    unspecified fidelity check."""
    client = _FakeDecomposeClient(
        '{"parts": [{"text": "A", "domain": "substrate"}, {"text": "B", "domain": "searchlight"}]}'
    )
    parts = await decompose_claim(client, "A and B")
    assert len(parts) == 2


async def test_fidelity_check_is_never_attempted_for_a_single_part():
    """A single part is trivially "the claim as-is" -- there is nothing to
    compare it against, and attempting the check anyway would just be a
    wasted call. Proven here by a fake client that would raise if its
    system prompt were ever the fidelity-check one for a single-part case."""
    class _RaisesOnFidelityCheck:
        async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
            if system == _FIDELITY_CHECK_SYSTEM_PROMPT:
                raise AssertionError("fidelity check must not be attempted for a single part")
            return '{"parts": [{"text": "A", "domain": "substrate"}]}'

    parts = await decompose_claim(_RaisesOnFidelityCheck(), "A")
    assert parts == [{"text": "A", "domain": "substrate"}]


def test_fidelity_check_prompt_forbids_calling_a_more_accurate_correction_faithful():
    """Locks in the exact distinction this whole fix depends on: a
    "corrected" negation is unfaithful even though it may be more
    factually accurate than the original claim -- faithfulness is about
    matching the ORIGINAL's assertion, not about being right."""
    assert "even if that corrected version happens to be more factually accurate" in _FIDELITY_CHECK_SYSTEM_PROMPT


def test_decompose_prompt_explicitly_forbids_negation_correction():
    assert "do NOT" in _DECOMPOSE_SYSTEM_PROMPT
    assert "its true negation" in _DECOMPOSE_SYSTEM_PROMPT
