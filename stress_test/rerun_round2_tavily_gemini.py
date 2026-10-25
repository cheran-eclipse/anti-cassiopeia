"""
Round 2, Erratum 1 fix verification: re-run ONLY the Tavily+Gemini
competitor across all 102 claims, now that run_test3_tavily_gemini.py's
circuit breaker distinguishes a real per-minute rate limit (retriable)
from a genuinely permanent per-day cap (still a hard stop, unchanged).

Does not touch Anti-Cassiopeia's own run or the other 4 competitors --
their original round 2 results stand. Writes a SEPARATE raw file
(does not overwrite the original, erratum-documented
benchmark_round2_tavily_gemini_raw.jsonl) so the original broken run
stays on record alongside this fix's real result.

Usage:
    PYTHONPATH=. python3 stress_test/rerun_round2_tavily_gemini.py
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

from run_benchmark_round2 import load_claims, _for_competitor_harness  # noqa: E402
from run_test1 import classify  # noqa: E402
from run_test3_tavily_gemini import run_tavily_gemini_batch  # noqa: E402

RESULTS_DIR = REPO_ROOT / "stress_test/results"
FIXED_RAW_PATH = RESULTS_DIR / "benchmark_round2_tavily_gemini_fixed_raw.jsonl"
FIXED_SCORECARD_PATH = RESULTS_DIR / "benchmark_round2_tavily_gemini_fixed_scorecard.json"


async def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if FIXED_RAW_PATH.exists():
        FIXED_RAW_PATH.unlink()

    all_claims = load_claims()
    competitor_claims = _for_competitor_harness(all_claims)

    results = await run_tavily_gemini_batch(
        competitor_claims, tag="round2-fixed", raw_results_path=FIXED_RAW_PATH,
    )

    scored = [r for r in results if r["predicted_verdict"] not in ("CRASH", "SKIPPED_QUOTA")]
    skipped = [r for r in results if r["predicted_verdict"] == "SKIPPED_QUOTA"]
    crashed = [r for r in results if r["predicted_verdict"] == "CRASH"]
    by_severity: dict[str, int] = {}
    for r in scored:
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1

    summary = {
        "n_claims": len(results),
        "n_scored": len(scored),
        "n_skipped_quota": len(skipped),
        "n_crashed": len(crashed),
        "severity": by_severity,
        "total_gemini_cost_usd": sum(r["gemini_cost_usd"] for r in results),
    }
    with open(FIXED_SCORECARD_PATH, "w") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2)

    print("\n=== ROUND 2 TAVILY+GEMINI RE-RUN SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
