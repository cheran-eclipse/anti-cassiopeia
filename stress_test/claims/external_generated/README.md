# Round 2 claims: externally generated, then independently verified

Generated 2026-10-25 by three external AI tools (ChatGPT, Gemini, Perplexity)
from a locked claim-generation prompt. ChatGPT and Gemini received the
prompt in their chat UIs alongside the project zip
(`anti-cassiopeia-for-claim-generation-20261025.zip`); their output is in
`source_chatgpt_gemini.docx` (both tools in one file, split by a `Gemini:`
header partway through). Perplexity was called directly through its
`/v1/responses` API, because its chat UI doesn't support file uploads. The
prompt was adapted inline (no zip reference, project context summarized in
the text) and run once; the output is `source_perplexity_raw.txt`.

## What's here

- `source_chatgpt_gemini.docx`, `source_perplexity_raw.txt`: raw outputs,
  unedited, kept for provenance.
- `claims_round2_raw_undeduped.json`: all 185 claims parsed from the two raw
  sources (96 ChatGPT, 56 Gemini, 33 Perplexity), before dedup.
- `claims_round2_candidates.json`: 171 entries after removing 14 true
  duplicates. Each carries the generating AI's `suggested_ground_truth` and
  `suggested_confidence`. These are the generator's hypotheses, not verified
  fact; the generation prompt required that.
- `claims_round2_verified.json`: **the file to use for testing** (see
  "Independent verification").

## Parsing

The generators used two layouts for the `CLAIM:` / `CATEGORY:` /
`SUGGESTED_GROUND_TRUTH:` / `CONFIDENCE:` / `WHY_INTERESTING:` fields
(ChatGPT: one field per line; Gemini: all five fields on one line per
claim). One regex keyed on the field labels, not the line structure, parses
both. It was checked against a raw `grep -c "CLAIM:"` count: 96 + 56 + 33 =
185, an exact match.

## Dedup: 14 true duplicates removed by hand

An automatic near-duplicate pass (token-Jaccard similarity over the claim
text) found 17 candidate pairs or groups. Each was read in full and judged
individually. Similarity caught real duplicates (independently generated,
same core assertion) and also false positives: claims with shared
vocabulary that assert different things. These were kept separate despite
high overlap:

- The two 1919-eclipse claims. One states the hedged historical fact; the
  other adds a false overreach ("general relativity has never received
  independent confirmation") to the same premise.
- The two Gilgamesh flood claims. One names the correct god who warns
  Utnapishtim privately; the other plants a wrong-god detail as a factual
  trap.
- The Jesus and Osiris resurrection pair. It is a deliberate cross-tradition
  calibration pair, per the generation prompt's category 6 instruction
  (generate from several traditions to test whether the system is equally
  uncertain about all of them). The Jesus-resurrection claim was merged
  across ChatGPT and Perplexity, since those two are the same claim.
- Several category 8 robotics and FPGA pairs that share dense technical
  vocabulary (Jacobians, fixed-point bits, inverse dynamics) but assert
  different false inferences.

Merged, because 2 or 3 generators independently produced the same core
assertion (when unrelated AIs converge on a test claim, it is a well-known
case, not a cherry-picked one): Apollo staging, vaccines and autism,
5G and COVID, Great Wall visibility (3-way), the 10%-of-brain myth, goldfish
memory (3-way), Einstein's math, the Antikythera mechanism, Newton and
Leibniz calculus, Shroud of Turin dating, the redundant-manipulator
null-space claim, and the Jesus-resurrection probe. Merged entries carry
`generated_by` and `duplicate_ids`. The Antikythera pair was categorized as
category 2 by ChatGPT and category 5 by Gemini. It is flagged as
`category_disagreement` and not resolved by merging, since the disagreement
shows how fuzzy the category boundary is.

## Dataset shape

171 claims. By category: 1 has 20, 2 has 17, 3 has 14, 4 has 11, 5 has 14, 6
has 14, 7 has 12, **8 has 69**.

Category 8 is 40% of the set. It is mostly dense control-theory and FPGA
formal claims from ChatGPT (Jacobian null-spaces, fixed-point bit-exactness,
inverse kinematics and dynamics limit propagation, formal equivalence-check
scope). They are a different kind of verification problem from categories
1 to 7: closed-form mathematical and engineering truths, checkable by formal
reasoning, which a web search does not resolve. They would route to
`substrate`, whose adaptive-depth search port is deferred, and it is open
whether `searchlight`-style web search finds anything useful on them or
returns "undetermined" for all of them. They are a separate track, not part
of the web-verifiable categories 1 to 7.

## Independent verification (2026-10-25)

Two tracks, per the round 2 scoping decision:

- **Track A** (`track_a_web_verifiable.json`, 102 claims, categories 1 to 7):
  web-searchable facts. Each claim was verified through four parallel
  research passes (category 1, categories 2 and 3, categories 4 and 7,
  category 5), checking primary and secondary sources. Category 6 (14
  calibration probes) is set to `undetermined` by project convention: that
  is the correct verdict whatever the tradition. The merged result is
  **`claims_round2_verified.json`**. Per-category verification output
  (sources checked, notes) is in `verified_category1.json`,
  `verified_category2_3.json`, `verified_category4_7.json`,
  `verified_category5.json` and `verified_category6.json`.
- **Track B** (`track_b_category8_formal.json`, 69 claims, category 8):
  formal control-theory, FPGA and math claims. Verified and run in a later
  step; see `stress_test/results/TRACK_B_REPORT.md`.

### Result: 100 of 102 generator suggestions held up at verification time

Two corrections at initial verification, both confirmed to contradicted:

- `chatgpt-011`: Hesiod's *Theogony* claim that Athena emerges "fully armed"
  from Zeus's head. The head-birth is real (Theogony line 924), but "fully
  armed" appears only in a line modern editors flag as probably spurious.
  That detail belongs to the Homeric Hymn to Athena, not the secure
  Theogony text.
- `gemini-027`: the Voynich Manuscript claim combines a solid 2009 Arizona
  radiocarbon result (1404 to 1438 CE) with a much weaker "northern Italy"
  origin inference (one castle illustration), as if both rested on the same
  evidence.

One claim (`gemini-031`, the 1918 flu's Kansas origin) was confirmed to be
unresolved in the historical literature. The generator already said so, and
verification agrees `undetermined` is the right answer.

**A third correction came later**, during round 2's benchmark review.
`gemini-012` (Newton and Leibniz, "exact same time") was first kept
`confirmed` on the reasoning that "most popular accounts use similarly loose
framing". It was overridden after all six systems tested in round 2
independently predicted `contradicted`. See Erratum 3 in
`stress_test/results/BENCHMARK_ROUND2_REPORT.md`. The rule it set for ground
truth in later rounds: when a claim's core relationship is true but a
specific qualifier it adds is false, score it `contradicted`. Initial
verification can be too lenient on exactly that shape.

Final verdict distribution across the 102: confirmed 33, contradicted 54,
undetermined 15 (14 calibration probes plus the open historical question
above). The original pass gave confirmed 34 and contradicted 53, before the
`gemini-012` correction.

The claims were run through the engine and all 5 competitors; see
`stress_test/results/BENCHMARK_ROUND2_REPORT.md`.
