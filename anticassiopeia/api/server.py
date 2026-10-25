"""
Live deployment surface.

One endpoint: POST /verify, body = {"text": ..., "domain": ..., "context": {...}}.
Returns a full Verdict (state, confidence, evidence, reasoning, missing).

This is intentionally small. The point of Anti-Cassiopeia as infrastructure
is that other developers integrate against this one contract regardless of
which domain they're checking against — the surface should stay stable
even as domain adapters get real implementations behind it.

AUTH + RATE LIMITING ON /verify (found during external security review:
this endpoint had neither): /verify is the Nebius-budget-burning endpoint
(substrate/searchlight claims trigger real, billed LLM calls) and was
open to anyone who could reach the server, with no per-caller limit at
all — an easy way to run up a real bill or exhaust a live API key's
quota. Fixed:
- API key: every /verify request needs a valid `X-API-Key` header,
  checked with `secrets.compare_digest` on BYTES, not str (a str
  comparison raises TypeError -- a 500, not a clean 401 -- for a
  non-ASCII header; found in a follow-up review, fixed by encoding both
  sides first). The expected key comes from `ANTICASSIOPEIA_API_KEY` —
  see README for setup; the README recommends generating it with
  `secrets.token_urlsafe(32)`, not "any string you like". FAILS CLOSED:
  if that env var isn't set at all, EVERY /verify request is rejected
  (401) rather than silently running with no auth.
- Main rate limit: a simple in-memory token bucket (no new dependency —
  stdlib `time`/`threading` only), keyed on the VALIDATED API KEY, not
  the client IP — fixed in a follow-up review: keying on
  `request.client.host` collapses every caller behind one shared
  reverse-proxy/NAT IP into a single bucket, which is a worse
  false-positive DoS risk than the problem it solves. Keying on the key
  instead means a leaked key's own budget can still be exhausted by
  whoever leaked it, but it can no longer DoS other legitimate callers
  sharing the same apparent IP. HONEST CAVEAT: this server currently
  only supports ONE configured key (`ANTICASSIOPEIA_API_KEY`), so right
  now this is close to one global bucket for all authenticated traffic;
  the design pays off once/if this ever supports multiple distinct keys.
- Failed-auth throttle: a SEPARATE, stricter token bucket keyed by client
  IP (this one has to be IP-keyed — a caller that hasn't proven a valid
  key has no key to key on), checked in `_require_api_key` itself.
  Repeated wrong keys from the same IP get 429 instead of 401 once that
  IP's small failed-attempt budget is exhausted — throttles key-guessing
  specifically, independent of the main per-key limit above.
HONEST LIMITATION, both buckets: this state is per-process, not shared —
running multiple uvicorn workers means each worker enforces its own
independent limit, not one combined limit across all of them. A shared
limiter (Redis, etc.) would be the real fix for a multi-worker
deployment, not implemented here.
`/health` and `/domains` stay open (no cost, no sensitive data) —
unauthenticated monitoring/discovery is a normal, intentional tradeoff.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from anticassiopeia.api.upload_store import StoredDocument, UploadStore
from anticassiopeia.core import Claim, UnknownDomainError, VerdictState, VerificationEngine
from anticassiopeia.core.compound import DECOMPOSABLE_DOMAINS, DecompositionError, SubClaimResult, decompose_claim, rollup
from anticassiopeia.domains import default_domains
# Reused, not reimplemented, for /verify/project's domain sniffing below --
# same "one place, not two that could drift" reasoning retrieval/stance.py's
# own docstring already states for a different extraction.
from anticassiopeia.domains.silicon import _DESIGN_TIMING_SUMMARY_HEADER_RE, _SVD_DEVICE_TAG_RE
from anticassiopeia.llm.nebius_client import NebiusClientError, NebiusTokenFactoryClient
from anticassiopeia.retrieval import DocumentIngestError, extract_text
from anticassiopeia.retrieval.document_ingest import SUPPORTED_EXTENSIONS

# FOUND BUG (follow-up security review), mechanism actually fixed (not
# just mitigated here): override=False below is the safe direction for a
# server (.env only fills in what the real environment doesn't already
# set) -- but `anticassiopeia.domains` is imported two lines below this
# comment used to be read, BEFORE this call ever ran, and that import
# transitively pulled in nebius_client.py, which used to call
# `load_dotenv(override=True)` at ITS import time. That global override
# fired first, so by the time this "safe" call executed, a stray `.env`
# file could ALREADY have silently beaten a real, platform-injected
# ANTICASSIOPEIA_API_KEY -- making this override=False a no-op in exactly
# the case it existed to prevent. Actually fixed at the source:
# nebius_client.py no longer calls load_dotenv() at all (see its own
# module docstring, "FIXED BUG #2b") -- it reads `.env` into a private,
# local dict and only ever consults it for its OWN three variable names,
# so it can no longer mutate this process's environment for
# ANTICASSIOPEIA_API_KEY or anything else this override=False call is
# responsible for. Import order no longer matters for this specific risk.
load_dotenv(override=False)

app = FastAPI(
    title="Anti-Cassiopeia",
    description="Domain-agnostic verification: confirmed / contradicted / undetermined — never a guess dressed up as certainty.",
    version="0.1.0",
)

# CORS: the frontend is served from a different origin than this API.
# allow_origins=["*"] is safe specifically because auth here is a header
# (X-API-Key), not a cookie -- there's no ambient-credential/CSRF risk a
# wildcard would normally introduce. allow_credentials stays False to match
# (CORS forbids combining wildcard origins with credentials anyway).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: v2 /verify/project (and, as of v3 §1.1, plain /verify too): quant.py/
#: silicon.py are path-based adapters (dataset_path/report_path),
#: unlike substrate.py's text-based BYOE -- deliberately NOT refactored to
#: also accept raw text (that would touch already-hardened, heavily-tested
#: file-reading/line-locator code in both adapters for no real benefit).
#: Instead, both endpoints write a resolved document's REAL extracted text
#: out to a real file under THIS one fixed, server-owned directory (added
#: to those two adapters' allowed_base_dirs via default_domains()'s
#: extra_allowed_base_dirs param below) -- deliberately ONE shared
#: directory, not two, now that both endpoints need it; nothing about the
#: allowlisting or lifecycle below changes by sharing it. /verify/project
#: scopes its writes to a per-call tempfile.mkdtemp() subdirectory, deleted
#: in a finally block right after that request's claims finish. Plain
#: /verify has no batch to scope a subdirectory to -- it writes ONE file
#: directly under this directory (named after the document_id, which is
#: already a long unguessable token, so no extra uniquing is needed) and
#: deletes that one file in its own finally block right after
#: engine.verify() returns. Either way nothing here accumulates across
#: requests the way upload_store's 24h-TTL in-memory text does.
_PROJECT_SCRATCH_DIR = _REPO_ROOT / "var" / "project_scratch"
_PROJECT_SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

engine = VerificationEngine(domains=default_domains(extra_allowed_base_dirs=[_PROJECT_SCRATCH_DIR]))
upload_store = UploadStore()

# v3 §1.2: /verify/compound's OWN LLM client, for the decompose_claim() call
# specifically -- separate from each domain adapter's own client (e.g.
# substrate.py's SUBSTRATE_MODEL override) since decomposition is a
# different task needing no particular model override. Constructed
# eagerly but safely: NebiusTokenFactoryClient() only reads env vars, no
# network call, so this is safe even when NEBIUS_API_KEY isn't set --
# same "error surfaces per-call, not at import/construction time" pattern
# substrate.py's own __init__ already establishes for exactly this reason.
_compound_client: NebiusTokenFactoryClient | None
try:
    _compound_client = NebiusTokenFactoryClient()
    _compound_client_error: str | None = None
except NebiusClientError as exc:
    _compound_client = None
    _compound_client_error = str(exc)

# v3 "per-verdict summary" (opt-in, context.include_summary=true):
# /verify's OWN LLM client, same safe-construction pattern as
# _compound_client above -- a plain-English gloss of a verdict that has
# ALREADY been computed is a different task from either decomposition or
# any domain adapter's own evidence-gathering, so this gets its own
# client rather than reusing either.
_summary_client: NebiusTokenFactoryClient | None
try:
    _summary_client = NebiusTokenFactoryClient()
    _summary_client_error: str | None = None
except NebiusClientError as exc:
    _summary_client = None
    _summary_client_error = str(exc)

#: Deliberately OFF by default, everywhere, for every domain -- including
#: quant/silicon, which today make ZERO live LLM calls. This is a
#: real, new, additional LLM call on top of whatever a claim's own domain
#: already costs, so it only ever runs when a caller explicitly opts in
#: via context.include_summary=true, accepting that cost for that one
#: call -- never silently added to any caller's existing bill.
_SUMMARY_SYSTEM_PROMPT = """You write a SHORT (at most 2 sentences) plain-English gloss of a \
verification result that has ALREADY been computed by an independent evidence-checking \
pipeline. You are commentary on a decision that is already made, not a new source of \
evidence: NEVER introduce a fact, number, or claim that is not already present in the given \
evidence/reasoning text, and NEVER soften, hedge, or contradict the given state. Just help a \
reader quickly understand what was found and why, in your own words."""


async def _generate_summary(client: NebiusTokenFactoryClient, verdict_dict: dict) -> str:
    """Best-effort only -- callers of this function catch its exceptions
    and fall back to an honest `summary_error`, never let a summary
    failure take down the real verdict that /verify already computed and
    is about to return regardless."""
    prompt = (
        f"State: {verdict_dict['state']}\n"
        f"Confidence: {verdict_dict.get('confidence')}\n"
        f"Evidence: {json.dumps(verdict_dict.get('evidence', []))}\n"
        f"Reasoning: {json.dumps(verdict_dict.get('reasoning', []))}\n"
        f"Missing: {json.dumps(verdict_dict.get('missing', []))}\n"
    )
    result = await client.complete(prompt, system=_SUMMARY_SYSTEM_PROMPT, temperature=0.2)
    return result.strip()

#: v2 master build prompt §3.1: generous enough for a real datasheet/
#: report/CSV/PDF, far below anything that risks memory exhaustion --
#: same reasoning searchlight.py's _MAX_RESPONSE_BYTES already uses for
#: fetched pages. Enforced by reading the upload with a size-aware guard
#: (see _read_upload_within_limit below), not by trusting a
#: Content-Length header a client could lie about.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: v3 §2.3: pooled BYOE search (context.document_pool=true) searches across
#: a caller's own uploaded documents instead of one pre-selected
#: document_id. Capped at the most-recently-uploaded N so one caller
#: cycling through many uploads can't make a single /verify call fan out
#: into an unbounded BM25 index / unbounded chunk count -- same "a limit
#: should exist and be stated, not implicit" discipline as every other cap
#: in this file. When a caller has MORE than this many valid uploads, the
#: truncation itself is stated in the verdict's own reasoning (see
#: substrate.py's _gather_byoe_pool), never silently fewer than the caller
#: assumed.
_MAX_POOL_DOCUMENTS = 10

_API_KEY_HEADER = "X-API-Key"
_RATE_LIMIT_PER_SECOND = 1.0  # sustained rate per API key
_RATE_LIMIT_BURST = 5  # allowance for a short burst above the sustained rate
_FAILED_AUTH_RATE_PER_SECOND = 0.2  # one recovered attempt every 5s, per client IP
_FAILED_AUTH_BURST = 3


class _TokenBucket:
    """A minimal, dependency-free token bucket -- real per-caller rate
    limiting without pulling in slowapi or a Redis dependency for this."""

    def __init__(self, rate_per_second: float, capacity: int) -> None:
        self._rate = rate_per_second
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._last_refill) * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def last_used(self) -> float:
        return self._last_refill


_buckets: dict[str, _TokenBucket] = {}
# RLock, not Lock: _bucket_for() calls _evict_if_over_cap() WHILE already
# holding this lock -- a plain Lock would deadlock a thread against itself.
_buckets_lock = threading.RLock()
_auth_failure_buckets: dict[str, _TokenBucket] = {}
_auth_failure_buckets_lock = threading.RLock()

# v2 master build prompt §3.5: /upload needs its OWN rate limit, separate
# from /verify's -- an unbounded upload endpoint is a new resource-
# exhaustion surface /verify's limiter doesn't cover (uploads are bigger,
# slower, and write to disk, unlike a /verify call). Same keyed-on-the-
# validated-API-key reasoning as /verify's limiter (see _enforce_rate_limit
# below), same _TokenBucket mechanism, deliberately a SEPARATE dict so a
# caller hammering /upload can't also exhaust their /verify budget and
# vice versa.
_UPLOAD_RATE_LIMIT_PER_SECOND = 0.2  # one upload every 5s, sustained
_UPLOAD_RATE_LIMIT_BURST = 3
_upload_buckets: dict[str, _TokenBucket] = {}
_upload_buckets_lock = threading.RLock()

# FOUND BUG (follow-up security review): these dicts added one entry per
# distinct API key / client IP FOREVER, with no eviction -- an attacker
# cycling through many distinct keys or spoofed IPs could grow this
# unboundedly, a real memory-exhaustion DoS, distinct from the main
# rate-limit's own (correctly bounded) per-caller behavior. Fixed with a
# hard cap plus idle eviction, checked opportunistically right before a
# NEW entry is about to be added (not via a background task), so the dict
# never actually exceeds the cap even transiently.
_MAX_TRACKED_BUCKETS = 10_000
_BUCKET_IDLE_TTL_SECONDS = 3600.0  # entries unused for an hour are dropped first


def _make_room_for_one_more(buckets: dict[str, _TokenBucket]) -> None:
    """Called with the dict's lock already held, right before adding a new
    entry -- triggers at >= cap (not > cap) so the dict never actually
    exceeds the cap even transiently, leaving room for the one about to be
    inserted."""
    if len(buckets) < _MAX_TRACKED_BUCKETS:
        return
    now = time.monotonic()
    for key in [k for k, b in buckets.items() if now - b.last_used > _BUCKET_IDLE_TTL_SECONDS]:
        del buckets[key]
    # Still at/over the cap after dropping idle entries (sustained high
    # cardinality, not just staleness) -- drop the least-recently-used
    # entries until there's room for one more, rather than letting it grow.
    if len(buckets) >= _MAX_TRACKED_BUCKETS:
        by_age = sorted(buckets.items(), key=lambda kv: kv[1].last_used)
        for key, _bucket in by_age[: len(buckets) - _MAX_TRACKED_BUCKETS + 1]:
            del buckets[key]


def _bucket_for(client_key: str) -> _TokenBucket:
    with _buckets_lock:
        bucket = _buckets.get(client_key)
        if bucket is None:
            _make_room_for_one_more(_buckets)
            bucket = _TokenBucket(_RATE_LIMIT_PER_SECOND, _RATE_LIMIT_BURST)
            _buckets[client_key] = bucket
        return bucket


def _auth_failure_bucket_for(client_ip: str) -> _TokenBucket:
    with _auth_failure_buckets_lock:
        bucket = _auth_failure_buckets.get(client_ip)
        if bucket is None:
            _make_room_for_one_more(_auth_failure_buckets)
            bucket = _TokenBucket(_FAILED_AUTH_RATE_PER_SECOND, _FAILED_AUTH_BURST)
            _auth_failure_buckets[client_ip] = bucket
        return bucket


def _require_api_key(request: Request, x_api_key: str | None = Header(default=None, alias=_API_KEY_HEADER)) -> str:
    expected = os.environ.get("ANTICASSIOPEIA_API_KEY")
    # Optional second key, meant for a public-facing demo frontend: kept
    # separate from the main key so a frontend can ship this one pre-filled
    # without exposing the primary key anyone else depends on. Unset by
    # default -- if ANTICASSIOPEIA_DEMO_API_KEY isn't configured, this
    # candidate simply never matches, same fail-closed behavior as before
    # for anyone not holding the main key.
    expected_demo = os.environ.get("ANTICASSIOPEIA_DEMO_API_KEY")
    # FOUND BUG (follow-up security review): secrets.compare_digest() raises
    # TypeError -- a 500, not a clean 401 -- for a str argument containing any
    # non-ASCII character. Encoding both sides to bytes first removes that
    # restriction entirely (bytes comparison has no ASCII requirement) while
    # keeping the same constant-time guarantee. Both candidates are checked
    # with compare_digest (never short-circuited on a plain ==) so neither
    # comparison leaks timing information.
    x_api_key_bytes = x_api_key.encode("utf-8") if x_api_key else None
    valid = bool(x_api_key_bytes) and (
        bool(expected and secrets.compare_digest(x_api_key_bytes, expected.encode("utf-8")))
        or bool(expected_demo and secrets.compare_digest(x_api_key_bytes, expected_demo.encode("utf-8")))
    )
    if not valid:
        client_ip = request.client.host if request.client else "unknown"
        if not _auth_failure_bucket_for(client_ip).allow():
            raise HTTPException(status_code=429, detail="Too many failed authentication attempts. Try again later.")
        raise HTTPException(status_code=401, detail=f"Missing or invalid {_API_KEY_HEADER} header.")
    return x_api_key


def _owner_key_hash(api_key: str) -> str:
    """v3 §2.1: SHA-256 of the validated API key, never the raw key -- used
    to scope UploadStore.put()/list_for_owner() to "this caller's own
    uploads" (see upload_store.py's own docstring for the full ownership
    reasoning, including the honest shared-demo-key caveat). Hashing one
    already-validated string is cheap; no reason to key a dict on the raw
    secret when a hash does the same job."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _enforce_rate_limit(api_key: str) -> None:
    if not _bucket_for(api_key).allow():
        raise HTTPException(status_code=429, detail="Rate limit exceeded for /verify. Try again shortly.")


