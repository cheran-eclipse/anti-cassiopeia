# Draft: feedback for the Nebius x NVIDIA Global AI Hackathon's "Feedback Submission" field

Real, specific findings from building and testing Anti-Cassiopeia against
Nebius Token Factory over this project's full history — not generic
praise, each point traces to a real, dated finding in this repo. For the
submission form's feedback section (also eligible for the "Most Valuable
Feedback" bonus award, $100 + NVIDIA swag, 10 awarded).

## On Nebius Token Factory's API

1. **The pricing page (`nebius.com/prices-ai-studio`) returns content
   that a static/automated fetch can't read** — it renders the price
   table via JavaScript. Hit this independently, twice, in two different
   investigations months apart: `stress_test/results/NEMOTRON_PIVOT_REPORT.md`
   (chat-model pricing, 2026-10-24) and this project's hybrid-retrieval
   build's own evaluation report (embedding pricing, 2026-10-25). Both
   times we worked around it with third-party cost-aggregator pages
   (correctly caveated as unconfirmed-by-the-source-of-truth). A plain
   static pricing table, or a `/v1/models` response that includes
   per-model price, would remove a real, repeated friction point for
   anyone trying to track real spend against a budget — exactly what a
   hackathon entrant with a hard $20 credit cap has to do constantly.

2. **Model ID naming has a real, easy-to-hit footgun**: `Nemotron-3.5-Lightning`
   (with a dot) and `Nemotron-3_5-Lightning` (with an underscore) are
   DIFFERENT, unrelated model identifiers — the dot version doesn't
   exist as a real model on this account; the underscore version does.
   This was only caught by directly checking `GET /v1/models` rather than
   trusting the name as typically written in documentation/reports.
   Surfacing both the display name and the literal API `id` side-by-side
   anywhere a model is named in docs would prevent a real class of silent
   failures (calling a model that returns 404, or worse, silently
   resolving to the wrong model if naming is ever more lenient than it
   is today).

3. **`/embeddings` works exactly like OpenAI's own endpoint shape** (confirmed
   live, `Qwen/Qwen3-Embedding-8B`) — this made porting a real,
   already-evaluated hybrid-retrieval implementation from a sibling
   project trivial; no new client code was needed beyond a thin wrapper.
   This consistency is a genuine strength worth highlighting positively,
   not just a neutral finding — it's the reason a BM25+vector hybrid
   retrieval upgrade was buildable in a single session instead of a
   multi-day integration effort.

4. **A reasoning-capable model (Nemotron tiers, confirmed across Super/
   Ultra/3.5-Lightning) can spend its entire visible-output budget on
   hidden thinking tokens, returning `content: null` in an otherwise
   well-formed 200 response** if `max_tokens` isn't set generously. This
   is documented, real, and was the direct cause of a production crash
   found during this project's own model-comparison testing (`NEMOTRON_PIVOT_REPORT.md`).
   Fixed on our end by setting an explicit, generous `max_tokens`
   (16384) — but a clearer signal in the response itself (a distinct
   `finish_reason` value specifically for "ran out of budget mid-thought,"
   rather than the same shape a normal truncation would produce) would
   make this failure mode much faster to diagnose for the next team that
   hits it blind.

## On NVIDIA Nemotron models specifically

5. **Nemotron 3 Ultra earned a real, measured trust advantage on
   adversarial, high-stakes verification tasks specifically** — not a
   general "bigger is better" claim. Across 3 independent, adequately-
   sized live test runs on this project's own robotics hardware-spec
   verification task, Ultra was the ONLY tested tier (vs. Nano, Super,
   gpt-oss-120b baseline, Nemotron-3.5-Lightning) with a perfect
   zero-dangerous-miss record, every time — at roughly 7x baseline's
   per-call cost, which this project judged worth paying specifically
   because its whole premise is never being confidently wrong. The same
   "Ultra reasons more carefully on genuinely ambiguous judgments" pattern
   showed up again, independently, on a completely different sub-task
   (judging whether a passage actually asserts a causal/historical
   relationship, versus merely being consistent with one) — gpt-oss-120b
   got a real, reproduced test case wrong 4 of 6 tries; Ultra got it
   right 5 of 5. Two independent findings, same direction, different
   tasks — this is the kind of "serious reasoning" the hackathon's own
   Best Apps and Agents track guidance points builders toward, and it
   held up under real, repeated measurement, not just the expectation
   that a larger model should be better.

## On Tavily

6. **Tavily's search results were directly, measurably better than this
   project's own keyless fallback (DuckDuckGo HTML scraping + Wikipedia's
   search API)** for exactly the claims that fallback couldn't resolve —
   confirmed by a real production bug this project found in its OWN test
   harness (not in Tavily): every internal test script had been silently
   failing to load the Tavily API key into the process environment,
   masking how much Tavily actually helps. Once that was fixed, calling
   Tavily directly with the exact failing claim text returned the exact
   right source (including finding one specific published fact-check
   article by exact URL, on the first call) for every case tested. This
   is about as clean a "the dedicated tool beats the generic fallback"
   result as a hackathon judge could ask for — happy to detail the exact
   before/after numbers if useful for Nebius's own case studies.
