# Robotics evidence seed, extracted from Eclipse: Constellation

Source repo: `eclipse-constellation` (read-only extraction, `main` / `slice2-base`
working tree as of 2026-10-17; paths below are repo-relative unless stated
otherwise). Nothing here is copied code. It is factual material and a
description of a retrieval pattern, used to seed the `substrate` domain's
evidence (written when the domain was named `robotics`; `robotics.py` is now
`substrate.py`).

Each entry gives the **spec or rating**, the **source and locator**, and the
**claim it supports or contradicts**. Every entry is marked sourced (with a
locator precise enough to re-check by hand) or unsourced.

---

## 1. BlueROV2 (platform / vehicle housing)

Constellation's demo scope (`demos/subsea_rov/README.md:11-13`) states the
test condition: **operate at 500 m depth**, ambient water as cold as about
2 °C. Everything below is checked against 500 m.

### 1.1 Hull and housing maximum rated depth: two conflicting manufacturer revisions

| Field | DOC1 (2025 datasheet) | DOC2 (Rev 10/16, older) |
|---|---|---|
| Max rated depth, acrylic tube | **100 m** | **100 m** |
| Max rated depth, aluminum tube | **300 m** | (no aluminum variant listed) |
| Max tested depth | (not given) | 130 m |
| Max forward speed | 1.5 m/s | 1 m/s |
| Buoyancy-foam depth rating | 300 m (R-3318 urethane) | 210 m (R-3318 urethane) |

