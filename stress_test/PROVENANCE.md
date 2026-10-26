# Data provenance: Stress Test #1

All retrieval dates below are 2026-10-18 unless stated. Every file in this
directory was fetched from the URL given, checked to have the expected
shape, and saved verbatim, except files marked SYNTHETIC.

**Reproducibility (external review, item 14):** `stress_test/data/` is
gitignored, so none of these files survive a fresh clone. Run
`PYTHONPATH=. python stress_test/bootstrap_data.py` to re-fetch every file
below from these URLs, regenerate the shard files and copy the two synthetic
fixtures. On 2026-10-24 it reproduced all 33 files byte-identical to the data
the stress-test numbers were computed from, checked against the committed
`stress_test/data_checksums.txt`.

## ml_data/ — UCI Machine Learning Repository (archive.ics.uci.edu)

All 14 were fetched through UCI's public dataset API
(`https://archive.ics.uci.edu/api/dataset?id=<id>`, no auth) and its
`data_url`. Each dataset's license is whatever UCI's API returned. Most are
CC BY 4.0; several returned no license string, and none is assumed.

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

The `data_url`s are all `https://archive.ics.uci.edu/static/public/<id>/data.csv`.
Raw API responses are not included; re-fetch
`https://archive.ics.uci.edu/api/dataset?id=<ID>` for the metadata (a stable,
versioned public API).

**Phase B item 11 (held-out set, 2026-10-19):** one more UCI dataset,
fetched because the main 3,383-claim manifest never used it (the point of a
held-out set):

| File | UCI ID | Name | Rows | Numeric columns | Source |
|---|---|---|---|---|---|
| yacht_hydrodynamics.csv | 243 | Yacht Hydrodynamics | 308 | 7 (6 hull-geometry features + 1 target) | https://archive.ics.uci.edu/ml/machine-learning-databases/00243/yacht_hydrodynamics.data |

Column names are this project's own labels, taken from the dataset page's
"Additional Variable Information" (the raw `.data` file has no header row),
and are not reused from any other file here. Statistics for the held-out
claims were computed with plain arithmetic in
`stress_test/claims/generate_heldout.py`, not by importing
`stress_test/oracles/ml_data_oracle.py`.

## fpga_embedded/: committed Vivado `report_timing_summary` output found via GitHub code search

GitHub's code-search API requires authentication even for read access (401
unauthenticated). The search used the already-authenticated `gh` CLI
(`gh auth status` showed `cheran-eclipse` logged in) instead of requesting or
storing a new token.

Such reports are scarce, since most FPGA projects gitignore build artifacts.
The search found 9 distinct files across 7 repos, each fetched with
`gh api repos/<repo>/contents/<path>` at the default branch HEAD as of
2026-10-18. The local filename is `<repo, "/"→"__">__<basename>`:

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

**Phase B item 11 (held-out set, 2026-10-19):** one more Vivado report, from
a project the main manifest never used, found with the same
`gh api search/code` method:

| Local file | Repo | Path | License | Notes |
|---|---|---|---|---|
| nethakah__nasdaq-pipeline__timing_route.rpt | nethakah/nasdaq-pipeline | fpga/results/timing_route.rpt | Apache-2.0 | Real, modern (Vivado v2024.1) routed report; two real clocks (core_clk 285.714MHz, dma_clk 100.000MHz); WNS(ns)=0.034, WHS(ns)=0.011, WPWS(ns)=1.218 — all read directly from the real file by eye for the held-out claims, quoted in `stress_test/claims/generate_heldout.py`'s own docstring, not parsed by a script sharing code with `fpga_embedded.py` |

### Quantum-control and accelerator FPGA data (amendment, added to the above)

The search targeted committed Vivado and EDA timing reports from FPGA-based
quantum control and accelerator projects, on top of the general FPGA data
above (nothing above was replaced):

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

**Result: this sub-population came up empty after a multi-angle search.** No
quantum-control or accelerator FPGA timing reports were found. The general
FPGA data listed above (9 real files and 2 synthetic fixtures) is not
relabeled as quantum. `manifest.jsonl`'s `fpga_embedded` claims cite the
general FPGA provenance above, and no claim in this stress test is tagged as
quantum-control-sourced.

**Note on "multi-corner", refining §4.3's design.** None of the 9 real files
contains the adapter's `Corner: <NAME>` label. `fpga_embedded.py`'s module
docstring has always described that label as this adapter's own convention,
not a copied real format, because no readable real multi-corner sample could
be fetched. That is still true. The multi-corner claims in the manifest use
the committed synthetic fixtures (`evals/fixtures/vivado_timing_report.rpt`
and `vivado_timing_report_single_corner.rpt`, copied unchanged into
`stress_test/data/fpga_embedded/` with their "synthetic fixture" header line)
to exercise `Corner:` parsing. They sit in a separate bucket from the 9 real
files in `manifest.jsonl`'s `provenance` field and are never described as
real.

