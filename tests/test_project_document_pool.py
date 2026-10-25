"""
Tests for v3 §2.4: /verify/project's per-claim document_pool option (the
same pooled-search resolution plain /verify gained in §2.3, now usable
inside a batch -- so one project call can mix claims pinned to one
specific document with claims that search the whole caller's upload
pool). Real HTTP, real uploads, real UploadStore/ownership -- the live
robotics BYOE pooled pipeline itself is covered offline in
tests/test_robotics_byoe_pool.py.
"""

import io

import pytest
from fastapi.testclient import TestClient

import anticassiopeia.api.server as server_mod
from anticassiopeia.api.server import app
from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

client = TestClient(app)

_CSV_FIXTURE = b"trial,voltage,current\n1,4.98,1.01\n2,5.02,0.99\n3,5.01,1.00\n4,4.99,1.02\n"


@pytest.fixture(autouse=True)
def _reset_state():
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    server_mod._upload_buckets.clear()
    server_mod._project_buckets.clear()
    server_mod.upload_store._documents.clear()
    yield
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    server_mod._upload_buckets.clear()
    server_mod._project_buckets.clear()
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
    domain_name = "robotics"
    implemented = True

    def __init__(self, stance: str = "supports"):
        self.received_claims: list[Claim] = []
        self._stance = stance

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        self.received_claims.append(claim)
        return [Evidence(source="capture", snippet="x", stance=self._stance, trust=0.9)]


def _project(claims: list[dict], api_key: str = "the-real-key"):
    return client.post("/verify/project", json={"claims": claims}, headers={"X-API-Key": api_key})


def test_project_claim_with_document_id_and_document_pool_is_a_per_claim_error(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("a.txt", b"hello", api_key="the-real-key")
    resp = _project([{"text": "x", "document_id": doc_id, "document_pool": True}])
    assert resp.status_code == 200  # the BATCH succeeds; the one bad claim gets a named error
    claim0 = resp.json()["claims"][0]
    assert "either document_id or document_pool, not both" in claim0["error"]
    assert resp.json()["rollup"]["state"] == "undetermined"


def test_project_document_pool_on_a_non_robotics_domain_is_a_named_per_claim_error(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _project([{"text": "x", "document_pool": True, "domain": "ml_data"}])
    claim0 = resp.json()["claims"][0]
    assert "does not support document_pool search (robotics-only)" in claim0["error"]


def test_project_document_pool_with_omitted_domain_defaults_to_robotics(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)
    resp = _project([{"text": "x", "document_pool": True}])
    assert resp.status_code == 200
    claim0 = resp.json()["claims"][0]
    assert claim0["domain"] == "robotics"
    assert claim0["error"] is None


def test_project_document_pool_injects_only_this_callers_own_uploads(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "key-a")
    monkeypatch.setenv("ANTICASSIOPEIA_DEMO_API_KEY", "key-b")
    _upload("mine.txt", b"my content", api_key="key-a")
    _upload("not-mine.txt", b"someone else's content", api_key="key-b")

    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)
    resp = _project([{"text": "x", "document_pool": True}], api_key="key-a")
    assert resp.status_code == 200
    pool_items = fake_adapter.received_claims[0].context["document_pool_items"]
    assert pool_items == [("mine.txt", "my content")]


def test_project_mixes_a_document_id_claim_and_a_document_pool_claim_in_one_batch(monkeypatch):
    """The actual point of §2.4: one project call, some claims pinned to a
    specific document, others searching the whole pool."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    csv_doc = _upload("measurements.csv", _CSV_FIXTURE, api_key="the-real-key")
    _upload("manual.txt", b"The Widget Mk4 is IP68 rated.", api_key="the-real-key")

    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)

    resp = _project([
        {"text": "mean voltage is 5.0", "document_id": csv_doc,
         "context": {"column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05}},
        {"text": "the widget is IP68 rated", "document_pool": True},
    ])
    body = resp.json()
    assert all(c["error"] is None for c in body["claims"])
    assert body["claims"][0]["domain"] == "ml_data"
    assert body["claims"][1]["domain"] == "robotics"
    pool_items = fake_adapter.received_claims[0].context["document_pool_items"]
    # pool search sees BOTH uploads (document_id pinning doesn't remove a
    # document from the pool -- they're independent ways to reference it)
    assert {f for f, _ in pool_items} == {"measurements.csv", "manual.txt"}
    assert body["rollup"]["state"] == "confirmed"


def test_project_document_pool_empty_is_a_clean_gap_not_an_error(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _project([{"text": "anything", "document_pool": True}])
    assert resp.status_code == 200
    claim0 = resp.json()["claims"][0]
    assert claim0["error"] is None
    assert claim0["verdict"]["state"] == "undetermined"
