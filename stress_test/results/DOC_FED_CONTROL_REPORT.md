# Document-fed control test

Run 2026-10-26. Script: `stress_test/run_doc_fed_control.py`. Raw rows:
`doc_fed_control_full_raw.jsonl` (full run) and
`doc_fed_control_pilot-1793019848_raw.jsonl` (pilot, superseded).

## Why

The headline comparison in `TEST3_REPORT.md` gave a claim's private file only
to Anti-Cassiopeia, the Nebius agent, generic RAG and code-exec. The bare
model, Perplexity and Tavily+Gemini saw only the claim text, and 993 of the
1,000 sampled claims needed a private file or corpus. This test gives two of
the competing models the same file, pasted into the prompt, to measure how
much of that gap was document access.

Models: `openai/gpt-oss-120b` (Nebius) and `perplexity/sonar`. Gemini
(`gemini-3.5-flash-lite`) was not run: its check through the run environment's
proxy returned HTTP 502, and it was deferred. No Gemini numbers are reported.
Arm 3 (model plus Anti-Cassiopeia's verdict) and a closed-corpus
`searchlight` test are not done.

## Method

- Claims: the 872 `fpga_embedded` and `ml_data` claims in the 1,000-claim
  sample. Each doc-fed prompt pastes the full file or files, never truncated,
  and states the claim's tolerance from its own context. The bare prompt is
  the one used in earlier tests, so bare numbers stay comparable.
- Paste limit: estimated input plus a 16,000-token output budget must stay
  under 131,072 tokens (1.3 bytes per token, an overestimate). The same rule
  applies to both models, so they see the same claims: all 116 `fpga` claims
  and 216 of 756 `ml_data` claims. The other 540 are recorded as
  `CANNOT_PASTE`: 496 files exceed the limit, and 44 `abalone.csv` claims
  (196 KB, about 141K tokens) overflow `gpt-oss-120b`'s context.
- Precision is correct / (correct + dangerous). Ranges are 95% Wilson.
- No key is in the code or requests; the environment's proxy adds it.
  Per-provider hard caps were $20 for Nebius and $5 for Perplexity; actual
  spend was $1.07 and $1.49. No call was skipped.
- sonar rows are labelled "file plus possible web search" because the
  endpoint doesn't let web search be turned off.

## Results

### `fpga_embedded` (all 116 claims fit)

| System and condition | Precision | Coverage | Wrong | Cost |
|---|---|---|---|---|
| `gpt-oss-120b`, file only | 96.6% (91.5 to 98.7) | 100% | 4 | $0.177 |
| sonar, file plus possible web search | 86.8% (79.4 to 91.9) | 98.3% | 15 | $0.273 |
| either model, claim text only | too few answers (1.7% coverage) | 1.7% | 0 | $0.012 each |

All 19 wrong answers were labelled `table_misread`: the model read the wrong
figure out of the report.

### `ml_data` (216 claims pasteable, 540 not)

| System and condition | Precision | Coverage | Wrong | Cost |
|---|---|---|---|---|
| `gpt-oss-120b`, file only | 66.7% (59.4 to 73.2) | 82.3% (76.7 to 86.8) | 59 | $0.845 |
| sonar, file plus possible web search | 77.6% (71.5 to 82.6) | 99.1% (96.7 to 99.7) | 48 | $1.183 |
| `gpt-oss-120b`, claim text only | 73.0% (61.0 to 82.4) | 29.3% | 17 | $0.034 |
| sonar, claim text plus possible web search | 65.9% (50.5 to 78.4) | 19.0% | 14 | $0.021 |

On the same 216 claims, against the corrected labels below, the wrong
confident answers of the other systems that had the file were: Anti-Cassiopeia
0, code-exec 1, generic RAG 55.

540 of 756 `ml_data` claims (71%) can't be given to these models as an inline
file. Giving the model the file does not make `ml_data` safe: reading a number
out of a report works, but computing a statistic over thousands of rows in a
prompt does not.

- All 59 of `gpt-oss-120b`'s wrong answers are on claims that are true (it says
  "contradicted" when the real value is within tolerance). On the 93 false
  claims it made no wrong answers (80 correct, 13 abstained). It estimates
  the statistic instead of computing it. Its worst statistics are `p25`
  (precision 0.41, n=17) and `p75` (0.38, n=14).
