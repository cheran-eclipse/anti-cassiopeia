# Stress Test #2: bare Nebius vs. the Anti-Cassiopeia pipeline

**Date:** 2026-10-18
**Sample:** a stratified **1,000-claim subset** of Test #1's existing
3,311-claim manifest (`stress_test/claims/manifest.jsonl`) — selected by
`stress_test/generate_test2_sample.py` (largest-remainder proportional
sampling, seeded, reproducible) to mirror the full manifest's per-domain,
per-tier composition within ~0.1 percentage points. The claim IDs are
recorded in `stress_test/claims/test2_sample.jsonl` (a pointer file —
claim ID + domain + tier only, not a copy of the claim payload or ground
truth, both of which are re-read from the original manifest). **This is
1,000 of 3,311 claims, not the full set** — same honesty rule as Test
#1's report: don't read any number below as more precise than a
~30%-of-manifest sample supports, especially for `research_web`, which
contributes only 7 claims to this sample (see the per-domain section
below).

Nothing in `anticassiopeia/` was touched to run this test. The pipeline
side (`stress_test/run_test1.py`'s `run_batch`, reused unmodified in
logic — only parameterized to accept shared output paths/tracker/budget,
see below) calls the real, already-fixed production code exactly as
Test #1 did. The bare-Nebius side is new code
(`stress_test/run_test2_bare.py`) that never imports anything from
`anticassiopeia/` at all.

## Method

For each of the 1,000 sampled claims, two independent answers were
produced for the exact same claim text and compared against the exact
same ground truth:

- **Bare Nebius**: one chat completion to `openai/gpt-oss-120b` (the
  same model and the same `InstrumentedNebiusClient` this repo's own
  test harness already uses — itself mirroring the real production
  `anticassiopeia/llm/nebius_client.py`), with the claim phrased as
  `"Is the following true: <claim text>? Answer confirmed, contradicted,
  or undetermined, and explain why in one sentence."` No retrieval, no
  file access, no tools. For `ml_data`/`fpga_embedded` claims, the real
  dataset/report file is never read or pasted into the prompt — the
  claim text alone (e.g. `"mean(CO(GT)) in air_quality.csv is
  -34.2075"`) is everything the model gets, so it genuinely cannot see
  the file it's being asked about.
- **Pipeline**: the real `VerificationEngine` + the real domain
  adapters, run exactly as Test #1 ran them (retrieve → propose → verify
  for `robotics`/`research_web`; direct computation against the real
  file for `ml_data`/`fpga_embedded`).

Both paths' verdicts were classified against ground truth into the same
four categories, using the same `classify()` function Test #1 already
used (`stress_test/run_test1.py`): **CORRECT** (verdict matches truth),
**DANGEROUS** (confidently wrong — confirmed/contradicted swapped, or a
confident verdict where truth is genuinely undetermined), **CONSERVATIVE**
(undetermined when a confident correct answer was achievable). Bare
Nebius additionally gets a **FABRICATED-DETAIL** flag for
`ml_data`/`fpga_embedded` claims specifically — see its own section
below.

Both paths shared **one** running cost tracker and a single **$4.00**
budget cap for this whole test (separate from, and on top of, Test #1's
own already-spent $6.00 cap) — a call on either path checked the same
running total, so neither path could overspend invisibly to the other.
A 20-claim stratified pilot ran first through both paths; its real
measured cost ($0.010493 combined) was extrapolated to the full 1,000
claims (~$0.52 projected, 13.1% of cap) and reported before the user's
explicit go-ahead to run the full sample.

## Actual spend

| | Bare Nebius | Pipeline | Combined |
|---|---|---|---|
| Pilot (20 claims, both paths run) | — | — | $0.010493 |
| Full run (1,000 claims) | $0.117912 | $0.054952 | $0.172864 |
| **Total actual cash spent, this test** | | | **$0.183357** |

