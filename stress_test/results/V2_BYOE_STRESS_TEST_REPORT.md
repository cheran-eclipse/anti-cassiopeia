# v2 "bring your own evidence" stress test — report

Run date: 2026-10-25. Runner: `stress_test/run_v2_byoe_stress_test.py`.
Raw per-scenario request/response pairs: `stress_test/results/v2_byoe_stress_test_raw.json`
(regenerated each run, not hand-edited).

**Scope:** exercises the full scenario matrix from
`claude/ANTI_CASSIOPEIA_V2_MASTER_BUILD_PROMPT.md` against the REAL
FastAPI app (`anticassiopeia.api.server.app`, via `TestClient` — same
process, same code, not a mock), using two genuinely open-source
robotics hardware documents fetched and license-verified this session
(see `stress_test/PROVENANCE.md`'s "v2 ... stress-test material"
section), plus the project's own existing real/synthetic fixtures for
the ml_data/fpga_embedded legs. Real local computation for ml_data/
fpga_embedded; real, live Nebius calls (Nemotron Ultra for robotics,
gpt-oss-120b for research_web) for every robotics/research_web claim —
10 live calls total across the whole run, kept deliberately small
against this project's $20 Nebius spend cap.

**Result: 17/17 scenarios passed**, after finding and fixing one real
bug along the way (below) — this report is the second run, not the
first; the first run's 4 failures, what they actually were, and how
each was resolved are documented honestly rather than silently rerun
until green.

## Real sources used

| Document | Project | License | Used for |
|---|---|---|---|
| `evals/fixtures/odrive_v3_6_specifications_excerpt.txt` | ODrive v3.6 motor controller | MIT (ODrive Robotics) | robotics BYOE (single-claim + project bundle) |
| `evals/fixtures/nasa_jpl_open_source_rover_readme_excerpt.txt` | NASA JPL Open Source Rover | Apache-2.0 (Caltech/JPL) | robotics BYOE |
| `evals/fixtures/esp32c2_register_map_excerpt.svd` | Espressif ESP32-C2 SVD (pre-existing) | Apache-2.0 | fpga_embedded via upload/sniffing (not direct path) |
| `evals/fixtures/sample_measurements.csv` | this project's own synthetic fixture (pre-existing) | n/a (original, not third-party) | ml_data via upload/sniffing |

Full license chain (exact raw URLs fetched, exact LICENSE file text
quoted) is in `stress_test/PROVENANCE.md`, not duplicated here.

## Scenario results

| # | Scenario | What ran | Result |
|---|---|---|---|
| 7 | No document at all | `robotics` claim, no `document_id` | **PASS** — fixed-corpus path unchanged, `contradicted` (0.90), same as before v2 existed |
| 2a/2d | Upload real documents | `/upload` with the real ODrive and NASA JPL rover excerpts | **PASS** — both extracted and stored correctly |
| 2b/2e | BYOE, TRUE claim | robotics claim against each real uploaded doc | **PASS** — both `confirmed` (0.90), citing the real quoted text |
| 2c/2f | BYOE, FALSE claim | robotics claim contradicting each real doc's real number | **PASS** — both `contradicted` (0.90) |
| 1 | research_web, no document | live search: "ODrive is an open-source motor controller project." | **PASS** — `confirmed` or an honest `undetermined` (live search result, not scripted) |
| 4 | research_web, no document | live search: NASA JPL/Caltech claim | **PASS** — same |
| 6a/6b | Upload CSV + SVD | `/upload` for both | **PASS** |
| 6c | Upload flow for a structured domain | SVD sniffed to `fpga_embedded`, real register check via `/verify/project` | **PASS** — `confirmed` (0.90), proves the upload→scratch-file→real-parser path works, not just a direct `report_path` |
| 3+5 | Multi-domain project bundle | robotics BYOE + ml_data + fpga_embedded, one `/verify/project` call | **PASS** (after the fix below) — all 3 claims `confirmed`, rollup `confirmed` |
| 10 | Nothing routable | claim with a fabricated `document_id` | **PASS** — named per-claim `error`, honest `undetermined` rollup, no fabrication |
| 9 | Oversized upload | 10MB+1 byte file | **PASS** — clean `413` |
| 8 | Malformed upload | garbage bytes named `broken.pdf` | **PASS** — clean `422`, "could not be read as a PDF" |
| 11 | No-text-layer PDF | a real blank PDF page (pypdf-generated, no content stream) | **PASS** — clean `422`, "no extractable text", no OCR attempted |

