"""
Root-cause investigation: re-run round 2's category-1 misses (11
conservative + 1 dangerous) live, capturing FULL evidence/reasoning this
time -- round 2's own scorecard only kept predicted/severity (the same
gap flagged for the 3 dangerous misses in BENCHMARK_ROUND2_REPORT.md).
Not a re-run of the whole round; just the 12 claims that need root-
causing before any threshold or stance-logic change.

Usage:
    PYTHONPATH=. python3 stress_test/investigate_cat1_misses.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO_ROOT / ".env", override=False)

from run_benchmark_round2 import load_claims, run_anti_cassiopeia  # noqa: E402

RESULTS_DIR = REPO_ROOT / "stress_test/results"
OUT_PATH = RESULTS_DIR / "round2_cat1_miss_investigation.json"

TARGET_IDS = {
    "chatgpt-001", "chatgpt-030", "chatgpt-031",
    "gemini-001", "gemini-011", "gemini-022", "gemini-023",
    "gemini-032", "gemini-043", "gemini-051",
    "perplexity-010",
    "gemini-012",  # the one dangerous cat-1 miss, included for comparison
}


async def main() -> None:
    all_claims = load_claims()
    targets = [c for c in all_claims if c["claim_id"] in TARGET_IDS]
    assert len(targets) == len(TARGET_IDS), f"expected {len(TARGET_IDS)}, found {len(targets)}"

    results, tracker = await run_anti_cassiopeia(targets)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n=== wrote {len(results)} full results to {OUT_PATH} ===")
    print(f"total cost: ${tracker.total_cost_usd:.6f}")


if __name__ == "__main__":
    asyncio.run(main())
