# Design notes

`docs/ARCHITECTURE.md` describes what is built. This file records the
design decisions behind it, so they are visible and open to argument.

## 1. Evidence retrieval per domain: four different problems, one contract

The engine only needs `list[Evidence]` back. What produces that list
differs by domain. Forcing one retrieval abstraction across all four would
turn a domain-agnostic engine into a `substrate`-shaped one with three
unused stubs.

| Domain | Retrieval shape | Primary source type |
|---|---|---|
| `substrate` | lookup against a structured parts/datasheet index | per-part spec sheets, keyed by manufacturer and model |
| `silicon` | parse tool-generated reports | synthesis, timing and simulation output files, register maps |
| `searchlight` | live fetch and extraction | web search and paper indices (a real fetch, not recall) |
| `quant` | re-execution | run the metric or statistic against the dataset |

Only `substrate` and `searchlight` share retrieval machinery (both look
facts up in an external source). `silicon` and `quant` parse or execute
local artifacts. A shared helper should be extracted only after two
implementations of different shapes exist.

`substrate` was wired first. Its evidence source is the datasheet facts
extracted from Constellation's research (BlueROV2, Bar30, Bar100XT, QuSpin
QZFM Gen-3), with their provenance kept; see
`docs/extracted/constellation-robotics-seed.md`.

## 2. Claim decomposition

A claim like "this robot survives the mission" is not atomic. It is N
per-part claims plus one whole-assembly claim. Two options were considered:

- **(a)** The caller decomposes. The API stays atomic, and the caller breaks
  "survives the mission" into "Bar30 survives 500m", "ESP32 survives
  submersion inside housing X", and so on, then calls `/verify` once per
  sub-claim.
- **(b)** The engine decomposes. An LLM pass (through the Nebius client)
  turns one compound claim into sub-claims, verifies each, and rolls them
  up.

Option (b) is built as `anticassiopeia/core/compound.py` and is available
over HTTP as `POST /verify/compound`.
- `decompose_claim()` makes one LLM call with strict JSON-shape validation
  and the same code-fence-stripping and error conventions as
  `retrieval/extract.py`'s `propose()`.
- `rollup()` has no I/O. `CONFIRMED` only if every verified sub-claim is
  `CONFIRMED`, any `CONTRADICTED` sub-claim contradicts the whole, and
  otherwise `UNDETERMINED`.
- `verify_compound()` runs both through the unmodified engine and adapters.
- The risk is that a bad decomposition silently changes what is checked.
  Decomposition only classifies a sub-claim into `substrate` or
  `searchlight`, the two domains that accept a bare free-text claim. A part
  needing `quant` or `silicon`'s structured file-path context stays a
  visible gap; the LLM does not invent a path or number.
- A fidelity check rejects decompositions that change a part's meaning (for
  example rewriting a false sub-claim into its negation).

See the "Item 20" and "v3 §1.2" sections of `docs/ARCHITECTURE.md`.

## 3. Scoring

The current rule in `engine.py` is a trust-weighted sum against a fixed
threshold (`DECISION_THRESHOLD=0.5`). Known weaknesses:

- The thresholds are arbitrary, not fit to data. They need evidence data
  from more than one domain before they can be tuned.
- **Redundancy: fixed (external review).** Five low-trust sources pointing
  the same way used to sum like five independent confirmations, though
  five pages of one datasheet are not five sources.
  `_redundancy_collapsed_weight()` now collapses same-source evidence to its
  highest-trust piece before summing.
- **Time decay: partially fixed (item 19, external review).** A 2019 report
  and one from this morning used to weigh the same. `Evidence.timestamp` and
  `engine.py`'s `_decayed_trust()` now decay trust by age, with a floor
  (`MIN_DECAY_FACTOR`) set so decay can't flip a single-source verdict on
  age alone. It is wired into one domain, `silicon.py`'s Vivado-report path,
  which has a reliable date (the report's `| Date : ...` header line). It
  is not wired into `silicon.py`'s SVD path (no comparable date field),
  `quant.py` (a re-computed statistic is always fresh), `substrate.py` or
  `searchlight.py` (no trustworthy per-evidence date found). Those stay open
  and are not filled with a formula fed a guessed date.

Scoring changes wait until more domains produce evidence to test against.

## 4. Deployment shape for "extensible infrastructure"

The hackathon ask is a live deployment that reads as infrastructure other
developers can build on. Beyond `POST /verify`:

- **OpenAPI schema:** FastAPI serves it at `/docs`. Done.
- **`GET /domains`:** lists registered domains and their status, so a caller
  can check a domain before relying on a verdict from it. Done.
- **Client library:** a `pip install anticassiopeia-client`-style package, or
  a documented `httpx` snippet, so integration doesn't require reading the
  server source. Not built (no client package in this repo).

## 5. `quant` and `silicon` stay outside `retrieval/`

Section 1 made this call before either adapter existed. After reading both
adapters' code (`quant.py`'s `_read_column()`, `silicon.py`'s
`_parse_report()`), it holds, for these reasons.

