"""
Competitive benchmark + self-improvement protocol -- ROUND 1.

See claude/ANTI_CASSIOPEIA_COMPETITIVE_BENCHMARK_PROTOCOL.md for the full,
locked spec this follows. This script implements one round: 9 hand-picked
claims across all 7 categories (skewed toward research_web, per §2 --
ml_data/fpga_embedded are explicitly not a fair fight, and no robotics
BYOE claim was picked this round since none of §1's categories are
robotics-shaped), run through the REAL Anti-Cassiopeia engine and every
applicable §0 competitor variant, reusing the existing harness functions
directly -- nothing here reimplements retrieval, propose, or any
competitor's calling code.

GROUND TRUTH SOURCING (done once, by hand, before this script existed --
see the round's own report for full citations):
- Categories 1-5: real primary/secondary sources checked directly.
- Category 6 (calibration probes): no ground truth at all by design --
  ground_truth_verdict is deliberately set to "undetermined" here so the
  existing classify() function's own semantics do exactly the right
  thing automatically (predicted=undetermined -> "correct"; predicted=
  confirmed/contradicted -> "dangerous", per run_test1.classify()'s own
  "a confident guess on a genuinely unanswerable claim" rule) -- no new
  scoring logic needed.
- Category 7: ground truth IS the real, directly-fetched (not
  secondhand) published verdict from Full Fact (fullfact.org) -- Snopes
  and AP both blocked automated fetches (HTTP 402 / unreachable) when
  this round's claims were sourced, so Full Fact was used instead; this
  is stated honestly in the round's report, not silently substituted.

COMPETITOR SCOPE PER CLAIM (per protocol §3.3): claims 1-7 (categories
1-6) run through ALL FIVE competitor variants (bare model, nebius-agent,
generic RAG, Perplexity, Tavily+Gemini) AND the real engine. Claims 8-9
(category 7) run through the real engine ONLY -- no competitor variant
is run against them, per §0.5/§3.3's own explicit exception (there is no
live fact-checking-org API to compare against; the "competitor" for
those two IS the already-published verdict used as ground truth).

BUDGET: Nebius sub-cap for this round is $2.00 (well under the
protocol's own suggested $2-3, itself tiny against the ~$18 remaining
of the project's $20 cap -- the last documented cumulative figure,
stress_test/results/PHASE_B_REPORT.md, was $1.944991 (9.7%) as of
2026-10-24; this session's own post-that-report live testing (the V2
BYOE stress test's 10 calls, the causal-claim stance-fix model-routing
investigation's ~30 short calls) added an estimated few more cents on
top -- stated as an estimate, not a live balance query, since no tool
exists to query the real account balance directly; this round's own
actual spend is tracked fresh below and reported exactly, not
estimated). Perplexity/Tavily: call-count only, against already-
provisioned free credits. Gemini: real dollar cost, tracked separately,
never summed with Nebius.

Usage:
    PYTHONPATH=. python3 stress_test/run_benchmark_round1.py
"""

from __future__ import annotations

import asyncio
import json
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

from anticassiopeia.core import Claim, VerificationEngine  # noqa: E402
from anticassiopeia.domains.research_web import RECOMMENDED_STANCE_MODEL, ResearchWebAdapter  # noqa: E402
from instrumented_client import InstrumentedNebiusClient, NEMOTRON_PRICING_PER_M, UsageTracker  # noqa: E402
from run_test1 import classify  # noqa: E402
from run_test3_bare_model import run_bare_model_batch  # noqa: E402
from run_test3_generic_rag import run_generic_rag_batch  # noqa: E402
from run_test3_nebius_agent import run_nebius_agent_batch  # noqa: E402
from run_test3_perplexity import run_perplexity_batch  # noqa: E402
from run_test3_tavily_gemini import run_tavily_gemini_batch  # noqa: E402

RESULTS_DIR = REPO_ROOT / "stress_test/results"
ROUND1_RAW_PATH = RESULTS_DIR / "benchmark_round1_raw.json"

ROUND1_NEBIUS_SUBCAP_USD = 2.00

# --- Round 1 claim set (9 claims, all 7 categories) ---------------------

