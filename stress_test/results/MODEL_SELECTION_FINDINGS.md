# Model-selection findings — consolidated

Every real, measured model-choice decision this project has made, in
one place, with its real evidence and the date it was decided. See
[INDEX.md](INDEX.md) for the full chronological report list this draws
from. Nothing here is a new measurement — this is a cross-reference of
decisions already made and already shipped in `anticassiopeia/`, so a
future session doesn't have to re-derive which model is used where, or
re-read five reports to find out why.

## Decision 1: `robotics.py`'s `propose()` → Nemotron Ultra

**Shipped as:** `anticassiopeia/domains/robotics.py`'s `ROBOTICS_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"`.

**Evidence:** [NEMOTRON_PIVOT_REPORT.md](NEMOTRON_PIVOT_REPORT.md),
2026-10-24. Ultra is the ONLY Nemotron tier proven, across THREE
independent runs at adequate sample size (n=15, n=40 pre-fix, n=40
post-fix), to have a perfect safety record on robotics: **zero
dangerous misses, every time.** Nano and Super both had real dangerous
incidents at n=40 (Nano 1, Super 3, on claims whose ground truth is
genuinely `undetermined` — both tiers sometimes guess confidently where
baseline correctly refuses). Cost: ~7x baseline gpt-oss-120b per call,
judged worth it for a project whose entire premise is not being
confidently wrong.

**Caveat already stated in the source report:** this recommendation
survived a REAL course correction — the first n=15 sample made Ultra
AND Super both look "tier-insensitive" (100%=100%), which was a
statistically underpowered conclusion the n=40 escalation overturned for
Super specifically. Worth remembering if a future round is tempted to
trust a small sample on a new model/domain combination.

## Decision 2: `research_web.py`'s `propose()` stays on `gpt-oss-120b`

**Shipped as:** no override — `ResearchWebAdapter`'s default client uses
`NebiusTokenFactoryClient()`'s own default model.

**Evidence:** same report. No Nemotron tier beat baseline on
`research_web` at ANY tested sample size; Ultra came closest (+2.5% at
n=40, post-fix, crash gone) but that's one sample against baseline's
10-run clean track record (165+110 robotics/research_web claims across
every pilot, zero dangerous misses, zero crashes, ever). The report's
own words: "revisit if a second independent research_web sample
confirms Ultra's edge holds" — that second sample has not been run.

**IMPORTANT — re-read this decision in light of the Tavily finding:**
every one of the research_web samples this decision was measured
against (baseline AND every Nemotron tier, across all pilots in this
report) was run through `stress_test/run_nemotron_pivot.py`, which —
like every other script in this directory — never called
`load_dotenv()`, so `research_web.py`'s real PRIMARY search backend
(Tavily) was silently disabled for every single one of these
measurements too (see [INDEX.md](INDEX.md)'s lead finding for the full
account). This decision was correctly made FOR THE SEARCH BACKEND THAT
WAS ACTUALLY ACTIVE during measurement (DDG/Wikipedia) — it is not
necessarily still the right call now that Tavily actually works. **This
is the single most concrete, actionable candidate for re-measurement
flagged by this whole findings review**: re-run the Nemotron pivot's
research_web pilots with `load_dotenv()` fixed, and check whether
gpt-oss-120b is still the best `propose()` model once the search step
is actually finding good candidates instead of falling back to DDG/
Wikipedia.

## Decision 3: `research_web.py`'s `judge_stance()` → Nemotron Ultra (separate from Decision 2, easy to miss)

**Shipped as:** `anticassiopeia/retrieval/stance.py`'s
`RECOMMENDED_STANCE_MODEL = "nvidia/Nemotron-3-Ultra-550b-a55b"`, wired
into `research_web.py` via a dedicated `stance_client` separate from its
`propose()` client (the one that stays on gpt-oss-120b per Decision 2).

