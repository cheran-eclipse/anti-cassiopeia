# Architecture

## The mechanism

A narrow, checkable `Claim` is routed to the one `DomainAdapter` that can
gather `Evidence` for it. One shared scoring rule in `VerificationEngine`
turns that evidence into a `Verdict`: `CONFIRMED`, `CONTRADICTED` or
`UNDETERMINED`.

```
Claim ──▶ VerificationEngine.verify()
              │
              ▼
        DomainAdapter.gather_evidence(claim)   (substrate | silicon | searchlight | quant)
              │
              ▼
        list[Evidence]  (source, snippet, stance, trust, locator)
              │
              ▼
        VerificationEngine._score()  ──▶  Verdict (state, confidence, reasoning, missing)
```

## Why the domain split

Four domains share one contract. Each adapter is the only place that knows
what "evidence" means for its domain: a datasheet locator for `substrate`,
a timing report for `silicon`, a fetched source for `searchlight`, a re-run
computation for `quant`. The engine only sees `Evidence` objects with a
`stance` and a `trust` weight already assigned. A fifth domain is a new
`DomainAdapter` subclass, not a fork of the engine.

## Why three states, not a probability

A single confidence score lets a fluent but fabricated answer carry a
number that makes it look measured. Three discrete states, with
`UNDETERMINED` as a normal and frequently correct answer rather than an
error fallback, force every integration to handle "I don't know" instead of
rounding it up to a guess.

`Verdict.missing` names what evidence would resolve an `UNDETERMINED`
claim. Each adapter's `describe_gap()` supplies it.

**Display rename (v3).** The frontend shows `UNDETERMINED` as **CLOUDED**
so the three displayed states all start with C. The enum value and the API
wire value (`"state": "undetermined"`) are unchanged, because the public
demo depends on them. `docs/index.html`'s `displayStateLabel()` is the only
place the translation happens.

## Current status

| Piece | Status |
|---|---|
| `core/verdict.py` | done |
| `core/domain.py` | done |
| `core/engine.py` | done: simple scoring, redundancy-aware and confidence-capped |
| `domains/substrate.py` | live-verified. 3 of 4 parts sourced (BlueROV2, Bar30, Bar100XT); QuSpin confirmed to have no rating. Runs on Nemotron Ultra |
| `domains/quant.py` | offline, tested. Known gaps listed below |
| `domains/silicon.py` | offline, tested. Timing summary and SVD register map |
| `domains/searchlight.py` | two modes. Tavily primary search, DDG and Wikipedia fallback |
| `llm/nebius_client.py` | live-verified Nebius Token Factory client |
| `api/server.py` | auth and rate limiting |
| `scripts/demo.py` | end-to-end demo, 6 claims, all 4 domains |
| `Dockerfile` | build-tested |
| `.github/workflows/evals.yml` | written; no CI run observed |
| `evals/` | 31 cases, all 4 domains, all passing (14 skip without a live key) |

Each piece's history is in its section below.

### `core/engine.py`

Trust-weighted sum against a fixed threshold (`DECISION_THRESHOLD`). It is
a simple first version; see `docs/DESIGN.md` §3. `contested` evidence is
excluded from scoring and shown in the reasoning.

**Three fixes from an external review of the scoring rule:**
1. Confidence reached 1.00 from a single piece of evidence regardless of
   its `trust`. `SINGLE_SOURCE_CONFIDENCE_CAP` now caps confidence below
   full certainty when only one source contributes. Two or more independent
   sources still reach 1.00.
2. Two near-identical pieces of evidence from the same source summed like
   two independent confirmations. `_redundancy_collapsed_weight()` now takes
   the highest-trust piece per source before summing across sources.
3. A source that returned an unusable (not `None`) answer vanished from the
   verdict when another source alone was enough.
   `DomainAdapter.describe_partial_gaps()` is now called unconditionally and
   appended to `Verdict.reasoning` (first override in `domains/substrate.py`).

**Item 19, time decay: partially implemented.** `Evidence.timestamp` plus
`_decayed_trust()` / `_decay_all()` in `engine.py` decay trust by evidence
age when the evidence carries a date. The floor `MIN_DECAY_FACTOR = 0.7`
keeps decay from flipping a single-source verdict to `UNDETERMINED` on age
alone: every current adapter's single-source trust is 0.9, and
`0.9 * 0.7 = 0.63 >= DECISION_THRESHOLD = 0.5`. This is checked by
`tests/test_engine.py::test_min_decay_factor_can_never_flip_an_existing_single_source_verdict`
and by re-running all 385 `silicon` claims in the 3,383-claim stress-test
manifest with decay on: zero verdict flips.

Decay is wired into one domain: `silicon.py`'s Vivado-report path, using the
`| Date : ...` header line present in all 9 committed Vivado reports. The
two older synthetic fixtures have no date and never decay; a third,
`evals/fixtures/vivado_timing_report_dated_2016.rpt`, has a date so tests
can exercise decay. It is not wired into the SVD register path (CMSIS-SVD
has no comparable date field), `quant.py` (a re-computed statistic is always
fresh), or `substrate.py` / `searchlight.py` (no reliable per-evidence date
source was found).

### `domains/substrate.py`

Chunking, BM25, a live `extract.propose()` call against
`NebiusTokenFactoryClient`, and `verify_proposal()` all run over a partial
corpus of Constellation-sourced excerpts. Verified offline against a
scripted fake client (17 tests) and against the live API: both `test_live_*`
tests in `tests/test_domains_substrate.py` pass (evidence accepted for a
corpus fact, and "not found" for a fact absent from the shown passages).

**Non-determinism, fixed.** An early live run returned the `kind` field
("rated" / "tested" / null) inconsistently across identical calls (about
4/8). The cause was `retrieval/extract.py`'s prompt, which named the three
values without saying what they mean. After the prompt was changed to
explain the distinction, runs were consistent at 8/8 and 6/6 on two
models. `kind == "rated"` was not loosened to get there.

Stance is derived per claim: depth and survives/fails polarity come from
`Claim.context` or a narrow text grammar, the spec is re-parsed from the
verified quote, and bar is converted to depth with a 5% too-close-to-call
margin. Bar100XT and QuSpin have their own sources, described below.

**Two bugs found by `stress_test/` Test #1 (2026-10-18)**, detailed in
`stress_test/BUGS_FOUND.md`:
1. A "not found" from `propose()` was accepted on the first try with no
   retry, so a transient miss could read as a real evidence gap.
   `_propose_with_retry()` now makes up to 3 attempts, only on an actual
   `None` return. 30/30 reruns of the previously dangerous "BlueROV2
   survives 200 m depth" claim now resolve `UNDETERMINED`.
2. The dominant cause, found after the first fix still failed a live rerun:
   `_RETRIEVAL_QUERIES["bluerov2"]["DOC1_BlueROV2"]` asked about "aluminum
   acrylic housing" at once, and DOC1 contains two rated-depth lines
   (Acrylic: 100 m, Aluminum: 300 m) that a live model picked between
   near-randomly (about 40% wrong-line rate over 20 trials). Retrying does
   not fix a wrong but real answer. Dropping "acrylic" from the query fixed
   it: 25/25 reruns retrieve the Aluminum / 300 m line.

**Live fabrication caught (2026-10-19).** The earlier "fabricated quote or
value is rejected" tests used a scripted fake client. A live, reproducible
case exists: asking `propose()` an adversarial unit-conversion question
against DOC1's meters-only text makes the model sometimes attach a
`value`/`unit` (for example 984.25 ft) that its own verbatim quote (300 m)
does not state. This occurred in about 7.5% of calls across two 20-sample
batches. `_spec_depth_m()` discards every one observed, tested by
`test_live_adversarial_unit_conversion_fabrication_is_caught_not_trusted`
(50 live samples; it skips if a run observes none, since this is
probabilistic).

**Fourth-round fixes (external review):**
1. A source that returned something other than a clean `None` (incomplete,
   ambiguous, or rejected by verification) used to `continue` silently, so
   once another source was enough, the failure vanished.
   `gather_evidence()` now records why each was skipped in `partial_gaps`,
   returned through `describe_partial_gaps()` and shown in every verdict's
   reasoning.
