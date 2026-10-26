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

## Competitor sweep — run (project owner's call: yes, it's required)

No new infrastructure needed, same as predicted: Track B's claims are
architecturally identical in shape to Track A (free-text claims through
the same harness functions), so the same 5-variant sweep round 2 used
applies unchanged. Script: `stress_test/run_track_b_competitors.py`
(reuses Anti-Cassiopeia's own already-captured results from
`track_b_raw.json` rather than re-running the real engine a second
time). Real cost: $0.181922 Nebius + $0.008770 Perplexity + $0.033884
Gemini (Tavily: 69 free-credit calls).

| System | Correct | Dangerous | Conservative miss | Crash |
|---|---|---|---|---|
| **Anti-Cassiopeia** | 26/69 (37.7%) | 1 | 42 | 0 |
| Bare model (no retrieval) | 66/69 (95.7%) | 1 | 2 | 0 |
| Nebius-agent | 29/69 (42.0%) | 1 | 39 | 0 |
| Generic RAG | 42/69 (60.9%) | 4 | 23 | 0 |
| Perplexity | 66/69 (95.7%) | 3 | 0 | 0 |
| Tavily+Gemini | 57/69 (82.6%) | 1 | 10 | 1 |

**This is a genuinely different, important result from Track A, not
just a smaller version of it.** Bare model — zero retrieval, pure
parametric knowledge — gets 95.7% correct, tied with Perplexity for
best of all six systems, and far ahead of Anti-Cassiopeia's 37.7%. This
makes sense once the claim shape is considered: category-8's formal/
technical claims (control theory, FPGA, digital logic, EKF-SLAM) are
well-established textbook and literature material that a capable LLM's
training data already covers cold — unlike Track A's claims (viral
myths, obscure history, calibration probes), where live, citable web
retrieval is exactly what makes the difference. **Here, retrieval is a
genuine handicap, not a help**: `searchlight`'s live web search mostly
can't find a page directly discussing "does a nonzero null-space vector
preserve end-effector pose over a finite interval," so it correctly, but
unhelpfully, defaults to conservative `undetermined` — while a model
just answering from what it already knows gets it right most of the
time. Anti-Cassiopeia's own dangerous-miss rate (1.4%) stays exactly as
safe as everywhere else; what changes here is that its retrieval-
grounded design trades a large amount of raw accuracy for that safety,
on a claim shape where the competitors' parametric knowledge happens to
already be strong. This is an honest limitation worth stating plainly,
not a reason to change anything about the engine's own design — a
retrieval-grounded verifier is not the right tool for "does the model
already know this cold," and this track demonstrates that boundary
concretely rather than leaving it theoretical.

**The one shared soft case**: `perplexity-025` (Wright Flyer "Kitty
Hawk") is dangerous for bare model, Perplexity, AND Anti-Cassiopeia —
the same popular-shorthand-vs-technical-precision tension flagged
throughout this track's own verification, not three independent system
failures. `perplexity-033` (Darwin's "survival of the fittest" phrase,
corrected to `confirmed` during this track's own verification — see that
file's commit) is where Perplexity-the-competitor lands on `contradicted`
instead — the same mistake the ORIGINAL generating AI made before
independent verification caught it, a small, concrete demonstration of
why this project never trusts a single system's own answer as ground
truth.