def _upload_bucket_for(client_key: str) -> _TokenBucket:
    with _upload_buckets_lock:
        bucket = _upload_buckets.get(client_key)
        if bucket is None:
            _make_room_for_one_more(_upload_buckets)
            bucket = _TokenBucket(_UPLOAD_RATE_LIMIT_PER_SECOND, _UPLOAD_RATE_LIMIT_BURST)
            _upload_buckets[client_key] = bucket
        return bucket


def _enforce_upload_rate_limit(api_key: str) -> None:
    if not _upload_bucket_for(api_key).allow():
        raise HTTPException(status_code=429, detail="Rate limit exceeded for /upload. Try again shortly.")


# v2 /verify/project: its OWN rate limit, stricter than /verify's -- one
# project call can trigger SEVERAL underlying engine.verify() calls (one
# per claim in the batch), each of which can itself be a live,
# Nebius-budget-burning LLM call. Same separate-bucket reasoning as
# /upload's limiter above.
_PROJECT_RATE_LIMIT_PER_SECOND = 0.1  # one project call every 10s, sustained
_PROJECT_RATE_LIMIT_BURST = 2
_project_buckets: dict[str, _TokenBucket] = {}
_project_buckets_lock = threading.RLock()
#: Hard cap on claims per /verify/project call -- bounds both the live-LLM
#: fan-out above and the number of scratch files one call can write, same
#: "a limit should exist and be stated, not implicit" discipline as every
#: other cap in this file.
_MAX_CLAIMS_PER_PROJECT = 20


