# Stress Test #1 — Full Report

3,311 claims, run through the real production pipeline (`anticassiopeia.core.VerificationEngine`
+ the actual domain adapters, imported normally — read-only use of `anticassiopeia/`, nothing
fixed inline). Run in one batch, tag `full`, raw per-claim results in
`stress_test/results/test1_raw.jsonl`. Pilot-stage results (40 claims across two earlier pilots,
superseded by this full run) are kept separately in `test1_pilot_only.jsonl`.

## Top-line

| | |
|---|---|
| Total claims | 3,311 |
| Correct | 3,287 (99.3%) |
| Conservative misses | 7 (0.2%) |
| **Dangerous** (confidently wrong) | **12 (0.4%)** |
| **Crashes** | **5 (0.2%)** |
| Actual total spend | **$0.216879** |
| Budget hard stop | $6.00 (3.6% used) |

**Phase B addendum (2026-10-19, external review):** the single 99.3%
figure above blends two genuinely different kinds of task — computed
answers that have no real way to be "almost right," and real
evidence-weighing that can fail in genuinely interesting ways. Read as
two numbers instead of one:

| | n | Correct |
|---|---|---|
| **Deterministic domains** (ml_data + fpga_embedded — computed, not verified) | 2,889 | 2,877 (99.58%) |
| **Verification domains** (robotics + research_web — real evidence-weighing) | 422 | 410 (97.16%) |

The deterministic domains' 0.42% of errors are exactly the pre-fix NaN
bug this run itself found (see `BUGS_FOUND.md`) — now fixed, see the
re-verification note at the end of this report. The verification
domains' 2.84% is where this project's actual hard problem lives, and
it's the one blended into invisibility by the deterministic domains'
sheer volume (2,889 vs. 422 claims) in the single top-line number above.

## Per-domain, per-tier confusion matrix

Rows show (ground truth → predicted) pairs that actually occurred; a
tier/domain combination with only matching-diagonal rows had zero
errors of any kind.

### `fpga_embedded` (385 claims, $0 — no LLM calls)

| Tier | truth → predicted | n |
|---|---|---|
| 1 | confirmed → confirmed | 85 |
| 1 | contradicted → contradicted | 84 |
| 2 | confirmed → confirmed | 23 |
| 2 | contradicted → contradicted | 23 |
| 3 | confirmed → confirmed | 84 |
| 3 | contradicted → contradicted | 84 |
| 3 | undetermined → undetermined | 2 |

**Zero errors across all 385 claims, all 3 tiers.** The §4.6 real-Vivado-format
rewrite holds up completely under volume, including the two genuinely
real adversarial NA-valued reports (correctly UNDETERMINED, tier 3).

### `ml_data` (2,504 claims, $0 — no LLM calls)

| Tier | truth → predicted | n | |
|---|---|---|---|
| 1 | confirmed → confirmed | 1045 | |
| 1 | contradicted → contradicted | 449 | |
| 1 | confirmed → contradicted | 4 | **dangerous** |
| 1 | confirmed → CRASH | 1 | **crash** |
| 1 | contradicted → CRASH | 1 | **crash** |
| 2 | confirmed → confirmed | 297 | |
| 2 | contradicted → contradicted | 401 | |
| 2 | confirmed → contradicted | 2 | **dangerous** |
| 2 | confirmed → CRASH | 1 | **crash** |
| 2 | contradicted → CRASH | 2 | **crash** |
| 3 | confirmed → confirmed | 149 | |
| 3 | contradicted → contradicted | 150 | |
| 3 | undetermined → undetermined | 1 | |
| 3 | confirmed → contradicted | 1 | **dangerous** |

All 12 errors (7 dangerous + 5 crash) are the SAME real bug, isolated to
one file/column: `auto_mpg.csv`'s `horsepower`, which UCI itself encodes
6 missing readings as the literal string `"NaN"`. Full root-cause writeup
in `BUGS_FOUND.md`. **Zero errors across the other 13 real datasets and
every other column** (2,492 of 2,504 ml_data claims correct).

### `robotics` (398 claims, $0.197106)

| Tier | truth → predicted | n | |
|---|---|---|---|
| 1 | confirmed → confirmed | 73 | |
| 1 | contradicted → contradicted | 76 | |
| 1 | undetermined → undetermined | 2 | |
| 2 | confirmed → confirmed | 76 | |
| 2 | contradicted → contradicted | 73 | |
| 3 | confirmed → confirmed | 3 | |
| 3 | contradicted → contradicted | 3 | |
| 3 | undetermined → undetermined | 87 | |
| 3 | undetermined → confirmed | 1 | **dangerous** |
| 3 | undetermined → contradicted | 4 | **dangerous** |

All 5 dangerous results are BlueROV2 claims in the genuine 100–300m
two-source-conflict zone (same scenario `bluerov2_200m_conflict_undetermined.json`
already tests). Root-caused directly (10 live reruns, isolated per-step):
roughly 1 in 10 live calls for a single corpus doc's evidence comes back
empty even though the fact is genuinely there (found correctly the other
9/10 times) — when that lands on just ONE of the two conflicting sources,
the engine never sees the conflict and renders a confident verdict off
the one source that came through. **393 of 398 (98.7%) robotics claims
correct** — including 87/92 (94.6%) of the conflict-zone tier-3 claims
specifically, which is the real, live, per-call reliability floor for
this specific failure mode, not a guess.

### `research_web` (24 claims, $0.019773)

| Tier | truth → predicted | n | |
|---|---|---|---|
| 1 | confirmed → confirmed | 4 | |
| 1 | confirmed → undetermined | 4 | conservative miss |
| 2 | contradicted → contradicted | 5 | |
| 2 | contradicted → undetermined | 3 | conservative miss |
| 3 | undetermined → undetermined | 8 | |

