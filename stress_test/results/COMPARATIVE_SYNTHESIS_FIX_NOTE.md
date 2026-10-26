# Comparative-synthesis contradiction fix — root cause, fix, live validation

Date: 2026-10-26. Context: `BENCHMARK_ROUND2_REPORT.md` flagged category 1's
55% conservative-miss rate for investigation "first inspect the missed
claims, identify why, then test candidate thresholds" — not a blind
threshold nudge. This is that investigation and the fix it led to.

## Root cause (not what was assumed)

Re-ran all 11 category-1 conservative misses + the 1 dangerous miss live,
capturing full evidence/reasoning (round 2's own scorecard only kept
predicted verdict + severity — the same gap already flagged for the 3
dangerous misses). Result: **9 of the 11 had ZERO evidence gathered at
all** — every individual source checked (3-6 per claim) came back "doesn't
address this specific claim" or "model honestly reported absence." The
one claim that looked like "a lone contradicting source flipped the
verdict too fast" (`gemini-012`, Newton/Leibniz) did not even reproduce
that pattern on this re-run — it came back zero-evidence too, confirming
that result was a one-off live-search draw, not representative.

The real, dominant shape: claims like *"the Industrial Revolution was
caused by cheap cotton via the Louisiana Purchase"* — real sources
describe the actual causes (textile mechanization, coal, trade) but never
explicitly quote-refute that specific invented mechanism. `judge_stance()`'s
existing SECOND paragraph (deliberately, correctly) rejects each such
passage individually as "unrelated," since none of them states or denies
the claim's specific assertion — that strictness is exactly right for
*confirming* (a passage's silence must never let a false claim through),
but it left a real gap for *contradicting*: when multiple sources
collectively describe a different, incompatible account, no mechanism
existed to recognize that.

## Fix — additive, not a change to the existing strict check

`retrieval/stance.py` gains `judge_comparative_stance()` — a separate
function, separate prompt (`COMPARATIVE_STANCE_SYSTEM_PROMPT`), never
touching `judge_stance()` or its existing four paragraphs. It only ever
runs (`domains/searchlight.py`'s `_gather_multi_candidate`) when:
- both passes (normal + escalation) found **zero** direct evidence, and
- at least 2 independent, already-verified "unrelated" quotes exist to
  compare (a single quote's silence proves nothing and must never trigger
  this on its own — `_MIN_QUOTES_FOR_COMPARATIVE_SYNTHESIS = 2`).

The prompt is deliberately conservative: "contradicts" only when the
passages *positively* describe an incompatible account, explicitly never
for mere silence ("mere absence of confirmation is not evidence of
denial" is locked into the prompt and tested against regression). Result
evidence is weighted at `_COMPARATIVE_SYNTHESIS_TRUST = 0.6` — above
`DECISION_THRESHOLD` (0.5) so it can produce a real verdict, but below
direct-evidence trust (0.75), reflecting the extra inferential step.
Can never produce "supports" — this recovers contradictions only, since
confirming is exactly the case the existing strictness protects.

Also addressed (same investigation, user's own request): the final
gap-description when evidence stays empty now reads "hasn't been
conclusively resolved from what they say," not "no evidence produced" —
honest about *why* (checked real sources, found real but inconclusive
material) rather than implying nothing was looked at.

## Live validation — real result, not just unit tests

Re-ran the same 12 claims live after the fix. Comparing the two runs
claim-by-claim (full evidence inspected, not just verdicts, to correctly
attribute cause):

| Claim | Before | After | Cause |
|---|---|---|---|
| `gemini-011` (printing press) | conservative_miss (0 evidence) | **correct** (contradicted) | **Comparative synthesis fired** — "comparative synthesis across 2 sources" |
| `gemini-022` (Industrial Revolution) | conservative_miss (0 evidence) | **correct** (contradicted) | **Comparative synthesis fired** — "comparative synthesis across 3 sources" |
| `chatgpt-031` (Higgs boson) | conservative_miss (0 evidence) | correct (contradicted) | Live-search variance — a direct single source was found this run, unrelated to this fix |
| `chatgpt-030` (Eddington eclipse) | correct | conservative_miss | Live-search variance (unrelated to this fix) |
| `gemini-012` (Newton/Leibniz) | conservative_miss (0 evidence) | dangerous (contradicted, truth=confirmed) | Live-search variance — same direct single source (`bhanzu.com`) the original benchmark's own post-hoc re-run already found and discussed as a genuine ground-truth tension, not new |
| 5 others | conservative_miss | conservative_miss (unchanged) | Synthesis attempted, stayed undetermined (correctly — no incompatible account found), or <2 quotes available |

**Cleanly attributable to this fix: 2 real recoveries (`gemini-011`,
`gemini-022`), both correct, zero attributable regressions.** The other
changes between runs are ordinary live-search non-determinism (documented
throughout this project — Piltdown Man's non-reproduction is the other
concrete example), not caused by this change. `gemini-012`'s dangerous
result is the SAME already-known, already-discussed ground-truth tension
flagged in `BENCHMARK_ROUND2_REPORT.md`'s own "Next round" item (a), not
a new problem this fix introduced.

## What this does NOT fix

The 5 unchanged claims (`gemini-023`, `gemini-032`, `gemini-043`,
`gemini-051`, `perplexity-010`) still correctly land on undetermined —
either comparative synthesis ran and genuinely found no incompatible
account (the honest answer for some of these), or fewer than 2 usable
"unrelated" quotes were available to compare. This is not a complete
fix for category 1's conservative-miss rate — it recovers the specific
"sources describe a different story but never explicitly rebut the
claim" shape, not every possible miss. Full category-1 re-measurement
at round-2 scale (all 20 claims) was not re-run here — this validation
was scoped to the 12 claims already investigated, per the project's own
small-deliberate-check discipline (same as `DECISION2_REMEASUREMENT_NOTE.md`).
