"""
Judge-facing demo: runs real claims from each of the four domains through
the real engine and prints each verdict with its evidence and locators.

Nothing in this script is scripted/mocked — every verdict below comes from
the actual VerificationEngine, the actual domain adapters, and (for
robotics/ml_data/fpga_embedded) actual sourced facts or re-computed values.
research_web's case will show UNDETERMINED with a real proxy-403 gap if run
somewhere with restricted outbound network (see domains/research_web.py);
it'll show a real fetched verdict anywhere with open HTTPS.

Usage: PYTHONPATH=. python scripts/demo.py
"""

from __future__ import annotations

import asyncio

from anticassiopeia.core import Claim, VerificationEngine
from anticassiopeia.domains import default_domains

CASES: list[Claim] = [
    Claim(text="BlueROV2 survives 500 m depth", domain="robotics"),
    Claim(text="Bar30 survives 500 m depth", domain="robotics"),
    Claim(text="Bar100XT survives 500 m depth", domain="robotics"),
    Claim(
        text="voltage column mean is 5.0V",
        domain="ml_data",
        context={
            "dataset_path": "evals/fixtures/sample_measurements.csv",
            "column": "voltage",
            "stat": "mean",
            "expected_value": 5.0,
            "tolerance": 0.01,
        },
    ),
    Claim(
        text="design meets 100 MHz timing",
        domain="fpga_embedded",
        context={
            "report_path": "evals/fixtures/sample_timing_report.txt",
            "metric": "max_frequency_mhz",
            "comparator": ">=",
            "expected_value": 100,
        },
    ),
    Claim(
        text="example.com states it is reserved for illustrative examples",
        domain="research_web",
        context={"url": "https://example.com", "quote": "illustrative examples in documents"},
    ),
]

_SYMBOL = {"confirmed": "✓", "contradicted": "✗", "undetermined": "?"}


async def main() -> None:
    engine = VerificationEngine(domains=default_domains())

    print("=" * 72)
    print("Anti-Cassiopeia — domain-agnostic verification engine")
    print("confirmed / contradicted / undetermined — never a guess dressed up as certainty")
    print("=" * 72)

    for claim in CASES:
        verdict = await engine.verify(claim)
        symbol = _SYMBOL[verdict.state.value]
        print(f"\n[{symbol}] ({claim.domain}) {claim.text}")
        print(f"    verdict: {verdict.state.value}" + (f" (confidence {verdict.confidence:.2f})" if verdict.confidence is not None else ""))
        for e in verdict.evidence:
            print(f"    evidence [{e.stance}, trust={e.trust}]: {e.snippet}")
            print(f"      locator: {e.locator}")
        for m in verdict.missing:
            print(f"    missing: {m}")


if __name__ == "__main__":
    asyncio.run(main())