def _project_bucket_for(client_key: str) -> _TokenBucket:
    with _project_buckets_lock:
        bucket = _project_buckets.get(client_key)
        if bucket is None:
            _make_room_for_one_more(_project_buckets)
            bucket = _TokenBucket(_PROJECT_RATE_LIMIT_PER_SECOND, _PROJECT_RATE_LIMIT_BURST)
            _project_buckets[client_key] = bucket
        return bucket


def _enforce_project_rate_limit(api_key: str) -> None:
    if not _project_bucket_for(api_key).allow():
        raise HTTPException(status_code=429, detail="Rate limit exceeded for /verify/project. Try again shortly.")


# v3 §1.2: /verify/compound's OWN rate limit, STRICTER than /verify/project's --
# one compound call can trigger 1 (the decomposition call itself) + N (one
# engine.verify() per sub-claim) live LLM calls from a SINGLE HTTP request,
# more fan-out per call than even /verify/project, so this is sized
# stricter: one call every 20s, burst of 2.
_COMPOUND_RATE_LIMIT_PER_SECOND = 0.05
_COMPOUND_RATE_LIMIT_BURST = 2
_compound_buckets: dict[str, _TokenBucket] = {}
_compound_buckets_lock = threading.RLock()
#: decompose_claim() (an LLM call) must not be trusted to produce an
#: unbounded number of sub-claims from one input -- a hard cap, with a
#: clear 422 above it rather than silently truncating (truncating would
#: mean "verifying" a claim that wasn't actually fully checked).
_MAX_SUBCLAIMS = 8


