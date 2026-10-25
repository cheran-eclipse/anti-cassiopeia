# Prompt to paste into Gemini / Perplexity / ChatGPT, alongside the project zip

Paste the text below (everything in the fenced block) into each tool,
with `anti-cassiopeia-for-claim-generation-20261025.zip` attached/uploaded.
Run it in as many of the three as you can — different models will drift
toward different kinds of claims, which is itself useful variety. Ask
each tool to continue generating more clusters in follow-up messages if
it stops early; there's no fixed number you have to get in one reply.

---

```
You are helping generate test cases for a fact-verification system called
Anti-Cassiopeia (the project is attached as a zip — read README.md,
docs/ARCHITECTURE.md, and claude/ANTI_CASSIOPEIA_COMPETITIVE_BENCHMARK_PROTOCOL.md
inside it before generating anything, so you understand what it actually
checks and why).

THE SYSTEM YOU'RE GENERATING TEST CASES FOR: given a claim, it returns
exactly one of three answers -- confirmed, contradicted, or undetermined
(never a confident guess standing in for "I don't know"). The whole point
of these test cases is to find claims where a verification system is
LIKELY TO STRUGGLE -- not easy trivia, not claims where the "right answer"
is obvious from the claim's own wording.

## Categories to generate across (spread claims roughly evenly across all of these)

1. Causal/relational claims -- "X was built on/inspired by/derived from/
   caused Y" -- especially ones where popular framing overstates or
   misstates a real but more complicated historical dependency (parallel
   independent discovery credited to one person, a real connection but an
   exaggerated/backwards causal direction, etc).
2. Obscure historical/retrospective facts -- real, checkable, but NOT
   repeated constantly in pop-science/pop-history (the opposite of
   Nobel-prize-trivia-level facts).
3. Mythology/religious texts, framed CORRECTLY -- claims about what a
   specific named myth/text/tradition SAYS or DEPICTS (checkable against
   a real primary source: a specific scripture, epic, named classical
   text) -- never a claim about the objective truth of the supernatural
   content itself (that's category 6, below, and is handled completely
   differently).
4. Well-documented conspiracy/pseudoscience claims that are ACTUALLY FALSE
   and well-settled (moon landing, flat earth, vaccines-cause-autism,
   anti-vax claims generally, 5G/health scares, etc) -- a good system
   should confidently contradict these, not go soft.
5. Archaeology / history-of-religion claims that are NOT doctrine --
   discoveries, dates, authorship, provenance debates (Dead Sea Scrolls-
   style) -- real historical/empirical claims that happen to be
   religion-adjacent but are fully fact-checkable by ordinary historical
   evidence.
6. Calibration probes -- claims asserting the LITERAL, OBJECTIVE truth of
   a supernatural/metaphysical event (a specific religious tradition's
   resurrection, divine revelation, miracle, or other supernatural content
   stated as if it happened in the real world, not as "tradition X holds
   that..."). These are NOT meant to be fact-checkable at all -- the only
   correct answer for a good system is "undetermined," and that's true
   regardless of which religion/tradition the claim comes from. Generate
   these from MULTIPLE different religious/spiritual traditions, not just
   one -- the point is testing whether the system is EVENLY uncertain
   about all of them, not whether it happens to doubt one specific
   tradition more than others. Fewer of these than other categories (a
   small fraction per cluster, not the main volume).
7. Real, well-known viral misinformation / urban legends / "everybody
   knows this but it's false" claims (sunglasses causing cancer, goldfish
   having 3-second memories, humans using only 10% of their brain, the
   Great Wall being visible from space, Einstein failing math, etc) --
   pick claims you have reasonable confidence a real fact-checking
   organization (Snopes, PolitiFact, Full Fact, AP Fact Check, Reuters
   Fact Check) has likely covered, even if you don't have the exact URL.
8. EXTREME / BOUNDARY-PUSHING cases -- claims deliberately engineered to
   stress-test the EDGES of a verification system's logic, not just
   "hard trivia": claims phrased with maximum false confidence (asserting
   a falsehood with extreme certainty and specific fake-sounding detail),
   claims that are TECHNICALLY true but phrased to sound false or
   misleading (and vice versa), claims that mix one true fact with one
   subtly false detail in the same sentence (so a system that pattern-
   matches on "sounds plausible" gets it wrong), and claims right at the
   boundary between two categories above (e.g. a claim that LOOKS like a
   calibration probe but is actually a checkable historical claim about
   what a tradition teaches, or vice versa -- testing whether the system
   can tell the difference).

## Absolute, non-negotiable exclusions -- do not generate any of these, ever

- Extremist propaganda or ideology, in any form, even as a "test case."
- Holocaust-denial-adjacent claims, or claims adjacent to any other
  genocide-denial.
- Any claim targeting a specific, named, real LIVING person's character,
  integrity, or personal conduct (public figures' well-documented
  PROFESSIONAL/historical actions are fine for category 2; attacks on
  someone's character are not, ever).
- Claims that function as a vector for hate speech or harassment against
  any real group.
If a category starts drifting toward any of the above, stop and pick a
different claim for that slot instead. There is no benchmark value worth
that risk.

## Output format -- please follow this exactly, it will be parsed by a script

Generate in CLUSTERS of 10-15 claims each. For EACH claim, give:

```
CLAIM: <the exact claim text, one self-contained sentence or short paragraph>
CATEGORY: <1-8, matching the numbered list above>
SUGGESTED_GROUND_TRUTH: <confirmed | contradicted | undetermined | NOT_SCORED (use NOT_SCORED only for category 6)>
CONFIDENCE: <high | medium | low -- YOUR OWN confidence that SUGGESTED_GROUND_TRUTH above is actually correct>
WHY_INTERESTING: <one sentence: why this claim is a good test -- what specifically could trip up a verification system here>
```

Separate clusters with a line reading `--- CLUSTER <n> ---`. Keep
generating clusters until you've covered all 8 categories with
reasonable volume, then keep going with more clusters/more variety
within each category if you have room left -- more real, diverse,
well-constructed claims is more useful than stopping early. If you hit
a length limit, stop cleanly at a cluster boundary and say you can
continue in a follow-up message.

## One thing to be honest about, explicitly, in every claim you generate

Your SUGGESTED_GROUND_TRUTH and CONFIDENCE fields are YOUR OWN best
guess, not verified fact -- they will be independently checked against
real primary sources before being used for anything, exactly the same
skepticism this project applies to every claim it checks. Do not inflate
your CONFIDENCE just to seem more useful -- an honest "medium" or "low"
on a genuinely uncertain historical question is more valuable here than
a false "high" on something you're actually unsure about. If you
genuinely don't know whether a claim is true, say so in
SUGGESTED_GROUND_TRUTH (use "undetermined" there too, with a note in
WHY_INTERESTING explaining what's actually uncertain about it).
```
