"""
v2 "bring your own evidence": tests for SubstrateAdapter's free-text BYOE
path (Claim.context["document_text"] present), added alongside the fixed-
corpus path tests in test_domains_substrate.py but kept in their own file
since this is a genuinely separate code path (see substrate.py's
_gather_byoe docstring).

All tests here are OFFLINE: a scripted fake LLM client (same dual-prompt-
shape convention test_domains_searchlight.py's _FakeClient already
established — "Question:" for propose(), "CLAIM:" for judge_stance()), a
real document_text string, and the REAL chunk_document -> BM25Index ->
extract.propose() -> verify_proposal() -> retrieval.stance.judge_stance()
pipeline. No network call, no live key, no corpus files touched.
"""

import json

import pytest

from anticassiopeia.core import Claim, VerdictState, VerificationEngine
from anticassiopeia.domains.substrate import SubstrateAdapter
from anticassiopeia.llm.nebius_client import NebiusClientError


class _FakeClient:
    """Same shape as test_domains_searchlight.py's _FakeClient: dispatches
    on whether the prompt is a propose() JSON-extraction prompt (starts
    "Question: ") or a judge_stance() one-word prompt (starts "CLAIM: ")."""

    def __init__(self, propose_response: str | Exception = "", stance_response: str | Exception = "supports"):
        self._propose_response = propose_response
        self._stance_response = stance_response

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        self.last_prompt = prompt
        if prompt.startswith("CLAIM:"):
            if isinstance(self._stance_response, Exception):
                raise self._stance_response
            return self._stance_response
        if isinstance(self._propose_response, Exception):
            raise self._propose_response
        return self._propose_response


def _found_json(chunk_id: str, quote: str) -> str:
    return json.dumps({"found": True, "chunk_id": chunk_id, "quote": quote, "value": None, "unit": None, "kind": None})


def _found_rated_json(chunk_id: str, quote: str, value: float, unit: str) -> str:
    """Same shape, but with kind="rated" -- the fixed-corpus path (unlike
    BYOE) rejects any proposal whose kind isn't exactly "rated" (see
    substrate.py's gather_evidence: `proposal.kind != "rated"`)."""
    return json.dumps({"found": True, "chunk_id": chunk_id, "quote": quote, "value": value, "unit": unit, "kind": "rated"})


_NOT_FOUND_JSON = json.dumps({"found": False, "reason": "not stated in this document"})

_DOCUMENT_TEXT = (
    "Widget Mk4 User Manual\n\n"
    "Section 3: Environmental Ratings\n"
    "The Widget Mk4 enclosure carries an IP68 rating and is certified for "
    "continuous operation when fully submerged in fresh water.\n\n"
    "Section 4: Power\n"
    "The Widget Mk4 draws a maximum of 4.2 watts under full load.\n"
)


async def test_byoe_confirms_against_the_uploaded_document_real_pipeline():
    """Real chunk_document() + real BM25Index + real verify_proposal(), only
    the LLM client is faked -- this is the thing the whole BYOE feature exists
    to do: check a claim against a document the caller supplied, not the
    fixed corpus."""
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("uploaded#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT, "document_filename": "widget_mk4_manual.txt"},
    )
    evidence = await adapter.gather_evidence(claim)
    assert len(evidence) == 1
    ev = evidence[0]
    assert ev.stance == "supports"
    assert ev.source == "widget_mk4_manual.txt"
    assert quote in ev.snippet
    assert not adapter.describe_partial_gaps(claim)


async def test_byoe_contradicts_when_the_model_judges_the_quote_conflicts():
    quote = "The Widget Mk4 draws a maximum of 4.2 watts under full load"
    client = _FakeClient(_found_json("uploaded#0", quote), stance_response="contradicts")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 draws 10 watts",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT},
    )
    evidence = await adapter.gather_evidence(claim)
    assert len(evidence) == 1
    assert evidence[0].stance == "contradicts"
    # no document_filename supplied -- falls back to a generic label, not a crash
    assert evidence[0].source == "uploaded document"


async def test_byoe_takes_over_even_when_depth_context_is_also_present():
    """IMPORTANT DESIGN NOTE from substrate.py's own docstring: document_text
    present means the depth-specific parser is never consulted, even if
    depth_m/polarity (the fixed-corpus path's OWN context keys) are ALSO
    present. A real caller might send both out of habit; BYOE must ignore
    the irrelevant depth keys rather than erroring or trying to apply them
    to the uploaded document's (unrelated) content."""
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("uploaded#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT, "depth_m": 500.0, "polarity": "survives"},
    )
    evidence = await adapter.gather_evidence(claim)
    assert len(evidence) == 1
    # Evidence came from the uploaded document, not a fixed-corpus doc_id --
    # proves the BYOE branch ran, not the depth-condition/fixed-corpus one.
    assert evidence[0].source == "uploaded document"


