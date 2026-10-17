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
| `domains/robotics.py` | **real retrieve + verify, simulated propose** — chunking, BM25 and `verify_proposal()` run for real over a partial corpus of Constellation-sourced excerpts; the LLM propose step is a hand-authored stand-in (no `NEBIUS_API_KEY` yet). Stance is now **derived per claim** (depth + survives/fails polarity from `Claim.context` or a narrow text grammar; spec re-parsed from the verified quote; bar→depth conversion with a 5% too-close-to-call margin). Unparseable/negated conditions return a named gap. Bar100XT/QuSpin return an honest gap, both unsourced in Constellation itself |
| `domains/ml_data.py` | **real, offline, tested** — re-computes the claimed statistic from an actual CSV via stdlib `csv`+`statistics`, no external dependency. Produced the engine's first real `CONFIRMED` verdict |
| `domains/fpga_embedded.py` | **real, offline, tested** — parses an actual `key: value` report file and compares a named metric against a threshold. **Known limitation:** report format is this adapter's own invention, not verified against real Vivado/Yosys/Quartus output — see module docstring |
| `domains/research_web.py` | **real, network-dependent** — fetches a URL live and verbatim-checks a quote. Evals/demo use a local fixture server (`evals/fixture_server.py`, pages in `evals/fixtures/web/`) so verdicts can't rot; one separate live case against example.com (`live_example_com_drift`) accepts `contradicted` as a legitimate "page drifted" outcome. Block pages served as HTTP 200 resolve to `UNDETERMINED`, not `contradicted` |
| `llm/nebius_client.py` — Token Factory client | written but **unverified** — base URL/model are TODO, confirm against live Nebius docs. Not yet used by any domain adapter |
| `api/server.py` — `POST /verify`, `GET /health`, `GET /domains` | done, routes straight to the engine above |
| `scripts/demo.py` | real end-to-end demo, 6 claims across all 4 domains, no mocked output |
| `Dockerfile` | written, **not build-tested** — no Docker daemon available in this build sandbox |
| `.github/workflows/evals.yml` | written, mirrors the exact local commands already verified to work (`pip install -e .` + `python evals/run_evals.py`) — CI run itself not observed |
| `evals/` | 17 cases across all 4 domains, all passing (`PYTHONPATH=. python evals/run_evals.py`) |

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