## robotics/: reused, not re-sourced

No new sourcing. Claims reuse the corpus in `anticassiopeia/corpus/`
(`doc1_bluerov2_excerpt.txt`, `doc2_bluerov2_excerpt.txt`,
`doc3_bar30_excerpt.txt`) and `docs/extracted/constellation-robotics-seed.md`,
the same material `anticassiopeia/domains/robotics.py` retrieves against. No
additional material was taken from the sibling `~/file/eclipse-constellation`
folder; the task said to confirm first whether more was wanted, and this run
did not ask.

**License.** The README's "License" section states the general policy for
third-party data; this file states it for this corpus. `doc1-4_*.txt` and
the Bar100XT and QuSpin material in `constellation-robotics-seed.md` are
short, numeric excerpts (depth ratings, pressure ranges, dimensions) from
Blue Robotics' and QuSpin's public product pages. Numeric specifications are
not independently copyrightable under US copyright law, whatever the source
page's terms say, and the excerpts are the minimal factual statement, not the
page's text, layout or imagery. Neither vendor published these pages under
an open-source license, so this content carries no MIT, Apache or CC license
of its own and is not claimed to. The README's "License" section explains how
this project's MPL-2.0 license excludes bundled third-party data.

### v2 "bring your own evidence" stress-test material (2026-10-25): MIT and Apache-2.0

Robotics source material added for the v2 upload stress test. It was chosen
because it carries a permissive open-source license, unlike the vendor-page
excerpts above. Each license was confirmed by fetching the repository's
LICENSE file, not from a GitHub sidebar badge:

| Local file | Project | Source | License | Verified via |
|---|---|---|---|---|
| `odrive_v3_6_specifications_excerpt.txt` | ODrive v3.6 motor controller | https://github.com/odriverobotics/ODrive, `docs/specifications.rst` | MIT (Copyright (c) 2016-2018 ODrive Robotics) | Raw fetch of `https://raw.githubusercontent.com/odriverobotics/ODrive/master/LICENSE.md` (opens "MIT License") and `.../master/docs/specifications.rst`, 2026-10-25 |
| `nasa_jpl_open_source_rover_readme_excerpt.txt` | NASA JPL Open Source Rover | https://github.com/nasa-jpl/open-source-rover | Apache License 2.0 (Copyright 2018 California Institute of Technology, Government Sponsorship Acknowledged) | Raw fetch of `https://raw.githubusercontent.com/nasa-jpl/open-source-rover/master/LICENSE.txt`, 2026-10-25 |

Both excerpts are short and verbatim, copied character for character from
the source (the quote-exactly rule `retrieval/extract.py`'s `propose()`
prompt applies to the LLM), and each file's header comment keeps the source
URL. Apache-2.0's attribution and NOTICE obligations are met by that header
naming the copyright holder and source; no NOTICE file is added because
neither source repository ships one. See
`stress_test/results/V2_BYOE_STRESS_TEST_REPORT.md` for what these were
tested against.

## research_web/: no local corpus; facts confirmed for claim templating

Mode 2 searches live at verification time, so there is no corpus to
pre-fetch. The facts that claims are templated from (to generate true,
negated and absent-detail variants) were each confirmed by fetching the page,
the same method as the `live_multi_candidate_*` eval cases from §4.3 and
§4.4:

| Topic | Source URL | Fetched | Anchor fact(s) used |
|---|---|---|---|
| BlueROV2 | https://en.wikipedia.org/wiki/BlueROV2 | 2026-10-17 (§4.3/§4.4), re-confirmed 2026-10-18 | developer (Blue Robotics), depth rating (100m standard / 300m extended), release year (2016) |
| ArduPilot | https://en.wikipedia.org/wiki/ArduPilot | 2026-10-18 | release year (2009), license (GPLv3), languages (C++, Python) |
| Raspberry Pi | https://en.wikipedia.org/wiki/Raspberry_Pi | 2026-10-18 | manufacturer (Sony, under contract), release date (29 February 2012) |
| ESP32 | https://en.wikipedia.org/wiki/ESP32 | 2026-10-18 | manufacturer (Espressif Systems), type (microcontroller) |
| BeagleBone | https://en.wikipedia.org/wiki/BeagleBone | 2026-10-18 | first-release date (2008-07-28, as "Beagle Board") |
| Analog Devices | https://en.wikipedia.org/wiki/Analog_Devices | 2026-10-18 | entity type (American semiconductor manufacturer), ticker (Nasdaq: ADI) |
| STM32 | https://en.wikipedia.org/wiki/STM32 | 2026-10-18 | manufacturer (STMicroelectronics), architecture (ARM Cortex-M) |
| Xilinx | https://en.wikipedia.org/wiki/Xilinx | 2026-10-18 | entity type (American technology company) |

