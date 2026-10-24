# Anti-Cassiopeia

A verification engine. Give it a claim, it gives you back one of exactly
three things: **confirmed**, **contradicted**, or **undetermined** — never
a confident-sounding guess standing in for the third one.

Built for the Nebius x NVIDIA Global AI Hackathon, Apps and Agents track:
an app or agent you'd actually use, not a single demo script. Run it as
a CLI, call it as an HTTP API, or wire it into another agent's tool-use
loop as the claim-checking step before that agent commits to an answer —
all three hit the same `VerificationEngine`. Runs on Nebius Token Factory
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
mocked output. Example excerpt (robotics, on real sourced facts):

```
[✗] (robotics) Bar30 survives 500 m depth
    verdict: contradicted (confidence 1.00)
    evidence [contradicts, trust=0.85]: Operating pressure range: 0 to 30 bar,
      -20 to +85 C (≈296 m depth-equivalent) — fails a 500 m condition by ~40%.
      locator: docs/extracted/constellation-robotics-seed.md §2, citing
      evals/model-comparison/corpus/DOC3_Bar30_MS5837-30BA_chip_datasheet.txt:11,33
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
  core/        verdict types, DomainAdapter interface, VerificationEngine
  domains/     robotics, ml_data, fpga_embedded, research_web — all real
  llm/         Nebius Token Factory client (live-verified, see docstring)
  api/         FastAPI surface (POST /verify, GET /health, GET /domains)
evals/         31 real test cases + fixtures + the runner (run_evals.py)
scripts/       demo.py — judge-facing end-to-end demo
docs/          architecture, design decisions, Constellation extraction provenance
.github/workflows/evals.yml   CI: runs the eval suite on every push/PR
Dockerfile     build-tested for real (see above)
```

## License

MPL 2.0 — see LICENSE. Copyright (c) 2026 Cheran N K (Eclipse Hovering).
Commercial licensing available on request.
