"""
Stance judgment for an ALREADY-mechanically-verified quote.

Extracted out of domains/searchlight.py (2026-10-25, v2 "bring your own
evidence" build) so domains/substrate.py's new free-text BYOE path can use
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

Two mechanical approaches were tried first (on searchlight.py, before
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
#: comparison found `openai/gpt-oss-120b` (searchlight.py's own propose()
#: model) correct only 2/6 times, while this model was correct 5/5 on the
#: identical, already-fixed prompt. A 5-pair balanced sample (3 "should be
#: unrelated" / 2 "should be supports" cases) showed both models tied 5/5
#: on the EASIER pairs -- the gap is specific to genuinely borderline
#: causal/relational judgments, not a general difference. This is NOT a
#: recommendation to also move propose()/decompose() calls here --
#: NEMOTRON_PIVOT_REPORT.md already found gpt-oss-120b strictly better at
#: full-pipeline scale for searchlight's OWN propose() step; this constant
#: is scoped to judge_stance() only. substrate.py's own SUBSTRATE_MODEL
#: already happens to be this same model, for its own, broader reasons
#: (see that module) -- not imported from here, to avoid coupling two
#: adapters' otherwise-independent model choices to one shared constant
#: for what is, for substrate.py, a coincidence.
RECOMMENDED_STANCE_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"

# FOUND BUG (external review, live, during the Nemotron pivot's pilot runs — not
# hypothetical, discovered on searchlight.py before this module existed): a
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
# FOUND BUG (live, 2026-10-25, competitive-benchmark round 1's category-6
# calibration probe -- see claude/ANTI_CASSIOPEIA_COMPETITIVE_BENCHMARK_PROTOCOL.md
# §1.6): the THIRD paragraph above fixed a passage that self-hedges
# ("according to Islamic tradition..."), but a real, unhedged passage from
# gotquestions.org (a Christian apologetics Q&A site) -- "Three days later,
# His body and spirit were reunited, and He rose from the dead (John 20)" --
# got "supports" for the flat claim "Jesus Christ physically rose from the
# dead three days after his crucifixion", producing a confident CONFIRMED on
# a matter of faith. judge_stance() was CORRECT that the passage addresses
# the same claim, worded as a direct assertion -- the gap is one level up:
# no passage's wording, hedged or not, can establish that a supernatural
# event objectively happened, because no empirical evidence could, even in
# principle. This is a DIFFERENT, deeper gap than the THIRD paragraph's
# hedge-detection -- it applies regardless of how confidently a source is
# worded. FOURTH check, below: is the CLAIM ITSELF (not the passage) an
# assertion of a supernatural/metaphysical event as real-world fact? If so,
# no "supports" passage can get through -- but a passage that explicitly
# contests the claim on ordinary historical/scientific grounds still can,
# since doubting a miracle rests on ordinary evidence in a way confirming
# one never could. Carved out explicitly: a claim about what a text/
# tradition SAYS (Theogony-shaped, category-3-style) or an ordinary
# historical/archaeological claim (Dead Sea Scrolls, category-5-style) is
# NOT a supernatural assertion and must keep confirming normally -- this
# paragraph is scoped narrowly to claims asserting the supernatural event
# itself as objective fact, not to religion/mythology/archaeology claims in
# general.
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

THIRD, check whether the passage asserts the claim's content as objective, established fact, or \
merely reports that it is something a specific religious tradition, belief system, culture, or \
group of people HOLDS or BELIEVES to be true (e.g. "according to Islamic tradition...", \
"Christians believe that...", "according to the Gospel accounts...", "in Hindu cosmology..."). A \
passage that attributes a claim to a tradition or belief, without itself vouching for the claim \
as objective fact, does NOT support a claim that is phrased as a flat, unqualified assertion \
about the real world — it would only support a DIFFERENT claim explicitly about what that \
tradition or group believes, which is not the same claim. Treat such a passage as "unrelated" to \
the flat, unqualified claim, UNLESS the claim itself is explicitly phrased as being about what a \
tradition or group believes (e.g. "Islamic tradition holds that...") rather than asserting the \
underlying event as fact — in that matching case, judge it normally. This matters because an \
encyclopedic source can state a supernatural or doctrinal claim's existence as a documented belief \
(a real, verifiable fact about what people believe) while explicitly declining to assert the \
underlying supernatural event itself as true — conflating the two turns "this is a documented \
belief" into a false "this is a confirmed fact," which is exactly the kind of overconfident \
answer this project exists to prevent, especially for claims about matters of faith that no web \
source can actually settle either way.

FOURTH, check whether the CLAIM ITSELF (not the passage) asserts that a supernatural or \
metaphysical event literally, objectively happened in the real world -- a resurrection, a divine \
revelation, a miracle, or the literal truth of a religious doctrine's supernatural content -- as \
opposed to a claim about what a text, tradition, or group of people SAYS, RECORDS, or TEACHES \
(e.g. "In Hesiod's Theogony, Cronus castrates Uranus", "the Gospels record that...", "Islamic \
tradition teaches that...") or an ordinary historical/archaeological claim (e.g. when and where a \
manuscript was found, who excavated a site) -- those remain ordinary, confirmable claims about \
real, checkable facts (what a text says, what was found where and when), NOT supernatural \
assertions, and this paragraph does not apply to them; judge them normally under the rules above. \
For a claim that DOES assert a supernatural event as objective real-world fact: no source's \
wording, however confident or authoritative-sounding, can establish that it actually happened, \
because no empirical evidence could confirm it even in principle -- treat ANY passage that would \
otherwise "support" this specific supernatural assertion as "unrelated" instead, even a passage \
that states it as flat, unhedged fact with no caveat at all. This is NOT the same situation the \
THIRD paragraph above covers (a passage that hedges its own wording) -- this applies regardless of \
how the passage is worded, because the problem is the CLAIM's own unfalsifiable nature, not the \
source's phrasing. A passage that explicitly CONTESTS or undermines the claim on ordinary \
historical, textual, or scientific grounds (e.g. "no contemporary record corroborates this", \
"textual analysis dates this account to long after the events it describes") is NOT blocked the \
same way -- ordinary evidence CAN cast real doubt on a supernatural claim even though no evidence \
can confirm one, so judge a genuinely contesting passage normally, as "contradicts".

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


# FOUND (round 2 competitive benchmark, 2026-10-26): of category-1's 11
# conservative misses, 9 had ZERO evidence at all -- not one contradicting
# source trusted too readily (the one claim that looked like that,
# gemini-012/Newton-Leibniz, didn't even reproduce that pattern on replay).
# The real, dominant shape: the SECOND paragraph above (correctly) rejects
# every individual passage as "unrelated" because none of them explicitly
# states or denies the claim's specific causal mechanism -- even when
# MULTIPLE passages, read together, clearly describe a different, real
# account that the claim's specific mechanism doesn't fit (e.g. three
# sources on the Industrial Revolution's actual causes, none of which ever
# says "not cheap cotton via the Louisiana Purchase", but none of which
# mentions that mechanism either, instead describing textile mechanization,
# coal, and trade broadly). A human reading all three would call the claim
# false; judge_stance() checking each ALONE never gets there, by design --
# that design is still correct for CONFIRMING (one passage's silence
# shouldn't let a claim through), but it leaves a real gap for
# CONTRADICTING via synthesis across sources.
#
# judge_comparative_stance() below is a SEPARATE, additive capability, not
# a change to judge_stance() or its prompt above -- it only ever runs (see
# searchlight.py's _gather_multi_candidate) when gather_evidence() would
# otherwise return nothing at all (every individual passage already judged
# "unrelated"), and only when at least 2 independently-sourced passages
# are available to compare, since a single passage's silence proves
# nothing and this function must not become a backdoor around the SECOND
# paragraph's deliberate strictness. Deliberately conservative: it must
# answer "contradicts" only when the passages themselves describe a
# positive, incompatible account, never merely because they're silent on
# the claim's specific mechanism (silence is what judge_stance() already
# handles correctly as "unrelated" -- this function's whole job is telling
# "silent" apart from "describes something else that doesn't fit").
COMPARATIVE_STANCE_SYSTEM_PROMPT = """You will be given a CLAIM and several PASSAGES. Each passage has \
already been independently confirmed to be real, verbatim text from a real source, and each was \
ALREADY checked individually and found not to directly state or deny the claim's specific assertion. \
Your job is different: look at the passages TOGETHER and decide whether they collectively describe a \
different, real account of the same event or relationship that is genuinely INCOMPATIBLE with the \
claim's specific assertion -- not whether they merely fail to confirm it.

