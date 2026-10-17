from anticassiopeia.domains.fpga_embedded import FPGAEmbeddedAdapter
from anticassiopeia.domains.ml_data import MLDataAdapter
from anticassiopeia.domains.research_web import ResearchWebAdapter
from anticassiopeia.domains.robotics import RoboticsAdapter

#: Convenience registry — pass to VerificationEngine(domains=default_domains())
#: once each adapter has a real gather_evidence() implementation.
def default_domains() -> dict:
    return {
        a.domain_name: a
        for a in (
            RoboticsAdapter(),
            FPGAEmbeddedAdapter(),
            ResearchWebAdapter(),
            MLDataAdapter(),
        )
    }


__all__ = [
    "RoboticsAdapter",
    "FPGAEmbeddedAdapter",
    "ResearchWebAdapter",
    "MLDataAdapter",
    "default_domains",
]
