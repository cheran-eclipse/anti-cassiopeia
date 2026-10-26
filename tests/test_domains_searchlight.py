import asyncio
import json
import os
import socket

import httpx
import pytest

import anticassiopeia.domains.searchlight as research_web_mod
import anticassiopeia.llm.nebius_client as nebius_client_mod
from anticassiopeia.core import Claim
from anticassiopeia.core.verdict import Evidence
from anticassiopeia.domains.searchlight import _MAX_RESPONSE_BYTES, SearchlightAdapter, _is_near_duplicate_evidence, _safe_fetch
from anticassiopeia.llm.nebius_client import NebiusClientError
from evals.fixture_server import serve_fixtures

# `block_private_networks=False` below (only on tests that fetch this file's own
# local fixture server, 127.0.0.1) opts out of the SSRF guard added to
# searchlight.py's real fetch calls -- see that module's docstring for the fix
# and why this is the ONLY place it's legitimate to disable it; default_domains()
# (what the real server uses) never does.


_REAL_GETADDRINFO = asyncio.base_events.BaseEventLoop.getaddrinfo


def _stub_dns_for_example_com(monkeypatch) -> None:
    """FOUND BUG (external review): 7 tests below use `https://example.com/...`
    as a stand-in "safe-looking" target while they actually test something
    ELSE (block-page detection, redirect handling, the size cap, the total
    timeout) -- but `_is_safe_to_fetch()` still does a REAL DNS lookup of
    example.com before ever reaching their own mocked
    `httpx.AsyncClient.stream`. That's non-hermetic: offline, or if
    example.com's resolution is slow/blocked, these tests fail or hang for
    a reason that has nothing to do with what they're actually checking.

    Fixed by faking DNS resolution for "example.com" specifically (to a
    real, fixed, globally-routable address, so `_is_safe_to_fetch()`'s own
    `ip.is_global` check still runs for real) -- NOT by stubbing
    `_is_safe_to_fetch()` itself, which would also defeat the redirect
    test's own real check of its UNSAFE second hop (169.254.169.254).
    Every other hostname (including literal IPs like 169.254.169.254,
    which resolve locally without any real network query regardless)
    still goes through the real resolver, unstubbed."""

    async def _fake_getaddrinfo(self, host, port, *args, **kwargs):
        if host == "example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return await _REAL_GETADDRINFO(self, host, port, *args, **kwargs)

    monkeypatch.setattr(asyncio.base_events.BaseEventLoop, "getaddrinfo", _fake_getaddrinfo)


class _DummyAsyncClient:
    def __init__(self, response: httpx.Response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str) -> httpx.Response:
        return self._response

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return self._response

    async def aclose(self) -> None:
        return None

    def stream(self, method: str, url: str, headers: dict | None = None, extensions: dict | None = None) -> "_DummyStream":
        return _DummyStream(self._response)


