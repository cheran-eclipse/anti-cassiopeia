"""
Tests for v3 §1.1: plain POST /verify's document_id resolution generalized
to quant/silicon (previously those two domains silently no-op'd on
an uploaded document -- see this fix's own commit message for the full
gap description). Real HTTP, real multipart upload, real UploadStore, real
quant.py/silicon.py computation against a real scratch file this
endpoint writes and deletes -- same "real app, real computation" standard
tests/test_project_endpoint.py already holds the project endpoint to, now
applied to the single-claim endpoint.
"""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import anticassiopeia.api.server as server_mod
from anticassiopeia.api.server import app

client = TestClient(app)

_CSV_FIXTURE = b"trial,voltage,current\n1,4.98,1.01\n2,5.02,0.99\n3,5.01,1.00\n4,4.99,1.02\n"
_SVD_FIXTURE = Path("evals/fixtures/esp32c2_register_map_excerpt.svd").read_bytes()


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


def _upload(filename: str, content: bytes, api_key: str = "the-real-key") -> str:
    resp = client.post(
        "/upload",
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["document_id"]


def _verify(text: str, domain: str, context: dict, api_key: str = "the-real-key"):
    return client.post(
        "/verify",
        json={"text": text, "domain": domain, "context": context},
        headers={"X-API-Key": api_key},
    )


def test_verify_ml_data_with_document_id_computes_a_real_statistic(monkeypatch):
    """Before this fix: quant.py never read document_text, so this call
    would silently ignore the upload and return an honest gap/UNDETERMINED
    instead of actually checking the real uploaded CSV."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("measurements.csv", _CSV_FIXTURE)
    resp = _verify(
        "the mean voltage is 5.0", "quant",
        {"document_id": doc_id, "column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed"
    assert "Re-computed mean(voltage)" in body["evidence"][0]["snippet"]


def test_verify_fpga_embedded_with_document_id_computes_a_real_register_check(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("esp32c2.svd", _SVD_FIXTURE)
    resp = _verify(
        "RNG's DATA register is at offset 0xB0", "silicon",
        {
            "document_id": doc_id, "metric": "register_offset", "peripheral": "RNG",
            "register": "DATA", "comparator": "==", "expected_value": "0xB0",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "confirmed"


def test_verify_research_web_with_document_id_is_a_named_400_not_a_silent_no_op(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("manual.txt", b"some real text content")
    resp = _verify("some claim", "searchlight", {"document_id": doc_id})
    assert resp.status_code == 400
    assert "does not support a document_id-linked claim" in resp.json()["detail"]


def test_verify_ml_data_scratch_file_is_cleaned_up_after_the_request(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    before = set(server_mod._PROJECT_SCRATCH_DIR.iterdir()) if server_mod._PROJECT_SCRATCH_DIR.exists() else set()
    doc_id = _upload("measurements.csv", _CSV_FIXTURE)
    _verify(
        "the mean voltage is 5.0", "quant",
        {"document_id": doc_id, "column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05},
    )
    after = set(server_mod._PROJECT_SCRATCH_DIR.iterdir())
    assert after == before  # the one scratch file this call wrote was deleted, nothing left behind


def test_verify_ml_data_scratch_file_is_cleaned_up_even_when_the_claim_errors(monkeypatch):
    """The scratch file must be deleted in a finally -- even when the claim
    itself fails to confirm/contradict (a missing required context field is
    still a real, non-crashing UNDETERMINED from the adapter, not an
    exception, but this proves cleanup doesn't depend on a happy path)."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    before = set(server_mod._PROJECT_SCRATCH_DIR.iterdir()) if server_mod._PROJECT_SCRATCH_DIR.exists() else set()
    doc_id = _upload("measurements.csv", _CSV_FIXTURE)
    resp = _verify("the mean voltage is 5.0", "quant", {"document_id": doc_id})
    assert resp.status_code == 200  # a missing 'column'/'stat' is an honest gap, not an error response
    after = set(server_mod._PROJECT_SCRATCH_DIR.iterdir())
    assert after == before


def test_verify_without_document_id_is_unaffected_for_ml_data(monkeypatch):
    """No regression: a normal path-based /verify call (no document_id at
    all) for quant must behave exactly as before this change."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _verify(
        "the mean voltage is 5.0", "quant",
        {"dataset_path": "evals/fixtures/sample_measurements.csv", "column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "confirmed"
