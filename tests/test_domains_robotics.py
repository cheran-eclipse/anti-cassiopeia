"""
Tests the robotics adapter's wiring to the real retrieve->propose->verify
pipeline (chunking + BM25 + a real/fake LLM client + verify_proposal) over
its actual corpus files, plus the honest-failure paths (no key configured,
a live call failing, a cited quote that doesn't actually exist in the
corpus) — the single most important property of this adapter.

Most tests inject `_FakeClient`, a scripted test double for
NebiusTokenFactoryClient, so they exercise the REAL extract.propose() ->
verify_proposal() code path without a network call or a live key. The
`test_live_*` tests at the bottom are the exception: they call the actual
Nebius API and require a real, working NEBIUS_API_KEY — see their own
docstrings.
"""

import json
import os

import pytest

from anticassiopeia.core import Claim, VerdictState, VerificationEngine
from anticassiopeia.domains.robotics import RoboticsAdapter
from anticassiopeia.llm.nebius_client import NebiusClientError
from anticassiopeia.retrieval import BM25Index, chunk_document
from anticassiopeia.retrieval.extract import propose


class _FakeClient:
    """Test double for NebiusTokenFactoryClient. `responses` maps a substring of
    the "Question: ..." line extract.propose() embeds in its prompt to either a
    canned JSON response string, or an Exception instance to raise instead —
    simulating a live-call failure without a network call."""

    def __init__(self, responses: dict[str, str | Exception]):
        self._responses = responses

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        for marker, response in self._responses.items():
            if marker in prompt:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"no fake response scripted for prompt: {prompt!r}")


# Correct, honest answers a real model should give — verified against the actual
# corpus/chunking output (see each chunk_id's real text in anticassiopeia/corpus/).
# These are the SAME facts the adapter used to hand-author in _KNOWN_PROPOSALS
# before propose() went live; scripting them here (as a fake remote LLM) instead
# of baking them into the adapter is the whole point of this change.
_HONEST_RESPONSES: dict[str, str] = {
    # Marker matches robotics.py's real DOC1 query, "maximum rated depth
    # aluminum housing" -- NOT "...aluminum acrylic housing" (the old query,
    # fixed in robotics.py per stress_test/BUGS_FOUND.md's dated correction:
    # asking about both materials at once was ambiguous between two real,
    # differently-valued lines in the same real chunk).
    "maximum rated depth aluminum housing": json.dumps(
        {
            "found": True,
            "chunk_id": "DOC1_BlueROV2#1",
            "quote": "Maximum Rated Depth (Aluminum): 300 m",
            "value": 300,
            "unit": "m",
            "kind": "rated",
        }
    ),
    "maximum rated depth housing": json.dumps(
        {
            "found": True,
            "chunk_id": "DOC2_BlueROV2#1",
            "quote": "Maximum Rated Depth: 100 m",
            "value": 100,
            "unit": "m",
            "kind": "rated",
        }
    ),
    "operating pressure range bar": json.dumps(
        {
            "found": True,
            "chunk_id": "DOC3_Bar30#3",
            "quote": "Operating range: 0 to 30 bar, -20 to +85 C",
            "value": 30,
            "unit": "bar",
            "kind": "rated",
        }
    ),
}

# Bar100XT uses its own distinct retrieval_query ("maximum operating pressure
# rating bar" — see _RETRIEVAL_QUERIES), so this can live in _HONEST_RESPONSES
# alongside Bar30's without one marker shadowing the other.
_HONEST_RESPONSES["maximum operating pressure rating bar"] = json.dumps(
    {
        "found": True,
        "chunk_id": "DOC4_Bar100XT#3",
        "quote": "Operating Pressure Range: 0 to 100 bar",
        "value": 100,
        "unit": "bar",
        "kind": "rated",
    }
)


def _honest_adapter() -> RoboticsAdapter:
    return RoboticsAdapter(client=_FakeClient(dict(_HONEST_RESPONSES)))


def _engine() -> VerificationEngine:
    return VerificationEngine(domains={"robotics": _honest_adapter()})


