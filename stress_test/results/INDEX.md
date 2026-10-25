# Stress-test findings index

The front door into everything `stress_test/` has found, in order. Every
report below is a real investigation against the real production
pipeline (or a real, honestly-labeled baseline), with real root causes
and real fixes — nothing here is re-summarized to look cleaner than the
report it points at; read the linked file for full detail, caveats, and
correction history. This index does not replace, restructure, or absorb
any existing file — `BUGS_FOUND.md` stays append-only, every report
below stays exactly as it was written.

## Added 2026-10-25: the product's domain names were renamed; stress_test/ was not

`anticassiopeia`'s four domains were renamed (a full, breaking rename,
including `Claim.domain`'s real wire value): `robotics`->`substrate`,
`research_web`->`searchlight`, `ml_data`->`quant`,
`fpga_embedded`->`silicon`. Every file below, every raw result, and
every one of `stress_test/`'s own `.py` scripts was deliberately left
untouched — this directory is historical record, not live product code,
and rewriting a 3,383-claim manifest's domain field (or any report's own
numbers) to use names that didn't exist when they were written would be
revisionist, not a correction.

**Practical consequence for anyone running `stress_test/` scripts going
forward**: 4 TEMPORARY backward-compatibility shim modules exist at the
OLD import paths (`anticassiopeia/domains/{robotics,research_web,ml_data,fpga_embedded}.py`)
so these scripts still IMPORT successfully — but
`run_test3_nebius_agent.py`'s own monkeypatch trick (disabling
`verify_proposal` to build its "no independent verify" baseline) now
silently no-ops, since it patches the shim's module namespace, not the
real one (`substrate.py`/`searchlight.py`) the renamed adapters actually
use. Any script comparing against that baseline is, until a future
migration pass updates `stress_test/` itself, actually comparing against
the SAME fully-verified pipeline on both sides. `tests/test_heldout_adversarial.py`'s
`ml_data`/`fpga_embedded` adversarial-case tests (and their live-gated
siblings) are now skipped, dated, for the identical structural reason —
see that file's own skip message.

## Read this first: one finding changes how every number below should be read

**Every `stress_test/*.py` script was missing a `load_dotenv()` call.**
`research_web.py`'s real PRIMARY search backend, `_tavily_search()`,
reads `os.environ.get("TAVILY_API_KEY")` directly — not
`dotenv_values()`, which is how every stress-test script read ITS OWN
provider keys (Perplexity/Tavily/Gemini) for their own direct calls.
Because no stress-test script ever called `load_dotenv()` to populate
the real process environment, `TAVILY_API_KEY` was never actually set in
any of them — so `_tavily_search()` silently returned `[]` (its own
documented contract for a missing key) in **every single stress-test run
in this project's history that exercised `research_web.py`'s real
pipeline**: Test #1, Test #2's pipeline leg, Test #3's Pipeline/Nebius-
agent/Generic-RAG rows, the Nemotron pivot, and the first run of
competitive-benchmark round 1. Every one of those runs silently fell
back to the much weaker DDG/Wikipedia backends for `research_web`
claims, never to Tavily.

**The live production server (`api/server.py`) was never affected** — it
already calls `load_dotenv(override=False)` at import time, so the
deployed service has always had Tavily active. This means the real,
live system has been measurably stronger at `research_web` than every
one of this project's own test reports shows. Confirmed directly (main
session, same day this index was written): calling Tavily live with the
exact claim text from three of round 1's failures returned excellent,
directly on-point results for all three, and re-running those claims
through the real engine with `load_dotenv()` actually called resolved
two of them correctly that had previously missed.

Fixed at the source in all eleven scripts (see `git log --oneline` for
the commit); **not yet retroactively re-run against the full historical
claim sets** (Test #1's 3,311 claims, Test #2/#3's 1,000-claim sample,
etc.) as of this index's writing — that would be real, additional spend
and is a candidate for a future round, not assumed to already be done.
Read every `research_web` number in TEST1/TEST2/TEST3/NEMOTRON_PIVOT
below as a measurement of "Anti-Cassiopeia's research_web pipeline
running on DDG/Wikipedia only," not of its actual, currently-shipped
search behavior.

## Chronological index

