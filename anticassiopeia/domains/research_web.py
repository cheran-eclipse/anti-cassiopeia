"""
Web / research-paper domain adapter — existence/verification POV.

TWO modes, selected by `Claim.context`:

1. Single-page check (`context = {"url": str, "quote": str}`, UNCHANGED from
   before): fetches that one URL for real and checks whether the quote
   appears verbatim (modulo whitespace) anywhere in the page. This is the
   original, simpler mechanism — kept exactly as it was so the existing
   fixture-based evals/tests (which always pass an explicit "url") stay
   stable and deterministic. "Not found" resolves to `contradicts` here, a
   simplification inherited unchanged from the original design.

2. Multi-candidate live research (`context` has NO "url" — just a claim,
   optionally with "quote" for a more specific search anchor): finds out
   whether ANY real source confirms the claim, not one pre-selected page.
   Runs the SAME real retrieve->propose->verify pipeline robotics.py uses:
       _search_candidate_urls() -> chunk_document() -> BM25Index.search()
       -> extract.propose() -> verify.verify_proposal()
   Chunks from ALL successfully fetched candidate pages are pooled into one
   combined BM25 index (there's no "the right doc" to pick ahead of time
   here, unlike robotics' per-part corpus), but the resulting hits are then
   GROUPED BY SOURCE PAGE — propose()/verify()/_judge_stance() run once per
   distinct source (up to `_MAX_SOURCES_TO_CHECK`), so a claim can collect
   independent Evidence from SEVERAL real sources, not just the single
   best-ranked chunk. This is what makes "multi-candidate" actually mean
   checking multiple candidates, not just picking one and discarding the
   rest. Three-way outcome per source, genuinely distinguished (an
   improvement over mode 1's found/not-found binary):
     - CONFIRMED-worthy ("supports"): a real, independently-verified quote
       from a real fetched page actually matches what the claim says.
     - CONTRADICTED-worthy ("contradicts"): a real, verified quote was
       found addressing the same question, but states something different
       from the claim — same subject, conflicting content, mirroring how
       robotics.py treats two disagreeing sourced facts.
     - UNDETERMINED, with a SPECIFIC named reason: no live candidate pages
       found at all; all candidates failed to fetch; nothing retrieved
       matched the claim's terms; or the model honestly reported the fact
       isn't stated in what it was shown. Never collapsed into a guess.

   NEAR-DUPLICATE GUARD: checking several real sources means two of them
   can be the same source in disguise — a mirror site, or a page that
   copy-pasted the same sentence. Before being added to the final list,
   each newly-accepted Evidence is checked with `_is_near_duplicate_evidence()`
   against every Evidence already accepted FOR THIS CLAIM; a near-verbatim
   match (Jaccard token overlap >= 0.8 — see that function for why that
   threshold, not a lower one) is dropped as not-independent rather than
   counted as a second confirmation. core/engine.py's trust-weighted sum has
   no way to know two Evidence items came from the same underlying source
   text, so this has to happen here, before the list ever reaches it —
   engine.py itself is untouched.

   Candidate discovery (`_search_candidate_urls`) is real and live.
   PRIMARY backend, as of this session: Tavily's `/search` API (needs
   `TAVILY_API_KEY` in `.env` — see `.env.example`), a real keyed search
   API built for this exact use case (LLM-facing retrieval), not a
   scraped HTML results page. FALLBACK, tried only when Tavily returns
   zero URLs (missing key, a live Tavily failure, or a genuine
   zero-result query) — kept exactly as before, still keyless so cloning
   this repo without a Tavily key still gets *some* real coverage:
     - DuckDuckGo's HTML results page (broad coverage when it works).
       CONFIRMED UNRELIABLE from this project's own dev sandbox: every
       attempt returned an HTTP 202 anti-bot "anomaly" challenge page
       instead of real results — a known failure mode of IP-based
       scraping from datacenter/CI/cloud networks, not specific to this
       repo. Tried anyway (best-effort; harmless if it contributes zero
       candidates) because it's real coverage when it isn't blocked.
     - Wikipedia's public search API. CONFIRMED WORKING, live, with a
       proper descriptive User-Agent (Wikipedia's API returns 403 without
       one — not a bug, their documented robots policy). Reliable but
       narrow: only finds candidates for topics with Wikipedia coverage.
   If Tavily AND both fallback backends return nothing, that's an honest
   "no live candidates" gap — not a crash, not a silent zero-evidence shrug.

   Stance (supports/contradicts) for mode 2 is decided by `_judge_stance()`,
   a BOUNDED LLM judgment call on a quote that's ALREADY been independently,
   mechanically confirmed to exist verbatim on a real page — this never runs
   on an unverified claim, so it isn't a new source of fabrication risk.
   Two purely mechanical alternatives were tried FIRST and both failed on
   real live tests: a strict substring check broke on real paraphrasing
   (a true claim's confirming sentence had extra clauses that broke
   containment); a token-overlap ratio broke the other way (a FALSE claim
   scored "supports" because common words dominated the ratio while the one
   word that actually mattered was noise). See `_judge_stance()`'s own
   comment for both failures in detail — they're why this ended up as a
   bounded model judgment instead of a formula.

The HTML-to-text extraction (`_strip_html`) is a plain regex tag-stripper,
not a real HTML parser — it will mis-handle `<script>`/`<style>` content
and JS-rendered pages; good enough for a static page's body text, not a
guarantee. Unchanged from before.

STATUS: mode 1 real, network-dependent, unchanged. Mode 2 real and
LIVE-VERIFIED end to end against real Wikipedia pages (see
tests/test_domains_research_web.py's live-gated tests and
evals/cases/research_web/live_multi_candidate_*.json) — a real CONFIRMED,
a real CONTRADICTED, and two differently-shaped real UNDETERMINED
outcomes (no candidates found at all vs. candidates found but the fact
genuinely absent from them) were each independently confirmed live before
being written down as eval cases, not assumed. Multi-source evidence
gathering and the near-duplicate guard are tested offline and
deterministically (`test_multi_candidate_mirror_sources_count_as_one_not_two`,
`test_multi_candidate_genuinely_different_sources_both_count`) against two
real local fixture pages — one byte-identical "mirror", one genuinely
independently-worded — proving the dedup actually changes the outcome in
the case it exists for, and does NOT wrongly collapse real corroboration.

SSRF GUARD (found during external security review, verified against the
real code): both fetch call sites (mode 1's `ctx["url"]`, fully
caller-supplied from a POST /verify body; mode 2's search-discovered
candidate URLs) previously fetched ANY url with zero validation. Fixed:
`_is_safe_to_fetch()` resolves the hostname and rejects it (fail closed
on resolution failure too) unless EVERY resolved address is
`ip.is_global` (not an enumerated blocklist — see that function's own
comment for why an earlier enumerated version missed carrier-grade NAT,
100.64.0.0/10) — this catches cloud metadata endpoints
(169.254.169.254), RFC1918 ranges, and localhost (checked on the REAL
resolved IP, not just the literal hostname string, which also rejects a
DNS name that merely *looks* external but resolves internally). On by
default (`block_private_networks=True`); only this project's own test
suite, which legitimately fetches its local fixture server on
127.0.0.1 (see `evals/fixture_server.py`), passes
`block_private_networks=False` explicitly — `default_domains()` never
disables it.

SSRF-VIA-REDIRECT, found and fixed in a follow-up review pass: the first
version of this guard checked only the ORIGINAL url, then fetched with
`httpx`'s own `follow_redirects=True` — a url that passes the check but
then 30x-redirects to a private address would have that redirect
followed with no second check, a known real bypass pattern, not a
hypothetical one. Fixed by `_safe_fetch()`: `follow_redirects=False`,
manually walking the redirect chain and re-running `_is_safe_to_fetch()`
on EVERY hop (the original url AND every `Location` header) before
following it, up to `_MAX_REDIRECTS` hops. The same function also caps
the final response body at `_MAX_RESPONSE_BYTES` by streaming instead of
loading the whole thing via `resp.text` — an unbounded fetch is its own,
separate resource-exhaustion risk.

KNOWN, ACCEPTED GAP — DNS REBINDING, not fixed: `_is_safe_to_fetch()`
resolves the hostname once to decide safety, then `httpx` resolves the
SAME hostname AGAIN (independently) to actually open the connection. A
DNS-rebinding attack controls authoritative DNS for its own domain and
can answer the first resolution with a public IP (passes the check) and
the second, moments later, with an internal one (what's actually
connected to) — the two lookups aren't guaranteed to agree. The real fix
is to resolve once and connect directly to that validated IP (bypassing
httpx's own resolution entirely, e.g. via a custom transport), which is
substantially more invasive to httpx's normal request flow than this
pass's fixes; deliberately not attempted here, stated plainly as an
accepted residual risk rather than left undocumented or silently
"handled" by the single-resolution check above.
"""

