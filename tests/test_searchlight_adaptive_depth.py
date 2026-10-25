"""
Tests for searchlight.py's ADAPTIVE-DEPTH evidence gathering: a fast
path that stops checking candidate sources early once evidence is
already decisive (_is_decisive_pair), and an escalation path that
checks MORE sources via a second, differently-phrased search when the
first pass's real outcome is ambiguous (_first_pass_is_ambiguous) --
never a guess about the claim made before searching.

THE SINGLE MOST IMPORTANT INVARIANT this feature must never break:
no matter which path runs, the final Verdict.state is always exactly
one of the three existing states (the "three C's" -- confirmed/
contradicted/undetermined). This feature only ever changes HOW MUCH
evidence reaches core/engine.py's scoring; it never bypasses or
reinterprets that scoring. See test_three_cs_invariant_holds_on_both_paths
below -- treat that test as load-bearing.

All OFFLINE: a real local fixture server (evals/fixture_server.py), a
call-tracking fake LLM client, real chunking/BM25/hybrid-rerank (no
embed() on the fake client, so hybrid degrades to BM25-only, same as
every other offline test in this file's sibling test modules) -- no
live Nebius call, no live search.
"""

import json

import pytest

from anticassiopeia.core import Claim, VerdictState, VerificationEngine
from anticassiopeia.domains.searchlight import (
    SearchlightAdapter,
    _first_pass_is_ambiguous,
    _is_decisive_pair,
)
from anticassiopeia.core.verdict import Evidence
from evals.fixture_server import serve_fixtures

_NOT_FOUND_JSON = json.dumps({"found": False, "reason": "not stated in the shown passages"})


def _found_json(chunk_id: str, quote: str) -> str:
    return json.dumps({"found": True, "chunk_id": chunk_id, "quote": quote, "value": None, "unit": None, "kind": None})


class _TrackingFakeClient:
    """Same dual-prompt-shape convention as this file's sibling test
    modules' own _FakeClient, plus a `calls` list recording every
    prompt sent -- needed here specifically to PROVE a source was never
    checked (fast path) or that a real second search round happened
    (escalation), not just to infer it from the final evidence shape."""

    def __init__(self, propose_by_marker: dict[str, str | Exception], stance_response: str = "supports"):
        self._propose_by_marker = propose_by_marker
        self._stance_response = stance_response
        self.calls: list[str] = []

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        self.calls.append(prompt)
        if prompt.startswith("CLAIM:"):
            return self._stance_response
        for marker, response in self._propose_by_marker.items():
            if marker in prompt:
                if isinstance(response, Exception):
                    raise response
                return response
        return _NOT_FOUND_JSON


def _assert_three_cs_invariant(verdict) -> None:
    """The single most important check in this whole test module -- see
    module docstring. Must hold regardless of which path (fast or
    escalated) produced `verdict`."""
    assert verdict.state in (VerdictState.CONFIRMED, VerdictState.CONTRADICTED, VerdictState.UNDETERMINED)
    assert isinstance(verdict.state, VerdictState)
    assert isinstance(verdict.evidence, list)
    assert isinstance(verdict.reasoning, list)
    assert isinstance(verdict.missing, list)


# --- pure unit tests for the two decision-rule helpers ---


def test_is_decisive_pair_false_with_fewer_than_two_sources():
    one = [Evidence(source="https://a.example", snippet="x", stance="supports", trust=0.75)]
    assert not _is_decisive_pair(one)


def test_is_decisive_pair_false_when_two_sources_disagree():
    two = [
        Evidence(source="https://a.example", snippet="x", stance="supports", trust=0.75),
        Evidence(source="https://b.example", snippet="y", stance="contradicts", trust=0.75),
    ]
    assert not _is_decisive_pair(two)


def test_is_decisive_pair_true_when_two_distinct_sources_agree():
    two = [
        Evidence(source="https://a.example", snippet="x", stance="supports", trust=0.75),
        Evidence(source="https://b.example", snippet="y", stance="supports", trust=0.75),
    ]
    assert _is_decisive_pair(two)


