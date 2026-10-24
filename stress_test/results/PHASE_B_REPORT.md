# Phase B — Evaluation Honesty (external review, 2026-10-19)

Fixes the ground truth itself and the two new, genuinely independent
measurements the review asked for: a code-execution baseline, and a
held-out claim set sharing nothing with the existing 3,383-claim
manifest. Read alongside the addenda added directly to
`TEST1_REPORT.md`/`TEST2_REPORT.md`/`TEST3_REPORT.md` for items 6-8
(deterministic-vs-verification splits, per-domain cost, the Tavily+Gemini
incomplete-coverage caveat) — this file covers items 5, 9, 10, 11.

## Item 5 — the robotics ground truth was circular; fixed

`stress_test/claims/generate_manifest.py`'s `_bluerov2_verdict()` and
`_bar30_verdict()` used to import `core/engine.py`'s own public
`DECISION_THRESHOLD`/`MIN_EVIDENCE_WEIGHT` constants AND the exact same
trust values (0.8/0.7/0.85) `robotics.py`'s own `_SOURCES` dict assigns,
then re-ran the engine's trust-weighted-sum formula on them to decide
"ground truth" — testing whether production code reproduces a copy of
its own scoring algorithm, not an independent check against reality.

**Fixed:** both functions now derive their verdict from the real-world
fact pattern directly, with zero reference to engine.py's constants or
any trust weight:
- BlueROV2: the two real housing variants (aluminum 300m, acrylic 100m)
  either agree on a depth (unambiguous) or genuinely disagree
  (100 < depth <= 300m, real-world undetermined — not an engine
  threshold artifact).
- Bar30: the real ~298.3m rating (physics-converted from 30 bar,
  independently recomputed) and the real, documented 5% gauge/absolute
  pressure margin — the only engine-constant reference in this function
  was dead code (0.85 never actually failed either threshold check) and
  was removed outright.

**Verified, not assumed:** regenerated the full manifest and diffed
every row against the pre-fix version by claim_id. Result: **0 verdict
differences, 0 claim_payload differences, across all 3,311 original
claims** — only the 396 robotics claims' `ground_truth_method`
justification STRINGS changed (2 of robotics' 398 claims are the
unsourced-part gap tests, whose method string was already
circularity-free). This means **every number in Tests #1-3's reports
remains exactly as valid as it was** — the fix was real (the
circularity is gone, and the verdict logic is now independently
justified) but it didn't happen to change any actual verdict on this
particular manifest, because the engine's trust-weighted-sum design, for
exactly two comparably-trusted sources, already collapses to "do the two
real sources agree" — which is what the fixed logic checks directly and
honestly instead of discovering by coincidence.

## Item 9 — research_web expanded 24 → 96 claims (4x)

Added 24 new topics to `_RESEARCH_WEB_FACTS`, each independently fetched
LIVE via Wikipedia's REST summary API (the same confirmed-working
backend `research_web.py`'s own live tests use) on 2026-10-19 *before*
any claim was written — see `stress_test/PROVENANCE.md` for the full
fetch log with per-topic anchor facts. All point at genuinely live,
fetchable `en.wikipedia.org` URLs, same as the original 8 — no
Perplexity/Tavily-style "file never published online" issue applies
here, since research_web claims were never file-based.

