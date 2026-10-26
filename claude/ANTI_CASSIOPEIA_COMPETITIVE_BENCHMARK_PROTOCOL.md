# Anti-Cassiopeia — competitive benchmark + self-improvement protocol

## PROMPT TO HAND TO THE NEXT SESSION, VERBATIM (and to every round after it)

This is a **repeatable protocol**, not a one-shot build — invoke it once per
round. Each round is bounded, stops, and reports back for the project
owner's own manual web fact-checking before the next round begins. Nothing
in here is an unsupervised, infinite, or autonomous loop: every round ends
with a human decision point, and every fix applied along the way needs a
real, stated root cause — never a prompt tweak that only makes one specific
test case pass.

## §0. What already exists — reuse it, do not rebuild it

`stress_test/` already has a real, tested, budget-tracked competitor
harness from a prior round:
- `run_test3_perplexity.py` — Perplexity API, real dollar cost tracked
  against its own already-provisioned free credits.
- `run_test3_tavily_gemini.py` — Tavily search + Gemini completion as a
  manually-wired "frontier model + live web search" competitor (direct
  Gemini search-grounding is blocked at the account/billing level — this
  variant exists specifically to work around that, documented in its own
  module docstring).
- `run_test3_generic_rag.py` — a plain, undifferentiated RAG baseline.
- `run_test3_nebius_agent.py` — retrieval+propose with NO independent
  verify step, i.e. "what if we skipped Anti-Cassiopeia's own mechanical
  verification and just trusted the model's citation" — this is the
  single most important baseline for this project's whole thesis, since
  it isolates exactly the value `verify_proposal()`'s independent re-check
  adds over a bare propose-and-trust pipeline.
- `run_test3.py` — the orchestrator, already wires all four together with
  separate, never-summed budget tracking per provider (Nebius sub-cap,
  Perplexity free-credit count, Tavily call count, Gemini real dollars).

**Read all five files in full before writing any new code.** Extend this
harness with new claims and, if genuinely needed, new competitor variants
(e.g. a raw Nemotron-Ultra-via-playground-equivalent API call, if not
already covered by one of the above) — do not create a second, parallel
comparison system.

**Addendum (post-causal-claim-fix round): a 6th variant now exists.**
`run_test3_bare_model.py` — a thin wrapper around the pre-existing
`run_test2_bare.py`'s `run_bare_batch()` (zero retrieval, zero tools,
just the claim asked directly of the same `openai/gpt-oss-120b` model
already used elsewhere, one real but tiny Nebius completion call per
claim). Wired into `run_test3.py`'s orchestration as "variant 2" (Test
#2's own numbering, since it's that same baseline, re-run against
whatever claims a given Test #3 invocation uses) alongside the four
above. Reused as-is for the SAME reason §0's own rule applies: it
already existed, with a smarter fabrication-detection flag for file-
dependent domains (`ml_data`/`fpga_embedded`) than a from-scratch
version would have had reason to build. A future round should check
for this kind of existing-but-not-yet-listed harness piece before
assuming something needs to be built new — the check that found this
one was reading `run_test2.py`'s own imports, not assuming §0's list
was exhaustive.

## §0.5. Fact-checking ORGANIZATIONS (Snopes, PolitiFact, Reuters Fact
Check, AFP Fact Check, Full Fact, AP Fact Check) are a DIFFERENT kind of
comparison than §0's live competitors — do not try to wire them in as a
sixth API-driven competitor variant

