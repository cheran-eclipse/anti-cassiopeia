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

## 2. Claim decomposition — still open

A claim like "this robot survives the mission" is not atomic — it's really
N per-part claims plus one whole-assembly claim. Two options:

- **(a)** Caller's responsibility: the API contract stays atomic claims
  only; whoever calls `/verify` must already have broken "survives the
  mission" into "Bar30 survives 500m", "ESP32 survives submersion inside
  housing X", etc., and calls `/verify` once per sub-claim.
- **(b)** Engine's responsibility: an LLM decomposition pass (via the
  Nebius client) turns one compound claim into sub-claims, verifies each,
  then rolls them up (`CONFIRMED` only if every sub-claim is `CONFIRMED`;
  any `CONTRADICTED` sub-claim contradicts the whole; otherwise
  `UNDETERMINED`).

(b) is more impressive as a demo and matches "extensible infrastructure"
positioning better, but adds a real failure surface — a bad decomposition
silently changes what's actually being checked, which is the exact kind
of ungrounded confidence this project exists to avoid introducing into
itself. **Leaning (a) for the bone framework, (b) as an explicit opt-in
later (`/verify/compound`), not the default path.** Not locked — revisit
once a real adapter exists to test either option against.

## 3. Scoring v2 — what would actually improve on the current placeholder

Current rule (`engine.py`): trust-weighted sum, fixed thresholds
(`DECISION_THRESHOLD=0.5`, `MIN_EVIDENCE_WEIGHT=0.3`). Known weaknesses,
listed honestly rather than hidden:

- Thresholds are arbitrary, not fit to anything. They need real evidence
  data from at least one domain before they can be tuned, not guessed at
  in the abstract.
- No handling of evidence *redundancy* — five low-trust sources all
  pointing the same direction currently sum like five independent
  confirmations, which they usually aren't (e.g. five pages of the same
  datasheet aren't five independent sources).
- No time-decay — a 2019 synthesis report and a report from this morning
  are weighted identically.

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
