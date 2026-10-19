# Stress Test #3: Anti-Cassiopeia vs. external competitors and baselines

**Date:** 2026-10-18/19
**Sample:** the SAME 1,000-claim stratified subset of the 3,311-claim
manifest that Test #2 already used (`stress_test/claims/test2_sample.jsonl`)
— no new claims generated, so every row below is exactly apples-to-apples
with Test #2's already-measured pipeline and bare-Nebius numbers.

Seven rows, a deliberate ladder of "how much grounding/verification":

1. **Pipeline** — the real Anti-Cassiopeia engine. Measured in Test #2, reused by claim ID here, not rerun.
2. **Bare Nebius** — one ungrounded completion, no retrieval/tools. Measured in Test #2, reused, not rerun.
3. **Nebius-agent** — the real pipeline's retrieval (chunking, BM25, domain-tuned queries) and real `propose()` call, but `verify_proposal()` skipped — propose()'s raw output trusted as final. NEW this test.
4. **Generic RAG** — a self-built, naive FacTool/RARR-style checker: real source text, generic chunk+BM25 retrieval (raw claim text as the query, not a domain-tuned question), one LLM call, no verify. NEW this test.
5. **Perplexity** (`perplexity/sonar` via its Agent API) — an external cited-answer API. NEW this test.
6. **Tavily + Gemini** — Tavily live web search feeding a Gemini completion. NEW this test (replaces a Gemini-grounding variant blocked at the account level — see Known Limitations).
7. **SAFE (DeepMind, LongFact)** — cited, not run live. Different data/methodology — context, not a controlled comparison.

