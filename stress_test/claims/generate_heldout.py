"""
Phase B item 11 (external review): a genuine HELD-OUT claim set that
shares NO template generation logic, NO source files, and NO code path
with the existing 3,383-claim manifest (generate_manifest.py) —
generated as a completely separate script, against completely
different real source material:

- ml_data: a NEW real UCI dataset never used anywhere in this project
  before (Yacht Hydrodynamics, 308 real instances, fetched live from
  https://archive.ics.uci.edu/ml/machine-learning-databases/00243/
  yacht_hydrodynamics.data on 2026-10-19 -- column names from the UCI
  dataset page's own "Additional Variable Information", in order).
  Statistics are computed by HAND-ROLLED arithmetic in this file (mean/
  median/stdev/correlation re-derived from scratch), NOT by importing
  stress_test/oracles/ml_data_oracle.py or Python's `statistics` module
  -- a genuinely separate verification code path, not just new data fed
  through the same oracle.
- fpga_embedded: a NEW real Vivado timing report from a different
  open-source project never used before (nethakah/nasdaq-pipeline,
  fpga/results/timing_route.rpt, found via `gh api search/code` the same
  way the original fpga_embedded.py sourcing was done, fetched live on
  2026-10-19). Values below are read directly from that real file by eye
  (quoted in this docstring), not parsed by a script sharing code with
  fpga_embedded.py's own parser.
- robotics: the SAME two known parts (BlueROV2, Bar30 -- robotics.py's
  corpus genuinely only covers these two, so "held-out" here can't mean
  "a different known part"), but exercised through the `Claim.context =
  {"depth_m": ..., "polarity": ...}` CONTRACT -- confirmed by reading
  generate_manifest.py's gen_robotics_claims() that the main 3,383-claim
  manifest ONLY EVER uses free-text claims (`context: {}`), so the
  context-dict path through `_parse_condition()` has literally never
  been exercised by any stress-test claim before now. Plus 2 genuinely
  unsourced-part claims (real Blue Robotics products with no corpus
  entry at all) confirming the honest-gap path on a part string
  robotics.py's own part-detection doesn't even recognize.
- research_web: 5 more real Wikipedia topics never used in
  generate_manifest.py's 32-topic list, each independently fetched live
  via the same Wikipedia REST summary API on 2026-10-19 before any claim
  was written (see stress_test/PROVENANCE.md for the fetch log).

Output: stress_test/claims/heldout_manifest.jsonl -- same schema as the
main manifest.jsonl (claim_id/domain/tier/claim_payload/
ground_truth_verdict/ground_truth_method/provenance), but with claim_id
prefixed "heldout-" so it can never collide with or be confused for a
main-manifest claim ID.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
YACHT_CSV = REPO_ROOT / "stress_test/data/ml_data/yacht_hydrodynamics.csv"
FPGA_RPT = "stress_test/data/fpga_embedded/nethakah__nasdaq-pipeline__timing_route.rpt"

_counter = 0


def _next_id() -> str:
    global _counter
    _counter += 1
    return f"heldout-{_counter:04d}"


# =========================================================================
# ml_data: hand-rolled statistics, NOT stress_test/oracles/ml_data_oracle.py
# =========================================================================

def _hand_mean(vals: list[float]) -> float:
    total = 0.0
    n = 0
    for v in vals:
        total += v
        n += 1
    return total / n


def _hand_median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _hand_stdev(vals: list[float]) -> float:
    m = _hand_mean(vals)
    n = len(vals)
    var = sum((v - m) ** 2 for v in vals) / (n - 1)
    return var ** 0.5


def _hand_correlation(xs: list[float], ys: list[float]) -> float:
    mx, my = _hand_mean(xs), _hand_mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy)


def gen_ml_data_heldout() -> list[dict]:
    with open(YACHT_CSV) as f:
        rows = list(csv.DictReader(f))

    claims = []
    rel_path = str(YACHT_CSV.relative_to(REPO_ROOT))

    def add(column: str, stat: str, computed: float, tolerance: float, verdict_true: bool, column_b: str | None = None):
        ctx = {"dataset_path": rel_path, "column": column, "stat": stat, "tolerance": tolerance}
        if column_b:
            ctx["column_b"] = column_b
        expected = computed if verdict_true else computed * 1.5 + 10  # deliberately wrong, same convention as the main manifest
        ctx["expected_value"] = expected
        col_desc = f"{column},{column_b}" if column_b else column
        claims.append({
            "claim_id": _next_id(), "domain": "ml_data", "tier": 1 if verdict_true else 2,
            "claim_payload": {
                "text": f"{stat}({col_desc}) in yacht_hydrodynamics.csv is {expected}",
                "domain": "ml_data", "context": ctx,
            },
            "ground_truth_verdict": "confirmed" if verdict_true else "contradicted",
            "ground_truth_method": (
                f"hand-rolled arithmetic (this file's own _hand_{stat if stat in ('mean','median','stdev','correlation') else 'mean'}-style "
                f"helpers, NOT ml_data_oracle.py) over real UCI Yacht Hydrodynamics data (308 real instances)"
            ),
            "provenance": "https://archive.ics.uci.edu/ml/machine-learning-databases/00243/yacht_hydrodynamics.data (fetched live 2026-10-19)",
        })

    froude = [float(r["froude_number"]) for r in rows]
    resid = [float(r["residuary_resistance"]) for r in rows]
    prismatic = [float(r["prismatic_coefficient"]) for r in rows]
    lbr = [float(r["length_beam_ratio"]) for r in rows]

    add("froude_number", "mean", _hand_mean(froude), 1e-6, True)
    add("froude_number", "mean", _hand_mean(froude), 1e-6, False)
    add("froude_number", "median", _hand_median(froude), 1e-9, True)
    add("residuary_resistance", "mean", _hand_mean(resid), 1e-6, True)
    add("residuary_resistance", "mean", _hand_mean(resid), 1e-6, False)
    add("residuary_resistance", "stdev", _hand_stdev(resid), 1e-6, True)
    add("prismatic_coefficient", "mean", _hand_mean(prismatic), 1e-6, True)
    add("prismatic_coefficient", "stdev", _hand_stdev(prismatic), 1e-6, False)
    add("length_beam_ratio", "median", _hand_median(lbr), 1e-9, True)
    add("froude_number", "correlation", _hand_correlation(froude, resid), 1e-6, True, column_b="residuary_resistance")
    add("froude_number", "correlation", _hand_correlation(froude, resid), 1e-6, False, column_b="residuary_resistance")

    return claims


# =========================================================================
# fpga_embedded: real values read directly from the real file by eye
# (nethakah/nasdaq-pipeline, fpga/results/timing_route.rpt), quoted here:
#   WNS(ns)=0.034  TNS(ns)=0.000  THS(ns)... wait: WHS(ns)=0.011  THS(ns)=0.000
#   core_clk: period=3.500ns, frequency=285.714MHz
#   dma_clk:  period=10.000ns, frequency=100.000MHz
# =========================================================================

def gen_fpga_heldout() -> list[dict]:
    claims = []

    def add(metric: str, comparator: str, expected: float, verdict: str, clock: str | None = None):
        ctx = {"report_path": FPGA_RPT, "metric": metric, "comparator": comparator, "expected_value": expected}
        if clock:
            ctx["clock"] = clock
        claims.append({
            "claim_id": _next_id(), "domain": "fpga_embedded", "tier": 1,
            "claim_payload": {
                "text": f"nethakah/nasdaq-pipeline: {metric} {comparator} {expected}" + (f" ({clock})" if clock else ""),
                "domain": "fpga_embedded", "context": ctx,
            },
            "ground_truth_verdict": verdict,
            "ground_truth_method": "value read directly from the real report file by eye, quoted in this script's own docstring",
            "provenance": "https://github.com/nethakah/nasdaq-pipeline/blob/main/fpga/results/timing_route.rpt (fetched live 2026-10-19)",
        })

    add("wns_ns", ">=", 0.03, "confirmed")        # real value 0.034 >= 0.03
    add("wns_ns", ">=", 0.05, "contradicted")     # real value 0.034 < 0.05
    add("whs_ns", ">=", 0.01, "confirmed")        # real value 0.011 >= 0.01
    add("whs_ns", ">=", 0.02, "contradicted")     # real value 0.011 < 0.02
    add("wpws_ns", ">=", 1.0, "confirmed")        # real value 1.218 >= 1.0
    add("frequency_mhz", ">=", 250.0, "confirmed", clock="core_clk")    # real 285.714 >= 250
    add("frequency_mhz", ">=", 300.0, "contradicted", clock="core_clk")  # real 285.714 < 300
    add("period_ns", "==", 10.0, "confirmed", clock="dma_clk")          # real 10.000 == 10.0

    return claims


# =========================================================================
# robotics: SAME two known parts, but via the never-before-exercised
# context={"depth_m":..., "polarity":...} contract, plus genuinely
# unsourced-part gap tests.
# =========================================================================

def gen_robotics_heldout() -> list[dict]:
    claims = []

    # FOUND BUG (external review): text used to be a content-free
    # "<part> depth check", with the actual depth/polarity living ONLY
    # in context -- invisible to every TEXT-ONLY baseline (bare,
    # Perplexity, Tavily+Gemini, generic-RAG), which could only ever see
    # a claim with no actual claim in it. That measured nothing for those
    # baselines on these 6 claims, not "robotics is hard for them". Fixed:
    # the text now states the same depth/polarity in plain language too
    # -- the context dict is STILL passed and still wins for the real
    # adapter (_parse_condition() checks `"depth_m" in ctx` before ever
    # trying to parse free text), so this still genuinely exercises the
    # context-dict code path for the real pipeline/Nebius-agent while no
    # longer being a content-free string for everything else.
    def add(part_text: str, depth_m: float, polarity: str, verdict: str, method: str):
        verb = "survives" if polarity == "survives" else "fails at"
        claims.append({
            "claim_id": _next_id(), "domain": "robotics", "tier": 2,
            "claim_payload": {
                "text": f"{part_text} {verb} {depth_m:g} m depth", "domain": "robotics",
                "context": {"depth_m": depth_m, "polarity": polarity},
            },
            "ground_truth_verdict": verdict,
            "ground_truth_method": method,
            "provenance": "anticassiopeia/corpus/doc{1,2,3}_*.txt (reused, not re-fetched) -- new code path: context dict, not free text",
        })

    add("BlueROV2", 37.5, "survives", "confirmed",
        "37.5m is within both real housings' ratings (acrylic 100m, aluminum 300m) -- unambiguous")
    add("BlueROV2", 212.5, "survives", "undetermined",
        "212.5m: acrylic (100m) says no, aluminum (300m) says yes -- the two real housings genuinely disagree")
    add("BlueROV2", 456.0, "fails", "confirmed",
        "456m exceeds both real housings' ratings (100m, 300m) -- unambiguously fails")
    add("Bar30", 150.0, "survives", "confirmed",
        "150m is well within Bar30's real ~298.3m rating (30 bar), outside the 5% margin")
    add("Bar30", 300.0, "survives", "undetermined",
        "300m is within the real 5% gauge/absolute pressure margin of Bar30's ~298.3m rating")
    add("Bar30", 450.0, "fails", "confirmed",
        "450m exceeds Bar30's real ~298.3m rating well beyond the 5% margin -- unambiguously fails")

    for part in ["Blue Robotics T200 Thruster", "Ping Sonar Altimeter"]:
        claims.append({
            "claim_id": _next_id(), "domain": "robotics", "tier": 3,
            "claim_payload": {"text": f"{part} survives 500 m depth", "domain": "robotics", "context": {}},
            "ground_truth_verdict": "undetermined",
            "ground_truth_method": (
                "genuinely real Blue Robotics product with NO corpus entry at all in robotics.py -- not even "
                "recognized by its own part-detection string matching, so this must resolve to the generic honest gap"
            ),
            "provenance": "https://bluerobotics.com (real product, deliberately never sourced into this project's corpus)",
        })

    return claims


# =========================================================================
# research_web: 5 NEW topics, never in generate_manifest.py's 32-topic list
# =========================================================================

_HELDOUT_RESEARCH_WEB_FACTS = [
    {
        "topic": "Micro Air Vehicle", "true": "A micro air vehicle is a class of man-portable miniature UAVs",
        "false": "A micro air vehicle is a class of crewed, long-range military bombers",
        "absent": "Micro air vehicles are restricted by international treaty to a maximum wingspan of exactly 15 centimeters",
        "source": "https://en.wikipedia.org/wiki/Micro_Air_Vehicle",
    },
    {
        "topic": "LoRa", "true": "LoRa is a proprietary radio communication technique based on spread spectrum modulation",
        "false": "LoRa is an open-standard wired communication technique based on time-division multiplexing",
        "absent": "LoRa's maximum range is defined as exactly 40 kilometers under all conditions",
        "source": "https://en.wikipedia.org/wiki/LoRa",
    },
    {
        "topic": "FPGA", "true": "A field-programmable gate array is a type of configurable integrated circuit that can be repeatedly programmed after manufacturing",
        "false": "A field-programmable gate array is a type of integrated circuit that can only be programmed once at the factory",
        "absent": "The first commercial FPGA contained exactly 1,200 logic gates",
        "source": "https://en.wikipedia.org/wiki/Field-programmable_gate_array",
    },
    {
        "topic": "Zigbee", "true": "Zigbee is an IEEE 802.15.4-based specification for low-power personal area networks",
        "false": "Zigbee is an IEEE 802.3-based specification for high-power wide area networks",
        "absent": "Zigbee's maximum network size is capped at exactly 500 devices",
        "source": "https://en.wikipedia.org/wiki/Zigbee",
    },
    {
        "topic": "Rust", "true": "Rust is a general-purpose programming language that emphasizes performance, type safety, concurrency, and memory safety",
        "false": "Rust is a domain-specific scripting language that emphasizes rapid prototyping over safety or performance",
        "absent": "The Rust compiler's borrow checker runs in exactly O(n) time for every program",
        "source": "https://en.wikipedia.org/wiki/Rust_(programming_language)",
    },
]


def gen_research_web_heldout() -> list[dict]:
    claims = []
    for fact in _HELDOUT_RESEARCH_WEB_FACTS:
        claims.append({
            "claim_id": _next_id(), "domain": "research_web", "tier": 1,
            "claim_payload": {"text": fact["true"], "domain": "research_web", "context": {}},
            "ground_truth_verdict": "confirmed",
            "ground_truth_method": f"fact independently confirmed live by fetching {fact['source']} on 2026-10-19",
            "provenance": fact["source"],
        })
        claims.append({
            "claim_id": _next_id(), "domain": "research_web", "tier": 2,
            "claim_payload": {"text": fact["false"], "domain": "research_web", "context": {}},
            "ground_truth_verdict": "contradicted",
            "ground_truth_method": f"negated/altered from the real fact at {fact['source']}",
            "provenance": fact["source"],
        })
        claims.append({
            "claim_id": _next_id(), "domain": "research_web", "tier": 3,
            "claim_payload": {"text": fact["absent"], "domain": "research_web", "context": {}},
            "ground_truth_verdict": "undetermined",
            "ground_truth_method": f"plausible-sounding but confirmed ABSENT from {fact['source']}'s summary text",
            "provenance": fact["source"],
        })
    return claims


def main() -> None:
    all_claims = (
        gen_ml_data_heldout() + gen_fpga_heldout() + gen_robotics_heldout() + gen_research_web_heldout()
    )
    out_path = REPO_ROOT / "stress_test/claims/heldout_manifest.jsonl"
    with open(out_path, "w") as f:
        for c in all_claims:
            f.write(json.dumps(c) + "\n")

    from collections import Counter
    by_domain = Counter(c["domain"] for c in all_claims)
    by_verdict = Counter(c["ground_truth_verdict"] for c in all_claims)
    print(f"Held-out set: {len(all_claims)} claims")
    print("By domain:", dict(by_domain))
    print("By verdict:", dict(by_verdict))


if __name__ == "__main__":
    main()