ROUND1_CLAIMS = [
    {
        "claim_id": "r1-cat1-darwin-wallace",
        "category": 1,
        "category_name": "causal/relational",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": (
                "Charles Darwin developed his theory of natural selection as an extension of "
                "Alfred Russel Wallace's independent theory, reading Wallace's work and then "
                "building upon it before publishing his own."
            ),
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "contradicted",
        "ground_truth_note": (
            "Darwin developed his theory independently over ~20 years (notebooks from the "
            "1830s-40s), BEFORE receiving Wallace's 1858 letter describing a similar idea -- "
            "the dependency direction claimed here is backwards. The real event was a joint "
            "1858 Linnean Society announcement of two independently-arrived-at theories, not "
            "Darwin building on Wallace."
        ),
    },
    {
        "claim_id": "r1-cat2-arpanet-login",
        "category": 2,
        "category_name": "obscure historical",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": (
                "The first message ever sent over the ARPANET in 1969 was intended to be the "
                "word 'LOGIN', but the system crashed after only the first two letters, 'LO', "
                "were transmitted."
            ),
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "confirmed",
        "ground_truth_note": (
            "Well-documented: UCLA (Kleinrock's lab) to Stanford Research Institute, "
            "October 29, 1969. Real, checkable, but not Nobel-prize-trivia-level repeated."
        ),
    },
    {
        "claim_id": "r1-cat3-theogony-cronus",
        "category": 3,
        "category_name": "mythology (text-framed)",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": (
                "In Hesiod's Theogony, Cronus castrates his father Uranus using a sickle given "
                "to him by his mother Gaia."
            ),
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "confirmed",
        "ground_truth_note": "Directly depicted in Hesiod's Theogony -- a claim about what the text says, not the myth's objective truth.",
    },
    {
        "claim_id": "r1-cat4-moon-landing-faked",
        "category": 4,
        "category_name": "well-documented conspiracy",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": "The Apollo 11 Moon landing in 1969 was faked by NASA and filmed on a Hollywood soundstage.",
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "contradicted",
        "ground_truth_note": "Well-settled false conspiracy claim -- the system should confidently contradict, not go soft.",
    },
    {
        "claim_id": "r1-cat5-dead-sea-scrolls",
        "category": 5,
        "category_name": "archaeology/religion-history (not doctrine)",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": "The Dead Sea Scrolls were discovered by Bedouin shepherds in caves near Qumran beginning in 1947.",
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "confirmed",
        "ground_truth_note": "Well-documented archaeological/historical fact, religion-adjacent but not doctrine.",
    },
    {
        "claim_id": "r1-cat6-resurrection",
        "category": 6,
        "category_name": "calibration probe (faith, not fact-checked)",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": "Jesus Christ physically rose from the dead three days after his crucifixion.",
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "undetermined",
        "ground_truth_note": (
            "NOT scored right/wrong. ground_truth_verdict is deliberately 'undetermined' so "
            "classify()'s own existing rule (a confident guess on an undecidable claim is "
            "'dangerous') does exactly the right scoring automatically. The only thing being "
            "measured: does the system land on UNDETERMINED with reasoning that names this as "
            "outside what web evidence can settle."
        ),
    },
    {
        "claim_id": "r1-cat6-quran-revelation",
        "category": 6,
        "category_name": "calibration probe (faith, not fact-checked)",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": (
                "The Prophet Muhammad received divine revelations from the angel Gabriel that "
                "were later compiled into the Quran."
            ),
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "undetermined",
        "ground_truth_note": "Same calibration-probe scoring as r1-cat6-resurrection above.",
    },
    {
        "claim_id": "r1-cat7-sunglasses-cancer",
        "category": 7,
        "category_name": "real published fact-check (Full Fact)",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": (
                "Wearing sunglasses causes cancer, because they block UV light from reaching "
                "the eyes, which stops the brain from producing a hormone needed for melanin "
                "production."
            ),
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "contradicted",
        "ground_truth_note": (
            "Full Fact, https://fullfact.org/health/theres-still-no-evidence-that-wearing-sunglasses-causes-cancer/ "
            "(fetched live, HTTP 200, 2026 round-1 sourcing session). Rated false. Real evidence "
            "cited: melanin is produced locally by skin cells responding to UV, not via a "
            "light-to-brain-to-hormone pathway; a Moorfields Eye Hospital ophthalmology professor "
            "noted people who lose their vision can still tan; a cited Nature study (s41416-021-01343-8) "
            "suggests sunglasses may help PREVENT ocular melanoma; NHS advice recommends sunglasses."
        ),
    },
    {
        "claim_id": "r1-cat7-spacex-moon-video",
        "category": 7,
        "category_name": "real published fact-check (Full Fact)",
        "domain": "research_web",
        "tier": 1,
        "claim_payload": {
            "text": (
                "A video that went viral online in August 2026 shows a real SpaceX Falcon 9 "
                "rocket crashing into the Moon."
            ),
            "domain": "research_web",
            "context": {},
        },
        "ground_truth_verdict": "contradicted",
        "ground_truth_note": (
            "Full Fact, https://fullfact.org/technology/spaceX-rocket-moon-crash-video-fake/ "
            "(fetched live, HTTP 200). Rated false/'altered' (Facebook third-party scheme). Real "
            "evidence cited: multiple named astronomers (Cambridge, Manchester, Boston University, "
            "Royal Observatory Greenwich) independently assessed the clip as fake/AI-generated -- "
            "wrong impact location, wrong surface detail, impossible resolution at lunar distance "
            "for a rocket-sized object; Elon Musk also stated on X the clip is not real. Note: part "
            "of a REAL SpaceX rocket stage did hit the Moon on 2026-08-05 -- but this specific viral "
            "video is not real footage of that event."
        ),
    },
]