**24 more topics added for Phase B item 9** (external review: `research_web`
was the most under-tested domain, at 24 claims). The total is **32** source
pages (the original 8 plus these 24). A later external review cited the total
as 24, confusing it with the topic count added in this step or the
pre-expansion claim count. Each page was fetched on 2026-10-19, before any
claim was written, through Wikipedia's REST summary API
(`https://en.wikipedia.org/api/rest_v1/page/summary/<title>`, the backend
`research_web.py`'s live tests use):

| Topic | Source URL | Fetched | Anchor fact(s) used |
|---|---|---|---|
| Arduino Uno | https://en.wikipedia.org/wiki/Arduino_Uno | 2026-10-19 | initial release (by the Arduino company, 2010) |
| Linux kernel | https://en.wikipedia.org/wiki/Linux_kernel | 2026-10-19 | creator and year (Linus Torvalds, 1991) |
| Python | https://en.wikipedia.org/wiki/Python_(programming_language) | 2026-10-19 | language character (high-level, general-purpose, readability-emphasizing) |
| ROS | https://en.wikipedia.org/wiki/Robot_Operating_System | 2026-10-19 | nature (open-source robotics middleware suite) |
| Nvidia Jetson | https://en.wikipedia.org/wiki/Nvidia_Jetson | 2026-10-19 | maker (series of embedded computing boards from Nvidia) |
| KiCad | https://en.wikipedia.org/wiki/KiCad | 2026-10-19 | licensing (free software suite for EDA) |
| Verilog | https://en.wikipedia.org/wiki/Verilog | 2026-10-19 | standard (IEEE 1364) |
| VHDL | https://en.wikipedia.org/wiki/VHDL | 2026-10-19 | origin (US military VHSIC program, 1980s) |
| RISC-V | https://en.wikipedia.org/wiki/RISC-V | 2026-10-19 | licensing character (free and open standard ISA) |
| MicroPython | https://en.wikipedia.org/wiki/MicroPython | 2026-10-19 | implementation language and compatibility (written in C, largely Python 3-compatible) |
| FreeRTOS | https://en.wikipedia.org/wiki/FreeRTOS | 2026-10-19 | license (MIT) |
| CAN bus | https://en.wikipedia.org/wiki/CAN_bus | 2026-10-19 | nature (vehicle bus standard for microcontroller/device communication) |
| I2C | https://en.wikipedia.org/wiki/I2C | 2026-10-19 | inventor and year (Philips Semiconductors, 1980) |
| SPI | https://en.wikipedia.org/wiki/Serial_Peripheral_Interface | 2026-10-19 | nature (synchronous serial communication standard for embedded systems) |
| Zephyr | https://en.wikipedia.org/wiki/Zephyr_(operating_system) | 2026-10-19 | license (Apache License 2.0) |
| OpenCV | https://en.wikipedia.org/wiki/OpenCV | 2026-10-19 | original developer (Intel) |
| TensorFlow | https://en.wikipedia.org/wiki/TensorFlow | 2026-10-19 | license (Apache License 2.0) |
| PyTorch | https://en.wikipedia.org/wiki/PyTorch | 2026-10-19 | original developer (Meta Platforms) |
| Intel 8051 | https://en.wikipedia.org/wiki/Intel_8051 | 2026-10-19 | maker and year (Intel, 1980; canonical title Intel_MCS-51) |
| ATmega328 | https://en.wikipedia.org/wiki/ATmega328 | 2026-10-19 | maker and family (Atmel, megaAVR) |
| Adafruit | https://en.wikipedia.org/wiki/Adafruit_Industries | 2026-10-19 | founder and year (Limor Fried, 2005) |
| SparkFun | https://en.wikipedia.org/wiki/SparkFun_Electronics | 2026-10-19 | location (Niwot, Colorado) |
| Bluetooth Low Energy | https://en.wikipedia.org/wiki/Bluetooth_Low_Energy | 2026-10-19 | steward (Bluetooth Special Interest Group) |
| Modbus | https://en.wikipedia.org/wiki/Modbus | 2026-10-19 | original use case (programmable logic controllers) |

Each topic's "absent" claim is an invented statistic that does not appear in
the fetched summary text, the same convention as the original 8 topics. It
was not checked against the full page beyond the summary extract, which is
the same residual risk the original 8 carry.

All Wikipedia content is CC BY-SA 4.0 (Wikipedia's site-wide license,
not re-checked per page).
