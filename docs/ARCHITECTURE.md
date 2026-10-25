# Architecture

## The mechanism, in one sentence

Take a narrow, checkable `Claim`, route it to the one `DomainAdapter` that
knows how to gather real `Evidence` for it, and let one shared, centralized
scoring rule in `VerificationEngine` decide the `Verdict` — `CONFIRMED`,
`CONTRADICTED`, or `UNDETERMINED` — never anything smoother than that.

```
Claim ──▶ VerificationEngine.verify()
              │
              ▼
        DomainAdapter.gather_evidence(claim)   (robotics | fpga_embedded | research_web | ml_data)
              │
              ▼
        list[Evidence]  (source, snippet, stance, trust, locator)
              │
              ▼
        VerificationEngine._score()  ──▶  Verdict (state, confidence, reasoning, missing)
```

## Why the domain split

Four domains, one contract. Each domain's adapter is the only place that
knows what "evidence" even means for that domain — a datasheet locator for
robotics, a timing report for FPGA/embedded, a fetched source for
web/research, a re-run computation for ML/data. None of that
domain-specific knowledge leaks into the engine. The engine only ever sees
`Evidence` objects with a `stance` and a `trust` weight already assigned —
it doesn't know or care what a "datasheet" is.

This is what makes the engine genuinely reusable as infrastructure: a
fifth domain is a new `DomainAdapter` subclass, not a fork of the engine.

## Why three states, not a probability

A single confidence score invites exactly the failure mode the project is
named against — a fabricated-but-fluent answer wearing a number that makes
it look measured. Three discrete states, with `UNDETERMINED` as a first-
class, frequently-correct answer (not a fallback for engine bugs), forces
every integration built on top of this to actually handle "I don't know"
rather than silently rounding it up to a guess.

