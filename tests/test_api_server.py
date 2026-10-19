"""
Tests the auth + rate-limiting fix on POST /verify (found during external
security review: this endpoint had neither — see server.py's module
docstring for the full writeup). /health and /domains stay unauthenticated
by design; only /verify is gated, since it's the Nebius-budget-burning one.
"""

import pytest
from fastapi.testclient import TestClient

import anticassiopeia.api.server as server_mod
from anticassiopeia.api.server import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limit_state():
    """Rate-limit buckets are module-level (main bucket keyed by API key,
    failed-auth bucket keyed by client IP) -- TestClient always presents the
    same host, so state would otherwise leak between tests. Reset before
    every test for isolation."""
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    yield
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()


@pytest.fixture(autouse=True)
def _no_api_key_by_default(monkeypatch):
    """Fails closed by default (no ANTICASSIOPEIA_API_KEY configured) unless
    a test explicitly sets one -- proving the "missing key is not the same
    as auth disabled" behavior, not just assuming it."""
    monkeypatch.delenv("ANTICASSIOPEIA_API_KEY", raising=False)


def test_health_and_domains_stay_open_with_no_api_key():
    assert client.get("/health").status_code == 200
    assert client.get("/domains").status_code == 200


def test_verify_without_api_key_header_is_rejected():
    resp = client.post("/verify", json={"text": "x", "domain": "ml_data", "context": {}})
    assert resp.status_code == 401


def test_verify_with_no_server_side_key_configured_rejects_every_request(monkeypatch):
    """FAILS CLOSED, explicitly: no ANTICASSIOPEIA_API_KEY set server-side
    means no key can ever be valid -- not "auth is effectively disabled"."""
    resp = client.post(
        "/verify",
        json={"text": "x", "domain": "ml_data", "context": {}},
        headers={"X-API-Key": "anything-at-all"},
    )
    assert resp.status_code == 401


def test_verify_with_wrong_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.post(
        "/verify",
        json={"text": "x", "domain": "ml_data", "context": {}},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_verify_with_correct_api_key_succeeds(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.post(
        "/verify",
        json={"text": "mean v is 1.0", "domain": "ml_data", "context": {"dataset_path": "/no/such/file.csv", "column": "v", "stat": "mean", "expected_value": 1.0}},
        headers={"X-API-Key": "the-real-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "undetermined"  # a real gap (missing file), not a crash


def test_rate_limit_trips_after_the_burst_allowance(monkeypatch):
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    headers = {"X-API-Key": "the-real-key"}
    body = {"text": "x", "domain": "ml_data", "context": {}}

    statuses = [client.post("/verify", json=body, headers=headers).status_code for _ in range(server_mod._RATE_LIMIT_BURST + 3)]

    assert statuses[: server_mod._RATE_LIMIT_BURST] == [200] * server_mod._RATE_LIMIT_BURST
    assert 429 in statuses[server_mod._RATE_LIMIT_BURST:]


def test_non_ascii_api_key_header_is_a_clean_401_not_a_crash(monkeypatch):
    """FOUND BUG (follow-up security review): secrets.compare_digest(str, str)
    raises TypeError for a non-ASCII argument -- a 500, not a 401. Encoding
    both sides to bytes first (see server.py) removes the restriction.
    Sent as raw latin-1 bytes, not a plain Python str -- httpx's own client
    refuses to even SEND a non-ASCII str header value (it insists on ascii
    client-side), so bytes are the only way to actually exercise the
    server-side code path a real non-ASCII header would reach."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    resp = client.post(
        "/verify",
        json={"text": "x", "domain": "ml_data", "context": {}},
        headers={"X-API-Key": "clé-non-ascii".encode("latin-1")},
    )
    assert resp.status_code == 401


def test_rate_limit_is_keyed_on_api_key_not_shared_across_different_keys(monkeypatch):
    """FOUND BUG (follow-up security review): keying the main rate limit on
    request.client.host collapses every caller behind a shared reverse-proxy
    IP into ONE bucket -- a legitimate second caller (different key, same
    apparent IP, which is all TestClient can simulate here) could be DoS'd
    by a first caller's traffic. Keyed on the validated API key instead:
    exhausting one key's budget must not affect a different key's budget."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "key-one")
    # Only one key can be "the" server-configured key at a time in this
    # simple design, so this test proves bucket INDEPENDENCE the way that's
    # actually observable here: two different dict keys in _buckets, not
    # sharing state, by calling _enforce_rate_limit directly for a second
    # hypothetical key alongside real requests under the first.
    headers = {"X-API-Key": "key-one"}
    body = {"text": "x", "domain": "ml_data", "context": {}}
    for _ in range(server_mod._RATE_LIMIT_BURST):
        assert client.post("/verify", json=body, headers=headers).status_code == 200
    assert client.post("/verify", json=body, headers=headers).status_code == 429

    # A second, independent key's bucket (same simulated client IP, which is
    # exactly the scenario this fix targets) still has its own full budget.
    server_mod._enforce_rate_limit("key-two")  # does not raise -- fresh bucket
    assert "key-one" in server_mod._buckets
    assert "key-two" in server_mod._buckets
    assert server_mod._buckets["key-one"] is not server_mod._buckets["key-two"]


def test_bucket_dict_is_evicted_when_it_grows_past_the_cap(monkeypatch):
    """FOUND BUG (follow-up security review): _buckets/_auth_failure_buckets
    added one entry per distinct API key / client IP forever, with no
    eviction -- an attacker cycling through many distinct keys/IPs could
    grow this unboundedly. Proves eviction actually keeps the dict bounded,
    not just that the constants exist. Uses a tiny cap (monkeypatched) so
    the test doesn't need to create thousands of real entries."""
    monkeypatch.setattr(server_mod, "_MAX_TRACKED_BUCKETS", 5)
    monkeypatch.setattr(server_mod, "_BUCKET_IDLE_TTL_SECONDS", 3600.0)  # nothing idle yet

    for i in range(10):
        server_mod._bucket_for(f"key-{i}")

    assert len(server_mod._buckets) <= 5
    # The most-recently-created entries should have survived eviction, not
    # an arbitrary subset -- proves it's evicting the OLDEST, not random ones.
    for i in range(5, 10):
        assert f"key-{i}" in server_mod._buckets


def test_failed_auth_throttle_trips_independently_of_the_main_rate_limit(monkeypatch):
    """Repeated WRONG keys from the same client get 429 once the small
    failed-auth budget (separate from the main per-key limit above) is
    exhausted -- throttles key-guessing specifically."""
    monkeypatch.setenv("ANTICASSIOPEIA_API_KEY", "the-real-key")
    body = {"text": "x", "domain": "ml_data", "context": {}}

    statuses = [
        client.post("/verify", json=body, headers={"X-API-Key": "wrong-key"}).status_code
        for _ in range(server_mod._FAILED_AUTH_BURST + 2)
    ]
    assert statuses[: server_mod._FAILED_AUTH_BURST] == [401] * server_mod._FAILED_AUTH_BURST
    assert 429 in statuses[server_mod._FAILED_AUTH_BURST :]
