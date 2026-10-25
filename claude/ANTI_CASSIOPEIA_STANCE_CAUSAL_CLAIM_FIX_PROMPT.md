# Anti-Cassiopeia — stance-judgment fix for causal/relational claims

## PROMPT TO HAND TO THE NEXT SESSION, VERBATIM

A real, live test on the deployed v3 build (`/verify/compound` against a
genuine historical claim from quantum cryptography) found a specific,
reproducible gap in `retrieval/stance.py`'s `judge_stance()`. This prompt
is the complete, locked spec for the fix — small, single-file, same shape
as the ESP32/ESP32-S31 fix already documented in that file's own
docstring. Read `retrieval/stance.py` in full before changing anything —
the fix is an addition to its existing `STANCE_SYSTEM_PROMPT`, not a
rewrite.

## §0. The finding, exact and reproducible

Live test, 2026-10-25, against the deployed Cloud Run service's
`/verify/compound`, claim text:

> "Charles Bennett and Gilles Brassard developed the BB84 quantum key
> distribution protocol in 1984 by building on Stephen Wiesner's earlier
> concept of quantum conjugate coding, which Wiesner originally conceived
> around 1970 but could not get published until 1983."

Decomposed into 4 sub-claims, 3 of which (dates, names, publication delay)
were correctly confirmed with solid multi-source evidence. **Sub-claim #2
is the problem:**

> "The BB84 protocol was built on Stephen Wiesner's earlier concept of
> quantum conjugate coding." → `CONFIRMED` (confidence 0.90)

on exactly ONE piece of evidence (from `qsnp.eu`, a physics-outreach site):

> "In 1984, the two combined quantum conjugate coding with a cryptographic
> key-exchange scheme, producing what became known as the BB84 protocol."

**Why this is wrong, or at least unjustified by the evidence actually
found:** that sentence narrates a sequence of events compatible with "built
on" (direct causal dependency — Bennett & Brassard knew of and used
Wiesner's work) but does not actually establish it, and real historical
accounts (Brassard's own retrospectives on the history of quantum
cryptography) describe BB84 as closer to an **independent rediscovery**:
Bennett and Brassard were likely unaware of Wiesner's 1983 paper (published
in an obscure newsletter) when they invented BB84 in 1984, and only later
had Wiesner's priority pointed out and credited it. "Built on" implies
direct dependency; "independently reinvented, later credited" is a
materially different historical claim. Confirmed live: asking Nemotron-3
Ultra directly (not through this pipeline) to verify the same sentence
correctly flagged exactly this distinction and called the "building on"
framing false/imprecise, citing the independent-rediscovery account.

**Root cause, precisely:** `judge_stance()` only ever asks "does this
passage support, contradict, or fail to address the claim's specific
assertion" — it has no notion of evidence *strength* for a causal claim
specifically. A passage that is merely *consistent with* a causal
relationship (doesn't contradict it, mentions both things in the same
breath) gets the same "supports" verdict as a passage that actually
*asserts* the causal relationship. This is a correctness gap specific to
**relational/causal claims** ("X was built on Y", "X was inspired by Y",
"X caused Y", "X was derived from Y") — it does not affect plain factual
claims (a date, a name, a numeric spec), where "the passage states the
fact" and "the passage supports the claim" are the same thing. This is
also why sub-claims #1/#3/#4 above (plain factual claims) were all
correctly, solidly confirmed — the gap is specific to this one claim
*shape*, not a general retrieval-quality problem.

## §1. Locked fix

Add ONE new paragraph to `retrieval/stance.py`'s `STANCE_SYSTEM_PROMPT`,
immediately after the existing entity-matching caution (the
ESP32/ESP32-S31 paragraph) — same prompt, same function, no new module, no
new call site, no change to `judge_stance()`'s signature or the
"supports"/"contradicts"/"unrelated" three-way contract:

```
SECOND, for a claim that asserts a CAUSAL or DEPENDENCY relationship between two \
things (e.g. "X was built on Y", "X was inspired by Y", "X was derived from Y", "X \
caused Y") — as opposed to a claim stating a single fact about one thing (a date, a \
name, a number) — check whether the passage actually STATES that relationship, not \
just whether it mentions both things in a way that is merely consistent with it. A \
passage that narrates two things happening in the same event or time period, without \
explicitly asserting that one depended on, was derived from, or was caused by the \
other, does NOT support a causal/dependency claim about them — treat it as \
"unrelated" to that specific relational assertion, even though it would be real, \
valid supporting evidence for a plain claim about either thing on its own. This \
matters because many real historical/technical narratives describe two actually- \
independent developments in the same breath without asserting either caused the \
other.
```