`Verdict.missing` exists so `UNDETERMINED` is never a dead end — it names,
concretely, what evidence would resolve the claim, the same way a domain
adapter should (see each adapter's `describe_gap()`).

**Display-only rename (v3):** the frontend shows `UNDETERMINED` as
**CLOUDED** instead — purely cosmetic, so the three displayed states all
start with C, matching this project's own name. The real
`VerdictState.UNDETERMINED` enum value and the API's wire value
(`"state": "undetermined"`) are UNCHANGED — this is a stable contract
already live on the public demo, and breaking it just for branding would
be exactly the kind of unstated, surprising change this project's own
conventions exist to prevent. `docs/index.html`'s `displayStateLabel()`
is the one place this translation happens; every other reference to
`"undetermined"` in this codebase (the enum, every domain adapter, every
test, CSS class names) is deliberately untouched.

## Current status (bone framework)

| Piece | Status |
|---|---|
| `core/verdict.py` | done |
| `core/domain.py` | done |
| `core/engine.py` | done — simple scoring, now redundancy-aware and confidence-capped |
| `domains/robotics.py` | real, live-verified · 3/4 parts sourced, 4th confirmed-unratable · runs on Nemotron Ultra |
| `domains/ml_data.py` | real, offline, tested · known gaps disclosed below |
| `domains/fpga_embedded.py` | real, offline, tested · timing-summary + real SVD register-map |
| `domains/research_web.py` | real, two modes · Tavily primary search, DDG+Wikipedia fallback |
| `llm/nebius_client.py` | live-verified Nebius Token Factory client |
| `api/server.py` | done — auth + rate-limited |
| `scripts/demo.py` | real end-to-end demo, 6 claims, all 4 domains |
| `Dockerfile` | build-tested for real |
| `.github/workflows/evals.yml` | written; CI run itself not observed |
| `evals/` | 31 cases, all 4 domains, all passing (13 skip cleanly without a live key — see detail below) |

(Rewritten to short cells after an external review noted the table was
unreadable at a skim — paragraph-length history per cell. Nothing above
claims to be more finished than this table says; the full history behind
each status, not shortened or dropped, moved to the per-piece sections
below.)

### `core/engine.py` detail

Deliberately simple trust-weighted sum against a fixed threshold
(`DECISION_THRESHOLD`) — a bone, not a finished spine; see
docs/DESIGN.md §3. Handles `contested` evidence (excluded from scoring,
surfaced in reasoning). **Four fixes from an external review of this
exact scoring rule:** (1) confidence reached a full 1.00 off a SINGLE
piece of evidence regardless of that source's own `trust` value —
`SINGLE_SOURCE_CONFIDENCE_CAP` now caps confidence below full certainty
when only one source contributes; two or more independent sources are
unaffected (genuine corroboration still reaches 1.00). (2) two
near-identical pieces of evidence from the SAME source used to sum like
two independent confirmations — `_redundancy_collapsed_weight()` now
takes the single highest-trust piece per source before summing across
distinct sources. (3) a source that returned an unusable (not
`None`) answer used to vanish with no trace once another source alone
was enough for a confident verdict — `DomainAdapter.describe_partial_gaps()`
is now called unconditionally and appended to `Verdict.reasoning`
regardless of final confidence (see `domains/robotics.py` for the first
real override).

**Item 19, time-decay (external review) — PARTIALLY implemented, not
faked.** `Evidence.timestamp: datetime | None` plus `engine.py`'s
`_decayed_trust()`/`_decay_all()` decay a piece of evidence's trust by
its real age once it carries a real date, with a floor
(`MIN_DECAY_FACTOR = 0.7`) chosen specifically so decay can never flip an
existing single-source verdict from CONFIRMED/CONTRADICTED to
UNDETERMINED purely from age (every current adapter's single-source
trust is 0.9; `0.9 * 0.7 = 0.63 >= DECISION_THRESHOLD = 0.5`) — checked
directly by `tests/test_engine.py::test_min_decay_factor_can_never_flip_an_existing_single_source_verdict`,
and separately by re-running all 385 `fpga_embedded` claims in the full
3,383-claim stress-test manifest against their recorded ground truth
with decay now live: zero verdict flips. Wired into exactly ONE domain:
`fpga_embedded.py`'s Vivado-report path, via a real, reliably-extractable
`| Date : ...` header line present in all 9 real committed Vivado
reports (absent from the two pre-existing synthetic fixtures, which
correctly never decay; a third, newly-added synthetic fixture,
`evals/fixtures/vivado_timing_report_dated_2016.rpt`, deliberately adds
a date line specifically to exercise this mechanism in tests). NOT wired
into: the SVD register path (CMSIS-SVD has no comparable real date
field), `ml_data.py` (a re-computed statistic is always fresh at verify
time — there is nothing to decay), or `robotics.py`/`research_web.py`
(no real, trustworthy per-evidence date source identified for either in
this round) — left open and stated as such, not guessed at.

### `domains/robotics.py` detail

**Real retrieve + propose + verify, end to end, LIVE ROUND TRIP
CONFIRMED** — chunking, BM25, a real `extract.propose()` call against
`NebiusTokenFactoryClient`, and `verify_proposal()` all run for real over
a partial corpus of Constellation-sourced excerpts; nothing hand-authored
stands in for the model's answer anymore. Verified two ways: offline
against a scripted fake client (17 tests) that reproduces the real
`propose()`→`verify_proposal()` code path without a network call, AND
against the genuine live API — both `test_live_*` tests in
`tests/test_domains_robotics.py` PASS for real (confirmed evidence
accepted for a corpus fact; honest "not found" for a fact genuinely
absent from the shown passages, not a hallucination).

**Earlier non-determinism (found, diagnosed, fixed, not papered over):**
an early live run showed the structured `kind` field ("rated"/"tested"/
null) coming back inconsistent across repeated identical calls (~4/8).
Root cause was `retrieval/extract.py`'s prompt, not the model: it named
the three allowed values with no explanation of what they mean, so a
model correctly refused to assert a classification it was never told how
to make. Fixed by naming the distinction in the prompt itself —
re-verified at 8/8 and 6/6 across two different models. `kind == "rated"`
was never loosened to force this green. Stance is **derived per claim**
(depth + survives/fails polarity from `Claim.context` or a narrow text
grammar; spec re-parsed from the verified quote; bar→depth conversion
with a 5% too-close-to-call margin). Bar100XT/QuSpin return an honest
gap, both unsourced in Constellation itself.

**Two more bugs found (by `stress_test/` Test #1, 2026-10-18) and fixed —
see `stress_test/BUGS_FOUND.md` for full detail:** (1) a genuine-absence
"not found" from `propose()` was accepted on the first try with no
retry, so a transient/ambiguous miss could read as a real evidence gap;
`_propose_with_retry()` now retries up to 3 attempts total but only on an
actual `None` return, never on a real (even low-confidence) proposal —
re-verified live, 30/30 reruns of the previously-dangerous "BlueROV2
survives 200 m depth" claim resolve UNDETERMINED. (2) the dominant cause,
found only after that first fix still failed a live rerun:
`_RETRIEVAL_QUERIES["bluerov2"]["DOC1_BlueROV2"]` asked about "aluminum
acrylic housing" at once, and DOC1 genuinely contains two different
rated-depth lines (Acrylic: 100 m, Aluminum: 300 m) that a live model
picked between near-randomly (~40% wrong-line rate over 20 trials) —
retrying does not fix a wrong-but-real answer. Fixed by dropping
"acrylic" from the query to disambiguate; re-verified live, 25/25 reruns
retrieve the Aluminum/300 m line every time.

**Phase B addendum (personal manual review, 2026-10-19): a real,
live-caught fabrication, not just a scripted one.** Every prior
"fabricated quote/value is rejected" test used a scripted fake client
told to lie — proving the logic works, never that a real model has ever
actually tried it. Found a live, reproducible case: asking `propose()` an
adversarial unit-conversion question against DOC1's real (meters-only)
text makes the model sometimes attach a `value`/`unit` (e.g. 984.25 ft)
that its own verbatim quote (300 m) does not state — confirmed at ~7.5%
across two independent 20-sample live batches. `_spec_depth_m()`
discards every one observed; proven by a new test,
`test_live_adversarial_unit_conversion_fabrication_is_caught_not_trusted`
(50 live samples, skips rather than fails if a given run observes zero —
this is probabilistic live behavior, not a deterministic contract).

**Fourth-round fixes (external review — fails-open bug, and rated-vs-
survives conflation):** (1) a source that returned something (an
incomplete, ambiguous, or verification-rejected answer, not a clean
`None`) used to `continue` with no trace at all — once another source
alone was enough for a confident verdict, that source's failure
vanished completely. `gather_evidence()` now records WHY every such case
was skipped in `partial_gaps`, returned via the new
`describe_partial_gaps()` override and surfaced in every verdict's
reasoning regardless of confidence (see `core/engine.py`'s detail
above). (2) the sourced facts here are manufacturer RATINGS, never an
observed destructive test, regardless of whether a claim's verb is
"survives"/"fails" or "is rated for" — this was documented in this
module's own docstring but never stated in the verdict a caller actually
reads. Every accepted piece of evidence's snippet now says so explicitly
("checked against the manufacturer's RATED limit (not an observed
destructive test)"), so a verdict can't be misread as a destructive-test
result just because the claim's wording implied one. A real claim-type
split (survives vs. is-rated-for as genuinely different checks) is not
implemented: there is no destructive-test data in this project's corpus
to check a "survives" claim against even if the two were split, so
splitting them would only turn every "survives"-phrased claim into an
UNDETERMINED with the same underlying rating evidence — stating the
conflation plainly in every verdict is the honest fix available without
new source data.

**Fifth-round addition (this session, 2026-10-24): Bar100XT sourced,
QuSpin's absence confirmed, not assumed.** Fetched Blue Robotics' real,
live BarXT product page (https://bluerobotics.com/?p=219055) — no
separate PDF exists for this part; the page itself is the manufacturer's
spec sheet. Real stated rating: 0-100 bar operating range (~995 m
depth-equivalent via this project's existing seawater-density
conversion). Now sourced as `DOC4_Bar100XT` in `_SOURCES`/
`_RETRIEVAL_QUERIES`, same trust tier (0.85) as Bar30's chip datasheet,
through the identical retrieve→propose→verify pipeline — live-verified
the same way Bar30 was (`test_bar100xt_claim_produces_real_evidence_with_a_real_locator`,
offline-fake-client; the project's standing live tests exercise the real
API path the same way they already do for Bar30/BlueROV2). The
destructive-limit figure the same page states (400 bar, under an
explicit "highest pressure before permanent damage" footnote) is
deliberately excluded from the corpus excerpt, same reasoning as Bar30's
own exclusion — see `docs/extracted/constellation-robotics-seed.md` §3.
Separately, also fetched QuSpin's real official QZFM Gen-3 page
(https://quspin.com/qzfm-gen-3, confirmed: a blog post, not a formal
datasheet, no PDF linked) and read the WHOLE page checking for any
pressure/depth/submersion/waterproof/IP-rating wording — there is none
at all. This CONFIRMS the previously-assumed hypothesis
("QZFM Gen-3 has no submersion rating") as true, via a real checked
source, but it's still not a number to compare a depth against, so a
QuSpin depth claim correctly stays UNDETERMINED — `describe_gap()`'s
QuSpin branch was rewritten to cite this real source and date instead of
saying a datasheet still needs pulling. No corpus file was added for
QuSpin: there's no numeric fact for the retrieve→propose→verify pipeline
to route. See `docs/extracted/constellation-robotics-seed.md` §4.

### `domains/ml_data.py` detail

**Real, offline, tested, grown** — re-computes the claimed statistic
from actual CSV(s) via stdlib `csv`+`statistics` only (no new dependency:
`median()`/`quantiles()`/`correlation()` are all stdlib, `correlation`
since Python 3.10, this project already requires >=3.11). Now:
`median`/`p25`/`p75`/`correlation` alongside `mean`/`min`/`max`/`stdev`;
multi-file datasets (`dataset_path` as a list, rows concatenated, a
column missing from any one shard is a named mismatch); real
AND-semantics compound claims (`"checks": [...]`) — CONFIRMED only if
every sub-check holds, one genuine failure CONTRADICTS the whole claim
(not averaged against the parts that held), a sub-check this adapter
can't even evaluate makes it UNDETERMINED with that specific reason.

**Bug fixed:** `stdev` (and now `p25`/`p75`/`correlation`) used to crash
with an uncaught `StatisticsError` on too few data points —
`_check_single()` now validates each stat's real minimum sample size.
Confirmed via docs/DESIGN.md §5 that this adapter correctly stays outside
`retrieval/` — there's no passage to search for, just a computation to
run.

**Another bug found (by `stress_test/` Test #1, 2026-10-18) and fixed —
see `stress_test/BUGS_FOUND.md`:** a real UCI dataset (`auto_mpg.csv`)
spells a missing value as the literal string `"NaN"`, which `float("NaN")`
parses successfully (it doesn't raise) instead of failing like a
genuinely malformed cell — silently corrupting `mean`/`median`/`p25`/
`p75`/`correlation` and crashing `stdev` outright. `_read_column()`/
`_read_column_pair()` now also require `math.isfinite(value)` after the
parse, treating non-finite the same as unparseable; re-verified against
the real file (mean/median/p25/p75/stdev/correlation on `horsepower` all
correct, no crash) plus a regression test proving clean data is
unaffected.

**Security fix (external review, 2026-10-19, two review passes): path
traversal / arbitrary file read.** `dataset_path` went straight into
`Path(...).open()` with no containment check — since `Claim.context` is
caller-supplied verbatim from a POST /verify body, this was an arbitrary
local file read (`/etc/passwd`, `.env`, source code — not just a
wrong-CSV bug). Fixed: every path is resolved (defeats both `..`
traversal AND symlink escapes — checked on the real resolved path, not
the literal string) and must land inside `allowed_base_dirs` (default:
`evals/fixtures/`, `stress_test/data/`; constructor-injectable, same DI
pattern as `RoboticsAdapter(client=...)`). **Follow-up review fixes:**
(1) a null byte in a path made `Path.resolve()` raise `ValueError`, not
`OSError` — only the latter was caught, so this 500'd instead of a clean
rejection; both are now caught in `_path_safety.py`. (2) a `dataset_path`
list's elements weren't checked to actually be strings — `Path(123)`
crashed; now validated explicitly. (3) the rejection message used to
print the server's real, absolute allowed-directory paths — an
information-disclosure leak of filesystem layout; the message now only
ever echoes the caller's own (unresolved) input, never the server's real
paths. All proven by dedicated regression tests, not just manual checks.

**Phase B addendum (personal manual review, 2026-10-19): percentile
convention, stated explicitly.** `p25`/`p75` use
`statistics.quantiles(..., method="exclusive")` (the default), which
genuinely disagrees with numpy/pandas/Excel's own default (a
linear-interpolation method) — a real product-trust risk affecting 300
of 2,504 `ml_data` manifest claims, never stated anywhere a user would
see it before. Now documented in this module's own docstring and in the
manifest's own p25/p75 claim text. **Also found (same review): a
display-precision bug in `stress_test/claims/generate_manifest.py`** —
claim text rounded `expected_value` to a fixed 6 significant figures
while the structured value kept full precision; for 41 of 2,185
single-stat claims (30 labeled "confirmed") with very tight tolerances —
not 2,504, a wording error caught on a second manual review (2026-10-21):
the other ~320 ml_data claims (compound multi-check claims, two-shard
combined-mean claims) use different text-generation code paths this
specific bug never touched — the rounding error exceeded the tolerance,
so the human-readable claim literally stated a different number than
what was being verified — invisible to the real adapter (which never
reads display text) but silently unfair to every baseline that only sees
it. Fixed with a tolerance-aware formatter; verified zero remaining
inconsistencies across the full manifest.

**FIXED (was "disclosed, not fixed" as of the second manual review,
2026-10-21; actually fixed this pass): the `-200` missing-value
sentinel.** `air_quality.csv`'s own UCI documentation defines `-200` as
that dataset's missing-value marker across all its measurement columns;
neither this adapter nor `stress_test/oracles/ml_data_oracle.py`
implemented that convention — both treated `-200` as a literal real
reading. Fixed in both (kept independent on purpose — the oracle
duplicates the lookup table rather than importing it, since sharing code
with the thing it's checking would defeat the point of an independent
oracle) via a per-FILENAME sentinel lookup populated only from a real,
cited source (`_DATASET_SENTINELS` in `ml_data.py`) — deliberately NOT a
blanket "-200 is always missing" rule, confirmed by its own test
(`test_minus_200_in_a_differently_named_file_is_not_treated_as_a_sentinel`):
a `-200` in a file never documented to use that convention is still
counted as a real, literal value.

**Known follow-up, stated plainly, not silently left stale:** the
stress-test manifest's ~212 `air_quality.csv` claims had their
`expected_value`/ground truth generated BEFORE this fix (with the
literal `-200` included in the computation). Regenerating those 212
claims against the now-fixed oracle is real, separate work — not done
in this pass — so running the full manifest against this adapter will
show new mismatches on those specific claims that are the GROUND TRUTH
being stale, not this adapter being wrong; see `stress_test/BUGS_FOUND.md`
for the original finding this fixes.

### `domains/fpga_embedded.py` detail

**Real, offline, tested, now against a REAL EDA tool format** — parses
Xilinx/AMD Vivado's actual `report_timing_summary` output (Design Timing
Summary: WNS/TNS/WHS/THS/WPWS/TPWS in Vivado's own fixed column order;
Clock Summary: per-clock period/frequency, generated clocks indented
under their source clock) instead of this adapter's previous invented
`key: value` format. **Verified, not assumed:** the real column
headers/table structure were copied from a real, fetched, open-source
project's actual Vivado report (Elphel x393 — URL and fetch details in
the module docstring), not guessed from memory. Now handles multi-corner
reports via a `Corner: <NAME>` label line — stated explicitly as THIS
ADAPTER'S OWN convention for concatenating several real per-corner
blocks into one file, not itself copied from one official multi-corner
sample (a real multi-corner `.sta.rpt` was found but sat behind a login
wall that couldn't be gotten past).

**Register-map support landed this session (2026-10-24) — via a SECOND
real file format, not forced into the first.** `report_timing_summary`
still genuinely carries no register/address data at all (unchanged fact
— `register_map_claim_undetermined.json` still proves that specific
honest gap holds for a Vivado file). Register-map claims are instead
routed to CMSIS-SVD (System View Description), a real, vendor-neutral
XML register-map schema used across the embedded-systems industry —
picked over a Xilinx/Vivado-specific export because no real Xilinx
register-map sample was ever actually found/fetched (checked this
session: searched for Xilinx IP-XACT `component.xml` examples, found
only tooling docs and MathWorks material, nothing real and fetchable —
see `fpga_embedded.py`'s module docstring), and SVD is the honestly
generic choice for a domain meant to cover arbitrary submissions, not
one vendor's toolchain. **Verified against two independently-sourced
real files, not invented:** ARM's own CMSIS_5 `ARMCM4.svd` example
(confirmed real but header-only, no peripherals — not usable as a
register-data sample) and Espressif's officially published
`svd/esp32c2.svd` (Apache-2.0, real peripherals with real addresses/
offsets/bit layouts) — `evals/fixtures/esp32c2_register_map_excerpt.svd`
keeps two complete, real, verbatim peripheral blocks (RNG, BB) from the
latter, copied byte-for-byte, same "partial excerpt, real, not invented"
convention `doc3_bar30_excerpt.txt` already uses. `_parse_svd_register_map()`
scans the real one-tag-per-line SVD structure by nesting (peripheral→
register→field), the same "known real format, position-based, not a
generic XML tree walk" convention `_parse_report()` already uses for
Vivado's tables — and tracks the exact source line number for every
value it reads, so every register-map `Evidence.locator` points at a
real, re-checkable line, not just a filename. New metrics:
`peripheral_base_address`, `register_offset`, `register_size_bits`,
`field_bit_offset`, `field_bit_width` — all STATIC facts an SVD actually
states (never a runtime register's live contents, which no static file
could honestly claim to know). Routed through entirely separate
`_check_register`/`_gather_register_evidence` code paths from the
Vivado timing logic (register claims have no "corner" concept at all);
the SAME path-containment check (`is_path_within_allowed_dirs`) guards
both. 15 new offline tests, all passing; see
`evals/cases/fpga_embedded/svd_register_offset_confirmed.json` for a
real end-to-end case.

**Second manual review (2026-10-21): the same `:.6g` display-precision
bug fixed in `ml_data.py`'s section above was never actually fixed here.**
`stress_test/claims/generate_manifest.py`'s `_fpga_single()` displayed
`expected_value` at a flat 6 significant figures, so its two
boundary-adversarial claims per metric per file (`== real+1e-6`,
`>= real+1e-6`, both "contradicted") rounded right back to text that
looked identical to the real, confirmed value — 28 claims stating the
file's exact true value in text while being graded "contradicted" over
an invisible 1e-6 offset. Fixed with the same tolerance-aware formatter,
scoped to just these two call sites; regenerated and diffed: 0
verdict/context diffs, 62 text diffs (28 confirmed genuinely fixed, 34 a
harmless cosmetic sci-notation change).

**Security fix (external review, 2026-10-19, two review passes): path
traversal / arbitrary file read.** Same vulnerability and same fix as
`ml_data.py`'s `dataset_path` above, including the follow-up null-byte
and absolute-path-leak fixes — `report_path` now requires the resolved
real path to land inside `allowed_base_dirs`, defeating `..` traversal
and symlink escapes, with its own dedicated tests.

### `domains/research_web.py` detail

**TWO modes, both real.** Mode 1 (unchanged): a pre-selected URL, fetched
live, verbatim quote check. Evals/demo use a local fixture server
(`evals/fixture_server.py`) so those verdicts can't rot; one separate
live case against example.com (`live_example_com_drift`) accepts
`contradicted` as a "page drifted" outcome. Mode 2 (**new**): genuine
multi-candidate live research — no pre-selected URL, just a claim. Real
keyless search (Wikipedia's API, confirmed working live; DuckDuckGo
HTML, confirmed anti-bot-blocked from this dev sandbox — tried anyway,
best-effort) finds candidate pages, which are fetched, chunked
(`retrieval/chunking.py`), BM25-searched (one combined index, then
grouped by source page so up to 3 distinct real sources are each
independently checked — not just the single best-ranked chunk), run
through the same live `extract.propose()` (`openai/gpt-oss-120b`)
robotics.py uses, and independently `verify_proposal()`-checked. A real
CONFIRMED, a real CONTRADICTED, and two differently-shaped real
UNDETERMINED outcomes (no candidates found at all vs. candidates found
but the fact genuinely absent) were each confirmed live, repeatedly, not
assumed — see `evals/cases/research_web/live_multi_candidate_*.json`.
The stance (supports/contradicts) for mode 2 is a bounded LLM judgment on
an ALREADY-mechanically-verified quote, not a new source of fabrication
risk — two purely mechanical approaches (strict substring, token-overlap
ratio) were tried first and both failed on real live tests (see module
docstring).

**Near-duplicate guard:** checking multiple sources means two of them can
be the same source in disguise (a mirror, a copy-pasted sentence) —
`_is_near_duplicate_evidence()` (Jaccard token overlap >= 0.8) drops a
second near-verbatim match before it ever reaches `core/engine.py`'s
scoring, so a mirror can't be double-counted as independent confirmation;
a genuinely differently-worded second source confirming the same fact
still counts, proven by two offline tests against real local fixture
pages (`test_multi_candidate_mirror_sources_count_as_one_not_two`,
`test_multi_candidate_genuinely_different_sources_both_count`) —
`core/engine.py` itself was not touched (its own, separate same-SOURCE
redundancy fix is in the `core/engine.py` section above).

**Security fix (external review, 2026-10-19, two review passes): SSRF.**
Both fetch sites previously fetched any url with zero validation — a
claim could point this at cloud metadata (169.254.169.254) or an
internal service. `_is_safe_to_fetch()` resolves the hostname and
rejects it unless every resolved address is `ip.is_global` (fail-closed
on resolution failure) before any network call; on by default.
**Follow-up review fixes:** (1) the first version enumerated specific
ranges to block and MISSED carrier-grade NAT (100.64.0.0/10) — replaced
with `not ip.is_global`, strict-by-default rather than
enumerate-what-to-block. (2) the first version checked only the ORIGINAL
url and then fetched with `follow_redirects=True` — a real
SSRF-via-redirect bypass, not hypothetical; `_safe_fetch()` now sets
`follow_redirects=False` and manually re-checks `_is_safe_to_fetch()` on
EVERY redirect hop, up to 3, before following it. (3) no response-size
cap — `_safe_fetch()` now streams and truncates at 5 MiB. Proven by 7
tests including one that simulates a real redirect-to-metadata-endpoint
bypass attempt and one that proves the size cap actually truncates.
**Third review pass, 4 more fixes:** (a) a malformed `Location` header
(e.g. `"http://[::1"`) made `httpx.URL.join()` raise `httpx.InvalidURL`,
which on httpx 0.28.1 is NOT an `httpx.HTTPError` subclass — neither
caller caught it, an unhandled 500; now wrapped and converted to
`_FetchRefused`. (b) a page truncated at the 5 MiB cap whose quote fell
past the cut used to read as "not found" → a confident CONTRADICTS —
mode 1 now downgrades this to an honest UNDETERMINED via a `truncated`
flag threaded through `httpx.Response.extensions` (mode 2 was never
affected — it never treats "not found in this chunk" as a contradiction
at all). (c) httpx's own `timeout=` bounds only the gap between
individual reads, not TOTAL time — a slow-trickle server could hold a
connection open indefinitely while technically staying under that
per-read limit; `_safe_fetch()` now wraps the whole multi-hop fetch in
`asyncio.timeout()`, converted to `httpx.ReadTimeout` (already an
`HTTPError` subclass) so neither caller needed a new except clause. All
proven by tests, now 27 in this file. **Known, accepted gap, documented
not fixed:** DNS rebinding — the hostname is resolved once for the
safety check and again (independently) by httpx to connect; a rebinding
attack could answer differently between the two. The real fix (connect
directly to the validated IP, bypassing httpx's own resolution) is
substantially more invasive; stated plainly in the module docstring as
accepted risk, not silently handled. Only this project's own
local-fixture tests opt out of the guard via `block_private_networks=False`,
explicitly.

**Phase B addendum (personal manual review, 2026-10-19): test
hermeticity.** 7 of these tests used `https://example.com/...` as a
stand-in "safe-looking" URL while testing something else entirely
(block-page detection, the redirect/size-cap/InvalidURL/timeout fixes
above) — but never stubbed DNS, so each one did a REAL network lookup of
example.com before reaching its own mock. Fixed by faking DNS resolution
for "example.com" specifically (to a real, fixed, globally-routable
address, so `ip.is_global` still runs for real) rather than stubbing the
safety check itself, which would have also defeated the redirect test's
own real check of its unsafe second hop. Verified hermetic by running
these 7 with real DNS resolution globally disabled (raises immediately
if ever invoked) — all 7 still pass, in under a second.

**Tavily landed this session (2026-10-24) as the PRIMARY search backend**
(resolves the "effectively Wikipedia-only" critique above) —
`_tavily_search()` calls Tavily's real `/search` API (`TAVILY_API_KEY`
in `.env`), a keyed search API built for feeding LLM pipelines, not a
scraped HTML results page. DDG+Wikipedia are now a FALLBACK, tried only
when Tavily returns zero URLs (missing key, a live failure, or a genuine
zero-result query) — kept exactly as before so cloning this repo
without a Tavily key still gets some real coverage. **Confirmed live to
materially change real outcomes, not just added inertly:** the eval case
for "BlueROV2 has a maximum operating time of 14 hours" used to resolve
UNDETERMINED (no candidates at all — DDG blocked, no Wikipedia runtime
figure) and now resolves CONTRADICTED, because Tavily surfaces a real
Blue Robotics distributor page (sepcotech.com) stating a real run-time
figure (~2-4 hours) that genuinely contradicts the claim — see
`evals/cases/research_web/live_multi_candidate_contradicted_via_tavily_distributor_page.json`.
A second case moved from "zero candidates" to "candidates found, fact
absent" for the same reason (Tavily simply finds more than DDG+Wikipedia
did) — both eval cases' notes were rewritten honestly rather than left
stating a now-false "both backends return nothing" claim. 5 new offline
tests (`_tavily_search`'s key-missing/success/non-200 paths, and the
fallback-ordering logic) — all passing, no network call.

### `llm/nebius_client.py` detail

**Fully live-verified.** Base URL **corrected**: was
`https://api.studio.nebius.ai/v1` (wrong domain and TLD), now
`https://api.tokenfactory.nebius.com/v1` — confirmed with a real
`GET /v1/models` call (200, 28 models). Model **set to
`openai/gpt-oss-120b`** on measured benchmark data (a related project's
Nebius model-selection benchmark: 100% strict-JSON extraction, 100%
JSON-valid, 100% overall on a 27x3 run, 0.95s latency, for an equivalent
"extract structured values" stage) — not the original guess
(`meta-llama/Meta-Llama-3.1-70B-Instruct`, which isn't in the live
catalog at all) and not picked for branding fit. Confirmed for this
account/endpoint specifically: live in the catalog, a real
chat-completions round trip works, and repeated real `propose()` calls
against this project's own corpus returned correct `chunk_id`+verbatim
`quote` every time (8/8, then 6/6 on a second doc pair).

**Three bugs found and fixed:** (1) `python-dotenv` was a declared
dependency but `load_dotenv()` was never called anywhere, so a
`.env`-only setup (the README's own documented flow) silently never
loaded the key; (2) the first fix used `load_dotenv()`'s default
`override=False`, which kept a stale already-exported shell value even
after `.env` was edited with a freshly rotated key — switched to
`override=True`; (3) `retrieval/extract.py`'s prompt named
`"kind": "rated" or "tested" or null` with no explanation of what those
values mean — see `domains/robotics.py`'s section for what that caused
and how it was found. Now used for real by `domains/robotics.py`.

**Nemotron swap DONE** (Apps and Agents track requirement — at least one
NVIDIA open model called in the real request path, not just mentioned):
`domains/robotics.py` now explicitly requests `nvidia/Nemotron-3-Ultra-550b-a55b`
(`ROBOTICS_MODEL`, overriding `NEBIUS_MODEL`/.env) for every live
`propose()` call — a real, live model in the request path, not a comment.
`research_web.py` is unchanged, still `openai/gpt-oss-120b`. This wasn't a
blanket swap: it's the outcome of an honest before/after comparison
across all three Nemotron tiers (Ultra/Super/Nano) plus a one-pilot look
at a fourth (3.5 Lightning), on both domains, at two sample sizes, that
found and fixed three real pipeline bugs along the way (no `max_tokens`
cap, no quote-length guidance, no entity-matching check in the stance
prompt) before trusting the comparison that produced them. Full
methodology, every pilot's real numbers, the bugs found, and why
`research_web` deliberately stayed on the current default:
[`stress_test/results/NEMOTRON_PIVOT_REPORT.md`](../stress_test/results/NEMOTRON_PIVOT_REPORT.md) —
summarized in the README's own "How the model choice was made" section.

### `api/server.py` detail

Done, routes straight to the engine above. **Security fix (external
review, 2026-10-19, two review passes):** `/verify` had no auth and no
rate limiting at all despite being the Nebius-budget-burning endpoint.
Fixed: a required `X-API-Key` header checked with
`secrets.compare_digest` on bytes (constant-time), fail-closed (no
`ANTICASSIOPEIA_API_KEY` configured means EVERY request is rejected, not
"auth disabled"); a dependency-free in-memory token-bucket rate limit on
`/verify`, plus a separate, stricter failed-auth throttle. `/health`/
`/domains` stay open on purpose. **Follow-up review fixes:** (1)
`secrets.compare_digest(str, str)` raises `TypeError` (a 500) for a
non-ASCII header value — fixed by encoding both sides to bytes first.
(2) the main rate limit was keyed on `request.client.host`, which
collapses every caller behind a shared reverse-proxy IP into one bucket —
rekeyed on the validated API key instead (honest caveat: with only one
key currently supported, this is close to one global bucket today; the
design pays off once/if multiple keys exist). (3) added a SEPARATE token
bucket keyed by client IP specifically for failed auth attempts, so
repeated wrong-key guesses get throttled (429) independently of the main
limit. (4) `load_dotenv(override=True)` would let a stray `.env`
silently out-rank a real platform-injected secret — switched to
`override=False` for this file specifically (`nebius_client.py`'s own
`override=True` is unchanged, a different deliberate fix for a different
dev-workflow problem explained in its own docstring). A `.dockerignore`
was also added (defense-in-depth — the current Dockerfile never `COPY`s
`.env` anyway). **Third review pass, 1 more fix:** the bucket dicts added
one entry per distinct API key / client IP forever with no eviction — a
real memory-exhaustion DoS, cycling through many distinct keys/spoofed
IPs. Fixed with a hard cap (`_MAX_TRACKED_BUCKETS`) plus idle-first
eviction (`_BUCKET_IDLE_TTL_SECONDS`), checked right before a new entry
would be added — proven to keep the dict bounded under a (monkeypatched,
for the test) tiny cap, not just that the constants exist. All proven by
10 tests. Honest limitation: both bucket types are per-process state, not
shared across multiple uvicorn workers — documented, not silently
assumed away.

**Track/UI framing (external review, item 26): a confirmed, deliberate
decision, not an implicit default.** This project deliberately ships no
dedicated UI. The Apps and Agents track asks for "an app or agent you'd
actually use," not a web frontend specifically — so the CLI
(`scripts/demo.py`), the HTTP API above, and direct use as another
agent's tool-use step are treated as three equally real surfaces over
one shared engine, and effort went into making all three genuinely work
rather than into a UI none of them need. See `README.md`'s opening
paragraph for where this is stated to a reader first.

### `scripts/demo.py`, `Dockerfile`, CI, `evals/` detail

`scripts/demo.py`: real end-to-end demo, 6 claims across all 4 domains,
no mocked output. `Dockerfile`: **build-tested for real, just now, with
the current code** — `docker build --no-cache` succeeds, the resulting
container's `/health`, `/domains`, and a real `POST /verify` round trip
(ml_data, a genuine `confirmed` verdict with real evidence) all verified
against a running container, right before this line was written, not
inherited from an earlier session's claim.

**FOUND BUG in the process of re-verifying this** (external review):
the in-build `evals/run_evals.py` step had NO way to pass
`NEBIUS_API_KEY`/`TAVILY_API_KEY` into the build (`.env` is deliberately
not copied into the image — secrets don't belong baked into a layer),
so every robotics case (always needs a live LLM call, no offline path
exists) and every research_web mode-2 case (`live_multi_candidate_*`)
was silently resolving to the wrong verdict and FAILING the build, not
skipping it — 9 failures, confirmed by actually running it. This
pre-dated this session's Nemotron/Tavily work; it just took that work
making those calls newly load-bearing to surface it. Fixed:
`run_evals.py`'s `_needs_live_key()` now skips (not fails) any case that
genuinely needs a live key when `NEBIUS_API_KEY` isn't set, the same
distinction the pytest suite's own `_requires_live_key` marker already
draws — re-verified: `docker build --no-cache` now reports
`17 passed, 0 failed, 13 skipped (no NEBIUS_API_KEY), 30 total` and
exits 0.

`.github/workflows/evals.yml`: written, mirrors the exact
local commands already verified to work (`pip install -e .` +
`python evals/run_evals.py`) — CI run itself not observed. `evals/`: 31
cases across all 4 domains, all passing with a real key present
(`PYTHONPATH=. python evals/run_evals.py`), live LLM/network calls
included — robotics' live round trip confirmed stable after the
`retrieval/extract.py` prompt fix; ml_data (+3: multi-file, compound
confirmed, compound one-part-false contradicted) and fpga_embedded (+4:
real-format confirmed/contradicted, two real multi-corner cases, one
register-map honest gap) grew an earlier pass, both fully offline and
deterministic; a later session added +1 robotics (Bar100XT confirmed +
contradicted, replacing the old undetermined case — net +1 since one
case was repurposed), +1 fpga_embedded (a real SVD register-map
confirmed case, alongside the pre-existing honest-gap case), +1
research_web net (one case moved
shape, one new contradicted-via-Tavily case added), and +1 robotics
(QuSpin QZFM Gen-3's confirmed-no-rating finding, previously described
only in `docs/extracted/constellation-robotics-seed.md` §4 and not
locked in by a test) — see each adapter's own detail section above for
what changed and why.

## Item 20: claim decomposition (external review, 2-hour-budgeted round)

**Built, real, tested:** `anticassiopeia/core/compound.py` —
`decompose_claim()` (one LLM call splitting "A and B" into independent
parts, each classified `robotics`/`research_web`/`unsupported`;
`unsupported` covers anything needing `ml_data`/`fpga_embedded`'s real
file-path context, which decomposition explicitly refuses to fabricate),
`rollup()` (pure AND-semantics: all-`CONFIRMED` parts → `CONFIRMED` at
the MINIMUM confidence among them — the AND is only as sure as its
weakest part; any `CONTRADICTED` part → `CONTRADICTED` at the MAXIMUM
confidence among the contradicting parts — only one needs to be false;
anything else → `UNDETERMINED`), and `verify_compound()` orchestrating
both through the real, completely unmodified `VerificationEngine` and
its real adapters — no engine/adapter code changed for this feature.
19 tests in `tests/test_compound.py`: JSON-shape validation (well-formed,
code-fenced, malformed, missing/empty fields), `rollup()`'s math against
every state combination including the empty/all-unsupported edge cases,
and `verify_compound()` end-to-end against a fake LLM client + a real
`VerificationEngine` — confirms-all, contradicts-on-one-part, the
`ml_data`-sub-claim-never-fabricated case, a non-compound single-part
claim, and a dead decomposition call resolving `UNDETERMINED` rather
than crashing.

**Deliberately NOT built this round:** no `/verify/compound` HTTP
endpoint — `server.py` does not import this module at all, so it is
real, reachable Python (`from anticassiopeia.core.compound import
verify_compound`) but not reachable over the network in this build. Per
the task's own instruction (partial-but-reachable is worse than
honestly-incomplete-and-documented): the core decompose→verify→rollup
logic was finished and tested cleanly within budget; the endpoint itself
— its own request/response schema, auth/rate-limit wiring consistent
with `/verify` (a compound request is MORE expensive than a plain one:
one decomposition call plus N sub-verifies, each potentially its own
LLM call — the existing per-key bucket sizes were never evaluated against
that), and its own endpoint-level tests — was left for a later round
rather than wired in half-finished. `docs/DESIGN.md` §2 has the original
design reasoning this followed.

## v2: "bring your own evidence" — upload, robotics BYOE, project verify, frontend

Built in three phases (2026-10-25), each committed and CI-green before
the next started; full detail, including every test file and both
deliberate live-call confirmations, is in each phase's own commit
message (`git log --grep "v2 Phase"`).

**Phase 1 — `POST /upload` + `robotics.py`'s free-text BYOE path.**
`anticassiopeia/retrieval/document_ingest.py` (`extract_text()`,
format-dispatched: `.txt/.md/.csv/.rpt/.svd/.xml` as UTF-8, `.pdf` via
`pypdf`, `.docx` via `python-docx`; a `DocumentIngestError` — never a
silent empty string — on an unsupported extension or no extractable
text, e.g. a scanned PDF with no text layer) and
`anticassiopeia/api/upload_store.py` (a thread-safe, capped, 24h-TTL
in-memory `UploadStore` keyed by an opaque `secrets.token_urlsafe`
`document_id`) were present but UNTESTED and missing real dependency
declarations going into this phase (see that commit's own "WIP, stopped
mid-Phase-1" message) — fixed for real: `pypdf`/`python-docx`/
`python-multipart` added to `pyproject.toml` pinned to the exact
versions actually installed and tested (`python-docx`/`python-multipart`
were missing from the environment entirely; the multipart one meant
`/upload`'s own form-parsing would have failed at runtime).
`anticassiopeia/retrieval/stance.py` was extracted out of
`research_web.py` (pure refactor, zero behavior change, proven by the
existing research_web suite staying green) so `robotics.py`'s new BYOE
path and `research_web.py`'s multi-candidate mode share one stance-
judgment implementation instead of two that could drift.
`robotics.py`'s `gather_evidence()`: when `Claim.context["document_text"]`
is present (resolved from a caller's `document_id` by `server.py`'s
`/verify` handler — `robotics.py` itself never imports the upload store,
keeping the domain/api layering clean), it takes over ENTIRELY — real
chunk → BM25 → propose → independently-reverify → judge-stance, the
SAME shape `research_web.py`'s multi-candidate mode already uses, minus
the web-search step. Deliberately does NOT route through the depth-
specific regex/bar-conversion parser even when `depth_m`/`polarity` are
also present in context — an uploaded document can be about anything,
not just a rated depth. No `document_text` → byte-for-byte the pre-v2
fixed-corpus behavior (proven by the pre-existing 229-test baseline
staying green throughout). 49 new offline tests (real `pypdf`-built
PDFs and `python-docx`-built DOCX files, not mocks, for the ingestion
module; `UploadStore`'s TTL/cap eviction; the BYOE path via a fake LLM
client; `/upload`'s auth/rate-limit/size-cap/extension-allowlist and
`/verify`'s `document_id` resolution/expiry) plus two deliberate live
calls against the real Nebius API confirming the full pipeline in both
directions (a true depth claim against an uploaded datasheet →
CONFIRMED; a false one → CONTRADICTED).

**Phase 2 — `POST /verify/project`.** A batch of claims, each optionally
tied to a prior upload's `document_id`, deterministically routed to the
right domain (`server.py`'s `_sniff_domain_for_document()`: extension
first, `.xml`/`.rpt` cross-checked against real content markers already
defined in `fpga_embedded.py` — `_SVD_DEVICE_TAG_RE`,
`_DESIGN_TIMING_SUMMARY_HEADER_RE`, imported and reused, never
reimplemented — so the one genuinely ambiguous extension isn't trusted
blind; never an LLM guess about a format code can already determine).
`ml_data.py`/`fpga_embedded.py` themselves are UNCHANGED — rather than
teach their already-hardened, heavily-tested file-reading/line-locator
code a second, raw-text code path, `server.py` writes a resolved
document's real extracted text to a real file under a new, fixed,
server-owned scratch directory (`var/project_scratch/`, gitignored),
added to just those two adapters' `allowed_base_dirs` via
`domains/__init__.py`'s new `default_domains(extra_allowed_base_dirs=...)`
param (default `None` — zero behavior change for every other caller).
Scoped to one request via a per-call `tempfile.mkdtemp()` subdirectory,
deleted in a `finally` block right after — proven empirically (not just
assumed) by a dedicated test asserting the scratch directory is empty
again after the call. The endpoint fabricates nothing: the caller still
supplies every structured field `ml_data`/`fpga_embedded` actually need
(column/stat/expected_value, or peripheral/metric/comparator/
expected_value) — this only ever auto-fills which real file a
`document_id` corresponds to. One claim's own failure (bad/expired
`document_id`, a domain with no defined way to consume a document) is a
named per-claim `error`, never a whole-batch failure; the real per-claim
`Verdict`s are rolled up via `core/compound.py`'s EXISTING `rollup()` —
this endpoint never calls `decompose_claim()` at all (see that section
above for why `DECOMPOSABLE_DOMAINS` is deliberately NOT loosened just
because this endpoint exists). Its own rate-limit bucket (stricter than
`/verify`'s — a project call can fan out into several live LLM calls)
and a hard cap of 20 claims/call. 18 new offline tests (real CSV/SVD/
Vivado-report fixture content through real `ml_data.py`/`fpga_embedded.py`
computation against real scratch files; sniffing correctness including
caller override; per-claim-vs-batch error isolation; scratch cleanup)
plus one deliberate live end-to-end confirmation through the real app
and the real Nebius API: a real CSV mean recomputation + a real Nemotron
Ultra robotics BYOE verification, rolled up to a real `CONFIRMED`.

**Phase 3 — frontend rebuild.** `docs/index.html`'s visual theme was
fully rewritten (clean Inter sans-serif chrome, monospace reserved for
precision/data content only, a near-black navy background with two
sparse neon accents — lime for CONFIRMED/highlights, cyan for primary
actions — replacing the single blue-violet terminal theme a direct
screenshot-comparison correction rejected) and extended with a Documents
upload card and a Project-verify card (dynamic claim rows, each
optionally tied to an uploaded document) wired to Phases 1-2's new
endpoints, reusing the same error-handling conventions (401 fixed
message, 429 real server detail + retry, network failure + retry) the
single-claim flow already had. No browser tool was available to verify
this visually in-session; verification used what was available instead
of being skipped: `node --check` on the extracted script, and two real
`jsdom` dry runs of the ACTUAL shipped file (real DOM, real event
dispatch, a mocked `fetch()` returning the exact response shapes Phases
1-2's own backend tests already proved correct) covering the success
path (presets, single verify, project verify, mixed success/error
per-claim rendering) and the error path (401/429+retry/network-failure+
retry/a real `missing[]` payload) end to end. This process also caught a
real gap by actually POSTing rather than trusting a CORS preflight's
200: the LIVE Cloud Run deployment this frontend points at by default is
still running the OLD `server.py` (`/verify/project` is a real 404
there right now) — stated plainly in the README's "Frontend" section,
not hidden. Redeploying is a real, billed action on the live GCP
project, not something any CI step in this repo does automatically, and
this session had no `gcloud` CLI available to do it even if that were
appropriate to do unprompted.

## v3: closing the v2 gaps + multi-document pooled search

Built following `claude/ANTI_CASSIOPEIA_V2_MASTER_BUILD_PROMPT.md`'s
successor spec (same verbatim-handoff convention), in the build order
that spec itself locked, each step committed and offline-suite-green
before the next started (`git log --grep "v3 §"`). All of §1.1/§2.1/
§2.2/§2.3/§2.4/§1.3/§2.5/§1.2 shipped in this round — §1.2
(`POST /verify/compound`) was built last, exactly as the spec's own
build order placed it (the least-requested of the original gaps, the
most expensive in live-LLM-call terms, and the one that benefited most
from everything above being stable first), but nothing was actually
dropped from this round's scope.

**§1.1 — plain `/verify` no longer silently no-ops on `ml_data`/
`fpga_embedded` uploads.** Before this fix, `_resolve_document_context()`
only ever injected `document_text`/`document_filename` — fields neither
`ml_data.py` nor `fpga_embedded.py` ever reads — so uploading a CSV and
then calling plain `/verify` with `domain=ml_data` and that `document_id`
silently ignored the upload (an honest `UNDETERMINED` gap, never a wrong
confident answer, but a real usability gap: the document picker did
nothing for 2 of the 4 domains). Fixed by generalizing the same real-
scratch-file translation `/verify/project` already did: the function
gained a `domain` parameter and now branches three ways (`robotics` →
inject text directly; `ml_data`/`fpga_embedded` → write a real scratch
file under the SAME `_PROJECT_SCRATCH_DIR` `/verify/project` already
uses, now shared rather than duplicated; anything else, most notably
`research_web` → a clean named 400, not a silent no-op). Lifecycle is
different from the batch endpoint's per-request subdirectory: a single
`/verify` call writes and deletes its own one file in a `finally` block
right around `engine.verify()`. 6 new offline tests, including one
proving cleanup happens even when the claim itself resolves to an honest
gap, not just on the happy path.

**§2.1 — ownership added to `UploadStore`.** Foundational for pooled
search: without an owner concept, "search across my documents" would
mean "search across every caller's documents" — a real scope violation
the moment more than one caller shares this server, which the public
demo key already risks (anyone who visits the hosted frontend shares
it). `StoredDocument` gained a frozen `owner_key_hash: str` field (a
SHA-256 hash of the uploading API key, never the raw key — defense in
depth even though this never leaves process memory); `put()` takes it as
a new required param; a new `list_for_owner()` returns one owner's own
currently-valid uploads, most-recent first. `get()` by `document_id` is
DELIBERATELY UNCHANGED in signature and behavior — every existing
single-document flow (`robotics` BYOE, `/verify/project`'s per-claim
`document_id`) keeps working exactly as before, regardless of who
uploaded the document a valid id happens to reference. Honest limitation
stated in the module docstring: under the shared public demo key
specifically, "your pool" really means "every demo-key visitor's
uploads, pooled together" — expected for a shared sandbox, not real
per-caller isolation; a caller's own real key gets genuine isolation. 5
new ownership-isolation tests (including: key A's list never contains
key B's documents; expired documents are excluded; direct `get()` is
unaffected).

**§2.2 — `GET /documents`.** Lists the calling key's own currently-valid
uploads (id, filename, size_bytes, and `seconds_until_expiry` — NOT a raw
`uploaded_at`, because `StoredDocument.uploaded_at` is
`time.monotonic()`-based with no wall-clock meaning on its own; handing
it back verbatim would be a meaningless number, so this endpoint returns
the actually-useful derived quantity instead). Reuses `/verify`'s own
rate-limit bucket rather than getting a dedicated one like `/upload`/
`/verify/project`/pooled search's resolution did — this is a cheap
in-memory dict scan, not real disk I/O or live-LLM fan-out, so it didn't
earn the stricter, separate-bucket treatment those did. 6 new tests,
including one proving the bucket-sharing itself (hammering `/documents`
trips the same budget `/verify` uses).

**§2.3 — multi-document pooled search, the core new feature.** New
`context.document_pool = true` (mutually exclusive with `document_id`;
robotics-only — `ml_data`/`fpga_embedded` need one exact structured file
per claim, "which of several CSVs has this column" is a different,
harder, out-of-scope feature; `research_web` has no document-consuming
mode at all). `server.py` resolves the pool via
`upload_store.list_for_owner()`, caps it at `_MAX_POOL_DOCUMENTS` (10,
most recent), and hands `robotics.py` the already-resolved `(filename,
text)` pairs plus the real total-available count via two context
fields — `robotics.py` itself still never imports `UploadStore` (same
clean domain/api layering `document_text` already established).
`robotics.py`'s new `_gather_byoe_pool()` builds ONE combined BM25 index
across every pooled document's chunks, namespaced by POOL INDEX
(`doc0`, `doc1`, ...) rather than filename — two of a caller's uploads
can share a filename (e.g. two different uploads both named
`spec.txt`), and a shared chunk-id prefix would silently collide entries
in the combined `chunks_by_id` dict; a parallel `doc_tag -> filename`
map is kept so the final `Evidence.source` still names the REAL
originating document, never a generic "pool" placeholder. Still exactly
ONE `propose()` call and ONE `judge_stance()` call per claim, same as
single-document BYOE — confirmed in testing, and stated here per this
project's own budget-discipline convention: only the local (free) BM25
corpus grows, never the live-call count. When a caller has more uploads
than fit under the cap, that truncation is named in the verdict's own
`reasoning` UNCONDITIONALLY — even on an otherwise-confirmed claim — via
the same `describe_partial_gaps()`/`reasoning` mechanism the rest of
`robotics.py` already uses for "a source was expected but something
about it didn't pan out." 11 new offline adapter tests (including the
filename-disambiguation case, the truncation-is-always-named case, and
the same ODrive-heading entity-ambiguity fix from the v2 stress test,
re-applied here since pooled search shares the same risk) plus 6 new
server-layer tests proving the ownership scoping actually holds end to
end over real HTTP.

**§2.4 — `/verify/project` gets the same `document_pool` option.** A
`ProjectClaimRequest` entry can set `document_pool: true` instead of
`document_id`, using the identical resolution §2.3 added — so one
project batch can mix claims pinned to a specific document with claims
that search the caller's whole pool. One deliberate deviation from the
spec's literal wording, stated here rather than silently done: a
`document_id`+`document_pool` conflict on one claim inside a batch is a
PER-CLAIM error, not the whole-request 400 plain `/verify` uses for the
identical conflict — plain `/verify` has only one claim, so request-
level and claim-level are the same thing there, but a batch's own
established principle ("one bad claim must not abort every other claim
in the same batch," stated in `_run_one_project_claim`'s own docstring
since v2) takes precedence for a multi-claim call. An omitted `domain`
on a pool claim defaults directly to `"robotics"` (no document to sniff
a domain FROM, and pooled search is robotics-only anyway, so that
default is never wrong). 6 new tests, including the actual point of this
section: one project call mixing a `document_id`-pinned `ml_data` claim
with a `document_pool` robotics claim in the same batch, both resolving
correctly.

**§1.3 — multi-instance deployment caveat (docs only, no code).** The
README's "Running the live API" section now states plainly that every
piece of this project's own in-memory state (rate-limit buckets,
`UploadStore`, pooled-search ownership lookups) is per-process, and
recommends `gcloud run deploy --max-instances=1` for exactly that reason
— naming the concrete failure mode (a document uploaded to instance A,
referenced from a later call routed to instance B, giving a false
"unknown or expired" or an emptier-than-real pool) rather than leaving it
implicit. A real shared-state fix (Redis, Firestore, etc.) stays out of
scope for this project's timeline and budget, same as it was when v2
first stated this limitation — restated here because pooled search adds
a second, related failure mode (an incomplete-looking pool) on top of
v2's original one (a falsely-expired `document_id`).

**§2.5 — frontend: 3-way document choice.** Both the single-claim
panel's document dropdown and each project-verify claim row's document
dropdown gained a 3rd option, "🔍 Search all uploaded documents (robotics
only)", alongside the existing "none" / "one specific document" choices.
Selecting it sends `context.document_pool = true` instead of
`document_id` — a sentinel `<select>` value (`__search_all__`, distinct
from any real `document_id`, which are `secrets.token_urlsafe(32)` and
far longer) drives this in `runVerification()`/`runProjectVerification()`.
The evidence card's existing source display needed no change — it
already renders `Evidence.source` generically, which
`_gather_byoe_pool()` already resolves to the real originating filename,
never a placeholder. Verified with `node --check` on the extracted
script plus a real `jsdom` dry run of the actual shipped file (mocked
`fetch()`, real DOM/event dispatch) proving both panels send
`document_pool: true` with no `document_id` present when the new option
is selected — same verification standard v2's own frontend rebuild used,
no browser tool being available in-session either time.

**§1.2 — `POST /verify/compound`, built LAST as the spec's own build
order required** (the least-requested of the three original gaps, the
most expensive in live-LLM-call terms — one decompose call plus up to
`_MAX_SUBCLAIMS` verify calls from a single request — and the one that
benefited most from everything above being proven first). Makes
`core/compound.py`'s `decompose_claim()`/`rollup()` (item 20, library-
only until now) reachable over HTTP by calling those real pieces
directly against the module-level `engine`, rather than through
`verify_compound()` as one atomic call — `verify_compound()` has no cap
on decomposed sub-claim count, and verifying every part before checking
a cap would waste exactly the live calls the cap exists to bound, so the
cap (`_MAX_SUBCLAIMS = 8`, a clear `422` above it, never a silent
truncation) is checked between decompose and verify instead. Its own
request model, `CompoundVerifyRequest`, deliberately has NO `domain`
field at all — `decompose_claim()` classifies each sub-claim into its
own domain itself, so a top-level domain would be meaningless and always
ignored, and this project's own convention is to never accept a field
that would just be silently ignored. Rejects (400) any request whose
`context` contains `document_id` OR `document_pool` — broader than the
spec's own literal text, which named only `document_id`; `document_pool`
(§2.3) didn't change the underlying reason at all (an LLM-invented
sub-claim has no way to know which uploaded document, or pool, it would
even correspond to), so both are rejected for the same stated reason.
Its own rate-limit bucket, stricter than `/verify/project`'s (one call
every 20s, burst of 2) given the larger potential fan-out. Its own LLM
client (`_compound_client`), constructed eagerly but safely at import
time — `NebiusTokenFactoryClient()` only reads env vars, no network
call, same "error surfaces per-call, not at construction time" pattern
`robotics.py`'s own `__init__` already established, giving a clean `503`
rather than an import-time crash when `NEBIUS_API_KEY` isn't set. 11 new
offline tests, all against a fake decompose client and fixed-evidence
fake domain adapters — no live Nebius call needed, including one that
proves the cap-before-verify ordering directly (a capturing adapter
asserting zero calls when decomposition blows past the cap).

## Post-v3: opt-in per-verdict summary + the "three C's" display rename

Two small additions requested directly by the project owner after the
v3 round above shipped, each resolved as a deliberate scope/identity
decision (both confirmed with the project owner before implementation,
not assumed):

**Display-only rename, not a wire-format change.** The project owner
asked why the third state doesn't also start with C (to match
CONFIRMED/CONTRADICTED and this project's own name). Confirmed scope:
the actual `VerdictState.UNDETERMINED` enum value and the API's wire
value stay exactly `"undetermined"` — a stable public contract already
live on the Cloud Run demo, never broken just for branding (the full
breaking-rename alternative was offered and declined). `docs/index.html`
gained one function, `displayStateLabel()`, that maps `"undetermined"` →
`"clouded"` for display text ONLY — CSS classes (`.state-badge.undetermined`,
`.verdict-card.undetermined`) stay keyed on the real state string, so
styling needed zero changes. Confirmed via a real `jsdom` dry run of the
shipped file: the badge's CSS class is still `undetermined`, its visible
text is `clouded`.

**Opt-in per-verdict summary (`context.include_summary=true`).** The
project owner asked for a small generated insight/summary after a
verify call. The real trade-off, surfaced and confirmed before writing
any code: an always-on summary would add a brand-new, additional live
LLM call to `ml_data`/`fpga_embedded`, which today make ZERO live calls
— a real, new budget line this project's own $20-cap discipline has
tracked carefully throughout. Confirmed scope: opt-in via a context
flag, off by default everywhere, applying uniformly across all four
domains when a caller does opt in (the caller is explicitly accepting
that one call's cost, so no domain-specific carve-out is needed once
asked for). Implementation: a new `_summary_client` (same safe,
import-time-but-never-crashing construction as `_compound_client`
above) and `_generate_summary()`, called in `/verify`'s handler AFTER
the real verdict is already fully computed — a summary failure (client
unavailable, a dead live call) is caught and reported as a separate,
named `summary_error` field, and NEVER affects the real verdict already
being returned regardless. The system prompt explicitly instructs the
model that it is commentary on an already-made decision, not a new
source of evidence: it must never introduce a fact/number/claim absent
from the real evidence/reasoning it's given, and never soften or
contradict the given state. 5 new offline tests (a fake summary client,
monkeypatched in) covering: absent by default, present when opted in,
a generation failure never failing the real verdict, an unavailable
client producing a named error rather than a crash, and the specific
point of the design — `ml_data` (otherwise LLM-free) successfully
getting a summary when asked.

## Causal-claim stance fix + judge_stance() model routing (found live, 2026-10-25)

Found by the project owner directly testing the live deployed
`/verify/compound` endpoint against a real, obscure historical claim
from their own research area (quantum key distribution) — not by an
internal test suite. Full finding, locked fix spec, and testing
requirements: `claude/ANTI_CASSIOPEIA_STANCE_CAUSAL_CLAIM_FIX_PROMPT.md`.

**The bug:** "The BB84 protocol was built on Stephen Wiesner's earlier
concept of quantum conjugate coding" was `CONFIRMED` on a passage that
only narrates "In 1984, the two combined quantum conjugate coding with a
cryptographic key-exchange scheme, producing ... BB84" — consistent with
a causal relationship but not actually asserting one. `judge_stance()`
had no notion of evidence *strength* for causal/dependency claims
specifically (a plain factual claim has no such gap — "the passage
states the fact" and "the passage supports the claim" are the same
thing there).

**The fix:** one additive paragraph in `retrieval/stance.py`'s
`STANCE_SYSTEM_PROMPT`, right after the existing ESP32/ESP32-S31 entity-
matching caution — instructs the model to check, for a causal/
dependency claim specifically, whether the passage actually STATES the
relationship rather than merely mentioning both things in a way that's
consistent with it. No new return value, no claim-type classifier added
in code (same "ask the model, don't pre-filter with a keyword list"
reasoning the entity-matching fix already established). 11 new offline
tests in the new `tests/test_retrieval_stance.py` (judge_stance()'s own
parsing contract, both fix paragraphs' guidance text locked in place
against accidental removal, and the Wiesner/BB84 shape scripted through
a fake client).

**The model-routing question, raised alongside the fix:** the finding's
own §0 text noted that asking Nemotron Ultra directly (outside this
pipeline) got the Wiesner/BB84 distinction right. A live paired test
(same fixed prompt, same real claim/passage pair) found gpt-oss-120b
(research_web's own default) returned "supports" — still wrong — while
Nemotron Ultra returned "unrelated", correctly. Per this project's own
`NEMOTRON_PIVOT_REPORT.md` standard (n=1 is not a conclusion), this was
escalated before any code changed:
- A 5-pair BALANCED live sample (3 "should be unrelated" co-occurrence-
  only pairs including the real Wiesner/BB84 case, 2 "should be
  supports" explicit-assertion pairs, covering different relation verbs)
  — both models scored 5/5. This matters because a model that just says
  "unrelated" to everything would trivially "win" a sample skewed toward
  negative cases without being more correct (the exact failure mode
  `NEMOTRON_PIVOT_REPORT.md` already documented for the Nemotron
  Lightning tier: "extremely safe but extremely unhelpful").
- The balanced sample alone didn't explain the one real disagreement, so
  the Wiesner/BB84 pair specifically was repeated 4 more times per
  model. **Reproducible result: gpt-oss-120b correct only 2/6 times
  total on this one genuinely borderline pair (coin-flip-ish, biased
  toward the wrong answer); Nemotron Ultra correct 5/5 times total.**
  The gap is specific to genuinely borderline causal/relational
  judgments, not a general difference between the models (both tied on
  every easier pair).
- **Decision: `research_web.py`'s `judge_stance()` calls now route to a
  separate, dedicated client on `RECOMMENDED_STANCE_MODEL`
  (`nvidia/Nemotron-3-Ultra-550b-a55b`, defined in `retrieval/stance.py`
  itself) — `propose()`/the live-search step stay on gpt-oss-120b**
  (`NEMOTRON_PIVOT_REPORT.md` already found it strictly better there at
  full-pipeline scale; nothing in this round's evidence says otherwise).
  `ResearchWebAdapter.__init__` gained a `stance_client` param,
  defaulting to the SAME object as `client` when a caller explicitly
  injects one — every existing test's single fake client keeps working
  unchanged; only `default_domains()`'s real, no-arg construction
  actually gets two different real clients. `robotics.py`'s own
  `ROBOTICS_MODEL` already happens to equal `RECOMMENDED_STANCE_MODEL`
  (for its own, broader, pre-existing reasons) — not imported from
  there, to avoid coupling two adapters' otherwise-independent model
  choices to one shared constant for what is, for `robotics.py`, a
  coincidence. 6 new offline tests in
  `tests/test_research_web_stance_routing.py` (two different real
  clients when nothing is injected; a single injected fake still
  handles both prompt shapes; two injected fakes are routed correctly;
  a broken stance client is a named per-source gap that doesn't block
  `propose()`).

**Honest note from the live end-to-end re-test:** re-running the exact
sub-claim through the REAL engine (live search, not the isolated
`judge_stance()` call) found a DIFFERENT source this time — Wikipedia's
"Timeline of cryptography" — whose own text states "Based on Stephen
Wiesner's idea ... Bennett and Brassard design ... BB84." That IS an
explicit causal assertion, so a `CONFIRMED` verdict on THAT passage is
correct, not a regression — live search results vary run to run (the
same documented caveat this project's test suite already carries
elsewhere). This surfaces a genuine, separate fact: real sources
disagree on whether BB84 was "based on" Wiesner's work or an
independent rediscovery later credited to him (Wikipedia's own timeline
page asserts the former; Brassard's own retrospectives lean toward the
latter) — this claim's ground truth is itself contested among reliable
sources, not something this fix is expected to resolve. Flagged here,
not silently absorbed into "the fix worked" or "the fix failed" —
exactly the kind of case `claude/ANTI_CASSIOPEIA_COMPETITIVE_BENCHMARK_PROTOCOL.md`'s
category 1 exists to probe at proper scale across many claims, not just
this one.

## Hybrid retrieval (BM25 + vector), ported from Constellation

Built per `claude/ANTI_CASSIOPEIA_HYBRID_RETRIEVAL_BUILD_PROMPT.md`, in
direct response to competitive-benchmark round 1's own finding: 3
conservative misses and one dangerously-soft conspiracy verdict, all
traced to BM25 finding nothing when a claim is phrased in different
words than its best source — a gap BM25 structurally cannot close,
regardless of tuning.

**Ported, not invented**: `retrieval/hybrid.py`'s `HybridIndex`/
`VectorIndex`/`rrf_fuse()` are a direct port of the sibling project
`eclipse-constellation`'s own already-evaluated `HybridRetriever`/
`VectorIndex` (RRF, k=60, the same standard constant, not re-tuned).
`NebiusTokenFactoryClient.embed()` uses the same `Qwen/Qwen3-Embedding-8B`
model and the same OpenAI-compatible `/embeddings` shape Constellation's
own client already proved works on this provider — confirmed live
against THIS account's own `GET /v1/models`, not assumed from
Constellation's choice (a separate project, separate account).

**Two integration points, deliberately different shapes** (per the
build spec's own §2): `robotics.py`'s BYOE/pooled paths build a
`HybridIndex` over the uploaded document(s)' chunks (closer to a direct
`HybridRetriever` port); `research_web.py`'s multi-candidate path embeds
the query plus that claim's freshly-fetched passages, RRF-fuses against
the BM25 ranking already happening over them, then discards — no
persistent index, since there's no persistent corpus to index.

**Honest degradation, both at index time and query time,
independently**: `embed()` catches `NebiusClientError` (a live failure)
AND `AttributeError`/`TypeError` (a client that doesn't implement
`embed()` at all — every existing offline test fake in this repo is
exactly this shape) — either way, `HybridSearchResult.methods` records
which method(s) actually ran, and a vector-less result is byte-for-byte
the same ranking `BM25Index.search()` already produced before this
build. 20+14+4+3 = new offline tests across `test_llm_nebius_client.py`
(embed()'s own contract), `test_retrieval_hybrid.py` (RRF fusion,
`VectorIndex`, degradation at both index and query time, the `mode=`
eval-only isolation parameter), and `test_hybrid_retrieval_integration.py`
(proving each domain adapter's wiring genuinely calls `embed()`, not
just that degradation-with-no-embedder still works).

**New honest limitation this build introduces** (see
`retrieval/__init__.py`'s own updated docstring): there is still no
persistent embedding — or chunk, or BM25 index — cache anywhere in this
codebase. Every hybrid-search call re-chunks AND re-embeds its source
text from scratch, same as BM25 already re-chunked and re-indexed on
every call before this build existed. Querying the same uploaded
document twice re-embeds it twice, at real added cost and latency. A
persistent per-document cache keyed off `UploadStore`'s own
`document_id` would close this — a real, separate architecture
decision, named here for a future round, not hidden.

**Real eval numbers** (`evals/retrieval/`, 13 hand-labelled questions
across 6 real documents, live `Qwen/Qwen3-Embedding-8B` — see
`evals/retrieval/RESULTS.md` for the full table and honest reading):
on questions deliberately paraphrased away from their source wording,
pure vector search has the best R@1 (0.50 vs. BM25's 0.36) — confirming
the core hypothesis. Fused hybrid's own R@1 on those same paraphrased
questions is, surprisingly, WORSE than either pure method alone (0.21)
— reported as a real, measured, counterintuitive result, not smoothed
over or tuned away on an N=7 sample. At R@3/hit@3 — the metric that
actually matches how this pipeline uses retrieval (a top-k candidate
list shown to `propose()`, never a blind trust of rank #1) — hybrid and
vector both beat BM25 on paraphrased questions (0.86 vs. 0.79) and tie
it on keyword-overlap questions (0.83 all three). **This is the build's
real, defensible result: hybrid never makes recall-at-the-metric-that-
matters worse, and measurably improves it for paraphrased claims** —
not a universal "hybrid beats BM25" claim, which this sample is too
small to support.

**Live re-test of round 1's own failing claims** (§4.3 of the build
spec), against the real `ResearchWebAdapter` with hybrid retrieval now
live: **3 of 4 are now fixed.** The ARPANET "LOGIN" claim now correctly
`CONFIRMED` (1.0 confidence, 2 real sources). The moon-landing
conspiracy claim now correctly `CONTRADICTED` (0.90) on a REAL
authoritative source (Wikipedia's own moon-landing-conspiracy-theories
page, "regarded as pseudoscience and demonstrably false") — replacing
round 1's fortuitous-but-weak fictional-movie-quote evidence entirely.
The sunglasses/cancer fact-check claim now correctly `CONTRADICTED`
(1.0 confidence, 3 real Full Fact sources). The 4th (the SpaceX viral-
video claim) is still `UNDETERMINED` — but retrieval itself clearly
improved: it now finds 4 real, topically-relevant sources (EarthSky,
Wikipedia's own "2026 SpaceX lunar impact" page, BBC) where round 1
found zero usable passages; the remaining gap is that those sources
address the real underlying lunar-impact event, not the specific
claim's nuance about one particular video being fake — a different,
more subtle limitation than the original verbatim-query retrieval gap,
not something this build claims to have also fixed.

## Open design decisions (not yet made)

- Evidence retrieval inside each domain adapter: web search? local
  datasheet index? direct API calls (synthesis tool output, dataset
  files)? Each domain will likely need a different answer.
- Scoring: the current trust-weighted threshold rule in `engine.py` is a
  placeholder, not a researched method. Revisit once real evidence from at
  least one real domain is flowing through it.