def test_first_pass_is_ambiguous_true_for_zero_evidence():
    assert _first_pass_is_ambiguous([])


def test_first_pass_is_ambiguous_true_for_a_genuine_tie():
    tied = [
        Evidence(source="https://a.example", snippet="x", stance="supports", trust=0.75),
        Evidence(source="https://b.example", snippet="y", stance="contradicts", trust=0.75),
    ]
    assert _first_pass_is_ambiguous(tied)


def test_first_pass_is_ambiguous_false_for_a_decisive_single_source():
    decisive = [Evidence(source="https://a.example", snippet="x", stance="supports", trust=0.75)]
    assert not _first_pass_is_ambiguous(decisive)


# --- fast path: real early exit, fewer live calls ---


async def test_fast_path_stops_before_checking_a_third_available_source():
    """3 candidate sources are available; whichever 2 the real BM25/hybrid
    ranking checks first agree ("supports") -- the 3rd must NEVER be
    checked. `url_c` deliberately reuses `stable_page_rephrased.html`'s
    real content (the static file server ignores query strings, so it
    is content-identical to `url_b`) specifically so this test does NOT
    depend on which 2 of the 3 the ranking happens to pick first: any
    pairing of {url_a, url_b-or-url_c} is a genuine agreement and must
    trigger the fast-path break, proven by checking that only 2 of the
    3 propose() markers were ever actually hit."""
    with serve_fixtures() as base_url:
        url_a = f"{base_url}/stable_page.html"
        url_b = f"{base_url}/stable_page_rephrased.html"
        url_c = f"{base_url}/stable_page_rephrased.html?decoy=1"

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [url_a, url_b, url_c]

        markers = {
            f"{url_a}#0": _found_json(f"{url_a}#0", "The reference pump is rated for a maximum operating pressure of 12 bar."),
            f"{url_b}#0": _found_json(f"{url_b}#0", "An independent test report confirmed the reference pump operates safely up to 12 bar without failure."),
            f"{url_c}#0": _found_json(f"{url_c}#0", "An independent test report confirmed the reference pump operates safely up to 12 bar without failure."),
        }
        client = _TrackingFakeClient(propose_by_marker=markers)
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        engine = VerificationEngine(domains={"searchlight": adapter})
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        verdict = await engine.verify(claim)

    _assert_three_cs_invariant(verdict)
    assert verdict.state == VerdictState.CONFIRMED
    assert len(verdict.evidence) == 2, "fast path must stop once 2 sources agree, not check all 3"
    markers_hit = {m for m in markers if any(m in call for call in client.calls)}
    assert len(markers_hit) == 2, f"expected exactly 2 of the 3 sources to be checked, got {len(markers_hit)}: {markers_hit}"


async def test_fast_path_does_not_stop_after_only_one_source():
    """A single decisive source is NOT enough to trigger the fast-path
    break (that requires 2 AGREEING sources, per _is_decisive_pair) --
    with only 1 source available, the loop ends because there's nothing
    left to check, not because of the fast-path rule. (This is really a
    pure-logic property already covered above; this test proves it
    doesn't change the existing single-source behavior end to end.)"""
    with serve_fixtures() as base_url:
        url_a = f"{base_url}/stable_page.html"

        async def fake_search(_query: str, _max: int) -> list[str]:
            return [url_a]

        client = _TrackingFakeClient(propose_by_marker={
            f"{url_a}#0": _found_json(f"{url_a}#0", "The reference pump is rated for a maximum operating pressure of 12 bar."),
        })
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        engine = VerificationEngine(domains={"searchlight": adapter})
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        verdict = await engine.verify(claim)

    _assert_three_cs_invariant(verdict)
    assert verdict.state == VerdictState.CONFIRMED
    assert verdict.confidence == pytest.approx(0.9)  # single-source cap, unchanged from before this feature


# --- escalation path: real second search, more live calls, only when ambiguous ---


