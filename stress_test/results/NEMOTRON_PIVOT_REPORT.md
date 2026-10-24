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
| 8 | robotics | 40 | Ultra | *(pending — see note)* | | | | |

Pilot 8 (the one cell needed for full symmetry — every other cell was
tested at n=40) was launched after pilot 7 and is not included in the
table above yet; this report will be updated once it completes, rather
than this file being written before that cell existed, per this
project's own "don't claim more finished than is true" rule.

## The central, load-bearing finding

**Baseline (gpt-oss-120b) was run 9 separate times across both domains
and never once produced a dangerous miss or a crash** — 125 robotics
claims (pilots 1/2/3/6/7's baseline legs) at 100% correct every single
time, and 110 research_web claims (pilots 1/2/4/5's baseline legs) at
73–82.5% with a consistent, bounded dangerous rate (6.7–12.5%), never
a crash.

Every Nemotron tier tested at an ADEQUATE sample size (n=40) underperformed
baseline on whatever domain it was tested on:

- **research_web**: both Super and Ultra, at both n=15 and n=40, landed
  below baseline — the larger sample CONFIRMED the direction, not
  overturned it (Super: -20% → -25%; Ultra: -13.3% → -12.5%). Both tiers
  also produced exactly one CRASH at n=40 that baseline never produced
  across any of its 9 runs (see "Crash root causes" below).
- **robotics**: this is the finding that changed the recommendation
  mid-session. At n=15, Super and Ultra both matched baseline exactly
  (100%=100%, 0% dangerous) — this LOOKED like "robotics is tier-insensitive,
  safe to route to any Nemotron tier." It was a statistically underpowered
  conclusion: one dangerous event at n=15 (Nano's single miss) is compatible
  with a true dangerous rate anywhere from ~1% to ~30% (and ZERO events at
  n=15, Super's result, is compatible with a true rate as high as ~20% by
  the same rule-of-three logic) — "proven flawless" and "proven risky" were
  both overclaims at that sample size. Escalating to n=40 (same rigor
  already applied to research_web, applied here for consistency) showed
  BOTH Nano and Super crack: 92.5% correct, with real dangerous misses
  (Nano 2.5%, Super 7.5%) concentrated on tier-3 claims whose ground truth
  is UNDETERMINED — baseline correctly refuses to call these; both
  Nemotron tiers sometimes guess confidently instead.

**No domain/tier combination tested at n=40 has yet shown a Nemotron
model matching or beating gpt-oss-120b.** This is a harder result than
"route each call to the right tier" — satisfying "a real NVIDIA model in
the request path" at any tested tier currently means accepting a
measurably higher dangerous-miss rate somewhere in a system whose entire
premise is not making confident false claims.

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

**Not yet done, and the natural next step if there's budget for one more
round:** re-run a small pilot with an explicit `max_tokens` cap and
tighter quote-length guidance in the prompt, specifically against
Nemotron, to see whether the gap shrinks. If it does, the honest
conclusion becomes "this pipeline wasn't tuned for Nemotron's output
style, and tuning it closes most of the gap" — a materially different
and more defensible finding than "Nemotron categorically loses here,"
and this report will be updated to say so if that turns out to be true.
Until that test actually runs, the measured deltas above stand as the
evidence, not a prompt-tuning excuse for them.

## Recommendation, pending the open items above

Not finalized — the Ultra/robotics/n=40 cell and the fair-fight re-test
are both still open. Whatever gets decided, it should be decided off
this full table (all 8 cells, both failure-mode breakdowns, the crash
root causes, and the fairness caveat) — not off the first flattering
cell, which is exactly the mistake this report's own pilot 3→6/7
sequence caught and corrected.
