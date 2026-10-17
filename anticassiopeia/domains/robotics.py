"""
Robotics domain adapter — physical/datasheet POV.

Verifies claims about real hardware against real, cited sources: datasheets,
manufacturer spec sheets, and per-part/whole-assembly survivability
conditions.

STATUS: seeded, not live. `gather_evidence()` below is a small, hand-built
lookup over facts extracted and sourced from Eclipse: Constellation's own
datasheet research (see
docs/extracted/constellation-robotics-seed.md for full provenance and the
retrieval-pattern this is modeled on). It is real, locator-backed evidence
for exactly the parts Constellation had already sourced — not a live
datasheet-retrieval pipeline. A claim about any part whose keyword
`gather_evidence()` doesn't recognize returns no evidence and an honest
gap, the same as before. This is step one of the pattern described in the seed doc
(ingest → hybrid retrieve → propose → independently verify → contested-or-
missing as explicit outcomes), not the finished version of it.

KNOWN LIMITATION, stated plainly rather than discovered later: `stance` on
every piece of evidence below is hand-assigned at authoring time against
one fixed claim framing ("<part> survives 500 m depth"). Evidence
retrieval here matches by part keyword only, not by claim polarity — a
claim phrased the other way ("<part> fails at 500 m") would retrieve the
*same* evidence objects with the *same* hardcoded stance, producing a
backwards verdict. This is exactly the kind of flaw this project exists
to catch, so it's being named here instead of papered over: do not trust
this adapter against a claim phrased as a negation until this is fixed
(real fix: derive stance from a comparison between the retrieved spec
value and the claim's stated condition, not from authoring-time intent).
"""

from __future__ import annotations

from anticassiopeia.core.domain import DomainAdapter
from anticassiopeia.core.verdict import Claim, Evidence

_SEED_DOC = "docs/extracted/constellation-robotics-seed.md"


class RoboticsAdapter(DomainAdapter):
    domain_name = "robotics"
    implemented = True  # seeded with real sourced facts for 2 of 4 researched parts — see module docstring

    async def gather_evidence(self, claim: Claim) -> list[Evidence]:
        text = claim.text.lower()

        evidence: list[Evidence] = []
        if "bluerov2" in text or "blue rov" in text or "blue rov2" in text:
            evidence += self._bluerov2_housing_evidence()
        if "bar30" in text or "bar 30" in text:
            evidence += self._bar30_evidence()
        # Bar100XT and QuSpin QZFM Gen-3 are known to this adapter but intentionally
        # produce no evidence — Constellation never sourced them (narrative-only,
        # see seed doc §3-4). describe_gap() below says so explicitly rather than
        # falling through to the generic "no datasheet found" message.

        return evidence

    def describe_gap(self, claim: Claim, evidence: list[Evidence]) -> list[str]:
        if evidence:
            return super().describe_gap(claim, evidence)

        text = claim.text.lower()
        if "bar100" in text or "bar 100" in text:
            return [
                "Bar100XT is a known revision-target part with NO sourced datasheet evidence "
                f"anywhere in Constellation — only a planning narrative ({_SEED_DOC} §3). "
                "A real Blue Robotics datasheet needs to be pulled before this can resolve "
                "past UNDETERMINED."
            ]
        if "quspin" in text or "qzfm" in text:
            return [
                "QuSpin QZFM Gen-3 is a known candidate sensor with NO sourced datasheet evidence "
                f"anywhere in Constellation — only a planning narrative ({_SEED_DOC} §4). "
                "A real QuSpin datasheet needs to be pulled before this can resolve past "
                "UNDETERMINED."
            ]
        return [
            f"No datasheet or spec-sheet evidence found for this part/assembly claim in "
            f"this adapter's seeded facts ({_SEED_DOC}). Robotics verdicts require a "
            "traceable datasheet locator, not a generated spec."
        ]

    # -- seeded facts, each carrying a real locator back to its source --------------

    @staticmethod
    def _bluerov2_housing_evidence() -> list[Evidence]:
        # Two manufacturer-revision datasheets disagree on the exact rating (300m vs
        # 100m aluminum/acrylic) but AGREE on stance — both fail a 500m condition — so
        # per core/verdict.py these are NOT "contested"; the disagreement in magnitude
        # is carried in each entry's own snippet instead of hidden.
        return [
            Evidence(
                source="Blue Robotics BlueROV2 datasheet, 2025 revision (DOC1)",
                snippet=(
                    "Maximum Rated Depth (Acrylic): 100 m; Maximum Rated Depth (Aluminum): 300 m "
                    "— best case 300 m, 40% short of a 500 m condition."
                ),
                stance="contradicts",
                trust=0.8,
                locator=f"{_SEED_DOC} §1.1, citing evals/model-comparison/corpus/DOC1_BlueROV2_datasheet_2025.txt:18-19",
            ),
            Evidence(
                source="Blue Robotics BlueROV2 datasheet, Rev 10/16 (DOC2)",
                snippet=(
                    "Maximum Rated Depth: 100 m (no aluminum variant listed); "
                    "Maximum Tested Depth: 130 m — fails a 500 m condition outright."
                ),
                stance="contradicts",
                trust=0.7,
                locator=f"{_SEED_DOC} §1.1, citing evals/model-comparison/corpus/DOC2_BlueROV2_datasheet_rev1016.txt:17,22-23",
            ),
        ]

    @staticmethod
    def _bar30_evidence() -> list[Evidence]:
        return [
            Evidence(
                source="Blue Robotics Bar30 / TE Connectivity MS5837-30BA chip datasheet (DOC3, unaltered line)",
                snippet=(
                    "Operating pressure range: 0 to 30 bar, -20 to +85 C "
                    "(≈296 m depth-equivalent) — fails a 500 m condition by ~40%."
                ),
                stance="contradicts",
                trust=0.85,
                locator=f"{_SEED_DOC} §2, citing evals/model-comparison/corpus/DOC3_Bar30_MS5837-30BA_chip_datasheet.txt:11,33",
            ),
            Evidence(
                source="Constellation's own canary documentation (METHOD.md) — NOT the chip datasheet directly",
                snippet=(
                    "Real overpressure Pmax ≈50 bar (≈500 m-equivalent) per Constellation's stated "
                    "ground truth for its own canary test; the in-corpus value (45 bar) is a "
                    "documented fake and is excluded here. 50 bar has not been independently "
                    "re-verified against the live vendor PDF by this adapter."
                ),
                stance="neutral",  # ~500m sits at the destructive limit either way — too close to call a stance
                trust=0.3,  # low trust: secondhand (Constellation's doc about its own test), not independently re-verified
                locator=f"{_SEED_DOC} §2, citing evals/model-comparison/METHOD.md:59-73",
            ),
        ]