class _DummyStream:
    """Matches the subset of httpx's `client.stream(...)` async-context-manager
    interface _safe_fetch() actually uses (status_code/headers/aiter_bytes) --
    needed once searchlight.py switched from client.get() to client.stream()
    to support manual per-hop redirect re-validation (see that module's
    _safe_fetch docstring)."""

    def __init__(self, response: httpx.Response):
        self._response = response

    async def __aenter__(self) -> httpx.Response:
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def test_block_page_200_is_treated_as_undetermined_not_contradicted(monkeypatch):
    _stub_dns_for_example_com(monkeypatch)
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(
        200,
        request=request,
        text="<html><body><h1>Access Denied</h1><p>Blocked by policy proxy.</p></body></html>",
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    adapter = SearchlightAdapter()
    claim = Claim(
        text="example.com states it is reserved for illustrative examples",
        domain="searchlight",
        context={"url": "https://example.com", "quote": "illustrative examples in documents"},
    )
    ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "block/proxy page" in gap[0]


async def test_non_block_page_without_quote_is_real_contradiction(monkeypatch):
    _stub_dns_for_example_com(monkeypatch)
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(200, request=request, text="<html><body><p>ordinary page text</p></body></html>")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    adapter = SearchlightAdapter()
    claim = Claim(
        text="example.com states it is reserved for illustrative examples",
        domain="searchlight",
        context={"url": "https://example.com", "quote": "illustrative examples in documents"},
    )
    ev = await adapter.gather_evidence(claim)

    assert len(ev) == 1
    assert ev[0].stance == "contradicts"


async def test_tavily_search_returns_no_urls_without_an_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    urls = await research_web_mod._tavily_search("does this need a key", max_results=5)
    assert urls == []


async def test_tavily_search_extracts_and_dedupes_urls_from_a_real_response_shape(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    request = httpx.Request("POST", "https://api.tavily.com/search")
    response = httpx.Response(
        200,
        request=request,
        json={
            "results": [
                {"title": "A", "url": "https://a.example/page"},
                {"title": "B (mirror)", "url": "https://a.example/page"},  # duplicate URL, not a duplicate title
                {"title": "C", "url": "https://c.example/page"},
            ]
        },
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    urls = await research_web_mod._tavily_search("some query", max_results=5)

    assert urls == ["https://a.example/page", "https://c.example/page"]


async def test_tavily_search_non_200_response_is_treated_as_no_results_not_a_crash(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    request = httpx.Request("POST", "https://api.tavily.com/search")
    response = httpx.Response(500, request=request, text="internal error")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _DummyAsyncClient(response))

    urls = await research_web_mod._tavily_search("some query", max_results=5)

    assert urls == []


async def test_search_candidate_urls_falls_back_to_ddg_and_wikipedia_when_tavily_finds_nothing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)  # Tavily contributes [] -- fallback path should still run

    async def _fake_ddg(query, max_results):
        return ["https://ddg.example/hit"]

    async def _fake_wiki(query, max_results):
        return ["https://en.wikipedia.org/wiki/Hit"]

    monkeypatch.setattr(research_web_mod, "_ddg_search", _fake_ddg)
    monkeypatch.setattr(research_web_mod, "_wikipedia_search", _fake_wiki)

    urls = await research_web_mod._search_candidate_urls("some query")

    assert urls == ["https://ddg.example/hit", "https://en.wikipedia.org/wiki/Hit"]


async def test_search_candidate_urls_does_not_fall_back_when_tavily_succeeds(monkeypatch):
    async def _fake_tavily(query, max_results):
        return ["https://tavily.example/hit"]

    async def _fail_if_called(query, max_results):
        raise AssertionError("fallback backend called even though Tavily already returned results")

    monkeypatch.setattr(research_web_mod, "_tavily_search", _fake_tavily)
    monkeypatch.setattr(research_web_mod, "_ddg_search", _fail_if_called)
    monkeypatch.setattr(research_web_mod, "_wikipedia_search", _fail_if_called)

    urls = await research_web_mod._search_candidate_urls("some query")

    assert urls == ["https://tavily.example/hit"]


async def test_concurrent_requests_on_one_shared_adapter_instance_do_not_leak_gap_state(monkeypatch):
    """Regression guard for the ContextVar fix (see the "HONEST SCOPE NOTE"
    next to _fetch_error_var's definition for the precise, checked claim:
    today's exact code already wrote its own gap value immediately before
    every empty-evidence return, so this specific interleaving didn't
    provably leak even under the OLD self-based design -- the fix is a
    real robustness improvement for FUTURE code changes, not a proven
    currently-firing exploit). This test proves the CURRENT behavior is
    correct with REAL concurrent asyncio Tasks (the same mechanism FastAPI
    uses to isolate concurrent requests) sharing ONE adapter instance,
    exactly like default_domains() builds."""
    b_is_done = asyncio.Event()

    async def fake_safe_fetch(url: str, *, headers=None, block_private_networks=True):
        if url == "https://a.example/":
            await b_is_done.wait()  # A's fetch doesn't resolve until B has fully finished
            raise httpx.HTTPError("A's own distinct network failure")
        if url == "https://b.example/":
            raise httpx.HTTPError("B's own distinct network failure")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(research_web_mod, "_safe_fetch", fake_safe_fetch)

    adapter = SearchlightAdapter()  # ONE shared instance, like default_domains() builds
    claim_a = Claim(text="a", domain="searchlight", context={"url": "https://a.example/", "quote": "x"})
    claim_b = Claim(text="b", domain="searchlight", context={"url": "https://b.example/", "quote": "x"})

    async def run_a():
        ev = await adapter.gather_evidence(claim_a)
        return adapter.describe_gap(claim_a, ev)

    async def run_b():
        ev = await adapter.gather_evidence(claim_b)
        gap = adapter.describe_gap(claim_b, ev)
        b_is_done.set()  # unblocks A's fetch -- B is now fully done, including its own describe_gap read
        return gap

    gap_a, gap_b = await asyncio.gather(run_a(), run_b())

    assert "A's own distinct network failure" in gap_a[0]
    assert "B's own distinct network failure" in gap_b[0]


class _NetworkCallAttempted(AssertionError):
    """Raised if anything tries to actually open a connection -- used below to
    prove the SSRF guard rejects an unsafe URL BEFORE any network call, not
    just eventually via a failed fetch."""


def _forbid_network_calls(monkeypatch) -> None:
    """Patches the actual request-issuing method, not just AsyncClient's
    constructor -- _safe_fetch() legitimately constructs a client lazily
    AFTER confirming the first hop is safe, so asserting "no client was ever
    constructed" would be the wrong (too strict, implementation-specific)
    claim; asserting "no request was ever issued" is the real property that
    matters and stays true regardless of internal client-construction timing."""

    def _raise(*_args, **_kwargs):
        raise _NetworkCallAttempted("httpx.AsyncClient.stream was called -- the SSRF guard did not short-circuit first.")

    monkeypatch.setattr(httpx.AsyncClient, "stream", _raise)


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint (link-local)
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",  # RFC1918 private range
    ],
)
async def test_ssrf_guard_rejects_unsafe_url_before_any_network_call_mode1(monkeypatch, unsafe_url):
    """FOUND BUG (external security review): searchlight.py fetched ANY url
    handed to it in Claim.context with zero validation -- SSRF. Fixed via
    _is_safe_to_fetch(). This proves the fix for mode 1 (ctx["url"], fully
    caller-supplied) and proves the rejection happens BEFORE any network
    call is attempted, not just that the eventual fetch fails."""
    _forbid_network_calls(monkeypatch)
    adapter = SearchlightAdapter()
    claim = Claim(
        text="x", domain="searchlight",
        context={"url": unsafe_url, "quote": "anything"},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "refused to fetch" in gap[0].lower()


async def test_ssrf_guard_rejects_unsafe_url_before_any_network_call_mode2(monkeypatch):
    """Same guard, mode 2 (multi-candidate): a search backend that returns an
    internal URL as a "candidate" must not get it fetched either -- the
    guard applies uniformly, not just to the directly caller-supplied url."""
    _forbid_network_calls(monkeypatch)

    async def fake_search(_query: str, _max: int) -> list[str]:
        return ["http://169.254.169.254/latest/meta-data/"]

    adapter = SearchlightAdapter(search=fake_search)
    claim = Claim(text="some claim with no url in context", domain="searchlight")
    ev = await adapter.gather_evidence(claim)
    assert ev == []


async def test_dns_rebinding_cannot_retarget_the_actual_connection(monkeypatch):
    """FOUND BUG (external review): _is_safe_to_fetch() used to validate the
    hostname, then _safe_fetch() fetched the ORIGINAL hostname-based URL --
    httpx resolves that hostname a SECOND time, independently, when it
    actually opens the connection. A hostile authoritative DNS server can
    answer the validation lookup with a public IP and the later connect-time
    lookup with a private one; the two lookups aren't guaranteed to agree.

    Proves the fix by checking the ACTUAL target httpx.AsyncClient.stream()
    is called with: it must be the literal, already-validated IP, never the
    hostname -- a literal IP can't be re-resolved to something else, which
    is what actually closes the window (not just "we checked the hostname
    once", which the old code already did and was still vulnerable)."""
    real_getaddrinfo = asyncio.base_events.BaseEventLoop.getaddrinfo
    call_count = {"n": 0}

    async def fake_getaddrinfo(self, host, port, *args, **kwargs):
        if host == "rebinding-target.example":
            call_count["n"] += 1
            # Always answers with the SAME real, public IP -- if _safe_fetch()
            # ever asked a SECOND time (i.e. let httpx resolve the hostname
            # again at connect time instead of connecting to the pinned IP
            # directly), this fake would have no way to simulate "answers
            # differently the second time" from inside httpx's own internals,
            # so the only way to PROVE no second resolution happens at all is
            # to check what URL was actually handed to the transport -- see
            # the assertion below, not this counter (kept only as a secondary
            # sanity signal that the FIRST, legitimate lookup still happens).
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return await real_getaddrinfo(self, host, port, *args, **kwargs)

    monkeypatch.setattr(asyncio.base_events.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)

    captured_urls = []

    class _FakeStream:
        def __init__(self, response):
            self._response = response

        async def __aenter__(self):
            return self._response

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_stream(self, method, url, headers=None, extensions=None):
        captured_urls.append((str(url), headers, extensions))
        request = httpx.Request(method, url)
        return _FakeStream(httpx.Response(200, text="no quote here", request=request))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)

    adapter = SearchlightAdapter()
    claim = Claim(
        text="x", domain="searchlight",
        context={"url": "https://rebinding-target.example/page", "quote": "irrelevant"},
    )
    await adapter.gather_evidence(claim)

    assert call_count["n"] == 1  # the one legitimate validation lookup happened
    assert len(captured_urls) == 1
    actual_url, actual_headers, actual_extensions = captured_urls[0]
    # The real connection target is the literal IP -- NOT the hostname. A
    # literal IP cannot be "re-resolved" to anything else, which is what
    # actually closes the rebinding window (checking the hostname once,
    # the OLD code's approach, is not enough on its own).
    assert "93.184.216.34" in actual_url
    assert "rebinding-target.example" not in actual_url
    # Host header and SNI are explicitly preserved so the request still
    # reaches the right virtual host and the TLS certificate check is
    # against the real hostname, not the raw IP.
    assert actual_headers.get("Host") == "rebinding-target.example"
    assert actual_extensions.get("sni_hostname") == "rebinding-target.example"


