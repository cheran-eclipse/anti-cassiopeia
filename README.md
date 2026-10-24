# Anti-Cassiopeia

A verification engine. Give it a claim, it gives you back one of exactly
three things: **confirmed**, **contradicted**, or **undetermined** — never
a confident-sounding guess standing in for the third one.

Built for the Nebius x NVIDIA Global AI Hackathon, Apps and Agents track:
an app or agent you'd actually use, not a single demo script. Run it as
a CLI, call it as an HTTP API, or wire it into another agent's tool-use
loop as the claim-checking step before that agent commits to an answer —
all three hit the same `VerificationEngine`. Runs on Nebius Token Factory
(see `anticassiopeia/llm/nebius_client.py`); the NVIDIA Nemotron model
swap and gpt-oss-120b baseline comparison are in progress — this line
gets updated to state the final model choice once that lands, not before.

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
| `robotics` | physical/datasheet | real parts/datasheet facts, retrieved+verified against manufacturer sources (BlueROV2, Bar30, Bar100XT) | 3/4 researched parts sourced; the 4th (QuSpin QZFM Gen-3) has a confirmed real source stating NO rating exists — [extraction provenance](docs/extracted/constellation-robotics-seed.md) |
| `ml_data` | ML | an actual re-computed statistic over a real CSV file | real, offline, no external dependency |
| `fpga_embedded` | quantum | a real parsed timing/synthesis report, or a real CMSIS-SVD register-map file | real, offline — timing parser verified against a real Vivado report; register-map parser verified against real ARM/Espressif SVD files, see module docstring |
| `research_web` | existence/verification | an actually-fetched URL, verbatim-quote-checked | real, network-dependent — Tavily primary search backend, DDG+Wikipedia fallback |

Every domain either returns real evidence with a real locator, or an
honest, specific, named reason it can't yet — never a guess. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full per-piece
status and known limitations stated plainly, not hidden.

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

30 real cases across all 4 domains, all passing as of this commit.

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

**Build-tested for real**: `docker build` succeeds (the in-build eval
suite passes inside the image), and the resulting container actually
serves `/health`, `/domains`, and `POST /verify` — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how this was verified.

## Repo layout

```
anticassiopeia/
  core/        verdict types, DomainAdapter interface, VerificationEngine
  domains/     robotics, ml_data, fpga_embedded, research_web — all real
  llm/         Nebius Token Factory client (unverified endpoint, see docstring)
  api/         FastAPI surface (POST /verify, GET /health, GET /domains)
evals/         30 real test cases + fixtures + the runner (run_evals.py)
scripts/       demo.py — judge-facing end-to-end demo
docs/          architecture, design decisions, Constellation extraction provenance
.github/workflows/evals.yml   CI: runs the eval suite on every push/PR
Dockerfile     untested (see above)
```

## License

MPL 2.0 — see LICENSE. Copyright (c) 2026 Cheran N K (Eclipse Hovering).
Commercial licensing available on request.
