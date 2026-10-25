# Decision 2 re-measurement — small, deliberate, live, Tavily now active

Date: 2026-10-25. Context: `MODEL_SELECTION_FINDINGS.md`'s "Decision 5"
flagged Decision 2 (`searchlight.py`'s `propose()` stays on
`openai/gpt-oss-120b`, never Nemotron Ultra) as made against a search
backend that was later found to be silently crippled (the `load_dotenv()`
bug — see that file's "Decision 4" and the project's commit history).
This note is the small, deliberate re-check that finding asked for — NOT
a re-run of the original 40-claim pilots, same budget discipline as the
investigation that settled Decision 3 (`judge_stance()` routing).

## Method

4 real claims, real ground truth, real live search (Tavily genuinely
active this time — confirmed via `load_dotenv()` before construction),
run through the real `SearchlightAdapter`/`VerificationEngine` twice:
once with `propose()`'s client set to `openai/gpt-oss-120b` (current
default), once with it set to `nvidia/Nemotron-3-Ultra-550b-a55b` — same
technique as the live paired test that settled Decision 3. Claims: the
ARPANET "LOGIN" claim (confirmed), the Darwin/Wallace causal claim
(contradicted), the moon-landing conspiracy claim (contradicted), the
Dead Sea Scrolls claim (confirmed) — all 4 from competitive-benchmark
round 1's claim set, chosen because their real ground truth is already
established and documented.

## Result

**Both models: 4/4 correct, identical verdicts and near-identical
confidence on every claim.**

| Claim | Ground truth | gpt-oss-120b | Nemotron Ultra |
|---|---|---|---|
| ARPANET "LOGIN" | confirmed | confirmed (0.90) | confirmed (0.90) |
| Darwin/Wallace | contradicted | contradicted (1.0) | contradicted (1.0) |
| Moon-landing hoax | contradicted | contradicted (0.90) | contradicted (0.90) |
| Dead Sea Scrolls | confirmed | confirmed (1.0) | confirmed (1.0) |

## Reading this honestly

This is a small sample (n=4) — not a re-run of the original pivot's
40-claim pilots, and not a basis for a strong new claim either direction.
What it DOES show: now that Tavily is genuinely finding good candidates
(unlike every prior measurement of this decision), there is still no
visible gap between the two models on `propose()` specifically. **The
original decision — keep `searchlight.py`'s `propose()` on
`gpt-oss-120b` — holds, now on marginally better evidence than before**
(the prior evidence was measured on a crippled search backend; this
small re-check used the real one). At ~7x Nemotron Ultra's cost for zero
measured accuracy gain on this sample, there is no reason found here to
change Decision 2.

This does NOT settle the question at the same statistical rigor
`NEMOTRON_PIVOT_REPORT.md` applied to Decision 1 (n=15 then n=40,
twice, with a real course correction along the way) — if Decision 2 is
ever revisited at that scale, do it with Tavily active from the start,
unlike the original pivot. Not acted on further here, per this note's
own small-scale, budget-conscious purpose.
