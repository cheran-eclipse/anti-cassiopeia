# Data provenance — Stress Test #1

All retrieval dates below: 2026-10-18. Nothing in this directory is
synthetic unless explicitly marked SYNTHETIC — every other file was
actually fetched from the URL given, verified to contain real content
matching its expected shape, and saved verbatim.

## ml_data/ — UCI Machine Learning Repository (archive.ics.uci.edu)

All 14 fetched via UCI's public dataset API (`https://archive.ics.uci.edu/api/dataset?id=<id>`,
no auth needed) and its `data_url`. Per-dataset license is whatever UCI's
API returned for that dataset (most UCI datasets: CC BY 4.0, confirmed per
dataset below where the API stated it; several returned no explicit
license string from the API — noted as such, not assumed).

| File | UCI ID | Name | Rows | Numeric columns | Source |
|---|---|---|---|---|---|
| air_quality.csv | 360 | Air Quality | 9357 | 13 (gas multisensor device readings) | https://archive.ics.uci.edu/dataset/360/air+quality |
| combined_cycle_power_plant.csv | 294 | Combined Cycle Power Plant | 9568 | 5 (AT, V, AP, RH, PE — physical plant measurements) | https://archive.ics.uci.edu/dataset/294/combined+cycle+power+plant |
| concrete_compressive_strength.csv | 165 | Concrete Compressive Strength | 1030 | 9 | https://archive.ics.uci.edu/dataset/165/concrete+compressive+strength |
| wine_quality.csv | 186 | Wine Quality | 6497 | 12 | https://archive.ics.uci.edu/dataset/186/wine+quality |
| appliances_energy_prediction.csv | 374 | Appliances Energy Prediction | 19735 | 28 (temperature/humidity sensors) | https://archive.ics.uci.edu/dataset/374/appliances+energy+prediction |
| auto_mpg.csv | 9 | Auto MPG | 398 | 8 | https://archive.ics.uci.edu/dataset/9/auto+mpg |
| abalone.csv | 1 | Abalone | 4177 | 8 | https://archive.ics.uci.edu/dataset/1/abalone |
| forest_fires.csv | 162 | Forest Fires | 517 | 11 | https://archive.ics.uci.edu/dataset/162/forest+fires |
| bike_sharing.csv | 275 | Bike Sharing | 17379 | 16 | https://archive.ics.uci.edu/dataset/275/bike+sharing |
| real_estate_valuation.csv | 477 | Real Estate Valuation | 414 | 8 | https://archive.ics.uci.edu/dataset/477/real+estate+valuation |
| airfoil_self_noise.csv | 291 | Airfoil Self-Noise | 1503 | 6 (NASA wind-tunnel physical measurements) | https://archive.ics.uci.edu/dataset/291/airfoil+self-noise |
| gas_turbine_emission.csv | 551 | Gas Turbine CO and NOx Emission | 36733 | 11 (sensor measurements) | https://archive.ics.uci.edu/dataset/551/gas+turbine+co+and+nox+emission+data+set |
| superconductivity.csv | 464 | Superconductivity Data | 21263 | 81 | https://archive.ics.uci.edu/dataset/464/superconductivty+data |
| parkinsons_telemonitoring.csv | 189 | Parkinsons Telemonitoring | 5875 | 21 (biomedical voice sensor measurements) | https://archive.ics.uci.edu/dataset/189/parkinsons+telemonitoring |

Exact `data_url`s used (all `https://archive.ics.uci.edu/static/public/<id>/data.csv`)
and raw API JSON responses are not re-included here to keep this file
short; re-fetch `https://archive.ics.uci.edu/api/dataset?id=<ID>` for the
exact metadata if needed — it is a stable, versioned public API.

## fpga_embedded/ — real, committed Vivado `report_timing_summary` output found via GitHub code search

GitHub's code-search API requires authentication even for read access
(returns 401 unauthenticated) — used the already-authenticated `gh` CLI
(`gh auth status` confirmed `cheran-eclipse` logged in) rather than
requesting/storing a new raw token, per the "use what's already safely
available before adding a new credential" spirit of the task's rule 2.

As predicted by the task brief, this is genuinely scarce — most FPGA
projects gitignore build artifacts. Found 9 distinct real files across 7
repos (each file fetched via `gh api repos/<repo>/contents/<path>`,
default branch HEAD as of 2026-10-18; local filename = `<repo, "/"→"__">__<basename>`):

