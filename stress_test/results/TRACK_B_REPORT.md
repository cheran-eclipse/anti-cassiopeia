# Track B — 69 category-8 claims through the real engine

Run 2026-10-26. Claims: `stress_test/claims/external_generated/track_b_category8_formal.json`,
ground truth: `stress_test/claims/external_generated/track_b_verified.json`
(independently verified — 68/69 matched the generating AI's own
suggestion; see that file's own commit message for the one correction).
Script: `stress_test/run_track_b.py`. Real engine only this round (not the
full 5-competitor sweep round 2 used) — real cost **$0.361438**.

## Why this needed its own run, and why plain `searchlight`

These 69 claims were parked at round-2 time. Two architecture questions
had to be resolved first, both answered this session:
- `substrate` (the robotics domain) has **no live web-search path at
  all** — it's fixed-corpus (4 hardcoded hardware parts) + BYOE
  (user-uploaded documents) only. There was nothing to "port" an
  adaptive-depth path into; that framing was a mischaracterization,
  corrected before any code was written.
- `core/compound.py`'s decompose+rollup looked like a promising fit for
  these claims' common "true premise; therefore false conclusion"
  shape, but testing it live surfaced a real, separate bug: for one
  claim, `decompose_claim()` silently rewrote a sub-part into its own
  **negation**, turning an obviously-false compound claim into a false
  CONFIRMED. Not safe to use without a fix that's its own, separate
  scope of work — not attempted here.

So all 69 route through plain `searchlight`, same as Track A.

## Result: 26/69 correct (37.7%), 42/69 conservative (60.9%), 1/69 dangerous (1.4%)

**Safer than Track A's already-safe profile** (which ran 3.4% dangerous).
Makes sense architecturally: most category-8 claims are dense formal/
technical assertions (Jacobian null-spaces, FPGA fixed-point bit-
exactness, recursive QP feasibility, EKF-SLAM observability) that simply
don't have a web page directly discussing them — `searchlight` correctly
finds nothing usable and stays `undetermined` rather than guessing,
exactly the conservative failure direction this project is built around.
All 26 correct verdicts are themselves category 8 (no other category in
this track).

**The one dangerous miss (`perplexity-025`, Wright Flyer "Kitty Hawk")**
is itself a soft case, not a clean bug: the claim's precise location is
technically Kill Devil Hills, 4 miles from Kitty Hawk proper, but two
real, authoritative sources (the Smithsonian Air & Space Museum,
Wikipedia) both say "Kitty Hawk" as the flight's location — the same
popular-shorthand-vs-technical-precision tension the independent
verification pass already flagged as a judgment call (medium confidence)
for this exact claim, not a new problem this run introduced.

## What this does and doesn't tell us

Confirms the engine's conservative-failure design holds even on claims
far outside its usual subject matter (formal engineering/math, not
history/mythology/conspiracy) — if anything, it gets MORE conservative
here, which is the right direction. Does NOT yet give a "which model
works for which" comparison for this track (no competitor run) — if
that's wanted, the same `_for_competitor_harness()`-style domain patch
round 2 used would apply identically here; not done in this pass to keep
scope and cost bounded for a track whose main open question (is this
testable at all) is what this run answers.
