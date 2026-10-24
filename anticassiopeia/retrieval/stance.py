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
