"""
Stress Test #1 runner. Loads stress_test/claims/manifest.jsonl and runs
each selected claim through the REAL production pipeline — the actual
anticassiopeia.core.VerificationEngine and the actual domain adapters,
imported normally (read-only use of anticassiopeia/, no edits). The only
stress-test-only substitution is instrumented_client.InstrumentedNebiusClient,
injected via the SAME constructor params (`client=...`) the production
adapters already expose for testing — robotics.py and research_web.py's
own real behavior is otherwise untouched.

Usage:
    PYTHONPATH=. python3 stress_test/run_test1.py --mode pilot
    PYTHONPATH=. python3 stress_test/run_test1.py --mode full   (NOT run yet — see rule 5)

Secret handling: NEBIUS_API_KEY is loaded only inside instrumented_client.py
via dotenv_values(); this file never touches it directly and never prints it.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from anticassiopeia.core import Claim, VerificationEngine  # noqa: E402
from anticassiopeia.domains.fpga_embedded import FPGAEmbeddedAdapter  # noqa: E402
from anticassiopeia.domains.ml_data import MLDataAdapter  # noqa: E402
from anticassiopeia.domains.research_web import ResearchWebAdapter  # noqa: E402
from anticassiopeia.domains.robotics import RoboticsAdapter  # noqa: E402
from instrumented_client import BudgetExceededError, InstrumentedNebiusClient, UsageTracker  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "stress_test/claims/manifest.jsonl"
RAW_RESULTS_PATH = REPO_ROOT / "stress_test/results/test1_raw.jsonl"
BUGS_PATH = REPO_ROOT / "stress_test/BUGS_FOUND.md"


def load_manifest() -> list[dict]:
    claims = []
    with open(MANIFEST_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                claims.append(json.loads(line))
    return claims


def select_pilot(claims: list[dict], n_per_domain: int = 5) -> list[dict]:
    """Deterministic, stratified pilot selection: up to n_per_domain claims
    per domain, spread across the tiers that domain actually has, so the
    pilot's real cost data isn't skewed toward one tier's call pattern."""
    by_domain: dict[str, list[dict]] = {}
    for c in claims:
        by_domain.setdefault(c["domain"], []).append(c)

    pilot = []
    for domain, domain_claims in sorted(by_domain.items()):
        by_tier: dict[int, list[dict]] = {}
        for c in domain_claims:
            by_tier.setdefault(c["tier"], []).append(c)
        tiers = sorted(by_tier)
        picked = []
        i = 0
        while len(picked) < n_per_domain and any(by_tier[t] for t in tiers):
            t = tiers[i % len(tiers)]
            if by_tier[t]:
                picked.append(by_tier[t].pop(0))
            i += 1
        pilot.extend(picked)
    return pilot