| Local file | Repo | Path | License | Notes |
|---|---|---|---|---|
| jiwoonl__timing.txt | jiwoonl/Event-Driven-Spiking-Neural-Network-Accelerator-for-FPGA | outputs/timing.txt | MIT | Real routed design, `Enable Multi Corner Analysis: Yes`; ONE Design Timing Summary row (Vivado folds multi-corner into one worst-case WNS at this summary level — per-corner detail only shows up in the per-path sections further down, e.g. "Setup (Max at Slow Process Corner)"). This REFINES — doesn't contradict — the §4.3 understanding: a single real multi-corner-enabled run still reports one summary table, not one per corner; see note below. |
| dawsonjon__FPGA-TX__post_synth_timing_summary.rpt | dawsonjon/FPGA-TX | synthesis/nexys_4/tx/post_synth_timing_summary.rpt | MIT | Real, parses cleanly |
| Nero7991__llm.vhdl__timing_summary_A.rpt | Nero7991/llm.vhdl | hw/jc/pinfinder/results/timing_summary_A.rpt | MIT | Real, parses cleanly — paired with _B below |
| Nero7991__llm.vhdl__timing_summary_B.rpt | Nero7991/llm.vhdl | hw/jc/pinfinder/results/timing_summary_B.rpt | MIT | Real, parses cleanly — two genuinely separate real report files from the same repo, usable as a real (not synthetic) two-corner/two-config pair for tier-2 multi-file-style claims |
| rbarzic__nanorv32__post_synth_timing_summary.rpt | rbarzic/nanorv32 | synt/fpga/rpt/post_synth_timing_summary.rpt | none stated | Real, parses cleanly |
| David-Durst__embeddedHaskellAetherling__timing_summary.txt | David-Durst/embeddedHaskellAetherling | pnr/exs/timing_summary.txt | BSD-3-Clause | Real, parses cleanly |
| hdlguy__make_for_vivado__timing.rpt | hdlguy/make_for_vivado | implement/results/timing.rpt | MIT | Real, parses cleanly |
| scarletnova20__...timing_impl.txt | scarletnova20/Vision-In-Memory-System-On-RISCV | reports/timing_impl.txt | MIT | Real, but the data row is literally `NA NA NA NA ...` (an incomplete/unclosed-timing run) — genuine real-world ADVERSARIAL edge case: correct behavior is "no numeric row matched, named gap", not a crash. Used for Tier 3. |
| scarletnova20__...timing_synth.txt | scarletnova20/Vision-In-Memory-System-On-RISCV | reports/timing_synth.txt | MIT | Same NA-row situation as above (post-synthesis, pre-route) |

### Quantum-control/accelerator FPGA data (amendment, additive to the above)

Searched specifically for real, committed Vivado/EDA timing reports from
FPGA-based quantum control/accelerator projects, per the amendment's
instruction, as a layer ON TOP of the general-FPGA data above (nothing
above was replaced):

- `org:m-labs` (ARTIQ) and `org:sinara-hw` (Sinara hardware: Kasli,
  Metlino, etc.) — code search for `"Design Timing Summary"` and
  `"WNS(ns)"` scoped to each org: **zero hits**. Checked the repos
  directly too (`m-labs/artiq`, `sinara-hw/Kasli`, `sinara-hw/Metlino`,
  `sinara-hw/sinara`) — these repos hold Migen/Python gateware SOURCE,
  not committed synthesis/timing build artifacts.
