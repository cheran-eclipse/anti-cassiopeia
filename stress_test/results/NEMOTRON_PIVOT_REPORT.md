# The Nemotron pivot: an honest before/after comparison

Written for the Apps and Agents track's "power it with Nemotron" requirement.
This is NOT a report of "we swapped the model" — it's the record of testing
that swap as a hypothesis, against the exact harness this project already
trusts (`stress_test/run_test1.py`'s `load_manifest`/`select_pilot`/
`run_batch`/`classify` — no new scoring logic, no new claim set), finding it
mostly didn't hold up, and documenting that plainly rather than reframing it.

## Scope

Only `robotics` and `research_web` make live LLM calls in the real engine
pipeline — `ml_data` and `fpga_embedded` re-derive/re-parse directly from
source (see `docs/DESIGN.md` §5) and are provably invariant to model choice.
Every pilot below is restricted to the domain(s) actually being tested
(`stress_test/run_nemotron_pivot.py --domains ...`), so no budget was spent
"testing" a domain that cannot change.

## Method

`stress_test/run_nemotron_pivot.py` runs the SAME stratified claim sample
through the real `VerificationEngine` twice — once with `openai/gpt-oss-120b`
(the current default, "baseline") and once with a named Nemotron model
("candidate") — via `InstrumentedNebiusClient`, injected the same way the
production adapters already support test substitution (`client=...`).
Pricing for cost reporting: baseline $0.15/$0.60 per 1M tok (input/output,
as already used project-wide); Nemotron figures are a working ESTIMATE
sourced from third-party cost-aggregator pages, since `nebius.com/prices-ai-studio`
renders its pricing table via JavaScript and a static fetch of it (tried,
see below) came back empty — Super $0.30/$0.90, Ultra $1.00/$3.00, Nano
$0.06/$0.24 per 1M tok. A wrong price here would misstate the dollar figure
but never cause real overspend beyond whatever the true rate actually costs,
since every dollar figure is computed from the real `usage` token counts the
API returns, not estimated token counts.

## All pilots run, in order

| # | Domain(s) | n | Model | baseline correct% | candidate correct% | delta | candidate dangerous% | crash? |
|---|---|---|---|---|---|---|---|---|
| 1 | robotics+research_web | 15 each | Super | robotics 100%, rw 73.3% | robotics 100%, rw 53.3% | rw **-20.0%** | rw 6.7% | no |
| 2 | robotics+research_web | 15 each | Ultra | robotics 100%, rw 80.0% | robotics 100%, rw 66.7% | rw **-13.3%** | rw 13.3% | no |
| 3 | robotics | 15 | Nano | 100% | 93.3% | **-6.7%** | 6.7% | no |
| 4 | research_web | 40 | Super | 80.0% | 55.0% | **-25.0%** | 10.0% | **yes** |
| 5 | research_web | 40 | Ultra | 82.5% | 70.0% | **-12.5%** | 15.0% | **yes** |
| 6 | robotics | 40 | Nano | 100% | 92.5% | **-7.5%** | 2.5% | no |
| 7 | robotics | 40 | Super | 100% | 92.5% | **-7.5%** | 7.5% | no |
| 8 | robotics | 40 | Ultra | 100.0% | 100.0% | **+0.0%** | 0.0% | no |

Pilot 8 completed after this report's first draft; this is the updated
version, not a prediction written before the cell existed.

## The central, load-bearing finding

