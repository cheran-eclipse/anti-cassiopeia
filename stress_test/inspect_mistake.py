"""
Diagnostic tool, not part of the harness: re-runs ONE named claim against
ONE named model, logging every raw LLM call (prompt + response) alongside
the final Verdict, so a specific pilot mistake can be read in full --
actual claim text, actual model output, actual verdict/reasoning -- not
just the aggregate severity classification run_batch() records.

HONESTY NOTE: this is a FRESH reproduction attempt, not a replay of the
exact original pilot run. Live calls are not fully deterministic (already
observed project-wide -- see e.g. stress_test/BUGS_FOUND.md's ~1-in-10
"not found" flakiness, and this project's own baseline numbers moving
between identical pilot re-runs). It may or may not reproduce the same
verdict the original pilot recorded; whichever happens is itself reported,
not hidden.

Usage:
    PYTHONPATH=. python3 stress_test/inspect_mistake.py <claim_id> <model>
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from anticassiopeia.core import Claim, VerificationEngine  # noqa: E402
from anticassiopeia.domains.research_web import ResearchWebAdapter  # noqa: E402
from anticassiopeia.domains.robotics import RoboticsAdapter  # noqa: E402
from instrumented_client import InstrumentedNebiusClient, NEMOTRON_PRICING_PER_M, UsageTracker  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "stress_test/claims/manifest.jsonl"
BASELINE_MODEL = "openai/gpt-oss-120b"
BASELINE_PRICING = (0.15, 0.60)


class _LoggingClient:
    """Wraps InstrumentedNebiusClient, logging every raw prompt+response pair
    so the actual model output behind a verdict is visible, not just the
    final classification."""

    def __init__(self, inner: InstrumentedNebiusClient):
        self._inner = inner
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> str:
        try:
            response = await self._inner.complete(prompt, system=system, temperature=temperature)
        except Exception as exc:  # noqa: BLE001 -- the failure itself is what we're inspecting
            self.calls.append({"prompt": prompt, "system": system, "response": None, "error": f"{type(exc).__name__}: {exc}"})
            raise
        self.calls.append({"prompt": prompt, "system": system, "response": response, "error": None})
        return response


def load_claim(claim_id: str) -> dict:
    with open(MANIFEST_PATH) as f:
        for line in f:
            d = json.loads(line)
            if d["claim_id"] == claim_id:
                return d
    raise SystemExit(f"claim_id {claim_id!r} not found in {MANIFEST_PATH}")


async def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: inspect_mistake.py <claim_id> <model>")
    claim_id, model_name = sys.argv[1], sys.argv[2]
    c = load_claim(claim_id)
    domain = c["domain"]

    if model_name == BASELINE_MODEL:
        pricing = BASELINE_PRICING
    elif model_name in NEMOTRON_PRICING_PER_M:
        pricing = NEMOTRON_PRICING_PER_M[model_name]
    else:
        raise SystemExit(f"no known pricing for {model_name!r}")

    tracker = UsageTracker()
    inner = InstrumentedNebiusClient(tracker, model=model_name, input_cost_per_m=pricing[0], output_cost_per_m=pricing[1])
    logger = _LoggingClient(inner)

    if domain == "robotics":
        adapter = RoboticsAdapter(client=logger)
    elif domain == "research_web":
        adapter = ResearchWebAdapter(client=logger)
    else:
        raise SystemExit(f"domain {domain!r} makes no live LLM call -- nothing to inspect")

    engine = VerificationEngine(domains={domain: adapter})
    claim = Claim(**c["claim_payload"])

    print(f"=== {claim_id} ({domain}, tier {c['tier']}) against {model_name} ===")
    print(f"Claim text: {claim.text!r}")
    print(f"Claim context: {claim.context}")
    print(f"Ground truth: {c['ground_truth_verdict']} ({c['ground_truth_method']})")
    print()

    try:
        verdict = await engine.verify(claim)
        print(f"VERDICT (this reproduction): {verdict.state.value} (confidence={verdict.confidence})")
        print("Reasoning:")
        for r in verdict.reasoning:
            print(f"  - {r}")
        print("Evidence:")
        for e in verdict.evidence:
            print(f"  - source={e.source} stance={e.stance} trust={e.trust}")
            print(f"    snippet: {e.snippet}")
            print(f"    locator: {e.locator}")
    except Exception as exc:  # noqa: BLE001
        print(f"CRASHED (this reproduction): {type(exc).__name__}: {exc}")

    print(f"\n--- {len(logger.calls)} raw LLM call(s) ---")
    for i, call in enumerate(logger.calls, start=1):
        print(f"\n[call {i}]")
        if call["system"]:
            print(f"SYSTEM: {call['system'][:300]}{'...' if len(call['system']) > 300 else ''}")
        print(f"PROMPT: {call['prompt']}")
        if call["error"]:
            print(f"ERROR: {call['error']}")
        else:
            print(f"RESPONSE: {call['response']}")

    print(f"\nCost this reproduction: ${tracker.total_cost_usd:.6f} ({tracker.call_count} calls)")


if __name__ == "__main__":
    asyncio.run(main())
