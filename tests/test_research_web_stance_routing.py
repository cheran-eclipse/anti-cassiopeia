"""
Tests for research_web.py's judge_stance() model routing (v3, found
live -- see retrieval/stance.py's RECOMMENDED_STANCE_MODEL for the full
finding): propose()/the live-search step stay on `self._client`;
judge_stance() routes to a SEPARATE `self._stance_client`, defaulting to
the SAME object as `client` when a caller explicitly injects one (so
every existing single-fake-client test keeps working unchanged -- see
test_domains_research_web.py's own 32 tests, all still green), and only
constructing two DIFFERENT real clients when neither is injected
(default_domains()'s real, no-arg path).

All OFFLINE: fake clients, a local fixture server -- no live Nebius call.
"""

import json

import anticassiopeia.llm.nebius_client as nebius_client_mod
from anticassiopeia.core import Claim
from anticassiopeia.domains.research_web import RECOMMENDED_STANCE_MODEL, ResearchWebAdapter
from anticassiopeia.llm.nebius_client import NebiusClientError
from evals.fixture_server import serve_fixtures

_FIXTURE_QUOTE = "The reference pump is rated for a maximum operating pressure of 12 bar."


def _found_json(chunk_id: str, quote: str) -> str:
    return json.dumps({"found": True, "chunk_id": chunk_id, "quote": quote, "value": None, "unit": None, "kind": None})


class _DualPromptFakeClient:
    """Same dual-prompt-shape convention as test_domains_research_web.py's
    own _FakeClient -- used here specifically to prove propose() and
    judge_stance() can be routed to TWO DIFFERENT fake objects, each only
    ever seeing the one prompt shape it should."""

    def __init__(self, response: str, label: str):
        self._response = response
        self.label = label
        self.calls: list[str] = []

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        self.calls.append(prompt)
        return self._response


def test_recommended_stance_model_is_a_real_nemotron_model_id():
    # Locks the constant's value against an accidental edit -- the whole
    # point of this module's own docstring is that THIS specific model id
    # was the one actually measured.
    assert RECOMMENDED_STANCE_MODEL == "nvidia/Nemotron-3-Ultra-550b-a55b"


def test_default_domains_style_construction_gets_two_different_real_clients(monkeypatch):
    """No client/stance_client injected at all (how default_domains() builds
    it) -- propose's client and the stance client must be two DIFFERENT
    real NebiusTokenFactoryClient instances, with different models."""
    monkeypatch.setitem(nebius_client_mod._DOTENV_VALUES, "NEBIUS_API_KEY", "fake-key-for-construction-only")
    adapter = ResearchWebAdapter()
    assert adapter._client is not adapter._stance_client
    assert adapter._stance_client.model == RECOMMENDED_STANCE_MODEL
    assert adapter._client.model != RECOMMENDED_STANCE_MODEL  # the default propose model, unchanged


async def test_a_single_injected_client_still_handles_both_prompt_shapes(monkeypatch):
    """No regression: existing tests inject ONE fake client via `client=` and
    rely on it handling both propose() and judge_stance() prompts -- proves
    `stance_client` defaults to that SAME object, not a second real one."""
    with serve_fixtures() as base_url:
        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        class _OneFakeClient:
            async def complete(self, prompt, *, system=None, temperature=0.0):
                if prompt.startswith("CLAIM:"):
                    return "supports"
                return _found_json(f"{base_url}/stable_page.html#0", _FIXTURE_QUOTE)

        one_client = _OneFakeClient()
        adapter = ResearchWebAdapter(client=one_client, search=fake_search, block_private_networks=False)
        assert adapter._stance_client is one_client

        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web")
        ev = await adapter.gather_evidence(claim)

    assert len(ev) == 1
    assert ev[0].stance == "supports"


async def test_explicit_stance_client_injection_is_used_for_judge_stance_only(monkeypatch):
    """A caller can inject TWO different fakes -- proves judge_stance() only
    ever talks to stance_client, and propose() only ever talks to client."""
    with serve_fixtures() as base_url:
        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        propose_client = _DualPromptFakeClient(_found_json(f"{base_url}/stable_page.html#0", _FIXTURE_QUOTE), "propose")
        stance_client = _DualPromptFakeClient("supports", "stance")
        adapter = ResearchWebAdapter(client=propose_client, stance_client=stance_client, search=fake_search, block_private_networks=False)

        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web")
        ev = await adapter.gather_evidence(claim)

    assert len(ev) == 1
    assert len(propose_client.calls) == 1
    assert propose_client.calls[0].startswith("Question:") or "Question" in propose_client.calls[0]
    assert len(stance_client.calls) == 1
    assert stance_client.calls[0].startswith("CLAIM:")


async def test_stance_client_unavailable_is_a_named_per_source_gap_not_a_crash(monkeypatch):
    """Mirrors the existing "propose step can't run" no-key test, but for
    the stance client specifically -- propose() can still succeed (a real
    quote gets verified), but judge_stance() failing must be a named,
    per-source gap, never an uncaught crash."""
    with serve_fixtures() as base_url:
        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        propose_client = _DualPromptFakeClient(_found_json(f"{base_url}/stable_page.html#0", _FIXTURE_QUOTE), "propose")
        adapter = ResearchWebAdapter(client=propose_client, search=fake_search, block_private_networks=False)
        # Simulate "stance client failed to construct" directly, same style
        # robotics.py's own test_byoe_with_no_client_configured_is_a_named_gap_not_a_crash uses.
        adapter._stance_client = None
        adapter._stance_client_error = "NEBIUS_API_KEY is not set."

        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web")
        ev = await adapter.gather_evidence(claim)

    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert any("stance-judging call failed" in g for g in gap)
    assert any("NEBIUS_API_KEY is not set" in g for g in gap)


async def test_stance_client_failure_does_not_prevent_propose_from_running(monkeypatch):
    """The propose() call (and its real quote verification) must still run
    and succeed even when the stance client is broken -- the failure is
    isolated to the judge_stance() sub-step, not the whole source check."""
    with serve_fixtures() as base_url:
        async def fake_search(_query: str, _max: int) -> list[str]:
            return [f"{base_url}/stable_page.html"]

        propose_client = _DualPromptFakeClient(_found_json(f"{base_url}/stable_page.html#0", _FIXTURE_QUOTE), "propose")
        adapter = ResearchWebAdapter(client=propose_client, search=fake_search, block_private_networks=False)
        adapter._stance_client = None
        adapter._stance_client_error = "stance client broken"

        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="research_web")
        await adapter.gather_evidence(claim)

    # propose() DID run (its one real call happened) -- the gap is specific
    # to stance-judging, not "nothing ran at all".
    assert len(propose_client.calls) == 1
