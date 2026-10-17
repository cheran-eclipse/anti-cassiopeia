# Evals

Run with: `PYTHONPATH=. python evals/run_evals.py`

Cases live at `evals/cases/<domain>/<case_id>.json`:

```json
{
  "claim": {"text": "...", "domain": "robotics", "context": {}},
  "expected_state": "confirmed",
  "note": "why this case matters — what failure mode it catches"
}
```

Cases should include at least one of each: a clean `confirmed`, a clean
`contradicted`, and — just as important — a genuine `undetermined` where
the honest answer really is "not enough evidence." A domain with no
`undetermined` cases in its eval set is probably over-claiming somewhere.

## Fixtures and placeholders

research_web cases fetch real URLs. To keep verdicts from rotting when a
third-party page changes, assertive cases point at a local server serving
`evals/fixtures/web/` (see `evals/fixture_server.py`); write their URL as
`{FIXTURE_BASE_URL}/<page>` and the runner substitutes the real address.
`research_web/live_example_com_drift.json` is the one live-internet case: it
accepts `confirmed`, `contradicted` and `undetermined` on purpose, because it
tests that the live path returns a real verdict and notices drift, not that
example.com's text is stable.

## Current coverage

`robotics` (7): `bluerov2_500m`, `bar30_500m` (contradicted);
`bar30_fails_500m_confirmed` (negated framing of the same fact — regression
for the stance-polarity bug), `bar30_100m_confirmed` (a claim the sourced
rating genuinely supports); `bluerov2_200m_conflict_undetermined` (sources
disagree), `bar30_ambiguous_polarity_undetermined`, `bar100xt_500m_undetermined`.
Every `confirmed` robotics case is backed by a sourced rating that really
supports it — none was added to fill the matrix.

`fpga_embedded` (3), `ml_data` (3), `research_web` (4: three local-fixture
cases plus the live drift case).