Nothing in `anticassiopeia/` was touched — variants 3/4 import it read-only (variant 3 via a runtime monkeypatch of `verify_proposal` scoped to this test's own process, restoring the real function afterward and writing nothing to disk; variant 4 via the same chunking/BM25 utilities used mechanically). Full methodology, including the VERDICT MAPPING for each external API, is in each variant's own module docstring (`stress_test/run_test3_*.py`).

## The comparison table

Accuracy/dangerous/conservative are against the exact same ground truth as every other test in this project. Cost and latency are real, measured, per-claim figures — not estimated.

| Row | n | Correct | Dangerous | Conservative | Other/crash | Cost/claim | Notes |
|---|---|---|---|---|---|---|---|
| 1. Pipeline | 1,000 | **99.9%** | **0.0%** | 0.1% | 0.0% | ~$0.00017 (Test #2) | real retrieve→propose→verify |
| 2. Bare Nebius | 1,000 | 17.7% | 4.1% | 78.2% | 0.0% | ~$0.00012 (Test #2) | zero grounding |
| 3. Nebius-agent | 1,000† | 99.9% | **0.0%** | 0.1% | 0.0% | $0.000413 | real retrieval, NO verify |
| 4. Generic RAG | 1,000 | 29.3% | 16.9% | 45.4% | 8.4% | $0.000461 | naive chunk+BM25, no domain tuning |
| 5. Perplexity | 1,000 | 10.1% | 3.5% | 86.4% | 0.0% | $0.0000968 | external cited-answer API |
| 6. Tavily+Gemini | 473‡ | 11.0% | 4.7% | 83.5% | 0.8% | gemini $0.000574 | Gemini daily quota ran out — see below |
| 7. SAFE (cited) | ~16,000 facts | 72%§ | — | — | — | — | different methodology, see below |

† Nebius-agent's own live code only runs on robotics/research_web claims (128 of the 1,000); ml_data/fpga_embedded never call `propose()`/`verify_proposal()` at all, so this variant is **byte-for-byte identical to the pipeline** for those 872 claims — their results are copied from Test #2's pipeline run, not meaninglessly rerun. Restricting to just the 128 claims that actually exercise the no-verify code path: **99.2% correct, 0.0% dangerous, 0.8% conservative** — one single miss (`research_web-003300`), which is the EXACT SAME claim the full pipeline also misses conservatively (see "What the ladder shows," below).

‡ Tavily+Gemini only completed 473 of 1,000 claims live before Gemini's free-tier daily quota ran out (a real external limit, not a bug — see Known Limitations). The remaining 527 were cleanly skipped by a circuit breaker, not force-run into a crash tail. This row's percentages are over the 473 it actually scored, not the full 1,000 — a smaller, real sample, stated plainly.

§ SAFE's "72%" is agreement with human annotators on ~16,000 individual facts from long-form model-generated text graded against live web search — NOT claims checked against this project's fixed source documents. See "SAFE benchmark" section below for why this is context, not a controlled comparison row.

## Per-domain breakdown

| Domain | Pipeline | Bare | Nebius-agent | Generic RAG | Perplexity | Tavily+Gemini (scored n) |
|---|---|---|---|---|---|---|
| ml_data (n=756) | 100.0% / 0.0% / 0.0% | 13.5% / 2.1% / 84.4% | 100.0% / 0.0% / 0.0% (copied) | 30.3% / 20.6% / 44.2% | 7.7% / 3.4% / 88.9% | 14.0% / 5.9% / 79.3% (n=357) |
| fpga_embedded (n=116) | 100.0% / 0.0% / 0.0% | 1.7% / 0.0% / 98.3% | 100.0% / 0.0% / 0.0% (copied) | 17.2% / 1.7% / 63.8% | 1.7% / 0.0% / 98.3% | 1.7% / 0.9% / 96.6% (n=116) |
| robotics (n=121) | 100.0% / 0.0% / 0.0% | 56.2% / 19.0% / 24.8% | 100.0% / 0.0% / 0.0% (live) | 34.7% / 9.1% / 33.9% | 28.9% / 6.6% / 64.5% | all skipped (quota ran out first) |
| research_web (n=7) | 85.7% / 0.0% / 14.3% | 71.4% / 28.6% / 0.0% | 85.7% / 0.0% / 14.3% (live, identical) | — | — | all skipped (quota ran out first) |

(Each cell: correct% / dangerous% / conservative%. Generic RAG's `fpga_embedded`/`robotics` "other/crash" share — not shown per-cell above — is the schema-drift finding below.)

## What the ladder shows about where Anti-Cassiopeia's accuracy comes from

Reading the ladder bare → generic RAG → Nebius-agent (tuned retrieval, no verify) → full pipeline:

- **Bare → generic RAG (17.7% → 29.3% correct, but dangerous RISES from 4.1% to 16.9%):** giving an LLM real source text with no domain knowledge of how to search it or extract from it helps a little, but the dangerous-error rate more than quadruples. Generic RAG's naive retrieval (raw claim text as the BM25 query, mechanical chunking of whatever file/pages it finds) surfaces *some* real content, but with no domain-aware extraction or verification, the model is now confidently wrong more often than when it had nothing at all. **More retrieval without grounding discipline is not strictly safer than no retrieval.**
- **Generic RAG → Nebius-agent (29.3% → 99.9% correct; dangerous 16.9% → 0.0%):** this is the single largest jump on the ladder, and it comes entirely from REPLACING naive generic retrieval with Anti-Cassiopeia's own domain-tuned retrieval (the right query for the right document, the right file read directly instead of blindly chunked) — **before verify_proposal() is even added back in.** This is the strongest evidence in this test that most of this project's real accuracy gain is architectural: knowing *what to look for and where*, not a generic "throw an LLM at retrieved text" pattern.
- **Nebius-agent → full pipeline (99.9% → 99.9% correct; both 0.0% dangerous):** on THIS 1,000-claim sample, adding the independent verify step back in changed **zero** final verdicts — restricted to the 128 claims that actually exercise `propose()`/`verify_proposal()` at all, Nebius-agent and the pipeline produced identical results, down to missing the exact same single claim (`research_web-003300`) the exact same way. **This does not mean verify_proposal() is valueless** — it is a structural safety net against quote fabrication (an LLM citing a chunk_id or quote that was never actually said), and this sample's live model simply didn't trigger that failure mode on these specific 128 claims. What it DOES mean, measured strictly by outcome accuracy on this run: this project's accuracy lead over a plausible "pipeline minus independent verification" competitor comes almost entirely from having the right domain-aware retrieval in the first place, not from the verify step catching live fabrications — on this sample. A larger or adversarially-selected sample could show verify_proposal() earning its keep; this test did not happen to surface that case.

## Fabricated-detail: a reused heuristic that means something different for context-having variants

Test #2 defined `fabricated_detail` for BARE NEBIUS specifically: a confident confirmed/contradicted verdict on an `ml_data`/`fpga_embedded` claim with zero acknowledgement that the model has no access to the file at all. That's unambiguous fabrication, because the model genuinely has nothing.

Generic RAG, Perplexity, and Tavily+Gemini are different: they DO receive real, retrieved context (generic RAG shows real file chunks; Perplexity and Tavily+Gemini search the live web). Reusing the same "no access-awareness language" heuristic on these three doesn't mean the same thing — a confident answer grounded in genuinely-retrieved context isn't fabrication just because the model didn't hedge. Reported honestly, not relabeled to look more dramatic than it is:

| Variant | "No access-awareness" rate on ml_data/fpga_embedded (n=872) | Of those, confidently WRONG |
|---|---|---|
| Generic RAG | 46.4% (405/872) | 158 (39.0% of the flagged subset) |
| Perplexity | 9.6% (84/872) | 26 (31.0%) |
| Tavily+Gemini | 15.2% (72/473 scored) | 22 (30.6%) |

The useful number here isn't the "fabrication" label — it's that roughly **30% of confident, unhedged answers across all three context-having variants were simply wrong**, on claims about real local files none of these three variants were ever given the actual contents of in a form their retrieval could reliably use (generic RAG's own chunking of a huge file like `superconductivity.csv` took up to 239 seconds and still didn't guarantee the right chunk was retrieved; Perplexity/Tavily+Gemini searched the live web for a local test-harness file that was never published online at all). Bare Nebius's own Test #2 finding — 13.5% outright fabrication with no retrieval at all — remains the single cleanest demonstration of this failure mode; these three numbers are a related but distinct one.

## Known limitations hit during this test (recorded here, not smoothed over)

- **Gemini Google Search grounding is blocked at the account level.** Confirmed live, repeatedly: `GEMINI_API_KEY` works for plain generation (HTTP 200) but returns `429 RESOURCE_EXHAUSTED` the instant the `google_search` grounding tool is attached — tried as `google_search`, `googleSearch`, and `google_search_retrieval`, across `gemini-flash-latest`, `gemini-3.1-flash-lite`, `gemini-3.5-flash-lite`, and `gemini-pro-latest`. Consistent with Google's own pricing page (`https://ai.google.dev/gemini-api/docs/pricing`, read 2026-10-18): grounding's Free Tier column reads "Not available" even though the Paid tier gets 5,000 free grounded requests/month — this key evidently has no billing account linked, so it can't reach even that nominally-free allotment. This is why variant 6 is Tavily+Gemini (a manually-wired retrieve-then-answer substitute) instead of Gemini's own grounding tool.
- **Perplexity's documented `/chat/completions` "Sonar" endpoint is retired.** It now returns `403` with `"Sonar is now the Agent API. Use /v1/responses instead."` The current working call is `POST https://api.perplexity.ai/v1/responses` with `model: "perplexity/sonar"` — confirmed live before any pilot spend, since several other plausible model names (`sonar`, `sonar-pro`, the old `llama-3.1-sonar-*-online` names) all return `400 "not supported"` under the new endpoint.
- **Gemini's free tier has a real per-model DAILY request quota, not just a rate limit.** The pilot's first attempt (`gemini-flash-latest`, resolving to `gemini-3.8-flash`) hit `429 RESOURCE_EXHAUSTED` with an explicit `GenerateRequestsPerDayPerProjectPerModel-FreeTier` quota of **20 requests/day** — 15 of 28 pilot claims crashed before this was caught (recorded honestly in the raw results and in `BUGS_FOUND.md`, not deleted). Switched to `gemini-flash-lite-latest` (`gemini-3.5-flash-lite`), a separate quota bucket, which ran the pilot cleanly — but the FULL 1,000-claim run exhausted even that model's daily quota after 473 real calls. A circuit breaker added after the pilot (2 consecutive quota-exhaustion errors trips it) stopped the batch cleanly at that point instead of burning Tavily credits on a guaranteed-fail tail for the remaining 527 claims, which are marked `SKIPPED_QUOTA` in the raw results, not scored as crashes or wrong answers.
- **Generic RAG's answer format drifted from the requested schema.** 83 of 1,000 claims (8.4%) came back `unparseable` — the model answered with a synonym ("**Supported**") instead of the literal word "confirmed" the prompt asked for, or otherwise didn't use any of the three canonical words. This is a genuine, reportable weakness of a naive prompt/parser combination (consistent with this variant's own design goal — a competent but NOT over-engineered generic baseline), not something patched to make the comparison look cleaner.
- **Generic RAG's naive full-file chunking has a real, heavy-tailed cost on large files.** ml_data's generic-RAG latency: median 2.37s, but mean 19.13s and a worst case of 239.5s, for `ml_data-002136` against `superconductivity.csv` (a large real UCI file) — building a from-scratch pure-Python BM25 index over the thousands of chunks a naive 500-character chunker produces from a multi-megabyte file is genuinely slow. The production `ml_data` adapter avoids this entirely by streaming the file with `csv.reader` and computing the statistic directly — no chunking, no index, no LLM call at all.

## A separate note on Tavily as a live-search backend (relevant to a possible future research_web upgrade)

Kept deliberately separate from the main comparison table above — this is about Tavily's *retrieval quality*, not about the Tavily+Gemini variant's final verdict accuracy (which the table already covers).

Tavily returned real, structured results (title, URL, a real content snippet, a relevance `score`) for every one of the 473 scored queries and the smoke/pilot queries before that — zero outright search failures observed in this test, a meaningfully different reliability profile from `research_web.py`'s own current DuckDuckGo backend (confirmed anti-bot-blocked from this dev sandbox in earlier work) or even its Wikipedia-only fallback (narrow, topic-limited coverage). Tavily's results also came back pre-summarized (a `content` field of cleaned prose, not raw HTML needing `_strip_html()`), which would simplify `research_web.py`'s own candidate-fetching code if adopted there. This test does not evaluate Tavily's result *ranking* quality in depth (that would need its own study against known-answer queries), and Tavily is a paid API with its own cost/credit model unlike the current keyless DuckDuckGo/Wikipedia approach — both real tradeoffs a future research_web upgrade decision would need to weigh, not evaluated further here.

## SAFE benchmark (DeepMind, LongFact) — cited for context, not run live

DeepMind's SAFE (Search-Augmented Factuality Evaluator), from the LongFact benchmark work, reported **72% agreement with human annotators on ~16,000 individual facts**, and in the roughly 100 cases where SAFE and human raters disagreed, a follow-up check found **SAFE itself was right 76% of the time**.

This is genuinely different data and a genuinely different methodology from everything else in this report, stated plainly rather than implied as equivalent: SAFE grades individual factual claims PULLED OUT OF long-form, open-ended model-generated text, checked against live web search — there is no fixed, pre-defined ground truth document the way every claim in this project's own manifest has one (a real CSV's actual computed statistic, a real Vivado timing report's actual value, a real corpus excerpt's actual stated rating). SAFE's "72%" and Anti-Cassiopeia's "99.9%" are not measuring the same task, the same claim difficulty distribution, or the same notion of "ground truth," and should not be read as two numbers on the same scale. It is included here because the task that prompted this test asked for it as context for anyone evaluating this project against the broader fact-checking literature — not because it is a controlled comparison.

## Actual spend

| | Cost | Against |
|---|---|---|
| Nebius (variant 3, pilot+full) | $0.052791 | $20.00 project cap |
| Nebius (variant 4, pilot+full) | $0.460615 | $20.00 project cap |
| **Nebius subtotal, this test** | **$0.513406** | |
| Nebius cumulative (Test #1 $0.216879 + Test #2 $0.183357 + Test #3 $0.513406) | **$0.913642** | **4.57% of the $20.00 cap** |
| Perplexity (variant 5) | $0.096780 | its own free credits, not the $20 cap |
| Gemini (variant 6's completion leg) | $0.271397 | separate provider, its own billing |
| Tavily (variant 6's search leg) | 473 calls | its own free Researcher-tier credits, no $ figure returned by the API |

The hard stop was never approached on any of the four tracked budgets.
