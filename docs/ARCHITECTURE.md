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
| `core/engine.py` — `VerificationEngine` scoring | done, deliberately simple (trust-weighted sum + fixed thresholds) |
| `domains/*.py` — robotics, fpga_embedded, research_web, ml_data | **stubs** — `gather_evidence()` returns `[]`, real retrieval not wired |
| `llm/nebius_client.py` — Token Factory client | written but **unverified** — base URL/model are TODO, confirm against live Nebius docs |
| `api/server.py` — `POST /verify`, `GET /health` | done, routes straight to the engine above |
| `evals/` | placeholder — needs real test cases per domain once an adapter has real evidence sources |

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
