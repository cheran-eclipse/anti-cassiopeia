"""
Offline relabelling of ml_data ground truth (no API spend, no network).

Background (documented in anticassiopeia/domains/ml_data.py): air_quality.csv
uses -200 as its missing-value marker. The adapter was fixed to skip it, but
the manifest's air_quality ground truth was generated BEFORE that fix, with
-200 counted as a real reading, and was never regenerated. This script:

1. Recomputes the verdict of every ml_data claim in the 1,000-claim sample
   with stress_test/oracles/ml_data_oracle.py (the independent oracle, which
   skips the sentinel) and compares it with the recorded ground truth.
   Rule (same as the manifest's own): a statistic is confirmed iff
   |oracle value - expected_value| <= tolerance; a compound claim is
   confirmed iff every part is.
2. Writes an OVERLAY of corrected labels (manifest.jsonl is not edited).
3. Re-runs the CURRENT engine (real MLDataAdapter, offline) on the
   disagreeing claims, and on all 872 file claims as a check that nothing
   else moved.
4. Re-scores every system from its SAVED raw results against the
   corrected labels, for the 872 file claims (ml_data + fpga_embedded),
   using run_test1.classify() unchanged, and prints old against corrected.

One row per claim per system: the LAST row for a claim id in that system's
raw file (this reproduces the headline Test #3 table exactly: pipeline
99.9/0.0, bare 17.7/4.1/78.2, generic RAG 36.2/18.3/45.4, Perplexity
10.1/3.5/86.4, code-exec 99.1/0.5).

Usage:
    PYTHONPATH=. python3 stress_test/rescore_corrected_labels.py
"""

from __future__ import annotations

import asyncio
import collections
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from anticassiopeia.core import Claim, VerificationEngine  # noqa: E402
from anticassiopeia.domains.fpga_embedded import FPGAEmbeddedAdapter  # noqa: E402
from anticassiopeia.domains.ml_data import MLDataAdapter  # noqa: E402
from oracles import ml_data_oracle  # noqa: E402
from run_test1 import classify  # noqa: E402

MANIFEST = REPO_ROOT / "stress_test/claims/manifest.jsonl"
SAMPLE = REPO_ROOT / "stress_test/claims/test2_sample.jsonl"
RESULTS = REPO_ROOT / "stress_test/results"
OVERLAY = REPO_ROOT / "stress_test/claims/corrected_labels_overlay.jsonl"
OUT_JSON = RESULTS / "corrected_labels_rescore.json"
OUT_MD = RESULTS / "corrected_labels_rescore.md"

FILE_DOMAINS = ("ml_data", "fpga_embedded")
CANONICAL = ("confirmed", "contradicted", "undetermined")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def paths_of(ctx: dict) -> list[str]:
    p = ctx["dataset_path"]
    return p if isinstance(p, list) else [p]


def oracle_verdict(claim: dict) -> tuple[str, list[dict]]:
    """Corrected verdict plus the per-part oracle values behind it."""
    ctx = claim["claim_payload"]["context"]
    parts = ctx["checks"] if "checks" in ctx else [ctx]
    detail = []
    for part in parts:
        v = ml_data_oracle.compute(paths_of(ctx), part["stat"], ctx["column"], part.get("column_b", ctx.get("column_b")))
        ok = abs(v - part["expected_value"]) <= part["tolerance"]
        detail.append({"stat": part["stat"], "oracle_value": v, "claimed_value": part["expected_value"],
                       "tolerance": part["tolerance"], "holds": ok})
    return ("confirmed" if all(d["holds"] for d in detail) else "contradicted"), detail


async def engine_verdicts(claims: list[dict]) -> dict[str, str]:
    engine = VerificationEngine(domains={"ml_data": MLDataAdapter(), "fpga_embedded": FPGAEmbeddedAdapter()})
    out = {}
    for c in claims:
        try:
            out[c["claim_id"]] = (await engine.verify(Claim(**c["claim_payload"]))).state.value
        except Exception as exc:  # noqa: BLE001 -- a crash is a result
            out[c["claim_id"]] = f"CRASH:{type(exc).__name__}"
    return out