from __future__ import annotations

import asyncio
import html as html_module
import ipaddress
import os
import re
import socket
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import replace

import httpx

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence
from anticassiopeia.llm.nebius_client import NebiusClientError, NebiusTokenFactoryClient
from anticassiopeia.retrieval import BM25Index, Chunk, ScoredChunk, chunk_document, verify_proposal
from anticassiopeia.retrieval.bm25 import tokenize
from anticassiopeia.retrieval.extract import propose

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_FETCH_TIMEOUT = 15.0
#: Max redirect hops _safe_fetch() will follow, re-checking _is_safe_to_fetch()
#: on EVERY hop -- see _safe_fetch()'s own docstring for why httpx's own
#: follow_redirects=True can't be used here.
_MAX_REDIRECTS = 3
#: Hard cap on a single fetched response body, enforced by streaming instead
#: of loading the whole thing via resp.text -- an attacker-controlled (or
#: just unexpectedly huge) page could otherwise exhaust server memory. 5 MiB
#: is generously larger than any real article/datasheet page this adapter
#: needs the text of; a legitimate page this adapter cares about is prose.
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
#: How many distinct source pages to actually run propose()/verify/judge_stance
#: against, out of however many matched the pooled BM25 search. Bounded so a
#: claim that matches many candidates doesn't trigger an unbounded number of
#: live LLM calls — 3 is enough to demonstrate real multi-source corroboration
#: (the point of this mode) without multiplying live-call cost much past the
#: original single-source design.
_MAX_SOURCES_TO_CHECK = 3
_BLOCK_PAGE_MARKERS = (
    "access denied",
    "request blocked",
    "forbidden",
    "blocked by policy",
    "security policy",
    "web filter",
    "proxy",
    "zscaler",
)

