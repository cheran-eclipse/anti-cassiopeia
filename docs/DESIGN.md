# Design notes (post-bone-framework)

Written while `docs/ARCHITECTURE.md` describes what's built; this file is
where the next layer gets decided before it's built, so the decision is
visible and arguable rather than buried in code.

## 1. Evidence retrieval per domain — four different problems, one contract

The engine only needs `list[Evidence]` back. What produces that list is
genuinely different per domain, and pretending otherwise is how a
"domain-agnostic" engine quietly becomes a robotics-shaped engine with
three unused stubs attached.

| Domain | Retrieval shape | Primary source type |
|---|---|---|
| `robotics` | lookup against a structured parts/datasheet index | per-part spec sheets, keyed by manufacturer+model |
| `fpga_embedded` | parse tool-generated reports | synthesis/timing/simulation output files, register maps |
| `research_web` | live fetch + extraction | web search + paper indices (must be a real fetch, not recall) |
| `ml_data` | re-execution | run the actual metric/stat test against the actual dataset |

Only `robotics` and `research_web` plausibly share retrieval machinery
(both are "look it up against an external source" problems). `fpga_embedded`
and `ml_data` are both "parse/execute local artifacts" problems. Don't
force a single retrieval abstraction across all four prematurely — let two
real implementations (one of each shape) exist before extracting a shared
helper, not before.

**Decision needed, not yet made:** which domain gets wired first decides
which retrieval shape gets built first. Robotics has a head start — real,
already-verified parts/datasheet facts exist from Constellation's research
(BlueROV2 / Bar30 / Bar100XT / QuSpin QZFM Gen-3). See the extraction
prompt in the repo root conversation — those facts, with their datasheet
provenance intact, are the natural seed for `robotics`' evidence source.

## 2. Claim decomposition — option (b) now built as a library, NOT yet wired to HTTP

A claim like "this robot survives the mission" is not atomic — it's really
N per-part claims plus one whole-assembly claim. Two options were
considered:

- **(a)** Caller's responsibility: the API contract stays atomic claims
  only; whoever calls `/verify` must already have broken "survives the
  mission" into "Bar30 survives 500m", "ESP32 survives submersion inside
  housing X", etc., and calls `/verify` once per sub-claim.
- **(b)** Engine's responsibility: an LLM decomposition pass (via the
  Nebius client) turns one compound claim into sub-claims, verifies each,
  then rolls them up.

**Item 20 (external review, 2-hour-budgeted round): (b) is now real,
tested code — `anticassiopeia/core/compound.py` — but deliberately NOT
wired to an HTTP endpoint yet.** What's built: `decompose_claim()` (one
LLM call, strict JSON-shape validation, same code-fence-stripping/error
conventions as `retrieval/extract.py`'s `propose()`), `rollup()` (pure,
no I/O — exactly the semantics sketched above: `CONFIRMED` only if every
verified sub-claim is `CONFIRMED`, any `CONTRADICTED` sub-claim
contradicts the whole, otherwise `UNDETERMINED`), and `verify_compound()`
orchestrating both through the REAL, unmodified engine/adapters. The
real failure surface this section worried about — "a bad decomposition
silently changes what's actually being checked" — is addressed directly:
decomposition is restricted to classifying each sub-claim into
`robotics`/`research_web` only (the two domains that accept a bare
free-text claim); a part needing `ml_data`/`fpga_embedded`'s structured
file-path context is left an explicit, visible gap rather than having
the LLM invent a plausible-looking path or number. See
`docs/ARCHITECTURE.md`'s own "Item 20" section for exactly what's tested
vs. still open (the HTTP endpoint itself, `/verify/compound`, named here
originally — not built this round; see that section for why).

## 3. Scoring v2 — what would actually improve on the current placeholder

Current rule (`engine.py`): trust-weighted sum, fixed threshold
(`DECISION_THRESHOLD=0.5`). Known weaknesses, listed honestly rather than
hidden:

- Thresholds are arbitrary, not fit to anything. They need real evidence
  data from at least one domain before they can be tuned, not guessed at
  in the abstract.
