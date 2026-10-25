"""
v3 §2.3 "bring your own evidence, pooled": tests for SubstrateAdapter's
_gather_byoe_pool path (Claim.context["document_pool"] truthy,
context["document_pool_items"] a list of (filename, text) pairs already
resolved by server.py -- see that module's _resolve_document_context).

Same offline discipline as test_substrate_byoe.py: a scripted fake LLM
client, real document text, the REAL chunk_document -> BM25Index ->
extract.propose() -> verify_proposal() -> retrieval.stance.judge_stance()
pipeline across a REAL combined multi-document index. No network call, no
live key.
"""

import json

from anticassiopeia.core import Claim, VerdictState, VerificationEngine
from anticassiopeia.domains.substrate import SubstrateAdapter


class _FakeClient:
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


_NOT_FOUND_JSON = json.dumps({"found": False, "reason": "not stated in any of these documents"})

_DOC_A_TEXT = "Widget Mk4 User Manual\n\nSection 3: Environmental Ratings\nThe Widget Mk4 enclosure carries an IP68 rating.\n"
_DOC_B_TEXT = "Gadget Pro Datasheet\n\nPower section\nThe Gadget Pro draws a maximum of 9 watts under full load.\n"


def _pool_context(*pool_items, total_available: int | None = None) -> dict:
    return {
        "document_pool": True,
        "document_pool_items": list(pool_items),
        "document_pool_total_available": total_available if total_available is not None else len(pool_items),
    }


async def test_pool_confirms_against_the_second_document_names_the_right_filename():
    """The claim is about doc B (second in the pool) -- proves chunk-id
    namespacing by pool index correctly resolves the citation back to
    doc B's real filename, not doc A's or a generic 'pool' placeholder."""
    quote = "The Gadget Pro draws a maximum of 9 watts under full load"
    client = _FakeClient(_found_json("doc1#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Gadget Pro draws 9 watts",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT), ("gadget.txt", _DOC_B_TEXT)),
    )
    evidence = await adapter.gather_evidence(claim)
    assert len(evidence) == 1
    assert evidence[0].source == "gadget.txt"
    assert evidence[0].stance == "supports"
    assert quote in evidence[0].snippet
    assert not adapter.describe_partial_gaps(claim)


async def test_pool_confirms_against_the_first_document():
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("doc0#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT), ("gadget.txt", _DOC_B_TEXT)),
    )
    evidence = await adapter.gather_evidence(claim)
    assert len(evidence) == 1
    assert evidence[0].source == "widget.txt"


async def test_pool_contradicts():
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("doc0#0", quote), stance_response="contradicts")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is not water resistant at all",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT), ("gadget.txt", _DOC_B_TEXT)),
    )
    evidence = await adapter.gather_evidence(claim)
    assert evidence[0].stance == "contradicts"


async def test_pool_empty_is_an_honest_named_gap_not_a_crash():
    adapter = SubstrateAdapter(client=_FakeClient())
    claim = Claim(text="anything", domain="substrate", context=_pool_context())
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("no valid uploaded documents to search" in g for g in gaps)
    gap = adapter.describe_gap(claim, evidence)
    assert any("no valid uploaded documents to search" in g for g in gap)


async def test_pool_truncation_is_always_named_in_reasoning_even_on_success():
    """server.py caps the pool at _MAX_POOL_DOCUMENTS and tells substrate.py
    the REAL total via document_pool_total_available -- this must show up
    in partial_gaps (and therefore Verdict.reasoning, unconditionally)
    even when the claim is otherwise confirmed, so a caller with more
    uploads than fit under the cap always learns some were skipped."""
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("doc0#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT), total_available=15),
    )
    evidence = await adapter.gather_evidence(claim)
    assert len(evidence) == 1  # still confirmed
    gaps = adapter.describe_partial_gaps(claim)
    assert any("only the 1 most recently uploaded document(s) were searched" in g and "15 total" in g for g in gaps)


async def test_pool_no_truncation_note_when_nothing_was_capped():
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("doc0#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT)),
    )
    await adapter.gather_evidence(claim)
    gaps = adapter.describe_partial_gaps(claim)
    assert not any("most recently uploaded" in g for g in gaps)


async def test_pool_no_bm25_match_across_any_document_is_an_honest_gap():
    client = _FakeClient(_NOT_FOUND_JSON)
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="xyzzy quux frobnicate unrelated gibberish term",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT), ("gadget.txt", _DOC_B_TEXT)),
    )
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("methods tried" in g for g in gaps)


async def test_pool_stance_unrelated_is_not_counted_as_evidence():
    quote = "The Gadget Pro draws a maximum of 9 watts under full load"
    client = _FakeClient(_found_json("doc1#0", quote), stance_response="unrelated")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT), ("gadget.txt", _DOC_B_TEXT)),
    )
    evidence = await adapter.gather_evidence(claim)
    assert evidence == []
    gaps = adapter.describe_partial_gaps(claim)
    assert any("doesn't address this specific claim" in g for g in gaps)


async def test_pool_stance_judging_is_given_the_resolved_filename_as_entity_context():
    """Same ODrive-style entity-ambiguity fix as _gather_byoe -- proves the
    REAL resolved filename (not a generic label) is what's prefixed onto
    the judge_stance prompt for the pooled path too."""
    quote = "* Peak current per motor: 120 Amps"
    odrive_like_text = "== ODrive v3.6 24V and 56V ==\n\n* Peak current per motor: 120 Amps\n"
    client = _FakeClient(_found_json("doc1#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    claim = Claim(
        text="The ODrive v3.6 24V supports a peak current of 120 Amps per motor.",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT), ("odrive.txt", odrive_like_text)),
    )
    await adapter.gather_evidence(claim)
    assert "odrive.txt" in client.last_prompt
    assert quote in client.last_prompt


async def test_pool_confirmed_end_to_end_through_the_real_engine():
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("doc0#0", quote), stance_response="supports")
    engine = VerificationEngine(domains={"substrate": SubstrateAdapter(client=client)})
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="substrate",
        context=_pool_context(("widget.txt", _DOC_A_TEXT), ("gadget.txt", _DOC_B_TEXT)),
    )
    verdict = await engine.verify(claim)
    assert verdict.state == VerdictState.CONFIRMED
    assert verdict.evidence[0].source == "widget.txt"


async def test_pool_takes_priority_over_fixed_corpus_depth_path():
    """document_pool present means the depth-specific fixed-corpus parser
    is never consulted, same "BYOE takes over entirely" principle
    document_text already established."""
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _FakeClient(_found_json("doc0#0", quote), stance_response="supports")
    adapter = SubstrateAdapter(client=client)
    context = _pool_context(("widget.txt", _DOC_A_TEXT))
    context["depth_m"] = 500.0
    context["polarity"] = "survives"
    claim = Claim(text="The Widget Mk4 is IP68 rated", domain="substrate", context=context)
    evidence = await adapter.gather_evidence(claim)
    assert len(evidence) == 1
    assert evidence[0].source == "widget.txt"
