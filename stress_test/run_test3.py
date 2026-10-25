"""
Stress Test #3 orchestrator: pilot (then, after explicit go-ahead, full)
run of FIVE variants -- bare model (2, Test #3's own re-run of Test #2's
already-built baseline), Nebius-agent (3), generic RAG (4), Perplexity
(5), Tavily+Gemini (6) -- against a stratified subset of Test #2's
existing 1,000-claim sample, so results are exactly apples-to-apples with
the already-measured real pipeline (1) from Test #2. No new claims are
generated.

Variant 2 (bare model) was added after the causal-claim stance fix round
(see claude/ANTI_CASSIOPEIA_COMPETITIVE_BENCHMARK_PROTOCOL.md) -- it is a
thin wrapper around run_test2_bare.py's pre-existing run_bare_batch(),
re-run here so its numbers come from the SAME claim set/run as variants
3-6 in a given Test #3 invocation, not just inherited from Test #2's own,
separately-timed run. It is a REAL Nebius call per claim (openai/gpt-oss-120b,
no retrieval at all) -- its cost is real and tracked in the SAME Nebius
sub-cap pool as variants 3/4 below, never reported as zero just because
retrieval itself is free for this one.

Budget tracks THREE separate things, never summed into one number:
- Nebius (variants 2, 3, and 4 all call it): checked against a $5.00
  sub-cap for this test specifically, itself well within the ~$19.6
  remaining under this project's $20 total Nebius cap (Test #1 spent
  $0.216879, Test #2 spent $0.183357 -- $0.400236 total so far).
- Perplexity (variant 5): real dollar cost from its own already-
  provisioned free credits, tracked but not counted against the $20.
- Tavily (variant 6's search leg): call count only, Tavily's Search API
  returns no dollar figure (flat per-call credits) -- drawn from its own
  already-provisioned free Researcher-tier credits.
- Gemini (variant 6's completion leg): real dollar cost, a separate
  provider, tracked on its own.

Usage:
    PYTHONPATH=. python3 stress_test/run_test3.py --mode pilot
    PYTHONPATH=. python3 stress_test/run_test3.py --mode full --confirm-full
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

# FOUND BUG (external review, 2026-10-25): this script constructs a real
# ResearchWebAdapter (directly or via run_test1.build_engine), whose
# research_web.py _tavily_search() reads os.environ.get("TAVILY_API_KEY")
# directly -- NOT dotenv_values(). Every script in this directory loaded
# secrets via dotenv_values(".env") for ITS OWN direct provider calls
# (Perplexity/Tavily/Gemini) without ever populating the real process
# environment -- so Tavily (research_web.py's PRIMARY search backend) has
# been silently returning [] (missing key -> empty list, by that
# function's own documented contract) in every prior run of this
# project's stress-test history, falling back to the much weaker DDG/
# Wikipedia backends every time. The real production server
# (api/server.py) was never affected -- it already calls
# load_dotenv(override=False) at import time. Fixed at the source here:
# load it into the real environment before anything downstream reads it.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO_ROOT / ".env", override=False)

from instrumented_client import UsageTracker  # noqa: E402
from run_test1 import select_pilot  # noqa: E402
from run_test2 import load_sample_claims  # noqa: E402
from run_test3_bare_model import RAW_RESULTS_PATH as BARE_MODEL_RAW_PATH  # noqa: E402
from run_test3_bare_model import run_bare_model_batch  # noqa: E402
from run_test3_generic_rag import RAW_RESULTS_PATH as GENERIC_RAG_RAW_PATH  # noqa: E402
from run_test3_generic_rag import run_generic_rag_batch  # noqa: E402
from run_test3_nebius_agent import RAW_RESULTS_PATH as NEBIUS_AGENT_RAW_PATH  # noqa: E402
from run_test3_nebius_agent import _PROPOSE_ONLY_DOMAINS, run_nebius_agent_batch  # noqa: E402
from run_test3_perplexity import RAW_RESULTS_PATH as PERPLEXITY_RAW_PATH  # noqa: E402
from run_test3_perplexity import run_perplexity_batch  # noqa: E402
from run_test3_tavily_gemini import RAW_RESULTS_PATH as TAVILY_GEMINI_RAW_PATH  # noqa: E402
from run_test3_tavily_gemini import run_tavily_gemini_batch  # noqa: E402

NEBIUS_TEST3_SUBCAP_USD = 5.00
NEBIUS_ALREADY_SPENT_TEST1_TEST2 = 0.216879 + 0.183357


async def run_all_five(claims: list[dict], tag: str) -> dict:
    nebius_tracker = UsageTracker()

    print(f"\n--- Variant 2: bare model (no retrieval at all), {tag} ---")
    bare_model_results = await run_bare_model_batch(
        claims, tag=tag, raw_results_path=BARE_MODEL_RAW_PATH,
        tracker=nebius_tracker, budget_usd=NEBIUS_TEST3_SUBCAP_USD,
    )

    print(f"\n--- Variant 3: Nebius-agent (retrieval+propose, no verify), {tag} ---")
    propose_claims = [c for c in claims if c["domain"] in _PROPOSE_ONLY_DOMAINS]
    nebius_agent_results = await run_nebius_agent_batch(
        claims, tag=tag, raw_results_path=NEBIUS_AGENT_RAW_PATH,
        tracker=nebius_tracker, budget_usd=NEBIUS_TEST3_SUBCAP_USD,
    )

    print(f"\n--- Variant 4: self-built generic RAG, {tag} ---")
    generic_rag_results = await run_generic_rag_batch(
        claims, tag=tag, raw_results_path=GENERIC_RAG_RAW_PATH,
        tracker=nebius_tracker, budget_usd=NEBIUS_TEST3_SUBCAP_USD,
    )

    print(f"\n--- Variant 5: Perplexity (perplexity/sonar via /v1/responses), {tag} ---")
    perplexity_results = await run_perplexity_batch(claims, tag=tag, raw_results_path=PERPLEXITY_RAW_PATH)

    print(f"\n--- Variant 6: Tavily search + Gemini completion, {tag} ---")
    tavily_gemini_results = await run_tavily_gemini_batch(claims, tag=tag, raw_results_path=TAVILY_GEMINI_RAW_PATH)

    return {
        "bare_model": bare_model_results,
        "nebius_agent": nebius_agent_results,
        "generic_rag": generic_rag_results,
        "perplexity": perplexity_results,
        "tavily_gemini": tavily_gemini_results,
        "nebius_tracker": nebius_tracker,
        "n_propose_claims": len(propose_claims),
    }


def _per_domain_mean(records: list[dict], cost_field: str) -> dict[str, float]:
    by_domain: dict[str, list[float]] = {}
    for r in records:
        by_domain.setdefault(r["domain"], []).append(r[cost_field])
    return {d: statistics.mean(vals) for d, vals in by_domain.items()}


def _extrapolate(per_domain_rate: dict[str, float], composition: dict[str, float], m: int) -> float:
    return sum(per_domain_rate.get(d, 0.0) * frac * m for d, frac in composition.items())


def _print_pilot_extrapolation(pilot: list[dict], batches: dict, all_sample_claims: list[dict]) -> None:
    n_pilot = len(pilot)
    n_propose = batches["n_propose_claims"]

    # The PILOT is stratified EQUALLY across domains (n_per_domain each) -- it is
    # NOT proportional to the full 1,000-claim sample's real composition (ml_data is
    # ~75% of that sample, research_web <1%). Extrapolating with one blended
    # $/claim rate would badly misstate cost at scale, especially for variant 3
    # (nebius-agent), which only runs on robotics/research_web claims at all.
    # Fix: compute a per-DOMAIN mean cost from the pilot, then extrapolate each
    # domain separately against the full sample's REAL domain composition.
    composition_counts: dict[str, int] = {}
    for c in all_sample_claims:
        composition_counts[c["domain"]] = composition_counts.get(c["domain"], 0) + 1
    total_sample = len(all_sample_claims)
    composition = {d: n / total_sample for d, n in composition_counts.items()}

    bare_model_per_domain = _per_domain_mean(batches["bare_model"], "cost_usd")
    nebius_agent_per_domain = _per_domain_mean(batches["nebius_agent"], "cost_usd")
    generic_rag_per_domain = _per_domain_mean(batches["generic_rag"], "cost_usd")
    perplexity_per_domain = _per_domain_mean(batches["perplexity"], "cost_usd")
    gemini_per_domain = _per_domain_mean(batches["tavily_gemini"], "gemini_cost_usd")

    bare_model_cost = sum(r["cost_usd"] for r in batches["bare_model"])
    nebius_agent_cost = sum(r["cost_usd"] for r in batches["nebius_agent"])
    generic_rag_cost = sum(r["cost_usd"] for r in batches["generic_rag"])
    perplexity_cost = sum(r["cost_usd"] for r in batches["perplexity"])
    gemini_cost = sum(r["gemini_cost_usd"] for r in batches["tavily_gemini"])
    tavily_calls = len(batches["tavily_gemini"])
    # Includes bare_model's cost -- a real Nebius completion call, same sub-cap
    # pool as variants 3/4 (see this module's own docstring: retrieval is free
    # for this variant, the completion call itself is not).
    nebius_combined = bare_model_cost + nebius_agent_cost + generic_rag_cost

    print(f"\n=== Pilot actuals ({n_pilot} claims, EQUAL stratification across domains; "
          f"{n_propose} of them robotics/research_web for variant 3's propose-based retrieval) ===")
    print(f"Bare model (variant 2, all domains, zero retrieval): ${bare_model_cost:.6f} over {n_pilot} claims")
    print(f"Nebius-agent (variant 3, robotics/research_web only): ${nebius_agent_cost:.6f} over {n_propose} claims")
    print(f"Generic RAG (variant 4, all domains): ${generic_rag_cost:.6f} over {n_pilot} claims")
    print(f"Nebius combined (variants 2+3+4): ${nebius_combined:.6f}")
    print(f"Perplexity (variant 5): ${perplexity_cost:.6f} over {n_pilot} claims")
    print(f"Gemini (variant 6's completion leg): ${gemini_cost:.6f} over {n_pilot} claims")
    print(f"Tavily (variant 6's search leg): {tavily_calls} call(s), free-credit, no $ figure returned")

    already_spent = NEBIUS_ALREADY_SPENT_TEST1_TEST2
    print(f"\nNebius cumulative: ${already_spent:.6f} (Test #1+#2) + ${nebius_combined:.6f} (this pilot) "
          f"= ${already_spent + nebius_combined:.6f}, against the $20.00 project-wide cap "
          f"({100*(already_spent + nebius_combined)/20.0:.2f}%). "
          f"This test's own Nebius sub-cap: ${NEBIUS_TEST3_SUBCAP_USD:.2f}.")

    print(f"\nFull-sample domain composition used for extrapolation: "
          f"{ {d: f'{100*f:.1f}%' for d, f in composition.items()} }")
    print("=== Extrapolation to candidate M (claims drawn proportionally from the SAME "
          "Test #2 1,000-claim sample, NOT the pilot's equal-per-domain shape) ===")
    for M in (200, 500, 1000):
        bm_m = _extrapolate(bare_model_per_domain, composition, M)
        na_m = _extrapolate(nebius_agent_per_domain, composition, M)
        gr_m = _extrapolate(generic_rag_per_domain, composition, M)
        pp_m = _extrapolate(perplexity_per_domain, composition, M)
        gm_m = _extrapolate(gemini_per_domain, composition, M)
        print(f"M={M:5d}: bare-model~${bm_m:.4f}  nebius-agent~${na_m:.4f}  generic-rag~${gr_m:.4f}  "
              f"nebius(2+3+4)~${bm_m + na_m + gr_m:.4f}  perplexity~${pp_m:.4f}  "
              f"gemini~${gm_m:.4f}  tavily~{M} calls")

    print("\nSTOPPING HERE -- waiting for explicit go-ahead on final M before --mode full.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    parser.add_argument("--n-per-domain", type=int, default=7)
    parser.add_argument("--m", type=int, default=200, help="Full-mode sample size (claims per stratified draw).")
    parser.add_argument("--confirm-full", action="store_true")
    args = parser.parse_args()

    all_sample_claims = load_sample_claims()
    print(f"Loaded {len(all_sample_claims)} claims from the Test #2 sample.")

    if args.mode == "full":
        if not args.confirm_full:
            print("Refusing to run --mode full without --confirm-full and an explicitly agreed M.")
            sys.exit(1)
        if args.m >= len(all_sample_claims):
            # M == the whole existing sample: it ALREADY has the full manifest's real
            # proportional composition (see Test #2's own sample generator) -- using it
            # directly, not re-stratifying, is both correct and simplest.
            full_claims = all_sample_claims
        else:
            # M < 1,000: a PROPORTIONAL stratified draw (same shape as the full sample,
            # not select_pilot's equal-per-domain shape, which would badly under-sample
            # ml_data and distort every variant's measured accuracy/cost at this M).
            by_domain: dict[str, list[dict]] = {}
            for c in all_sample_claims:
                by_domain.setdefault(c["domain"], []).append(c)
            full_claims = []
            for domain, domain_claims in by_domain.items():
                n = round(len(domain_claims) / len(all_sample_claims) * args.m)
                full_claims.extend(domain_claims[:n])
        print(f"Full Test #3 run: {len(full_claims)} claims through all 5 variants, user-authorized.\n")
        asyncio.run(run_all_five(full_claims, tag="full"))
        return

    pilot = select_pilot(all_sample_claims, n_per_domain=args.n_per_domain)
    print(f"Pilot batch: {len(pilot)} claims, stratified across domains/tiers, "
          f"run through all 5 variants.\n")
    batches = asyncio.run(run_all_five(pilot, tag="pilot"))
    _print_pilot_extrapolation(pilot, batches, all_sample_claims)


if __name__ == "__main__":
    main()
