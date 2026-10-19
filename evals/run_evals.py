"""
Runs every evals/cases/**/*.json case against the real engine + registered
domain adapters, and reports pass/fail against each case's expected_state.

Usage: PYTHONPATH=. python evals/run_evals.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from anticassiopeia.core import Claim, VerificationEngine
from anticassiopeia.domains import default_domains
from anticassiopeia.domains.research_web import ResearchWebAdapter
from evals.fixture_server import resolve, serve_fixtures

CASES_DIR = Path(__file__).parent / "cases"


async def main() -> int:
    # research_web's own 3 local_fixture_* cases fetch THIS repo's own local
    # fixture server (127.0.0.1, see evals/fixture_server.py) for real, on
    # purpose -- the SSRF guard research_web.py's real default now carries
    # (see that module's docstring) would otherwise reject that fetch before
    # it ever reached the block-page/quote check these cases exist to test.
    # Every OTHER domain still comes from default_domains()'s real,
    # production-default instance; only research_web is overridden here.
    domains = default_domains()
    domains["research_web"] = ResearchWebAdapter(block_private_networks=False)
    engine = VerificationEngine(domains=domains)
    case_files = sorted(CASES_DIR.rglob("*.json"))

    if not case_files:
        print("No eval cases found under evals/cases/.")
        return 0

    with serve_fixtures() as base_url:
        return await _run(engine, case_files, base_url)


async def _run(engine: VerificationEngine, case_files: list[Path], base_url: str) -> int:
    passed, failed = 0, 0
    for path in case_files:
        case = json.loads(path.read_text())
        claim = Claim(**resolve(case["claim"], base_url))
        verdict = await engine.verify(claim)
        got = verdict.state.value

        # Most cases: one correct answer. A few (currently just research_web's
        # live example.com case) are genuinely environment-dependent — network
        # availability or third-party page drift changes the verdict — and declare the full set of
        # states that count as a pass via "acceptable_states" instead of a single
        # "expected_state". Don't add this escape hatch to a case casually; it
        # exists for real environment variance, not to paper over a flaky adapter.
        acceptable = case.get("acceptable_states") or [case["expected_state"]]
        ok = got in acceptable
        passed += ok
        failed += not ok
        status = "PASS" if ok else "FAIL"
        want_desc = case.get("expected_state", "/".join(acceptable))
        print(f"[{status}] {path.relative_to(CASES_DIR)} — expected={want_desc} got={got}")
        if not ok:
            print(f"         note: {case.get('note', '')}")

    print(f"\n{passed} passed, {failed} failed, {len(case_files)} total.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
