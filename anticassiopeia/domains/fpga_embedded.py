"""
FPGA / embedded-systems domain adapter — quantum POV.

Verifies claims about synthesizable RTL and embedded hardware behavior:
timing closure, register-level correctness, resource utilization, and
(per the "quantum POV" framing) claims that touch quantum-adjacent hardware
paths such as QKD parameter estimation in RTL. Evidence here should trace
to simulation/synthesis reports, register maps, or timing reports — not to
a plausible-sounding description of what the hardware "should" do.

STATUS: stub. gather_evidence() is not implemented yet.
"""

from __future__ import annotations

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence


class FPGAEmbeddedAdapter(DomainAdapter):
    domain_name = "fpga_embedded"

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        # TODO: retrieve from synthesis/timing reports, register maps, or
        # simulation logs — not from a described-but-unverified behavior.
        return []

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if not evidence:
            return [
                "No synthesis/timing/simulation evidence found for this RTL or embedded "
                "hardware claim."
            ]
        return super().describe_gap(claim, evidence)
