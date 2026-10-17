import json
import os

import httpx
import pytest

from anticassiopeia.core import Claim
from anticassiopeia.domains.research_web import ResearchWebAdapter
from anticassiopeia.llm.nebius_client import NebiusClientError
from evals.fixture_server import serve_fixtures


class _DummyAsyncClient:
    def __init__(self, response: httpx.Response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str) -> httpx.Response:
        return self._response


async def test_block_page_200_is_treated_as_undetermined_not_contradicted(monkeypatch):
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(
        200,
        request=request,
        text="<html><body><h1>Access Denied</h1><p>Blocked by policy proxy.</p></body></html>",
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    adapter = ResearchWebAdapter()
    claim = Claim(
        text="example.com states it is reserved for illustrative examples",
        domain="research_web",
        context={"url": "https://example.com", "quote": "illustrative examples in documents"},
    )
    ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "block/proxy page" in gap[0]


async def test_non_block_page_without_quote_is_real_contradiction(monkeypatch):
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(200, request=request, text="<html><body><p>ordinary page text</p></body></html>")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    adapter = ResearchWebAdapter()
    claim = Claim(
        text="example.com states it is reserved for illustrative examples",
        domain="research_web",
        context={"url": "https://example.com", "quote": "illustrative examples in documents"},
    )
    ev = await adapter.gather_evidence(claim)

    assert len(ev) == 1
    assert ev[0].stance == "contradicts"


# --- mode 2: multi-candidate live search, tested offline via a fake search provider
# that points at the real local fixture server (same fixtures/web/ pages mode 1 uses)
# plus a scripted fake LLM client, so the REAL propose()->verify_proposal() pipeline
# runs over a real local HTTP fetch without any network/live-key dependency. ---


class _FakeClient:
    """Test double for NebiusTokenFactoryClient covering BOTH prompt shapes this
    adapter sends: a propose() JSON-extraction prompt (starts "Question: ") and a
    _judge_stance() one-word prompt (starts "CLAIM: ")."""

    def __init__(self, propose_response: str | Exception, stance_response: str = "supports"):
        self._propose_response = propose_response
        self._stance_response = stance_response

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        if prompt.startswith("CLAIM:"):
            return self._stance_response
        if isinstance(self._propose_response, Exception):
            raise self._propose_response
        return self._propose_response


def _found_json(chunk_id: str, quote: str) -> str:
    return json.dumps({"found": True, "chunk_id": chunk_id, "quote": quote, "value": None, "unit": None, "kind": None})


_NOT_FOUND_JSON = json.dumps({"found": False, "reason": "not stated in the shown passages"})
_FIXTURE_QUOTE = "The reference pump is rated for a maximum operating pressure of 12 bar."


async def test_multi_candidate_confirmed_through_real_fixture_fetch_and_verify():
    """A real HTTP fetch of a local fixture page, real chunking, real BM25, the real
    propose()->verify_proposal() pipeline, and a scripted stance judgment — the only
    fake things are the search-candidate list (points at the fixture server instead
    of the live web) and the LLM client (no network/key needed)."""
    with serve_fixtures() as base_url:

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        # chunk_id = f"{doc_id}#0": this tiny page's stripped text is one chunk,
        # and doc_id is the fetched URL itself — verified via chunk_document's
        # own documented id scheme, not guessed.
        client = _FakeClient(_found_json(f"{base_url}/stable_page.html#0", _FIXTURE_QUOTE), stance_response="supports")
        adapter = ResearchWebAdapter(client=client, search=fake_search)
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web")
        ev = await adapter.gather_evidence(claim)

    assert len(ev) == 1
    assert ev[0].stance == "supports"
    assert ev[0].source == f"{base_url}/stable_page.html"
    assert "chunk" in ev[0].locator


async def test_multi_candidate_contradicted_when_model_judges_conflict():
    with serve_fixtures() as base_url:

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        client = _FakeClient(
            _found_json(f"{base_url}/stable_page.html#0", _FIXTURE_QUOTE), stance_response="contradicts"
        )
        adapter = ResearchWebAdapter(client=client, search=fake_search)
        claim = Claim(text="the reference pump is rated for 9999 bar", domain="research_web")
        ev = await adapter.gather_evidence(claim)

    assert len(ev) == 1
    assert ev[0].stance == "contradicts"


async def test_multi_candidate_no_candidates_found_is_a_named_gap():
    async def fake_search(_query: str, _max: int) -> list[str]:
        return []

    adapter = ResearchWebAdapter(client=_FakeClient(_NOT_FOUND_JSON), search=fake_search)
    claim = Claim(text="some claim no search backend will find anything for", domain="research_web")
    ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "no live candidate pages found" in gap[0].lower()


async def test_multi_candidate_model_honestly_reports_not_found_is_undetermined_not_contradicted():
    """The fact genuinely isn't on the fetched page — the model must say so, and
    that must NOT collapse into a false 'contradicts'."""
    with serve_fixtures() as base_url:

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        adapter = ResearchWebAdapter(client=_FakeClient(_NOT_FOUND_JSON), search=fake_search)
        claim = Claim(text="the reference pump has a maximum operating pressure of 12 bar", domain="research_web")
        ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "honestly reported" in gap[0]


async def test_multi_candidate_fabricated_quote_is_rejected_even_with_a_real_candidate_page():
    """The core property, carried over to mode 2: a quote that is NOT actually on
    the real fetched page must be rejected by verify_proposal(), regardless of
    what the (fake, scripted) proposer claims."""
    with serve_fixtures() as base_url:

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        client = _FakeClient(_found_json(f"{base_url}/stable_page.html#0", "maximum operating pressure of 9999 bar"))
        adapter = ResearchWebAdapter(client=client, search=fake_search)
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web")
        ev = await adapter.gather_evidence(claim)

    assert ev == [], "a quote that does not exist in the real fetched page must never become Evidence"


async def test_multi_candidate_missing_key_is_a_named_gap_not_a_crash(monkeypatch):
    """NEBIUS_API_KEY missing entirely must surface as a specific, honest gap —
    reached only after a real fetch + real BM25 match, so this exercises the
    client-missing branch for real, not in isolation."""
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)

    with serve_fixtures() as base_url:

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        adapter = ResearchWebAdapter(search=fake_search)  # no client injected, no key in env
        claim = Claim(
            text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web"
        )
        ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "propose step can't run" in gap[0]
    assert "NEBIUS_API_KEY" in gap[0]


