# Round 2 candidate claims — externally generated, not yet verified

Generated 2026-10-25 by three external AI tools (ChatGPT, Gemini, Perplexity)
from `claude/CLAIM_GENERATION_PROMPT_FOR_EXTERNAL_AI.md` — ChatGPT and Gemini
via that prompt pasted into their chat UI alongside the project zip
(`anti-cassiopeia-for-claim-generation-20261025.zip`), captured here as
`source_chatgpt_gemini.docx` (both tools' output in one file, split by a
`Gemini:` header partway through); Perplexity via a direct call to its
`/v1/responses` API instead, since its chat UI doesn't support file
uploads — the prompt was adapted inline (no zip reference, project context
summarized in the prompt text itself) and run once, captured as
`source_perplexity_raw.txt`.

## What's here

- `source_chatgpt_gemini.docx`, `source_perplexity_raw.txt` — raw outputs,
  unedited, kept for provenance.
- `claims_round2_raw_undeduped.json` — all 185 claims parsed out of the two
  raw sources (96 ChatGPT + 56 Gemini + 33 Perplexity), before dedup.
- `claims_round2_candidates.json` — **the dataset to actually use.** 171
  entries after removing 14 true duplicates (see below). Each entry carries
  the external AI's own `suggested_ground_truth`/`suggested_confidence` —
  **these are hypotheses from the generating model, not verified fact**, per
  the generation prompt's own explicit, non-negotiable condition. Nothing
  here has been independently checked against primary sources yet.

## Parsing

Both `CLAIM:`/`CATEGORY:`/`SUGGESTED_GROUND_TRUTH:`/`CONFIDENCE:`/
`WHY_INTERESTING:` layouts were used by different generators (ChatGPT: one
field per line; Gemini: all five fields concatenated on a single line per
claim) — parsed with one regex keyed on the field labels themselves, not
line structure, so both layouts parse identically. Verified against a raw
`grep -c "CLAIM:"` count: 96 ChatGPT + 56 Gemini + 33 Perplexity = 185,
exact match, nothing lost or double-counted.

## Dedup — 14 true duplicates removed, by hand, after the fact

An automatic near-duplicate pass (token-Jaccard similarity over the claim
text) found 17 candidate pairs/groups. Each was read in full and judged
individually — automatic similarity caught real duplicates (independently
generated, same core assertion) but also several false positives: claims
that share vocabulary/topic but assert genuinely different things. Kept
separate despite high lexical overlap:

- The two 1919-eclipse claims (one states the real, hedged historical fact;
  the other builds a false overreach — "general relativity has never
  received independent confirmation" — on top of the same premise).
- The two Gilgamesh flood claims (one names the correct god who warns
  Utnapishtim privately; the other plants a specific wrong-god detail —
  a deliberate factual trap, not the same claim restated).
- The Jesus/Osiris resurrection pair — this is an intentional cross-tradition
  calibration probe pair per the generation prompt's own category-6
  instruction ("generate from MULTIPLE different traditions... testing
  whether the system is EVENLY uncertain about all of them"), not a
  duplicate. (Jesus-resurrection *was* merged across chatgpt+perplexity,
  since those two really are the same claim restated.)
- Several category-8 robotics/FPGA pairs that share dense technical
  vocabulary (Jacobians, fixed-point bits, inverse dynamics) but assert
  different specific false inferences.

Actually merged (same core assertion, independently produced by 2-3
generators — itself a useful signal: when three unrelated AIs independently
converge on the same test claim, that's evidence it's a genuinely
well-known/well-covered case, not cherry-picked): Apollo staging, vaccines/
autism, 5G/COVID, Great Wall visibility (3-way), 10%-of-brain myth, goldfish
memory (3-way), Einstein's math, Antikythera mechanism, Newton/Leibniz
calculus, Shroud of Turin dating, the redundant-manipulator null-space
claim, and the Jesus-resurrection probe. Merged entries carry `generated_by`
(which sources produced it) and `duplicate_ids`. The Antikythera pair was
independently categorized as category 2 by ChatGPT and category 5 by
Gemini — flagged as `category_disagreement`, not resolved by merging; that
disagreement is itself informative about how fuzzy the category boundary
is in practice.

## Dataset shape — read before planning any test run

171 claims. By category: 1→20, 2→17, 3→14, 4→11, 5→14, 6→14, 7→12, **8→69**.

Category 8 is 40% of the whole set — almost entirely dense control-theory/
FPGA formal claims from ChatGPT (Jacobian null-spaces, fixed-point
bit-exactness, inverse-kinematics/dynamics limit propagation, formal
equivalence-check scope). These are a **different kind of verification
problem** from categories 1-7: they're closed-form mathematical/engineering
truths, checkable by formal reasoning, not claims a web search resolves.
They'd route to the `substrate` domain (robotics), whose adaptive-depth
search port is still deferred — and it's an open question whether
`searchlight`-style web search finds anything useful on them at all, versus
correctly/uselessly defaulting to "undetermined" on all of them. Worth
running as its own distinct track, not folded into the categories 1-7
web-verifiable set.

## Independent verification — done, 2026-10-25

Split into two tracks per the round-2 scoping decision:

- **Track A** (`track_a_web_verifiable.json`, 102 claims, categories 1-7) —
  web-searchable facts. Independently verified claim-by-claim via four
  parallel research passes (one per category group: cat 1 / cat 2+3 /
  cat 4+7 / cat 5), each checking real primary/secondary sources, plus
  category 6 (14 calibration probes) set directly to `undetermined` by
  project convention, no research needed since that's the correct verdict
  regardless of which tradition the claim is about. Merged result:
  **`claims_round2_verified.json`** — the file to actually use for testing.
  Per-category raw verification output (sources checked, notes) kept in
  `verified_category1.json`, `verified_category2_3.json`,
  `verified_category4_7.json`, `verified_category5.json`,
  `verified_category6.json`.

- **Track B** (`track_b_category8_formal.json`, 69 claims, category 8) —
  parked. These are closed-form control-theory/FPGA/math claims, not
  web-verifiable facts; see the section above. Not yet verified or run.

### Verification result: 100/102 of the generators' own suggestions held up

Only **2 corrections** out of 102, both confirmed→contradicted:

- `chatgpt-011` — Hesiod's *Theogony* claim that Athena emerges "fully
  armed" from Zeus's head. The head-birth itself is real (Theogony line
  924), but "fully armed" only appears in a line modern editors flag as
  probably spurious — that specific detail belongs to the Homeric Hymn to
  Athena, not the secure Theogony text.
- `gemini-027` — the Voynich Manuscript claim bundles a solid, real 2009
  Arizona radiocarbon result (1404-1438 CE) with a much weaker "northern
  Italy" origin inference (one castle illustration) as if both rested on
  the same evidence.

One claim (`gemini-031`, the 1918 flu's Kansas origin) was independently
confirmed as genuinely unresolved in the historical literature — the
generator already said so; verification agrees undetermined is the honest
answer, not a guess either way.

Final verdict distribution across all 102: confirmed 34, contradicted 53,
undetermined 15 (14 calibration probes + the one genuinely open historical
question above).

Not yet done: running any of this through the real engine or any
competitor.
