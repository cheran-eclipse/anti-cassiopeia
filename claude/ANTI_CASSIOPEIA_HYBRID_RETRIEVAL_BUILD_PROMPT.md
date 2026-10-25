# Anti-Cassiopeia — hybrid retrieval build prompt (port from Constellation)

## PROMPT TO HAND TO THE NEXT SESSION, VERBATIM

Anti-Cassiopeia's retrieval is currently BM25-only — stated honestly in
`retrieval/__init__.py`'s own docstring ("Vector/embedding search is NOT
implemented — it needs an embedding model, which nothing in this repo
currently provides or calls"). Round 1 of the competitive-benchmark
protocol (`stress_test/results/BENCHMARK_ROUND1_REPORT.md`) found real,
live evidence this gap costs real verdicts: 3 conservative misses traced
to verbatim-claim-as-search-query retrieval gaps, and the moon-landing
conspiracy claim going soft instead of confidently contradicting — same
root cause, no domain-tuned search. This prompt is the build spec for
closing that gap by porting a real, working, already-evaluated
implementation from the sibling project `cheran-eclipse/eclipse-constellation`,
not inventing one from scratch.

## §0. What to read first — the reference implementation

Clone/read `cheran-eclipse/eclipse-constellation` before writing any new
code. The files that matter:
- `src/constellation/retrieval/hybrid.py` — `HybridRetriever`: BM25 +
  vector search, fused with reciprocal rank fusion (RRF, k=60, the
  standard constant). Degrades honestly to BM25-only if embeddings are
  unavailable or fail at query time (`EvidencePack.methods` records which
  methods actually ran — never silently pretends). Optional graph
  expansion (`GraphExpander`) exists, off by default — out of scope for
  this port, don't add it.
- `src/constellation/retrieval/index.py` — `VectorIndex` (the actual
  nearest-neighbor search over embedded chunks).
- `src/constellation/retrieval/bm25.py` — their BM25 implementation, for
  comparison against Anti-Cassiopeia's own existing one (which stays;
  see §2).
- `src/constellation/retrieval/evaluate.py` and
  `evals/retrieval/results.md` — **read the honest eval caveat in full
  before trusting any number**: their only offline eval table used a FAKE
  hashed bag-of-words stand-in embedder (no live Qwen3 calls were
  allowed in that pass), and under that stand-in, plain BM25 actually
  BEAT hybrid (R@1 0.47 vs 0.42, MRR 0.648 vs 0.605). Their own
  conclusion: the stand-in adds noise, not real semantic signal — not
  evidence against real embeddings. Their real live result (Qwen3-
  Embedding-8B, 24 chunks): hit@1 71%, hit@3 86% — the actual number that
  matters, but not yet re-measured offline on their full 37-question set
  either. **Do not port the stand-in numbers as if they were validated
  results for Anti-Cassiopeia — re-measure with the real embedder on
  Anti-Cassiopeia's own eval data, per §4 below.**
- Anti-Cassiopeia's own `retrieval/__init__.py`, `retrieval/stance.py`,
  `research_web.py`, `robotics.py`, and `upload_store.py` — read these
  fresh (not from memory of an earlier session) before changing anything,
  same "read in full before writing new code" discipline as every prior
  build prompt in this project.

## §1. What NOT to do

- Do not add graph expansion (`GraphExpander`) — Constellation's own eval
  found it changed zero scores on their test set and left it off by
  default; out of scope here too unless a future round finds a specific
  need.
- Do not remove or replace the existing BM25 implementation —
  Anti-Cassiopeia keeps its own BM25 path; hybrid is additive (fusion of
  BM25 + vector), not a swap.
- Do not fold this into the competitive-benchmark protocol's own files
  (`stress_test/`) — this is a change to Anti-Cassiopeia's actual
  retrieval, not a new competitor variant. Keep the two efforts separate.
- Do not claim the stand-in eval numbers transfer. Do not skip §4's
  real-embedder re-evaluation step to save time.

## §2. Two different integration points — not one copy-paste

Anti-Cassiopeia has two retrieval shapes, and Constellation's
`HybridRetriever` is built for only one of them directly:

### §2.1 `robotics` BYOE/pooled (fixed corpus per upload)