## Bug found and fixed during this stress test

**First run: 4/14 failed.** Investigated each rather than rerun blind:

- **Two were the stress-test script's own fault, not a product bug:**
  scenarios 10 and 11 failed with `429 Rate limit exceeded` — the script
  was making several `/upload`/`/verify/project` calls back-to-back
  under one API key, correctly tripping the real rate limiter
  (`_UPLOAD_RATE_LIMIT_BURST=3`, `_PROJECT_RATE_LIMIT_BURST=2`) that is
  already its own dedicated, separately-tested feature. Fixed by having
  the script clear the server's in-memory rate-limit buckets before each
  call (`reset_rate_limits()`) — this test is about scenario correctness,
  not re-proving the limiter.

- **One was a real, reproducible product bug, found live, not assumed:**
  scenario 2b (the ODrive TRUE claim) and the robotics leg of scenario
  3+5 both came back `undetermined` instead of `confirmed` — reproduced
  4/4 on a dedicated isolation run (ruled out as one-off model flakiness
  before assuming a fix was even needed). Root cause, traced by
  instrumenting the real pipeline call-by-call: `retrieval/extract.py`'s
  `propose()` correctly found and verified the real quote
  (`"* Peak current per motor: 120 Amps"`), but that quote is
  *deliberately kept short* (by design — see `extract.py`'s own system
  prompt) and, in ODrive's real document structure, the device/variant
  name ("ODrive v3.6 24V") only appears in a *preceding section
  heading*, not restated in the bullet line itself. `retrieval/stance.py`'s
  `judge_stance()` — which exists specifically to catch an unrelated
  entity sharing a similar name (its own docstring's ESP32/ESP32-S31
  case) — had no way to confirm the bare quote was even about an ODrive
  at all, and safely-but-wrongly returned `"unrelated"` for a claim that
  was actually true. This is a pre-existing limitation of the *shared*
  propose()/judge_stance() pipeline (also usable by `research_web.py`'s
  live mode 2 against any real page with the same heading-then-bullets
  structure), surfaced here because this stress test used a real-world
  document instead of the hand-curated corpus, which happens not to hit
  this pattern.

  **Fix, scoped narrowly:** `anticassiopeia/domains/robotics.py`'s BYOE
  call site now prefixes the text it shows `judge_stance()` with the
  real, already-known source filename (`f"[Source document:
  {filename}]\n{proposal.quote}"`) — real, already-available context,
  not fabricated. Verified live, 3/3, that this resolves the
  misjudgment; re-verified the original two Acme-X9 confirmations from
  Phase 1 still pass unchanged; full offline suite (296 tests) stayed
  green. Deliberately scoped to ONLY this one call site — neither
  `retrieval/stance.py`'s shared function/prompt nor `research_web.py`'s
  own already-live-tested call site were touched, to avoid risking a
  regression in a different, separately-proven domain for a fix found
  via robotics-specific testing. `research_web.py` likely has the same
  latent limitation against a similarly-structured real page; left as a
  known, named follow-up, not silently fixed by assumption.

## Honest scope notes

- This is a deliberate, hand-picked set of ~17 scenarios proving the
  scenario matrix works end to end with real documents, real licenses,
  and real live calls — it is NOT a large-scale statistical stress test
  like the original `stress_test/claims/manifest.jsonl` (3,383 claims).
  That distinction matters for what this report can and can't claim: it
  proves the v2 pipeline is correct on these real cases, not a dangerous-
  miss rate at scale.
- research_web's two live-search scenarios (1, 4) accept either
  `confirmed` or `undetermined` as passing — live web search result
  quality varies run to run by design (this is the same honest
  tolerance this project's own `tests/test_domains_research_web.py`
  live tests already use), never a wrong `contradicted` for a true
  claim.