These sites are human-curated archives of already-published fact-checks,
not live systems that take an arbitrary new claim and return a fresh
verdict. None of them expose a general-purpose "check this claim" API —
what little API surface exists (e.g. Google's Fact Check Tools API) is
itself just a search over their existing published archive, not a live
checker. Ask one of these sites about a claim a journalist there has
actually investigated and written up, and you get a real, well-sourced
verdict; ask about anything else — which is most of this protocol's own
categories (obscure history, mythology-as-text, archaeology, calibration
probes) — and there's nothing there at all. Trying to "battle" them head
to head the way §3 battles Perplexity/Gemini/generic-RAG is not a fair
fight; it's comparing a live system to a specific, narrow archive.

**The correct use of these sites is as a GROUND-TRUTH SOURCE for a new
claim category, not as a sixth competitor in the loop:**

7. **Real, already-published fact-checks, re-verified independently**
   (new claim category, added to §1's list — call it category 7). Pick a
   small number of claims (2-4 per round is enough) that one of these
   organizations has ALREADY investigated and published a verdict on —
   ideally viral/political/health misinformation claims, since that's
   most of what they cover and it's squarely in `research_web`'s actual
   target use case, unlike the deliberately obscure/mythological claims
   elsewhere in this protocol. Feed Anti-Cassiopeia the claim text ONLY —
   never the fact-check article itself, never a link to it, nothing that
   would let retrieval just find and parrot back the existing
   fact-check — and let it do its own independent live search and
   verification. Then compare Anti-Cassiopeia's independently-reached
   verdict against the fact-checking organization's own published
   verdict (used here as ground truth, the same role primary sources play
   in every other category — not as a competitor being scored against
   Anti-Cassiopeia on the same scorecard row).
   - This is a STRONGER ground-truth source than anything else in §1,
     because it's real, professionally-researched, already-public, and
     wasn't picked or verified by whoever is running this round — reduces
     the risk of the round's own ground-truth-finding step quietly
     agreeing with whatever Anti-Cassiopeia said (a real failure mode to
     watch for in every other category too).
   - Sourcing claims for this category: WebSearch/WebFetch the
     fact-checking org's own site directly (e.g. search
     site:snopes.com or site:politifact.com for a recent published
     fact-check) to find real claims and their real published verdicts —
     this is something a session CAN do live, since it's reading one
     specific published page, not calling a nonexistent live-check API.
   - If Anti-Cassiopeia's independent verdict disagrees with the
     published fact-check, treat that with the same root-cause rigor as
     §3.6 — it could be a real gap worth fixing, or the fact-check could
     itself be stale/outdated (these organizations do sometimes revise
     or retract), or the claim as given to Anti-Cassiopeia may have lost
     context the original article had. Say explicitly which of these it
     looks like; never just mark it a loss without investigating.
   - Do NOT build or maintain a standalone "Snopes/PolitiFact competitor"
     module in `stress_test/` parallel to the ones in §0 — there is no
     live API to wire up, so there is no harness code to write here, only
     claim-sourcing (a research step, not a new competitor script).

## §1. The claim categories for this round — locked, with reasoning

Each round draws claims from these categories, roughly balanced across
Anti-Cassiopeia's domains where the category allows it:

1. **Causal/relational claims** (the Wiesner/BB84 shape) — "X was built
   on/inspired by/derived from Y." These are the category where a real,
   documented gap was already found (see
   `claude/ANTI_CASSIOPEIA_STANCE_CAUSAL_CLAIM_FIX_PROMPT.md` — apply that
   fix FIRST, before this round, if it hasn't shipped yet, so this round
   measures the post-fix behavior, not the known bug).
2. **Obscure historical/retrospective facts** — real, checkable, but not
   constantly repeated in pop-science/pop-history writing (contrast with
   Nobel-prize-trivia-level facts, which this project's own earlier
   testing already showed both raw models AND this system handle well —
   not where the interesting gap is).
3. **Mythology, framed correctly** — claims about what a myth/text/
   tradition SAYS (checkable against primary sources: Hesiod, Homer,
   named classical texts), never claims about the objective truth of a
   myth.
4. **Well-documented conspiracy claims** — claims that are actually false
   and well-settled (moon landing, flat earth, etc.) — the system should
   confidently, correctly CONTRADICT these with real evidence. A system
   that goes soft/UNDETERMINED on a well-settled false claim is itself a
   finding worth treating as seriously as a wrong CONFIRMED.
5. **Archaeology/history-of-religion claims that are NOT doctrine** —
   discoveries, dates, authorship, provenance (Dead Sea Scrolls, biblical
   archaeology dating debates, etc.) — real historical/empirical claims
   that happen to be religion-adjacent, fully fact-checkable.
6. **Calibration probes — matters of faith, NOT fact-checked for
   true/false at all.** A small number of claims asserting the literal
   truth of core religious doctrine (resurrection, divinity, etc.). THESE
   ARE NOT SCORED RIGHT/WRONG. The only thing being measured is: does the
   system correctly land on `UNDETERMINED` with reasoning that names this
   as outside what web evidence can settle, rather than forcing a verdict
   either direction? If it ever confidently CONFIRMS or CONTRADICTS one of
   these, that is itself the finding to write up — not "the model got it
   wrong," but "the system overreached into a claim type it should
   recognize as undecidable." Fewer of these than other categories (2-3
   per round is enough) — this is a boundary check, not the main event.
