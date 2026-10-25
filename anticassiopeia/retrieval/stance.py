"""
Stance judgment for an ALREADY-mechanically-verified quote.

Extracted out of domains/research_web.py (2026-10-25, v2 "bring your own
evidence" build) so domains/robotics.py's new free-text BYOE path can use
the exact same judgment logic instead of a second hand-copied prompt —
this is the one place in the repo that decides "do these two verified
texts agree", and it should stay one place, not two that could drift.

This never runs on an unverified claim: `verify_proposal()` (retrieval/
verify.py) has already confirmed the quote is real, verbatim text from a
real source (a fetched web page, or now an uploaded document) before this
module is ever called. The fabrication risk this whole project exists to
catch — an unverified quote — stays fully mechanical, upstream of this
file; only "do these two verified texts agree" is the model's job here,
which is what it's actually good at.

Two mechanical approaches were tried first (on research_web.py, before
this was its own module) and both failed on real live tests, not
hypothetically:
  1. Strict substring check: broke on a true claim whose real confirming
     sentence had extra clauses ("(ROV)", "the American marine robotics
     company") — substring containment doesn't survive real paraphrasing.
  2. Token-overlap ratio: broke the OTHER way — "BlueROV2 was developed by
     OpenROV" (false) scored "supports" against the real "...developed by
     ...Blue Robotics" sentence, because common words ("bluerov2",
     "developed", "by") dominated the overlap score while the one word
     that actually matters (OpenROV vs Blue Robotics) was just noise in
     the ratio.
A bounded LLM judgment on the already-verified pair is what's actually
used below.
"""

from __future__ import annotations

from anticassiopeia.llm.nebius_client import NebiusTokenFactoryClient

#: RECOMMENDED model for judge_stance() calls specifically -- found live
#: (2026-10-25, see claude/ANTI_CASSIOPEIA_STANCE_CAUSAL_CLAIM_FIX_PROMPT.md's
#: addendum): on the real Wiesner/BB84 causal-claim pair (this module's own
#: new "SECOND" prompt paragraph above), a real, REPRODUCED 10-call live
#: comparison found `openai/gpt-oss-120b` (research_web.py's own propose()
#: model) correct only 2/6 times, while this model was correct 5/5 on the
#: identical, already-fixed prompt. A 5-pair balanced sample (3 "should be
#: unrelated" / 2 "should be supports" cases) showed both models tied 5/5
#: on the EASIER pairs -- the gap is specific to genuinely borderline
#: causal/relational judgments, not a general difference. This is NOT a
#: recommendation to also move propose()/decompose() calls here --
#: NEMOTRON_PIVOT_REPORT.md already found gpt-oss-120b strictly better at
#: full-pipeline scale for research_web's OWN propose() step; this constant
#: is scoped to judge_stance() only. robotics.py's own ROBOTICS_MODEL
#: already happens to be this same model, for its own, broader reasons
#: (see that module) -- not imported from here, to avoid coupling two
#: adapters' otherwise-independent model choices to one shared constant
#: for what is, for robotics.py, a coincidence.
RECOMMENDED_STANCE_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"