- No handling of evidence *redundancy* — five low-trust sources all
  pointing the same direction currently sum like five independent
  confirmations, which they usually aren't (e.g. five pages of the same
  datasheet aren't five independent sources). **FIXED** (external
  review): `_redundancy_collapsed_weight()` now collapses same-source
  evidence to its single highest-trust piece before summing.
- No time-decay — a 2019 synthesis report and a report from this morning
  are weighted identically. **PARTIALLY FIXED** (item 19, external
  review): `Evidence.timestamp` + `engine.py`'s `_decayed_trust()` now
  decay a piece of evidence's trust by real age, with a floor
  (`MIN_DECAY_FACTOR`) calibrated so it can never flip an existing
  single-source verdict purely from age. Wired into exactly ONE domain so
  far — `fpga_embedded.py`'s Vivado-report path, which is the only one
  with a real, reliably-extractable date (the report's own
  `| Date : ...` header line). NOT wired into `fpga_embedded.py`'s SVD
  register path (no comparable real date field), nor into `ml_data.py`
  (a re-computed statistic is always fresh at verify time, never stale),
  `robotics.py`, or `research_web.py` (no real, trustworthy per-evidence
  date source identified yet for either) — stated as open for those,
  not faked with a formula fed a guessed date.

None of this gets fixed speculatively. It gets revisited once `robotics`
(or whichever domain goes first) is producing real `Evidence` lists to
test the scoring rule against actual cases, per `docs/ARCHITECTURE.md`'s
own instruction not to claim more finished than is true.

## 4. Deployment shape for "extensible infrastructure" positioning

The hackathon ask is a polished live deployment that reads as
infrastructure other developers could build on, not a single demo app.
Concretely, that means beyond the current `POST /verify`:

- An OpenAPI schema (FastAPI generates this for free at `/docs` —
  already true today, worth highlighting rather than building separately).
- A minimal client library (`pip install anticassiopeia-client` style, or
  even just a documented `httpx` snippet) so integration doesn't require
  reading the server source.
- `GET /domains` — list registered domains and their current status
  (stub vs. real), so a caller can check before relying on a verdict from
  a domain that's still returning `[]`. **Not yet built** — small, worth
  adding early since it directly supports the "don't trust more than is
  earned" ethos at the API level, not just inside one verdict.

## 5. Confirmed: `ml_data`/`fpga_embedded` stay outside `retrieval/` — read the actual code first, then decided

Section 1 above already called this, before either adapter existed to check
it against. Having now read both adapters' real code (`ml_data.py`'s
`_read_column()`, `fpga_embedded.py`'s `_parse_report()`), the reasoning
holds, and here's the concrete argument for why, not just a restatement:

`retrieval/`'s whole job (`chunking.py` + `bm25.py` + `extract.py`) is
finding the right PASSAGE in unstructured prose when you don't know in
advance where in the document a fact is phrased — that's a real, hard
problem, and BM25 + an LLM propose step earns its keep solving it (see
`robotics.py`'s and `research_web.py`'s actual live-verified use of it).

Neither `ml_data.py` nor `fpga_embedded.py` has that problem:

