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
| `domains/robotics.py` | **real retrieve + propose + verify, end to end, LIVE ROUND TRIP CONFIRMED** — chunking, BM25, a real `extract.propose()` call against `NebiusTokenFactoryClient`, and `verify_proposal()` all run for real over a partial corpus of Constellation-sourced excerpts; nothing hand-authored stands in for the model's answer anymore. Verified two ways: offline against a scripted fake client (17 tests) that reproduces the real `propose()`→`verify_proposal()` code path without a network call, AND against the genuine live API — both `test_live_*` tests in `tests/test_domains_robotics.py` PASS for real (confirmed evidence accepted for a corpus fact; honest "not found" for a fact genuinely absent from the shown passages, not a hallucination). **Earlier non-determinism (found, diagnosed, fixed, not papered over):** an early live run showed the structured `kind` field ("rated"/"tested"/null) coming back inconsistent across repeated identical calls (~4/8). Root cause was `retrieval/extract.py`'s prompt, not the model: it named the three allowed values with no explanation of what they mean, so a model correctly refused to assert a classification it was never told how to make. Fixed by naming the distinction in the prompt itself — re-verified at 8/8 and 6/6 across two different models. `kind == "rated"` was never loosened to force this green. Stance is **derived per claim** (depth + survives/fails polarity from `Claim.context` or a narrow text grammar; spec re-parsed from the verified quote; bar→depth conversion with a 5% too-close-to-call margin). Bar100XT/QuSpin return an honest gap, both unsourced in Constellation itself |
| `domains/ml_data.py` | **real, offline, tested** — re-computes the claimed statistic from an actual CSV via stdlib `csv`+`statistics`, no external dependency. Produced the engine's first real `CONFIRMED` verdict |
| `domains/fpga_embedded.py` | **real, offline, tested** — parses an actual `key: value` report file and compares a named metric against a threshold. **Known limitation:** report format is this adapter's own invention, not verified against real Vivado/Yosys/Quartus output — see module docstring |
| `domains/research_web.py` | **TWO modes, both real.** Mode 1 (unchanged): a pre-selected URL, fetched live, verbatim quote check. Evals/demo use a local fixture server (`evals/fixture_server.py`) so those verdicts can't rot; one separate live case against example.com (`live_example_com_drift`) accepts `contradicted` as a "page drifted" outcome. Mode 2 (**new**): genuine multi-candidate live research — no pre-selected URL, just a claim. Real keyless search (Wikipedia's API, confirmed working live; DuckDuckGo HTML, confirmed anti-bot-blocked from this dev sandbox — tried anyway, best-effort) finds candidate pages, which are fetched, chunked (`retrieval/chunking.py`), BM25-searched (one combined index, then grouped by source page so up to 3 distinct real sources are each independently checked — not just the single best-ranked chunk), run through the same live `extract.propose()` (`openai/gpt-oss-120b`) robotics.py uses, and independently `verify_proposal()`-checked. A real CONFIRMED, a real CONTRADICTED, and two differently-shaped real UNDETERMINED outcomes (no candidates found at all vs. candidates found but the fact genuinely absent) were each confirmed live, repeatedly, not assumed — see `evals/cases/research_web/live_multi_candidate_*.json`. The stance (supports/contradicts) for mode 2 is a bounded LLM judgment on an ALREADY-mechanically-verified quote, not a new source of fabrication risk — two purely mechanical approaches (strict substring, token-overlap ratio) were tried first and both failed on real live tests (see module docstring). **Near-duplicate guard:** checking multiple sources means two of them can be the same source in disguise (a mirror, a copy-pasted sentence) — `_is_near_duplicate_evidence()` (Jaccard token overlap >= 0.8) drops a second near-verbatim match before it ever reaches `core/engine.py`'s scoring, so a mirror can't be double-counted as independent confirmation; a genuinely differently-worded second source confirming the same fact still counts, proven by two offline tests against real local fixture pages (`test_multi_candidate_mirror_sources_count_as_one_not_two`, `test_multi_candidate_genuinely_different_sources_both_count`) — `core/engine.py` itself was not touched |
| `llm/nebius_client.py` — Token Factory client | **fully live-verified**. Base URL **corrected**: was `https://api.studio.nebius.ai/v1` (wrong domain and TLD), now `https://api.tokenfactory.nebius.com/v1` — confirmed with a real `GET /v1/models` call (200, 28 models). Model **set to `openai/gpt-oss-120b`** on measured benchmark data (a related project's Nebius model-selection benchmark: 100% strict-JSON extraction, 100% JSON-valid, 100% overall on a 27x3 run, 0.95s latency, for an equivalent "extract structured values" stage) — not the original guess (`meta-llama/Meta-Llama-3.1-70B-Instruct`, which isn't in the live catalog at all) and not picked for branding fit. Confirmed for this account/endpoint specifically: live in the catalog, a real chat-completions round trip works, and repeated real `propose()` calls against this project's own corpus returned correct `chunk_id`+verbatim `quote` every time (8/8, then 6/6 on a second doc pair). **Three bugs found and fixed:** (1) `python-dotenv` was a declared dependency but `load_dotenv()` was never called anywhere, so a `.env`-only setup (the README's own documented flow) silently never loaded the key; (2) the first fix used `load_dotenv()`'s default `override=False`, which kept a stale already-exported shell value even after `.env` was edited with a freshly rotated key — switched to `override=True`; (3) `retrieval/extract.py`'s prompt named `"kind": "rated" or "tested" or null` with no explanation of what those values mean — see `domains/robotics.py`'s row for what that caused and how it was found. Now used for real by `domains/robotics.py` |
| `api/server.py` — `POST /verify`, `GET /health`, `GET /domains` | done, routes straight to the engine above |
| `scripts/demo.py` | real end-to-end demo, 6 claims across all 4 domains, no mocked output |
| `Dockerfile` | **build-tested for real**: `docker build` succeeds (the in-build `evals/run_evals.py` step passes all 17 cases), and the resulting container actually serves — `/health`, `/domains`, and `POST /verify` all verified live against a running container |
| `.github/workflows/evals.yml` | written, mirrors the exact local commands already verified to work (`pip install -e .` + `python evals/run_evals.py`) — CI run itself not observed |
| `evals/` | 17 cases across all 4 domains, all passing (`PYTHONPATH=. python evals/run_evals.py`), live LLM call included — confirmed 17/17 on three separate runs after the `retrieval/extract.py` prompt fix (see `domains/robotics.py`'s row; before that fix, robotics cases flipped between passing and an honest `UNDETERMINED` run to run) |

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