**Evidence:** this session, 2026-10-25 (NOT in `NEMOTRON_PIVOT_REPORT.md`
— a later, separate decision, on a narrower question). Found while
fixing the causal-claim stance bug (`claude/ANTI_CASSIOPEIA_STANCE_CAUSAL_CLAIM_FIX_PROMPT.md`):
a real, REPRODUCED 10-call live comparison on the one genuinely
borderline causal/relational claim found gpt-oss-120b correct only 2/6
times, Nemotron Ultra correct 5/5. A 5-pair balanced sample (3
"should be unrelated" / 2 "should be supports" cases) showed both models
TIED 5/5 on the easier pairs — the gap is specific to genuinely
borderline judgments, not a general difference. This is a narrower,
better-evidenced decision than Decision 2 (which never found a
reproducible gap at all) — but still a single claim shape tested (causal/
relational judgments), not a general claim that Ultra is better at
`judge_stance()` across every claim type.

**Why this doesn't contradict Decision 2:** `propose()` (finding and
extracting a quote) and `judge_stance()` (judging whether an
already-verified quote supports/contradicts/is-unrelated-to a claim) are
different tasks measured separately, on purpose — this project's own
design keeps the two steps independent. A model can be the wrong choice
for one and the right choice for the other.

## Decision 4: Tavily as `research_web.py`'s primary search backend

**Shipped as:** `research_web.py`'s `_search_candidate_urls()` tries
`_tavily_search()` first, only falling back to DDG/Wikipedia when Tavily
contributes zero URLs.

**Evidence the decision was based on:**
[TEST3_REPORT.md](TEST3_REPORT.md)'s "A separate note on Tavily as a
live-search backend" section, 2026-10-18/19 — Tavily returned real,
structured results for 100% of 473 scored queries in the Tavily+Gemini
variant, a meaningfully more reliable profile than DDG (confirmed
anti-bot-blocked from this dev sandbox) or Wikipedia-only search
(narrow, topic-limited). That section explicitly names this as
"relevant to a possible future research_web upgrade" — this is that
upgrade, made good on.

**The decision was sound. Measuring it was not, until now.** Every
stress-test script that's since tried to measure `research_web.py`'s
real accuracy (Test #1, Test #2, Test #3's Pipeline/Nebius-agent rows,
the Nemotron pivot, round 1's first run) ran with Tavily silently
disabled by the missing-`load_dotenv()` bug — see [INDEX.md](INDEX.md).
The decision to make Tavily primary was correct and well-evidenced; the
project simply never got to see it working in its own test harness
until this session. Confirmed directly, live, same day as this
document: calling Tavily with the exact text of 3 of round 1's failing
claims returned excellent, directly on-point results (including finding
the EXACT Full Fact article for the sunglasses claim, and the real
Wikipedia page for the actual SpaceX lunar-impact event) — Tavily is not
a theoretical improvement, it demonstrably works, and the project's own
test numbers have been underselling it this whole time.

## Decision 5 (not yet made): whether to re-measure anything above

Flagged, not acted on, per this fork's own scope (organize, don't
re-engineer or re-spend):

1. **Highest-value candidate: re-run the Nemotron pivot's research_web
   pilots with the `load_dotenv()` fix in place.** Decision 2 (keep
   gpt-oss-120b) was made against a crippled search backend; it may or
   may not still hold once Tavily is actually active.
2. **Re-run Test #1/#2/#3's `research_web` legs** (24, 7, and 7 claims
   respectively — all small samples already) with the fix in place, for
   an apples-to-apples before/after on exactly how much Tavily helps in
   this project's own harness, not just in the isolated live checks done
   so far.
3. **Round 1 of the competitive-benchmark protocol** already has a
   corrected re-run in progress as of this writing (see
   [BENCHMARK_ROUND1_REPORT.md](BENCHMARK_ROUND1_REPORT.md) for whether
   it's landed) — once it has, its own before/after numbers are the
   cleanest small-scale demonstration of the Tavily fix's real impact,
   and worth citing ahead of a larger, costlier re-run of 1/2/3 above.

None of this is urgent in the sense of a production bug — the live
deployed service was never affected. It's an opportunity: this
project's own documentation of its research_web accuracy is currently
more pessimistic than the real, shipped system, and that's worth fixing
in the record, not just in code.
