"""
Tests for POST /verify/compound (v3 §1.2) -- makes core/compound.py's
decompose_claim()/rollup() (item 20, library-only until now) reachable
over HTTP. All tests here are OFFLINE: server_mod._compound_client is
monkeypatched to a fake (same dual-response convention test_compound.py's
_FakeDecomposeClient already established), and server_mod.engine's
domains are monkeypatched to fixed-evidence fakes -- no live Nebius call,
no real sub-claim retrieval pipeline (that's covered by each domain's own
tests + test_compound.py's offline rollup()/decompose_claim() coverage).
"""

import json

import pytest
from fastapi.testclient import TestClient

import anticassiopeia.api.server as server_mod
from anticassiopeia.api.server import app
from anticassiopeia.core.compound import _FIDELITY_CHECK_SYSTEM_PROMPT
from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    server_mod._compound_buckets.clear()
    yield
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    server_mod._compound_buckets.clear()


@pytest.fixture(autouse=True)
def _no_api_key_by_default(monkeypatch):
    monkeypatch.delenv("ANTICASSIOPEIA_API_KEY", raising=False)


class _FakeDecomposeClient:
    """Same dual-call dispatch as test_compound.py's own fake of the same
    name — decompose_claim() makes a second (fidelity-check) call for any
    multi-part response; defaults to "faithful" so existing single-response
    call sites keep passing unchanged."""

    def __init__(self, response: str | Exception, fidelity_response: str = "faithful"):
        self._response = response
        self._fidelity_response = fidelity_response

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        if system == _FIDELITY_CHECK_SYSTEM_PROMPT:
            return self._fidelity_response
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _FixedEvidenceAdapter(DomainAdapter):
    def __init__(self, domain_name: str, stance: str = "supports"):
        self.domain_name = domain_name
        self.implemented = True
        self._stance = stance
        self.calls: list[Claim] = []

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        self.calls.append(claim)
        return [Evidence(source="fixed", snippet="x", stance=self._stance, trust=0.9)]


def _compound(text: str, context: dict | None = None, api_key: str = "the-real-key"):
    return client.post(
        "/verify/compound",
        json={"text": text, "context": context or {}},
        headers={"X-API-Key": api_key},
    )


def _two_part_decompose(domain_a: str, domain_b: str) -> str:
    return json.dumps({"parts": [{"text": "A", "domain": domain_a}, {"text": "B", "domain": domain_b}]})


# --- auth / request-shape rejections ---


def test_compound_without_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.post("/verify/compound", json={"text": "x", "context": {}})
    assert resp.status_code == 401


