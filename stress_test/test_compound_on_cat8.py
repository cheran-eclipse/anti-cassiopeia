"""Quick live test: does core/compound.py's decompose_claim() + verify_compound()
handle category-8's 'true premise; therefore false conclusion' claims better
than a single atomic searchlight call? Not a permanent script -- throwaway
investigation before deciding Track B's real execution path."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(REPO_ROOT / ".env", override=False)

from anticassiopeia.core.compound import decompose_claim, verify_compound  # noqa: E402
from anticassiopeia.core import VerificationEngine  # noqa: E402
from anticassiopeia.domains import default_domains  # noqa: E402
from anticassiopeia.llm.nebius_client import NebiusTokenFactoryClient  # noqa: E402

CLAIMS = [
    "A paper published in a peer-reviewed journal reports a statistically significant "
    "association between two variables; therefore, the first variable caused the second, "
    "the association must replicate in every population, and no confounding variable can "
    "explain the result.",
    "A modern scientific instrument measures a quantity to twelve decimal places; "
    "therefore, the measured value is accurate to twelve decimal places, the instrument "
    "is free from systematic error, and the underlying physical model is correct.",
    "For a redundant robot manipulator, a nonzero vector in the null space of the "
    "manipulator Jacobian produces zero instantaneous end-effector velocity; therefore, "
    "integrating any such null-space velocity command over an arbitrary finite interval "
    "is guaranteed to preserve the end-effector pose exactly.",
]


async def main() -> None:
    client = NebiusTokenFactoryClient()
    for claim_text in CLAIMS:
        print(f"\n{'='*90}\nCLAIM: {claim_text}")
        try:
            parts = await decompose_claim(client, claim_text)
        except Exception as exc:  # noqa: BLE001
            print(f"  decompose FAILED: {exc}")
            continue
        for p in parts:
            print(f"  PART ({p['domain']}): {p['text']}")

        engine = VerificationEngine(domains=default_domains())
        result = await verify_compound(engine, client, claim_text)
        print(f"  COMPOUND VERDICT: {result.state.value} (confidence {result.confidence})")
        for r in result.reasoning:
            print(f"    - {r}")


if __name__ == "__main__":
    asyncio.run(main())
