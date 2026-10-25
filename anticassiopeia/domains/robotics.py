"""
TEMPORARY backward-compatibility shim, added by the domain rename
(robotics -> substrate). The real adapter now lives in
`anticassiopeia/domains/substrate.py`; this module exists ONLY because
`stress_test/`'s own scripts (explicitly out of scope for this rename --
see the rename's own commit messages) import this old path directly, and
some of them (`run_test3_nebius_agent.py`) monkeypatch
`anticassiopeia.domains.robotics.verify_proposal` at the MODULE level to
disable independent verification for a baseline comparison.

HONEST LIMITATION: that monkeypatch trick targets THIS shim module's own
`verify_proposal` name, not `substrate.py`'s -- `SubstrateAdapter`'s real
methods resolve `verify_proposal` from `substrate.py`'s own module
namespace, which this shim does not and cannot intercept. So
`run_test3_nebius_agent.py` will still IMPORT successfully through this
shim, but its monkeypatch will silently no-op: it will measure the SAME
pipeline as the real, fully-verified one, not the "no independent
verify" baseline it's named for and reports on. This is real, accepted
collateral of the rename (stress_test/ was explicitly left untouched) --
not patched here, since fixing it means editing `stress_test/` itself,
which is out of scope. Remove this shim and update
`stress_test/run_test1.py`/`run_test3_nebius_agent.py`/`inspect_mistake.py`/
`run_benchmark_round1.py` in a future, separate pass.

Delete this file once every remaining `stress_test/` consumer of the old
path is migrated.
"""

from anticassiopeia.domains.substrate import *  # noqa: F401,F403
from anticassiopeia.domains.substrate import SubstrateAdapter as RoboticsAdapter  # noqa: F401
