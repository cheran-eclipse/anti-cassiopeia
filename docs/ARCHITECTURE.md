# Architecture

## The mechanism, in one sentence

Take a narrow, checkable `Claim`, route it to the one `DomainAdapter` that
knows how to gather real `Evidence` for it, and let one shared, centralized
scoring rule in `VerificationEngine` decide the `Verdict` — `CONFIRMED`,
`CONTRADICTED`, or `UNDETERMINED` — never anything smoother than that.

```
Claim ──▶ VerificationEngine.verify()
              │
              ▼
        DomainAdapter.gather_evidence(claim)   (robotics | fpga_embedded | research_web | ml_data)
              │
              ▼
        list[Evidence]  (source, snippet, stance, trust, locator)
              │
              ▼
        VerificationEngine._score()  ──▶  Verdict (state, confidence, reasoning, missing)
```

## Why the domain split

Four domains, one contract. Each domain's adapter is the only place that
knows what "evidence" even means for that domain — a datasheet locator for
robotics, a timing report for FPGA/embedded, a fetched source for
web/research, a re-run computation for ML/data. None of that
domain-specific knowledge leaks into the engine. The engine only ever sees
`Evidence` objects with a `stance` and a `trust` weight already assigned —
it doesn't know or care what a "datasheet" is.

This is what makes the engine genuinely reusable as infrastructure: a
fifth domain is a new `DomainAdapter` subclass, not a fork of the engine.

## Why three states, not a probability

A single confidence score invites exactly the failure mode the project is
named against — a fabricated-but-fluent answer wearing a number that makes
it look measured. Three discrete states, with `UNDETERMINED` as a first-
class, frequently-correct answer (not a fallback for engine bugs), forces
every integration built on top of this to actually handle "I don't know"
rather than silently rounding it up to a guess.

`Verdict.missing` exists so `UNDETERMINED` is never a dead end — it names,
concretely, what evidence would resolve the claim, the same way a domain
adapter should (see each adapter's `describe_gap()`).

## Current status (bone framework)

| Piece | Status |
|---|---|
| `core/verdict.py` — `Claim`, `Evidence`, `Verdict`, `VerdictState` | done |
| `core/domain.py` — `DomainAdapter` interface | done |
| `core/engine.py` — `VerificationEngine` scoring | done, deliberately simple (trust-weighted sum + fixed thresholds); now also handles `contested` evidence (excluded from scoring, surfaced in reasoning) |
| `domains/robotics.py` | **seeded, not live** — hand-built lookup over real, locator-backed facts extracted from Constellation (BlueROV2, Bar30); Bar100XT/QuSpin return an honest gap, both unsourced in Constellation itself. **Known limitation:** stance is hardcoded to one claim framing, not polarity-aware — see the module docstring |
| `domains/ml_data.py` | **real, offline, tested** — re-computes the claimed statistic from an actual CSV via stdlib `csv`+`statistics`, no external dependency. Produced the engine's first real `CONFIRMED` verdict |
| `domains/fpga_embedded.py` | **real, offline, tested** — parses an actual `key: value` report file and compares a named metric against a threshold. **Known limitation:** report format is this adapter's own invention, not verified against real Vivado/Yosys/Quartus output — see module docstring |
| `domains/research_web.py` | **real, network-dependent** — fetches a URL live and verbatim-checks a quote. **Confirmed blocked in this build sandbox** (proxy 403, allowlisted to package registries + GitHub only) — correctly surfaces as `UNDETERMINED` with the real error, not a crash. Needs a real network to produce `confirmed`/`contradicted` |
| `llm/nebius_client.py` — Token Factory client | written but **unverified** — base URL/model are TODO, confirm against live Nebius docs. Not yet used by any domain adapter |
| `api/server.py` — `POST /verify`, `GET /health`, `GET /domains` | done, routes straight to the engine above |
| `scripts/demo.py` | real end-to-end demo, 6 claims across all 4 domains, no mocked output |
| `Dockerfile` | written, **not build-tested** — no Docker daemon available in this build sandbox |
| `.github/workflows/evals.yml` | written, mirrors the exact local commands already verified to work (`pip install -e .` + `python evals/run_evals.py`) — CI run itself not observed |
| `evals/` | 3 real cases for `robotics`, all passing (`python evals/run_evals.py`) — none yet for the other 3 domains (still stubs) |

Nothing above claims to be more finished than this table says. That table
itself is a claim this project would check against — keep it honest as
pieces move from stub to real.

## Open design decisions (not yet made)

- Claim decomposition: should the engine (or an LLM pass) break a complex
  claim into sub-claims before routing, or does every `Claim` stay atomic
  by convention? Currently: atomic by convention, no decomposition step.
- Evidence retrieval inside each domain adapter: web search? local
  datasheet index? direct API calls (synthesis tool output, dataset
  files)? Each domain will likely need a different answer.
- Scoring: the current trust-weighted threshold rule in `engine.py` is a
  placeholder, not a researched method. Revisit once real evidence from at
  least one real domain is flowing through it.