2. The sourced facts are manufacturer ratings, not destructive tests,
   whether the claim says "survives", "fails" or "is rated for". That was in
   the module docstring but not in the verdict a caller reads. Every
   accepted snippet now says "checked against the manufacturer's RATED limit
   (not an observed destructive test)". Splitting "survives" from "is rated
   for" would only turn every "survives" claim into `UNDETERMINED`, since
   the corpus has no destructive-test data, so the fix is the explicit
   statement.

**Fifth round (2026-10-24): Bar100XT sourced, QuSpin's absence confirmed.**
Blue Robotics' BarXT product page (https://bluerobotics.com/?p=219055) is
the manufacturer's spec sheet; no separate PDF exists. It states a 0 to 100
bar operating range (about 995 m depth-equivalent with the project's
seawater-density conversion). It is sourced as `DOC4_Bar100XT` in
`_SOURCES` / `_RETRIEVAL_QUERIES` at trust 0.85, the same as Bar30's chip
datasheet, through the same retrieve, propose, verify pipeline
(`test_bar100xt_claim_produces_real_evidence_with_a_real_locator`, with a
fake client). The page also states a 400 bar figure under a "highest
pressure before permanent damage" footnote; that is left out of the corpus
excerpt, as with Bar30 (see `docs/extracted/constellation-robotics-seed.md` §3).

QuSpin's official QZFM Gen-3 page (https://quspin.com/qzfm-gen-3) is a blog
post with no datasheet. Reading the whole page for any pressure, depth,
submersion, waterproof or IP-rating wording found none, which confirms the
earlier assumption that QZFM Gen-3 has no submersion rating. It still gives
no number to compare a depth against, so a QuSpin depth claim stays
`UNDETERMINED`. The QuSpin branch of `describe_gap()` now cites this source
and date. No corpus file was added because there is no numeric fact to
route (see `docs/extracted/constellation-robotics-seed.md` §4).

### `domains/quant.py`

Re-computes the claimed statistic from the CSV(s) using only stdlib `csv`
and `statistics` (`median()`, `quantiles()` and `correlation()`; the project
requires Python 3.11 or later). It supports `median`, `p25`, `p75` and
`correlation` alongside `mean`, `min`, `max` and `stdev`. It reads
multi-file datasets (`dataset_path` as a list, rows concatenated; a column
missing from one shard is a named mismatch). Compound claims
(`"checks": [...]`) use AND semantics: `CONFIRMED` only if every sub-check
holds, one failure `CONTRADICTS` the whole claim, and a sub-check the
adapter can't evaluate makes it `UNDETERMINED` with that reason. The
adapter stays outside `retrieval/` (`docs/DESIGN.md` §5): there is no
passage to search, only a computation to run.

**Bug: too few data points.** `stdev`, `p25`, `p75` and `correlation`
crashed with an uncaught `StatisticsError`. `_check_single()` now validates
each statistic's minimum sample size.

**Bug found by Test #1 (2026-10-18)**, see `stress_test/BUGS_FOUND.md`. The
UCI `auto_mpg.csv` spells a missing value as the string `"NaN"`.
`float("NaN")` parses without raising, so it silently corrupted `mean`,
`median`, `p25`, `p75` and `correlation`, and crashed `stdev`.
`_read_column()` and `_read_column_pair()` now also require
`math.isfinite(value)`. Re-verified on the real file (mean, median, p25,
p75, stdev and correlation of `horsepower` all correct), plus a regression
test showing clean data is unaffected.

**Security fix: path traversal and arbitrary file read (external review,
2026-10-19, two passes).** `dataset_path` went straight to
`Path(...).open()` with no containment check, and `Claim.context` comes
verbatim from a `POST /verify` body. Every path is now resolved, which
defeats both `..` traversal and symlink escapes (checked on the resolved
path), and must land inside `allowed_base_dirs` (default `evals/fixtures/`
and `stress_test/data/`; injectable in the constructor, like
`SubstrateAdapter(client=...)`). Follow-up fixes:
1. A null byte in a path made `Path.resolve()` raise `ValueError`, which was
   not caught (only `OSError` was), producing a 500. `_path_safety.py` now
   catches both.
2. Elements of a `dataset_path` list weren't checked to be strings, so
   `Path(123)` crashed. They are now validated.
3. The rejection message printed the server's absolute allowed-directory
   paths. It now only echoes the caller's own unresolved input.

Each has a regression test.

**Percentile convention (2026-10-19).** `p25` / `p75` use
`statistics.quantiles(..., method="exclusive")`, the default, which differs
from numpy, pandas and Excel's default (linear interpolation). This affects
300 of 2,504 `quant` manifest claims and was not stated where a user would
see it. It is now documented in the module docstring and in the manifest's
p25/p75 claim text.

**Display-precision bug in `stress_test/claims/generate_manifest.py`.**
Claim text rounded `expected_value` to 6 significant figures while the
structured value kept full precision. For 41 of 2,185 single-stat claims
(30 labeled "confirmed") with very tight tolerances, the rounding error
exceeded the tolerance, so the claim text stated a different number from
the one verified. The adapter never reads display text, so it was
unaffected; baselines that see only the text were treated unfairly. (The
count was first misreported as 2,504; corrected on a second review,
2026-10-21, since the other ~320 claims use different text paths.) Fixed
with a tolerance-aware formatter, and the full manifest was checked for
remaining inconsistencies: zero.

**Fixed: the `-200` missing-value sentinel.** UCI's documentation for
`air_quality.csv` defines `-200` as the missing-value marker. Neither this
adapter nor `stress_test/oracles/ml_data_oracle.py` handled it, so both
treated `-200` as a reading. Both now apply a per-filename lookup
(`_DATASET_SENTINELS` in `quant.py`) populated only from a cited source.
The oracle keeps its own copy of the table, since sharing code with the
thing it checks would defeat the point of an independent oracle. It is not
a blanket rule: `test_minus_200_in_a_differently_named_file_is_not_treated_as_a_sentinel`
confirms a `-200` in an undocumented file is still a value.

**Known follow-up.** About 212 `air_quality.csv` claims in the stress-test
manifest had their `expected_value` and ground truth generated before this
fix, with `-200` included. Running the full manifest now shows mismatches
on those claims that come from stale ground truth, not from the adapter.
The 25 such claims in the 1,000-claim Test #2 and #3 sample were relabelled on
2026-10-26 with the independent oracle, in
`stress_test/claims/corrected_labels_overlay.jsonl` (the manifest is not
edited); see `stress_test/results/DOC_FED_CONTROL_REPORT.md`. The other
air-quality claims in the full manifest are still stale. See
`stress_test/BUGS_FOUND.md`.

### `domains/silicon.py`

Parses Xilinx/AMD Vivado's `report_timing_summary` output: Design Timing
Summary (WNS/TNS/WHS/THS/WPWS/TPWS in Vivado's fixed column order) and
Clock Summary (per-clock period and frequency, generated clocks indented
under their source). This replaced an earlier invented `key: value`
format. The column headers and table structure were copied from a fetched
open-source project's actual Vivado report (Elphel x393; URL and fetch
details are in the module docstring), not written from memory.
Multi-corner reports use a `Corner: <NAME>` label line. That is this
adapter's own convention for concatenating per-corner blocks into one
file; it was not copied from an official sample, because the one real
multi-corner `.sta.rpt` found sat behind a login.

**Register-map support (2026-10-24), via a second file format.**
`report_timing_summary` carries no register or address data, and
`register_map_claim_undetermined.json` still covers that gap for Vivado
files. Register-map claims go to CMSIS-SVD (System View Description), a
vendor-neutral XML register-map schema used across embedded systems. SVD
was chosen over a Xilinx export because no Xilinx register-map sample could
be found (a search for IP-XACT `component.xml` examples returned only
tooling docs and MathWorks material; see `silicon.py`'s module docstring),
and SVD suits a domain meant to cover arbitrary submissions.

It was checked against two independently sourced files: ARM's CMSIS_5
`ARMCM4.svd` (header only, no peripherals, so not usable as register data)
and Espressif's published `svd/esp32c2.svd` (Apache-2.0, with real
peripherals, addresses, offsets and bit layouts).
`evals/fixtures/esp32c2_register_map_excerpt.svd` holds two complete
peripheral blocks (RNG, BB) copied byte for byte from the latter, the same
partial-excerpt convention `doc3_bar30_excerpt.txt` uses.

