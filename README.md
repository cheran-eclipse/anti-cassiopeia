# Anti-Cassiopeia

A verification engine. Give it a claim, it gives you back one of exactly
three things: **confirmed**, **contradicted**, or **undetermined** — never
a confident-sounding guess standing in for the third one. Displayed in
the frontend as the three C's — **Confirmed / Contradicted / Clouded**
(evidence is clouded, not absent) — matching this project's own name;
the API's actual wire value for the third state stays `"undetermined"`,
a stable contract already live on the public demo and never broken just
for branding. See `docs/index.html`'s `displayStateLabel()` for exactly
where that cosmetic rename happens and nowhere else.

Built for the Nebius x NVIDIA Global AI Hackathon, Apps and Agents track:
an app or agent you'd actually use, not a single demo script. Run it as
a CLI, call it as an HTTP API, through the hosted web frontend (see
["Frontend"](#frontend) below), or wire it into another agent's tool-use
loop as the claim-checking step before that agent commits to an answer —
all four hit the same `VerificationEngine`. Runs on Nebius Token Factory
(see `anticassiopeia/llm/nebius_client.py`). The `robotics` domain's live
calls run on **NVIDIA Nemotron Ultra** — a real, live model in the
request path, not a mention — and `research_web` runs on `gpt-oss-120b`;
both choices are the outcome of a real before/after comparison, not a
default. See ["How the model choice was made"](#how-the-model-choice-was-made)
below.

## Why "Anti-Cassiopeia"

Cassiopeia, in Greek myth, was the queen punished for boasting an
unfounded claim of beauty — bound to her throne, forced to circle the pole
eternally, upside-down half the year. This project is named against that
specific failure: it exists to catch and refuse the fluent, detailed,
plausible-sounding claim that doesn't actually check out. Where evidence
is thin, it says so — it does not round up to confidence it hasn't earned.

## The mechanism

```
Claim ──▶ VerificationEngine.verify()
              │
              ▼
        DomainAdapter.gather_evidence(claim)
              │
              ▼
        list[Evidence]  (source, snippet, stance, trust, locator)
              │
              ▼
        VerificationEngine._score()  ──▶  Verdict (state, confidence, reasoning, missing)
```

One verification engine, one shared `Verdict` contract — orchestrating
independent, domain-specific evidence strategies, not running one unified
reasoning algorithm across them. Everything domain-specific — what counts
as a source, how to retrieve evidence, how much to trust it — lives in a
`DomainAdapter` plugin. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the full design and current build status, and
[`docs/DESIGN.md`](docs/DESIGN.md#related-work) for how this relates to
FEVER, FActScore, SAFE, RARR, and FacTool.

## Four domains, all real

| Domain | POV | Evidence traces back to | Status |
|---|---|---|---|
| `robotics` | physical/datasheet | real parts/datasheet facts, retrieved+verified against manufacturer sources (BlueROV2, Bar30, Bar100XT), via live NVIDIA Nemotron Ultra | 3/4 researched parts sourced; the 4th (QuSpin QZFM Gen-3) has a confirmed real source stating NO rating exists — [extraction provenance](docs/extracted/constellation-robotics-seed.md) |
| `ml_data` | ML | an actual re-computed statistic over a real CSV file | real, offline, no external dependency |
| `fpga_embedded` | quantum | a real parsed timing/synthesis report, or a real CMSIS-SVD register-map file | real, offline — timing parser verified against a real Vivado report; register-map parser verified against real ARM/Espressif SVD files, see module docstring |
| `research_web` | existence/verification | an actually-fetched URL, verbatim-quote-checked | real, network-dependent — Tavily primary search backend, DDG+Wikipedia fallback |

Every domain either returns real evidence with a real locator, or an
honest, specific, named reason it can't yet — never a guess. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full per-piece
status and known limitations stated plainly, not hidden.

## Bring your own evidence (v2 + v3)

The four domains above also work against a document YOU supply, not just
the project's own seeded corpus / live search:

```bash
curl -X POST localhost:8000/upload -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -F file=@my_datasheet.pdf
# -> {"document_id": "...", "filename": "my_datasheet.pdf", "size_bytes": 48213}
```

`.txt` / `.md` / `.csv` / `.rpt` / `.svd` / `.xml` are read as plain text;
`.pdf` (via `pypdf`) and `.docx` (via `python-docx`) have their real text
layer extracted. A scanned/image-only PDF with no text layer is a named
error, not a silent empty result — OCR is explicitly out of scope. The
extracted text is held in memory for 24h under an opaque `document_id`,
capped and evicted the same way the API's own rate-limit state is.

**Single claim against your document** — pass that `document_id` in
`context`. For `robotics`, the real chunk → BM25 retrieve → LLM propose →
independently re-verify → judge stance pipeline runs against your
document's real text instead of the fixed corpus. For `ml_data` /
`fpga_embedded` (v3), plain `/verify` resolves the same way
`/verify/project` always has for those two domains — the document's real
extracted text is written to a server-owned scratch file and pointed at
by the existing `dataset_path`/`report_path` context field, so you still
supply every structured field those adapters need (column/stat, or
peripheral/metric/comparator) — nothing is fabricated. `research_web`'s
two modes (URL-fetch or live search) don't consume an uploaded document
at all, so a `document_id` there is a clean, named `400`, not a silent
no-op:

```bash
curl -X POST localhost:8000/verify -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"text": "the X9 sensor is rated for 450m depth", "domain": "robotics", "context": {"document_id": "..."}}'
```

**Search across all your documents (v3 pooled search)** — don't know
which of your uploads has the fact? Set `document_pool: true` instead of
`document_id` (robotics-only; mutually exclusive with `document_id`).
`GET /documents` lists your own currently-valid uploads first if you want
to check what's poolable:

```bash
curl localhost:8000/documents -H "X-API-Key: $ANTICASSIOPEIA_API_KEY"
# -> {"documents": [{"document_id": "...", "filename": "odrive.txt", "size_bytes": 1824, "seconds_until_expiry": 86391.2}, ...]}

curl -X POST localhost:8000/verify -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"text": "the X9 sensor is rated for 450m depth", "domain": "robotics", "context": {"document_pool": true}}'
```

One combined BM25 index is built across every one of your pooled
documents' chunks — still exactly ONE live LLM propose call and ONE
judge-stance call per claim, same cost as searching a single document;
only the local (free) BM25 corpus is bigger. The citation names the real
document the answer actually came from, never a generic "pool"
placeholder. Capped at the 10 most-recently-uploaded documents per call —
stated in the verdict's own reasoning if you have more than that.
Documents are scoped to the API key that uploaded them (a SHA-256 hash of
the key, never the raw key, is the ownership tag) — one caller's pool
never includes another caller's uploads. Honest exception: the public
demo key is shared by every visitor to the hosted frontend, so under that
one key specifically, "your pool" means "every demo-key visitor's
uploads, pooled together" — expected for a shared sandbox, not real
per-caller isolation. A caller using their own `ANTICASSIOPEIA_API_KEY`
gets genuine isolation.

**A bundle of claims, each tied to a different document** — `ml_data` and
`fpga_embedded` need their own structured fields too (column/stat, or
peripheral/metric/comparator), same as always; `POST /verify/project`
only auto-fills *which real file* a `document_id` refers to, by
deterministically sniffing the upload's format (extension first, cross-
checked by real content markers for the one genuinely ambiguous case,
`.xml` — never an LLM guessing what code can already determine) and
routing it to the right domain:

```bash
curl -X POST localhost:8000/verify/project -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"claims": [
        {"text": "the mean voltage is 5.0", "document_id": "<csv-doc>", "context": {"column": "voltage", "stat": "mean", "expected_value": 5.0}},
        {"text": "the X9 sensor is rated for 450m depth", "document_id": "<datasheet-doc>"}
      ]}'
```

The response carries both each claim's own full `Verdict` and one rolled-
up project status (AND-semantics — one real `CONTRADICTED` part falsifies
the whole bundle; one claim's own error, e.g. an unknown `document_id`,
never fails the others). Up to 20 claims per call, its own rate limit
(a project call can fan out into several live LLM calls). Any claim in
the batch can use `"document_pool": true` instead of `document_id` (v3) —
one project call can mix claims pinned to a specific document with claims
that search your whole upload pool.

**Compound claims (v3)** — `POST /verify/compound` splits ONE free-text
claim ("A and B") into independent parts via an LLM call
(`anticassiopeia/core/compound.py`'s `decompose_claim()` — see
`docs/ARCHITECTURE.md`'s "Item 20" section for the full history), verifies
each part through this same engine, and rolls the sub-verdicts up with
AND-semantics (any real `CONTRADICTED` part falsifies the whole claim):

```bash
curl -X POST localhost:8000/verify/compound -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"text": "The ODrive is open-source and BlueROV2 uses a Bar30 sensor rated for 300m"}'
```

Decomposition only ever classifies a sub-claim into `robotics`/
`research_web` — that restriction is deliberately **not** loosened just
because `/verify/project`/pooled search can now resolve a real uploaded
document elsewhere; an LLM splitting free text never sees which
document, or document pool, a sub-claim would even need. `context` on
this endpoint flatly REJECTS `document_id` and `document_pool` (a clean
400, not a silent ignore) for exactly that reason. Its own, stricter
rate limit (one call every 20s) — a single call here can fan out into a
decompose call plus one verify call per sub-claim — and a hard cap of 8
decomposed sub-claims (a clear `422` above it, never a silent truncation).

## How the model choice was made

Not a blanket swap to "the NVIDIA model" and a claim of done. Four
Nemotron tiers (Ultra, Super, Nano, and a one-pilot look at 3.5
Lightning) were tested against `openai/gpt-oss-120b` on both live-LLM
domains, reusing the project's own eval harness, at two sample sizes,
tracking not just accuracy but *dangerous* misses — a confident wrong
answer, the exact failure this project exists to prevent, as distinct
from an honest "undetermined."

The honest version of what happened, in order:
1. **First look (n=15):** robotics seemed tier-insensitive — Super and
   Ultra both matched baseline exactly. Wrong conclusion, too early:
   one dangerous event at n=15 is statistically compatible with a true
   rate anywhere from ~1% to ~30%.
2. **Escalating to n=40** (the same rigor, applied consistently, not
   just where it helped the headline number) showed Super AND Nano both
   crack — real dangerous misses neither had shown at n=15. Only Ultra
   held clean across both sample sizes.
3. **Reading the actual failure transcripts**, not just the aggregate
   rates, found three real, model-agnostic pipeline bugs (no output-
   token cap, no quote-length guidance, no entity-matching check before
   judging a passage's stance) — fixed before trusting any further
   comparison, since all three would distort results for every model,
   not just Nemotron.
4. **Re-testing everything that had shown a problem**, baseline rerun
   fresh each time too (so a post-fix change could be attributed
   correctly): the fixes flipped Ultra to a real win on `research_web`
   and fully resolved Nano's robotics weakness — but did nothing for
   Super on either domain, evidence that Super's underperformance is a
   real model property, not a pipeline artifact.

**Result:** `robotics` now runs on **Nemotron Ultra** — the only tier
with a clean, zero-dangerous-miss record across all three of its
independent robotics runs. `research_web` stays on `gpt-oss-120b` —
no tested Nemotron tier beat it there at an adequately-sized sample,
and Ultra's one post-fix win is narrow and single-sample against
baseline's ten-run, crash-free record across this entire investigation.
Nano and 3.5 Lightning remain credible cheaper follow-ups, not yet
proven to the same standard.

Full numbers, every pilot, the bugs found and how they were found, and
the reasoning behind every decision point above:
[`stress_test/results/NEMOTRON_PIVOT_REPORT.md`](stress_test/results/NEMOTRON_PIVOT_REPORT.md).

## See it run

```bash
pip install -e .
PYTHONPATH=. python scripts/demo.py
```

Runs 6 real claims across all 4 domains through the actual engine — no
mocked output. Example excerpt (robotics, on real sourced facts, from an
actual run on 2026-10-24 — regenerated here after an external review
caught the previous excerpt showing a stale confidence 1.00 the engine's
single-source cap, added earlier this project, no longer produces):

```
[✗] (robotics) Bar30 survives 500 m depth
    verdict: contradicted (confidence 0.90)
    evidence [contradicts, trust=0.85]: Operating Pressure Range: 0 to 30 bar
      [checked against the manufacturer's RATED limit (not an observed
      destructive test): ~298 m depth-equivalent rating vs claimed 500 m
      (survives claim) -> contradicts]
      locator: DOC3_Bar30, chunk DOC3_Bar30#3, ~char 813 (chunk starts line 10)
```

## Eval suite

```bash
PYTHONPATH=. python evals/run_evals.py
```

31 real cases across all 4 domains, all passing as of this commit (13
need a live `NEBIUS_API_KEY` — robotics' calls and research_web's
multi-candidate mode both do — and skip cleanly, not falsely, without one;
see `docs/ARCHITECTURE.md` for how that's decided).

## Running the live API

```bash
cp .env.example .env   # fill in NEBIUS_API_KEY — only needed once an adapter uses the LLM client
```

`POST /verify` requires an API key — set `ANTICASSIOPEIA_API_KEY` in `.env`
before starting the server. Generate a real random key, don't type one by
hand: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
This is a deliberate fail-closed design: if `ANTICASSIOPEIA_API_KEY` isn't set at all, **every**
`/verify` request is rejected, not silently allowed through with no auth.
`/health` and `/domains` stay open (no cost, nothing sensitive). `/verify`
is also rate-limited, keyed on the validated API key (not client IP, which
would collapse every caller behind a shared proxy into one bucket) — plus
a separate, stricter per-IP throttle on repeated FAILED auth attempts, so
key-guessing gets slowed down independently of the main limit. See
`anticassiopeia/api/server.py`'s module docstring for the exact numbers
and its one honest limitation: this state isn't shared across multiple
worker processes.

```bash
uvicorn anticassiopeia.api.server:app --reload
```

```bash
curl -X POST localhost:8000/verify \
  -H 'content-type: application/json' \
  -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -d '{"text": "Bar30 survives 500m depth", "domain": "robotics"}'
```

**Deploying to Cloud Run (or any multi-instance platform): pin `--max-instances=1`.**
The rate-limit buckets, `UploadStore`, and `GET /documents`/pooled-search
ownership lookups are all per-process, in-memory state — stated plainly
in each module's own docstring, not silently assumed away. A real shared
store (Redis, Firestore, etc.) would be the correct fix for a genuinely
multi-instance deployment, but it's out of scope for this project's
timeline and budget. Without `--max-instances=1`, a document uploaded to
instance A and then referenced (by `document_id`, or implicitly via
pooled search) in a later call routed to instance B gives a false
"Unknown or expired document_id" — or a pool that looks emptier than it
really is — for a document that is actually still valid, just sitting in
a different process's memory. If this project's real traffic volume
needs `--concurrency` raised instead of scaling out, that's a one-line
fix with no downside; auto-scaling past one instance is what actually
breaks this design.

```bash
gcloud run deploy anti-cassiopeia --max-instances=1 ...
```

**Opt-in per-verdict summary.** Set `context.include_summary = true` on
any `/verify` call to get a short, best-effort, plain-English gloss of
the verdict that was *already computed* — commentary, not a new source
of evidence (the model generating it is explicitly told never to
introduce a fact not already present in the real evidence/reasoning).
OFF by default, every domain, including `ml_data`/`fpga_embedded` (which
otherwise make zero live LLM calls) — this is a real, additional LLM
call that only ever runs, and only ever costs anything, when a caller
explicitly asks for it:

```bash
curl -X POST localhost:8000/verify -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"text": "Bar30 survives 500m depth", "domain": "robotics", "context": {"include_summary": true}}'
# -> {..., "summary": "The Bar30's rated depth falls short of the 500m claimed, so this is contradicted."}
```

A summary failure (client unavailable, a dead live call) never fails the
real verdict — it's reported as a separate, named `summary_error` field
alongside the (unaffected) `state`/`confidence`/`evidence`, the same
"never let a secondary concern take down the primary result" discipline
`/verify`'s own scratch-file cleanup already follows.

## Frontend

**[cheran-eclipse.github.io/anti-cassiopeia](https://cheran-eclipse.github.io/anti-cassiopeia/)**
— a single dependency-free static HTML+JS file (`docs/index.html`,
served by GitHub Pages, no build step, no framework), pointed at the
deployed engine by default. Covers the same surface as the API: a
single-claim verify form (with live-loaded domains and quick-verify
presets), a document uploader, and a project-verify panel for a bundle
of claims each optionally tied to a different uploaded document, rolled
up the same way the API itself does. The API key field is a plain
password input stored only in that browser's `localStorage`, pre-filled
with a dedicated, separately-rate-limited public demo key (never the
primary one) so a first-time visitor can try it immediately.

**Known gap, stated plainly:** the live Cloud Run deployment this
frontend points at by default has not yet been redeployed with this
repo's current `server.py` — its own `/openapi.json` currently lists
only `/health`, `/domains`, and `/verify`. The frontend's Documents and
Project-verify panels need `POST /upload` / `POST /verify/project`,
which only exist in this repository right now, not yet on that live
service. The single-claim verify flow is unaffected (unchanged endpoint,
unchanged contract). Redeploying the service is a real, billed action on
whoever controls that Cloud Run project, so it's intentionally not done
automatically by any CI step in this repo.

## Docker

```bash
docker build -t anticassiopeia .
docker run -p 8000:8000 anticassiopeia
```

**Build-tested for real, with no secrets baked in**: `docker build`
succeeds with zero API keys available at build time (`.env` is
deliberately not copied into the image) — the in-build eval suite skips
the 13 cases that genuinely need a live key rather than failing on them,
and the resulting container actually serves `/health`, `/domains`, and a
real `POST /verify` round trip. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for how this was verified, and for a bug this re-verification found and
fixed (the eval suite used to fail the build outright on those 13 cases,
not skip them).

## Repo layout

```
anticassiopeia/
  core/        verdict types, DomainAdapter interface, VerificationEngine,
               compound.py (LLM claim decomposition + AND-rollup)
  domains/     robotics, ml_data, fpga_embedded, research_web — all real
  retrieval/   shared chunk/BM25/propose/verify/stance pipeline +
               document_ingest.py (.txt/.md/.csv/.rpt/.svd/.xml/.pdf/.docx)
  llm/         Nebius Token Factory client (live-verified, see docstring)
  api/         FastAPI surface — POST /verify, POST /upload, GET /documents,
               POST /verify/project, POST /verify/compound, GET /health, GET /domains
evals/         31 real test cases + fixtures + the runner (run_evals.py)
scripts/       demo.py — judge-facing end-to-end demo
docs/          index.html (the frontend, GitHub-Pages-served — see
               "Frontend" above), architecture, design decisions,
               Constellation extraction provenance
.github/workflows/evals.yml   CI: runs the eval suite on every push/PR
Dockerfile     build-tested for real (see above)
```

## License

MPL 2.0 — see LICENSE. Copyright (c) 2026 Cheran N K (Eclipse Hovering).
Commercial licensing available on request.

**Scope, stated explicitly (external review):** this license covers the
code in this repository only — `anticassiopeia/`, `evals/`, `scripts/`,
`stress_test/`'s own scripts, and the docs. It does NOT cover third-party
data files or vendor reports bundled or referenced alongside the code
(e.g. the UCI datasets `ml_data` claims are checked against, fetched
manufacturer datasheet excerpts, sample EDA/synthesis reports) — those
keep whatever license their original source states, which varies by
source and in some cases isn't stated by the source at all. See
[`stress_test/PROVENANCE.md`](stress_test/PROVENANCE.md) for exactly
which license applies to each bundled third-party file, stated plainly
rather than assumed.
