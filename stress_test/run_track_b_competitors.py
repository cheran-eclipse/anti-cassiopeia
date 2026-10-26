"""
Track B competitor sweep: the same 5 competitor variants round 2 used,
against Track B's 69 category-8 claims -- decided open by the project
owner ("is the comparison required for it or not"), resolved: yes, since
these claims are architecturally identical in SHAPE to Track A (free-text
claims through searchlight) -- no new infrastructure (no "document
parsing API" or anything else) is actually needed; the same harness
functions round2 reused apply unchanged.

Reuses Anti-Cassiopeia's own results already captured in
stress_test/results/track_b_raw.json (run_track_b.py) rather than
re-running the real engine a second time -- only the 5 competitors run
here. Same domain-patch convention as run_benchmark_round2.py's
_for_competitor_harness() (un-migrated competitor harness still expects
the OLD domain string "research_web").

Usage:
    PYTHONPATH=. python3 stress_test/run_track_b_competitors.py
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

from instrumented_client import UsageTracker  # noqa: E402
from run_test1 import classify  # noqa: E402
from run_test3_bare_model import run_bare_model_batch  # noqa: E402
from run_test3_generic_rag import run_generic_rag_batch  # noqa: E402
from run_test3_nebius_agent import run_nebius_agent_batch  # noqa: E402
from run_test3_perplexity import run_perplexity_batch  # noqa: E402
from run_test3_tavily_gemini import run_tavily_gemini_batch  # noqa: E402
from run_track_b import load_claims  # noqa: E402

RESULTS_DIR = REPO_ROOT / "stress_test/results"
AC_RESULTS_PATH = RESULTS_DIR / "track_b_raw.json"
OUT_PATH = RESULTS_DIR / "track_b_competitors_raw.json"

ROUND2_NEBIUS_COMPETITOR_SUBCAP_USD = 3.00


def _for_competitor_harness(claims: list[dict]) -> list[dict]:
    patched = []
    for c in claims:
        c2 = dict(c)
        c2["domain"] = "research_web"
        c2["claim_payload"] = {**c["claim_payload"], "domain": "research_web"}
        patched.append(c2)
    return patched


async def main() -> None:
    claims = load_claims()
    competitor_claims = _for_competitor_harness(claims)

    with open(AC_RESULTS_PATH) as f:
        ac_data = json.load(f)
    ac_by_id = {r["claim_id"]: r for r in ac_data["scorecard"]}

    tag = "track_b"
    nebius_tracker = UsageTracker()

    print("--- Variant 2: bare model ---")
    bare_model_results = await run_bare_model_batch(
        competitor_claims, tag=tag, tracker=nebius_tracker, budget_usd=ROUND2_NEBIUS_COMPETITOR_SUBCAP_USD,
        raw_results_path=RESULTS_DIR / f"benchmark_{tag}_bare_model_raw.jsonl",
    )
    print("\n--- Variant 3: Nebius-agent ---")
    nebius_agent_results = await run_nebius_agent_batch(
        competitor_claims, tag=tag, tracker=nebius_tracker, budget_usd=ROUND2_NEBIUS_COMPETITOR_SUBCAP_USD,
        raw_results_path=RESULTS_DIR / f"benchmark_{tag}_nebius_agent_raw.jsonl",
    )
    print("\n--- Variant 4: generic RAG ---")
    generic_rag_results = await run_generic_rag_batch(
        competitor_claims, tag=tag, tracker=nebius_tracker, budget_usd=ROUND2_NEBIUS_COMPETITOR_SUBCAP_USD,
        raw_results_path=RESULTS_DIR / f"benchmark_{tag}_generic_rag_raw.jsonl",
    )
    print("\n--- Variant 5: Perplexity ---")
    perplexity_results = await run_perplexity_batch(
        competitor_claims, tag=tag, raw_results_path=RESULTS_DIR / f"benchmark_{tag}_perplexity_raw.jsonl",
    )
    print("\n--- Variant 6: Tavily + Gemini ---")
    tavily_gemini_results = await run_tavily_gemini_batch(
        competitor_claims, tag=tag, raw_results_path=RESULTS_DIR / f"benchmark_{tag}_tavily_gemini_raw.jsonl",
    )

    def _find(results, claim_id):
        return next((r for r in results if r["claim_id"] == claim_id), None)

    scorecard = []
    for c in claims:
        cid = c["claim_id"]
        ac_row = ac_by_id[cid]
        bm = _find(bare_model_results, cid)
        na = _find(nebius_agent_results, cid)
        gr = _find(generic_rag_results, cid)
        pp = _find(perplexity_results, cid)
        tg = _find(tavily_gemini_results, cid)
        scorecard.append({
            "claim_id": cid,
            "category": c["category"],
            "generated_by": c["generated_by"],
            "claim_text": c["claim_payload"]["text"],
            "ground_truth": c["ground_truth_verdict"],
            "anti_cassiopeia": {"predicted": ac_row["predicted_verdict"], "severity": ac_row["severity"]},
            "competitors": {
                "bare_model": {"predicted": bm["predicted_verdict"], "severity": bm["severity"]} if bm else None,
                "nebius_agent": {"predicted": na["predicted_verdict"], "severity": na["severity"]} if na else None,
                "generic_rag": {"predicted": gr["predicted_verdict"], "severity": gr["severity"]} if gr else None,
                "perplexity": {"predicted": pp["predicted_verdict"], "severity": pp["severity"]} if pp else None,
                "tavily_gemini": {"predicted": tg["predicted_verdict"], "severity": tg["severity"]} if tg else None,
            },
        })

    perplexity_cost = sum(r["cost_usd"] for r in perplexity_results)
    gemini_cost = sum(r["gemini_cost_usd"] for r in tavily_gemini_results)
    tavily_calls = sum(1 for r in tavily_gemini_results if r["predicted_verdict"] != "SKIPPED_QUOTA")

    out = {
        "n_claims": len(scorecard),
        "scorecard": scorecard,
        "budget": {
            "nebius_competitors_usd": nebius_tracker.total_cost_usd,
            "perplexity_usd": perplexity_cost,
            "tavily_calls": tavily_calls,
            "gemini_usd": gemini_cost,
        },
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    print("\n=== TRACK B COMPETITORS SUMMARY ===")
    for name in ["bare_model", "nebius_agent", "generic_rag", "perplexity", "tavily_gemini"]:
        sevs: dict[str, int] = {}
        for row in scorecard:
            sev = row["competitors"][name]["severity"] if row["competitors"][name] else "missing"
            sevs[sev] = sevs.get(sev, 0) + 1
        print(f"{name}: {sevs}")
    print(json.dumps(out["budget"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
