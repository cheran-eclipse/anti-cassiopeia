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

## Current coverage

`robotics` has 3 cases, all passing: `bluerov2_500m` (contradicted),
`bar30_500m` (contradicted), `bar100xt_500m_undetermined` (undetermined).

**No `confirmed` case exists yet, on purpose.** None of the facts
Constellation actually sourced happen to support any claim tested so far
— every real part found so far fails a 500 m condition, or is unsourced.
Adding a fabricated "confirmed" case just to fill the matrix would be
exactly the kind of unearned confidence this project exists to refuse.
Add one once a real sourced fact that *supports* some claim shows up —
not before.

`fpga_embedded`, `research_web`, `ml_data` have no cases yet — their
adapters are still stubs (`gather_evidence()` returns `[]`).