async def test_escalation_runs_a_real_second_search_when_first_pass_is_empty():
    """First pass: one source, model honestly reports the claim isn't
    stated (evidence == [] -- genuinely ambiguous/empty). Escalation
    must fire: a SECOND, differently-phrased search call happens (proven
    by call count, not inferred), finds a NEW source, and that source's
    real evidence makes it into the final verdict."""
    with serve_fixtures() as base_url:
        url_first_pass = f"{base_url}/stable_page.html?pass=1"
        url_escalated = f"{base_url}/stable_page_rephrased.html?pass=2"
        search_calls: list[str] = []

        async def fake_search(query: str, _max: int) -> list[str]:
            search_calls.append(query)
            if len(search_calls) == 1:
                return [url_first_pass]
            return [url_escalated]

        client = _TrackingFakeClient(propose_by_marker={
            f"{url_first_pass}#0": _NOT_FOUND_JSON,
            f"{url_escalated}#0": _found_json(
                f"{url_escalated}#0",
                "An independent test report confirmed the reference pump operates safely up to 12 bar without failure.",
            ),
        })
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        engine = VerificationEngine(domains={"searchlight": adapter})
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        verdict = await engine.verify(claim)

    _assert_three_cs_invariant(verdict)
    assert len(search_calls) == 2, "escalation must trigger a real second search call"
    assert search_calls[1] != search_calls[0], "the escalated search must be differently-phrased, not the same question again"
    assert verdict.state == VerdictState.CONFIRMED
    assert len(verdict.evidence) == 1
    assert verdict.evidence[0].source == url_escalated


async def test_escalation_does_not_fire_when_first_pass_is_already_decisive():
    """Negative case, proving escalation is a REACTION to ambiguity, not
    something that always runs 'for better quality' regardless of need:
    a single decisive source in the first pass must mean exactly ONE
    search call total."""
    with serve_fixtures() as base_url:
        url_a = f"{base_url}/stable_page.html"
        search_calls: list[str] = []

        async def fake_search(query: str, _max: int) -> list[str]:
            search_calls.append(query)
            return [url_a]

        client = _TrackingFakeClient(propose_by_marker={
            f"{url_a}#0": _found_json(f"{url_a}#0", "The reference pump is rated for a maximum operating pressure of 12 bar."),
        })
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        engine = VerificationEngine(domains={"searchlight": adapter})
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        verdict = await engine.verify(claim)

    _assert_three_cs_invariant(verdict)
    assert len(search_calls) == 1, "a decisive first pass must not trigger an escalated second search"
    assert verdict.state == VerdictState.CONFIRMED


async def test_escalation_respects_the_total_source_cap():
    """Even when ambiguous, escalation never checks more than
    _ESCALATED_MAX_SOURCES_TO_CHECK sources TOTAL across both passes --
    proven by exhausting the cap with sources that would otherwise keep
    producing fresh (non-agreeing, non-empty) evidence forever."""
    from anticassiopeia.domains import searchlight as rw_mod

    with serve_fixtures() as base_url:
        # First pass: one source, contradicts. Escalation: more sources,
        # alternating stance, so _is_decisive_pair/._first_pass_is_ambiguous
        # never resolves the tie -- the ONLY thing that can stop checking
        # is the hard total-source cap.
        urls = [f"{base_url}/stable_page.html?n={i}" for i in range(8)]
        search_calls: list[str] = []

        async def fake_search(query: str, _max: int) -> list[str]:
            search_calls.append(query)
            # pass 1 gets urls[0]; escalation gets the rest, freshly, never repeating.
            return [urls[0]] if len(search_calls) == 1 else urls[1:]

        propose_by_marker = {}
        for i, url in enumerate(urls):
            stance_text = "The reference pump is rated for a maximum operating pressure of 12 bar."
            propose_by_marker[f"{url}#0"] = _found_json(f"{url}#0", f"{stance_text} (source {i})")

        class _AlternatingStanceClient(_TrackingFakeClient):
            async def complete(self, prompt, *, system=None, temperature=0.0):
                if prompt.startswith("CLAIM:"):
                    # alternate supports/contradicts so evidence never
                    # becomes decisive and never resolves the ambiguity --
                    # only the hard cap can end this.
                    self.calls.append(prompt)
                    return "supports" if len(self.calls) % 4 < 2 else "contradicts"
                return await super().complete(prompt, system=system, temperature=temperature)

        client = _AlternatingStanceClient(propose_by_marker=propose_by_marker)
        adapter = SearchlightAdapter(client=client, search=fake_search, block_private_networks=False)
        engine = VerificationEngine(domains={"searchlight": adapter})
        claim = Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        verdict = await engine.verify(claim)

    _assert_three_cs_invariant(verdict)
    propose_calls = [c for c in client.calls if c.startswith("Question:") or "quote the passage" in c]
    assert len(propose_calls) <= rw_mod._ESCALATED_MAX_SOURCES_TO_CHECK, (
        f"checked {len(propose_calls)} sources, more than the "
        f"{rw_mod._ESCALATED_MAX_SOURCES_TO_CHECK}-source total cap allows"
    )


