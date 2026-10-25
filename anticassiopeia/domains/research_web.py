"""
TEMPORARY backward-compatibility shim, added by the domain rename
(research_web -> searchlight). The real adapter now lives in
`anticassiopeia/domains/searchlight.py`; this module exists ONLY because
`stress_test/`'s own scripts (explicitly out of scope for this rename)
import this old path directly, and `run_test3_nebius_agent.py`
monkeypatches `anticassiopeia.domains.research_web.verify_proposal` at
the module level -- same honest limitation as `domains/robotics.py`'s
own shim docstring describes: that monkeypatch targets THIS shim's
namespace, not `searchlight.py`'s real one, so it will silently no-op
rather than actually disabling verification. Not fixed here (fixing it
means editing `stress_test/`, out of scope for this rename).

Delete this file once every remaining `stress_test/`/`evals/`/`scripts/`
consumer of the old path is migrated (evals/run_evals.py and
scripts/demo.py were already migrated directly to the new path as part
of this same rename, since both are in-scope; only the stress_test/
scripts still need this shim).
"""

from anticassiopeia.domains.searchlight import *  # noqa: F401,F403
from anticassiopeia.domains.searchlight import (  # noqa: F401
    SearchlightAdapter as ResearchWebAdapter,
    _looks_like_block_page,
    _search_candidate_urls,
    _strip_html,
)