# FOUND BUG (external review, live, during the Nemotron pivot's pilot runs — not
# hypothetical, discovered on research_web.py before this module existed): a
# passage about the ESP32-S31 ("Espressif Systems has officially started mass
# production of its new ESP32-S31 wireless microcontroller") was judged "supports"
# for a claim about the plain ESP32 — a DIFFERENT, newer chip that merely shares
# most of its name. This produced a false tie against a correct "contradicts" from
# a real source, pulling a verdict to UNDETERMINED that should have been a clean
# CONTRADICTED. FIRST check whether the passage is actually about the SAME specific
# entity the claim names — a product, model, version, or variant can share most of
# a name with a different one (ESP32 vs ESP32-S31; "iPhone 15" vs "iPhone 15 Pro")
# while being a genuinely different thing with its own facts. A passage about a
# DIFFERENT specific entity than the one the claim names is "unrelated", even if it
# uses similar or identical wording about that different entity, and even if it
# would otherwise seem to support or contradict the claim's general shape — do not
# let topical similarity substitute for actually checking the subject is the same
# one the claim names.
#
# FOUND BUG (live, 2026-10-25, direct test of the deployed /verify/compound
# against a real quantum-cryptography history claim — see
# claude/ANTI_CASSIOPEIA_STANCE_CAUSAL_CLAIM_FIX_PROMPT.md for the full
# finding): "The BB84 protocol was built on Stephen Wiesner's earlier
# concept of quantum conjugate coding" was judged "supports" on a passage
# that only narrates "In 1984, the two combined quantum conjugate coding
# with a cryptographic key-exchange scheme, producing ... BB84" — that
# sentence is consistent with a "built on" relationship but does not
# actually ASSERT one (real historical accounts describe BB84 as closer
# to an independent rediscovery, later credited to Wiesner). This is a
# gap specific to CAUSAL/DEPENDENCY claims ("X was built on/inspired by/
# derived from/caused Y") — a plain factual claim (a date, a name, a
# number) has no such gap, since "the passage states the fact" and "the
# passage supports the claim" are the same thing there. SECOND check,
# for a causal/dependency claim specifically: does the passage actually
# STATE that relationship, not just mention both things in a way that's
# merely consistent with it.
STANCE_SYSTEM_PROMPT = """You will be given a CLAIM and a PASSAGE. The passage has already been \
independently confirmed to be real, verbatim text from a real, already-verified source — your \
only job is to decide how it relates to the claim's SPECIFIC assertion, not just whether they \
share a general topic.

FIRST check whether the passage is actually about the SAME specific entity the claim names — a \
product, model, version, or variant can share most of a name with a different one (ESP32 vs \
ESP32-S31; "iPhone 15" vs "iPhone 15 Pro") while being a genuinely different thing with its own \
facts. A passage about a DIFFERENT specific entity than the one the claim names is "unrelated", \
even if it uses similar or identical wording about that different entity, and even if it would \
otherwise seem to support or contradict the claim's general shape — do not let topical similarity \
substitute for actually checking the subject is the same one the claim names.

SECOND, for a claim that asserts a CAUSAL or DEPENDENCY relationship between two things (e.g. "X \
was built on Y", "X was inspired by Y", "X was derived from Y", "X caused Y") — as opposed to a \
claim stating a single fact about one thing (a date, a name, a number) — check whether the \
passage actually STATES that relationship, not just whether it mentions both things in a way \
that is merely consistent with it. A passage that narrates two things happening in the same \
event or time period, without explicitly asserting that one depended on, was derived from, or \
was caused by the other, does NOT support a causal/dependency claim about them — treat it as \
"unrelated" to that specific relational assertion, even though it would be real, valid \
supporting evidence for a plain claim about either thing on its own. This matters because many \
real historical/technical narratives describe two actually-independent developments in the same \
breath without asserting either caused the other.

Reply with EXACTLY one word, nothing else:
supports — the passage confirms the claim's specific assertion is true, about the SAME entity the \
claim names
contradicts — the passage states something that conflicts with the claim's specific assertion \
(e.g. a different name, number, date, or entity for the same question), about the SAME entity the \
claim names
unrelated — the passage is on the same general topic but does not actually address this specific \
assertion either way, OR is about a different specific entity than the one the claim names"""


async def judge_stance(client: NebiusTokenFactoryClient, claim_text: str, verified_quote: str) -> str:
    """Returns "supports" | "contradicts" | "unrelated". Any model reply not
    containing the word "contradict" or "support" is treated as "unrelated"
    — an ambiguous judgment must not silently become a confident stance."""
    prompt = f"CLAIM: {claim_text}\n\nPASSAGE: {verified_quote}"
    raw = await client.complete(prompt, system=STANCE_SYSTEM_PROMPT, temperature=0.0)
    word = raw.strip().lower()
    if "contradict" in word:
        return "contradicts"
    if "support" in word:
        return "supports"
    return "unrelated"