`_parse_svd_register_map()` scans the one-tag-per-line SVD structure by
nesting (peripheral, register, field), position-based like
`_parse_report()` for Vivado's tables, and records the source line number of
every value so each register-map `Evidence.locator` points at a checkable
line. New metrics: `peripheral_base_address`, `register_offset`,
`register_size_bits`, `field_bit_offset`, `field_bit_width`. These are
static facts an SVD states, never a runtime register's contents. They go
through `_check_register` / `_gather_register_evidence`, separate from the
Vivado timing logic (register claims have no corner), and the same
path-containment check (`is_path_within_allowed_dirs`) guards both. 15 new
offline tests pass; `evals/cases/silicon/svd_register_offset_confirmed.json`
is an end-to-end case.

**Display-precision bug (second manual review, 2026-10-21).** The `:.6g`
bug described under `quant.py` was still present here.
`_fpga_single()` in `stress_test/claims/generate_manifest.py` displayed
`expected_value` at 6 significant figures, so its two
boundary-adversarial claims per metric per file (`== real+1e-6`,
`>= real+1e-6`, both "contradicted") rounded to text identical to the true
value. 28 claims stated the file's exact value while being graded
"contradicted" over an invisible 1e-6 offset. The tolerance-aware formatter
now covers these two call sites. Regenerated and diffed: 0 verdict or
context diffs, 62 text diffs (28 fixed, 34 cosmetic scientific-notation
changes).

**Security fix: path traversal and arbitrary file read (external review,
2026-10-19, two passes).** Same issue and same fix as `quant.py`'s
`dataset_path`, including the null-byte and path-leak follow-ups.
`report_path` must resolve inside `allowed_base_dirs`, defeating `..`
traversal and symlink escapes, with its own tests.

### `domains/searchlight.py`

**Two modes.**

Mode 1: a pre-selected URL is fetched and the quote is checked verbatim.
Evals and the demo use a local fixture server (`evals/fixture_server.py`)
so the verdicts can't change when a third-party page does. One live case
against example.com (`live_example_com_drift`) accepts `contradicted` as a
"page drifted" outcome.

Mode 2: multi-candidate research from a claim alone. Keyless search
(Wikipedia's API, working; DuckDuckGo HTML, blocked as anti-bot from the dev
sandbox but tried best-effort) finds candidate pages. These are fetched,
chunked (`retrieval/chunking.py`) and BM25-searched with one combined index,
then grouped by source page so up to 3 distinct sources are each checked,
not just the top chunk. They go through the same live `extract.propose()`
(`openai/gpt-oss-120b`) that `substrate.py` uses, then `verify_proposal()`.
A `CONFIRMED`, a `CONTRADICTED`, and two kinds of `UNDETERMINED` (no
candidates, and candidates found but the fact absent) were each confirmed
live, repeatedly; see `evals/cases/searchlight/live_multi_candidate_*.json`.
Stance (supports or contradicts) in mode 2 is a bounded LLM judgment on a
quote that was already verified mechanically. Two purely mechanical
approaches (strict substring, token-overlap ratio) were tried first and both
failed on live tests (see the module docstring).

**Near-duplicate guard.** With several sources, two can be the same source
(a mirror, a copied sentence). `_is_near_duplicate_evidence()` (Jaccard token
overlap >= 0.8) drops a second near-verbatim match before scoring, so a
mirror isn't counted as independent confirmation. A differently worded
second source still counts. Both are tested against local fixture pages
(`test_multi_candidate_mirror_sources_count_as_one_not_two`,
`test_multi_candidate_genuinely_different_sources_both_count`).
`core/engine.py` was not changed; its same-source redundancy fix is
described above.

**Security fix: SSRF (external review, 2026-10-19, three passes).** Both
fetch sites fetched any URL without validation, so a claim could point at
cloud metadata (169.254.169.254) or an internal service.
`_is_safe_to_fetch()` resolves the hostname and rejects it unless every
resolved address is `ip.is_global`, failing closed if resolution fails,
before any network call. It is on by default.

Second pass:
1. The first version listed ranges to block and missed carrier-grade NAT
   (100.64.0.0/10). It now uses `not ip.is_global`: strict by default
   instead of listing what to block.
2. The first version checked only the original URL and then fetched with
   `follow_redirects=True`, which allowed SSRF through a redirect.
   `_safe_fetch()` now sets `follow_redirects=False` and re-checks
   `_is_safe_to_fetch()` on every redirect hop, up to 3.
3. There was no response-size cap. `_safe_fetch()` now streams and truncates
   at 5 MiB.

Seven tests cover these, including one that simulates a redirect to the
metadata endpoint and one that shows the size cap truncating.

Third pass:
1. A malformed `Location` header (for example `"http://[::1"`) made
   `httpx.URL.join()` raise `httpx.InvalidURL`, which on httpx 0.28.1 is not
   an `httpx.HTTPError` subclass. Neither caller caught it, giving a 500. It
   is now wrapped and converted to `_FetchRefused`.
2. When a page was truncated at the 5 MiB cap and the quote sat past the
   cut, "not found" became a confident `CONTRADICTS`. Mode 1 now returns
   `UNDETERMINED` through a `truncated` flag carried in
   `httpx.Response.extensions`. Mode 2 was never affected, since it never
   treats "not found in this chunk" as a contradiction.
3. httpx's `timeout=` bounds the gap between reads, not total time, so a
   slow-trickle server could hold a connection open. `_safe_fetch()` now
   wraps the whole multi-hop fetch in `asyncio.timeout()` and converts it to
   `httpx.ReadTimeout` (already an `HTTPError`), so neither caller needed a
   new except clause.

The file now has 27 tests.

**Known and accepted gap: DNS rebinding.** The hostname is resolved once for
the safety check and again by httpx to connect, so a rebinding attack could
answer differently between the two. Connecting directly to the validated IP
would fix it but is more invasive; the module docstring records it as an
accepted risk. Only local-fixture tests turn the guard off, with
`block_private_networks=False`.

**Test hermeticity (personal manual review, 2026-10-19).** Seven tests used
`https://example.com/...` as a stand-in safe-looking URL while testing
something else (block-page detection, redirect, size cap, `InvalidURL`,
timeout), but did not stub DNS, so each did a real lookup before reaching
its mock. DNS for "example.com" is now faked to a fixed, globally routable
address, so `ip.is_global` still runs. Stubbing the safety check itself
would have defeated the redirect test's check of its unsafe second hop. All
7 pass in under a second with real DNS resolution disabled.

**Tavily as the primary search backend (2026-10-24).** `_tavily_search()`
calls Tavily's `/search` API (`TAVILY_API_KEY` in `.env`), a keyed search
API built for LLM pipelines. DDG and Wikipedia are a fallback, tried only
when Tavily returns no URLs (missing key, a failure, or a query with no
results), so a clone without a Tavily key still gets some coverage.

It changed outcomes: the eval case "BlueROV2 has a maximum operating time of
14 hours" used to resolve `UNDETERMINED` (DDG blocked, no Wikipedia run-time
figure) and now resolves `CONTRADICTED`, because Tavily finds a Blue
Robotics distributor page (sepcotech.com) stating a run time of about 2 to
4 hours; see
`evals/cases/searchlight/live_multi_candidate_contradicted_via_tavily_distributor_page.json`.
A second case moved from "zero candidates" to "candidates found, fact
absent". Both cases' notes were rewritten so they no longer say both
backends return nothing. Five new offline tests cover `_tavily_search`'s
missing-key, success and non-200 paths and the fallback ordering.

### `llm/nebius_client.py`

