# Anti-Cassiopeia v2 master build prompt

This is the actual handoff prompt the v2 "bring your own evidence" build
(upload, robotics BYOE, `/verify/project`, frontend rebuild) was built
from, kept verbatim so code comments that cite it (e.g.
`anticassiopeia/api/upload_store.py`, `anticassiopeia/api/server.py`)
resolve to something real instead of a dangling reference. See
`docs/ARCHITECTURE.md`'s "v2: 'bring your own evidence'" section for
what was actually built against this prompt, phase by phase, including
what was deliberately NOT done and why.

---

You are continuing work on `anti-cassiopeia` (repo: `cheran-eclipse/anti-cassiopeia`), a domain-agnostic fact-verification engine built for the Nebius x NVIDIA Global AI Hackathon. Read `README.md`, `docs/ARCHITECTURE.md`, and `docs/DESIGN.md` first for full context on the existing system before changing anything.

### What already exists and works (don't rebuild)

Four domain adapters behind one `VerificationEngine`/`Verdict` contract: `robotics` (datasheet retrieval, runs on Nemotron Ultra — see `stress_test/results/NEMOTRON_PIVOT_REPORT.md` for why), `ml_data` (re-computes real CSV stats), `fpga_embedded` (parses real Vivado timing reports + CMSIS-SVD register maps), `research_web` (live Tavily/Wikipedia search + verify, runs on gpt-oss-120b). Full retrieve→propose→verify pipeline in `anticassiopeia/retrieval/`. Security hardening already done: SSRF guard with DNS-rebinding protection, path traversal protection (`_path_safety.py`), API key auth + rate limiting in `api/server.py`. Deployed to Cloud Run, frontend at `docs/index.html` (GitHub Pages).

### Partial progress already landed THIS session — verify and continue from here, don't redo

- `anticassiopeia/retrieval/document_ingest.py` — new module, `extract_text(raw_bytes, filename) -> str`, dispatches by extension: `.txt/.md/.csv/.rpt/.svd/.xml` as UTF-8, `.pdf` via `pypdf`, `.docx` via `python-docx`. Raises `DocumentIngestError` (never silent empty string) on unsupported extension or no extractable text (e.g. scanned PDF with no text layer — OCR explicitly out of scope).
- `anticassiopeia/api/upload_store.py` — new module, thread-safe in-memory `UploadStore` keyed by opaque `document_id` (`secrets.token_urlsafe`), 24h TTL, capped+evicted same discipline as `server.py`'s existing rate-limit buckets.
- `anticassiopeia/api/server.py` — `POST /upload` endpoint added (multipart, same `X-API-Key` auth as `/verify`, its OWN separate rate limit bucket, 10 MiB size cap enforced by reading past the limit rather than trusting `Content-Length`, extension allowlist, returns `{document_id, filename, size_bytes}`).
- `anticassiopeia/retrieval/__init__.py` updated to export `extract_text`/`DocumentIngestError`.
- **NOT YET DONE, and NOT YET TESTED AT ALL** (this is where to pick up): `pyproject.toml` doesn't yet declare `pypdf`/`python-docx`/`python-multipart` as real dependencies (they happened to be present in the build sandbox — must be added explicitly or the deploy will break). No tests written for any of the above. `robotics.py` has NOT been wired to accept `document_id`/`document_text` yet — the upload endpoint exists but nothing consumes its output yet. Verify all of the above actually imports and runs before building further on it.

### What to build, in order

