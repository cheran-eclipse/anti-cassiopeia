"""
Tests for v3 §2.3's server-side pooled-search resolution in plain
POST /verify: context.document_pool=true resolves to the CALLING key's
own currently-valid uploads (never another caller's), capped at
_MAX_POOL_DOCUMENTS, injected as context["document_pool_items"] before
any domain adapter runs -- real HTTP, real multipart uploads, real
UploadStore/ownership. The live substrate BYOE pooled pipeline itself is
covered offline in tests/test_substrate_byoe_pool.py; this file is pure
API-layer plumbing, same split test_upload_endpoint.py already
established for the single-document case.
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


class _CapturingAdapter(DomainAdapter):
    domain_name = "substrate"
    implemented = True

    def __init__(self):
        self.received_claim: Claim | None = None

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        self.received_claim = claim
        return [Evidence(source="capture", snippet="x", stance="supports", trust=0.9)]


def _verify(text: str, domain: str, context: dict, api_key: str = "the-real-key"):
    return client.post("/verify", json={"text": text, "domain": domain, "context": context}, headers={"X-API-Key": api_key})


def test_document_id_and_document_pool_together_is_a_clean_400(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("a.txt", b"hello", api_key="the-real-key")
    resp = _verify("x", "substrate", {"document_id": doc_id, "document_pool": True})
    assert resp.status_code == 400
    assert "either document_id or document_pool, not both" in resp.json()["detail"]


def test_document_pool_on_a_non_robotics_domain_is_a_named_400(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _verify("x", "quant", {"document_pool": True})
    assert resp.status_code == 400
    assert "does not support document_pool search (substrate-only)" in resp.json()["detail"]


def test_document_pool_injects_only_this_callers_own_uploads(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "key-a")
    monkeypatch.setenv("ANTICASSIOPEIA_DEMO_API_KEY", "key-b")
    _upload("mine.txt", b"my content", api_key="key-a")
    _upload("not-mine.txt", b"someone else's content", api_key="key-b")

    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "substrate", fake_adapter)

    resp = _verify("x", "substrate", {"document_pool": True}, api_key="key-a")
    assert resp.status_code == 200
    pool_items = fake_adapter.received_claim.context["document_pool_items"]
    assert pool_items == [("mine.txt", "my content")]
    assert fake_adapter.received_claim.context["document_pool_total_available"] == 1


def test_document_pool_with_no_uploads_resolves_to_an_empty_pool_not_an_error(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "substrate", fake_adapter)
    resp = _verify("x", "substrate", {"document_pool": True})
    assert resp.status_code == 200
    assert fake_adapter.received_claim.context["document_pool_items"] == []
    assert fake_adapter.received_claim.context["document_pool_total_available"] == 0


def test_document_pool_is_capped_and_total_available_is_the_real_count(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setattr(server_mod, "_MAX_POOL_DOCUMENTS", 2)
    for i in range(4):
        server_mod._upload_buckets.clear()  # this test uploads more than the burst allows -- not what it's testing
        _upload(f"{i}.txt", f"content {i}".encode(), api_key="the-real-key")

    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "substrate", fake_adapter)
    resp = _verify("x", "substrate", {"document_pool": True})
    assert resp.status_code == 200
    pool_items = fake_adapter.received_claim.context["document_pool_items"]
    assert len(pool_items) == 2  # capped
    assert fake_adapter.received_claim.context["document_pool_total_available"] == 4  # real total, not silently fewer
    # most-recently-uploaded first
    assert pool_items[0][0] == "3.txt"
    assert pool_items[1][0] == "2.txt"


def test_document_pool_most_recent_items_preserve_real_text(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    _upload("widget.txt", b"The Widget Mk4 is IP68 rated.", api_key="the-real-key")
    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "substrate", fake_adapter)
    resp = _verify("x", "substrate", {"document_pool": True})
    assert resp.status_code == 200
    filename, text = fake_adapter.received_claim.context["document_pool_items"][0]
    assert filename == "widget.txt"
    assert text == "The Widget Mk4 is IP68 rated."
