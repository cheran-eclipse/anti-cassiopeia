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
   over chunks pooled from ALL successfully fetched candidate pages (one
   combined BM25 index, not one per page — there's no "the right doc" to
   pick ahead of time here, unlike robotics' per-part corpus). Three-way
   outcome, genuinely distinguished (an improvement over mode 1's
   found/not-found binary):
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

   Candidate discovery (`_search_candidate_urls`) is real, live, and
   keyless — no API key, so it works the same way for anyone cloning this
   repo. Two backends, merged:
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
   If both backends return nothing, that's an honest "no live candidates"
   gap — not a crash, not a silent zero-evidence shrug.

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
being written down as eval cases, not assumed.
"""

from __future__ import annotations

import html as html_module
import re
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import replace

import httpx

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence
from anticassiopeia.llm.nebius_client import NebiusClientError, NebiusTokenFactoryClient
from anticassiopeia.retrieval import BM25Index, Chunk, chunk_document, verify_proposal
from anticassiopeia.retrieval.extract import propose

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


async def _search_candidate_urls(query: str, max_results: int = 5) -> list[str]:
    """Real, live, keyless multi-backend search — "an existing search
    capability", not a hand-rolled index over the whole web. Merges both
    backends and dedupes; see module docstring for each backend's real,
    observed reliability."""
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
    ) -> None:
        # Injected the same way robotics.py injects its client: tests supply a
        # fake (here, also a fake `search` that returns local fixture URLs) so
        # the real propose()->verify_proposal() pipeline runs offline and
        # deterministically; default_domains() gets the real thing.
        self._search = search or _search_candidate_urls
        self._client = client
        self._client_error: str | None = None
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
                async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
                    resp = await client.get(url, headers={"User-Agent": _SEARCH_USER_AGENT})
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
        hits = index.search(question, top_k=5)
        if not hits:
            self._last_web_gap = (
                f"Fetched {len(chunks_by_id)} chunk(s) across {len(candidate_urls)} live candidate page(s), "
                "but none matched this claim's search terms at all (BM25 found zero overlap)."
            )
            return []

        if self._client is None:
            self._last_web_gap = f"Live candidates and matching passages were found, but the LLM propose step can't run: {self._client_error}"
            return []

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
        try:
            proposal = await propose(model_question, hits, self._client)
        except (NebiusClientError, httpx.HTTPError) as exc:
            self._last_web_gap = f"Live candidates and matching passages were found, but the LLM propose call failed: {exc}"
            return []

        if proposal is None:
            self._last_web_gap = (
                f"Fetched {len(candidate_urls)} live candidate page(s) and found passages matching this "
                "claim's search terms, but the model honestly reported the claim isn't actually stated in "
                "any of them — a plausible-sounding citation is not evidence until it's retrieved and confirmed."
            )
            return []

        cited_chunk = chunks_by_id.get(proposal.chunk_id)
        if cited_chunk is None:
            self._last_web_gap = f"Model cited an unknown chunk_id {proposal.chunk_id!r} — dropped, not trusted."
            return []

        # Placeholder stance here — verify_proposal() only needs *some* string to
        # attach to the Evidence it builds; the real stance is decided below, AFTER
        # the quote's existence is independently confirmed, and never trusted from
        # the proposer itself either way.
        result = verify_proposal(proposal, chunks_by_id, source=cited_chunk.doc_id, stance="supports", trust=0.75)
        if not result.accepted or result.evidence is None:
            self._last_web_gap = (
                f"The model cited a quote from a live fetched page, but it does not actually appear there "
                f"verbatim: {result.reason}"
            )
            return []

        try:
            stance = await _judge_stance(self._client, claim.text, proposal.quote)
        except (NebiusClientError, httpx.HTTPError) as exc:
            self._last_web_gap = f"A real quote was verified, but the stance-judging call failed: {exc}"
            return []
        if stance == "unrelated":
            self._last_web_gap = (
                f"A real, verified quote was found on the same general topic, but it does not actually "
                f"address this claim's specific assertion: {proposal.quote!r}"
            )
            return []

        return [replace(result.evidence, stance=stance)]

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

Reply with EXACTLY one word, nothing else:
supports — the passage confirms the claim's specific assertion is true
contradicts — the passage states something that conflicts with the claim's specific assertion \
(e.g. a different name, number, date, or entity for the same question)
unrelated — the passage is on the same general topic but does not actually address this specific \
assertion either way"""


async def _judge_stance(client: NebiusTokenFactoryClient, claim_text: str, verified_quote: str) -> str:
    prompt = f"CLAIM: {claim_text}\n\nPASSAGE: {verified_quote}"
    raw = await client.complete(prompt, system=_STANCE_SYSTEM_PROMPT, temperature=0.0)
    word = raw.strip().lower()
    if "contradict" in word:
        return "contradicts"
    if "support" in word:
        return "supports"
    return "unrelated"
