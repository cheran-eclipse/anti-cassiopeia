"""
TEMPORARY backward-compatibility shim, added by the domain rename
(fpga_embedded -> silicon). The real adapter now lives in
`anticassiopeia/domains/silicon.py`; this module exists ONLY because
`stress_test/run_test1.py` (explicitly out of scope for this rename)
imports this old path directly. Delete this file once that script is
migrated.
"""

from anticassiopeia.domains.silicon import *  # noqa: F401,F403
from anticassiopeia.domains.silicon import SiliconAdapter as FPGAEmbeddedAdapter  # noqa: F401