- DOC1: `evals/model-comparison/corpus/DOC1_BlueROV2_datasheet_2025.txt:18-19`
  (PERFORMANCE section: "Maximum Rated Depth (Acrylic): 100 m", "Maximum Rated
  Depth (Aluminum): 300 m"); line 10 (buoyancy foam "rated to 300 m").
- DOC2: `evals/model-comparison/corpus/DOC2_BlueROV2_datasheet_rev1016.txt:17,22-23`
  ("Maximum Rated Depth: 100 m", "Maximum Tested Depth (so far): 130 m", foam
  "rated to 210 m").
- Both corpus files are transcriptions that Constellation's eval team made from
  the vendor PDFs. Their provenance is in `evals/model-comparison/SOURCES.md`:
  DOC1 is the robotshop.com-hosted `bluerov2-datasheet.pdf` (April 2025), and
  DOC2 is the bluerobotics.com-hosted
  `br_bluerov2_datasheet_rev3-bleed-dragged.pdf` (Rev 10/16). The original
  PDFs are not committed ("so we don't redistribute vendor documents we don't
  own"), so the locators point at the transcribed copies, not at the PDFs'
  page numbers, which the repo doesn't record.
- Constellation's eval flags this as a **known cross-revision conflict**, not
  an extraction error: `evals/model-comparison/questions.json` question **E2**
  (foam depth rating in each document, expected "300 m vs 210 m") and **E1**
  (forward speed, "1.5 m/s (2025) vs 1 m/s (Rev 10/16)"), with DOC1 marked
  newer. `evals/model-comparison/METHOD.md:50-52` calls this "Group E:
  conflicting sources."
- **Claim check, "BlueROV2 (standard housing) survives 500 m depth":
  CONTRADICTS.** The best figure across both revisions (aluminum tube, 300 m,
  DOC1 only) is 40% short of 500 m. The acrylic rating (100 m, agreed by
  both) fails by far more. Constellation's demo doc names this as a known,
  unimplemented scope boundary (`demos/subsea_rov/README.md:23-30`): "A stock
  BlueROV2's extended-range housing is rated to 300 m, which would also need
  to be addressed for a genuine 500 m mission. The current pipeline does not
  check vehicle hull/housing rating against the stated condition."

### 1.2 Stock external pressure and depth sensor is the Bar30 (cross-reference)

- `DOC1_BlueROV2_datasheet_2025.txt:53` ("Pressure/Depth and Temperature
  Sensor (external): Blue Robotics Bar30") and
  `DOC2_BlueROV2_datasheet_rev1016.txt:54` ("Blue Robotics Bar 30
  Pressure/Depth & Temperature Sensor (external)"). This confirms the Bar30
  (section 2) is the part on a stock BlueROV2. It is not a separate depth
  rating for the vehicle.

---

## 2. Bar30 (Blue Robotics "Bar30 High-Resolution 300 m Depth/Pressure Sensor")

**A sourced number below is a known-fake test value. Read this before reusing
the corpus.**

Constellation's corpus text for this part (`DOC3`) is not an unmodified copy
of the datasheet. `evals/model-comparison/METHOD.md:59-73` (mirrored at
`API_Testings/pack/CANARY_EDITS.md`) documents that Constellation's eval
authors altered one Bar30-relevant number in the text every model reads, as a
"canary" to detect models answering from training memory:

| Field | Real PDF value | Value in `corpus/DOC3...txt` (altered) |
|---|---|---|
| Overpressure Pmax (chip absolute max rating) | **50 bar** | 45 bar |

`METHOD.md:69-73`, verbatim: *"The edited values are NOT real specifications
— never cite them outside this test."* So
`DOC3_Bar30_MS5837-30BA_chip_datasheet.txt:18` reads "Overpressure Pmax (ISO
6425, note 1): max 45 bar", and **45 bar is not a real Bar30 spec.** The
real figure, per Constellation's documentation of its own test, is **50
bar**. That 50 bar was not re-verified against the vendor PDF (not
redistributed in the repo); it is Constellation's stated ground truth for the
canary.

Facts below use only the non-canary (unaltered) lines of DOC3:

- **Operating pressure range: 0 to 30 bar.**
  `DOC3_Bar30_MS5837-30BA_chip_datasheet.txt:11` ("Operating range: 0 to 30
  bar, -20 to +85 C") and line 33 ("Operating Pressure Range: 0 to 30 bar").
  This line is not in the canary table, so it is the unaltered chip spec (TE
  Connectivity MS5837-30BA, REV C2 12/2019; header at line 1 of the same file,
  "pages 1-4 of 16").
- **Depth-equivalent of that range: about 296 m**, using Constellation's
  conversion rule from `evals/model-comparison/questions.json` question **C1**:
  "Assume the sensor reads absolute pressure, surface pressure is 1.013 bar,
  and each 1 bar of gauge pressure equals 10.2 m of seawater depth. At the
  sensor's maximum operating pressure in DOC3, what depth in metres does it
  read?" The expected answer is `(30 - 1.013) * 10.2 ≈ 295.8 m`. The chip
  datasheet never states "300 m" or "296 m" as a depth (no line in DOC3 uses
  "m" as a depth unit). "300 m" is Blue Robotics' name for the Bar30 board
  built around the chip (visible in the vendor PDF's filename, recorded in
  `evals/model-comparison/SOURCES.md`:
  `.../bar30-high-resolution-300m-depth-pressure-sensor-r2-datasheet.pdf`),
  and is not a quote inside the chip datasheet text Constellation holds. By
  Constellation's citation rule (a Cited claim's quote must appear
  character for character in the source; `src/constellation/contracts.py`,
  `Claim` rule 1), "Bar30 is rated to 300 m" can't be marked as a direct quote
  from DOC3. It is a pressure-to-depth conversion of a quote that is in DOC3
  ("0 to 30 bar").
- **Claim check, "Bar30 survives 500 m depth": CONTRADICTS**, on the
  operating range (about 296 to 300 m against 500 m required, a shortfall of
  about 40%). This is the "intended first-pass failure case" of the demo
  scope (`demos/subsea_rov/README.md:19`: "rated to 300 m, so it fails a 500 m
  condition outright"). On the absolute-max rating (50 bar real, about 500 m
  by the same conversion), 500 m sits almost exactly at the sensor's
  destructive limit. Operating failure is certain; physical destruction at
  exactly 500 m is closer. That nuance rests on the real-PDF canary value,
  which was not independently re-verified.

---

## 3. Bar100XT (Blue Robotics): revision target

**Constellation holds no datasheet text, locator or corpus entry for this
part.** A search of the full tree (including the duplicated
`constellation_slice1/` and `constellation_slice2/` snapshots and the private
`API_Testings/` folder) for "Bar100", "bar-100" and related strings found one
narrative table, repeated across the duplicated snapshots.

- The only mention: `demos/subsea_rov/README.md:20` (table row): *"Bar100XT |
  Blue Robotics | Rated to 1000 m; same manufacturer and ecosystem as the
  Bar30, with confirmed ArduSub/BlueROV2 compatibility, making it a realistic
  'revise' recommendation rather than a speculative swap."*
- This is a planning narrative, not an ingested datasheet fact. The same file
  says (line 34): *"Demo scope defined; no retrieval, synthesis, or scoring
  logic is implemented yet."* Constellation never retrieved, chunked or cited
  a Bar100XT datasheet. The 1000 m figure and the ArduSub-compatibility claim
  come from the demo's author, with no page, section or table locator, no
  corpus file and no verification step.
- **Status in this project at extraction time: UNSOURCED.** "Bar100XT rated to
  1000 m" and "Bar100XT is ArduSub/BlueROV2-compatible" were hypotheses to
  check against a Blue Robotics datasheet or product page. `demos/subsea_rov/README.md`
  is Constellation's planning doc, one step removed from a primary source, and
  is not a datasheet locator.

**Resolved (2026-10-24).** Blue Robotics' BarXT product page,
https://bluerobotics.com/?p=219055 ("BarXT Extended Submersion Depth/Pressure
Sensors"), has no separate PDF; the page is the manufacturer's spec sheet. It
states for the Bar100XT **Operating Pressure Range: 0 to 100 bar** (dropdown
and spec table agree) and **Operating Depth: 0-1009 m** (spec table) or
**about 1000 m** (summary table). The 1009 m figure assumes freshwater density
per the page's footnote 2. This project's conversion uses seawater, as
`robotics.py` did, giving about 995 m. All three describe the same rating.

A separate figure, **Maximum Mechanical Pressure: 400 bar**, is described by
the page's footnote 1 as "the highest pressure the sensor can withstand before
sustaining permanent damage". That is a destructive limit, not an operating
rating, and is excluded from `anticassiopeia/corpus/doc4_bar100xt_excerpt.txt`
for the reason Bar30's excerpt excludes its destructive-adjacent figure
(section 2): citing it as a "rated" value would bring back the
rated-versus-survives conflation. The page also states "The BarXT sensor is
not fully waterproof. The front side is sealed... but the back side... is not
sealed." This isn't a depth rating, but it is stated and easy to overclaim.
The part is sourced in `_SOURCES` / `_RETRIEVAL_QUERIES` as `DOC4_Bar100XT`,
at trust 0.85, the same as Bar30's chip datasheet.

---

## 4. QuSpin QZFM Gen-3 (zero-field optically pumped quantum magnetometer)

**Same situation as Bar100XT at extraction: no datasheet text or locator in
the repo.** Same search scope; one hit.

- The only mention: `demos/subsea_rov/README.md:21` (table row): *"QZFM Gen-3
  zero-field optically-pumped magnetometer | QuSpin | A real, commercially
  available quantum sensor (spin-exchange relaxation-free magnetometry) with a
  public datasheet stating an operating temperature range and no
  pressure/submersion rating. Scoring it against the stated condition produces
  an honest fail with a clear, citable reason, demonstrating that Grounded mode
  applies the same rigor to a frontier sensing technology as to a standard
  part."*
- As with Bar100XT, this describes what a future retrieval step would find
  ("a public datasheet stating..."), not a datasheet Constellation ingested.
  No operating-temperature figures, no explicit "no pressure rating" quote and
  no locator exist in the repo.
- **Status at extraction time: UNSOURCED.** The underlying claim (QuSpin
  states no pressure or submersion rating for a QZFM Gen-3, so there is no
  basis to confirm survival at any depth) is plausible and fits how QuSpin
  markets the sensor (lab and clinical environments, zero-field
  magnetometry), but nothing in Constellation backs it with a checkable
  locator.

**Resolved (2026-10-24), but not as the hypothesis expected.** QuSpin's
official product page, https://quspin.com/qzfm-gen-3, is a blog post ("Home /
Blog / QZFM Gen-3", dated June 20, 2021), not a datasheet, and links no PDF
datasheet or spec sheet. The whole page was read for any pressure, depth,
submersion, waterproof, sealed or IP-rating wording. **There is none.** It
states sensitivity figures only ("7-12 fT/√Hz in single-axis mode... 10-15
fT/√Hz in dual-axis mode" for the dual-axis variant). So the hypothesis that
QuSpin states no pressure or submersion rating for a QZFM Gen-3 is confirmed
by a checked source, but it gives no number to compare a depth against. A
"QuSpin survives or fails N m" claim stays UNDETERMINED for any N, as before,
but now for a sourced reason: `describe_gap()` cites the page and date instead
of saying a datasheet still has to be pulled. No corpus file was added (there
is no numeric fact to route through retrieve, propose and verify); the change
lives in the QuSpin branch of the adapter's `describe_gap()`.

**Grounding strengthened (external review, 2026-10-24).** The finding above
rested on one page's silence. Three more QuSpin-hosted pages were checked:
the product page (`https://quspin.com/products-qzfm/`), the mechanical
dimensions page (`https://quspin.com/qzfm-dimensions/`) and the quick-start
guide (`https://quspin.com/products-qzfm/qzfm-quick-start-guide/`). None
states a pressure, depth, submersion, waterproof or IP rating, and the
product page describes the device as "designed for magnetically shielded or
actively field-controlled environments — not direct operation in Earth's
magnetic field." A fifth candidate, an HSE University page mirroring QuSpin's
specs, was checked and excluded as corroboration, because it states that its
text is copied verbatim from QuSpin and so is not an independent source.

---

## 5. The retrieval and grounding pattern

This is the approach Constellation uses to turn an unchunked document into a
claim it will stand behind. It is not code to port: this project's engine and
`Evidence` / `Claim` contract are already fixed and shaped differently.

**Two layers exist in Constellation.**

- `src/constellation/pipeline.py` is an interface skeleton: every function
  raises `NotImplementedError`. It describes four intended stages.
  `retrieve()` returns only citable sources and never fabricates one.
  `synthesize()` has every recommendation cite a retrieved source and, when
  revising after a failure, address the specific failures from the prior
  iteration. `score()` compares a cited specification against a stated
  condition for each component and condition pair, and never assumes a pass
  without a supporting source. `iterate()` loops retrieve, synthesize, score
  and revise up to a maximum count, feeding each failure into the next
  synthesis call. The file predates any implementation and was never wired up,
  but its rules (always cite, never fabricate a source, never default to pass)
  are the design intent worth keeping.
- The working, tested implementation of the same shape lives elsewhere
  (`src/constellation/demo_slice1.py` runs it end to end). In order:
  1. **Ingest with exact offsets.** A document is split into chunks, each with
     an id and the exact character span (`start`/`end`, plus page number when
     paginated) it came from, so every later citation points at one
     re-checkable span.
  2. **Retrieve by hybrid search, and record any degradation.** A question
     about one field ("thruster maximum thrust", "Bar30 depth rating") is run
     through a BM25 index and a vector-embedding index, fused by reciprocal
     rank fusion, giving a small ranked set of candidate chunks. If embeddings
     are unavailable it falls back to BM25 only and records that in the
     result.
  3. **The model proposes; it never decides.** The model sees only the
     retrieved chunks (not the whole document) and produces one structured
     proposal: a value, a unit, the chunk it came from, and the exact
     verbatim words it copied. For this kind of fact it also says whether the
     quoted number is a rating or maximum ("rated") or a measured result
     ("tested"). It is told the passages are untrusted data and to say "not
     found" instead of guessing.
  4. **Verify independently.** Code, not the model, re-checks the proposal:
     does the quoted text appear character for character (modulo whitespace)
     in the chunk the model named; does the unit parse and match the expected
     physical dimension; is a "rated" value being reported as "tested" or the
     reverse. Any failure gives a specific rejection reason ("quote not found
     in that chunk", "unit is a different dimension"). Nothing becomes a
     trusted fact until it passes; the model's output until then is a
     proposal.
  5. **Disagreement is a signal.** For facts that matter to a hard decision, a
     second, independent extraction pass can run over the same evidence. If it
     disagrees with the first, the fact is marked "contested" and neither
     reading is silently preferred.
  6. **A missing fact is its own outcome.** When no evidence supports a field,
     that is recorded as a gap with a reason (not stated in the source,
     extraction failed, or rejected by verification), never treated as a pass
     or a fail.
  7. **Comparing a verified fact with a requirement is a classification, not a
     boolean.** A verified value (optionally a low and high range, when the
     source states a tolerance) is checked against a numeric threshold with an
     explicit comparator: the whole range clears it (pass), none of it does
     (fail), or it straddles the boundary (marginal). A fact with no verified
     value is a fourth outcome, "unknown", grouped with "marginal" for ranking
     and never counted as a pass.

What matters for `gather_evidence()`: a piece of evidence is worth returning
only if it carries a specific, re-checkable locator to the place its value
came from, and the code that decides whether to trust it is separate from
whatever proposed it. That maps to `Evidence.locator`, plus keeping `stance`
assignment inside the domain adapter, decided from source text that was
inspected and never defaulted to "supports".

---

## Summary

| Part | Sourced facts with a locator? | Usable in `gather_evidence()` |
|---|---|---|
| BlueROV2 housing | Yes: two conflicting manufacturer revisions, both located | Yes, carrying the DOC1 versus DOC2 conflict through instead of resolving it silently |
| Bar30 | Yes, with one flagged fake (canary) value excluded | Yes, for the operating-range fact; the absolute-max fact is not independently re-verified |
| Bar100XT | Yes, as of 2026-10-24: Blue Robotics' official BarXT page | Yes: `DOC4_Bar100XT`, same pipeline as Bar30 |
| QuSpin QZFM Gen-3 | Yes, as of 2026-10-24, but the source states no rating | No numeric comparison is possible (nothing to compare), but the UNDETERMINED gap is now a cited, checked fact |
