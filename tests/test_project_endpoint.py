"""
Tests for POST /verify/project (v2 "bring your own evidence", Phase 2):
multi-document domain sniffing + per-claim routing + rollup via
core.compound's existing AND-semantics rollup(). Real uploads, real CSV/
SVD/Vivado-report fixture content, real ml_data.py/fpga_embedded.py
adapters computing against real scratch files this endpoint writes --
only the robotics/research_web domains (which need a live LLM) are
exercised through a capturing fake adapter here, same pattern
test_upload_endpoint.py already established.
"""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import anticassiopeia.api.server as server_mod
from anticassiopeia.api.server import app
from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

client = TestClient(app)

_SVD_FIXTURE = Path("evals/fixtures/esp32c2_register_map_excerpt.svd").read_bytes()
_RPT_WITH_BANNER = Path("evals/fixtures/vivado_timing_report_single_corner.rpt").read_bytes()
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


def _upload(filename: str, content: bytes, api_key: str = "the-real-key") -> str:
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


# --- request validation ---


def test_project_requires_a_nonempty_claims_list(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _project([])
    assert resp.status_code == 400
    assert "non-empty" in resp.json()["detail"]


def test_project_rejects_too_many_claims(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    claims = [{"text": f"claim {i}", "domain": "research_web"} for i in range(server_mod._MAX_CLAIMS_PER_PROJECT + 1)]
    resp = _project(claims)
    assert resp.status_code == 400
    assert "at most" in resp.json()["detail"]


def test_project_without_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.post("/verify/project", json={"claims": [{"text": "x", "domain": "research_web"}]})
    assert resp.status_code == 401


def test_project_rate_limit_trips_after_the_burst_allowance_and_is_separate_from_verify(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    claims = [{"text": "x", "domain": "ml_data", "context": {}}]
    statuses = [_project(claims).status_code for _ in range(server_mod._PROJECT_RATE_LIMIT_BURST + 2)]
    assert statuses[: server_mod._PROJECT_RATE_LIMIT_BURST].count(429) == 0
    assert 429 in statuses[server_mod._PROJECT_RATE_LIMIT_BURST :]
    verify_resp = client.post(
        "/verify", json={"text": "x", "domain": "ml_data", "context": {}}, headers={"X-API-Key": "the-real-key"}
    )
    assert verify_resp.status_code != 429


# --- per-claim document_id resolution ---


def test_project_with_unknown_document_id_is_a_per_claim_error_not_a_batch_failure(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _project([{"text": "x", "document_id": "never-issued"}])
    assert resp.status_code == 200
    body = resp.json()
    assert body["claims"][0]["error"] is not None
    assert "Unknown or expired document_id" in body["claims"][0]["error"]
    assert body["rollup"]["state"] == "undetermined"


# --- deterministic domain sniffing, real adapters, real computation ---


def test_project_sniffs_csv_to_ml_data_and_computes_a_real_statistic(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("measurements.csv", _CSV_FIXTURE)
    resp = _project([{
        "text": "the mean voltage is 5.0",
        "document_id": doc_id,
        "context": {"column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05},
    }])
    assert resp.status_code == 200
    body = resp.json()
    claim_result = body["claims"][0]
    assert claim_result["domain"] == "ml_data"
    assert claim_result["error"] is None
    assert claim_result["verdict"]["state"] == "confirmed"
    assert "Re-computed mean(voltage)" in claim_result["verdict"]["evidence"][0]["snippet"]


def test_project_sniffs_svd_to_fpga_embedded_register_claim(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("esp32c2.svd", _SVD_FIXTURE)
    resp = _project([{
        "text": "RNG's DATA register is at offset 0xB0",
        "document_id": doc_id,
        "context": {
            "metric": "register_offset", "peripheral": "RNG", "register": "DATA",
            "comparator": "==", "expected_value": "0xB0",
        },
    }])
    assert resp.status_code == 200
    claim_result = resp.json()["claims"][0]
    assert claim_result["domain"] == "fpga_embedded"
    assert claim_result["verdict"]["state"] == "confirmed"


def test_project_sniffs_rpt_with_timing_banner_to_fpga_embedded(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("build.rpt", _RPT_WITH_BANNER)
    resp = _project([{
        "text": "WNS is at least 0.1 ns",
        "document_id": doc_id,
        "context": {"metric": "wns_ns", "comparator": ">=", "expected_value": 0.1},
    }])
    assert resp.status_code == 200
    claim_result = resp.json()["claims"][0]
    assert claim_result["domain"] == "fpga_embedded"
    assert claim_result["verdict"]["state"] == "confirmed"


def test_project_rpt_without_timing_banner_falls_back_to_robotics(monkeypatch):
    """A .rpt extension alone is not trusted as "definitely a Vivado
    report" -- content is cross-checked, same discipline
    fpga_embedded.py's own _is_svd_file() already applies to .xml."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)
    doc_id = _upload("notes.rpt", b"Just some plain notes, not a real Vivado report at all.")
    resp = _project([{"text": "the notes say something", "document_id": doc_id}])
    assert resp.status_code == 200
    claim_result = resp.json()["claims"][0]
    assert claim_result["domain"] == "robotics"
    assert fake_adapter.received_claims[0].context["document_text"] == "Just some plain notes, not a real Vivado report at all."


def test_project_xml_with_device_tag_sniffs_to_fpga_embedded(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("esp32c2.xml", _SVD_FIXTURE)  # same real content, .xml extension this time
    resp = _project([{
        "text": "RNG's DATA register is at offset 0xB0",
        "document_id": doc_id,
        "context": {
            "metric": "register_offset", "peripheral": "RNG", "register": "DATA",
            "comparator": "==", "expected_value": "0xB0",
        },
    }])
    claim_result = resp.json()["claims"][0]
    assert claim_result["domain"] == "fpga_embedded"


def test_project_plain_xml_without_device_tag_sniffs_to_robotics(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)
    doc_id = _upload("data.xml", b"<root><item>just generic xml, no device element</item></root>")
    resp = _project([{"text": "something about this xml", "document_id": doc_id}])
    claim_result = resp.json()["claims"][0]
    assert claim_result["domain"] == "robotics"


def test_project_txt_sniffs_to_robotics_byoe_and_injects_document_text(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)
    doc_id = _upload("manual.txt", b"The Widget Mk4 is IP68 rated.")
    resp = _project([{"text": "Is the Widget Mk4 IP68 rated?", "document_id": doc_id}])
    assert resp.status_code == 200
    claim_result = resp.json()["claims"][0]
    assert claim_result["domain"] == "robotics"
    assert fake_adapter.received_claims[0].context["document_text"] == "The Widget Mk4 is IP68 rated."
    assert fake_adapter.received_claims[0].context["document_filename"] == "manual.txt"


def test_project_caller_can_override_the_sniffed_domain_explicitly(monkeypatch):
    """A .csv would normally sniff to ml_data -- an explicit domain in the
    per-claim request overrides that, same "never override what the
    caller explicitly said" principle as plain /verify."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter()
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)
    doc_id = _upload("measurements.csv", _CSV_FIXTURE)
    resp = _project([{"text": "something about this csv", "document_id": doc_id, "domain": "robotics"}])
    claim_result = resp.json()["claims"][0]
    assert claim_result["domain"] == "robotics"
    assert "voltage" in fake_adapter.received_claims[0].context["document_text"]


def test_project_document_linked_to_an_unsupported_domain_is_a_named_per_claim_error(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    doc_id = _upload("manual.txt", b"some text")
    resp = _project([{"text": "x", "document_id": doc_id, "domain": "research_web"}])
    claim_result = resp.json()["claims"][0]
    assert claim_result["error"] is not None
    assert "does not support a document_id-linked claim" in claim_result["error"]


# --- rollup across multiple claims ---


def test_project_rollup_confirmed_when_every_claim_confirms(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter(stance="supports")
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)
    csv_doc = _upload("measurements.csv", _CSV_FIXTURE)
    txt_doc = _upload("manual.txt", b"The Widget Mk4 is IP68 rated.")
    resp = _project([
        {"text": "mean voltage is 5.0", "document_id": csv_doc,
         "context": {"column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05}},
        {"text": "the widget is IP68 rated", "document_id": txt_doc},
    ])
    body = resp.json()
    assert all(c["error"] is None for c in body["claims"])
    assert body["rollup"]["state"] == "confirmed"


def test_project_rollup_contradicted_when_one_claim_contradicts(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake_adapter = _CapturingAdapter(stance="contradicts")
    monkeypatch.setitem(server_mod.engine._domains, "robotics", fake_adapter)
    csv_doc = _upload("measurements.csv", _CSV_FIXTURE)
    txt_doc = _upload("manual.txt", b"The Widget Mk4 is IP68 rated.")
    resp = _project([
        {"text": "mean voltage is 5.0", "document_id": csv_doc,
         "context": {"column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05}},
        {"text": "the widget is IP68 rated", "document_id": txt_doc},
    ])
    body = resp.json()
    assert body["rollup"]["state"] == "contradicted"


def test_project_rollup_undetermined_when_a_claim_errors_out_but_nothing_contradicts(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _project([
        {"text": "x", "document_id": "never-issued"},
        {"text": "y", "domain": "research_web", "context": {"url": "http://127.0.0.1:1/nope", "quote": "x"}},
    ])
    body = resp.json()
    assert body["rollup"]["state"] == "undetermined"


# --- scratch file lifecycle ---


def test_project_scratch_files_are_cleaned_up_after_the_request(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    before = set(server_mod._PROJECT_SCRATCH_DIR.iterdir()) if server_mod._PROJECT_SCRATCH_DIR.exists() else set()
    doc_id = _upload("measurements.csv", _CSV_FIXTURE)
    _project([{
        "text": "mean voltage is 5.0", "document_id": doc_id,
        "context": {"column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05},
    }])
    after = set(server_mod._PROJECT_SCRATCH_DIR.iterdir())
    assert after == before  # the per-request tempdir was removed, nothing left behind
