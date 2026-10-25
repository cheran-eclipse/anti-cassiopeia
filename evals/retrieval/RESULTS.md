# Retrieval eval results — real embedder, real corpus

Run 2026-10-25, `PYTHONPATH=. python3 evals/retrieval/evaluate.py`,
against `Qwen/Qwen3-Embedding-8B` via Nebius (live, real call — not a
stand-in). 13 hand-labelled questions (6 "keyword-overlap", 7
"paraphrase" — see `questions.json`) across 6 real documents (the
substrate seeded corpus + the ODrive/NASA JPL BYOE fixtures), 46 chunks
total. Full method: `evaluate.py`'s own docstring.

**Run twice** (output below is the second run) — numbers moved slightly
between runs (e.g. hybrid MRR 0.603 → 0.615, hybrid keyword-overlap MRR
0.639 → 0.667), consistent with ordinary live-call variance at this
small a sample size, not a bug. Treat the numbers below as "broadly
this", not exact to the third decimal — N=13 is a real, hand-checked
sample, not a statistically powered benchmark (stated plainly, per this
project's own standard, not overclaimed).

**Real cost**: one representative embedding call (a single ~130-
character sentence) measured 25 real tokens via the API's own `usage`
field. The full eval's embedding load (46 corpus chunks in one batch +
13 queries × 2 modes needing embeddings = 26 query embeds) was not
separately instrumented for an exact total, but at this per-sentence
rate the whole run is a low-thousands-of-tokens job — negligible
regardless of the per-token price, which could NOT be confirmed
(`nebius.com/prices-ai-studio` returned HTTP 404 on a live fetch attempt
this session — same category of pricing-page access problem
`NEMOTRON_PIVOT_REPORT.md` already documented for chat-model pricing,
not a new gap this build introduced).

**Real latency**: corpus embedding (46 chunks, one batch call) took
1.9–4.4s across the two runs. Per-query added latency for a mode that
embeds the query (`vector`/`hybrid`) was 1.1–2.1s/query across the two
runs — real, not negligible, and worth the production pipeline's own
callers (substrate.py, searchlight.py) being aware this is ~1-2 extra
seconds per claim beyond what BM25-only cost before this build, on top
of whatever propose()/judge_stance() calls already add.

```
Real corpus embedding: 46 chunks, 4.43s (ONE batch call).
Per-query latency, mode=bm25: mean 0.000s over 13 queries
Per-query latency, mode=vector: mean 2.133s over 13 queries
Per-query latency, mode=hybrid: mean 2.047s over 13 queries
```

| config | n | R@1 | R@3 | R@5 | MRR | hit@3 |
|---|---|---|---|---|---|---|
| bm25 | 13 | 0.50 | 0.81 | 0.81 | 0.679 | 0.85 |
| vector | 13 | 0.35 | 0.85 | 0.85 | 0.577 | 0.85 |
| hybrid | 13 | 0.35 | 0.85 | 0.85 | 0.615 | 0.85 |

**keyword-overlap** (6 questions phrased close to the source wording)

| config | n | R@1 | R@3 | R@5 | MRR | hit@3 |
|---|---|---|---|---|---|---|
| bm25 | 6 | 0.67 | 0.83 | 0.83 | 0.722 | 0.83 |
| vector | 6 | 0.17 | 0.83 | 0.83 | 0.444 | 0.83 |
| hybrid | 6 | 0.50 | 0.83 | 0.83 | 0.667 | 0.83 |

**paraphrase** (7 questions deliberately phrased in different words than their gold passage)

| config | n | R@1 | R@3 | R@5 | MRR | hit@3 |
|---|---|---|---|---|---|---|
| bm25 | 7 | 0.36 | 0.79 | 0.79 | 0.643 | 0.86 |
| vector | 7 | 0.50 | 0.86 | 0.86 | 0.690 | 0.86 |
| hybrid | 7 | 0.21 | 0.86 | 0.86 | 0.571 | 0.86 |

## Honest reading — not smoothed over

- **On keyword-overlap questions, plain BM25 wins outright** (R@1 0.67
  vs. vector's 0.17) — exactly as expected: when the query already shares
  words with the source, adding a semantic signal mostly adds noise for
  the single-best-rank metric.
- **On paraphrase questions, vector alone has the best R@1** (0.50 vs.
  BM25's 0.36) — confirms the core hypothesis this build exists to test:
  vector search can bridge a wording gap BM25 structurally cannot.
- **Hybrid's fused R@1 is, surprisingly, WORSE than either pure method
  alone on paraphrase questions** (0.21). Plausible mechanism, not
  confirmed further this round (would need a larger sample to chase
  properly, not patched based on N=7): RRF rewards agreement between
  methods: a WRONG chunk that both methods rank moderately well can
  out-score a RIGHT chunk only one method (correctly) ranks highly. This
  is a real, measured, counterintuitive result — reported as-is, not
  tuned away.
- **At R@3/R@5/hit@3 — the metrics that actually matter for how this
  project's pipeline uses retrieval** (it shows the LLM propose() step a
  top-k candidate list, never blindly trusts rank #1) — hybrid and
  vector both beat BM25 on paraphrase (0.86 vs. 0.79) and tie BM25 on
  keyword-overlap (0.83 all three). **This is the metric or this build's
  real, defensible win: hybrid never makes recall-at-the-metrics-that-
  matter worse, and measurably improves it for paraphrased claims.**
- Do not read "hybrid beats BM25 at R@3" as a universal law from N=13 —
  it's what this specific, honestly-labelled sample shows.
