from pathlib import Path

from anticassiopeia.domains.quant import QuantAdapter
from anticassiopeia.domains.searchlight import SearchlightAdapter
from anticassiopeia.domains.silicon import SiliconAdapter
from anticassiopeia.domains.substrate import SubstrateAdapter


#: Convenience registry — pass to VerificationEngine(domains=default_domains())
#: once each adapter has a real gather_evidence() implementation.
#:
#: `extra_allowed_base_dirs` (v2 /verify/project build): appended to ONLY
#: QuantAdapter's/SiliconAdapter's allowed_base_dirs (the two
#: path-based adapters -- substrate.py's BYOE path takes text directly, no
#: path involved at all). Omitted/None (the default) is byte-for-byte the
#: pre-v2 behavior, so every existing caller (tests, stress_test/ scripts,
#: default_domains() with no args) is unaffected. api/server.py is the one
#: caller that passes its own server-controlled project-upload scratch
#: directory here -- never a caller-supplied path, so widening the
#: allowlist by this one fixed, server-owned directory carries no new
#: arbitrary-file-read risk (see _path_safety.py's own docstring for what
#: that containment check defends against).
def default_domains(extra_allowed_base_dirs: list[Path] | None = None) -> dict:
    quant_dirs = None
    silicon_dirs = None
    if extra_allowed_base_dirs:
        from anticassiopeia.domains.quant import _DEFAULT_ALLOWED_BASE_DIRS as _QUANT_DEFAULTS
        from anticassiopeia.domains.silicon import _DEFAULT_ALLOWED_BASE_DIRS as _SILICON_DEFAULTS

        quant_dirs = [*_QUANT_DEFAULTS, *extra_allowed_base_dirs]
        silicon_dirs = [*_SILICON_DEFAULTS, *extra_allowed_base_dirs]

    return {
        a.domain_name: a
        for a in (
            SubstrateAdapter(),
            SiliconAdapter(allowed_base_dirs=silicon_dirs),
            SearchlightAdapter(),
            QuantAdapter(allowed_base_dirs=quant_dirs),
        )
    }


__all__ = [
    "SubstrateAdapter",
    "SiliconAdapter",
    "SearchlightAdapter",
    "QuantAdapter",
    "default_domains",
]
