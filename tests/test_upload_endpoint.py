"""
Tests for POST /upload and /verify's document_id resolution (v2 "bring
your own evidence" build) -- real HTTP, real multipart upload, real
extract_text(), real UploadStore. Only the LLM is out of scope here (no
NEBIUS_API_KEY in test env): these tests cover the API-layer plumbing
(auth, rate limit, size cap, extension allowlist, document_id resolution/
error handling), not the live robotics BYOE pipeline itself (see
tests/test_robotics_byoe.py for that, fully offline via a fake client).
"""

import io

import pytest
from fastapi.testclient import TestClient

import anticassiopeia.api.server as server_mod
from anticassiopeia.api.server import app
from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    """Mirrors test_api_server.py's own isolation fixture, extended to the
    two pieces of module-level state this file's tests also touch: the
    upload-specific rate-limit bucket and the upload store itself."""
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    server_mod._upload_buckets.clear()
    server_mod.upload_store._documents.clear()
    yield
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    server_mod._upload_buckets.clear()
    server_mod.upload_store._documents.clear()


@pytest.fixture(autouse=True)
def _no_api_key_by_default(monkeypatch):
    monkeypatch.delenv("ANTICASSIOPEIA_API_KEY", raising=False)


def _upload(filename: str, content: bytes, api_key: str = "the-real-key"):
    return client.post(
        "/upload",
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        headers={"X-API-Key": api_key},
    )


# --- /upload: auth + rate limit, same discipline as /verify ---


def test_upload_without_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.post("/upload", files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")})
    assert resp.status_code == 401


def test_upload_with_correct_key_succeeds(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _upload("a.txt", b"hello world")
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "a.txt"
    assert body["size_bytes"] == 11
    assert len(body["document_id"]) > 32


def test_upload_rate_limit_trips_after_the_burst_allowance(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    statuses = [_upload(f"{i}.txt", b"hello").status_code for i in range(server_mod._UPLOAD_RATE_LIMIT_BURST + 2)]
    assert statuses[: server_mod._UPLOAD_RATE_LIMIT_BURST] == [200] * server_mod._UPLOAD_RATE_LIMIT_BURST
    assert 429 in statuses[server_mod._UPLOAD_RATE_LIMIT_BURST :]


def test_upload_rate_limit_is_separate_from_verify_rate_limit(monkeypatch):
    """server.py's own stated reasoning for a SEPARATE bucket: hammering
    /upload must not also exhaust the caller's /verify budget."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    for i in range(server_mod._UPLOAD_RATE_LIMIT_BURST + 2):
        _upload(f"{i}.txt", b"hello")
    resp = client.post(
        "/verify",
        json={"text": "x", "domain": "ml_data", "context": {}},
        headers={"X-API-Key": "the-real-key"},
    )
    assert resp.status_code != 429


# --- /upload: extension allowlist, size cap, empty file ---


def test_upload_rejects_an_unsupported_extension(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _upload("archive.zip", b"PK\x03\x04whatever")
    assert resp.status_code == 400
    assert "Unsupported file extension" in resp.json()["detail"]


def test_upload_rejects_an_empty_file(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _upload("empty.txt", b"")
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_upload_rejects_a_file_over_the_size_cap(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setattr(server_mod, "_MAX_UPLOAD_BYTES", 10)
    resp = _upload("big.txt", b"0123456789 this is definitely more than 10 bytes")
    assert resp.status_code == 413
    assert "byte limit" in resp.json()["detail"]


def test_upload_rejects_a_file_that_extracts_to_no_usable_text(monkeypatch):
    """A .csv with an unsupported-shape payload still round-trips as plain
    UTF-8 text in this ingestion pipeline (.csv is in the plain-text set),
    so use a real malformed-PDF case instead to exercise the 422 path --
    same DocumentIngestError -> 422 mapping server.py's /upload declares."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _upload("broken.pdf", b"%PDF-1.4 not actually a valid pdf structure at all")
    assert resp.status_code == 422
    assert "could not be read as a PDF" in resp.json()["detail"]


# --- /verify: document_id resolution ---


class _CapturingAdapter(DomainAdapter):
    """Records the Claim it actually received -- used to prove /verify
    resolved document_id -> document_text/document_filename in context
    BEFORE the domain adapter ever ran, without needing a live LLM key."""

    domain_name = "robotics"
    implemented = True

    def __init__(self):
        self.received_claim: Claim | None = None

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        self.received_claim = claim
        return [Evidence(source="capture", snippet="x", stance="supports", trust=0.9)]


def test_verify_with_unknown_document_id_is_a_clean_400_not_a_silent_fallback(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.post(
        "/verify",
        json={"text": "x", "domain": "robotics", "context": {"document_id": "never-issued"}},
        headers={"X-API-Key": "the-real-key"},
    )
    assert resp.status_code == 400
    assert "Unknown or expired document_id" in resp.json()["detail"]


def test_verify_with_non_string_document_id_is_a_clean_400_not_a_crash(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.post(
        "/verify",
        json={"text": "x", "domain": "robotics", "context": {"document_id": 12345}},
        headers={"X-API-Key": "the-real-key"},
    )
    assert resp.status_code == 400
    assert "Unknown or expired document_id" in resp.json()["detail"]


def test_verify_with_valid_document_id_injects_text_and_filename_before_the_adapter_runs(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    upload_resp = _upload("manual.txt", b"The Widget Mk4 is IP68 rated.")
    document_id = upload_resp.json()["document_id"]

    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)

    resp = client.post(
        "/verify",
        json={"text": "Is the Widget Mk4 IP68 rated?", "domain": "robotics", "context": {"document_id": document_id}},
        headers={"X-API-Key": "the-real-key"},
    )
    assert resp.status_code == 200
    assert fake_adapter.received_claim is not None
    assert fake_adapter.received_claim.context["document_text"] == "The Widget Mk4 is IP68 rated."
    assert fake_adapter.received_claim.context["document_filename"] == "manual.txt"
    # "document_id" itself is still passed through (resolution adds keys,
    # it doesn't strip the original) -- not load-bearing for any adapter,
    # but no reason to silently drop caller-supplied context either.
    assert fake_adapter.received_claim.context["document_id"] == document_id


def test_verify_without_document_id_leaves_context_untouched(monkeypatch):
    """No regression: a normal /verify call with no document_id at all gets
    exactly the context it sent, same as before this feature existed."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)

    resp = client.post(
        "/verify",
        json={"text": "x", "domain": "robotics", "context": {"depth_m": 500.0}},
        headers={"X-API-Key": "the-real-key"},
    )
    assert resp.status_code == 200
    assert fake_adapter.received_claim.context == {"depth_m": 500.0}


def test_document_expires_after_its_ttl_and_then_resolves_as_unknown(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    upload_resp = _upload("manual.txt", b"some real text content")
    document_id = upload_resp.json()["document_id"]
    # force the already-stored document to look expired, rather than
    # sleeping past a real 24h TTL in a test
    doc = server_mod.upload_store._documents[document_id]
    server_mod.upload_store._documents[document_id] = doc.__class__(
        document_id=doc.document_id, filename=doc.filename, text=doc.text,
        size_bytes=doc.size_bytes, uploaded_at=doc.uploaded_at - server_mod.upload_store._ttl_seconds - 1,
    )
    resp = client.post(
        "/verify",
        json={"text": "x", "domain": "robotics", "context": {"document_id": document_id}},
        headers={"X-API-Key": "the-real-key"},
    )
    assert resp.status_code == 400
    assert "Unknown or expired document_id" in resp.json()["detail"]
