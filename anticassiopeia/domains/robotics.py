"""
Robotics domain adapter — physical/datasheet POV.

Verifies claims about real hardware against real, cited sources: datasheets,
manufacturer spec sheets, and (per-part and whole-assembly) survivability
conditions — e.g. "this BLDC motor survives 500m depth", "this sensor is
ArduSub-compatible". Evidence here must trace back to an actual datasheet
locator (page/section/table), never to a generated or assumed spec.

STATUS: stub. gather_evidence() is not implemented yet — this is the bone,
not the organ. Wire it to a real datasheet/part-spec source before trusting
any verdict out of this domain.
"""

from __future__ import annotations

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence


class RoboticsAdapter(DomainAdapter):
    domain_name = "robotics"

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        # TODO: retrieve from a real parts/datasheet index (per-part conditions,
        # then whole-assembly survivability), not a generated claim.
        return []

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if not evidence:
            return [
                "No datasheet or spec-sheet evidence found for this part/assembly claim. "
                "Robotics verdicts require a traceable datasheet locator, not a generated spec."
            ]
        return super().describe_gap(claim, evidence)