async def test_bluerov2_claim_produces_two_contradicting_sources():
    adapter = _honest_adapter()
    claim = Claim(text="BlueROV2 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 2
    assert all(e.stance == "contradicts" for e in ev)
    sources = {e.source for e in ev}
    assert sources == {"DOC1_BlueROV2", "DOC2_BlueROV2"}


async def test_bar30_claim_produces_real_evidence_with_a_real_locator():
    adapter = _honest_adapter()
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"
    assert "DOC3_Bar30" in ev[0].locator
    assert "chunk" in ev[0].locator  # proves it went through chunking, not a hardcoded string


async def test_bar100xt_claim_produces_real_evidence_with_a_real_locator():
    """Bar100XT was sourced this session (Blue Robotics' official BarXT page,
    see doc4_bar100xt_excerpt.txt) — it used to have no corpus at all."""
    adapter = _honest_adapter()
    claim = Claim(text="Bar100XT survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "supports"  # 100 bar rating ~= 995 m depth-equivalent >= 500 m
    assert "DOC4_Bar100XT" in ev[0].locator
    assert "chunk" in ev[0].locator


async def test_bar100xt_claim_beyond_its_rating_contradicts():
    adapter = _honest_adapter()
    claim = Claim(text="Bar100XT survives 1200 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert ev[0].stance == "contradicts"  # ~995 m depth-equivalent rating < 1200 m


async def test_quspin_has_no_numeric_rating_and_gets_a_specific_named_gap():
    """QuSpin QZFM Gen-3 was checked live this session against QuSpin's own
    official product page (confirmed: no pressure/depth rating stated at
    all) — a real, checked absence now, not just an unsourced narrative gap."""
    adapter = _honest_adapter()
    claim = Claim(text="QuSpin QZFM Gen-3 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "quspin" in gap[0].lower()
    assert "quspin.com" in gap[0].lower()


async def test_unrecognized_part_gets_the_generic_gap():
    adapter = _honest_adapter()
    claim = Claim(text="Some totally unrelated part survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "no datasheet" in gap[0].lower()


async def test_fabricated_quote_is_rejected_even_through_the_full_adapter_path():
    """The core property this whole pipeline exists for: even if the (fake,
    scripted) LLM proposes a chunk_id that's real but a quote that is NOT
    actually in that chunk's text, verify_proposal() must reject it rather
    than trusting the proposer's say-so."""
    lying = json.dumps(
        {
            "found": True,
            "chunk_id": "DOC3_Bar30#3",  # a real chunk...
            "quote": "Operating range: 0 to 9999 bar",  # ...but this text isn't actually in it
            "value": 9999,
            "unit": "bar",
            "kind": "rated",
        }
    )
    adapter = RoboticsAdapter(client=_FakeClient({"operating pressure range bar": lying}))
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == [], "a quote that does not exist in the real corpus text must never become Evidence"


async def test_proposal_value_that_disagrees_with_its_own_quote_is_dropped():
    """verify_proposal only checks the quote; stance must not follow an unchecked
    'value' field the proposer attached to an otherwise-real quote."""
    lying = json.dumps(
        {
            "found": True,
            "chunk_id": "DOC3_Bar30#3",
            "quote": "Operating range: 0 to 30 bar, -20 to +85 C",  # real quote...
            "value": 9999,  # ...but this doesn't match the 30 the quote itself states
            "unit": "bar",
            "kind": "rated",
        }
    )
    adapter = RoboticsAdapter(client=_FakeClient({"operating pressure range bar": lying}))
    ev = await adapter.gather_evidence(Claim(text="Bar30 survives 500 m depth", domain="robotics"))
    assert ev == []


async def test_no_api_key_is_a_named_gap_not_a_crash(monkeypatch):
    """NEBIUS_API_KEY missing entirely must surface as a specific, honest gap —
    never a constructor crash and never silently treated the same as
    'nothing found'."""
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_BASE_URL", raising=False)
    adapter = RoboticsAdapter()  # no client injected, and no key in env
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "propose step can't run" in gap[0]
    assert "NEBIUS_API_KEY" in gap[0]


async def test_live_call_failure_is_a_named_gap_not_a_crash():
    """A NebiusClientError from the live client (bad key, non-200, wrong model,
    ...) must be caught per-document and surfaced by name, same pattern as
    domains/research_web.py's fetch-failure handling — never an unhandled
    exception out of gather_evidence(), never silently equated with
    'nothing found'."""
    failing = NebiusClientError("Nebius Token Factory returned 401: {\"detail\": \"...\"}")
    adapter = RoboticsAdapter(client=_FakeClient({"operating pressure range bar": failing}))
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == []
    gap = adapter.describe_gap(claim, ev)
    assert "LLM propose call failed" in gap[0]
    assert "401" in gap[0]


# --- stance polarity (docs/DESIGN: stance must follow the claim, not authoring-time intent) ---


async def test_negated_bar30_claim_gets_opposite_stance_from_the_positive_framing():
    """The bug: 'Bar30 fails at 500 m' (TRUE per the ~30 bar rating) used to get the
    same 'contradicts' evidence as 'Bar30 survives 500 m' and so a BACKWARDS verdict."""
    pos = await _honest_adapter().gather_evidence(Claim(text="Bar30 survives 500 m depth", domain="robotics"))
    neg = await _honest_adapter().gather_evidence(Claim(text="Bar30 fails at 500 m depth", domain="robotics"))
    assert [e.stance for e in pos] == ["contradicts"]
    assert [e.stance for e in neg] == ["supports"]
    assert [e.locator for e in pos] == [e.locator for e in neg]  # same retrieved evidence, opposite stance


async def test_negated_claims_get_correct_verdicts_end_to_end():
    engine = _engine()
    for text in ("Bar30 fails at 500 m depth", "BlueROV2 fails at 500 m"):
        v = await engine.verify(Claim(text=text, domain="robotics"))
        assert v.state == VerdictState.CONFIRMED, text
    v = await engine.verify(Claim(text="Bar30 survives 500 m depth", domain="robotics"))
    assert v.state == VerdictState.CONTRADICTED


async def test_condition_is_read_from_the_claim_not_assumed_to_be_500m():
    engine = _engine()
    v = await engine.verify(Claim(text="Bar30 survives 100 m depth", domain="robotics"))
    assert v.state == VerdictState.CONFIRMED  # ~298 m depth-equivalent rating >= 100 m
    v = await engine.verify(Claim(text="Bar30 fails at 100 m depth", domain="robotics"))
    assert v.state == VerdictState.CONTRADICTED


async def test_context_condition_is_preferred_and_equivalent_to_text():
    engine = _engine()
    ctx = {"depth_m": 500, "polarity": "fails"}
    v = await engine.verify(Claim(text="Bar30 depth claim", domain="robotics", context=ctx))
    assert v.state == VerdictState.CONFIRMED


async def test_conflicting_sources_stay_undetermined():
    """BlueROV2 DOC1 says 300 m, DOC2 says 100 m: at 200 m they genuinely disagree."""
    v = await _engine().verify(Claim(text="BlueROV2 survives 200 m depth", domain="robotics"))
    assert {e.stance for e in v.evidence} == {"supports", "contradicts"}
    assert v.state == VerdictState.UNDETERMINED


async def test_bar_conversion_too_close_to_call_is_neutral_not_guessed():
    # 30 bar ~= 298 m; at 300 m the gauge/absolute ambiguity decides it, so say nothing.
    v = await _engine().verify(Claim(text="Bar30 survives 300 m depth", domain="robotics"))
    assert [e.stance for e in v.evidence] == ["neutral"]
    assert v.state == VerdictState.UNDETERMINED


async def test_ambiguous_or_missing_condition_is_a_named_gap_not_a_guess():
    adapter = _honest_adapter()
    for text in (
        "Bar30 does not fail at 500 m depth",   # negated verb: refuse to guess polarity
        "Bar30 survives 500 ft depth",          # unsupported unit
        "BlueROV2 weighs 10 kg",                # not a depth claim at all
    ):
        claim = Claim(text=text, domain="robotics")
        ev = await adapter.gather_evidence(claim)
        assert ev == [], text
        gap = adapter.describe_gap(claim, ev)
        assert "depth condition" in gap[0], text
        assert "depth_m" in gap[0], text


async def test_bad_context_values_are_a_named_gap():
    adapter = _honest_adapter()
    claim = Claim(text="Bar30 survives it", domain="robotics", context={"depth_m": "deep"})
    assert await adapter.gather_evidence(claim) == []
    assert "not a number" in adapter.describe_gap(claim, [])[0]


# --- live tests: require a real, working NEBIUS_API_KEY. Skipped (not run) when
# the var is entirely unset, so CI/local runs without a key don't silently fail.
# If the var IS set but the live API rejects it (bad/expired key, account not
# provisioned, wrong endpoint), these FAIL for real rather than skipping —
# a configured-but-broken key is itself a fact worth surfacing, not hiding. ---

_requires_live_key = pytest.mark.skipif(
    not os.environ.get("NEBIUS_API_KEY"), reason="requires a real, working NEBIUS_API_KEY"
)


@_requires_live_key
async def test_live_bar30_claim_is_accepted_through_the_real_propose_and_verify_pipeline():
    """4a: a part that IS in the corpus. The REAL live model must propose a quote
    that verify_proposal() actually accepts against the real chunk text — not a
    fake, not a mock, the genuine Nebius Token Factory round trip."""
    adapter = RoboticsAdapter()  # real NebiusTokenFactoryClient from the real env
    claim = Claim(text="Bar30 survives 100 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev, f"expected real accepted evidence; propose errors: {getattr(adapter, '_last_propose_errors', None)}"
    assert ev[0].stance == "supports"  # ~298 m depth-equivalent rating >= 100 m
    assert "DOC3_Bar30" in ev[0].locator


@_requires_live_key
async def test_live_model_honestly_reports_a_fact_not_in_the_shown_passages():
    """4b: the REAL model, shown real retrieved passages that genuinely don't state
    the requested fact, must report "not found" rather than hallucinating a value
    that could slip past verify_proposal(). Uses the real BlueROV2 corpus chunks
    (which state depth ratings) but asks about battery runtime, which isn't
    stated anywhere in them — a plausible-sounding fabrication is exactly the
    failure mode this project exists to catch."""
    from pathlib import Path

    from anticassiopeia.llm.nebius_client import NebiusTokenFactoryClient

    corpus_dir = Path(__file__).parent.parent / "anticassiopeia" / "corpus"
    text = (corpus_dir / "doc1_bluerov2_excerpt.txt").read_text()
    chunks = chunk_document("DOC1_BlueROV2", text, chunk_size=300, overlap=50)
    hits = BM25Index(chunks).search("maximum battery runtime hours", top_k=3)
    assert hits, "query must share at least one token with the corpus to reach a live call"

    proposal = await propose("maximum battery runtime hours", hits, NebiusTokenFactoryClient())
    assert proposal is None, f"expected an honest 'not found', got a hallucinated proposal: {proposal}"


# --- FOUND BUG fix (see stress_test/BUGS_FOUND.md): a single propose() "not
# found" used to be trusted as genuine absence; observed live, ~1-in-10 calls
# against a real corpus doc returned "not found" even though the fact is
# genuinely present, and when that landed on one side of a genuine two-source
# conflict, the engine never saw the conflict. Fixed with _propose_with_retry:
# retries ONLY on None, up to 3 attempts, never on an actual returned proposal. ---


class _SequencedFakeClient:
    """Returns one scripted response per call, in order — unlike _FakeClient's
    static marker->response mapping, this is for testing retry behavior, where
    the SAME question needs a DIFFERENT answer on successive calls (e.g. "not
    found" twice, then a real answer)."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.call_count = 0

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        self.call_count += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


_BAR30_FOUND_JSON = _HONEST_RESPONSES["operating pressure range bar"]
_NOT_FOUND_JSON = json.dumps({"found": False, "reason": "not stated in the shown passages"})


async def test_retry_succeeds_on_a_later_attempt_after_empty_results():
    client = _SequencedFakeClient([_NOT_FOUND_JSON, _NOT_FOUND_JSON, _BAR30_FOUND_JSON])
    adapter = RoboticsAdapter(client=client)
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1, "the 3rd attempt found real evidence -- must not be treated as absent"
    assert ev[0].stance == "contradicts"  # real 30 bar rating (~298m) genuinely contradicts "survives 500m"
    assert client.call_count == 3


async def test_retry_stops_as_soon_as_evidence_is_found_not_a_fixed_3_calls():
    client = _SequencedFakeClient([_BAR30_FOUND_JSON, _NOT_FOUND_JSON, _NOT_FOUND_JSON])
    adapter = RoboticsAdapter(client=client)
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert len(ev) == 1
    assert client.call_count == 1, "an actual returned proposal must not be retried, even though more responses were queued"


async def test_retry_gives_up_after_the_full_budget_and_reports_genuine_absence():
    client = _SequencedFakeClient([_NOT_FOUND_JSON, _NOT_FOUND_JSON, _NOT_FOUND_JSON])
    adapter = RoboticsAdapter(client=client)
    claim = Claim(text="Bar30 survives 500 m depth", domain="robotics")
    ev = await adapter.gather_evidence(claim)
    assert ev == [], "all 3 attempts genuinely found nothing -- must still correctly report absence, not fabricate evidence"
    assert client.call_count == 3


async def test_propose_with_retry_unit_directly():
    """Direct unit test of the retry helper itself, isolated from the rest of
    gather_evidence()."""
    from anticassiopeia.domains.robotics import _propose_with_retry

    client_fails_then_succeeds = _SequencedFakeClient([_NOT_FOUND_JSON, _BAR30_FOUND_JSON])
    from anticassiopeia.retrieval import BM25Index, chunk_document
    from pathlib import Path

    text = Path("anticassiopeia/corpus/doc3_bar30_excerpt.txt").read_text()
    chunks = chunk_document("DOC3_Bar30", text, chunk_size=300, overlap=50)
    hits = BM25Index(chunks).search("operating pressure range bar", top_k=3)

    proposal = await _propose_with_retry("operating pressure range bar", hits, client_fails_then_succeeds)
    assert proposal is not None
    assert proposal.chunk_id == "DOC3_Bar30#3"
    assert client_fails_then_succeeds.call_count == 2

    client_always_fails = _SequencedFakeClient([_NOT_FOUND_JSON, _NOT_FOUND_JSON, _NOT_FOUND_JSON])
    proposal2 = await _propose_with_retry("operating pressure range bar", hits, client_always_fails)
    assert proposal2 is None
    assert client_always_fails.call_count == 3


@_requires_live_key
async def test_live_conflict_zone_claim_resolves_undetermined_every_time_not_just_usually():
    """THE test that would have caught the retry bug before the stress test did.
    evals/cases/robotics/bluerov2_200m_conflict_undetermined.json tests this exact
    claim, but only ONCE per `evals/run_evals.py` invocation -- not enough samples
    to catch a ~1-in-10-per-doc live "not found" rate. This resamples the SAME
    real conflict-zone claim 30 times against the real live pipeline and asserts
    EVERY run resolves UNDETERMINED (DOC1=300m supports, DOC2=100m contradicts,
    genuinely conflicting at 200m) -- with the retry fix, a single unlucky
    "not found" draw on one doc no longer silently removes that doc's evidence
    and flips the verdict to a confident CONFIRMED/CONTRADICTED. ~$0.0007/run,
    ~$0.02 total for this test, negligible against the project's budget."""
    # NOT _engine() -- that helper injects the FAKE client (_HONEST_RESPONSES);
    # this test needs the real, live NebiusTokenFactoryClient (RoboticsAdapter()
    # with no client= arg), same as every other test_live_* in this file.
    engine = VerificationEngine(domains={"robotics": RoboticsAdapter()})
    claim = Claim(text="BlueROV2 survives 200 m depth", domain="robotics")
    states = []
    for i in range(30):
        v = await engine.verify(claim)
        states.append(v.state.value)
        assert v.state == VerdictState.UNDETERMINED, (
            f"run {i}: expected UNDETERMINED (genuine DOC1/DOC2 conflict at 200m), "
            f"got {v.state.value} with evidence {[(e.source, e.stance) for e in v.evidence]} -- "
            f"states so far: {states}"
        )


@_requires_live_key
async def test_live_doc1_aluminum_query_retrieves_the_aluminum_line_every_time():
    """THE test that would have caught the 40% query-ambiguity rate directly,
    the same way test_live_conflict_zone_claim_... resamples the conflict
    claim itself. BEFORE this fix, DOC1's retrieval_query asked about "aluminum
    acrylic housing" at once -- genuinely ambiguous between two different real
    lines in the same real chunk ("Maximum Rated Depth (Acrylic): 100 m" vs
    "...(Aluminum): 300 m") -- and a 20-trial live sample showed the model
    honestly citing the Acrylic line roughly 40% of the time, which is the
    dominant cause (not the rarer ~1-in-10 absence case) of the stress test's
    dangerous conflict-zone verdicts. The fixed query ("maximum rated depth
    aluminum housing", no "acrylic") was itself verified live 20/20 before
    landing in robotics.py; this resamples it independently, at a higher
    count, as this project's permanent regression guard for that finding."""
    from pathlib import Path

    from anticassiopeia.llm.nebius_client import NebiusTokenFactoryClient
    from anticassiopeia.retrieval import BM25Index, chunk_document
    from anticassiopeia.retrieval.extract import propose

    text = Path("anticassiopeia/corpus/doc1_bluerov2_excerpt.txt").read_text()
    chunks = chunk_document("DOC1_BlueROV2", text, chunk_size=300, overlap=50)
    query = "maximum rated depth aluminum housing"
    hits = BM25Index(chunks).search(query, top_k=3)
    client = NebiusTokenFactoryClient()

    quotes = []
    for i in range(25):
        proposal = await propose(query, hits, client)
        assert proposal is not None, f"run {i}: model reported not-found for a fact genuinely in the corpus"
        quotes.append(proposal.quote)
        assert "Aluminum" in proposal.quote and "300" in proposal.quote, (
            f"run {i}: expected the Aluminum:300m line every time, got {proposal.quote!r} -- "
            f"quotes so far: {quotes}"
        )


@_requires_live_key
async def test_live_adversarial_unit_conversion_fabrication_is_caught_not_trusted():
    """FOUND LIVE (external review follow-up), scope corrected on a second
    manual review (2026-10-21) -- read the caveats below before citing this
    as "fabrication is caught":

    1. **This tests `_spec_depth_m()`, not `verify_proposal()`.** It says
       nothing about whether a live model has ever tried to fabricate a
       QUOTE (invent text the source never said) -- that's verify_proposal()'s
       own job and remains covered only by scripted-liar tests elsewhere in
       this file. This test is narrower: given a quote that IS genuinely
       verbatim (verify_proposal() independently confirms that below), does
       the separate `value` field the model also returned agree with the
       number that quote itself states?
    2. **"Fabrication" overclaims what's actually being provoked.** The query
       explicitly asks for a unit conversion ("...in feet, convert from
       meters") against DOC1's real corpus text (which only ever states
       meters) -- a `value` that disagrees with the quote's own number is
       exactly what a CORRECT unit conversion would also produce (300 m is
       genuinely ~984.25 ft). This test cannot and does not distinguish
       "the model fabricated a number" from "the model did the conversion
       it was asked to do and attached the result as if the cited text said
       it." Either way, `_spec_depth_m()`'s job is the same: a `value` that
       doesn't match its own cited quote is untrusted and must be discarded,
       regardless of whether the mismatch came from fabrication or from
       correct-but-undisclosed arithmetic -- that's the real property this
       test demonstrates, not "the model lied and got caught."
    3. Observed live at roughly 7.5% (3/20, then 0/20 across two independent
       20-sample batches) -- genuinely probabilistic, not a fixed rate; see
       the loop below for why 50 samples and a `skip`-on-zero are used
       instead of a hard assertion."""
    import re
    from pathlib import Path

    from anticassiopeia.domains.robotics import _spec_depth_m
    from anticassiopeia.llm.nebius_client import NebiusTokenFactoryClient
    from anticassiopeia.retrieval import BM25Index, chunk_document
    from anticassiopeia.retrieval.extract import propose
    from anticassiopeia.retrieval.verify import verify_proposal

    text = Path("anticassiopeia/corpus/doc1_bluerov2_excerpt.txt").read_text()
    chunks = chunk_document("DOC1_BlueROV2", text, chunk_size=300, overlap=50)
    chunks_by_id = {c.chunk_id: c for c in chunks}
    adversarial_query = "maximum rated depth aluminum housing in feet, convert from meters"
    hits = BM25Index(chunks).search("maximum rated depth aluminum housing", top_k=3)
    client = NebiusTokenFactoryClient()

    # Confirmed genuinely probabilistic, not a fixed rate: an initial 20-sample
    # batch that found this pattern got 3/20; a second, independent 20-sample
    # batch immediately after got 0/20 (combined ~7.5% across 40 live calls).
    # 50 samples here is a deliberate margin over that -- enough that a true
    # rate anywhere near what's actually been observed makes an all-zero run
    # unlikely, without pretending a single fixed trial count makes this a
    # fully deterministic check of inherently probabilistic live behavior.
    value_quote_mismatches_observed = 0
    for i in range(50):
        proposal = await propose(adversarial_query, hits, client)
        if proposal is None:
            continue

        # If verify_proposal() itself rejects the quote as non-verbatim, that's the
        # SYSTEM correctly catching a different failure mode (a fabricated quote, not
        # a value/quote mismatch) -- not a bug in this test. Skip the run rather than
        # hard-failing on behavior this test isn't about and that it would be wrong to
        # penalize (a prior version asserted the quote must always be accepted, which
        # would have spuriously failed the whole test on exactly the run where
        # verify_proposal() did its job best).
        result = verify_proposal(proposal, chunks_by_id, source="DOC1_BlueROV2", stance="supports", trust=0.8)
        if not result.accepted:
            continue

        quote_match = re.search(r"(\d+(?:\.\d+)?)\s*(m|bar)\b", proposal.quote)
        assert quote_match, f"run {i}: couldn't find the real number in the verbatim quote {proposal.quote!r}"
        quote_number = float(quote_match.group(1))
        value_mismatches_quote = proposal.value is not None and abs(float(proposal.value) - quote_number) > 0.5

        spec_depth, _converted, problem = _spec_depth_m(proposal.quote, proposal)
        if value_mismatches_quote:
            value_quote_mismatches_observed += 1
            assert spec_depth is None, (
                f"run {i}: model fabricated value={proposal.value!r} {proposal.unit!r}, not stated in its own "
                f"verbatim quote {proposal.quote!r}, but _spec_depth_m did not discard it (got {spec_depth})"
            )
            assert problem is not None and "quote states" in problem, (
                f"run {i}: expected a named 'value disagrees with quote' rejection reason, got {problem!r}"
            )

    if value_quote_mismatches_observed == 0:
        pytest.skip(
            "did not observe the known value/quote mismatch pattern in these 50 live calls -- this is "
            "probabilistic live model behavior (observed ~7.5% across 40 earlier calls), not a regression; "
            "a SKIP here means this run didn't get to exercise the defense, not that the defense failed. "
            "Rerun, or widen the sample, to get an actual pass/fail on the thing this test checks."
        )
