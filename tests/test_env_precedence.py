"""
Regression test for a real import-order bug (external review, verified
directly against the code before being reported): nebius_client.py used to
call `load_dotenv(override=True)` at import time, mutating the GLOBAL
process environment for every name `.env` defines -- not just its own three
variables. `anticassiopeia/api/server.py` imports `anticassiopeia.domains`
(which transitively imports nebius_client.py) BEFORE running its own
`load_dotenv(override=False)` for `ANTICASSIOPEIA_API_KEY` -- so the global
override had already run by the time server.py's "safe" call executed,
silently letting a stray `.env` file beat a real, platform-injected
`ANTICASSIOPEIA_API_KEY` in production.

This can only be faithfully tested with a FRESH process -- the bug is
specifically about what happens the first time these modules are ever
imported, in this exact order, which already happened once (and can't be
undone) in this test session's own process. A subprocess, with a crafted
`.env` in its cwd and a conflicting process env var, reproduces the real
scenario end to end.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _run_fresh_import_and_read_env(tmp_path: Path, var: str, process_value: str, dotenv_value: str) -> str:
    (tmp_path / ".env").write_text(f"{var}={dotenv_value}\nNEBIUS_API_KEY=unused-dummy-key\n")
    script = textwrap.dedent(f"""
        import os
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})
        import anticassiopeia.api.server  # noqa: F401 -- the exact real import order
        print(os.environ.get({var!r}, ""))
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", var: process_value},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    return result.stdout.strip()


def test_a_real_process_set_anticassiopeia_api_key_beats_a_conflicting_dotenv_value(tmp_path):
    """The exact scenario the bug allowed: a platform-injected secret
    (process env) must win over whatever a stray .env file says, even
    though importing the server pulls in nebius_client.py first."""
    printed = _run_fresh_import_and_read_env(
        tmp_path, "ANTICASSIOPEIA_API_KEY", process_value="from-process", dotenv_value="from-dotenv-should-lose"
    )
    assert printed == "from-process"


def test_nebius_api_key_dotenv_still_wins_for_its_own_rotation_convenience(tmp_path):
    """NOT a regression of the behavior FIXED BUG #2 wanted: NEBIUS_API_KEY
    itself still lets an edited .env win over an already-exported stale
    shell value -- just scoped to this one variable via _env_or_dotenv(),
    never leaking into any other process env var the way the old
    load_dotenv(override=True) did."""
    (tmp_path / ".env").write_text("NEBIUS_API_KEY=from-dotenv-fresh-rotation\n")
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})
        from anticassiopeia.llm.nebius_client import NebiusTokenFactoryClient
        client = NebiusTokenFactoryClient()
        print(client.api_key)
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "NEBIUS_API_KEY": "stale-shell-value"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "from-dotenv-fresh-rotation"


def test_importing_nebius_client_does_not_mutate_unrelated_process_env_vars(tmp_path):
    """The actual mechanism fix: importing nebius_client.py (even with a
    .env present that defines OTHER variables) must not touch any env var
    this module doesn't own -- unlike the old load_dotenv(override=True),
    which mutated the whole process environment for every name in .env."""
    (tmp_path / ".env").write_text(
        "NEBIUS_API_KEY=whatever\nSOME_UNRELATED_VAR=from-dotenv-should-not-win\n"
    )
    script = textwrap.dedent(f"""
        import os
        import sys
        sys.path.insert(0, {str(REPO_ROOT)!r})
        import anticassiopeia.llm.nebius_client  # noqa: F401
        print(os.environ.get("SOME_UNRELATED_VAR", ""))
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "SOME_UNRELATED_VAR": "from-process-should-win"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    assert result.stdout.strip() == "from-process-should-win"
