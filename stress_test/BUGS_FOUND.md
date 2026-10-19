# Bugs found by Stress Test #1

Real bugs discovered while running real claims through the production
pipeline (`anticassiopeia/`, used read-only — nothing here was fixed
inline, per this task's own instruction; fixing is a separate, later,
user-decided task). Each entry: what claim, what happened, what should
have happened instead. Entries below this line are appended automatically
by `run_test1.py` for every "dangerous" or "crash" result; nothing here
is hand-edited to look better than what actually ran.

## Found during manifest generation/validation (before the pilot run): `ml_data.py` does not filter non-finite (NaN/Infinity) values

**What claim:** Any claim against `stress_test/data/ml_data/auto_mpg.csv`'s
`horsepower` column — e.g. `{"dataset_path": ".../auto_mpg.csv", "column":
"horsepower", "stat": "stdev", ...}` (claim_id `ml_data-001012` in the
pre-fix manifest; regenerated after the fix below so that exact id no
longer points at a NaN-valued claim, but the underlying file/column is
unchanged and still real).

**What happened:** UCI's real `auto_mpg.csv` (fetched live from
`archive.ics.uci.edu`, not synthetic — see PROVENANCE.md) spells 6 missing
`horsepower` readings as the literal string `"NaN"`, not `"?"` or empty.
`anticassiopeia/domains/ml_data.py`'s `_read_column()` parses cells with
a bare `try: float(raw) except (TypeError, ValueError)` guard — but
`float("NaN")` and `float("inf")`/`float("-inf")` all succeed in Python
(they don't raise), so these 6 values are silently included in `values`
as real IEEE NaN, not filtered out the way an actually-non-numeric cell
(empty string, text) correctly is. Traced the exact real downstream
effect per statistic, using production's own exact code path against the
real data (`statistics.<func>([float(r['horsepower']) for r in rows])`):

| stat | production's actual result | correct result (NaN rows excluded, n=392) | effect |
|---|---|---|---|
| `mean` | `nan` | `104.469...` | **silent wrong answer** — `nan <= tolerance` is always `False` in Python, so any mean-based claim on this column always resolves `contradicts`, even a genuinely true one |
| `median` | `115.0` | `93.5` | **silent wrong answer** — a real, different, plausible-looking number, not even a NaN flag to notice |
| `p25` / `p75` | `58.5` / `90.5` | `75.0` / `128.0` | **silent wrong answer**, same mechanism (`statistics.quantiles()` sorts with NaN present — comparison with NaN is undefined, so sort order, and the quantile read off it, is wrong but not obviously so) |
| `correlation` | `nan` | `0.8645...` | **silent wrong answer**, same `nan <=` issue as mean |
| `stdev` | **raises `ValueError: inf or nan encountered in data`, uncaught** | `38.491...` | **crash** — propagates straight out of `MLDataAdapter.gather_evidence()`, out of `VerificationEngine.verify()`, out of a real `/verify` API call, with no named gap and no graceful UNDETERMINED |
| `min` / `max` | `46.0` / `230.0` | `46.0` / `230.0` | happens to be unaffected here — Python's built-in `min()`/`max()` comparisons against `nan` are always `False`, so `nan` never "wins," but this is incidental to CPython's comparison behavior, not a property the adapter deliberately relies on or tests for |

**What should have happened:** the SAME thing `_read_column()` already
does for a cell that fails `float()` outright (an empty string, "N/A",
text) — treat a non-finite parse as "not a numeric value for this row,"
excluded from `values` and counted toward `bad_rows`, never silently
degrading a real computation into `nan` or crashing a stdlib call three
functions later. The fix (not applied here, per this task's instruction)
is likely a one-line change to `_read_column`/`_read_column_pair`: after
`float(raw)`, also require `math.isfinite(...)`, else treat it the same
as the existing `except (TypeError, ValueError)` branch.

**Scope check:** confirmed this is specific to this one real file/column
in the current data pool — swept all 14 real UCI files' numeric columns
for non-finite values; `auto_mpg.csv`'s `horsepower` (6 rows) is the only
one affected. Fixed in `stress_test/oracles/ml_data_oracle.py` (this
project's OWN harness code, not production) so the manifest's ground
truth for horsepower claims is the correct NaN-excluded value — meaning
the regenerated manifest's horsepower claims now correctly expect
production to get them wrong (silent wrong answer or crash, per the
table above), and the pilot/full run will surface exactly that as
"dangerous" or "crash" results, not something hidden by a bad oracle.

**FIXED (2026-10-18).** `anticassiopeia/domains/ml_data.py`'s `_read_column()`
and `_read_column_pair()` now require `math.isfinite(value)` after
`float(raw)` succeeds; a non-finite parse is treated exactly like the
existing `except (TypeError, ValueError)` branch — excluded from
`values`, counted toward `bad_rows`. Re-verified against the real,
unmodified `auto_mpg.csv` (copied into `evals/fixtures/auto_mpg.csv` for
the production test suite): `mean`/`median`/`p25`/`p75`/`stdev`/
`correlation` on the `horsepower` column now all give the correct,
NaN-excluded values from the table above (104.469/93.5/75.0/128.0/
38.491/0.8645) and `stdev` no longer raises. 5 new tests added to
`tests/test_domains_ml_data.py`, plus one explicit regression test
proving a column with zero non-finite values is byte-for-byte unaffected
by the fix. All 22 tests in that file pass.

## Batch `full` — 17 dangerous/crash result(s) found

### ml_data-000924 (ml_data, tier 1)
- Claim: `{"text": "mean(horsepower) in auto_mpg.csv is 104.469", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "mean", "expected_value": 104.46938775510205, "tolerance": 0.10446938775510205}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: ml_data_oracle.compute(): oracle_mean exact match

### ml_data-000926 (ml_data, tier 1)
- Claim: `{"text": "median(horsepower) in auto_mpg.csv is 93.5", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "median", "expected_value": 93.5, "tolerance": 0.0935}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: ml_data_oracle.compute(): oracle_median exact match

### ml_data-000928 (ml_data, tier 1)
- Claim: `{"text": "p25(horsepower) in auto_mpg.csv is 75", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "p25", "expected_value": 75.0, "tolerance": 0.075}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: ml_data_oracle.compute(): oracle_p25 exact match

### ml_data-000929 (ml_data, tier 1)
- Claim: `{"text": "p75(horsepower) in auto_mpg.csv is 128", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "p75", "expected_value": 128.0, "tolerance": 0.128}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: ml_data_oracle.compute(): oracle_p75 exact match

### ml_data-000932 (ml_data, tier 2)
- Claim: `{"text": "mean(horsepower) in auto_mpg.csv is 101.858", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "mean", "expected_value": 101.8576530612245, "tolerance": 5.223469387755102}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: ml_data_oracle.compute(): mean within a deliberately wide 5% tolerance window

### ml_data-000934 (ml_data, tier 3)
- Claim: `{"text": "mean(horsepower) in auto_mpg.csv is 104.574", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "mean", "expected_value": 104.5737526734694, "tolerance": 0.10446938775510205}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: ml_data_oracle.compute(): diff deliberately just inside the tolerance boundary (0.999x)

### ml_data-000936 (ml_data, tier 1)
- Claim: `{"text": "stdev(horsepower) in auto_mpg.csv is 38.4912", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "stdev", "expected_value": 38.49115993282849, "tolerance": 0.03849115993282849}}`
- Predicted: **CRASH**, ground truth: **confirmed** (crash)
- Ground truth method: ml_data_oracle.compute(): oracle_stdev exact match
- Error: `ValueError: inf or nan encountered in data`

### ml_data-000937 (ml_data, tier 1)
- Claim: `{"text": "stdev(horsepower) in auto_mpg.csv is 77.9823", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "stdev", "expected_value": 77.98231986565698, "tolerance": 0.03849115993282849}}`
- Predicted: **CRASH**, ground truth: **contradicted** (crash)
- Ground truth method: ml_data_oracle.compute(): oracle_stdev, expected deliberately off
- Error: `ValueError: inf or nan encountered in data`

### ml_data-001014 (ml_data, tier 2)
- Claim: `{"text": "horsepower in auto_mpg.csv: mean is 104.469 AND stdev is 38.4912", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "checks": [{"stat": "mean", "expected_value": 104.46938775510205, "tolerance": 0.10446938775510205}, {"stat": "stdev", "expected_value": 38.49115993282849, "tolerance": 0.03849115993282849}]}}`
- Predicted: **CRASH**, ground truth: **confirmed** (crash)
- Ground truth method: ml_data_oracle, compound AND: both sub-checks genuinely hold
- Error: `ValueError: inf or nan encountered in data`

### ml_data-001015 (ml_data, tier 2)
- Claim: `{"text": "horsepower in auto_mpg.csv: mean is 104.469 AND stdev is 116.473", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "checks": [{"stat": "mean", "expected_value": 104.46938775510205, "tolerance": 0.10446938775510205}, {"stat": "stdev", "expected_value": 116.47347979848547, "tolerance": 0.03849115993282849}]}}`
- Predicted: **CRASH**, ground truth: **contradicted** (crash)
- Ground truth method: ml_data_oracle, compound AND: mean holds, stdev sub-check deliberately false
- Error: `ValueError: inf or nan encountered in data`

### ml_data-001016 (ml_data, tier 2)
- Claim: `{"text": "horsepower in auto_mpg.csv: mean is 213.939 AND stdev is 38.4912", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "checks": [{"stat": "mean", "expected_value": 213.9387755102041, "tolerance": 0.10446938775510205}, {"stat": "stdev", "expected_value": 38.49115993282849, "tolerance": 0.03849115993282849}]}}`
- Predicted: **CRASH**, ground truth: **contradicted** (crash)
- Ground truth method: ml_data_oracle, compound AND: mean sub-check deliberately false, stdev holds
- Error: `ValueError: inf or nan encountered in data`

### ml_data-001034 (ml_data, tier 2)
- Claim: `{"text": "correlation between horsepower and weight in auto_mpg.csv is 0.8645", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "column_b": "weight", "stat": "correlation", "expected_value": 0.8645377375741444, "tolerance": 0.01}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: ml_data_oracle.oracle_correlation() on real paired columns

### robotics-002960 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 185 m depth", "domain": "robotics", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: independently reasoned: DOC1=300m (trust 0.8), DOC2=100m (trust 0.7), engine DECISION_THRESHOLD=0.5/MIN_EVIDENCE_WEIGHT=0.3 (both are this project's own documented, public constants, not internal adapter logic)

### robotics-002966 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 200 m depth", "domain": "robotics", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: independently reasoned: DOC1=300m (trust 0.8), DOC2=100m (trust 0.7), engine DECISION_THRESHOLD=0.5/MIN_EVIDENCE_WEIGHT=0.3 (both are this project's own documented, public constants, not internal adapter logic)

### robotics-002978 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 230 m depth", "domain": "robotics", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: independently reasoned: DOC1=300m (trust 0.8), DOC2=100m (trust 0.7), engine DECISION_THRESHOLD=0.5/MIN_EVIDENCE_WEIGHT=0.3 (both are this project's own documented, public constants, not internal adapter logic)

### robotics-002989 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 255 m depth", "domain": "robotics", "context": {}}`
- Predicted: **confirmed**, ground truth: **undetermined** (dangerous)
- Ground truth method: independently reasoned: DOC1=300m (trust 0.8), DOC2=100m (trust 0.7), engine DECISION_THRESHOLD=0.5/MIN_EVIDENCE_WEIGHT=0.3 (both are this project's own documented, public constants, not internal adapter logic)

### robotics-003006 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 300 m depth", "domain": "robotics", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: independently reasoned: DOC1=300m (trust 0.8), DOC2=100m (trust 0.7), engine DECISION_THRESHOLD=0.5/MIN_EVIDENCE_WEIGHT=0.3 (both are this project's own documented, public constants, not internal adapter logic)

## Root cause analysis: the 5 `robotics` dangerous results above (new finding, distinct from the §4.5 `kind`-field issue)

All 5 are BlueROV2 claims with a claimed depth in the genuine 100-300m
conflict zone, where DOC1 (300m Aluminum rating) and DOC2 (100m rating)
*should* disagree and correctly produce `UNDETERMINED` — exactly the
behavior `evals/cases/robotics/bluerov2_200m_conflict_undetermined.json`
already tests and expects. Investigated by re-running the EXACT same
claim (`"BlueROV2 survives 200 m depth"`) live, repeatedly, through the
real adapter:

- `RoboticsAdapter().gather_evidence()`, 10 live trials: **9/10** correctly
  returned both pieces of evidence (DOC1 `supports`, DOC2 `contradicts`,
  as documented). **1/10 returned ONLY DOC2's evidence** — DOC1's evidence
  was silently absent that one time (no error, `gather_evidence()` simply
  didn't include it — consistent with the model, on that one call,
  reporting the DOC1 fact as honestly "not found" even though it's
  genuinely in the corpus and was found correctly the other 9 times).
- Isolated `extract.propose()` calls against DOC1 alone, 10 live trials,
  same question text robotics.py actually uses
  (`"maximum rated depth aluminum acrylic housing"`): **10/10** correctly
  cited `"Maximum Rated Depth (Aluminum): 300 m"`. So it isn't that DOC1's
  fact is hard to extract in isolation — the drop happens at a LOWER rate
  when it happens at all, consistent with genuine but infrequent live-call
  non-determinism, not a deterministic flaw in the question text itself.
- Confirmed the downstream mechanism is exactly what you'd expect once
  DOC1's evidence is missing: `engine.py`'s scoring sees only DOC2's
  single `contradicts` (trust 0.7) piece — weight 0.7 clears
  `MIN_EVIDENCE_WEIGHT` (0.3) and `DECISION_THRESHOLD` (0.5) on its own,
  so the engine (correctly, given what it was handed) renders a confident
  `CONTRADICTED` instead of ever seeing the conflict that should have
  produced `UNDETERMINED`.

**Why this is worse than the already-known, already-documented single-source
non-determinism** (robotics.py's module docstring, §4.1/§4.5, about the
`kind` field): that issue's failure direction was safe — an unlucky draw
fell through to an honest `UNDETERMINED` gap. This one's failure
direction is NOT safe: losing just ONE of two genuinely-conflicting
sources doesn't just lose information, it actively REMOVES the signal
that should have triggered the conflict-detection path, flipping the
verdict to confidently wrong. This is new, not a recurrence of a
documented limitation, and specific to multi-source conflict claims
(nothing in the existing eval suite exercises this scenario repeatedly
enough to have caught it before — `bluerov2_200m_conflict_undetermined.json`
is run once per `evals/run_evals.py` invocation, not resampled).

**What should have happened:** `UNDETERMINED`, every time, for any depth
in (100m, 300m] — the same genuine two-source disagreement the existing
eval case already covers. **Estimated rate from this run:** 5 dangerous
results out of roughly 40 BlueROV2 conflict-zone claims in the manifest
(100-300m range, 5m steps, both claim-polarities) — call it in the
rough ballpark of 1 in 8, consistent with the ~1-in-10 single-call drop
rate observed directly above landing on the "only one of two sources
drops out" case somewhat more or less often than that per-call rate,
given two independent draws per claim.

## CORRECTION (2026-10-18) — the root-cause analysis above was incomplete; the dominant cause is query ambiguity, not absence

The "Root cause analysis" section directly above this one (written right
after the stress test) characterized the 5 `robotics` dangerous results as
"~1-in-10... silently return no evidence." That mechanism is real — the
retry fix below does fix it, and a fake-client test proves it — but it is
NOT the dominant cause of the dangerous conflict-zone verdicts. This entry
corrects the record; the original entry above is left as-is, unedited, not
deleted, per this project's own "found bugs stay visible" premise.

**What the original 10-sample characterization missed:** the original
investigation ran `gather_evidence()` 10 times and saw ONE case where
DOC1's evidence was entirely absent, and separately ran `engine.verify()`
5 times and saw ONE case where DOC1's evidence was present but with the
WRONG stance ("contradicts" instead of "supports"). Both were reported as
consistent with "evidence missing," but they are NOT the same mechanism —
the second one is a proposal that IS present, just about a different real
fact. The 10-sample size on each check was too small to tell these apart
cleanly, and the writeup generalized from the absence case without
separately investigating the stance-flip case.

**What a 20-trial direct diagnostic of DOC1's query actually showed:**
DOC1's corpus excerpt (`anticassiopeia/corpus/doc1_bluerov2_excerpt.txt`)
states TWO different real depth ratings: `"Maximum Rated Depth (Acrylic):
100 m"` and `"Maximum Rated Depth (Aluminum): 300 m"`. The retrieval
query robotics.py used, `"maximum rated depth aluminum acrylic housing"`,
asks about BOTH materials in one question. Looping the real `propose()`
call against this exact query 20 times: **8 of 20 (40%)** cited the
Acrylic line instead of the Aluminum line — not a rare fluke, and not the
model being unreliable; it was honestly answering a genuinely ambiguous
question, and both answers are real, verified-via-`verify_proposal()`
quotes from the same real chunk. This 40% rate is the DOMINANT cause of
the dangerous verdicts the stress test found; the ~10% pure-absence case
documented above is real but secondary.

**Why this matters for the fix:** the retry-on-absence logic
(`_propose_with_retry`, described below) only retries when `propose()`
returns `None`. It does nothing for this case, because the model always
returns a valid, non-`None`, verified proposal — just sometimes about the
wrong material. Confirmed directly: after implementing ONLY the retry
fix, a live 30-run resample of the exact conflict-zone claim
(`"BlueROV2 survives 200 m depth"`) still failed on run 1 (`ValueError`-free,
a confident `contradicted` where the truth is `undetermined`), with BOTH
DOC1 and DOC2 evidence showing stance `contradicts` — the Acrylic-citation
pattern, not absence.

**The actual fix for this part:** `_RETRIEVAL_QUERIES["bluerov2"]["DOC1_BlueROV2"]`
changed from `"maximum rated depth aluminum acrylic housing"` to
`"maximum rated depth aluminum housing"` (dropping "acrylic" entirely).
Checked first whether anything legitimately depended on DOC1 citing the
Acrylic line via this query before changing it: `evals/cases/robotics/bluerov2_500m.json`
mentions the Acrylic rating only in its `note` field as background (its
`contradicted` verdict holds at 500m regardless of which of DOC1's two
real lines gets cited), and the `stress_test/claims/manifest.jsonl`
ground-truth model already assumed DOC1=300m (Aluminum) throughout — so
nothing broke, and the fix makes MORE of the manifest's claims resolve
correctly, not fewer. `docs/extracted/constellation-robotics-seed.md`
§1.1 already documents DOC1 as this project's source for the Aluminum
figure specifically ("best-case figure... aluminum tube, 300 m, DOC1
only") — the query now matches that documented intent.

**Re-verified live, twice, independently:** the disambiguated query alone,
20/20 trials, always retrieved the Aluminum line
(`test_live_doc1_aluminum_query_retrieves_the_aluminum_line_every_time`,
25 trials in the committed test). The full conflict-zone claim with BOTH
fixes in place (retry + disambiguated query), 30/30 trials, always
resolved `UNDETERMINED`
(`test_live_conflict_zone_claim_resolves_undetermined_every_time_not_just_usually`).

**Status: both the absence case (retry, ~10% -> ~0.1%) and the dominant
query-ambiguity case (disambiguated query, ~40% -> 0% in 20/20 + 25/25
live samples) are now fixed. Neither fix alone was sufficient; both are
needed and both are in place.**

## Test #2 bare-Nebius batch `pilot` — 3 dangerous/crash result(s) (baseline, not a pipeline bug)

### research_web-003300 (research_web, tier 1)
- Claim: `{"text": "The first Beagle Board was released in 2008", "domain": "research_web", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### research_web-003290 (research_web, tier 3)
- Claim: `{"text": "BlueROV2 has a maximum operating time of 14 hours", "domain": "research_web", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002928 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 105 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)


## Test #2 bare-Nebius batch `full` — 41 dangerous/crash result(s) (baseline, not a pipeline bug)

### ml_data-000091 (ml_data, tier 1)
- Claim: `{"text": "min(PT08.S3(NOx)) in air_quality.csv is -200", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "PT08.S3(NOx)", "stat": "min", "expected_value": -200.0, "tolerance": 1e-09}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000420 (ml_data, tier 1)
- Claim: `{"text": "min(Concrete compressive strength) in concrete_compressive_strength.csv is 2.33", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Concrete compressive strength", "stat": "min", "expected_value": 2.33, "tolerance": 1e-09}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000576 (ml_data, tier 1)
- Claim: `{"text": "min(pH) in wine_quality.csv is 2.72", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "pH", "stat": "min", "expected_value": 2.72, "tolerance": 1e-09}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000988 (ml_data, tier 2)
- Claim: `{"text": "mean(origin) in auto_mpg.csv is 1.53354", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "origin", "stat": "mean", "expected_value": 1.5335427135678392, "tolerance": 0.07864321608040202}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001002 (ml_data, tier 2)
- Claim: `{"text": "mean(mpg) in auto_mpg.csv is 22.9267", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "mpg", "stat": "mean", "expected_value": 22.926708542713566, "tolerance": 1.1757286432160805}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001080 (ml_data, tier 1)
- Claim: `{"text": "mean(Whole_weight) in abalone.csv is 0.828742", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Whole_weight", "stat": "mean", "expected_value": 0.8287421594445774, "tolerance": 0.0008287421594445774}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001320 (ml_data, tier 1)
- Claim: `{"text": "mean(area) in forest_fires.csv is 12.8473", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "area", "stat": "mean", "expected_value": 12.847292069632495, "tolerance": 0.012847292069632496}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001731 (ml_data, tier 1)
- Claim: `{"text": "median(frequency) in airfoil_self_noise.csv is 1600", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "frequency", "stat": "median", "expected_value": 1600.0, "tolerance": 1.6}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001734 (ml_data, tier 1)
- Claim: `{"text": "p75(frequency) in airfoil_self_noise.csv is 4000", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "frequency", "stat": "p75", "expected_value": 4000.0, "tolerance": 4.0}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001741 (ml_data, tier 1)
- Claim: `{"text": "stdev(frequency) in airfoil_self_noise.csv is 3152.57", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "frequency", "stat": "stdev", "expected_value": 3152.5731369306686, "tolerance": 3.152573136930669}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001750 (ml_data, tier 1)
- Claim: `{"text": "max(attack-angle) in airfoil_self_noise.csv is 22.2", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "attack-angle", "stat": "max", "expected_value": 22.2, "tolerance": 1e-09}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001767 (ml_data, tier 3)
- Claim: `{"text": "mean(chord-length) in airfoil_self_noise.csv is 0.136685", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "chord-length", "stat": "mean", "expected_value": 0.13668464854823684, "tolerance": 0.0001365482368596141}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001769 (ml_data, tier 1)
- Claim: `{"text": "stdev(chord-length) in airfoil_self_noise.csv is 0.0935407", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "chord-length", "stat": "stdev", "expected_value": 0.09354072837396629, "tolerance": 9.35407283739663e-05}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001776 (ml_data, tier 1)
- Claim: `{"text": "p75(free-stream-velocity) in airfoil_self_noise.csv is 71.3", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "free-stream-velocity", "stat": "p75", "expected_value": 71.3, "tolerance": 0.0713}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001805 (ml_data, tier 1)
- Claim: `{"text": "min(scaled-sound-pressure) in airfoil_self_noise.csv is 103.38", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "scaled-sound-pressure", "stat": "min", "expected_value": 103.38, "tolerance": 1e-09}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002294 (ml_data, tier 1)
- Claim: `{"text": "p75(test_time) in parkinsons_telemonitoring.csv is 138.46", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/parkinsons_telemonitoring.csv", "column": "test_time", "stat": "p75", "expected_value": 138.46, "tolerance": 0.13846}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### research_web-003290 (research_web, tier 3)
- Claim: `{"text": "BlueROV2 has a maximum operating time of 14 hours", "domain": "research_web", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### research_web-003293 (research_web, tier 3)
- Claim: `{"text": "ArduPilot has over 10 million lines of code", "domain": "research_web", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002928 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 105 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002932 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 115 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002942 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 140 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002946 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 150 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002950 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 160 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002954 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 170 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002960 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 185 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002962 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 190 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002966 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 200 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002973 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 215 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002975 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 220 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **confirmed**, ground truth: **undetermined** (dangerous)

### robotics-002978 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 230 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002984 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 245 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002988 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 255 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002989 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 255 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002992 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 265 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002997 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 275 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **confirmed**, ground truth: **undetermined** (dangerous)

### robotics-003007 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 300 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **confirmed**, ground truth: **undetermined** (dangerous)

### robotics-003115 (robotics, tier 2)
- Claim: `{"text": "Bar30 fails at 75 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### robotics-003202 (robotics, tier 3)
- Claim: `{"text": "Bar30 survives 295 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **confirmed**, ground truth: **undetermined** (dangerous)

### robotics-003208 (robotics, tier 3)
- Claim: `{"text": "Bar30 survives 310 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-003231 (robotics, tier 2)
- Claim: `{"text": "Bar30 fails at 365 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### robotics-003239 (robotics, tier 2)
- Claim: `{"text": "Bar30 fails at 385 m depth", "domain": "robotics", "context": {}}`
- Bare-Nebius predicted: **contradicted**, ground truth: **confirmed** (dangerous)


## Test #3 Perplexity batch `smoke` — 1 dangerous/crash result(s) (external API baseline; not a pipeline bug)

### robotics-003051 (robotics, tier 2)
- Claim: `{"text": "BlueROV2 fails at 410 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **confirmed** (dangerous)


## Test #3 Tavily+Gemini batch `smoke` — 1 dangerous/crash result(s) (external API baseline; not a pipeline bug)

### ml_data-001914 (ml_data, tier 1)
- Claim: `{"text": "max(TIT) in gas_turbine_emission.csv is 1100.9", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "TIT", "stat": "max", "expected_value": 1100.9, "tolerance": 1e-09}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)


## Test #3 generic-RAG batch `pilot` — 4 dangerous/crash result(s) (a naive off-the-shelf-style baseline; not a pipeline bug)

### ml_data-000027 (ml_data, tier 1)
- Claim: `{"text": "stdev(PT08.S1(CO)) in air_quality.csv is 329.833", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "PT08.S1(CO)", "stat": "stdev", "expected_value": 329.83270988618807, "tolerance": 0.32983270988618807}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000037 (ml_data, tier 2)
- Claim: `{"text": "mean(NMHC(GT)) in air_quality.csv is -163.067", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "NMHC(GT)", "stat": "mean", "expected_value": -163.06734530298172, "tolerance": 7.954504648925938}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000039 (ml_data, tier 3)
- Claim: `{"text": "mean(NMHC(GT)) in air_quality.csv is -158.931", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "NMHC(GT)", "stat": "mean", "expected_value": -158.93116197563322, "tolerance": 0.15909009297851875}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### robotics-002931 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 110 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)


## Test #3 Perplexity batch `pilot` — 2 dangerous/crash result(s) (external API baseline; not a pipeline bug)

### research_web-003290 (research_web, tier 3)
- Claim: `{"text": "BlueROV2 has a maximum operating time of 14 hours", "domain": "research_web", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### research_web-003293 (research_web, tier 3)
- Claim: `{"text": "ArduPilot has over 10 million lines of code", "domain": "research_web", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)


## Test #3 Tavily+Gemini batch `pilot` — 15 dangerous/crash result(s) (external API baseline; not a pipeline bug)

### fpga_embedded-002508 (fpga_embedded, tier 1)
- Claim: `{"text": "jiwoonl__timing.txt: wns_ns <= -1.159", "domain": "fpga_embedded", "context": {"report_path": "stress_test/data/fpga_embedded/jiwoonl__timing.txt", "metric": "wns_ns", "comparator": "<=", "expected_value": -1.159}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `TavilyGeminiError: Gemini returned 503: {
  "error": {
    "code": 503,
    "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.",
    "status": "UNAVAILABLE"
  }
}
`

### fpga_embedded-002523 (fpga_embedded, tier 1)
- Claim: `{"text": "jiwoonl__timing.txt: whs_ns <= 0.058", "domain": "fpga_embedded", "context": {"report_path": "stress_test/data/fpga_embedded/jiwoonl__timing.txt", "metric": "whs_ns", "comparator": "<=", "expected_value": 0.058}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash\nPlease retry in 44.633446332s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "5"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "44s"
      }
    ]
  }
}
`

### ml_data-000042 (ml_data, tier 1)
- Claim: `{"text": "stdev(NMHC(GT)) in air_quality.csv is 280.578", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "NMHC(GT)", "stat": "stdev", "expected_value": 280.5781857935629, "tolerance": 0.13978909289678146}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash\nPlease retry in 115.067916ms.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "model": "gemini-3.8-flash",
              "location": "global"
            },
            "quotaValue": "5"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "0s"
      }
    ]
  }
}
`

### research_web-003300 (research_web, tier 1)
- Claim: `{"text": "The first Beagle Board was released in 2008", "domain": "research_web", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash\nPlease retry in 56.937487644s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "model": "gemini-3.8-flash",
              "location": "global"
            },
            "quotaValue": "5"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "56s"
      }
    ]
  }
}
`

### research_web-003289 (research_web, tier 2)
- Claim: `{"text": "BlueROV2 was developed by OpenROV", "domain": "research_web", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash\nPlease retry in 53.955354503s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "5"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "53s"
      }
    ]
  }
}
`

### research_web-003290 (research_web, tier 3)
- Claim: `{"text": "BlueROV2 has a maximum operating time of 14 hours", "domain": "research_web", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **undetermined** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash\nPlease retry in 50.884708907s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "model": "gemini-3.8-flash",
              "location": "global"
            },
            "quotaValue": "5"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "50s"
      }
    ]
  }
}
`

### research_web-003306 (research_web, tier 1)
- Claim: `{"text": "STM32 is a family of ARM Cortex-M based microcontrollers made by STMicroelectronics", "domain": "research_web", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash\nPlease retry in 48.516958897s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "5"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "48s"
      }
    ]
  }
}
`

### research_web-003307 (research_web, tier 2)
- Claim: `{"text": "STM32 is a family of ARM Cortex-M based microcontrollers made by Microchip Technology", "domain": "research_web", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash\nPlease retry in 45.285994742s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "5"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "45s"
      }
    ]
  }
}
`

### research_web-003293 (research_web, tier 3)
- Claim: `{"text": "ArduPilot has over 10 million lines of code", "domain": "research_web", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **undetermined** (crash)
- Error: `TavilyGeminiError: Gemini returned 503: {
  "error": {
    "code": 503,
    "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.",
    "status": "UNAVAILABLE"
  }
}
`

### robotics-002903 (robotics, tier 2)
- Claim: `{"text": "BlueROV2 fails at 40 m depth", "domain": "robotics", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\nPlease retry in 5h47m26.030057108s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "20"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "20846s"
      }
    ]
  }
}
`

### robotics-002928 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 105 m depth", "domain": "robotics", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **undetermined** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\nPlease retry in 5h47m21.692444716s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "20"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "20841s"
      }
    ]
  }
}
`

### robotics-002898 (robotics, tier 1)
- Claim: `{"text": "BlueROV2 survives 30 m depth", "domain": "robotics", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\nPlease retry in 5h47m19.394456023s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "20"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "20839s"
      }
    ]
  }
}
`

### robotics-002905 (robotics, tier 2)
- Claim: `{"text": "BlueROV2 fails at 45 m depth", "domain": "robotics", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\nPlease retry in 5h47m16.765162087s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "20"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "20836s"
      }
    ]
  }
}
`

### robotics-002931 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 110 m depth", "domain": "robotics", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **undetermined** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\nPlease retry in 5h47m14.658818183s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.8-flash"
            },
            "quotaValue": "20"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "20834s"
      }
    ]
  }
}
`

### robotics-002904 (robotics, tier 1)
- Claim: `{"text": "BlueROV2 survives 45 m depth", "domain": "robotics", "context": {}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `TavilyGeminiError: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash\nPlease retry in 5h47m12.286365171s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "model": "gemini-3.8-flash",
              "location": "global"
            },
            "quotaValue": "20"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "20832s"
      }
    ]
  }
}
`


## Test #3 Tavily+Gemini batch `pilot` — 5 dangerous/crash result(s) (external API baseline; not a pipeline bug)

### ml_data-000022 (ml_data, tier 1)
- Claim: `{"text": "max(PT08.S1(CO)) in air_quality.csv is 2040", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "PT08.S1(CO)", "stat": "max", "expected_value": 2040.0, "tolerance": 1e-09}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### research_web-003290 (research_web, tier 3)
- Claim: `{"text": "BlueROV2 has a maximum operating time of 14 hours", "domain": "research_web", "context": {}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### research_web-003293 (research_web, tier 3)
- Claim: `{"text": "ArduPilot has over 10 million lines of code", "domain": "research_web", "context": {}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002928 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 105 m depth", "domain": "robotics", "context": {}}`
- Tavily+Gemini predicted: **confirmed**, ground truth: **undetermined** (dangerous)

### robotics-002931 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 110 m depth", "domain": "robotics", "context": {}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **undetermined** (dangerous)


## Test #3 generic-RAG batch `full` — 170 dangerous/crash result(s) (a naive off-the-shelf-style baseline; not a pipeline bug)

### fpga_embedded-002531 (fpga_embedded, tier 1)
- Claim: `{"text": "jiwoonl__timing.txt: ths_ns <= 0.001", "domain": "fpga_embedded", "context": {"report_path": "stress_test/data/fpga_embedded/jiwoonl__timing.txt", "metric": "ths_ns", "comparator": "<=", "expected_value": 0.001}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### fpga_embedded-002886 (fpga_embedded, tier 2)
- Claim: `{"text": "[SYNTHETIC] SLOW_MAX corner WNS clears 0.81 ns", "domain": "fpga_embedded", "context": {"report_path": "stress_test/data/fpga_embedded/SYNTHETIC_multi_corner.rpt", "metric": "wns_ns", "corner": "SLOW_MAX", "comparator": ">=", "expected_value": 0.8099999999999999}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000025 (ml_data, tier 3)
- Claim: `{"text": "mean(PT08.S1(CO)) in air_quality.csv is 1050.04", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "PT08.S1(CO)", "stat": "mean", "expected_value": 1050.0380019878166, "tolerance": 1.0489900609169607}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000027 (ml_data, tier 1)
- Claim: `{"text": "stdev(PT08.S1(CO)) in air_quality.csv is 329.833", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "PT08.S1(CO)", "stat": "stdev", "expected_value": 329.83270988618807, "tolerance": 0.32983270988618807}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000037 (ml_data, tier 2)
- Claim: `{"text": "mean(NMHC(GT)) in air_quality.csv is -163.067", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "NMHC(GT)", "stat": "mean", "expected_value": -163.06734530298172, "tolerance": 7.954504648925938}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000039 (ml_data, tier 3)
- Claim: `{"text": "mean(NMHC(GT)) in air_quality.csv is -158.931", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "NMHC(GT)", "stat": "mean", "expected_value": -158.93116197563322, "tolerance": 0.15909009297851875}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000047 (ml_data, tier 1)
- Claim: `{"text": "p25(C6H6(GT)) in air_quality.csv is 4", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "C6H6(GT)", "stat": "p25", "expected_value": 4.0, "tolerance": 0.004}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000050 (ml_data, tier 1)
- Claim: `{"text": "max(C6H6(GT)) in air_quality.csv is 63.7", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "C6H6(GT)", "stat": "max", "expected_value": 63.7, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000095 (ml_data, tier 3)
- Claim: `{"text": "mean(PT08.S3(NOx)) in air_quality.csv is 795.784", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "PT08.S3(NOx)", "stat": "mean", "expected_value": 795.7843629664422, "tolerance": 0.7949901677888211}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000148 (ml_data, tier 1)
- Claim: `{"text": "max(T) in air_quality.csv is 44.6", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "T", "stat": "max", "expected_value": 44.6, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000179 (ml_data, tier 3)
- Claim: `{"text": "mean(AH) in air_quality.csv is -6.83077", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "AH", "stat": "mean", "expected_value": -6.830772878289762, "tolerance": 0.006837603644330449}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000201 (ml_data, tier 2)
- Claim: `{"text": "PT08.S3(NOx) in air_quality.csv: mean is 794.99 AND stdev is 321.994", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "PT08.S3(NOx)", "checks": [{"stat": "mean", "expected_value": 794.9901677888212, "tolerance": 0.7949901677888211}, {"stat": "stdev", "expected_value": 321.993551603116, "tolerance": 0.321993551603116}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000217 (ml_data, tier 1)
- Claim: `{"text": "p25(AT) in combined_cycle_power_plant.csv is 13.51", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "AT", "stat": "p25", "expected_value": 13.51, "tolerance": 0.01351}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000223 (ml_data, tier 3)
- Claim: `{"text": "mean(AT) in combined_cycle_power_plant.csv is 19.6709", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "AT", "stat": "mean", "expected_value": 19.670862767247076, "tolerance": 0.019651231187290973}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000225 (ml_data, tier 1)
- Claim: `{"text": "stdev(AT) in combined_cycle_power_plant.csv is 7.45247", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "AT", "stat": "stdev", "expected_value": 7.452473229611079, "tolerance": 0.007452473229611079}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000243 (ml_data, tier 1)
- Claim: `{"text": "median(AP) in combined_cycle_power_plant.csv is 1012.94", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "AP", "stat": "median", "expected_value": 1012.94, "tolerance": 1.0129400000000002}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000259 (ml_data, tier 1)
- Claim: `{"text": "p25(RH) in combined_cycle_power_plant.csv is 63.3225", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "RH", "stat": "p25", "expected_value": 63.3225, "tolerance": 0.0633225}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000263 (ml_data, tier 2)
- Claim: `{"text": "mean(RH) in combined_cycle_power_plant.csv is 71.4763", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "RH", "stat": "mean", "expected_value": 71.47625339673914, "tolerance": 3.6654488921404687}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000267 (ml_data, tier 1)
- Claim: `{"text": "stdev(RH) in combined_cycle_power_plant.csv is 14.6003", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "RH", "stat": "stdev", "expected_value": 14.600268756728955, "tolerance": 0.014600268756728955}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000283 (ml_data, tier 2)
- Claim: `{"text": "AT in combined_cycle_power_plant.csv: mean is 19.6512 AND stdev is 7.45247", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "AT", "checks": [{"stat": "mean", "expected_value": 19.65123118729097, "tolerance": 0.019651231187290973}, {"stat": "stdev", "expected_value": 7.452473229611079, "tolerance": 0.007452473229611079}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000286 (ml_data, tier 2)
- Claim: `{"text": "V in combined_cycle_power_plant.csv: mean is 54.3058 AND stdev is 12.7079", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "V", "checks": [{"stat": "mean", "expected_value": 54.30580372073579, "tolerance": 0.05430580372073579}, {"stat": "stdev", "expected_value": 12.707892998326809, "tolerance": 0.012707892998326809}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000295 (ml_data, tier 2)
- Claim: `{"text": "PE in combined_cycle_power_plant.csv: mean is 454.365 AND stdev is 17.067", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "PE", "checks": [{"stat": "mean", "expected_value": 454.36500940635455, "tolerance": 0.45436500940635455}, {"stat": "stdev", "expected_value": 17.06699499980342, "tolerance": 0.01706699499980342}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000300 (ml_data, tier 2)
- Claim: `{"text": "correlation between AP and RH in combined_cycle_power_plant.csv is 0.09957", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/combined_cycle_power_plant.csv", "column": "AP", "column_b": "RH", "stat": "correlation", "expected_value": 0.09957431526340707, "tolerance": 0.01}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000308 (ml_data, tier 1)
- Claim: `{"text": "min(Cement) in concrete_compressive_strength.csv is 102", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Cement", "stat": "min", "expected_value": 102.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000314 (ml_data, tier 1)
- Claim: `{"text": "stdev(Cement) in concrete_compressive_strength.csv is 104.506", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Cement", "stat": "stdev", "expected_value": 104.50636449481532, "tolerance": 0.10450636449481532}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000316 (ml_data, tier 1)
- Claim: `{"text": "mean(Blast Furnace Slag) in concrete_compressive_strength.csv is 73.8958", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Blast Furnace Slag", "stat": "mean", "expected_value": 73.89582524271844, "tolerance": 0.07389582524271844}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000318 (ml_data, tier 1)
- Claim: `{"text": "median(Blast Furnace Slag) in concrete_compressive_strength.csv is 22", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Blast Furnace Slag", "stat": "median", "expected_value": 22.0, "tolerance": 0.022}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000342 (ml_data, tier 1)
- Claim: `{"text": "stdev(Fly Ash) in concrete_compressive_strength.csv is 63.997", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Fly Ash", "stat": "stdev", "expected_value": 63.99700415268765, "tolerance": 0.06399700415268765}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000354 (ml_data, tier 3)
- Claim: `{"text": "mean(Water) in concrete_compressive_strength.csv is 181.749", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Water", "stat": "mean", "expected_value": 181.7486672676699, "tolerance": 0.18156728155339807}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000370 (ml_data, tier 1)
- Claim: `{"text": "stdev(Superplasticizer) in concrete_compressive_strength.csv is 5.97384", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Superplasticizer", "stat": "stdev", "expected_value": 5.97384139248552, "tolerance": 0.00597384139248552}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000380 (ml_data, tier 2)
- Claim: `{"text": "mean(Coarse Aggregate) in concrete_compressive_strength.csv is 948.596", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Coarse Aggregate", "stat": "mean", "expected_value": 948.5959587378641, "tolerance": 48.645946601941745}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000386 (ml_data, tier 1)
- Claim: `{"text": "mean(Fine Aggregate) in concrete_compressive_strength.csv is 773.58", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Fine Aggregate", "stat": "mean", "expected_value": 773.5804854368932, "tolerance": 0.7735804854368933}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000388 (ml_data, tier 1)
- Claim: `{"text": "median(Fine Aggregate) in concrete_compressive_strength.csv is 779.5", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Fine Aggregate", "stat": "median", "expected_value": 779.5, "tolerance": 0.7795}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000391 (ml_data, tier 1)
- Claim: `{"text": "p75(Fine Aggregate) in concrete_compressive_strength.csv is 824.25", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Fine Aggregate", "stat": "p75", "expected_value": 824.25, "tolerance": 0.82425}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000396 (ml_data, tier 3)
- Claim: `{"text": "mean(Fine Aggregate) in concrete_compressive_strength.csv is 774.353", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Fine Aggregate", "stat": "mean", "expected_value": 774.3532923418447, "tolerance": 0.7735804854368933}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000400 (ml_data, tier 1)
- Claim: `{"text": "mean(Age) in concrete_compressive_strength.csv is 45.6621", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Age", "stat": "mean", "expected_value": 45.662135922330094, "tolerance": 0.045662135922330094}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000416 (ml_data, tier 1)
- Claim: `{"text": "median(Concrete compressive strength) in concrete_compressive_strength.csv is 34.445", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Concrete compressive strength", "stat": "median", "expected_value": 34.445, "tolerance": 0.034445}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000422 (ml_data, tier 2)
- Claim: `{"text": "mean(Concrete compressive strength) in concrete_compressive_strength.csv is 34.9225", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Concrete compressive strength", "stat": "mean", "expected_value": 34.92251213592233, "tolerance": 1.7908980582524272}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000428 (ml_data, tier 2)
- Claim: `{"text": "Cement in concrete_compressive_strength.csv: mean is 281.168 AND stdev is 104.506", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Cement", "checks": [{"stat": "mean", "expected_value": 281.16786407766995, "tolerance": 0.28116786407766997}, {"stat": "stdev", "expected_value": 104.50636449481532, "tolerance": 0.10450636449481532}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000434 (ml_data, tier 2)
- Claim: `{"text": "Fly Ash in concrete_compressive_strength.csv: mean is 54.1883 AND stdev is 63.997", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Fly Ash", "checks": [{"stat": "mean", "expected_value": 54.18834951456311, "tolerance": 0.05418834951456311}, {"stat": "stdev", "expected_value": 63.99700415268765, "tolerance": 0.06399700415268765}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000440 (ml_data, tier 2)
- Claim: `{"text": "Superplasticizer in concrete_compressive_strength.csv: mean is 6.20466 AND stdev is 5.97384", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Superplasticizer", "checks": [{"stat": "mean", "expected_value": 6.204660194174758, "tolerance": 0.006204660194174758}, {"stat": "stdev", "expected_value": 5.97384139248552, "tolerance": 0.00597384139248552}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000449 (ml_data, tier 2)
- Claim: `{"text": "Age in concrete_compressive_strength.csv: mean is 45.6621 AND stdev is 63.1699", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Age", "checks": [{"stat": "mean", "expected_value": 45.662135922330094, "tolerance": 0.045662135922330094}, {"stat": "stdev", "expected_value": 63.16991158103249, "tolerance": 0.0631699115810325}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000458 (ml_data, tier 1)
- Claim: `{"text": "mean(fixed_acidity) in wine_quality.csv is 7.21531", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "fixed_acidity", "stat": "mean", "expected_value": 7.215307064799138, "tolerance": 0.007215307064799138}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000465 (ml_data, tier 1)
- Claim: `{"text": "max(fixed_acidity) in wine_quality.csv is 15.9", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "fixed_acidity", "stat": "max", "expected_value": 15.9, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000478 (ml_data, tier 1)
- Claim: `{"text": "min(volatile_acidity) in wine_quality.csv is 0.08", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "volatile_acidity", "stat": "min", "expected_value": 0.08, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000488 (ml_data, tier 1)
- Claim: `{"text": "median(citric_acid) in wine_quality.csv is 0.31", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "citric_acid", "stat": "median", "expected_value": 0.31, "tolerance": 0.00031}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000494 (ml_data, tier 2)
- Claim: `{"text": "mean(citric_acid) in wine_quality.csv is 0.310667", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "citric_acid", "stat": "mean", "expected_value": 0.31066738494689855, "tolerance": 0.015931660766507618}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000500 (ml_data, tier 1)
- Claim: `{"text": "mean(residual_sugar) in wine_quality.csv is 5.44324", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "residual_sugar", "stat": "mean", "expected_value": 5.443235339387409, "tolerance": 0.005443235339387409}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000502 (ml_data, tier 1)
- Claim: `{"text": "median(residual_sugar) in wine_quality.csv is 3", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "residual_sugar", "stat": "median", "expected_value": 3.0, "tolerance": 0.003}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000519 (ml_data, tier 1)
- Claim: `{"text": "p75(chlorides) in wine_quality.csv is 0.065", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "chlorides", "stat": "p75", "expected_value": 0.065, "tolerance": 6.500000000000001e-05}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000526 (ml_data, tier 1)
- Claim: `{"text": "stdev(chlorides) in wine_quality.csv is 0.0350336", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "chlorides", "stat": "stdev", "expected_value": 0.03503360137245907, "tolerance": 3.503360137245907e-05}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000528 (ml_data, tier 1)
- Claim: `{"text": "mean(free_sulfur_dioxide) in wine_quality.csv is 30.5253", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "free_sulfur_dioxide", "stat": "mean", "expected_value": 30.525319378174544, "tolerance": 0.030525319378174546}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000532 (ml_data, tier 1)
- Claim: `{"text": "p25(free_sulfur_dioxide) in wine_quality.csv is 17", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "free_sulfur_dioxide", "stat": "p25", "expected_value": 17.0, "tolerance": 0.017}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000536 (ml_data, tier 2)
- Claim: `{"text": "mean(free_sulfur_dioxide) in wine_quality.csv is 29.7622", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "free_sulfur_dioxide", "stat": "mean", "expected_value": 29.76218639372018, "tolerance": 1.5262659689087272}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000538 (ml_data, tier 3)
- Claim: `{"text": "mean(free_sulfur_dioxide) in wine_quality.csv is 30.5558", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "free_sulfur_dioxide", "stat": "mean", "expected_value": 30.55581417223334, "tolerance": 0.030525319378174546}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000540 (ml_data, tier 1)
- Claim: `{"text": "stdev(free_sulfur_dioxide) in wine_quality.csv is 17.7494", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "free_sulfur_dioxide", "stat": "stdev", "expected_value": 17.7493997720025, "tolerance": 0.017749399772002503}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000558 (ml_data, tier 1)
- Claim: `{"text": "median(density) in wine_quality.csv is 0.99489", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "density", "stat": "median", "expected_value": 0.99489, "tolerance": 0.00099489}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000604 (ml_data, tier 1)
- Claim: `{"text": "min(alcohol) in wine_quality.csv is 8", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "alcohol", "stat": "min", "expected_value": 8.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000619 (ml_data, tier 1)
- Claim: `{"text": "max(quality) in wine_quality.csv is 9", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "quality", "stat": "max", "expected_value": 9.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000626 (ml_data, tier 2)
- Claim: `{"text": "fixed_acidity in wine_quality.csv: mean is 7.21531 AND stdev is 1.29643", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "fixed_acidity", "checks": [{"stat": "mean", "expected_value": 7.215307064799138, "tolerance": 0.007215307064799138}, {"stat": "stdev", "expected_value": 1.2964337577998155, "tolerance": 0.0012964337577998156}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000629 (ml_data, tier 2)
- Claim: `{"text": "volatile_acidity in wine_quality.csv: mean is 0.339666 AND stdev is 0.164636", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "volatile_acidity", "checks": [{"stat": "mean", "expected_value": 0.3396659996921656, "tolerance": 0.0003396659996921656}, {"stat": "stdev", "expected_value": 0.16463647408467877, "tolerance": 0.00016463647408467878}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000635 (ml_data, tier 2)
- Claim: `{"text": "residual_sugar in wine_quality.csv: mean is 5.44324 AND stdev is 4.7578", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "residual_sugar", "checks": [{"stat": "mean", "expected_value": 5.443235339387409, "tolerance": 0.005443235339387409}, {"stat": "stdev", "expected_value": 4.757803743147418, "tolerance": 0.004757803743147418}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000644 (ml_data, tier 2)
- Claim: `{"text": "total_sulfur_dioxide in wine_quality.csv: mean is 115.745 AND stdev is 56.5219", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "total_sulfur_dioxide", "checks": [{"stat": "mean", "expected_value": 115.7445744189626, "tolerance": 0.1157445744189626}, {"stat": "stdev", "expected_value": 56.52185452263028, "tolerance": 0.056521854522630276}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000647 (ml_data, tier 2)
- Claim: `{"text": "density in wine_quality.csv: mean is 0.994697 AND stdev is 0.00299867", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "density", "checks": [{"stat": "mean", "expected_value": 0.9946966338309989, "tolerance": 0.000994696633830999}, {"stat": "stdev", "expected_value": 0.002998673003719039, "tolerance": 2.998673003719039e-06}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000706 (ml_data, tier 2)
- Claim: `{"text": "mean(RH_1) in appliances_energy_prediction.csv is 39.2532", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_1", "stat": "mean", "expected_value": 39.25324579778064, "tolerance": 2.012986963988751}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000718 (ml_data, tier 1)
- Claim: `{"text": "min(T2) in appliances_energy_prediction.csv is 16.1", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "T2", "stat": "min", "expected_value": 16.1, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000728 (ml_data, tier 1)
- Claim: `{"text": "median(RH_2) in appliances_energy_prediction.csv is 40.5", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_2", "stat": "median", "expected_value": 40.5, "tolerance": 0.0405}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000732 (ml_data, tier 1)
- Claim: `{"text": "min(RH_2) in appliances_energy_prediction.csv is 20.4633", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_2", "stat": "min", "expected_value": 20.46333333, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000733 (ml_data, tier 1)
- Claim: `{"text": "max(RH_2) in appliances_energy_prediction.csv is 56.0267", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_2", "stat": "max", "expected_value": 56.02666667, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000764 (ml_data, tier 3)
- Claim: `{"text": "mean(RH_3) in appliances_energy_prediction.csv is 39.2817", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_3", "stat": "mean", "expected_value": 39.2817033347755, "tolerance": 0.03924250007719838}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000774 (ml_data, tier 1)
- Claim: `{"text": "min(T4) in appliances_energy_prediction.csv is 15.1", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "T4", "stat": "min", "expected_value": 15.1, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000794 (ml_data, tier 1)
- Claim: `{"text": "stdev(RH_4) in appliances_energy_prediction.csv is 4.34132", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_4", "stat": "stdev", "expected_value": 4.3413206531365285, "tolerance": 0.0043413206531365284}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000812 (ml_data, tier 1)
- Claim: `{"text": "median(RH_5) in appliances_energy_prediction.csv is 49.09", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_5", "stat": "median", "expected_value": 49.09, "tolerance": 0.04909}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000817 (ml_data, tier 1)
- Claim: `{"text": "max(RH_5) in appliances_energy_prediction.csv is 96.3217", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_5", "stat": "max", "expected_value": 96.32166667, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000840 (ml_data, tier 1)
- Claim: `{"text": "median(RH_6) in appliances_energy_prediction.csv is 55.29", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_6", "stat": "median", "expected_value": 55.29, "tolerance": 0.05529}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000848 (ml_data, tier 3)
- Claim: `{"text": "mean(RH_6) in appliances_energy_prediction.csv is 54.6636", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_6", "stat": "mean", "expected_value": 54.66363786187865, "tolerance": 0.05460908338757446}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000859 (ml_data, tier 1)
- Claim: `{"text": "max(T7) in appliances_energy_prediction.csv is 26", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "T7", "stat": "max", "expected_value": 26.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000869 (ml_data, tier 2)
- Claim: `{"text": "lights in appliances_energy_prediction.csv: mean is 3.80187 AND stdev is 7.93599", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "lights", "checks": [{"stat": "mean", "expected_value": 3.8018748416518875, "tolerance": 0.0038018748416518877}, {"stat": "stdev", "expected_value": 7.935987600215888, "tolerance": 0.007935987600215888}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000902 (ml_data, tier 1)
- Claim: `{"text": "min(cylinders) in auto_mpg.csv is 3", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "cylinders", "stat": "min", "expected_value": 3.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000916 (ml_data, tier 1)
- Claim: `{"text": "min(displacement) in auto_mpg.csv is 68", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "displacement", "stat": "min", "expected_value": 68.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000936 (ml_data, tier 1)
- Claim: `{"text": "stdev(horsepower) in auto_mpg.csv is 38.4912", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "stdev", "expected_value": 38.49115993282849, "tolerance": 0.03849115993282849}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000943 (ml_data, tier 1)
- Claim: `{"text": "p75(weight) in auto_mpg.csv is 3610", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "weight", "stat": "p75", "expected_value": 3610.0, "tolerance": 3.61}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000998 (ml_data, tier 1)
- Claim: `{"text": "p25(mpg) in auto_mpg.csv is 17.375", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "mpg", "stat": "p25", "expected_value": 17.375, "tolerance": 0.017375}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001020 (ml_data, tier 2)
- Claim: `{"text": "acceleration in auto_mpg.csv: mean is 15.5681 AND stdev is 2.75769", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "acceleration", "checks": [{"stat": "mean", "expected_value": 15.568090452261307, "tolerance": 0.015568090452261308}, {"stat": "stdev", "expected_value": 2.7576889298126757, "tolerance": 0.0027576889298126755}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001050 (ml_data, tier 1)
- Claim: `{"text": "stdev(Length) in abalone.csv is 0.120093", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Length", "stat": "stdev", "expected_value": 0.12009291256479956, "tolerance": 0.00012009291256479957}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001114 (ml_data, tier 1)
- Claim: `{"text": "min(Viscera_weight) in abalone.csv is 0.0005", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Viscera_weight", "stat": "min", "expected_value": 0.0005, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001118 (ml_data, tier 3)
- Claim: `{"text": "mean(Viscera_weight) in abalone.csv is 0.180774", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Viscera_weight", "stat": "mean", "expected_value": 0.1807740208667704, "tolerance": 0.00018059360785252574}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001126 (ml_data, tier 1)
- Claim: `{"text": "p25(Shell_weight) in abalone.csv is 0.13", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Shell_weight", "stat": "p25", "expected_value": 0.13, "tolerance": 0.00013000000000000002}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001127 (ml_data, tier 1)
- Claim: `{"text": "p75(Shell_weight) in abalone.csv is 0.329", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Shell_weight", "stat": "p75", "expected_value": 0.329, "tolerance": 0.00032900000000000003}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001130 (ml_data, tier 2)
- Claim: `{"text": "mean(Shell_weight) in abalone.csv is 0.23286", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Shell_weight", "stat": "mean", "expected_value": 0.2328600879818051, "tolerance": 0.011941542973425904}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001150 (ml_data, tier 2)
- Claim: `{"text": "Length in abalone.csv: mean is 0.523992 AND stdev is 0.120093", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Length", "checks": [{"stat": "mean", "expected_value": 0.5239920995930094, "tolerance": 0.0005239920995930094}, {"stat": "stdev", "expected_value": 0.12009291256479956, "tolerance": 0.00012009291256479957}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001171 (ml_data, tier 2)
- Claim: `{"text": "Rings in abalone.csv: mean is 9.93368 AND stdev is 3.22417", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Rings", "checks": [{"stat": "mean", "expected_value": 9.933684462532918, "tolerance": 0.009933684462532918}, {"stat": "stdev", "expected_value": 3.224169032068128, "tolerance": 0.003224169032068128}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001190 (ml_data, tier 3)
- Claim: `{"text": "mean(X) in forest_fires.csv is 4.67391", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "X", "stat": "mean", "expected_value": 4.673910224371373, "tolerance": 0.004669245647969052}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001200 (ml_data, tier 1)
- Claim: `{"text": "min(Y) in forest_fires.csv is 2", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "Y", "stat": "min", "expected_value": 2.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001202 (ml_data, tier 2)
- Claim: `{"text": "mean(Y) in forest_fires.csv is 4.19231", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "Y", "stat": "mean", "expected_value": 4.192311411992263, "tolerance": 0.21499032882011604}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001234 (ml_data, tier 1)
- Claim: `{"text": "stdev(DMC) in forest_fires.csv is 64.0465", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "DMC", "stat": "stdev", "expected_value": 64.04648224925425, "tolerance": 0.06404648224925426}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001246 (ml_data, tier 3)
- Claim: `{"text": "mean(DC) in forest_fires.csv is 548.487", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "DC", "stat": "mean", "expected_value": 548.4874307833655, "tolerance": 0.5479400386847195}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001256 (ml_data, tier 1)
- Claim: `{"text": "min(ISI) in forest_fires.csv is 0", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "ISI", "stat": "min", "expected_value": 0.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001258 (ml_data, tier 2)
- Claim: `{"text": "mean(ISI) in forest_fires.csv is 8.79612", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "ISI", "stat": "mean", "expected_value": 8.796121856866538, "tolerance": 0.45108317214700194}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001262 (ml_data, tier 1)
- Claim: `{"text": "stdev(ISI) in forest_fires.csv is 4.55948", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "ISI", "stat": "stdev", "expected_value": 4.559477175216039, "tolerance": 0.00455947717521604}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001274 (ml_data, tier 3)
- Claim: `{"text": "mean(temp) in forest_fires.csv is 18.908", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "temp", "stat": "mean", "expected_value": 18.908038557640236, "tolerance": 0.01888916827852998}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001286 (ml_data, tier 2)
- Claim: `{"text": "mean(RH) in forest_fires.csv is 43.181", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "RH", "stat": "mean", "expected_value": 43.18099613152804, "tolerance": 2.214410058027079}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001292 (ml_data, tier 1)
- Claim: `{"text": "mean(wind) in forest_fires.csv is 4.0176", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "wind", "stat": "mean", "expected_value": 4.017601547388781, "tolerance": 0.004017601547388782}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001320 (ml_data, tier 1)
- Claim: `{"text": "mean(area) in forest_fires.csv is 12.8473", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "area", "stat": "mean", "expected_value": 12.847292069632495, "tolerance": 0.012847292069632496}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001442 (ml_data, tier 2)
- Claim: `{"text": "mean(weekday) in bike_sharing.csv is 2.92859", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/bike_sharing.csv", "column": "weekday", "stat": "mean", "expected_value": 2.928590540307267, "tolerance": 0.15018413027216757}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001453 (ml_data, tier 1)
- Claim: `{"text": "p75(workingday) in bike_sharing.csv is 1", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/bike_sharing.csv", "column": "workingday", "stat": "p75", "expected_value": 1.0, "tolerance": 0.001}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001469 (ml_data, tier 1)
- Claim: `{"text": "max(weathersit) in bike_sharing.csv is 4", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/bike_sharing.csv", "column": "weathersit", "stat": "max", "expected_value": 4.0, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001498 (ml_data, tier 2)
- Claim: `{"text": "mean(atemp) in bike_sharing.csv is 0.463881", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/bike_sharing.csv", "column": "atemp", "stat": "mean", "expected_value": 0.46388072458139123, "tolerance": 0.023788755106738016}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001560 (ml_data, tier 1)
- Claim: `{"text": "mean(cnt) in bike_sharing.csv is 189.463", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/bike_sharing.csv", "column": "cnt", "stat": "mean", "expected_value": 189.46308763450142, "tolerance": 0.18946308763450143}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001604 (ml_data, tier 1)
- Claim: `{"text": "mean(X1 transaction date) in real_estate_valuation.csv is 2013.15", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X1 transaction date", "stat": "mean", "expected_value": 2013.1489710144926, "tolerance": 2.0131489710144925}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001622 (ml_data, tier 1)
- Claim: `{"text": "p25(X2 house age) in real_estate_valuation.csv is 8.975", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X2 house age", "stat": "p25", "expected_value": 8.975, "tolerance": 0.008975}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001630 (ml_data, tier 1)
- Claim: `{"text": "stdev(X2 house age) in real_estate_valuation.csv is 11.3925", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X2 house age", "stat": "stdev", "expected_value": 11.39248453324253, "tolerance": 0.011392484533242531}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001632 (ml_data, tier 1)
- Claim: `{"text": "mean(X3 distance to the nearest MRT station) in real_estate_valuation.csv is 1083.89", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X3 distance to the nearest MRT station", "stat": "mean", "expected_value": 1083.8856889130436, "tolerance": 1.0838856889130437}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001656 (ml_data, tier 3)
- Claim: `{"text": "mean(X4 number of convenience stores) in real_estate_valuation.csv is 4.09829", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X4 number of convenience stores", "stat": "mean", "expected_value": 4.098293007246377, "tolerance": 0.004094202898550725}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001708 (ml_data, tier 2)
- Claim: `{"text": "X3 distance to the nearest MRT station in real_estate_valuation.csv: mean is 1083.89 AND stdev is 1262.11", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X3 distance to the nearest MRT station", "checks": [{"stat": "mean", "expected_value": 1083.8856889130436, "tolerance": 1.0838856889130437}, {"stat": "stdev", "expected_value": 1262.1095954078512, "tolerance": 1.2621095954078512}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001725 (ml_data, tier 2)
- Claim: `{"text": "correlation between X3 distance to the nearest MRT station and X4 number of convenience stores in real_estate_valuation.csv is -0.6025", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X3 distance to the nearest MRT station", "column_b": "X4 number of convenience stores", "stat": "correlation", "expected_value": -0.6025191447226254, "tolerance": 0.01}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001731 (ml_data, tier 1)
- Claim: `{"text": "median(frequency) in airfoil_self_noise.csv is 1600", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "frequency", "stat": "median", "expected_value": 1600.0, "tolerance": 1.6}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001734 (ml_data, tier 1)
- Claim: `{"text": "p75(frequency) in airfoil_self_noise.csv is 4000", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "frequency", "stat": "p75", "expected_value": 4000.0, "tolerance": 4.0}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001741 (ml_data, tier 1)
- Claim: `{"text": "stdev(frequency) in airfoil_self_noise.csv is 3152.57", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "frequency", "stat": "stdev", "expected_value": 3152.5731369306686, "tolerance": 3.152573136930669}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001753 (ml_data, tier 3)
- Claim: `{"text": "mean(attack-angle) in airfoil_self_noise.csv is 6.78908", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "attack-angle", "stat": "mean", "expected_value": 6.789077582302062, "tolerance": 0.0067823020625415835}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001765 (ml_data, tier 2)
- Claim: `{"text": "mean(chord-length) in airfoil_self_noise.csv is 0.133135", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "chord-length", "stat": "mean", "expected_value": 0.13313453093812375, "tolerance": 0.006827411842980705}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001767 (ml_data, tier 3)
- Claim: `{"text": "mean(chord-length) in airfoil_self_noise.csv is 0.136685", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "chord-length", "stat": "mean", "expected_value": 0.13668464854823684, "tolerance": 0.0001365482368596141}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001769 (ml_data, tier 1)
- Claim: `{"text": "stdev(chord-length) in airfoil_self_noise.csv is 0.0935407", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "chord-length", "stat": "stdev", "expected_value": 0.09354072837396629, "tolerance": 9.35407283739663e-05}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001799 (ml_data, tier 1)
- Claim: `{"text": "mean(scaled-sound-pressure) in airfoil_self_noise.csv is 124.836", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "scaled-sound-pressure", "stat": "mean", "expected_value": 124.83594278110445, "tolerance": 0.12483594278110445}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001801 (ml_data, tier 1)
- Claim: `{"text": "median(scaled-sound-pressure) in airfoil_self_noise.csv is 125.721", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "scaled-sound-pressure", "stat": "median", "expected_value": 125.721, "tolerance": 0.125721}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001805 (ml_data, tier 1)
- Claim: `{"text": "min(scaled-sound-pressure) in airfoil_self_noise.csv is 103.38", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "scaled-sound-pressure", "stat": "min", "expected_value": 103.38, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001807 (ml_data, tier 2)
- Claim: `{"text": "mean(scaled-sound-pressure) in airfoil_self_noise.csv is 121.715", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "scaled-sound-pressure", "stat": "mean", "expected_value": 121.71504421157684, "tolerance": 6.2417971390552225}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001839 (ml_data, tier 1)
- Claim: `{"text": "median(AT) in gas_turbine_emission.csv is 17.801", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AT", "stat": "median", "expected_value": 17.801, "tolerance": 0.017800999999999997}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001845 (ml_data, tier 2)
- Claim: `{"text": "mean(AT) in gas_turbine_emission.csv is 17.2699", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AT", "stat": "mean", "expected_value": 17.269908097326656, "tolerance": 0.8856363126834182}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001849 (ml_data, tier 1)
- Claim: `{"text": "stdev(AT) in gas_turbine_emission.csv is 7.44745", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AT", "stat": "stdev", "expected_value": 7.44745123459077, "tolerance": 0.00744745123459077}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001859 (ml_data, tier 2)
- Claim: `{"text": "mean(AP) in gas_turbine_emission.csv is 987.743", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AP", "stat": "mean", "expected_value": 987.7434108499169, "tolerance": 50.65350824871369}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001861 (ml_data, tier 3)
- Claim: `{"text": "mean(AP) in gas_turbine_emission.csv is 1014.08", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AP", "stat": "mean", "expected_value": 1014.0822220690831, "tolerance": 1.0130701649742737}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001873 (ml_data, tier 2)
- Claim: `{"text": "mean(AH) in gas_turbine_emission.csv is 75.9203", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AH", "stat": "mean", "expected_value": 75.92034010290476, "tolerance": 3.8933507745079363}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001875 (ml_data, tier 3)
- Claim: `{"text": "mean(AH) in gas_turbine_emission.csv is 77.9448", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AH", "stat": "mean", "expected_value": 77.94480463863339, "tolerance": 0.07786701549015872}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001879 (ml_data, tier 1)
- Claim: `{"text": "mean(AFDP) in gas_turbine_emission.csv is 3.92552", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AFDP", "stat": "mean", "expected_value": 3.9255177143168267, "tolerance": 0.003925517714316827}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001884 (ml_data, tier 1)
- Claim: `{"text": "p75(AFDP) in gas_turbine_emission.csv is 4.3769", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AFDP", "stat": "p75", "expected_value": 4.3769, "tolerance": 0.0043769}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001901 (ml_data, tier 2)
- Claim: `{"text": "mean(GTEP) in gas_turbine_emission.csv is 24.9247", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "GTEP", "stat": "mean", "expected_value": 24.924706343070266, "tolerance": 1.2781900688753982}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001913 (ml_data, tier 1)
- Claim: `{"text": "min(TIT) in gas_turbine_emission.csv is 1000.8", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "TIT", "stat": "min", "expected_value": 1000.8, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001917 (ml_data, tier 3)
- Claim: `{"text": "mean(TIT) in gas_turbine_emission.csv is 1082.51", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "TIT", "stat": "mean", "expected_value": 1082.5084303950723, "tolerance": 1.0814280837394168}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001923 (ml_data, tier 1)
- Claim: `{"text": "median(TAT) in gas_turbine_emission.csv is 549.88", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "TAT", "stat": "median", "expected_value": 549.88, "tolerance": 0.54988}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001929 (ml_data, tier 2)
- Claim: `{"text": "mean(TAT) in gas_turbine_emission.csv is 532.505", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "TAT", "stat": "mean", "expected_value": 532.5045542087496, "tolerance": 27.307925856858954}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001931 (ml_data, tier 3)
- Claim: `{"text": "mean(TAT) in gas_turbine_emission.csv is 546.704", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "TAT", "stat": "mean", "expected_value": 546.7041294957991, "tolerance": 0.5461585171371791}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001933 (ml_data, tier 1)
- Claim: `{"text": "stdev(TAT) in gas_turbine_emission.csv is 6.84236", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "TAT", "stat": "stdev", "expected_value": 6.84236043343257, "tolerance": 0.00684236043343257}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001968 (ml_data, tier 1)
- Claim: `{"text": "p75(CO) in gas_turbine_emission.csv is 2.8429", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "CO", "stat": "p75", "expected_value": 2.8429, "tolerance": 0.0028429}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001975 (ml_data, tier 1)
- Claim: `{"text": "stdev(CO) in gas_turbine_emission.csv is 2.26267", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "CO", "stat": "stdev", "expected_value": 2.26267163863963, "tolerance": 0.0022626716386396303}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001977 (ml_data, tier 1)
- Claim: `{"text": "mean(NOX) in gas_turbine_emission.csv is 65.2931", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "NOX", "stat": "mean", "expected_value": 65.29306726921297, "tolerance": 0.06529306726921297}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001987 (ml_data, tier 3)
- Claim: `{"text": "mean(NOX) in gas_turbine_emission.csv is 65.3583", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "NOX", "stat": "mean", "expected_value": 65.35829504341491, "tolerance": 0.06529306726921297}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001997 (ml_data, tier 2)
- Claim: `{"text": "AH in gas_turbine_emission.csv: mean is 77.867 AND stdev is 14.4614", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AH", "checks": [{"stat": "mean", "expected_value": 77.86701549015872, "tolerance": 0.07786701549015872}, {"stat": "stdev", "expected_value": 14.461354946665596, "tolerance": 0.014461354946665596}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002000 (ml_data, tier 2)
- Claim: `{"text": "AFDP in gas_turbine_emission.csv: mean is 3.92552 AND stdev is 0.773936", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AFDP", "checks": [{"stat": "mean", "expected_value": 3.9255177143168267, "tolerance": 0.003925517714316827}, {"stat": "stdev", "expected_value": 0.7739355929063553, "tolerance": 0.0007739355929063553}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002003 (ml_data, tier 2)
- Claim: `{"text": "GTEP in gas_turbine_emission.csv: mean is 25.5638 AND stdev is 4.19596", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "GTEP", "checks": [{"stat": "mean", "expected_value": 25.563801377507964, "tolerance": 0.025563801377507966}, {"stat": "stdev", "expected_value": 4.195957462496971, "tolerance": 0.0041959574624969714}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002012 (ml_data, tier 2)
- Claim: `{"text": "TEY in gas_turbine_emission.csv: mean is 133.506 AND stdev is 15.6186", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "TEY", "checks": [{"stat": "mean", "expected_value": 133.5064035063839, "tolerance": 0.1335064035063839}, {"stat": "stdev", "expected_value": 15.618634370154345, "tolerance": 0.015618634370154346}]}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002017 (ml_data, tier 2)
- Claim: `{"text": "correlation between AH and AFDP in gas_turbine_emission.csv is -0.1478", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AH", "column_b": "AFDP", "stat": "correlation", "expected_value": -0.14784048227528823, "tolerance": 0.01}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002077 (ml_data, tier 1)
- Claim: `{"text": "mean(wtd_gmean_atomic_mass) in superconductivity.csv is 58.5399", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/superconductivity.csv", "column": "wtd_gmean_atomic_mass", "stat": "mean", "expected_value": 58.539915554195844, "tolerance": 0.05853991555419585}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002225 (ml_data, tier 2)
- Claim: `{"text": "mean(wtd_gmean_fie) in superconductivity.csv is 811.95", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/superconductivity.csv", "column": "wtd_gmean_fie", "stat": "mean", "expected_value": 811.9504075467532, "tolerance": 41.63848243829504}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002242 (ml_data, tier 2)
- Claim: `{"text": "gmean_atomic_mass in superconductivity.csv: mean is 147.581 AND stdev is 31.0303", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/superconductivity.csv", "column": "gmean_atomic_mass", "checks": [{"stat": "mean", "expected_value": 147.58125407540058, "tolerance": 0.0712906270377003}, {"stat": "stdev", "expected_value": 31.030271676748463, "tolerance": 0.031030271676748464}]}}`
- Generic-RAG predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `ConnectError: [Errno -3] Temporary failure in name resolution`

### ml_data-002305 (ml_data, tier 1)
- Claim: `{"text": "median(Jitter(%)) in parkinsons_telemonitoring.csv is 0.0049", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/parkinsons_telemonitoring.csv", "column": "Jitter(%)", "stat": "median", "expected_value": 0.0049, "tolerance": 4.9e-06}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002309 (ml_data, tier 1)
- Claim: `{"text": "min(Jitter(%)) in parkinsons_telemonitoring.csv is 0.00083", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/parkinsons_telemonitoring.csv", "column": "Jitter(%)", "stat": "min", "expected_value": 0.00083, "tolerance": 1e-09}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002433 (ml_data, tier 1)
- Claim: `{"text": "p25(Shimmer:APQ11) in parkinsons_telemonitoring.csv is 0.01566", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/parkinsons_telemonitoring.csv", "column": "Shimmer:APQ11", "stat": "p25", "expected_value": 0.01566, "tolerance": 1.566e-05}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-002501 (ml_data, tier 2)
- Claim: `{"text": "combined mean of CO(GT) across both real shards of air_quality is -34.2075", "domain": "ml_data", "context": {"dataset_path": ["stress_test/data/ml_data/air_quality_shard1.csv", "stress_test/data/ml_data/air_quality_shard2.csv"], "column": "CO(GT)", "stat": "mean", "expected_value": -34.20752377898899, "tolerance": 0.034207523778988995}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### robotics-002931 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 110 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002935 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 120 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002947 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 150 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002953 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 165 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002963 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 190 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002975 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 220 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002989 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 255 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002997 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 275 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-003007 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 300 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-003208 (robotics, tier 3)
- Claim: `{"text": "Bar30 survives 310 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-003229 (robotics, tier 2)
- Claim: `{"text": "Bar30 fails at 360 m depth", "domain": "robotics", "context": {}}`
- Generic-RAG predicted: **contradicted**, ground truth: **confirmed** (dangerous)


## Test #3 Perplexity batch `full` — 35 dangerous/crash result(s) (external API baseline; not a pipeline bug)

### ml_data-000210 (ml_data, tier 2)
- Claim: `{"text": "correlation between NMHC(GT) and C6H6(GT) in air_quality.csv is 0.9373", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "NMHC(GT)", "column_b": "C6H6(GT)", "stat": "correlation", "expected_value": 0.9373225180362648, "tolerance": 0.01}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-000357 (ml_data, tier 1)
- Claim: `{"text": "stdev(Water) in concrete_compressive_strength.csv is 43.7084", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Water", "stat": "stdev", "expected_value": 43.70843713006494, "tolerance": 0.02135421856503247}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-000381 (ml_data, tier 2)
- Claim: `{"text": "mean(Coarse Aggregate) in concrete_compressive_strength.csv is 1118.86", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Coarse Aggregate", "stat": "mean", "expected_value": 1118.8567718446602, "tolerance": 48.645946601941745}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-000423 (ml_data, tier 2)
- Claim: `{"text": "mean(Concrete compressive strength) in concrete_compressive_strength.csv is 41.1907", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Concrete compressive strength", "stat": "mean", "expected_value": 41.19065533980583, "tolerance": 1.7908980582524272}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-000427 (ml_data, tier 1)
- Claim: `{"text": "stdev(Concrete compressive strength) in concrete_compressive_strength.csv is 34.4115", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Concrete compressive strength", "stat": "stdev", "expected_value": 34.411483923825024, "tolerance": 0.01670574196191251}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-000444 (ml_data, tier 2)
- Claim: `{"text": "Coarse Aggregate in concrete_compressive_strength.csv: mean is 972.919 AND stdev is 234.262", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Coarse Aggregate", "checks": [{"stat": "mean", "expected_value": 972.9189320388349, "tolerance": 0.972918932038835}, {"stat": "stdev", "expected_value": 234.26186190016233, "tolerance": 0.07775395396672077}]}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-000583 (ml_data, tier 1)
- Claim: `{"text": "stdev(pH) in wine_quality.csv is 1.32157", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "pH", "stat": "stdev", "expected_value": 1.3215744042079753, "tolerance": 0.00016078720210398764}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-000965 (ml_data, tier 1)
- Claim: `{"text": "stdev(acceleration) in auto_mpg.csv is 6.51538", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "acceleration", "stat": "stdev", "expected_value": 6.515377859625351, "tolerance": 0.0027576889298126755}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001023 (ml_data, tier 2)
- Claim: `{"text": "model_year in auto_mpg.csv: mean is 76.0101 AND stdev is 3.69763", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "model_year", "checks": [{"stat": "mean", "expected_value": 76.01005025125629, "tolerance": 0.07601005025125629}, {"stat": "stdev", "expected_value": 3.6976266467326226, "tolerance": 0.0036976266467326226}]}}`
- Perplexity predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001033 (ml_data, tier 2)
- Claim: `{"text": "correlation between cylinders and displacement in auto_mpg.csv is -0.9507", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "cylinders", "column_b": "displacement", "stat": "correlation", "expected_value": -0.9507213901392411, "tolerance": 0.01}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001223 (ml_data, tier 1)
- Claim: `{"text": "mean(DMC) in forest_fires.csv is 176.309", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "DMC", "stat": "mean", "expected_value": 176.3085106382979, "tolerance": 0.11087234042553192}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001340 (ml_data, tier 2)
- Claim: `{"text": "FFMC in forest_fires.csv: mean is 90.6447 AND stdev is 5.52011", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/forest_fires.csv", "column": "FFMC", "checks": [{"stat": "mean", "expected_value": 90.64468085106384, "tolerance": 0.09064468085106384}, {"stat": "stdev", "expected_value": 5.520110848851268, "tolerance": 0.005520110848851269}]}}`
- Perplexity predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001627 (ml_data, tier 2)
- Claim: `{"text": "mean(X2 house age) in real_estate_valuation.csv is 20.3694", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X2 house age", "stat": "mean", "expected_value": 20.369444444444447, "tolerance": 0.8856280193236716}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001641 (ml_data, tier 2)
- Claim: `{"text": "mean(X3 distance to the nearest MRT station) in real_estate_valuation.csv is 1246.47", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X3 distance to the nearest MRT station", "stat": "mean", "expected_value": 1246.4685422500002, "tolerance": 54.19428444565219}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001699 (ml_data, tier 3)
- Claim: `{"text": "mean(Y house price of unit area) in real_estate_valuation.csv is 38.0182", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "Y house price of unit area", "stat": "mean", "expected_value": 38.018177227971016, "tolerance": 0.037980193236714976}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001701 (ml_data, tier 1)
- Claim: `{"text": "stdev(Y house price of unit area) in real_estate_valuation.csv is 28.213", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "Y house price of unit area", "stat": "stdev", "expected_value": 28.212975395470625, "tolerance": 0.013606487697735313}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001708 (ml_data, tier 2)
- Claim: `{"text": "X3 distance to the nearest MRT station in real_estate_valuation.csv: mean is 1083.89 AND stdev is 1262.11", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/real_estate_valuation.csv", "column": "X3 distance to the nearest MRT station", "checks": [{"stat": "mean", "expected_value": 1083.8856889130436, "tolerance": 1.0838856889130437}, {"stat": "stdev", "expected_value": 1262.1095954078512, "tolerance": 1.2621095954078512}]}}`
- Perplexity predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001740 (ml_data, tier 3)
- Claim: `{"text": "mean(frequency) in airfoil_self_noise.csv is 2889.27", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "frequency", "stat": "mean", "expected_value": 2889.2672413992013, "tolerance": 2.8863805721889553}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001768 (ml_data, tier 3)
- Claim: `{"text": "mean(chord-length) in airfoil_self_noise.csv is 0.136685", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "chord-length", "stat": "mean", "expected_value": 0.13668479875129738, "tolerance": 0.0001365482368596141}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001808 (ml_data, tier 2)
- Claim: `{"text": "mean(scaled-sound-pressure) in airfoil_self_noise.csv is 143.561", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/airfoil_self_noise.csv", "column": "scaled-sound-pressure", "stat": "mean", "expected_value": 143.56133419827012, "tolerance": 6.2417971390552225}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-002066 (ml_data, tier 1)
- Claim: `{"text": "median(gmean_atomic_mass) in superconductivity.csv is 21.5446", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/superconductivity.csv", "column": "gmean_atomic_mass", "stat": "median", "expected_value": 21.544636972628766, "tolerance": 0.06636159243157191}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-002235 (ml_data, tier 2)
- Claim: `{"text": "mean_atomic_mass in superconductivity.csv: mean is 87.5576 AND stdev is 90.0295", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/superconductivity.csv", "column": "mean_atomic_mass", "checks": [{"stat": "mean", "expected_value": 87.55763086475905, "tolerance": 0.08755763086475905}, {"stat": "stdev", "expected_value": 90.02949178689222, "tolerance": 0.029676497262297406}]}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-002260 (ml_data, tier 2)
- Claim: `{"text": "correlation between wtd_gmean_atomic_mass and entropy_atomic_mass in superconductivity.csv is 0.3706", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/superconductivity.csv", "column": "wtd_gmean_atomic_mass", "column_b": "entropy_atomic_mass", "stat": "correlation", "expected_value": 0.370561445554125, "tolerance": 0.01}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-002300 (ml_data, tier 3)
- Claim: `{"text": "mean(test_time) in parkinsons_telemonitoring.csv is 92.9566", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/parkinsons_telemonitoring.csv", "column": "test_time", "stat": "mean", "expected_value": 92.95659505437561, "tolerance": 0.09286372204595744}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-002440 (ml_data, tier 3)
- Claim: `{"text": "mean(Shimmer:APQ11) in parkinsons_telemonitoring.csv is 0.0275083", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/parkinsons_telemonitoring.csv", "column": "Shimmer:APQ11", "stat": "mean", "expected_value": 0.027508344885958467, "tolerance": 2.7480861276595746e-05}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-002478 (ml_data, tier 2)
- Claim: `{"text": "test_time in parkinsons_telemonitoring.csv: mean is 92.8637 AND stdev is 161.337", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/parkinsons_telemonitoring.csv", "column": "test_time", "checks": [{"stat": "mean", "expected_value": 92.86372204595745, "tolerance": 0.09286372204595744}, {"stat": "stdev", "expected_value": 161.33680624282485, "tolerance": 0.05344560208094162}]}}`
- Perplexity predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### research_web-003293 (research_web, tier 3)
- Claim: `{"text": "ArduPilot has over 10 million lines of code", "domain": "research_web", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002942 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 140 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002946 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 150 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **confirmed**, ground truth: **undetermined** (dangerous)

### robotics-002950 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 160 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002954 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 170 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002978 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 230 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002988 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 255 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-002992 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 265 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **undetermined** (dangerous)

### robotics-003069 (robotics, tier 2)
- Claim: `{"text": "BlueROV2 fails at 455 m depth", "domain": "robotics", "context": {}}`
- Perplexity predicted: **contradicted**, ground truth: **confirmed** (dangerous)


## Test #3 Tavily+Gemini batch `full` — 26 dangerous/crash result(s) (external API baseline; not a pipeline bug)

### fpga_embedded-002519 (fpga_embedded, tier 3)
- Claim: `{"text": "jiwoonl__timing.txt: tns_ns >= 0", "domain": "fpga_embedded", "context": {"report_path": "stress_test/data/fpga_embedded/jiwoonl__timing.txt", "metric": "tns_ns", "comparator": ">=", "expected_value": 0.0}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### fpga_embedded-002663 (fpga_embedded, tier 1)
- Claim: `{"text": "Nero7991__llm.vhdl__timing_summary_A.rpt: tpws_ns >= -0.001", "domain": "fpga_embedded", "context": {"report_path": "stress_test/data/fpga_embedded/Nero7991__llm.vhdl__timing_summary_A.rpt", "metric": "tpws_ns", "comparator": ">=", "expected_value": -0.001}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `ReadTimeout: `

### ml_data-000037 (ml_data, tier 2)
- Claim: `{"text": "mean(NMHC(GT)) in air_quality.csv is -163.067", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "NMHC(GT)", "stat": "mean", "expected_value": -163.06734530298172, "tolerance": 7.954504648925938}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000104 (ml_data, tier 1)
- Claim: `{"text": "p75(NO2(GT)) in air_quality.csv is 133", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "NO2(GT)", "stat": "p75", "expected_value": 133.0, "tolerance": 0.133}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000161 (ml_data, tier 1)
- Claim: `{"text": "min(RH) in air_quality.csv is -200", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/air_quality.csv", "column": "RH", "stat": "min", "expected_value": -200.0, "tolerance": 1e-09}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000351 (ml_data, tier 1)
- Claim: `{"text": "max(Water) in concrete_compressive_strength.csv is 247", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Water", "stat": "max", "expected_value": 247.0, "tolerance": 1e-09}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000354 (ml_data, tier 3)
- Claim: `{"text": "mean(Water) in concrete_compressive_strength.csv is 181.749", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Water", "stat": "mean", "expected_value": 181.7486672676699, "tolerance": 0.18156728155339807}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000391 (ml_data, tier 1)
- Claim: `{"text": "p75(Fine Aggregate) in concrete_compressive_strength.csv is 824.25", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/concrete_compressive_strength.csv", "column": "Fine Aggregate", "stat": "p75", "expected_value": 824.25, "tolerance": 0.82425}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000458 (ml_data, tier 1)
- Claim: `{"text": "mean(fixed_acidity) in wine_quality.csv is 7.21531", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "fixed_acidity", "stat": "mean", "expected_value": 7.215307064799138, "tolerance": 0.007215307064799138}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `ConnectError: [Errno -3] Temporary failure in name resolution`

### ml_data-000478 (ml_data, tier 1)
- Claim: `{"text": "min(volatile_acidity) in wine_quality.csv is 0.08", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "volatile_acidity", "stat": "min", "expected_value": 0.08, "tolerance": 1e-09}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000488 (ml_data, tier 1)
- Claim: `{"text": "median(citric_acid) in wine_quality.csv is 0.31", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "citric_acid", "stat": "median", "expected_value": 0.31, "tolerance": 0.00031}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000561 (ml_data, tier 1)
- Claim: `{"text": "p75(density) in wine_quality.csv is 0.99699", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "density", "stat": "p75", "expected_value": 0.99699, "tolerance": 0.0009969900000000001}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000586 (ml_data, tier 1)
- Claim: `{"text": "median(sulphates) in wine_quality.csv is 0.51", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "sulphates", "stat": "median", "expected_value": 0.51, "tolerance": 0.00051}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000619 (ml_data, tier 1)
- Claim: `{"text": "max(quality) in wine_quality.csv is 9", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "quality", "stat": "max", "expected_value": 9.0, "tolerance": 1e-09}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000629 (ml_data, tier 2)
- Claim: `{"text": "volatile_acidity in wine_quality.csv: mean is 0.339666 AND stdev is 0.164636", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "volatile_acidity", "checks": [{"stat": "mean", "expected_value": 0.3396659996921656, "tolerance": 0.0003396659996921656}, {"stat": "stdev", "expected_value": 0.16463647408467877, "tolerance": 0.00016463647408467878}]}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000644 (ml_data, tier 2)
- Claim: `{"text": "total_sulfur_dioxide in wine_quality.csv: mean is 115.745 AND stdev is 56.5219", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/wine_quality.csv", "column": "total_sulfur_dioxide", "checks": [{"stat": "mean", "expected_value": 115.7445744189626, "tolerance": 0.1157445744189626}, {"stat": "stdev", "expected_value": 56.52185452263028, "tolerance": 0.056521854522630276}]}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000830 (ml_data, tier 1)
- Claim: `{"text": "min(T6) in appliances_energy_prediction.csv is -6.065", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "T6", "stat": "min", "expected_value": -6.065, "tolerance": 1e-09}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000869 (ml_data, tier 2)
- Claim: `{"text": "lights in appliances_energy_prediction.csv: mean is 3.80187 AND stdev is 7.93599", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "lights", "checks": [{"stat": "mean", "expected_value": 3.8018748416518875, "tolerance": 0.0038018748416518877}, {"stat": "stdev", "expected_value": 7.935987600215888, "tolerance": 0.007935987600215888}]}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000929 (ml_data, tier 1)
- Claim: `{"text": "p75(horsepower) in auto_mpg.csv is 128", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "horsepower", "stat": "p75", "expected_value": 128.0, "tolerance": 0.128}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-000973 (ml_data, tier 1)
- Claim: `{"text": "max(model_year) in auto_mpg.csv is 82", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/auto_mpg.csv", "column": "model_year", "stat": "max", "expected_value": 82.0, "tolerance": 1e-09}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001046 (ml_data, tier 2)
- Claim: `{"text": "mean(Length) in abalone.csv is 0.510892", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Length", "stat": "mean", "expected_value": 0.5108922971031842, "tolerance": 0.026199604979650473}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001049 (ml_data, tier 3)
- Claim: `{"text": "mean(Length) in abalone.csv is 0.524516", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Length", "stat": "mean", "expected_value": 0.5245161440918124, "tolerance": 0.0005239920995930094}}`
- Tavily+Gemini predicted: **confirmed**, ground truth: **contradicted** (dangerous)

### ml_data-001060 (ml_data, tier 2)
- Claim: `{"text": "mean(Diameter) in abalone.csv is 0.397684", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Diameter", "stat": "mean", "expected_value": 0.397684223126646, "tolerance": 0.020394062724443385}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001118 (ml_data, tier 3)
- Claim: `{"text": "mean(Viscera_weight) in abalone.csv is 0.180774", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Viscera_weight", "stat": "mean", "expected_value": 0.1807740208667704, "tolerance": 0.00018059360785252574}}`
- Tavily+Gemini predicted: **contradicted**, ground truth: **confirmed** (dangerous)

### ml_data-001151 (ml_data, tier 2)
- Claim: `{"text": "Length in abalone.csv: mean is 0.523992 AND stdev is 1.36028", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Length", "checks": [{"stat": "mean", "expected_value": 0.5239920995930094, "tolerance": 0.0005239920995930094}, {"stat": "stdev", "expected_value": 1.3602787376943986, "tolerance": 0.00012009291256479957}]}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `GeminiQuotaExhausted: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 500, model: gemini-3.5-flash-lite\nPlease retry in 18h51m19.150395233s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "location": "global",
              "model": "gemini-3.5-flash-lite"
            },
            "quotaValue": "500"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "67879s"
      }
    ]
  }
}
`

### ml_data-001152 (ml_data, tier 2)
- Claim: `{"text": "Length in abalone.csv: mean is 6.04798 AND stdev is 0.120093", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/abalone.csv", "column": "Length", "checks": [{"stat": "mean", "expected_value": 6.047984199186018, "tolerance": 0.0005239920995930094}, {"stat": "stdev", "expected_value": 0.12009291256479956, "tolerance": 0.00012009291256479957}]}}`
- Tavily+Gemini predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `GeminiQuotaExhausted: Gemini returned 429: {
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 500, model: gemini-3.5-flash-lite\nPlease retry in 18h51m15.245526539s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.Help",
        "links": [
          {
            "description": "Learn more about Gemini API quotas",
            "url": "https://ai.google.dev/gemini-api/docs/rate-limits"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
          {
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {
              "model": "gemini-3.5-flash-lite",
              "location": "global"
            },
            "quotaValue": "500"
          }
        ]
      },
      {
        "@type": "type.googleapis.com/google.rpc.RetryInfo",
        "retryDelay": "67875s"
      }
    ]
  }
}
`