def _compound_bucket_for(client_key: str) -> _TokenBucket:
    with _compound_buckets_lock:
        bucket = _compound_buckets.get(client_key)
        if bucket is None:
            _make_room_for_one_more(_compound_buckets)
            bucket = _TokenBucket(_COMPOUND_RATE_LIMIT_PER_SECOND, _COMPOUND_RATE_LIMIT_BURST)
            _compound_buckets[client_key] = bucket
        return bucket


def _enforce_compound_rate_limit(api_key: str) -> None:
    if not _compound_bucket_for(api_key).allow():
        raise HTTPException(status_code=429, detail="Rate limit exceeded for /verify/compound. Try again shortly.")


class VerifyRequest(BaseModel):
    text: str
    domain: str
    context: dict = {}


class ProjectClaimRequest(BaseModel):
    """One claim inside a /verify/project batch. `domain`, unlike plain
    /verify, is OPTIONAL: when a `document_id` is given, the domain is
    deterministically sniffed from the uploaded document (see
    _sniff_domain_for_document below) rather than asked of the caller --
    the whole point of the project endpoint is routing a bundle of mixed
    documents without the caller having to pre-sort them by domain. A
    claim with no document_id and no explicit domain defaults to
    searchlight (free-text, no-file claims are exactly what that domain
    is for -- see the v2 master build prompt's scenario #4/#5).

    `document_pool` (v3 §2.4): same pooled-search option plain /verify
    gained in §2.3, now per-claim inside a batch -- lets one project call
    mix claims pinned to one specific document with claims that search
    the whole caller's upload pool. Mutually exclusive with document_id
    (a per-claim error, not a whole-batch 400, if both are set -- a bad
    claim shape in a batch must not abort every OTHER claim in the same
    batch, same principle _run_one_project_claim's own docstring already
    states). There's no document to sniff a domain FROM for a pool claim
    (sniffing needs one concrete uploaded document), so an omitted
    `domain` on a pool claim defaults to "substrate" directly, rather than
    falling through to searchlight's own no-document default --
    document_pool is substrate-only anyway (see §2.3's own scope note), so
    that default is never wrong, only a convenience for a caller who
    didn't bother spelling out the only domain that could apply."""

    text: str
    document_id: str | None = None
    document_pool: bool = False
    domain: str | None = None
    context: dict = {}


class ProjectVerifyRequest(BaseModel):
    claims: list[ProjectClaimRequest]


