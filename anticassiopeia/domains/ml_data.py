"""
TEMPORARY backward-compatibility shim, added by the domain rename
(ml_data -> quant). The real adapter now lives in
`anticassiopeia/domains/quant.py`; this module exists ONLY because
`stress_test/run_test1.py` (explicitly out of scope for this rename)
imports this old path directly. Delete this file once that script is
migrated.
"""

from anticassiopeia.domains.quant import *  # noqa: F401,F403
from anticassiopeia.domains.quant import QuantAdapter as MLDataAdapter  # noqa: F401