(Wording above is a draft starting point, not frozen word-for-word — keep
the core distinction, polish the phrasing if it reads awkwardly once
tested against real live calls; what must NOT change is the underlying
rule: narrative co-occurrence ≠ asserted causation.)

**Why this is the right scope, and why not to do more:**
- This is additive to the existing prompt, not a rewrite — the
  ESP32/ESP32-S31 entity-matching caution and the three-way
  supports/contradicts/unrelated contract are both proven, live-tested,
  and used by both `research_web.py` and `robotics.py`'s BYOE/pool paths.
  Do not touch anything else in this file.
- Do NOT add a new return value (e.g. a 4th "weakly-supports" category) —
  that would be a breaking contract change touching every caller
  (`research_web.py`, `robotics.py`'s `_gather_byoe`/`_gather_byoe_pool`).
  Folding this into "unrelated" for causal claims specifically is
  sufficient and keeps the existing three-way contract intact everywhere.
- Do NOT try to detect "is this a causal claim" with a separate regex or
  classifier before calling `judge_stance()` — the model itself, given
  both the claim and the passage in one call, is better positioned to
  judge "does this specific passage establish this specific relationship"
  than a keyword heuristic ("built on", "inspired by", "based on", "led
  to", "derived from", "caused" is already a non-exhaustive, gameable
  list) — exactly the same reasoning the existing entity-matching caution
  already uses (ask the model to check, don't pre-filter with code).

## §2. Testing — real, not just offline

1. **Offline regression test** (`tests/test_retrieval_stance.py` — check if
   this file exists yet; create it if not, following the existing fake-client
   test pattern used elsewhere in `tests/`): a fake client scripted to
   return the ESP32/ESP32-S31 behavior must still pass unchanged (don't
   regress the existing fix). A NEW fake-client case: claim "X was built on
   Y", passage "In 1984, the two combined A with B, producing C" (the exact
   real Wiesner/BB84 shape above, anonymized or literal) — assert the
   expected judgment is `"unrelated"`, not `"supports"`.
2. **Live re-test, small and deliberate** (budget discipline — this is ONE
   live call, not a new stress-test suite): re-run the exact Wiesner/BB84
   `/verify/compound` call from §0 against the fixed code, confirm
   sub-claim #2 now comes back `UNDETERMINED` (or `CONFIRMED` only if a
   better, more explicit source is found by `research_web`'s live search at
   that moment — live search results vary run to run, same honest caveat
   this project's own test suite already documents) rather than a
   `CONFIRMED` built on evidence that doesn't actually establish the
   relationship.
3. Confirm the full offline suite stays green (355 passed / 13 skipped is
   the baseline going into this fix).
4. Also worth a quick live spot-check (not a full suite): re-run ONE of the
   existing proven-good cases (e.g. the ODrive BYOE confirm from the v2
   stress test, or the Nobel Prize/Higgs boson `research_web` tests from
   this session's live testing) to confirm the new prompt paragraph doesn't
   make the model newly over-cautious on claims that are NOT causal/
   relational — those should be entirely unaffected (the new paragraph is
   explicitly scoped to causal/dependency claims only), but a live
   confirmation costs one call and removes doubt.

## §3. Write up what's found, honestly, same convention as every other
   phase of this project

If the live re-test confirms the fix works as intended, add a short,
dated entry to `stress_test/BUGS_FOUND.md` (or wherever this project's
convention keeps its "found live, here's the root cause, here's the fix,
here's what was deliberately left unchanged" write-ups) describing exactly
what's in §0 above — this was found by the project owner directly testing
the live deployed `/verify/compound` endpoint against a real, obscure
historical claim from their own research area (quantum key distribution),
not by an internal test suite, which is itself worth noting as a real
example of the system being validated by actual use, not just synthetic
tests.

## Addendum: model-choice question raised alongside this fix

While applying this fix, the project owner raised a related question: the
live finding's own §0 text already notes that asking Nemotron-3 Ultra
directly (outside this pipeline) got the Wiesner/BB84 distinction right —
suggesting `judge_stance()`'s MODEL, not just its prompt, may matter for
this claim shape specifically. A live paired test (gpt-oss-120b vs.
Nemotron Ultra, same fixed prompt, same real claim/passage pair) confirmed
this directly: gpt-oss-120b still returned "supports" even with the fixed
prompt; Nemotron Ultra returned "unrelated", correctly. This is real,
live, n=1 evidence — not yet the statistically-powered sample this
project's own `NEMOTRON_PIVOT_REPORT.md` standard requires before
committing to a permanent model-routing change. See
`stress_test/results/` for the follow-up small-sample test this prompted,
and `claude/ANTI_CASSIOPEIA_COMPETITIVE_BENCHMARK_PROTOCOL.md`'s category
1 for where this question is meant to be settled at proper scale.