# --- the three-C's invariant, explicit and standalone, per this module's own docstring ---


async def test_three_cs_invariant_holds_on_both_paths():
    """THE load-bearing test for this entire feature (see module
    docstring). Constructs one fast-path scenario and one escalation
    scenario, and for BOTH asserts the final verdict is still exactly
    one of CONFIRMED/CONTRADICTED/UNDETERMINED with the same response
    shape as before this feature existed. If this test ever fails, the
    adaptive-depth feature itself must be considered broken regardless
    of any speed/quality metric it otherwise improved."""
    with serve_fixtures() as base_url:
        # Fast-path scenario: 2 agreeing sources, decisive immediately.
        url_a = f"{base_url}/stable_page.html"
        url_b = f"{base_url}/stable_page_rephrased.html"

        async def fast_search(_query: str, _max: int) -> list[str]:
            return [url_a, url_b]

        fast_client = _TrackingFakeClient(propose_by_marker={
            f"{url_a}#0": _found_json(f"{url_a}#0", "The reference pump is rated for a maximum operating pressure of 12 bar."),
            f"{url_b}#0": _found_json(f"{url_b}#0", "An independent test report confirmed the reference pump operates safely up to 12 bar without failure."),
        })
        fast_adapter = SearchlightAdapter(client=fast_client, search=fast_search, block_private_networks=False)
        fast_engine = VerificationEngine(domains={"searchlight": fast_adapter})
        fast_verdict = await fast_engine.verify(
            Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        )

        # Escalation scenario: first pass empty, second (escalated) search finds it.
        url_empty = f"{base_url}/stable_page.html?empty=1"
        url_found = f"{base_url}/stable_page_rephrased.html?found=1"
        esc_search_calls: list[str] = []

        async def escalation_search(query: str, _max: int) -> list[str]:
            esc_search_calls.append(query)
            return [url_empty] if len(esc_search_calls) == 1 else [url_found]

        esc_client = _TrackingFakeClient(propose_by_marker={
            f"{url_empty}#0": _NOT_FOUND_JSON,
            f"{url_found}#0": _found_json(
                f"{url_found}#0",
                "An independent test report confirmed the reference pump operates safely up to 12 bar without failure.",
            ),
        })
        esc_adapter = SearchlightAdapter(client=esc_client, search=escalation_search, block_private_networks=False)
        esc_engine = VerificationEngine(domains={"searchlight": esc_adapter})
        esc_verdict = await esc_engine.verify(
            Claim(text="the reference pump is rated for a maximum operating pressure of 12 bar", domain="searchlight")
        )

    for verdict in (fast_verdict, esc_verdict):
        _assert_three_cs_invariant(verdict)
    assert fast_verdict.state == VerdictState.CONFIRMED
    assert esc_verdict.state == VerdictState.CONFIRMED
    assert len(esc_search_calls) == 2, "escalation scenario must have actually escalated"