All 7 conservative misses are the already-known, already-documented
search-reliability limitation (`research_web.py`'s own module docstring):
Wikipedia's relevance search sometimes doesn't surface the right article
when the query contains a specific number (confirmed directly in §4.7's
pilot — the false-year "ArduPilot ... 1999" query returns unrelated
Australian Air Force pages). **Zero dangerous results** — every miss fell
safely to UNDETERMINED, never a confident wrong answer. 17/24 (70.8%)
correct; the other 7 are honest "couldn't find a usable source," not
wrong answers.

## Error severity — kept separate, never merged into one "error rate"

**(a) Dangerous (confidently wrong): 12 / 3,311 (0.4%)**
- 7 in `ml_data`, all the same real NaN-handling bug (see `BUGS_FOUND.md`).
- 5 in `robotics`, all the same real multi-source-conflict-masking issue (see `BUGS_FOUND.md`).
- 0 in `fpga_embedded`, 0 in `research_web`.

**(b) Conservative misses (overly cautious, not wrong): 7 / 3,311 (0.2%)**
- All 7 in `research_web`, all the same already-documented search-reliability limitation.
- 0 in the other three domains.

No claim in this run fell into the "confident guess on a claim that was
genuinely unanswerable" sub-case of dangerous that §4.7's harness
specifically watches for as distinct from "confidently wrong in the
opposite direction" — all 12 dangerous results were real evidence
mishandling (NaN propagation/crash, or a conflict masked by partial
evidence loss), not a model inventing an answer from nothing.

## Latency distribution (p50 / p95 / p99, seconds)

| Domain | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| fpga_embedded | 385 | 0.001 | 0.002 | 0.003 | 0.004 |
| ml_data | 2,504 | 0.034 | 0.554 | 0.780 | 3.645 |
| robotics | 398 | 2.617 | 4.338 | 4.948 | 6.402 |
| research_web | 24 | 6.966 | 10.704 | 11.223 | 11.223 |

fpga_embedded/ml_data are pure local parsing/computation (no network) —
sub-millisecond to sub-second even at the tail. robotics' live propose()
calls land around 2.6-5s typically. research_web is the slowest, as
expected: real web search (DDG + Wikipedia) plus up to 3 sources' worth
of real propose()+judge_stance() calls per claim.

## Actual spend by domain

| Domain | Spend | Claims | $/claim |
|---|---|---|---|
| ml_data | $0 | 2,504 | $0 |
| fpga_embedded | $0 | 385 | $0 |
| robotics | $0.197106 | 398 | $0.000495 |
| research_web | $0.019773 | 24 | $0.000824 |
| **Total** | **$0.216879** | **3,311** | |

657 live Nebius API calls total, 422,092 prompt tokens + 255,942
completion tokens. Robotics dominates spend here simply because it has
far more claims (398 vs. research_web's 24), not because it's more
expensive per claim — research_web's $/claim is actually higher (more
live calls per claim: up to 3 sources × 2 calls each, vs. robotics' 1-2
calls per claim). Real spend ($0.217) came in slightly under the
pre-run extrapolation ($0.289) — consistent with a cost model built from
a real, if small, pilot sample, not off by an order of magnitude either
direction. **3.6% of the $6.00 budget used; the hard stop was never
approached.**

## Real bugs found — full detail in `stress_test/BUGS_FOUND.md`

1. **`ml_data.py` doesn't filter non-finite (NaN/Infinity) values.** A real
   UCI dataset (`auto_mpg.csv`) spells missing data as the literal string
   `"NaN"`, which `float()` parses without raising. Silently wrong answers
   for `mean`/`median`/`p25`/`p75`/`correlation`; an uncaught crash for
   `stdev`. Isolated to this one real file/column; 12 claims in this run.
2. **A live multi-source-conflict masking issue in `robotics.py`** (new,
   not a recurrence of the already-documented `kind`-field issue): roughly
   1-in-10 live propose() calls for a single corpus doc return no evidence
   even though the fact is genuinely present; when that lands on just one
   of two genuinely-conflicting sources, the engine never sees the
   conflict and confidently resolves off the remaining one-sided evidence.
   5 claims in this run, all in the real 100-300m BlueROV2 conflict zone.

Both documented with exact claim IDs, exact repro steps, and exact
root-cause tracing — neither fixed inline, per this task's instruction.

## What this run does NOT show

`research_web`'s conservative misses and sample size (24 claims) mean its
numbers here are a much thinner sample than the other three domains —
real, but don't read "70.8% correct" as a precise reliability figure the
way ml_data's "99.5%" (2,492/2,504 correct+crash-free) can be read, given
the two-order-of-magnitude difference in sample size.

## Update (2026-10-18): both bugs above are now fixed in production

Both real bugs this run found have since been fixed directly in
`anticassiopeia/` (explicitly authorized as an exception to this harness's
own read-only rule). Full fix detail, including a second, more severe
root cause for bug 2 that a deeper live investigation surfaced after the
first fix alone didn't hold up, is in `stress_test/BUGS_FOUND.md` — this
report is left exactly as it was written at the time of the run, as an
honest record of what that run actually found, not edited to look
cleaner after the fact.

The 17 specific claim IDs these two bugs were isolated to (12 ml_data,
5 robotics — not the full 3,311-claim batch) were re-run against the
fixed code and all 17 now resolve to their ground-truth verdict. The
production test suite (`pytest tests/`, 111 tests) and `evals/run_evals.py`
(27 cases) both stay green after the fixes, with new tests added
specifically covering both bugs — see `BUGS_FOUND.md` for exactly which.