7. **Real, already-published fact-checks, re-verified independently** —
   see §0.5 above for the full rationale and sourcing method. 2-4 per
   round. Scored right/wrong/undetermined against the fact-checking
   organization's own published verdict, used as ground truth — NOT
   scored as a head-to-head competitor row; see §0.5's note on disagreement
   handling before marking one of these a loss.

**Explicitly excluded, every round, no exception:** any claim shaped like
extremist propaganda, Holocaust-denial-adjacent claims, or claims
targeting a specific real living person's character — never construct
these even as "test cases." This project's job is calibration on
legitimate ambiguous/obscure/mythological/conspiratorial claims, not
generating or legitimizing extremist content under a testing label. If a
category feels like it's drifting toward this, drop it and pick a
different one — there is no benchmark value worth that risk.

## §2. Per-domain scope, stated honestly

- `research_web` is where the real head-to-head competition lives — every
  competitor variant above can attempt a `research_web`-shaped claim.
  Most of §1's categories belong here, including the new category 7.
- `robotics` BYOE (single-document and pooled) is comparable too, but only
  against competitors given the SAME uploaded document as context (a fair
  fight needs the same evidence available to both sides) — don't compare
  Anti-Cassiopeia-with-a-document against a competitor with no document.
- `ml_data`/`fpga_embedded` are **not** a fair head-to-head category at
  all, and this round should say so plainly rather than force a
  comparison: these domains do real, deterministic local computation over
  a real CSV/Vivado report (recomputing an actual mean, actually parsing
  an actual timing summary) — no generic RAG/search competitor can do
  this at all without being handed the literal file and asked to compute
  by hand, which is a different, much weaker task than what they're
  actually built for. Framing this as "Anti-Cassiopeia wins" would be
  comparing apples to oranges; the honest framing is "this is a
  structural capability the competitor class doesn't have," which is
  worth stating once, clearly, rather than padding the scorecard with it.

## §3. One round, step by step

1. **Generate N claims** (suggest 6-10 total per round, not more — budget
   discipline, see §4) spread across §1's categories, skewed toward
   `research_web` and `robotics` per §2's scoping.
2. **Run every claim through Anti-Cassiopeia** (live, on the deployed
   service or the local engine directly — either is fine, local is
   cheaper if the deployed service isn't specifically what's being
   tested) via whichever endpoint fits the claim (`/verify`,
   `/verify/compound` for genuinely compound ones).
3. **Run the SAME claims through every applicable competitor variant**
   from §0, reusing the existing harness functions directly (don't
   re-implement the Perplexity/Gemini/generic-RAG calling code). Category
   7 claims (§0.5) are the exception — they are NOT run through §0's
   competitor harness at all, since there is no live fact-checking-org API
   to call; their "competitor" is the already-published verdict found
   during sourcing.