- sonar's errors are spread over both truth values (27 on true claims, 21 on
  false). Tier 3 boundary claims (n=20) are hardest for it (precision 0.50);
  tier 1 (n=135) is 0.83 for sonar and 0.62 for `gpt-oss-120b`.
- Without the file, both models mostly abstain but still give 14 to 17
  confident wrong answers about a file they can't see.
- One `gpt-oss-120b` answer used the whole 16,000-token output budget and is
  counted as unparseable, not wrong.
- Every wrong `ml_data` answer is labelled `arithmetic_over_rows`. The label is
  assigned by claim type, not diagnosed per answer, and it also covers `min`
  and `max` claims. Every row keeps the full response text for checking.

## Correction to the headline Test #3 labels

`air_quality.csv` uses `-200` as its missing-value marker. The `quant`
adapter was changed to skip it, but ground truth for `air_quality.csv` claims
was generated earlier, with `-200` counted as a value, and not regenerated.
`stress_test/rescore_corrected_labels.py` recomputes every `ml_data` claim in
the 1,000-claim sample with `stress_test/oracles/ml_data_oracle.py` (confirmed
if the oracle value is within the claim's tolerance; a compound claim needs
every part).

- **25 claims disagree with their recorded label.** All are `air_quality.csv`,
  and all change from confirmed to contradicted. Nothing else disagrees.
  `manifest.jsonl` is not edited; the corrected labels are in
  `stress_test/claims/corrected_labels_overlay.jsonl`.
- The current engine matches the corrected label on 25 of 25, and the old label
  on 0 of 25. On the other 847 file claims it differs from the recorded label
  0 times.
- None of these claims was pasted in the document-fed run: every
  `air_quality.csv` file is over the paste limit.

Old against corrected, re-scored from each system's saved raw results for the
872 file claims (full table: `corrected_labels_rescore.md`):

| System | Correct | Wrong | Precision when answering |
|---|---|---|---|
| Pipeline, saved run (old adapter) | 100% to 97.1% | 0 to 25 | 100% to 97.1% |
| Pipeline, current engine re-run | 97.1% to 100% | 25 to 0 | 97.1% to 100% |
| Code-exec | 99.1% to 96.2% | 4 to 29 | 99.5% to 96.7% |
| Generic RAG | 34.3% to 34.7% | 164 to 160 | 64.6% to 65.4% |
| Tavily+Gemini (473 scored claims) | 11.0% to 11.4% | 22 to 20 | 70.3% to 73.0% |
| Bare Nebius, Perplexity | unchanged | unchanged | unchanged |

The earlier "pipeline 100% correct, 0 dangerous" was scored against stale
labels using the old adapter. Re-run with the current engine and scored
against corrected labels, the pipeline is 100% on the 872 file claims.
Code-exec drops because it read the file literally and counted `-200` as a
value. **Caveat:** the corrected labels rest on the UCI convention that
`-200` means missing, and the claim text doesn't state it, so a system that
reads the file literally is wrong only by that convention. The Tavily+Gemini
row covers only 473 of 1,000 claims, as in `TEST3_REPORT.md`. About 212
`air_quality.csv` claims in the full manifest are stale in the same way; only
the 25 in this sample were relabelled.

## Caveats

- The pilot used a different prompt (no tolerance, a 3,000-token budget), so
  its numbers are not combined with the full run.
- The cost guards use estimates that overstate real cost, so they can stop
  early but not overspend. Recorded spend uses each response's own usage.
- sonar's web use can't be ruled out, so its rows are not a clean file-only
  condition.
- Bare-arm precision on `fpga` rests on 2 answers and should not be quoted.
- Not done: Gemini (deferred), arm 3, the closed-corpus `searchlight` test.