**Base URL corrected.** It was `https://api.studio.nebius.ai/v1` (wrong
domain and TLD) and is now `https://api.tokenfactory.nebius.com/v1`,
confirmed by a `GET /v1/models` call (200, 28 models).

**Model set to `openai/gpt-oss-120b`**, based on a related project's Nebius
model-selection benchmark for an equivalent "extract structured values"
stage: 100% strict-JSON extraction, 100% JSON-valid, 100% overall on a 27x3
run, 0.95 s latency. The original guess,
`meta-llama/Meta-Llama-3.1-70B-Instruct`, is not in the live catalog. For
this account and endpoint, the model is in the catalog, a chat-completions
round trip works, and repeated `propose()` calls on this project's corpus
returned the correct `chunk_id` and verbatim `quote` every time (8/8, then
6/6 on a second document pair).

**Three bugs fixed:**
1. `python-dotenv` was a declared dependency but `load_dotenv()` was never
   called, so a `.env`-only setup (the README's documented flow) never
   loaded the key.
2. The first fix used `load_dotenv()`'s default `override=False`, which kept
   a stale exported shell value after `.env` was edited with a rotated key.
   It now uses `override=True`.
3. `retrieval/extract.py`'s prompt named `"kind": "rated" or "tested" or
   null` without explaining the values; see `domains/substrate.py` for the
   effect and how it was found.

**Nemotron in the request path.** The Apps and Agents track requires at
least one NVIDIA open model in the real request path. `domains/substrate.py`
requests `nvidia/Nemotron-3-Ultra-550b-a55b` (`SUBSTRATE_MODEL`, overriding
`NEBIUS_MODEL` and `.env`) for every live `propose()` call. `searchlight.py`
stays on `openai/gpt-oss-120b`. The choice came from comparing three
Nemotron tiers (Ultra, Super, Nano) and a one-pilot look at a fourth (3.5
Lightning), on both domains at two sample sizes. That comparison found and
fixed three pipeline bugs (no `max_tokens` cap, no quote-length guidance, no
entity-matching check in the stance prompt) before its results were trusted.
Methodology, pilot numbers and why `searchlight` stayed on the default:
[`stress_test/results/NEMOTRON_PIVOT_REPORT.md`](../stress_test/results/NEMOTRON_PIVOT_REPORT.md),
summarized in the README's "Models" section.

### `api/server.py`

Routes to the engine above. **Security fix (external review, 2026-10-19,
three passes).** `/verify` had no auth or rate limiting, although it is the
endpoint that spends Nebius budget. It now requires an `X-API-Key` header
checked with `secrets.compare_digest` on bytes. It fails closed: with no
`ANTICASSIOPEIA_API_KEY` configured, every request is rejected. There is an
in-memory token-bucket rate limit on `/verify` with no dependencies, plus a
separate, stricter failed-auth throttle. `/health` and `/domains` stay
open.

Second pass:
1. `secrets.compare_digest(str, str)` raises `TypeError` (a 500) for a
   non-ASCII header value. Both sides are now encoded to bytes first.
2. The main rate limit was keyed on `request.client.host`, which merges
   every caller behind a shared reverse-proxy IP into one bucket. It is now
   keyed on the validated API key. With only one key supported today, this
   is close to one global bucket; it pays off once several keys exist.
3. A separate token bucket keyed by client IP now throttles failed auth
   attempts (429), independent of the main limit.
4. `load_dotenv(override=True)` would let a stray `.env` outrank a
   platform-injected secret, so this file uses `override=False`.
   `nebius_client.py`'s `override=True` is unchanged, for a different
   dev-workflow reason in its own docstring. A `.dockerignore` was also
   added; the Dockerfile never copies `.env` anyway.

Third pass: the bucket dicts added one entry per distinct API key or client
IP forever, so cycling through many keys or spoofed IPs could exhaust
memory. A hard cap (`_MAX_TRACKED_BUCKETS`) and idle-first eviction
(`_BUCKET_IDLE_TTL_SECONDS`) are applied before a new entry is added. A test
with a monkeypatched tiny cap shows the dict stays bounded. 10 tests cover
all of this. Both bucket types are per-process state and are not shared
across uvicorn workers.

**Surfaces and UI (external review, item 26).** The project originally
shipped no dedicated UI. The Apps and Agents track asks for "an app or
agent you'd actually use", so the CLI (`scripts/demo.py`), the HTTP API and
use as another agent's tool-use step were treated as three surfaces over one
engine. A static frontend was added in v2 (below); the other three remain.

### `scripts/demo.py`, `Dockerfile`, CI, `evals/`

`scripts/demo.py` runs 6 claims across all 4 domains with no mocked output.
For the `Dockerfile`, `docker build --no-cache` succeeds, and the resulting
container's `/health`, `/domains` and a `POST /verify` round trip (`quant`,
a `confirmed` verdict with evidence) were checked against the running
container with the current code.

**Bug found while re-verifying (external review).** The in-build
`evals/run_evals.py` step had no way to receive `NEBIUS_API_KEY` or
`TAVILY_API_KEY` (`.env` is deliberately not copied into the image, so
secrets aren't baked into a layer). Every `substrate` case (always needs a
live LLM call) and every `searchlight` mode-2 case
(`live_multi_candidate_*`) resolved to the wrong verdict and failed the
build instead of skipping: 9 failures, confirmed by running it. It predated
the Nemotron and Tavily work, which made those calls load-bearing.
`run_evals.py`'s `_needs_live_key()` now skips any case that needs a live
key when `NEBIUS_API_KEY` isn't set, the same distinction the pytest suite's
`_requires_live_key` marker draws. `docker build --no-cache` now reports
`17 passed, 0 failed, 13 skipped (no NEBIUS_API_KEY), 30 total` and exits 0.

`.github/workflows/evals.yml` mirrors the local commands that were
verified (`pip install -e .` and `python evals/run_evals.py`). No CI run has
been observed.

`evals/` has 31 cases across all 4 domains, all passing with a live key
(`PYTHONPATH=. python evals/run_evals.py`), including live LLM and network
calls. Growth by pass: `quant` +3 (multi-file, compound confirmed, compound
one-part-false contradicted) and `silicon` +4 (real-format confirmed and
contradicted, two multi-corner cases, one register-map gap), both offline
and deterministic. A later session added `substrate` +1 (Bar100XT confirmed
and contradicted replacing the old undetermined case, net +1), `silicon` +1
(an SVD register-map confirmed case beside the existing gap case),
`searchlight` +1 net (one case reshaped, one new contradicted-via-Tavily
case), and `substrate` +1 (QuSpin QZFM Gen-3's confirmed no-rating finding,
previously described only in `docs/extracted/constellation-robotics-seed.md`
§4 and not covered by a test). Each adapter's section above says what
changed and why.

## Item 20: claim decomposition (external review, 2-hour round)

`anticassiopeia/core/compound.py` has three parts:
- `decompose_claim()`: one LLM call that splits "A and B" into independent
  parts, each classified `substrate`, `searchlight` or `unsupported`.
  `unsupported` covers anything that would need `quant` or `silicon`'s
  file-path context, which decomposition won't invent.
- `rollup()`: pure AND semantics. All parts `CONFIRMED` gives `CONFIRMED`
  at the minimum confidence among them (the AND is only as sure as its
  weakest part). Any part `CONTRADICTED` gives `CONTRADICTED` at the
  maximum confidence among the contradicting parts (one false part is
  enough). Anything else gives `UNDETERMINED`.
- `verify_compound()`: runs both through the unmodified
  `VerificationEngine` and its adapters. No engine or adapter code changed.

19 tests in `tests/test_compound.py` cover JSON-shape validation
(well-formed, code-fenced, malformed, missing or empty fields), `rollup()`
for every state combination including empty and all-unsupported, and
`verify_compound()` against a fake LLM client and a real
`VerificationEngine`: confirms-all, contradicts-on-one-part, a `quant`
sub-claim never invented, a single-part claim, and a failed decomposition
call resolving `UNDETERMINED` instead of crashing.

In this round there was no `/verify/compound` endpoint: `server.py` did not
import the module, so `verify_compound` was reachable as Python
(`from anticassiopeia.core.compound import verify_compound`) but not over
HTTP. The endpoint needed its own request schema, auth and rate-limit
wiring (a compound request costs more: one decomposition call plus N
sub-verifies, and the existing bucket sizes had not been evaluated against
that) and endpoint tests, so it was left for a later round. It shipped in
v3 §1.2 below. `docs/DESIGN.md` §2 has the original design reasoning.

## v2: bring your own evidence (upload, substrate BYOE, project verify, frontend)

Built in three phases (2026-10-25), each committed and CI-green before the
next. Per-phase detail is in the commit messages (`git log --grep "v2 Phase"`).

**Phase 1: `POST /upload` and `substrate.py`'s free-text BYOE path.**
- `anticassiopeia/retrieval/document_ingest.py`: `extract_text()` dispatches
  by format (`.txt`, `.md`, `.csv`, `.rpt`, `.svd`, `.xml` as UTF-8; `.pdf`
  via `pypdf`; `.docx` via `python-docx`). An unsupported extension or no
  extractable text (for example a scanned PDF) raises `DocumentIngestError`,
  never an empty string.
- `anticassiopeia/api/upload_store.py`: a thread-safe, capped, 24-hour-TTL
  in-memory `UploadStore`, keyed by an opaque `secrets.token_urlsafe`
  `document_id`.
- Both modules were present but untested going into this phase, and
  the dependencies were not declared (commit message: "WIP, stopped
  mid-Phase-1"). `pypdf`, `python-docx` and `python-multipart` were added to
  `pyproject.toml`, pinned to the versions tested. `python-docx` and
  `python-multipart` were missing from the environment entirely; without the
  latter, `/upload`'s form parsing would have failed at runtime.
- `anticassiopeia/retrieval/stance.py` was extracted from `searchlight.py`
  (a refactor with no behavior change, shown by the searchlight suite
  staying green) so `substrate.py`'s BYOE path and `searchlight.py`'s
  multi-candidate mode share one stance-judgment implementation.
- `substrate.py`'s `gather_evidence()`: when `Claim.context["document_text"]`
  is present (resolved from a `document_id` by `server.py`'s `/verify`
  handler, so `substrate.py` never imports the upload store), it takes over
  entirely: chunk, BM25, propose, re-verify, judge stance. This is the same
  shape as `searchlight.py`'s multi-candidate mode without the web search.
  It does not use the depth-specific regex and bar-conversion parser even
  when `depth_m` or `polarity` are in context, because an uploaded document
  can be about anything. With no `document_text`, behavior is identical to
  the pre-v2 fixed corpus (the 229-test baseline stayed green throughout).
- 49 new offline tests: `pypdf`-built PDFs and `python-docx`-built DOCX
  files (not mocks) for ingestion, `UploadStore` TTL and cap eviction, the
  BYOE path through a fake LLM client, and `/upload`'s auth, rate limit,
  size cap and extension allowlist plus `/verify`'s `document_id`
  resolution and expiry. Two live Nebius calls confirmed the pipeline in
  both directions (a true depth claim against an uploaded datasheet gave
  `CONFIRMED`, a false one `CONTRADICTED`).

**Phase 2: `POST /verify/project`.** A batch of claims, each optionally
tied to an earlier upload's `document_id`, routed to a domain by
`server.py`'s `_sniff_domain_for_document()`: extension first, with `.xml`
and `.rpt` cross-checked against content markers from `silicon.py`
(`_SVD_DEVICE_TAG_RE`, `_DESIGN_TIMING_SUMMARY_HEADER_RE`, imported and not
reimplemented). Code determines the format, never an LLM.

`quant.py` and `silicon.py` are unchanged. Rather than add a raw-text path
to their tested file-reading and line-locator code, `server.py` writes the
document's extracted text to a file in a fixed, server-owned scratch
directory (`var/project_scratch/`, gitignored), added to those two
adapters' `allowed_base_dirs` through `default_domains(extra_allowed_base_dirs=...)`
(default `None`, so no change for other callers). Each request uses its own
`tempfile.mkdtemp()` subdirectory, deleted in a `finally` block; a test
asserts the directory is empty after the call.

The endpoint invents nothing: the caller still supplies every structured
field `quant` and `silicon` need (column, stat and expected value, or
peripheral, metric, comparator and expected value); it only fills in which
file a `document_id` refers to. One claim's failure (a bad or expired
`document_id`, a domain that can't consume a document) is a per-claim
`error`, not a whole-batch failure. Verdicts are rolled up with the existing
`rollup()`; the endpoint never calls `decompose_claim()` (see Item 20 for why
`DECOMPOSABLE_DOMAINS` is not widened). It has its own rate-limit bucket,
stricter than `/verify`'s since one call can fan out into several live LLM
calls, and a cap of 20 claims per call. 18 new offline tests use CSV, SVD
and Vivado fixtures through the real `quant.py` and `silicon.py` against
real scratch files, and cover sniffing (including caller override),
per-claim versus batch error isolation, and scratch cleanup. One live
end-to-end run through the real app and Nebius API recomputed a CSV mean and
ran a Nemotron Ultra substrate BYOE check, and the two rolled up to
`CONFIRMED`.

**Phase 3: frontend rebuild.** `docs/index.html`'s theme was rewritten:
Inter sans-serif for the interface, monospace only for data, a near-black
navy background with two accents (lime for `CONFIRMED` and highlights, cyan
for primary actions). This replaced a single blue-violet terminal theme that
a screenshot comparison rejected. It gained a Documents upload card and a
Project-verify card (claim rows, each optionally tied to an uploaded
document) wired to the Phase 1 and 2 endpoints, with the same error
handling as the single-claim flow (a fixed message on 401, the server's
detail plus retry on 429, retry on network failure).

No browser tool was available, so verification used `node --check` on the
extracted script and two `jsdom` runs of the shipped file (real DOM and
events, a mocked `fetch()` returning the response shapes the backend tests
had proven), covering the success path (presets, single verify, project
verify, mixed success and error rows) and the error path (401, 429 with
retry, network failure with retry, a `missing[]` payload). That process also
found a gap that a CORS preflight's 200 had hidden: the live Cloud Run
deployment was still running the old `server.py`, so `/verify/project` was a
404 there (noted in the README's Frontend section at the time). Redeploying
is a billed action on the live GCP project that no CI step performs, and
the session had no `gcloud` CLI.

## v3: closing the v2 gaps and multi-document pooled search

Built in the order the v3 spec set, each step committed and
offline-suite-green before the next (`git log --grep "v3 §"`). §1.1, §2.1,
§2.2, §2.3, §2.4, §1.3, §2.5 and §1.2 all shipped. §1.2
(`POST /verify/compound`) was built last: it was the least requested, the
most expensive in live LLM calls, and the one that gained most from
everything else being stable.

**§1.1: plain `/verify` no longer silently ignores `quant` and `silicon`
uploads.** `_resolve_document_context()` only injected
`document_text` and `document_filename`, which neither `quant.py` nor
`silicon.py` reads. Uploading a CSV and calling `/verify` with
`domain=quant` and its `document_id` therefore ignored the upload: an
`UNDETERMINED` gap, never a wrong confident answer, but the document picker
did nothing for 2 of the 4 domains. The function now takes a `domain`
parameter and branches three ways: `substrate` injects text directly;
`quant` and `silicon` write a scratch file under the same
`_PROJECT_SCRATCH_DIR` that `/verify/project` uses (now shared); anything
else, notably `searchlight`, returns a named 400. A single `/verify` call
writes and deletes its own file in a `finally` block around
`engine.verify()`, unlike the batch endpoint's per-request subdirectory. 6
new offline tests, including one showing cleanup happens when the claim
resolves to a gap.

**§2.1: ownership in `UploadStore`.** Pooled search needs an owner concept.
Without one, "search across my documents" would search every caller's
documents, which matters once callers share a server (the public demo key
already does). `StoredDocument` gained a frozen `owner_key_hash: str` (a
SHA-256 hash of the uploading API key, never the raw key); `put()` takes it
as a new required parameter, and `list_for_owner()` returns one owner's
valid uploads, most recent first. `get()` by `document_id` is unchanged, so
single-document flows (`substrate` BYOE, `/verify/project`'s per-claim
`document_id`) work as before whoever uploaded the document. Limitation
stated in the module docstring: under the shared demo key, "your pool"
means every demo-key visitor's uploads. A caller's own key gets real
isolation. 5 new tests: key A's list never contains key B's documents,
expired documents are excluded, and direct `get()` is unaffected.

**§2.2: `GET /documents`.** Lists the calling key's valid uploads: id,
filename, size_bytes and `seconds_until_expiry`. It returns the derived
expiry instead of `uploaded_at` because `StoredDocument.uploaded_at` is
`time.monotonic()`-based and meaningless as a raw value. It shares
`/verify`'s rate-limit bucket instead of getting its own, since it is an
in-memory scan with no disk I/O or live LLM calls. 6 new tests, including
one showing the shared budget (hammering `/documents` trips the `/verify`
limit).

**§2.3: multi-document pooled search.** New `context.document_pool = true`,
exclusive with `document_id` and `substrate` only (`quant` and `silicon`
need one exact structured file per claim, and "which of several CSVs has
this column" is a different problem; `searchlight` has no document mode).
`server.py` resolves the pool with `upload_store.list_for_owner()`, caps it
at `_MAX_POOL_DOCUMENTS` (10, most recent), and gives `substrate.py` the
resolved `(filename, text)` pairs plus the true available count in two
context fields. `substrate.py` still never imports `UploadStore`.

`_gather_byoe_pool()` builds one combined BM25 index across every pooled
document's chunks, namespaced by pool index (`doc0`, `doc1`, ...) and not
by filename, because two of a caller's uploads can share a filename (such
as two files named `spec.txt`) and a shared prefix would collide in the
combined `chunks_by_id` dict. A `doc_tag -> filename` map keeps
`Evidence.source` naming the real originating document. It still makes one
`propose()` call and one `judge_stance()` call per claim, as in
single-document BYOE; only the local BM25 corpus grows. When a caller has
more uploads than the cap, the truncation is named in the verdict's
`reasoning` every time, even on a confirmed claim, through the existing
`describe_partial_gaps()` mechanism. 11 new adapter tests (the
filename-disambiguation case, truncation always named, and the ODrive
heading entity-ambiguity fix from the v2 stress test, reapplied because
pooled search has the same risk) plus 6 server tests showing ownership
scoping holds over HTTP.

**§2.4: `/verify/project` accepts `document_pool`.** A `ProjectClaimRequest`
entry can set `document_pool: true` instead of `document_id`, using the
same resolution as §2.3, so one batch can mix claims pinned to a document
with claims that search the whole pool. One deviation from the spec's
wording: a `document_id` plus `document_pool` conflict on a claim inside a
batch is a per-claim error, not the whole-request 400 that plain `/verify`
returns. Plain `/verify` has one claim, so the two coincide there, but the
batch's own rule ("one bad claim must not abort every other claim",
`_run_one_project_claim`'s docstring since v2) applies to a multi-claim
call. An omitted `domain` on a pool claim defaults to `"substrate"`, since
there is no document to sniff a domain from and pooled search is
`substrate`-only. 6 new tests, including one batch that mixes a
`document_id`-pinned `quant` claim with a `document_pool` `substrate` claim.

**§1.3: multi-instance deployment caveat (docs only).** The README's
"Run it" section states that rate-limit buckets, `UploadStore` and
pooled-search ownership lookups are per-process, and recommends
`gcloud run deploy --max-instances=1`. The failure mode is a document
uploaded to instance A and referenced from a call routed to instance B,
giving a false "unknown or expired" or an emptier pool than exists. A shared
store (Redis, Firestore) stays out of scope. Pooled search adds a second
symptom (an incomplete-looking pool) to v2's falsely expired `document_id`.

**§2.5: frontend three-way document choice.** The single-claim document
dropdown and each project claim row's dropdown gained a third option,
"🔍 Search all uploaded documents (substrate only)", beside "none" and "one
specific document". It sends `context.document_pool = true` instead of
`document_id`, driven by a sentinel `<select>` value (`__search_all__`,
distinct from real `document_id`s, which are 32-byte
`secrets.token_urlsafe` strings) in `runVerification()` and
`runProjectVerification()`. The evidence card needed no change, since it
already renders `Evidence.source`, which `_gather_byoe_pool()` sets to the
real filename. Verified with `node --check` and a `jsdom` run of the
shipped file (mocked `fetch()`) showing both panels send `document_pool: true`
with no `document_id`, the same standard as v2's rebuild.

**§1.2: `POST /verify/compound`.** Makes `core/compound.py`'s
`decompose_claim()` and `rollup()` reachable over HTTP. It calls them
directly against the module-level `engine` instead of `verify_compound()`,
because `verify_compound()` has no cap on sub-claims, and verifying every
part before checking a cap would spend the live calls the cap exists to
limit. The cap (`_MAX_SUBCLAIMS = 8`, a `422` above it, never silent
truncation) is checked between decompose and verify.

`CompoundVerifyRequest` has no `domain` field: `decompose_claim()` classifies
each sub-claim itself, so a top-level domain would always be ignored, and
the project's convention is to not accept fields that are ignored. A request
whose `context` contains `document_id` or `document_pool` returns 400. The
spec named only `document_id`; `document_pool` is rejected for the same
reason, since an LLM-invented sub-claim can't know which uploaded document
or pool it corresponds to. The endpoint has its own rate-limit bucket,
stricter than `/verify/project`'s (one call every 20 seconds, burst of 2),
given the larger fan-out. Its LLM client (`_compound_client`) is built at
import time; `NebiusTokenFactoryClient()` only reads env vars, so a missing
`NEBIUS_API_KEY` gives a clean `503` on the call instead of an import crash,
the same pattern as `substrate.py`'s `__init__`. 11 new offline tests use a
fake decompose client and fixed-evidence fake adapters, including one that
shows the cap is checked before verification (a capturing adapter asserts
zero calls when decomposition exceeds the cap).

## Post-v3: opt-in per-verdict summary and the "three C's" display rename

Two small additions requested by the project owner after v3 shipped. Both
were confirmed with the owner before implementation.

**Display rename only, no wire-format change.** The owner asked why the
third state doesn't also start with C, to match CONFIRMED and CONTRADICTED.
The `VerdictState.UNDETERMINED` enum value and the API wire value stay
`"undetermined"`: the Cloud Run demo depends on them, and the full
breaking-rename alternative was offered and declined. `docs/index.html`
gained `displayStateLabel()`, which maps `"undetermined"` to `"clouded"` for
display text only. CSS classes (`.state-badge.undetermined`,
`.verdict-card.undetermined`) stay keyed on the real state string, so styling
needed no change. A `jsdom` run of the shipped file confirmed the badge's
CSS class is still `undetermined` and its visible text is `clouded`.

**Opt-in summary (`context.include_summary=true`).** The owner asked for a
short generated summary after a verify call. An always-on summary would add
a new live LLM call to `quant` and `silicon`, which make zero live calls
today, and the project tracks LLM spend against a $20 cap. The scope
agreed: opt-in through a context flag, off by default everywhere, and
uniform across all four domains when requested (the caller accepts that
call's cost).

A new `_summary_client` (built at import time without crashing, like
`_compound_client`) and `_generate_summary()` run in `/verify`'s handler
after the verdict is fully computed. A summary failure (client unavailable,
a failed call) is caught and reported as a separate `summary_error` field
and never affects the verdict. The system prompt tells the model the summary
is commentary on a decision already made: it must not introduce a fact,
number or claim absent from the evidence and reasoning it is given, and must
not soften or contradict the state. 5 new offline tests (a monkeypatched
fake summary client) cover: absent by default, present when opted in, a
generation failure never failing the verdict, an unavailable client giving a
named error, and `quant` (otherwise LLM-free) getting a summary when asked.

## Causal-claim stance fix + judge_stance() model routing (found live, 2026-10-25)

The project owner found this by testing the live `/verify/compound`
endpoint with an obscure historical claim from their own research area
(quantum key distribution), not through the test suite.

**The bug.** "The BB84 protocol was built on Stephen Wiesner's earlier
concept of quantum conjugate coding" was `CONFIRMED` on a passage that only
says "In 1984, the two combined quantum conjugate coding with a
cryptographic key-exchange scheme, producing ... BB84". That is consistent
with a causal relationship but does not assert one. `judge_stance()` had no
notion of evidence strength for causal or dependency claims. For a plain
factual claim, "the passage states the fact" and "the passage supports the
claim" are the same thing; for a causal claim they are not.

**The fix.** One paragraph added to `retrieval/stance.py`'s
`STANCE_SYSTEM_PROMPT`, after the existing ESP32 / ESP32-S31
entity-matching caution. For a causal or dependency claim, the model must
check whether the passage states the relationship or only mentions both
things in a way consistent with it. There is no new return value and no
claim-type classifier in code, following the same "ask the model, don't
pre-filter with a keyword list" reasoning as the entity-matching fix. 11 new
offline tests in `tests/test_retrieval_stance.py` cover `judge_stance()`'s
parsing contract, both fix paragraphs' text (locked against accidental
removal), and the Wiesner/BB84 shape through a fake client.

**Model routing.** Asking Nemotron Ultra directly (outside the pipeline)
got the Wiesner/BB84 distinction right. A paired live test (same prompt,
same claim and passage) found `gpt-oss-120b` (`searchlight`'s default)
returned "supports", which is wrong, and Nemotron Ultra returned
"unrelated", which is correct. By the `NEMOTRON_PIVOT_REPORT.md` standard
(n=1 is not a conclusion), this was escalated before any code changed:
- A balanced 5-pair live sample (3 pairs that should be "unrelated" because
  they are co-occurrence only, including Wiesner/BB84, and 2 that should be
  "supports" because they assert explicitly, across different relation
  verbs): both models scored 5/5. Balance matters because a model that
  answers "unrelated" to everything would win a skewed sample without being
  more correct, the failure `NEMOTRON_PIVOT_REPORT.md` documented for the
  Nemotron Lightning tier ("extremely safe but extremely unhelpful").
- The balanced sample didn't explain the one disagreement, so the
  Wiesner/BB84 pair was repeated 4 more times per model. Result:
  `gpt-oss-120b` correct 2/6 times on this borderline pair, Nemotron Ultra
  correct 5/5 times. The gap is specific to borderline causal or relational
  judgments; both models tied on every easier pair.
- **Decision.** `searchlight.py`'s `judge_stance()` calls route to a
  separate client on `RECOMMENDED_STANCE_MODEL`
  (`nvidia/Nemotron-3-Ultra-550b-a55b`, defined in `retrieval/stance.py`).
  `propose()` and the live-search step stay on `gpt-oss-120b`, which
  `NEMOTRON_PIVOT_REPORT.md` found better at full-pipeline scale and nothing
  here contradicts. `SearchlightAdapter.__init__` gained a `stance_client`
  parameter that defaults to the same object as `client` when a caller
  injects one, so every existing test with a single fake client works
  unchanged; only `default_domains()`'s no-argument construction gets two
  different real clients. `substrate.py`'s `SUBSTRATE_MODEL` happens to equal
  `RECOMMENDED_STANCE_MODEL` for its own, older reasons and is not imported
  from there, to keep two adapters' model choices independent. 6 new offline
  tests in `tests/test_searchlight_stance_routing.py`: two different real
  clients when nothing is injected, a single injected fake handling both
  prompt shapes, two injected fakes routed correctly, and a broken stance
  client giving a named per-source gap that doesn't block `propose()`.

**Note from the live end-to-end re-test.** Re-running the sub-claim through
the full engine (live search) found a different source, Wikipedia's
"Timeline of cryptography", which states "Based on Stephen Wiesner's idea
... Bennett and Brassard design ... BB84." That is an explicit causal
assertion, so `CONFIRMED` on that passage is correct and not a regression;
live search varies run to run. It also shows that reliable sources disagree
on whether BB84 was "based on" Wiesner's work or an independent
rediscovery later credited to him (Wikipedia's timeline asserts the former;
Brassard's retrospectives lean toward the latter). The claim's ground truth
is contested, so this fix isn't expected to settle it. It is the kind of case
category 1 of the competitive-benchmark protocol probes at scale.

## Hybrid retrieval (BM25 + vector), ported from Constellation

Built in response to competitive-benchmark round 1: 3 conservative misses
and one weak conspiracy verdict, all traced to BM25 finding nothing when a
claim is worded differently from its best source. BM25 cannot close that gap
by tuning.

**Ported from the sibling project.** `retrieval/hybrid.py`'s `HybridIndex`,
`VectorIndex` and `rrf_fuse()` port `eclipse-constellation`'s
`HybridRetriever` and `VectorIndex` (RRF with k=60, the standard constant,
not re-tuned). `NebiusTokenFactoryClient.embed()` uses the same
`Qwen/Qwen3-Embedding-8B` model and OpenAI-compatible `/embeddings` shape
that Constellation's client uses on this provider, confirmed against this
account's own `GET /v1/models`.

**Two integration points with different shapes.** `substrate.py`'s BYOE and
pooled paths build a `HybridIndex` over the uploaded documents' chunks
(close to a direct `HybridRetriever` port). `searchlight.py`'s
multi-candidate path embeds the query and that claim's freshly fetched
passages, RRF-fuses against the BM25 ranking over them, then discards the
result. There is no persistent index because there is no persistent corpus.

**Degradation at index time and query time, independently.** `embed()`
catches `NebiusClientError` (a live failure) and `AttributeError` /
`TypeError` (a client without `embed()`, which describes every existing
offline test fake). In either case `HybridSearchResult.methods` records
which methods ran, and a vector-less result is the same ranking
`BM25Index.search()` produced before this build. New offline tests (20 + 14 + 4 + 3 = 41) across
`test_llm_nebius_client.py` (`embed()`'s contract), `test_retrieval_hybrid.py`
(RRF fusion, `VectorIndex`, degradation at index and query time, the `mode=`
eval-only isolation parameter), and `test_hybrid_retrieval_integration.py`
(each adapter's wiring calls `embed()`, not only that degradation works).

**New limitation.** There is no persistent embedding, chunk or BM25 index
cache anywhere (see `retrieval/__init__.py`'s docstring). Each hybrid search
re-chunks and re-embeds its source text, as BM25 already re-chunked and
re-indexed on every call. Querying the same uploaded document twice
embeds it twice, at added cost and latency. A per-document cache keyed on
`UploadStore`'s `document_id` would fix this; it is a separate architecture
decision for a later round.

**Eval numbers** (`evals/retrieval/`: 13 hand-labelled questions across 6
documents, live `Qwen/Qwen3-Embedding-8B`; full table and reading in
`evals/retrieval/RESULTS.md`). On questions paraphrased away from their
source wording, vector search alone has the best R@1 (0.50 against BM25's
0.36). Fused hybrid's R@1 on the same questions is worse than either method
alone (0.21), reported as measured and not tuned away on an N=7 sample. At
R@3 and hit@3, the metric that matches how the pipeline uses retrieval (a
top-k list shown to `propose()`, never blind trust of rank 1), hybrid and
vector both beat BM25 on paraphrased questions (0.86 against 0.79) and tie
it on keyword-overlap questions (0.83 for all three). So hybrid does not
lower recall at the metric that matters and improves it for paraphrased
claims. The sample is too small to support a general claim that hybrid beats
BM25.

**Live re-test of round 1's failing claims** (§4.3 of the build spec)
against `SearchlightAdapter` with hybrid retrieval: 3 of 4 are fixed.
- The ARPANET "LOGIN" claim is now `CONFIRMED` (1.0 confidence, 2 sources).
- The moon-landing conspiracy claim is now `CONTRADICTED` (0.90) on
  Wikipedia's moon-landing-conspiracy-theories page ("regarded as
  pseudoscience and demonstrably false"), replacing round 1's weak
  fictional-movie-quote evidence.
- The sunglasses and cancer fact-check claim is now `CONTRADICTED` (1.0
  confidence, 3 Full Fact sources).
- The SpaceX viral-video claim is still `UNDETERMINED`. Retrieval improved:
  it finds 4 relevant sources (EarthSky, Wikipedia's "2026 SpaceX lunar
  impact" page, BBC) where round 1 found none. Those sources cover the
  lunar-impact event, not the claim's point about one video being fake, a
  subtler gap that this build does not claim to fix.

## The Tavily/load_dotenv bug: a measurement bug, not a product bug

Found on 2026-10-25 while investigating whether Tavily, Nemotron and this
project's verification could beat Perplexity head to head.
`searchlight.py`'s `_tavily_search()` is the primary search backend in
production and reads its key with `os.environ.get("TAVILY_API_KEY")`.
Every script in `stress_test/` (`run_test1.py`, `run_test2.py`, every
`run_test3_*.py`, `run_nemotron_pivot.py`, and round 1's runner) read its own
provider keys (Perplexity, Tavily, Gemini) with `dotenv_values(".env")`,
which reads the file into a dict without touching the process environment,
and none called `load_dotenv()`. So `TAVILY_API_KEY` was never set in those
processes, and `_tavily_search()`'s documented contract (return `[]` when
the key is unset) fired silently in every stress-test run that exercised
`searchlight.py`'s pipeline. Each such run fell back to DDG and Wikipedia.
The production server was not affected: `api/server.py` calls
`load_dotenv(override=False)` at import time. Only the project's
measurement of it was weakened.

**Fixed** in all 11 affected scripts. **Confirmed:** calling Tavily with the
text of 3 claims that failed in round 1 returned directly relevant results
for all three (including the Full Fact article, by URL, for the sunglasses
claim), and re-running them through the engine resolved them. The hybrid
retrieval build, using a different mechanism (better ranking, not search
availability), re-tested the same 4 claims and also fixed 3 of 4. Details,
including the claim that stayed unresolved and two that got worse on re-run
from live-search variance (not a regression from this fix), are in the
erratum in
[`stress_test/results/BENCHMARK_ROUND1_REPORT.md`](../stress_test/results/BENCHMARK_ROUND1_REPORT.md).
Which model-choice decisions need re-measuring now that Tavily works:
[`stress_test/results/MODEL_SELECTION_FINDINGS.md`](../stress_test/results/MODEL_SELECTION_FINDINGS.md).

## Adaptive-depth evidence gathering ("the optimiser")

Requested by the project owner: a cheap claim should resolve fast, an
ambiguous one should get more scrutiny, and either way the output must be
exactly one of the three states. The design is fixed: there is no upfront
call to classify a claim's type, which the project already rejected (the
causal-claim fix's docstring explains why). The escalation trigger is the
evidence a first cheap pass produces, never a guess made before searching.

`searchlight.py`'s `_gather_multi_candidate` does two things, both reusing
`core/engine.py`'s scoring conditions directly instead of copies that could
drift:
- **Fast path.** It stops checking candidate sources once two independent
  sources agree on a stance. One easy claim (Dead Sea Scrolls) needed 2
  `propose()` calls instead of the earlier unconditional 3.
- **Escalation path.** If the first pass's evidence is empty or tied
  (`abs(support - contradict) < DECISION_THRESHOLD`, the same condition
  `engine.py` uses, imported directly), it checks more sources with a
  second, differently phrased search.

Both paths produce ordinary `Evidence` that goes through the unchanged
`VerificationEngine` scoring. There is no new state and no bypass, and the
most important test in the build asserts that `verdict.state` is always a
`VerdictState` member on both paths.

**Limitation.** The escalation path's reworded second search does not always
surface different candidate URLs: in a repeated test it sometimes returned
the same or overlapping results as the plain claim text. The mechanism
reacts to ambiguity every time, but the second search doesn't always help.

## The domain rename: robotics / research_web / ml_data / fpga_embedded to substrate / searchlight / quant / silicon

A full, breaking rename, including `Claim.domain`'s wire value, confirmed
with the project owner first because anyone polling the live demo with the
old names gets errors after redeploy. Each old name was only the current
example of a broader category (robotics is one example of a physical
hardware and datasheet domain, and likewise for the others), so the new
names describe the category. No adapter's behavior changed.

Scope: the product (`anticassiopeia/`), its tests, `docs/`, `evals/` and
`scripts/demo.py` are renamed and were smoke-tested (`GET /domains` returns
the 4 new names, `POST /verify` with them routes correctly, and the old
names return a clean 400). Not renamed: `docs/extracted/constellation-robotics-seed.md`
and all of `stress_test/` (scripts, claim manifests, reports), which are
records of a point in time.

Backward-compatibility shim modules remain at the four old import paths
because `stress_test/`'s scripts import them directly. One accepted
limitation follows: `run_test3_nebius_agent.py`'s monkeypatch (used to
simulate "skip independent verification" for a baseline) now silently does
nothing, because it patches the shim's namespace and not the renamed module
the adapters use. This is recorded in the shim's docstring and in
`stress_test/results/INDEX.md`. Fixing it means editing `stress_test/`,
which was out of scope for the rename.

## Competitive benchmark round 2: 102 externally generated claims, independently verified

Round 2 scaled round 1 up 11x and changed the claim source. Instead of 9
hand-picked claims, 102 were generated by three external AI tools (ChatGPT,
Gemini, and Perplexity by direct API call, because its UI doesn't support
file uploads) from a locked prompt, then verified independently against
primary and secondary sources before any was used for scoring. The
generating AI's own `suggested_ground_truth` is never used, only
`verified_ground_truth`. From 185 raw claims, 14 true duplicates were
removed (several more candidate pairs were read in full and judged not
duplicates: same vocabulary, different assertions). 102 web-verifiable
claims were kept. A block of 69 category-8 formal control-theory and FPGA
claims was parked (they are closed-form mathematical truths, not
web-searchable facts, and need `substrate`'s adaptive-depth search, which
wasn't ported). Of the 102, 100 generator-suggested verdicts held up and 2
were corrected: a Hesiod *Theogony* claim that bundled a secure textual
detail with one from a disputed spurious line, and a Voynich Manuscript
claim that bundled a solid radiocarbon result with a weaker, separately
sourced origin claim. Dataset and method: `stress_test/claims/external_generated/`.

All 102 ran through the engine and all 5 competitor variants, with no
category exemption (unlike round 1; see `BENCHMARK_ROUND2_REPORT.md`). The
14 calibration probes were all correct with zero overreach across 7
traditions, so the round 1 stance fix holds at 7x the sample on 6 traditions
it was not tuned on. Generic RAG's round 1 calibration "win" (blanket
caution) reversed, confirming 9 of 14 supernatural claims. After the
ground-truth correction in Erratum 3 of the round 2 report, Anti-Cassiopeia's
raw accuracy was 71.6% (lowest of the six systems), with 2 dangerous misses
out of 88 scored claims against 4 to 8 for every competitor, and the rest
conservative. One gap: round 2's script did not save full per-claim
evidence, so one dangerous miss that did not reproduce on replay could not
be root-caused afterwards, a live-search non-determinism gap noted for a
future round's script.

**Found and fixed from this round's data.** `run_test3_tavily_gemini.py`'s
circuit breaker was built for a permanent per-day Gemini quota cap and could
not tell it from an ordinary per-minute rate limit, which round 2 hit around
claim 18 of 102. The breaker tripped and skipped 84 claims instead of
backing off about 49 seconds. It now parses the error body's `retryDelay`
and treats only a short (under 90 s), explicit delay as retriable; the
original permanent-cap behavior is unchanged. The affected variant was
re-run separately (`stress_test/rerun_round2_tavily_gemini.py`), since
nothing else in round 2 was affected.

## Open design decisions

- Evidence retrieval inside each domain adapter: web search, a local
  datasheet index, or direct API calls (synthesis tool output, dataset
  files). Each domain likely needs a different answer.
- Scoring: the trust-weighted threshold rule in `engine.py` is a
  placeholder, not a researched method. Revisit it once evidence from more
  than one real domain flows through it.