async def test_ssrf_guard_catches_a_redirect_to_an_unsafe_address_not_just_the_original_url(monkeypatch):
    """FOUND BUG (follow-up security review): the first version of this guard
    checked only the ORIGINAL url, then fetched with follow_redirects=True --
    a url that passes the check could still 302-redirect straight to an
    internal address with no second check. Simulates exactly that: a public-
    looking first hop (passes _is_safe_to_fetch) that 302s to the cloud
    metadata endpoint. Must be rejected at the redirect hop, not followed."""
    _stub_dns_for_example_com(monkeypatch)
    call_count = {"n": 0}

    class _RedirectOnceStream:
        def __init__(self, response: httpx.Response):
            self._response = response

        async def __aenter__(self) -> httpx.Response:
            return self._response

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _fake_stream(self, method, url, headers=None, extensions=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # A real, legitimate-looking first hop -- passes _is_safe_to_fetch
            # (example.com is a real public address) -- then redirects.
            resp = httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
                request=httpx.Request(method, url),
            )
            return _RedirectOnceStream(resp)
        raise AssertionError("the redirect target was followed without being re-checked -- SSRF-via-redirect bypass")

    monkeypatch.setattr(httpx.AsyncClient, "stream", _fake_stream)

    adapter = SearchlightAdapter()
    claim = Claim(
        text="x", domain="searchlight",
        context={"url": "https://example.com/looks-fine", "quote": "anything"},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "refused to fetch" in gap[0].lower()
    assert call_count["n"] == 1  # the redirect target was checked and rejected, never fetched


async def test_safe_fetch_caps_response_body_at_the_documented_limit(monkeypatch):
    """FOUND BUG (follow-up security review): resp.text loaded the entire
    response body into memory with no cap -- an oversized (or malicious)
    response could exhaust server memory. _safe_fetch() now streams and
    stops at _MAX_RESPONSE_BYTES; proves it actually truncates, not just
    that the constant exists."""
    _stub_dns_for_example_com(monkeypatch)
    oversized = b"x" * (_MAX_RESPONSE_BYTES + 1000)

    class _OversizedStream:
        status_code = 200
        headers = httpx.Headers({"content-type": "text/plain"})
        request = httpx.Request("GET", "https://example.com/huge")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_bytes(self):
            # Yield in chunks, like a real streamed response would.
            chunk_size = 64 * 1024
            for i in range(0, len(oversized), chunk_size):
                yield oversized[i : i + chunk_size]

    monkeypatch.setattr(httpx.AsyncClient, "stream", lambda self, method, url, headers=None, extensions=None: _OversizedStream())

    resp = await _safe_fetch("https://example.com/huge")
    assert len(resp.content) == _MAX_RESPONSE_BYTES
    assert resp.extensions["truncated"] is True


async def test_malformed_redirect_location_header_is_a_clean_refusal_not_a_crash(monkeypatch):
    """FOUND BUG (follow-up security review): a malformed Location header
    (e.g. "http://[::1") makes httpx.URL.join() raise httpx.InvalidURL,
    which on httpx 0.28.1 is NOT a subclass of httpx.HTTPError -- neither
    caller catches it, so this was an unhandled 500 instead of a clean
    refusal. _safe_fetch() now wraps the .join() call and converts the
    failure into _FetchRefused."""
    _stub_dns_for_example_com(monkeypatch)
    call_count = {"n": 0}

    class _MalformedRedirectStream:
        def __init__(self, response: httpx.Response):
            self._response = response

        async def __aenter__(self) -> httpx.Response:
            return self._response

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _fake_stream(self, method, url, headers=None, extensions=None):
        call_count["n"] += 1
        resp = httpx.Response(
            302, headers={"Location": "http://[::1"}, request=httpx.Request(method, url)
        )
        return _MalformedRedirectStream(resp)

    monkeypatch.setattr(httpx.AsyncClient, "stream", _fake_stream)

    adapter = SearchlightAdapter()
    claim = Claim(
        text="x", domain="searchlight",
        context={"url": "https://example.com/redirects-badly", "quote": "anything"},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "invalid" in gap[0].lower() and "location" in gap[0].lower()
    assert call_count["n"] == 1  # never attempted to actually follow the malformed redirect


async def test_truncated_page_without_the_quote_is_undetermined_not_a_false_contradiction(monkeypatch):
    """FOUND BUG (follow-up security review): a page cut at _MAX_RESPONSE_BYTES
    whose quote falls past the cut used to read as "not found" -> a
    confident CONTRADICTS, even though the quote might genuinely be present
    just past the truncation point. Must be UNDETERMINED (a named gap)
    instead -- a truncated page proves nothing about what it doesn't show."""
    _stub_dns_for_example_com(monkeypatch)
    quote = "the reference pump is rated for 12 bar"
    # Real body: lots of filler, cut by _MAX_RESPONSE_BYTES, THEN the quote --
    # so the quote genuinely exists on the real page but falls past the cut.
    body = ("filler " * (_MAX_RESPONSE_BYTES // 7 + 10)).encode()[: _MAX_RESPONSE_BYTES + 5000]
    body += quote.encode()

    class _TruncatedStream:
        status_code = 200
        headers = httpx.Headers({"content-type": "text/plain"})
        request = httpx.Request("GET", "https://example.com/big-page")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_bytes(self):
            chunk_size = 64 * 1024
            for i in range(0, len(body), chunk_size):
                yield body[i : i + chunk_size]

    monkeypatch.setattr(httpx.AsyncClient, "stream", lambda self, method, url, headers=None, extensions=None: _TruncatedStream())

    adapter = SearchlightAdapter()
    claim = Claim(
        text="x", domain="searchlight",
        context={"url": "https://example.com/big-page", "quote": quote},
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == []  # NOT a confident contradicts
    gap = adapter.describe_gap(claim, ev)
    assert "truncated" in gap[0].lower()


async def test_total_timeout_bounds_a_slow_trickling_response(monkeypatch):
    """FOUND BUG (follow-up security review): httpx's own timeout= is a
    PER-READ timeout, not a cap on TOTAL time -- a server trickling bytes
    slowly (each gap individually within the per-read timeout) could hold
    the connection open indefinitely. asyncio.timeout() now bounds the
    WHOLE fetch; proves a trickling response that would otherwise take far
    longer than the configured total timeout is cut off close to it,
    not after all the data eventually arrives."""
    import time

    _stub_dns_for_example_com(monkeypatch)

    class _SlowTrickleStream:
        status_code = 200
        headers = httpx.Headers({"content-type": "text/plain"})
        request = httpx.Request("GET", "https://example.com/slow")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_bytes(self):
            for _ in range(100):  # would take ~5s total if never cut off
                await asyncio.sleep(0.05)
                yield b"x"

    monkeypatch.setattr(httpx.AsyncClient, "stream", lambda self, method, url, headers=None, extensions=None: _SlowTrickleStream())

    start = time.monotonic()
    with pytest.raises(httpx.ReadTimeout):
        await _safe_fetch("https://example.com/slow", timeout=0.3)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0  # cut off near the 0.3s budget, not after the full ~5s


# --- mode 2: multi-candidate live search, tested offline via a fake search provider
# that points at the real local fixture server (same fixtures/web/ pages mode 1 uses)
# plus a scripted fake LLM client, so the REAL propose()->verify_proposal() pipeline
# runs over a real local HTTP fetch without any network/live-key dependency. ---


class _FakeClient:
    """Test double for NebiusTokenFactoryClient covering BOTH prompt shapes this
    adapter sends: a propose() JSON-extraction prompt (starts "Question: ") and a
    _judge_stance() one-word prompt (starts "CLAIM: ").

    `propose_response` is the default answer for any propose() prompt.
    `propose_by_marker`, if given, picks a DIFFERENT answer per source when the
    prompt contains a given substring (e.g. a chunk_id prefix unique to one
    fetched page) — needed for tests with more than one distinct source."""

    def __init__(
        self,
        propose_response: str | Exception = "",
        stance_response: str = "supports",
        propose_by_marker: dict[str, str | Exception] | None = None,
    ):
        self._propose_response = propose_response
        self._stance_response = stance_response
        self._propose_by_marker = propose_by_marker or {}

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        if prompt.startswith("CLAIM:"):
            return self._stance_response
        for marker, response in self._propose_by_marker.items():
            if marker in prompt:
                if isinstance(response, Exception):
                    raise response
                return response
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
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
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
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        claim = Claim(text="the reference pump is rated for 9999 bar", domain="searchlight")
        ev = await adapter.gather_evidence(claim)

    assert len(ev) == 1
    assert ev[0].stance == "contradicts"


async def test_multi_candidate_no_candidates_found_is_a_named_gap():
    async def fake_search(_query: str, _max: int) -> list[str]:
        return []

    adapter = SearchlightAdapter(client=_FakeClient(_NOT_FOUND_JSON), search=fake_search, block_private_networks=False)
    claim = Claim(text="some claim no search backend will find anything for", domain="searchlight")
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

        adapter = SearchlightAdapter(client=_FakeClient(_NOT_FOUND_JSON), search=fake_search, block_private_networks=False)
        claim = Claim(text="the reference pump has a maximum operating pressure of 12 bar", domain="searchlight")
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
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        ev = await adapter.gather_evidence(claim)

    assert ev == [], "a quote that does not exist in the real fetched page must never become Evidence"


async def test_multi_candidate_missing_key_is_a_named_gap_not_a_crash(monkeypatch):
    """NEBIUS_API_KEY missing entirely must surface as a specific, honest gap —
    reached only after a real fetch + real BM25 match, so this exercises the
    client-missing branch for real, not in isolation."""
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    # See the identical note in test_domains_substrate.py's version of this
    # test: nebius_client.py caches .env in a local dict at import time now,
    # so delenv() alone no longer simulates "no key anywhere" -- this
    # project's own real .env still has one cached.
    monkeypatch.setitem(nebius_client_mod._DOTENV_VALUES, "NEBIUS_API_KEY", None)

    with serve_fixtures() as base_url:

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        adapter = SearchlightAdapter(search=fake_search, block_private_networks=False)  # no client injected, no key in env
        claim = Claim(
            text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight"
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
        adapter = SearchlightAdapter(client=_FakeClient(failing), search=fake_search, block_private_networks=False)
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "propose call failed" in gap[0]
    assert "401" in gap[0]


async def test_multi_candidate_malformed_json_response_is_a_named_gap_not_a_crash():
    """FOUND BUG (Nemotron pivot pilot runs, see
    stress_test/results/NEMOTRON_PIVOT_REPORT.md): a live Nemotron Ultra call
    against a real Wikipedia candidate returned a `quote` field containing a
    huge, malformed raw-wikitext dump that broke extract.py's JSON parsing --
    the resulting ValueError propagated uncaught out of gather_evidence() in
    the pilot harness instead of becoming a named "propose call failed" gap
    like every other live-call failure already does. Fixed by adding
    ValueError to this adapter's propose-call except clause too (searchlight.py
    has its own, separate from substrate.py's) -- reproduces the failure shape
    directly here, without a live call."""
    with serve_fixtures() as base_url:

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        not_json = "this is not valid json at all {broken"
        adapter = SearchlightAdapter(client=_FakeClient(not_json), search=fake_search, block_private_networks=False)
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "propose call failed" in gap[0]


# --- live tests: require a real, working NEBIUS_API_KEY and real network access.
# Skipped (not run) when the var is entirely unset; FAIL for real (not skip) if the
# var is set but something's actually broken — same policy as substrate.py's live
# tests, same reasoning: a configured-but-broken key/search/model is a fact worth
# surfacing, not hiding. Each outcome below was independently confirmed live,
# repeatedly, before being written down here — see searchlight.py's module
# docstring and evals/cases/searchlight/live_multi_candidate_*.json. ---

_requires_live_key = pytest.mark.skipif(
    not os.environ.get("NEBIUS_API_KEY"), reason="requires a real, working NEBIUS_API_KEY"
)


@_requires_live_key
async def test_live_multi_candidate_confirmed_from_a_real_wikipedia_article():
    adapter = SearchlightAdapter()
    claim = Claim(
        text="BlueROV2 is a modular remotely operated underwater vehicle developed by Blue Robotics",
        domain="searchlight",
    )
    ev = await adapter.gather_evidence(claim)
    assert ev, f"expected real confirmed evidence; gap: {getattr(adapter, '_last_web_gap', None)}"
    assert ev[0].stance == "supports"
    assert ev[0].source == "https://en.wikipedia.org/wiki/BlueROV2"


@_requires_live_key
async def test_live_multi_candidate_contradicted_by_a_real_wikipedia_article():
    adapter = SearchlightAdapter()
    claim = Claim(text="BlueROV2 was developed by OpenROV", domain="searchlight")
    ev = await adapter.gather_evidence(claim)
    assert ev, f"expected real contradicting evidence; gap: {getattr(adapter, '_last_web_gap', None)}"
    assert ev[0].stance == "contradicts"


@_requires_live_key
async def test_live_multi_candidate_undetermined_when_no_real_source_settles_it():
    """A specific, plausible-sounding, fabricated-style number that no real
    source actually states — must stay UNDETERMINED, never a guessed CONFIRMED,
    regardless of which specific honest-gap shape it lands in.

    UPDATED this session: with Tavily wired in as the primary search backend
    (replacing keyless DDG+Wikipedia, which found NOTHING for this query —
    the original reason this test asserted the "no live candidate pages
    found" gap specifically), Tavily now genuinely finds real candidate
    pages (real Blue Robotics forum threads) for this query. The model
    still, correctly, reports the MTBF figure isn't stated in any of them —
    a DIFFERENT honest-gap shape (candidates found, but none confirm) from
    before, not a regression: ev == [] either way is the property that
    actually matters, and is unchanged."""
    adapter = SearchlightAdapter()
    claim = Claim(
        text="Blue Robotics Bar30 pressure sensor has a mean time between failures of 50000 hours",
        domain="searchlight",
    )
    ev = await adapter.gather_evidence(claim)
    assert ev == [], f"expected no evidence (honest gap), got: {ev}"
    gap = adapter.describe_gap(claim, ev)
    # Reworded 2026-10-26 (comparative-synthesis fix, round 2 category-1
    # investigation): phrased as "not yet resolved" rather than "no
    # evidence exists" -- real sources were checked and read, the honest
    # state is "not conclusively resolved from what they say", not
    # "nothing is known about this at all". See stance.py's own module
    # comment and COMPARATIVE_SYNTHESIS_FIX_NOTE.md for the full reasoning.
    assert (
        "no live candidate pages found" in gap[0].lower()
        or "none produced usable evidence" in gap[0].lower()
        or "hasn't been conclusively resolved" in gap[0].lower()
    ), gap


# --- near-duplicate evidence guard: two near-identical sources (a mirror, or a
# page that copy-pasted the same sentence) must not both count as independent
# confirmation; two genuinely different sources confirming the same real-world
# fact must still both count, since that's real corroboration, not redundancy. ---


def test_is_near_duplicate_evidence_true_for_near_identical_quotes():
    a = Evidence(source="https://mirror-a.example/page", snippet=_FIXTURE_QUOTE, stance="supports", trust=0.75)
    b = Evidence(source="https://mirror-b.example/page", snippet=_FIXTURE_QUOTE, stance="supports", trust=0.75)
    assert _is_near_duplicate_evidence(a, b)


def test_is_near_duplicate_evidence_false_for_genuinely_different_quotes():
    a = Evidence(source="https://site-a.example/page", snippet=_FIXTURE_QUOTE, stance="supports", trust=0.75)
    b = Evidence(
        source="https://site-b.example/page",
        snippet="An independent test report confirmed the reference pump operates safely up to 12 bar without failure.",
        stance="supports",
        trust=0.75,
    )
    assert not _is_near_duplicate_evidence(a, b)


def test_is_near_duplicate_evidence_false_for_empty_text():
    a = Evidence(source="https://a.example", snippet="", stance="supports", trust=0.75)
    b = Evidence(source="https://b.example", snippet="", stance="supports", trust=0.75)
    assert not _is_near_duplicate_evidence(a, b)


async def test_multi_candidate_mirror_sources_count_as_one_not_two():
    """PROVES the fix matters: two different URLs serving byte-identical content
    (a mirror site, simulated here via a harmless query-string variant of the
    same real fixture page) must resolve to exactly ONE piece of Evidence, not
    two — engine.py's trust-weighted sum must not see this as double the real
    confirmation it actually has."""
    with serve_fixtures() as base_url:
        url_a = f"{base_url}/stable_page.html?mirror=1"
        url_b = f"{base_url}/stable_page.html?mirror=2"

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [url_a, url_b]

        client = _FakeClient(
            propose_by_marker={
                f"{url_a}#0": _found_json(f"{url_a}#0", _FIXTURE_QUOTE),
                f"{url_b}#0": _found_json(f"{url_b}#0", _FIXTURE_QUOTE),
            }
        )
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        claim = Claim(
            text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight"
        )
        ev = await adapter.gather_evidence(claim)

    assert len(ev) == 1, f"two near-identical mirror sources must count as ONE confirmation, got {len(ev)}"
    assert ev[0].stance == "supports"


async def test_multi_candidate_genuinely_different_sources_both_count():
    """Negative case for the same fix: two sources that are REALLY different
    text (different fixture pages, independently worded) confirming the same
    underlying fact must both be kept — that's real independent corroboration,
    which the near-duplicate guard must not throw away."""
    with serve_fixtures() as base_url:
        url_a = f"{base_url}/stable_page.html"
        url_b = f"{base_url}/stable_page_rephrased.html"
        rephrased_quote = "An independent test report confirmed the reference pump operates safely up to 12 bar without failure."

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [url_a, url_b]

        client = _FakeClient(
            propose_by_marker={
                f"{url_a}#0": _found_json(f"{url_a}#0", _FIXTURE_QUOTE),
                f"{url_b}#0": _found_json(f"{url_b}#0", rephrased_quote),
            }
        )
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        claim = Claim(
            text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight"
        )
        ev = await adapter.gather_evidence(claim)

    assert len(ev) == 2, f"two genuinely different confirming sources should BOTH count, got {len(ev)}"
    assert {e.source for e in ev} == {url_a, url_b}
    assert all(e.stance == "supports" for e in ev)