# Identifies this tool honestly to the services it queries, per Wikipedia's own
# robots policy (https://w.wiki/4wJS) — not a browser-spoof. A generic
# browser-looking UA is what got the DDG attempts anti-bot-challenged in the
# first place; this at least behaves correctly where that's respected.
_SEARCH_USER_AGENT = (
    "AntiCassiopeiaResearchBot/1.0 "
    "(https://github.com/cheran-eclipse/anti-cassiopeia; research-verification tool)"
)
_DDG_RESULT_LINK_RE = re.compile(r'class="result__a"[^>]+href="([^"]+)"')
_DDG_REDIRECT_RE = re.compile(r"(?:^|//)duckduckgo\.com/l/\?uddg=([^&]+)")

_TAVILY_ENDPOINT = "https://api.tavily.com/search"


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def _strip_html(html: str) -> str:
    # Deliberately crude — see module docstring. Good enough to check whether a
    # quote appears in a static page's visible text, not a real renderer.
    no_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    return _TAG_RE.sub(" ", no_script)


def _looks_like_block_page(html: str) -> bool:
    text = _normalize(_strip_html(html))
    return any(marker in text for marker in _BLOCK_PAGE_MARKERS)


# FOUND BUG (external security review, verified against the real code): this
# module fetched ANY URL handed to it (ctx["url"] in mode 1, verbatim from a
# POST /verify body) with zero validation -- SSRF, not just a "fetch failed"
# edge case. A claim could point this adapter at the cloud metadata endpoint
# (169.254.169.254), an internal service on a private IP, or localhost, and
# the server would dutifully fetch it and hand the response text back
# through the propose()/verify pipeline.
#
# FIX: resolve the hostname and check EVERY resolved address before any
# network call is made -- checked on the real resolved IP(s), not the
# literal hostname string, so a DNS name that merely LOOKS external but
# resolves to an internal address is still caught. A hostname that fails to
# resolve at all is treated as unsafe (fail closed), not silently allowed
# through.
#
# FOLLOW-UP FIX (second review pass, same date): the FIRST version of this
# check enumerated specific ranges to block (is_private/is_loopback/
# is_link_local/is_multicast/is_reserved/is_unspecified) -- an
# enumerate-what-to-block list, and it was incomplete: 100.64.0.0/10
# (carrier-grade NAT, RFC 6598) passed it, since none of those properties
# cover it. Replaced with `not ip.is_global`, which is strict-by-default
# (block everything NOT affirmatively known-public) rather than
# permissive-by-default -- confirmed against the real stdlib: 100.64.0.1,
# 169.254.169.254, 127.0.0.1, 10.0.0.1, ::1 are all correctly `is_global ==
# False`; 8.8.8.8 is correctly `True`.
_LOCALHOST_NAMES = {"localhost", "localhost.localdomain"}


async def _is_safe_to_fetch(url: str) -> tuple[bool, str | None]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"URL scheme '{parsed.scheme}' is not http/https."
    host = parsed.hostname
    if not host:
        return False, "URL has no hostname."
    if host.lower() in _LOCALHOST_NAMES:
        return False, f"Hostname '{host}' is localhost."

    try:
        loop = asyncio.get_running_loop()
        addrinfo = await loop.getaddrinfo(host, None)
    except (socket.gaierror, OSError) as exc:
        return False, f"Hostname '{host}' could not be resolved ({exc}) -- fail closed, not fetched."

    for *_rest, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            return False, f"Hostname '{host}' resolves to {ip}, which is not a global/public address."
    return True, None


class _FetchRefused(Exception):
    """Raised by _safe_fetch() when the original URL, or any redirect hop,
    fails _is_safe_to_fetch() -- distinct from httpx.HTTPError (an ordinary
    network failure), so callers can tell "we refused to even try" from
    "we tried and the network failed"."""