**Phase 1 (finish this first):**
1. Add `pypdf`, `python-docx`, `python-multipart` to `pyproject.toml` dependencies for real.
2. Write offline tests for `document_ingest.py` (fake bytes per format, including a malformed-PDF case and a no-text-layer case) and `upload_store.py` (TTL expiry, cap eviction) — follow this project's existing test conventions (`tests/test_domains_robotics.py` etc. for style).
3. Wire `robotics.py`: `Claim.context` gains `document_id` (resolved to text via `UploadStore`, resolution happens in `server.py`'s `/verify` handler — inject resolved text into `context["document_text"]` before constructing the `Claim`, so `robotics.py` itself only ever deals with plain text, never needs to import the upload store directly — keeps domain/api layering clean) or `document_text` directly. When either is present: build a ONE-OFF `BM25Index` over `chunk_document()` of that text and run the existing `propose()`→`verify_proposal()` pipeline against it INSTEAD of the fixed `_SOURCES` corpus. IMPORTANT DESIGN NOTE: the existing `robotics.py` pipeline is narrowly built around depth-rating claims (regex-based `_parse_condition`, bar→metre conversion). A real uploaded document could be about ANYTHING — for the BYOE path, do NOT force the claim through that depth-specific parser. Instead, for BYOE mode, ask `propose()` the claim text directly as the retrieval query/question, verify the returned quote, then judge supports/contradicts/unrelated the same way `research_web.py`'s `_judge_stance()` already does (consider extracting that function + its system prompt into a shared `retrieval/stance.py` module so both `robotics.py` and `research_web.py` import one implementation instead of duplicating it — cleaner than copy-pasting).
4. When `document_id`/`document_text` is ABSENT: `robotics.py` falls back to today's fixed-corpus behavior exactly, no regression.
5. Offline-test the full BYOE path with a fake client (same DI pattern `RoboticsAdapter(client=...)` already supports) before any live call.
6. Budget: user has a hard $20 Nebius spend cap (balance was $49 as of 2026-10-25). Reserve real live-LLM calls for a small number of deliberate end-to-end confirmations, not the default test loop.

**Phase 2:** `POST /verify/project` — accepts multiple `document_id`s, auto-detects which domain each belongs to (deterministic sniffing — SVD root tag for `fpga_embedded`, CSV header row for `ml_data`, otherwise robotics' BYOE path — never ask an LLM to guess what code can determine), runs real checks per domain, rolls up via `core/compound.py`'s EXISTING AND-semantics `rollup()` (generalize `decompose_claim()`'s domain restriction to include `ml_data`/`fpga_embedded` now that a real uploaded path exists instead of one needing to be invented). Response carries both full per-domain `Verdict`s and one rolled-up project status.

**Phase 3: frontend rebuild — READ THIS DESIGN SECTION CAREFULLY, it corrects a prior wrong attempt**

The current `docs/index.html` is a dark-terminal aesthetic: monospace font, purple/violet accent color, `$`/`>` prompt-style text, pill-shaped command chips. **This was explicitly rejected by the user as the wrong direction.** The reference the user wants instead is the Nebius Token Factory dashboard's own look:

- Clean sans-serif typography throughout, NOT monospace/terminal-style.
- Dark background (near-black / dark navy), but the UI reads as a modern SaaS dashboard, not a hacker terminal.
- Card-based, grid-organized panels with visible rounded borders/subtle separation — e.g. a 2-3 column card grid for things like model/option selection, each card self-contained with its own header, stats row, and action button.
- Bright accent colors used SPARINGLY as highlights against the dark background — lime/neon green and cyan specifically (matching Nebius's own brand accent), used for: primary action buttons, "New"/status badges (small pill-shaped tags in a corner of a card), active-state indicators, and key numeric stats (pricing figures, token rates) — not washing the whole UI in one color the way the current purple terminal theme does.
- Left sidebar nav pattern is a fine reference for IF this app grows multiple views, but is not mandatory — the main visual DNA to copy is the CARD GRID + sparse neon accents + clean typography, not necessarily the exact sidebar layout.
- Small metadata rows inside cards (e.g. "1M Input $0.15 / 1M Cached $0.015 / 1M Output $0.60" shown as a compact 3-up stat row) are a good pattern to borrow for showing per-domain or per-document stats compactly.
- Badges/pills for tags (region, status, "Vision"/"Text-to-text" capability tags) are a good pattern for showing which domains a document was routed to, or a document's detected type.

Apply this to the Phase 3 panel flow (Upload → Scan → Verify → Connected summary, from the earlier spec) — each panel should read as a card-grid section in this visual language, not a single scrolling terminal-style form. Build it as a single dependency-free static HTML+JS file still (no new build step/framework — matches this project's existing GitHub Pages convention), `localStorage` for API key/base URL exactly as today, but the CSS needs a full rewrite to match this direction, not a patch on top of the current theme.

**Phase 4:** README/title rewrite — only after Phases 1-3 are real and working, so docs describe what's actually shipped.

### Non-goals (explicitly out of scope for this build)

- Scenario "find a better datasheet/approach via research comparison" — backlog, not this build.
- OCR for scanned/image-only PDFs — text-layer extraction only.
- Any new frontend framework or build step.

### Full scenario matrix this build satisfies (for context on WHY each piece exists)

| # | Persona | Has | System behavior |
|---|---|---|---|
| 1 | PCB/robotics designer, early | Framework/design, no datasheet yet | research_web mode: live search assesses feasibility |
| 2 | Same, with datasheet(s) | Design + uploaded datasheet | robotics BYOE: verify against the UPLOADED doc |
| 3 | Same, wants improvement | Design + datasheet + FPGA/ML component | fpga_embedded/ml_data real parsing on uploaded report/dataset; "find something better" deferred |
| 4 | Researcher/hackathon participant | Papers/data only | research_web mode 2, as-is |
| 5 | Same, needs more | Multi-domain bundle | Project orchestration: auto-detect domains, run all, roll up |
| 6 | FPGA/ML designer, real benchmarks | Real Vivado report / SVD / CSV | Already works — pure upload-flow problem |
| 7 | No document at all | Just a claim in words | Falls back to today's behavior exactly |
| 8 | Malformed/corrupt upload | Unparseable file | Named, specific gap, never a crash |
| 9 | Upload too large | Over size cap | Rejected before parsing, clean 4xx |
| 10 | Bundle with no domain match | Nothing routable | Honest "nothing checkable yet," never fabricated |
| 11 | PDF with no text layer | Scanned image PDF | Named "no extractable text" gap, no OCR attempted |

## Decision log (why things are the way they are above)

1. Upload shape: BOTH a real `/upload` endpoint AND inline `document_text` — real app needs real file upload, inline text keeps the simple case fast.
2. Uploaded robotics document REPLACES the fixed corpus for that request; fixed corpus stays reachable as an explicit "try the demo" option.
3. Project rollup shows BOTH full per-domain verdicts and one rolled-up status, reusing `compound.py`'s existing AND-semantics.
4. File types: text formats + PDF (pypdf) + DOCX (python-docx), both confirmed available and added as real dependencies. OCR explicitly out.
5. Frontend direction corrected 2026-10-25: Nebius-dashboard card-grid + neon-accent aesthetic, NOT the current purple terminal theme — see Phase 3 section above for the full detail, this correction came from the user directly rejecting the first frontend attempt by screenshot comparison.