class CompoundVerifyRequest(BaseModel):
    """One free-text claim for /verify/compound to split and verify. NO
    `domain` field, unlike VerifyRequest/ProjectClaimRequest -- deliberate,
    not an oversight: decompose_claim() classifies EACH sub-claim into its
    own domain itself (see core/compound.py's own system prompt), so a
    top-level domain on the whole compound claim would be meaningless and
    always ignored. This project's own convention (see
    _run_one_project_claim's document_id-for-an-unsupported-domain error)
    is to never accept a field that would just be silently ignored --
    better to not have the field at all than accept-and-ignore it.

    `context` exists only so a 400 can name EXACTLY what's not allowed in
    it (document_id/document_pool) with a clear reason, rather than
    accepting no context at all and giving a generic "extra field not
    permitted" validation error with none of that reasoning."""

    text: str
    context: dict = {}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "domains": sorted(engine._domains)}


@app.get("/domains")
async def domains() -> dict:
    """Lists registered domains and whether each is wired to a real evidence
    source yet, so a caller can check before trusting a verdict from a
    domain that's still a stub. Reads DomainAdapter.implemented — each
    adapter sets this explicitly, no heuristic guessing."""
    return {
        name: {"adapter": adapter.__class__.__name__, "implemented": adapter.implemented}
        for name, adapter in engine._domains.items()
    }


@app.post("/verify")
async def verify(req: VerifyRequest, api_key: str = Depends(_require_api_key)) -> dict:
    """context.include_summary=true (opt-in, off by default) adds a short
    best-effort "summary"/"summary_error" field generated from the
    ALREADY-COMPUTED verdict below -- see _generate_summary's own
    docstring for why this is commentary, never a new source of evidence,
    and why it's a real additional LLM call that only ever runs when
    explicitly asked for, regardless of domain (including quant/
    silicon, which otherwise make zero live LLM calls)."""
    _enforce_rate_limit(api_key)
    context, scratch_path = _resolve_document_context(req.context, req.domain, _owner_key_hash(api_key))
    claim = Claim(text=req.text, domain=req.domain, context=context)
    try:
        verdict = await engine.verify(claim)
    except UnknownDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        # v3 §1.1: a single /verify call isn't a batch with one natural
        # "end" to clean up at like /verify/project has -- this call wrote
        # its own one scratch file (if any) above, and deletes that same
        # one file here, every time, success or failure. missing_ok=True
        # because a concurrent /verify call for the SAME document_id could
        # already have deleted it first (harmless: both calls wrote
        # identical content, derived from the same stored document).
        if scratch_path is not None:
            scratch_path.unlink(missing_ok=True)

    result = verdict.to_dict()

    # Opt-in only (see _generate_summary's own comment) -- checked AFTER
    # the real verdict is fully computed, so a summary failure below can
    # never affect, delay unnecessarily, or take down the actual verdict
    # this endpoint exists to produce. "summary"/"summary_error" are only
    # ever present in the response when include_summary was actually set
    # -- never silent extra fields nobody asked for.
    if context.get("include_summary"):
        if _summary_client is None:
            result["summary_error"] = f"Summary generation's LLM client is not available: {_summary_client_error}"
        else:
            try:
                result["summary"] = await _generate_summary(_summary_client, result)
            except (NebiusClientError, httpx.HTTPError) as exc:
                result["summary_error"] = f"Summary generation failed: {exc}"

    return result


def _resolve_document_context(context: dict, domain: str, owner_key_hash: str) -> tuple[dict, Path | None]:
    """v2 master build prompt §3.2, generalized by v3 §1.1, extended by v3
    §2.3 for pooled search: if the caller's context names a document_id
    (from a prior /upload) OR sets document_pool=true, resolve it to real
    content HERE, in the API layer, before any domain adapter ever sees
    the claim. An unknown/expired document_id, or an empty/unsupported
    pool request, is a clean, explicit 400 -- NOT a silent fall-through to
    the fixed-corpus behavior a caller who explicitly asked to check
    against their own document(s) would never want and would have no way
    to notice happened.

    document_id and document_pool are MUTUALLY EXCLUSIVE -- a request
    naming both is a 400 before either is resolved, same "name the
    conflict, don't silently prefer one" discipline as every other
    request-shape check in this file.

    POOLED SEARCH (document_pool=true), substrate-only: looks up the
    CALLING key's own currently-valid uploads via
    upload_store.list_for_owner(owner_key_hash) -- never any other
    caller's documents (see upload_store.py's own ownership docstring) --
    caps at the _MAX_POOL_DOCUMENTS most recent, and hands substrate.py the
    already-resolved (filename, text) pairs via
    context["document_pool_items"], plus the real total available via
    context["document_pool_total_available"] (so substrate.py can name the
    truncation in its own reasoning when a caller has more uploads than
    fit under the cap -- see that module's _gather_byoe_pool). substrate.py
    itself never imports UploadStore (clean domain/api layering, per that
    module's own docstring) -- it only ever reads context fields, exactly
    like the single-document document_text/document_filename path below.
    An empty pool (no valid uploads at all) is NOT an error here -- it's
    resolved through fine, and substrate.py's own gather_evidence() turns
    an empty document_pool_items list into an honest, named gap.

    What "resolve" means for document_id depends on `domain`, same
    three-way split /verify/project's _run_one_project_claim already
    established for the project endpoint (see that function's own
    comments for the full reasoning -- not repeated here):
    - "substrate": inject document_text/document_filename directly --
      substrate.py's BYOE path only ever reads those two context keys,
      never document_id or the upload store itself (clean domain/api
      layering, per that module's own docstring).
    - "quant" / "silicon": both adapters are path-based
      (dataset_path/report_path) and were deliberately NOT given a
      document_text mode (see domains/__init__.py's docstring) -- so the
      resolved document's real extracted text is written to a real,
      server-owned scratch file under _PROJECT_SCRATCH_DIR (already in
      both adapters' allowed_base_dirs), and that file's path becomes the
      existing, unmodified dataset_path/report_path context field. This
      endpoint fabricates NOTHING: every structured field those adapters
      actually need (column/stat/..., peripheral/metric/...) still comes
      from the caller's own context, this only auto-fills the one field
      it legitimately knows -- which real file this document_id
      corresponds to. The caller (this function's one caller, /verify)
      is responsible for deleting the returned scratch_path afterward.
    - anything else (most notably "searchlight", which has no mode that
      consumes an already-extracted document's text at all -- its two
      modes are URL-fetch or live search) -- a clean, named 400, not a
      silent no-op that would leave a caller thinking their uploaded
      document was actually checked when it was quietly ignored. The same
      named-400 treatment applies to document_pool for any domain other
      than substrate (quant/silicon need one exact structured
      file per claim, not a search across several; searchlight has no
      document-consuming mode at all -- see the v3 master build prompt's
      §2.3 scope note).

    Returns (resolved_context, scratch_path_or_None). scratch_path is only
    ever non-None for the document_id + quant/silicon branch.

    `context` is a plain dict here (Pydantic already validated VerifyRequest.
    context as `dict`), so a non-string document_id (an int, a list, ...)
    simply never matches anything in the store and resolves to the same
    clean 400 below -- no separate type check needed."""
    document_id = context.get("document_id")
    document_pool = bool(context.get("document_pool"))

    if document_id is not None and document_pool:
        raise HTTPException(status_code=400, detail="Specify either document_id or document_pool, not both.")

    if document_pool:
        if domain != "substrate":
            raise HTTPException(
                status_code=400,
                detail=f"domain {domain!r} does not support document_pool search (substrate-only).",
            )
        all_owned = upload_store.list_for_owner(owner_key_hash)
        pool_docs = all_owned[:_MAX_POOL_DOCUMENTS]
        resolved = dict(context)
        resolved["document_pool_items"] = [(doc.filename, doc.text) for doc in pool_docs]
        resolved["document_pool_total_available"] = len(all_owned)
        return resolved, None

    if document_id is None:
        return context, None
    doc = upload_store.get(document_id) if isinstance(document_id, str) else None
    if doc is None:
        raise HTTPException(status_code=400, detail=f"Unknown or expired document_id: {document_id!r}.")

    resolved = dict(context)
    if domain == "substrate":
        resolved["document_text"] = doc.text
        resolved.setdefault("document_filename", doc.filename)
        return resolved, None
    if domain in ("quant", "silicon"):
        scratch_path = _PROJECT_SCRATCH_DIR / f"{document_id}{_extension_of(doc.filename) or '.txt'}"
        scratch_path.write_text(doc.text)
        key = "dataset_path" if domain == "quant" else "report_path"
        resolved[key] = str(scratch_path)
        return resolved, scratch_path
    raise HTTPException(
        status_code=400,
        detail=f"domain {domain!r} does not support a document_id-linked claim.",
    )