#: Categories 1-6 (claims 1-7) run through every competitor; category 7
#: (claims 8-9) does not, per §0.5/§3.3.
COMPETITOR_ELIGIBLE = [c for c in ROUND1_CLAIMS if c["category"] != 7]
CATEGORY7_ONLY = [c for c in ROUND1_CLAIMS if c["category"] == 7]


async def run_anti_cassiopeia(claims: list[dict]) -> tuple[list[dict], UsageTracker]:
    """Real engine, real adapter, exactly as default_domains() builds it --
    including this session's own stance-routing change (propose() on
    gpt-oss-120b, judge_stance() on RECOMMENDED_STANCE_MODEL/Nemotron
    Ultra). Only substitution: InstrumentedNebiusClient in place of the
    production NebiusTokenFactoryClient, for real cost tracking -- same
    duck-typed injection point every other harness script in this
    directory already uses."""
    tracker = UsageTracker()
    propose_client = InstrumentedNebiusClient(tracker, model="openai/gpt-oss-120b", budget_usd=10.0)
    stance_in, stance_out = NEMOTRON_PRICING_PER_M[RECOMMENDED_STANCE_MODEL]
    stance_client = InstrumentedNebiusClient(
        tracker, model=RECOMMENDED_STANCE_MODEL, input_cost_per_m=stance_in, output_cost_per_m=stance_out, budget_usd=10.0,
    )
    adapter = ResearchWebAdapter(client=propose_client, stance_client=stance_client)
    engine = VerificationEngine(domains={"research_web": adapter})

    results = []
    for c in claims:
        claim = Claim(**c["claim_payload"])
        verdict = await engine.verify(claim)
        results.append({
            "claim_id": c["claim_id"],
            "category": c["category"],
            "predicted_verdict": verdict.state.value,
            "confidence": verdict.confidence,
            "ground_truth_verdict": c["ground_truth_verdict"],
            "evidence": [{"source": e.source, "stance": e.stance, "snippet": e.snippet[:300]} for e in verdict.evidence],
            "reasoning": verdict.reasoning,
            "missing": verdict.missing,
        })
        print(
            f"[anti-cassiopeia] {c['claim_id']:28s} predicted={verdict.state.value:13s} "
            f"truth={c['ground_truth_verdict']:13s} confidence={verdict.confidence}"
        )
    return results, tracker


def _score_row(predicted: str, ground_truth: str) -> str:
    return classify(predicted, ground_truth)


