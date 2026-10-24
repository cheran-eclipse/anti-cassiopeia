# Robotics evidence seed, extracted from Eclipse: Constellation

Source repo: `eclipse-constellation` (read-only extraction, `main`/`slice2-base` working
tree as of 2026-10-17; paths below are repo-relative unless stated otherwise). Nothing
here is copied code — this is factual material and a retrieval-pattern description, to
seed `anticassiopeia/domains/robotics.py`'s `gather_evidence()`.

Format per part: **spec/rating**, **source + locator**, **claim it supports/contradicts**.
Every entry below is marked either sourced (with a locator precise enough to re-check by
hand) or explicitly unsourced — none are silently omitted.

---

## 1. BlueROV2 (platform / vehicle housing)

Constellation's own demo scope (`demos/subsea_rov/README.md:11-13`) states the test
condition: **operate at 500 m depth**, ambient water as low as ~2°C. Everything below is
checked against that 500 m figure.

### 1.1 Hull/housing maximum rated depth — two conflicting manufacturer revisions exist

| Field | DOC1 (2025 datasheet) | DOC2 (Rev 10/16, older) |
|---|---|---|
| Max rated depth, acrylic tube | **100 m** | **100 m** |
| Max rated depth, aluminum tube | **300 m** | *(no aluminum variant listed)* |
| Max tested depth | *(not given)* | 130 m |
| Max forward speed | 1.5 m/s | 1 m/s |
| Buoyancy-foam depth rating | 300 m (R-3318 urethane) | 210 m (R-3318 urethane) |

- Source: `evals/model-comparison/corpus/DOC1_BlueROV2_datasheet_2025.txt:18-19` (PERFORMANCE
  section: "Maximum Rated Depth (Acrylic): 100 m", "Maximum Rated Depth (Aluminum): 300 m"),
  line 10 (buoyancy foam "rated to 300 m").