@app.get("/documents")
async def documents(api_key: str = Depends(_require_api_key)) -> dict:
    """v3 §2.2: lists the CALLING API key's own currently-valid uploads --
    needed so a caller (or the frontend) can discover what's poolable
    before verifying (see §2.3's document_pool), and so GET /documents
    actually proves the ownership plumbing added in §2.1 end-to-end before
    pooled search is built on top of it. Same auth as /verify; reuses
    /verify's OWN rate-limit bucket rather than getting a dedicated one --
    this is a cheap in-memory dict scan (upload_store.list_for_owner), not
    real work like /upload's disk I/O or /verify/project's live-LLM
    fan-out, so it doesn't need the stricter, separate-bucket treatment
    those two earned.

    `seconds_until_expiry`, not a raw `uploaded_at`: StoredDocument's own
    uploaded_at is `time.monotonic()`-based (see upload_store.py's own
    docstring -- "not wall-clock display"), so handing it back to a caller
    verbatim would be a meaningless number with no relation to wall-clock
    time. "How much longer is this still valid" is the actually useful
    derived quantity, and it's what this endpoint returns instead."""
    _enforce_rate_limit(api_key)
    owner_key_hash = _owner_key_hash(api_key)
    now = time.monotonic()
    return {
        "documents": [
            {
                "document_id": doc.document_id,
                "filename": doc.filename,
                "size_bytes": doc.size_bytes,
                "seconds_until_expiry": max(0.0, upload_store._ttl_seconds - (now - doc.uploaded_at)),
            }
            for doc in upload_store.list_for_owner(owner_key_hash)
        ]
    }


@app.post("/upload")
async def upload(file: UploadFile = File(...), api_key: str = Depends(_require_api_key)) -> dict:
    """v2 master build prompt §3.1: accepts a document, extracts text
    (format-dispatched by anticassiopeia.retrieval.document_ingest -- see
    §0.6 for the supported-extension list), stores the EXTRACTED TEXT
    (never the raw path) under an opaque document_id, returns that id for
    later /verify calls (substrate.py's document_id context field) to
    reference. Same auth as /verify; a SEPARATE rate limit (see
    _enforce_upload_rate_limit) since this is a bigger, slower, disk-
    writing operation /verify's own limiter was never sized for."""
    _enforce_upload_rate_limit(api_key)

    filename = file.filename or "upload"
    ext = filename[filename.rfind(".") :].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}.",
        )

    # FOUND BUG pattern this guards against (same class already fixed
    # elsewhere in this project, e.g. searchlight.py's _MAX_RESPONSE_BYTES
    # streaming cap): a client-supplied Content-Length header can lie.
    # Reading one byte past the cap and checking length (rather than
    # trusting the header) is what actually enforces the limit.
    raw_bytes = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds the {_MAX_UPLOAD_BYTES} byte limit.",
        )
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        text = extract_text(raw_bytes, filename)
    except DocumentIngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    doc = upload_store.put(filename=filename, text=text, size_bytes=len(raw_bytes), owner_key_hash=_owner_key_hash(api_key))
    return {"document_id": doc.document_id, "filename": doc.filename, "size_bytes": doc.size_bytes}


