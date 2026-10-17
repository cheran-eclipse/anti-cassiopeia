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
from evals.fixture_server import resolve, serve_fixtures

CASES_DIR = Path(__file__).parent / "cases"


async def main() -> int:
    engine = VerificationEngine(domains=default_domains())
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
