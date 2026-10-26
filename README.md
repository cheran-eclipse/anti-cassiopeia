# Anti-Cassiopeia

**A claim checker that is allowed to say "I can't tell."**

Give it a claim. It returns one of three verdicts: **confirmed**,
**contradicted** or **undetermined**, together with the quote, the source
and the location it relied on. When it can't find the evidence, it says
what is missing instead of guessing. The frontend labels the states
Confirmed / Contradicted / Clouded; the API value is `"undetermined"`.

Built for the Nebius x NVIDIA Global AI Hackathon, Apps and Agents track.
Use it as a CLI, an HTTP API, the hosted web frontend (see
["Frontend"](#frontend)), or as the claim-checking step in another
agent's tool loop, before that agent commits to an answer. All four go
through the same `VerificationEngine`. Runs on Nebius Token Factory.

## Where it fits

Anti-Cassiopeia is for work where a confident wrong claim costs more than a
missing answer. It checks a claim against evidence a person can inspect (a
document, a dataset, a report, or the open web) and returns "undetermined"
when the evidence isn't there. It does not answer from a model's memory.

| Setting | Problem | What it does |
|---|---|---|
| Training and evaluation data | Claims inside candidate training or evaluation sets are too many to check by hand | Labels each claim confirmed, contradicted or undetermined, with a quote and a locator. Undetermined items are held back instead of guessed, so the labels you keep are the ones with evidence |
| Newsrooms and fact-checkers | A viral claim needs a sourced answer fast, and "no source found" is a result | Fetches sources, quotes them, and returns undetermined when nothing settles it |
| Research groups | Citations and reported statistics get repeated without being re-checked | Matches a quoted passage against the cited page and recomputes a reported statistic from the dataset |
| Scientific institutions and labs | Specs, timing and instrument reports are compared with requirements by eye | Parses the report or datasheet and compares the stated figure with the requirement, with a line-level locator |
| Government and public bodies | Statements about policy or statistics must match the official documents | Checks claims against uploaded documents (up to 10 pooled) and cites the document and passage |
| AI labs and agent builders | An agent states facts it has not checked | Runs as a tool call before the agent answers, and returns the missing evidence when the claim isn't supported |
| Education | Claims in coursework are checked against course material by hand | Checks a claim against an uploaded text and shows where the support comes from |
| Space, defence and other high-consequence engineering | A part, a margin or a number in a report must match a requirement | Compares a stated rating or report figure with the requirement, and says when no rating exists, as it does for QuSpin's magnetometer |

**Why it helps in these settings.**
- Every confirmed or contradicted answer carries the quote or the
  recomputation and where it came from, so reviewing it is a lookup, not a
  research task.
- "Undetermined" is a normal result with the missing evidence named. For a
  training set or a report, that is the difference between a clean label and
  a plausible one.
- Statistics and timing figures are recomputed from the file, whatever its
  size. The largest test file was 23 MB, and models given a file inline
  can't take most of the `ml_data` files at all.
- It works on your own material: uploads, pooled search across documents,
  and bundles of claims.

**What is measured and what is not.** Measured so far: sourced answers on 88
independently verified open-web claims (12 of them shaped like published
fact-checks, all answered correctly), recomputed statistics and report
figures on 14 UCI datasets and 9 real Vivado reports, and document checks on
two open-source documents (ODrive, NASA JPL rover). Not measured: any effect
on model training, a deployment in any of the settings above, or use inside
a live agent loop. Read the table as the design's intended fit, not as
validation in those settings. [`docs/USE_CASES.md`](docs/USE_CASES.md)
gives, for each setting, what the repo shows and what test would show more.

## How it compares

A comparison only counts when every system works from the same evidence: the
same file, or the same search results. Systems answering from what they
learned in training (a bare model, or Perplexity's own index) are left out of
the claims below, because their results say nothing about verification,
either for or against. Those runs are in the benchmark reports.

| Same evidence for all | Anti-Cassiopeia | Others |
|---|---|---|
| Wrong answers on open-web claims (88 scored, independently verified, same Tavily search) | **2 of 64 answered** (96.9% precision) | Tavily+Gemini 4 of 85, generic RAG 5 of 74, same pipeline with one stance model 5 of 68 |
| Faith-based claims that must not be confirmed or denied (14 probes, 7 traditions, same search) | **14 / 14 undetermined** | Tavily+Gemini 5, generic RAG 3, same pipeline with one stance model 10 |
| Wrong confident answers on 116 `silicon` timing and register claims, same report for all | **0** | code-exec 3, `gpt-oss-120b` with the file pasted in 4, generic RAG 7, sonar with the file pasted in 15 (may also search the web) |
| Wrong confident answers on the 216 `quant` claims small enough to paste, same file for all (corrected labels) | **0** | code-exec 1, sonar with the file pasted in 48, generic RAG 55, `gpt-oss-120b` with the file pasted in 59 |

**Limits.** The precision ranges on the first row overlap (Anti-Cassiopeia
89.3 to 99.1%, Tavily+Gemini 88.5 to 98.2%), so it is a lead, not a proof.
Anti-Cassiopeia answers fewer claims (73.6% of decidable open-web claims in
round 2). On claims with no retrievable page, such as textbook control
theory (Track B), the result depends on what a model memorized, so those runs
are reported in [`TRACK_B_REPORT.md`](stress_test/results/TRACK_B_REPORT.md)
and not used as evidence either way. A model can't be given most `ml_data`
files inline: 540 of 756 claims use a file too large to paste (the largest is
23 MB), and Anti-Cassiopeia reads them from disk. The file-claim rows use
labels corrected for 25 stale `air_quality.csv` claims, described in
[`DOC_FED_CONTROL_REPORT.md`](stress_test/results/DOC_FED_CONTROL_REPORT.md). Details are in
[Competitive benchmark](#competitive-benchmark).

**Models.** No single model does everything: Nemotron Ultra, `gpt-oss-120b`,
Tavily and `Qwen/Qwen3-Embedding-8B` each handle the stage where they
measured best. See [Models](#models).

## Why "Anti-Cassiopeia"

In Greek myth, Cassiopeia was punished for boasting of a beauty she could
not back up. The project is named against that failure: a fluent,
plausible claim that doesn't check out. Where evidence is thin, it says so.

## How it works

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

One engine and one `Verdict` type. Everything domain-specific (what counts
as a source, how to retrieve evidence, how much to trust it) lives in a
`DomainAdapter` plugin. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the design and build status, and
[`docs/DESIGN.md`](docs/DESIGN.md#related-work) for how this relates to
FEVER, FActScore, SAFE, RARR, and FacTool.

## Four domains

| Domain | What it checks | Example claim | Evidence | Status |
|---|---|---|---|---|
| `substrate` | Hardware specs against a stated condition | "Bar30 survives 500 m depth" | Datasheet facts retrieved and re-checked against manufacturer sources (BlueROV2, Bar30, Bar100XT) with Nemotron Ultra, or your uploaded document | 3 of 4 researched parts sourced. The 4th (QuSpin QZFM Gen-3) has a confirmed source stating no rating exists, see [extraction provenance](docs/extracted/constellation-robotics-seed.md). Fixed corpus plus uploads, no live web search |
| `quant` | A statistic in a dataset | "The mean of `voltage` is 5.0 V" | Re-computed from the real CSV | Offline, no external dependency |
| `silicon` | FPGA timing and register maps | "The design meets 100 MHz timing" | Parsed from a Vivado timing or synthesis report, or a CMSIS-SVD register-map file | Offline. Timing parser verified against a real Vivado report, register-map parser against real ARM and Espressif SVD files (see module docstring) |
| `searchlight` | Whether a source says what is claimed | "ARPANET's first message crashed after two letters" | A fetched page, quote matched verbatim | Needs network. Tavily is the primary search backend, with DDG and Wikipedia as fallback |

Every domain returns evidence with a locator, or names the reason it can't.
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for per-component status
and known limitations.

## Models

| Stage | Model | Why |
|---|---|---|
| `substrate` evidence extraction (`propose()`) | **Nemotron Ultra** | Zero dangerous misses in 3 independent runs (n=15, 40, 40). [Pivot report](stress_test/results/NEMOTRON_PIVOT_REPORT.md) |
| `searchlight` evidence extraction (`propose()`) | **`gpt-oss-120b`** | No Nemotron tier beat it at an adequate sample size. A 4-claim re-check with Tavily active tied 4/4 at about one seventh of the cost. [Note](stress_test/results/DECISION2_REMEASUREMENT_NOTE.md) |
| `searchlight` hard stance judgments (`judge_stance()`) | **Nemotron Ultra** | Correct 5/5 on a hard causal case where `gpt-oss-120b` was correct 2/6; tied on easier cases. [Details](docs/ARCHITECTURE.md#causal-claim-stance-fix--judge_stance-model-routing-found-live-2026-10-25) |
| Live web search | **Tavily** (DDG and Wikipedia fallback) | See [Search](#search-tavily) |
| Hybrid retrieval, semantic half | **`Qwen/Qwen3-Embedding-8B`** | The embedding model available on this account's `GET /v1/models` |

Super and Nano each produced dangerous misses at n=40 that n=15 had not
shown, so only Ultra was adopted for `substrate`. The comparison also
found and fixed three pipeline bugs that affected every model: no
output-token cap, no quote-length guidance, and no entity-matching check
before judging a passage's stance. Nano and 3.5 Lightning remain untested
cheaper options. Full ledger:
[`MODEL_SELECTION_FINDINGS.md`](stress_test/results/MODEL_SELECTION_FINDINGS.md).

## Search (Tavily)

Tavily is `searchlight`'s primary search backend, a live API call at
runtime. DDG and Wikipedia run only when Tavily returns no URLs
(`_search_candidate_urls()` in `searchlight.py`). In Test #3 it returned
results for all 473 scored queries.

Every stress-test script before 2026-10-25 was missing `load_dotenv()`, so
Tavily was switched off in those runs and `searchlight` fell back to
DDG and Wikipedia. The production server was not affected. After the fix,
3 of the 4 claims that failed in benchmark round 1 resolved. Details:
[`BENCHMARK_ROUND1_REPORT.md`](stress_test/results/BENCHMARK_ROUND1_REPORT.md).

## Hybrid retrieval (BM25 + vector)

BM25 keyword search fused with `Qwen/Qwen3-Embedding-8B` embeddings by
reciprocal rank fusion, alongside the BM25-only path. Ported from
`eclipse-constellation`. On 13 hand-labelled questions, hit@3 on paraphrased
questions was 0.86 for hybrid and vector against 0.79 for BM25. On
keyword-overlap questions BM25 alone does better (R@1 0.67 against 0.50
for hybrid). It falls back to BM25 if embedding fails, and adds about 1 to
2 seconds per claim. Results:
[`evals/retrieval/RESULTS.md`](evals/retrieval/RESULTS.md).

## Adaptive-depth evidence gathering

`searchlight` stops checking sources once two independent sources agree
(one easy claim took 2 calls instead of 3). When the first pass finds
nothing or ties, it checks more sources with a reworded second search.
Both paths feed the same scoring, so the verdict is always one of the
three states, and a test covers that.

## Competitive benchmark

Claims were generated by ChatGPT, Gemini and Perplexity from a locked
prompt, then **independently verified against real sources** before any of
them touched the engine. Six systems ran on the same claims. Four use the
same Tavily search results and are compared here: Anti-Cassiopeia, the same
pipeline with a single stance model ("Nebius-agent"), generic RAG, and
Tavily+Gemini. The bare model (training data only) and Perplexity (its own
index) are in the reports and are not compared here.

**Round 2, open web, 88 scored claims** (precision = correct among the
claims a system answered):

| System | Answered | Wrong | Precision | Coverage |
|---|---|---|---|---|
| **Anti-Cassiopeia** | 64 | **2** | **96.9%** | 73.6% |
| Tavily+Gemini | 85 | 4 | 95.3% | 96.6% |
| Generic RAG | 74 | 5 | 93.2% | 86.0% |
| Same pipeline, single stance model | 68 | 5 | 92.6% | 78.2% |

Precision ranges overlap (Anti-Cassiopeia 89.3 to 99.1%, Tavily+Gemini
88.5 to 98.2%), so this is a lead, not a proof. Anti-Cassiopeia declines
more often: most of its misses are "undetermined" where an answer existed.

**Other results.** The 14 faith-based probes covered 7 traditions; generic
RAG confirmed 9 of them, including the Fátima apparition and Muhammad's
Night Journey. Most of Anti-Cassiopeia's misses are causal and relational
claims, where it requires a source to state the relationship. A follow-up,
`judge_comparative_stance()`, recovered 2 of 12 such claims in a live
check, with no regressions. Track B (69 formal and technical claims) is
the case where retrieval doesn't help, covered above.

**What the benchmark changed.** It found and fixed a calibration bug that
confirmed a faith claim on a source that said "according to tradition", a
stance rule too strict to contradict claims no single source rebuts, a
compound-claim path that rewrote a sub-claim into its own negation, and the
Tavily measurement bug above. Each is documented with its fix.

Reports:
[round 1](stress_test/results/BENCHMARK_ROUND1_REPORT.md),
[round 2](stress_test/results/BENCHMARK_ROUND2_REPORT.md),
[comparative-synthesis fix](stress_test/results/COMPARATIVE_SYNTHESIS_FIX_NOTE.md),
[Track B](stress_test/results/TRACK_B_REPORT.md),
and the claim sets in
[`stress_test/claims/external_generated/`](stress_test/claims/external_generated/README.md).

## Bring your own evidence

The four domains also work against a document you supply.

```bash
curl -X POST localhost:8000/upload -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -F file=@my_datasheet.pdf
# -> {"document_id": "...", "filename": "my_datasheet.pdf", "size_bytes": 48213}
```

`.txt`, `.md`, `.csv`, `.rpt`, `.svd` and `.xml` are read as plain text;
`.pdf` (via `pypdf`) and `.docx` (via `python-docx`) have their text layer
extracted. A PDF with no text layer returns an error; there is no OCR. The
extracted text is kept in memory for 24 hours under an opaque
`document_id`.

**One claim against a document.** Pass the `document_id` in `context`. For
`substrate`, the pipeline (chunk, BM25 retrieve, propose, re-verify, judge
stance) runs on your document instead of the fixed corpus. For `quant` and
`silicon`, the document text is written to a scratch file and used as
`dataset_path` / `report_path`; you still supply the structured fields
(column and stat, or peripheral, metric and comparator). `searchlight`
doesn't use uploads, so a `document_id` there returns 400.

```bash
curl -X POST localhost:8000/verify -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"text": "the X9 sensor is rated for 450m depth", "domain": "substrate", "context": {"document_id": "..."}}'
```

**Search all your uploads.** Set `document_pool: true` instead of
`document_id` (`substrate` only, exclusive with `document_id`).
`GET /documents` lists your current uploads.

```bash
curl localhost:8000/documents -H "X-API-Key: $ANTICASSIOPEIA_API_KEY"
# -> {"documents": [{"document_id": "...", "filename": "odrive.txt", "size_bytes": 1824, "seconds_until_expiry": 86391.2}, ...]}

curl -X POST localhost:8000/verify -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"text": "the X9 sensor is rated for 450m depth", "domain": "substrate", "context": {"document_pool": true}}'
```

One BM25 index covers up to your 10 most recently uploaded documents, with
one propose call and one stance call per claim. The citation names the
document the answer came from. Uploads are tied to the API key that
uploaded them (stored as a SHA-256 hash). The shared public demo key is the
exception: under it, the pool holds every demo visitor's uploads.

**A bundle of claims.** `POST /verify/project` takes up to 20 claims, each
with its own `document_id` or `document_pool`. It detects each upload's
format (by extension, and by content markers for `.xml`) and routes it to
the right domain. `quant` and `silicon` claims still need their structured
fields. The response has each claim's `Verdict` and one rolled-up status:
any `CONTRADICTED` claim makes the bundle contradicted, and one claim's
error doesn't fail the others. It has its own rate limit.

```bash
curl -X POST localhost:8000/verify/project -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"claims": [
        {"text": "the mean voltage is 5.0", "document_id": "<csv-doc>", "context": {"column": "voltage", "stat": "mean", "expected_value": 5.0}},
        {"text": "the X9 sensor is rated for 450m depth", "document_id": "<datasheet-doc>"}
      ]}'
```

**Compound claims.** `POST /verify/compound` splits one free-text claim
("A and B") into parts with an LLM call (`decompose_claim()` in
`core/compound.py`), verifies each part, and rolls up the same way (any
`CONTRADICTED` part contradicts the whole). A fidelity check rejects
splits that change a part's meaning. Parts go to `substrate` or
`searchlight` only, and `document_id` / `document_pool` in `context`
return 400. Limits: 8 parts (422 above that) and one call per 20 seconds.

```bash
curl -X POST localhost:8000/verify/compound -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"text": "The ODrive is open-source and BlueROV2 uses a Bar30 sensor rated for 300m"}'
```

## Run it

```bash
pip install -e .
PYTHONPATH=. python scripts/demo.py
```

The demo runs 6 claims across all 4 domains through the engine. Example
output (`substrate`, 2026-10-24):

```
[✗] (substrate) Bar30 survives 500 m depth
    verdict: contradicted (confidence 0.90)
    evidence [contradicts, trust=0.85]: Operating Pressure Range: 0 to 30 bar
      [checked against the manufacturer's RATED limit (not an observed
      destructive test): ~298 m depth-equivalent rating vs claimed 500 m
      (survives claim) -> contradicts]
      locator: DOC3_Bar30, chunk DOC3_Bar30#3, ~char 813 (chunk starts line 10)
```

**Evals:**

```bash
PYTHONPATH=. python evals/run_evals.py
```

31 cases across all 4 domains. 14 need a live `NEBIUS_API_KEY` (`substrate`
and `searchlight`'s multi-candidate mode) and are skipped without one. See
`docs/ARCHITECTURE.md` for how that is decided.

**API:**

```bash
cp .env.example .env   # fill in NEBIUS_API_KEY
```

`POST /verify` needs an API key: set `ANTICASSIOPEIA_API_KEY` in `.env`
before starting the server, and generate it with
`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. If it
isn't set, every `/verify` request is rejected. `/health` and `/domains`
are open. `/verify` is rate-limited per API key (not per IP, which would
merge callers behind a shared proxy), with a separate per-IP throttle on
failed auth attempts. This state isn't shared across worker processes; the
exact numbers are in `anticassiopeia/api/server.py`'s module docstring.

```bash
uvicorn anticassiopeia.api.server:app --reload
```

```bash
curl -X POST localhost:8000/verify \
  -H 'content-type: application/json' \
  -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -d '{"text": "Bar30 survives 500m depth", "domain": "substrate"}'
```

**Cloud Run and other multi-instance hosts: use `--max-instances=1`.**
Rate-limit state, `UploadStore` and document ownership live in each
process's memory. Without a single instance, a document uploaded to one
instance can come back as "Unknown or expired document_id" from another.
If load is the problem, raise `--concurrency` instead. A shared store such
as Redis is the proper fix and is out of scope here.

```bash
gcloud run deploy anti-cassiopeia --max-instances=1 ...
```

**Optional summary.** Set `context.include_summary = true` on `/verify` to
get a one-sentence plain-English summary of the verdict. It is an extra LLM
call, off by default in every domain, and it only restates the existing
evidence. If it fails, the verdict is unaffected and the response carries a
`summary_error` field.

```bash
curl -X POST localhost:8000/verify -H "X-API-Key: $ANTICASSIOPEIA_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"text": "Bar30 survives 500m depth", "domain": "substrate", "context": {"include_summary": true}}'
# -> {..., "summary": "The Bar30's rated depth falls short of the 500m claimed, so this is contradicted."}
```

## Frontend

**[cheran-eclipse.github.io/anti-cassiopeia](https://cheran-eclipse.github.io/anti-cassiopeia/)**
is one static HTML and JS file (`docs/index.html`, served by GitHub Pages,
no build step). It has a single-claim form with domain presets, a document
uploader, and a project panel for a bundle of claims. The API key field is
stored in the browser's `localStorage` and pre-filled with a rate-limited
public demo key. The deployed backend (redeployed 2026-10-25) serves every
endpoint in this repo and the renamed domains.

## Docker

```bash
docker build -t anticassiopeia .
docker run -p 8000:8000 anticassiopeia
```

The build needs no API keys (`.env` is not copied into the image) and
skips the 14 key-dependent evals. The container serves `/health`,
`/domains` and `POST /verify`. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for how this was verified.

## Repo layout

```
anticassiopeia/
  core/        verdict types, DomainAdapter interface, VerificationEngine,
               compound.py (LLM claim decomposition + AND-rollup)
  domains/     substrate, quant, silicon, searchlight
  retrieval/   shared chunk/BM25/propose/verify/stance pipeline,
               hybrid.py (BM25+vector fusion, ported from Constellation),
               document_ingest.py (.txt/.md/.csv/.rpt/.svd/.xml/.pdf/.docx)
  llm/         Nebius Token Factory client, with embed() for hybrid retrieval
  api/         FastAPI surface — POST /verify, POST /upload, GET /documents,
               POST /verify/project, POST /verify/compound, GET /health, GET /domains
evals/         31 test cases + fixtures + the runner (run_evals.py);
               evals/retrieval/ — the hybrid-retrieval eval
scripts/       demo.py — end-to-end demo
docs/          index.html (the frontend), architecture, design decisions,
               Constellation extraction provenance
stress_test/   benchmark harness (run_benchmark_round1.py + 5 competitor
               variants) and the full stress-test history: every bug found,
               every report, indexed in results/INDEX.md
.github/workflows/evals.yml   CI: runs the eval suite on every push/PR
Dockerfile
```

## License

MPL 2.0, see LICENSE. Copyright (c) 2026 Cheran N K (Eclipse Hovering).
Commercial licensing available on request.

**Scope:** the license covers the code in this repository only
(`anticassiopeia/`, `evals/`, `scripts/`, `stress_test/`'s own scripts, and
the docs). It does not cover third-party data files or vendor reports
bundled or referenced alongside the code (for example the UCI datasets
`quant` claims are checked against, fetched manufacturer datasheet
excerpts, and sample EDA/synthesis reports). Those keep the license their
source states, which varies and in some cases isn't stated. See
[`stress_test/PROVENANCE.md`](stress_test/PROVENANCE.md) for the license of
each bundled third-party file.
