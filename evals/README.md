# Evals

Run with: `PYTHONPATH=. python evals/run_evals.py`

Cases live at `evals/cases/<domain>/<case_id>.json`:

```json
{
  "claim": {"text": "...", "domain": "substrate", "context": {}},
  "expected_state": "confirmed",
  "note": "why this case matters: what failure it catches"
}
```

Each domain should have a clean `confirmed`, a clean `contradicted`, and an
`undetermined` where the right answer is "not enough evidence". A domain
with no `undetermined` cases is probably over-claiming.

## Fixtures and placeholders

`searchlight` mode 1 (pre-selected URL) cases fetch real URLs. So that
verdicts don't change when a third-party page does, assertive cases point at
a local server serving `evals/fixtures/web/` (see `evals/fixture_server.py`).
Write the URL as `{FIXTURE_BASE_URL}/<page>` and the runner substitutes the
real address. `searchlight/live_example_com_drift.json` is the one live-internet
mode 1 case. It accepts `confirmed`, `contradicted` and `undetermined`,
because it tests that the live path returns a verdict and notices drift, not
that example.com's text is stable.

`searchlight` mode 2 cases (`live_multi_candidate_*.json`) have no `url` in
`context`, so no fixture is possible: they test live candidate discovery, not
one pre-selected page. They use the internet on every run (Wikipedia's search
API and whatever it finds). Each outcome (confirmed, contradicted, and both
undetermined shapes) was verified live, repeatedly, before it was recorded.
`domains/searchlight.py`'s module docstring says which search backends work
and which don't (DuckDuckGo is blocked from the dev sandbox).

## Current coverage (31 cases)

`substrate` (9):
- `bluerov2_500m`, `bar30_500m`, `bar100xt_1200m_contradicted`: contradicted.
- `bar30_fails_500m_confirmed`: the negated framing of the same fact, a
  regression test for the stance-polarity bug.
- `bar30_100m_confirmed`, `bar100xt_500m_confirmed`: claims the sourced
  ratings support.
- `bluerov2_200m_conflict_undetermined`: sources disagree.
- `bar30_ambiguous_polarity_undetermined`, `quspin_500m_undetermined`
  (QuSpin's source states no rating exists).

Every `confirmed` `substrate` case is backed by a sourced rating that
supports it; none was added to fill the matrix.

`quant` (6): single-stat confirmed and contradicted, multi-file, two
compound (AND) cases, and a missing dataset (`undetermined`).

`silicon` (7): timing confirmed and contradicted, two multi-corner cases, an
SVD register-offset case (`confirmed`), and two `undetermined` cases (an
unknown metric, and a register-map claim against a Vivado file).

`searchlight` (9): three local-fixture mode 1 cases, the live mode 1 drift
case, and five live mode 2 cases (`confirmed`, `contradicted`,
`contradicted` via a Tavily-found distributor page, and two `undetermined`:
fact absent from the candidates, and no candidate page found).