Same shape as Constellation's use case: index once at upload time, query
many times. This is the closer-to-direct port:
- Add embedding at upload time (`upload_store.py`'s `put()` path, or
  wherever document chunking currently happens) — embed each chunk once,
  store alongside the existing BM25 index for that document/pool.
  Embedding failure at this stage must degrade honestly to BM25-only for
  that document (same discipline as Constellation's own `try/except
  ModelError` pattern in `HybridRetriever.__init__`) — never silently
  skip embedding without recording that it happened.
- At query time, fuse BM25 + vector ranks with RRF (same formula,
  `1.0 / (RRF_K + rank)`, RRF_K=60) across both BYOE (single document)
  and pooled (multi-document) search paths.

### §2.2 `research_web` (live web search results, different passages every query)

No persistent corpus to pre-index — this needs a smaller, different
adaptation: embed the query once plus the freshly-fetched passages from
that query's live search, RRF-fuse against the same BM25 ranking already
happening over those same passages, then discard (no index persists
between claims). This is a rerank step layered onto the existing
retrieval flow in `research_web.py`, not a `HybridRetriever`-style
persistent index. Scope this as its own sub-task — don't assume the
BYOE-path code reuses cleanly here.

## §3. The embedding client

Anti-Cassiopeia's model-client layer needs an `embed()` method added
(same interface shape as Constellation's `ModelClient.embed()` /
`Embedder` wrapper in `hybrid.py`). Check what embedding model is
actually available through whatever Nebius/API setup Anti-Cassiopeia
already has provisioned before assuming Qwen3-Embedding-8B specifically
is available or already budgeted — Constellation's choice of embedder
was its own decision, not necessarily already paid for or available
under Anti-Cassiopeia's current Nebius credentials. Confirm this first,
state it plainly in the PR/commit if it differs from Constellation's
choice.

## §4. Evaluation — real, not assumed

1. Build (or port/adapt) an offline retrieval eval harness, same pattern
   as Constellation's `evaluate.py` — R@1/R@3/R@5/MRR/top-k-hit over a
   real question set against Anti-Cassiopeia's own retrieval corpus/BYOE
   documents, not Constellation's synthetic datasheets.
2. Run it with the REAL embedder, not a stand-in — budget-permitting,
   per §5 below. If budget genuinely doesn't allow a live-embedder eval
   run, say so plainly and don't publish a BM25-only or fake-stand-in
   comparison as if it validates the real hybrid path (same honesty
   standard Constellation's own report held itself to).
3. Live re-test, small and deliberate (same discipline as the stance-fix
   prompt's own re-test step): re-run the 3 conservative misses and the
   moon-landing claim from round 1's report against the new hybrid
   retrieval, confirm whether the root cause (verbatim-query retrieval
   gap) is actually fixed, not just theoretically addressed.

## §5. Budget discipline — explicit, same convention as the rest of this project

- A new per-call Nebius embedding cost exists now — track it as its own
  line, never summed silently into existing retrieval/propose/verify
  costs. State the actual per-call cost once measured.
- Added latency per claim (embedding call on top of existing retrieval)
  — measure and state it, don't just assume it's negligible.
- If embedding costs or latency turn out to be a real problem at the
  BYOE-pooled scale (many documents, many chunks), say so plainly rather
  than quietly disabling the feature or hiding the cost.

## §6. What "done" means for this build

- Full offline test suite stays green (same bar as every prior fix in
  this project).
- New tests cover: hybrid retrieval degrading honestly to BM25-only when
  embedding fails (both at index time and query time), RRF fusion
  correctness, and the two integration points (§2.1/§2.2) separately —
  don't assume one test suite covers both.
- `retrieval/__init__.py`'s docstring gets updated to reflect the new
  capability AND states plainly whatever new honest limitation exists
  once this ships (there will be one — find it, don't assume "added
  embeddings" means "no more retrieval gaps").
- Round 1's 3 conservative misses and the moon-landing claim get
  re-tested per §4.3, with the result reported honestly whether it fixed
  them, partially helped, or didn't — same standard as every other fix
  in this project's history.
- Report back: what shipped, what the real (not stand-in) eval numbers
  came out to, what the new honest limitation is, and whether round 1's
  specific failing claims are now resolved.

## §7. Sequencing note

This build is independent of round 2 of the competitive-benchmark
protocol — round 2 is not required before this ships, and this build is
not required before round 2 could start. If both are live at once,
whichever lands first should be the one round 2 (when it happens) tests
against, so regression-safety (protocol §3.7) stays meaningful. Owner's
call on order; this prompt doesn't assume one.
