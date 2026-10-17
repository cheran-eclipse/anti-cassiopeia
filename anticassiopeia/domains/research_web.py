"""
Web / research-paper domain adapter — existence/verification POV.

Verifies "this source, at this URL, actually says X" by fetching the URL
for real and checking whether the claimed quote appears verbatim (modulo
whitespace) in the fetched page — never from recalled/trained knowledge.
This is the domain most directly aimed at the failure Anti-Cassiopeia is
named against: a confident, detailed, plausible-sounding citation that
turns out to be fabricated.

STATUS: real code, network-dependent. CONFIRMED BLOCKED inside this build
sandbox — a live test against https://example.com failed with
`ProxyError('403 Forbidden')` (this sandbox's outbound network is
allowlisted to package registries and GitHub, nothing else), and that
failure came back correctly as an UNDETERMINED verdict with the real
proxy error as the named gap, not a crash or a silent guess. That's the
one case this adapter could actually prove end to end from there. Evals and
the demo now fetch a local fixture server (evals/fixture_server.py) over real
HTTP, so confirmed/contradicted/block-page paths are exercised offline; only
evals/cases/research_web/live_example_com_drift.json touches the internet, and
it accepts any verdict (including `contradicted` when the live page drifts). The HTML-to-text
extraction below is a plain regex tag-stripper, not a real HTML parser —
it will mis-handle `<script>`/`<style>` content and JS-rendered pages;
good enough for a static page's body text, not a guarantee.

Claim contract (via Claim.context):
    context = {
        "url": str,
        "quote": str,     # the exact text the claim says appears at `url`
    }
"""

from __future__ import annotations

import re

import httpx

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_FETCH_TIMEOUT = 15.0
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


class ResearchWebAdapter(DomainAdapter):
    domain_name = "research_web"
    implemented = True

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        ctx = claim.context
        gap = self._check_ctx(ctx)
        if gap is not None:
            return []

        url, quote = ctx["url"], ctx["quote"]
        try:
            async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(url)
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

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if evidence:
            return super().describe_gap(claim, evidence)
        ctx_gap = self._check_ctx(claim.context)
        if ctx_gap:
            return [ctx_gap]
        fetch_err = getattr(self, "_last_fetch_error", None)
        if fetch_err:
            return [fetch_err]
        return [
            "No fetched source found confirming or contradicting this claim. A "
            "plausible-sounding citation is not evidence until it's actually retrieved."
        ]

    @staticmethod
    def _check_ctx(ctx: dict) -> str | None:
        required = {"url", "quote"}
        missing_keys = required - ctx.keys()
        if missing_keys:
            return f"Claim is missing required context key(s): {sorted(missing_keys)}."
        return None