# FOLLOW-UP FIX (second review pass): the FIRST version of the SSRF guard
# only checked the ORIGINAL url and then fetched with follow_redirects=True
# -- a url that passes the check could still 30x-redirect straight to an
# internal address, and httpx would silently follow it with no second
# check. That's a well-known SSRF-via-redirect bypass, not a hypothetical
# one. FIX: follow_redirects=False, and manually walk the redirect chain
# here, re-running _is_safe_to_fetch() on EVERY hop (the original URL AND
# every Location header) before following it -- up to _MAX_REDIRECTS hops.
#
# Also enforces _MAX_RESPONSE_BYTES on the FINAL (non-redirect) response by
# streaming it rather than loading the whole body via resp.text -- an
# intermediate redirect response's body is irrelevant (only its Location
# header matters) and isn't capped, since 3xx bodies aren't what this
# adapter ever reads.
async def _safe_fetch(
    url: str, *, headers: dict | None = None, timeout: float = _FETCH_TIMEOUT, block_private_networks: bool = True
) -> httpx.Response:
    current = url
    client: httpx.AsyncClient | None = None
    try:
        # FOUND BUG (follow-up security review): httpx's own `timeout=` is a
        # PER-OPERATION timeout (max gap between successive reads), not a cap
        # on TOTAL wall-clock time -- a server trickling one byte just under
        # that interval, repeatedly, could hold the connection open far past
        # `timeout` in aggregate while never triggering httpx's own timeout.
        # asyncio.timeout() bounds the WHOLE fetch (all redirect hops, all
        # streaming reads) by wall clock instead, converted below to
        # httpx.ReadTimeout (already an httpx.HTTPError subclass) so neither
        # caller needs its own except clause for this.
        async with asyncio.timeout(timeout):
            for _hop in range(_MAX_REDIRECTS + 1):
                if block_private_networks:
                    safe, reason = await _is_safe_to_fetch(current)
                    if not safe:
                        raise _FetchRefused(f"Refused to fetch '{current}': {reason}")

                # Client is constructed lazily, only once the FIRST hop is confirmed
                # safe -- a rejected url never causes so much as an AsyncClient to be
                # instantiated, let alone a socket opened (proven by tests that patch
                # AsyncClient.stream and assert it's never called for a rejected url).
                if client is None:
                    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)

                async with client.stream("GET", current, headers=headers) as streamed:
                    if streamed.status_code in (301, 302, 303, 307, 308) and "location" in streamed.headers:
                        # FOUND BUG (follow-up security review): a malformed
                        # Location header (e.g. "http://[::1" or "http://a:b:c/")
                        # makes httpx.URL.join() raise httpx.InvalidURL, which on
                        # httpx 0.28.1 is NOT an httpx.HTTPError subclass -- neither
                        # caller catches it, so this was an unhandled 500, not a
                        # clean refusal.
                        try:
                            current = str(httpx.URL(current).join(streamed.headers["location"]))
                        except httpx.InvalidURL as exc:
                            raise _FetchRefused(
                                f"Redirect from '{current}' has an invalid Location header: {exc}"
                            ) from exc
                        continue

                    # FOUND BUG (follow-up security review): when a fetch is cut at
                    # _MAX_RESPONSE_BYTES, a quote that falls past the cut read as
                    # "not found" -> a confident CONTRADICTS, even though the page
                    # might genuinely have stated it just past the truncation point.
                    # `truncated` is tracked precisely (only true when real data was
                    # actually discarded, not just when the real body happens to
                    # land exactly on the cap) and passed through via `extensions`
                    # so mode 1 (_gather_single_page) can downgrade this to an
                    # honest UNDETERMINED instead of a wrong CONTRADICTS. Mode 2
                    # doesn't have this failure mode at all: it never treats
                    # "quote not found in this chunk" as a contradiction, only as
                    # "no evidence from this chunk" -- a truncated page there just
                    # yields fewer chunks, not a false verdict.
                    chunks = []
                    total = 0
                    truncated = False
                    async for chunk in streamed.aiter_bytes():
                        remaining = _MAX_RESPONSE_BYTES - total
                        if remaining <= 0:
                            truncated = True
                            break
                        if len(chunk) > remaining:
                            truncated = True
                            chunk = chunk[:remaining]
                        chunks.append(chunk)
                        total += len(chunk)
                    # aiter_bytes() already transparently decompresses (gzip/br/deflate) --
                    # the headers copied from `streamed` still say e.g. content-encoding:
                    # gzip, which would make the NEW Response try to decompress the
                    # ALREADY-decompressed bytes a second time (a real zlib error, found
                    # while testing this against a real gzipped Wikipedia response, not a
                    # hypothetical). Strip the headers that describe a transfer/encoding
                    # that no longer applies to the bytes we're handing over.
                    response_headers = httpx.Headers(streamed.headers)
                    for stale_header in ("content-encoding", "content-length", "transfer-encoding"):
                        response_headers.pop(stale_header, None)
                    return httpx.Response(
                        streamed.status_code,
                        headers=response_headers,
                        content=b"".join(chunks),
                        request=streamed.request,
                        extensions={"truncated": truncated},
                    )
            raise _FetchRefused(f"Too many redirects (> {_MAX_REDIRECTS}) starting from '{url}'.")
    except TimeoutError as exc:
        raise httpx.ReadTimeout(f"Fetch of '{url}' exceeded the total timeout of {timeout}s.") from exc
    finally:
        if client is not None:
            await client.aclose()