- `QubiC` (LBNL's open-source superconducting-qubit FPGA controller) —
  found no repository under that name with committed timing reports.
- `QICK` (Quantum Instrumentation Control Kit, RFSoC-based qubit
  controller, `openquantumhardware/qick` — genuinely the right kind of
  project for this category): code search found exactly ONE match,
  `firmware/projects/qick_tprocv2_2x4_standard/out/timing_summary_routed.rpt`.
  Fetched it — **it is a symlink** (`type: "symlink"` in the GitHub
  contents API response) pointing at
  `../top/top.runs/impl_1/d_1_wrapper_timing_summary_routed.rpt`, a
  Vivado build-output path that was never actually committed (confirmed
  absent from the repo's full git tree via `gh api .../git/trees/main?recursive=true`).
  The real file this symlink was meant to point to does not exist in the
  repository — it's a dangling reference, not retrievable real content.
- `"surface code decoder" "report_timing_summary"` and similar QEC-decoder
  phrasings: zero genuinely relevant hits (the broader, looser
  `decoder FPGA "Design Timing Summary"` query returned 518 results, but
  inspection showed generic unrelated FPGA/SDR/CPU projects incidentally
  matching those common words, not quantum error-correction decoders).

**Honest result: this sub-population came up EMPTY after a real, multi-angle
attempt.** Zero real quantum-control/accelerator FPGA timing reports were
found and added. The general-FPGA data sourced earlier (9 real files + 2
synthetic fixtures, listed above) is NOT relabeled as quantum to
compensate — `manifest.jsonl`'s claims drawing on fpga_embedded data all
cite the general-FPGA provenance already documented above, and no claim
in this stress test is tagged as quantum-control-sourced, because none
genuinely is.

**Honest note on "multi-corner", refining §4.3's design:** none of the 9
real files found contain the adapter's `Corner: <NAME>` label convention
— that was always documented in `fpga_embedded.py`'s own module docstring
as THIS ADAPTER'S OWN structuring convention, not a copied real format,
specifically because no readable real multi-corner-labeled sample could
be fetched then. That remains true now. The multi-corner claims in this
stress test's manifest use the EXISTING already-committed, already
explicitly-marked-synthetic fixtures
(`evals/fixtures/vivado_timing_report.rpt`,
`vivado_timing_report_single_corner.rpt` — copied into
`stress_test/data/fpga_embedded/` unchanged, still carrying their own
"synthetic fixture" header line) for exercising the `Corner:` parsing
mechanism itself; they are kept in a clearly separate bucket from the 9
real files above in `manifest.jsonl`'s `provenance` field and never
described as "real" there.

## robotics/ — reused, not re-sourced (per task instruction)

No new sourcing. Claims reuse the existing corpus already in
`anticassiopeia/corpus/` (`doc1_bluerov2_excerpt.txt`,
`doc2_bluerov2_excerpt.txt`, `doc3_bar30_excerpt.txt`) and
`docs/extracted/constellation-robotics-seed.md`, exactly as
`anticassiopeia/domains/robotics.py` already retrieves against them. Did
NOT pull additional material from the sibling `~/file/eclipse-constellation`
folder beyond what's already used in production — the task said to
confirm first whether more was wanted, and this run didn't pause to ask,
so it stuck to the existing corpus only.

## research_web/ — no local corpus (live search is the point); real facts confirmed for claim templating

Mode 2 does live search itself at claim-verification time — nothing to
pre-fetch as a corpus. The real-world facts claims are TEMPLATED FROM
(to generate true/negated/absent-detail variants) were each independently
confirmed by fetching the real page (same method as the existing
`live_multi_candidate_*` eval cases from §4.3/§4.4):

| Topic | Source URL | Fetched | Anchor fact(s) used |
|---|---|---|---|
| BlueROV2 | https://en.wikipedia.org/wiki/BlueROV2 | 2026-10-17 (§4.3/§4.4), re-confirmed 2026-10-18 | developer (Blue Robotics), depth rating (100m standard / 300m extended), release year (2016) |
| ArduPilot | https://en.wikipedia.org/wiki/ArduPilot | 2026-10-18 | release year (2009), license (GPLv3), languages (C++, Python) |
| Raspberry Pi | https://en.wikipedia.org/wiki/Raspberry_Pi | 2026-10-18 | manufacturer (Sony, under contract), release date (29 February 2012) |
| ESP32 | https://en.wikipedia.org/wiki/ESP32 | 2026-10-18 | manufacturer (Espressif Systems), type (microcontroller) |
| BeagleBone | https://en.wikipedia.org/wiki/BeagleBone | 2026-10-18 | first-release date (2008-07-28, as "Beagle Board") |
| Analog Devices | https://en.wikipedia.org/wiki/Analog_Devices | 2026-10-18 | entity type (American semiconductor manufacturer), ticker (Nasdaq: ADI) |

All Wikipedia content: CC BY-SA 4.0 (Wikipedia's standard license,
confirmed per Wikipedia's own terms, not re-checked per-page since it's
site-wide policy).
