"""
Tests for GET /documents (v3 §2.2) -- proves the ownership plumbing added
to UploadStore in §2.1 actually works end-to-end over real HTTP: a caller
only ever sees their OWN uploads, scoped by their own API key, same auth
as /verify, reusing /verify's rate-limit bucket (see server.py's own
docstring on that endpoint for why it doesn't need a dedicated one).
"""

import io

import pytest
from fastapi.testclient import TestClient

import anticassiopeia.api.server as server_mod
from anticassiopeia.api.server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
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
    monkeypatch.delenv("ANTICASSIOPEIA_DEMO_API_KEY", raising=False)


def _upload(filename: str, content: bytes, api_key: str) -> str:
    resp = client.post(
        "/upload",
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["document_id"]


def _documents(api_key: str):
    return client.get("/documents", headers={"X-API-Key": api_key})


def test_documents_without_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.get("/documents")
    assert resp.status_code == 401


def test_documents_lists_only_this_keys_own_uploads(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "key-a")
    monkeypatch.setenv("ANTICASSIOPEIA_DEMO_API_KEY", "key-b")
    _upload("mine.txt", b"my content", api_key="key-a")
    _upload("not-mine.txt", b"someone else's content", api_key="key-b")

    resp = _documents("key-a")
    assert resp.status_code == 200
    filenames = [d["filename"] for d in resp.json()["documents"]]
    assert filenames == ["mine.txt"]


def test_documents_returns_empty_list_for_a_key_with_no_uploads(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _documents("the-real-key")
    assert resp.status_code == 200
    assert resp.json()["documents"] == []


def test_documents_includes_id_filename_size_and_a_positive_ttl(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("a.txt", b"hello world", api_key="the-real-key")
    resp = _documents("the-real-key")
    entry = resp.json()["documents"][0]
    assert entry["document_id"] == doc_id
    assert entry["filename"] == "a.txt"
    assert entry["size_bytes"] == 11
    assert 0 < entry["seconds_until_expiry"] <= server_mod.upload_store._ttl_seconds


def test_documents_most_recent_first(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    _upload("first.txt", b"x", api_key="the-real-key")
    _upload("second.txt", b"x", api_key="the-real-key")
    resp = _documents("the-real-key")
    filenames = [d["filename"] for d in resp.json()["documents"]]
    assert filenames == ["second.txt", "first.txt"]


def test_documents_reuses_verifys_rate_limit_bucket_not_a_separate_one(monkeypatch):
    """server.py's own docstring: /documents is cheap, so it deliberately
    reuses /verify's bucket instead of getting its own -- prove that
    sharing actually happens (hammering /documents trips the SAME budget
    /verify uses, not an independent one)."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    statuses = [_documents("the-real-key").status_code for _ in range(server_mod._RATE_LIMIT_BURST + 2)]
    assert 429 in statuses[server_mod._RATE_LIMIT_BURST :]
