"""
In-memory store for uploaded documents, keyed by an opaque document_id.

Deliberately NOT a raw filesystem path a caller ever sees or supplies —
the whole point of routing uploads through `POST /upload` first (see the
v2 master build prompt, `claude/ANTI_CASSIOPEIA_V2_MASTER_BUILD_PROMPT.md`
in the project docs) is that `robotics.py`'s `document_id` context field
never has to trust a caller-supplied path the way `ml_data.py`'s
`dataset_path`/`fpga_embedded.py`'s `report_path` historically had to be
hardened against (see `_path_safety.py`) — an opaque token that only
resolves through this store's own dict has no traversal surface at all.

Stores EXTRACTED TEXT (via `retrieval.document_ingest.extract_text`), not
raw file bytes — the upload endpoint extracts once at upload time, so
every later `/verify` call re-reads already-plain-text content, not a PDF
it has to re-parse per request.

Same discipline `api/server.py`'s own rate-limit buckets already
established for unbounded-growth state (see that module's own
`_MAX_TRACKED_BUCKETS`/`_BUCKET_IDLE_TTL_SECONDS` comments): a hard cap
plus idle-first eviction, checked right before a new entry is added, so
this dict never actually exceeds the cap even transiently. HONEST
LIMITATION, same as the rate limiter: this is per-process, in-memory
state, not shared across multiple worker processes or persisted across a
restart -- an uploaded document does not survive a redeploy or a second
Cloud Run instance being spun up. Stated plainly, not silently assumed
away (same convention `server.py`'s own docstring already uses).

OWNERSHIP (v3 §2.1): every document now carries the SHA-256 hash of the
API key that uploaded it (`owner_key_hash`), and `list_for_owner()` scopes
a caller to their own uploads -- added so "search across my documents"
(pooled BYOE search) doesn't become "search across every caller's
documents", a real scope violation once more than one caller shares this
server (which a public hackathon demo already risks: the demo key is
shared by anyone who visits the site). HONEST LIMITATION, stated plainly:
`list_for_owner()` under the shared demo key means "every demo-key
visitor's documents, pooled together" -- expected and fine for a
hackathon demo (anyone using the demo key is already trusting a shared,
rate-limited, temporary sandbox), but this is NOT real per-user isolation
under that key. A caller using their own real `ANTICASSIOPEIA_API_KEY`
gets genuine isolation (no one else has that key). Direct `get()` by
document_id is completely unaffected by any of this -- see that method's
own docstring.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

#: How long an uploaded document stays referenceable after upload, in
#: seconds. 24h -- generous enough for a real working session, short
#: enough that this doesn't quietly become a permanent, unbounded corpus
#: addition (see the v2 master build prompt §3.1: uploads are explicitly
#: NOT permanent corpus additions).
UPLOAD_TTL_SECONDS = 24.0 * 3600.0

#: Same reasoning as server.py's _MAX_TRACKED_BUCKETS -- a hard cap so a
#: caller cycling through many uploads (or many distinct callers, once
#: this supports more than one API key) can't grow this dict unboundedly
#: before TTL eviction ever gets a chance to run.
_MAX_TRACKED_DOCUMENTS = 1_000


@dataclass(frozen=True)
class StoredDocument:
    document_id: str
    filename: str
    text: str
    size_bytes: int
    uploaded_at: float  # time.monotonic() -- for TTL/idle comparison, not wall-clock display
    #: v3 §2.1: a SHA-256 hash of the API key that uploaded this document --
    #: never the raw key (defense in depth even though this is server-side-
    #: only memory, never persisted to disk or logged). Added so a caller
    #: can discover/pool-search across "their own" uploads (see
    #: list_for_owner below and api/server.py's GET /documents and pooled
    #: BYOE search) without this store becoming a flat global namespace any
    #: valid key could enumerate. direct get(document_id) lookup (unchanged
    #: below) deliberately does NOT check this field -- every existing
    #: single-document /verify and /verify/project flow keeps working
    #: exactly as before, regardless of who uploaded the document being
    #: referenced by its own opaque, unguessable id.
    owner_key_hash: str


class UploadStore:
    """Thread-safe in-memory document store. One instance shared across
    requests (same pattern as server.py's module-level `_buckets` dict)."""

    def __init__(self, ttl_seconds: float = UPLOAD_TTL_SECONDS, max_documents: int = _MAX_TRACKED_DOCUMENTS) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_documents = max_documents
        self._documents: dict[str, StoredDocument] = {}
        self._lock = threading.RLock()

    def put(self, filename: str, text: str, size_bytes: int, owner_key_hash: str) -> StoredDocument:
        with self._lock:
            self._evict_expired_and_make_room()
            document_id = secrets.token_urlsafe(32)
            doc = StoredDocument(
                document_id=document_id,
                filename=filename,
                text=text,
                size_bytes=size_bytes,
                uploaded_at=time.monotonic(),
                owner_key_hash=owner_key_hash,
            )
            self._documents[document_id] = doc
            return doc

    def get(self, document_id: str) -> StoredDocument | None:
        """Returns None for an unknown OR expired document_id -- caller
        can't distinguish "never existed" from "expired", same as how a
        rejected API key gives no information about whether it was ever
        valid -- not a security-critical distinction here, but consistent.

        Deliberately UNCHANGED by v3 §2.1's ownership addition: a direct
        document_id lookup never checks owner_key_hash -- every existing
        single-document flow (robotics BYOE document_id, /verify/project's
        per-claim document_id) keeps working exactly as before, regardless
        of who uploaded it. Ownership only gates the NEW list_for_owner()
        below, never this."""
        with self._lock:
            doc = self._documents.get(document_id)
            if doc is None:
                return None
            if time.monotonic() - doc.uploaded_at > self._ttl_seconds:
                del self._documents[document_id]
                return None
            return doc

    def list_for_owner(self, owner_key_hash: str) -> list[StoredDocument]:
        """Returns `owner_key_hash`'s own currently-valid (non-expired)
        documents, most-recently-uploaded first. Powers GET /documents and
        pooled BYOE search (v3 §2.2/§2.3) -- the only two places this store
        is asked "which documents belong to this caller" rather than "give
        me the one document at this id". Does NOT evict expired entries
        for OTHER owners as a side effect -- eviction stays put()'s job
        (see _evict_expired_and_make_room); this is a read-only filter over
        whatever's currently live, same as get()'s own expiry check."""
        with self._lock:
            now = time.monotonic()
            live = [
                d for d in self._documents.values()
                if d.owner_key_hash == owner_key_hash and now - d.uploaded_at <= self._ttl_seconds
            ]
            return sorted(live, key=lambda d: d.uploaded_at, reverse=True)

    def _evict_expired_and_make_room(self) -> None:
        """Called with the lock already held, right before adding a new
        entry -- same "triggers at >= cap, not > cap" discipline as
        server.py's _make_room_for_one_more, so the dict never actually
        exceeds the cap even transiently."""
        now = time.monotonic()
        for doc_id in [k for k, d in self._documents.items() if now - d.uploaded_at > self._ttl_seconds]:
            del self._documents[doc_id]
        if len(self._documents) >= self._max_documents:
            by_age = sorted(self._documents.items(), key=lambda kv: kv[1].uploaded_at)
            for doc_id, _doc in by_age[: len(self._documents) - self._max_documents + 1]:
                del self._documents[doc_id]