- Source: `evals/model-comparison/corpus/DOC2_BlueROV2_datasheet_rev1016.txt:17,22-23` ("Maximum
  Rated Depth: 100 m", "Maximum Tested Depth (so far): 130 m", foam "rated to 210 m").
- Both corpus files are transcriptions Constellation's own eval team made from the vendor
  PDFs; provenance is recorded in `evals/model-comparison/SOURCES.md` (DOC1 =
  robotshop.com-hosted `bluerov2-datasheet.pdf`, dated April 2025; DOC2 =
  bluerobotics.com-hosted `br_bluerov2_datasheet_rev3-bleed-dragged.pdf`, Rev 10/16). The
  original PDFs are not committed to the repo (SOURCES.md: "so we don't redistribute vendor
  documents we don't own") — the locators above point at Constellation's transcribed copies,
  not the original PDF's own page numbers, which are not recorded anywhere in this repo.
- Constellation's own eval explicitly flags this as a **known cross-revision conflict**, not
  an extraction error: `evals/model-comparison/questions.json`, question **E2** ("What depth
  rating does each of DOC1 and DOC2 give for the buoyancy foam?" — expected answer "300 m vs
  210 m") and **E1** (forward speed, "1.5 m/s (2025) vs 1 m/s (Rev 10/16)"), with DOC1 marked
  as the newer document. `evals/model-comparison/METHOD.md:50-52` names this "Group E —
  conflicting sources."
- **Claim check — "BlueROV2 (standard housing) survives 500 m depth": CONTRADICTS.** Even
  the best-case figure across both revisions (aluminum tube, 300 m, DOC1 only) is 40% short
  of 500 m. The acrylic-tube rating (100 m, agreed by both revisions) fails far more
  severely. This is also the exact gap Constellation's own demo doc calls out as a known,
  unimplemented scope boundary: `demos/subsea_rov/README.md:23-30` — "A stock BlueROV2's
  extended-range housing is rated to 300 m, which would also need to be addressed for a
  genuine 500 m mission. The current pipeline does not check vehicle hull/housing rating
  against the stated condition."

### 1.2 Stock external pressure/depth sensor = Bar30 (cross-reference, not a separate rating)

- Source: `evals/model-comparison/corpus/DOC1_BlueROV2_datasheet_2025.txt:53` ("Pressure/Depth
  and Temperature Sensor (external): Blue Robotics Bar30"); also
  `DOC2_BlueROV2_datasheet_rev1016.txt:54` ("Blue Robotics Bar 30 Pressure/Depth & Temperature
  Sensor (external)"). This just confirms the Bar30 (section 2 below) is the part actually
  mounted on a stock BlueROV2 — it is not an independent depth-rating claim about the vehicle.

---

## 2. Bar30 (Blue Robotics "Bar30 High-Resolution 300 m Depth/Pressure Sensor")

**IMPORTANT — a sourced number below is a known-fake test value. Read before reusing.**

Constellation's corpus text for this part (`DOC3`) is *not* an unmodified copy of the real
datasheet. `evals/model-comparison/METHOD.md:59-73` (also mirrored at
`API_Testings/pack/CANARY_EDITS.md`) documents that Constellation's eval authors deliberately
altered exactly one Bar30-relevant number in the text every model/corpus reader sees, as a
"canary" to detect models answering from training memory instead of the given text:

| Field | Real PDF value | Value in `corpus/DOC3...txt` (altered) |
|---|---|---|
| Overpressure Pmax (chip absolute max rating) | **50 bar** | 45 bar |

`METHOD.md:69-73`, verbatim: *"The edited values are NOT real specifications — never cite
them outside this test."* So: `DOC3_Bar30_MS5837-30BA_chip_datasheet.txt:18` currently reads
"Overpressure Pmax (ISO 6425, note 1): max 45 bar" — **do not treat 45 bar as a real Bar30
spec.** The real figure, per Constellation's own documentation of its own test design, is
**50 bar**. I have not independently re-verified 50 bar against the live vendor PDF (not
redistributed in this repo) — it is Constellation's own stated ground truth for its canary,
not a value I re-derived.

Facts below use only the **non-canary** (confirmed unaltered) lines of DOC3:

- **Operating pressure range: 0 to 30 bar.** Source:
  `DOC3_Bar30_MS5837-30BA_chip_datasheet.txt:11` ("Operating range: 0 to 30 bar, -20 to +85 C")
  and line 33 ("Operating Pressure Range: 0 to 30 bar"). This line is not listed in the
  canary table, so it is unaltered real chip spec (TE Connectivity MS5837-30BA, REV C2
  12/2019 — header at line 1 of the same file, "pages 1-4 of 16").
- **Depth-equivalent conversion of that range: ≈296 m**, using Constellation's own stated
  conversion rule. Source: `evals/model-comparison/questions.json`, question **C1** — "Assume
  the sensor reads absolute pressure, surface pressure is 1.013 bar, and each 1 bar of gauge
  pressure equals 10.2 m of seawater depth. At the sensor's maximum operating pressure in
  DOC3, what depth in metres does it read?" with expected answer derived as
  `(30 - 1.013) * 10.2 ≈ 295.8 m`. Note: the sensor chip datasheet itself never states "300 m"
  or "296 m" in metres anywhere in its text (confirmed: no line in DOC3 contains "m" as a
  depth unit) — the "300 m" figure is Blue Robotics' own product name/rating for the
  Bar30 board built around this chip (visible in the vendor PDF's own filename, recorded at
  `evals/model-comparison/SOURCES.md`: `.../bar30-high-resolution-300m-depth-pressure-sensor-r2-datasheet.pdf`),
  not a verbatim quote inside the chip datasheet text Constellation holds. Under
  Constellation's own citation rule (a Cited claim's quote must appear character-for-character
  in the source — see `src/constellation/contracts.py`, `Claim` rule 1), "Bar30 is rated to
  300 m" could not be marked as a direct quote from DOC3; it is a standard pressure-to-depth
  conversion of a quote that is directly in DOC3 ("0 to 30 bar").
- **Claim check — "Bar30 survives 500 m depth": CONTRADICTS**, on the operating/guaranteed-
  accuracy range (≈296–300 m vs. 500 m required, a ~40% shortfall) — this is the "intended
  first-pass failure case" the demo scope deliberately set up
  (`demos/subsea_rov/README.md:19`: "rated to 300 m, so it fails a 500 m condition outright").
  On the absolute-max/burst rating (50 bar real, ≈500 m-equivalent by the same conversion),
  500 m sits almost exactly at the sensor's destructive limit rather than comfortably past
  it — worth carrying as a nuance (operating failure is certain; physical destruction at
  exactly 500 m is a closer call), but this nuance rests on the real-PDF canary value, which
  this session did not independently re-verify.

---

## 3. Bar100XT (Blue Robotics) — revision target

**No datasheet text, locator, or corpus entry exists anywhere in the Constellation repo for
this part.** I searched the full tree (including the duplicated historical `constellation_slice1/`
and `constellation_slice2/` snapshots and the private `API_Testings/` folder) for "Bar100",
"bar-100", and related strings — the only hits are the same single narrative table, repeated
verbatim across those duplicated snapshots.

- The only mention anywhere: `demos/subsea_rov/README.md:20` (table row): *"Bar100XT | Blue
  Robotics | Rated to 1000 m; same manufacturer and ecosystem as the Bar30, with confirmed
  ArduSub/BlueROV2 compatibility, making it a realistic 'revise' recommendation rather than a
  speculative swap."*
- This is a **planning/scope narrative**, not an ingested or verified datasheet fact. The
  same file states outright (line 34): *"Demo scope defined; no retrieval, synthesis, or
  scoring logic is implemented yet."* Constellation never actually retrieved, chunked, or
  cited a Bar100XT datasheet — the 1000 m figure and the ArduSub-compatibility claim are
  asserted by the demo's author, with no page/section/table locator, no corpus file, and no
  independent verification step behind them anywhere in this codebase.
- **Status for Anti-Cassiopeia: UNSOURCED.** Treat "Bar100XT rated to 1000 m" and "Bar100XT is
  ArduSub/BlueROV2-compatible" as hypotheses to re-verify against a real Blue Robotics
  datasheet or product page — not as confirmed evidence. Do not cite `demos/subsea_rov/README.md`
  as if it were a datasheet locator; it is Constellation's own planning doc, one level removed
  from a primary source.

**RESOLVED this session (2026-10-24):** fetched Blue Robotics' real, live BarXT product page —
https://bluerobotics.com/?p=219055 ("BarXT Extended Submersion Depth/Pressure Sensors"). No
separate PDF datasheet is linked from it; the page itself is the manufacturer's spec sheet for
this part. Bar100XT's real, stated figures: **Operating Pressure Range: 0 to 100 bar**
(dropdown and spec table agree), **Operating Depth: 0-1009 m** (spec table) / **~1000 m**
(summary table — the page states both; the spec table's 1009 m assumes freshwater density per
its own footnote 2, this project's conversion uses seawater per `robotics.py`'s existing
convention, giving ~995 m — all three numbers describe the SAME real rating, not a
discrepancy). A SEPARATE figure, **Maximum Mechanical Pressure: 400 bar**, is explicitly stated
by the page's own footnote 1 as "the highest pressure the sensor can withstand before
sustaining permanent damage" — a destructive limit, not an operating rating, and deliberately
EXCLUDED from `anticassiopeia/corpus/doc4_bar100xt_excerpt.txt` for exactly the reason Bar30's
own excerpt excludes its destructive-adjacent figure (see §2 above): citing it as if it were a
"rated" value would reintroduce the rated-vs-survives conflation this project's own fix
addresses. The page also states plainly: "The BarXT sensor is not fully waterproof. The front
side is sealed... but the back side... is not sealed." — not itself a depth-rating fact, but
worth recording since it's real, stated, and easy to otherwise overclaim. Now sourced in
`_SOURCES`/`_RETRIEVAL_QUERIES` as `DOC4_Bar100XT`, same trust tier (0.85) as Bar30's chip
datasheet.

---

## 4. QuSpin QZFM Gen-3 (zero-field optically-pumped quantum magnetometer)

**Same situation as Bar100XT — no datasheet text or locator exists in the repo.** Same
search scope as above (including duplicated slices and `API_Testings/`); only one hit.

- The only mention anywhere: `demos/subsea_rov/README.md:21` (table row): *"QZFM Gen-3
  zero-field optically-pumped magnetometer | QuSpin | A real, commercially available quantum
  sensor (spin-exchange relaxation-free magnetometry) with a public datasheet stating an
  operating temperature range and no pressure/submersion rating. Scoring it against the
  stated condition produces an honest fail with a clear, citable reason, demonstrating that
  Grounded mode applies the same rigor to a frontier sensing technology as to a standard
  part."*
- As with Bar100XT: this is narrative description of what a future retrieval step *would*
  find ("a public datasheet stating..."), not a datasheet Constellation actually ingested.
  No operating-temperature figures, no explicit "no pressure rating" quote, and no
  page/section/table locator exist anywhere in this repo.
- **Status for Anti-Cassiopeia: UNSOURCED.** The underlying claim — a QZFM Gen-3 has no
  pressure/submersion rating stated by QuSpin, hence no basis to confirm survival at any
  depth — is plausible and matches how QuSpin markets this sensor (lab/clinical-environment,
  zero-field magnetometry) in general knowledge outside this repo, but nothing in
  Constellation itself backs it with a checkable locator. Needs a real QuSpin datasheet
  pulled before `gather_evidence()` can cite it as evidence rather than assumption.

**RESOLVED this session (2026-10-24), but NOT the way the hypothesis above expected:**
fetched QuSpin's real, live official product page — https://quspin.com/qzfm-gen-3. It is a
blog post ("Home / Blog / QZFM Gen-3", dated June 20, 2021), not a formal datasheet, and no
PDF datasheet or spec sheet is linked from it anywhere. The WHOLE page was read, specifically
checking for any pressure/depth/submersion/waterproof/sealed/IP-rating wording — **there is
none.** It states sensitivity figures only ("7-12 fT/√Hz in single-axis mode... 10-15 fT/√Hz
in dual-axis mode" for the dual-axis variant) and nothing else relevant. So the hypothesis
above ("a QZFM Gen-3 has no pressure/submersion rating stated by QuSpin") is now CONFIRMED
true, by a real, citable, checked source — but it is still not a NUMBER `robotics.py` can
compare a claimed depth against; there is nothing to compare. This means a "QuSpin survives/
fails N m" claim correctly stays UNDETERMINED for any N, same outcome as before this session,
but for a different, now fully-sourced reason: `describe_gap()` cites the real page and date
instead of saying a datasheet still needs to be pulled. No corpus file was added for QuSpin
(there is no numeric fact to route through the retrieve→propose→verify pipeline) — the fix
lives entirely in `RoboticsAdapter.describe_gap()`'s QuSpin branch.

---

## 5. The retrieval/grounding pattern (for designing `gather_evidence()`)

This describes the *approach* Constellation uses to turn an unchunked document into a
claim it will actually stand behind — not code to port in; Anti-Cassiopeia's engine and
`Evidence`/`Claim` contract are already fixed and shaped differently.

**Two layers exist in Constellation, at two different levels of "real":**

- `src/constellation/pipeline.py` is a **pure interface skeleton** (every function raises
  `NotImplementedError`) describing the intended four stages narratively: `retrieve()` must
  return only real, citable sources and never fabricate one; `synthesize()` must have every
  recommendation cite back to a specific retrieved source, and when revising after a failure
  must address the specific failures recorded from the prior iteration; `score()` must compare
  a cited specification against a stated condition per component-condition pair and must
  never assume a pass in the absence of a source that supports it; `iterate()` loops
  retrieve→synthesize→score→revise up to a max count, feeding each failure back into the next
  synthesis call. This file predates any real implementation and nothing in it was ever
  wired up — but the *rules* it states (always cite, never fabricate a source, never default
  to pass) are the actual design intent worth carrying over.
- The **real, working, tested implementation** of that same shape lives elsewhere and
  actually runs (`src/constellation/demo_slice1.py` exercises the whole thing end to end).
  Its approach, in order:
  1. **Ingest with exact offsets.** A document is split into chunks, each chunk carrying an
     id and the exact character span (`start`/`end`, plus page number when paginated) it came
     from in the source text, so every later citation can point at one specific, re-checkable
     span rather than "the document" in general.
  2. **Retrieve by hybrid search, and say so when it degrades.** A question about one specific
     field ("thruster maximum thrust", "Bar30 depth rating") is run through both a keyword
     index (BM25) and a vector-embedding index, fused by reciprocal rank fusion, returning a
     small ranked set of candidate chunks. If embeddings aren't available, it falls back to
     BM25-only and records that fact in the result rather than silently pretending it used
     both.
  3. **Let the model propose, never let it decide.** The model is shown *only* the retrieved
     chunks (never the whole document) and asked to produce exactly one structured proposal:
     a value, a unit, which chunk it came from, and the exact verbatim words it copied — plus,
     for this kind of fact, whether the quoted number is a rating/maximum ("rated") or a
     measured/tested result ("tested"). The model is explicitly told the passages are
     untrusted data and to say "not found" rather than guess if the value isn't stated.
  4. **Verify independently before trusting anything.** Code — not the model — then re-checks
     the proposal from scratch: does the quoted text appear character-for-character (modulo
     whitespace) inside the exact chunk the model named; does the stated unit parse and match
     the expected physical dimension; is a "rated" value being misreported as "tested" or vice
     versa. Any failure produces a specific, named rejection reason (e.g. "quote not found in
     that chunk", "unit is a different dimension") rather than a generic reject. Nothing
     becomes a trusted fact until it passes this step — the model's output up to here is only
     ever a proposal.
  5. **Disagreement is a signal, not noise.** For facts that matter to a hard decision, a
     second, independent extraction pass can be run over the same evidence; if it disagrees
     with the first reading, the fact is marked "contested" rather than either reading being
     silently preferred.
  6. **A missing fact is its own outcome, not a default.** When no evidence supports a field
     at all, that is recorded explicitly as a gap with a reason (not stated in the source vs.
     extraction failed vs. rejected by verification) — never silently treated as a pass or a
     fail.
  7. **Comparing a verified fact against a stated requirement is a three-way (really
     four-way) classification, not a boolean.** Once a fact has a verified value (optionally a
     low/high range, when the source itself states a tolerance), it's checked against a
     numeric threshold with an explicit comparator: the value's whole range clears the
     threshold (pass), none of it does (fail), or it straddles the boundary (marginal) — and a
     fact with no verified value at all is its own fourth, explicit "unknown" outcome, folded
     in with "marginal" for ranking purposes but never silently counted as a pass.

The throughline most relevant to `gather_evidence()`: a piece of evidence is only worth
returning if it carries a *specific, re-checkable locator* back to the exact place the value
came from, and the code path that decides whether to trust it is kept separate from (and
independent of) whatever proposed it in the first place. That maps directly onto
`Evidence.locator` plus keeping `stance` assignment inside the domain adapter, decided from
source text actually inspected — never defaulted to "supports" for lack of a reason to doubt
it.

---

## Summary of what's usable right now

| Part | Sourced facts with a locator? | Usable in `gather_evidence()` today? |
|---|---|---|
| BlueROV2 housing | Yes — two conflicting manufacturer revisions, both located | Yes, with the DOC1-vs-DOC2 conflict carried through rather than resolved silently |
| Bar30 | Yes, with one flagged fake (canary) value excluded | Yes, for the operating-range fact; absolute-max fact flagged as not independently re-verified |
| Bar100XT | **Yes, as of 2026-10-24** — Blue Robotics' real official BarXT page | **Yes** — DOC4_Bar100XT, same pipeline as Bar30 |
| QuSpin QZFM Gen-3 | **Yes, as of 2026-10-24** — but the real source states NO rating at all | No numeric comparison possible (nothing to compare) — but the UNDETERMINED gap is now a cited, checked fact, not an assumption |
