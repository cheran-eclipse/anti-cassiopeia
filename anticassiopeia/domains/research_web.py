"""
Web / research-paper domain adapter — existence/verification POV.

Verifies claims of the form "this paper/source/fact exists and says X":
author lists, publication venues, specific figures or quotes, whether a
cited source is real at all. This is the domain most directly aimed at the
failure Anti-Cassiopeia is named against — a confident, detailed,
plausible-sounding citation that turns out to be fabricated. Evidence here
must trace to an actual fetched page, paper, or search result, never to
recalled/trained knowledge presented as a lookup.

STATUS: stub. gather_evidence() is not implemented yet.
"""

from __future__ import annotations

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence


class ResearchWebAdapter(DomainAdapter):
    domain_name = "research_web"

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        # TODO: retrieve via real web/paper-index search, not recalled
        # training knowledge. A claim this domain can't actually fetch and
        # check should resolve UNDETERMINED, not CONFIRMED-from-memory.
        return []

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if not evidence:
            return [
                "No fetched source found confirming or contradicting this claim. "
                "A plausible-sounding citation is not evidence until it's actually retrieved."
            ]
        return super().describe_gap(claim, evidence)
