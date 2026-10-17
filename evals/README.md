# Evals

Placeholder. Once a domain adapter has a real `gather_evidence()`
implementation (not the current stub returning `[]`), add test cases here
as `evals/cases/<domain>/<case_id>.json`:

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

No cases exist yet. Nothing is tested until a domain adapter is real.
