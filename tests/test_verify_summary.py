"""
Tests for /verify's opt-in context.include_summary (a short, best-effort,
LLM-generated gloss of the already-computed verdict -- commentary, never
a new source of evidence). All OFFLINE: server_mod._summary_client is
monkeypatched to a fake, and server_mod.engine's robotics domain is
monkeypatched to a fixed-evidence fake -- no live Nebius call needed.
"""

import pytest
from fastapi.testclient import TestClient

import anticassiopeia.api.server as server_mod
from anticassiopeia.api.server import app
from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence
from anticassiopeia.llm.nebius_client import NebiusClientError

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    yield
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()


@pytest.fixture(autouse=True)
def _no_api_key_by_default(monkeypatch):
    monkeypatch.delenv("ANTICASSIOPEIA_API_KEY", raising=False)


class _FixedEvidenceAdapter(DomainAdapter):
    domain_name = "robotics"
    implemented = True

    def __init__(self, stance: str = "supports"):
        self._stance = stance

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        return [Evidence(source="fixed", snippet="x", stance=self._stance, trust=0.9)]


class _FakeSummaryClient:
    def __init__(self, response: str | Exception):
        self._response = response
        self.last_prompt: str | None = None

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.2) -> str:
        self.last_prompt = prompt
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _verify(context: dict, api_key: str = "the-real-key"):
    return client.post(
        "/verify",
        json={"text": "x", "domain": "robotics", "context": context},
        headers={"X-API-Key": api_key},
    )


def test_summary_is_absent_by_default(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setitem(server_mod.engine._domains, "robotics", _FixedEvidenceAdapter())
    monkeypatch.setattr(server_mod, "_summary_client", _FakeSummaryClient("should never be called"))
    resp = _verify({})
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" not in body
    assert "summary_error" not in body


def test_summary_is_generated_when_opted_in(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setitem(server_mod.engine._domains, "robotics", _FixedEvidenceAdapter())
    fake = _FakeSummaryClient("The evidence supports this claim.")
    monkeypatch.setattr(server_mod, "_summary_client", fake)
    resp = _verify({"include_summary": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == "The evidence supports this claim."
    assert "summary_error" not in body
    # the prompt is built from the ALREADY-COMPUTED verdict, not raw claim text
    assert "confirmed" in fake.last_prompt


def test_summary_failure_never_fails_the_real_verdict(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setitem(server_mod.engine._domains, "robotics", _FixedEvidenceAdapter())
    monkeypatch.setattr(server_mod, "_summary_client", _FakeSummaryClient(NebiusClientError("Nebius Token Factory returned 500")))
    resp = _verify({"include_summary": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed"  # the real verdict is unaffected
    assert "summary" not in body
    assert "Summary generation failed" in body["summary_error"]


def test_summary_client_unavailable_is_a_named_summary_error_not_a_crash(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setitem(server_mod.engine._domains, "robotics", _FixedEvidenceAdapter())
    monkeypatch.setattr(server_mod, "_summary_client", None)
    monkeypatch.setattr(server_mod, "_summary_client_error", "NEBIUS_API_KEY not set.")
    resp = _verify({"include_summary": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed"
    assert "NEBIUS_API_KEY not set" in body["summary_error"]


def test_summary_works_for_ml_data_which_otherwise_makes_zero_llm_calls(monkeypatch):
    """The actual point of "opt-in regardless of domain": a caller can pay
    for a summary even on a domain that's normally free local computation."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    fake = _FakeSummaryClient("The dataset's mean matches the claimed value.")
    monkeypatch.setattr(server_mod, "_summary_client", fake)
    resp = client.post(
        "/verify",
        json={
            "text": "the mean voltage is 5.0", "domain": "ml_data",
            "context": {
                "dataset_path": "evals/fixtures/sample_measurements.csv",
                "column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05,
                "include_summary": True,
            },
        },
        headers={"X-API-Key": "the-real-key"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed"
    assert body["summary"] == "The dataset's mean matches the claimed value."