**4.6% of the $4.00 cap used; the hard stop was never approached.** (The
pilot's 20 claims are a subset of the full 1,000 and were genuinely run
twice — once as the pilot, once again inside the full run — so the
$0.0105 pilot cost is real spend on top of the full run's own total, not
double-counted in any of the per-domain/accuracy numbers below, which
are all computed from the 1,000 *unique* claim IDs, keeping each
claim's later [full-run] result when a duplicate exists.)

Per-domain cost for the full 1,000-claim run, bare + pipeline combined
(this is a shared tracker, so the two paths' spend isn't separable
per domain from the console output alone — the numbers below are
summed from the per-claim `cost_usd` field in both raw result files,
which IS separable):

| Domain | Bare cost | Pipeline cost |
|---|---|---|
| `fpga_embedded` | $0.012128 | $0.000000 (free — local computation, no LLM call) |
| `ml_data` | $0.082690 | $0.000000 (free — local computation, no LLM call) |
| `research_web` | $0.000841 | $0.008094 |
| `robotics` | $0.022253 | $0.046858 |

(`ml_data`'s bare cost dominates purely because it's 75.6% of the
sample by count, not because it's expensive per call — robotics costs
more than 2x as much per call on the pipeline side specifically because
each robotics claim triggers a real retrieve→propose→verify round trip.)

## Per-domain, per-tier comparison

Accuracy / dangerous-rate / conservative-rate, bare Nebius vs. pipeline,
for every (domain, tier) stratum in the sample:

| Domain | Tier | n | Bare correct | Bare dangerous | Bare conservative | Pipeline correct | Pipeline dangerous | Pipeline conservative |
|---|---|---|---|---|---|---|---|---|
| fpga_embedded | 1 | 51 | 0.0% | 0.0% | 100.0% | 100.0% | 0.0% | 0.0% |
| fpga_embedded | 2 | 14 | 0.0% | 0.0% | 100.0% | 100.0% | 0.0% | 0.0% |
| fpga_embedded | 3 | 51 | 3.9% | 0.0% | 96.1% | 100.0% | 0.0% | 0.0% |
| ml_data | 1 | 453 | 16.1% | 2.9% | 81.0% | 100.0% | 0.0% | 0.0% |
| ml_data | 2 | 212 | 12.7% | 0.9% | 86.3% | 100.0% | 0.0% | 0.0% |
| ml_data | 3 | 91 | 2.2% | 1.1% | 96.7% | 100.0% | 0.0% | 0.0% |
| research_web | 1 | 3 | 100.0% | 0.0% | 0.0% | 66.7% | 0.0% | 33.3% |
| research_web | 2 | 2 | 100.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| research_web | 3 | 2 | 0.0% | 100.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| robotics | 1 | 46 | 84.8% | 0.0% | 15.2% | 100.0% | 0.0% | 0.0% |
| robotics | 2 | 45 | 42.2% | 6.7% | 51.1% | 100.0% | 0.0% | 0.0% |
| **robotics** | **3** | **30** | **33.3%** | **66.7%** | **0.0%** | **100.0%** | **0.0%** | **0.0%** |

**Per-domain overall (n = all tiers combined):**

| Domain | n | Bare correct | Bare dangerous | Bare conservative | Pipeline correct | Pipeline dangerous | Pipeline conservative |
|---|---|---|---|---|---|---|---|
| fpga_embedded | 116 | 1.7% | 0.0% | 98.3% | 100.0% | 0.0% | 0.0% |
| ml_data | 756 | 13.5% | 2.1% | 84.4% | 100.0% | 0.0% | 0.0% |
| research_web | 7 | 71.4% | 28.6% | 0.0% | 85.7% | 0.0% | 14.3% |
| robotics | 121 | 56.2% | 19.0% | 24.8% | 100.0% | 0.0% | 0.0% |
| **Overall (n=1,000)** | 1,000 | **17.7%** | **4.1%** | **78.2%** | **99.9%** | **0.0%** | **0.1%** |

**Phase B addendum (2026-10-19, external review):** the pipeline's
single "99.9%" above blends computed-not-verified claims with real
evidence-weighing ones. Read as two numbers:

| | n | Bare correct | Bare dangerous | Pipeline correct | Pipeline dangerous |
|---|---|---|---|---|---|
| **Deterministic** (ml_data+fpga_embedded) | 872 | 11.9% | 1.83% | **100.0%** | **0.0%** |
| **Verification** (robotics+research_web) | 128 | 57.0% | 19.53% | **99.2%** | **0.0%** |

The pipeline's one miss anywhere in this sample is in the verification
domains (a conservative one, not dangerous — see the single `research_web`
tier-1 cell above); the deterministic domains are not just "mostly
right," they are exactly, provably right every time, because they are
computed, not verified.

The single most striking line is **robotics tier 3: bare Nebius is
confidently wrong 66.7% of the time** — not uncertain, not declining,
*confidently wrong on two-thirds of the hardest-tier claims*. Two real
examples from the raw responses (`stress_test/results/test2_bare_raw.jsonl`):

> `robotics-002928` ("BlueROV2 survives 105 m depth"): bare Nebius —
> *"Contradicted – Blue Robotics lists the BlueROV2's maximum operating
> depth as 100 m (≈330 ft), so 105 m exceeds its rated limit."*
> Ground truth: **undetermined** (the real corpus has genuinely
> conflicting ratings — 100 m for the acrylic housing, 300 m for the
> aluminum — so without knowing which housing, 105 m is neither clearly
> safe nor clearly unsafe). The pipeline gets this right precisely
> because it's the fix from the previous task: it surfaces both
> conflicting sources instead of picking one.
>
> `robotics-002942` (140 m): bare Nebius — *"Contradicted – the
> BlueROV2 is specified for roughly 100 m... so 140 m exceeds its
> specified operating limit."* Same ground truth, same failure, same
> single-number recollection with no notion that a conflict exists.

Bare Nebius has clearly memorized *a* BlueROV2 depth rating (100 m, the
acrylic figure) from training data and applies it uniformly, with no
awareness that the real source material disagrees with itself — which
is exactly the failure mode the retrieve→verify pipeline exists to
catch.

The one pipeline miss worth naming honestly: `research_web-003300`
(tier 1, ground truth confirmed) came back **undetermined** from the
pipeline — a genuine conservative miss, not a bug (consistent with Test
#1's own classification; nothing this conservative gets logged in
`BUGS_FOUND.md`, which is reserved for dangerous/crash findings). With
`research_web` at only 7 claims in this sample, one miss is 14.3% of
that domain's result — read this domain's row as a thin, suggestive
signal, not a settled rate.

## Latency — "the cost of honesty"

| Domain | Bare avg latency | Pipeline avg latency | Multiplier |
|---|---|---|---|
| fpga_embedded | 1.03s | 0.00s | **pipeline is faster** (no LLM call at all) |
| ml_data | 1.07s | 0.08s | **pipeline is ~13x faster** (no LLM call at all) |
| robotics | 1.40s | 1.88s | pipeline is **1.3x slower** |
| research_web | 1.02s | 6.84s | pipeline is **6.7x slower** |
| **Overall (n=1,000)** | 1.11s | 0.34s | pipeline is 0.3x — *misleading in aggregate* |

The overall multiplier is **misleading on its own**: `ml_data` and
`fpga_embedded` make up 87.2% of this sample and are free, instant local
computation on the pipeline side (no network call at all), which drags
the aggregate average down and makes the pipeline look faster overall.
The real "cost of honesty" only applies to the two domains where the
pipeline actually does retrieval:

- **robotics: pipeline is 1.3x slower (1.40s → 1.88s) for 100% fewer
  dangerous errors (19.0% → 0.0%)** — a ~34% latency cost buys a
  complete elimination of confident wrong answers.
- **research_web: pipeline is 6.7x slower (1.02s → 6.84s) for 100%
  fewer dangerous errors (28.6% → 0.0%)**, at the cost of a somewhat
  higher conservative rate (0% → 14.3%, on a 7-claim sample — see the
  caveat above). Multi-source retrieve→verify genuinely costs an order
  of magnitude more wall-clock time per claim than one bare completion.

For `ml_data`/`fpga_embedded`, there is no tradeoff to state at all —
the pipeline is simultaneously faster AND the only path capable of
being correct, since those claims require reading an actual file bare
Nebius never sees.

## Fabricated-detail: the single most demonstrative finding

This is the comparison most worth reading closely. `ml_data` and
`fpga_embedded` claims (872 of the 1,000 sampled claims) ask about a
real file bare Nebius was never shown. A model with no access to that
file has exactly two honest options: decline, or confirm/contradict
based on actual knowledge of that specific file (which it cannot have).
A third, dishonest-looking option is to state a specific number with no
acknowledgement that it has no way to have seen the real data — flagged
here as **FABRICATED-DETAIL**, based purely on whether the response
shows any awareness of lacking file access (checked by matching phrases
like *"I don't have access to..."*, *"without seeing the actual
data..."*), not on whether the final verdict happens to be right.

**Result: 118 of 872 file-dependent claims (13.5%) were FABRICATED-DETAIL**
— a confident confirmed/contradicted verdict given with zero acknowledgement
that the model never saw the file. All 118 were `ml_data` claims (0 of
116 `fpga_embedded` claims showed this pattern — for the fpga domain,
bare Nebius either declined or hedged every single time it answered
confidently... which in this sample was essentially never: only 1.7%
`fpga_embedded` accuracy and a 0% fabrication rate because it almost
always just said "undetermined").

Of those 118 fabricated-detail cases: **102 happened to land on the
numerically correct verdict (by luck/pattern-matching), and 16 were
confidently, dangerously wrong.** Getting lucky 86% of the time on a
fabricated number is not the same as being grounded — and the raw
responses show exactly why luck, not grounding, is the right word for
it. Two real examples from the same dataset, `air_quality.csv`, whose
real UCI-standard `-200` missing-value placeholder bare Nebius has
clearly memorized from training data in a generic, file-independent way:

> `ml_data-000133` ("min(PT08.S5(O3)) in air_quality.csv is -200"):
> bare Nebius — *"Confirmed – the smallest value recorded for
> PT08.S5(O3) in the air_quality.csv file is –200, which is the
> placeholder used in this dataset to denote missing measurements."*
> **Correct** — but for the wrong reason: it's recalling that UCI's Air
> Quality dataset uses -200 as a missing-value sentinel in general
> (true, and a reasonably well-known fact about this specific public
> dataset), not that it computed `min()` over the actual file's
> `PT08.S5(O3)` column.
>
> `ml_data-000091` ("min(PT08.S3(NOx)) in air_quality.csv is -200," a
> *different* column, same file): bare Nebius — *"Contradicted – in the
> UCI Air Quality dataset the PT08.S3(NOx) sensor values are
> non-negative, with a minimum near zero (certainly not –200)."*
> **Wrong** — the real file uses -200 as its missing-value placeholder
> for *every* sensor column, including this one; "certainly not -200"
> is confidently, specifically false. The same model, the same file,
> the same -200 convention — right when its generic prior happened to
> match, wrong when it didn't, with identical confidence either way.

The pipeline is correct on both of these (and all 756 `ml_data` claims
in this sample) for the uninteresting, correct reason: it opens the
actual file and computes the actual statistic.

## What this test does NOT show

- **research_web (n=7)** is far too small a sample in this subset to
  read any of its percentages as a precise rate — it is included for
  completeness and because its numbers are directionally consistent
  with the other domains (bare confidently wrong once out of seven;
  pipeline conservative once out of seven), not because 7 claims
  settles anything on their own. The full manifest only has 24
  research_web claims across all 3,311, so no fixed-size subset of it
  will ever be a large sample.
- This is 1,000 of 3,311 manifest claims (~30%), stratified to match the
  full manifest's composition — not the full set, and not an
  independent new corpus. Numbers here describe this sample, not a
  universal rate; the direction and scale of the gap (bare 17.7%
  correct / 4.1% confidently wrong vs. pipeline 99.9% correct / 0.0%
  confidently wrong, overall) is large enough that it is very unlikely
  to reverse on the full 3,311, but the exact percentages would move.
- Nothing here is a production bug. The bare-Nebius path never imports
  or calls anything in `anticassiopeia/` — its failures describe what a
  single ungrounded LLM call does with these claims, not a defect in
  this project's own code. The pipeline's one miss
  (`research_web-003300`) is a conservative "didn't know," not a wrong
  answer, and is not logged as a bug for the same reason Test #1 never
  logged conservative misses as bugs.
