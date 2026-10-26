"""
Track B: the 69 category-8 "extreme/boundary-pushing" claims
(stress_test/claims/external_generated/track_b_category8_formal.json),
parked at round-2 time pending ground-truth verification and a decision
on how to route them. Both resolved since: ground truth independently
verified (track_b_verified.json, 0 undetermined -- these were deliberately
engineered to have a clear intended answer, see that file's own
generation), and routing decided as plain `searchlight` -- `substrate` has
no live web-search path at all (fixed-corpus + BYOE only), and the
compound/decompose path has its own, separate, real decomposition-fidelity
bug (see claude's own investigation note) that makes it unsafe to use
here without a fix that's out of scope for this round.

Real engine only this round -- not the full 5-competitor sweep round 2
used, to keep this scoped; same reuse-don't-reimplement discipline as
every other script in this directory (run_anti_cassiopeia() straight from
run_benchmark_round2.py, untouched).

Usage:
    PYTHONPATH=. python3 stress_test/run_track_b.py
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

from run_benchmark_round2 import run_anti_cassiopeia  # noqa: E402
from run_test1 import classify  # noqa: E402

RESULTS_DIR = REPO_ROOT / "stress_test/results"
CLAIMS_PATH = REPO_ROOT / "stress_test/claims/external_generated/track_b_category8_formal.json"
VERIFIED_PATH = REPO_ROOT / "stress_test/claims/external_generated/track_b_verified.json"
OUT_PATH = RESULTS_DIR / "track_b_raw.json"


def load_claims() -> list[dict]:
    with open(CLAIMS_PATH) as f:
        raw = {c["id"]: c for c in json.load(f)}
    with open(VERIFIED_PATH) as f:
        verified = {v["id"]: v for v in json.load(f)}
    assert set(raw) == set(verified), f"id mismatch: {set(raw) ^ set(verified)}"

    claims = []
    for cid, entry in raw.items():
        v = verified[cid]
        claims.append({
            "claim_id": cid,
            "category": entry["category"],
            "generated_by": entry["generated_by"],
            "domain": "searchlight",
            "tier": 1,
            "claim_payload": {"text": entry["claim"], "domain": "searchlight", "context": {}},
            "ground_truth_verdict": v["verified_ground_truth"],
            "ground_truth_note": v["verification_notes"],
            "verification_confidence": v["verification_confidence"],
        })
    return claims


async def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    claims = load_claims()
    results, tracker = await run_anti_cassiopeia(claims)

    by_severity: dict[str, int] = {}
    for r in results:
        by_severity[r["severity"]] = by_severity.get(r["severity"], 0) + 1

    out = {"n_claims": len(results), "severity": by_severity, "cost_usd": tracker.total_cost_usd, "scorecard": results}
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\n=== TRACK B SUMMARY ===")
    print(json.dumps({"n_claims": len(results), "severity": by_severity, "cost_usd": tracker.total_cost_usd}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
