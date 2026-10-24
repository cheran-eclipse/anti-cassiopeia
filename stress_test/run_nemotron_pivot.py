"""
The Nemotron pivot (Apps and Agents track requirement): an honest,
same-harness, before/after comparison of the current default model
(openai/gpt-oss-120b) against an NVIDIA Nemotron model, reusing the
EXACT same manifest/ground-truth/classification machinery Test #1 already
built and this project already trusts (`run_test1.load_manifest`,
`select_pilot`, `run_batch`, `classify`) — no new scoring logic, no new
claim set, nothing invented for this comparison specifically.

SCOPE, stated plainly: only `robotics` and `research_web` claims are run.
`ml_data` and `fpga_embedded` make ZERO live LLM calls in the real engine
pipeline (see docs/DESIGN.md §5 — both re-derive/re-parse directly from
source, no retrieval/LLM step at all) — their verdicts are PROVABLY
invariant to which model is configured, so including them would spend
real API budget to "test" something that cannot change. Re-running them
here would not be thoroughness, it would be waste.

Usage:
    PYTHONPATH=. python3 stress_test/run_nemotron_pivot.py --mode pilot
    PYTHONPATH=. python3 stress_test/run_nemotron_pivot.py --mode full --confirm-full
        (only after reviewing the pilot's real cost + accuracy delta first)

Secret handling: NEBIUS_API_KEY loaded only inside instrumented_client.py
via dotenv_values(); this file never touches it directly.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from instrumented_client import NEMOTRON_PRICING_PER_M, UsageTracker  # noqa: E402
from run_test1 import classify, load_manifest, run_batch, select_pilot  # noqa: E402

RESULTS_DIR = REPO_ROOT / "stress_test/results"
BASELINE_MODEL = "openai/gpt-oss-120b"
BASELINE_PRICING = (0.15, 0.60)  # same constants instrumented_client.py already uses by default

#: This pilot's own hard stop -- deliberately small and separate from Test
#: #1/#2/#3's own $6/$4 caps (never touched here). $0.50/model, $1.00 total:
#: existing measured data (TEST3_REPORT.md: 128 LLM-calling claims cost
#: $0.0457 total under a comparable call pattern) puts a ~30-60-claim pilot
#: at low cents, so this cap is a safety margin, not an expected spend.
PILOT_BUDGET_PER_MODEL_USD = 0.50


_LLM_CALLING_DOMAINS = ("robotics", "research_web")


def _llm_calling_claims(claims: list[dict], domains: tuple[str, ...] = _LLM_CALLING_DOMAINS) -> list[dict]:
    return [c for c in claims if c["domain"] in domains]


async def _run_one_model(
    claims: list[dict], tag: str, model: str, pricing: tuple[float, float], budget_usd: float
) -> tuple[list[dict], UsageTracker]:
    tracker = UsageTracker()
    input_cost, output_cost = pricing
    results = await run_batch(
        claims,
        tag=tag,
        raw_results_path=RESULTS_DIR / f"nemotron_pivot_{tag}_raw.jsonl",
        bugs_path=RESULTS_DIR / "nemotron_pivot_bugs.md",
        tracker=tracker,
        budget_usd=budget_usd,
        model=model,
        input_cost_per_m=input_cost,
        output_cost_per_m=output_cost,
    )
    return results, tracker


def _per_domain_breakdown(results: list[dict]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in results:
        d = out.setdefault(r["domain"], {})
        d[r["severity"]] = d.get(r["severity"], 0) + 1
        d["_n"] = d.get("_n", 0) + 1
    return out


def _print_comparison(baseline_results: list[dict], nemotron_results: list[dict], baseline_tracker: UsageTracker, nemotron_tracker: UsageTracker, nemotron_model: str) -> None:
    base_by_id = {r["claim_id"]: r for r in baseline_results}
    nem_by_id = {r["claim_id"]: r for r in nemotron_results}
    common_ids = [r["claim_id"] for r in baseline_results if r["claim_id"] in nem_by_id]

    print(f"\n{'='*78}\nSIDE-BY-SIDE: {BASELINE_MODEL} (baseline) vs {nemotron_model}\n{'='*78}")

    base_breakdown = _per_domain_breakdown(baseline_results)
    nem_breakdown = _per_domain_breakdown(nemotron_results)
    domains = sorted(set(base_breakdown) | set(nem_breakdown))

    print(f"\n{'Domain':14s} {'n':>4s}  {'baseline correct':>18s}  {'nemotron correct':>18s}  {'delta':>7s}")
    for d in domains:
        b = base_breakdown.get(d, {})
        n = nem_breakdown.get(d, {})
        bn, nn = b.get("_n", 0), n.get("_n", 0)
        b_correct = b.get("correct", 0)
        n_correct = n.get("correct", 0)
        b_pct = 100 * b_correct / bn if bn else 0.0
        n_pct = 100 * n_correct / nn if nn else 0.0
        print(f"{d:14s} {bn:>4d}  {b_correct:>3d}/{bn:<3d} ({b_pct:5.1f}%)  {n_correct:>3d}/{nn:<3d} ({n_pct:5.1f}%)  {n_pct-b_pct:+6.1f}%")

    print("\nPer-claim disagreements (where the two models landed on different verdicts for the SAME claim):")
    disagreements = 0
    for cid in common_ids:
        b, n = base_by_id[cid], nem_by_id[cid]
        if b["predicted_verdict"] != n["predicted_verdict"]:
            disagreements += 1
            print(
                f"  {cid:28s} domain={b['domain']:14s} truth={b['ground_truth_verdict']:13s} "
                f"baseline={b['predicted_verdict']:13s}({b['severity']:17s}) "
                f"nemotron={n['predicted_verdict']:13s}({n['severity']:17s})"
            )
    if disagreements == 0:
        print("  none — both models reached the identical verdict on every claim in this pilot.")

    print(f"\nCost -- baseline ({BASELINE_MODEL}): ${baseline_tracker.total_cost_usd:.6f} "
          f"({baseline_tracker.call_count} calls, {baseline_tracker.total_prompt_tokens}+{baseline_tracker.total_completion_tokens} tok)")
    print(f"Cost -- nemotron ({nemotron_model}): ${nemotron_tracker.total_cost_usd:.6f} "
          f"({nemotron_tracker.call_count} calls, {nemotron_tracker.total_prompt_tokens}+{nemotron_tracker.total_completion_tokens} tok)")
    print(f"Combined pilot cost: ${baseline_tracker.total_cost_usd + nemotron_tracker.total_cost_usd:.6f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    parser.add_argument("--n-per-domain", type=int, default=15, help="pilot only")
    parser.add_argument(
        "--nemotron-model", default="nvidia/nemotron-3-super-120b-a12b",
        choices=sorted(NEMOTRON_PRICING_PER_M),
        help="which Nemotron variant to run as the comparison/candidate model",
    )
    parser.add_argument(
        "--domains", nargs="+", choices=list(_LLM_CALLING_DOMAINS), default=list(_LLM_CALLING_DOMAINS),
        help="restrict the batch to these domain(s) -- e.g. --domains research_web for a domain-focused "
             "pilot without spending calls re-confirming an already-settled domain",
    )
    parser.add_argument("--confirm-full", action="store_true")
    args = parser.parse_args()

    if args.nemotron_model not in NEMOTRON_PRICING_PER_M:
        print(f"No pricing known for {args.nemotron_model!r} — refusing to run with an unpriced model.")
        sys.exit(1)
    nemotron_pricing = NEMOTRON_PRICING_PER_M[args.nemotron_model]

    all_claims = load_manifest()
    llm_claims = _llm_calling_claims(all_claims, tuple(args.domains))
    print(
        f"Loaded {len(all_claims)} total manifest claims; {len(llm_claims)} match --domains {args.domains} "
        f"and actually make a live LLM call in the real pipeline (ml_data/fpga_embedded are always "
        f"excluded regardless of --domains — see module docstring for why)."
    )

    if args.mode == "full":
        if not args.confirm_full:
            print("Refusing --mode full without --confirm-full (requires reviewing the pilot's cost/accuracy first).")
            sys.exit(1)
        batch = llm_claims
        tag_suffix = "full"
        budget = max(PILOT_BUDGET_PER_MODEL_USD, 0.01 * len(batch))  # generous per-model cap for the real run
    else:
        batch = select_pilot(llm_claims, n_per_domain=args.n_per_domain)
        tag_suffix = "pilot"
        budget = PILOT_BUDGET_PER_MODEL_USD

    print(f"Batch: {len(batch)} claims ({tag_suffix}).\n")

    print(f"--- Running baseline: {BASELINE_MODEL} ---")
    baseline_results, baseline_tracker = asyncio.run(
        _run_one_model(batch, f"baseline_{tag_suffix}", BASELINE_MODEL, BASELINE_PRICING, budget)
    )

    print(f"\n--- Running candidate: {args.nemotron_model} ---")
    nemotron_results, nemotron_tracker = asyncio.run(
        _run_one_model(batch, f"nemotron_{tag_suffix}", args.nemotron_model, nemotron_pricing, budget)
    )

    _print_comparison(baseline_results, nemotron_results, baseline_tracker, nemotron_tracker, args.nemotron_model)

    if tag_suffix == "pilot":
        full_budget_estimate_base = (baseline_tracker.total_cost_usd / len(batch)) * len(llm_claims) if batch else 0.0
        full_budget_estimate_nem = (nemotron_tracker.total_cost_usd / len(batch)) * len(llm_claims) if batch else 0.0
        print(f"\nExtrapolated full-harness cost (robotics+research_web, {len(llm_claims)} claims):")
        print(f"  baseline (~{BASELINE_MODEL}):   ${full_budget_estimate_base:.4f}")
        print(f"  nemotron (~{args.nemotron_model}): ${full_budget_estimate_nem:.4f}")
        print(f"  combined:                      ${full_budget_estimate_base + full_budget_estimate_nem:.4f}")
        print("\nNot proceeding to the full run automatically -- rerun with --mode full --confirm-full after reviewing this.")


if __name__ == "__main__":
    main()