Answer "contradicts" ONLY if the passages, taken together, consistently describe what actually \
happened, caused, or was responsible, AND that real account leaves no room for the claim's specific \
mechanism to also be true (e.g. the passages describe several different real causes of an event, none \
of which is the one the claim names, and naming the real causes implicitly rules out the claim's \
invented one). Do NOT answer "contradicts" just because the passages are silent about the claim's \
specific mechanism, cover a related but different aspect, or could in principle coexist with it --mere \
absence of confirmation is not evidence of denial, and this is NOT license to treat silence as \
contradiction. If you are not genuinely confident the passages describe an incompatible account, \
answer "undetermined".

Reply with EXACTLY one word: contradicts or undetermined."""


async def judge_comparative_stance(
    client: NebiusTokenFactoryClient, claim_text: str, verified_quotes: list[str]
) -> str:
    """Returns "contradicts" | "undetermined" -- never "supports": this
    function only ever runs when gather_evidence() would otherwise be
    empty, specifically to recover a CONTRADICTION synthesized across
    multiple individually-"unrelated" passages (see the module-level
    comment above) -- it has no role in confirming a claim, which is
    exactly the case judge_stance()'s existing SECOND paragraph already
    protects deliberately. Caller's responsibility (see searchlight.py):
    only call this with 2+ independently-sourced, already-verified quotes.
    Any model reply not containing "contradict" is treated as
    "undetermined" -- same fail-safe convention as judge_stance()."""
    numbered = "\n\n".join(f"PASSAGE {i + 1}: {q}" for i, q in enumerate(verified_quotes))
    prompt = f"CLAIM: {claim_text}\n\n{numbered}"
    raw = await client.complete(prompt, system=COMPARATIVE_STANCE_SYSTEM_PROMPT, temperature=0.0)
    word = raw.strip().lower()
    if "contradict" in word:
        return "contradicts"
    return "undetermined"
