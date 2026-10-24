from pathlib import Path

from anticassiopeia.domains.fpga_embedded import FPGAEmbeddedAdapter
from anticassiopeia.domains.ml_data import MLDataAdapter
from anticassiopeia.domains.research_web import ResearchWebAdapter
from anticassiopeia.domains.robotics import RoboticsAdapter


#: Convenience registry — pass to VerificationEngine(domains=default_domains())
#: once each adapter has a real gather_evidence() implementation.
#:
#: `extra_allowed_base_dirs` (v2 /verify/project build): appended to ONLY
#: MLDataAdapter's/FPGAEmbeddedAdapter's allowed_base_dirs (the two
#: path-based adapters -- robotics.py's BYOE path takes text directly, no
#: path involved at all). Omitted/None (the default) is byte-for-byte the
#: pre-v2 behavior, so every existing caller (tests, stress_test/ scripts,
#: default_domains() with no args) is unaffected. api/server.py is the one
#: caller that passes its own server-controlled project-upload scratch
#: directory here -- never a caller-supplied path, so widening the
#: allowlist by this one fixed, server-owned directory carries no new
#: arbitrary-file-read risk (see _path_safety.py's own docstring for what
#: that containment check defends against).
def default_domains(extra_allowed_base_dirs: list[Path] | None = None) -> dict:
    ml_data_dirs = None
    fpga_dirs = None
    if extra_allowed_base_dirs:
        from anticassiopeia.domains.fpga_embedded import _DEFAULT_ALLOWED_BASE_DIRS as _FPGA_DEFAULTS
        from anticassiopeia.domains.ml_data import _DEFAULT_ALLOWED_BASE_DIRS as _ML_DATA_DEFAULTS

        ml_data_dirs = [*_ML_DATA_DEFAULTS, *extra_allowed_base_dirs]
        fpga_dirs = [*_FPGA_DEFAULTS, *extra_allowed_base_dirs]

    return {
        a.domain_name: a
        for a in (
            RoboticsAdapter(),
            FPGAEmbeddedAdapter(allowed_base_dirs=fpga_dirs),
            ResearchWebAdapter(),
            MLDataAdapter(allowed_base_dirs=ml_data_dirs),
        )
    }


__all__ = [
    "RoboticsAdapter",
    "FPGAEmbeddedAdapter",
    "ResearchWebAdapter",
    "MLDataAdapter",
    "default_domains",
]