async def test_multi_candidate_propose_failure_is_a_named_gap_not_a_crash():
    with serve_fixtures() as base_url:

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        failing = NebiusClientError('Nebius Token Factory returned 401: {"detail": "..."}')
        adapter = ResearchWebAdapter(client=_FakeClient(failing), search=fake_search)
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web")
        ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "propose call failed" in gap[0]
    assert "401" in gap[0]


# --- live tests: require a real, working NEBIUS_API_KEY and real network access.
# Skipped (not run) when the var is entirely unset; FAIL for real (not skip) if the
# var is set but something's actually broken — same policy as robotics.py's live
# tests, same reasoning: a configured-but-broken key/search/model is a fact worth
# surfacing, not hiding. Each outcome below was independently confirmed live,
# repeatedly, before being written down here — see research_web.py's module
# docstring and evals/cases/research_web/live_multi_candidate_*.json. ---

_requires_live_key = pytest.mark.skipif(
    not os.environ.get("NEBIUS_API_KEY"), reason="requires a real, working NEBIUS_API_KEY"
)


@_requires_live_key
async def test_live_multi_candidate_confirmed_from_a_real_wikipedia_article():
    adapter = ResearchWebAdapter()
    claim = Claim(
        text="BlueROV2 is a modular remotely operated underwater vehicle developed by Blue Robotics",
        domain="research_web",
    )
    ev = await adapter.gather_evidence(claim)
    assert ev, f"expected real confirmed evidence; gap: {getattr(adapter, '_last_web_gap', None)}"
    assert ev[0].stance == "supports"
    assert ev[0].source == "https://en.wikipedia.org/wiki/BlueROV2"


@_requires_live_key
async def test_live_multi_candidate_contradicted_by_a_real_wikipedia_article():
    adapter = ResearchWebAdapter()
    claim = Claim(text="BlueROV2 was developed by OpenROV", domain="research_web")
    ev = await adapter.gather_evidence(claim)
    assert ev, f"expected real contradicting evidence; gap: {getattr(adapter, '_last_web_gap', None)}"
    assert ev[0].stance == "contradicts"


@_requires_live_key
async def test_live_multi_candidate_undetermined_when_no_real_source_settles_it():
    """A specific, plausible-sounding, fabricated-style number that no real
    source actually states — must stay UNDETERMINED, never a guessed CONFIRMED."""
    adapter = ResearchWebAdapter()
    claim = Claim(
        text="Blue Robotics Bar30 pressure sensor has a mean time between failures of 50000 hours",
        domain="research_web",
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == [], f"expected no evidence (honest gap), got: {ev}"
    gap = adapter.describe_gap(claim, ev)
    assert "no live candidate pages found" in gap[0].lower()
