"""
Judge-facing demo: runs real claims from each of the four domains through
the real engine and prints each verdict with its evidence and locators.

Nothing in this script is scripted/mocked — every verdict below comes from
the actual VerificationEngine, the actual domain adapters, and (for
robotics/ml_data/fpga_embedded) actual sourced facts or re-computed values.
research_web's case does a real HTTP fetch of a local, version-controlled
fixture page (evals/fixtures/web/) so the demo works offline and can't rot
when a third-party site changes its text.

Usage: PYTHONPATH=. python scripts/demo.py
"""

from __future__ import annotations

import asyncio

from anticassiopeia.core import Claim, VerificationEngine
from anticassiopeia.domains import default_domains
from anticassiopeia.domains.research_web import ResearchWebAdapter
from evals.fixture_server import resolve, serve_fixtures

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
        text="design's clk_main meets 100 MHz timing",
        domain="fpga_embedded",
        context={
            "report_path": "evals/fixtures/vivado_timing_report_single_corner.rpt",
            "metric": "frequency_mhz",
            "clock": "clk_main",
            "comparator": ">=",
            "expected_value": 100,
        },
    ),
    Claim(
        text="the local fixture page states the reference pump is rated for 12 bar",
        domain="research_web",
        context={"url": "{FIXTURE_BASE_URL}/stable_page.html", "quote": "maximum operating pressure of 12 bar"},
    ),
]

_SYMBOL = {"confirmed": "✓", "contradicted": "✗", "undetermined": "?"}


async def main() -> None:
    # Same reasoning as evals/run_evals.py: this demo's research_web case
    # fetches its own local fixture server (127.0.0.1) on purpose -- the
    # real default's SSRF guard (see research_web.py's docstring) would
    # otherwise reject that fetch. Every other domain stays production-default.
    domains = default_domains()
    domains["research_web"] = ResearchWebAdapter(block_private_networks=False)
    engine = VerificationEngine(domains=domains)

    print("=" * 72)
    print("Anti-Cassiopeia — domain-agnostic verification engine")
    print("confirmed / contradicted / undetermined — never a guess dressed up as certainty")
    print("=" * 72)

    with serve_fixtures() as base_url:
        await _run(engine, base_url)


async def _run(engine: VerificationEngine, base_url: str) -> None:
    for claim in CASES:
        claim = Claim(text=claim.text, domain=claim.domain, context=resolve(claim.context, base_url))
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