async def test_byoe_falls_back_to_fixed_corpus_when_document_text_is_absent():
    """No regression: a claim with no document_text in context behaves
    exactly as before -- the known fixed-corpus marker-based fake client
    convention from test_domains_substrate.py still works unchanged."""
    client = _FakeClient(_found_rated_json("DOC3_Bar30#3", "Operating range: 0 to 30 bar, -20 to +85 C", 30, "bar"))
    adapter = SubstrateAdapter(client=client)
    claim = Claim(text="bar30 survives 500m depth", domain="substrate")
    evidence = await adapter.gather_evidence(claim)
    assert len(evidence) == 1
    assert evidence[0].source == "DOC3_Bar30"


async def test_byoe_no_bm25_match_is_an_honest_named_gap_not_a_crash():
    client = _FakeClient(_NOT_FOUND_JSON)
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="xyzzy quux frobnicate unrelated gibberish term",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT, "document_filename": "widget_mk4_manual.txt"},
    )
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("methods tried" in g for g in gaps)
    gap = adapter.describe_gap(claim, evidence)
    assert any("methods tried" in g for g in gap)


async def test_byoe_model_honestly_reports_fact_absent():
    client = _FakeClient(_NOT_FOUND_JSON)
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT},
    )
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("genuinely absent" in g for g in gaps)


async def test_byoe_propose_call_failure_is_a_named_gap():
    client = _FakeClient(propose_response=NebiusClientError("Nebius Token Factory returned 500"))
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT},
    )
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("LLM propose call failed" in g for g in gaps)


async def test_byoe_unverifiable_quote_is_rejected_not_trusted():
    """The model claims a quote that is NOT actually in the document --
    verify_proposal() must independently catch this, exactly as it does for
    the fixed-corpus path; the proposer is never trusted on its own say-so."""
    client = _FakeClient(_found_json("uploaded#0", "This exact sentence does not appear anywhere in the document."))
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT},
    )
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("failed independent verification" in g for g in gaps)


async def test_byoe_stance_judging_is_given_the_source_filename_as_entity_context():
    """BUG FOUND (v2 stress test, live, reproducible 4/4 before this fix --
    see stress_test/results/V2_BYOE_STRESS_TEST_REPORT.md): extract.py's
    propose() keeps "quote" deliberately short, so a real document whose
    entity name lives only in a PRECEDING section heading (not restated in
    the quoted bullet line itself, e.g. real ODrive docs: "== ODrive v3.6
    24V and 56V ==" followed by "* Peak current per motor: 120 Amps" with
    no device name on that line) gave judge_stance() no way to confirm the
    quote was even about the claimed device -- it safely-but-wrongly
    returned "unrelated" for a true claim. Fixed by prefixing the text
    shown to judge_stance() with the real, already-known source filename.
    This test proves that prefix is actually present in the real prompt
    sent to the client, not just that the live call happened to work."""
    quote = "* Peak current per motor: 120 Amps"
    odrive_like_text = "== ODrive v3.6 24V and 56V ==\n\n* Peak current per motor: 120 Amps\n"
    client = _FakeClient(_found_json("uploaded#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The ODrive v3.6 24V supports a peak current of 120 Amps per motor.",
        domain="substrate",
        context={"document_text": odrive_like_text, "document_filename": "odrive_v3_6_specifications_excerpt.txt"},
    )
    await adapter.gather_evidence(claim)
    assert "odrive_v3_6_specifications_excerpt.txt" in client.last_prompt
    assert quote in client.last_prompt


async def test_byoe_stance_unrelated_is_not_counted_as_evidence():
    quote = "The Widget Mk4 draws a maximum of 4.2 watts under full load"
    client = _FakeClient(_found_json("uploaded#0", quote), stance_response="unrelated")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT},
    )
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("doesn't address this specific claim" in g for g in gaps)


async def test_byoe_with_no_client_configured_is_a_named_gap_not_a_crash():
    adapter = SubstrateAdapter(client=_FakeClient())  # constructed with a client...
    adapter._client = None  # ...then simulate "no NEBIUS_API_KEY configured" directly
    adapter._client_error = "NEBIUS_API_KEY is not set."
    claim = Claim(text="The Widget Mk4 is IP68 rated", domain="substrate", context={"document_text": _DOCUMENT_TEXT})
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("NEBIUS_API_KEY is not set" in g for g in gaps)


async def test_byoe_confirmed_end_to_end_through_the_real_engine():
    """Same pipeline, but through the real VerificationEngine (scoring,
    reasoning, missing[]) rather than calling the adapter directly -- proves
    the BYOE evidence actually produces a CONFIRMED verdict end to end."""
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("uploaded#0", quote), stance_response="supports")
    engine = VerificationEngine(domains={"substrate": SubstrateAdapter(client=client)})
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context={"document_text": _DOCUMENT_TEXT, "document_filename": "widget_mk4_manual.txt"},
    )
    verdict = await engine.verify(claim)
    assert verdict.state == VerdictState.CONFIRMED
    assert verdict.evidence[0].source == "widget_mk4_manual.txt"