async def _ddg_search(query: str, max_results: int) -> list[str]:
    """DuckDuckGo HTML results — real, keyless, broad when it isn't blocked.
    See module docstring: confirmed anti-bot-challenged from this dev sandbox.
    Returns [] on anything other than a clean 200 with parseable result links
    — never raises; a search backend being unavailable is not this function's
    failure to report, _search_candidate_urls() merging zero results from it
    is."""
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": _SEARCH_USER_AGENT},
            )
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []

    urls: list[str] = []
    for m in _DDG_RESULT_LINK_RE.finditer(resp.text):
        href = html_module.unescape(m.group(1))
        redirect = _DDG_REDIRECT_RE.search(href)
        if redirect:
            href = urllib.parse.unquote(redirect.group(1))
        if href.startswith("http") and href not in urls:
            urls.append(href)
    return urls[:max_results]


async def _wikipedia_search(query: str, max_results: int) -> list[str]:
    """Wikipedia's public search API — real, keyless, CONFIRMED working live.
    Narrow (Wikipedia-only coverage) but reliable, unlike the DDG attempt
    above. Returns [] (never raises) on any failure, same contract as
    _ddg_search."""
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": max_results,
                },
                headers={"User-Agent": _SEARCH_USER_AGENT},
            )
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    try:
        hits = resp.json()["query"]["search"]
    except (KeyError, ValueError, TypeError):
        return []
    return [
        f"https://en.wikipedia.org/wiki/{urllib.parse.quote(hit['title'].replace(' ', '_'))}"
        for hit in hits
        if isinstance(hit, dict) and "title" in hit
    ][:max_results]


