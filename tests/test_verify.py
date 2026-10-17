from anticassiopeia.retrieval.chunking import chunk_document
from anticassiopeia.retrieval.verify import Proposal, verify_proposal


def _chunks_by_id(text: str):
    chunks = chunk_document("doc", text, chunk_size=200, overlap=20)
    return chunks, {c.chunk_id: c for c in chunks}


def test_real_verbatim_quote_is_accepted():
    chunks, by_id = _chunks_by_id("Maximum Rated Depth (Aluminum): 300 m")
    p = Proposal(chunk_id=chunks[0].chunk_id, quote="Maximum Rated Depth (Aluminum): 300 m", value=300, unit="m")
    result = verify_proposal(p, by_id, source="doc", stance="contradicts")
    assert result.accepted
    assert result.evidence is not None
    assert result.evidence.stance == "contradicts"


def test_quote_with_different_whitespace_still_matches():
    chunks, by_id = _chunks_by_id("Maximum   Rated Depth (Aluminum):\n300 m")
    p = Proposal(chunk_id=chunks[0].chunk_id, quote="Maximum Rated Depth (Aluminum): 300 m")
    result = verify_proposal(p, by_id, source="doc", stance="contradicts")
    assert result.accepted


def test_fabricated_quote_is_rejected_not_trusted():
    chunks, by_id = _chunks_by_id("Maximum Rated Depth (Aluminum): 300 m")
    p = Proposal(chunk_id=chunks[0].chunk_id, quote="Maximum Rated Depth (Aluminum): 9999 m")
    result = verify_proposal(p, by_id, source="doc", stance="contradicts")
    assert not result.accepted
    assert "not found" in result.reason.lower()
    assert result.evidence is None


def test_unknown_chunk_id_is_rejected_with_a_named_reason():
    _chunks, by_id = _chunks_by_id("some real text")
    p = Proposal(chunk_id="nonexistent#99", quote="anything")
    result = verify_proposal(p, by_id, source="doc", stance="neutral")
    assert not result.accepted
    assert "unknown chunk_id" in result.reason.lower()


def test_accepted_evidence_locator_includes_doc_and_chunk_id():
    # locator is built from the CHUNK's own doc_id (ground truth), not the
    # `source` kwarg — so for this to actually test locator correctness, the
    # chunks need to carry the doc_id under test rather than the helper's
    # generic "doc" default.
    chunks = chunk_document("DOC3_Bar30", "Operating range: 0 to 30 bar", chunk_size=200, overlap=20)
    by_id = {c.chunk_id: c for c in chunks}
    p = Proposal(chunk_id=chunks[0].chunk_id, quote="Operating range: 0 to 30 bar", value=30, unit="bar")
    result = verify_proposal(p, by_id, source="DOC3_Bar30", stance="contradicts")
    assert result.accepted
    assert "DOC3_Bar30" in result.evidence.locator
    assert chunks[0].chunk_id in result.evidence.locator


def test_quote_substring_of_a_longer_real_line_is_accepted():
    # proposer quotes only part of a line — still a real substring, should pass
    chunks, by_id = _chunks_by_id("Operating range: 0 to 30 bar, -20 to +85 C")
    p = Proposal(chunk_id=chunks[0].chunk_id, quote="0 to 30 bar")
    result = verify_proposal(p, by_id, source="doc", stance="contradicts")
    assert result.accepted
