"""
Local HTTP server for searchlight evals and the demo.

searchlight fetches a URL for real (httpx, real sockets); pointing it at a
page we control means the verdict tests the adapter, not whatever a
third-party site happens to say this month. Pages live in evals/fixtures/web/.

STATUS: real, offline, tested (exercised by evals/run_evals.py and
scripts/demo.py). The one live-internet searchlight case is kept separate
(evals/cases/searchlight/live_example_com_drift.json) and says so.

Case JSON and demo claims write URLs as "{FIXTURE_BASE_URL}/<page>"; use
`resolve()` to substitute the real base URL (the port is OS-assigned).
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import os
import threading
from pathlib import Path
from typing import Any, Iterator

WEB_DIR = Path(__file__).parent / "fixtures" / "web"
PLACEHOLDER = "{FIXTURE_BASE_URL}"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # keep eval/demo output clean
        pass


@contextlib.contextmanager
def serve_fixtures() -> Iterator[str]:
    """Serve evals/fixtures/web/ on 127.0.0.1:<free port>; yield the base URL."""
    handler = functools.partial(_QuietHandler, directory=str(WEB_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # The sandbox/CI proxy env (HTTPS_PROXY etc.) must not capture loopback traffic.
    prior = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    for k in prior:
        os.environ[k] = ",".join(filter(None, [prior[k], "127.0.0.1"]))
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        for k, v in prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def resolve(value: Any, base_url: str) -> Any:
    """Recursively replace the {FIXTURE_BASE_URL} placeholder in str values."""
    if isinstance(value, str):
        return value.replace(PLACEHOLDER, base_url)
    if isinstance(value, dict):
        return {k: resolve(v, base_url) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, base_url) for v in value]
    return value