`retrieval/` (`chunking.py`, `bm25.py`, `extract.py`) finds the right
passage in unstructured prose when you don't know where a fact is phrased.
BM25 plus an LLM propose step earns its place there (see `substrate.py` and
`searchlight.py`). Neither `quant.py` nor `silicon.py` has that problem.

- `quant.py`'s answer is a statistic computed over every row of a named
  column, not a sentence in a CSV. There is no right chunk to retrieve.
  Chunking the CSV into 800-character blocks would slice rows apart, and
  getting a correct mean or stdev back would mean asking an LLM to re-derive
  a global aggregate from a truncated view. `statistics.mean()` on the whole
  column is exact, free and instant. Routing it through retrieval would
  replace an exact computation with an LLM's approximation.
- `silicon.py`'s answer is looked up by an exact key (`report[metric]` after
  `_parse_report()`). The report's structure says where the value lives. A
  Vivado or Quartus report is even more rigid than the format the adapter
  first used: fixed-width tables with named columns. The right tool is a
  structured parser. Feeding a table through BM25 and chunking risks
  separating a row from its header or corner label, which a table-aware
  parser avoids because it never treats the row as free text to re-rank.

Neither adapter imports anything from `anticassiopeia.retrieval`, and both
recompute from the file on every call instead of trusting a reported
number. That is the property that matters: never trust a described result,
always recompute or re-parse from the source. Retrieval satisfies it for
unstructured sources and direct parsing for structured ones. Using retrieval
here would add an approximate step to something exact.

If a future EDA report has a large free-text section (design notes,
warnings) that a claim needs to reference, that sub-problem could use
`retrieval/`. That would be a narrow extension, not a reason to route the
structured-metric lookups through it.

## Related work

How this project relates to existing claim-verification and factuality work
(external review).

- **FEVER** (Thorne et al., claim verification against Wikipedia) is the
  closest in shape. Its 3-way label (SUPPORTED / REFUTED / NOT ENOUGH INFO)
  maps almost directly onto CONFIRMED / CONTRADICTED / UNDETERMINED. FEVER
  is a single-domain (Wikipedia text) benchmark and pipeline, with a trained
  entailment classifier choosing the label. Anti-Cassiopeia spans several
  domains (datasheets, EDA reports, datasets, the open web) and uses no
  classifier: every `Evidence` locator is a verbatim quote or an exact
  recomputation that a person can re-check by hand.
- **FActScore** (Min et al.) and **SAFE** (Wei et al., "long-form
  factuality in large language models") decompose long-form model output
  into atomic facts and check each against retrieved evidence. Both roll the
  results into one continuous score (a precision percentage), a single
  number presented as measured confidence, which is what this project is
  named against. The stress tests cite SAFE's 72% figure as context only
  (`stress_test/results/TEST3_REPORT.md`): SAFE scores agreement with human
  annotators on open-ended generated text checked against live web search,
  not against fixed source documents, so the numbers answer different
  questions. SAFE's atomic-fact-then-search loop resembles `searchlight.py`'s
  mode 2 (multi-candidate live search, each candidate checked
  independently). Here, each claim resolves to one of three states with a
  locator, never a blended score.
- **RARR** (Gao et al., "retrofit attribution using research and revision")
  retrieves evidence for a generated text's claims and then edits the text
  to match, attaching attribution. Its goal is revision, so it never has to
  say "I don't know". Anti-Cassiopeia never edits a claim; it answers
  CONFIRMED, CONTRADICTED or UNDETERMINED about the claim as given.
- **FacTool** (Chern et al.) is closest to the domain-adapter idea:
  different task domains (KB-QA, code, math, scientific review) get
  different tools to check claims, like this project's `DomainAdapter`s.
  FacTool's per-claim output is a binary factual or non-factual judgment
  from an LLM weighing tool output. It has no three-state scheme with an
  "insufficient evidence" outcome, and no verbatim-quote locator like
  `verify_proposal()` requires.

Three-state verdicts and quote-grounded evidence are each a small, specific
choice, not a new paradigm. What this project does is apply both together,
across unrelated domains (a CSV, a timing report, a live web page) behind
one contract, with every confident answer traceable to a locator a person
can re-check.