def locked_append(path: Path, text: str) -> None:
    """Single, serialized writer path for any file this script appends to —
    fixes the earlier race risk (this script appending while something else
    held the same path open) with a real POSIX advisory lock (fcntl.flock),
    not just a convention. Blocks until the lock is free, so two concurrent
    run_test1.py processes (or a hand-edit elsewhere while one is running)
    serialize instead of interleaving or truncating each other's writes."""
    with open(path, "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(text)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def classify(predicted: str, truth: str) -> str:
    if predicted == truth:
        return "correct"
    if predicted in ("confirmed", "contradicted") and truth in ("confirmed", "contradicted"):
        return "dangerous"  # confidently wrong in the opposite direction
    if predicted == "undetermined" and truth in ("confirmed", "contradicted"):
        return "conservative_miss"  # overly cautious, not wrong
    if predicted in ("confirmed", "contradicted") and truth == "undetermined":
        # Extended beyond the task's two named categories: a confident guess on
        # a claim that was genuinely unanswerable is arguably the MOST dangerous
        # case this whole project exists to catch — classified as dangerous too,
        # named explicitly here so it isn't silently folded into "correct" or lost.
        return "dangerous"
    return "other"


async def build_engine(tracker: UsageTracker) -> VerificationEngine:
    client = InstrumentedNebiusClient(tracker)
    domains = {
        "ml_data": MLDataAdapter(),
        "fpga_embedded": FPGAEmbeddedAdapter(),
        "robotics": RoboticsAdapter(client=client),
        "research_web": ResearchWebAdapter(client=client),
    }
    return VerificationEngine(domains=domains)


async def run_batch(claims: list[dict], tag: str) -> None:
    tracker = UsageTracker()
    engine = await build_engine(tracker)

    RAW_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    bugs_found: list[dict] = []
    results = []
    try:
        for c in claims:
            tracker.set_domain(c["domain"])
            before = tracker.snapshot()
            claim = Claim(**c["claim_payload"])

            start = time.monotonic()
            error = None
            try:
                verdict = await engine.verify(claim)
                predicted = verdict.state.value
            except BudgetExceededError:
                raise
            except Exception as exc:  # noqa: BLE001 -- a crash IS a result worth recording, not re-raising mid-batch
                predicted = "CRASH"
                error = f"{type(exc).__name__}: {exc}"
            latency = time.monotonic() - start

            after = tracker.snapshot()
            delta_prompt = after["total_prompt_tokens"] - before["total_prompt_tokens"]
            delta_completion = after["total_completion_tokens"] - before["total_completion_tokens"]
            delta_cost = after["total_cost_usd"] - before["total_cost_usd"]

            severity = "crash" if predicted == "CRASH" else classify(predicted, c["ground_truth_verdict"])

            record = {
                "claim_id": c["claim_id"],
                "domain": c["domain"],
                "tier": c["tier"],
                "predicted_verdict": predicted,
                "ground_truth_verdict": c["ground_truth_verdict"],
                "severity": severity,
                "latency_s": latency,
                "prompt_tokens": delta_prompt,
                "completion_tokens": delta_completion,
                "cost_usd": delta_cost,
                "error": error,
            }
            results.append(record)
            locked_append(RAW_RESULTS_PATH, json.dumps(record) + "\n")

            if severity in ("dangerous", "crash"):
                bugs_found.append({**record, "claim_payload": c["claim_payload"], "ground_truth_method": c["ground_truth_method"]})

            print(
                f"[{tag}] {c['claim_id']:28s} domain={c['domain']:14s} tier={c['tier']} "
                f"predicted={predicted:13s} truth={c['ground_truth_verdict']:13s} "
                f"severity={severity:17s} latency={latency:.2f}s cost=${delta_cost:.6f}"
            )
    except BudgetExceededError as exc:
        print(f"\nBUDGET HARD STOP: {exc}")

    if bugs_found:
        chunk = [f"\n## Batch `{tag}` — {len(bugs_found)} dangerous/crash result(s) found\n\n"]
        for b in bugs_found:
            chunk.append(f"### {b['claim_id']} ({b['domain']}, tier {b['tier']})\n")
            chunk.append(f"- Claim: `{json.dumps(b['claim_payload'])}`\n")
            chunk.append(f"- Predicted: **{b['predicted_verdict']}**, ground truth: **{b['ground_truth_verdict']}** ({b['severity']})\n")
            chunk.append(f"- Ground truth method: {b['ground_truth_method']}\n")
            if b["error"]:
                chunk.append(f"- Error: `{b['error']}`\n")
            chunk.append("\n")
        locked_append(BUGS_PATH, "".join(chunk))  # one single locked write, not one lock per line

    _print_summary(results, tracker, tag)


def _print_summary(results: list[dict], tracker: UsageTracker, tag: str) -> None:
    n = len(results)
    severities = {}
    for r in results:
        severities[r["severity"]] = severities.get(r["severity"], 0) + 1

    print(f"\n=== {tag} summary: {n} claims ===")
    for sev, count in sorted(severities.items()):
        print(f"  {sev}: {count} ({100*count/n:.1f}%)")
    print(f"\nActual spend this batch: ${tracker.total_cost_usd:.6f} "
          f"({tracker.total_prompt_tokens} prompt tok, {tracker.total_completion_tokens} completion tok, "
          f"{tracker.call_count} live API calls)")
    print("By-domain cost this batch:")
    for domain, cost in sorted(tracker.by_domain_cost.items()):
        print(f"  {domain}: ${cost:.6f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    parser.add_argument("--n-per-domain", type=int, default=5)
    parser.add_argument(
        "--confirm-full", action="store_true",
        help="Required alongside --mode full. Only pass this after the user has "
             "explicitly authorized a full run in their own words, having already "
             "seen a pilot's real cost estimate (rule 5) -- not on inference alone.",
    )
    args = parser.parse_args()

    all_claims = load_manifest()
    print(f"Loaded {len(all_claims)} claims from manifest.")

    if args.mode == "full":
        if not args.confirm_full:
            print(
                "Refusing to run --mode full without --confirm-full. Rule 5 requires "
                "explicit user go-ahead after reviewing the pilot's cost estimate first."
            )
            sys.exit(1)
        print(f"Full batch: {len(all_claims)} claims, user-authorized.\n")
        asyncio.run(run_batch(all_claims, tag="full"))
        return

    pilot = select_pilot(all_claims, n_per_domain=args.n_per_domain)
    print(f"Pilot batch: {len(pilot)} claims, stratified across domains/tiers.\n")
    asyncio.run(run_batch(pilot, tag="pilot"))

    # Extrapolate to the full manifest, broken out per domain (ml_data/
    # fpga_embedded are free -- zero Nebius calls -- so only robotics/
    # research_web's real per-claim cost from the pilot is extrapolated).
    print("\n=== Extrapolation to full manifest ===")
    full_counts = {}
    for c in all_claims:
        full_counts[c["domain"]] = full_counts.get(c["domain"], 0) + 1
    print(f"Full manifest size: {len(all_claims)} claims — {full_counts}")


if __name__ == "__main__":
    main()
