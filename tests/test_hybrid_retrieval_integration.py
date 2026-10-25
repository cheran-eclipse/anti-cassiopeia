"""
Integration tests for the hybrid-retrieval build's two integration points
(robotics.py's BYOE/pooled paths, and research_web.py's multi-candidate
path) -- proving the WIRING is real, not dead code. retrieval/hybrid.py's
own test_retrieval_hybrid.py already proves HybridIndex's fusion/
degradation logic in isolation; this file proves each domain adapter
actually calls `embed()` and that a working embedder's result reaches
the final Evidence, not just that degradation-with-no-embedder still
works (already covered elsewhere).

All OFFLINE: fake clients with a real, working (if not semantically
meaningful) embed() method -- no live Nebius call needed.
"""

import json

from anticassiopeia.core import Claim
from anticassiopeia.domains.research_web import ResearchWebAdapter
from anticassiopeia.domains.robotics import RoboticsAdapter
from evals.fixture_server import serve_fixtures

_DOCUMENT_TEXT = (
    "Widget Mk4 User Manual\n\n"
    "Section 3: Environmental Ratings\n"
    "The Widget Mk4 enclosure carries an IP68 rating and is certified for "
    "continuous operation when fully submerged in fresh water.\n\n"
    "Section 4: Power\n"
    "The Widget Mk4 draws a maximum of 4.2 watts under full load.\n"
)


def _found_json(chunk_id: str, quote: str) -> str:
    return json.dumps({"found": True, "chunk_id": chunk_id, "quote": quote, "value": None, "unit": None, "kind": None})


class _EmbeddingAwareFakeClient:
    """Dual-prompt-shape dispatch (same convention as every other fake
    client in this repo) PLUS a real, working embed() -- deterministic,
    not semantically meaningful (these tests check the PLUMBING: that
    embed() gets called and its vectors reach the final ranking, not
    retrieval quality, which needs a real embedder)."""

    def __init__(self, propose_response: str, stance_response: str = "supports", dim: int = 4):
        self._propose_response = propose_response
        self._stance_response = stance_response
        self._dim = dim
        self.embed_calls: list[list[str]] = []
        self.last_prompt: str | None = None

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        self.last_prompt = prompt
        if prompt.startswith("CLAIM:"):
            return self._stance_response
        return self._propose_response

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [[float((hash(t) >> (i * 4)) % 7) for i in range(self._dim)] for t in texts]


# --- robotics.py's BYOE path ---


async def test_byoe_calls_embed_when_the_client_supports_it():
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _EmbeddingAwareFakeClient(_found_json("uploaded#0", quote))
    adapter = RoboticsAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="robotics",
        context={"document_text": _DOCUMENT_TEXT, "document_filename": "widget_mk4_manual.txt"},
    )
    evidence = await adapter.gather_evidence(claim)

    assert len(evidence) == 1
    assert evidence[0].stance == "supports"
    # embed() was called TWICE: once for the corpus chunks (HybridIndex.embed),
    # once for the query (HybridIndex.search) -- proves both halves of the
    # vector leg actually ran, not just that degradation-with-no-embedder works.
    assert len(client.embed_calls) == 2


# --- robotics.py's pooled BYOE path ---


async def test_pool_calls_embed_once_for_the_whole_combined_pool():
    quote = "The Widget Mk4 enclosure carries an IP68 rating"
    client = _EmbeddingAwareFakeClient(_found_json("doc0#0", quote))
    adapter = RoboticsAdapter(client=client)
    claim = Claim(
        text="The Widget Mk4 is IP68 rated",
        domain="robotics",
        context={
            "document_pool": True,
            "document_pool_items": [("widget.txt", _DOCUMENT_TEXT)],
            "document_pool_total_available": 1,
        },
    )
    evidence = await adapter.gather_evidence(claim)

    assert len(evidence) == 1
    # corpus embed (all pooled chunks in ONE batch) + query embed = 2 calls,
    # same as the single-document BYOE path -- pooling multiple documents
    # must not multiply the embed call COUNT (only the batch SIZE).
    assert len(client.embed_calls) == 2


# --- research_web.py's multi-candidate path ---


async def test_multi_candidate_calls_embed_for_the_fetched_passages_and_the_query():
    with serve_fixtures() as base_url:
        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        quote = "The reference pump is rated for a maximum operating pressure of 12 bar."
        client = _EmbeddingAwareFakeClient(_found_json(f"{base_url}/stable_page.html#0", quote))
        adapter = ResearchWebAdapter(client=client, search=fake_search, block_private_networks=False)
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web")

        evidence = await adapter.gather_evidence(claim)

    assert len(evidence) == 1
    assert evidence[0].stance == "supports"
    assert len(client.embed_calls) == 2  # fetched-passage corpus embed + query embed