async def main() -> None:
    print("=" * 90)
    print("COMPETITIVE BENCHMARK ROUND 1")
    print(f"{len(ROUND1_CLAIMS)} claims across 7 categories; {len(COMPETITOR_ELIGIBLE)} run through "
          f"all 5 competitors, {len(CATEGORY7_ONLY)} (category 7) run through Anti-Cassiopeia only.")
    print("=" * 90)

    ac_results, ac_tracker = await run_anti_cassiopeia(ROUND1_CLAIMS)

    print("\n--- Variant 2: bare model ---")
    nebius_tracker = UsageTracker()
    bare_model_results = await run_bare_model_batch(
        COMPETITOR_ELIGIBLE, tag="round1", tracker=nebius_tracker, budget_usd=ROUND1_NEBIUS_SUBCAP_USD,
        raw_results_path=RESULTS_DIR / "benchmark_round1_bare_model_raw.jsonl",
    )

    print("\n--- Variant 3: Nebius-agent ---")
    nebius_agent_results = await run_nebius_agent_batch(
        COMPETITOR_ELIGIBLE, tag="round1", tracker=nebius_tracker, budget_usd=ROUND1_NEBIUS_SUBCAP_USD,
        raw_results_path=RESULTS_DIR / "benchmark_round1_nebius_agent_raw.jsonl",
    )

    print("\n--- Variant 4: generic RAG ---")
    generic_rag_results = await run_generic_rag_batch(
        COMPETITOR_ELIGIBLE, tag="round1", tracker=nebius_tracker, budget_usd=ROUND1_NEBIUS_SUBCAP_USD,
        raw_results_path=RESULTS_DIR / "benchmark_round1_generic_rag_raw.jsonl",
    )

    print("\n--- Variant 5: Perplexity ---")
    perplexity_results = await run_perplexity_batch(
        COMPETITOR_ELIGIBLE, tag="round1", raw_results_path=RESULTS_DIR / "benchmark_round1_perplexity_raw.jsonl",
    )

    print("\n--- Variant 6: Tavily + Gemini ---")
    tavily_gemini_results = await run_tavily_gemini_batch(
        COMPETITOR_ELIGIBLE, tag="round1", raw_results_path=RESULTS_DIR / "benchmark_round1_tavily_gemini_raw.jsonl",
    )

    # --- scorecard ---
    print("\n" + "=" * 90)
    print("SCORECARD")
    print("=" * 90)

    by_claim_id = {c["claim_id"]: c for c in ROUND1_CLAIMS}
    scorecard = []
    for ac_row in ac_results:
        cid = ac_row["claim_id"]
        c = by_claim_id[cid]
        row = {
            "claim_id": cid,
            "category": c["category"],
            "category_name": c["category_name"],
            "claim_text": c["claim_payload"]["text"],
            "ground_truth": c["ground_truth_verdict"],
            "ground_truth_note": c["ground_truth_note"],
            "anti_cassiopeia": {"predicted": ac_row["predicted_verdict"], "severity": _score_row(ac_row["predicted_verdict"], c["ground_truth_verdict"]), "confidence": ac_row["confidence"]},
        }
        if c["category"] != 7:
            def _find(results, claim_id):
                return next((r for r in results if r["claim_id"] == claim_id), None)

            bm = _find(bare_model_results, cid)
            na = _find(nebius_agent_results, cid)
            gr = _find(generic_rag_results, cid)
            pp = _find(perplexity_results, cid)
            tg = _find(tavily_gemini_results, cid)
            row["competitors"] = {
                "bare_model": {"predicted": bm["predicted_verdict"], "severity": bm["severity"]} if bm else None,
                "nebius_agent": {"predicted": na["predicted_verdict"], "severity": na["severity"]} if na else None,
                "generic_rag": {"predicted": gr["predicted_verdict"], "severity": gr["severity"]} if gr else None,
                "perplexity": {"predicted": pp["predicted_verdict"], "severity": pp["severity"]} if pp else None,
                "tavily_gemini": {"predicted": tg["predicted_verdict"], "severity": tg["severity"]} if tg else None,
            }
        else:
            row["competitors"] = None  # category 7: no competitor row, per §0.5
        scorecard.append(row)

        print(f"\n[{cid}] (category {c['category']}: {c['category_name']})")
        print(f"  claim: {c['claim_payload']['text']}")
        print(f"  ground truth: {c['ground_truth_verdict']}")
        print(f"  Anti-Cassiopeia: {row['anti_cassiopeia']['predicted']} ({row['anti_cassiopeia']['severity']}, conf={row['anti_cassiopeia']['confidence']})")
        if row["competitors"]:
            for name, res in row["competitors"].items():
                if res:
                    print(f"    {name:15s}: {res['predicted']} ({res['severity']})")

    # --- budget report ---
    print("\n" + "=" * 90)
    print("BUDGET")
    print("=" * 90)
    print(f"Anti-Cassiopeia's own run: ${ac_tracker.total_cost_usd:.6f} "
          f"({ac_tracker.total_prompt_tokens} prompt / {ac_tracker.total_completion_tokens} completion tok, {ac_tracker.call_count} calls)")
    print(f"Nebius-billed competitors (bare_model+nebius_agent+generic_rag): ${nebius_tracker.total_cost_usd:.6f} "
          f"({nebius_tracker.call_count} calls), against this round's own ${ROUND1_NEBIUS_SUBCAP_USD:.2f} sub-cap")
    perplexity_cost = sum(r["cost_usd"] for r in perplexity_results)
    gemini_cost = sum(r["gemini_cost_usd"] for r in tavily_gemini_results)
    tavily_calls = sum(1 for r in tavily_gemini_results if r.get("n_tavily_results", 0) or r["predicted_verdict"] not in ("SKIPPED_QUOTA",))
    print(f"Perplexity (free credits, real $ reported): ${perplexity_cost:.6f}")
    print(f"Tavily (free credits, call count): {tavily_calls} calls")
    print(f"Gemini (real $, separate provider): ${gemini_cost:.6f}")
    print(f"\nTotal Nebius this round: ${ac_tracker.total_cost_usd + nebius_tracker.total_cost_usd:.6f}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ROUND1_RAW_PATH.write_text(json.dumps({
        "scorecard": scorecard,
        "budget": {
            "anti_cassiopeia_usd": ac_tracker.total_cost_usd,
            "nebius_competitors_usd": nebius_tracker.total_cost_usd,
            "perplexity_usd": perplexity_cost,
            "gemini_usd": gemini_cost,
            "tavily_calls": tavily_calls,
        },
    }, indent=2, default=str))
    print(f"\nFull scorecard + budget written to {ROUND1_RAW_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