def _extension_of(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


def _sniff_domain_for_document(doc: StoredDocument) -> str:
    """v2 master build prompt §4: deterministic, code-based sniffing --
    NEVER an LLM guess about what a file format "probably" is, since code
    can already tell for certain. Dispatches on the uploaded filename's
    extension (already validated once, at /upload time, against
    document_ingest.SUPPORTED_EXTENSIONS) plus, for the one genuinely
    ambiguous extension (.xml -- could be a real CMSIS-SVD register map OR
    just a generic XML document), the same real root-tag check
    silicon.py's own _is_svd_file() uses.

    Returns "quant" | "silicon" | "substrate" -- substrate.py's BYOE
    path is the catch-all for any supported text-like format that isn't
    one of the two structured ones, per the master prompt's own wording
    ("otherwise substrate' BYOE path")."""
    ext = _extension_of(doc.filename)
    if ext == ".csv":
        return "quant"
    if ext == ".svd":
        return "silicon"
    if ext == ".xml":
        return "silicon" if _SVD_DEVICE_TAG_RE.search(doc.text[:4000]) else "substrate"
    if ext == ".rpt":
        return "silicon" if _DESIGN_TIMING_SUMMARY_HEADER_RE.search(doc.text) else "substrate"
    return "substrate"  # .txt/.md/.pdf/.docx -- free text, no structured shape to sniff


@app.post("/verify/project")
async def verify_project(req: ProjectVerifyRequest, api_key: str = Depends(_require_api_key)) -> dict:
    """v2 master build prompt §4: a bundle of claims, each optionally tied
    to a previously /upload'd document, auto-routed to the right domain
    and rolled up with core.compound's existing AND-semantics
    rollup() -- the SAME pure function item 20's LLM-decomposition path
    uses, just fed real per-claim Verdicts this endpoint already computed
    instead of LLM-decomposed sub-claims (this endpoint never calls
    decompose_claim() at all: the caller already told us the distinct
    claims and which document each belongs to, so there is nothing left
    to decompose).

    DELIBERATELY NOT done here, stated plainly rather than silently
    assumed: core.compound.DECOMPOSABLE_DOMAINS (item 20's OWN
    LLM-decomposition restriction to substrate/searchlight) is NOT
    loosened to include quant/silicon by this endpoint's
    existence. decompose_claim() splits ONE free-text claim via an LLM
    call that never sees any uploaded document at all -- a real project
    scratch path existing HERE, for THIS endpoint's own explicitly-named
    documents, gives decompose_claim() no way to know which (if any)
    uploaded file a sub-claim it invents would even correspond to.
    Loosening that restriction would reintroduce exactly the
    fabricated-file-path risk item 20 was built to close. If a future
    round wants an LLM to decompose a claim AND route parts to quant/
    silicon, it needs its own explicit per-part document binding,
    not a relaxed domain set on the existing LLM-decomposition path.
    """
    _enforce_project_rate_limit(api_key)

    if not req.claims:
        raise HTTPException(status_code=400, detail="'claims' must be a non-empty list.")
    if len(req.claims) > _MAX_CLAIMS_PER_PROJECT:
        raise HTTPException(
            status_code=400,
            detail=f"'claims' has {len(req.claims)} entries; at most {_MAX_CLAIMS_PER_PROJECT} per /verify/project call.",
        )

    owner_key_hash = _owner_key_hash(api_key)
    scratch_dir = Path(tempfile.mkdtemp(dir=_PROJECT_SCRATCH_DIR))
    try:
        results: list[dict] = []
        sub_results: list[SubClaimResult] = []
        for claim_req in req.claims:
            result = await _run_one_project_claim(claim_req, scratch_dir, owner_key_hash)
            results.append(result)
            sub_results.append(
                SubClaimResult(
                    text=claim_req.text,
                    domain=result["domain"] or "unsupported",
                    verdict=result["verdict_obj"],
                )
            )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    state, confidence, reasoning = rollup(sub_results)
    return {
        "claims": [{k: v for k, v in r.items() if k != "verdict_obj"} for r in results],
        "rollup": {"state": state.value, "confidence": confidence, "reasoning": reasoning},
    }


async def _run_one_project_claim(claim_req: ProjectClaimRequest, scratch_dir: Path, owner_key_hash: str) -> dict:
    """Runs one claim of a /verify/project batch to completion (or to a
    named, honest per-claim error) -- NEVER raises; a problem with one
    claim (bad document_id, nothing routable, a bad file for its sniffed
    domain, an invalid document_id/document_pool combination) must not
    abort the other claims in the same batch, same "one false part
    falsifies the whole AND, but a different kind of problem must still
    be visible" principle core.compound.rollup() itself already
    documents -- this is also why document_id+document_pool conflicts are
    a per-claim error here rather than the whole-request 400 plain
    /verify uses for the same conflict (plain /verify has only one claim,
    so request-level and claim-level are the same thing there; a batch
    is not)."""
    base_result = {"text": claim_req.text, "document_id": claim_req.document_id, "domain": None, "verdict_obj": None, "verdict": None, "error": None}

    context = dict(claim_req.context)
    domain = claim_req.domain

    if claim_req.document_id is not None and claim_req.document_pool:
        return {**base_result, "error": "Specify either document_id or document_pool, not both."}

    if claim_req.document_pool:
        # v3 §2.4: same pooled-search resolution as plain /verify's §2.3
        # (see _resolve_document_context's own docstring for the full
        # reasoning) -- ownership-scoped via upload_store.list_for_owner(),
        # capped at _MAX_POOL_DOCUMENTS, substrate-only. No document_id
        # to sniff a domain FROM here, so an omitted domain defaults
        # directly to "substrate" (see ProjectClaimRequest's own
        # docstring) rather than falling through to the no-document
        # searchlight default below.
        if domain is None:
            domain = "substrate"
        if domain != "substrate":
            return {
                **base_result,
                "domain": domain,
                "error": f"domain {domain!r} does not support document_pool search (substrate-only).",
            }
        all_owned = upload_store.list_for_owner(owner_key_hash)
        pool_docs = all_owned[:_MAX_POOL_DOCUMENTS]
        context["document_pool"] = True
        context["document_pool_items"] = [(doc.filename, doc.text) for doc in pool_docs]
        context["document_pool_total_available"] = len(all_owned)
    elif claim_req.document_id is not None:
        doc = upload_store.get(claim_req.document_id)
        if doc is None:
            return {**base_result, "error": f"Unknown or expired document_id: {claim_req.document_id!r}."}
        if domain is None:
            domain = _sniff_domain_for_document(doc)

        if domain == "substrate":
            context["document_text"] = doc.text
            context.setdefault("document_filename", doc.filename)
        elif domain in ("quant", "silicon"):
            # write the REAL extracted text to a REAL file under this
            # request's own scratch subdirectory (already in both adapters'
            # allowed_base_dirs -- see default_domains()'s
            # extra_allowed_base_dirs), then point the existing, unmodified
            # path-based context field at it. The caller still supplies
            # every structured field those adapters actually need (column/
            # stat/expected_value, or peripheral/metric/comparator/
            # expected_value) via claim_req.context -- this endpoint
            # fabricates NOTHING, it only auto-fills the one field it
            # legitimately knows: which real file this document_id
            # corresponds to.
            scratch_path = scratch_dir / f"{claim_req.document_id}{_extension_of(doc.filename) or '.txt'}"
            scratch_path.write_text(doc.text)
            key = "dataset_path" if domain == "quant" else "report_path"
            context[key] = str(scratch_path)
        else:
            # A document tied to a domain that has no defined way to consume
            # one (searchlight's two modes are URL-fetch or live search,
            # neither of which is "here is a document's already-extracted
            # text") -- an honest, named per-claim error, not a silently
            # ignored document or a meaningless context key.
            return {
                **base_result,
                "domain": domain,
                "error": f"domain {domain!r} does not support a document_id-linked claim in this endpoint.",
            }
    elif domain is None:
        domain = "searchlight"  # no document, no explicit domain -- free-text default (see model docstring)

    claim = Claim(text=claim_req.text, domain=domain, context=context)
    try:
        verdict = await engine.verify(claim)
    except UnknownDomainError as exc:
        return {**base_result, "domain": domain, "error": str(exc)}

    return {**base_result, "domain": domain, "verdict_obj": verdict, "verdict": verdict.to_dict()}


@app.post("/verify/compound")
async def verify_compound_endpoint(req: CompoundVerifyRequest, api_key: str = Depends(_require_api_key)) -> dict:
    """v3 §1.2: makes core/compound.py's decompose_claim()/rollup() (item
    20, library-only until now -- see docs/ARCHITECTURE.md's "Item 20"
    section) reachable over HTTP, LAST of everything this build shipped --
    the least-requested of the original gaps this round closed, the most
    expensive in live-LLM-call terms (1 decompose call + up to
    _MAX_SUBCLAIMS verify calls from ONE request), and the one that
    benefits most from everything else being stable first.

    Calls the real pieces directly (decompose_claim(), then this SAME
    module-level `engine` per sub-claim, then rollup()) rather than
    verify_compound() as one atomic call -- verify_compound() has no cap
    on sub-claim count, and verifying every decomposed part BEFORE
    checking the cap would waste exactly the live calls this cap exists
    to bound. The cap is checked between decompose and verify, so a
    claim that decomposes into too many parts is rejected (422) before
    any of those parts are ever verified.

    REJECTS (400) any request whose context names document_id OR
    document_pool -- broader than this build's own spec text, which named
    only document_id; document_pool (v3 §2.3) didn't change the
    underlying reason at all: an LLM-invented sub-claim has no way to
    know which uploaded document, or pool, if any, it would even
    correspond to. Loosening either would reintroduce exactly the
    fabricated-file-path risk DECOMPOSABLE_DOMAINS (substrate/searchlight
    only -- see core/compound.py's own docstring) already exists to
    close.
    """
    _enforce_compound_rate_limit(api_key)

    if "document_id" in req.context or "document_pool" in req.context:
        raise HTTPException(
            status_code=400,
            detail=(
                "compound decomposition is not available for document-bound claims -- an "
                "LLM-invented sub-claim has no way to know which uploaded document (or "
                "document pool), if any, it corresponds to."
            ),
        )

    if _compound_client is None:
        raise HTTPException(
            status_code=503,
            detail=f"Compound decomposition's LLM client is not available: {_compound_client_error}",
        )

    try:
        parts = await decompose_claim(_compound_client, req.text)
    except DecompositionError as exc:
        return {
            "claim_text": req.text,
            "state": VerdictState.UNDETERMINED.value,
            "confidence": None,
            "sub_claims": [],
            "reasoning": [f"Could not decompose this claim into parts: {exc}"],
        }

    if len(parts) > _MAX_SUBCLAIMS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"This claim decomposed into {len(parts)} parts; at most {_MAX_SUBCLAIMS} are "
                "allowed per /verify/compound call. Not silently truncated -- a truncated "
                "compound claim would mean verifying something that wasn't actually fully checked."
            ),
        )

    sub_results: list[SubClaimResult] = []
    for part in parts:
        text, domain = part["text"], part["domain"]
        if domain not in DECOMPOSABLE_DOMAINS:
            sub_results.append(SubClaimResult(text=text, domain="unsupported", verdict=None))
            continue
        verdict = await engine.verify(Claim(text=text, domain=domain, context={}))
        sub_results.append(SubClaimResult(text=text, domain=domain, verdict=verdict))

    state, confidence, reasoning = rollup(sub_results)
    return {
        "claim_text": req.text,
        "state": state.value,
        "confidence": confidence,
        "sub_claims": [
            {"text": r.text, "domain": r.domain, "verdict": r.verdict.to_dict() if r.verdict is not None else None}
            for r in sub_results
        ],
        "reasoning": reasoning,
    }
