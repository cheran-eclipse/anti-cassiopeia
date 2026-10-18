"""
Generates stress_test/claims/manifest.jsonl — one JSON object per claim,
across all four domains, with ground truth that is either mechanically
computed (ml_data/fpga_embedded, via the independent oracles in
stress_test/oracles/) or true-by-construction from a real, independently
verified source fact (robotics/research_web, same method as this
project's existing hand-authored eval cases).

This script makes NO network calls and NO calls into anticassiopeia/ —
it only reads the real data files already saved under stress_test/data/
and writes the manifest. Run with: python3 stress_test/claims/generate_manifest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "oracles"))
import fpga_embedded_oracle  # noqa: E402
import ml_data_oracle  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent.parent
ML_DATA_DIR = REPO_ROOT / "stress_test/data/ml_data"
FPGA_DIR = REPO_ROOT / "stress_test/data/fpga_embedded"

_claim_counter = 0


def _next_id(domain: str) -> str:
    global _claim_counter
    _claim_counter += 1
    return f"{domain}-{_claim_counter:06d}"


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))


# =========================================================================
# ml_data claim generation
# =========================================================================

_ML_FILES = [
    "air_quality", "combined_cycle_power_plant", "concrete_compressive_strength",
    "wine_quality", "appliances_energy_prediction", "auto_mpg", "abalone",
    "forest_fires", "bike_sharing", "real_estate_valuation", "airfoil_self_noise",
    "gas_turbine_emission", "superconductivity", "parkinsons_telemonitoring",
]
# ID-like columns to skip (not meaningful physical/sensor quantities).
_ML_SKIP_COLS = {"no", "subject#", "instant", "year", "index"}


def gen_ml_data_claims() -> list[dict]:
    claims = []
    for slug in _ML_FILES:
        path = ML_DATA_DIR / f"{slug}.csv"
        header, rows = ml_data_oracle.read_columns([str(path)])
        numeric_cols = []
        for c in header:
            if c.lower() in _ML_SKIP_COLS:
                continue
            vals = ml_data_oracle.column_values(header, rows, c)
            if len(vals) >= max(2, int(0.9 * len(rows))):  # genuinely numeric in ~all rows, not sparse
                numeric_cols.append(c)
        # cap columns per file to control volume on very wide datasets (raised
        # from the pilot's 6 -> 15 as part of the amendment's scale-up)
        use_cols = numeric_cols[:15] if len(numeric_cols) > 15 else numeric_cols

        for col in use_cols:
            values = ml_data_oracle.column_values(header, rows, col)
            if len(values) < 2:
                continue
            real_mean = ml_data_oracle.oracle_mean(values)
            real_stdev = ml_data_oracle.oracle_stdev(values)
            real_median = ml_data_oracle.oracle_median(values)
            real_p25 = ml_data_oracle.oracle_p25(values)
            real_p75 = ml_data_oracle.oracle_p75(values)
            real_min, real_max = min(values), max(values)
            tol = max(abs(real_mean) * 0.001, 1e-6)

            # --- Tier 1: single metric, unambiguous, both directions ---
            claims.append(_ml_single(path, col, "mean", real_mean, tol, "confirmed", 1, "oracle_mean exact match"))
            claims.append(_ml_single(path, col, "mean", real_mean * 1.5 + 10, tol, "contradicted", 1,
                                      "oracle_mean, expected deliberately 50%+ off"))
            claims.append(_ml_single(path, col, "median", real_median, max(abs(real_median) * 0.001, 1e-6),
                                      "confirmed", 1, "oracle_median exact match"))
            claims.append(_ml_single(path, col, "median", real_median - abs(real_median) * 0.6 - 5,
                                      max(abs(real_median) * 0.001, 1e-6), "contradicted", 1,
                                      "oracle_median, expected deliberately off"))
            claims.append(_ml_single(path, col, "p25", real_p25, max(abs(real_p25) * 0.001, 1e-6),
                                      "confirmed", 1, "oracle_p25 exact match"))
            claims.append(_ml_single(path, col, "p75", real_p75, max(abs(real_p75) * 0.001, 1e-6),
                                      "confirmed", 1, "oracle_p75 exact match"))
            claims.append(_ml_single(path, col, "min", real_min, 1e-9, "confirmed", 1, "oracle min() exact match"))
            claims.append(_ml_single(path, col, "max", real_max, 1e-9, "confirmed", 1, "oracle max() exact match"))

            # --- Tier 2: looser-tolerance variants (ml_data's real contract has no
            # directional comparator -- always |diff| <= tolerance -- so "tier 2"
            # variety here comes from a deliberately wide tolerance window instead) ---
            wide_tol = max(abs(real_mean) * 0.05, 1e-3)
            claims.append(_ml_single(path, col, "mean", real_mean - wide_tol * 0.5, wide_tol, "confirmed", 2,
                                      "mean within a deliberately wide 5% tolerance window"))
            claims.append(_ml_single(path, col, "mean", real_mean + wide_tol * 3, wide_tol, "contradicted", 2,
                                      "mean well outside even a deliberately wide 5% tolerance window"))

            # --- Tier 3: boundary adversarial (just inside vs. just past tolerance).
            # NOTE: an earlier version of this generator used `real_mean + tol`
            # EXACTLY for the "confirmed" case, intending diff == tolerance
            # (inclusive boundary, since the real check is `diff <= tolerance`).
            # That was WRONG -- not a production bug, a bug in THIS generator:
            # floating-point addition-then-subtraction doesn't reliably round-trip
            # exactly (confirmed directly: for a real air_quality.csv column,
            # `abs(real_mean - (real_mean + tol))` came out ~8.8e-14 LARGER than
            # `tol` itself, flipping 85 claims to a false "contradicted" that had
            # nothing to do with ml_data.py's actual logic). Using 0.999x/1.0001x
            # multipliers instead keeps both cases robustly on their intended side
            # of the boundary without resting on exact float round-tripping.
            claims.append(_ml_single(path, col, "mean", real_mean + tol * 0.999, tol, "confirmed", 3,
                                      "diff deliberately just inside the tolerance boundary (0.999x)"))
            claims.append(_ml_single(path, col, "mean", real_mean + tol * 1.0001, tol, "contradicted", 3,
                                      "diff deliberately just past the tolerance boundary (1.0001x)"))

            if len(values) >= 2 and real_stdev > 0:
                claims.append(_ml_single(path, col, "stdev", real_stdev, max(abs(real_stdev) * 0.001, 1e-6),
                                          "confirmed", 1, "oracle_stdev exact match"))
                claims.append(_ml_single(path, col, "stdev", real_stdev * 2 + 1, max(abs(real_stdev) * 0.001, 1e-6),
                                          "contradicted", 1, "oracle_stdev, expected deliberately off"))

        # --- Tier 2: compound AND claims (mean+stdev, and p25+p75) ---
        for col in use_cols[:8]:
            values = ml_data_oracle.column_values(header, rows, col)
            if len(values) < 2:
                continue
            real_mean = ml_data_oracle.oracle_mean(values)
            real_stdev = ml_data_oracle.oracle_stdev(values)
            real_p25 = ml_data_oracle.oracle_p25(values)
            real_p75 = ml_data_oracle.oracle_p75(values)
            tol = max(abs(real_mean) * 0.001, 1e-6)
            tol_s = max(abs(real_stdev) * 0.001, 1e-6)
            claims.append(_ml_compound(path, col, real_mean, tol, real_stdev, tol_s, "confirmed", 2,
                                        "both sub-checks genuinely hold"))
            claims.append(_ml_compound(path, col, real_mean, tol, real_stdev * 3 + 1, tol_s, "contradicted", 2,
                                        "mean holds, stdev sub-check deliberately false"))
            claims.append(_ml_compound(path, col, real_mean * 2 + 5, tol, real_stdev, tol_s, "contradicted", 2,
                                        "mean sub-check deliberately false, stdev holds"))

        # --- Tier 2: correlation between real column pairs (more than one pair per file) ---
        pairs = [(use_cols[i], use_cols[i + 1]) for i in range(0, min(len(use_cols) - 1, 6), 2)]
        for a, b in pairs:
            try:
                real_corr = ml_data_oracle.compute([str(path)], "correlation", a, b)
                claims.append(_ml_corr(path, a, b, real_corr, "confirmed", 2))
                claims.append(_ml_corr(path, a, b, -real_corr if abs(real_corr) > 0.1 else real_corr + 0.9,
                                        "contradicted", 2))
            except Exception:
                pass

    # --- Tier 2: multi-file (real data, repartitioned into real shards) ---
    for slug in ["air_quality", "bike_sharing", "gas_turbine_emission"]:
        s1 = ML_DATA_DIR / f"{slug}_shard1.csv"
        s2 = ML_DATA_DIR / f"{slug}_shard2.csv"
        header, rows = ml_data_oracle.read_columns([str(s1), str(s2)])
        col = None
        for c in header:
            if c.lower() in _ML_SKIP_COLS:
                continue
            vals = ml_data_oracle.column_values(header, rows, c)
            if len(vals) >= max(2, int(0.9 * len(rows))):
                col = c
                break
        if col is None:
            continue
        values = ml_data_oracle.column_values(header, rows, col)
        real_mean = ml_data_oracle.oracle_mean(values)
        tol = max(abs(real_mean) * 0.001, 1e-6)
        claims.append({
            "claim_id": _next_id("ml_data"), "domain": "ml_data", "tier": 2,
            "claim_payload": {
                "text": f"combined mean of {col} across both real shards of {slug} is {real_mean:.6g}",
                "domain": "ml_data",
                "context": {"dataset_path": [_rel(s1), _rel(s2)], "column": col, "stat": "mean",
                            "expected_value": real_mean, "tolerance": tol},
            },
            "ground_truth_verdict": "confirmed",
            "ground_truth_method": f"ml_data_oracle.compute() over both real shard files combined = {real_mean!r}",
            "provenance": f"real UCI dataset {slug}, split into two real-row shards (see PROVENANCE.md)",
        })

    # --- Tier 3: malformed-but-parseable — column present in one real file, absent in another ---
    s1 = ML_DATA_DIR / "air_quality_shard1.csv"
    other = ML_DATA_DIR / "abalone.csv"  # genuinely has no "T" column
    claims.append({
        "claim_id": _next_id("ml_data"), "domain": "ml_data", "tier": 3,
        "claim_payload": {
            "text": "mean T across a mismatched real two-file dataset is 20.0",
            "domain": "ml_data",
            "context": {"dataset_path": [_rel(s1), _rel(other)], "column": "T", "stat": "mean", "expected_value": 20.0},
        },
        "ground_truth_verdict": "undetermined",
        "ground_truth_method": "column 'T' genuinely absent from abalone.csv's real header — adapter must name this, not guess",
        "provenance": "real files air_quality_shard1.csv + abalone.csv, deliberately mismatched pairing",
    })

    return claims


def _ml_single(path, col, stat, expected, tol, verdict, tier, method) -> dict:
    return {
        "claim_id": _next_id("ml_data"), "domain": "ml_data", "tier": tier,
        "claim_payload": {
            "text": f"{stat}({col}) in {path.name} is {expected:.6g}",
            "domain": "ml_data",
            "context": {"dataset_path": _rel(path), "column": col, "stat": stat,
                        "expected_value": expected, "tolerance": tol},
        },
        "ground_truth_verdict": verdict,
        "ground_truth_method": f"ml_data_oracle.compute(): {method}",
        "provenance": f"real UCI dataset file {path.name} (see PROVENANCE.md)",
    }


def _ml_compound(path, col, mean, tol_m, stdev, tol_s, verdict, tier, method) -> dict:
    return {
        "claim_id": _next_id("ml_data"), "domain": "ml_data", "tier": tier,
        "claim_payload": {
            "text": f"{col} in {path.name}: mean is {mean:.6g} AND stdev is {stdev:.6g}",
            "domain": "ml_data",
            "context": {
                "dataset_path": _rel(path), "column": col,
                "checks": [
                    {"stat": "mean", "expected_value": mean, "tolerance": tol_m},
                    {"stat": "stdev", "expected_value": stdev, "tolerance": tol_s},
                ],
            },
        },
        "ground_truth_verdict": verdict,
        "ground_truth_method": f"ml_data_oracle, compound AND: {method}",
        "provenance": f"real UCI dataset file {path.name} (see PROVENANCE.md)",
    }


def _ml_corr(path, a, b, expected, verdict, tier) -> dict:
    return {
        "claim_id": _next_id("ml_data"), "domain": "ml_data", "tier": tier,
        "claim_payload": {
            "text": f"correlation between {a} and {b} in {path.name} is {expected:.4g}",
            "domain": "ml_data",
            "context": {"dataset_path": _rel(path), "column": a, "column_b": b, "stat": "correlation",
                        "expected_value": expected, "tolerance": max(abs(expected) * 0.01, 0.01)},
        },
        "ground_truth_verdict": verdict,
        "ground_truth_method": "ml_data_oracle.oracle_correlation() on real paired columns",
        "provenance": f"real UCI dataset file {path.name} (see PROVENANCE.md)",
    }


# =========================================================================
# fpga_embedded claim generation
# =========================================================================

_FPGA_REAL_GOOD = [
    "jiwoonl__timing.txt",
    "dawsonjon__FPGA-TX__post_synth_timing_summary.rpt",
    "Nero7991__llm.vhdl__timing_summary_A.rpt",
    "Nero7991__llm.vhdl__timing_summary_B.rpt",
    "rbarzic__nanorv32__post_synth_timing_summary.rpt",
    "David-Durst__embeddedHaskellAetherling__timing_summary.txt",
    "hdlguy__make_for_vivado__timing.rpt",
]
_FPGA_REAL_NA = [
    "scarletnova20__Vision-In-Memory-System-On-RISCV__timing_impl.txt",
    "scarletnova20__Vision-In-Memory-System-On-RISCV__timing_synth.txt",
]
_FPGA_TIMING_METRICS = ("wns_ns", "tns_ns", "whs_ns", "ths_ns", "wpws_ns", "tpws_ns")


def gen_fpga_embedded_claims() -> list[dict]:
    claims = []
    for fname in _FPGA_REAL_GOOD:
        path = FPGA_DIR / fname
        report = fpga_embedded_oracle.parse_report(str(path))
        corner_data = report.get("DEFAULT", {})
        if not corner_data:
            continue

        for metric in _FPGA_TIMING_METRICS:
            if metric not in corner_data:
                continue
            real = corner_data[metric]
            claims.append(_fpga_single(path, metric, ">=", real - 0.001, "confirmed", 1,
                                        f"oracle: real {metric}={real!r}, clears a value just below it"))
            claims.append(_fpga_single(path, metric, ">=", real + max(abs(real), 1) * 2 + 1, "contradicted", 1,
                                        f"oracle: real {metric}={real!r}, fails a much higher requirement"))
            claims.append(_fpga_single(path, metric, "<=", real + 0.001, "confirmed", 1,
                                        f"oracle: real {metric}={real!r}, clears a value just above it (<=)"))
            claims.append(_fpga_single(path, metric, "<=", max(real - abs(real) * 2 - 1, -1e6), "contradicted", 1,
                                        f"oracle: real {metric}={real!r}, fails a much lower <= requirement"))
            # Tier 3: boundary adversarial — expected_value exactly equal (==) vs an epsilon off
            claims.append(_fpga_single(path, metric, "==", real, "confirmed", 3,
                                        f"oracle: exact equality to real {metric}={real!r}"))
            claims.append(_fpga_single(path, metric, "==", real + 1e-6, "contradicted", 3,
                                        f"oracle: real {metric}={real!r}, expected off by a tiny epsilon (== has 1e-9 tolerance)"))
            claims.append(_fpga_single(path, metric, ">=", real, "confirmed", 3,
                                        f"oracle: real {metric}={real!r}, >= itself exactly (boundary-inclusive)"))
            claims.append(_fpga_single(path, metric, ">=", real + 1e-6, "contradicted", 3,
                                        f"oracle: real {metric}={real!r}, >= an infinitesimally higher value"))

        for key, val in corner_data.items():
            if key.endswith(".frequency_mhz"):
                clock = key.rsplit(".", 1)[0]
                claims.append(_fpga_clock(path, clock, val, "confirmed", 1 if fname == _FPGA_REAL_GOOD[0] else 2))
                claims.append(_fpga_clock_contradicted(path, clock, val, 2))

    # Tier 2: Nero7991's A/B pair treated as a real two-config comparison
    a_path = FPGA_DIR / "Nero7991__llm.vhdl__timing_summary_A.rpt"
    b_path = FPGA_DIR / "Nero7991__llm.vhdl__timing_summary_B.rpt"
    ra = fpga_embedded_oracle.parse_report(str(a_path))["DEFAULT"]
    rb = fpga_embedded_oracle.parse_report(str(b_path))["DEFAULT"]
    if "wns_ns" in ra and "wns_ns" in rb:
        claims.append({
            "claim_id": _next_id("fpga_embedded"), "domain": "fpga_embedded", "tier": 2,
            "claim_payload": {
                "text": f"config B's WNS ({rb['wns_ns']:.3g} ns) differs from config A's WNS ({ra['wns_ns']:.3g} ns)",
                "domain": "fpga_embedded",
                "context": {"report_path": _rel(b_path), "metric": "wns_ns", "comparator": "==",
                             "expected_value": ra["wns_ns"]},
            },
            "ground_truth_verdict": "confirmed" if abs(ra["wns_ns"] - rb["wns_ns"]) < 1e-9 else "contradicted",
            "ground_truth_method": f"oracle: A real wns_ns={ra['wns_ns']!r}, B real wns_ns={rb['wns_ns']!r}",
            "provenance": "two real, separately-committed report files from Nero7991/llm.vhdl (see PROVENANCE.md)",
        })

    # Tier 2: synthetic multi-corner fixture exercising the Corner: label mechanism (explicitly marked synthetic)
    mc_path = FPGA_DIR / "SYNTHETIC_multi_corner.rpt"
    mc_report = fpga_embedded_oracle.parse_report(str(mc_path))
    for corner in ("SLOW_MAX", "FAST_MIN"):
        if corner in mc_report and "wns_ns" in mc_report[corner]:
            real = mc_report[corner]["wns_ns"]
            claims.append({
                "claim_id": _next_id("fpga_embedded"), "domain": "fpga_embedded", "tier": 2,
                "claim_payload": {
                    "text": f"[SYNTHETIC] {corner} corner WNS clears {real - 0.01:.3g} ns",
                    "domain": "fpga_embedded",
                    "context": {"report_path": _rel(mc_path), "metric": "wns_ns", "corner": corner,
                                 "comparator": ">=", "expected_value": real - 0.01},
                },
                "ground_truth_verdict": "confirmed",
                "ground_truth_method": f"oracle on SYNTHETIC fixture: {corner} wns_ns={real!r}",
                "provenance": "SYNTHETIC fixture (evals/fixtures/vivado_timing_report.rpt) — NOT a real report, see PROVENANCE.md",
            })

    # Tier 3: real adversarial NA-valued reports — a genuinely real file the format can't answer
    for fname in _FPGA_REAL_NA:
        path = FPGA_DIR / fname
        claims.append({
            "claim_id": _next_id("fpga_embedded"), "domain": "fpga_embedded", "tier": 3,
            "claim_payload": {
                "text": f"design in {fname} meets a 1 ns setup slack requirement",
                "domain": "fpga_embedded",
                "context": {"report_path": _rel(path), "metric": "wns_ns", "comparator": ">=", "expected_value": 1.0},
            },
            "ground_truth_verdict": "undetermined",
            "ground_truth_method": "oracle: real report's Design Timing Summary data row is literally 'NA' (incomplete run) — no numeric value to compare, confirmed via fpga_embedded_oracle.parse_report() returning {}",
            "provenance": f"real, genuinely NA-valued report from scarletnova20/Vision-In-Memory-System-On-RISCV (see PROVENANCE.md)",
        })

    return claims


def _fpga_single(path, metric, comparator, expected, verdict, tier, method) -> dict:
    return {
        "claim_id": _next_id("fpga_embedded"), "domain": "fpga_embedded", "tier": tier,
        "claim_payload": {
            "text": f"{path.name}: {metric} {comparator} {expected:.6g}",
            "domain": "fpga_embedded",
            "context": {"report_path": _rel(path), "metric": metric, "comparator": comparator,
                        "expected_value": expected},
        },
        "ground_truth_verdict": verdict,
        "ground_truth_method": method,
        "provenance": f"real committed Vivado report {path.name} (see PROVENANCE.md)",
    }


def _fpga_clock(path, clock, real_freq, verdict, tier) -> dict:
    return {
        "claim_id": _next_id("fpga_embedded"), "domain": "fpga_embedded", "tier": tier,
        "claim_payload": {
            "text": f"{path.name}: clock {clock} runs at at least {real_freq - 1:.6g} MHz",
            "domain": "fpga_embedded",
            "context": {"report_path": _rel(path), "metric": "frequency_mhz", "clock": clock,
                        "comparator": ">=", "expected_value": real_freq - 1},
        },
        "ground_truth_verdict": verdict,
        "ground_truth_method": f"oracle: real {clock} frequency_mhz={real_freq!r}",
        "provenance": f"real committed Vivado report {path.name} (see PROVENANCE.md)",
    }


def _fpga_clock_contradicted(path, clock, real_freq, tier) -> dict:
    too_high = real_freq * 3 + 100
    return {
        "claim_id": _next_id("fpga_embedded"), "domain": "fpga_embedded", "tier": tier,
        "claim_payload": {
            "text": f"{path.name}: clock {clock} runs at at least {too_high:.6g} MHz",
            "domain": "fpga_embedded",
            "context": {"report_path": _rel(path), "metric": "frequency_mhz", "clock": clock,
                        "comparator": ">=", "expected_value": too_high},
        },
        "ground_truth_verdict": "contradicted",
        "ground_truth_method": f"oracle: real {clock} frequency_mhz={real_freq!r}, fails a much higher requirement",
        "provenance": f"real committed Vivado report {path.name} (see PROVENANCE.md)",
    }


# =========================================================================
# robotics claim generation (true-by-construction, independently-reasoned
# from the SAME real sourced facts robotics.py's own docstring documents —
# NOT by importing robotics.py)
# =========================================================================

# Real sourced facts (see anticassiopeia/corpus/doc{1,2,3}_*.txt and
# docs/extracted/constellation-robotics-seed.md — already-committed,
# already-sourced material, reused per task instruction, not re-fetched).
_BLUEROV2_DOC1_M = 300.0  # Aluminum housing, trust 0.8
_BLUEROV2_DOC2_M = 100.0  # trust 0.7
_BAR30_BAR = 30.0         # trust 0.85
_SEAWATER_DENSITY, _GRAVITY, _BAR_TO_PA = 1025.0, 9.80665, 1e5
_BAR30_M = _BAR30_BAR * _BAR_TO_PA / (_SEAWATER_DENSITY * _GRAVITY)  # ~298.3 m
_DECISION_THRESHOLD, _MIN_EVIDENCE_WEIGHT = 0.5, 0.3  # engine.py's own documented, public constants


def _bluerov2_verdict(depth_m: float, survives_claim: bool) -> str:
    stance1 = "supports" if (depth_m <= _BLUEROV2_DOC1_M) == survives_claim else "contradicts"
    stance2 = "supports" if (depth_m <= _BLUEROV2_DOC2_M) == survives_claim else "contradicts"
    weights = {"supports": 0.0, "contradicts": 0.0}
    for s, trust in [(stance1, 0.8), (stance2, 0.7)]:
        weights[s] += trust
    net = weights["supports"] - weights["contradicts"]
    total = weights["supports"] + weights["contradicts"]
    if total < _MIN_EVIDENCE_WEIGHT or abs(net) < _DECISION_THRESHOLD:
        return "undetermined"
    return "confirmed" if net > 0 else "contradicted"


def _bar30_verdict(depth_m: float, survives_claim: bool) -> str:
    margin = 0.05 * depth_m
    if abs(_BAR30_M - depth_m) <= margin:
        return "undetermined"  # neutral — gauge/absolute ambiguity, same as production's documented margin
    within_rating = _BAR30_M >= depth_m
    stance = "supports" if within_rating == survives_claim else "contradicts"
    weight = 0.85
    if weight < _MIN_EVIDENCE_WEIGHT or weight < _DECISION_THRESHOLD:
        return "undetermined"
    return "confirmed" if stance == "supports" else "contradicted"


def gen_robotics_claims() -> list[dict]:
    claims = []

    # BlueROV2 depth sweep: tier1 unambiguous zones, tier3 the known conflict zone.
    # Densified (step=5m, 10-500m) as part of the amendment's scale-up -- still
    # true-by-construction from the SAME two real sourced facts (DOC1=300m,
    # DOC2=100m), just many more genuinely distinct depth values asked about.
    for depth in range(10, 501, 5):
        for survives in (True, False):
            verdict = _bluerov2_verdict(depth, survives)
            tier = 3 if 100 < depth <= 300 else (2 if not survives else 1)
            verb = "survives" if survives else "fails at"
            claims.append({
                "claim_id": _next_id("robotics"), "domain": "robotics", "tier": tier,
                "claim_payload": {"text": f"BlueROV2 {verb} {depth} m depth", "domain": "robotics", "context": {}},
                "ground_truth_verdict": verdict,
                "ground_truth_method": (
                    f"independently reasoned: DOC1=300m (trust 0.8), DOC2=100m (trust 0.7), "
                    f"engine DECISION_THRESHOLD=0.5/MIN_EVIDENCE_WEIGHT=0.3 (both are this project's own "
                    f"documented, public constants, not internal adapter logic)"
                ),
                "provenance": "real sourced facts in anticassiopeia/corpus/doc{1,2}_bluerov2_excerpt.txt (reused, not re-fetched)",
            })

    # Bar30 depth sweep around the real ~298m rating, including the documented
    # 5% neutral margin. Densified (step=5m, 10-500m) same as BlueROV2 above.
    for depth in range(10, 501, 5):
        for survives in (True, False):
            verdict = _bar30_verdict(depth, survives)
            near_margin = abs(_BAR30_M - depth) <= 0.05 * depth * 1.5
            tier = 3 if near_margin else (2 if not survives else 1)
            verb = "survives" if survives else "fails at"
            claims.append({
                "claim_id": _next_id("robotics"), "domain": "robotics", "tier": tier,
                "claim_payload": {"text": f"Bar30 {verb} {depth} m depth", "domain": "robotics", "context": {}},
                "ground_truth_verdict": verdict,
                "ground_truth_method": (
                    f"independently reasoned: 30 bar -> {_BAR30_M:.1f}m via seawater density 1025 kg/m^3, "
                    f"g=9.80665 (documented public physics conversion, independently recomputed here), "
                    f"5% neutral margin (documented), trust 0.85, engine thresholds"
                ),
                "provenance": "real sourced fact in anticassiopeia/corpus/doc3_bar30_excerpt.txt (reused, not re-fetched)",
            })

    # Unsourced parts: always undetermined
    for part in ["Bar100XT", "QuSpin QZFM Gen-3"]:
        claims.append({
            "claim_id": _next_id("robotics"), "domain": "robotics", "tier": 1,
            "claim_payload": {"text": f"{part} survives 500 m depth", "domain": "robotics", "context": {}},
            "ground_truth_verdict": "undetermined",
            "ground_truth_method": "both parts documented as unsourced in Constellation's own research — no corpus exists",
            "provenance": "docs/extracted/constellation-robotics-seed.md (reused, not re-fetched)",
        })

    return claims


# =========================================================================
# research_web claim generation (true-by-construction from real, independently
# confirmed public facts — same method as the existing live_multi_candidate_*
# eval cases)
# =========================================================================

_RESEARCH_WEB_FACTS = [
    {
        "topic": "BlueROV2", "true": "BlueROV2 is a modular remotely operated underwater vehicle developed by Blue Robotics",
        "false": "BlueROV2 was developed by OpenROV",
        "absent": "BlueROV2 has a maximum operating time of 14 hours",
        "source": "https://en.wikipedia.org/wiki/BlueROV2",
    },
    {
        "topic": "ArduPilot", "true": "ArduPilot was first released in 2009",
        "false": "ArduPilot was first released in 1999",
        "absent": "ArduPilot has over 10 million lines of code",
        "source": "https://en.wikipedia.org/wiki/ArduPilot",
    },
    {
        "topic": "Raspberry Pi", "true": "The Raspberry Pi is manufactured by Sony under contract",
        "false": "The Raspberry Pi is manufactured by Samsung under contract",
        "absent": "The Raspberry Pi 5 draws exactly 1.2 watts at idle",
        "source": "https://en.wikipedia.org/wiki/Raspberry_Pi",
    },
    {
        "topic": "ESP32", "true": "The ESP32 is a microcontroller manufactured by Espressif Systems",
        "false": "The ESP32 is a microcontroller manufactured by Texas Instruments",
        "absent": "The ESP32 has a built-in hardware random number generator rated at 5 Mbps",
        "source": "https://en.wikipedia.org/wiki/ESP32",
    },
    {
        "topic": "BeagleBone", "true": "The first Beagle Board was released in 2008",
        "false": "The first Beagle Board was released in 2015",
        "absent": "The BeagleBone Black has exactly 47 GPIO pins",
        "source": "https://en.wikipedia.org/wiki/BeagleBone",
    },
    {
        "topic": "Analog Devices", "true": "Analog Devices is an American semiconductor manufacturer",
        "false": "Analog Devices is a Japanese semiconductor manufacturer",
        "absent": "Analog Devices' headquarters building has exactly 12 floors",
        "source": "https://en.wikipedia.org/wiki/Analog_Devices",
    },
    # Added in the amendment (2 more real, independently-verified topics):
    {
        "topic": "STM32", "true": "STM32 is a family of ARM Cortex-M based microcontrollers made by STMicroelectronics",
        "false": "STM32 is a family of ARM Cortex-M based microcontrollers made by Microchip Technology",
        "absent": "The STM32H7B0 consumes exactly 85 milliwatts in standby mode",
        "source": "https://en.wikipedia.org/wiki/STM32",
    },
    {
        "topic": "Xilinx", "true": "Xilinx is an American technology company",
        "false": "Xilinx is a German technology company",
        "absent": "Xilinx's first FPGA shipped with exactly 64 configurable logic blocks",
        "source": "https://en.wikipedia.org/wiki/Xilinx",
    },
]


def gen_research_web_claims() -> list[dict]:
    claims = []
    for fact in _RESEARCH_WEB_FACTS:
        claims.append({
            "claim_id": _next_id("research_web"), "domain": "research_web", "tier": 1,
            "claim_payload": {"text": fact["true"], "domain": "research_web", "context": {}},
            "ground_truth_verdict": "confirmed",
            "ground_truth_method": f"fact independently confirmed live by fetching {fact['source']} (see PROVENANCE.md)",
            "provenance": fact["source"],
        })
        claims.append({
            "claim_id": _next_id("research_web"), "domain": "research_web", "tier": 2,
            "claim_payload": {"text": fact["false"], "domain": "research_web", "context": {}},
            "ground_truth_verdict": "contradicted",
            "ground_truth_method": f"negated/altered from the real fact at {fact['source']} (see PROVENANCE.md)",
            "provenance": fact["source"],
        })
        claims.append({
            "claim_id": _next_id("research_web"), "domain": "research_web", "tier": 3,
            "claim_payload": {"text": fact["absent"], "domain": "research_web", "context": {}},
            "ground_truth_verdict": "undetermined",
            "ground_truth_method": f"plausible-sounding but confirmed ABSENT from {fact['source']} by reading the real page",
            "provenance": fact["source"],
        })
    return claims


# =========================================================================

def main():
    all_claims = []
    all_claims += gen_ml_data_claims()
    all_claims += gen_fpga_embedded_claims()
    all_claims += gen_robotics_claims()
    all_claims += gen_research_web_claims()

    out_path = REPO_ROOT / "stress_test/claims/manifest.jsonl"
    with open(out_path, "w") as f:
        for c in all_claims:
            f.write(json.dumps(c) + "\n")

    from collections import Counter
    by_domain_tier = Counter((c["domain"], c["tier"]) for c in all_claims)
    by_domain = Counter(c["domain"] for c in all_claims)
    by_verdict = Counter(c["ground_truth_verdict"] for c in all_claims)

    print(f"Total claims: {len(all_claims)}")
    print("\nBy domain:")
    for d, n in sorted(by_domain.items()):
        print(f"  {d}: {n}")
    print("\nBy (domain, tier):")
    for (d, t), n in sorted(by_domain_tier.items()):
        print(f"  {d} tier {t}: {n}")
    print("\nBy ground truth verdict:")
    for v, n in sorted(by_verdict.items()):
        print(f"  {v}: {n}")


if __name__ == "__main__":
    main()
