"""
Algorithms / data domain adapter — ML POV.

Verifies claims about ML/data-science work: whether a reported metric
reproduces, whether a stated statistical relationship actually holds in
the given data, whether a claimed property of an algorithm/model is
correct. Evidence here should trace to an actual re-run computation,
statistical test result, or dataset inspection — not to a described result
nobody re-derived.

STATUS: stub. gather_evidence() is not implemented yet.
"""

from __future__ import annotations

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence


class MLDataAdapter(DomainAdapter):
    domain_name = "ml_data"

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        # TODO: retrieve/compute from the actual dataset or a re-run of the
        # claimed metric/test — not from a described-but-unverified result.
        return []

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if not evidence:
            return [
                "No computed/re-run evidence found for this metric or statistical claim."
            ]
        return super().describe_gap(claim, evidence)