4. **Establish ground truth** for each claim from real, citable primary
   sources found during this step — not assumed, not taken from any one
   system's own answer. Where ground truth is itself genuinely uncertain
   or contested (this will happen for some of category 1/2), say so
   explicitly rather than forcing a right answer. For category 7, ground
   truth IS the sourced fact-check's published verdict (see §0.5) —
   skip re-deriving it from scratch, but do sanity-check it isn't itself
   stale/retracted.

   **Rule, found the hard way (round 2's `gemini-012`, Newton/Leibniz,
   2026-10-26) — not a one-off exception, apply to every future round:**
   a causal/priority claim can bundle a TRUE core relationship with a
   FALSE specific qualifier in the same sentence ("X and Y independently
   developed Z, at the EXACT SAME TIME" — the independent-development part
   is true; "exact same time" is not, when one party's work demonstrably
   predates the other's by a real margin). **Do not round this up to
   "confirmed" because the core relationship is right and "most popular
   accounts use similarly loose framing."** Popular looseness is not
   evidence the specific qualifier is true — it's evidence the popular
   framing is ALSO imprecise. Score the claim's qualifier as literally,
   specifically worded: if a real, citable source states a fact
   incompatible with that specific qualifier, the correct ground truth is
   `contradicted` (the claim as actually written is false), not
   `confirmed` with a caveat buried in the notes. This is the exact same
   literal-reading standard `retrieval/stance.py`'s own causal-claim
   paragraphs already hold the ENGINE to — ground truth sourcing must
   hold itself to the same standard, or a correct, literal engine verdict
   gets scored as a "dangerous miss" against ground truth that was
   itself too lenient. (`gemini-012` was re-scored `contradicted` under
   this rule — see `claims_round2_verified.json` and
   `BENCHMARK_ROUND2_REPORT.md`'s own correction note.)
5. **Score head-to-head** (right/wrong/undetermined against ground truth,
   for every system including Anti-Cassiopeia) EXCEPT category 6
   (calibration probes), which is scored separately as described in §1,
   and EXCEPT category 7, which is scored as Anti-Cassiopeia-vs-ground-truth
   only (no competitor row — see §0.5).
6. **For every claim where Anti-Cassiopeia is wrong, or meaningfully
   weaker than a competitor**, diagnose root cause with the SAME rigor as
   every prior fix in this project (the Wiesner stance-judgment fix is
   the house standard): is it a retrieval gap, a stance-judgment gap, a
   scoring/confidence-calibration issue, or a genuine, honestly-documented
   out-of-scope limitation (no OCR, BM25-only, etc.) that should NOT be
   hacked around? Never apply a fix that only works for the literal test
   claim used to find it — same "scoped to the real root cause, tested
   against the regression suite, documented honestly" discipline as every
   phase before this one.
7. **Apply fixes found this round** (if any), re-run the FULL offline test
   suite (must stay green), re-run every claim from EVERY PRIOR round
   (regression safety — a fix must not un-fix something already proven
   correct), then re-run this round's claims to confirm the fix actually
   worked.
8. **Stop. Report a scorecard** (per claim: ground truth, Anti-Cassiopeia's
   verdict, each competitor's verdict, right/wrong/undetermined, confidence
   where applicable) and a plain-language summary of what was found and
   fixed this round — same honest-write-up convention as
   `stress_test/BUGS_FOUND.md`. **Do not start another round automatically.**

## §4. Budget discipline — explicit, per-provider, same convention as `run_test3.py`

- Nebius: this round's own small sub-cap, e.g. $2-3 (well within whatever
  remains of the project's $20 total cap — check actual remaining balance
  before starting; state it in the round's own report).
- Perplexity/Tavily: call-count tracked, drawn from already-provisioned
  free credits — note if either is getting close to exhaustion.
- Gemini: real dollar cost, tracked separately, never summed into the
  Nebius figure (same separation `run_test3.py` already enforces).
- If any provider's budget is genuinely tight going into a round, say so
  BEFORE spending it, and either shrink the round's claim count or stop
  and ask, rather than quietly burning through what's left.
- Category 7 (§0.5) claims cost nothing beyond ordinary WebSearch/WebFetch
  usage for sourcing — there is no per-call API budget to track for the
  fact-checking organizations themselves, since nothing is being called
  live.

## §5. The human checkpoint between rounds

After a round's report, the project owner does their own manual web
fact-check on any claim where ground truth was uncertain or where a
competitor's and Anti-Cassiopeia's verdicts disagreed, and brings back
notes (corrected ground truth, additional context, a source that resolves
an ambiguity). **The next round's claim set should incorporate those
notes** — either re-testing a corrected claim, or using what was learned
about a source/category to pick the next round's claims more sharply.
This protocol is meant to be re-invoked this way, round after round, for
as many rounds as the project owner wants to keep running it — each
invocation is this same document, carried forward with whatever the
previous round's report and the owner's notes added.

## §6. What "self-improving" explicitly does NOT mean here

- Not unsupervised or autonomous — every round ends with a human
  checkpoint, no round starts itself.
- Not unbounded — hard per-round claim-count and budget caps, every time.
- Not prompt-golfing a specific test case — every fix needs a real,
  generalizable root cause, same bar as the rest of this project's history
  of documented fixes.
- Not "beat the competitors at any cost" — category 6 is explicitly NOT
  about winning; a correct `UNDETERMINED` there is the win condition, not
  a loss. The scorecard in §3.8 should make this distinction visible, not
  fold calibration probes into the same right/wrong tally as everything
  else. Category 7 is similarly not about "beating" Snopes/PolitiFact —
  see §0.5 — it's a ground-truth source, not a leaderboard opponent.