| Date | Report | What was tested | Headline finding | Fix |
|---|---|---|---|---|
| 2026-10-18 | [TEST1_REPORT.md](TEST1_REPORT.md) | 3,311-claim full manifest run, real pipeline | 99.3% correct blended; split by Phase B into 99.58% deterministic / 97.16% verification. 2 real bugs: `ml_data`'s NaN-as-string parsing, and a ~1-in-10 live-call evidence-loss masking a genuine 2-source robotics conflict. `research_web`'s 7 conservative misses (of 24 claims) — **now known to be measured without Tavily, see above**. | Both bugs fixed in production same day; 17 affected claim IDs re-verified correct post-fix. |
| 2026-10-18 | [TEST2_REPORT.md](TEST2_REPORT.md) | Bare `gpt-oss-120b` vs. real pipeline, 1,000-claim stratified sample | Pipeline 99.9% correct / 0.0% dangerous vs. bare 17.7% / 4.1%. Bare Nebius confidently wrong 66.7% of the time on the hardest robotics tier. 13.5% of file-dependent (ml_data/fpga) bare answers were confident FABRICATED-DETAIL — no file access, no hedge, often lucky-right (102/118) but sometimes dangerously wrong (16/118). | None needed — this is a comparison report, not a bug hunt. `research_web`'s 1 pipeline miss (of 7) is now known to be measured without Tavily. |
| 2026-10-18/19 | [TEST3_REPORT.md](TEST3_REPORT.md) | 8-row competitor ladder (pipeline, bare, nebius-agent, generic-RAG, Perplexity, Tavily+Gemini, code-exec, SAFE-cited) on the same 1,000-claim sample | The real accuracy jump (36.2%→99.9%) comes almost entirely from domain-tuned retrieval, BEFORE independent verification is even added back — "knowing what to look for and where" is this project's real edge, more than the verify step, *on this sample*. Contains its own explicit note recommending Tavily as a future `research_web` upgrade based on its 100%-of-queries reliability in the Tavily+Gemini leg — the decision later made, see MODEL_SELECTION_FINDINGS.md. Multiple harness bugs found and corrected in-place (generic-RAG synonym parsing, Gemini free-tier daily quota exhaustion). | Generic-RAG verdict-parser fix (reparsed offline). Gemini circuit breaker added. `research_web`/`robotics` numbers in the Tavily+Gemini row are incomplete (quota ran out before reaching them). |
| 2026-10-19 | [PHASE_B_REPORT.md](PHASE_B_REPORT.md) | External-review response: fixed circular robotics ground truth, expanded research_web 24→96 claims, built a genuine code-execution baseline, built a 42-claim genuinely-held-out set | Code-exec (model + real `execute_python` tool) ties exact computation on the held-out set (100%/100%) and comes close at scale (99.47% ml_data, 96.55% fpga_embedded) — "a model that can actually look" closes most of the gap bare Nebius showed. Ground-truth circularity fix changed 0 verdicts (the engine's trust formula already collapsed to "do the sources agree" for this manifest). One genuine counter-example (`heldout-0029`) where skipping verification got a claim right that the full pipeline got wrong. | Robotics ground-truth generator decoupled from engine.py's own constants. Code-exec harness fixed across 4 correction rounds (round/output budget, hidden tolerance, display-precision, parser bugs) — see the report's own "Second/Third/Fourth correction" notes for the full, honest history of getting this one right. |
| 2026-10-24 | [NEMOTRON_PIVOT_REPORT.md](NEMOTRON_PIVOT_REPORT.md) | Nemotron Nano/Super/Ultra vs. baseline `gpt-oss-120b`, robotics + research_web | **Nemotron Ultra: zero dangerous misses across all 3 independent robotics runs** (the only tier with a perfect safety record) → recommendation: route robotics `propose()` to Ultra. `research_web` stays on `gpt-oss-120b` — no Nemotron tier beat it there at any tested sample size (Ultra came closest, +2.5% post-fix, but on one sample against baseline's 10-run clean record). Found and fixed 2 real crashes (unset `max_tokens`, a non-string `content` field) and 1 real prompt gap (the ESP32/ESP32-S31 entity-matching bug, since fixed in `retrieval/stance.py`). | `ROBOTICS_MODEL = Nemotron Ultra` adopted in production. `max_tokens` fix, entity-matching stance-prompt fix, both model-agnostic and still in effect. **This report's own research_web numbers were measured without Tavily — see the top of this index.** |
| 2026-10-24 | [nemotron_pivot_bugs.md](nemotron_pivot_bugs.md) | Raw auto-appended dangerous/crash log underlying the pivot report | Supporting detail only — all entries are `research_web` claims (ESP32/BeagleBone/Raspberry Pi GPIO-count claims), all later explained in the pivot report itself. | — |
| 2026-10-24 | [investigate_empty_bugs.md](investigate_empty_bugs.md) | Follow-up investigation into 3 code-exec claims with empty final messages | First attempt crashed on a `.env`-loading race (`dotenv_values()` called before the file was readable in that process — a smaller, earlier instance of the same class of secret-loading fragility as the Tavily finding above); the real repro attempt hit a genuine, independently-observed `503` from Nebius's own endpoint, supporting "rare transient glitch" over "deterministic bug" as the best-supported conclusion. | Logging improved so a future recurrence shows real cause instead of an empty message with no context. |
| 2026-10-25 | [V2_BYOE_STRESS_TEST_REPORT.md](V2_BYOE_STRESS_TEST_REPORT.md) | v2 "bring your own evidence" scenario matrix, 17 scenarios, real uploaded documents (ODrive, NASA JPL rover excerpts) | Found and fixed the ODrive/heading-entity-ambiguity bug: `judge_stance()` couldn't confirm a quote was about the claimed device when the device name lived only in a preceding section heading. 10 live calls total, kept deliberately small. | `robotics.py`'s BYOE call site now prefixes the source filename onto the quote shown to `judge_stance()`. Scoped to that one call site, not the shared function. |
| 2026-10-25 | [BENCHMARK_ROUND1_REPORT.md](BENCHMARK_ROUND1_REPORT.md) | Competitive-benchmark protocol round 1 — 9 hand-picked claims across all 7 categories, vs. 5 competitor variants | Found and fixed a real calibration-probe bug: a flat claim about Quran revelation was confidently CONFIRMED on a passage that itself hedged "according to Islamic tradition" — the companion resurrection probe only passed by accident (zero evidence that run). generic-RAG "won" both calibration probes by refusing to commit on almost everything (6/7 undetermined) — flagged as not a real win, per the protocol's own §6. **This round's first run is also now known to be measured without Tavily — see the top of this index; a corrected re-run is in progress as of this writing, check the report itself for whether an erratum has been added.** | Third additive paragraph in `STANCE_SYSTEM_PROMPT` (attributed belief ≠ confirmed fact). `load_dotenv()` fix applied to the whole `stress_test/` harness as a direct result of investigating this round's own conservative misses. |

## Model-selection findings

Pulled together in one place, with evidence and dates, in
[MODEL_SELECTION_FINDINGS.md](MODEL_SELECTION_FINDINGS.md) — read that
file for the full picture rather than reconstructing it from the
reports above individually; it cross-references exactly which report
each decision came from and flags which ones should be considered for
re-measurement now that Tavily is confirmed to actually work.

## Claim-schema divergence across this project's data files

Three real, different schemas exist for "a claim," evolved over time.
This is documentation of the divergence, not a unification — unifying
them is a bigger, riskier change than this pass's scope.

**1. `stress_test/claims/manifest.jsonl`** (the original, largest set —
3,383 claims as of the Phase B research_web expansion) and
**`stress_test/claims/heldout_manifest.jsonl`** (42 claims, same shape,
independently authored) share one schema:
```json
{"claim_id": "<domain>-<zero-padded-number>", "domain": "robotics|research_web|ml_data|fpga_embedded",
 "tier": 1|2|3, "claim_payload": {"text": "...", "domain": "...", "context": {...}},
 "ground_truth_verdict": "confirmed|contradicted|undetermined",
 "ground_truth_method": "<free-text explanation of how truth was derived>",
 "provenance": "<free-text source citation>"}
```
`claim_payload` is exactly what `anticassiopeia.core.Claim(**claim_payload)`
expects — this is deliberate, so every stress-test harness script can
construct a real `Claim` directly from a manifest row with no
translation step. `context` is domain-specific: empty `{}` for
robotics/research_web's free-text claims, `{dataset_path, column, stat,
expected_value, tolerance}` for ml_data, `{report_path, metric,
comparator, expected_value}` for fpga_embedded.

**2. `stress_test/claims/test2_sample.jsonl`** is deliberately NOT a
copy of manifest rows — it's a pointer file, one line per sampled claim:
```json
{"claim_id": "robotics-003051", "domain": "robotics", "tier": 2}
```
Every script that uses this sample (`run_test2.py`'s `load_sample_claims()`)
joins these IDs back against the full `manifest.jsonl` to recover the
real `claim_payload`/`ground_truth_verdict` — by design, so the sample
can never drift out of sync with the manifest it was drawn from.

**3. `stress_test/run_benchmark_round1.py`'s `ROUND1_CLAIMS`** (and any
future round's claim list, by the same convention) is a different shape
again, Python literals rather than JSONL, with two fields the other two
schemas don't have at all:
```python
{"claim_id": "r1-cat1-darwin-wallace", "category": 1, "category_name": "causal/relational",
 "domain": "research_web", "tier": 1, "claim_payload": {...},
 "ground_truth_verdict": "contradicted", "ground_truth_note": "<the real citation/reasoning>"}
```
`category`/`category_name` exist because competitive-benchmark rounds
draw from the protocol's own 7 named categories
(`claude/ANTI_CASSIOPEIA_COMPETITIVE_BENCHMARK_PROTOCOL.md`), which
`manifest.jsonl`'s `tier` concept has no equivalent for. `tier` is kept
only for compatibility with the shared harness functions
(`run_test1.classify()` and friends don't require it to mean anything
specific) — for hand-picked benchmark-round claims it's currently a
placeholder (`1` for every claim in round 1), not a real difficulty
signal the way it is in `manifest.jsonl`. A future round that wants
`tier` to mean something for benchmark claims would need to define that
meaning explicitly; it isn't implied by this schema today.

Practical consequence for a future session: **you cannot pass a
`ROUND1_CLAIMS`-shaped list anywhere expecting `manifest.jsonl`'s
`ground_truth_method`/`provenance` fields** (it has `ground_truth_note`
instead, a single field covering both), and **you cannot assume
`test2_sample.jsonl`'s rows are self-contained** (they require the join
step). Every stress-test script that's been checked already handles its
own expected schema correctly; the risk is a NEW script assuming one
schema's fields exist on data drawn from a different one.
