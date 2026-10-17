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

## Four initial domains

| Domain | POV | What evidence has to trace back to |
|---|---|---|
| `robotics` | physical/datasheet | a real part/assembly datasheet locator |
| `fpga_embedded` | quantum | synthesis/timing reports, register maps, sim logs |
| `research_web` | existence/verification | an actually-fetched source, not recalled knowledge |
| `ml_data` | ML | a re-run computation or statistical test |

All four are currently **stubs** — `gather_evidence()` returns `[]`. The
engine, scoring, and API surface around them are real and tested.

## Status: bone framework

This is the skeleton, built first so the "skin" (demos, UI, polish) has
something real and load-bearing to sit on rather than the other way
around. Smoke-tested end to end: a claim with no wired evidence source
correctly resolves to `UNDETERMINED` with a named, domain-specific gap —
not a silent failure, not a guess.

```
$ python -c "..."
VerdictState.UNDETERMINED None
['Gathered 0 piece(s) of evidence from domain 'robotics'.',
 'Support weight: 0.00, contradiction weight: 0.00.',
 'Total evidence weight below minimum — refusing to render a confident verdict.']
['No datasheet or spec-sheet evidence found for this part/assembly claim. ...']
```

## Running it

```bash
pip install -e .
cp .env.example .env   # fill in NEBIUS_API_KEY
uvicorn anticassiopeia.api.server:app --reload
```

```bash
curl -X POST localhost:8000/verify \
  -H 'content-type: application/json' \
  -d '{"text": "Bar30 survives 500m depth", "domain": "robotics"}'
```

## Repo layout

```
anticassiopeia/
  core/        verdict types, DomainAdapter interface, VerificationEngine
  domains/     one adapter per domain (stubs for now)
  llm/         Nebius Token Factory client
  api/         FastAPI surface (POST /verify, GET /health)
evals/         test cases per domain (empty until a domain is real)
docs/          architecture + open design decisions
```

## License

TBD.