async def _tavily_search(query: str, max_results: int) -> list[str]:
    """Tavily's `/search` API — real, live, keyed (`TAVILY_API_KEY`), a
    search backend actually built for feeding LLM pipelines (unlike DDG's
    HTML results page, which is scraped). Returns [] (never raises) if the
    key isn't set, the call fails, or the response doesn't parse — same
    "a backend being unavailable isn't this function's failure to report"
    contract as `_ddg_search`/`_wikipedia_search`; `_search_candidate_urls`
    below is what decides what happens when this returns nothing."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            resp = await client.post(
                _TAVILY_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": query, "max_results": max_results},
            )
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    try:
        results = resp.json().get("results", [])
    except ValueError:
        return []
    urls: list[str] = []
    for r in results:
        url = r.get("url") if isinstance(r, dict) else None
        if isinstance(url, str) and url and url not in urls:
            urls.append(url)
    return urls[:max_results]


async def _search_candidate_urls(query: str, max_results: int = 5) -> list[str]:
    """Tavily first (see module docstring's "Candidate discovery" section
    for why it's primary now); DDG+Wikipedia are a fallback, tried ONLY
    when Tavily contributes zero URLs — not merged in alongside Tavily
    results, so a working Tavily call is never diluted by DDG's usual
    anti-bot-blocked [] or Wikipedia's narrower coverage."""
    tavily_urls = await _tavily_search(query, max_results)
    if tavily_urls:
        return tavily_urls[:max_results]

    ddg_urls = await _ddg_search(query, max_results)
    wiki_urls = await _wikipedia_search(query, max_results)
    seen: set[str] = set()
    merged: list[str] = []
    for url in ddg_urls + wiki_urls:
        if url not in seen:
            seen.add(url)
            merged.append(url)
    return merged[:max_results]


class ResearchWebAdapter(DomainAdapter):
    domain_name = "research_web"
    implemented = True

    def __init__(
        self,
        client: NebiusTokenFactoryClient | None = None,
        search: Callable[[str, int], Awaitable[list[str]]] | None = None,
        block_private_networks: bool = True,
    ) -> None:
        # Injected the same way robotics.py injects its client: tests supply a
        # fake (here, also a fake `search` that returns local fixture URLs) so
        # the real propose()->verify_proposal() pipeline runs offline and
        # deterministically; default_domains() gets the real thing.
        self._search = search or _search_candidate_urls
        self._client = client
        self._client_error: str | None = None
        # SSRF guard (see _is_safe_to_fetch's comment) -- on by default, the
        # safe choice for the real server. ONLY the test suite's own local
        # fixture server (127.0.0.1, see evals/fixture_server.py) legitimately
        # needs this off; default_domains() never disables it.
        self._block_private_networks = block_private_networks
        if self._client is None:
            try:
                self._client = NebiusTokenFactoryClient()
            except NebiusClientError as exc:
                self._client_error = str(exc)

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        ctx = claim.context
        if "url" in ctx:
            return await self._gather_single_page(claim)
        return await self._gather_multi_candidate(claim)

    # --- mode 1: single pre-selected page, UNCHANGED from before ---

    async def _gather_single_page(self, claim: Claim) -> list[Evidence]:
        ctx = claim.context
        gap = self._check_ctx(ctx)
        if gap is not None:
            return []

        url, quote = ctx["url"], ctx["quote"]
        try:
            resp = await _safe_fetch(url, block_private_networks=self._block_private_networks)
        except _FetchRefused as exc:
            self._last_fetch_error = str(exc)
            return []
        except httpx.HTTPError as exc:
            # Network failure is its own outcome — NOT silently treated as
            # "quote not found" / contradicts. The caller needs to know the
            # check didn't actually run, not that it ran and failed.
            # NOTE: stored on self, unlike ml_data/fpga_embedded's stateless _check().
            # Re-fetching inside describe_gap() to stay stateless would double the
            # network cost for every gap explanation; the tradeoff is that two
            # concurrent verify() calls on ONE adapter *instance* could race and
            # report each other's fetch error. default_domains() builds one adapter
            # instance per process, so don't share an adapter across concurrent
            # requests without fixing this (e.g. return the error inline instead of
            # through describe_gap) first.
            self._last_fetch_error = f"Fetch of '{url}' failed: {exc!r}."
            return []

        if resp.status_code != 200:
            self._last_fetch_error = f"Fetch of '{url}' returned HTTP {resp.status_code}, not 200."
            return []

        page_text = _normalize(_strip_html(resp.text))
        found = _normalize(quote) in page_text
        if not found and _looks_like_block_page(resp.text):
            self._last_fetch_error = (
                f"Fetch of '{url}' appears to have returned a network block/proxy page (HTTP {resp.status_code}) "
                "instead of the requested source content."
            )
            return []
        # FOUND BUG (follow-up security review): a page cut at _MAX_RESPONSE_BYTES
        # that doesn't contain the quote in its RETAINED portion used to be
        # reported as a confident CONTRADICTS -- but the quote might genuinely
        # be past the cut, which the page being truncated means we simply don't
        # know. Downgrade to an honest UNDETERMINED (a named gap) instead of a
        # wrong confident answer -- but only when the quote wasn't already found
        # in what WAS retained; a found quote is still real evidence regardless
        # of truncation elsewhere in the page.
        if not found and resp.extensions.get("truncated"):
            self._last_fetch_error = (
                f"Fetch of '{url}' was truncated at {_MAX_RESPONSE_BYTES} bytes before the quote could be "
                "confirmed or ruled out -- not treated as a confident contradiction."
            )
            return []

        snippet = (
            f"Quote {'found' if found else 'NOT found'} verbatim (whitespace-normalized) "
            f"in the fetched page at '{url}' (HTTP {resp.status_code}, {len(resp.text)} bytes)."
        )
        return [
            Evidence(
                source=url,
                snippet=snippet,
                stance="supports" if found else "contradicts",
                trust=0.75,  # real fetch + exact-match check, but crude HTML stripping — see docstring
                locator=f"{url} (fetched live, {len(resp.text)} bytes)",
            )
        ]

    # --- mode 2: live multi-candidate search ---

    async def _gather_multi_candidate(self, claim: Claim) -> list[Evidence]:
        self._last_web_gap = None
        question = claim.context.get("quote") or claim.text

        candidate_urls = await self._search(question, 5)
        if not candidate_urls:
            self._last_web_gap = (
                f"No live candidate pages found via search for {question!r} "
                "(both the DuckDuckGo and Wikipedia search backends returned nothing)."
            )
            return []

        all_chunks: list[Chunk] = []
        chunks_by_id: dict[str, Chunk] = {}
        fetch_notes: list[str] = []
        for url in candidate_urls:
            try:
                resp = await _safe_fetch(
                    url, headers={"User-Agent": _SEARCH_USER_AGENT}, block_private_networks=self._block_private_networks
                )
            except _FetchRefused as exc:
                fetch_notes.append(str(exc))
                continue
            except httpx.HTTPError as exc:
                fetch_notes.append(f"{url}: fetch failed ({exc!r})")
                continue
            if resp.status_code != 200:
                fetch_notes.append(f"{url}: HTTP {resp.status_code}")
                continue
            if _looks_like_block_page(resp.text):
                fetch_notes.append(f"{url}: looked like a block/proxy page")
                continue

            page_text = _strip_html(resp.text)
            chunks = chunk_document(url, page_text)
            all_chunks.extend(chunks)
            chunks_by_id.update({c.chunk_id: c for c in chunks})

        if not all_chunks:
            self._last_web_gap = (
                f"Found {len(candidate_urls)} live candidate URL(s) but could not fetch any of them: "
                + "; ".join(fetch_notes)
            )
            return []

        index = BM25Index(all_chunks)
        hits = index.search(question, top_k=10)
        if not hits:
            self._last_web_gap = (
                f"Fetched {len(chunks_by_id)} chunk(s) across {len(candidate_urls)} live candidate page(s), "
                "but none matched this claim's search terms at all (BM25 found zero overlap)."
            )
            return []

        if self._client is None:
            self._last_web_gap = f"Live candidates and matching passages were found, but the LLM propose step can't run: {self._client_error}"
            return []

        # Grouped by SOURCE PAGE (not one pooled top-hit) — checking only the single
        # best-ranked chunk across all candidates would mean "multi-candidate search"
        # only ever actually asks about one source, defeating the point of finding
        # out whether ANY real source confirms a claim. Order preserved from the
        # pooled BM25 ranking (best-matching source first); capped at
        # _MAX_SOURCES_TO_CHECK so a claim that matches many candidates doesn't
        # trigger an unbounded number of live LLM calls.
        hits_by_source: dict[str, list[ScoredChunk]] = {}
        for hit in hits:
            hits_by_source.setdefault(hit.chunk.doc_id, []).append(hit)

        # Phrased so the model reports the REAL stated fact even when it
        # conflicts with the claim, not just whether the claim's exact
        # wording appears — same lesson robotics.py already learned ("a
        # real source doesn't restate the claim being checked, it states
        # facts"), applied here instead of hardcoded per-topic queries
        # since this adapter has to handle arbitrary claims. Verified live:
        # the plain claim text alone got a false "not found" against a real
        # chunk that actually states a conflicting number; this phrasing
        # reliably (5/5 live) surfaces it instead.
        model_question = (
            f"{question} -- quote the passage that states the actual relevant fact, "
            "even if it states a different value than this claim asserts."
        )

        evidence: list[Evidence] = []
        problems: list[str] = []
        for source_url, source_hits in list(hits_by_source.items())[:_MAX_SOURCES_TO_CHECK]:
            try:
                proposal = await propose(model_question, source_hits, self._client)
            except (NebiusClientError, httpx.HTTPError, ValueError) as exc:
                # ValueError added after the Nemotron pivot's pilot runs surfaced one
                # live, against Nemotron Ultra: extract.py's _parse_response() raises
                # ValueError when the model's response isn't valid JSON after
                # fence-stripping (here: a `quote` field containing a huge, malformed
                # raw-wikitext dump that broke JSON parsing) -- an honest named gap,
                # not an uncaught crash reaching the engine. See
                # stress_test/results/NEMOTRON_PIVOT_REPORT.md.
                problems.append(f"{source_url}: LLM propose call failed: {exc}")
                continue
            if proposal is None:
                problems.append(f"{source_url}: model honestly reported the claim isn't stated here")
                continue

            cited_chunk = chunks_by_id.get(proposal.chunk_id)
            if cited_chunk is None:
                problems.append(f"{source_url}: model cited an unknown chunk_id {proposal.chunk_id!r} — dropped")
                continue

            # Placeholder stance here — verify_proposal() only needs *some* string to
            # attach to the Evidence it builds; the real stance is decided below, AFTER
            # the quote's existence is independently confirmed, and never trusted from
            # the proposer itself either way.
            result = verify_proposal(proposal, chunks_by_id, source=cited_chunk.doc_id, stance="supports", trust=0.75)
            if not result.accepted or result.evidence is None:
                problems.append(f"{source_url}: cited quote not actually verbatim on the page ({result.reason})")
                continue

            try:
                stance = await _judge_stance(self._client, claim.text, proposal.quote)
            except (NebiusClientError, httpx.HTTPError) as exc:
                problems.append(f"{source_url}: stance-judging call failed: {exc}")
                continue
            if stance == "unrelated":
                problems.append(f"{source_url}: real verified quote found, but doesn't address this specific claim")
                continue

            candidate_evidence = replace(result.evidence, stance=stance)
            # Near-duplicate guard: a mirror site or a page that copy-pasted the
            # same sentence must not count as a SECOND independent confirmation —
            # see _is_near_duplicate_evidence() for the threshold and why.
            if any(_is_near_duplicate_evidence(candidate_evidence, existing) for existing in evidence):
                problems.append(f"{source_url}: near-duplicate of an already-counted source — not independent")
                continue
            evidence.append(candidate_evidence)

        if not evidence:
            self._last_web_gap = (
                f"Checked {len(hits_by_source)} distinct live source(s) with matching passages, but none "
                "produced usable evidence: " + "; ".join(problems)
            )
        return evidence

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if evidence:
            return super().describe_gap(claim, evidence)
        ctx = claim.context
        if "url" in ctx:
            ctx_gap = self._check_ctx(ctx)
            if ctx_gap:
                return [ctx_gap]
            fetch_err = getattr(self, "_last_fetch_error", None)
            if fetch_err:
                return [fetch_err]
            return [
                "No fetched source found confirming or contradicting this claim. A "
                "plausible-sounding citation is not evidence until it's actually retrieved."
            ]
        web_gap = getattr(self, "_last_web_gap", None)
        if web_gap:
            return [web_gap]
        return [
            "No live web source found confirming or contradicting this claim. A "
            "plausible-sounding citation is not evidence until it's actually retrieved."
        ]

    @staticmethod
    def _check_ctx(ctx: dict) -> str | None:
        required = {"url", "quote"}
        missing_keys = required - ctx.keys()
        if missing_keys:
            return f"Claim is missing required context key(s): {sorted(missing_keys)}."
        return None


# Decides supports/contradicts/unrelated for an ALREADY-mechanically-verified
# quote (verify_proposal() has already confirmed it's real, verbatim text from
# a real fetched page — this never runs on an unverified claim). Two mechanical
# approaches were tried first and both failed on real live tests, not
# hypothetically:
#   1. Strict substring check: broke on a true claim whose real confirming
#      sentence had extra clauses ("(ROV)", "the American marine robotics
#      company") — substring containment doesn't survive real paraphrasing.
#   2. Token-overlap ratio: broke the OTHER way — "BlueROV2 was developed by
#      OpenROV" (false) scored "supports" against the real "...developed by
#      ...Blue Robotics" sentence, because common words ("bluerov2",
#      "developed", "by") dominated the overlap score while the one word that
#      actually matters (OpenROV vs Blue Robotics) was just noise in the ratio.
# A bounded LLM judgment on the already-verified pair is what's actually used
# below — the fabrication risk this project exists to catch (an unverified
# quote) stays fully mechanical; only "do these two verified texts agree" is
# the model's job, which is what it's actually good at.
_STANCE_SYSTEM_PROMPT = """You will be given a CLAIM and a PASSAGE. The passage has already been \
independently confirmed to be real, verbatim text from a live web page — your only job is to decide \
how it relates to the claim's SPECIFIC assertion, not just whether they share a general topic.

FOUND BUG (external review, live, during the Nemotron pivot's pilot runs — not hypothetical): a
passage about the ESP32-S31 ("Espressif Systems has officially started mass production of its new
ESP32-S31 wireless microcontroller") was judged "supports" for a claim about the plain ESP32 — a
DIFFERENT, newer chip that merely shares most of its name. This produced a false tie against a
correct "contradicts" from a real source, pulling a verdict to UNDETERMINED that should have been a
clean CONTRADICTED. FIRST check whether the passage is actually about the SAME specific entity the
claim names — a product, model, version, or variant can share most of a name with a different one \
(ESP32 vs ESP32-S31; "iPhone 15" vs "iPhone 15 Pro") while being a genuinely different thing with its \
own facts. A passage about a DIFFERENT specific entity than the one the claim names is "unrelated", \
even if it uses similar or identical wording about that different entity, and even if it would \
otherwise seem to support or contradict the claim's general shape — do not let topical similarity \
substitute for actually checking the subject is the same one the claim names.

Reply with EXACTLY one word, nothing else:
supports — the passage confirms the claim's specific assertion is true, about the SAME entity the \
claim names
contradicts — the passage states something that conflicts with the claim's specific assertion \
(e.g. a different name, number, date, or entity for the same question), about the SAME entity the \
claim names
unrelated — the passage is on the same general topic but does not actually address this specific \
assertion either way, OR is about a different specific entity than the one the claim names"""


async def _judge_stance(client: NebiusTokenFactoryClient, claim_text: str, verified_quote: str) -> str:
    prompt = f"CLAIM: {claim_text}\n\nPASSAGE: {verified_quote}"
    raw = await client.complete(prompt, system=_STANCE_SYSTEM_PROMPT, temperature=0.0)
    word = raw.strip().lower()
    if "contradict" in word:
        return "contradicts"
    if "support" in word:
        return "supports"
    return "unrelated"


#: Jaccard token-overlap threshold above which two accepted Evidence quotes
#: count as the SAME source (a mirror site, or a page that copy-pasted the
#: same sentence) rather than independent corroboration. Deliberately set
#: HIGH (0.8, not the 0.6 tried and explicitly rejected for stance-judgment
#: above in this same file) because this check answers a narrower question:
#: not "are these about the same fact" (0.6 was already shown, on a real
#: live test, to call two DIFFERENT facts a match just because common words
#: dominated the ratio) but "are these nearly the same TEXT" — true mirrors
#: and copy-pastes are near-verbatim, typically >0.9 overlap once whitespace
#: and incidental citation markers are tokenized away; two independently
#: written sentences stating the same real-world fact in different words
#: (genuine corroboration, which must still count) land well below 0.8 in
#: practice. Erring toward UNDER-deduplicating at the boundary is the safer
#: direction: wrongly keeping a true duplicate only inflates one claim's
#: confidence slightly, while wrongly discarding real independent
#: corroboration throws away evidence this project exists to surface.
_NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.8


def _is_near_duplicate_evidence(a: Evidence, b: Evidence) -> bool:
    """True if two ALREADY-accepted Evidence items' quotes are near-identical
    text — the mirror-site / copy-pasted-sentence case — and so must not both
    count as independent confirmation of the same claim, even though they
    came from different source URLs. Compares `.snippet` (the verified quote
    text engine.py actually sees), not the source URL — a mirror has a
    DIFFERENT url by definition, so comparing urls would never catch it."""
    a_words = set(tokenize(a.snippet))
    b_words = set(tokenize(b.snippet))
    if not a_words or not b_words:
        return False
    jaccard = len(a_words & b_words) / len(a_words | b_words)
    return jaccard >= _NEAR_DUPLICATE_JACCARD_THRESHOLD
