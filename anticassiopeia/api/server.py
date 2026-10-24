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
(robotics/research_web claims trigger real, billed LLM calls) and was
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

import os
import secrets
import threading
import time

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from anticassiopeia.core import Claim, UnknownDomainError, VerificationEngine
from anticassiopeia.domains import default_domains

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

engine = VerificationEngine(domains=default_domains())

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
    # FOUND BUG (follow-up security review): secrets.compare_digest() raises
    # TypeError -- a 500, not a clean 401 -- for a str argument containing any
    # non-ASCII character. Encoding both sides to bytes first removes that
    # restriction entirely (bytes comparison has no ASCII requirement) while
    # keeping the same constant-time guarantee.
    valid = bool(expected and x_api_key and secrets.compare_digest(x_api_key.encode("utf-8"), expected.encode("utf-8")))
    if not valid:
        client_ip = request.client.host if request.client else "unknown"
        if not _auth_failure_bucket_for(client_ip).allow():
            raise HTTPException(status_code=429, detail="Too many failed authentication attempts. Try again later.")
        raise HTTPException(status_code=401, detail=f"Missing or invalid {_API_KEY_HEADER} header.")
    return x_api_key


def _enforce_rate_limit(api_key: str) -> None:
    if not _bucket_for(api_key).allow():
        raise HTTPException(status_code=429, detail="Rate limit exceeded for /verify. Try again shortly.")


class VerifyRequest(BaseModel):
    text: str
    domain: str
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
    _enforce_rate_limit(api_key)
    claim = Claim(text=req.text, domain=req.domain, context=req.context)
    try:
        verdict = await engine.verify(claim)
    except UnknownDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return verdict.to_dict()
