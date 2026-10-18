"""
Stress Test #2 orchestrator: bare Nebius vs. the real Anti-Cassiopeia
pipeline, same claims (a stratified ~1,000-claim subset of Test #1's
existing 3,311-claim manifest — see generate_test2_sample.py), same
ground truth, same model.

Both paths share ONE UsageTracker and a SINGLE $4.00 budget cap (rule 2;
separate from, and smaller than, Test #1's own $6.00 cap, which this
script never touches) — a call on either path checks the same running
total, so neither path can silently blow past the shared cap just
because the other path's spend isn't visible to it.

Usage:
    PYTHONPATH=. python3 stress_test/run_test2.py --mode pilot
    PYTHONPATH=. python3 stress_test/run_test2.py --mode full --confirm-full
        (only after reviewing the pilot's printed cost estimate — rule 2)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from instrumented_client import UsageTracker  # noqa: E402
from run_test1 import run_batch, select_pilot  # noqa: E402
from run_test2_bare import run_bare_batch  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "stress_test/claims/manifest.jsonl"
SAMPLE_PATH = REPO_ROOT / "stress_test/claims/test2_sample.jsonl"
BARE_RAW_PATH = REPO_ROOT / "stress_test/results/test2_bare_raw.jsonl"
PIPELINE_RAW_PATH = REPO_ROOT / "stress_test/results/test2_pipeline_raw.jsonl"

TEST2_BUDGET_USD = 4.00


def load_sample_claims() -> list[dict]:
    """Joins stress_test/claims/test2_sample.jsonl's claim-ID pointers back
    against the full manifest to get each claim's real payload/ground
    truth — the sample file itself never duplicates that data."""
    wanted_ids = set()
    with open(SAMPLE_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                wanted_ids.add(json.loads(line)["claim_id"])

    found = {}
    with open(MANIFEST_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row["claim_id"] in wanted_ids:
                found[row["claim_id"]] = row

    missing = wanted_ids - found.keys()
    if missing:
        print(f"WARNING: {len(missing)} sample claim id(s) not found in manifest: {sorted(missing)[:5]}...")
    return [found[cid] for cid in sorted(found)]


async def run_both_paths(claims: list[dict], tag: str, tracker: UsageTracker) -> None:
    print(f"\n--- Part B: bare Nebius, {tag} ({len(claims)} claims) ---")
    await run_bare_batch(
        claims, tag=tag,
        raw_results_path=BARE_RAW_PATH,
        tracker=tracker, budget_usd=TEST2_BUDGET_USD,
    )
    print(f"\n--- Part C: real pipeline, {tag} ({len(claims)} claims) ---")
    await run_batch(
        claims, tag=tag,
        raw_results_path=PIPELINE_RAW_PATH,
        tracker=tracker, budget_usd=TEST2_BUDGET_USD,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    parser.add_argument("--n-per-domain", type=int, default=5)
    parser.add_argument(
        "--confirm-full", action="store_true",
        help="Required alongside --mode full. Only pass this after the user has "
             "explicitly authorized a full run in their own words, having already "
             "seen the pilot's real combined cost estimate (rule 2) -- not on inference alone.",
    )
    args = parser.parse_args()

    all_sample_claims = load_sample_claims()
    print(f"Loaded {len(all_sample_claims)} claims from the Test #2 sample.")

    if args.mode == "full":
        if not args.confirm_full:
            print(
                "Refusing to run --mode full without --confirm-full. Rule 2 requires "
                "explicit user go-ahead after reviewing the pilot's cost estimate first."
            )
            sys.exit(1)
        tracker = UsageTracker()
        print(f"Full Test #2 run: {len(all_sample_claims)} claims through BOTH paths, "
              f"user-authorized, shared ${TEST2_BUDGET_USD:.2f} cap.\n")
        asyncio.run(run_both_paths(all_sample_claims, tag="full", tracker=tracker))
        print(f"\nTotal combined spend (both paths): ${tracker.total_cost_usd:.6f} "
              f"of ${TEST2_BUDGET_USD:.2f} cap ({100*tracker.total_cost_usd/TEST2_BUDGET_USD:.1f}%)")
        return

    pilot = select_pilot(all_sample_claims, n_per_domain=args.n_per_domain)
    print(f"Pilot batch: {len(pilot)} claims, stratified across domains/tiers, "
          f"run through BOTH paths.\n")
    tracker = UsageTracker()
    asyncio.run(run_both_paths(pilot, tag="pilot", tracker=tracker))

    print(f"\n=== Pilot combined spend: ${tracker.total_cost_usd:.6f} "
          f"({tracker.call_count} live API calls total, both paths) ===")
    print("By-domain cost this pilot (bare + pipeline combined):")
    for domain, cost in sorted(tracker.by_domain_cost.items()):
        print(f"  {domain}: ${cost:.6f}")

    per_claim_cost = tracker.total_cost_usd / len(pilot) if pilot else 0.0
    projected_total = per_claim_cost * len(all_sample_claims)
    print(f"\n=== Extrapolation to the full {len(all_sample_claims)}-claim Test #2 sample ===")
    print(f"Pilot: {len(pilot)} claims cost ${tracker.total_cost_usd:.6f} combined "
          f"=> ${per_claim_cost:.6f}/claim average (both paths together).")
    print(f"Projected full-sample combined cost: ${projected_total:.4f} "
          f"against the ${TEST2_BUDGET_USD:.2f} cap "
          f"({100*projected_total/TEST2_BUDGET_USD:.1f}%).")
    if projected_total >= TEST2_BUDGET_USD:
        print("WARNING: projected cost meets or exceeds the cap -- do not proceed to --mode full "
              "without reconsidering sample size.")
    print("\nSTOPPING HERE per rule 2 -- waiting for explicit go-ahead before --mode full.")


if __name__ == "__main__":
    main()