def rescore_row(row: dict, truth: str) -> str:
    pred = row.get("predicted_verdict")
    if pred == "declined":
        pred = "undetermined"
    if pred in CANONICAL:
        return classify(pred, truth)
    return row["severity"]  # crash / skipped / unparseable / other: not a verdict, unchanged


def tally(sevs: list[str]) -> dict:
    c = collections.Counter(sevs)
    scored = len(sevs) - c.get("skipped", 0)
    correct, danger = c.get("correct", 0), c.get("dangerous", 0)
    lo, hi = wilson(correct, correct + danger)
    return {"n": len(sevs), "scored": scored, "correct": correct, "dangerous": danger,
            "conservative_miss": c.get("conservative_miss", 0),
            "other_or_crash": scored - correct - danger - c.get("conservative_miss", 0),
            "skipped": c.get("skipped", 0),
            "correct_pct": 100 * correct / scored if scored else float("nan"),
            "dangerous_pct": 100 * danger / scored if scored else float("nan"),
            "precision_when_answering": correct / (correct + danger) if correct + danger else None,
            "precision_ci95": [lo, hi] if correct + danger else None}


def main() -> None:
    manifest = {c["claim_id"]: c for c in load_jsonl(MANIFEST)}
    sample_ids = [r["claim_id"] for r in load_jsonl(SAMPLE)]
    file_claims = [manifest[i] for i in sample_ids if manifest[i]["domain"] in FILE_DOMAINS]
    ml_claims = [c for c in file_claims if c["domain"] == "ml_data"]
    assert len(file_claims) == 872, len(file_claims)

    # 1. oracle verdict for every ml_data claim; disagreements with the record
    overlay, disagree = [], []
    for c in ml_claims:
        v, detail = oracle_verdict(c)
        if v != c["ground_truth_verdict"]:
            disagree.append(c)
            overlay.append({
                "claim_id": c["claim_id"], "domain": c["domain"], "tier": c["tier"],
                "recorded_ground_truth": c["ground_truth_verdict"], "corrected_ground_truth": v,
                "datasets": [Path(p).name for p in paths_of(c["claim_payload"]["context"])],
                "method": ("stress_test/oracles/ml_data_oracle.py recomputation (skips the dataset's "
                           "missing-value sentinel); confirmed iff every part is within its tolerance"),
                "oracle_detail": detail,
            })
    with open(OVERLAY, "w") as f:
        for r in overlay:
            f.write(json.dumps(r) + "\n")
    by_file = collections.Counter(d for r in overlay for d in r["datasets"])
    print(f"ml_data claims whose recorded label disagrees with the oracle: {len(overlay)} "
          f"(by file: {dict(by_file)}); overlay -> {OVERLAY}")
    corrected = {r["claim_id"]: r["corrected_ground_truth"] for r in overlay}
    flips = collections.Counter((r["recorded_ground_truth"], r["corrected_ground_truth"]) for r in overlay)
    print("label changes (recorded -> corrected):", dict(flips))

    # 2. current engine, offline
    verdicts = asyncio.run(engine_verdicts(file_claims))
    full_truth = {c["claim_id"]: corrected.get(c["claim_id"], c["ground_truth_verdict"]) for c in file_claims}
    on_disagree = {i: verdicts[i] for i in corrected}
    agree_corrected = sum(on_disagree[i] == corrected[i] for i in corrected)
    agree_recorded = sum(on_disagree[i] == manifest[i]["ground_truth_verdict"] for i in corrected)
    print(f"current engine on the {len(corrected)} claims: matches corrected label {agree_corrected}, "
          f"matches old recorded label {agree_recorded}")
    elsewhere = [c["claim_id"] for c in file_claims
                 if c["claim_id"] not in corrected and verdicts[c["claim_id"]] != c["ground_truth_verdict"]]
    print(f"current engine on the other {872 - len(corrected)} file claims: "
          f"{len(elsewhere)} differ from their recorded label {elsewhere[:10]}")

    # 3. rescore every system from its saved raw rows
    file_ids = {c["claim_id"] for c in file_claims}

    def last_rows(name: str) -> dict[str, dict]:
        d: dict[str, dict] = {}
        for r in load_jsonl(RESULTS / f"{name}_raw.jsonl"):
            if r["claim_id"] in file_ids:
                d[r["claim_id"]] = r
        return d

    systems = {
        "Pipeline (saved run, old adapter)": last_rows("test2_pipeline"),
        "Bare Nebius": last_rows("test2_bare"),
        "Generic RAG": last_rows("test3_generic_rag"),
        "Perplexity": last_rows("test3_perplexity"),
        "Tavily+Gemini (scored claims only)": last_rows("test3_tavily_gemini"),
        "Code-exec": last_rows("test3_codeexec"),
    }
    # Nebius-agent never runs ml_data/fpga: its results there are the pipeline's, copied.
    systems["Nebius-agent (ml/fpga = copy of pipeline)"] = systems["Pipeline (saved run, old adapter)"]

    report: dict[str, dict] = {}
    for name, rows in systems.items():
        old = [r["severity"] for r in rows.values()]
        new = [rescore_row(r, full_truth[cid]) for cid, r in rows.items()]
        changed = [cid for (cid, r), o, n in zip(rows.items(), old, new) if o != n]
        report[name] = {"old": tally(old), "corrected": tally(new), "claims_whose_score_changed": changed}

    # current engine re-run scored on the corrected labels (all 872)
    old_sev = [classify(verdicts[c["claim_id"]], c["ground_truth_verdict"]) if verdicts[c["claim_id"]] in CANONICAL
               else "crash" for c in file_claims]
    new_sev = [classify(verdicts[c["claim_id"]], full_truth[c["claim_id"]]) if verdicts[c["claim_id"]] in CANONICAL
               else "crash" for c in file_claims]
    report["Pipeline (current engine re-run)"] = {"old": tally(old_sev), "corrected": tally(new_sev),
                                                   "claims_whose_score_changed": [
                                                       c["claim_id"] for c, o, n in zip(file_claims, old_sev, new_sev) if o != n]}

    summary = {"n_file_claims": 872, "n_relabelled": len(overlay), "label_flips": {f"{a}->{b}": n for (a, b), n in flips.items()},
               "relabelled_by_file": dict(by_file),
               "current_engine_on_relabelled": {"matches_corrected": agree_corrected, "matches_old_label": agree_recorded},
               "current_engine_other_file_claims_differing_from_record": elsewhere,
               "systems": report}
    with open(OUT_JSON, "w") as f:
        json.dump(summary, f, indent=1)

    lines = ["| System | n scored | Correct old -> corrected | Dangerous old -> corrected | "
             "Precision when answering old -> corrected | Claims whose score changed |", "|---|---|---|---|---|---|"]
    for name, r in report.items():
        o, n = r["old"], r["corrected"]

        def prec(t):
            return f"{100 * t['precision_when_answering']:.1f}%" if t["precision_when_answering"] is not None else "n/a"
        lines.append(f"| {name} | {o['scored']} | {o['correct_pct']:.1f}% -> {n['correct_pct']:.1f}% "
                     f"({o['correct']} -> {n['correct']}) | {o['dangerous_pct']:.1f}% -> {n['dangerous_pct']:.1f}% "
                     f"({o['dangerous']} -> {n['dangerous']}) | {prec(o)} -> {prec(n)} | "
                     f"{len(r['claims_whose_score_changed'])} |")
    OUT_MD.write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))
    print(f"\nwritten: {OUT_JSON}, {OUT_MD}")


if __name__ == "__main__":
    main()