- `ml_data.py`'s "answer" isn't a sentence hiding somewhere in a CSV — it's
  a statistic computed over EVERY row of a named column
  (`statistics.mean(values)` in `_read_column()`'s caller). There is no
  "right chunk" to retrieve: chunking the CSV into 800-char text blocks
  would arbitrarily slice rows apart, and the only way to get a correct
  mean/stdev back out would be to ask an LLM to re-derive a global
  aggregate from a partial, truncated view it was shown — strictly worse
  than just running `statistics.mean()` on the whole column, which is
  exact, free, and instant. Routing this through retrieval/ wouldn't make
  it more real, it would make it less real: swapping an exact computation
  for an LLM's approximation of one.
- `fpga_embedded.py`'s "answer" is looked up by an EXACT key
  (`report[metric]` after `_parse_report()`'s regex match on `key: value`
  lines) — the report's own structure already says exactly where the
  value lives; there's no ambiguity to search over. A real EDA tool
  report (Vivado/Quartus) is even more rigidly structured than this
  adapter's current invented format — fixed-width tables with named
  columns, not free prose — so the fix needed there (Part 2 of this
  session's task) is a better STRUCTURED parser, not retrieval. Feeding a
  timing table through BM25/chunking risks separating a table row from
  its header or corner label, which a line/table-aware parser can't do
  because it never treats the row as free text to re-rank in the first
  place.

Both adapters already encode this correctly: neither imports anything from
`anticassiopeia.retrieval`, and both re-derive their answer from the
actual file every call rather than trusting a cached/reported number —
which is the real property that matters (never trust a described result;
always recompute/re-parse from the source), independent of which
mechanism does the re-deriving. Retrieval is one way to satisfy that
property (for unstructured sources); direct parsing/computation is
another (for structured ones). Using retrieval here wouldn't make either
adapter MORE rigorous — it would introduce an unnecessary approximate step
into something that's currently exact, which is the opposite of what this
project is for.

**Not changed by this confirmation:** if a future real EDA report turns
out to have a substantial free-text section (design notes, warnings) that
a claim needs to reference, THAT specific sub-problem might reasonably use
`retrieval/` — but that's a new, narrow extension if/when it's needed, not
a reason to route the existing structured-metric lookups through it now.

## Not decided here

Team-coordination/build-split questions (which of the parallel Claude
accounts builds which domain) belong in planning, not in this file — this
file is architecture only.

## Related work

Named explicitly rather than left implicit (external review): where this
project sits relative to existing claim-verification/factuality work, and
how it genuinely differs, not just "we also check facts."

- **FEVER** (Thorne et al., claim verification against Wikipedia) is the
  closest prior work in *shape*: a 3-way label (SUPPORTED / REFUTED / NOT
  ENOUGH INFO) that maps almost directly onto this project's CONFIRMED /
  CONTRADICTED / UNDETERMINED. The real difference is scope and
  grounding: FEVER is a single-domain (Wikipedia-text) benchmark+pipeline
  with a trained entailment classifier picking the label; Anti-Cassiopeia
  is domain-plural (datasheets, EDA reports, datasets, the open web) with
  no classifier at all — every `Evidence` locator is a verbatim quote or
  an exact recomputation a human could re-check by hand, not a learned
  probability over a label.
- **FActScore** (Min et al.) and **SAFE** (Wei et al., "long-form
  factuality in large language models") both decompose long-form model
  output into atomic facts and check each against retrieved evidence —
  but both roll the per-fact results up into one continuous score (a
  precision percentage). That's exactly the failure mode this project is
  named against: a single number dressed up as measured confidence. This
  project's own stress-test suite cites SAFE's 72% figure directly (see
  `stress_test/results/TEST3_REPORT.md`) as context, not as a comparable
  number — SAFE scores agreement with human annotators on open-ended
  generated text against live web search, not fixed source documents, so
  the two numbers answer different questions. SAFE's atomic-fact-then-
  search-agent loop is architecturally close to `research_web.py`'s mode
  2 (multi-candidate live search, each candidate independently checked);
  the difference is this project keeps each claim resolving to one of
  three states with a locator, never a blended score across many facts.
- **RARR** (Gao et al., "retrofit attribution using research and
  revision") retrieves evidence for a generated text's claims and then
  *edits* the text to match the evidence, attaching attribution as it
  goes. Its goal is revision, not verdicts — it never has to say "I don't
  know and won't guess," because its job is to fix the text, not refuse
  an answer. Anti-Cassiopeia never edits or rewrites a claim; it only
  ever answers CONFIRMED/CONTRADICTED/UNDETERMINED about the claim as
  given.
- **FacTool** (Chern et al.) is the closest in spirit to the
  domain-adapter idea: different task domains (KB-QA, code, math,
  scientific review) get different "tools" to check claims against,
  similar to this project's per-domain `DomainAdapter`s. The real
  difference: FacTool's per-claim output is a binary factual/
  non-factual judgment from an LLM weighing tool output, not a
  three-state scheme with a first-class "insufficient evidence, refusing
  to guess" outcome, and it doesn't require a verbatim-quote-level
  locator the way `verify_proposal()` does here.

None of this is a claim of novelty for novelty's sake — three-state
verdicts and quote-grounded evidence are both small, specific choices,
not a new paradigm. What's different here is applying both together,
consistently, across structurally unrelated domains (a CSV, a timing
report, a live web page) behind one shared contract, with every
confident answer traceable to a locator a human can independently
re-check.
