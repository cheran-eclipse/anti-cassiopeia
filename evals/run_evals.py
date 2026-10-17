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

CASES_DIR = Path(__file__).parent / "cases"


async def main() -> int:
    engine = VerificationEngine(domains=default_domains())
    case_files = sorted(CASES_DIR.rglob("*.json"))

    if not case_files:
        print("No eval cases found under evals/cases/.")
        return 0

    passed, failed = 0, 0
    for path in case_files:
        case = json.loads(path.read_text())
        claim = Claim(**case["claim"])
        verdict = await engine.verify(claim)
        got = verdict.state.value
        want = case["expected_state"]
        ok = got == want
        passed += ok
        failed += not ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {path.relative_to(CASES_DIR)} — expected={want} got={got}")
        if not ok:
            print(f"         note: {case.get('note', '')}")

    print(f"\n{passed} passed, {failed} failed, {len(case_files)} total.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