def test_compound_rejects_document_id_in_context(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _compound("x", context={"document_id": "abc"})
    assert resp.status_code == 400
    assert "not available for document-bound claims" in resp.json()["detail"]


def test_compound_rejects_document_pool_in_context(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = _compound("x", context={"document_pool": True})
    assert resp.status_code == 400
    assert "not available for document-bound claims" in resp.json()["detail"]


def test_compound_rate_limit_trips_after_the_burst_allowance_and_is_separate_from_other_endpoints(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setattr(server_mod, "_compound_client", _FakeDecomposeClient(RuntimeError("never reached")))
    statuses = [_compound("x").status_code for _ in range(server_mod._COMPOUND_RATE_LIMIT_BURST + 2)]
    assert 429 in statuses[server_mod._COMPOUND_RATE_LIMIT_BURST :]
    other_resp = client.post(
        "/verify", json={"text": "x", "domain": "searchlight", "context": {"url": "http://127.0.0.1:1/nope", "quote": "x"}},
        headers={"X-API-Key": "the-real-key"},
    )
    assert other_resp.status_code != 429


def test_compound_client_unavailable_is_a_clean_503_not_a_crash(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setattr(server_mod, "_compound_client", None)
    monkeypatch.setattr(server_mod, "_compound_client_error", "NEBIUS_API_KEY not set.")
    resp = _compound("x")
    assert resp.status_code == 503
    assert "NEBIUS_API_KEY not set" in resp.json()["detail"]


# --- decomposition failure / cap enforcement ---


def test_compound_decomposition_failure_is_an_honest_undetermined_not_a_crash(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setattr(server_mod, "_compound_client", _FakeDecomposeClient("not valid json at all"))
    resp = _compound("A and B")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "undetermined"
    assert body["sub_claims"] == []
    assert any("Could not decompose" in r for r in body["reasoning"])


def test_compound_decomposition_blowup_is_a_422_before_any_subclaim_is_verified(monkeypatch):
    """The cap must be enforced BEFORE verification -- proven by a capturing
    adapter asserting it was never called, not just by the status code."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    too_many = json.dumps({"parts": [{"text": f"part {i}", "domain": "substrate"} for i in range(server_mod._MAX_SUBCLAIMS + 1)]})
    monkeypatch.setattr(server_mod, "_compound_client", _FakeDecomposeClient(too_many))
    fake_robotics = _FixedEvidenceAdapter("substrate")
    monkeypatch.setitem(server_mod.engine._domains, "substrate", fake_robotics)

    resp = _compound("way too many parts")
    assert resp.status_code == 422
    assert str(server_mod._MAX_SUBCLAIMS) in resp.json()["detail"]
    assert fake_robotics.calls == []  # never verified -- the cap stopped it before any live work


def test_compound_exactly_at_the_cap_is_allowed(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    exactly_cap = json.dumps({"parts": [{"text": f"part {i}", "domain": "substrate"} for i in range(server_mod._MAX_SUBCLAIMS)]})
    monkeypatch.setattr(server_mod, "_compound_client", _FakeDecomposeClient(exactly_cap))
    fake_robotics = _FixedEvidenceAdapter("substrate", stance="supports")
    monkeypatch.setitem(server_mod.engine._domains, "substrate", fake_robotics)

    resp = _compound("exactly at the cap")
    assert resp.status_code == 200
    assert len(fake_robotics.calls) == server_mod._MAX_SUBCLAIMS


# --- rollup through the real engine ---


def test_compound_rollup_confirmed_when_every_subclaim_confirms(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setattr(server_mod, "_compound_client", _FakeDecomposeClient(_two_part_decompose("substrate", "searchlight")))
    monkeypatch.setitem(server_mod.engine._domains, "substrate", _FixedEvidenceAdapter("substrate", stance="supports"))
    monkeypatch.setitem(server_mod.engine._domains, "searchlight", _FixedEvidenceAdapter("searchlight", stance="supports"))

    resp = _compound("A and B")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "confirmed"
    assert len(body["sub_claims"]) == 2
    assert all(sc["verdict"]["state"] == "confirmed" for sc in body["sub_claims"])


def test_compound_rollup_contradicted_when_one_subclaim_contradicts(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    monkeypatch.setattr(server_mod, "_compound_client", _FakeDecomposeClient(_two_part_decompose("substrate", "searchlight")))
    monkeypatch.setitem(server_mod.engine._domains, "substrate", _FixedEvidenceAdapter("substrate", stance="supports"))
    monkeypatch.setitem(server_mod.engine._domains, "searchlight", _FixedEvidenceAdapter("searchlight", stance="contradicts"))

    resp = _compound("A and B")
    body = resp.json()
    assert body["state"] == "contradicted"


def test_compound_unsupported_domain_part_becomes_a_null_verdict_subclaim(monkeypatch):
    """decompose_claim() can classify a part as needing quant/silicon
    (DECOMPOSABLE_DOMAINS excludes them) -- that part is never verified,
    kept as a named, visible gap (verdict: null), not silently dropped."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    decompose_response = json.dumps({"parts": [
        {"text": "A", "domain": "substrate"},
        {"text": "the dataset's mean voltage is 5.0", "domain": "unsupported"},
    ]})
    monkeypatch.setattr(server_mod, "_compound_client", _FakeDecomposeClient(decompose_response))
    monkeypatch.setitem(server_mod.engine._domains, "substrate", _FixedEvidenceAdapter("substrate", stance="supports"))

    resp = _compound("A and the dataset's mean voltage is 5.0")
    body = resp.json()
    assert body["state"] == "undetermined"  # confirmed part + unsupported part -> undetermined, not contradicted
    unsupported = [sc for sc in body["sub_claims"] if sc["domain"] == "unsupported"][0]
    assert unsupported["verdict"] is None
