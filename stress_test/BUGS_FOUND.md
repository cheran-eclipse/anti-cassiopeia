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
