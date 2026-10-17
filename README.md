# Anti-Cassiopeia

A domain-agnostic verification engine. Give it a claim, it gives you back
one of exactly three things: **confirmed**, **contradicted**, or
**undetermined** — never a confident-sounding guess standing in for the
third one.

Built for the Nebius x NVIDIA Global AI Hackathon, Personal AI track, as
infrastructure other developers and AI systems can build on — not a single
demo app.

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

One domain-agnostic engine, one shared `Verdict` contract. Everything
domain-specific — what counts as a source, how to retrieve evidence, how
much to trust it — lives in a `DomainAdapter` plugin. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and
current build status.

## Four domains, all real

| Domain | POV | Evidence traces back to | Status |
|---|---|---|---|
| `robotics` | physical/datasheet | real parts/datasheet facts extracted from Eclipse: Constellation's own research (BlueROV2, Bar30) | seeded, 2/4 researched parts sourced — [extraction provenance](docs/extracted/constellation-robotics-seed.md) |
| `ml_data` | ML | an actual re-computed statistic over a real CSV file | real, offline, no external dependency |
| `fpga_embedded` | quantum | a real parsed timing/synthesis report | real, offline — parser format not yet verified against a real EDA tool's output, see module docstring |
| `research_web` | existence/verification | an actually-fetched URL, verbatim-quote-checked | real, network-dependent — confirmed blocked in *this* build sandbox (proxy 403), works wherever outbound HTTPS is open |

Every domain either returns real evidence with a real locator, or an
honest, specific, named reason it can't yet — never a guess. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full per-piece
status and known limitations stated plainly (not hidden), including a
real one in `robotics.py`: stance is currently hardcoded to one claim
framing, not polarity-aware.

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

10 real cases across all 4 domains, all passing as of this commit.

## Running the live API

```bash
cp .env.example .env   # fill in NEBIUS_API_KEY — only needed once an adapter uses the LLM client
uvicorn anticassiopeia.api.server:app --reload
```

```bash
curl -X POST localhost:8000/verify \
  -H 'content-type: application/json' \
  -d '{"text": "Bar30 survives 500m depth", "domain": "robotics"}'
```

## Docker

```bash
docker build -t anticassiopeia .
docker run -p 8000:8000 anticassiopeia
```

**Not build-tested** — written and reasoned through, but this build
sandbox had no Docker daemon to actually run `docker build` against. Test
before relying on it for submission.

## Repo layout

```
anticassiopeia/
  core/        verdict types, DomainAdapter interface, VerificationEngine
  domains/     robotics, ml_data, fpga_embedded, research_web — all real
  llm/         Nebius Token Factory client (unverified endpoint, see docstring)
  api/         FastAPI surface (POST /verify, GET /health, GET /domains)
evals/         10 real test cases + fixtures + the runner (run_evals.py)
scripts/       demo.py — judge-facing end-to-end demo
docs/          architecture, design decisions, Constellation extraction provenance
.github/workflows/evals.yml   CI: runs the eval suite on every push/PR
Dockerfile     untested (see above)
```

## License

TBD.
