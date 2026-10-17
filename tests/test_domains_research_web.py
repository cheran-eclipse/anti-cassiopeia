import httpx

from anticassiopeia.core import Claim
from anticassiopeia.domains.research_web import ResearchWebAdapter


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
