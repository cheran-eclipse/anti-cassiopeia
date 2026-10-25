"""
Tests for retrieval/stance.py's judge_stance() — the one shared place in
the repo that decides "do these two already-verified texts agree",
used by both research_web.py and robotics.py's BYOE/pool paths.

All OFFLINE: a fake client, same dual-response convention established
elsewhere in this repo (test_domains_research_web.py's/test_robotics_byoe.py's
own _FakeClient). This module's own prompt text can't be unit-tested for
whether a REAL model reasons correctly from it (that needs a live call,
see the causal-claim fix's own commit for the one deliberate live
re-test) -- what IS tested offline: judge_stance()'s own parsing contract
(any reply not containing "support"/"contradict" is "unrelated", never a
crash on an unexpected reply), and that both fix paragraphs' guidance
text is actually present in STANCE_SYSTEM_PROMPT, locking each fix in
place against an accidental future removal.
"""

import pytest

from anticassiopeia.retrieval.stance import STANCE_SYSTEM_PROMPT, judge_stance


class _FakeClient:
    def __init__(self, response: str | Exception):
        self._response = response
        self.last_prompt: str | None = None
        self.last_system: str | None = None

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        self.last_prompt = prompt
        self.last_system = system
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


# --- judge_stance()'s own parsing contract ---


async def test_supports_reply_is_parsed_as_supports():
    client = _FakeClient("supports")
    result = await judge_stance(client, "claim", "quote")
    assert result == "supports"


async def test_contradicts_reply_is_parsed_as_contradicts():
    client = _FakeClient("contradicts")
    result = await judge_stance(client, "claim", "quote")
    assert result == "contradicts"


async def test_unrelated_reply_is_parsed_as_unrelated():
    client = _FakeClient("unrelated")
    result = await judge_stance(client, "claim", "quote")
    assert result == "unrelated"


async def test_an_ambiguous_reply_defaults_to_unrelated_not_a_crash():
    """Any reply not containing "support"/"contradict" is "unrelated" --
    an ambiguous judgment must never silently become a confident stance."""
    client = _FakeClient("I'm not sure, maybe, hard to say")
    result = await judge_stance(client, "claim", "quote")
    assert result == "unrelated"


async def test_reply_is_case_and_whitespace_insensitive():
    client = _FakeClient("  SUPPORTS  \n")
    result = await judge_stance(client, "claim", "quote")
    assert result == "supports"


async def test_prompt_contains_the_real_claim_and_quote_text():
    client = _FakeClient("supports")
    await judge_stance(client, "the real claim text", "the real verified quote")
    assert "the real claim text" in client.last_prompt
    assert "the real verified quote" in client.last_prompt
    assert client.last_system == STANCE_SYSTEM_PROMPT


# --- ESP32/ESP32-S31 entity-matching fix (pre-existing) stays in place ---


def test_entity_matching_guidance_is_still_present_in_the_prompt():
    assert "SAME specific entity" in STANCE_SYSTEM_PROMPT
    assert "ESP32-S31" in STANCE_SYSTEM_PROMPT


async def test_entity_mismatch_scripted_as_unrelated_round_trips_correctly():
    """Not a test of real model reasoning (that's a live concern) -- proves
    judge_stance() correctly returns whatever the (correctly-prompted)
    model says for this shape of case, same as any other reply."""
    client = _FakeClient("unrelated")
    result = await judge_stance(
        client,
        "The ESP32 is manufactured by Espressif.",
        "Espressif Systems has officially started mass production of its new ESP32-S31 wireless microcontroller.",
    )
    assert result == "unrelated"


# --- causal/dependency-claim fix (Wiesner/BB84, new) ---


def test_causal_claim_guidance_is_present_in_the_prompt():
    assert "CAUSAL or DEPENDENCY" in STANCE_SYSTEM_PROMPT
    assert "built on" in STANCE_SYSTEM_PROMPT
    assert "merely consistent with it" in STANCE_SYSTEM_PROMPT


async def test_causal_claim_scripted_as_unrelated_round_trips_correctly():
    """The real Wiesner/BB84 shape: a passage that narrates two things in
    the same event without asserting either caused the other. Not a test
    of real model reasoning -- proves judge_stance() correctly returns
    "unrelated" for this shape once the model (correctly prompted) says
    so, same parsing contract as every other case."""
    client = _FakeClient("unrelated")
    result = await judge_stance(
        client,
        "The BB84 protocol was built on Stephen Wiesner's earlier concept of quantum conjugate coding.",
        "In 1984, the two combined quantum conjugate coding with a cryptographic key-exchange scheme, producing what became known as the BB84 protocol.",
    )
    assert result == "unrelated"


async def test_plain_factual_claim_is_unaffected_by_the_causal_guidance():
    """No regression: a plain factual claim (not causal/relational) still
    round-trips a real "supports" exactly as before -- the new paragraph
    is scoped to causal/dependency claims only, per its own wording."""
    client = _FakeClient("supports")
    result = await judge_stance(
        client,
        "The Widget Mk4 enclosure carries an IP68 rating.",
        "The Widget Mk4 enclosure carries an IP68 rating and is certified for continuous operation when fully submerged.",
    )
    assert result == "supports"