The main manifest now has 3,383 claims (research_web: 96, up from 24;
every other domain's claim_ids/verdicts are byte-identical to before).
Test #2/#3's existing 1,000-claim sample predates this expansion and
still only has 7 research_web claims — left as the honest historical
record of what those tests actually ran; the larger research_web
representation is available for Test #4 (Phase F) to sample from.

## Item 10 — the missing baseline: an LLM with a real code-execution tool

**Correction (personal manual review, 2026-10-19):** the harness this
section originally reported on had two real bugs, now fixed, and every
number below is from the corrected rerun — the original numbers are
gone, not kept alongside for comparison, per the review's instruction
not to leave the mischaracterized framing in place.
1. `_MAX_TOOL_ROUNDS` was capped at **4**. Many `fpga_embedded` claims
   genuinely need more back-and-forth (read file → try a parse → check
   the format → retry) than 4 rounds allow, so a real fraction of the
   old "conservative miss" results were the model **running out of
   tool-call budget**, not the model recognizing a limit and declining.
   Those are different findings and were being reported as the second
   one. Fixed: raised to **10** rounds, and every claim's full per-round
   transcript (assistant text, generated code, and tool output) is now
   saved to the raw results file, so which of the two actually happened
   is auditable after the fact instead of asserted.
2. The prompt gave the model the claim text and the file, but never the
   claim's own `tolerance`/`expected_value`/`comparator` fields that the
   real pipeline uses to decide confirmed-vs-contradicted. A model doing
   its own arithmetic with no tolerance information will legitimately
   disagree with a tolerance-aware ground truth on tight-tolerance
   claims — that's a hidden-tolerance artifact of the test harness, not
   a reasoning failure. Fixed: the system/user prompt now states these
   fields explicitly via a new `_context_summary()` helper.

**Second correction (personal manual review, 2026-10-21):** the rerun
that produced the numbers originally reported for items 1-2 above was
ITSELF invalid — it ran against a stale cached sample of the claims,
built before `generate_manifest.py`'s percentile-note and display-
precision fixes were applied, so the model never actually saw either
fix (confirmed directly: zero mentions of "exclusive"/"statistics.quantiles"
anywhere in that run's transcripts for any of its 7 percentile claims).
Numbers below are from a second rerun, built fresh from the live,
verified-current manifest, with three further fixes also applied
(all found and fixed in this same pass — full detail in
`stress_test/BUGS_FOUND.md`'s "SECOND CORRECTION" entry):
3. `fpga_embedded` had its own, never-fixed twin of the ml_data display-
   precision bug (28 claims where boundary-adversarial text rounded back
   to looking identical to the real, confirmed value) — now fixed with
   the same formatter.
4. The verdict parser reused `parse_bare_verdict()` (first canonical
   word), wrong for code-exec's long-form final answers that sometimes
   state a sub-finding before the actual conclusion — a dedicated
   last-word parser (`parse_codeexec_verdict()`) is now used for the
   file-domain claims.
5. A malformed tool-call JSON argument was silently reported as "no file
   exists," wasting rounds on a false premise mid-task — now reported
   as the real parse error it is, inviting a retry.

**Third correction (personal manual review, 2026-10-22):** even on the
second rerun, `fpga_embedded`'s conservative-miss rate was STILL mostly
a budget artifact, not a real finding about parsing difficulty —
verified directly: of the 12 conservative misses at `_MAX_TOOL_ROUNDS=10`,
8 were on just 2 files, and 8 of their 120 tool outputs were truncated at
the then-4,000-char output cap. A diagnostic rerun of exactly those 12
claims at rounds=20 / a 16,000-char cap resolved 11 of 12 to a correct
answer — strong enough to adopt as the real default, not just disclose
as a caveat. `_MAX_TOOL_ROUNDS` raised to **20**, `_MAX_TOOL_OUTPUT_CHARS`
to **16,000**; full main-sample and held-out sets reran a third time at
these settings, numbers below are from that rerun. Two smaller fixes
landed in the same pass: a negation guard on the verdict parser
("cannot be confirmed nor contradicted" no longer misparses as
"contradicted" — now covered by `tests/test_codeexec_parser.py`), and
`finish_reason`/reasoning-field logging on every API response, so an
empty final answer is diagnosable going forward instead of asserted.

**Fourth correction (personal manual review, 2026-10-23):** the negation
guard added in the third correction was itself wrong, and DID occur in
current data, contrary to what this report claimed. It matched a
negation word anywhere in the ~25 characters before a canonical word,
not one actually governing it — four real `ml_data` transcripts
(`ml_data-001854`, `-000529`, `-001217`, `-000537`) phrase their answer
as "...the claim does **not** hold.\n\n**Result: contradicted**.", where
"not" negates "hold", not "contradicted", but still sat inside the old
25-character window and caused the real, correct verdict to be skipped
and the row mis-scored "unparseable" → `other`. Fixed by shrinking the
guard to a 12-character lookbehind and anchoring it to require the
negation word be immediately adjacent to the canonical word (mod
"be"/"been"/markdown `**`), verified against both the original 5
adversarial unit tests and the 4 real transcript strings above, now all
in `tests/test_codeexec_parser.py` (10 tests total). **No new API calls
were made** — the fixed parser was rerun offline over the already-saved
`response_text` in `test3_codeexec_raw.jsonl` and
`heldout_codeexec_raw.jsonl`; exactly these 4 rows changed verdict
(all four from "unparseable" to the correct "contradicted"), nothing
else in either file changed. Numbers below, and the `ml_data`/`other`/
`reasoning` statements elsewhere in this report, are corrected to
reflect this.

**Built:** `stress_test/run_test_codeexec.py` — a genuine multi-turn
tool-use loop against `openai/gpt-oss-120b`'s OpenAI-compatible
function-calling (confirmed live before building the loop: the model
correctly calls a toy `execute_python` tool with real Python for a
trivial arithmetic question). One tool, `execute_python(code)`, up to 20
rounds, each tool output capped at 16,000 characters, full per-round
transcript saved. **Scoped to
`ml_data`/`fpga_embedded` only** — those are the two domains this
baseline actually tests (exact computation vs. a model writing its
own); `robotics`/`research_web` claims have no local file to compute
over, so they fall back to the same plain single-completion prompt
`run_test2_bare.py` already uses (not a new, meaningful baseline for
those two domains — included in the numbers below for completeness,
clearly labeled as the fallback it is).

**Sandboxing, stated honestly:** each `execute_python` call runs in a
separate `python3 -I` subprocess (isolated mode), in a fresh per-claim
scratch directory containing ONLY a copy of the one file the claim
references, with a minimal environment (no `NEBIUS_API_KEY` or any other
secret reachable even if the model's own code tried to dump
`os.environ`), and a 10-second wall-clock timeout. This is **not** a
full container/chroot sandbox — model-generated code could, in
principle, still try absolute-path file I/O outside the scratch
directory. Accepted for this controlled research run (not a
public-facing service), same as this project's other documented-not-
fixed residual gaps (DNS rebinding, redirect-at-connect-time) — stated
plainly, not silently assumed away.

### Result 1 — held-out set (the cleanest comparison, n=42)

| Variant | ml_data (n=11) correct/dangerous | fpga_embedded (n=8) correct/dangerous |
|---|---|---|
| **Pipeline** (exact computation) | **100.0% / 0.0%** | **100.0% / 0.0%** |
| **Code-exec** (model writes its own code) | **100.0% / 0.0%** | **100.0% / 0.0%** |
| Bare Nebius (no tool at all) | 9.1% / 0.0% | 0.0% / 0.0% |

Three things worth saying plainly:
1. **Exact computation and write-your-own-code are now statistically
   tied on BOTH domains (11/11 and 8/8) once the model is told the
   claim's own tolerance and given a realistic round/output budget** —
   the earlier gaps (90.9% on ml_data, then 87.5% on fpga_embedded) were
   harness artifacts (items 2 and the third correction above), not real
   findings. This is a small-n result (n=11, n=8) and should be read as
   "no detectable gap on this held-out set," not as proof the two
   approaches are equivalent at scale — see Result 3 below for the
   larger-n picture, which still shows a small, real gap for
   `fpga_embedded`.
2. **The round/output-budget fix (third correction) is what closed
   fpga_embedded's gap here**, not a change in the model or the claims:
   the one held-out miss from the previous rerun (`heldout-0015`, a
   misread WHS table) now resolves correctly at rounds=20 — the model
   found the real value (0.011 ns, on line 141) instead of latching onto
   a stray, much-larger number.
3. **Code-exec is unambiguously better than bare Nebius on both domains**
   (100.0% vs 9.1%; 100.0% vs 0.0%) — giving a model the ability to
   actually look is a real, substantial improvement over a one-shot
   guess, and on this held-out set now closes the gap to exact
   computation entirely.

### Result 2 — all 4 domains, held-out set (n=42, includes the fallback)

| Domain | Pipeline | Nebius-agent | Bare | Code-exec | Generic RAG | Perplexity | Tavily+Gemini |
|---|---|---|---|---|---|---|---|
| ml_data (n=11) | 100.0%/0% | — | 9.1%/0% | 100.0%/0% | 45.5%/27.3% | 0.0%/0% | 9.1%/0% |
| fpga_embedded (n=8) | 100.0%/0% | — | 0.0%/0% | 100.0%/0% | 62.5%/12.5% | 0.0%/0% | 12.5%/12.5% |
| robotics (n=8) | 100.0%/0% | 100.0%/0% | 25.0%/50.0% | 50.0%/25.0%† | 75.0%/12.5% | 25.0%/25.0% | 75.0%/12.5% |
| research_web (n=15) | 80.0%/0% | 86.7%/0% | 66.7%/33.3% | 66.7%/33.3%† | 33.3%/0% | 60.0%/40.0% | 73.3%/26.7% |

(Each cell: correct%/dangerous%. † = fallback rows for code-exec — same
user-prompt text as Bare for these two domains, under a slightly
different system prompt, so not a new finding about code execution
itself; included for table completeness only. The `robotics` row here
also reflects the item-7 text fix below — the earlier version of this
table was measuring baselines against claim text that didn't actually
state the depth/polarity it was asking about, so every non-pipeline
variant's robotics numbers in this row changed, not just code-exec's.)

**Notable, honest finding not seen in Tests #1-3's main-sample run:**
`heldout-0029` (a `research_web` claim about Micro Air Vehicles) is the
**first claim anywhere in this project where Nebius-agent (no verify)
got something right that the full pipeline got wrong** — nebius-agent
correctly said `contradicted`, the full pipeline said `undetermined`
(the near-duplicate guard or `_judge_stance()` step evidently filtered
out or reinterpreted a signal the unverified path kept). Test #3's
finding that "verify never changed an outcome" was accurate for its own
1,000-claim sample, but this one, genuinely-novel claim shows it's not
universally true — the verify/dedup machinery can occasionally cost a
correct answer, not just prevent wrong ones. Not root-caused further
here; flagged honestly as a real counter-example worth a deeper look in
a future pass, not swept under Test #3's earlier, now-narrower-than-
stated claim.

### Result 3 — larger-scale confirmation, main 1,000-claim sample (n=872)

Ran code-exec against the SAME 872 `ml_data`/`fpga_embedded` claims
Test #2/#3 already used (the exact subset of the 1,000-claim sample),
for a real, much-larger-n confirmation of Result 1's split:

| Domain | n | Pipeline correct/dangerous | Code-exec correct/dangerous | Code-exec conservative-miss | Code-exec other | Code-exec $/claim |
|---|---|---|---|---|---|---|
| ml_data | 756 | 100.0% / 0.0% | **99.47% / 0.13%** | 0.0% | 0.40% | $0.000759 |
| fpga_embedded | 116 | 100.0% / 0.0% | **96.55% / 2.59%** | 0.86% | 0.0% | $0.002813 |

(Percentages per row sum to 100%, including the `other` column — stated
explicitly after an earlier version of this table omitted it and its own
percentages silently summed to 99.5%. 3 of 872 claims crashed on
transient infra errors unrelated to the model or harness logic -- a
`ReadTimeout` and two DNS `Temporary failure in name resolution` errors
-- and were retried once each; all 3 retries succeeded cleanly, and the
numbers above use the retried results, disclosed here rather than
silently folded in.)

This now tells a dramatically cleaner, and far more accurate, story than
any of the three earlier attempts at this section did — see the
"Second," "Third" and "Fourth correction" notes above for why those
don't count:
- **ml_data is now essentially solved: 99.47% correct (752/756), a
  single dangerous case (1/756, 0.13%).** Inspected via the model's own
  EXECUTED CODE, not just its prose summary: `ml_data-000929`'s code
  contains `if val == '' or val == '?': continue` -- it checks for the
  literal string `"?"` but never for `"NaN"`, and this project's actual
  `auto_mpg.csv` spells its 6 missing `horsepower` readings as the
  literal string `"NaN"` (the SAME dataset-specific gotcha
  `anticassiopeia/domains/ml_data.py` itself was originally caught by,
  see `BUGS_FOUND.md`) -- `float("NaN")` parses successfully into a real
  IEEE NaN without raising, silently keeping all 398 rows instead of the
  real 392, computing p75=90.5 against a ground truth of 128.0. Not a
  tolerance or percentile-method artifact; a real data-hygiene mistake a
  model can make too, confirmed from its own code rather than inferred
  from its prose.
  - The other 3 "other" claims (0.40%) — corrected from the 7 originally
    reported here: 4 of those 7 were not empty messages at all, they
    were the negation-guard parser bug described in the "Fourth
    correction" note above, and are now scored "correct" instead.
    **Only these 3** (`ml_data-000767`, `-001857`, `-001860`) are genuine
    empty final messages: the model computes a real answer via a real
    tool call, then emits an EMPTY final message with
    `finish_reason="stop"` (confirmed via logging added in the third
    correction -- NOT a length cutoff). That logging also shows a
    `reasoning` field present in the raw API response alongside the
    empty `content` field on these 3 rows -- but, checked now against
    all 872 rows rather than assumed, that field is present on EVERY
    final message in this run, empty or not, so its presence next to
    these 3 is not itself evidence of anything; it does not distinguish
    them from the 869 normal responses.
    **UPDATED (fifth correction, 2026-10-24, `BUGS_FOUND.md`): actually
    investigated, not left as "remains unknown."** The logging gap is
    fixed (the `reasoning` field's real contents are now captured, not
    just its presence), and all 3 claims were re-run 12 more times total
    with zero reproductions of the empty-message shape -- plus a real,
    independently-observed `503 Service Temporarily Unavailable` from
    Nebius's own endpoint during that investigation, direct evidence the
    API does have genuine transient-failure modes of its own. Best-
    supported conclusion, not asserted as proof: a rare transient
    response-delivery glitch, not a bug tied to these claims or this
    harness. See `BUGS_FOUND.md`'s fifth correction for the full account.
    **Honestly reported as likely, not proven, and only partially
    verifiable from this artifact:** `BUGS_FOUND.md`'s own account of
    the retry investigation says 4 originally-affected claims were
    retried up to 4 additional times each (20 retries) plus 8 more on
    one of them (28 total) -- a wording this report previously gave as
    "5 affected claims," which does not match either that 4 or the
    (corrected) 3 "other" rows above. None of those retry transcripts
    were included in the delivered zip, so the retry count and outcome
    cannot be independently re-verified from the raw files alone, only
    from the prose record in `BUGS_FOUND.md`.
- **fpga_embedded: 96.55% correct, 2.59% dangerous (3/116), 0.86%
  conservative (1/116) -- a dramatically smaller gap than any earlier
  version of this run showed, now that the round/output-budget fix
  (third correction, above) is actually in effect.** Inspected
  individually:
  - The single remaining conservative miss used 6 of its 20 available
    rounds -- a genuine quick decline this time, not round-exhaustion.
  - The 3 dangerous misses are two distinct, real failure modes: (a)
    `fpga_embedded-002888`/`-002889`, the two genuinely-NA-valued real
    reports (ground truth `undetermined` -- the file's own Design
    Timing Summary row IS the literal string "NA"). The model correctly
    IDENTIFIES the value is "NA," then reasons "no numeric slack is
    reported, so the requirement is not satisfied" -- confusing
    *absence of evidence* with *evidence of absence*, concluding
    `contradicted` instead of `undetermined`. (b) `fpga_embedded-002573`:
    the real file's WHS is 0.036 ns (independently confirmed via
    `fpga_embedded_oracle.parse_report()`), but the model extracted
    0.345 ns -- a genuine column-misalignment misread, the same kind of
    mistake the held-out set's `heldout-0015` miss showed before the
    budget fix, just one this particular increase didn't happen to
    catch.
- **A real, but now small and well-understood, gap vs. the pipeline's
  100% on both domains.** What these four correction rounds
  collectively establish: the ORIGINAL apparent gap (up to ~70 points on
  fpga_embedded) was almost entirely harness bugs (round/output budget,
  hidden tolerance, display-precision, a parser bug) stacked on a real
  but much smaller underlying gap -- concentrated in exactly two
  understood failure modes (occasional fixed-width table misreads;
  confusing missing data with a negative answer), not a diffuse,
  unexplained error rate. "Exact computation is strictly more reliable"
  is now a defensible claim for this project's specific failure modes,
  not an assumption.
- **Total cost for this confirmation: $0.900039** across 872 claims
  ($0.00103/claim average; $0.000759 for ml_data, $0.002813 for
  fpga_embedded) — cheap, same order of magnitude as every other
  variant in this project, even after the round/output budget increase.

## Item 11 — a genuine held-out set (42 claims)

`stress_test/claims/generate_heldout.py` — zero shared template logic,
source files, or code path with `generate_manifest.py`:

- **ml_data:** a new real UCI dataset (Yacht Hydrodynamics, 308 real
  instances, never used before), statistics computed by hand-rolled
  arithmetic in the held-out generator itself, not
  `stress_test/oracles/ml_data_oracle.py`.
- **fpga_embedded:** a new real Vivado report from a different
  open-source project (nethakah/nasdaq-pipeline), values read directly
  from the real file by eye, not parsed by code shared with
  `fpga_embedded.py`'s own parser.
- **robotics:** the same two known parts (robotics.py's corpus
  genuinely only covers these two — "held-out" can't mean "a different
  known part" here), but exercised through the `Claim.context =
  {"depth_m": ..., "polarity": ...}` contract — confirmed by reading
  `generate_manifest.py` that the main 3,383-claim manifest **only ever
  uses free-text claims**, so this context-dict code path through
  `_parse_condition()` had literally never been exercised by any
  stress-test claim before now. Plus 2 genuinely unsourced-part claims
  (real Blue Robotics products with zero corpus entry) confirming the
  honest-gap path on parts `robotics.py`'s own part-detection doesn't
  even recognize as a string.
- **research_web:** 5 more real Wikipedia topics never in the 32-topic
  list above, independently fetched live on 2026-10-19.

**Ground truth cross-check:** ran the real pipeline against all 42
claims before running any baseline. Result: **39/42 correct (92.9%), 0
dangerous, 3 conservative misses** — and critically, **every single one
of the 27 `ml_data`/`fpga_embedded`/`robotics` claims matched my
independently hand-derived ground truth exactly** (zero mismatches),
which is the real validation this held-out set needed: the ground truth
isn't just asserted, it's been checked against the real system and
found internally consistent, with the only misses falling in
`research_web` (3 conservative misses — genuine production behavior on
claims the system had never seen, not a ground-truth error).

Full per-domain, per-variant results are in the tables under item 10
above (the held-out set is the vehicle for both items 10 and 11 at once
— the same 42 claims, run through every variant).

**Credibility disclosure (personal manual review, 2026-10-19): this is
a consistency check, not independent validation, and should be read
that way.** Two real limitations, stated plainly rather than implied
away:
- **This set was authored AFTER seeing this project's own failure
  modes** (the BlueROV2 conflict zone, the ml_data NaN bug, the
  percentile-convention question) — it was not designed blind, and it
  contains NONE of the claim shapes that actually found real bugs
  elsewhere in this project: no near-miss/tolerance-boundary cases (the
  0.999x/1.0001x adversarial pattern the main manifest uses), no
  percentile-method cases, no sentinel-value (NaN-as-string) cases, no
  deliberately adversarial claims at all beyond the 2 unsourced-part gap
  tests. A system could pass this set completely and still have the
  exact bugs this review found in the main manifest.
- **The held-out Pipeline and Nebius-agent rows were run ONCE and never
  rerun across these correction rounds** (unlike Bare/Generic
  RAG/Perplexity/Tavily+Gemini/Code-exec, each rerun at least once as
  harness bugs were found and fixed). Flagged explicitly rather than left
  implicit: this is low-risk here specifically because both read the
  claim's structured `context` fields directly, the same way code-exec's
  file-domain path does — none of the TEXT-level bugs this round fixed
  (the fpga display-precision bug, the robotics claim-text fix) change
  what either of these two actually sees or computes. It would NOT be
  safe to assume this in general for any future baseline added to this
  comparison that only reads claim text.
- **n=8-15 per domain is small enough that several of the headline
  comparisons above are not statistically distinguishable.** Example:
  the pipeline's 80.0% vs. Nebius-agent's 86.7% on `research_web`
  (n=15) — 95% **Wilson score** intervals (correction, personal manual
  review, 2026-10-21: an earlier version of this report gave Wald
  intervals clipped at 100%, [60%, 100%] and [69%, 100%] — wrong for a
  small n and a sample proportion this close to 1; Wilson is the correct
  interval here) are **[55%, 93%]** and **[62%, 96%]**
  respectively: heavily overlapping, so this is NOT good evidence that
  Nebius-agent is actually more accurate than the pipeline on
  `research_web`, only that one claim (`heldout-0029`) happened to land
  differently, as already stated honestly above. The same caveat applies
  to every other held-out per-domain percentage with n<20 in this
  report — read them as directional, single-sample data points, not
  precise rates.

What this held-out set DOES genuinely establish, scoped honestly: the
pipeline's ground truth logic checks out against an independently-
derived (hand-rolled arithmetic, different real files) computation with
zero mismatches on 27 non-research_web claims, and the system doesn't
collapse or behave nonsensically on genuinely novel inputs (new files,
a never-before-exercised code path, new web topics). That is real and
worth having. It is not evidence of robustness against adversarial or
boundary-condition inputs, which this set doesn't contain.

## Actual spend, Phase B

| | Cost |
|---|---|
| Held-out set, all variants (pipeline/bare/nebius-agent/generic-rag shared tracker) | $0.049682 |
| Held-out set, code-exec (third-corrected rerun: rounds=20, 16K output cap) | $0.026078 |
| Main-sample code-exec (ml_data+fpga_embedded, n=872; third-corrected rerun, incl. 3 infra-flake retries) | $0.900039 |
| Diagnostics this round (fpga 20-round budget test, empty-message repro attempts) | $0.05555 |
| Perplexity, Tavily, Gemini (held-out) | small — not against the $20 Nebius cap |
| **Phase B Nebius subtotal** | **$1.031349** |
| **Nebius cumulative (Tests #1-3 + Phase B)** | **$1.944991 (9.7% of the $20.00 cap)** |

(The code-exec lines above have climbed across three correction rounds —
$0.017024→$0.030221→$0.026594 held-out, $0.642645→$0.844813→$0.823835→
$0.900039 main-sample — purely because the round/output budget kept
being raised to fix real bugs (4→10→20 rounds, 4,000→16,000-char output
cap), each time traded against a real accuracy improvement documented
above. Earlier, cheaper numbers belonged to runs now known to be buggy
or stale and are not kept for comparison. The fourth correction's
accuracy fix above added **$0** to this table — it reparsed already-
saved `response_text` offline; no new API calls were made.)

The hard stop was never approached at any point in Phase B.