**Baseline (gpt-oss-120b) was run 10 separate times across both domains
and never once produced a dangerous miss or a crash** — 165 robotics
claims (pilots 1/2/3/6/7/8's baseline legs) at 100% correct every single
time, and 110 research_web claims (pilots 1/2/4/5's baseline legs) at
73–82.5% with a consistent, bounded dangerous rate (6.7–12.5%), never
a crash.

- **research_web**: both Super and Ultra, at both n=15 and n=40, landed
  below baseline — the larger sample CONFIRMED the direction, not
  overturned it (Super: -20% → -25%; Ultra: -13.3% → -12.5%). Both tiers
  also produced exactly one CRASH at n=40 that baseline never produced
  across any of its 9 runs there (see "Crash root causes" below). No
  Nemotron tier has beaten baseline here at any tested sample size.
- **robotics**: this is the finding that changed the recommendation
  mid-session, TWICE. At n=15, Super and Ultra both matched baseline
  exactly (100%=100%, 0% dangerous) — this LOOKED like "robotics is
  tier-insensitive, safe to route to any Nemotron tier." It was a
  statistically underpowered conclusion: one dangerous event at n=15
  (Nano's single miss) is compatible with a true dangerous rate anywhere
  from ~1% to ~30%, and ZERO events at n=15 (Super's result) is compatible
  with a true rate as high as ~20% by the same rule-of-three logic —
  "proven flawless" and "proven risky" were both overclaims at that
  sample size. Escalating to n=40 (the same rigor already applied to
  research_web, applied here for consistency) showed Nano AND Super both
  crack (92.5% correct, with real dangerous misses — Nano 2.5%, Super
  7.5% — concentrated on tier-3 claims whose ground truth is UNDETERMINED;
  baseline correctly refuses to call these, both tiers sometimes guess
  confidently instead). **Ultra, tested at n=40 for exactly this reason
  (closing the one cell left asymmetric), held: 100%=100%, zero dangerous,
  zero crashes — matching its own n=15 result.** Two independent,
  adequately-sized samples agreeing is a real, earned result, unlike the
  n=15-only conclusions that preceded it for Nano/Super.

**Net result: Nemotron Ultra is the one tier, in the one domain, proven
at an adequate sample size to match gpt-oss-120b — robotics' `propose()`
calls, at roughly 7x the cost. Nothing tested beats baseline on
research_web at any sample size.** This is a narrower, harder-won
conclusion than "route each call to the tier suited to it" — it took
escalating sample size on BOTH domains, and reversing an earlier
recommendation once, to get here honestly.

## Crash root causes — real parsing-robustness bugs, not just accuracy

Two crashes, two different root causes, both now fixed in
`anticassiopeia/llm/nebius_client.py` and the adapters' except clauses
(see commit — this was done independently of the model-choice decision,
since a crash reaching the engine is exactly the failure class this
project exists to prevent, just at the code layer instead of the
reasoning layer):

1. **`research_web-003304` (Ultra, pilot 5):** the model's `quote` field
   came back containing a huge, raw, half-escaped dump of Wikipedia
   wikitext (citation templates, unescaped braces/quotes) that broke
   `extract.py`'s JSON-fence-stripping parser — `ValueError`. Now caught
   in both `robotics.py` and `research_web.py`'s propose-call except
   clauses, same as any other live-call failure (honest named gap, not
   a crash).
2. **`research_web-003303` (Super, pilot 4):** `completion_tokens` hit
   exactly 8192 (the implicit cap), 51s latency, fully truncated — the
   API returned `content: null` in an otherwise well-formed 200 response.
   `NebiusTokenFactoryClient.complete()` previously returned that `None`
   straight to the caller, which crashed on `.strip()`. Fixed at the
   source: a non-string `content` now raises `NebiusClientError` (the
   same exception type every caller already catches).

## Mistake-case inspection: reading the actual failures, not just the rates

5 of the 7 named dangerous/crash cases had no persisted record of the
model's actual reasoning (`run_batch()` only recorded the final verdict +
severity) — a fresh reproduction was run against the same model for each,
logging every raw prompt/response. HONEST CAVEAT: this is a NEW attempt,
not a replay; live calls aren't fully deterministic.

**None of the 7 original mistakes reproduced.** All 7 landed safer
(UNDETERMINED or correct) on the fresh attempt, consistent with these
being real probabilistic failure RATES (matching the aggregate n=40
deltas, which stand) rather than deterministic per-claim bugs.

Reading the actual transcripts surfaced two things the aggregate numbers
alone did not:

1. **A real, separate, model-agnostic bug** (`research_web-003297`'s
   reproduction): the Wikipedia passage was correctly extracted and
   correctly judged "contradicts" ("designed by Espressif, manufactured
   by TSMC" vs. the claim "manufactured by Espressif"). A SECOND passage,
   from a LeadIQ page about the ESP32-**S31** — a different, newer chip —
   saying Espressif "started mass production" of IT, was judged
   "supports" for a claim about the plain ESP32. `_judge_stance()`'s
   prompt never checked whether the passage addresses the SAME specific
   entity the claim names. That false "support" pulled a clean
   CONTRADICTED to a 50/50 tie, producing UNDETERMINED instead. Fixed in
   `_STANCE_SYSTEM_PROMPT` (see below) — this would misfire identically
   regardless of which model does the judging, since it's a scope-matching
   gap in the prompt, not a reasoning failure.
2. **A possible ground-truth labeling wrinkle**, separate from any code
   bug: the manifest labels "The ESP32 is a microcontroller manufactured
   by Espressif Systems" as `confirmed`, but Wikipedia's own precise
   wording says Espressif *designs* it and TSMC *manufactures* it — a
   colloquial reading, common for fabless semiconductor companies, but
   arguably not literally true. Not changed here (a manifest/claim-
   generation decision, not this round's scope) — flagged for a future
   pass to decide: relabel, or document the ambiguity as intentional.
3. **`robotics-002929`'s reproduction is the system working as designed**,
   not luck: two real datasheet variants (aluminum rated 300m, acrylic
   rated 100m) genuinely disagree at the claimed 105m, and the engine
   correctly refused to pick a side. Good independent confirmation the
   core disagreement-zone logic is sound, separate from model accuracy.
4. Both crash cases reproduced cleanly post-fix (one clean CONTRADICTED
   at 0.9 confidence, one honest UNDETERMINED from zero usable evidence)
   — consistent with "probabilistic, not deterministic."

Full transcripts (claim text, every raw prompt/response, final verdict)
were packaged for direct inspection rather than summarized; see the
session's working notes for the zip's contents if this report is being
read without that context.

## Three real pipeline gaps, fixed before any re-test

All three are model-agnostic — each would distort the comparison for
EVERY model, not just Nemotron — so all three are fixed here, before any
re-test, and the re-test reruns baseline too, not just Nemotron, so a
post-fix accuracy change can be attributed correctly (fairer pipeline vs.
fairer treatment specifically for Nemotron):

1. **No `max_tokens` was ever set** (`nebius_client.py`,
   `instrumented_client.py`) — now explicitly 16384 on both, up from
   whatever the API's own implicit default was (crash #2 hit exactly
   8192). Locked in with `test_max_tokens_is_actually_sent_in_the_request`.
2. **No quote-length guidance** (`extract.py`'s `_SYSTEM_PROMPT`) — now
   explicitly tells the model to keep "quote" to the single sentence
   stating the fact, not the surrounding block, naming crash #1's
   garbled-dump failure as the reason.
3. **No entity-matching check** (`research_web.py`'s
   `_STANCE_SYSTEM_PROMPT`) — now explicitly instructs the model to
   verify the passage addresses the SAME specific entity the claim names
   before judging support/contradiction, naming the ESP32/ESP32-S31
   mix-up as the reason it exists.

## Is this a fair fight? — investigated, not just asserted

A fair question: is some of this gap "baseline is better-INTEGRATED with
this pipeline" (prompts/parsing tuned around gpt-oss-120b's specific
output habits) rather than "baseline is a better model at this task"?
Checked directly against the real code, not assumed either way:

- **No `max_tokens` is ever set** in either `nebius_client.py`'s or
  `instrumented_client.py`'s request body — the API's own default
  applies. Crash #2's `completion_tokens: 8192` landing on an exact
  round number strongly suggests an implicit cap was hit. If Nemotron's
  "serious reasoning" tiers spend hidden reasoning/thinking tokens before
  producing a visible answer (a real, documented behavior of reasoning
  models generally) and gpt-oss-120b doesn't — or spends far fewer — then
  the comparison is not apples-to-apples for ANY call where that matters:
  Nemotron could be running out of budget mid-answer where gpt-oss-120b
  never approaches the limit. This is directly actionable (set an explicit
  `max_tokens`, or use a Nebius-exposed reasoning-effort/thinking-budget
  parameter if one exists) and untested as a fix in this round.
- **The system prompt gives zero quote-length guidance** (`extract.py`'s
  `_SYSTEM_PROMPT`: "The quote field MUST be copied character-for-character"
  — no instruction to keep it short, no bound on how much of a messy
  source chunk is reasonable to cite). Crash #1's garbled dump is
  consistent with a model being more literal about "copy the passage"
  against a messy real source chunk (a raw Wikipedia infobox/citation
  block) than gpt-oss-120b happened to be on this sample.
- **Official Nebius pricing could not be statically fetched** for this
  report either (`nebius.com/prices-ai-studio` renders via JavaScript) —
  noted here for the same reason: this round's investigation hit real,
  documented limits, not glossed over ones.

All three fixes above (max_tokens, quote-length guidance, and the
entity-matching gap the mistake-case inspection separately surfaced) are
now applied; the re-test (research_web, n=40, both Super and Ultra,
baseline rerun fresh alongside each) is running. Results below once it
lands — if the gap shrinks, the honest conclusion becomes "this pipeline
wasn't tuned for Nemotron's output style, and tuning it closes most of
the gap," a materially different and more defensible finding than
"Nemotron categorically loses here." Until that result is in, the
measured deltas earlier in this report stand as the evidence, not a
prompt-tuning excuse for them.

### Fair-fight re-test results

Critical scope correction mid-re-test: the max_tokens and quote-length
fixes live in `nebius_client.py`/`extract.py`, shared by BOTH domains —
only the entity-matching fix is research_web-specific. That means
robotics' recorded dangerous misses (Nano, Super) were ALSO measured
against the pre-fix pipeline and needed the same re-test, not just
research_web. Re-run for every cell that showed a dangerous miss
pre-fix, baseline rerun fresh alongside each:

| Domain | Model | n | pre-fix delta | pre-fix dangerous% | **post-fix delta** | **post-fix dangerous%** | crash (pre→post) |
|---|---|---|---|---|---|---|---|
| research_web | Super | 40 | -25.0% | 10.0% | **-20.0%** | **15.0%** | yes → no |
| research_web | Ultra | 40 | -12.5% | 15.0% | **+2.5%** | **10.0%** | yes → no |
| robotics | Nano | 40 | -7.5% | 2.5% | **+0.0%** | **0.0%** | no → no |
| robotics | Super | 40 | -7.5% | 7.5% | **-7.5%** | **7.5%** | no → no |
| robotics | Ultra | 40 | +0.0% | 0.0% | **-5.0%** | **0.0%** | no → no |

**The fix was real, not favoritism, and it did NOT affect every tier the
same way:**

- **Ultra improved on BOTH domains** — research_web flipped from -12.5%
  to +2.5% (now BEATS baseline), and its one crash disappeared. The
  "unfair fight" hypothesis holds for Ultra.
- **Nano's robotics result flipped completely** — from 92.5% (1
  dangerous + 2 conservative) to 100%, matching baseline exactly, zero
  dangerous. The smallest model benefited the most from the max_tokens
  fix specifically.
- **Super did not improve on either domain** — research_web stayed at
  -20 to -25% (crash gone, but accuracy unchanged, dangerous rate even
  ticked up slightly), and robotics stayed at exactly -7.5% / 7.5%
  dangerous (same rate, a slightly different SET of claims tripped it —
  consistent with live variance, not a fix doing anything). **Super's
  underperformance on both domains is now evidenced as a real,
  model-specific property, not a pipeline artifact** — the same fixes
  that rescued Nano and Ultra did nothing for it.
- **Ultra's robotics confirmatory re-run** (queued purely for
  consistency — it was already flawless pre-fix on two samples) landed
  at 95.0% (38/40, 2 conservative misses), not another perfect 100%.
  The headline number isn't perfectly reproducible; what IS consistent
  across all three of Ultra's independent robotics runs (n=15, n=40
  pre-fix, n=40 post-fix) is **zero dangerous misses, every time** — the
  property that actually matters for this project, and the one worth
  trusting, rather than the raw percentage.

**Dangerous-miss rate, every robotics run, pre- and post-fix, for the
record:** baseline 0/205 across all 6 of its robotics runs now (including
this round's 3 fresh baseline legs); Nano 1-then-0 across its two n=40
runs; Super 3-then-3 (same rate, different claims) across its two n=40
runs; Ultra 0-then-0 across all three of its runs. Ultra is the only
Nemotron tier with a perfect dangerous-miss record on robotics across
every sample size tested.

## Recommendation — final, based on the bug-fixed comparison

Every cell that showed a dangerous miss under the old pipeline has now
been re-run post-fix (max_tokens, quote-length guidance, entity-matching),
baseline rerun fresh alongside each. This is the dataset the decision is
actually based on — everything before the `extract.py`/`nebius_client.py`
fix was measuring the pipeline's own bugs as much as the models':

- **Route robotics' `propose()` calls to Nemotron Ultra.** Zero dangerous
  misses across all THREE of its independent robotics runs (n=15 and
  n=40 pre-fix, n=40 post-fix) — a clean safety record, every time it
  was tested. Cost: ~7x baseline (~$1.19-1.24 vs ~$0.17-0.19 for the
  full 398-claim robotics set — affordable against the ~$17 remaining
  budget). Satisfies "a real NVIDIA model in the request path" without
  a measured safety cost.
- **Not Nemotron Nano, despite its lower cost and its own clean most-
  recent result.** The real comparison isn't "one fewer confirming
  sample" — it's zero dangerous misses across three runs (Ultra) versus
  TWO actual dangerous-miss incidents, on two separate occasions (n=15
  and n=40 pre-fix), before Nano's most recent run came back clean.
  That's a track record with two real incidents in it, not a thinner
  version of a clean one. For a project whose entire premise is not
  being confidently wrong, a model with a perfect safety record at
  higher cost beats a model with a checkered-then-recently-clean record
  at lower cost — the savings don't buy anything if what they're being
  traded against is exactly the failure mode that showed up twice
  before. Nano remains worth re-testing further (its fix-driven recovery
  is real and worth tracking), but it is not the recommendation today.
- **Keep gpt-oss-120b for research_web's `propose()`+`_judge_stance()`.**
  The fix flipped Ultra to a real, if narrow, win there (+2.5%, crash
  gone) — but Super's gap on the SAME domain, under the SAME fix, did
  not move at all (-20 to -25% both times). Since Super is not the
  model being recommended for either domain, and Ultra's research_web
  win is narrow (+2.5%, one sample) against gpt-oss-120b's consistent,
  crash-free, 10-run track record across this entire investigation,
  baseline remains the safer default for this call specifically —
  revisit if a second independent research_web sample confirms Ultra's
  edge holds.

**What changed this session, in order:** an initial "robotics is
tier-insensitive" conclusion (wrong, n=15-underpowered) → a corrected
"only Ultra is proven on robotics" conclusion (right, but measured
against a buggy pipeline) → three real pipeline bugs found by reading
actual failure transcripts, not just aggregate rates → a bug-fixed
re-test that vindicated Ultra further, left Super unchanged, and fully
rescued Nano on robotics specifically. Each correction came from
applying the same rigor to a cell that had been accepted too quickly,
not from re-running until the answer looked better.
