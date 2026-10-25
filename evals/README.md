# Evals

Run with: `PYTHONPATH=. python evals/run_evals.py`

Cases live at `evals/cases/<domain>/<case_id>.json`:

```json
{
  "claim": {"text": "...", "domain": "substrate", "context": {}},
  "expected_state": "confirmed",
  "note": "why this case matters — what failure mode it catches"
}
```

Cases should include at least one of each: a clean `confirmed`, a clean
`contradicted`, and — just as important — a genuine `undetermined` where
the honest answer really is "not enough evidence." A domain with no
`undetermined` cases in its eval set is probably over-claiming somewhere.

## Fixtures and placeholders

searchlight mode 1 (pre-selected URL) cases fetch real URLs. To keep
verdicts from rotting when a third-party page changes, assertive cases
point at a local server serving `evals/fixtures/web/` (see
`evals/fixture_server.py`); write their URL as `{FIXTURE_BASE_URL}/<page>`
and the runner substitutes the real address.
`searchlight/live_example_com_drift.json` is the one live-internet mode-1
case: it accepts `confirmed`, `contradicted` and `undetermined` on purpose,
because it tests that the live path returns a real verdict and notices
drift, not that example.com's text is stable.

searchlight mode 2 (`live_multi_candidate_*.json`) cases have NO `url` in
context — no fixture possible, by design: the whole point is live
candidate *discovery*, not checking one pre-selected page. These touch
the real internet (Wikipedia's search API + whatever it finds) every run;
each outcome (confirmed/contradicted/both undetermined shapes) was
independently verified live, repeatedly, before being written down — see
`domains/searchlight.py`'s module docstring for what's actually been
confirmed working vs. confirmed unreliable (DuckDuckGo search, blocked
from this dev sandbox) among the search backends.

## Current coverage

`substrate` (7): `bluerov2_500m`, `bar30_500m` (contradicted);
`bar30_fails_500m_confirmed` (negated framing of the same fact — regression
for the stance-polarity bug), `bar30_100m_confirmed` (a claim the sourced
rating genuinely supports); `bluerov2_200m_conflict_undetermined` (sources
disagree), `bar30_ambiguous_polarity_undetermined`, `bar100xt_500m_undetermined`.
Every `confirmed` substrate case is backed by a sourced rating that really
supports it — none was added to fill the matrix.

`silicon` (3), `quant` (3), `searchlight` (8: three local-fixture
mode-1 cases, the live mode-1 drift case, and four live mode-2
multi-candidate cases — one `confirmed`, one `contradicted`, and two
differently-shaped `undetermined` — no real source confirms vs. no real
candidate page found at all).
