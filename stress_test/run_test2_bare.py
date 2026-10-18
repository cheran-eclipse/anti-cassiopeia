"""
Stress Test #2, Part B: the bare-Nebius comparison path. For each claim,
sends a single chat completion to the SAME model this repo already uses
(openai/gpt-oss-120b via InstrumentedNebiusClient, which itself mirrors
the real production anticassiopeia/llm/nebius_client.py) with NO
retrieval, NO file access, NO tools — just the claim phrased as a direct
yes/no question. This is the "what if we skipped the whole pipeline"
baseline Test #2 measures the real pipeline against.

For ml_data/fpga_embedded claims specifically, the claim's dataset/report
file is never read or pasted in here — the model genuinely has no way to
see it, so a confident confirmed/contradicted verdict for those two
domains is only possible by fabrication, not by looking anything up.
Flagged as `fabricated_detail` based on whether the model's own response
shows awareness it lacks file access — not on whether its answer happens
to be numerically right, since a fabricated number landing in-tolerance
by chance is not the same as a grounded one.

Secret handling: unchanged from instrumented_client.py (dotenv_values()
only, never printed). Reuses run_test1.py's locked_append/classify rather
than reimplementing the race-safe file write or the severity taxonomy.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import json  # noqa: E402

from instrumented_client import BUDGET_HARD_STOP_USD, BudgetExceededError, InstrumentedNebiusClient, UsageTracker  # noqa: E402
from run_test1 import classify, locked_append  # noqa: E402

RAW_RESULTS_PATH = REPO_ROOT / "stress_test/results/test2_bare_raw.jsonl"
BUGS_PATH = REPO_ROOT / "stress_test/BUGS_FOUND.md"

# Domains where the claim references a real file the bare model cannot see.
_FILE_DEPENDENT_DOMAINS = {"ml_data", "fpga_embedded"}

_CANONICAL_WORDS = ("confirmed", "contradicted", "undetermined")

# Phrases taken as the model itself signaling it knows it lacks file access —
# used only to flag fabricated-detail cases, not to grade correctness.
_ACCESS_AWARENESS_MARKERS = (
    "don't have access", "do not have access", "no access to", "without access to",
    "cannot access", "can't access", "unable to access", "not provided with the",
    "haven't been given", "have not been given", "cannot see the file", "can't see the file",
    "no way to verify", "no way to access", "without seeing the", "without the actual data",
    "cannot verify this without", "can't verify this without", "don't have the data",
    "do not have the data", "i do not have the file", "i don't have the file",
    "cannot open the file", "can't open the file", "no direct access",
)


def build_prompt(claim_text: str) -> str:
    return (
        f"Is the following true: {claim_text}? Answer confirmed, contradicted, "
        f"or undetermined, and explain why in one sentence."
    )


def shows_access_awareness(response_text: str) -> bool:
    t = response_text.lower()
    return any(marker in t for marker in _ACCESS_AWARENESS_MARKERS)


def parse_bare_verdict(response_text: str) -> str:
    """Returns one of confirmed/contradicted/undetermined (the first of the
    three canonical words the model actually states, by position — not just
    whichever regex happens to match first), "declined" (no canonical word
    stated, but the response signals it can't know), or "unparseable"."""
    t = response_text.lower()
    positions = {}
    for word in _CANONICAL_WORDS:
        m = re.search(rf"\b{word}\b", t)
        if m:
            positions[word] = m.start()
    if positions:
        return min(positions, key=positions.get)
    if shows_access_awareness(t) or "cannot determine" in t or "can't determine" in t or "unable to determine" in t:
        return "declined"
    return "unparseable"


def is_fabricated_detail(domain: str, predicted: str, response_text: str) -> bool:
    """Only meaningful for ml_data/fpga_embedded: a confident verdict given
    with no acknowledgement of lacking file access means the model is
    asserting knowledge of file contents it cannot actually have — flagged
    regardless of whether that assertion happens to be numerically correct."""
    if domain not in _FILE_DEPENDENT_DOMAINS:
        return False
    if predicted not in ("confirmed", "contradicted"):
        return False
    return not shows_access_awareness(response_text)


async def run_bare_batch(
    claims: list[dict],
    tag: str,
    *,
    raw_results_path: Path = RAW_RESULTS_PATH,
    bugs_path: Path = BUGS_PATH,
    tracker: UsageTracker | None = None,
    budget_usd: float = BUDGET_HARD_STOP_USD,
) -> list[dict]:
    tracker = tracker if tracker is not None else UsageTracker()
    client = InstrumentedNebiusClient(tracker, budget_usd=budget_usd)
    raw_results_path.parent.mkdir(parents=True, exist_ok=True)

    bugs_found: list[dict] = []
    results = []
    try:
        for c in claims:
            tracker.set_domain(c["domain"])
            before = tracker.snapshot()
            prompt = build_prompt(c["claim_payload"]["text"])

            start = time.monotonic()
            error = None
            response_text = ""
            try:
                response_text = await client.complete(prompt, temperature=0.2)
                predicted = parse_bare_verdict(response_text)
            except BudgetExceededError:
                raise
            except Exception as exc:  # noqa: BLE001 -- a crash IS a result worth recording
                predicted = "CRASH"
                error = f"{type(exc).__name__}: {exc}"
            latency = time.monotonic() - start

            after = tracker.snapshot()
            delta_prompt = after["total_prompt_tokens"] - before["total_prompt_tokens"]
            delta_completion = after["total_completion_tokens"] - before["total_completion_tokens"]
            delta_cost = after["total_cost_usd"] - before["total_cost_usd"]

            # "declined" behaves like "undetermined" for severity purposes —
            # both are a refusal to commit, just worded differently.
            classify_input = "undetermined" if predicted == "declined" else predicted
            severity = "crash" if predicted == "CRASH" else classify(classify_input, c["ground_truth_verdict"])
            fabricated = False if predicted == "CRASH" else is_fabricated_detail(c["domain"], predicted, response_text)

            record = {
                "claim_id": c["claim_id"],
                "domain": c["domain"],
                "tier": c["tier"],
                "predicted_verdict": predicted,
                "ground_truth_verdict": c["ground_truth_verdict"],
                "severity": severity,
                "fabricated_detail": fabricated,
                "latency_s": latency,
                "prompt_tokens": delta_prompt,
                "completion_tokens": delta_completion,
                "cost_usd": delta_cost,
                "response_text": response_text,
                "error": error,
            }
            results.append(record)
            locked_append(raw_results_path, json.dumps(record) + "\n")

            if severity in ("dangerous", "crash"):
                bugs_found.append({**record, "claim_payload": c["claim_payload"]})

            print(
                f"[{tag}] {c['claim_id']:28s} domain={c['domain']:14s} tier={c['tier']} "
                f"predicted={predicted:13s} truth={c['ground_truth_verdict']:13s} "
                f"severity={severity:17s} fab={fabricated!s:5s} latency={latency:.2f}s cost=${delta_cost:.6f}"
            )
    except BudgetExceededError as exc:
        print(f"\nBUDGET HARD STOP: {exc}")

    if bugs_found:
        # Bare-Nebius "bugs" are not production bugs (no anticassiopeia/ code
        # ran) — recorded separately in its own tagged section so they're
        # never confused with a real pipeline finding.
        chunk = [f"\n## Test #2 bare-Nebius batch `{tag}` — {len(bugs_found)} dangerous/crash result(s) (baseline, not a pipeline bug)\n\n"]
        for b in bugs_found:
            chunk.append(f"### {b['claim_id']} ({b['domain']}, tier {b['tier']})\n")
            chunk.append(f"- Claim: `{json.dumps(b['claim_payload'])}`\n")
            chunk.append(f"- Bare-Nebius predicted: **{b['predicted_verdict']}**, ground truth: **{b['ground_truth_verdict']}** ({b['severity']})\n")
            if b["error"]:
                chunk.append(f"- Error: `{b['error']}`\n")
            chunk.append("\n")
        locked_append(bugs_path, "".join(chunk))

    _print_summary(results, tracker, tag)
    return results


def _print_summary(results: list[dict], tracker: UsageTracker, tag: str) -> None:
    n = len(results)
    if n == 0:
        print(f"\n=== {tag} (bare) summary: 0 claims ===")
        return
    severities: dict[str, int] = {}
    fab_count = 0
    for r in results:
        severities[r["severity"]] = severities.get(r["severity"], 0) + 1
        if r.get("fabricated_detail"):
            fab_count += 1

    print(f"\n=== {tag} (bare) summary: {n} claims ===")
    for sev, count in sorted(severities.items()):
        print(f"  {sev}: {count} ({100*count/n:.1f}%)")
    print(f"  fabricated_detail: {fab_count} ({100*fab_count/n:.1f}%)")
    print(f"\nActual spend this batch: ${tracker.total_cost_usd:.6f} "
          f"({tracker.total_prompt_tokens} prompt tok, {tracker.total_completion_tokens} completion tok, "
          f"{tracker.call_count} live API calls)")
